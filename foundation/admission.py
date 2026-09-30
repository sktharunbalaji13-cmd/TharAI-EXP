"""M010 resource admission: may this artifact be attempted on this machine?

The question this answers
-------------------------
"Given the artifact size, the configured context, the requested GPU layers, and
the VRAM actually observable *right now*, is attempting a load defensible?"

Three answers, and the third is not a soft yes
-----------------------------------------------
``ADMIT``
    The evidence supports an attempt.
``REFUSE``
    The evidence rules it out. Observed facts only.
``UNKNOWN``
    A fact needed for the decision is not observable.

``UNKNOWN`` is the interesting one. The temptation is to read it as permission,
because a load might well succeed. It is not permission: if VRAM cannot be
observed, the laboratory does not estimate it, and if it estimates it, a
quantization-heavy model on a laptop GPU produces a load failure at best and a
thrashing machine at worst. :meth:`AdmissionDecision.may_attempt` is ``True``
only for ``ADMIT``, and the refusal path records why the retry matrix does not
include a smaller configuration.

VRAM is measured, not inferred
------------------------------
The size of a model is not its memory footprint, and a model's memory footprint
is not VRAM. KV cache scales with context length and layer count, not file size.
:func:`foundation.hardware` obtains free VRAM from ``nvidia-smi``; this module
uses that figure and never derives one from the artifact.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from babylab.runtime.governor import Admission
from babylab.runtime.hardware import HardwareReport, detect_gpu


class AdmissionState(str, enum.Enum):
    ADMIT = "ADMIT"
    REFUSE = "REFUSE"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class AdmissionDecision:
    """The admission verdict, with the evidence that produced it."""

    state: AdmissionState
    reason: str
    artifact_bytes: int | None = None
    context_length: int | None = None
    gpu_requested_layers: int | None = None
    vram_total_bytes: int | None = None
    vram_free_bytes: int | None = None
    vram_source: str = "none"
    #: Deliberately not inferred. Stated as a reminder in the report.
    vram_per_artifact_inference: str = (
        "not performed: VRAM consumed by a GGUF is not its file size. KV cache "
        "scales with context length and layer count, so no figure here is "
        "derived from artifact size."
    )
    policy: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def may_attempt(self) -> bool:
        """Only an explicit ADMIT authorises an attempt. UNKNOWN does not."""
        return self.state is AdmissionState.ADMIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "reason": self.reason,
            "may_attempt": self.may_attempt,
            "artifact_bytes": self.artifact_bytes,
            "context_length": self.context_length,
            "gpu_requested_layers": self.gpu_requested_layers,
            "vram_total_bytes": self.vram_total_bytes,
            "vram_free_bytes": self.vram_free_bytes,
            "vram_source": self.vram_source,
            "vram_per_artifact_inference": self.vram_per_artifact_inference,
            "policy": dict(self.policy),
            "evidence": dict(self.evidence),
        }


def observe_vram() -> dict[str, Any]:
    """Ask the machine how much VRAM is free right now.

    ``nvidia-smi`` is the vendor's own tool, so a figure from it is observed.
    When it is absent the answer is an absence, and the caller is expected to
    report ``UNKNOWN`` rather than substitute a remembered total.
    """
    report = detect_gpu()
    total = report.vram_total_bytes
    used = report.vram_used_bytes
    free = None
    if total.is_available and used.is_available:
        free = max(0, int(total.value) - int(used.value))
    return {
        "total_bytes": int(total.value) if total.is_available else None,
        "used_bytes": int(used.value) if used.is_available else None,
        "free_bytes": free,
        "source": total.source if total.is_available else "no vendor tool reported VRAM",
        "gpu_name": report.name.value if report.name.is_available else "UNAVAILABLE",
        "gpu_available": report.available,
    }


def evaluate_admission(
    *,
    artifact_bytes: int | None,
    context_length: int,
    gpu_requested_layers: int | None = None,
    max_artifact_bytes: int | None = None,
    vram_headroom_fraction: float = 0.9,
    require_gpu: bool = False,
    vram_observation: dict[str, Any] | None = None,
    gpu_available: bool | None = None,
) -> AdmissionDecision:
    """Decide whether an attempt is defensible, from observed facts only.

    ``vram_observation`` and ``gpu_available`` exist so tests can drive specific
    states without needing a real GPU of a particular size. The default path
    measures this machine.
    """
    vram = vram_observation if vram_observation is not None else observe_vram()
    gpu_present = gpu_available if gpu_available is not None else bool(vram.get("gpu_available"))

    policy = {
        "max_artifact_bytes": max_artifact_bytes,
        "vram_headroom_fraction": vram_headroom_fraction,
        "require_gpu": require_gpu,
    }
    evidence: dict[str, Any] = {
        "artifact_bytes": artifact_bytes,
        "context_length": context_length,
        "gpu_requested_layers": gpu_requested_layers,
        "gpu_present": gpu_present,
        "vram_source": vram.get("source"),
    }

    if artifact_bytes is None or artifact_bytes <= 0:
        return AdmissionDecision(
            state=AdmissionState.UNKNOWN,
            reason=(
                "the artifact size is not established, so no memory admission "
                "decision can be made from evidence. The laboratory will not "
                "estimate a size and admit on that basis."
            ),
            context_length=context_length,
            gpu_requested_layers=gpu_requested_layers,
            vram_source=str(vram.get("source", "none")),
            policy=policy,
            evidence=evidence,
        )

    if max_artifact_bytes is not None and artifact_bytes > max_artifact_bytes:
        return AdmissionDecision(
            state=AdmissionState.REFUSE,
            reason=(
                f"artifact is {artifact_bytes} bytes, above the declared ceiling "
                f"of {max_artifact_bytes} bytes"
            ),
            artifact_bytes=artifact_bytes,
            context_length=context_length,
            gpu_requested_layers=gpu_requested_layers,
            vram_total_bytes=vram.get("total_bytes"),
            vram_free_bytes=vram.get("free_bytes"),
            vram_source=str(vram.get("source", "none")),
            policy=policy,
            evidence=evidence,
        )

    if require_gpu and not gpu_present:
        return AdmissionDecision(
            state=AdmissionState.REFUSE,
            reason=(
                "the policy requires a GPU and no GPU was observed; CPU fallback "
                "is disabled by configuration rather than silently enabled"
            ),
            artifact_bytes=artifact_bytes,
            context_length=context_length,
            gpu_requested_layers=gpu_requested_layers,
            vram_source=str(vram.get("source", "none")),
            policy=policy,
            evidence=evidence,
        )

    free = vram.get("free_bytes")
    if free is None:
        return AdmissionDecision(
            state=AdmissionState.UNKNOWN,
            reason=(
                "free VRAM is not observable on this host "
                f"({vram.get('source')}). The laboratory will not estimate it, and "
                "UNKNOWN is not converted into ADMIT."
            ),
            artifact_bytes=artifact_bytes,
            context_length=context_length,
            gpu_requested_layers=gpu_requested_layers,
            vram_total_bytes=vram.get("total_bytes"),
            vram_source=str(vram.get("source", "none")),
            policy=policy,
            evidence=evidence,
        )

    budget = int(free * vram_headroom_fraction)
    if artifact_bytes > budget:
        return AdmissionDecision(
            state=AdmissionState.REFUSE,
            reason=(
                f"artifact is {artifact_bytes / (1024 ** 3):.2f} GiB against a free "
                f"VRAM budget of {budget / (1024 ** 3):.2f} GiB "
                f"({free / (1024 ** 3):.2f} GiB free at "
                f"{vram_headroom_fraction:.0%} headroom, source "
                f"{vram.get('source')})"
            ),
            artifact_bytes=artifact_bytes,
            context_length=context_length,
            gpu_requested_layers=gpu_requested_layers,
            vram_total_bytes=vram.get("total_bytes"),
            vram_free_bytes=free,
            vram_source=str(vram.get("source", "none")),
            policy=policy,
            evidence=evidence,
        )

    return AdmissionDecision(
        state=AdmissionState.ADMIT,
        reason=(
            f"artifact {artifact_bytes / (1024 ** 3):.2f} GiB fits within "
            f"{budget / (1024 ** 3):.2f} GiB of free VRAM "
            f"({vram.get('source')}); context {context_length}, "
            f"gpu layers {gpu_requested_layers}"
        ),
        artifact_bytes=artifact_bytes,
        context_length=context_length,
        gpu_requested_layers=gpu_requested_layers,
        vram_total_bytes=vram.get("total_bytes"),
        vram_free_bytes=free,
        vram_source=str(vram.get("source", "none")),
        policy=policy,
        evidence=evidence,
    )


def from_m006(decision: Any) -> AdmissionState:
    """Bridge an M006 :class:`Admission` into the M010 vocabulary.

    The M006 governor keeps its own enum; translating rather than reimplementing
    keeps one admission rule per project instead of two that can disagree.
    """
    if decision.admission is Admission.ADMIT:
        return AdmissionState.ADMIT
    if decision.admission is Admission.REFUSE:
        return AdmissionState.REFUSE
    return AdmissionState.UNKNOWN


__all__ = [
    "AdmissionDecision",
    "AdmissionState",
    "evaluate_admission",
    "from_m006",
    "observe_vram",
]
