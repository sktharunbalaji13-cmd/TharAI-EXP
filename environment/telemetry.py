"""Environment telemetry for the M002 Observatory.

The line this module holds
--------------------------
**An environment has state and transitions. It does not have states of mind.**

So the display reports identity, state version, state hash, the latest
observation and action, resources, active branch and snapshot lineage -- and
nothing about wanting, thinking, curiosity, or learning. Those are not
attributes of a world; they are claims about a mind, and no measurement here
produces one. The ban list is enforced by a test over emitted literals, so
adding a "the environment wants to..." line later takes a deliberate edit.

Every numeric value carries its epistemic status, continuing the M002
discipline: a resource the environment does not model is ``UNAVAILABLE`` rather
than assumed unlimited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from babylab.measure import EpistemicStatus, Measurement
from environment.environment import Environment

#: Telemetry keys this display is willing to show.
ALLOWED_TELEMETRY = frozenset({
    "environment_identity",
    "state_version",
    "state_hash",
    "latest_observation",
    "latest_action",
    "latest_result",
    "resources",
    "active_branch",
    "snapshot_lineage",
    "event_chain",
})


@dataclass(frozen=True)
class EnvironmentTelemetry:
    """A read-only view of one environment, ready to render."""

    available: bool
    environment_id: str
    state_version: int
    state_hash: str
    sections: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    unavailable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "environment_id": self.environment_id,
            "state_version": self.state_version,
            "state_hash": self.state_hash,
            "unavailable_reason": self.unavailable_reason,
            "sections": {k: list(v) for k, v in self.sections.items()},
        }

    def render_lines(self) -> list[str]:
        if not self.available:
            return [
                "  -- ENVIRONMENT -- " + "-" * 34,
                f"  {'status'.ljust(20)}{self.unavailable_reason}",
            ]
        lines = ["  -- ENVIRONMENT -- " + "-" * 34]
        lines.append(f"  {'environment'.ljust(20)}{self.environment_id}")
        lines.append(f"  {'state version'.ljust(20)}{self.state_version}")
        lines.append(f"  {'state hash'.ljust(20)}{self.state_hash[:16]}...")
        for section, rows in self.sections.items():
            lines.append(f"  {section}")
            for key, value in rows:
                lines.append(f"    {key.ljust(18)}{value}")
        return lines


def _fmt(measurement: Measurement) -> str:
    if measurement.status is EpistemicStatus.UNAVAILABLE:
        return "UNAVAILABLE"
    return f"{measurement.value}{(' ' + measurement.unit) if measurement.unit else ''} " \
           f"[{measurement.status.value}]"


def build_telemetry(environment: Environment | None) -> EnvironmentTelemetry:
    """Assemble environment telemetry. Never raises."""
    if environment is None:
        return EnvironmentTelemetry(
            available=False,
            environment_id="",
            state_version=0,
            state_hash="",
            unavailable_reason="no environment instance",
        )

    identity = environment.identity
    status = environment.status()
    resources = environment.state.resource_observations()

    latest_action = ""
    latest_result = ""
    for event in reversed(environment.events.events()):
        if event.event_type.value == "action_applied":
            latest_result = (
                f"{event.payload.get('action_id', '?')[:12]} "
                f"-> {event.payload.get('consequence', '?')}"
            )
            break
    for event in reversed(environment.events.events()):
        if event.event_type.value == "action_requested":
            latest_action = (
                f"{event.payload.get('operation', '?')} "
                f"on {event.payload.get('target') or '(none)'}"
            )
            break

    sections: dict[str, list[tuple[str, str]]] = {
        "identity": [
            ("type", identity.environment_type),
            ("implementation", identity.implementation_version),
            ("config hash", identity.configuration_hash[:16] + "..."),
            ("declared by", identity.declared_by),
        ],
        "history": [
            ("events", str(status["event_count"])),
            ("chain intact", str(status["chain_intact"])),
            ("active branch", status["current_branch_id"]),
        ],
        "activity": [
            ("latest action", latest_action or "NONE"),
            ("latest result", latest_result or "NONE"),
        ],
        "resources": [
            (key, _fmt(measurement)) for key, measurement in sorted(resources.items())
        ],
        "lineage": [
            (branch_id, " -> ".join(environment.branch_lineage(branch_id)))
            for branch_id in sorted(environment.branches)
        ],
    }

    return EnvironmentTelemetry(
        available=True,
        environment_id=identity.environment_id,
        state_version=environment.state.state_version,
        state_hash=environment.state.state_hash,
        sections=sections,
    )


__all__ = ["ALLOWED_TELEMETRY", "EnvironmentTelemetry", "build_telemetry"]
