"""Tests for affordances and the restricted environment.

The load-bearing assertion: an affordance cannot be given a purpose, and a
description cannot claim to be exercisable while nothing is connected.
"""

from __future__ import annotations

import unittest

from babylab.errors import ValidationError
from birth.environment import (
    FORBIDDEN_SEMANTIC_FIELDS,
    Affordance,
    Availability,
    Modality,
    RestrictedEnvironment,
    spoon_like_affordance,
    unattached_environment,
)


class TestNoPurpose(unittest.TestCase):
    def test_semantic_field_names_are_rejected(self) -> None:
        for field in sorted(FORBIDDEN_SEMANTIC_FIELDS):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError) as caught:
                    Affordance(
                        affordance_id="A1",
                        handle="object.a",
                        modality=Modality.VISUAL,
                        trigger="t",
                        observable_consequence="c",
                        measurements={field: "spoon"},
                    )
                self.assertIn("not a measurement", str(caught.exception))

    def test_affordance_has_no_purpose_field_at_all(self) -> None:
        keys = set(spoon_like_affordance().to_dict())
        self.assertEqual(keys & FORBIDDEN_SEMANTIC_FIELDS, set())
        for name in ("purpose", "function", "use", "meaning", "label"):
            self.assertNotIn(name, keys)

    def test_the_example_says_nothing_about_eating(self) -> None:
        """The specification's own example, checked for the usual wrong answer."""
        text = (spoon_like_affordance().describe() + " " + str(spoon_like_affordance().measurements)).lower()
        for word in ("eat", "food", "soup", "stir", "utensil", "kitchen", "meal"):
            with self.subTest(word=word):
                self.assertNotIn(word, text)

    def test_example_uses_only_physical_measurements(self) -> None:
        measurements = spoon_like_affordance().measurements
        self.assertIn("outer_diameter_cm", measurements)
        self.assertIn("mass_g", measurements)
        for value in measurements.values():
            self.assertIsInstance(value, (int, float))

    def test_trigger_and_consequence_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            Affordance(
                affordance_id="A1",
                handle="object.a",
                modality=Modality.VISUAL,
                trigger="   ",
                observable_consequence="c",
            )
        with self.assertRaises(ValidationError):
            Affordance(
                affordance_id="A1",
                handle="object.a",
                modality=Modality.VISUAL,
                trigger="t",
                observable_consequence="",
            )

    def test_described_and_available_are_distinct(self) -> None:
        self.assertIsNot(Availability.DESCRIBED, Availability.AVAILABLE)
        self.assertIs(spoon_like_affordance().availability, Availability.DESCRIBED)


class TestRestrictedEnvironment(unittest.TestCase):
    def test_nothing_is_connected(self) -> None:
        environment = unattached_environment()
        self.assertFalse(environment.connected)
        self.assertIn("Milestone 003", environment.reason())

    def test_describing_an_affordance_does_not_allow_exercising_it(self) -> None:
        environment = unattached_environment()
        described = environment.describe("AFF-EXAMPLE-0001")
        self.assertEqual(described["status"], "UNAVAILABLE")
        self.assertIn("not an interaction that occurred", described["detail"])

    def test_unknown_affordance_is_unknown_not_guessed(self) -> None:
        environment = unattached_environment()
        result = environment.describe("AFF-DOES-NOT-EXIST")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertNotIn("affordance", result)
        self.assertNotIn("AVAILABLE", result["detail"])
        self.assertIn("no affordance", result["detail"])

    def test_available_affordance_requires_a_connection(self) -> None:
        affordance = Affordance(
            affordance_id="A1",
            handle="object.b",
            modality=Modality.TACTILE,
            trigger="contact",
            observable_consequence="force is measurable",
            availability=Availability.AVAILABLE,
        )
        with self.assertRaises(ValidationError) as caught:
            RestrictedEnvironment(affordances=[affordance], connected=False)
        self.assertIn("one of the two is wrong", str(caught.exception))

    def test_connected_environment_can_describe_exercise(self) -> None:
        affordance = Affordance(
            affordance_id="A1",
            handle="object.b",
            modality=Modality.TACTILE,
            trigger="contact",
            observable_consequence="force is measurable",
            availability=Availability.AVAILABLE,
        )
        environment = RestrictedEnvironment(
            affordances=[affordance], connected=True, reason="test"
        )
        self.assertEqual(environment.describe("A1")["status"], "AVAILABLE")

    def test_effectful_capabilities_are_excluded_permanently(self) -> None:
        for excluded in (
            "network-egress",
            "privileged-control",
            "human-control-credentials",
            "filesystem-outside-workspace",
        ):
            with self.subTest(excluded=excluded):
                self.assertIn(excluded, RestrictedEnvironment.EXCLUDED)

    def test_hash_is_stable(self) -> None:
        self.assertEqual(
            unattached_environment().content_hash(), unattached_environment().content_hash()
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
