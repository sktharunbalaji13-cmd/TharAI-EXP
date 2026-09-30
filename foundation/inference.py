"""M010 inference: one real generation, characterised honestly.

The three things this module refuses to do
------------------------------------------
1. **Call a stub a real inference.** Every result carries
   :class:`InferenceKind`. ``REAL_RUNTIME`` requires an actual binary invocation
   that produced actual output; a stubbed runner is ``STUB_RUNTIME`` and says so
   in the same field a real result would use.
2. **Invent token counts.** If the runtime does not print them, the value is
   ``UNAVAILABLE`` with a reason. An estimate presented as an observation is
   worse than a gap, because a gap can be noticed.
3. **Prompt the model as a Baby AI.** The validation prompt is neutral. M010 is
   testing a runtime artifact, not a developmental subject, and a prompt that
   says "you are learning" would contaminate the measurement with a claim the
   laboratory has not earned.

What a successful run does and does not establish
-------------------------------------------------
A passing inference establishes: the artifact loads, the runtime executes, the
bytes were unchanged, and some text came out. It establishes **nothing** about
memory, learning, experience, or a subject. :attr:`InferenceRecord.output_class`
is ``FOUNDATION_MODEL_OUTPUT`` and the string constants in this module exist so
that distinction is quotable in code rather than only in prose.
"""

from __future__ import annotations

import enum
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from babylab.runtime.contract import (
    EpistemicStatus,
    FinishReason,
    Measurement,
    RuntimeErrorKind,
    RuntimeFailure,
)

#: The prompt used for runtime validation. Deliberately boring.
#:
#: It asks the model to repeat a token, which is checkable, and it contains no
#: identity, no developmental framing, and no instruction that could be read as
#: a claim about a subject. A test prompt that says "you are a newborn AI" would
#: make the output unfalsifiable, which is the opposite of validation.
VALIDATION_PROMPT = "Count from one to five, separated by spaces. Output only the numbers."

#: Classification of any text this milestone produces. Not a subject output.
OUTPUT_CLASS = "FOUNDATION_MODEL_OUTPUT"

#: The things it is not. Named so a report cannot accidentally imply otherwise.
OUTPUT_IS_NOT = (
    "SUBJECT_OUTPUT",
    "EXPERIENCE",
    "MEMORY",
    "LEARNING",
    "BABY_AI_OUTPUT",
)

#: Banned in any prompt or completion this milestone stores. Kept as data so a
#: test can assert the ban without parsing prose.
BANNED_PROMPT_SUBSTRINGS = (
    "you are baby ai",
    "you are babyai",
    "you are conscious",
    "you are sentient",
    "you are learning",
    "you are a baby",
    "you are developing",
    "you are a newborn",
    "your consciousness",
    "remember this",
)

#: Deterministic validation sampling. Explicit, not inherited from defaults.
BASELINE_SAMPLING: dict[str, Any] = {
    "temperature": 0.0,
    "top_p": 1.0,
    "top_k": 1,
    "seed": 0,
    "max_tokens": 32,
    "repeat_penalty": 1.0,
    "stop": [],
    "determinism_basis": (
        "greedy sampling (temperature 0, top_k 1) with a fixed seed. Selected so "
        "that a repeat run is expected to match, which makes a mismatch "
        "informative rather than routine."
    ),
}


class InferenceKind(str, enum.Enum):
    """What actually produced this text."""

    #: A real binary was invoked and returned output.
    REAL_RUNTIME = "REAL_RUNTIME"
    #: A caller-supplied runner stood in for the binary.
    STUB_RUNTIME = "STUB_RUNTIME"
    #: No run happened; prerequisites were absent or refused.
    NOT_TESTABLE = "NOT_TESTABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_real(self) -> bool:
        return self is InferenceKind.REAL_RUNTIME


class InferenceOutcome(str, enum.Enum):
    """Why the inference ended, in terms a failure audit can group on."""

    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    NOT_RUN = "NOT_RUN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class SamplingConfiguration:
    """Explicit sampling, written down rather than inherited."""

    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 1
    seed: int = 0
    max_tokens: int = 32
    repeat_penalty: float = 1.0
    stop: tuple[str, ...] = ()
    n_gpu_layers: int | None = None
    threads: int | None = None
    context_length: int = 2048

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
            "repeat_penalty": self.repeat_penalty,
            "stop": list(self.stop),
            "n_gpu_layers": self.n_gpu_layers,
            "threads": self.threads,
            "context_length": self.context_length,
        }

    def identical_to(self, other: "SamplingConfiguration") -> bool:
        return self.to_dict() == other.to_dict()


def baseline_sampling(**overrides: Any) -> SamplingConfiguration:
    """The declared baseline, with explicit overrides for a retry matrix."""
    values = dict(BASELINE_SAMPLING)
    values.update(overrides)
    return SamplingConfiguration(
        temperature=float(values["temperature"]),
        top_p=float(values["top_p"]),
        top_k=int(values["top_k"]),
        seed=int(values["seed"]),
        max_tokens=int(values["max_tokens"]),
        repeat_penalty=float(values["repeat_penalty"]),
        stop=tuple(values.get("stop") or ()),
        n_gpu_layers=values.get("n_gpu_layers"),
        threads=values.get("threads"),
        context_length=int(values.get("context_length", 2048)),
    )


def prompt_digest(prompt: str) -> str:
    """Digest of the prompt.

    The prompt is short, non-sensitive, and needed to reproduce the run, so it is
    recorded verbatim *and* hashed. The completion is hashed and not stored in
    full, because output text has no evidential value beyond its bytes and
    storing it invites a reader to treat it as meaningful.
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def output_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_neutral_prompt(prompt: str) -> None:
    """Refuse a prompt that frames the model as a subject.

    Raising rather than warning: a contaminated prompt makes the entire run
    uninterpretable, so it must not be recorded as a passing validation.
    """
    lowered = prompt.lower()
    for banned in BANNED_PROMPT_SUBSTRINGS:
        if banned in lowered:
            raise ValueError(
                f"validation prompt contains {banned!r}. M010 validates a runtime "
                "artifact and must not frame the model as a subject."
            )


@dataclass
class InferenceRecord:
    """One inference attempt, fully characterised."""

    kind: InferenceKind
    outcome: InferenceOutcome
    prompt_sha256: str = ""
    prompt_text: str = ""
    output_sha256: str = ""
    output_text: str = ""
    output_class: str = OUTPUT_CLASS
    output_is_not: tuple[str, ...] = OUTPUT_IS_NOT
    finish_reason: str = ""
    termination_reason: str = ""
    sampling: SamplingConfiguration = field(default_factory=SamplingConfiguration)
    model_identity: dict[str, Any] = field(default_factory=dict)
    runtime_identity: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    completion_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    total_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    load_duration_ms: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    inference_duration_ms: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    tokens_per_second: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    resources: dict[str, Measurement] = field(default_factory=dict)
    error: str = ""
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def token_accounting_complete(self) -> bool:
        """True only when the runtime itself reported all three counts.

        A total is *derived* from two reported values, so it carries DERIVED
        status rather than OBSERVED. This property checks the two observed ones.
        """
        return (
            self.prompt_tokens.is_available
            and self.completion_tokens.is_available
            and self.prompt_tokens.status is EpistemicStatus.OBSERVED
            and self.completion_tokens.status is EpistemicStatus.OBSERVED
        )

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "is_real_inference": self.kind.is_real,
            "outcome": self.outcome.value,
            "prompt_sha256": self.prompt_sha256,
            "output_sha256": self.output_sha256,
            "output_class": self.output_class,
            "output_is_not": list(self.output_is_not),
            "output_is_subject_output": False,
            "output_is_experience": False,
            "output_is_memory": False,
            "output_is_learning": False,
            "finish_reason": self.finish_reason,
            "termination_reason": self.termination_reason,
            "sampling": self.sampling.to_dict(),
            "model_identity": dict(self.model_identity),
            "runtime_identity": dict(self.runtime_identity),
            "token_accounting": {
                "prompt_tokens": self.prompt_tokens.to_dict(),
                "completion_tokens": self.completion_tokens.to_dict(),
                "total_tokens": self.total_tokens.to_dict(),
                "complete": self.token_accounting_complete,
                "policy": (
                    "counts are reported only when the runtime printed them. An "
                    "unreported count is UNAVAILABLE, never an estimate."
                ),
            },
            "timing": {
                "load_duration_ms": self.load_duration_ms.to_dict(),
                "inference_duration_ms": self.inference_duration_ms.to_dict(),
                "tokens_per_second": self.tokens_per_second.to_dict(),
            },
            "resources": {k: v.to_dict() for k, v in self.resources.items()},
            "error": self.error,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }
        if include_text:
            payload["prompt_text"] = self.prompt_text
            payload["output_text"] = self.output_text
        return payload


def _counts_from(response: Any) -> tuple[Measurement, Measurement, Measurement]:
    """Honest token accounting, copied from the runtime and never invented."""
    prompt = getattr(response, "prompt_tokens", None)
    completion = getattr(response, "completion_tokens", None)

    if isinstance(prompt, Measurement) and prompt.is_available:
        prompt_count: Measurement = prompt
    else:
        prompt_count = Measurement.unavailable(
            "the runtime printed no prompt token count; the laboratory does not "
            "estimate one"
        )
    if isinstance(completion, Measurement) and completion.is_available:
        completion_count: Measurement = completion
    else:
        completion_count = Measurement.unavailable(
            "the runtime printed no completion token count; the laboratory does "
            "not estimate one"
        )

    if prompt_count.is_available and completion_count.is_available:
        total = Measurement.derived(
            int(prompt_count.value) + int(completion_count.value),
            "count",
            "sum of the two runtime-reported counts",
        )
    else:
        total = Measurement.unavailable("one or both component counts are unavailable")
    return prompt_count, completion_count, total


def _finish_name(value: Any) -> str:
    return value.value if isinstance(value, FinishReason) else str(value or "")


def run_inference(
    runtime: Any,
    *,
    model_identity: dict[str, Any],
    sampling: SamplingConfiguration | None = None,
    prompt: str = VALIDATION_PROMPT,
    kind: InferenceKind = InferenceKind.REAL_RUNTIME,
    timeout_seconds: float = 300.0,
) -> InferenceRecord:
    """Run one inference and characterise it.

    ``runtime`` is an M006 adapter already holding a *verified* load. This
    function does not load, does not verify, and does not decide admission --
    those are separate decisions that must not be collapsed into "just run it".

    ``kind`` is a required argument rather than inferred, because inferring it
    would mean the code guessing whether its own runner was real. The caller
    knows, and honesty here is the caller's responsibility to get right; making
    it explicit is what keeps that responsibility visible.
    """
    sampling = sampling or baseline_sampling()
    assert_neutral_prompt(prompt)
    digest = prompt_digest(prompt)

    from babylab.runtime.contract import InferenceRequest

    request = InferenceRequest(
        request_id=f"m010-{digest[:12]}",
        prompt=prompt,
        max_tokens=sampling.max_tokens,
        temperature=sampling.temperature,
        top_p=sampling.top_p,
        top_k=sampling.top_k,
        stop=sampling.stop,
        seed=sampling.seed,
        timeout_seconds=timeout_seconds,
        intent="runtime-validation",
    )

    started = time.perf_counter()
    try:
        response = runtime.generate(request)
    except RuntimeFailure as exc:
        return InferenceRecord(
            kind=kind,
            outcome=_outcome_for(exc.kind),
            prompt_sha256=digest,
            prompt_text=prompt,
            sampling=sampling,
            model_identity=dict(model_identity),
            runtime_identity=getattr(runtime, "identity", lambda: {})().__dict__
            if callable(getattr(runtime, "identity", None))
            else {},
            inference_duration_ms=Measurement.observed(
                round((time.perf_counter() - started) * 1000.0, 3), "ms", "perf_counter"
            ),
            error=str(exc),
            detail=f"the runtime refused the request with {exc.kind.value}",
            evidence={"runtime_error_kind": exc.kind.value},
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    text = getattr(response, "text", "") or ""
    error = getattr(response, "error", "") or ""
    finish = _finish_name(getattr(response, "finish_reason", ""))

    prompt_tokens, completion_tokens, total_tokens = _counts_from(response)

    if error and not text:
        outcome = _outcome_from_text(finish, error)
    elif finish in {"TIMEOUT", "timeout"}:
        outcome = InferenceOutcome.TIMEOUT
    elif finish in {"CANCELLED", "cancelled"}:
        outcome = InferenceOutcome.CANCELLED
    elif not text.strip():
        outcome = InferenceOutcome.MALFORMED_OUTPUT
    else:
        outcome = InferenceOutcome.COMPLETED

    duration = Measurement.observed(round(elapsed_ms, 3), "ms", "perf_counter")
    load = getattr(response, "load_duration_ms", None)
    throughput = getattr(response, "tokens_per_second", None)

    runtime_identity = getattr(response, "runtime_identity", None)
    if hasattr(runtime_identity, "to_dict"):
        runtime_identity = runtime_identity.to_dict()
    if not isinstance(runtime_identity, dict):
        runtime_identity = {"declared": str(runtime_identity)}

    resources = getattr(response, "resources", {}) or {}
    clean_resources = {
        key: (value if isinstance(value, Measurement)
              else Measurement.observed(value, source="runtime"))
        for key, value in resources.items()
    }

    return InferenceRecord(
        kind=kind,
        outcome=outcome,
        prompt_sha256=digest,
        prompt_text=prompt,
        output_sha256=output_digest(text) if text else "",
        output_text=text,
        finish_reason=finish,
        termination_reason=finish or outcome.value,
        sampling=sampling,
        model_identity=dict(model_identity),
        runtime_identity=runtime_identity,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        load_duration_ms=load if isinstance(load, Measurement)
        else Measurement.unavailable("not reported"),
        inference_duration_ms=duration,
        tokens_per_second=throughput if isinstance(throughput, Measurement)
        else Measurement.unavailable("not reported"),
        resources=clean_resources,
        error=error,
        detail=(
            "a real binary produced this text. It is foundation model output. "
            "It is not a subject, not an experience, and not evidence of memory "
            "or learning."
            if kind.is_real
            else "a stub runner produced this text; it is not a real inference "
                 "and must never be reported as one"
        ),
        evidence={"finish_reason": finish, "error": error},
    )


def _outcome_for(kind: RuntimeErrorKind) -> InferenceOutcome:
    if kind is RuntimeErrorKind.TIMEOUT:
        return InferenceOutcome.TIMEOUT
    if kind is RuntimeErrorKind.CANCELLED:
        return InferenceOutcome.CANCELLED
    if kind is RuntimeErrorKind.MALFORMED_OUTPUT:
        return InferenceOutcome.MALFORMED_OUTPUT
    return InferenceOutcome.ERROR


def _outcome_from_text(finish: str, error: str) -> InferenceOutcome:
    lowered = error.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return InferenceOutcome.TIMEOUT
    if "cancel" in lowered:
        return InferenceOutcome.CANCELLED
    if "malformed" in lowered or "could not parse" in lowered:
        return InferenceOutcome.MALFORMED_OUTPUT
    return InferenceOutcome.ERROR


@dataclass(frozen=True)
class DeterminismObservation:
    """What happened when the identical configuration was run again.

    Deliberately a description rather than a verdict. A language model can be
    nondeterministic for legitimate reasons, and calling the *runtime* broken
    because a *model* sampled differently would be the wrong diagnosis. The
    record says what was observed and leaves the interpretation to a reader.
    """

    attempted: bool
    repeats: int
    identical: bool | None
    first_output_sha256: str
    repeat_output_sha256: str
    token_counts_agree: bool | None
    outcomes_agree: bool | None
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "repeats": self.repeats,
            "identical_outputs": self.identical,
            "first_output_sha256": self.first_output_sha256,
            "repeat_output_sha256": self.repeat_output_sha256,
            "token_counts_agree": self.token_counts_agree,
            "outcomes_agree": self.outcomes_agree,
            "claim": (
                "characterisation only: this records whether identical "
                "configuration produced identical output on this runtime and "
                "model. It is not a claim about model determinism in general, "
                "and it is not hidden when it does not hold."
            ),
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


def compare_repeat(
    first: InferenceRecord,
    second: InferenceRecord | None,
) -> DeterminismObservation:
    """Compare a repeat run against the baseline.

    ``second`` is ``None`` when no repeat was possible, which is reported as
    ``attempted: False`` rather than as a pass.
    """
    if second is None:
        return DeterminismObservation(
            attempted=False,
            repeats=0,
            identical=None,
            first_output_sha256=first.output_sha256,
            repeat_output_sha256="",
            token_counts_agree=None,
            outcomes_agree=None,
            detail=(
                "no repeat run was performed, so determinism was not established "
                "in either direction"
            ),
        )

    identical = bool(
        first.output_sha256
        and first.output_sha256 == second.output_sha256
    )
    token_agree = (
        first.completion_tokens.value == second.completion_tokens.value
        if first.completion_tokens.is_available and second.completion_tokens.is_available
        else None
    )
    outcome_agree = first.outcome is second.outcome

    if identical:
        detail = (
            "the repeat run produced byte-identical output under an identical, "
            "explicitly recorded configuration"
        )
    else:
        detail = (
            "the repeat run produced different output under an identical "
            "configuration. This is recorded as an observation about this "
            "runtime and model pair; it is not evidence that either is broken, "
            "and it is not suppressed."
        )

    return DeterminismObservation(
        attempted=True,
        repeats=1,
        identical=identical,
        first_output_sha256=first.output_sha256,
        repeat_output_sha256=second.output_sha256,
        token_counts_agree=token_agree,
        outcomes_agree=outcome_agree,
        detail=detail,
        evidence={
            "same_sampling": first.sampling.identical_to(second.sampling),
            "first_outcome": first.outcome.value,
            "repeat_outcome": second.outcome.value,
            "prompt_digest_agrees": first.prompt_sha256 == second.prompt_sha256,
        },
    )


__all__ = [
    "BANNED_PROMPT_SUBSTRINGS",
    "BASELINE_SAMPLING",
    "OUTPUT_CLASS",
    "OUTPUT_IS_NOT",
    "VALIDATION_PROMPT",
    "DeterminismObservation",
    "InferenceKind",
    "InferenceOutcome",
    "InferenceRecord",
    "SamplingConfiguration",
    "assert_neutral_prompt",
    "baseline_sampling",
    "compare_repeat",
    "output_digest",
    "prompt_digest",
    "run_inference",
]
