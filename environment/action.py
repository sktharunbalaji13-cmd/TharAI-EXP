"""The action contract and its validation outcomes.

An action is a *request*. What happened is decided by the environment, recorded
in the event stream, and returned as a result. Nothing here decides whether an
action is a good idea, only whether it is well formed and currently possible.

Validation outcomes are four distinct things, and conflating them is how an
environment ends up quietly coercing nonsense into something that works:

``ACCEPTED``   well formed and currently possible; it will be applied
``REJECTED``   well formed but not currently possible (no such target, cannot
               afford the cost, already holding something)
``INVALID``    not well formed at all (unknown operation, missing parameter,
               wrong type)
``UNAVAILABLE``cannot be determined right now, because the environment lacks
               the information to decide

``REJECTED`` and ``INVALID`` are kept apart on purpose: one is a real world
saying no, the other is a malformed request. An environment that collapses them
hides caller bugs.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any


class Operation(str, enum.Enum):
    """Operations the deterministic environment admits.

    Named for what physically happens, not for what it is for. ``INSERT`` moves
    one entity inside another; whether that is "feeding" or "charging" or
    "loading" is not recorded anywhere and is not the environment's business.
    """

    OBSERVE = "OBSERVE"
    GRASP = "GRASP"
    RELEASE = "RELEASE"
    MOVE = "MOVE"
    INSERT = "INSERT"
    REMOVE = "REMOVE"
    #: A no-op that advances the clock. Present so a caller can hold still.
    WAIT = "WAIT"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Validation(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Action:
    """One requested interaction. Carries no expectation of success."""

    operation: Operation
    actor: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    environment_id: str = ""
    request_timestamp: str = ""

    @property
    def action_id(self) -> str:
        """A stable identifier derived from the request's content.

        Content-addressed rather than random, so replaying the same request
        yields the same id and a duplicate can be detected by identity rather
        than by a counter that would drift between runs.
        """
        from babylab.hashing import canonical_bytes, sha256_hex

        return "act-" + sha256_hex(canonical_bytes({
            "operation": self.operation.value,
            "actor": self.actor,
            "target": self.target,
            "parameters": self.parameters,
            "environment_id": self.environment_id,
        }))[:20]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "operation": self.operation.value,
            "actor": self.actor,
            "target": self.target,
            "parameters": self.parameters,
            "environment_id": self.environment_id,
            "request_timestamp": self.request_timestamp,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Action":
        return cls(
            operation=Operation(payload["operation"]),
            actor=payload["actor"],
            target=payload.get("target"),
            parameters=dict(payload.get("parameters", {})),
            environment_id=payload.get("environment_id", ""),
            request_timestamp=payload.get("request_timestamp", ""),
        )


@dataclass(frozen=True)
class ValidationOutcome:
    """The environment's verdict on a request, with the reason it gave."""

    validation: Validation
    reason: str
    #: What the environment would need in order to decide, when UNAVAILABLE.
    missing_information: tuple[str, ...] = ()

    def __property__(self):  # pragma: no cover - alias for readability
        return self.validation

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation": self.validation.value,
            "reason": self.reason,
            "missing_information": list(self.missing_information),
        }


def new_action_id() -> str:  # pragma: no cover - retained for callers needing one
    return f"act-{uuid.uuid4().hex[:16]}"


__all__ = [
    "Action",
    "Operation",
    "Validation",
    "ValidationOutcome",
    "new_action_id",
]
