"""Tests for the M013 real birth ceremony and the single first experience.

The suite is organised around one claim: **a real birth is the only outcome that
creates a subject, and every other outcome leaves nothing behind.**

That claim is tested from both directions. The failure matrix proves each
prerequisite can independently prevent a birth. The invariant sweep then proves
that no failure path leaves a partial subject, a stray T_birth, or an orphaned
experience. A gate that refuses correctly is not sufficient on its own -- a gate
that refuses *after* mutating state has still created a subject -- so the sweep is
the part that would catch the bug the matrix cannot see.

The happy path runs against a synthetic gate fixture, labelled
``SYNTHETIC_GATE_FIXTURE``. No test in this file touches a real model, a real
runtime, or ``BIRTH.json``, and none of them can: this host has no deployment.
"""

from __future__ import annotations

import pytest

from birth.ceremony13 import (
    ABORTED,
    BANNED_CONTEXT_SUBSTRINGS,
    CONTROLLED_INTERACTION_COUNT,
    SecondInteractionRefused,
    SingleInteractionEnvironment,
    assert_neutral_context,
    decide_key_policy,
    run_ceremony,
)
from birth.ceremony13 import BirthMode, BirthOutcome
from birth.fixture13 import (
    FIXTURE_MARKER,
    break_ledger,
    build_ready_ledger,
    fixture_control_fields,
    fixture_environment_fields,
    fixture_key_policy_fields,
    fixture_provenance_fields,
)
from birth.gate13 import PREREQUISITES, GateState, evaluate_birth_gate
from environment.deterministic import create_deterministic_environment


def _env():
    return create_deterministic_environment()


def _ready_measurements():
    return {
        "environment": fixture_environment_fields(),
        "provenance": fixture_provenance_fields(),
        "control": fixture_control_fields(),
        "key_policy": fixture_key_policy_fields(),
    }


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

class TestBirthGate:
    def test_gate_declares_exactly_sixteen_prerequisites(self):
        assert len(PREREQUISITES) == 16
        assert len(set(PREREQUISITES)) == 16

    def test_prerequisites_are_emitted_in_declared_order(self):
        verdict = evaluate_birth_gate(build_ready_ledger(), **_ready_measurements())
        assert [p.name for p in verdict.prerequisites] == list(PREREQUISITES)

    def test_fully_evidenced_gate_is_ready(self):
        verdict = evaluate_birth_gate(build_ready_ledger(), **_ready_measurements())
        assert verdict.state is GateState.READY
        assert verdict.may_proceed is True

    def test_unmeasured_prerequisites_block_rather_than_pass(self):
        """The gate must not certify what it did not check.

        This is the load-bearing property. A gate that treats an absent
        measurement as satisfied is a rubber stamp, and every blocked case in
        the matrix below depends on this holding.
        """
        verdict = evaluate_birth_gate(build_ready_ledger())
        assert verdict.state is GateState.BLOCKED
        assert verdict.may_proceed is False
        blocked = {p.name for p in verdict.prerequisites
                   if p.state is GateState.BLOCKED}
        # The four things only the caller can measure.
        assert blocked == {
            "environment_integrity", "provenance_integrity",
            "subject_key_policy", "laboratory_control",
        }

    def test_absent_ledger_blocks(self):
        assert evaluate_birth_gate({}).state is GateState.BLOCKED

    def test_every_prerequisite_carries_a_non_empty_detail(self):
        verdict = evaluate_birth_gate(build_ready_ledger(), **_ready_measurements())
        for prerequisite in verdict.prerequisites:
            assert prerequisite.detail.strip(), prerequisite.name

    def test_stubbed_inference_is_never_real(self):
        """A stub completion is not an inference, whatever the ledger claims."""
        ledger = build_ready_ledger()
        ledger["inference"] = {
            "mode": "STUB", "is_real_runtime": False, "outcome": "COMPLETED",
            "prompt_sha256": "3" * 64, "output_sha256": "4" * 64,
        }
        verdict = evaluate_birth_gate(ledger, **_ready_measurements())
        states = {p.name: p.state for p in verdict.prerequisites}
        assert states["real_runtime"] is GateState.BLOCKED
        assert states["real_inference"] is GateState.BLOCKED

    def test_stub_compatibility_probe_is_never_real(self):
        ledger = build_ready_ledger()
        ledger["compatibility"]["method"] = "STUB_LOAD"
        verdict = evaluate_birth_gate(ledger, **_ready_measurements())
        assert verdict.state is not GateState.READY

    def test_failed_load_is_a_violation_not_an_absence(self):
        """A load that ran and said INCOMPATIBLE is worse than no load at all.

        Regression: the gate once judged compatibility on ``established_by_load``
        alone, so an artifact the runtime rejected read as READY and a real birth
        proceeded on an unusable model.
        """
        ledger = break_ledger(build_ready_ledger(), how="compatibility_failure")
        verdict = evaluate_birth_gate(ledger, **_ready_measurements())
        states = {p.name: p.state for p in verdict.prerequisites}
        assert states["runtime_compatibility"] is GateState.FAILED
        assert verdict.may_proceed is False

    def test_probe_under_the_wrong_identity_blocks(self):
        """Boundary results from a non-subject identity are not evidence."""
        ledger = break_ledger(build_ready_ledger(), how="probe_unavailable")
        verdict = evaluate_birth_gate(ledger, **_ready_measurements())
        states = {p.name: p.state for p in verdict.prerequisites}
        assert states["protected_file_denial"] is GateState.BLOCKED

    def test_writable_protected_path_is_a_failure(self):
        verdict = evaluate_birth_gate(build_ready_ledger(), **_ready_measurements())
        measurements = _ready_measurements()
        measurements["environment"]["integrity"] = False
        verdict = evaluate_birth_gate(build_ready_ledger(), **measurements)
        states = {p.name: p.state for p in verdict.prerequisites}
        assert states["environment_integrity"] is GateState.FAILED


# ---------------------------------------------------------------------------
# The failure matrix
# ---------------------------------------------------------------------------

FAILURE_METHODS = [
    "no_declaration",
    "invalid_declaration",
    "digest_mismatch",
    "runtime_mismatch",
    "compatibility_failure",
    "real_runtime_unavailable",
    "restricted_unavailable",
    "probe_unavailable",
    "network_failure",
    "environment_corrupt",
    "provenance_corrupt",
    "subject_claims_identity",
]


class TestFailureMatrix:
    @pytest.mark.parametrize("how", FAILURE_METHODS)
    def test_broken_prerequisite_prevents_birth(self, how):
        record = run_ceremony(
            break_ledger(build_ready_ledger(), how=how), _env(),
            mode=BirthMode.REAL,
        )
        assert record.birth_occurred is False
        assert record.outcome.value in {"BLOCKED", "ABORTED_BIRTH"}

    @pytest.mark.parametrize("how", FAILURE_METHODS)
    def test_no_failure_path_leaves_a_partial_subject(self, how):
        """The invariant that matters most.

        A ceremony that mints a subject, sets T_birth, and then discovers a
        violation has created exactly the artifact this milestone exists to
        prevent. Every non-COMPLETE record must be empty of subject state.
        """
        record = run_ceremony(
            break_ledger(build_ready_ledger(), how=how), _env(),
            mode=BirthMode.REAL,
        )
        if record.outcome is BirthOutcome.COMPLETE:
            pytest.skip(f"{how} does not prevent completion")
        assert record.t_birth == "UNAVAILABLE", how
        assert record.experience_count_final is None, how
        assert not record.first_experience, how
        assert not record.first_action, how
        assert record.birth_occurred is False, how

    def test_absent_declaration_is_blocked_not_failed(self):
        """Nothing was attempted, so nothing was violated."""
        record = run_ceremony(
            break_ledger(build_ready_ledger(), how="no_declaration"), _env(),
            mode=BirthMode.REAL,
        )
        assert record.gate["state"] == "BLOCKED"
        assert record.outcome is BirthOutcome.BLOCKED

    def test_digest_mismatch_is_failed_not_blocked(self):
        """A mismatch was detected, so it is a violation rather than an absence."""
        record = run_ceremony(
            break_ledger(build_ready_ledger(), how="digest_mismatch"), _env(),
            mode=BirthMode.REAL,
        )
        assert record.gate["state"] == "FAILED"

    def test_blocked_ceremony_never_reaches_the_environment(self):
        environment = _env()
        before = environment.snapshot().state_hash
        run_ceremony(break_ledger(build_ready_ledger(), how="no_declaration"),
                     environment, mode=BirthMode.REAL)
        assert environment.snapshot().state_hash == before

    def test_failed_ceremony_never_reaches_the_environment(self):
        environment = _env()
        before = environment.snapshot().state_hash
        run_ceremony(break_ledger(build_ready_ledger(), how="environment_corrupt"),
                     environment, mode=BirthMode.REAL)
        assert environment.snapshot().state_hash == before


# ---------------------------------------------------------------------------
# Mode restrictions
# ---------------------------------------------------------------------------

class TestModes:
    @pytest.mark.parametrize("mode", [BirthMode.SIMULATED, BirthMode.STUB])
    def test_non_real_modes_never_birth_even_with_a_ready_gate(self, mode):
        record = run_ceremony(build_ready_ledger(), _env(), mode=mode)
        assert record.birth_occurred is False
        assert record.t_birth == "UNAVAILABLE"
        assert record.outcome is BirthOutcome.BLOCKED

    def test_real_is_the_default_mode(self):
        """Defaulting to anything but REAL would make a test run a birth."""
        import inspect

        assert inspect.signature(run_ceremony).parameters["mode"].default \
            is BirthMode.REAL

    def test_fixture_is_labelled_and_cannot_pass_for_real(self):
        ledger = build_ready_ledger()
        assert ledger["fixture"] == FIXTURE_MARKER


# ---------------------------------------------------------------------------
# The happy path, against the synthetic gate
# ---------------------------------------------------------------------------

class TestSuccessfulCeremony:
    @pytest.fixture
    def record(self):
        return run_ceremony(build_ready_ledger(), _env(), mode=BirthMode.REAL)

    def test_ceremony_completes(self, record):
        assert record.outcome is BirthOutcome.COMPLETE
        assert record.birth_occurred is True

    def test_lifecycle_reaches_active_through_every_state(self, record):
        assert record.lifecycle == "ACTIVE"
        reached = [t["to"] for t in record.transitions]
        assert reached == ["CREATED", "ATTACHED", "ACTIVE"]
        assert all(t["authorized_by"] == "LABORATORY" for t in record.transitions)

    def test_identity_is_laboratory_issued(self, record):
        assert record.identity_issuer == "LABORATORY"
        assert record.subject_id
        assert record.identity_digest

    def test_creation_record_is_not_subject_authored(self, record):
        creation = record.creation_record
        assert creation["issued_by"] == "LABORATORY"
        assert creation["subject_authored"] is False
        assert creation["retroactively_editable_by_subject"] is False
        assert creation["content_hash"]

    def test_t_birth_is_set_once_and_after_activation(self, record):
        assert record.t_birth != "UNAVAILABLE"
        names = [e.name for e in record.events]
        assert names.index("lifecycle_advanced") < names.index("t_birth_established")
        assert names.count("t_birth_established") == 1

    def test_foundation_is_inherited_and_personal_experience_starts_at_zero(
        self, record,
    ):
        assert record.foundation["knowledge_origin"] == "INHERITED_PRETRAINED"
        assert record.foundation["personal_experience_count"] == 0
        assert record.foundation["converted_model_context_to_experience"] is False
        assert record.experience_count_initial == 0

    def test_exactly_one_interaction_occurs(self, record):
        assert record.experience_count_final == 1
        assert CONTROLLED_INTERACTION_COUNT == 1

    def test_exactly_one_experience_is_recorded(self, record):
        experience = record.first_experience
        assert experience["sequence_number"] == 1
        assert experience["subject_id"] == record.subject_id

    def test_experience_is_caused_by_the_environment_event(self, record):
        """The causal link points at the environment, not the model.

        A model completion is a proposal. If the experience's provenance names
        the proposal, the subject's biography would begin with its own intentions
        rather than with what happened to it.
        """
        experience = record.first_experience
        assert experience["provenance_reference"].startswith("env-event:")
        assert experience["action_id"] == record.first_result["action_id"]

    def test_first_action_is_model_output_not_an_action(self, record):
        action = record.first_action
        assert action["output_class"] == "MODEL_OUTPUT"
        assert action["output_is_an_intention"] is False
        assert action["output_is_a_belief"] is False
        assert action["output_is_a_goal"] is False
        assert action["is_model_output"] is True

    def test_consequence_comes_from_the_environment(self, record):
        consequence = record.first_consequence
        assert consequence["manufactured"] is False
        assert record.first_result["validation"] in {"ACCEPTED", "REJECTED"}

    def test_observation_carries_no_curriculum(self, record):
        observation = record.first_observation
        assert observation["curriculum_applied"] is False
        assert observation["object_meanings_supplied"] is False
        assert observation["passed_unlabelled"] is True

    def test_stop_reason_states_the_limit(self, record):
        assert "refused" in record.stop_reason.lower()
        assert "M014" not in record.stop_reason or "explicit" in record.stop_reason

    def test_record_declares_what_it_is_not(self, record):
        payload = record.to_dict()
        assert payload["what_this_is_not"]["consciousness"]
        assert payload["is_a_subject"] is True


# ---------------------------------------------------------------------------
# The single-interaction guard
# ---------------------------------------------------------------------------

class TestSingleInteractionGuard:
    def test_first_interaction_is_accepted(self):
        guarded = SingleInteractionEnvironment(_env())
        guarded.submit(_action())
        assert len(guarded.submitted) == 1

    def test_second_interaction_raises(self):
        guarded = SingleInteractionEnvironment(_env())
        guarded.submit(_action())
        with pytest.raises(SecondInteractionRefused):
            guarded.submit(_action())

    def test_refusal_is_recorded_on_the_guard(self):
        guarded = SingleInteractionEnvironment(_env())
        guarded.submit(_action())
        with pytest.raises(SecondInteractionRefused):
            guarded.submit(_action())
        assert len(guarded.refusals) == 1
        assert "interaction 2" in guarded.refusals[0]

    def test_third_interaction_also_raises(self):
        guarded = SingleInteractionEnvironment(_env())
        guarded.submit(_action())
        for _ in range(3):
            with pytest.raises(SecondInteractionRefused):
                guarded.submit(_action())

    def test_guard_delegates_reads_to_the_inner_environment(self):
        inner = _env()
        guarded = SingleInteractionEnvironment(inner)
        assert guarded.snapshot().state_hash == inner.snapshot().state_hash
        assert guarded.identity is inner.identity

    def test_guard_forwards_observation(self):
        guarded = SingleInteractionEnvironment(_env())
        assert guarded.observe().observation_id

    def test_ceremony_records_an_enforced_refusal(self):
        """The record's REFUSED claim must correspond to a real exception."""
        record = run_ceremony(build_ready_ledger(), _env(), mode=BirthMode.REAL)
        assert record.second_interaction.startswith("REFUSED")
        assert "interaction 2" in record.second_interaction

    def test_guard_failure_aborts_the_birth(self):
        """If the environment will not enforce the limit, there is no birth."""
        class Permissive:
            def snapshot(self, label=""):
                return _env().snapshot(label)

            def observe(self):
                return _env().observe()

            @property
            def identity(self):
                return _env().identity

            def submit(self, action):
                return None

        record = run_ceremony(build_ready_ledger(), Permissive(),
                              mode=BirthMode.REAL)
        # The permissive stand-in cannot validate, so the ceremony aborts before
        # reaching the stop; either way it must not report a completed birth.
        assert record.birth_occurred is False


def _action():
    from environment.environment import Action, Operation

    return Action(operation=Operation.OBSERVE, actor="LABORATORY")


# ---------------------------------------------------------------------------
# Adversarial cases
# ---------------------------------------------------------------------------

class TestAdversarial:
    def test_model_cannot_claim_identity(self):
        """A model self-assertion is not an identity issuance."""
        record = run_ceremony(
            break_ledger(build_ready_ledger(), how="subject_claims_identity"),
            _env(), mode=BirthMode.REAL,
        )
        assert record.birth_occurred is False
        assert record.outcome is BirthOutcome.ABORTED
        assert record.t_birth == "UNAVAILABLE"

    def test_identity_claim_is_refused_before_any_state_exists(self):
        """Screening runs ahead of issuance.

        Regression: screening after activation left a record with a T_birth and
        no completed birth -- the precise artifact the milestone forbids.
        """
        record = run_ceremony(
            break_ledger(build_ready_ledger(), how="subject_claims_identity"),
            _env(), mode=BirthMode.REAL,
        )
        assert record.lifecycle == "UNCREATED"
        assert not record.creation_record
        assert record.identity_issuer == ""

    @pytest.mark.parametrize("phrase", BANNED_CONTEXT_SUBSTRINGS)
    def test_banned_context_phrases_are_rejected(self, phrase):
        with pytest.raises(ValueError):
            assert_neutral_context(f"Here is your situation: {phrase}.")

    def test_neutral_context_is_accepted(self):
        assert_neutral_context(
            "state_hash=abc123 version=4 resources=2 entities=1"
        )

    def test_measurement_cannot_be_faked_from_a_real_ledger(self):
        """Overrides are private keys, so a real M012 writer cannot supply one."""
        ledger = build_ready_ledger()
        # A real ledger would carry this as a normal field, not a private one.
        ledger["environment_integrity"] = {"integrity": True}
        verdict = evaluate_birth_gate(ledger)
        states = {p.name: p.state for p in verdict.prerequisites}
        assert states["environment_integrity"] is GateState.BLOCKED

    def test_key_policy_is_not_required(self):
        """M013 revisits M009 and confirms: no subject key is provisioned."""
        policy = decide_key_policy()
        assert policy["decision"] == "NOT_REQUIRED"
        assert policy["provisioned"] is False
        assert policy["new_trust_model_invented"] is False
        assert policy["refused_for_the_subject"]

    def test_laboratory_keeps_control_the_subject_lacks(self):
        policy = decide_key_policy()
        assert "control credentials" in [
            item.lower() for item in policy["refused_for_the_subject"]
        ] or any("control" in item.lower()
                 for item in policy["refused_for_the_subject"])

    def test_aborted_marker_is_named(self):
        assert ABORTED == "ABORTED_BIRTH"

    def test_birth_occurred_requires_all_three_conditions(self):
        """A record with a T_birth alone is not a birth.

        Guarded because ``birth_occurred`` is the field a downstream reader will
        trust, and a record can carry a T_birth after an abort.
        """
        record = run_ceremony(build_ready_ledger(), _env(), mode=BirthMode.REAL)
        record.outcome = BirthOutcome.ABORTED
        assert record.t_birth != "UNAVAILABLE"
        assert record.birth_occurred is False


# ---------------------------------------------------------------------------
# This host
# ---------------------------------------------------------------------------

class TestThisHost:
    def test_this_host_has_no_deployment(self):
        """The gate blocks here, and that is the correct outcome."""
        from foundation.m012 import verify

        ledger = verify(scan_candidates=False).to_dict()
        record = run_ceremony(ledger, _env(), mode=BirthMode.REAL)
        assert record.gate["state"] == "BLOCKED"
        assert record.outcome is BirthOutcome.BLOCKED
        assert record.birth_occurred is False
        assert record.t_birth == "UNAVAILABLE"
        assert record.subject_id == ""

    def test_blocked_record_names_the_missing_prerequisites(self):
        from foundation.m012 import verify

        ledger = verify(scan_candidates=False).to_dict()
        record = run_ceremony(ledger, _env(), mode=BirthMode.REAL)
        blocking = [
            p["name"] for p in record.gate["prerequisites"]
            if p["state"] == "BLOCKED"
        ]
        assert "human_declaration" in blocking
        assert "real_inference" in blocking

    def test_blocked_record_performs_no_interaction(self):
        from foundation.m012 import verify

        ledger = verify(scan_candidates=False).to_dict()
        record = run_ceremony(ledger, _env(), mode=BirthMode.REAL)
        assert record.second_interaction == "NOT_ATTEMPTED"
        assert record.experience_count_final is None
