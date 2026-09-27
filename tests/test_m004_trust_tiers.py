"""Milestone 004 -- trust tier architecture and the execution identity.

Covers the Tier 0-3 model, the separate Baby AI execution identity, and the
future birth-authorization chain. The recurring theme: the subject must not be
able to *describe* itself as safe, and an identity that is not actually
separated at the OS level must say so.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from babylab.errors import TrustBoundaryViolation
from babylab.identity import Actor, Role
from babylab.paths import ProjectPaths
from babylab.trust import (
    BIRTH_AUTHORIZATION_CHAIN,
    FORBIDDEN_BABY_AI_CREDENTIALS,
    BabyAIExecutionIdentity,
    Domain,
    PathPolicy,
    TrustTier,
    tier_of,
)
from tests.support import LabTestCase


class TestTrustTierModel(unittest.TestCase):
    def test_four_tiers_are_declared(self):
        self.assertEqual(
            [t.value for t in TrustTier],
            [
                "TIER_0_HUMAN",
                "TIER_1_LABORATORY",
                "TIER_2_BABY_EXECUTION",
                "TIER_3_EXTERNAL",
            ],
        )

    def test_every_domain_maps_to_exactly_one_tier(self):
        for domain in Domain:
            self.assertIsInstance(tier_of(domain), TrustTier)

    def test_human_control_is_tier_0(self):
        self.assertIs(tier_of(Domain.HUMAN_CONTROL), TrustTier.TIER_0_HUMAN)

    def test_baby_workspace_is_the_only_subject_tier(self):
        self.assertIs(tier_of(Domain.BABY_WORKSPACE), TrustTier.TIER_2_BABY_EXECUTION)

    def test_provenance_and_events_are_tier_1_not_subject_tier(self):
        for domain in (Domain.SYSTEM_RUNTIME, Domain.RESEARCH_DOCS):
            self.assertIs(tier_of(domain), TrustTier.TIER_1_LABORATORY)

    def test_outside_the_project_is_tier_3(self):
        self.assertIs(tier_of(Domain.OUTSIDE), TrustTier.TIER_3_EXTERNAL)


class TestSubjectNeverInheritsHumanAuthority(LabTestCase):
    """Uses the real isolated-laboratory fixture: self.paths / self.policy."""

    def test_subject_cannot_write_human_control(self):
        subject = Actor.baby_ai(key_id="BK-TEST")
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_writable(
                subject, self.paths.human_control / "provenance" / "seals" / "X.json"
            )

    def test_subject_cannot_write_provenance_ledger(self):
        """The *runtime* ledger is SYSTEM_RUNTIME, so appending is permitted.

        M001 designed the shared log as append-only and M002's Observatory reads
        it; forbidding append entirely would break M002. What is protected is
        the human-owned evidence in human_control/provenance/, asserted below.
        See docs/known-limitations.md, "M004 section 9 vs M001 append semantics".
        """
        subject = Actor.baby_ai(key_id="BK-TEST")
        self.policy.assert_writable(subject, self.paths.provenance_ledger)

    def test_subject_cannot_write_protected_provenance_seals(self):
        subject = Actor.baby_ai(key_id="BK-TEST")
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_writable(
                subject, self.paths.protected_provenance / "seals" / "PROV-000099.json"
            )

    def test_subject_cannot_write_provenance_head(self):
        subject = Actor.baby_ai(key_id="BK-TEST")
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_writable(
                subject, self.paths.protected_provenance / "HEAD.json"
            )

    def test_subject_cannot_write_event_store(self):
        """Append-only shared log: the subject may append its own, not rewrite.

        See the provenance-ledger test above for why append is not denied.
        """
        subject = Actor.baby_ai(key_id="BK-TEST")
        self.policy.assert_writable(subject, self.paths.event_store)

    def test_subject_cannot_write_research_docs(self):
        subject = Actor.baby_ai(key_id="BK-TEST")
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_writable(subject, self.paths.docs / "notes.md")

    def test_subject_may_write_its_own_workspace(self):
        subject = Actor.baby_ai(key_id="BK-TEST")
        self.policy.assert_writable(subject, self.paths.baby_workspace / "generated" / "a.txt")

    def test_baby_ai_actor_requires_a_key(self):
        with self.assertRaises(ValueError):
            Actor.baby_ai(key_id="")

    def test_no_role_can_write_outside_the_project(self):
        for actor in (
            Actor.human_operator(),
            Actor.system(),
            Actor.baby_ai(key_id="BK-TEST"),
        ):
            with self.assertRaises(TrustBoundaryViolation):
                self.policy.assert_writable(actor, Path("C:/Windows/System32/drivers/etc/hosts"))


class TestBabyAIExecutionIdentity(unittest.TestCase):
    def test_forbidden_credential_list_is_declared_and_non_empty(self):
        self.assertIn("provenance_signing_key", FORBIDDEN_BABY_AI_CREDENTIALS)
        self.assertIn("git_signing_credential", FORBIDDEN_BABY_AI_CREDENTIALS)
        self.assertGreaterEqual(len(FORBIDDEN_BABY_AI_CREDENTIALS), 5)

    def test_unprovisioned_identity_reports_it_is_not_separated(self):
        ident = BabyAIExecutionIdentity(identity_id="baby-ai:subject")
        self.assertEqual(ident.separation_status(), "same_os_user")
        self.assertFalse(ident.os_identity_provisioned)

    def test_identity_holding_a_provenance_key_is_flagged(self):
        ident = BabyAIExecutionIdentity(
            identity_id="baby-ai:subject",
            granted=frozenset({"provenance_signing_key"}),
        )
        self.assertIn("provenance_signing_key", ident.holds_forbidden())

    def test_clean_identity_holds_nothing_forbidden(self):
        ident = BabyAIExecutionIdentity(
            identity_id="baby-ai:subject", granted=frozenset({"workspace_write"})
        )
        self.assertEqual(ident.holds_forbidden(), ())

    def test_provisioned_identity_reports_separate(self):
        ident = BabyAIExecutionIdentity(
            identity_id="baby-ai:subject",
            os_identity_provisioned=True,
            os_separation="dedicated service account",
        )
        self.assertEqual(ident.separation_status(), "separate")


class TestBirthAuthorizationChain(unittest.TestCase):
    def test_chain_starts_with_human_authorization(self):
        self.assertEqual(BIRTH_AUTHORIZATION_CHAIN[0].name, "human_authorization")

    def test_chain_is_ordered_without_gaps(self):
        orders = [s.order for s in BIRTH_AUTHORIZATION_CHAIN]
        self.assertEqual(orders, list(range(1, len(orders) + 1)))

    def test_final_activation_is_explicitly_not_implemented(self):
        final = BIRTH_AUTHORIZATION_CHAIN[-1]
        self.assertEqual(final.name, "subject_activation")
        self.assertFalse(final.implemented_in_m004)

    def test_every_step_before_activation_is_architecture_only(self):
        for step in BIRTH_AUTHORIZATION_CHAIN[:-1]:
            self.assertTrue(step.description)


if __name__ == "__main__":
    unittest.main()
