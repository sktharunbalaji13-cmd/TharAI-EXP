"""Birth state for the M002 Observatory.

What is shown
-------------
Whether a birth was attempted and what kind, the gate verdict, the subject id
and lifecycle if one exists, T_birth, foundation and environment references,
experience count, first-experience status, provenance integrity, model runtime
status, and key custody. Every one of those is a fact about records the
laboratory holds.

What is never shown
--------------------
Consciousness, sentience, awareness, intelligence, feelings, curiosity, learning
progress, developmental level. None is implemented and none is measurable, so
each is reported UNAVAILABLE with the reason beside it -- the alternative would
be hiding the absence, which reads as quietly as claiming the presence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Telemetry keys this display is willing to show.
ALLOWED_TELEMETRY = frozenset({
    "birth_attempted",
    "birth_mode",
    "birth_outcome",
    "gate_verdict",
    "gate_blocking",
    "subject_id",
    "lifecycle_state",
    "t_birth",
    "foundation_state",
    "environment_reference",
    "experience_count",
    "first_experience",
    "provenance_integrity",
    "model_runtime",
    "key_custody",
})


@dataclass(frozen=True)
class BirthTelemetry:
    """A read-only view of birth state, ready to render."""

    available: bool
    sections: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    unavailable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "sections": {k: list(v) for k, v in self.sections.items()},
        }

    def render_lines(self) -> list[str]:
        if not self.available:
            return [
                "  -- BIRTH -- " + "-" * 40,
                f"  {'status'.ljust(20)}{self.unavailable_reason}",
            ]
        lines = ["  -- BIRTH -- " + "-" * 40]
        for section, rows in self.sections.items():
            lines.append(f"  {section}")
            for key, value in rows:
                lines.append(f"    {key.ljust(18)}{value}")
        return lines


def build_telemetry(record=None, gate_verdict=None) -> BirthTelemetry:
    """Assemble birth telemetry from a ceremony record and a gate verdict.

    ``None`` for both is the normal state of a laboratory that has not run a
    ceremony: the display says no birth was attempted rather than failing.
    """
    if record is None:
        return BirthTelemetry(
            available=False,
            unavailable_reason="NO BIRTH ATTEMPTED",
        )

    gate = gate_verdict.to_dict() if gate_verdict is not None else {}
    t_birth = record.t_birth.to_dict() if record.t_birth else None

    sections: dict[str, list[tuple[str, str]]] = {
        "ceremony": [
            ("mode", record.mode.value),
            ("outcome", record.outcome),
            ("simulated_is_not_birth",
             "true" if record.mode.value == "SIMULATED" else "false"),
        ],
        "gate": [
            ("verdict", gate.get("verdict", "UNEVALUATED")),
            ("blocking", ", ".join(gate.get("blocking", [])) or "(none)"),
        ],
        "subject": [
            ("subject", record.subject_id or "NONE"),
            ("t_birth", t_birth["timestamp"] if t_birth else "NONE"),
        ],
        "first experience": [
            ("id", record.first_experience_id or "NONE"),
            ("hash", (record.first_experience_hash[:16] + "...")
             if record.first_experience_hash else "NONE"),
        ],
        "not implemented": [
            ("consciousness", "UNAVAILABLE - no such mechanism exists"),
            ("sentience", "UNAVAILABLE - no such mechanism exists"),
            ("awareness", "UNAVAILABLE - no such mechanism exists"),
            ("intelligence", "UNAVAILABLE - no such mechanism exists"),
            ("feelings", "UNAVAILABLE - no such mechanism exists"),
            ("learning progress", "UNAVAILABLE - no learning exists"),
            ("developmental level", "UNAVAILABLE - no curriculum exists"),
        ],
    }
    return BirthTelemetry(available=True, sections=sections)


__all__ = ["ALLOWED_TELEMETRY", "BirthTelemetry", "build_telemetry"]
