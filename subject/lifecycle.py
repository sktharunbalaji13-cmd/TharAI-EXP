"""Subject lifecycle: laboratory process state, and nothing more.

What the lifecycle is not
-------------------------
A lifecycle transition says what the *laboratory* has done with a subject
record. It says nothing about awareness, experience, intelligence, aliveness,
or consciousness. ``ACTIVE`` means "the laboratory has attached this record to
an interaction harness". Rendering any transition as a mental event would be
inventing data, so the states carry exactly the operational semantics written
below and no others.

No automatic ACTIVE
-------------------
A subject that exists is not automatically active. ``CREATED`` means the record
exists; ``ATTACHED`` means it has been bound to an environment interface;
``ACTIVE`` requires an explicit laboratory operation *after* attachment. The
reason is structural: if creating a subject implied activity, there would be no
way to hold a subject still while examining it, and a subject that cannot be
held still cannot be studied safely.
"""

from __future__ import annotations

import enum


class LifecycleState(str, enum.Enum):
    """Process states a subject record may occupy."""

    #: No record. The initial state of every subject that does not exist.
    UNCREATED = "UNCREATED"
    #: A creation record exists. The subject does nothing.
    CREATED = "CREATED"
    #: Bound to an environment interface. Still does nothing.
    ATTACHED = "ATTACHED"
    #: Laboratory process state only: attached *and* explicitly activated by the
    #: laboratory. Says nothing about awareness of any kind.
    ACTIVE = "ACTIVE"
    #: Suspended by the laboratory. Interactions are refused until reactivation.
    PAUSED = "PAUSED"
    #: Terminal. No further transition is possible from here.
    TERMINATED = "TERMINATED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: The complete transition graph. Absent edges are refused, and a refusal is
#: recorded rather than silently accepted.
ALLOWED_TRANSITIONS: dict[LifecycleState, tuple[LifecycleState, ...]] = {
    LifecycleState.UNCREATED: (LifecycleState.CREATED,),
    LifecycleState.CREATED: (LifecycleState.ATTACHED, LifecycleState.TERMINATED),
    LifecycleState.ATTACHED: (LifecycleState.ACTIVE, LifecycleState.TERMINATED),
    LifecycleState.ACTIVE: (LifecycleState.PAUSED, LifecycleState.TERMINATED),
    LifecycleState.PAUSED: (LifecycleState.ACTIVE, LifecycleState.TERMINATED),
    LifecycleState.TERMINATED: (),
}


class LifecycleError(RuntimeError):
    """An invalid or unauthorized lifecycle operation."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class SubjectLifecycle:
    """The lifecycle of one subject record, held by the laboratory, not the subject.

    Transitions are requested with an explicit ``authorized_by`` of
    ``"LABORATORY"``. The subject has no method and no path to request its own
    transition; there is no ``subject.request_activation`` because the concept
    does not exist at this layer.
    """

    def __init__(self, initial: LifecycleState = LifecycleState.UNCREATED) -> None:
        self._state = initial
        self._history: list[tuple[LifecycleState, LifecycleState, str]] = []

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def history(self) -> tuple[tuple[LifecycleState, LifecycleState, str], ...]:
        return tuple(self._history)

    def can_transition(self, target: LifecycleState) -> bool:
        return target in ALLOWED_TRANSITIONS[self._state]

    def transition(self, target: LifecycleState, authorized_by: str,
                   timestamp: str) -> LifecycleState:
        """Move to ``target``. Authorization is laboratory-only."""
        if authorized_by != "LABORATORY":
            raise LifecycleError(
                "UNAUTHORIZED_TRANSITION",
                f"lifecycle transitions require laboratory authorization; "
                f"got {authorized_by!r}",
            )
        if not self.can_transition(target):
            raise LifecycleError(
                "INVALID_TRANSITION",
                f"{self._state.value} -> {target.value} is not a permitted "
                "lifecycle transition",
            )
        previous = self._state
        self._state = target
        self._history.append((previous, target, timestamp))
        return self._state

    def is_interactive(self) -> bool:
        """Whether this record may currently take part in interactions."""
        return self._state is LifecycleState.ACTIVE

    def is_terminal(self) -> bool:
        return self._state is LifecycleState.TERMINATED


__all__ = [
    "ALLOWED_TRANSITIONS",
    "LifecycleError",
    "LifecycleState",
    "SubjectLifecycle",
]
