"""The versioned model-adapter contract for Milestone 006.

What this is
------------
A stable, vendor-neutral boundary between *the laboratory* and *some particular
inference implementation*. Everything above this line (subject-facing interface,
Observatory, provenance) is written against these types and never against
llama.cpp, a vendor name, or a file extension.

Why it is a contract and not a base class
-----------------------------------------
:class:`ModelAdapter` is a :class:`typing.Protocol`. A new runtime is adopted by
writing a class that satisfies it and registering it -- not by editing the
laboratory, and not by subclassing something that carries llama.cpp's defaults
into the process. That is what makes "replace the model without rewriting the
subject architecture" a structural property rather than an intention.

The three-layer shape
---------------------
::

    model artifact          the weights on disk, identified by digest
        |
        v
    model adapter           this contract; owns the runtime binding
        |
        v
    inference runtime       :mod:`babylab.runtime.runtime`; policy, limits, events
        |
        v
    constrained interface   :mod:`babylab.runtime.interface`; what a subject may call

Epistemic discipline
--------------------
Every measurement carries an :class:`Measurement` with an explicit
:class:`EpistemicStatus`. ``DERIVED`` never masquerades as ``OBSERVED`` and
``UNAVAILABLE`` is a real answer, not a failure to be papered over. This is the
M002 discipline, carried forward.

What this module deliberately does not have
-------------------------------------------
No curriculum, no developmental stage, no learning, no memory, no goal, no
autonomy, no tool discovery. A :class:`PromptRequest` is one generation. Nothing
here keeps a conversation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

#: Bumped only for a breaking change to this contract. Adapters declare the
#: version they were written against, and the registry refuses a mismatch rather
#: than binding something subtly incompatible.
ADAPTER_CONTRACT_VERSION = "1.0.0"


class EpistemicStatus(str, enum.Enum):
    """How a value came to be known. Never omitted."""

    #: Read directly from the host or the runtime.
    OBSERVED = "OBSERVED"
    #: Computed from observed values by a stated rule.
    DERIVED = "DERIVED"
    #: Could not be measured. A real answer, not a zero.
    UNAVAILABLE = "UNAVAILABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Measurement:
    """A value plus how we came to know it."""

    value: Any
    status: EpistemicStatus
    unit: str = ""
    source: str = ""

    @classmethod
    def observed(cls, value: Any, unit: str = "", source: str = "") -> "Measurement":
        return cls(value, EpistemicStatus.OBSERVED, unit, source)

    @classmethod
    def derived(cls, value: Any, unit: str = "", source: str = "") -> "Measurement":
        return cls(value, EpistemicStatus.DERIVED, unit, source)

    @classmethod
    def unavailable(cls, reason: str = "not measurable here") -> "Measurement":
        return cls(None, EpistemicStatus.UNAVAILABLE, "", reason)

    @property
    def is_available(self) -> bool:
        return self.status is not EpistemicStatus.UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status.value,
            "unit": self.unit,
            "source": self.source,
        }


class RuntimeState(str, enum.Enum):
    """Lifecycle of one runtime instance."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    LOADING = "LOADING"
    READY = "READY"
    GENERATING = "GENERATING"
    FAILED = "FAILED"
    SHUTDOWN = "SHUTDOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class RuntimeErrorKind(str, enum.Enum):
    """Why a runtime operation failed. Explicit, never a bare exception string."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    RUNTIME_MISSING = "RUNTIME_MISSING"
    GPU_UNAVAILABLE = "GPU_UNAVAILABLE"
    INSUFFICIENT_VRAM = "INSUFFICIENT_VRAM"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    GENERATION_FAILED = "GENERATION_FAILED"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    BOUNDARY_VIOLATION = "BOUNDARY_VIOLATION"
    CAPABILITY_DENIED = "CAPABILITY_DENIED"


class RuntimeFailure(RuntimeError):
    """A runtime failure carrying its kind, so callers branch on structure.

    A bare string error is not enough: the Observatory has to render *why* the
    laboratory cannot run, and a test has to assert on a category rather than on
    prose that a refactor might reword.
    """

    def __init__(self, kind: RuntimeErrorKind, detail: str, **context: Any) -> None:
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "detail": self.detail, "context": self.context}


class FinishReason(str, enum.Enum):
    """Why generation stopped."""

    STOP_SEQUENCE = "stop_sequence"
    LENGTH = "length"
    EOS = "eos"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class InferenceRequest:
    """One generation request.

    Explicit and complete: there is no ambient conversation, no remembered
    history, and no hidden state carried between calls. ``request_id`` exists so
    an event, a provenance entry and a response can be joined after the fact.
    """

    request_id: str
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    stop: tuple[str, ...] = ()
    seed: int = 0
    timeout_seconds: float | None = None
    intent: str = "unspecified"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stop", tuple(self.stop))
        if not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if self.max_tokens < 1:
            raise ValueError(f"max_tokens must be >= 1, got {self.max_tokens}")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(f"temperature must be in [0, 2], got {self.temperature}")
        if self.seed < 0:
            raise ValueError(f"seed must be >= 0, got {self.seed}")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive when supplied")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "stop": list(self.stop),
            "seed": self.seed,
            "timeout_seconds": self.timeout_seconds,
            "intent": self.intent,
        }


@dataclass(frozen=True)
class InferenceResponse:
    """What the runtime returned, plus what it could actually measure."""

    request_id: str
    text: str = ""
    finish_reason: FinishReason = FinishReason.UNKNOWN
    model_identity: dict[str, Any] = field(default_factory=dict)
    runtime_identity: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("runtime reported none")
    )
    completion_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("runtime reported none")
    )
    load_duration_ms: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no load measured")
    )
    inference_duration_ms: Measurement = field(
        default_factory=lambda: Measurement.unavailable("not measured")
    )
    tokens_per_second: Measurement = field(
        default_factory=lambda: Measurement.unavailable("not computable")
    )
    resources: dict[str, Measurement] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.finish_reason not in {
            FinishReason.ERROR,
            FinishReason.CANCELLED,
            FinishReason.TIMEOUT,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "text": self.text,
            "finish_reason": self.finish_reason.value,
            "model_identity": self.model_identity,
            "runtime_identity": self.runtime_identity,
            "prompt_tokens": self.prompt_tokens.to_dict(),
            "completion_tokens": self.completion_tokens.to_dict(),
            "load_duration_ms": self.load_duration_ms.to_dict(),
            "inference_duration_ms": self.inference_duration_ms.to_dict(),
            "tokens_per_second": self.tokens_per_second.to_dict(),
            "resources": {k: v.to_dict() for k, v in self.resources.items()},
            "error": self.error,
        }


@dataclass(frozen=True)
class RuntimeIdentity:
    """Who executed this generation. Produced by the laboratory, never the model."""

    adapter: str
    adapter_version: str
    contract_version: str = ADAPTER_CONTRACT_VERSION
    runtime_implementation: str = ""
    runtime_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "contract_version": self.contract_version,
            "runtime_implementation": self.runtime_implementation,
            "runtime_version": self.runtime_version,
        }


@runtime_checkable
class ModelAdapter(Protocol):
    """A binding to one concrete inference implementation.

    An adapter owns the mechanics of loading weights and producing text. It owns
    no policy: admission, limits, events, provenance and the trust boundary all
    live above it, so swapping runtimes cannot quietly widen privilege.
    """

    #: Registry key, e.g. ``"llamacpp"``.
    adapter_id: str
    #: Version of this adapter implementation.
    adapter_version: str
    #: The :data:`ADAPTER_CONTRACT_VERSION` this adapter was written against.
    contract_version: str

    def describe(self) -> dict[str, Any]:
        """Static, externally-derived facts about the backing runtime."""
        ...

    def probe(self) -> tuple[bool, str]:
        """Can this runtime be executed at all? ``(available, detail)``."""
        ...

    def load(self, model_path: str, expected_sha256: str) -> dict[str, Any]:
        """Verify the artifact and make it usable. Returns observed identity.

        Must raise :class:`RuntimeFailure` on a missing artifact, a digest
        mismatch or an unsupported format. It must not download, search, or
        substitute a different artifact.
        """
        ...

    def unload(self) -> None:
        """Release anything resident. After this, VRAM is genuinely free."""
        ...

    def generate(self, request: InferenceRequest) -> InferenceResponse:
        """One generation. No conversation state may be retained across calls."""
        ...

    def supports_streaming(self) -> bool:
        """Whether :meth:`stream` yields chunks."""
        ...

    def stream(self, request: InferenceRequest) -> Iterator[str]:
        """Yield text chunks. Default raises rather than silently buffering."""
        ...

    def cancel(self) -> None:
        """Ask an in-flight generation to stop."""
        ...


__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "EpistemicStatus",
    "FinishReason",
    "InferenceRequest",
    "InferenceResponse",
    "Measurement",
    "ModelAdapter",
    "RuntimeErrorKind",
    "RuntimeFailure",
    "RuntimeIdentity",
    "RuntimeState",
]
