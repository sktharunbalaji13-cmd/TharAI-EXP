"""Action results: consequences, state deltas, and resource changes.

The honesty rule here is narrow and important: **an action that changed nothing
says so.** There is no :class:`Consequence` invented to fill a result, and no
"success" reported for a request the environment could not carry out. A caller
that cannot tell the difference between "did nothing" and "succeeded quietly"
cannot learn from the environment at all, which defeats the entire point.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex
from babylab.measure import Measurement
from environment.state import EnvironmentState


class ConsequenceKind(str, enum.Enum):
    """What actually happened, as opposed to what was requested."""

    STATE_CHANGED = "STATE_CHANGED"
    #: The request was valid and possible, and deliberately did nothing.
    NO_EFFECT = "NO_EFFECT"
    NOT_APPLIED = "NOT_APPLIED"
    FAULTED = "FAULTED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class StateDelta:
    """The difference between two states, stated as observable facts."""

    added_entities: tuple[str, ...] = ()
    removed_entities: tuple[str, ...] = ()
    changed_entities: tuple[str, ...] = ()
    from_state_version: int = 0
    to_state_version: int = 0
    from_state_hash: str = ""
    to_state_hash: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.added_entities or self.removed_entities
                    or self.changed_entities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_entities": list(self.added_entities),
            "removed_entities": list(self.removed_entities),
            "changed_entities": list(self.changed_entities),
            "from_state_version": self.from_state_version,
            "to_state_version": self.to_state_version,
            "from_state_hash": self.from_state_hash,
            "to_state_hash": self.to_state_hash,
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


@dataclass(frozen=True)
class ResourceChange:
    """One resource's movement. A measurement, never a score change."""

    resource_id: str
    before: Measurement
    after: Measurement
    delta: Measurement

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "delta": self.delta.to_dict(),
        }


@dataclass(frozen=True)
class ActionResult:
    """The full account of one action: verdict, effect, and cost."""

    action_id: str
    operation: str
    validation: str
    consequence: ConsequenceKind
    reason: str
    previous_state_hash: str
    resulting_state_hash: str
    delta: StateDelta
    resource_changes: tuple[ResourceChange, ...] = ()
    #: Facts that were not previously observable and now are, or vice versa.
    newly_observable: tuple[str, ...] = ()
    error: str = ""
    state_version: int = 0

    @property
    def applied(self) -> bool:
        return self.consequence is ConsequenceKind.STATE_CHANGED

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "operation": self.operation,
            "validation": self.validation,
            "consequence": self.consequence.value,
            "reason": self.reason,
            "previous_state_hash": self.previous_state_hash,
            "resulting_state_hash": self.resulting_state_hash,
            "delta": self.delta.to_dict(),
            "resource_changes": [c.to_dict() for c in self.resource_changes],
            "newly_observable": list(self.newly_observable),
            "error": self.error or None,
            "state_version": self.state_version,
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


def compute_delta(before: EnvironmentState, after: EnvironmentState) -> StateDelta:
    """Diff two states by observable identity, not by object comparison."""
    before_ids = set(before.entities)
    after_ids = set(after.entities)
    added = tuple(sorted(after_ids - before_ids))
    removed = tuple(sorted(before_ids - after_ids))
    changed = tuple(sorted(
        entity_id for entity_id in before_ids & after_ids
        if before.entities[entity_id].to_dict() != after.entities[entity_id].to_dict()
    ))
    return StateDelta(
        added_entities=added,
        removed_entities=removed,
        changed_entities=changed,
        from_state_version=before.state_version,
        to_state_version=after.state_version,
        from_state_hash=before.state_hash,
        to_state_hash=after.state_hash,
    )


def compute_resource_changes(before, after) -> tuple[ResourceChange, ...]:
    """Every resource that moved, with before/after/delta as measurements."""
    changes: list[ResourceChange] = []
    for resource_id in sorted(set(before.amounts) | set(after.amounts)):
        before_amount = before.amounts.get(resource_id)
        after_amount = after.amounts.get(resource_id)
        if before_amount is None or after_amount is None:
            changes.append(ResourceChange(
                resource_id=resource_id,
                before=(Measurement.observed(before_amount.value, before_amount.unit,
                                            "state")
                        if before_amount else Measurement.unavailable("absent before")),
                after=(Measurement.observed(after_amount.value, after_amount.unit,
                                           "state")
                       if after_amount else Measurement.unavailable("absent after")),
                delta=Measurement.unavailable("resource appeared or disappeared"),
            ))
            continue
        if before_amount.value == after_amount.value:
            continue
        changes.append(ResourceChange(
            resource_id=resource_id,
            before=Measurement.observed(before_amount.value, before_amount.unit, "state"),
            after=Measurement.observed(after_amount.value, after_amount.unit, "state"),
            delta=Measurement.observed(
                after_amount.value - before_amount.value, before_amount.unit,
                "after - before",
            ),
        ))
    return tuple(changes)


__all__ = [
    "ActionResult",
    "ConsequenceKind",
    "ResourceChange",
    "StateDelta",
    "compute_delta",
    "compute_resource_changes",
]
