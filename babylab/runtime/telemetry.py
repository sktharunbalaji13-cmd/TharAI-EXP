"""Runtime telemetry for the M002 Observatory.

Scope
-----
The Observatory displays what the *runtime* did. It is a machine telemetry
display, not a mind-reading display, and this module is where that line is held.

Deliberately absent, and absent on purpose
------------------------------------------
No consciousness indicator, intelligence meter, readiness score, mood,
engagement, confidence, attention, "thought visualisation", or neural-activity
animation. None of those is produced by a defined external measurement, so
rendering one would be inventing data. If a future milestone introduces a real
measurement for one of them, it arrives with the measurement, not with a widget.

What is rendered
----------------
Runtime state, model identity, the last inference, and resource observations --
each carrying the epistemic status the value was recorded with, so ``UNAVAILABLE``
reads as unavailable rather than as zero.

Every value shown here is a fact about a process on this machine. None of it is a
fact about a subject, because M006 has no subject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from babylab.runtime.contract import EpistemicStatus, Measurement, RuntimeState
from babylab.runtime.hardware import HardwareReport
from babylab.runtime.runtime import FoundationRuntime

#: Telemetry keys this module is willing to show. A key outside this set is not
#: rendered, which makes adding a "mood" field a deliberate edit rather than an
#: accident.
ALLOWED_TELEMETRY = frozenset({
    "model_loaded",
    "model_identity",
    "runtime_state",
    "last_inference",
    "resource_observations",
    "hardware",
    "inference_count",
    "configuration_state",
})


@dataclass(frozen=True)
class RuntimeTelemetry:
    """A snapshot of runtime facts, ready to render."""

    available: bool
    state: str
    detail: str
    sections: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    unavailable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "state": self.state,
            "detail": self.detail,
            "unavailable_reason": self.unavailable_reason,
            "sections": {k: list(v) for k, v in self.sections.items()},
        }

    def render_lines(self, width: int = 78) -> list[str]:
        """Render as text, in the Observatory's own style."""
        if not self.available:
            return [
                "  -- RUNTIME -- " + "-" * 40,
                f"  {'runtime'.ljust(18)}{self.state}",
                f"  {'detail'.ljust(18)}{self.unavailable_reason or self.detail}",
            ]
        lines = ["  -- RUNTIME -- " + "-" * 40]
        for section, rows in self.sections.items():
            lines.append(f"  {section}")
            for key, value in rows:
                lines.append(f"    {key.ljust(20)}{value}")
        return lines


def _fmt(measurement: Measurement | None, suffix: str = "") -> str:
    """Render one measurement with its status. Never prints a bare number."""
    if measurement is None:
        return "UNAVAILABLE"
    if measurement.status is EpistemicStatus.UNAVAILABLE:
        return f"UNAVAILABLE [{measurement.source}]" if measurement.source else "UNAVAILABLE"
    text = f"{measurement.value}{suffix} [{measurement.status.value}]"
    return text


def _model_identity_rows(identity: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not identity:
        return [("model", "NOT_CONFIGURED")]
    rows: list[tuple[str, str]] = [("model", identity.get("name") or "(unnamed)")]
    if identity.get("path"):
        rows.append(("artifact", identity["path"]))
    if identity.get("sha256"):
        rows.append(("sha256", identity["sha256"][:16] + "..."))
    if identity.get("size_bytes"):
        rows.append(("size", f"{identity['size_bytes'] / (1024 ** 2):.1f} MiB"))
    for key in ("format", "quantization", "license"):
        if identity.get(key):
            rows.append((key, str(identity[key])))
    return rows


def _inference_rows(response: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not response:
        return [("last inference", "NONE")]
    rows = [
        ("request", response.get("request_id", "?")),
        ("finish", response.get("finish_reason", "?")),
        ("output chars", str(response.get("output_chars", "?"))),
    ]
    for label, key in (
        ("prompt tokens", "prompt_tokens"),
        ("completion tokens", "completion_tokens"),
        ("inference ms", "inference_duration_ms"),
        ("tokens/s", "tokens_per_second"),
    ):
        block = response.get(key)
        if isinstance(block, dict):
            rows.append((label, _fmt(_measurement_from_dict(block))))
    if response.get("error"):
        rows.append(("error", response["error"]))
    return rows


def _measurement_from_dict(block: dict[str, Any]) -> Measurement:
    return Measurement(
        value=block.get("value"),
        status=EpistemicStatus(block.get("status", "UNAVAILABLE")),
        unit=block.get("unit", ""),
        source=block.get("source", ""),
    )


def _hardware_rows(hardware: HardwareReport | None) -> list[tuple[str, str]]:
    if hardware is None:
        return [("hardware", "NOT_PROBED")]
    rows: list[tuple[str, str]] = []
    if hardware.gpu.available:
        rows.append(("gpu", str(hardware.gpu.name.value)))
        rows.append(("vram", _fmt(hardware.gpu.vram_total_bytes)))
    else:
        rows.append(("gpu", "UNAVAILABLE"))
    name = hardware.cpu.get("name")
    if name is not None:
        rows.append(("cpu", str(name.value)))
    cores = hardware.cpu.get("logical_cores")
    if cores is not None:
        rows.append(("cores", _fmt(cores)))
    total = hardware.memory.get("total_bytes")
    if total is not None:
        rows.append(("system ram", _fmt(total)))
    return rows


def build_telemetry(
    runtime: FoundationRuntime | None,
    configuration_state: str = "NOT_CONFIGURED",
) -> RuntimeTelemetry:
    """Assemble runtime telemetry for display. Never raises.

    ``runtime`` being ``None`` is a normal state: the laboratory may be running
    with no runtime at all, and the Observatory should say so rather than fail.
    """
    if runtime is None:
        return RuntimeTelemetry(
            available=False,
            state=configuration_state,
            detail="no runtime instance was constructed",
            unavailable_reason=(
                "no runtime instance: the laboratory has no foundation model "
                "configured, which is the correct state until a human supplies "
                "one explicitly"
            ),
        )

    status = runtime.status()
    last = status.get("last_response") or {}
    # The response's completion length is not in to_dict(); recompute cheaply.
    inference_view: dict[str, Any] = {}
    if last:
        inference_view = dict(last)
        inference_view["output_chars"] = len(last.get("text", ""))

    sections: dict[str, list[tuple[str, str]]] = {
        "state": [
            ("runtime", status.get("state", "?")),
            ("configuration", configuration_state),
            ("inferences", str(status.get("inference_count", 0))),
        ],
        "model": _model_identity_rows(status.get("model")),
        "last inference": _inference_rows(inference_view or None),
        "hardware": _hardware_rows(runtime.hardware),
    }

    # Guarantee the epistemic framing is visible even in a passing case.
    sections["notes"] = [
        ("conversation retained", "no"),
        ("autonomous", "no"),
        ("subject", "none attached"),
    ]

    return RuntimeTelemetry(
        available=True,
        state=status.get("state", RuntimeState.NOT_CONFIGURED.value),
        detail=status.get("failure_detail", "") or "runtime constructed",
        sections=sections,
    )


__all__ = ["ALLOWED_TELEMETRY", "RuntimeTelemetry", "build_telemetry"]
