"""The foundation-model interface, and the record of every call to it.

The abstraction
---------------
:class:`FoundationModel` is the only way anything in the system reaches a model.
It is intentionally small: load, generate, unload. The point is not to wrap a
particular runtime but to make the runtime replaceable without the research
record lying about which runtime was used.

What an invocation record is for
--------------------------------
This project will be studied long after the code that made the calls is gone.
An invocation record answers, for one call:

* what went in, and what came out;
* which model produced it, by digest;
* how long it took, on what backend;
* whether the output could be parsed at all, and if not, why that was recorded
  rather than retried into a nicer-looking answer.

The honesty rules in that record are the interesting part:

* :attr:`OutputKind` distinguishes *raw* text from *interpretation*. An
  interpretation is this laboratory's reading of a model output, and it is
  labelled as such. Collapsing the two would make a model appear to understand
  something it merely emitted.
* :attr:`ObservationStatus` is a fact about parsing, not about quality. A
  perfectly formed string that means nothing is ``PARSED``; a string that
  isn't JSON is ``UNPARSED``. Neither implies understanding.
* There is no retry loop. A model that fails to produce a usable answer produces
  a record of having failed.

What is deliberately absent
---------------------------
No reasoning trace, no "thinking" field, no token-by-token log of internal
state. A runtime that exposes chain-of-thought is not asked for it, and if one
arrives in a response it is dropped before the record is built. Hidden
chain-of-thought is not stored in this laboratory.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from babylab.clock import Clock, format_timestamp
from babylab.errors import ValidationError
from babylab.hashing import canonical_bytes, sha256_hex
from birth.identity import ModelIdentity

INVOCATION_RECORD_SCHEMA = "babylab/invocation-record/v1"

#: Response fields that carry model-internal reasoning. Stripped unconditionally.
#: Present so that a runtime offering them has somewhere honest to put the fact
#: that they are ignored.
REASONING_FIELD_NAMES = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "thinking",
        "thought",
        "thoughts",
        "chain_of_thought",
        "cot",
        "inner_monologue",
        "scratchpad",
        "plan_internal",
    }
)


class ObservationStatus(str, enum.Enum):
    """What happened when the laboratory looked at the output."""

    #: Output was produced and parsed into a structured form.
    PARSED = "PARSED"
    #: Output was produced but could not be parsed. Recorded, not retried.
    UNPARSED = "UNPARSED"
    #: No output at all; the runtime failed.
    ERROR = "ERROR"
    #: The call was refused before reaching the model. See the refusal reason.
    REFUSED = "REFUSED"
    #: The model is not installed, so there was nothing to call.
    MODEL_NOT_INSTALLED = "MODEL_NOT_INSTALLED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @property
    def produced_output(self) -> bool:
        return self in (ObservationStatus.PARSED, ObservationStatus.UNPARSED)


class OutputKind(str, enum.Enum):
    """What sort of thing the recorded output is.

    ``INTERPRETATION`` is the important one: it is this laboratory's reading of a
    model output, kept separate from what the model actually emitted so that the
    two are never confused later.
    """

    #: Text exactly as the runtime returned it.
    RAW = "RAW"
    #: This laboratory's structured reading of that text.
    INTERPRETATION = "INTERPRETATION"
    #: The output failed validation and is recorded as-is for inspection.
    VALIDATION_ERROR = "VALIDATION_ERROR"
    #: An internal status string from the runtime, not model content.
    SYSTEM = "SYSTEM"
    #: The model was not called.
    NONE = "NONE"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class PromptRequest:
    """One request to the model."""

    prompt: str
    max_tokens: int = 512
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    stop: tuple[str, ...] = ()
    seed: int = 0
    #: What the caller wants back. Recorded so a later reader can tell an
    #: intended free-form generation from a request for structured output.
    intent: str = "unspecified"
    #: Names of capabilities the caller believes it has. Not authorisation; see
    #: :mod:`birth.boundary`.
    requested_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stop", tuple(self.stop))
        object.__setattr__(
            self, "requested_capabilities", tuple(self.requested_capabilities)
        )
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValidationError("prompt must be a non-empty string")
        if self.max_tokens < 1:
            raise ValidationError(f"max_tokens must be >= 1, got {self.max_tokens}")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValidationError(
                f"temperature must be within [0, 2], got {self.temperature}"
            )
        if self.seed < 0:
            raise ValidationError(f"seed must be >= 0, got {self.seed}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "stop": list(self.stop),
            "seed": self.seed,
            "intent": self.intent,
            "requested_capabilities": list(self.requested_capabilities),
        }

    def prompt_hash(self) -> str:
        return sha256_hex(self.prompt.encode("utf-8"))


@dataclass(frozen=True)
class ModelResponse:
    """Raw output plus whatever the runtime honestly reported about it."""

    text: str
    finish_reason: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    duration_ms: float | None = None
    backend: str = "unknown"
    #: Free-form diagnostics. Used for failure detail, not for narrative.
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValidationError(f"response text must be a string, got {self.text!r}")
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValidationError(f"{name} must be an integer or None, got {value!r}")
            if isinstance(value, int) and value < 0:
                raise ValidationError(f"{name} must be >= 0, got {value}")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValidationError(
                f"duration_ms must be >= 0, got {self.duration_ms}"
            )
        object.__setattr__(self, "_sanitized", strip_reasoning_fields(self.diagnostics))

    def sanitized_diagnostics(self) -> dict[str, Any]:
        """Diagnostics with any reasoning-shaped field removed."""
        return dict(getattr(self, "_sanitized", strip_reasoning_fields(self.diagnostics)))

    def token_count_is_reported(self) -> bool:
        return self.total_tokens is not None

    @property
    def is_error(self) -> bool:
        return bool(self.error) or not self.text


@dataclass(frozen=True)
class InvocationRecord:
    """A durable record of exactly one call to the foundation model."""

    invocation_id: str
    model_sha256: str
    model_name: str
    runtime: str
    runtime_version: str
    backend: str
    observation: ObservationStatus
    output_kind: OutputKind
    input_text: str
    output_text: str
    prompt_hash: str
    token_count: int | None
    token_count_reported: bool
    duration_ms: float | None
    finish_reason: str
    intent: str
    requested_capabilities: tuple[str, ...]
    interpretation: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    schema: str = INVOCATION_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_capabilities", tuple(self.requested_capabilities))
        if self.observation is ObservationStatus.MODEL_NOT_INSTALLED and self.output_text:
            raise ValidationError(
                "a record that reports MODEL_NOT_INSTALLED cannot also contain "
                "output text; that would be an invented observation"
            )
        if self.token_count is not None and not self.token_count_reported:
            raise ValidationError(
                "token_count_reported=False with a token_count present would "
                "claim a measurement the runtime did not report"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "invocation_id": self.invocation_id,
            "timestamp": self.timestamp,
            "model_name": self.model_name,
            "model_sha256": self.model_sha256,
            "runtime": self.runtime,
            "runtime_version": self.runtime_version,
            "backend": self.backend,
            "observation": self.observation.value,
            "output_kind": self.output_kind.value,
            "intent": self.intent,
            "requested_capabilities": list(self.requested_capabilities),
            "input_text": self.input_text,
            "input_hash": self.prompt_hash,
            "output_text": self.output_text,
            "interpretation": dict(self.interpretation),
            "token_count": self.token_count,
            "token_count_reported": self.token_count_reported,
            "duration_ms": self.duration_ms,
            "finish_reason": self.finish_reason,
            "error": self.error,
            "diagnostics": dict(self.diagnostics),
        }

    def content_hash(self) -> str:
        """Digest over the record, for integrity checking after the fact."""
        body = self.to_dict()
        body.pop("invocation_id", None)
        body.pop("timestamp", None)
        return sha256_hex(canonical_bytes(body))

    def describe(self) -> str:
        return (
            f"{self.invocation_id} {self.observation.value}/{self.output_kind.value} "
            f"model={self.model_name} backend={self.backend} "
            f"tokens={self.token_count if self.token_count_reported else 'UNAVAILABLE'}"
        )


def strip_reasoning_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove reasoning-shaped keys, at any depth.

    Chain-of-thought is never stored. A runtime that offers it is not asked, and
    if it arrives anyway it is dropped here rather than filtered by convention.
    """
    if not isinstance(payload, dict):
        return {}

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: clean(item)
                for key, item in value.items()
                if str(key).lower() not in REASONING_FIELD_NAMES
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(payload)


@runtime_checkable
class FoundationModel(Protocol):
    """The only sanctioned path to model output.

    A note on :meth:`unload`: it is part of the interface, not an optimisation
    hook. A model left resident holds VRAM that the measurement of the next run
    would have to account for, and on a shared laptop GPU that quietly changes
    results.
    """

    def load(self) -> None:
        """Bring the model into memory, or raise if that is not possible."""

    def generate(self, request: PromptRequest) -> ModelResponse:
        """Produce one response."""

    def unload(self) -> None:
        """Release the model. Must be safe to call when nothing is loaded."""

    @property
    def is_loaded(self) -> bool:
        """Whether the model currently occupies resources."""

    def identity(self) -> ModelIdentity:
        """Which model this is, by digest."""


def build_invocation_record(
    invocation_id: str,
    identity: ModelIdentity,
    request: PromptRequest,
    response: ModelResponse | None,
    observation: ObservationStatus,
    output_kind: OutputKind,
    interpretation: dict[str, Any] | None = None,
    error: str = "",
    now: Any = None,
) -> InvocationRecord:
    """Assemble a record, keeping ``RAW`` and ``INTERPRETATION`` separate.

    When ``output_kind`` is :attr:`OutputKind.INTERPRETATION` the output text is
    the *model's* text and the interpretation is this laboratory's reading of it.
    They are stored in different fields precisely so that a future reader cannot
    mistake one for the other.
    """
    if not invocation_id:
        raise ValidationError("invocation_id must be a non-empty string")
    if response is None and observation is not ObservationStatus.MODEL_NOT_INSTALLED:
        raise ValidationError(
            "a record with no response must be MODEL_NOT_INSTALLED or carry an "
            "error; a missing response is not an observation"
        )
    if output_kind is OutputKind.NONE and observation.produced_output:
        raise ValidationError(
            "a record reporting output cannot claim output_kind NONE"
        )
    if interpretation and output_kind is not OutputKind.INTERPRETATION:
        raise ValidationError(
            "an interpretation can only be attached to an INTERPRETATION "
            "record; labelling it as RAW would misrepresent it"
        )

    reported = response is not None and response.total_tokens is not None
    return InvocationRecord(
        invocation_id=invocation_id,
        model_sha256=identity.model_sha256,
        model_name=identity.model_name,
        runtime=identity.runtime,
        runtime_version=identity.runtime_version,
        backend=(response.backend if response else "none"),
        observation=observation,
        output_kind=output_kind,
        input_text=request.prompt,
        output_text=(response.text if response else ""),
        prompt_hash=request.prompt_hash(),
        token_count=(response.total_tokens if response else None),
        token_count_reported=reported,
        duration_ms=(response.duration_ms if response else None),
        finish_reason=(response.finish_reason if response else ""),
        intent=request.intent,
        requested_capabilities=request.requested_capabilities,
        interpretation=dict(interpretation or {}),
        error=error or (response.error if response else ""),
        diagnostics=(response.sanitized_diagnostics() if response else {}),
        timestamp=format_timestamp(now) if now is not None else format_timestamp(Clock().now()),
    )


__all__ = [
    "INVOCATION_RECORD_SCHEMA",
    "FoundationModel",
    "InvocationRecord",
    "ModelResponse",
    "ObservationStatus",
    "OutputKind",
    "PromptRequest",
    "REASONING_FIELD_NAMES",
    "build_invocation_record",
    "strip_reasoning_fields",
]
