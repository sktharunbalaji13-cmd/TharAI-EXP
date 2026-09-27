"""Tests for the action boundary.

The property: nothing is ever granted, credentials never decide anything, and
self-asserted authority can only lower the effective trust level.
"""

from __future__ import annotations

import unittest

from babylab.errors import ValidationError
from birth.boundary import (
    REQUIRED_TRUST,
    TRUST_LEVELS,
    UNVERIFIED_CREDENTIAL_TRUST,
    ActionBoundary,
    ActionIntent,
    ActionKind,
    DecisionOutcome,
    RefusalReason,
    keyring_resolver,
)
from birth.cognitive import (
    CapabilityContract,
    CapabilityKind,
    CapabilityRegistry,
    CapabilityStatus,
)


def intent(kind: ActionKind, trust: str = "UNTRUSTED", credential: str = "") -> ActionIntent:
    return ActionIntent(
        kind=kind,
        target="target",
        summary="a summary",
        claimed_trust_level=trust,
        presented_credential_id=credential,
    )


def _all_implemented_registry() -> CapabilityRegistry:
    """A registry with every capability implemented, for isolating the trust layer.

    Never used outside tests. The real registry implements nothing, which means a
    default-registry test of the trust logic would be short-circuited by the
    capability check and would assert nothing about trust at all.
    """
    contracts = {
        kind: CapabilityContract(
            kind=kind,
            status=CapabilityStatus.IMPLEMENTED,
            contract="test double",
            reason="test double, not a real implementation",
            implementations=(f"tests.double.{kind.value.lower()}",),
        )
        for kind in CapabilityKind
    }
    return CapabilityRegistry(contracts)


class TestDenyByDefault(unittest.TestCase):
    def setUp(self) -> None:
        self.boundary = ActionBoundary()

    def test_allowlist_starts_empty(self) -> None:
        self.assertTrue(self.boundary.allowlist_is_empty)

    def test_every_action_kind_is_denied(self) -> None:
        for kind in ActionKind:
            with self.subTest(kind=kind.value):
                decision = self.boundary.authorize(intent(kind, trust="SYSTEM"))
                self.assertIs(decision.decision, DecisionOutcome.DENIED)
                self.assertIsNotNone(decision.reason)
                self.assertEqual(self.boundary.granted_count(), 0)

    def test_no_capability_is_implemented_so_capability_is_the_first_refusal(self) -> None:
        decision = self.boundary.authorize(intent(ActionKind.OBSERVE, trust="HUMAN"))
        self.assertIs(decision.reason, RefusalReason.NO_CAPABILITY)
        self.assertEqual(decision.capability_status, "UNAVAILABLE")

    def test_nothing_is_executed(self) -> None:
        """The boundary has no execution path.

        Checked over the parsed syntax tree rather than the raw text, so that the
        module's own prose describing *why* it has no executor cannot satisfy or
        fail the check.
        """
        import ast
        import inspect

        import birth.boundary as module

        tree = ast.parse(inspect.getsource(module))
        forbidden_modules = {"subprocess", "socket", "shutil", "ctypes", "asyncio"}
        forbidden_calls = {"system", "popen", "run", "Popen", "exec", "eval", "open"}
        imported: set[str] = set()
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called.add(func.attr)
        self.assertEqual(
            imported & forbidden_modules,
            set(),
            f"the action boundary must not import {sorted(imported & forbidden_modules)}",
        )
        self.assertEqual(
            called & forbidden_calls,
            set(),
            f"the action boundary must not call {sorted(called & forbidden_calls)}; it "
            "authorizes and performs nothing",
        )


class TestTrustLevels(unittest.TestCase):
    def setUp(self) -> None:
        self.boundary = ActionBoundary()

    def test_self_assertion_cannot_raise_the_effective_level(self) -> None:
        """A model claiming to be SYSTEM gets nothing at all, not the requirement."""
        claim = self.boundary.authorize(intent(ActionKind.OBSERVE, trust="SYSTEM"))
        required = REQUIRED_TRUST[ActionKind.OBSERVE]
        self.assertNotEqual(claim.effective_trust, "SYSTEM")
        self.assertEqual(claim.effective_trust, UNVERIFIED_CREDENTIAL_TRUST)
        self.assertNotEqual(claim.effective_trust, required)

    def test_effective_level_is_the_lowest_of_three(self) -> None:
        low = self.boundary.authorize(intent(ActionKind.OBSERVE, trust="UNTRUSTED"))
        self.assertEqual(low.effective_trust, "UNTRUSTED")
        high = self.boundary.authorize(intent(ActionKind.OBSERVE, trust="SYSTEM"))
        self.assertEqual(
            high.effective_trust,
            "UNTRUSTED",
            "a claim of SYSTEM with no verified credential is worth UNTRUSTED",
        )

    def test_every_trust_level_is_capped_by_the_requirement(self) -> None:
        for level in TRUST_LEVELS:
            for kind in ActionKind:
                with self.subTest(level=level, kind=kind.value):
                    decision = self.boundary.authorize(intent(kind, trust=level))
                    self.assertEqual(
                        decision.effective_trust,
                        min((level, UNVERIFIED_CREDENTIAL_TRUST), key=TRUST_LEVELS.index),
                    )

    def test_effectful_actions_require_at_least_a_human(self) -> None:
        for kind in ActionKind:
            if kind.is_effectful:
                with self.subTest(kind=kind.value):
                    self.assertIn(REQUIRED_TRUST[kind], ("HUMAN", "SYSTEM"))

    def test_unknown_trust_level_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            intent(ActionKind.OBSERVE, trust="OMNISCIENT")

    def test_self_asserted_system_cannot_reach_human_authority(self) -> None:
        """The escalation this design exists to prevent.

        A request claiming ``SYSTEM`` for a ``HUMAN``-gated action must not
        arrive holding ``HUMAN`` authority on the strength of its own say-so.
        Taking the minimum of claim and requirement alone would have let it.

        Checked against a registry whose capabilities are all implemented, so the
        trust layer is what is actually being exercised rather than the absent
        capability short-circuiting ahead of it.
        """
        boundary = ActionBoundary(registry=_all_implemented_registry())
        decision = boundary.authorize(
            intent(ActionKind.RUN_CODE, trust="SYSTEM", credential="key-abc")
        )
        self.assertEqual(decision.required_trust, "HUMAN")
        self.assertEqual(decision.capability_status, "IMPLEMENTED")
        self.assertEqual(decision.effective_trust, "UNTRUSTED")
        self.assertLess(
            TRUST_LEVELS.index(decision.effective_trust), TRUST_LEVELS.index("HUMAN")
        )
        self.assertIs(decision.reason, RefusalReason.TRUST_LEVEL_INSUFFICIENT)

    def test_a_verified_human_credential_clears_the_trust_layer(self) -> None:
        """The complementary case, so the denial above is not vacuous."""
        boundary = ActionBoundary(
            registry=_all_implemented_registry(),
            credential_resolver=lambda _c: "HUMAN",
        )
        decision = boundary.authorize(
            intent(ActionKind.RUN_CODE, trust="HUMAN", credential="human-key")
        )
        self.assertEqual(decision.effective_trust, "HUMAN")
        self.assertIsNot(decision.reason, RefusalReason.TRUST_LEVEL_INSUFFICIENT)
        self.assertIs(decision.reason, RefusalReason.ALLOWLIST_EMPTY)


class TestCredentialsAreNotAuthority(unittest.TestCase):
    def setUp(self) -> None:
        self.boundary = ActionBoundary()

    def test_a_credential_never_determines_the_outcome(self) -> None:
        without = self.boundary.authorize(intent(ActionKind.NETWORK, trust="MODEL"))
        with_credential = self.boundary.authorize(
            intent(ActionKind.NETWORK, trust="MODEL", credential="subject-key-1")
        )
        self.assertIs(without.decision, with_credential.decision)
        self.assertIs(without.reason, with_credential.reason)
        self.assertFalse(with_credential.credential_determined_outcome)

    def test_unverified_credential_is_worth_nothing(self) -> None:
        self.assertEqual(
            self.boundary.credential_trust("subject-key-1"),
            UNVERIFIED_CREDENTIAL_TRUST,
        )

    def test_a_failing_resolver_fails_closed(self) -> None:
        def explode(_credential_id: str) -> str:
            raise RuntimeError("keyring unavailable")

        boundary = ActionBoundary(credential_resolver=explode)
        self.assertEqual(
            boundary.credential_trust("any"), UNVERIFIED_CREDENTIAL_TRUST
        )

    def test_a_resolver_returning_junk_fails_closed(self) -> None:
        boundary = ActionBoundary(credential_resolver=lambda _c: "GODMODE")
        self.assertEqual(boundary.credential_trust("any"), UNVERIFIED_CREDENTIAL_TRUST)

    def test_credential_is_named_in_the_denial_detail(self) -> None:
        boundary = ActionBoundary(registry=_all_implemented_registry())
        decision = boundary.authorize(
            intent(ActionKind.MODIFY_LAB, trust="SYSTEM", credential="subject-key-1")
        )
        self.assertIn("subject-key-1", decision.detail)

    def test_credential_value_is_not_published_in_the_decision(self) -> None:
        payload = self.boundary.authorize(
            intent(ActionKind.CONTROL, trust="SYSTEM", credential="secret-token")
        ).to_dict()
        self.assertNotIn("secret-token", str(payload))


class TestKeyringResolver(unittest.TestCase):
    def setUp(self) -> None:
        from babylab.identity import Role

        class FakeKeyring:
            def __init__(self) -> None:
                self._roles = {
                    "k-human": Role.HUMAN,
                    "k-system": Role.SYSTEM,
                    "k-subject": Role.BABY_AI,
                }

            def role_of(self, key_id: str):
                return self._roles[key_id]

        self.resolve = keyring_resolver(FakeKeyring())

    def test_baby_ai_key_resolves_to_subject_and_no_higher(self) -> None:
        self.assertEqual(self.resolve("k-subject"), "SUBJECT")

    def test_human_and_system_keys_resolve_to_themselves(self) -> None:
        self.assertEqual(self.resolve("k-human"), "HUMAN")
        self.assertEqual(self.resolve("k-system"), "SYSTEM")

    def test_a_subject_key_cannot_authorise_an_effectful_action(self) -> None:
        boundary = ActionBoundary(credential_resolver=self.resolve)
        decision = boundary.authorize(
            intent(ActionKind.RUN_CODE, trust="SUBJECT", credential="k-subject")
        )
        self.assertEqual(decision.required_trust, "HUMAN")
        self.assertEqual(decision.effective_trust, "SUBJECT")
        self.assertIs(decision.decision, DecisionOutcome.DENIED)
        self.assertIn(
            decision.reason,
            (RefusalReason.TRUST_LEVEL_INSUFFICIENT, RefusalReason.NO_CAPABILITY),
            "either way it is denied; with the default registry the absent "
            "capability is the first blocker, which is reported first on purpose",
        )


class TestDecisionRecording(unittest.TestCase):
    def setUp(self) -> None:
        self.boundary = ActionBoundary()

    def test_every_decision_is_retained(self) -> None:
        for kind in ActionKind:
            self.boundary.authorize(intent(kind))
        self.assertEqual(len(self.boundary.decisions), len(ActionKind))
        self.assertEqual(self.boundary.denied_count(), len(ActionKind))

    def test_denial_detail_explains_the_blocker(self) -> None:
        decision = self.boundary.authorize(intent(ActionKind.PERCEIVE if False else ActionKind.OBSERVE))
        self.assertTrue(decision.detail.strip())
        self.assertIn(decision.reason.value, decision.to_dict()["detail"] + decision.reason.value)

    def test_event_payload_is_reportable(self) -> None:
        payload = self.boundary.authorize(intent(ActionKind.OBSERVE)).to_event_payload()
        for key in ("decision", "reason", "action_kind", "required_trust", "capability_status"):
            self.assertIn(key, payload)

    def test_boundary_summary_states_that_it_executes_nothing(self) -> None:
        self.boundary.authorize(intent(ActionKind.OBSERVE))
        self.assertIn("performs nothing", self.boundary.to_dict()["note"])


class TestIntentValidation(unittest.TestCase):
    def test_empty_target_and_summary_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ActionIntent(kind=ActionKind.OBSERVE, target="  ", summary="s")
        with self.assertRaises(ValidationError):
            ActionIntent(kind=ActionKind.OBSERVE, target="t", summary="")

    def test_intent_hash_is_stable(self) -> None:
        first = intent(ActionKind.OBSERVE)
        second = intent(ActionKind.OBSERVE)
        self.assertEqual(first.intent_hash(), second.intent_hash())
        self.assertNotEqual(first.intent_hash(), intent(ActionKind.NETWORK).intent_hash())

    def test_default_registry_denies_everything(self) -> None:
        boundary = ActionBoundary(registry=CapabilityRegistry())
        for kind in ActionKind:
            with self.subTest(kind=kind.value):
                self.assertIs(
                    boundary.authorize(intent(kind, trust="SYSTEM")).decision,
                    DecisionOutcome.DENIED,
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
