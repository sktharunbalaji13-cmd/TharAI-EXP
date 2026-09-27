"""Milestone 005 -- the OS denial harness must not over-claim.

The central guard: a refusal raised in the *current* process is an application
observation, not an OS boundary. If the harness cannot enforce that, it will
eventually record the human operator's own PermissionError as OS_DENIED, which
is exactly the mislabelling section 15 forbids.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from babylab.osboundary import (
    ExecutionIdentity,
    IsolationState,
    Result,
    assess_os_isolation,
    attempt_in_process,
    classify_os_error,
    identify_current_process,
    require_distinct_principal,
)
from tests.support import LabTestCase


class TestIdentityIsCapturedFirst(LabTestCase):
    def test_identity_reports_username_and_integrity(self):
        ident = identify_current_process()
        self.assertTrue(ident.username)
        self.assertIn(ident.integrity_level, {"High", "Medium", "Low", "Unknown"})
        self.assertTrue(ident.source)

    def test_identity_records_whether_it_is_administrator(self):
        ident = identify_current_process()
        self.assertIsInstance(ident.is_administrator, bool)

    def test_sid_is_recorded_when_available(self):
        ident = identify_current_process()
        self.assertIsInstance(ident.sid, str)


class TestResultVocabulary(unittest.TestCase):
    def test_all_six_categories_exist(self):
        self.assertEqual(
            {r.value for r in Result},
            {"OS_DENIED", "APPLICATION_DENIED", "ALLOWED", "NOT_TESTABLE",
             "NOT_IMPLEMENTED", "UNKNOWN"},
        )

    def test_permission_error_maps_to_os_denied_at_the_os_layer(self):
        result, _ = classify_os_error(PermissionError("denied"))
        self.assertIs(result, Result.OS_DENIED)

    def test_other_errors_do_not_become_os_denied(self):
        for exc in (OSError("disk"), ValueError("x"), KeyError("k")):
            with self.subTest(exc=exc):
                result, _ = classify_os_error(exc)
                self.assertIsNot(result, Result.OS_DENIED)


class TestInProcessRefusalIsNotAnOsBoundary(LabTestCase):
    """The single most important guard in this milestone."""

    def test_permission_error_in_process_is_not_cross_process(self):
        attempt = attempt_in_process(
            "write protected", self.paths.human_control,
            lambda: (_ for _ in ()).throw(PermissionError("denied")),
        )
        self.assertIs(attempt.result, Result.OS_DENIED)
        self.assertFalse(attempt.cross_process)

    def test_require_distinct_principal_rejects_in_process_denial(self):
        """An in-process OS_DENIED must be rejected as a boundary claim."""
        attempt = attempt_in_process(
            "write protected", self.paths.human_control,
            lambda: (_ for _ in ()).throw(PermissionError("denied")),
        )
        with self.assertRaises(AssertionError) as ctx:
            require_distinct_principal([attempt])
        self.assertIn("not an OS boundary", str(ctx.exception))

    def test_require_distinct_principal_accepts_no_denials(self):
        require_distinct_principal([])

    def test_attempt_records_who_what_where_when(self):
        attempt = attempt_in_process(
            "append event", self.paths.event_store, lambda: None
        )
        payload = attempt.to_dict()
        for key in ("operation", "target", "result", "layer", "identity", "observed_at"):
            self.assertIn(key, payload)
        self.assertIn("username", payload["identity"])
        self.assertIn("integrity_level", payload["identity"])


class TestAssessmentNeverOverclaims(LabTestCase):
    def test_no_attempts_means_not_implemented(self):
        report = assess_os_isolation([])
        self.assertIs(report.state, IsolationState.NOT_IMPLEMENTED)

    def test_in_process_denial_does_not_produce_verified(self):
        attempt = attempt_in_process(
            "write protected", self.paths.human_control,
            lambda: (_ for _ in ()).throw(PermissionError("denied")),
        )
        report = assess_os_isolation([attempt])
        self.assertIsNot(report.state, IsolationState.VERIFIED)

    def test_missing_account_is_reported_as_a_fault(self):
        report = assess_os_isolation([])
        joined = " ".join(report.faults)
        self.assertTrue(
            "principal" in joined or "identity" in joined,
            "the absence of a distinct principal must be stated as a fault",
        )

    def test_prerequisites_are_concrete(self):
        report = assess_os_isolation([])
        self.assertTrue(report.prerequisites)
        joined = " ".join(report.prerequisites).lower()
        self.assertTrue("elevated" in joined or "account" in joined)

    def test_render_states_the_verdict(self):
        text = assess_os_isolation([]).render()
        self.assertIn("OS_ISOLATION = NOT_IMPLEMENTED", text)

    def test_verified_requires_a_cross_process_denial(self):
        """Constructing VERIFIED by hand still requires cross_process=True."""
        report = assess_os_isolation([])
        forged = ExecutionIdentity(
            username="BABY_AI_TEST", sid="", is_administrator=False,
            integrity_level="Low", source="test",
        )
        from babylab.osboundary import Attempt

        cross = Attempt(
            "write provenance", "x", Result.OS_DENIED, "operating system",
            forged, "2026-01-01T00:00:00+00:00", "denied", cross_process=True,
        )
        self.assertIs(assess_os_isolation([cross]).state, IsolationState.VERIFIED)


if __name__ == "__main__":
    unittest.main()
