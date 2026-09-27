"""Milestone 004 -- OS isolation measurement (module: os_isolation_measurement).

These tests assert on the *measured* posture of the host, and critically on the
rule that a status is never upgraded without real evidence of an attempted,
denied write.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from babylab.isolation import (
    EnforcementLayer,
    IsolationReport,
    IsolationStatus,
    assess_isolation,
    measure_broad_write_grant,
)
from babylab.paths import default_paths


class TestIsolationStatusVocabulary(unittest.TestCase):
    def test_status_never_collapses_to_a_bare_boolean(self):
        """Isolation must be reported as a graded status, not True/False."""
        self.assertEqual(
            {s.value for s in IsolationStatus},
            {"VERIFIED", "UNVERIFIED", "NOT_IMPLEMENTED"},
        )

    def test_verified_exists_only_as_a_distinct_state(self):
        self.assertNotEqual(IsolationStatus.VERIFIED, IsolationStatus.NOT_IMPLEMENTED)


class TestBroadWriteGrantParsing(unittest.TestCase):
    """The ACL parser must read the TRUSTEE, not the leading path token.

    A parser that mis-reads the trustee would report a clean boundary on a
    directory that is actually world-writable for any authenticated account.
    """

    def test_parsing_extracts_trustee_not_path(self):
        from babylab import isolation

        real_run = isolation._run
        sample = (
            "C:\\dev\\TharAI-EXP\\human_control BUILTIN\\Administrators:(I)(F)\n"
            "C:\\dev\\TharAI-EXP\\human_control NT AUTHORITY\\Authenticated Users:(I)(M)\n"
            "\n"
            "Successfully processed 1 files; Failed processing 0 files\n"
        )
        isolation._run = lambda cmd, timeout=60: (0, sample, "")
        try:
            m = measure_broad_write_grant(Path("C:/dev/TharAI-EXP/human_control"))
        finally:
            isolation._run = real_run

        value = m.value
        self.assertTrue(value["broad_write_present"], "Authenticated Users:(M) is a write grant")
        trustees = [e["trustee"] for e in value["broad_write_entries"]]
        self.assertIn("NT AUTHORITY\\Authenticated Users", trustees)
        # the path must never be mistaken for a trustee
        self.assertFalse(any(t.startswith("C:") for t in trustees))

    def test_read_only_acl_reports_no_broad_write(self):
        from babylab import isolation

        real_run = isolation._run
        sample = (
            "C:\\x BUILTIN\\Administrators:(I)(F)\n"
            "C:\\x NT AUTHORITY\\Authenticated Users:(I)(RX)\n"
        )
        isolation._run = lambda cmd, timeout=60: (0, sample, "")
        try:
            m = measure_broad_write_grant(Path("C:/x"))
        finally:
            isolation._run = real_run
        self.assertFalse(m.value["broad_write_present"])


class TestAssessNeverOverclaims(unittest.TestCase):
    def test_no_write_attempt_cannot_never_be_verified(self):
        """VERIFIED requires an attempted AND denied write. No evidence -> not VERIFIED."""
        report = assess_isolation(
            protected_paths=[Path(default_paths().root / "human_control")],
            write_attempt_performed=False,
            write_attempt_denied=False,
        )
        self.assertIsInstance(report, IsolationReport)
        self.assertNotEqual(report.status, IsolationStatus.VERIFIED)

    def test_report_states_layer_and_prerequisites(self):
        report = assess_isolation(
            protected_paths=[Path(default_paths().root / "human_control")],
            write_attempt_performed=False,
            write_attempt_denied=False,
        )
        self.assertIsInstance(report.layer, EnforcementLayer)
        self.assertTrue(report.prerequisites, "an unverified boundary must state its prerequisites")
        self.assertTrue(report.reasons, "an unverified boundary must state why")

    def test_every_measurement_carries_a_source(self):
        report = assess_isolation(
            protected_paths=[Path(default_paths().root / "human_control")],
            write_attempt_performed=False,
            write_attempt_denied=False,
        )
        self.assertTrue(report.measurements)
        for m in report.measurements:
            self.assertTrue(m.source, f"measurement {m.name} must record how it was observed")
            self.assertTrue(m.name)

    def test_assessment_is_deterministic_in_its_verdict_rules(self):
        """Same evidence in -> same verdict out."""
        a = assess_isolation([Path("C:/x")], write_attempt_performed=False, write_attempt_denied=False)
        b = assess_isolation([Path("C:/x")], write_attempt_performed=False, write_attempt_denied=False)
        self.assertEqual(a.status, b.status)


if __name__ == "__main__":
    unittest.main()
