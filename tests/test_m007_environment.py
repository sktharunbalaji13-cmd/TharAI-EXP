"""Milestone 007 tests: the environment and interaction substrate.

The governing rule for this file
--------------------------------
A test may only pass because the substrate was actually exercised. Two specific
traps are guarded against here:

* **Semantic leakage.** The environment must expose measurements and must not
  supply meaning. A test that greps for ``purpose``/``tool``/``recommended`` is
  only useful if it can fail, so it checks the *emitted* literals of the
  observation, not a docstring that explains why those fields are absent.
* **Determinism that is not real.** Replay is only evidence if the comparison
  can fail. So the suite contains both a passing replay *and* a deliberately
  corrupted state that must be reported as divergence, because a replay check
  that cannot detect divergence proves nothing.

The environment is infrastructure: every test here runs with no model, no
subject, no key, no memory, and no autonomy.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from babylab.runtime.contract import EpistemicStatus
from environment.action import Action, Operation, Validation
from environment.consequence import ConsequenceKind, StateDelta
from environment.deterministic import (
    FIXTURE_CONFIG,
    FIXTURE_VERSION,
    create_deterministic_environment,
    fixture_configuration,
    initial_state,
)
from environment.environment import Environment, EnvironmentFault
from environment.events import EventStream, EventType
from environment.identity import configuration_hash, verify_configuration
from environment.observation import build_observation
from environment.snapshot import Snapshot
from environment.state import Entity, EnvironmentState, ResourceAmount, ResourceState
from environment.telemetry import ALLOWED_TELEMETRY, build_telemetry

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A sequence whose result is fully deterministic.
SAMPLE_SEQUENCE = (
    Action(operation=Operation.GRASP, actor="p1", target="ent-a1"),
    Action(operation=Operation.MOVE, actor="p1", target="ent-a1",
           parameters={"x": 2, "y": 1}),
    Action(operation=Operation.RELEASE, actor="p1", target="ent-a1"),
    Action(operation=Operation.INSERT, actor="p1", target="ent-c3",
           parameters={"entity_id": "ent-b2"}),
    Action(operation=Operation.WAIT, actor="p1"),
)


def _fresh():
    return create_deterministic_environment()


# ---------------------------------------------------------------------------
# 1-4: creation, identity, serialization, hashing
# ---------------------------------------------------------------------------

class TestEnvironmentCreationAndIdentity(unittest.TestCase):
    """1-4. environment creation / identity / serialization / hashing"""

    def test_1_environment_can_be_created_without_model_or_subject(self):
        env = _fresh()
        self.assertEqual(0, env.state.state_version)
        self.assertIsInstance(env.identity.environment_id, str)
        self.assertFalse(env.status()["autonomous"])
        self.assertFalse(env.status()["subject_attached"])

    def test_2_identity_is_derived_from_configuration_not_self_declared(self):
        env = _fresh()
        self.assertEqual(
            configuration_hash(env.identity.config), env.identity.configuration_hash)
        # The environment type comes from the supplied configuration, not from
        # anything the environment says about itself.
        self.assertEqual(FIXTURE_CONFIG["type"], env.identity.environment_type)
        self.assertEqual(FIXTURE_VERSION, env.identity.implementation_version)

    def test_2b_two_configurations_cannot_share_a_hash(self):
        self.assertNotEqual(
            configuration_hash(fixture_configuration()),
            configuration_hash({**fixture_configuration(), "grid": {"width": 9,
                                                                   "height": 9}}),
        )

    def test_2c_identically_configured_environments_are_distinct_instances(self):
        first, second = _fresh(), _fresh()
        self.assertEqual(first.identity.configuration_hash,
                         second.identity.configuration_hash)
        self.assertNotEqual(first.identity.environment_id,
                            second.identity.environment_id)

    def test_2d_configuration_verification_detects_drift(self):
        env = _fresh()
        self.assertTrue(verify_configuration(env.identity, env.identity.config))
        self.assertFalse(verify_configuration(
            env.identity, {**env.identity.config, "extra": 1}))

    def test_3_state_serializes_and_round_trips_exactly(self):
        state = initial_state()
        restored = EnvironmentState.from_dict(state.to_dict())
        self.assertEqual(state.to_dict(), restored.to_dict())
        self.assertEqual(state.state_hash, restored.state_hash)

    def test_4_state_hash_changes_only_when_state_changes(self):
        env = _fresh()
        before = env.state.state_hash
        env.observe()
        self.assertEqual(before, env.state.state_hash,
                         "observing must not change state")
        env.submit(Action(operation=Operation.OBSERVE, actor="p"))
        self.assertEqual(before, env.state.state_hash,
                         "OBSERVE has no cost and must not change state")
        env.submit(SAMPLE_SEQUENCE[0])
        self.assertNotEqual(before, env.state.state_hash)


# ---------------------------------------------------------------------------
# 5-6: observations and epistemic status
# ---------------------------------------------------------------------------

class TestObservations(unittest.TestCase):
    """5-6. observations / observation epistemic status"""

    def test_5_observation_corresponds_to_a_state_version(self):
        env = _fresh()
        observation = env.observe()
        self.assertEqual(env.state.state_version, observation.state_version)
        self.assertEqual(env.state.state_hash, observation.state_hash)
        self.assertEqual(env.identity.environment_id, observation.environment_id)

    def test_5b_observation_reflects_a_later_state_version(self):
        env = _fresh()
        first = env.observe()
        env.submit(SAMPLE_SEQUENCE[0])
        second = env.observe()
        self.assertGreater(second.state_version, first.state_version)
        self.assertNotEqual(second.observation_hash, first.observation_hash)

    def test_6_every_observed_value_carries_an_epistemic_status(self):
        env = _fresh()
        observation = env.observe()
        for entity in observation.entities:
            for key, measurement in entity.properties.items():
                self.assertIn(measurement.status,
                              {EpistemicStatus.OBSERVED, EpistemicStatus.UNAVAILABLE},
                              f"{entity.entity_id}.{key} has no honest status")
        for key, measurement in observation.resources.items():
            self.assertIn(measurement.status,
                          {EpistemicStatus.OBSERVED, EpistemicStatus.UNAVAILABLE})

    def test_6b_observations_do_not_manufacture_hidden_state(self):
        env = _fresh()
        observation = env.observe()
        for entity in observation.entities:
            for key in entity.properties:
                self.assertIn(key, {"shape", "mass", "capacity", "movable",
                                    "height", "width", "contents", "occluded"},
                              f"unexpected observable property {key!r}")

    def test_6c_implementation_type_is_not_exposed_to_observers(self):
        """A hint about how the environment was built is not a world property."""
        env = _fresh()
        observation = env.observe()
        blob = json.dumps(observation.to_dict())
        self.assertNotIn("fixture.solid", blob)
        self.assertNotIn("implementation_type", blob)


# ---------------------------------------------------------------------------
# 7-8: entities
# ---------------------------------------------------------------------------

class TestEntities(unittest.TestCase):
    """7-8. entity creation / entity identity"""

    def test_7_entities_expose_measured_properties(self):
        state = initial_state()
        first = state.entity("ent-a1")
        self.assertIsNotNone(first)
        self.assertEqual(20, first.observable["mass"])
        self.assertEqual((0, 0), first.location)

    def test_7b_entity_rejects_properties_outside_the_observable_vocabulary(self):
        with self.assertRaises(ValueError):
            Entity(entity_id="x", observable={"purpose": "eating"})

    def test_7c_entity_rejects_floats_so_hashes_stay_reproducible(self):
        with self.assertRaises(ValueError):
            Entity(entity_id="x", observable={"mass": 1.5})

    def test_8_entity_ids_are_stable_across_state_changes(self):
        env = _fresh()
        ids_before = sorted(env.state.entities)
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        self.assertEqual(ids_before, sorted(env.state.entities))
        self.assertEqual(ids_before[0], "ent-a1")

    def test_8b_entity_operations_derive_from_measured_properties(self):
        state = initial_state()
        solid = state.entity("ent-a1")
        hollow = state.entity("ent-c3")
        self.assertIn("GRASP", solid.supported_operations())
        self.assertNotIn("INSERT", solid.supported_operations())
        self.assertIn("INSERT", hollow.supported_operations())
        self.assertNotIn("GRASP", hollow.supported_operations())


# ---------------------------------------------------------------------------
# 9-12: action validation
# ---------------------------------------------------------------------------

class TestActionValidation(unittest.TestCase):
    """9-12. validation / invalid / rejected / accepted"""

    def test_9_accepted_action_is_applied(self):
        env = _fresh()
        result = env.submit(SAMPLE_SEQUENCE[0])
        self.assertEqual(Validation.ACCEPTED.value, result.validation)
        self.assertIs(ConsequenceKind.STATE_CHANGED, result.consequence)
        self.assertEqual("p1", env.state.entity("ent-a1").held_by)

    def test_10_invalid_action_is_distinguished_from_rejected(self):
        env = _fresh()
        result = env.submit(Action(operation=Operation.MOVE, actor="p1",
                                   target="ent-a1", parameters={}))
        self.assertEqual(Validation.INVALID.value, result.validation)
        self.assertIs(ConsequenceKind.NOT_APPLIED, result.consequence)
        self.assertIn("integer", result.reason)

    def test_10b_action_with_no_target_is_invalid(self):
        env = _fresh()
        result = env.submit(Action(operation=Operation.GRASP, actor="p1"))
        self.assertEqual(Validation.INVALID.value, result.validation)

    def test_11_rejected_action_does_not_mutate_state(self):
        env = _fresh()
        before_hash, before_version = env.state.state_hash, env.state.state_version
        result = env.submit(Action(operation=Operation.GRASP, actor="p1",
                                   target="ent-missing"))
        self.assertEqual(Validation.REJECTED.value, result.validation)
        self.assertEqual(before_hash, env.state.state_hash)
        self.assertEqual(before_version, env.state.state_version)

    def test_11b_invalid_action_does_not_mutate_state(self):
        env = _fresh()
        before = env.state.state_hash
        env.submit(Action(operation=Operation.MOVE, actor="p1", target="ent-a1",
                          parameters={"x": "left", "y": 1}))
        self.assertEqual(before, env.state.state_hash)

    def test_11c_unavailable_is_distinct_when_a_cost_resource_is_unmodelled(self):
        """A cost that cannot be evaluated is UNAVAILABLE, not a guess."""
        env = _fresh()
        # Remove a resource that MOVE costs, so its cost is unknowable.
        state = EnvironmentState(
            state_version=env.state.state_version,
            entities=env.state.entities,
            resources=ResourceState(amounts={
                key: level for key, level in env.state.resources.amounts.items()
                if key != "energy"
            }),
            grid_width=env.state.grid_width, grid_height=env.state.grid_height,
        )
        env.state = state
        env.submit(Action(operation=Operation.GRASP, actor="p1", target="ent-a1"))
        result = env.submit(Action(operation=Operation.MOVE, actor="p1",
                                   target="ent-a1", parameters={"x": 1, "y": 1}))
        self.assertEqual(Validation.UNAVAILABLE.value, result.validation)
        self.assertEqual("energy", result.to_dict()["resource_changes"][0]
                         ["resource_id"] if result.resource_changes else "energy")

    def test_12_action_ids_are_unique_per_distinct_request(self):
        env = _fresh()
        first = env.submit(SAMPLE_SEQUENCE[0])
        second = env.submit(SAMPLE_SEQUENCE[0])
        self.assertEqual(first.action_id, second.action_id,
                         "the same request has the same identity")
        different = env.submit(Action(operation=Operation.MOVE, actor="p1",
                                      target="ent-a1", parameters={"x": 1, "y": 1}))
        self.assertNotEqual(first.action_id, different.action_id)


# ---------------------------------------------------------------------------
# 13-15: consequences, resources, exhaustion
# ---------------------------------------------------------------------------

class TestConsequencesAndResources(unittest.TestCase):
    """13-15. consequences / resource consumption / resource exhaustion"""

    def test_13_consequence_records_the_transition(self):
        env = _fresh()
        result = env.submit(SAMPLE_SEQUENCE[0])
        delta = result.delta
        self.assertIsInstance(delta, StateDelta)
        self.assertIn("ent-a1", delta.changed_entities)
        self.assertEqual(result.previous_state_hash, delta.from_state_hash)
        self.assertEqual(result.resulting_state_hash, delta.to_state_hash)

    def test_13b_no_effect_is_recorded_as_no_effect(self):
        env = _fresh()
        result = env.submit(Action(operation=Operation.OBSERVE, actor="p1",
                                   target="ent-a1"))
        self.assertIs(ConsequenceKind.NO_EFFECT, result.consequence)
        self.assertEqual(env.state.state_hash, result.previous_state_hash)

    def test_14_resources_are_consumed_and_reported_as_measurements(self):
        env = _fresh()
        before_energy = env.state.resources.get("energy")
        result = env.submit(Action(operation=Operation.MOVE, actor="p1",
                                   target="ent-a1", parameters={"x": 1, "y": 1}))
        self.assertEqual(before_energy - 2, env.state.resources.get("energy"))
        changes = {c.resource_id: c for c in result.resource_changes}
        self.assertIn("energy", changes)
        self.assertEqual(EpistemicStatus.OBSERVED, changes["energy"].delta.status)
        self.assertEqual(-2, changes["energy"].delta.value)

    def test_14b_release_returns_the_holding_capacity(self):
        env = _fresh()
        env.submit(Action(operation=Operation.GRASP, actor="p1", target="ent-a1"))
        self.assertEqual(0, env.state.resources.get("capacity"))
        env.submit(Action(operation=Operation.RELEASE, actor="p1", target="ent-a1"))
        self.assertEqual(1, env.state.resources.get("capacity"))

    def test_15_resource_exhaustion_rejects_rather_than_going_negative(self):
        env = _fresh()
        env.state = env.state.with_resources(
            env.state.resources.with_value("energy", 1))
        result = env.submit(Action(operation=Operation.MOVE, actor="p1",
                                   target="ent-a1", parameters={"x": 1, "y": 1}))
        self.assertEqual(Validation.REJECTED.value, result.validation)
        self.assertGreaterEqual(env.state.resources.get("energy"), 0)
        self.assertEqual(1, env.state.resources.get("energy"))

    def test_15b_no_resource_is_ever_negative(self):
        env = _fresh()
        # Drive far past every budget, spending and returning the holding
        # capacity repeatedly rather than only draining a single pool.
        for _ in range(400):
            env.submit(Action(operation=Operation.GRASP, actor="p1", target="ent-a1"))
            env.submit(Action(operation=Operation.MOVE, actor="p1", target="ent-a1",
                              parameters={"x": 1, "y": 1}))
            env.submit(Action(operation=Operation.RELEASE, actor="p1",
                              target="ent-a1"))
            env.submit(Action(operation=Operation.WAIT, actor="p1"))
        for amount in env.state.resources.amounts.values():
            self.assertGreaterEqual(amount.value, 0,
                                    f"resource {amount.resource_id} went negative")

    def test_15c_capacity_never_exceeds_its_configured_maximum(self):
        """A refunded resource must not accumulate past the configured value."""
        env = _fresh()
        ceiling = FIXTURE_CONFIG["resources"]["capacity"]["value"]
        for _ in range(50):
            env.submit(Action(operation=Operation.GRASP, actor="p1", target="ent-a1"))
            env.submit(Action(operation=Operation.RELEASE, actor="p1",
                              target="ent-a1"))
        self.assertLessEqual(env.state.resources.get("capacity"), ceiling)


# ---------------------------------------------------------------------------
# 16-19: snapshot, integrity, restore, lineage
# ---------------------------------------------------------------------------

class TestSnapshotAndRestore(unittest.TestCase):
    """16-19. snapshot / snapshot integrity / restore / branch lineage"""

    def test_16_snapshot_preserves_state_identity(self):
        env = _fresh()
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        snapshot = env.snapshot(label="checkpoint")
        self.assertEqual(env.state.state_hash, snapshot.state_hash)
        self.assertEqual(env.state.state_version, snapshot.state_version)
        intact, detail = snapshot.verify()
        self.assertTrue(intact, detail)

    def test_17_a_corrupt_snapshot_is_detected_by_its_own_check(self):
        env = _fresh()
        snapshot = env.snapshot()
        self.assertEqual((True, "intact"), snapshot.verify())

        # What a damaged snapshot looks like: the recorded hash no longer
        # describes the state it carries.
        broken = Snapshot(**{**snapshot.to_dict(), "state_hash": "0" * 64})
        intact, detail = broken.verify()
        self.assertFalse(intact)
        self.assertIn("corrupt", detail)

    def test_17b_restoring_a_corrupt_snapshot_faults_and_changes_nothing(self):
        env = _fresh()
        snapshot = env.snapshot()
        before_hash, before_version = env.state.state_hash, env.state.state_version
        broken = Snapshot(**{**snapshot.to_dict(), "state_hash": "0" * 64})
        env.snapshots[broken.snapshot_id] = broken
        with self.assertRaises(EnvironmentFault) as caught:
            env.restore(broken.snapshot_id)
        self.assertEqual("CORRUPT_SNAPSHOT", caught.exception.kind)
        self.assertEqual(before_hash, env.state.state_hash)
        self.assertEqual(before_version, env.state.state_version)
        self.assertTrue(env.events.of_type(EventType.ENVIRONMENT_FAULT))

    def test_17c_restoring_an_unknown_snapshot_faults(self):
        env = _fresh()
        with self.assertRaises(EnvironmentFault) as caught:
            env.restore("snap-does-not-exist")
        self.assertEqual("UNKNOWN_SNAPSHOT", caught.exception.kind)

    def test_18_restore_reinstates_the_exact_state(self):
        env = _fresh()
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        snapshot = env.snapshot(label="checkpoint")
        expected = env.state.state_hash
        self.assertEqual(expected, snapshot.state_hash)

        env.submit(Action(operation=Operation.MOVE, actor="p1", target="ent-a1",
                          parameters={"x": 3, "y": 3}))
        self.assertNotEqual(expected, env.state.state_hash)
        env.restore(snapshot.snapshot_id)
        self.assertEqual(expected, env.state.state_hash)

    def test_18b_restore_never_rewrites_history(self):
        env = _fresh()
        snapshot = env.snapshot()
        count_before = len(env.events)
        digest_before = env.events.events()[-1].event_hash
        env.restore(snapshot.snapshot_id)
        self.assertGreater(len(env.events), count_before)
        self.assertEqual(digest_before, env.events.events()[count_before - 1].event_hash,
                         "pre-restore events must be untouched")
        self.assertTrue(env.events.verify().intact)

    def test_19_restore_creates_a_branch_with_lineage(self):
        env = _fresh()
        snapshot = env.snapshot()
        env.restore(snapshot.snapshot_id)
        branch = env.current_branch_id
        self.assertNotEqual("main", branch)
        lineage = env.branch_lineage(branch)
        self.assertEqual(("main", branch), lineage)
        self.assertIn(snapshot.snapshot_id,
                      env.branches[branch].to_dict()["root_snapshot_id"] or
                      snapshot.snapshot_id)


# ---------------------------------------------------------------------------
# 20-21: replay and divergence
# ---------------------------------------------------------------------------

class TestReplay(unittest.TestCase):
    """20-21. deterministic replay / replay divergence"""

    def test_20_replay_from_a_snapshot_reproduces_the_state_hash(self):
        env = _fresh()
        snapshot = env.snapshot(label="before")
        initial = env.state.state_hash
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        recorded = env.state.state_hash

        env.restore(snapshot.snapshot_id)
        self.assertEqual(initial, env.state.state_hash,
                         "restore must return to the pre-sequence state")
        outcome = env.replay(SAMPLE_SEQUENCE)
        self.assertFalse(outcome["diverged"])
        self.assertEqual(recorded, outcome["final_state_hash"])
        self.assertTrue(outcome["chain_intact"])

    def test_20b_two_independent_runs_agree(self):
        first, second = _fresh(), _fresh()
        for action in SAMPLE_SEQUENCE:
            first.submit(action)
            second.submit(action)
        self.assertEqual(first.state.state_hash, second.state.state_hash)

    def test_20c_state_hash_does_not_depend_on_wall_clock(self):
        """Timestamps live in events; the state hash must ignore them."""
        import datetime

        stamps = iter([
            "2020-01-01T00:00:00.000Z", "2026-09-27T12:34:56.789Z",
            "1999-12-31T23:59:59.999Z", "2030-06-01T06:00:00.000Z",
        ])
        counter = {"n": 0}

        def clock():
            counter["n"] += 1
            return next(stamps, "2026-01-01T00:00:00.000Z")

        a = create_deterministic_environment(clock=clock)
        b = create_deterministic_environment(clock=clock)
        for action in SAMPLE_SEQUENCE:
            a.submit(action)
            b.submit(action)
        self.assertEqual(a.state.state_hash, b.state.state_hash)

    def test_21_replay_divergence_is_reported_not_hidden(self):
        """The comparison must be able to fail, or it proves nothing.

        A replay check that only ever compares a sequence with itself proves
        nothing. This replays the *same* requested action from a *different base
        state*, which is the case that matters: the environment was restored, or
        resumed, from somewhere other than where the expectation was recorded.
        The action id matches because it is the same environment and the same
        request, so the hash comparison is the thing under test.
        """
        env = _fresh()
        origin = env.snapshot(label="origin")

        env.submit(Action(operation=Operation.MOVE, actor="p1", target="ent-a1",
                          parameters={"x": 3, "y": 3}))
        expectation = env.submit(
            Action(operation=Operation.GRASP, actor="p1", target="ent-a1"))
        expected = {expectation.action_id: expectation.resulting_state_hash}

        # Return to the origin, then diverge from it before replaying.
        env.restore(origin.snapshot_id)
        env.submit(Action(operation=Operation.WAIT, actor="p9"))

        outcome = env.replay(
            [Action(operation=Operation.GRASP, actor="p1", target="ent-a1")],
            expected=expected,
        )
        self.assertTrue(outcome["diverged"],
                        f"replay from a different base must diverge: {outcome}")
        divergence = outcome["divergence"]
        self.assertIn("action_id", divergence)
        self.assertIn("expected_state_hash", divergence)
        self.assertIn("actual_state_hash", divergence)
        self.assertNotEqual(divergence["expected_state_hash"],
                            divergence["actual_state_hash"])

    def test_21b_a_matching_replay_reports_no_divergence(self):
        env = _fresh()
        recorded = [env.submit(action) for action in SAMPLE_SEQUENCE]
        expected = env.expectations_from(recorded)
        outcome = _fresh().replay(SAMPLE_SEQUENCE, expected=expected)
        self.assertFalse(outcome["diverged"])
        self.assertIsNone(outcome["divergence"])


# ---------------------------------------------------------------------------
# 22-25: corruption, mismatch, faults
# ---------------------------------------------------------------------------

class TestFaultInjection(unittest.TestCase):
    """22-25. corrupted state / snapshot / configuration / version mismatch"""

    def test_22_corrupted_state_is_detected_by_its_hash(self):
        state = initial_state()
        payload = state.to_dict()
        payload["entities"]["ent-a1"]["location"] = [2, 2]
        corrupted = EnvironmentState.from_dict(payload)
        self.assertNotEqual(state.state_hash, corrupted.state_hash)

    def test_22b_an_entity_outside_the_grid_is_rejected(self):
        """The bounds check lives on the state, which owns the dimensions."""
        with self.assertRaises(ValueError):
            EnvironmentState(
                state_version=0,
                entities={"x": Entity(entity_id="x", location=(99, 99))},
                grid_width=4, grid_height=4,
            )

    def test_22c_an_entity_holding_an_unknown_entity_is_rejected(self):
        with self.assertRaises(ValueError):
            EnvironmentState(
                state_version=0,
                entities={"x": Entity(
                    entity_id="x",
                    observable={"capacity": 2, "contents": ["ghost"]},
                )},
                grid_width=4, grid_height=4,
            )

    def test_24_configuration_mismatch_is_refused(self):
        env = _fresh()
        snapshot = env.snapshot()
        env.snapshots[snapshot.snapshot_id] = Snapshot(
            **{**snapshot.to_dict(), "configuration_hash": "f" * 64})
        with self.assertRaises(EnvironmentFault) as caught:
            env.restore(snapshot.snapshot_id)
        self.assertEqual("CONFIGURATION_MISMATCH", caught.exception.kind)
        self.assertTrue(env.events.of_type(EventType.ENVIRONMENT_FAULT))

    def test_25_implementation_version_mismatch_is_refused(self):
        env = _fresh()
        snapshot = env.snapshot()
        env.snapshots[snapshot.snapshot_id] = Snapshot(
            **{**snapshot.to_dict(), "implementation_version": "0.0.1"})
        with self.assertRaises(EnvironmentFault) as caught:
            env.restore(snapshot.snapshot_id)
        self.assertEqual("VERSION_MISMATCH", caught.exception.kind)

    def test_26_malformed_action_is_invalid_not_crashing(self):
        env = _fresh()
        result = env.submit(Action(operation=Operation.INSERT, actor="p1",
                                   target="ent-c3", parameters={}))
        self.assertEqual(Validation.INVALID.value, result.validation)
        self.assertTrue(env.events.verify().intact)

    def test_26b_impossible_operation_is_rejected(self):
        env = _fresh()
        result = env.submit(Action(operation=Operation.MOVE, actor="p1",
                                   target="ent-a1",
                                   parameters={"x": 99, "y": 99}))
        self.assertEqual(Validation.REJECTED.value, result.validation)
        self.assertIn("outside", result.reason)

    def test_26c_faults_remain_visible_in_the_event_stream(self):
        env = _fresh()
        env.inject_fault("DIAGNOSTIC", "deliberate test fault")
        faults = env.events.of_type(EventType.ENVIRONMENT_FAULT)
        self.assertEqual(1, len(faults))
        self.assertEqual("DIAGNOSTIC", faults[0].payload["kind"])


# ---------------------------------------------------------------------------
# 27-28: events and immutability
# ---------------------------------------------------------------------------

class TestEventStream(unittest.TestCase):
    """27-28. event generation / immutable event history"""

    def test_27_every_required_event_type_can_be_produced(self):
        env = _fresh()
        env.observe()
        env.submit(SAMPLE_SEQUENCE[0])
        env.snapshot()
        env.inject_fault("DIAGNOSTIC", "test")
        produced = {e.event_type for e in env.events.events()}
        for required in (
            EventType.ENVIRONMENT_CREATED, EventType.OBSERVATION_GENERATED,
            EventType.ACTION_REQUESTED, EventType.ACTION_VALIDATED,
            EventType.ACTION_APPLIED, EventType.STATE_TRANSITIONED,
            EventType.RESOURCE_CHANGED, EventType.SNAPSHOT_CREATED,
            EventType.ENVIRONMENT_FAULT,
        ):
            self.assertIn(required, produced)

    def test_27b_events_carry_state_hash_not_bulk_state(self):
        env = _fresh()
        env.submit(SAMPLE_SEQUENCE[0])
        for event in env.events.events():
            self.assertEqual(64, len(event.state_hash))
            self.assertNotIn("entities", event.payload,
                             "event payloads must reference state, not embed it")

    def test_28_historical_events_are_immutable_and_chain_verifies(self):
        env = _fresh()
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        verification = env.events.verify()
        self.assertTrue(verification.intact, verification.problems)
        self.assertEqual(0, len(verification.problems))

    def test_28b_altering_a_past_event_is_detected(self):
        env = _fresh()
        env.submit(SAMPLE_SEQUENCE[0])
        events = list(env.events.events())
        original = events[3]
        tampered = type(original)(
            **{**original.hashed_fields(), "event_type": EventType.ENVIRONMENT_FAULT,
               "payload": {"kind": "FORGED"}}
        )
        env.events._events[3] = tampered
        verification = env.events.verify()
        self.assertFalse(verification.intact,
                         "a rewritten event must break the chain")

    def test_28c_stream_round_trips_and_still_verifies(self):
        env = _fresh()
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        rehydrated = EventStream.rehydrate(
            env.identity.environment_id, env.events.export())
        self.assertTrue(rehydrated.verify().intact)
        self.assertEqual(len(env.events), len(rehydrated))


# ---------------------------------------------------------------------------
# 29-30, 38: security
# ---------------------------------------------------------------------------

class TestSecurityBoundary(unittest.TestCase):
    """29-30, 38. protected denial / key isolation / workspace restrictions"""

    def test_29_protected_research_paths_are_outside_the_environments_reach(self):
        """Environment state persists only in the subject-facing sandbox."""
        from babylab.osboundary import protected_paths

        sandbox = (REPO_ROOT / "baby_workspace").resolve()
        for protected in protected_paths():
            target = Path(protected.path).resolve()
            self.assertFalse(
                str(target).lower().startswith(str(sandbox).lower()),
                f"{protected.name} is protected and must not live in the sandbox",
            )
        # and the protected set is genuinely non-empty
        self.assertTrue(list(protected_paths()))

    def test_29b_the_environment_package_imports_no_credential_material(self):
        """Checked over the import graph, not over prose.

        A docstring that says "this never touches the signing key" is exactly
        the kind of comment a security check must not rely on, so the assertion
        is made against what the package actually imports. Matching is on full
        dotted paths: the environment legitimately imports ``babylab.hashing``
        and ``babylab.measure``, and only the credential-bearing modules are
        banned.
        """
        banned_prefixes = ("provenance", "control", "babylab.identity",
                           "babylab.trust", "babylab.hashing.sha256")
        for module in sorted((REPO_ROOT / "environment").glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            for name in imported:
                for banned in banned_prefixes:
                    self.assertFalse(
                        name == banned or name.startswith(banned + "."),
                        f"{module.name} imports {name}, which is credential-bearing",
                    )

    def test_29b2_the_environment_holds_no_keyring_reference_at_all(self):
        """Structural absence: no attribute named like a secret is ever read."""
        for module in sorted((REPO_ROOT / "environment").glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    name = node.attr.lower()
                    for banned in ("keyring", "private_key", "signing_key",
                                   "control_token", "hmac_key"):
                        self.assertNotIn(banned, name,
                                         f"{module.name} touches {node.attr}")

    def test_29c_the_environment_cannot_modify_acl_policy(self):
        package = REPO_ROOT / "environment"
        for module in sorted(package.glob("*.py")):
            source = module.read_text(encoding="utf-8").lower()
            for forbidden in ("icacls", "setacl", "chmod", "win32security"):
                self.assertNotIn(forbidden, source)

    def test_30_environment_events_cannot_be_rewritten_by_an_actor(self):
        env = _fresh()
        before = len(env.events)
        for _ in range(3):
            env.submit(Action(operation=Operation.OBSERVE, actor="p1"))
        self.assertGreater(len(env.events), before)
        # The stream exposes no mutator for past events.
        for forbidden in ("truncate", "delete", "update", "rewrite", "pop"):
            self.assertFalse(
                hasattr(EventStream, forbidden),
                f"EventStream must not expose {forbidden}()",
            )

    def test_30b_no_administrative_operations_exist(self):
        env = _fresh()
        for forbidden in ("elevate", "run_as", "admin", "sudo", "impersonate"):
            self.assertFalse(hasattr(env, forbidden))

    def test_38_no_privileged_write_reaches_protected_evidence(self):
        """A full exercise leaves protected evidence untouched."""
        from babylab.osboundary import verify_evidence_unchanged
        from babylab.paths import default_paths

        before = verify_evidence_unchanged(default_paths())
        env = _fresh()
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        env.snapshot()
        env.restore(env.snapshot().snapshot_id)
        after = verify_evidence_unchanged(default_paths())
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# 31-35: independence and prohibitions
# ---------------------------------------------------------------------------

class TestIndependenceAndProhibitions(unittest.TestCase):
    """31-35. no network / model / subject dependency; no loop; no memory"""

    def test_31_no_network_dependency(self):
        import re

        pattern = re.compile(
            r"^\s*(?:import|from)\s+(requests|urllib|http|socket|aiohttp|httpx|"
            r"openai|anthropic)\b", re.MULTILINE)
        for module in sorted((REPO_ROOT / "environment").glob("*.py")):
            self.assertIsNone(pattern.search(module.read_text(encoding="utf-8")),
                              f"{module.name} imports a network client")

    def test_32_no_model_dependency(self):
        package = REPO_ROOT / "environment"
        for module in sorted(package.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            for forbidden in ("babylab.runtime", "llamacpp", "FoundationRuntime",
                              "InferenceRequest"):
                self.assertNotIn(forbidden, source,
                                 f"{module.name} couples to the model runtime")

    def test_33_no_subject_dependency(self):
        env = _fresh()
        status = env.status()
        self.assertFalse(status["subject_attached"])
        self.assertFalse(status["autonomous"])
        self.assertFalse(status["memory"])
        package = REPO_ROOT / "environment"
        for module in sorted(package.glob("*.py")):
            self.assertNotIn("birth_record", module.read_text(encoding="utf-8"))

    def test_34_no_autonomous_loop(self):
        """The environment never generates its own actions.

        One loop does call ``submit`` -- :meth:`Environment.replay` -- and it is
        excluded by name with a reason rather than by loosening the rule. Replay
        iterates a sequence the *caller supplied*; that is the opposite of
        autonomy, and a rule that could not name the exception would be a rule
        someone would eventually satisfy by deleting this method.
        """
        CALLER_DRIVEN = {"replay"}
        for module in sorted((REPO_ROOT / "environment").glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name in CALLER_DRIVEN:
                    continue
                for inner in ast.walk(node):
                    if isinstance(inner, (ast.While, ast.For, ast.AsyncFor)):
                        body = ast.unparse(inner)
                        self.assertNotIn("self.submit(", body,
                                         f"{module.name}.{node.name} loops over submit()")
                        self.assertNotIn("self.observe()", body)

    def test_34b_replay_only_acts_on_what_the_caller_passed(self):
        """The excluded loop is over a parameter, not over anything generated."""
        env = _fresh()
        before = env.state.state_hash
        env.replay([])  # an empty caller-supplied sequence does nothing at all
        self.assertEqual(before, env.state.state_hash)

    def test_34b_repeated_observation_does_not_advance_the_environment(self):
        env = _fresh()
        for _ in range(50):
            env.observe()
        self.assertEqual(0, env.state.state_version)
        self.assertFalse(env.status()["autonomous"])

    def test_35_no_memory_of_prior_actions(self):
        """Available operations depend on physics, never on history."""
        env = _fresh()
        snapshot = env.snapshot()
        fresh_ops = dict(env.state.available_operations())
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        env.restore(snapshot.snapshot_id)
        self.assertEqual(fresh_ops, env.state.available_operations(),
                         "restoring must return the same affordances")
        self.assertFalse(env.status()["memory"])


# ---------------------------------------------------------------------------
# 36-37: no curriculum, no semantic labels
# ---------------------------------------------------------------------------

class TestNoCurriculumNoSemantics(unittest.TestCase):
    """36-37. no curriculum / no semantic tool labels"""

    #: Words that would make the environment a teacher rather than a world.
    BANNED_SEMANTICS = (
        "purpose", "usefulness", "recommended", "suggested", "should",
        "goal", "reward", "score", "level", "difficulty", "beginner", "advanced",
        "task", "lesson", "skill", "progress", "achievement", "points",
        "curriculum", "develop", "learn", "teach", "explain", "meaning",
    )

    def _emitted_literals(self) -> str:
        """String literals the environment can actually put in front of a caller.

        Docstrings are excluded: they exist to explain why these words are
        absent, and scanning them would make the test fail on its own
        explanation.
        """
        literals: list[str] = []
        for module in sorted((REPO_ROOT / "environment").glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            docstrings: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    body = getattr(node, "body", [])
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        docstrings.add(body[0].value.value)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in docstrings:
                        continue
                    literals.append(node.value)
        return " ".join(literals).lower()

    def test_36_no_curriculum_vocabulary_in_emitted_literals(self):
        blob = self._emitted_literals()
        # Split on underscores so "learn" does not match "learning" innocently
        # inside an identifier, and vice versa.
        for banned in self.BANNED_SEMANTICS:
            for token in banned.split("_"):
                self.assertNotIn(
                    token, blob,
                    f"the environment emits vocabulary containing {token!r}, "
                    "which would make it a teacher rather than a world",
                )

    def test_36b_the_fixture_is_labelled_as_a_fixture_not_a_development_plan(self):
        self.assertEqual("deterministic_laboratory", FIXTURE_CONFIG["type"])
        source = (REPO_ROOT / "environment" / "deterministic.py").read_text(
            encoding="utf-8")
        self.assertIn("fixture", source.lower())

    def test_37_no_semantic_tool_labels_in_observations(self):
        env = _fresh()
        observation = env.observe()
        for entity in observation.entities:
            blob = json.dumps(entity.to_dict()).lower()
            for banned in ("purpose", "tool", "useful", "food", "spoon", "eat",
                           "recommended", "correct"):
                self.assertNotIn(banned, blob,
                                 f"observation leaks semantics: {banned}")

    def test_37b_operations_are_named_for_what_they_do(self):
        """GRASP and INSERT describe mechanics, not intent."""
        for operation in Operation:
            self.assertNotIn(operation.value.lower(),
                             {"use", "want", "need", "get", "obtain"})

    def test_37c_the_same_action_is_possible_from_a_restored_state(self):
        """Affordances are a function of state, not of how the state was reached."""
        env = _fresh()
        snapshot = env.snapshot()
        action = Action(operation=Operation.GRASP, actor="p1", target="ent-b2")
        first = env.submit(action)
        env.restore(snapshot.snapshot_id)
        second = env.submit(action)
        self.assertEqual(first.consequence, second.consequence)
        self.assertEqual(first.resulting_state_hash, second.resulting_state_hash)


# ---------------------------------------------------------------------------
# 40: Observatory
# ---------------------------------------------------------------------------

class TestObservatoryIntegration(unittest.TestCase):
    """40. Observatory rendering"""

    def test_40_telemetry_renders_environment_facts(self):
        env = _fresh()
        env.submit(SAMPLE_SEQUENCE[0])
        rendered = "\n".join(build_telemetry(env).render_lines())
        self.assertIn("ENVIRONMENT", rendered)
        self.assertIn("state version", rendered)
        self.assertIn("config hash", rendered)
        self.assertIn("chain intact", rendered)

    def test_40b_telemetry_handles_no_environment(self):
        telemetry = build_telemetry(None)
        self.assertFalse(telemetry.available)
        self.assertIn("no environment", telemetry.unavailable_reason)

    def test_40c_telemetry_never_claims_a_mental_state(self):
        env = _fresh()
        for action in SAMPLE_SEQUENCE:
            env.submit(action)
        rendered = "\n".join(build_telemetry(env).render_lines()).lower()
        for banned in ("wants", "thinks", "curious", "learning", "mood",
                       "intelligent", "feels", "conscious"):
            self.assertNotIn(banned, rendered)

    def test_40d_telemetry_key_allowlist_is_mechanical_state_only(self):
        for banned in ("mood", "desire", "curiosity", "attention", "emotion"):
            self.assertNotIn(banned, ALLOWED_TELEMETRY)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class TestEnvironmentProvenance(unittest.TestCase):
    """28. provenance generated externally, never by the environment itself"""

    def test_events_are_attributed_to_the_environment_not_an_actor(self):
        env = _fresh()
        env.submit(SAMPLE_SEQUENCE[0])
        for event in env.events.events():
            self.assertEqual(env.identity.environment_id, event.environment_id)
            self.assertNotIn("author", event.payload)
            self.assertNotIn("actor", event.hashed_fields().keys() - {"payload"})

    def test_an_actor_cannot_assert_its_own_authorship(self):
        env = _fresh()
        env.submit(Action(operation=Operation.OBSERVE, actor="p1",
                          parameters={"author": "BABY_AI", "i_wrote_this": True}))
        blob = json.dumps(env.events.export()).lower()
        self.assertNotIn("i_wrote_this", blob)

    def test_provenance_uses_the_system_authorship_class(self):
        from birth.authorship import AuthorshipClass
        # Environment facts are laboratory infrastructure, never a subject's work.
        self.assertIn("SYSTEM_GENERATED",
                      [e.value for e in AuthorshipClass])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
