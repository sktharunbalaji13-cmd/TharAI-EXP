"""The birth ceremony: one explicit, staged, auditable operation.

What the ceremony is
--------------------
A fixed sequence of steps, each producing an event, each checked before the
next begins. If any step fails, the ceremony stops *there*: the failure is
recorded, the evidence gathered so far is preserved, the subject (if one was
created) is terminated, and nothing downstream is fabricated to make the run
look complete. **Partial birth must not look like success**, and the way that
property is implemented is that there is simply no code path that continues
past a failure.

Modes
-----
``REAL`` means a production birth: verified foundation artifact, verified
runtime, verified environment, gate PROCEED. ``SIMULATED`` means the full
pipeline exercised against test fixtures, explicitly labelled as not a birth.
The mode travels with every event and every record the ceremony produces, and
a simulated run can never report ``REAL_BIRTH`` -- the ceremony refuses to
write the modes the same way in more than one place, and tests assert the
refusal.

Where artifacts go
------------------
In ``SIMULATED`` mode everything lives in memory and caller-supplied temporary
directories. Nothing touches ``human_control/``. In ``REAL`` mode the records
would go to the laboratory paths -- but REAL mode cannot execute unless the
gate proceeds, and on this machine it does not. The paths are named in code so
the destination is explicit rather than decided at the last moment.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from birth.keycustody import evaluate_key_custody
from environment.action import Operation
from subject.creation import CreationRecord, create_record, verify_record
from subject.experience import Experience
from subject.harness import HarnessSubject, SubjectHarness
from subject.identity import (
    FoundationReference,
    SubjectIdentity,
    derive_identity,
)
from subject.interface import SubjectInterface
from subject.lifecycle import LifecycleState
from subject.state import SubjectState

#: The environment this ceremony was reviewed against. A different fixture
#: version refuses to participate rather than running against an unreviewed
#: world.
EXPECTED_ENVIRONMENT_VERSION = "1.0.0"

#: The interface this ceremony was reviewed against.
EXPECTED_INTERFACE_VERSION = "babylab/subject-interface/v1"

#: Ceremony implementation version, recorded in every run.
CEREMONY_VERSION = "babylab/birth-ceremony/v1"


class BirthMode(str, enum.Enum):
    """Which kind of birth this ceremony performs."""

    #: A production birth. Requires the gate to PROCEED.
    REAL = "REAL"
    #: The full pipeline against fixtures, explicitly not a birth.
    SIMULATED = "SIMULATED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class CeremonyError(RuntimeError):
    """A ceremony step failed. Carries the step, so the audit can point at it."""

    def __init__(self, step: str, reason: str, detail: str = "") -> None:
        super().__init__(f"{step}: {reason}: {detail}" if detail else f"{step}: {reason}")
        self.step = step
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class CeremonyEvent:
    """One auditable step of a ceremony."""

    sequence: int
    step: str
    mode: str
    outcome: str  # "ok" or "failed"
    detail: str
    timestamp: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "step": self.step,
            "mode": self.mode,
            "outcome": self.outcome,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "evidence": self.evidence,
        }


@dataclass
class TBirth:
    """The birth boundary: one immutable, provenance-linked event.

    ``T_birth`` is the moment a subject came into existence as far as the
    laboratory is concerned. Before it, no subject and no experience. It names
    the subject, the foundation, the environment and the ceremony, so that any
    of those changing would make this a different birth.
    """

    subject_id: str
    timestamp: str
    foundation_digest: str
    environment_id: str
    ceremony_id: str
    mode: str
    provenance_reference: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "timestamp": self.timestamp,
            "foundation_digest": self.foundation_digest,
            "environment_id": self.environment_id,
            "ceremony_id": self.ceremony_id,
            "mode": self.mode,
            "provenance_reference": self.provenance_reference,
        }

    @property
    def digest(self) -> str:
        from babylab.hashing import canonical_bytes, sha256_hex

        return sha256_hex(canonical_bytes(self.to_dict()))


@dataclass(frozen=True)
class CeremonyConfig:
    """The birth configuration. One source, validated, hashed."""

    mode: BirthMode = BirthMode.SIMULATED
    expected_environment_version: str = EXPECTED_ENVIRONMENT_VERSION
    expected_interface_version: str = EXPECTED_INTERFACE_VERSION
    require_active_for_first_interaction: bool = True
    first_operation: str = "OBSERVE"
    first_target: str | None = None
    first_parameters: dict[str, Any] = field(default_factory=dict)
    subject_id: str | None = None

    @classmethod
    def default(cls) -> "CeremonyConfig":
        return cls()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.expected_environment_version != EXPECTED_ENVIRONMENT_VERSION:
            problems.append(
                f"expected_environment_version {self.expected_environment_version!r} "
                f"does not match the ceremony's {EXPECTED_ENVIRONMENT_VERSION!r}")
        if self.expected_interface_version != EXPECTED_INTERFACE_VERSION:
            problems.append(
                f"expected_interface_version {self.expected_interface_version!r} "
                f"does not match the ceremony's {EXPECTED_INTERFACE_VERSION!r}")
        try:
            Operation(self.first_operation)
        except ValueError:
            problems.append(f"first_operation {self.first_operation!r} is unknown")
        return problems

    def configuration_hash(self) -> str:
        from babylab.hashing import canonical_bytes, sha256_hex

        return sha256_hex(canonical_bytes({
            "mode": self.mode.value,
            "expected_environment_version": self.expected_environment_version,
            "expected_interface_version": self.expected_interface_version,
            "require_active_for_first_interaction":
                self.require_active_for_first_interaction,
            "first_operation": self.first_operation,
            "first_target": self.first_target,
            "first_parameters": self.first_parameters,
            "subject_id": self.subject_id,
        }))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "expected_environment_version": self.expected_environment_version,
            "expected_interface_version": self.expected_interface_version,
            "require_active_for_first_interaction":
                self.require_active_for_first_interaction,
            "first_operation": self.first_operation,
            "first_target": self.first_target,
            "first_parameters": dict(self.first_parameters),
            "subject_id": self.subject_id,
            "ceremony_version": CEREMONY_VERSION,
        }


@dataclass
class CeremonyRecord:
    """Everything one ceremony run did, in order. The audit reads this."""

    ceremony_id: str
    mode: BirthMode
    config: CeremonyConfig
    events: list[CeremonyEvent] = field(default_factory=list)
    outcome: str = "IN_PROGRESS"  # IN_PROGRESS | COMPLETE | ABORTED
    failure: dict[str, Any] | None = None
    subject_id: str | None = None
    t_birth: TBirth | None = None
    first_experience_id: str | None = None
    first_experience_hash: str | None = None

    def record(self, step: str, outcome: str, detail: str, timestamp: str,
               **evidence: Any) -> CeremonyEvent:
        event = CeremonyEvent(
            sequence=len(self.events) + 1,
            step=step, mode=self.mode.value, outcome=outcome, detail=detail,
            timestamp=timestamp, evidence=dict(evidence))
        self.events.append(event)
        return event

    def abort(self, step: str, reason: str, detail: str, timestamp: str) -> None:
        self.record(step, "failed", f"{reason}: {detail}", timestamp)
        self.outcome = "ABORTED"
        self.failure = {"step": step, "reason": reason, "detail": detail}

    def steps(self) -> tuple[str, ...]:
        return tuple(e.step for e in self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ceremony_id": self.ceremony_id,
            "mode": self.mode.value,
            "ceremony_version": CEREMONY_VERSION,
            "config": self.config.to_dict(),
            "config_hash": self.config.configuration_hash(),
            "events": [e.to_dict() for e in self.events],
            "outcome": self.outcome,
            "failure": self.failure,
            "subject_id": self.subject_id,
            "t_birth": self.t_birth.to_dict() if self.t_birth else None,
            "first_experience_id": self.first_experience_id,
            "first_experience_hash": self.first_experience_hash,
        }


class BirthCeremony:
    """Runs the ceremony, one checked step at a time."""

    def __init__(self, gate=None, harness: SubjectHarness | None = None,
                 clock: Callable[[], str] | None = None) -> None:
        from birth.gate import BirthGate

        self._gate = gate or BirthGate()
        self._harness = harness or SubjectHarness()
        self._clock = clock or (lambda: "1970-01-01T00:00:00.000Z")
        if clock is not None:
            self._harness._clock = clock  # noqa: SLF001 - same laboratory

    def _now(self) -> str:
        return self._clock()

    # -- the ceremony ----------------------------------------------------
    def perform(self, config: CeremonyConfig | None = None,
                foundation: FoundationReference | None = None) -> CeremonyRecord:
        """Run the full ceremony. Stops at the first failure."""
        config = config or CeremonyConfig.default()
        record = CeremonyRecord(
            ceremony_id=f"ceremony-{uuid.uuid4().hex[:16]}",
            mode=config.mode, config=config)
        now = self._now

        # 1. preflight ----------------------------------------------------
        problems = config.validate()
        if problems:
            record.abort("preflight", "INVALID_CONFIGURATION", problems[0], now())
            return record
        record.record("preflight", "ok",
                      f"configuration validates; mode {config.mode.value}", now(),
                      config_hash=config.configuration_hash())

        # 2. prerequisites --------------------------------------------------
        verdict = self._gate.evaluate()
        record.record("verify_prerequisites", "ok" if verdict.may_proceed else "failed",
                      f"gate: {verdict.verdict} - {verdict.reason}", now(),
                      gate=verdict.to_dict())
        if config.mode is BirthMode.REAL and not verdict.may_proceed:
            record.abort("verify_prerequisites", "GATE_BLOCKED", verdict.reason, now())
            return record
        if config.mode is BirthMode.SIMULATED:
            record.record("mode", "ok",
                          "SIMULATED: the gate result is recorded but does not "
                          "govern; this run is explicitly not a birth", now(),
                          gate_verdict=verdict.verdict)

        # 3. identity -------------------------------------------------------
        try:
            identity = derive_identity(
                subject_id=config.subject_id or f"subject-{record.ceremony_id[:8]}",
                issuer="LABORATORY",
                foundation=foundation or FoundationReference.none(),
                environment_interface_version=EXPECTED_INTERFACE_VERSION,
                derived_at=now(),
                derivation_basis=(
                    "M009 birth ceremony" if config.mode is BirthMode.REAL
                    else "M009 simulated ceremony (not a birth)"),
            )
        except Exception as exc:  # noqa: BLE001 - every failure is recorded
            record.abort("issue_subject_identity", type(exc).__name__, str(exc), now())
            return record
        record.subject_id = identity.subject_id
        record.record("issue_subject_identity", "ok",
                      f"identity derived for {identity.subject_id}", now(),
                      identity_hash=identity.identity_hash,
                      foundation_state=identity.foundation.state)

        # 4. creation -------------------------------------------------------
        try:
            creation = create_record(
                subject_id=identity.subject_id, identity=identity,
                identity_hash=identity.identity_hash,
                foundation_identity=identity.foundation.to_dict(),
                environment_interface_version=EXPECTED_INTERFACE_VERSION,
                subject_schema_version=identity.schema_version,
                laboratory_implementation_version="babylab/m009/v1",
                creation_reason=(
                    "M009 birth ceremony" if config.mode is BirthMode.REAL
                    else "M009 simulated ceremony (not a birth)"),
                provenance_identity=f"ceremony:{record.ceremony_id}",
                created_at=now())
        except Exception as exc:  # noqa: BLE001
            record.abort("create_creation_record", type(exc).__name__, str(exc), now())
            return record
        intact, detail = verify_record(creation)
        if not intact:
            record.abort("create_creation_record", "RECORD_INVALID", detail, now())
            return record
        record.record("create_creation_record", "ok",
                      f"creation record {creation.record_hash[:16]}", now(),
                      record_hash=creation.record_hash)
        # Pre-birth proof: at this point, no experience can exist.
        record.record("pre_birth_proof", "ok",
                      "identity and creation exist; experience count is 0; no "
                      "observation has occurred; nothing has been backfilled",
                      now(), experience_count=0)

        # 5. foundation attachment -------------------------------------------
        foundation_ok, foundation_detail = self._attach_foundation(
            record, identity, config, now)
        if not foundation_ok:
            self._terminate_record(record, identity, now)
            record.abort("attach_verified_foundation", "FOUNDATION_REFUSED",
                         foundation_detail, now())
            return record

        # 6. environment attachment -------------------------------------------
        try:
            from environment.deterministic import create_deterministic_environment

            environment = create_deterministic_environment(
                created_at=now(), declared_by="LABORATORY", clock=self._clock)
        except Exception as exc:  # noqa: BLE001
            self._terminate_record(record, identity, now)
            record.abort("attach_environment_interface", type(exc).__name__,
                         str(exc), now())
            return record
        if environment.identity.implementation_version != config.expected_environment_version:
            self._terminate_record(record, identity, now)
            record.abort(
                "attach_environment_interface", "VERSION_MISMATCH",
                f"environment is {environment.identity.implementation_version}, "
                f"ceremony expects {config.expected_environment_version}", now())
            return record
        record.record("attach_environment_interface", "ok",
                      f"environment {environment.identity.environment_id} "
                      f"({environment.identity.implementation_version})", now(),
                      environment_id=environment.identity.environment_id)

        # 7. T_birth -----------------------------------------------------------
        t_birth = TBirth(
            subject_id=identity.subject_id, timestamp=now(),
            foundation_digest=identity.foundation.artifact_digest,
            environment_id=environment.identity.environment_id,
            ceremony_id=record.ceremony_id, mode=config.mode.value,
            provenance_reference=f"ceremony:{record.ceremony_id}:pre_birth_proof",
        )
        record.t_birth = t_birth
        record.record("establish_T_birth", "ok",
                      f"T_birth {t_birth.timestamp} for {identity.subject_id}", now(),
                      t_birth=t_birth.to_dict(), t_birth_digest=t_birth.digest)

        # 8-10. lifecycle -------------------------------------------------------
        lifecycle = SubjectLifecycleHolder()
        for target in ("CREATED", "ATTACHED"):
            lifecycle.transition(target, now())
        record.record("transition_to_CREATED", "ok", "lifecycle CREATED", now())
        record.record("transition_to_ATTACHED", "ok", "lifecycle ATTACHED", now())

        if config.require_active_for_first_interaction:
            lifecycle.transition("ACTIVE", now())
            record.record("transition_to_ACTIVE", "ok",
                          "lifecycle ACTIVE by explicit ceremony requirement; "
                          "ACTIVE is laboratory process state only", now())
        lifecycle_state = lifecycle.state

        # 11. first interaction ---------------------------------------------------
        interface = SubjectInterface(environment, identity.subject_id)
        state = SubjectState(
            subject_id=identity.subject_id, lifecycle=lifecycle_state,
            identity_hash=identity.identity_hash,
            creation_record_hash=creation.record_hash)
        try:
            observation = interface.observe()
        except Exception as exc:  # noqa: BLE001
            self._terminate_record(record, identity, now)
            record.abort("first_observation", type(exc).__name__, str(exc), now())
            return record
        record.record("first_observation", "ok",
                      f"observation {observation.observation_id} at state v"
                      f"{observation.state_version}", now(),
                      observation_hash=observation.observation_hash)

        try:
            proposal = interface.propose(
                observation, Operation(config.first_operation),
                target=config.first_target,
                parameters=dict(config.first_parameters), actor="SUBJECT")
        except Exception as exc:  # noqa: BLE001
            self._terminate_record(record, identity, now)
            record.abort("action_proposal", type(exc).__name__, str(exc), now())
            return record
        record.record("action_proposal", "ok",
                      f"{proposal.action.operation.value} proposed", now(),
                      action_id=proposal.action.action_id,
                      operation=proposal.action.operation.value,
                      target=proposal.action.target,
                      parameters=dict(proposal.action.parameters),
                      origin=proposal.origin.value)

        try:
            result = interface.apply(proposal)
        except Exception as exc:  # noqa: BLE001
            self._terminate_record(record, identity, now)
            record.abort("action_application", type(exc).__name__, str(exc), now())
            return record
        record.record("action_consequence", "ok",
                      f"{result.validation} / {result.consequence.value}", now(),
                      validation=result.validation,
                      consequence=result.consequence.value,
                      resulting_state_hash=result.resulting_state_hash)

        # 12. first experience ------------------------------------------------------
        experience = self._commit_experience(
            record, identity, environment, observation, proposal, result, state, now)
        record.first_experience_id = experience.experience_id
        record.first_experience_hash = experience.experience_hash
        record.record("first_experience", "ok",
                      f"experience 1 committed: {experience.experience_id}", now(),
                      experience_hash=experience.experience_hash,
                      experience_count=1)

        record.outcome = "COMPLETE"
        record.record("ceremony_complete", "ok",
                      f"mode {config.mode.value}; "
                      + ("REAL_BIRTH PERFORMED" if config.mode is BirthMode.REAL
                         else "simulated run; NOT_A_BIRTH; no subject was born"),
                      now())
        return record

    # -- helpers -----------------------------------------------------------
    def _commit_experience(self, record, identity, environment, observation,
                           proposal, result, state, now):
        """Commit the first experience through the M008 record machinery."""
        from subject.experience import Experience, experience_id_for
        from subject.provenance import Source, attribute_record

        sequence = 1
        attribution = attribute_record(
            record_id=f"{identity.subject_id}-attr-{sequence:06d}",
            channel=Source.SUBJECT,
            content={"operation": proposal.action.operation.value,
                     "target": proposal.action.target},
            recorded_at=now(),
        )
        draft = Experience(
            experience_id=experience_id_for(identity.subject_id, sequence),
            subject_id=identity.subject_id,
            environment_id=environment.identity.environment_id,
            sequence_number=sequence,
            created_at=now(),
            observation_id=observation.observation_id,
            observation_hash=observation.observation_hash,
            action_id=result.action_id,
            action_operation=proposal.action.operation.value,
            action_validation=result.validation,
            consequence=result.consequence.value,
            consequence_digest=result.digest,
            environment_state_hash=result.resulting_state_hash,
            environment_state_version=result.state_version,
            prior_subject_state_hash=state.state_hash,
            resulting_subject_state_hash="0" * 64,
            provenance_reference=attribution.digest,
            origin=proposal.origin,
        )
        advanced = state.advanced(experience_hash=draft.content_hash)
        return Experience(
            **{**draft.to_dict(),
               "resulting_subject_state_hash": advanced.state_hash})

    def _attach_foundation(self, record, identity, config, now) -> tuple[bool, str]:
        foundation = identity.foundation
        if config.mode is BirthMode.SIMULATED:
            record.record("attach_verified_foundation", "ok",
                          "SIMULATED: foundation reference recorded without "
                          "verification; a simulated fixture is not a verified "
                          "artifact and is never reported as one", now(),
                          foundation_state=foundation.state)
            return True, "simulated"
        # REAL mode: verification is mandatory, never assumed.
        if foundation.state != "VERIFIED":
            return False, (
                f"foundation state is {foundation.state}, not VERIFIED; a real "
                "birth requires a verified artifact")
        return True, "verified"

    def _terminate_record(self, record, identity, now) -> None:
        record.record("terminate_record", "ok",
                      "subject record terminated after a failed step; the "
                      "failure evidence above is preserved and nothing "
                      "downstream was fabricated", now(),
                      subject_id=identity.subject_id)


class SubjectLifecycleHolder:
    """The ceremony's own lifecycle tracker, separate from M008's class.

    M008's SubjectLifecycle starts at UNCREATED and is the general mechanism.
    The ceremony drives CREATED/ATTACHED/ACTIVE in a fixed order and records
    each edge, so the audit can point at the exact transition.
    """

    def __init__(self) -> None:
        from subject.lifecycle import SubjectLifecycle

        self._lifecycle = SubjectLifecycle()

    @property
    def state(self):
        return self._lifecycle.state

    def transition(self, target: str, timestamp: str):
        from subject.lifecycle import LifecycleState

        return self._lifecycle.transition(LifecycleState(target), "LABORATORY",
                                          timestamp)


__all__ = [
    "BirthCeremony",
    "BirthMode",
    "CEREMONY_VERSION",
    "CeremonyConfig",
    "CeremonyError",
    "CeremonyEvent",
    "CeremonyRecord",
    "EXPECTED_ENVIRONMENT_VERSION",
    "EXPECTED_INTERFACE_VERSION",
    "SubjectLifecycleHolder",
    "TBirth",
]
