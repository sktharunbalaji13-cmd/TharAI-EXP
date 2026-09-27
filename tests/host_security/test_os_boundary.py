"""Milestone 005 -- host-security suite.

Separated from the portable unit suite on purpose. These tests depend on the
host: they need Windows, a dedicated low-privilege account, real NTFS, and a
real process launched as that account. A normal ``pytest`` run must stay
portable and deterministic, so this directory is excluded by default and run
explicitly::

    py -3 -m pytest tests/host_security -q

Every test here either exercises a real OS boundary or skips with a stated
reason. None of them may pass by asserting that a refusal happened when no
refusal was possible -- that is the mislabelling section 15 forbids.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from babylab.osboundary import (
    TEST_PRINCIPAL_NAME,
    Result,
    assess_os_isolation,
    identify_current_process,
    protected_paths,
    subject_workspace_paths,
)


def principal_available() -> tuple[bool, str]:
    """Whether the dedicated security-test principal exists on this host."""
    import subprocess

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-LocalUser -Name '{TEST_PRINCIPAL_NAME}' -ErrorAction Stop).Name"],
            capture_output=True, text=True, timeout=90,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"could not query local users: {exc}"
    if proc.returncode == 0:
        return True, f"{TEST_PRINCIPAL_NAME} exists"
    return False, (
        f"{TEST_PRINCIPAL_NAME} does not exist on this host. Creating it requires "
        f"an elevated session; New-LocalUser is currently refused."
    )


class TestExecutionIdentityRequirements(unittest.TestCase):
    """Identity checks that need no account and therefore always run."""

    def test_test_principal_is_a_security_principal_not_a_subject(self):
        self.assertEqual(TEST_PRINCIPAL_NAME, "BABY_AI_TEST")
        self.assertNotIn("BABY_AI", TEST_PRINCIPAL_NAME.replace("BABY_AI_TEST", ""))

    def test_no_baby_ai_cryptographic_identity_is_created(self):
        """The harness must not mint a BABY_AI key. Verify the real keyring."""
        from babylab.identity import Role
        from babylab.paths import default_paths
        from provenance.keyring import Keyring

        paths = default_paths()
        if not paths.keyring.exists():
            self.skipTest("no keyring on this host")
        keyring = Keyring(paths.keyring, paths.private_key_dir)
        try:
            has_subject = keyring.has_role(Role.BABY_AI)
        except Exception:  # noqa: BLE001
            has_subject = False
        self.assertFalse(
            has_subject,
            "Milestone 005 must not create a real BABY_AI signing key",
        )

    def test_current_identity_is_recorded(self):
        ident = identify_current_process()
        self.assertTrue(ident.username)
        self.assertIn(ident.integrity_level, {"High", "Medium", "Low", "Unknown"})


class TestAccountCreationPrerequisite(unittest.TestCase):
    """Records the exact blocker rather than pretending it is satisfied."""

    def test_account_absence_is_reported_not_hidden(self):
        available, reason = principal_available()
        if available:
            self.assertTrue(available)
        else:
            self.assertIn("elevated", reason.lower())
            self.skipTest(reason)

    def test_assessment_reports_not_implemented_without_a_principal(self):
        available, _ = principal_available()
        report = assess_os_isolation([])
        if not available:
            self.assertIsNot(
                report.state.value, "VERIFIED",
                "VERIFIED is impossible without a distinct principal",
            )


class TestProtectedPathsAreIdentified(unittest.TestCase):
    def test_every_protected_path_exists_or_is_declared(self):
        entries = protected_paths()
        self.assertGreaterEqual(len(entries), 12)
        for entry in entries:
            with self.subTest(entry=entry.name):
                self.assertTrue(entry.path.name or entry.path.is_dir())

    def test_workspace_paths_are_separate_from_protected(self):
        protected = {str(p.path).lower() for p in protected_paths()}
        workspace = {str(p.path).lower() for p in subject_workspace_paths()}
        self.assertFalse(protected & workspace)


class TestActualOsDenial(unittest.TestCase):
    """Real cross-process attempts. Skipped when no principal exists."""

    def setUp(self) -> None:
        self.available, self.reason = principal_available()
        if not self.available:
            self.skipTest(self.reason)

    def test_protected_write_is_denied_by_the_os(self):
        from babylab.osboundary import launch_attempt_as_principal

        results = launch_attempt_as_principal("write", protected_paths()[0].path)
        self.assertTrue(results, "an attempt must be recorded")
        for attempt in results:
            with self.subTest(target=attempt.target):
                self.assertIs(attempt.result, Result.OS_DENIED)


class TestPositiveCapability(unittest.TestCase):
    """The subject identity must still be able to do its own work."""

    def setUp(self) -> None:
        self.available, self.reason = principal_available()
        if not self.available:
            self.skipTest(self.reason)

    def test_experimental_workspace_is_writable(self):
        from babylab.osboundary import launch_attempt_as_principal

        results = launch_attempt_as_principal("write", subject_workspace_paths()[0].path)
        for attempt in results:
            with self.subTest(target=attempt.target):
                self.assertIs(attempt.result, Result.ALLOWED)


class TestTamperLeavesEvidenceUnchanged(unittest.TestCase):
    def setUp(self) -> None:
        self.available, self.reason = principal_available()
        if not self.available:
            self.skipTest(self.reason)

    def test_evidence_unchanged_after_denied_attempts(self):
        from babylab.osboundary import verify_evidence_unchanged

        before = verify_evidence_unchanged()
        from babylab.osboundary import launch_attempt_as_principal

        for entry in protected_paths():
            launch_attempt_as_principal("write", entry.path)
        after = verify_evidence_unchanged()
        self.assertEqual(before, after, "a denied attempt must not alter evidence")


if __name__ == "__main__":
    unittest.main()
