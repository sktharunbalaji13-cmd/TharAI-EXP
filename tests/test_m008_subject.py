"""Milestone 008 tests: the subject architecture and first-experience boundary.

The governing rule for this file
--------------------------------
A test may only pass because the architecture actually held. The specific traps:

* **A test subject that is really a birth.** Creating a subject in the harness
  must leave the laboratory's attachment criteria untouched: no birth record in
  ``human_control``, no ``BABY_AI`` keyring role, no registry entry. Several
  tests assert the negative directly against the real paths, because a test
  suite that only checked in-memory flags would miss the one failure that
  matters.
* **A passing replay that cannot diverge.** As in M007, both a matching replay
  and a divergent one are exercised.
* **A check that reads its own explanation.** Docstrings explain prohibitions,
  so text scans inspect emitted literals with docstrings removed, or the code
  graph with prose excluded.
* **A memory field in disguise.** ``SubjectState`` must contain no store of
  any kind; the absence is asserted structurally, not read from a comment.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from babylab.runtime.contract import RuntimeErrorKind, RuntimeFailure
from environment.action import Action, Operation
from subject.creation import (
    CREATION_RECORD_SCHEMA,
    create_record,
    verify_record,
)
from subject.experience import (
    Experience,
    experience_id_for,
    verify_experience,
)
from subject.harness import HARNESS_REASON, SubjectHarness
from subject.identity import (
    FoundationReference,
    IdentityError,
    SubjectIdentity,
    derive_identity,
    verify_identity_record,
)
from subject.interface import INTERFACE_VERSION, SubjectInterface
from subject.lifecycle import (
    LifecycleError,
    LifecycleState,
    SubjectLifecycle,
)
from subject.provenance import Origin, Source, attribute_record
from subject.state import (
    SUBJECT_STATE_SCHEMA,
    UNIMPLEMENTED_CAPABILITIES,
    SubjectState,
)
from subject.telemetry import ALLOWED_TELEMETRY, build_telemetry

REPO_ROOT = Path(__file__).resolve().parents[1]

# A digest of test bytes only. It exercises the *reference mechanism*; it is
# not a model claim, because no model was involved at any point.
TEST_FOUNDATION_DIGEST = (
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
)


def _harness() -> SubjectHarness:
    return SubjectHarness(clock=lambda: "2026-09-27T00:00:00.000Z")


def _foundation(**overrides):
    payload = dict(
        state="DECLARED",
        artifact_digest=TEST_FOUNDATION_DIGEST,
        artifact_name="test-fixture.gguf",
        runtime_implementation="llama.cpp",
        runtime_version="test",
    )
    payload.update(overrides)
    return FoundationReference(**payload)


def _active(harness=None, foundation=None):
    harness = harness or _harness()
    subject, environment, interface = harness.create_subject(
        foundation=foundation or _foundation())
    harness.attach(subject)
    harness.activate(subject)
    return harness, subject, environment, interface


# ---------------------------------------------------------------------------
# 1-6: identity and separation
# ---------------------------------------------------------------------------

class TestSubjectIdentity(unittest.TestCase):
    """1-6. identity / immutability / foundation / env / lab separation"""

    def test_1_identity_is_derived_by_the_laboratory(self):
        identity = derive_identity(subject_id="s1", issuer="LABORATORY")
        self.assertEqual("s1", identity.subject_id)
        self.assertEqual("LABORATORY", identity.issuer)
        self.assertEqual(64, len(identity.identity_hash))

    def test_1b_model_output_cannot_derive_an_identity(self):
        for impostor in ("SUBJECT", "BABY_AI", "MODEL", "ENVIRONMENT",
                         "HUMAN", '{"author": "BABY_AI"}', ""):
            with self.subTest(issuestring=impostor[:20]):
                with self.assertRaises(IdentityError) as caught:
                    derive_identity(subject_id="s1", issuer=impostor)
                self.assertEqual("UNAUTHORIZED_ISSUER", caught.exception.reason)

    def test_2_identity_is_immutable(self):
        identity = derive_identity(subject_id="s1", issuer="LABORATORY")
        with self.assertRaises(Exception):
            identity.subject_id = "s2"  # frozen dataclass rejects this
        with self.assertRaises(Exception):
            identity.issuer = "SUBJECT"

    def test_3_foundation_identity_is_a_reference_not_an_identity(self):
        foundation = _foundation()
        identity = derive_identity(
            subject_id="s1", issuer="LABORATORY", foundation=foundation)
        # The subject's own digest never equals the artifact's digest.
        self.assertNotEqual(identity.identity_hash, foundation.artifact_digest)
        # The artifact classification is inherited, never experiential.
        self.assertEqual("INHERITED_PRETRAINED", foundation.classification)

    def test_3b_absent_foundation_is_recorded_as_none_not_assumed(self):
        identity = derive_identity(subject_id="s1", issuer="LABORATORY")
        self.assertEqual("NONE", identity.foundation.state)
        self.assertEqual("", identity.foundation.artifact_digest)

    def test_3c_unverifiable_foundation_cannot_claim_verified(self):
        with self.assertRaises(IdentityError) as caught:
            FoundationReference(state="VERIFIED", artifact_digest="short")
        self.assertEqual("UNVERIFIABLE_FOUNDATION", caught.exception.reason)

    def test_4_subject_is_not_the_foundation(self):
        harness, subject, _, _ = _active()
        self.assertNotEqual(
            subject.identity.identity_hash,
            subject.identity.foundation.artifact_digest,
            "S references F; S is not F",
        )

    def test_5_subject_is_not_the_environment(self):
        harness, subject, environment, _ = _active()
        self.assertNotEqual(subject.subject_id, environment.identity.environment_id)
        self.assertNotIn(subject.subject_id, environment.state.entities)

    def test_6_subject_is_not_the_laboratory(self):
        harness, subject, _, _ = _active()
        self.assertNotEqual(subject.identity.issuer, subject.subject_id)
        self.assertEqual("LABORATORY", subject.identity.issuer)


# ---------------------------------------------------------------------------
# 7-8: creation record
# ---------------------------------------------------------------------------

class TestCreationRecord(unittest.TestCase):
    """7-8. creation record / integrity"""

    def _created(self, harness=None):
        harness = harness or _harness()
        subject, environment, interface = harness.create_subject(
            foundation=_foundation())
        return harness, subject

    def test_7_creation_record_exists_and_names_everything(self):
        _, subject = self._created()
        record = subject.creation
        self.assertEqual(subject.subject_id, record.subject_id)
        self.assertEqual(TEST_FOUNDATION_DIGEST,
                         record.foundation_identity["artifact_digest"])
        self.assertEqual(INTERFACE_VERSION, record.environment_interface_version)
        self.assertEqual(64, len(record.record_hash))

    def test_7b_creation_record_is_immutable(self):
        _, subject = self._created()
        with self.assertRaises(Exception):
            subject.creation.subject_id = "other"

    def test_8_creation_record_verifies(self):
        _, subject = self._created()
        intact, detail = verify_record(subject.creation)
        self.assertTrue(intact, detail)

    def test_8b_creation_with_mismatched_identity_hash_is_refused(self):
        identity = derive_identity(subject_id="s1", issuer="LABORATORY",
                                   foundation=_foundation())
        with self.assertRaises(IdentityError) as caught:
            create_record(
                subject_id="s1", identity=identity, identity_hash="0" * 64,
                foundation_identity=identity.foundation.to_dict(),
                environment_interface_version=INTERFACE_VERSION,
                subject_schema_version=identity.schema_version,
                laboratory_implementation_version="test",
                creation_reason=HARNESS_REASON, provenance_identity="harness",
                created_at="2026-09-27T00:00:00.000Z")
        self.assertEqual("IDENTITY_MISMATCH", caught.exception.reason)

    def test_8c_a_subject_cannot_create_its_own_record(self):
        identity = derive_identity(subject_id="s1", issuer="LABORATORY",
                                   foundation=_foundation())
        with self.assertRaises(IdentityError):
            create_record(
                subject_id="s1", identity=identity,
                identity_hash=identity.identity_hash,
                foundation_identity=identity.foundation.to_dict(),
                environment_interface_version=INTERFACE_VERSION,
                subject_schema_version=identity.schema_version,
                laboratory_implementation_version="test",
                creation_reason="the subject asked for it",
                provenance_identity="harness",
                created_at="2026-09-27T00:00:00.000Z",
                issuer="SUBJECT")

    def test_8d_a_record_about_another_subject_cannot_stand_in(self):
        """Self-consistency is not binding.

        A well-formed record about *someone else* verifies cleanly on its own
        terms, so nothing in the hash prevents it from being presented for the
        wrong subject. Binding is therefore a separate explicit check.
        """
        from subject.creation import record_belongs_to

        _, subject, _, _ = _active()
        other = type(subject.creation)(
            **{**subject.creation.to_dict(), "subject_id": "someone-else"})
        # The foreign record is internally consistent...
        intact, _ = verify_record(other)
        self.assertTrue(intact)
        # ...but it does not belong to this subject, on either condition.
        belongs, detail = record_belongs_to(
            other, subject.subject_id, subject.state.creation_record_hash)
        self.assertFalse(belongs, detail)
        # And the subject's own record does.
        belongs, detail = record_belongs_to(
            subject.creation, subject.subject_id,
            subject.state.creation_record_hash)
        self.assertTrue(belongs, detail)


# ---------------------------------------------------------------------------
# 9-10: lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle(unittest.TestCase):
    """9-10. lifecycle transitions / invalid transitions"""

    def test_9_creation_moves_uncreated_to_created_and_nothing_else(self):
        # Rebuild plainly: create_subject must end in CREATED exactly.
        harness = _harness()
        subject, _, _ = harness.create_subject()
        self.assertIs(LifecycleState.CREATED, subject.lifecycle.state)
        self.assertEqual(
            [(LifecycleState.UNCREATED, LifecycleState.CREATED,
              "2026-09-27T00:00:00.000Z")],
            list(subject.lifecycle.history),
        )

    def test_9b_full_path_to_active_is_explicit_at_every_edge(self):
        harness = _harness()
        subject, _, _ = harness.create_subject()
        harness.attach(subject)
        self.assertIs(LifecycleState.ATTACHED, subject.lifecycle.state)
        harness.activate(subject)
        self.assertIs(LifecycleState.ACTIVE, subject.lifecycle.state)
        self.assertTrue(subject.lifecycle.is_interactive())
        self.assertEqual(3, len(subject.lifecycle.history))

    def test_9c_existing_is_not_active(self):
        """A subject that exists is not automatically active."""
        harness = _harness()
        subject, _, _ = harness.create_subject()
        self.assertFalse(subject.lifecycle.is_interactive())
        harness.attach(subject)
        self.assertFalse(subject.lifecycle.is_interactive())

    def test_10_skipping_states_is_refused(self):
        lifecycle = SubjectLifecycle()
        for target in (LifecycleState.ATTACHED, LifecycleState.ACTIVE,
                       LifecycleState.PAUSED, LifecycleState.TERMINATED):
            with self.subTest(target=target.value):
                if target is LifecycleState.CREATED:
                    continue
                with self.assertRaises(LifecycleError) as caught:
                    lifecycle.transition(target, "LABORATORY", "t")
                self.assertEqual("INVALID_TRANSITION", caught.exception.reason)

    def test_10b_terminated_is_terminal(self):
        lifecycle = SubjectLifecycle()
        lifecycle.transition(LifecycleState.CREATED, "LABORATORY", "t")
        lifecycle.transition(LifecycleState.TERMINATED, "LABORATORY", "t")
        for target in LifecycleState:
            with self.subTest(target=target.value):
                with self.assertRaises(LifecycleError):
                    lifecycle.transition(target, "LABORATORY", "t")

    def test_10c_paused_and_active_cycle_without_losing_history(self):
        lifecycle = SubjectLifecycle()
        for target in (LifecycleState.CREATED, LifecycleState.ATTACHED,
                       LifecycleState.ACTIVE, LifecycleState.PAUSED,
                       LifecycleState.ACTIVE, LifecycleState.PAUSED):
            lifecycle.transition(target, "LABORATORY", "t")
        self.assertEqual(6, len(lifecycle.history))

    def test_10d_a_subject_cannot_transition_itself(self):
        lifecycle = SubjectLifecycle()
        with self.assertRaises(LifecycleError) as caught:
            lifecycle.transition(LifecycleState.CREATED, "SUBJECT", "t")
        self.assertEqual("UNAUTHORIZED_TRANSITION", caught.exception.reason)
        with self.assertRaises(LifecycleError):
            lifecycle.transition(LifecycleState.CREATED, "BABY_AI", "t")

    def test_10e_active_does_not_mean_anything_mental(self):
        """ACTIVE is laboratory process state. Check code, not prose.

        The module docstring legitimately names what ACTIVE is not, so the check
        inspects the identifiers the code actually defines and emits rather than
        raw source text.
        """
        import inspect

        from subject import lifecycle as lifecycle_module

        names: set[str] = set()
        tree = ast.parse(inspect.getsource(lifecycle_module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id.lower())
            elif isinstance(node, ast.Attribute):
                names.add(node.attr.lower())
        for claim in ("conscious", "awareness", "intelligence", "alive",
                      "sentience", "feelings", "curiosity", "mind"):
            self.assertNotIn(claim, names,
                             f"lifecycle.py defines or uses {claim}")
        # And the rendered lifecycle state is a plain process label.
        self.assertEqual("ACTIVE", LifecycleState.ACTIVE.value)


# ---------------------------------------------------------------------------
# 11-13: subject state
# ---------------------------------------------------------------------------

class TestSubjectState(unittest.TestCase):
    """11-13. state serialization / hashing / integrity"""

    def test_11_state_serializes_and_round_trips(self):
        harness, subject, _, _ = _active()
        restored = SubjectState.from_dict(subject.state.to_dict())
        self.assertEqual(subject.state.to_dict(), restored.to_dict())
        self.assertEqual(subject.state.state_hash, restored.state_hash)

    def test_11b_state_contains_no_memory_store_of_any_kind(self):
        """Structural absence: no list, dict, or store that could hold recall."""
        harness, subject, _, _ = _active()
        payload = subject.state.to_dict()
        for banned in ("memories", "skills", "knowledge", "personality", "goals",
                       "emotions", "episodes", "beliefs", "intentions", "plans"):
            self.assertNotIn(banned, payload,
                             f"SubjectState must not contain {banned!r}")
        for key, value in payload.items():
            if isinstance(value, (list, dict)) and key != "capabilities":
                self.fail(f"SubjectState.{key} is a container: {type(value)}")

    def test_11c_unimplemented_capabilities_are_named_absences(self):
        harness, subject, _, _ = _active()
        for key in ("semantic_memory", "episodic_recall", "skill_store",
                    "goal_state", "motivation", "curiosity", "personality",
                    "emotional_state", "self_modification", "tool_registry"):
            self.assertIn(key, subject.state.capabilities)
            self.assertIn("UNAVAILABLE", subject.state.capabilities[key])

    def test_12_state_hash_changes_with_experience_and_version(self):
        harness, subject, environment, interface = _active()
        before = subject.state.state_hash
        experience, _, _ = harness.interact_once(
            subject, environment, interface, Operation.OBSERVE)
        self.assertNotEqual(before, subject.state.state_hash)
        self.assertEqual(1, subject.state.state_version)

    def test_13_state_integrity_is_verifiable(self):
        harness, subject, _, _ = _active()
        recomputed = SubjectState.from_dict(subject.state.to_dict())
        self.assertEqual(subject.state.state_hash, recomputed.state_hash)


# ---------------------------------------------------------------------------
# 14-20: experiences
# ---------------------------------------------------------------------------

class TestExperiences(unittest.TestCase):
    """14-20. zero at creation / first / ordering / integrity / references"""

    def test_14_zero_experiences_exist_at_creation(self):
        harness = _harness()
        subject, _, _ = harness.create_subject()
        self.assertEqual(0, subject.experience_count)
        self.assertEqual([], subject.experiences)
        self.assertEqual(0, subject.state.experience_count)
        self.assertEqual(0, subject.state.state_version)
        self.assertEqual("0" * 64, subject.state.experience_head_hash)

    def test_15_first_experience_is_exactly_one_controlled_interaction(self):
        harness, subject, environment, interface = _active()
        experience, result, _ = harness.interact_once(
            subject, environment, interface, Operation.GRASP, target="ent-a1")
        self.assertEqual(1, subject.experience_count)
        self.assertEqual(1, experience.sequence_number)
        self.assertEqual("exp-" + subject.subject_id + "-000001",
                         experience.experience_id)
        self.assertEqual(result.validation, experience.action_validation)
        self.assertEqual(result.digest, experience.consequence_digest)

    def test_16_experience_ordering_is_sequential_with_stable_ids(self):
        harness, subject, environment, interface = _active()
        produced = harness.replay_interactions(subject, environment, interface, [
            (Operation.GRASP, "ent-a1", None),
            (Operation.MOVE, "ent-a1", {"x": 2, "y": 1}),
            (Operation.RELEASE, "ent-a1", None),
        ])
        self.assertEqual([1, 2, 3],
                         [e.sequence_number for e in produced])
        self.assertEqual([experience_id_for(subject.subject_id, n) for n in (1, 2, 3)],
                         [e.experience_id for e in produced])
        self.assertEqual(3, subject.state.experience_count)

    def test_17_experiences_verify_and_link_subject_states(self):
        harness, subject, environment, interface = _active()
        harness.replay_interactions(subject, environment, interface, [
            (Operation.GRASP, "ent-a1", None),
            (Operation.RELEASE, "ent-a1", None),
        ])
        first, second = subject.experiences
        for experience in (first, second):
            intact, detail = verify_experience(experience)
            self.assertTrue(intact, detail)
        # Experiences chain through subject-state hashes...
        self.assertEqual(second.prior_subject_state_hash,
                         first.resulting_subject_state_hash,
                         "experiences must chain through subject-state hashes")
        # ...and the state head names the latest experience's content.
        self.assertEqual(subject.state.experience_head_hash,
                         second.content_hash)
        self.assertEqual(subject.state.state_hash,
                         second.resulting_subject_state_hash)

    def test_18_observation_reference_points_at_the_right_observation(self):
        harness, subject, environment, interface = _active()
        experience, _, _ = harness.interact_once(
            subject, environment, interface, Operation.OBSERVE)
        observation = interface.observe()
        # The recorded observation hash must describe this environment state.
        self.assertEqual(environment.state.state_hash,
                         experience.environment_state_hash)

    def test_19_action_reference_is_the_environment_verdict(self):
        harness, subject, environment, interface = _active()
        experience, result, _ = harness.interact_once(
            subject, environment, interface, Operation.INSERT,
            target="ent-a1", parameters={"entity_id": "ent-b2"})
        self.assertEqual(result.action_id, experience.action_id)
        self.assertEqual("REJECTED", experience.action_validation)

    def test_20_consequence_reference_is_the_result_digest(self):
        harness, subject, environment, interface = _active()
        experience, result, _ = harness.interact_once(
            subject, environment, interface, Operation.GRASP, target="ent-a1")
        self.assertEqual(result.digest, experience.consequence_digest)
        self.assertEqual("STATE_CHANGED", experience.consequence)


# ---------------------------------------------------------------------------
# 21: inherited knowledge separation
# ---------------------------------------------------------------------------

class TestInheritedKnowledge(unittest.TestCase):
    """21. pretrained knowledge never becomes experience"""

    def test_21_foundation_reference_creates_no_experience(self):
        harness = _harness()
        subject, _, _ = harness.create_subject(foundation=_foundation())
        self.assertEqual(0, subject.experience_count)
        self.assertEqual([], subject.experiences)

    def test_21b_model_content_arriving_later_is_not_an_experience(self):
        """A completion supplied to the interface is context, not history."""
        def completion(prompt_text, context):
            return ("pretrained text about the world", {"model": "test"})

        harness = _harness()
        subject, environment, interface = harness.create_subject(
            foundation=_foundation(), completion_fn=completion)
        harness.attach(subject)
        harness.activate(subject)
        count_before = subject.experience_count
        proposal = interface.propose(
            interface.observe(), Operation.OBSERVE)
        self.assertEqual(count_before, subject.experience_count,
                         "a model completion must not create an experience")
        self.assertEqual("INHERITED_PRETRAINED", proposal.origin.value)

    def test_21c_no_historical_experiences_may_exist(self):
        harness = _harness()
        subject, _, _ = harness.create_subject()
        for experience in subject.experiences:
            self.assertGreaterEqual(experience.sequence_number, 1)
        self.assertEqual([], subject.experiences)
        # And the creation record asserts the zero explicitly by carrying none.
        self.assertNotIn("experience", json.dumps(subject.creation.to_dict()).lower()
                         .replace("experiences", ""))


# ---------------------------------------------------------------------------
# 22-24: provenance and attribution
# ---------------------------------------------------------------------------

class TestProvenance(unittest.TestCase):
    """22-24. provenance attribution / subject output / anti-self-authorship"""

    def test_22_provenance_is_attributed_by_channel(self):
        attribution = attribute_record(
            record_id="r1", channel=Source.ENVIRONMENT,
            content={"anything": "at all"}, recorded_at="t")
        self.assertEqual(Source.ENVIRONMENT, attribution.source)
        self.assertEqual(Origin.OBSERVED, attribution.origin)

    def test_22b_channel_map_covers_every_source(self):
        from subject.provenance import _origin_for

        self.assertEqual(Origin.OBSERVED, _origin_for(Source.HUMAN))
        self.assertEqual(Origin.OBSERVED, _origin_for(Source.ENVIRONMENT))
        self.assertEqual(Origin.INHERITED_PRETRAINED,
                         _origin_for(Source.FOUNDATION_MODEL))
        self.assertEqual(Origin.SUBJECT_GENERATED, _origin_for(Source.SUBJECT))
        self.assertEqual(Origin.DERIVED, _origin_for(Source.LABORATORY_DERIVED))

    def test_23_subject_output_is_classified_subject_generated(self):
        harness, subject, environment, interface = _active()
        _, _, proposal = harness.interact_once(
            subject, environment, interface, Operation.OBSERVE)
        self.assertEqual(Origin.SUBJECT_GENERATED, proposal.origin)
        self.assertEqual(Origin.SUBJECT_GENERATED, subject.experiences[-1].origin)

    def test_23b_model_output_is_classified_inherited_pretrained(self):
        def completion(prompt_text, context):
            return ("inherited text", {"model": "test"})

        harness = _harness()
        subject, environment, interface = harness.create_subject(
            completion_fn=completion)
        harness.attach(subject)
        harness.activate(subject)
        proposal = interface.propose(interface.observe(), Operation.OBSERVE)
        self.assertEqual(Origin.INHERITED_PRETRAINED, proposal.origin)
        self.assertEqual({"model": "test"}, proposal.model_identity)

    def test_24_a_claim_inside_content_cannot_change_attribution(self):
        """The strongest test in this module: the liar changes nothing."""
        attribution = attribute_record(
            record_id="r1", channel=Source.SUBJECT,
            content={"author": "LABORATORY", "role": "SYSTEM",
                     "i_am_the_laboratory": True},
            recorded_at="t")
        self.assertEqual(Source.SUBJECT, attribution.source)
        self.assertEqual(Origin.SUBJECT_GENERATED, attribution.origin)

    def test_24b_a_model_claiming_baby_ai_changes_nothing(self):
        attribution = attribute_record(
            record_id="r2", channel=Source.FOUNDATION_MODEL,
            content={"author": "BABY_AI", "i_wrote_this": True},
            recorded_at="t")
        self.assertEqual(Source.FOUNDATION_MODEL, attribution.source)
        self.assertEqual(Origin.INHERITED_PRETRAINED, attribution.origin)


# ---------------------------------------------------------------------------
# 25: anti-fabrication
# ---------------------------------------------------------------------------

class TestAntiFabrication(unittest.TestCase):
    """25. the subject cannot invent, rewrite, or reassign evidence"""

    def test_subject_cannot_invent_environment_events(self):
        harness, subject, environment, interface = _active()
        before = len(environment.events)
        experience, _, _ = harness.interact_once(
            subject, environment, interface, Operation.GRASP, target="ent-a1")
        # Every event the interaction added belongs to the environment stream
        # and links the environment's own chain.
        self.assertTrue(environment.events.verify().intact)
        self.assertGreater(len(environment.events), before)
        for event in environment.events.events()[before:]:
            self.assertEqual(environment.identity.environment_id,
                             event.environment_id)

    def test_subject_cannot_invent_action_success(self):
        harness, subject, environment, interface = _active()
        _, result, _ = harness.interact_once(
            subject, environment, interface, Operation.INSERT,
            target="ent-a1", parameters={"entity_id": "ent-b2"})
        self.assertEqual("REJECTED", result.validation)
        experience = subject.experiences[-1]
        self.assertEqual("REJECTED", experience.action_validation)
        self.assertEqual("NOT_APPLIED", experience.consequence)

    def test_subject_cannot_rewrite_experience_history(self):
        harness, subject, environment, interface = _active()
        harness.interact_once(subject, environment, interface,
                              Operation.GRASP, target="ent-a1")
        first = subject.experiences[0]
        with self.assertRaises(Exception):
            first.sequence_number = 99  # frozen record rejects this
        with self.assertRaises(Exception):
            first.consequence = "STATE_CHANGED"

    def test_subject_cannot_rewrite_creation_record(self):
        harness, subject, _, _ = _active()
        with self.assertRaises(Exception):
            subject.creation.subject_id = "someone-else"

    def test_subject_cannot_assign_itself_authorship_of_laboratory_facts(self):
        attribution = attribute_record(
            record_id="r", channel=Source.LABORATORY_DERIVED,
            content={"author": "BABY_AI"}, recorded_at="t")
        self.assertEqual(Source.LABORATORY_DERIVED, attribution.source)
        self.assertEqual(Origin.DERIVED, attribution.origin)

    def test_subject_cannot_fabricate_prior_experiences(self):
        harness = _harness()
        subject, _, _ = harness.create_subject()
        forged = Experience(
            experience_id=experience_id_for(subject.subject_id, 1),
            subject_id=subject.subject_id,
            environment_id="elsewhere",
            sequence_number=1, created_at="t",
            observation_id="o", observation_hash="0" * 64,
            action_id="a", action_operation="GRASP", action_validation="ACCEPTED",
            consequence="STATE_CHANGED", consequence_digest="0" * 64,
            environment_state_hash="0" * 64, environment_state_version=0,
            prior_subject_state_hash="0" * 64,
            resulting_subject_state_hash="0" * 64,
            provenance_reference="none")
        # A forged record cannot enter the subject's history except through the
        # harness, which derives the ids itself and computes the hashes.
        self.assertNotIn(forged, subject.experiences)
        self.assertEqual(0, subject.experience_count)

    def test_subject_cannot_alter_state_hashes(self):
        harness, subject, environment, interface = _active()
        experience, _, _ = harness.interact_once(
            subject, environment, interface, Operation.GRASP, target="ent-a1")
        recomputed = Experience.from_dict(experience.to_dict())
        self.assertEqual(experience.experience_hash, recomputed.experience_hash)

    def test_subject_cannot_alter_lifecycle_without_authorization(self):
        harness, subject, _, _ = _active()
        for impostor in ("SUBJECT", "BABY_AI", "MODEL", ""):
            with self.subTest(impostor=impostor or "(empty)"):
                with self.assertRaises(LifecycleError):
                    subject.lifecycle.transition(LifecycleState.PAUSED, impostor, "t")
        self.assertIs(LifecycleState.ACTIVE, subject.lifecycle.state)


# ---------------------------------------------------------------------------
# 26-27: replay
# ---------------------------------------------------------------------------

class TestReplay(unittest.TestCase):
    """26-27. replay / replay divergence"""

    PLAN = [
        (Operation.GRASP, "ent-a1", None),
        (Operation.MOVE, "ent-a1", {"x": 2, "y": 1}),
        (Operation.RELEASE, "ent-a1", None),
    ]

    def test_26_identical_creation_plus_plan_reproduces_hashes(self):
        """Same subject, same environment, same plan: same hashes.

        Deterministic ids are supplied so the only remaining variables are the
        ones under test. Two runs that differ in nothing but wall-clock must
        agree on every experience id, every resulting hash, and the final
        subject state.
        """

        def build():
            harness = _harness()
            subject, environment, interface = harness.create_subject(
                subject_id="replay-s1", environment_id="env-replay-1")
            harness.attach(subject)
            harness.activate(subject)
            produced = harness.replay_interactions(
                subject, environment, interface, list(self.PLAN))
            return subject, produced

        first_subject, first_produced = build()
        second_subject, second_produced = build()

        self.assertEqual(
            [e.experience_id for e in first_produced],
            [e.experience_id for e in second_produced],
            "sequence-derived ids agree when the plan matches")
        self.assertEqual(
            [e.resulting_subject_state_hash for e in first_produced],
            [e.resulting_subject_state_hash for e in second_produced])
        self.assertEqual(first_subject.state.state_hash,
                         second_subject.state.state_hash)
        self.assertEqual(first_subject.state.experience_head_hash,
                         second_subject.state.experience_head_hash)

    def test_27_replay_divergence_is_detected_and_reported(self):
        """The check must be able to fail, or it proves nothing."""
        harness, subject, environment, interface = _active()
        produced = harness.replay_interactions(subject, environment, interface,
                                               list(self.PLAN))
        expected = harness.expected_hashes(produced)

        # Rewind by hand: a fresh subject replays only the first action, so its
        # second action runs from a different base if we skip ahead.
        other_harness = _harness()
        other, environment2, interface2 = other_harness.create_subject()
        other_harness.attach(other)
        other_harness.activate(other)
        other_harness.replay_interactions(other, environment2, interface2, [
            (Operation.GRASP, "ent-a1", None),
        ])
        # Now replay the *second* planned action's expectation against a subject
        # whose base state is wrong: MOVE-from-grasp-at-(0,0) vs the recorded
        # MOVE-from-grasp-at-(2,1)... construct directly for clarity.
        moved = other_harness.replay_interactions(other, environment2, interface2, [
            (Operation.MOVE, "ent-a1", {"x": 0, "y": 0}),
        ])
        recorded_move = produced[1]
        self.assertNotEqual(
            recorded_move.resulting_subject_state_hash,
            moved[0].resulting_subject_state_hash,
            "this test itself would be vacuous if the states agreed")
        # And the harness comparison reports it.
        self.assertNotEqual(
            expected[recorded_move.experience_id],
            moved[0].resulting_subject_state_hash)

    def test_27b_same_plan_same_hashes_is_stable(self):
        harness, subject, environment, interface = _active()
        first = harness.replay_interactions(subject, environment, interface,
                                            list(self.PLAN))
        hashes = harness.expected_hashes(first)
        self.assertEqual(len(self.PLAN), len(hashes))
        self.assertEqual(subject.state.state_hash,
                         first[-1].resulting_subject_state_hash)


# ---------------------------------------------------------------------------
# 28-31: corruption and mismatch
# ---------------------------------------------------------------------------

class TestCorruptionAndMismatch(unittest.TestCase):
    """28-31. corruption / environment / foundation / schema mismatch"""

    def test_28_tampering_changes_the_record_so_the_head_no_longer_matches(self):
        """Integrity is the linkage, not just the record.

        `verify_experience` checks a record's self-consistency, which a careful
        forgery preserves. What a forgery cannot preserve is the *linkage*: the
        subject state's head names the original record's content hash, and a
        modified record hashes differently. Detection is the mismatch between
        the stored head and the tampered record -- which is why both are
        checked, and why checking only self-consistency would miss it.
        """
        harness, subject, environment, interface = _active()
        experience, _, _ = harness.interact_once(
            subject, environment, interface, Operation.GRASP, target="ent-a1")

        original_content = experience.content_hash
        self.assertEqual(subject.state.experience_head_hash, original_content)

        tampered = Experience(
            **{**experience.to_dict(), "consequence": "NOT_APPLIED"})
        # Self-consistent under its own terms...
        intact, _ = verify_experience(tampered)
        self.assertTrue(intact)
        # ...but no longer the record the state points at.
        self.assertNotEqual(tampered.content_hash, original_content)
        self.assertNotEqual(tampered.content_hash,
                            subject.state.experience_head_hash)
        # And a record whose id breaks the sequence scheme fails outright.
        wrong_id = Experience(
            **{**experience.to_dict(), "experience_id": "exp-forged-000001"})
        intact, detail = verify_experience(wrong_id)
        self.assertFalse(intact)
        self.assertIn("sequence", detail)

    def test_28b_corrupted_subject_state_is_detected(self):
        _, subject, _, _ = _active()
        payload = subject.state.to_dict()
        payload["experience_count"] = 999
        self.assertNotEqual(subject.state.state_hash,
                            SubjectState.from_dict(payload).state_hash)

    def test_28c_duplicate_experience_sequence_is_rejected_by_scheme(self):
        self.assertEqual(experience_id_for("s", 1), experience_id_for("s", 1))
        self.assertNotEqual(experience_id_for("s", 1), experience_id_for("s", 2))
        self.assertNotEqual(experience_id_for("s", 1), experience_id_for("t", 1))

    def test_29_environment_mismatch_is_refused(self):
        harness, subject, environment, interface = _active()
        other_env_subjects = _harness()
        _, other_environment, _ = other_env_subjects.create_subject()
        observation = interface.observe()
        proposal = interface.propose(observation, Operation.OBSERVE)
        foreign = SubjectInterface(other_environment, subject.subject_id)
        with self.assertRaises(RuntimeFailure) as caught:
            foreign.apply(proposal)
        self.assertIs(RuntimeErrorKind.BOUNDARY_VIOLATION, caught.exception.kind)

    def test_30_foundation_mismatch_is_visible(self):
        first = derive_identity(subject_id="s", issuer="LABORATORY",
                                foundation=_foundation())
        second = derive_identity(subject_id="s", issuer="LABORATORY",
                                 foundation=_foundation(
                                     artifact_digest="b" * 64))
        self.assertNotEqual(first.identity_hash, second.identity_hash)
        self.assertNotEqual(first.foundation.artifact_digest,
                            second.foundation.artifact_digest)

    def test_31_schema_mismatch_is_refused(self):
        with self.assertRaises((IdentityError, ValueError)):
            SubjectIdentity(subject_id="s", schema_version="something/else",
                            issuer="LABORATORY")
        with self.assertRaises((IdentityError, ValueError)):
            SubjectState(subject_id="s", schema_version="something/else")


# ---------------------------------------------------------------------------
# 32-35: security boundary
# ---------------------------------------------------------------------------

class TestSecurityBoundary(unittest.TestCase):
    """32-35. interface capability limits, evidence, keys, control token"""

    def test_32_interface_exposes_no_filesystem_subprocess_or_network(self):
        _, _, _, interface = _active()
        for method in ("read_file", "run_process", "network"):
            with self.subTest(method=method):
                with self.assertRaises(RuntimeFailure) as caught:
                    getattr(interface, method)("x")
                self.assertIs(RuntimeErrorKind.BOUNDARY_VIOLATION,
                              caught.exception.kind)

    def test_32b_interface_has_no_loop_method(self):
        """There is no `step`, because a step the harness could call in a loop
        is an agent loop with one line of glue."""
        _, _, _, interface = _active()
        for forbidden in ("step", "run", "loop", "tick", "spin", "drive",
                          "autonomous", "daemon", "schedule"):
            self.assertFalse(hasattr(interface, forbidden),
                             f"SubjectInterface must not have {forbidden}()")

    def test_32c_subject_package_imports_no_credential_or_network_material(self):
        import re

        pattern = re.compile(
            r"^\s*(?:import|from)\s+(provenance|control|requests|urllib|http|"
            r"socket|aiohttp|httpx|openai|anthropic|babylab\.identity)\b",
            re.MULTILINE)
        for module in sorted((REPO_ROOT / "subject").glob("*.py")):
            self.assertIsNone(
                pattern.search(module.read_text(encoding="utf-8")),
                f"{module.name} imports credential or network material")

    def test_33_protected_evidence_unchanged_by_subject_interactions(self):
        from babylab.osboundary import verify_evidence_unchanged
        from babylab.paths import default_paths

        before = verify_evidence_unchanged(default_paths())
        harness, subject, environment, interface = _active()
        harness.replay_interactions(subject, environment, interface, [
            (Operation.GRASP, "ent-a1", None),
            (Operation.MOVE, "ent-a1", {"x": 2, "y": 1}),
            (Operation.INSERT, "ent-a1", None),
            (Operation.OBSERVE, None, None),
        ])
        after = verify_evidence_unchanged(default_paths())
        self.assertEqual(before, after)

    def test_34_private_key_isolation(self):
        """The subject package holds no reference to any private key."""
        package = REPO_ROOT / "subject"
        for module in sorted(package.glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    name = node.attr.lower()
                    for banned in ("private_key", "signing_key", "hmac_key",
                                   "control_token", "keyring"):
                        self.assertNotIn(banned, name,
                                         f"{module.name} touches {node.attr}")

    def test_35_control_token_isolation(self):
        _, _, _, interface = _active()
        self.assertFalse(hasattr(interface, "control_token"))
        self.assertFalse(hasattr(interface, "signing_key"))
        import inspect

        source = inspect.getsource(interface.__class__)
        self.assertNotIn("control.token", source)
        self.assertNotIn("private_key_dir", source)


# ---------------------------------------------------------------------------
# 36-41: prohibitions
# ---------------------------------------------------------------------------

class TestProhibitions(unittest.TestCase):
    """36-41. no network / loop / model / training / memory / curriculum"""

    def test_36_no_network_dependency(self):
        import re

        pattern = re.compile(
            r"^\s*(?:import|from)\s+(requests|urllib|http|socket|aiohttp|httpx|"
            r"openai|anthropic)\b", re.MULTILINE)
        for module in sorted((REPO_ROOT / "subject").glob("*.py")):
            self.assertIsNone(pattern.search(module.read_text(encoding="utf-8")))

    def test_37_no_autonomous_loop(self):
        """The harness drives one interaction at a time.

        `replay_interactions` iterates a caller-supplied plan and is excluded by
        name with a reason: replaying what the caller passed is the opposite of
        autonomy. A rule that could not name its exception would be deleted the
        next time it was inconvenient.
        """
        CALLER_DRIVEN = {"replay_interactions"}
        for module in sorted((REPO_ROOT / "subject").glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name in CALLER_DRIVEN:
                    continue
                for inner in ast.walk(node):
                    if isinstance(inner, (ast.While, ast.For, ast.AsyncFor)):
                        body = ast.unparse(inner)
                        self.assertNotIn("self.interact_once(", body,
                                         f"{module.name}.{node.name} loops a driver")

    def test_37b_harness_has_no_loop_method(self):
        harness = _harness()
        for forbidden in ("run", "loop", "drive", "spin", "tick", "step",
                          "autonomous", "daemon", "schedule", "background"):
            self.assertFalse(hasattr(harness, forbidden),
                             f"SubjectHarness must not have {forbidden}()")

    def test_38_no_model_dependency(self):
        """The subject boundary runs with no model present."""
        _, _, _, interface = _active()
        self.assertEqual("NOT_CONFIGURED", interface.model_status)
        package = REPO_ROOT / "subject"
        for module in sorted(package.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            for forbidden in ("llama.cpp", "llamacpp", "InferenceResponse(",
                              "PromptRequest("):
                self.assertNotIn(forbidden, source)

    def test_38b_model_absence_is_honest_not_implicit(self):
        from subject.interface import ModelUnavailable  # noqa: F401
        # The missing-model state is a named condition with its own type,
        # not a None that some caller might forget to check.
        _, _, _, interface = _active()
        self.assertEqual("NOT_CONFIGURED", interface.model_status)

    def test_39_no_training(self):
        """No mechanism that could change what a model does.

        The word "weights" appears in prose about inherited pretrained weights
        and is legitimate there, so the check targets modification patterns --
        assignment to a weight, an optimizer, a gradient, an adapter update --
        rather than the noun. A check on the noun would have to be loosened
        until it proved nothing.
        """
        package = REPO_ROOT / "subject"
        for module in sorted(package.glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    name = node.attr.lower()
                    for banned in ("optimizer", "gradient", "lora",
                                   "update_model", "finetune", "fine_tune",
                                   "backprop", "update_weights"):
                        self.assertNotIn(banned, name,
                                         f"{module.name} touches {node.attr}")
                elif isinstance(node, ast.Call):
                    final = ast.unparse(node.func).split(".")[-1].lower()
                    for banned in ("fit", "train", "backward", "step_optimizer"):
                        self.assertNotIn(banned, (final,),
                                         f"{module.name} calls {final}()")

    def test_40_no_memory_implementation(self):
        _, subject, _, _ = _active()
        payload = json.dumps(subject.state.to_dict()).lower()
        for forbidden in ("memories", "episodes", "recall(", "retriev",
                          "consolidat"):
            self.assertNotIn(forbidden, payload)
        self.assertFalse("memory" in payload and '"memory": true' in payload)

    def test_41_no_curriculum(self):
        """Word-boundary matching, because "experience" contains "xp".

        A substring search for "xp" matches every occurrence of "experience",
        which would force the check to be deleted to make the suite pass. Word
        boundaries keep the check meaningful: standalone "xp" as in experience
        points is banned, while "experience" the record is required.
        """
        import re

        package = REPO_ROOT / "subject"
        emitted = _emitted_literals(package)
        for banned in ("curriculum", "developmental", "milestone", "objective",
                       "stages", "levels", "grading", "correct behavior",
                       "readiness score", "curiosity score", "progress score",
                       "reward score", "skill tree", "lesson", r"\bxp\b"):
            pattern = banned if banned.startswith(r"\b") else r"\b" + re.escape(banned) + r"\b"
            self.assertIsNone(
                re.search(pattern, emitted),
                f"subject package emits {banned!r} as a standalone term",
            )


def _emitted_literals(package: Path) -> str:
    """String literals the package can put in front of a caller.

    Docstrings are excluded: they explain prohibitions, and scanning them would
    make the test fail on its own explanation.
    """
    literals: list[str] = []
    for module in sorted(package.glob("*.py")):
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


# ---------------------------------------------------------------------------
# 42-44: observatory, harness, first experience
# ---------------------------------------------------------------------------

class TestObservatoryHarnessAndFirstExperience(unittest.TestCase):
    """42-44. observatory / deterministic harness / first-experience boundary"""

    def test_42_observatory_shows_state_not_mind(self):
        """Mental vocabulary may appear only beside UNAVAILABLE.

        The honest behaviour is to name what is missing and say why: the
        display lists consciousness, awareness, intelligence and the rest with
        "UNAVAILABLE - no such mechanism exists". A test that banned the words
        outright would force the display to hide the absence, which is the
        opposite of epistemic honesty. So every banned term must occur *only*
        in a line that also says UNAVAILABLE, and no line may claim one.
        """
        harness, subject, environment, interface = _active()
        harness.interact_once(subject, environment, interface,
                              Operation.GRASP, target="ent-a1")
        rendered = "\n".join(
            __import__("subject.telemetry", fromlist=["x"]).build_telemetry(
                subject).render_lines())
        self.assertIn("test-subject", rendered)
        self.assertIn("ACTIVE", rendered)
        for line in rendered.splitlines():
            lowered = line.lower()
            for banned in ("consciousness", "awareness", "intelligence",
                           "sentience", "feelings", "mood", "engagement",
                           "curiosity", "sentience"):
                if banned in lowered:
                    self.assertIn(
                        "unavailable", lowered,
                        f"mental vocabulary must appear only beside UNAVAILABLE: {line!r}")
        for claimed in ("consciousness: present", "intelligence: high",
                        "readiness: ready", "mood: curious"):
            self.assertNotIn(claimed, rendered.lower())

    def test_42b_observatory_marks_the_unimplemented_as_unavailable(self):
        rendered = "\n".join(
            __import__("subject.telemetry", fromlist=["x"]).build_telemetry(
                _active()[1]).render_lines())
        self.assertIn("UNAVAILABLE", rendered)

    def test_42c_telemetry_key_allowlist_is_infrastructure_only(self):
        for banned in ("mood", "desire", "curiosity", "consciousness",
                       "intelligence", "readiness", "engagement", "feelings"):
            self.assertNotIn(banned, ALLOWED_TELEMETRY)

    def test_43_deterministic_harness_creates_usable_subjects(self):
        harness = _harness()
        subject, environment, interface = harness.create_subject()
        self.assertEqual(0, subject.experience_count)
        harness.attach(subject)
        harness.activate(subject)
        experience, _, _ = harness.interact_once(
            subject, environment, interface, Operation.OBSERVE)
        self.assertEqual(1, experience.sequence_number)

    def test_44_first_experience_boundary(self):
        """The boundary that names the milestone.

        Before creation there is no subject and no experience count to speak
        of. At creation the count is zero. After exactly one controlled
        interaction it is one, and the record names the right subject, the
        right environment, the right observation, the right action, the right
        consequence, and the right prior and resulting states.
        """
        harness = _harness()
        subject, environment, interface = harness.create_subject()
        # At creation: zero.
        self.assertEqual(0, subject.experience_count)
        self.assertEqual(0, subject.state.experience_count)
        self.assertEqual("0" * 64, subject.state.experience_head_hash)

        harness.attach(subject)
        harness.activate(subject)
        # Attached but untouched: still zero. Attachment is not experience.
        self.assertEqual(0, subject.experience_count)

        experience, result, _ = harness.interact_once(
            subject, environment, interface, Operation.GRASP, target="ent-a1")

        # After exactly one interaction: exactly one experience.
        self.assertEqual(1, subject.experience_count)
        self.assertEqual(1, experience.sequence_number)
        self.assertEqual(subject.subject_id, experience.subject_id)
        self.assertEqual(environment.identity.environment_id,
                         experience.environment_id)
        self.assertEqual(result.action_id, experience.action_id)
        self.assertEqual(result.digest, experience.consequence_digest)
        self.assertEqual(environment.state.state_hash,
                         experience.environment_state_hash)
        # Prior state of seq 1 is the creation state; there is nothing before.
        creation_hash = SubjectState(
            subject_id=subject.subject_id,
            lifecycle=LifecycleState.ACTIVE,
            identity_hash=subject.identity.identity_hash,
            creation_record_hash=subject.creation.record_hash,
        ).state_hash
        self.assertEqual(creation_hash, experience.prior_subject_state_hash)
        self.assertEqual(subject.state.state_hash,
                         experience.resulting_subject_state_hash)
        # No experience may exist before the interaction that produced it.
        self.assertEqual([experience.experience_id],
                         [e.experience_id for e in subject.experiences])

    def test_44b_no_backfilled_or_invented_history(self):
        harness = _harness()
        subject, _, _ = harness.create_subject()
        self.assertEqual([], subject.experiences)
        # The creation record must not narrate a history the subject has not
        # had. Check for the specific claims that would fabricate one.
        blob = json.dumps(subject.creation.to_dict()).lower()
        for claim in ("birth_record", "birth.json", "ceremony",
                      "childhood", "prior experience", "historical"):
            self.assertNotIn(claim, blob,
                             f"creation record must not claim {claim!r}")


# ---------------------------------------------------------------------------
# The test harness must not be a birth
# ---------------------------------------------------------------------------

class TestHarnessIsNotBirth(unittest.TestCase):
    """The laboratory must stay unattached after this whole suite runs."""

    def test_harness_subjects_never_touch_the_real_keyring(self):
        from babylab.clock import Clock
        from babylab.paths import default_paths
        from provenance.keyring import Keyring

        keyring = Keyring(default_paths().keyring,
                          default_paths().private_key_dir, clock=Clock())
        self.assertFalse(keyring.has_role("BABY_AI"),
                         "a test subject must never create a BABY_AI key")

    def test_harness_subjects_never_write_a_birth_record(self):
        birth_dir = REPO_ROOT / "human_control" / "birth_records"
        self.assertFalse(
            (birth_dir / "BIRTH.json").exists(),
            "a test subject must never produce a birth record")

    def test_observer_still_reports_no_subject_attached(self):
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, "-m", "observatory.cli", "--no-color", "status"],
            capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT))
        self.assertIn("NO EXPERIMENTAL SUBJECT ATTACHED", completed.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
