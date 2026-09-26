"""The epistemic status rules: the core "no fake cognition" guarantee."""

from __future__ import annotations

import unittest

from babylab.errors import ValidationError
from observatory.model import (
    CognitiveState,
    EpistemicStatus,
    StateTransition,
    StateValue,
)


class EpistemicStatusTests(unittest.TestCase):
    def test_only_observed_and_derived_are_claims(self) -> None:
        self.assertTrue(EpistemicStatus.OBSERVED.is_claim)
        self.assertTrue(EpistemicStatus.DERIVED.is_claim)
        self.assertFalse(EpistemicStatus.UNAVAILABLE.is_claim)
        self.assertFalse(EpistemicStatus.UNKNOWN.is_claim)

    def test_status_values_are_stable_strings(self) -> None:
        # These strings reach the future API, so they are part of the contract.
        self.assertEqual(EpistemicStatus.OBSERVED.value, "OBSERVED")
        self.assertEqual(EpistemicStatus.DERIVED.value, "DERIVED")
        self.assertEqual(EpistemicStatus.UNAVAILABLE.value, "UNAVAILABLE")
        self.assertEqual(EpistemicStatus.UNKNOWN.value, "UNKNOWN")


class StateValueTests(unittest.TestCase):
    def test_observed_requires_a_source_event(self) -> None:
        with self.assertRaises(ValidationError):
            StateValue.observed("memory", ["note"], ())

    def test_observed_requires_a_value(self) -> None:
        # The heart of the matter: OBSERVED with no value would display an
        # absence as a claim.
        with self.assertRaises(ValidationError):
            StateValue("memory", EpistemicStatus.OBSERVED, None, ("EVENT-000001",))

    def test_unavailable_must_not_carry_a_value(self) -> None:
        with self.assertRaises(ValidationError):
            StateValue("memory", EpistemicStatus.UNAVAILABLE, [], ("EVENT-000001",))

    def test_unavailable_must_not_cite_events(self) -> None:
        with self.assertRaises(ValidationError):
            StateValue("memory", EpistemicStatus.UNAVAILABLE, None, ("EVENT-000001",))

    def test_domain_must_not_be_blank(self) -> None:
        with self.assertRaises(ValidationError):
            StateValue.unavailable("   ")

    def test_display_never_shows_an_empty_container_for_an_absence(self) -> None:
        # The regression this project exists to prevent: memory_activity shown
        # as [] when the truth is that nothing was reported.
        value = StateValue.unavailable("memory_activity")
        self.assertEqual(value.display(), "UNAVAILABLE")
        self.assertNotIn("[]", value.display())
        self.assertNotEqual(value.display(), "None")

    def test_display_of_unknown_is_shouty(self) -> None:
        self.assertEqual(StateValue.unknown("perception").display(), "UNKNOWN")

    def test_note_never_replaces_the_placeholder_in_the_value_column(self) -> None:
        # A note is prose; prose in the value column is one refactor away from
        # being read as data. Explanations live in the detail column.
        value = StateValue.unavailable("memory", note="subject never reported")
        self.assertEqual(value.display(), "UNAVAILABLE")
        self.assertEqual(value.note, "subject never reported")

    def test_observed_displays_compactly(self) -> None:
        self.assertEqual(
            StateValue.observed("memory", {"count": 3}, ("EVENT-000001",)).display(),
            '{"count": 3}',
        )

    def test_observed_displays_plain_string(self) -> None:
        self.assertEqual(
            StateValue.observed("decision", "run experiment 2", ("EVENT-000001",)).display(),
            "run experiment 2",
        )

    def test_round_trips_through_dict(self) -> None:
        original = StateValue.observed("memory", {"count": 1}, ("EVENT-000001",), "note")
        restored = StateValue.from_dict(original.to_dict())
        self.assertEqual(restored, original)

    def test_absence_round_trips_through_dict(self) -> None:
        original = StateValue.unavailable("memory", note="no report")
        restored = StateValue.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertIsNone(restored.to_dict()["value"])

    def test_from_dict_rejects_unknown_status(self) -> None:
        with self.assertRaises(ValidationError):
            StateValue.from_dict({"domain": "memory", "status": "PROBABLY"})

    def test_from_dict_rejects_non_object(self) -> None:
        with self.assertRaises(ValidationError):
            StateValue.from_dict(["memory"])


class StateTransitionTests(unittest.TestCase):
    def test_requires_a_cause(self) -> None:
        # A change with no cause is not a change, it is a fabrication.
        with self.assertRaises(ValidationError):
            StateTransition(version=1, cause_event_ids=(), reason="something changed")

    def test_version_starts_at_one(self) -> None:
        with self.assertRaises(ValidationError):
            StateTransition(version=0, cause_event_ids=("EVENT-000001",), reason="x")

    def test_round_trips_through_dict(self) -> None:
        original = StateTransition(
            version=3,
            cause_event_ids=("EVENT-000004", "EVENT-000005"),
            reason="subject reported memory",
            changed_domains=("memory",),
            timestamp="2026-01-01T00:00:00.000Z",
        )
        self.assertEqual(StateTransition.from_dict(original.to_dict()), original)


class CognitiveStateTests(unittest.TestCase):
    def test_get_returns_marked_absence_not_none(self) -> None:
        state = CognitiveState.empty()
        value = state.get("memory")
        self.assertIs(value.status, EpistemicStatus.UNAVAILABLE)
        self.assertIn("not reported", value.note)

    def test_empty_state_has_no_version(self) -> None:
        # Version 1 is reserved for the first reported state, so an empty state
        # is not a numbered version of anything.
        self.assertEqual(CognitiveState.empty().version, 0)

    def test_empty_state_reports_nothing(self) -> None:
        state = CognitiveState.empty()
        self.assertTrue(state.is_empty())
        self.assertEqual(state.reported(), {})

    def test_state_without_subject_may_not_claim_domains(self) -> None:
        # Milestone 002 has no subject, so nothing can have reported anything.
        with self.assertRaises(ValidationError):
            CognitiveState(
                subject_id=None,
                version=1,
                timestamp="2026-01-01T00:00:00.000Z",
                domains={"memory": StateValue.observed("memory", [], ("EVENT-000001",))},
            )

    def test_state_without_subject_may_record_absence(self) -> None:
        state = CognitiveState(
            subject_id=None,
            version=0,
            timestamp="",
            domains={"memory": StateValue.unavailable("memory")},
        )
        self.assertTrue(state.is_empty())

    def test_domain_key_must_match_value_domain(self) -> None:
        with self.assertRaises(ValidationError):
            CognitiveState(
                subject_id="baby-ai:subject",
                version=1,
                timestamp="",
                domains={"wrong": StateValue.observed("memory", [], ("EVENT-000001",))},
            )

    def test_ordered_domains_puts_conventional_first(self) -> None:
        state = CognitiveState(
            subject_id="baby-ai:subject",
            version=1,
            timestamp="",
            domains={
                "zzz_custom": StateValue.observed("zzz_custom", 1, ("EVENT-000001",)),
                "memory": StateValue.observed("memory", 1, ("EVENT-000001",)),
                "perception": StateValue.observed("perception", 1, ("EVENT-000001",)),
            },
        )
        # An unrecognised domain is still shown; the subject is free to report
        # something the Observatory has never heard of.
        self.assertEqual(state.ordered_domains(), ["perception", "memory", "zzz_custom"])

    def test_all_source_event_ids_deduplicates(self) -> None:
        state = CognitiveState(
            subject_id="baby-ai:subject",
            version=1,
            timestamp="",
            domains={
                "memory": StateValue.observed("memory", 1, ("EVENT-000001", "EVENT-000002")),
                "perception": StateValue.observed("perception", 2, ("EVENT-000001",)),
            },
        )
        self.assertEqual(state.all_source_event_ids(), ["EVENT-000001", "EVENT-000002"])

    def test_round_trips_through_dict(self) -> None:
        original = CognitiveState(
            subject_id="baby-ai:subject",
            version=2,
            timestamp="2026-01-01T00:00:00.000Z",
            domains={
                "memory": StateValue.observed("memory", {"count": 2}, ("EVENT-000001",)),
                "perception": StateValue.unavailable("perception", note="no report"),
            },
            last_event_id="EVENT-000001",
            last_event_seq=1,
        )
        restored = CognitiveState.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(restored.get("perception").note, "no report")

    def test_dict_carries_schema(self) -> None:
        self.assertEqual(
            CognitiveState.empty().to_dict()["schema"], "babylab/cognitive-state/v1"
        )

    def test_from_dict_rejects_non_object(self) -> None:
        with self.assertRaises(ValidationError):
            CognitiveState.from_dict("not a state")


if __name__ == "__main__":
    unittest.main()
