"""State derivation: only what the subject said, and always traceable.

The deriver is where the temptation to be clever lives. These tests are mostly
assertions that it is *boring*: it copies through what was reported, marks what
was not, and refuses to read a mind into an event.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

from events.model import Event
from observatory.attribution import Attributor
from observatory.derive import StateDeriver
from observatory.model import EpistemicStatus
from tests.support import LabTestCase


def subject_event(seq: int, state: dict | None, namespace: str = "baby") -> Event:
    payload = {} if state is None else {"state": state}
    return Event(
        event_id=f"EVENT-{seq:06d}",
        seq=seq,
        timestamp="2026-01-01T00:00:00.000Z",
        event_type=f"{namespace}.report",
        source="subject.runtime",
        payload=payload,
    )


class NoSubjectDerivationTests(LabTestCase):
    """With no subject, infrastructure events produce no cognitive state."""

    def setUp(self) -> None:
        super().setUp()
        self.deriver = StateDeriver(attributor=Attributor(), subject_id=None, clock=self.clock)

    def test_infrastructure_event_produces_no_state(self) -> None:
        event = subject_event(1, {"memory": []}, namespace="control")
        self.assertIsNone(self.deriver.apply(event))
        self.assertEqual(self.deriver.version(), 0)

    def test_snapshot_is_empty(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": []}, namespace="system"))
        state = self.deriver.snapshot(self.clock.now())
        self.assertTrue(state.is_empty())
        self.assertIsNone(state.subject_id)

    def test_liveness_is_unavailable_not_false(self) -> None:
        # Reporting "not active" would describe an entity that does not exist.
        value = self.deriver.liveness(self.clock.now())
        self.assertIs(value.status, EpistemicStatus.UNAVAILABLE)
        self.assertIn("no subject is attached", value.note)

    def test_reported_state_counts_but_displays_nothing(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": []}, namespace="control"))
        self.assertEqual(self.deriver.stats()["processed_events"], 1)
        self.assertEqual(self.deriver.stats()["reported_domains"], 0)

    def test_history_is_empty(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": []}, namespace="control"))
        self.assertEqual(self.deriver.history(), [])


class SubjectDerivationTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provision_baby_ai("baby-ai:subject")
        self.attributor = Attributor(
            subject_namespace=frozenset({"baby"}), subject_label="SUBJECT"
        )
        self.deriver = StateDeriver(
            attributor=self.attributor, subject_id="baby-ai:subject", clock=self.clock
        )

    def test_reported_domain_becomes_observed(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 2}}))
        state = self.deriver.snapshot(self.clock.now())
        self.assertIs(state.get("memory").status, EpistemicStatus.OBSERVED)
        self.assertEqual(state.get("memory").value, {"count": 2})

    def test_observed_value_cites_its_event(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 2}}))
        state = self.deriver.snapshot(self.clock.now())
        self.assertEqual(state.get("memory").source_event_ids, ("EVENT-000001",))

    def test_unreported_domain_stays_unavailable(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 2}}))
        state = self.deriver.snapshot(self.clock.now())
        perception = state.get("perception")
        self.assertIs(perception.status, EpistemicStatus.UNAVAILABLE)
        self.assertEqual(perception.display(), "UNAVAILABLE")

    def test_empty_reported_list_is_preserved_as_observed(self) -> None:
        # The subject really did report an empty memory. That is different
        # from not reporting, and we keep the difference.
        self.deriver.apply(subject_event(1, {"memory": []}))
        value = self.deriver.snapshot(self.clock.now()).get("memory")
        self.assertIs(value.status, EpistemicStatus.OBSERVED)
        self.assertEqual(value.value, [])

    def test_event_without_state_key_produces_nothing(self) -> None:
        # An event happening is not a report of a mental state.
        self.assertIsNone(self.deriver.apply(subject_event(1, None)))
        self.assertEqual(self.deriver.version(), 0)

    def test_event_type_alone_implies_no_state(self) -> None:
        event = Event(
            event_id="EVENT-000009",
            seq=9,
            timestamp="2026-01-01T00:00:00.000Z",
            event_type="baby.tool.use",
            source="subject.runtime",
            payload={"tool": "calculator"},
        )
        self.deriver.apply(event)
        self.assertEqual(self.deriver.version(), 0)

    def test_non_dict_state_payload_is_ignored(self) -> None:
        event = Event(
            event_id="EVENT-000009",
            seq=9,
            timestamp="2026-01-01T00:00:00.000Z",
            event_type="baby.report",
            source="subject.runtime",
            payload={"state": "thinking hard"},
        )
        self.deriver.apply(event)
        self.assertEqual(self.deriver.version(), 0)

    # -- transitions ------------------------------------------------------
    def test_first_report_is_version_one(self) -> None:
        transition = self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        self.assertEqual(transition.version, 1)
        self.assertEqual(transition.cause_event_ids, ("EVENT-000001",))

    def test_changed_domain_bumps_the_version(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        transition = self.deriver.apply(subject_event(2, {"memory": {"count": 2}}))
        self.assertEqual(transition.version, 2)
        self.assertEqual(transition.changed_domains, ("memory",))

    def test_re_reporting_the_same_value_is_not_a_transition(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        self.assertIsNone(self.deriver.apply(subject_event(2, {"memory": {"count": 1}})))
        self.assertEqual(self.deriver.version(), 1)

    def test_re_reporting_moves_the_cited_event_forward(self) -> None:
        # A reader should be able to cite the most recent statement.
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        self.deriver.apply(subject_event(2, {"memory": {"count": 1}}))
        value = self.deriver.snapshot(self.clock.now()).get("memory")
        self.assertEqual(value.source_event_ids, ("EVENT-000002",))

    def test_new_domain_produces_a_transition(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        transition = self.deriver.apply(subject_event(2, {"perception": "wall"}))
        self.assertEqual(transition.changed_domains, ("perception",))

    def test_duplicate_event_is_ignored(self) -> None:
        event = subject_event(1, {"memory": {"count": 1}})
        self.deriver.apply(event)
        self.assertIsNone(self.deriver.apply(event))
        self.assertEqual(self.deriver.version(), 1)

    def test_history_records_every_transition_with_its_cause(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        self.deriver.apply(subject_event(2, {"memory": {"count": 2}}))
        self.deriver.apply(subject_event(3, {"perception": "wall"}))
        history = self.deriver.history()
        self.assertEqual([t.version for t in history], [1, 2, 3])
        self.assertEqual(history[2].cause_event_ids, ("EVENT-000003",))

    def test_apply_all_returns_transitions(self) -> None:
        transitions = self.deriver.apply_all(
            [
                subject_event(1, {"memory": {"count": 1}}),
                subject_event(2, {"perception": "wall"}),
            ]
        )
        self.assertEqual(len(transitions), 2)

    # -- liveness ---------------------------------------------------------
    def test_liveness_is_derived_with_a_citation(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        value = self.deriver.liveness(self.clock.now())
        self.assertIs(value.status, EpistemicStatus.DERIVED)
        self.assertTrue(value.value)
        self.assertTrue(value.source_event_ids)

    def test_liveness_goes_false_after_the_window(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        later = self.clock.now() + timedelta(minutes=5)
        value = self.deriver.liveness(later)
        self.assertIs(value.status, EpistemicStatus.DERIVED)
        self.assertFalse(value.value)

    def test_liveness_unavailable_before_any_report(self) -> None:
        # An attached subject that has said nothing is not the same as a
        # subject known to be inactive.
        value = self.deriver.liveness(self.clock.now())
        self.assertIs(value.status, EpistemicStatus.UNAVAILABLE)
        self.assertIn("never reported", value.note)

    def test_snapshot_includes_liveness(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        state = self.deriver.snapshot(self.clock.now())
        self.assertIn("liveness", state.domains)
        self.assertIs(state.get("liveness").status, EpistemicStatus.DERIVED)

    def test_snapshot_carries_last_event(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        state = self.deriver.snapshot(self.clock.now(), timestamp="t")
        self.assertEqual(state.last_event_id, "EVENT-000001")
        self.assertEqual(state.last_event_seq, 1)

    def test_snapshot_round_trips(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}))
        state = self.deriver.snapshot(self.clock.now(), timestamp="t")
        from observatory.model import CognitiveState

        self.assertEqual(CognitiveState.from_dict(state.to_dict()), state)

    def test_infrastructure_events_do_not_pollute_subject_state(self) -> None:
        self.deriver.apply(subject_event(1, {"memory": {"count": 1}}, namespace="baby"))
        self.deriver.apply(subject_event(2, {"memory": "control lied"}, namespace="control"))
        value = self.deriver.snapshot(self.clock.now()).get("memory")
        self.assertEqual(value.value, {"count": 1})
        self.assertEqual(value.source_event_ids, ("EVENT-000001",))


if __name__ == "__main__":
    unittest.main()
