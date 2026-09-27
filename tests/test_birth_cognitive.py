"""Tests for the capability registry.

The assertions here are largely negative, and that is the point: the tests fail
if a capability is implemented, if an ordering appears, or if a subject-side
attribute is introduced.
"""

from __future__ import annotations

import inspect
import re
import unittest

from babylab.errors import ValidationError
from birth import cognitive
from birth.cognitive import (
    CapabilityContract,
    CapabilityKind,
    CapabilityRegistry,
    CapabilityStatus,
    capability_names,
    contract_texts,
    default_registry,
)

#: Words that would turn an interface registry into a story about a mind. If one
#: of these appears as a *capability name* or in a status, a developmental
#: curriculum has crept in.
FORBIDDEN_VOCABULARY = (
    "stage",
    "developmental",
    "phase",
    "level",
    "maturity",
    "readiness",
    "emotion",
    "motivat",
    "curios",
    "conscious",
    "intellig",
    "personality",
    "empathy",
    "self_aware",
)


class TestRegistryShape(unittest.TestCase):
    def test_is_a_set_of_all_declared_capabilities(self) -> None:
        self.assertIsInstance(cognitive.CAPABILITY_KINDS, frozenset)
        self.assertEqual(len(cognitive.CAPABILITY_KINDS), 9)

    def test_covers_every_kind_exactly_once(self) -> None:
        registry = CapabilityRegistry()
        self.assertEqual(len(registry), len(cognitive.CAPABILITY_KINDS))
        for kind in CapabilityKind:
            self.assertIn(kind, registry)

    def test_registry_rejects_a_partial_set(self) -> None:
        contracts = default_registry()
        contracts.pop(CapabilityKind.MEMORY)
        with self.assertRaises(ValidationError):
            CapabilityRegistry(contracts)

    def test_registry_rejects_an_extra_capability(self) -> None:
        contracts = default_registry()
        contracts["IMAGINATION"] = CapabilityContract(
            kind="IMAGINATION",
            status=CapabilityStatus.UNAVAILABLE,
            contract="x",
            reason="y",
        )
        with self.assertRaises(ValidationError):
            CapabilityRegistry(contracts)


class TestNoOrdering(unittest.TestCase):
    def test_no_precedence_or_progression_field_exists(self) -> None:
        """Ordering cannot be reintroduced through a new field without failing this."""
        forbidden = {"precedes", "follows", "unlocks", "depends_on", "order", "rank", "index"}
        for contract in CapabilityRegistry():
            with self.subTest(capability=contract.kind.value):
                self.assertEqual(
                    forbidden & set(contract.to_dict()),
                    set(),
                    f"{contract.kind.value} gained an ordering field",
                )

    def test_status_values_are_unordered(self) -> None:
        """A status must not be rankable. Incomparability is the property."""
        members = list(CapabilityStatus)
        for left in members:
            for right in members:
                for operation in ("__lt__", "__le__", "__gt__", "__ge__"):
                    with self.subTest(left=left.value, op=operation):
                        with self.assertRaises(TypeError):
                            getattr(left, operation)(right)

    def test_ordering_error_explains_why(self) -> None:
        with self.assertRaises(TypeError) as caught:
            CapabilityStatus.IMPLEMENTED > CapabilityStatus.UNAVAILABLE  # noqa: B015
        message = str(caught.exception)
        self.assertIn("not ordered", message)
        self.assertIn("developmental", message)

    def test_names_are_sorted_only_for_display(self) -> None:
        names = capability_names()
        self.assertEqual(names, sorted(names))
        self.assertNotEqual(
            [item.value for item in CapabilityKind],
            names,
            "the enum's declaration order and the display order should differ, "
            "which shows the listing order is chosen rather than meaningful",
        )

    def test_iteration_order_does_not_change_status(self) -> None:
        registry = CapabilityRegistry()
        first = {c.kind.value: c.status.value for c in registry}
        shuffled = CapabilityRegistry(
            {kind: registry.get(kind) for kind in reversed(list(CapabilityKind))}
        )
        second = {c.kind.value: c.status.value for c in shuffled}
        self.assertEqual(first, second)


class TestHonestStatuses(unittest.TestCase):
    def test_nothing_is_implemented(self) -> None:
        for contract in CapabilityRegistry():
            with self.subTest(capability=contract.kind.value):
                self.assertNotEqual(
                    contract.status,
                    CapabilityStatus.IMPLEMENTED,
                    f"{contract.kind.value} claims to be implemented; Milestone 003 "
                    "implements no cognitive capability",
                )
                self.assertFalse(contract.status.is_functional)

    def test_no_capability_advertises_functionality(self) -> None:
        registry = CapabilityRegistry()
        self.assertEqual(registry.to_dict()["functional"], [])

    def test_experimentation_is_explicitly_deferred(self) -> None:
        registry = CapabilityRegistry()
        self.assertIs(
            registry.status_of(CapabilityKind.EXPERIMENTATION),
            CapabilityStatus.NOT_YET_IMPLEMENTED,
        )
        self.assertIn("curriculum", registry.get(CapabilityKind.EXPERIMENTATION).reason)

    def test_every_contract_states_its_shape_and_why(self) -> None:
        for contract in CapabilityRegistry():
            with self.subTest(capability=contract.kind.value):
                self.assertTrue(contract.contract.strip())
                self.assertTrue(contract.reason.strip())

    def test_implemented_requires_a_named_implementation(self) -> None:
        with self.assertRaises(ValidationError):
            CapabilityContract(
                kind=CapabilityKind.MEMORY,
                status=CapabilityStatus.IMPLEMENTED,
                contract="c",
                reason="r",
            )

    def test_absent_capability_cannot_name_implementations(self) -> None:
        with self.assertRaises(ValidationError):
            CapabilityContract(
                kind=CapabilityKind.MEMORY,
                status=CapabilityStatus.UNAVAILABLE,
                contract="c",
                reason="r",
                implementations=("birth.memory",),
            )

    def test_blocked_requires_a_reason(self) -> None:
        with self.assertRaises(ValidationError):
            CapabilityContract(
                kind=CapabilityKind.MEMORY,
                status=CapabilityStatus.BLOCKED,
                contract="c",
                reason="r",
            )

    def test_simulated_is_not_functional(self) -> None:
        self.assertFalse(CapabilityStatus.SIMULATED.is_functional)
        self.assertFalse(CapabilityStatus.SIMULATED.is_advertised)

    def test_missing_contract_or_reason_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CapabilityContract(
                kind=CapabilityKind.MEMORY,
                status=CapabilityStatus.UNAVAILABLE,
                contract="  ",
                reason="r",
            )
        with self.assertRaises(ValidationError):
            CapabilityContract(
                kind=CapabilityKind.MEMORY,
                status=CapabilityStatus.UNAVAILABLE,
                contract="c",
                reason="",
            )


class TestNoPsychology(unittest.TestCase):
    def test_no_capability_name_is_psychological(self) -> None:
        for name in capability_names():
            lowered = name.lower()
            for word in FORBIDDEN_VOCABULARY:
                with self.subTest(capability=name, word=word):
                    self.assertNotIn(word, lowered)

    def test_no_contract_text_describes_an_inner_state(self) -> None:
        for name, text in contract_texts().items():
            lowered = text.lower()
            for word in FORBIDDEN_VOCABULARY:
                with self.subTest(capability=name, word=word):
                    self.assertNotIn(
                        word,
                        lowered,
                        f"{name}'s contract text uses {word!r}, which describes the "
                        "subject rather than the interface",
                    )

    def test_no_source_reference_to_a_personality_or_emotion_metric(self) -> None:
        source = inspect.getsource(cognitive).lower()
        for word in ("emotional_state", "mood", "happiness", "intelligence_score", "iq"):
            with self.subTest(word=word):
                self.assertNotIn(word, source)

    def test_registry_hash_is_stable(self) -> None:
        self.assertEqual(
            CapabilityRegistry().registry_hash(), CapabilityRegistry().registry_hash()
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
