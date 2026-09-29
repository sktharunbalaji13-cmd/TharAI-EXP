"""Subject infrastructure telemetry for the M002 Observatory.

The distinction this module holds
----------------------------------
**Subject infrastructure state is not subject mental state.**

What is shown: existence, id, lifecycle, foundation reference, environment
reference, creation record, state version and hash, experience count, the latest
experience, provenance integrity, capability state. Every one of those is a fact
about a record the laboratory holds.

What is never shown: consciousness, awareness, intelligence, sentience,
feelings, curiosity, readiness, confidence, engagement. None of those is
implemented, none is measurable, and rendering one would be inventing data. They
are reported ``UNAVAILABLE`` -- and the reason they stay unavailable belongs in
the same line, so that a reader cannot mistake a missing widget for a missing
measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from subject.harness import HarnessSubject

#: Telemetry keys this display is willing to show.
ALLOWED_TELEMETRY = frozenset({
    "subject_existence",
    "subject_id",
    "lifecycle_state",
    "foundation_reference",
    "environment_reference",
    "creation_record",
    "subject_state_version",
    "subject_state_hash",
    "experience_count",
    "latest_experience",
    "provenance_integrity",
    "capability_state",
})


@dataclass(frozen=True)
class SubjectTelemetry:
    """A read-only view of one subject record, ready to render."""

    available: bool
    subject_id: str
    sections: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    unavailable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "subject_id": self.subject_id,
            "unavailable_reason": self.unavailable_reason,
            "sections": {k: list(v) for k, v in self.sections.items()},
        }

    def render_lines(self) -> list[str]:
        if not self.available:
            return [
                "  -- SUBJECT -- " + "-" * 38,
                f"  {'status'.ljust(20)}{self.unavailable_reason}",
            ]
        lines = ["  -- SUBJECT -- " + "-" * 38]
        lines.append(f"  {'subject'.ljust(20)}{self.subject_id}")
        for section, rows in self.sections.items():
            lines.append(f"  {section}")
            for key, value in rows:
                lines.append(f"    {key.ljust(18)}{value}")
        return lines


def build_telemetry(subject: HarnessSubject | None) -> SubjectTelemetry:
    """Assemble subject telemetry. Never raises, never invents."""
    if subject is None:
        return SubjectTelemetry(
            available=False,
            subject_id="",
            unavailable_reason="NO SUBJECT ATTACHED",
        )

    latest = subject.experiences[-1] if subject.experiences else None
    sections: dict[str, list[tuple[str, str]]] = {
        "identity": [
            ("issuer", subject.identity.issuer),
            ("schema", subject.identity.schema_version),
            ("identity hash", subject.identity.identity_hash[:16] + "..."),
        ],
        "foundation": [
            ("state", subject.identity.foundation.state),
            ("digest", (subject.identity.foundation.artifact_digest[:16] + "...")
             if subject.identity.foundation.artifact_digest else "NONE"),
            ("classification",
             subject.identity.foundation.classification),
        ],
        "lifecycle": [
            ("state", subject.lifecycle.state.value),
            ("transitions", str(len(subject.lifecycle.history))),
        ],
        "state": [
            ("version", str(subject.state.state_version)),
            ("hash", subject.state.state_hash[:16] + "..."),
            ("experiences", str(subject.experience_count)),
        ],
        "latest experience": (
            [("id", latest.experience_id),
             ("sequence", str(latest.sequence_number)),
             ("operation", latest.action_operation),
             ("validation", latest.action_validation),
             ("consequence", latest.consequence)]
            if latest else [("latest experience", "NONE")]
        ),
        "capabilities": [
            (key, value)
            for key, value in sorted(subject.state.capabilities.items())
        ],
        "not implemented": [
            ("consciousness", "UNAVAILABLE - no such mechanism exists"),
            ("awareness", "UNAVAILABLE - no such mechanism exists"),
            ("intelligence", "UNAVAILABLE - no such mechanism exists"),
            ("sentience", "UNAVAILABLE - no such mechanism exists"),
            ("feelings", "UNAVAILABLE - no such mechanism exists"),
            ("curiosity", "UNAVAILABLE - no such mechanism exists"),
            ("readiness", "UNAVAILABLE - no such mechanism exists"),
        ],
    }
    return SubjectTelemetry(
        available=True, subject_id=subject.subject_id, sections=sections)


__all__ = ["ALLOWED_TELEMETRY", "SubjectTelemetry", "build_telemetry"]
