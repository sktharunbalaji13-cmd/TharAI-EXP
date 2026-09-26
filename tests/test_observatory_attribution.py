"""Attribution: the event source is not an identity.

If this module is wrong, every other guarantee in the Observatory becomes
decorative. An event that says it came from the subject is not evidence of
anything, because the future subject will be able to write events. These tests
hold the line between "what produced this record" and "who is accountable".
"""

from __future__ import annotations

import unittest

from events.model import INFRASTRUCTURE_NAMESPACES, Event
from observatory.attribution import Attributor, AttributionKind
from tests.support import LabTestCase


def make_event(seq: int = 1, namespace: str = "system", payload: dict | None = None) -> Event:
    return Event(
        event_id=f"EVENT-{seq:06d}",
        seq=seq,
        timestamp="2026-01-01T00:00:00.000Z",
        event_type=f"{namespace}.something.happened",
        source="test.harness",
        payload=payload or {},
    )


class NoSubjectAttributionTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.attributor = Attributor()

    def test_no_subject_means_everything_is_infrastructure(self) -> None:
        event = make_event(namespace="control")
        attribution = self.attributor.attribute(event)
        self.assertIs(attribution.kind, AttributionKind.INFRASTRUCTURE)
        self.assertFalse(attribution.is_subject)

    def test_namespace_is_used_as_the_label(self) -> None:
        self.assertEqual(self.attributor.attribute(make_event(namespace="control")).label, "CONTROL")

    def test_basis_explains_that_no_subject_is_attached(self) -> None:
        basis = self.attributor.attribute(make_event()).basis
        self.assertIn("no subject is attached", basis)

    def test_event_source_is_never_the_label(self) -> None:
        # source is "test.harness" on every event here. If the label ever became
        # the source, this would read "TEST.HARNESS" instead of "SYSTEM".
        event = make_event(namespace="system")
        self.assertEqual(self.attributor.attribute(event).label, "SYSTEM")
        self.assertNotEqual(self.attributor.attribute(event).label, event.source)

    def test_payload_author_claim_is_not_believed(self) -> None:
        # A subject asserting its own identity in the payload proves nothing.
        event = make_event(namespace="system", payload={"author": "BABY_AI"})
        self.assertIsNot(self.attributor.attribute(event).kind, AttributionKind.SUBJECT)

    def test_source_naming_the_subject_is_not_believed(self) -> None:
        event = Event(
            event_id="EVENT-000001",
            seq=1,
            timestamp="2026-01-01T00:00:00.000Z",
            event_type="system.pretending",
            source="baby_ai",
            payload={},
        )
        self.assertIs(self.attributor.attribute(event).kind, AttributionKind.INFRASTRUCTURE)

    def test_attribution_records_the_event_id(self) -> None:
        event = make_event(seq=7)
        self.assertEqual(self.attributor.attribute(event).event_id, event.event_id)

    def test_partition_splits_by_kind(self) -> None:
        buckets = self.attributor.partition([make_event(1), make_event(2)])
        self.assertEqual(len(buckets[AttributionKind.INFRASTRUCTURE]), 2)
        self.assertEqual(len(buckets[AttributionKind.SUBJECT]), 0)

    def test_does_not_expect_subject_events(self) -> None:
        self.assertFalse(self.attributor.expects_subject_events)
        self.assertEqual(self.attributor.subject_namespaces(), frozenset())


class WithSubjectAttributionTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provision_baby_ai("baby-ai:subject")
        self.attributor = Attributor(
            subject_namespace=frozenset({"baby"}), subject_label="SUBJECT"
        )

    def test_declared_namespace_is_subject_attributed(self) -> None:
        event = make_event(namespace="baby")
        attribution = self.attributor.attribute(event)
        self.assertIs(attribution.kind, AttributionKind.SUBJECT)
        self.assertTrue(attribution.is_subject)

    def test_basis_says_the_human_declared_it_not_the_event(self) -> None:
        basis = self.attributor.attribute(make_event(namespace="baby")).basis
        self.assertIn("declared by the human", basis)

    def test_undeclared_namespace_is_unattributed_not_assumed(self) -> None:
        # Once a subject exists, an event in a namespace that is neither
        # laboratory infrastructure nor subject-declared is NOT silently folded
        # into the subject's history. It is marked unknown.
        attribution = self.attributor.attribute(make_event(namespace="rogue"))
        self.assertIs(attribution.kind, AttributionKind.UNATTRIBUTED)

    def test_every_laboratory_namespace_stays_infrastructure(self) -> None:
        for namespace in INFRASTRUCTURE_NAMESPACES:
            with self.subTest(namespace=namespace):
                attribution = self.attributor.attribute(make_event(namespace=namespace))
                self.assertIs(attribution.kind, AttributionKind.INFRASTRUCTURE)

    def test_infrastructure_namespace_stays_infrastructure(self) -> None:
        # The control plane is not the subject, even with a subject attached.
        attribution = self.attributor.attribute(make_event(namespace="control"))
        self.assertIsNot(attribution.kind, AttributionKind.SUBJECT)

    def test_partition_separates_all_three_kinds(self) -> None:
        buckets = self.attributor.partition(
            [make_event(1, "baby"), make_event(2, "control"), make_event(3, "rogue")]
        )
        self.assertEqual(len(buckets[AttributionKind.SUBJECT]), 1)
        self.assertEqual(len(buckets[AttributionKind.INFRASTRUCTURE]), 1)
        self.assertEqual(len(buckets[AttributionKind.UNATTRIBUTED]), 1)

    def test_expects_subject_events(self) -> None:
        self.assertTrue(self.attributor.expects_subject_events)

    def test_attribution_serialises(self) -> None:
        data = self.attributor.attribute(make_event(1, "baby")).to_dict()
        self.assertEqual(data["kind"], "SUBJECT")
        self.assertEqual(data["label"], "SUBJECT")

    def test_namespace_configuration_is_not_a_schema(self) -> None:
        # Namespaces are configuration supplied by the human, never derived
        # from an event's own claims about itself.
        self.assertEqual(self.attributor.subject_namespaces(), frozenset({"baby"}))


if __name__ == "__main__":
    unittest.main()
