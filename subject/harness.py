"""The deterministic test harness: laboratory-driven subject interaction.

What the harness is
-------------------
The only thing in M008 that creates subjects. It exists so the architecture can
be exercised without birth, and every interaction it performs is an explicit,
single call. There is no loop, no scheduler, and no background process: a test
calls ``interact_once`` exactly as many times as it wants interactions, and the
count is visible in the test.

What the harness is not
------------------------
It is not an autonomous runtime, and it must never become one. The difference
is structural: ``interact_once`` performs exactly one observation, one proposal
and one application, and returns. A method that called it repeatedly would be an
agent loop, and writing one is outside this milestone. A test asserts the method
does not exist.

Where test subjects live
------------------------
In memory and in caller-supplied temporary directories. Never in
``human_control/``. A harness subject is not registered in the real session
registry and never touches the real keyring, so the observer cannot see it as
attached -- which is the entire point, because a test subject is not the Baby.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from environment.action import Action, Operation
from environment.consequence import ActionResult
from environment.deterministic import create_deterministic_environment
from subject.creation import CreationRecord, create_record
from subject.experience import Experience, experience_id_for
from subject.identity import (
    FoundationReference,
    SubjectIdentity,
    derive_identity,
)
from subject.interface import INTERFACE_VERSION, Proposal, SubjectInterface
from subject.lifecycle import LifecycleState, SubjectLifecycle
from subject.provenance import Source, attribute_record
from subject.state import SubjectState

#: Laboratory implementation version reported in creation records.
LABORATORY_VERSION = "babylab/m008/v1"

#: What the harness writes as its creation reason. A fixture label, not a birth.
HARNESS_REASON = "deterministic test harness subject (M008, not a birth)"


@dataclass
class HarnessSubject:
    """A subject record under laboratory control, for tests only."""

    identity: SubjectIdentity
    creation: CreationRecord
    lifecycle: SubjectLifecycle
    state: SubjectState
    experiences: list[Experience] = field(default_factory=list)
    attributions: list[Any] = field(default_factory=list)

    @property
    def subject_id(self) -> str:
        return self.identity.subject_id

    @property
    def experience_count(self) -> int:
        return len(self.experiences)


class SubjectHarness:
    """Creates test subjects and drives explicit single interactions."""

    def __init__(self, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock or (lambda: "1970-01-01T00:00:00.000Z")
        self._counter = 0

    def create_subject(
        self,
        *,
        subject_id: str | None = None,
        environment_id: str | None = None,
        foundation: FoundationReference | None = None,
        completion_fn=None,
    ) -> tuple[HarnessSubject, Any, SubjectInterface]:
        """Create a test subject: identity, record, zero experiences.

        The returned environment is the M007 deterministic fixture. Nothing is
        registered, nothing is persisted, and the experience count is zero --
        asserted here, so a subject that appeared with history would fail at
        creation rather than somewhere downstream.
        """
        self._counter += 1
        identity = derive_identity(
            subject_id=subject_id or f"test-subject-{self._counter:04d}",
            issuer="LABORATORY",
            foundation=foundation or FoundationReference.none(),
            environment_interface_version=INTERFACE_VERSION,
            derived_at=self._clock(),
            derivation_basis=HARNESS_REASON,
        )
        creation = create_record(
            subject_id=identity.subject_id,
            identity=identity,
            identity_hash=identity.identity_hash,
            foundation_identity=identity.foundation.to_dict(),
            environment_interface_version=INTERFACE_VERSION,
            subject_schema_version=identity.schema_version,
            laboratory_implementation_version=LABORATORY_VERSION,
            creation_reason=HARNESS_REASON,
            provenance_identity="harness",
            created_at=self._clock(),
        )
        lifecycle = SubjectLifecycle()
        lifecycle.transition(LifecycleState.CREATED, "LABORATORY", self._clock())
        state = SubjectState(
            subject_id=identity.subject_id,
            lifecycle=LifecycleState.CREATED,
            identity_hash=identity.identity_hash,
            creation_record_hash=creation.record_hash,
        )
        environment = create_deterministic_environment(
            created_at=self._clock(), declared_by="LABORATORY", clock=self._clock,
            environment_id=environment_id)
        interface = SubjectInterface(
            environment, identity.subject_id, completion_fn=completion_fn)

        subject = HarnessSubject(
            identity=identity, creation=creation, lifecycle=lifecycle, state=state)
        assert subject.experience_count == 0, "a new subject has no experiences"
        return subject, environment, interface

    def attach(self, subject: HarnessSubject) -> HarnessSubject:
        subject.lifecycle.transition(
            LifecycleState.ATTACHED, "LABORATORY", self._clock())
        subject.state = SubjectState(
            **{**subject.state.to_dict(), "lifecycle": LifecycleState.ATTACHED})
        return subject

    def activate(self, subject: HarnessSubject) -> HarnessSubject:
        subject.lifecycle.transition(
            LifecycleState.ACTIVE, "LABORATORY", self._clock())
        subject.state = SubjectState(
            **{**subject.state.to_dict(), "lifecycle": LifecycleState.ACTIVE})
        return subject

    def interact_once(
        self,
        subject: HarnessSubject,
        environment,
        interface: SubjectInterface,
        operation: Operation,
        target: str | None = None,
        parameters: dict[str, Any] | None = None,
        actor: str = "SUBJECT",
    ) -> tuple[Experience, ActionResult, Proposal]:
        """One interaction: observe, propose, apply, record. Exactly one.

        Refuses to run for a subject that is not ACTIVE, because an interaction
        with a subject in any other state would be the harness deciding on its
        own that the subject was ready.
        """
        if not subject.lifecycle.is_interactive():
            raise RuntimeError(
                f"subject is {subject.lifecycle.state.value}, not ACTIVE; "
                "the harness does not activate subjects on its own")

        observation = interface.observe()
        proposal = interface.propose(
            observation, operation, target=target,
            parameters=parameters, actor=actor)
        result = interface.apply(proposal)

        sequence = subject.experience_count + 1
        attribution = attribute_record(
            record_id=f"{subject.subject_id}-attr-{sequence:06d}",
            channel=Source.SUBJECT,
            content={"operation": proposal.action.operation.value,
                     "target": proposal.action.target},
            recorded_at=self._clock(),
        )
        prior_hash = subject.state.state_hash
        # The content hash is computable before the state exists; the full
        # record hash needs the state it lands in. So: build the record with a
        # placeholder linkage, take its content hash, advance the state with
        # that as the head, then fill in the linkage. One version bump, and the
        # head names content that actually exists.
        draft = Experience(
            experience_id=experience_id_for(subject.subject_id, sequence),
            subject_id=subject.subject_id,
            environment_id=environment.identity.environment_id,
            sequence_number=sequence,
            created_at=self._clock(),
            observation_id=observation.observation_id,
            observation_hash=observation.observation_hash,
            action_id=result.action_id,
            action_operation=proposal.action.operation.value,
            action_validation=result.validation,
            consequence=result.consequence.value,
            consequence_digest=result.digest,
            environment_state_hash=result.resulting_state_hash,
            environment_state_version=result.state_version,
            prior_subject_state_hash=prior_hash,
            resulting_subject_state_hash="0" * 64,
            provenance_reference=attribution.digest,
            origin=proposal.origin,
        )
        advanced = subject.state.advanced(experience_hash=draft.content_hash)
        experience = Experience(
            **{**draft.to_dict(),
               "resulting_subject_state_hash": advanced.state_hash})
        subject.state = advanced
        subject.experiences.append(experience)
        subject.attributions.append(attribution)
        return experience, result, proposal

    # -- replay ----------------------------------------------------------
    def replay_interactions(
        self,
        subject: HarnessSubject,
        environment,
        interface: SubjectInterface,
        plan: list[tuple[Operation, str | None, dict[str, Any] | None]],
    ) -> list[Experience]:
        """Replay is explicit repetition by the caller, not a loop that decides.

        The caller supplies the plan; the harness performs it one interaction at
        a time. It still returns after each list is exhausted.
        """
        produced: list[Experience] = []
        for operation, target, parameters in plan:
            experience, _, _ = self.interact_once(
                subject, environment, interface, operation,
                target=target, parameters=parameters)
            produced.append(experience)
        return produced

    def expected_hashes(self, experiences: list[Experience]) -> dict[str, str]:
        return {e.experience_id: e.resulting_subject_state_hash for e in experiences}


__all__ = ["HARNESS_REASON", "HarnessSubject", "LABORATORY_VERSION", "SubjectHarness"]
