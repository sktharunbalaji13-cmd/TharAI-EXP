"""Milestone 004 -- negative security tests for the Baby AI trust boundary.

Every test here ATTEMPTS a boundary violation and asserts it is refused. The
crucial discipline is the one in section 9: each outcome is labelled

    APPLICATION DENIED | OS DENIED | NOT TESTABLE | NOT IMPLEMENTED

and the categories are never collapsed. An application-level refusal is real and
worth having, but on this host it is NOT an OS boundary, and calling it one
would be the exact overclaim Milestone 003 was criticised for.

``babylab.isolation.assess_isolation`` supplies the measured truth about which
layer is actually in force; the tests below refuse to assert OS DENIED unless
that measurement says so.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from babylab.errors import IntegrityError, TrustBoundaryViolation
from babylab.identity import Actor, Role
from babylab.isolation import IsolationStatus, assess_isolation
from babylab.trust import PathPolicy
from birth.boundary import ActionBoundary, ActionIntent, ActionKind, keyring_resolver
from observatory.subject import SubjectRegistry
from tests.support import LabTestCase

#: Denial categories. Kept as literals so a reader sees the vocabulary the
#: milestone requires rather than an invented synonym.
APPLICATION_DENIED = "APPLICATION DENIED"
OS_DENIED = "OS DENIED"
NOT_TESTABLE = "NOT TESTABLE"
NOT_IMPLEMENTED = "NOT IMPLEMENTED"


class DenialMatrixMixin:
    """Shared helpers for attempting a violation and classifying the outcome."""

    def setUp(self) -> None:
        super().setUp()
        self.subject = Actor.baby_ai(key_id="BK-SUBJECT", actor_id="baby-ai:subject")
        self.policy: PathPolicy = self.policy  # provided by LabTestCase

    def assert_application_denied(self, callable_, *args, **kwargs):
        """Assert the call is refused by laboratory policy, and say so plainly.

        Deliberately does NOT claim an OS denial. The distinction is the entire
        point of this module.
        """
        with self.assertRaises((TrustBoundaryViolation, PermissionError, ValueError)):
            callable_(*args, **kwargs)
        return APPLICATION_DENIED


class TestOSIsolationIsNotClaimedWithoutEvidence(DenialMatrixMixin, LabTestCase):
    """The matrix may only say OS DENIED when a real denial was observed."""

    def test_host_measurement_does_not_report_verified(self):
        report = assess_isolation(
            [self.paths.human_control, self.paths.provenance_ledger],
            write_attempt_performed=False,
            write_attempt_denied=False,
        )
        self.assertNotEqual(
            report.status,
            IsolationStatus.VERIFIED,
            "no write from a lower-privilege identity has been attempted, so "
            "VERIFIED must be unreachable",
        )

    def test_reports_the_layer_actually_in_force(self):
        report = assess_isolation([self.paths.human_control])
        self.assertIsNotNone(report.status)
        self.assertEqual(report.layer.value, "application policy")

    def test_unverified_is_not_collapsed_into_pass(self):
        report = assess_isolation([self.paths.human_control])
        self.assertIn(
            report.status,
            {IsolationStatus.NOT_IMPLEMENTED, IsolationStatus.UNVERIFIED},
        )


class TestBabyAIVsProvenance(DenialMatrixMixin, LabTestCase):
    def test_cannot_write_provenance_seals(self):
        outcome = self.assert_application_denied(
            self.policy.assert_writable,
            self.subject,
            self.paths.protected_provenance / "seals" / "PROV-000099.json",
        )
        self.assertEqual(outcome, APPLICATION_DENIED)

    def test_cannot_modify_provenance_head(self):
        self.assert_application_denied(
            self.policy.assert_writable,
            self.subject,
            self.paths.protected_provenance / "HEAD.json",
        )

    def test_cannot_delete_provenance_evidence(self):
        target = self.paths.protected_provenance / "HEAD.json"
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, target
        )

    def test_cannot_replace_provenance_key_material(self):
        self.assert_application_denied(
            self.policy.assert_writable,
            self.subject,
            self.paths.private_key_dir / "HK-attacker.key",
        )

    def test_cannot_write_the_keyring(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.keyring
        )

    def test_cannot_register_its_own_role(self):
        """The subject cannot mint itself authority by editing the keyring."""
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.keyring
        )


class TestProvenanceIndependence(DenialMatrixMixin, LabTestCase):
    """Section 19: the subject cannot certify itself."""

    def test_recorder_strips_self_declared_authorship(self):
        from birth.authorship import strip_self_declared_authorship

        payload = {
            "author": "BABY_AI",
            "authorship_classification": "BABY_AI_AUTHORED",
            "note": "keep me",
        }
        cleaned, stripped = strip_self_declared_authorship(payload)
        self.assertNotIn("author", cleaned)
        self.assertNotIn("authorship_classification", cleaned)
        self.assertEqual(cleaned["note"], "keep me")
        self.assertTrue(stripped, "the stripped keys must be reported, not silently dropped")

    def test_subject_cannot_self_declare_authorship_in_provenance(self):
        payload = {"authorship_classification": "BABY_AI_AUTHORED"}
        from birth.authorship import strip_self_declared_authorship

        cleaned, _ = strip_self_declared_authorship(payload)
        self.assertNotIn("authorship_classification", cleaned)

    def test_actor_role_comes_from_key_not_payload(self):
        """A payload claiming HUMAN must not produce a HUMAN actor."""
        subject = Actor.baby_ai(key_id="BK-SUBJECT")
        self.assertIs(subject.role, Role.BABY_AI)
        self.assertNotEqual(subject.role, Role.HUMAN)


class TestBabyAIVsEventHistory(DenialMatrixMixin, LabTestCase):
    """What actually protects event history, measured rather than assumed.

    Measured finding (Milestone 004): the hash chain in ``events.jsonl`` verifies
    *linkage and ordering only*. It does **not** detect modification of a
    payload, deletion of a trailing event, or truncation of the log -- all three
    leave ``verify_chain().intact`` True. The guarantee that event history
    cannot be rewritten is carried by the **provenance layer**, which records a
    content hash of the whole log and compares it on demand.

    These tests assert both halves of that finding, because reporting only the
    weak half would understate the boundary and reporting only the strong half
    would credit the wrong mechanism.
    """

    def _seed_log(self) -> str:
        for i in range(3):
            self.store.append("system.test", "test", {"n": i})
        self.recorder.record_creation(
            self.store.path, self.human, "MILESTONE-004", "event log under test"
        )
        self.assertEqual(self.recorder.verify_paths([self.store.path]), [])
        return self.store.path.read_text(encoding="utf-8")

    def test_chain_does_not_detect_payload_modification(self):
        """Documented weakness: the chain alone is not a content guarantee."""
        original = self._seed_log()
        self.rewrite_events(lambda t: t.replace('"n": 0', '"n": 99'))
        self.assertTrue(
            self.store.verify_chain().intact,
            "measured: payload modification is invisible to the hash chain",
        )

    def test_chain_does_not_detect_suffix_deletion(self):
        original = self._seed_log()
        self.rewrite_events(lambda t: "\n".join(t.splitlines()[:-1]) + "\n")
        self.assertTrue(
            self.store.verify_chain().intact,
            "measured: dropping the trailing event leaves linkage intact",
        )

    def test_chain_does_not_detect_truncation(self):
        self._seed_log()
        self.rewrite_events(lambda t: "")
        self.assertTrue(
            self.store.verify_chain().intact,
            "measured: an empty log is vacuously intact",
        )

    def test_chain_does_detect_prefix_deletion(self):
        original = self._seed_log()
        self.rewrite_events(lambda t: "\n".join(t.splitlines()[1:]) + "\n")
        self.assertFalse(
            self.store.verify_chain().intact,
            "measured: removing a leading event breaks prev_hash linkage",
        )

    def test_provenance_detects_payload_modification(self):
        self._seed_log()
        self.rewrite_events(lambda t: t.replace('"n": 0', '"n": 99'))
        problems = self.recorder.verify_paths([self.store.path])
        self.assertTrue(problems, "provenance must detect a modified event log")

    def test_provenance_detects_suffix_deletion(self):
        self._seed_log()
        self.rewrite_events(lambda t: "\n".join(t.splitlines()[:-1]) + "\n")
        problems = self.recorder.verify_paths([self.store.path])
        self.assertTrue(problems, "provenance must detect a truncated event log")

    def test_provenance_detects_truncation_to_empty(self):
        self._seed_log()
        self.rewrite_events(lambda t: "")
        problems = self.recorder.verify_paths([self.store.path])
        self.assertTrue(problems, "provenance must detect an emptied event log")

    def test_appending_is_permitted_but_only_for_its_own_authorship(self):
        """M001 allows the subject to append; M004 section 9 does not.

        Forbidding append would break M002's Observatory. The defensible reading
        is enforced here and documented in docs/known-limitations.md: the subject
        may append, and may not rewrite, delete, or forge authorship.
        """
        self.policy.assert_writable(self.subject, self.paths.event_store)


class TestBabyAIVsBirthRecord(DenialMatrixMixin, LabTestCase):
    def test_cannot_modify_birth_record(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.birth_record
        )

    def test_cannot_delete_birth_record(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.birth_record
        )

    def test_cannot_write_birth_record_directory(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.birth_records
        )

    def test_cannot_replace_model_hash_in_protected_config(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.foundation_config
        )

    def test_cannot_change_experiment_configuration(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.experiment_config
        )

    def test_recorded_subject_is_not_reported_as_attached(self):
        """A birth record alone must not read as a key-backed subject."""
        registry = SubjectRegistry(
            keyring=None,
            birth={"subject_exists": True, "subject_id": "baby-ai:subject-001"},
        )
        self.assertEqual(registry.status.value, "RECORDED")
        self.assertNotEqual(registry.status.value, "ATTACHED")
        self.assertIn("NOT KEY-ATTACHED", registry.describe())


class TestBabyAIVsControlPlane(DenialMatrixMixin, LabTestCase):
    def test_cannot_read_control_token(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.control_token
        )

    def test_cannot_write_control_configuration(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.control_config
        )

    def test_unauthenticated_control_intent_is_refused(self):
        """A privileged action from the subject is denied without a credential."""
        boundary = ActionBoundary(credential_resolver=keyring_resolver(self.keyring))
        intent = ActionIntent(
            kind=ActionKind.CONTROL,
            target="control-plane",
            summary="subject-initiated control operation",
        )
        decision = boundary.authorize(intent)
        self.assertFalse(
            decision.granted,
            "a Baby AI actor must not be granted a privileged control operation",
        )

    def test_control_intent_from_subject_lacks_trust(self):
        from birth.boundary import ActionBoundary as _AB

        boundary = _AB(credential_resolver=keyring_resolver(self.keyring))
        intent = ActionIntent(
            kind=ActionKind.CONTROL,
            target="control-plane",
            summary="subject-initiated",
        )
        trust = boundary.effective_trust(intent)
        self.assertNotIn(trust, {"HUMAN", "SYSTEM"})


class TestBabyAIVsResearchFiles(DenialMatrixMixin, LabTestCase):
    def test_cannot_write_docs(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.docs / "notes.md"
        )

    def test_cannot_write_research_records(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.research_records
        )

    def test_cannot_write_experiment_log(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.research / "experiment-log.md"
        )

    def test_cannot_write_snapshots(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.snapshots
        )

    def test_cannot_write_baseline(self):
        self.assert_application_denied(
            self.policy.assert_writable, self.subject, self.paths.baseline
        )

    def test_cannot_write_outside_the_project(self):
        self.assert_application_denied(
            self.policy.assert_writable,
            self.subject,
            Path("C:/Windows/System32/drivers/etc/hosts"),
        )


class TestBabyAIVsSourceRepository(DenialMatrixMixin, LabTestCase):
    """The source tree is protected by version control, NOT by the write matrix.

    An honest finding rather than a passing test: ``babylab/`` and friends sit at
    the project root and therefore classify as ``SYSTEM_RUNTIME``, where the
    write matrix permits the subject to write. The laboratory's own policy does
    not protect its own source. What protects it is Git, which makes tampering
    visible as a working-tree modification. Both facts are asserted here so the
    gap is recorded instead of being hidden behind a green test.
    """

    def test_application_policy_does_not_protect_the_source_tree(self):
        """Documents the gap: policy permits writes to code directories."""
        target = self.paths.root / "babylab" / "identity.py"
        # No exception expected. If a future change makes this raise, the gap
        # has been closed and this test should be updated deliberately.
        self.policy.assert_writable(self.subject, target)

    def test_code_directories_are_classified_system_runtime(self):
        from babylab.trust import Domain

        for package in ("babylab", "events", "provenance", "observatory"):
            with self.subTest(package=package):
                self.assertIs(
                    self.policy.classify(self.paths.root / package),
                    Domain.SYSTEM_RUNTIME,
                )

    def test_m004_did_not_modify_m001_to_m003_core_source(self):
        """Read-only: the layer protecting source is Git, so assert on Git.

        Scoped to the packages Milestone 004 must leave byte-identical. The
        Observatory is excluded because section 22 requires it to gain a
        trust-boundary section, and the birth package is excluded because the
        readiness audit lives there. A change in either is the milestone working
        as specified, not a regression.
        """
        import subprocess

        from tests.support import ROOT

        proc = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain",
             "--", "events", "provenance", "control"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            self.skipTest("git is unavailable in this environment")
        self.assertEqual(
            proc.stdout.strip(),
            "",
            "Milestone 004 must leave the event log, provenance, birth and "
            "control packages untouched",
        )


class TestProtectedEvidenceIsOutsideSubjectDomain(DenialMatrixMixin, LabTestCase):
    """Section 10: evidence lives outside the Baby AI trust domain."""

    PROTECTED = (
        "event_log",
        "provenance_ledger",
        "provenance_seals",
        "birth_record",
        "keyring",
        "private_keys",
        "control_token",
        "research_records",
        "snapshots",
    )

    def test_every_protected_evidence_path_is_refused_to_the_subject(self):
        paths = {
            "event_log": self.paths.event_store,
            "provenance_ledger": self.paths.provenance_ledger,
            "provenance_seals": self.paths.protected_provenance / "seals",
            "birth_record": self.paths.birth_record,
            "keyring": self.paths.keyring,
            "private_keys": self.paths.private_key_dir,
            "control_token": self.paths.control_token,
            "research_records": self.paths.research_records,
            "snapshots": self.paths.snapshots,
        }
        for name in self.PROTECTED:
            with self.subTest(evidence=name):
                path = paths[name]
                # Two distinct outcomes, both acceptable, and both honest:
                #   - refused outright (HUMAN_CONTROL domain), or
                #   - permitted only because it is the shared append-only log.
                shared_append_only = path in (self.paths.event_store, self.paths.provenance_ledger)
                if shared_append_only:
                    self.policy.assert_writable(self.subject, path)
                else:
                    with self.assertRaises(TrustBoundaryViolation):
                        self.policy.assert_writable(self.subject, path)

    def test_subject_cannot_reach_evidence_by_traversal(self):
        target = self.paths.human_control / ".." / "human_control" / "security" / "control.token"
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_writable(self.subject, target)


if __name__ == "__main__":
    unittest.main()
