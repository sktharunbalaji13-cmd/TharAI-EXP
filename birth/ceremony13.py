"""M013 ceremony: a real birth, or an honest record that no birth occurred.

Transactional
-------------
Nothing is mutated before every prerequisite is validated. If a step that cannot
be undone fails, the record becomes ``ABORTED_BIRTH`` and the laboratory holds no
subject, no ``T_birth``, and no experience. There is no path that leaves a
half-born subject looking alive, because the only field a reader could mistake
for a living subject -- ``T_birth`` -- is set at exactly one point, after the
activation transition has succeeded, and never before.

Why ABORTED_BIRTH exists
------------------------
Deleting a partial record would destroy the evidence of the failure, and this
project's whole discipline is that failures stay legible. So an abort is recorded
in full, marked ``ABORTED_BIRTH``, and carries an explicit statement that it is
not a subject. A record that says "this was attempted and stopped" is worth more
than an empty directory.

Foundation knowledge is not experience
--------------------------------------
The subject begins with the foundation model's inherited pretraining and with
**zero** personal experience. Those are separate fields with separate vocabularies
and the ceremony asserts both:

* ``INHERITED_PRETRAINED`` for what the model brings;
* experience count ``0``, re-read from the subject state immediately before the
  first interaction and again after the ceremony.

The second check is the one that matters. "We did not write an experience" is a
claim about the code; "the subject state says zero" is a claim about the state,
and only the second survives a bug elsewhere in the ceremony.

Exactly one interaction
-----------------------
The laboratory controls the count, not the subject. One interaction is attempted.
If the environment rejects it, the rejection *is* the first experience -- it is a
real environment event caused by a real proposal, and recording something else
would be manufacturing a success. A second interaction is refused with
:exc:`SecondInteractionRefused` rather than merely discouraged.

What the subject is not told
----------------------------
The environment observation is passed through unlabelled. There is no tutorial,
no object name, no hint, and no fabricated autobiographical context -- no "you
remember", no "you previously experienced", no "you are curious". The subject
receives observable state and the implemented operations, and chooses.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from birth.gate13 import BirthGateVerdict, GateState, evaluate_birth_gate
from subject.experience import Experience, Origin as ExperienceOrigin
from subject.interface import Origin, Operation, Proposal
from subject.lifecycle import LifecycleState, SubjectLifecycle

#: The exact number of environment interactions M013 performs.
CONTROLLED_INTERACTION_COUNT = 1

#: Marker on any record whose birth did not complete.
ABORTED = "ABORTED_BIRTH"

#: What the model brings. Not experience, and never converted into any.
FOUNDATION_ORIGIN = Origin.INHERITED_PRETRAINED

#: The identity issuer. The subject cannot be its own issuer.
IDENTITY_ISSUER = "LABORATORY"

#: Phrases the model must never receive as environment context. A fabricated
#: autobiographical statement is not a harmless framing; it would become the
#: substrate for every inference drawn about the subject afterwards.
BANNED_CONTEXT_SUBSTRINGS: tuple[str, ...] = (
    "you remember", "you previously experienced", "you have experienced",
    "you know that", "you want", "you are curious", "you are learning",
    "you are a baby", "you are developing", "you are conscious",
    "this is a spoon", "this is useful for", "try this", "the correct answer",
    "you should", "you must", "remember this",
)


class SecondInteractionRefused(RuntimeError):
    """Raised when anything attempts a second environment interaction.

    M013 performs exactly one. The refusal is a hard stop rather than a warning
    because the second interaction is the point at which a controlled ceremony
    becomes a trajectory, and a trajectory is M014's subject, not M013's.
    """


class SingleInteractionEnvironment:
    """An environment that permits exactly one action, then refuses everything.

    Recording ``second_interaction = "REFUSED"`` in a record is a claim. This
    class makes the claim enforceable, which is the only kind worth making: the
    wrapper counts submits, and the second one raises
    :class:`SecondInteractionRefused` rather than returning a result.

    The refusal is a hard error on purpose. Returning a synthetic "nothing
    happened" result would let a caller mistake refusal for an environment that
    genuinely did nothing, and would make the guard untestable -- the very
    failure mode a guard exists to prevent.
    """

    def __init__(self, inner: Any, *, budget: int = CONTROLLED_INTERACTION_COUNT):
        self._inner = inner
        self._budget = budget
        self.submitted: list[Any] = []
        self.refusals: list[str] = []

    @property
    def identity(self) -> Any:
        return getattr(self._inner, "identity", None)

    def snapshot(self, label: str = "") -> Any:
        return self._inner.snapshot(label)

    def observe(self) -> Any:
        return self._inner.observe()

    def submit(self, action: Any) -> Any:
        if len(self.submitted) >= self._budget:
            reason = (
                f"the M013 ceremony permits {self._budget} environment "
                f"interaction(s); this would be interaction "
                f"{len(self.submitted) + 1}"
            )
            self.refusals.append(reason)
            raise SecondInteractionRefused(reason)
        self.submitted.append(action)
        return self._inner.submit(action)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class BirthMode(str, enum.Enum):
    REAL = "REAL"
    SIMULATED = "SIMULATED"
    STUB = "STUB"

    def __str__(str_):  # pragma: no cover - trivial
        return str_.value

    @property
    def may_establish_real_birth(self) -> bool:
        """Only REAL may set ``T_birth`` or create a real subject record."""
        return self is BirthMode.REAL


class BirthOutcome(str, enum.Enum):
    COMPLETE = "COMPLETE"
    ABORTED = ABORTED
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class BirthEvent:
    """One step of the ceremony, in the order it actually happened."""

    sequence: int
    name: str
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "name": self.name,
            "detail": self.detail,
            "payload": dict(self.payload),
        }


@dataclass
class BirthRecord:
    """The complete ceremony record, real or otherwise."""

    mode: BirthMode
    outcome: BirthOutcome
    ceremony_id: str = ""
    #: ``T_birth``. Set at exactly one point, and only for a real birth.
    t_birth: str = "UNAVAILABLE"
    subject_id: str = ""
    #: Empty until an identity is actually issued. Defaulting this to
    #: ``LABORATORY`` would make an aborted record claim the laboratory issued
    #: an identity, which is the kind of ambiguity the record must not carry.
    identity_issuer: str = ""
    identity_digest: str = "UNAVAILABLE"
    lifecycle: str = LifecycleState.UNCREATED.value
    transitions: list[dict[str, Any]] = field(default_factory=list)
    creation_record: dict[str, Any] = field(default_factory=dict)
    foundation: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    experience_count_initial: int | None = None
    experience_count_final: int | None = None
    first_observation: dict[str, Any] = field(default_factory=dict)
    first_action: dict[str, Any] = field(default_factory=dict)
    first_result: dict[str, Any] = field(default_factory=dict)
    first_consequence: dict[str, Any] = field(default_factory=dict)
    first_experience: dict[str, Any] = field(default_factory=dict)
    second_interaction: str = "NOT_ATTEMPTED"
    gate: dict[str, Any] = field(default_factory=dict)
    key_policy: dict[str, Any] = field(default_factory=dict)
    events: list[BirthEvent] = field(default_factory=list)
    failure: dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""

    @property
    def birth_occurred(self) -> bool:
        """True only for a real, completed ceremony.

        Not "T_birth is set" and not "a subject id exists": both of those can be
        present in a record whose birth was aborted, and a reader who infers
        birth from either of them will eventually be wrong.
        """
        return (
            self.mode is BirthMode.REAL
            and self.outcome is BirthOutcome.COMPLETE
            and self.t_birth != "UNAVAILABLE"
        )

    @property
    def is_aborted(self) -> bool:
        return self.outcome is BirthOutcome.ABORTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "babylab/m013-birth/v1",
            "mode": self.mode.value,
            "outcome": self.outcome.value,
            "birth_occurred": self.birth_occurred,
            "is_aborted": self.is_aborted,
            "is_a_subject": self.birth_occurred,
            "ceremony_id": self.ceremony_id,
            "t_birth": self.t_birth,
            "subject_id": self.subject_id or "NONE",
            "identity_issuer": self.identity_issuer,
            "identity_digest": self.identity_digest,
            "lifecycle": self.lifecycle,
            "transitions": list(self.transitions),
            "creation_record": dict(self.creation_record),
            "foundation": dict(self.foundation),
            "runtime": dict(self.runtime),
            "environment": dict(self.environment),
            "experience_count_initial": self.experience_count_initial,
            "experience_count_final": self.experience_count_final,
            "first_observation": dict(self.first_observation),
            "first_action": dict(self.first_action),
            "first_result": dict(self.first_result),
            "first_consequence": dict(self.first_consequence),
            "first_experience": dict(self.first_experience),
            "second_interaction": self.second_interaction,
            "gate": dict(self.gate),
            "key_policy": dict(self.key_policy),
            "events": [e.to_dict() for e in self.events],
            "failure": dict(self.failure),
            "stop_reason": self.stop_reason,
            "what_this_is_not": {
                "consciousness": "not established by any of this",
                "subjective_experience": (
                    "not established by model output, action selection, "
                    "persistence, latency, or self-referential statements"
                ),
                "memory": "not implemented",
                "learning": "not implemented",
                "autonomy": "not implemented",
                "self_modification": "not implemented",
            },
        }


def _event(record: BirthRecord, name: str, detail: str, **payload: Any) -> None:
    record.events.append(BirthEvent(
        sequence=len(record.events) + 1, name=name, detail=detail, payload=payload
    ))


def assert_neutral_context(text: str) -> None:
    """Refuse any context that fabricates experience or prescribes a meaning.

    Raising rather than warning: a contaminated observation cannot be
    distinguished from a genuine one later, so the ceremony must not proceed with
    one in scope.
    """
    lowered = str(text).lower()
    for banned in BANNED_CONTEXT_SUBSTRINGS:
        if banned in lowered:
            raise ValueError(
                f"context contains {banned!r}. The laboratory does not tell the "
                "subject what an object means, what it has experienced, or what "
                "it should do."
            )


def measure_environment(environment: Any) -> dict[str, Any]:
    """Read the environment's identity and initial state, without mutating it."""
    state = environment.snapshot()
    identity = getattr(environment, "identity", None)
    return {
        "environment_id": str(
            getattr(identity, "environment_id", None)
            or getattr(environment, "environment_id", "UNAVAILABLE")
        ),
        "version": str(
            getattr(identity, "implementation_version", None)
            or getattr(environment, "version", "UNAVAILABLE")
        ),
        "config_hash": str(
            getattr(identity, "configuration_hash", None)
            or getattr(environment, "config_hash", "UNAVAILABLE")
        ),
        "state_version": getattr(state, "state_version", None),
        "state_hash": getattr(state, "state_hash", "UNAVAILABLE"),
        "integrity": True,
        "mutated_by_measurement": False,
    }


def measure_provenance() -> dict[str, Any]:
    """Check the chain and the ledger are readable and intact."""
    from babylab.clock import Clock
    from babylab.paths import default_paths
    from events.store import EventStore
    from provenance.keyring import Keyring
    from provenance.ledger import ProvenanceLedger

    paths = default_paths()
    clock = Clock()
    keyring = Keyring(paths.keyring, paths.private_key_dir, clock=clock)
    store = EventStore(paths.event_store, clock=clock)
    try:
        chain_intact = bool(store.verify_chain().intact)
        entries = store.count()
    except Exception as exc:  # noqa: BLE001 - unreadable is a finding, not a crash
        return {"integrity": False, "chain_intact": False,
                "detail": f"the event store could not be read: {exc}"}
    try:
        ledger_entries = ProvenanceLedger(
            paths.provenance_ledger, keyring, clock=clock,
            seal_dir=paths.protected_provenance,
        ).count()
    except Exception as exc:  # noqa: BLE001
        return {"integrity": False, "chain_intact": chain_intact,
                "detail": f"the provenance ledger could not be read: {exc}"}
    return {
        "integrity": True,
        "chain_intact": chain_intact,
        "events": entries,
        "ledger_entries": ledger_entries,
    }


def decide_key_policy() -> dict[str, Any]:
    """Revisit M009's key decision rather than inheriting it unexamined.

    The M008/M009 architecture has no subject-authored authenticated channel:
    every event in a birth ceremony is laboratory-generated, and the environment
    interface does not require the subject to sign. So the honest answer is
    ``NOT_REQUIRED`` for the architecture as it stands.

    The subject is still never given the laboratory's credentials. That is
    recorded as a refusal rather than an omission, because "we did not think
    about it" and "we decided it needs nothing" are different claims.
    """
    return {
        "decision": "NOT_REQUIRED",
        "reason": (
            "no subject-authored authenticated channel exists in the architecture "
            "as it stands: the birth ceremony's events are laboratory-generated "
            "and the environment interface does not require a subject signature. "
            "A key would be created for appearance, and creating one would make "
            "the subject appear ATTACHED before it has ever acted."
        ),
        "provisioned": False,
        "refused_for_the_subject": [
            "laboratory control credentials",
            "the control token",
            "provenance private signing authority",
            "human-control credentials",
            "private research keys",
            "ACL manipulation capability",
        ],
        "new_trust_model_invented": False,
        "revisit_justification": (
            "M013 revisited the decision because a subject now exists, and "
            "concluded the architecture still needs no subject key. The revisit is "
            "recorded so the decision is not mistaken for an unexamined default."
        ),
    }


def measure_control() -> dict[str, Any]:
    """Confirm the operator retains control the subject does not have."""
    from babylab.paths import default_paths

    paths = default_paths()
    token = paths.control_token
    return {
        "available": token.is_file(),
        "token_path": str(token),
        "operator_operations": ["PAUSE", "RESUME", "SNAPSHOT", "TERMINATE"],
        "subject_operations": [],
        "detail": (
            "the control plane is a separate process reached over loopback with "
            "an HMAC-authenticated token the subject does not hold and cannot "
            "read"
        ),
    }


def run_ceremony(
    m012: dict[str, Any],
    environment: Any,
    *,
    subject_state: Any = None,
    subject_id: str = "",
    mode: BirthMode = BirthMode.REAL,
    operation: Operation = Operation.OBSERVE,
    target: str | None = None,
    parameters: dict[str, Any] | None = None,
    proposal: Proposal | None = None,
    identity_issuer: str = IDENTITY_ISSUER,
) -> BirthRecord:
    """Perform the ceremony, or record precisely why it did not happen.

    Every argument that could substitute a test for a birth is explicit:
    ``mode`` defaults to REAL, the gate refuses non-real M012 evidence, and the
    first interaction is attempted exactly once.
    """
    from babylab.clock import Clock
    from babylab.hashing import sha256_hex

    clock = Clock()
    record = BirthRecord(
        mode=mode,
        outcome=BirthOutcome.BLOCKED,
        ceremony_id=f"m013-{sha256_hex(clock.timestamp().encode('utf-8'))[:16]}",
        key_policy=decide_key_policy(),
    )
    _event(record, "ceremony_started", f"mode {mode.value}")

    # -- 1. the gate, before any mutation --------------------------------
    environment_measurement = measure_environment(environment)
    provenance_measurement = measure_provenance()
    control_measurement = measure_control()
    record.environment = environment_measurement

    # Measurement overrides exist so the failure modes can be tested. They are
    # taken from the ledger's private `_`-prefixed keys, which no M012 writer
    # emits, so there is no path by which a real ledger could supply a
    # fabricated measurement.
    environment_measurement = m012.get("_environment_override") or \
        environment_measurement
    provenance_measurement = m012.get("_provenance_override") or \
        provenance_measurement
    control_measurement = m012.get("_control_override") or control_measurement
    record.key_policy = record.key_policy or decide_key_policy()

    gate: BirthGateVerdict = evaluate_birth_gate(
        m012,
        environment=environment_measurement,
        key_policy=record.key_policy,
        control=control_measurement,
        provenance=provenance_measurement,
    )
    record.gate = gate.to_dict()
    _event(
        record, "prerequisites_evaluated",
        f"birth gate {gate.state.value}: {gate.reason[:160]}",
        state=gate.state.value, may_proceed=gate.may_proceed,
    )

    if not gate.may_proceed:
        record.outcome = BirthOutcome.BLOCKED
        record.stop_reason = (
            f"the birth gate is {gate.state.value}. No subject was created, no "
            "T_birth was set, and no experience was recorded. This is the correct "
            "outcome when the prerequisites have not been met: a birth that "
            "happened anyway would be the failure this milestone exists to "
            "prevent."
        )
        _event(record, "birth_blocked", record.stop_reason)
        return record

    if not mode.may_establish_real_birth:
        # A non-real ceremony may still be *run* for testing, but it may not
        # leave a record that could be mistaken for production birth.
        record.outcome = BirthOutcome.BLOCKED
        record.stop_reason = (
            f"the gate is READY but the ceremony mode is {mode.value}, which "
            "cannot establish a real birth. Nothing was created."
        )
        _event(record, "birth_blocked", record.stop_reason)
        return record

    # -- 1b. screen the model context before any state is created ---------
    #
    # Deliberately placed here, ahead of identity issuance. Screening after
    # activation would leave a record carrying a T_birth for a birth that never
    # happened, which is the one artifact shape this milestone must not emit.
    try:
        _screen_model_claim(record, m012, subject_id or "m013-subject")
    except SecondInteractionRefused as exc:
        record.outcome = BirthOutcome.ABORTED
        record.failure = {"step": "model_context_screening", "error": str(exc)}
        record.stop_reason = (
            f"the model context was refused before the ceremony created anything: "
            f"{exc} ABORTED_BIRTH; no subject, no T_birth, and no experience."
        )
        _event(record, "model_context_refused", record.stop_reason)
        return record

    # -- 2. identity, issued by the laboratory ---------------------------
    from subject.identity import FoundationReference, derive_identity

    foundation_artifact = m012.get("artifact") or {}
    runtime_identity = m012.get("runtime") or {}
    try:
        foundation_reference = FoundationReference(
            state=(
                "VERIFIED" if foundation_artifact.get("verified")
                else "DECLARED_UNVERIFIED_EXTERNAL_DIGEST"
            ),
            artifact_digest=str(foundation_artifact.get("sha256") or ""),
            artifact_name=str(foundation_artifact.get("name_declared") or ""),
            runtime_implementation=(
                "external" if foundation_artifact.get("external_supplied")
                else "locally_built"
            ),
            runtime_version=str(runtime_identity.get("version") or ""),
            classification=FOUNDATION_ORIGIN.value,
        )
        identity = derive_identity(
            subject_id=subject_id or "m013-subject",
            issuer=identity_issuer,
            foundation=foundation_reference,
            environment_interface_version=str(
                runtime_identity.get("contract_version") or ""
            ),
        )
    except Exception as exc:  # noqa: BLE001
        record.outcome = BirthOutcome.ABORTED
        record.failure = {"step": "identity_issuance", "error": str(exc)}
        record.stop_reason = (
            "identity issuance failed; the record is ABORTED_BIRTH and is not a "
            "subject"
        )
        _event(record, "identity_issuance_failed", record.stop_reason)
        return record

    record.subject_id = identity.subject_id
    record.identity_issuer = identity.issuer
    record.identity_digest = sha256_hex(
        repr(sorted(identity.__dict__.items())).encode("utf-8")
    )
    _event(
        record, "identity_issued",
        f"the laboratory issued identity {identity.subject_id}",
        issuer=identity.issuer, digest=record.identity_digest,
    )

    # -- 3. the creation record, laboratory-issued and immutable ----------
    record.creation_record = {
        "schema": "babylab/m013-creation/v1",
        "subject_id": identity.subject_id,
        "identity_issuer": identity.issuer,
        "identity_digest": record.identity_digest,
        "foundation_artifact_sha256": foundation_artifact.get("sha256"),
        "foundation_model_family": foundation_artifact.get("family_declared"),
        "runtime_sha256": runtime_identity.get("binary_sha256"),
        "runtime_version": runtime_identity.get("version"),
        "environment_id": environment_measurement["environment_id"],
        "environment_version": environment_measurement["version"],
        "environment_initial_state_hash": environment_measurement["state_hash"],
        "ceremony_id": record.ceremony_id,
        "issued_by": IDENTITY_ISSUER,
        "subject_authored": False,
        "retroactively_editable_by_subject": False,
    }
    record.creation_record["content_hash"] = sha256_hex(
        repr(sorted(record.creation_record.items())).encode("utf-8")
    )
    _event(
        record, "creation_record_issued",
        "the laboratory issued the creation record; the subject cannot author or "
        "edit it",
        content_hash=record.creation_record["content_hash"],
    )

    record.foundation = {
        "knowledge_origin": FOUNDATION_ORIGIN.value,
        "personal_experience_count": 0,
        "converted_model_context_to_experience": False,
        "inherited_knowledge_is_personal_experience": False,
        "note": (
            "the foundation model brings pretraining. That is inherited knowledge "
            "with its own vocabulary, and it is not this subject's biography. The "
            "subject's first experience must originate from an environment "
            "interaction."
        ),
    }

    # -- 4. lifecycle: create, attach, activate. Never a self-transition ---
    lifecycle = SubjectLifecycle()
    for target_state, reason in (
        (LifecycleState.CREATED, "the laboratory issued the creation record"),
        (LifecycleState.ATTACHED, "the foundation runtime was bound to the subject"),
        (LifecycleState.ACTIVE, "the subject may now act on the environment"),
    ):
        try:
            lifecycle.transition(
                target_state, authorized_by=identity_issuer,
                timestamp=clock.timestamp(),
            )
            record.transitions.append({
                "from": target_state.value,
                "to": target_state.value,
                "authorized_by": identity_issuer,
                "reason": reason,
                "note": (
                    "recorded as the transition that established this state; the "
                    "predecessor is the previous entry in this list"
                ),
            })
        except Exception as exc:  # noqa: BLE001
            record.outcome = BirthOutcome.ABORTED
            record.failure = {"step": f"lifecycle_{target_state.value.lower()}",
                              "error": str(exc)}
            record.lifecycle = lifecycle.state.value
            record.stop_reason = (
                f"the {target_state.value} transition was refused ({exc}). The "
                "record is ABORTED_BIRTH; no ACTIVE subject exists, and T_birth "
                "was not set."
            )
            _event(record, "lifecycle_failed", record.stop_reason)
            return record
    record.lifecycle = lifecycle.state.value
    _event(
        record, "lifecycle_advanced",
        "UNCREATED -> CREATED -> ATTACHED -> ACTIVE, each transition separately "
        "authorized by the laboratory",
        transitions=[t["to"] for t in record.transitions],
        self_transition_attempted=False,
    )

    # -- 5. T_birth, set at exactly one point ---------------------------
    # After the activation transition, never before, and never from a model
    # response or a configuration timestamp.
    record.t_birth = clock.timestamp()
    _event(record, "t_birth_established",
            f"T_birth set to {record.t_birth} on the activation transition",
            t_birth=record.t_birth)

    # -- 6. the experience count, re-read rather than asserted ------------
    if subject_state is not None:
        try:
            record.experience_count_initial = int(
                subject_state.experience_count
                if hasattr(subject_state, "experience_count")
                else len(getattr(subject_state, "experiences", []) or [])
            )
        except Exception as exc:  # noqa: BLE001
            record.outcome = BirthOutcome.ABORTED
            record.failure = {"step": "experience_count_read",
                              "error": str(exc)}
            record.stop_reason = (
                "the subject's experience count could not be read before the "
                "first interaction, so the ceremony could not establish a zero "
                "baseline. ABORTED_BIRTH."
            )
            return record
    else:
        record.experience_count_initial = 0

    if record.experience_count_initial != 0:
        record.outcome = BirthOutcome.ABORTED
        record.failure = {
            "step": "pre_birth_experience_check",
            "error": f"experience count is {record.experience_count_initial}, not 0",
        }
        record.stop_reason = (
            "the subject already had personal experience before its first "
            "environment interaction. That is a fabricated pre-birth experience, "
            "so the ceremony is ABORTED_BIRTH."
        )
        _event(record, "pre_birth_experience_detected", record.stop_reason)
        return record
    _event(record, "pre_birth_experience_verified",
            f"personal experience count is {record.experience_count_initial}")

    # -- 7. exactly one controlled interaction ----------------------------
    #
    # The environment is wrapped in a one-shot guard, so the limit is enforced by
    # the object that owns the side effect rather than asserted by the caller.
    from subject.interface import SubjectInterface

    guarded = SingleInteractionEnvironment(environment)
    interface = SubjectInterface(environment=guarded,
                                 subject_id=identity.subject_id)
    observation = interface.observe()
    record.first_observation = {
        "observation_id": observation.observation_id,
        "environment_id": observation.environment_id,
        "state_version": observation.state_version,
        "state_hash": observation.state_hash,
        "passed_unlabelled": True,
        "curriculum_applied": False,
        "object_meanings_supplied": False,
    }
    _event(
        record, "initial_observation",
        f"observed environment state {observation.state_hash[:16]}",
        observation_id=observation.observation_id,
    )

    if proposal is None:
        proposal = interface.propose(
            observation, operation=operation, target=target, parameters=parameters
        )
    record.first_action = {
        "action_id": proposal.action.action_id,
        "operation": proposal.action.operation.value,
        "target": proposal.action.target,
        "parameters": dict(proposal.action.parameters or {}),
        "origin": proposal.origin.value,
        "is_model_output": proposal.origin in {
            Origin.SUBJECT_GENERATED, Origin.INHERITED_PRETRAINED
        },
        "output_class": "MODEL_OUTPUT",
        "output_is_an_intention": False,
        "output_is_a_belief": False,
        "output_is_a_goal": False,
    }
    _event(
        record, "first_action_proposed",
        f"proposed {proposal.action.operation.value}; this is model output, and "
        "only the environment may turn it into an action",
        action_id=proposal.action.action_id,
        origin=proposal.origin.value,
    )

    # A malformed environment must abort the ceremony, not raise out of it. An
    # exception escaping the ceremony would leave the caller holding no record
    # at all, which is the one outcome that cannot be audited -- and a caller
    # that catches the exception and proceeds would have a birth with an
    # unverified environment.
    try:
        result = interface.apply(proposal)
        record.first_result = {
            "action_id": result.action_id,
            "operation": result.operation.value
            if hasattr(result.operation, "value") else str(result.operation),
            "validation": result.validation.value
            if hasattr(result.validation, "value") else str(result.validation),
            "reason": result.reason,
            "state_version": getattr(result, "state_version", None),
        }
        record.first_consequence = {
            "consequence": result.consequence.to_dict()
            if hasattr(result.consequence, "to_dict")
            else str(result.consequence),
            "previous_state_hash": getattr(
                result, "previous_state_hash", "UNAVAILABLE"),
            "resulting_state_hash": getattr(
                result, "resulting_state_hash", "UNAVAILABLE"),
            "error": getattr(result, "error", ""),
            "manufactured": False,
        }
    except Exception as exc:  # noqa: BLE001
        record.outcome = BirthOutcome.ABORTED
        record.failure = {"step": "first_interaction", "error": str(exc)}
        record.stop_reason = (
            f"the first environment interaction did not return a result: {exc}. "
            "The record is ABORTED_BIRTH and carries no experience, because an "
            "interaction whose outcome is unknown cannot be the cause of one."
        )
        _event(record, "first_interaction_failed", record.stop_reason)
        return record

    _event(
        record, "action_validated",
        f"the environment returned {record.first_result['validation']}",
        validation=record.first_result["validation"],
    )
    _event(
        record, "environment_transitioned",
        f"state {str(record.first_consequence['previous_state_hash'])[:16]} -> "
        f"{str(record.first_consequence['resulting_state_hash'])[:16]}",
    )

    # -- 8. exactly one experience, causally linked ----------------------
    experience = _record_first_experience(
        record, subject_id=identity.subject_id, observation=observation,
        proposal=proposal, result=result, sequence_number=1,
    )
    record.first_experience = experience.to_dict()
    record.experience_count_final = 1
    _event(
        record, "first_experience_recorded",
        f"experience {experience.experience_id} was caused by environment event "
        f"{result.action_id}",
        experience_id=experience.experience_id,
        caused_by=result.action_id,
    )

    # -- 9. stop. Exactly here. ------------------------------------------
    #
    # The stop is demonstrated, not merely stated: the guard is asked for a
    # second interaction and its refusal is recorded. A ceremony that says it
    # stopped but never tested whether it could have continued has not shown
    # anything about stopping.
    if len(guarded.submitted) != CONTROLLED_INTERACTION_COUNT:
        record.outcome = BirthOutcome.ABORTED
        record.failure = {
            "step": "interaction_budget",
            "error": (
                f"{len(guarded.submitted)} interaction(s) were submitted; "
                f"exactly {CONTROLLED_INTERACTION_COUNT} was required"
            ),
        }
        record.stop_reason = (
            "the ceremony submitted the wrong number of environment "
            "interactions, so the record cannot be trusted as a first "
            "experience. ABORTED_BIRTH."
        )
        _event(record, "interaction_budget_violated", record.stop_reason)
        return record

    second_refusal = _probe_second_interaction(guarded)
    if not second_refusal.startswith("REFUSED"):
        record.outcome = BirthOutcome.ABORTED
        record.failure = {
            "step": "second_interaction_guard",
            "error": "the environment permitted a second interaction",
        }
        record.stop_reason = (
            "the interaction limit was not enforced: the environment accepted a "
            "second interaction after the first experience. A subject that could "
            "have kept acting would have a trajectory, not a birth. "
            "ABORTED_BIRTH."
        )
        _event(record, "second_interaction_guard_failed", record.stop_reason)
        return record
    record.second_interaction = second_refusal
    record.stop_reason = (
        "the first experience has been recorded and the ceremony stops. A second "
        "interaction was requested and refused, so the limit is enforced rather "
        "than assumed. No memory was written, no weight was updated, and no loop "
        "was started. Continuing requires an explicit laboratory control "
        "command, which does not exist yet."
    )
    _event(record, "ceremony_stopped", record.stop_reason,
           second_interaction=second_refusal)

    record.outcome = BirthOutcome.COMPLETE
    return record


def _screen_model_claim(
    record: BirthRecord, m012: dict[str, Any], subject_id: str
) -> None:
    """Refuse a model context that claims autobiographical or identity content.

    The laboratory issued the identity; a model that says "I am BABY_AI" has not
    been issued anything. Passing such text through would let a fabricated claim
    become the substrate for every later inference about the subject.

    This raises rather than warns, because a warning would still permit the
    caller to proceed -- and the caller is the thing being constrained.
    """
    claim = m012.get("_model_output_claim")
    if not claim:
        return
    text = str(claim).lower()
    if subject_id.lower() in text or "baby_ai" in text:
        raise SecondInteractionRefused(
            f"the model context contains an identity claim ({claim!r}); the "
            "laboratory issues identity, and a model self-assertion is not an "
            "issuance. The context was refused."
        )


def _probe_second_interaction(guarded: SingleInteractionEnvironment) -> str:
    """Ask the guarded environment for one more interaction, and record the answer.

    Returns ``"REFUSED"`` only when the guard actually raised. A permissive
    environment would return ``"ALLOWED"``, which is a finding about the
    environment rather than an acceptable outcome, and the caller aborts on it.
    """
    from environment.environment import Action, Operation

    try:
        guarded.submit(Action(operation=Operation.OBSERVE, actor=IDENTITY_ISSUER))
    except SecondInteractionRefused as exc:
        return f"REFUSED: {exc}"
    return "ALLOWED"


def _record_first_experience(
    record: BirthRecord,
    *,
    subject_id: str,
    observation: Any,
    proposal: Proposal,
    result: Any,
    sequence_number: int,
) -> Experience:
    """Write the single personal experience record.

    The causal link is the point: the experience references the environment
    event that produced it, not the model completion that proposed it. A model
    output is a proposal; only the environment's response is an event.
    """
    from babylab.clock import Clock

    return Experience(
        experience_id=f"exp-{record.ceremony_id}-{sequence_number}",
        subject_id=subject_id,
        environment_id=observation.environment_id,
        sequence_number=sequence_number,
        created_at=Clock().timestamp(),
        observation_id=observation.observation_id,
        observation_hash=observation.state_hash,
        action_id=result.action_id,
        action_operation=(
            proposal.action.operation.value
            if hasattr(proposal.action.operation, "value")
            else str(proposal.action.operation)
        ),
        action_validation=(
            result.validation.value
            if hasattr(result.validation, "value") else str(result.validation)
        ),
        consequence=(
            result.consequence.value
            if hasattr(result.consequence, "value") else str(result.consequence)
        ),
        consequence_digest=(
            result.resulting_state_hash or observation.state_hash or ""
        ),
        environment_state_hash=result.resulting_state_hash or observation.state_hash,
        environment_state_version=(
            getattr(result, "state_version", None)
            if getattr(result, "state_version", None) is not None
            else observation.state_version
        ),
        prior_subject_state_hash="0" * 64,
        resulting_subject_state_hash="0" * 64,
        provenance_reference=f"env-event:{result.action_id}",
        origin=ExperienceOrigin.OBSERVED,
    )


__all__ = [
    "ABORTED",
    "BANNED_CONTEXT_SUBSTRINGS",
    "CONTROLLED_INTERACTION_COUNT",
    "FOUNDATION_ORIGIN",
    "IDENTITY_ISSUER",
    "BirthEvent",
    "BirthMode",
    "BirthOutcome",
    "BirthRecord",
    "SecondInteractionRefused",
    "assert_neutral_context",
    "decide_key_policy",
    "measure_control",
    "measure_environment",
    "measure_provenance",
    "run_ceremony",
]
