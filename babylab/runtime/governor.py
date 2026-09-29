"""Resource admission and limits for Milestone 006.

What this decides
-----------------
Whether a *proposed* model may be loaded, given what the host actually reports.
It is an admission controller, not a performance tuner: its job is to refuse a
load that cannot work, and to say why.

The epistemics matter more than usual here, because the two common failure modes
both involve a number that was invented:

* **Refusing too much.** Estimating VRAM from a parameter count and refusing on
  the estimate would reject models that fit. The estimate is never used to
  refuse.
* **Accepting too much.** Assuming "there's probably enough VRAM" would accept a
  model that fails at load. When VRAM is genuinely unknown, that is reported as
  ``UNKNOWN`` and the caller decides, not this module guessing.

Therefore: admission refuses on *observed* insufficient VRAM only. When the
total is ``UNAVAILABLE``, the outcome is ``UNKNOWN`` and the decision is
deferred to the human who configured it. That is the honest answer on a machine
where the only VRAM source saturates at 4 GiB.

Nothing here runs the model, and nothing here acquires anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from babylab.runtime.contract import Measurement
from babylab.runtime.hardware import HardwareReport


class Admission(str, Enum):
    """The outcome of a load request."""

    ADMIT = "ADMIT"
    REFUSE = "REFUSE"
    #: Could not be decided from observed values. Never silently ADMIT.
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class AdmissionDecision:
    """Why a load was admitted, refused, or could not be judged."""

    admission: Admission
    reason: str
    requested_bytes: Measurement
    available_bytes: Measurement
    evidence: dict[str, Any]

    @property
    def admitted(self) -> bool:
        return self.admission is Admission.ADMIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.value,
            "reason": self.reason,
            "requested_bytes": self.requested_bytes.to_dict(),
            "available_bytes": self.available_bytes.to_dict(),
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ResourcePolicy:
    """Ceilings the runtime will not exceed. Explicit, never implicit."""

    #: Refuse a load whose weights exceed this many bytes.
    max_model_bytes: int | None = None
    #: Refuse a load whose weights plus context exceed this share of VRAM.
    max_vram_fraction: float = 0.85
    #: Context lengths above this are refused outright.
    max_context_length: int = 32768
    #: When True, a model that needs the GPU may not fall back to CPU.
    require_gpu: bool = False
    #: Wall-clock ceiling for one generation.
    max_inference_seconds: float = 600.0

    def __post_init__(self) -> None:
        if not 0.0 < self.max_vram_fraction <= 1.0:
            raise ValueError(
                f"max_vram_fraction must be within (0, 1], got {self.max_vram_fraction}"
            )
        if self.max_context_length < 1:
            raise ValueError("max_context_length must be >= 1")
        if self.max_inference_seconds <= 0:
            raise ValueError("max_inference_seconds must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_model_bytes": self.max_model_bytes,
            "max_vram_fraction": self.max_vram_fraction,
            "max_context_length": self.max_context_length,
            "require_gpu": self.require_gpu,
            "max_inference_seconds": self.max_inference_seconds,
        }


def _vram_budget(hardware: HardwareReport, policy: ResourcePolicy) -> Measurement:
    """Bytes this policy would allow on the GPU, from the *observed* total."""
    total = hardware.gpu.vram_total_bytes
    if not total.is_available:
        return Measurement.unavailable(
            "VRAM total is not observable on this host, so no GPU budget can "
            f"be computed ({total.source})"
        )
    return Measurement.derived(
        int(total.value * policy.max_vram_fraction),
        "bytes",
        f"observed VRAM {total.value} x fraction {policy.max_vram_fraction}",
    )


def evaluate_load(
    model_size_bytes: int | None,
    context_length: int,
    hardware: HardwareReport,
    policy: ResourcePolicy,
) -> AdmissionDecision:
    """Decide whether a proposed model may be loaded.

    Refuses only on observed facts. When the relevant fact is unobservable the
    result is :attr:`Admission.UNKNOWN`, which callers must surface rather than
    read as permission.
    """
    evidence: dict[str, Any] = {
        "context_length": context_length,
        "policy": policy.to_dict(),
        "gpu_available": hardware.gpu.available,
    }

    if model_size_bytes is None:
        return AdmissionDecision(
            admission=Admission.UNKNOWN,
            reason=(
                "model size is not declared in the configuration, so no memory "
                "admission decision can be made from evidence"
            ),
            requested_bytes=Measurement.unavailable("configuration declares no size"),
            available_bytes=hardware.gpu.vram_total_bytes,
            evidence=evidence,
        )

    requested = Measurement.observed(model_size_bytes, "bytes", "configuration")
    evidence["model_size_bytes"] = model_size_bytes

    if policy.max_model_bytes is not None and model_size_bytes > policy.max_model_bytes:
        return AdmissionDecision(
            admission=Admission.REFUSE,
            reason=(
                f"model is {model_size_bytes} bytes, above the configured ceiling "
                f"of {policy.max_model_bytes} bytes"
            ),
            requested_bytes=requested,
            available_bytes=hardware.gpu.vram_total_bytes,
            evidence=evidence,
        )

    if context_length > policy.max_context_length:
        return AdmissionDecision(
            admission=Admission.REFUSE,
            reason=(
                f"context length {context_length} exceeds the policy ceiling of "
                f"{policy.max_context_length}"
            ),
            requested_bytes=requested,
            available_bytes=hardware.gpu.vram_total_bytes,
            evidence=evidence,
        )

    budget = _vram_budget(hardware, policy)

    if not hardware.gpu.available:
        if policy.require_gpu:
            return AdmissionDecision(
                admission=Admission.REFUSE,
                reason=(
                    "policy requires a GPU and none was detected; CPU fallback is "
                    "disabled by configuration"
                ),
                requested_bytes=requested,
                available_bytes=Measurement.unavailable("no GPU present"),
                evidence=evidence,
            )
        return AdmissionDecision(
            admission=Admission.UNKNOWN,
            reason=(
                "no GPU detected. The runtime may still run on CPU, which is much "
                "slower; this is reported rather than assumed acceptable."
            ),
            requested_bytes=requested,
            available_bytes=Measurement.unavailable("no GPU present"),
            evidence=evidence,
        )

    if not budget.is_available:
        return AdmissionDecision(
            admission=Admission.UNKNOWN,
            reason=(
                "VRAM total is not observable on this host "
                f"({budget.source}); the laboratory will not estimate it. "
                "Confirm the model fits before configuring it."
            ),
            requested_bytes=requested,
            available_bytes=budget,
            evidence=evidence,
        )

    if model_size_bytes > budget.value:
        return AdmissionDecision(
            admission=Admission.REFUSE,
            reason=(
                f"model is {model_size_bytes / (1024 ** 3):.2f} GiB, above the "
                f"policy budget of {budget.value / (1024 ** 3):.2f} GiB "
                f"({budget.source})"
            ),
            requested_bytes=requested,
            available_bytes=budget,
            evidence=evidence,
        )

    return AdmissionDecision(
        admission=Admission.ADMIT,
        reason=(
            f"model {model_size_bytes / (1024 ** 3):.2f} GiB fits within the "
            f"{budget.value / (1024 ** 3):.2f} GiB budget ({budget.source})"
        ),
        requested_bytes=requested,
        available_bytes=budget,
        evidence=evidence,
    )


def compute_throughput(
    completion_tokens: Measurement,
    duration_ms: Measurement,
) -> Measurement:
    """Tokens per second, DERIVED from two observed values.

    Returns ``UNAVAILABLE`` rather than a number when either input is missing,
    because a rate computed from an unmeasured token count is a fiction.
    """
    if not completion_tokens.is_available or not duration_ms.is_available:
        return Measurement.unavailable(
            "needs both an observed completion-token count and an observed duration"
        )
    if not duration_ms.value or duration_ms.value <= 0:
        return Measurement.unavailable("duration was zero")
    rate = completion_tokens.value / (duration_ms.value / 1000.0)
    return Measurement.derived(round(rate, 3), "tokens/s", "completion_tokens / duration")


__all__ = [
    "Admission",
    "AdmissionDecision",
    "ResourcePolicy",
    "compute_throughput",
    "evaluate_load",
]
