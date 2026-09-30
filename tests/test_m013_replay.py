"""Tests for M013 replay.

The distinction under test is that ``MODEL_OUTPUT_REPLAY`` and ``ENVIRONMENT_REPLAY``
answer different questions, and that a missing model produces ``UNVERIFIABLE`` rather
than a quiet pass. A replay that reports CONFIRMED because it found nothing to
contradict is worse than no replay, because it manufactures assurance.
"""

from __future__ import annotations

from birth.ceremony13 import BirthMode, run_ceremony
from birth.fixture13 import build_ready_ledger
from birth.replay13 import (
    ReplayVerdict,
    replay_environment,
    replay_model_output,
)
from environment.deterministic import create_deterministic_environment


def _completed_record():
    return run_ceremony(
        build_ready_ledger(), create_deterministic_environment(),
        mode=BirthMode.REAL,
    ).to_dict()


class TestModelOutputReplay:
    def test_blocked_birth_is_unverifiable_not_confirmed(self):
        from foundation.m012 import verify

        record = run_ceremony(
            verify(scan_candidates=False).to_dict(),
            create_deterministic_environment(), mode=BirthMode.REAL,
        ).to_dict()
        report = replay_model_output(record)
        assert report.verdict is ReplayVerdict.UNVERIFIABLE
        assert "did not complete" in report.note

    def test_missing_reprompt_is_unverifiable(self):
        """Recording an output is not reproducing it."""
        report = replay_model_output(_completed_record())
        assert report.verdict is ReplayVerdict.UNVERIFIABLE
        assert "not re-derived" in report.note

    def test_matching_reproposal_is_confirmed(self):
        record = _completed_record()
        expected = record["first_action"]["operation"]

        class Proposal:
            action = type("A", (), {"operation": expected})()

        report = replay_model_output(record, propose_again=lambda obs: Proposal())
        assert report.verdict is ReplayVerdict.CONFIRMED

    def test_differing_reproposal_is_contradicted(self):
        """The same input yielding a different proposal is a real contradiction."""
        report = replay_model_output(
            _completed_record(),
            propose_again=lambda obs: type(
                "P", (), {"action": type("A", (), {"operation": "GRASP"})()})(),
        )
        assert report.verdict is ReplayVerdict.CONTRADICTED

    def test_raising_reprompt_is_contradicted(self):
        def boom(observation):
            raise RuntimeError("the runtime was not available")

        report = replay_model_output(_completed_record(), propose_again=boom)
        assert report.verdict is ReplayVerdict.CONTRADICTED


def _same_environment_as(record):
    """Rebuild the environment the birth was recorded against.

    The default factory derives a fresh environment id per call, so a legitimate
    replay has to be handed an environment carrying the *recorded* identity. The
    id is passed into the factory rather than assigned afterwards, because the
    identity is frozen -- which is itself worth having to work around.
    """
    from environment.deterministic import create_deterministic_environment

    return create_deterministic_environment(
        environment_id=record["creation_record"]["environment_id"],
    )


class TestEnvironmentReplay:
    def test_blocked_birth_leaves_the_environment_unreplayed(self):
        from foundation.m012 import verify

        environment = create_deterministic_environment()
        before = environment.snapshot().state_hash
        record = run_ceremony(
            verify(scan_candidates=False).to_dict(), environment,
            mode=BirthMode.REAL,
        ).to_dict()
        report = replay_environment(record, environment=environment)
        assert report.verdict is ReplayVerdict.UNVERIFIABLE
        assert environment.snapshot().state_hash == before

    def test_missing_environment_is_unverifiable(self):
        report = replay_environment(_completed_record())
        assert report.verdict is ReplayVerdict.UNVERIFIABLE

    def test_a_different_environment_is_contradicted(self):
        """A different world that happens to start identically is still another world.

        The state hash alone cannot tell these apart -- two fresh environments
        share an initial state hash -- so the identity check is what refuses this.
        """
        record = _completed_record()
        other = create_deterministic_environment(
            environment_id="env.different", created_at="1970-01-02T00:00:00.000Z",
        )
        assert other.snapshot().state_hash == \
            record["creation_record"]["environment_initial_state_hash"]
        report = replay_environment(record, environment=other)
        assert report.verdict is ReplayVerdict.CONTRADICTED
        assert "another world" in report.checks[0].detail

    def test_state_drift_is_contradicted(self):
        """Correct environment, but no longer in the recorded state."""
        record = _completed_record()
        drifted = _same_environment_as(record)
        from environment.environment import Action, Operation

        drifted.submit(Action(operation=Operation.WAIT, actor="LABORATORY"))
        assert drifted.snapshot().state_hash != \
            record["creation_record"]["environment_initial_state_hash"]
        report = replay_environment(record, environment=drifted)
        assert report.verdict is ReplayVerdict.CONTRADICTED
        assert "not in the state the birth was recorded" in report.checks[1].detail

    def test_same_environment_reproduces_the_event(self):
        record = _completed_record()
        report = replay_environment(record, environment=_same_environment_as(record))
        assert report.verdict is ReplayVerdict.CONFIRMED
        claims = {c.claim for c in report.checks}
        assert "the replay environment is the recorded environment" in claims
        assert "the same proposal yields the same validation" in claims

    def test_replay_mints_no_subject(self):
        """Replay is a read of existing evidence, never a second birth."""
        record = _completed_record()
        replay_environment(record, environment=_same_environment_as(record))
        assert record["birth_occurred"] is True
        assert record["experience_count_final"] == 1
        assert record["second_interaction"].startswith("REFUSED")

    def test_worst_verdict_wins(self):
        """One contradiction must not be averaged away by a passing check."""
        record = _completed_record()
        report = replay_environment(
            record,
            environment=create_deterministic_environment(
                environment_id="env.different"),
        )
        assert report.verdict is ReplayVerdict.CONTRADICTED
        assert report.contradicted


class TestReplaySeparation:
    def test_the_two_replays_report_their_own_kind(self):
        record = _completed_record()
        model = replay_model_output(record)
        environment = replay_environment(
            record, environment=create_deterministic_environment(),
        )
        assert model.replay_kind == "MODEL_OUTPUT_REPLAY"
        assert environment.replay_kind == "ENVIRONMENT_REPLAY"
        assert model.verdict is not environment.verdict

    def test_a_confirmed_environment_does_not_vouch_for_the_model(self):
        """The whole point of separating them: the model was never re-prompted."""
        record = _completed_record()
        environment_report = replay_environment(
            record, environment=_same_environment_as(record),
        )
        model_report = replay_model_output(record)
        assert environment_report.verdict is ReplayVerdict.CONFIRMED
        assert model_report.verdict is ReplayVerdict.UNVERIFIABLE

    def test_reports_are_serialisable(self):
        record = _completed_record()
        for report in (
            replay_model_output(record),
            replay_environment(
                record, environment=_same_environment_as(record),
            ),
        ):
            payload = report.to_dict()
            assert payload["verdict"] in {"CONFIRMED", "CONTRADICTED", "UNVERIFIABLE"}
            assert payload["checks"]
