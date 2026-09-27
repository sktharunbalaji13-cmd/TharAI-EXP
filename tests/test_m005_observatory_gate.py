"""Milestone 005 -- Observatory OS-boundary display and the birth safety gate.

Section 23: every displayed value must come from an actual observation.
Section 24: the gate requires OS isolation = VERIFIED, where VERIFIED means all
seven measured conditions -- not "the ACL code exists".
"""

from __future__ import annotations

import unittest

from babylab.isolation import (
    EnforcementLayer,
    IsolationReport,
    IsolationStatus,
    assess_isolation,
)
from birth.readiness import (
    OS_VERIFICATION_CONDITIONS,
    OsIsolationEvidence,
    assess_readiness,
)
from observatory.model import CognitiveState
from observatory.render import ObservatoryRenderer, RenderOptions
from observatory.snapshot import ObservatorySnapshot
from tests.test_m004_rendering import birth_payload, make_snapshot


def render(snap) -> str:
    return ObservatoryRenderer(RenderOptions(color=False)).render(snap)


def snapshot_with_boundary(boundary: dict) -> ObservatorySnapshot:
    return make_snapshot(birth=birth_payload(), os_boundary=dict(boundary))


def no_boundary() -> ObservatorySnapshot:
    return make_snapshot(birth=birth_payload())


OBSERVED = {
    "execution_identity": "BABY_AI_TEST",
    "integrity": "Low",
    "administrator": False,
    "os_isolation": "VERIFIED",
    "protected_evidence": "OS DENIED",
    "control_credentials": "OS DENIED",
    "provenance_keys": "OS DENIED",
    "experimental_workspace": "WRITE ALLOWED",
}


class TestOsBoundaryRendering(unittest.TestCase):
    def test_section_is_rendered_when_observed(self):
        text = render(snapshot_with_boundary(OBSERVED))
        self.assertIn("OS BOUNDARY", text)
        self.assertIn("BABY_AI_TEST", text)

    def test_administrator_is_shown_as_no(self):
        self.assertIn("NO", render(snapshot_with_boundary(OBSERVED)))

    def test_workspace_write_allowed_is_visible(self):
        self.assertIn("WRITE ALLOWED", render(snapshot_with_boundary(OBSERVED)))

    def test_denial_rows_are_visible(self):
        text = render(snapshot_with_boundary(OBSERVED))
        self.assertIn("OS DENIED", text)

    def test_absent_boundary_renders_nothing_rather_than_inventing(self):
        self.assertNotIn("OS BOUNDARY", render(no_boundary()))

    def test_missing_keys_render_unavailable_not_default(self):
        partial = snapshot_with_boundary({"os_isolation": "NOT_IMPLEMENTED"})
        text = render(partial)
        self.assertIn("NOT_IMPLEMENTED", text)
        self.assertIn("UNAVAILABLE", text)
        self.assertNotIn("VERIFIED", text)

    def test_unmeasured_state_is_never_upgraded_to_verified(self):
        for state in ("NOT_IMPLEMENTED", "UNVERIFIED", "FAILED", "UNAVAILABLE"):
            with self.subTest(state=state):
                text = render(snapshot_with_boundary({"os_isolation": state}))
                self.assertNotIn("os isolation     VERIFIED", text)

    def test_snapshot_serialises_the_boundary(self):
        payload = snapshot_with_boundary(OBSERVED).to_dict()
        self.assertEqual(payload["os_boundary"]["os_isolation"], "VERIFIED")


class TestSevenConditionGate(unittest.TestCase):
    def test_seven_conditions_are_declared(self):
        self.assertEqual(len(OS_VERIFICATION_CONDITIONS), 7)

    def test_all_unmeasured_is_not_implemented(self):
        self.assertEqual(OsIsolationEvidence().state(), "NOT_IMPLEMENTED")

    def test_all_measured_true_is_verified(self):
        evidence = OsIsolationEvidence(
            identity_exists=True, identity_verified=True,
            protected_paths_identified=True, writes_attempted=True,
            writes_denied_by_os=True, positive_access_works=True,
            evidence_unchanged=True,
        )
        self.assertTrue(evidence.is_verified())
        self.assertEqual(evidence.unmet(), ())

    def test_one_missing_condition_blocks_verification(self):
        evidence = OsIsolationEvidence(
            identity_exists=True, identity_verified=True,
            protected_paths_identified=True, writes_attempted=True,
            writes_denied_by_os=True, positive_access_works=True,
            evidence_unchanged=None,
        )
        self.assertFalse(evidence.is_verified())
        self.assertEqual(len(evidence.unmet()), 1)

    def test_unmeasured_is_distinct_from_failed(self):
        unmeasured = OsIsolationEvidence(identity_exists=True)
        failed = OsIsolationEvidence(identity_exists=False)
        self.assertNotEqual(unmeasured.state(), failed.state())

    def test_a_failed_condition_reports_failed(self):
        self.assertEqual(
            OsIsolationEvidence(writes_denied_by_os=False).state(), "FAILED"
        )

    def test_acl_code_presence_does_not_satisfy_the_gate(self):
        """Configuration is not enforcement."""
        evidence = OsIsolationEvidence(protected_paths_identified=True)
        self.assertFalse(evidence.is_verified())


class TestBirthGateBlocks(unittest.TestCase):
    def _isolation(self) -> IsolationReport:
        return assess_isolation([])

    def test_gate_is_blocked_while_os_isolation_is_not_implemented(self):
        report = assess_readiness(isolation=self._isolation())
        self.assertFalse(report.ready)
        self.assertIn("BIRTH READINESS: BLOCKED", report.render())

    def test_unmeasured_conditions_appear_individually(self):
        report = assess_readiness(
            isolation=self._isolation(),
            os_evidence=OsIsolationEvidence(),
        )
        rendered = report.render()
        for condition in OS_VERIFICATION_CONDITIONS:
            self.assertIn(condition, rendered)

    def test_no_single_green_verdict_is_possible(self):
        report = assess_readiness(
            isolation=self._isolation(),
            os_evidence=OsIsolationEvidence(
                identity_exists=True, identity_verified=True,
                protected_paths_identified=True, writes_attempted=True,
                writes_denied_by_os=True, positive_access_works=True,
                evidence_unchanged=True,
            ),
        )
        # Even with all seven satisfied, OS ISOLATION READY is still driven by
        # the measured isolation report, which on this host is NOT_IMPLEMENTED.
        self.assertFalse(report.ready)
        self.assertIn("BIRTH READINESS: BLOCKED", report.render())


if __name__ == "__main__":
    unittest.main()
