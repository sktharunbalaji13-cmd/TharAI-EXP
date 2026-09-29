"""The environment: the thing a future subject will eventually act within.

What this is
------------
Infrastructure. It exists on its own, with no model, no subject, no memory, no
goals and no autonomy. It waits for an explicit action, decides whether it is
possible, applies it, and records what happened. It never acts first.

The flow every action takes
---------------------------
::

    submit action
        -> action_requested event
        -> validate      (ACCEPTED / REJECTED / INVALID / UNAVAILABLE)
        -> action_validated or action_rejected event
        -> if accepted: apply, then state_transitioned + resource_changed events
        -> action_applied event with the full result
        -> return ActionResult

A rejected or invalid action produces a result and an event but **no state
change**. That is enforced by construction: the state object is immutable and is
only replaced on the accepted path, so there is no code path in which a bad
action can mutate anything.

Determinism
-----------
The state carries no timestamp and no float, so the same action sequence from
the same initial state produces the same ``state_hash``. Timestamps appear in
events and results, where they belong. That is what makes
:func:`Environment.replay` a real check rather than a tautology.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

from environment.action import Action, Operation, Validation, ValidationOutcome
from environment.consequence import (
    ActionResult,
    ConsequenceKind,
    compute_delta,
    compute_resource_changes,
)
from environment.events import ENVIRONMENT_SOURCE, EventStream, EventType
from environment.identity import EnvironmentIdentity, derive_identity
from environment.observation import Observation, build_observation
from environment.snapshot import Branch, Snapshot, take_snapshot
from environment.state import (
    UNIT_COUNT,
    UNIT_TICKS,
    Entity,
    EnvironmentState,
    ResourceAmount,
    ResourceState,
)


def _request_payload(action: Action, action_id: str) -> dict[str, Any]:
    """What the environment records about a request.

    Deliberately **not** the caller's raw ``parameters`` -- neither the values nor
    the key names. An actor can put anything in there, and copying it verbatim
    would let a caller write ``{"author": "BABY_AI", "i_wrote_this": true}`` into
    an append-only log that is supposed to record what the *environment* did.
    Even the parameter names are caller-supplied text, so only a count and a
    digest are recorded here; the parameters the environment actually
    interpreted are recorded separately by :func:`_interpreted_parameters`.

    The event log therefore describes environment facts. What a caller said about
    itself does not become a fact by being written down.
    """
    from babylab.hashing import canonical_bytes, sha256_hex

    return {
        "action_id": action_id,
        "operation": action.operation.value,
        "actor": action.actor,
        "target": action.target,
        # A count and a digest, never the caller's keys or values. Even the
        # parameter *names* are caller-supplied text, so recording them would let
        # a request smuggle a claim such as "i_wrote_this" into an append-only
        # log. The digest still correlates a request with a replay.
        "parameter_count": len(action.parameters),
        "parameters_digest": sha256_hex(canonical_bytes(action.parameters)),
    }


def _interpreted_parameters(action: Action) -> dict[str, Any]:
    """Only the parameters the environment actually acted on.

    These are the environment's own readings of the request, not the caller's
    free-form input, so recording them is recording a fact rather than an echo.
    """
    keys = ("x", "y", "entity_id")
    return {k: action.parameters[k] for k in keys if k in action.parameters}


class EnvironmentFault(RuntimeError):
    """A fault raised by the environment itself, distinct from a bad request."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass
class Environment:
    """One environment instance with its own state, history and branches."""

    identity: EnvironmentIdentity
    state: EnvironmentState
    events: EventStream
    branches: dict[str, Branch] = field(default_factory=dict)
    snapshots: dict[str, Snapshot] = field(default_factory=dict)
    current_branch_id: str = "main"
    _clock: Callable[[], str] = lambda: "1970-01-01T00:00:00.000Z"

    # -- construction ----------------------------------------------------
    @classmethod
    def create(
        cls,
        config: dict[str, Any],
        state: EnvironmentState,
        created_at: str,
        declared_by: str = "LABORATORY",
        environment_id: str | None = None,
        clock: Callable[[], str] | None = None,
    ) -> "Environment":
        """Build an environment whose identity is derived from outside it."""
        identity = derive_identity(config, created_at, declared_by, environment_id)
        environment = cls(
            identity=identity,
            state=state,
            events=EventStream(identity.environment_id),
            _clock=clock or (lambda: created_at),
        )
        environment.branches["main"] = Branch(
            branch_id="main", parent_branch_id=None, root_snapshot_id=None,
            created_at=created_at,
        )
        environment.events.append(
            EventType.ENVIRONMENT_CREATED,
            timestamp=created_at,
            state_version=state.state_version,
            state_hash=state.state_hash,
            payload={
                "environment_type": identity.environment_type,
                "implementation_version": identity.implementation_version,
                "configuration_hash": identity.configuration_hash,
                "declared_by": declared_by,
            },
        )
        return environment

    # -- observation -----------------------------------------------------
    def observe(self) -> Observation:
        """Expose the current state. Read-only."""
        visible = tuple(
            event.event_id for event in self.events.events()
            if event.state_version == self.state.state_version
        )
        observation = build_observation(
            self.identity.environment_id, self.state, self._clock(), visible
        )
        self.events.append(
            EventType.OBSERVATION_GENERATED,
            timestamp=self._clock(),
            state_version=self.state.state_version,
            state_hash=self.state.state_hash,
            # The observation is referenced by hash, not stored inline, so the
            # event log stays a log rather than becoming a data store.
            payload={
                "observation_id": observation.observation_id,
                "observation_hash": observation.observation_hash,
                "entity_count": len(observation.entities),
            },
        )
        return observation

    # -- action ----------------------------------------------------------
    def submit(self, action: Action) -> ActionResult:
        """Validate, apply, and record one action. Never acts unprompted."""
        action = replace(
            action, environment_id=self.identity.environment_id,
            request_timestamp=action.request_timestamp or self._clock(),
        )
        action_id = action.action_id
        before = self.state

        self.events.append(
            EventType.ACTION_REQUESTED,
            timestamp=self._clock(),
            state_version=before.state_version,
            state_hash=before.state_hash,
            payload=_request_payload(action, action_id),
        )

        outcome = self._validate(action)
        if outcome.validation is not Validation.ACCEPTED:
            self.events.append(
                EventType.ACTION_REJECTED,
                timestamp=self._clock(),
                state_version=before.state_version,
                state_hash=before.state_hash,
                payload={
                    "action_id": action_id,
                    "validation": outcome.validation.value,
                    "reason": outcome.reason,
                },
            )
            return ActionResult(
                action_id=action_id,
                operation=action.operation.value,
                validation=outcome.validation.value,
                consequence=ConsequenceKind.NOT_APPLIED,
                reason=outcome.reason,
                previous_state_hash=before.state_hash,
                resulting_state_hash=before.state_hash,
                delta=compute_delta(before, before),
                state_version=before.state_version,
                error=outcome.reason,
            )

        self.events.append(
            EventType.ACTION_VALIDATED,
            timestamp=self._clock(),
            state_version=before.state_version,
            state_hash=before.state_hash,
            payload={"action_id": action_id, "validation": outcome.validation.value},
        )

        after, consequence, resource_changes, newly_observable = self._apply(action)
        delta = compute_delta(before, after)
        kind = ConsequenceKind.STATE_CHANGED if not delta.is_empty or resource_changes \
            else ConsequenceKind.NO_EFFECT

        if after is not before:
            self.state = after

        result = ActionResult(
            action_id=action_id,
            operation=action.operation.value,
            validation=outcome.validation.value,
            consequence=kind,
            reason=outcome.reason,
            previous_state_hash=before.state_hash,
            resulting_state_hash=self.state.state_hash,
            delta=delta,
            resource_changes=resource_changes,
            newly_observable=newly_observable,
            state_version=self.state.state_version,
        )

        for change in resource_changes:
            self.events.append(
                EventType.RESOURCE_CHANGED,
                timestamp=self._clock(),
                state_version=self.state.state_version,
                state_hash=self.state.state_hash,
                payload={"action_id": action_id, **change.to_dict()},
            )
        if not delta.is_empty:
            self.events.append(
                EventType.STATE_TRANSITIONED,
                timestamp=self._clock(),
                state_version=self.state.state_version,
                state_hash=self.state.state_hash,
                payload={"action_id": action_id, "delta": delta.to_dict(),
                         "delta_digest": delta.digest,
                         "interpreted": _interpreted_parameters(action)},
            )
        self.events.append(
            EventType.ACTION_APPLIED,
            timestamp=self._clock(),
            state_version=self.state.state_version,
            state_hash=self.state.state_hash,
            payload={
                "action_id": action_id,
                "consequence": kind.value,
                "resulting_state_hash": self.state.state_hash,
                "result_digest": result.digest,
            },
        )
        return result

    # -- validation ------------------------------------------------------
    def _validate(self, action: Action) -> ValidationOutcome:
        """Decide whether an action is well formed and currently possible.

        ``INVALID`` and ``REJECTED`` are kept distinct. ``REJECTED`` means the
        world said no; ``INVALID`` means the request was malformed. Collapsing
        them would hide caller bugs behind a plausible-sounding refusal.
        """
        if action.operation is Operation.OBSERVE:
            return ValidationOutcome(Validation.ACCEPTED, "observation has no cost")

        if not action.actor:
            return ValidationOutcome(Validation.INVALID, "action has no actor")

        # Cost is checked before any operation-specific shortcut, so that WAIT
        # cannot bypass it. An earlier version returned ACCEPTED for WAIT
        # immediately, which let an exhausted clock be drained to -390: the
        # action was valid in form and impossible in the world, and only the
        # second check noticed.
        cost = self._cost_of(action)
        for resource_id, amount in cost.items():
            available = self.state.resources.get(resource_id)
            if available is None:
                return ValidationOutcome(
                    Validation.UNAVAILABLE,
                    f"resource {resource_id!r} is not modelled in this "
                    "environment, so the cost of this action cannot be determined",
                    missing_information=(resource_id,),
                )
            if available < amount:
                return ValidationOutcome(
                    Validation.REJECTED,
                    f"action requires {amount} {resource_id} but only "
                    f"{available} is available",
                )

        if action.operation is Operation.WAIT:
            return ValidationOutcome(Validation.ACCEPTED, "waiting is currently possible")

        if action.target is None:
            return ValidationOutcome(
                Validation.INVALID, f"{action.operation.value} requires a target")

        entity = self.state.entity(action.target)
        if entity is None:
            return ValidationOutcome(
                Validation.REJECTED,
                f"no entity {action.target!r} exists in this environment",
            )

        supported = entity.supported_operations()
        if action.operation.value not in supported:
            return ValidationOutcome(
                Validation.REJECTED,
                f"entity {action.target!r} does not currently admit "
                f"{action.operation.value}; it admits "
                f"{', '.join(supported) or '(nothing)'}",
            )

        if action.operation is Operation.MOVE:
            x = action.parameters.get("x")
            y = action.parameters.get("y")
            if not isinstance(x, int) or not isinstance(y, int):
                return ValidationOutcome(
                    Validation.INVALID, "MOVE requires integer 'x' and 'y'")
            if not (0 <= x < self.state.grid_width and 0 <= y < self.state.grid_height):
                return ValidationOutcome(
                    Validation.REJECTED,
                    f"({x}, {y}) is outside the {self.state.grid_width}x"
                    f"{self.state.grid_height} grid",
                )

        if action.operation is Operation.INSERT:
            child = action.parameters.get("entity_id")
            if not isinstance(child, str):
                return ValidationOutcome(
                    Validation.INVALID, "INSERT requires a string 'entity_id'")
            if child not in self.state.entities:
                return ValidationOutcome(
                    Validation.REJECTED, f"no entity {child!r} exists")
            if child == action.target:
                return ValidationOutcome(
                    Validation.REJECTED, "an entity cannot be inserted into itself")
            if child in self.state.entity(action.target).contents:
                return ValidationOutcome(
                    Validation.REJECTED, f"{child!r} is already inside {action.target!r}")

        if action.operation is Operation.REMOVE:
            child = action.parameters.get("entity_id")
            if not isinstance(child, str):
                return ValidationOutcome(
                    Validation.INVALID, "REMOVE requires a string 'entity_id'")
            if child not in self.state.entity(action.target).contents:
                return ValidationOutcome(
                    Validation.REJECTED, f"{child!r} is not inside {action.target!r}")

        return ValidationOutcome(Validation.ACCEPTED, "action is currently possible")

    def _cost_of(self, action: Action) -> dict[str, int]:
        """What an action costs, in resources. Facts, not a difficulty score.

        Costs are what must be *available* for the action to be accepted. Refunds
        are handled separately by :meth:`_resource_delta`, so a signed number
        never has to mean both "must have" and "gives back".
        """
        if action.operation is Operation.OBSERVE:
            return {}
        if action.operation is Operation.WAIT:
            return {"time": 1}
        if action.operation is Operation.GRASP:
            return {"energy": 1, "time": 1, "capacity": 1}
        if action.operation is Operation.RELEASE:
            return {"energy": 1, "time": 1}
        if action.operation is Operation.MOVE:
            return {"energy": 2, "time": 1}
        if action.operation is Operation.INSERT:
            return {"energy": 2, "time": 1}
        if action.operation is Operation.REMOVE:
            return {"energy": 2, "time": 1}
        return {}

    def _resource_delta(self, action: Action) -> dict[str, int]:
        """Signed resource movement actually applied on success."""
        delta = {resource_id: -amount
                 for resource_id, amount in self._cost_of(action).items()}
        if action.operation is Operation.RELEASE:
            # Letting go returns the holding slot. Modelled explicitly rather
            # than by inverting the cost, so the meaning stays readable.
            delta["capacity"] = 1
        return delta

    # -- application -----------------------------------------------------
    def _apply(self, action: Action) -> tuple[EnvironmentState, str,
                                               tuple, tuple[str, ...]]:
        """Apply an accepted action. The only place state is replaced."""
        delta = self._resource_delta(action)
        new_state = self.state
        if delta:
            resources = new_state.resources
            for resource_id, amount in delta.items():
                resources = resources.with_value(
                    resource_id, resources.get(resource_id) + amount)
            new_state = new_state.with_resources(resources)

        newly: list[str] = []
        operation = action.operation
        target = self.state.entity(action.target) if action.target else None

        if operation is Operation.GRASP and target is not None:
            new_state = new_state.with_entity(replace(target, held_by=action.actor))
            newly.append(f"{action.target}.held_by")

        elif operation is Operation.RELEASE and target is not None:
            new_state = new_state.with_entity(replace(target, held_by=None))
            newly.append(f"{action.target}.held_by")

        elif operation is Operation.MOVE and target is not None:
            x, y = action.parameters["x"], action.parameters["y"]
            new_state = new_state.with_entity(replace(target, location=(x, y)))
            newly.append(f"{action.target}.location")

        elif operation is Operation.INSERT and target is not None:
            child_id = action.parameters["entity_id"]
            child = self.state.entity(child_id)
            contents = list(target.contents) + [child_id]
            new_state = new_state.with_entity(replace(
                target, observable={**target.observable, "contents": contents}))
            new_state = new_state.with_entity(replace(child, held_by=target.entity_id))
            newly.extend([f"{action.target}.contents", f"{child_id}.held_by"])

        elif operation is Operation.REMOVE and target is not None:
            child_id = action.parameters["entity_id"]
            child = self.state.entity(child_id)
            contents = [c for c in target.contents if c != child_id]
            new_state = new_state.with_entity(replace(
                target, observable={**target.observable, "contents": contents}))
            new_state = new_state.with_entity(replace(child, held_by=None))
            newly.extend([f"{action.target}.contents", f"{child_id}.held_by"])

        elif operation in (Operation.OBSERVE, Operation.WAIT):
            pass  # deliberate no-op; WAIT already advanced `time` above

        resource_changes = compute_resource_changes(self.state.resources, new_state.resources)
        return new_state, "applied", resource_changes, tuple(newly)

    def _held_by_actor(self, actor: str) -> Entity | None:
        for entity in self.state.entities.values():
            if entity.held_by == actor:
                return entity
        return None

    # -- snapshots and branching -----------------------------------------
    def snapshot(self, label: str = "") -> Snapshot:
        """Capture the current state as a verified snapshot."""
        snapshot = take_snapshot(
            self.identity, self.state, self._clock(),
            parent_snapshot_id=None, branch_id=self.current_branch_id, label=label,
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        self.events.append(
            EventType.SNAPSHOT_CREATED,
            timestamp=self._clock(),
            state_version=self.state.state_version,
            state_hash=self.state.state_hash,
            payload={
                "snapshot_id": snapshot.snapshot_id,
                "state_hash": snapshot.state_hash,
                "snapshot_digest": snapshot.digest(),
                "branch_id": snapshot.branch_id,
                "label": label,
            },
        )
        return snapshot

    def restore(self, snapshot_id: str) -> "Environment":
        """Restore into a **new branch**. History is never rewound.

        Refuses a corrupt snapshot rather than loading a state that never
        existed, and refuses one whose configuration does not match this
        environment.
        """
        snapshot = self.snapshots.get(snapshot_id)
        if snapshot is None:
            raise EnvironmentFault("UNKNOWN_SNAPSHOT",
                                   f"no snapshot {snapshot_id!r} in this environment")

        intact, detail = snapshot.verify()
        if not intact:
            self._record_fault("CORRUPT_SNAPSHOT", detail)
            raise EnvironmentFault("CORRUPT_SNAPSHOT", detail)

        if snapshot.configuration_hash != self.identity.configuration_hash:
            detail = (
                f"snapshot configuration {snapshot.configuration_hash[:12]} does "
                f"not match this environment "
                f"{self.identity.configuration_hash[:12]}"
            )
            self._record_fault("CONFIGURATION_MISMATCH", detail)
            raise EnvironmentFault("CONFIGURATION_MISMATCH", detail)

        if snapshot.implementation_version != self.identity.implementation_version:
            detail = (
                f"snapshot was taken by implementation "
                f"{snapshot.implementation_version!r}, this environment is "
                f"{self.identity.implementation_version!r}"
            )
            self._record_fault("VERSION_MISMATCH", detail)
            raise EnvironmentFault("VERSION_MISMATCH", detail)

        branch_id = f"branch-{len(self.branches) + 1}"
        self.branches[branch_id] = Branch(
            branch_id=branch_id,
            parent_branch_id=self.current_branch_id,
            root_snapshot_id=snapshot_id,
            created_at=self._clock(),
            state_version=snapshot.state_version,
        )
        previous_branch = self.current_branch_id
        self.current_branch_id = branch_id
        self.events.set_branch(branch_id)
        self.state = EnvironmentState.from_dict(snapshot.state)

        self.events.append(
            EventType.SNAPSHOT_RESTORED,
            timestamp=self._clock(),
            state_version=self.state.state_version,
            state_hash=self.state.state_hash,
            payload={
                "snapshot_id": snapshot_id,
                "branch_id": branch_id,
                "parent_branch_id": previous_branch,
                "state_hash": snapshot.state_hash,
            },
        )
        return self

    def branch_lineage(self, branch_id: str) -> tuple[str, ...]:
        """Branch ids from the root to ``branch_id``."""
        return self.branches[branch_id].lineage(self.branches)

    # -- replay ----------------------------------------------------------
    def replay(
        self,
        actions: Iterable[Action],
        expected: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Apply a recorded action sequence and report whether it diverged.

        ``expected`` maps ``action_id`` to the ``resulting_state_hash`` the same
        action produced on an earlier run. Divergence is reported, never hidden:
        the result names the first action whose resulting state hash differs and
        carries both hashes.

        A replay that quietly matched a *different* sequence would be worse than
        one that failed loudly, so a mismatch stops the replay and is reported
        rather than papered over.
        """
        expected = expected or {}
        applied: list[ActionResult] = []
        divergence: dict[str, Any] | None = None
        for action in actions:
            result = self.submit(action)
            applied.append(result)
            # Look the expectation up by the id `submit` actually produced.
            # Computing it here from the raw request would omit the environment
            # id that `submit` attaches, so the key would never match and
            # divergence detection would be dead code that always reported
            # success.
            recorded = expected.get(result.action_id)
            if recorded is not None and recorded != result.resulting_state_hash:
                divergence = {
                    "action_id": result.action_id,
                    "operation": result.operation,
                    "expected_state_hash": recorded,
                    "actual_state_hash": result.resulting_state_hash,
                }
                break
        return {
            "actions_applied": len(applied),
            "actions_in_sequence": len(applied),
            "final_state_hash": self.state.state_hash,
            "final_state_version": self.state.state_version,
            "diverged": divergence is not None,
            "divergence": divergence,
            "chain_intact": self.events.verify().intact,
        }

    def expectations_from(self, results: Iterable[ActionResult]) -> dict[str, str]:
        """Build the ``expected`` map from a previous run's results."""
        return {r.action_id: r.resulting_state_hash for r in results}

    def _record_fault(self, kind: str, detail: str) -> None:
        """Faults are events. A failure is never silent."""
        self.events.append(
            EventType.ENVIRONMENT_FAULT,
            timestamp=self._clock(),
            state_version=self.state.state_version,
            state_hash=self.state.state_hash,
            payload={"kind": kind, "detail": detail},
        )

    def inject_fault(self, kind: str, detail: str) -> None:
        """Record a fault deliberately. Used by fault-injection tests."""
        self._record_fault(kind, detail)

    # -- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "environment": self.identity.to_dict(),
            "state_version": self.state.state_version,
            "state_hash": self.state.state_hash,
            "event_count": len(self.events),
            "chain_intact": self.events.verify().intact,
            "current_branch_id": self.current_branch_id,
            "branches": sorted(self.branches),
            "snapshots": sorted(self.snapshots),
            "resources": self.state.resources.to_dict(),
            "autonomous": False,
            "memory": False,
            "subject_attached": False,
        }


__all__ = ["Environment", "EnvironmentFault"]
