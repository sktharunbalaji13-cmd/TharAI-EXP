"""Milestone 004 -- audit snapshot and birth readiness (sections 13, 14, 15, 16, 17).

These tests assert the properties that make an audit *honest* rather than
merely present: that an unavailable value stays unavailable, that a fault is
visible rather than smoothed over, that every claim carries a source, and that
readiness refuses to collapse into a single verdict.
"""

from __future__ import annotations

import unittest

from babylab.isolation import (
    EnforcementLayer,
    HostMeasurement,
    IsolationReport,
    IsolationStatus,
    assess_isolation,
)
from birth.readiness import (
    PREREQUISITE_NAMES,
    PrereqState,
    ReadinessReport,
    Prerequisite,
    assess_readiness,
)
from observatory.audit import (
    AUDIT_SECTIONS,
    LABEL_MEANINGS,
    Claim,
    Fault,
    Label,
    detect_authority_faults,
    isolation_claims,
)
from tests.support import LabTestCase


def fake_isolation(status=IsolationStatus.NOT_IMPLEMENTED) -> IsolationReport:
    return IsolationReport(
        status=status,
        layer=EnforcementLayer.APPLICATION_POLICY,
        measurements=(
            HostMeasurement("elevated", {"elevated": False}, "whoami /groups"),
        ),
        prerequisites=("An elevated session",),
        reasons=("no OS boundary on this host",),
    )


class TestEpistemicLabels(unittest.TestCase):
    def test_all_nine_labels_exist(self):
        self.assertEqual(
            {label.value for label in Label},
            {
                "OBSERVED", "DERIVED", "RECORDED", "INHERITED", "UNVERIFIED",
                "UNAVAILABLE", "DENIED", "FAILED", "UNKNOWN",
            },
        )

    def test_every_label_has_a_documented_meaning(self):
        for label in Label:
            with self.subTest(label=label):
                self.assertTrue(LABEL_MEANINGS[label].strip())

    def test_unverified_is_never_a_synonym_for_pass(self):
        self.assertIn("a synonym for PASS", LABEL_MEANINGS[Label.UNVERIFIED])

    def test_unavailable_is_distinct_from_zero(self):
        meaning = LABEL_MEANINGS[Label.UNAVAILABLE]
        self.assertIn("not zero", meaning)


class TestAuditSections(unittest.TestCase):
    def test_twelve_sections_are_declared_in_order(self):
        self.assertEqual(
            AUDIT_SECTIONS,
            (
                "SUBJECT", "FOUNDATION", "RUNTIME", "BIRTH", "PROVENANCE",
                "CONTROL", "ISOLATION", "COGNITIVE COMPONENTS", "ENVIRONMENT",
                "EXPERIMENTAL STATUS", "UNVERIFIED CLAIMS", "FAULTS",
            ),
        )

    def test_every_claim_carries_a_source(self):
        from observatory.audit import AuditReport

        report = AuditReport(
            sections={"SUBJECT": [Claim("a subject exists", Label.RECORDED, "BIRTH.json")]}
        )
        for claim in report.all_claims():
            self.assertTrue(claim.source, "a claim without a source is not auditable")

    def test_render_includes_every_section(self):
        from observatory.audit import AuditReport

        text = AuditReport().render()
        for name in AUDIT_SECTIONS:
            self.assertIn(name, text)

    def test_render_includes_label_definitions(self):
        from observatory.audit import AuditReport

        text = AuditReport().render()
        self.assertIn("LABEL DEFINITIONS", text)
        for label in Label:
            self.assertIn(label.value, text)

    def test_empty_section_says_so_rather_than_inventing(self):
        from observatory.audit import AuditReport

        self.assertIn("(no claims recorded)", AuditReport().render())


class TestFaultVisibility(unittest.TestCase):
    """Section 15: prefer a visible inconsistency to a convenient reading."""

    def test_record_without_key_is_a_warning(self):
        faults = detect_authority_faults(record_exists=True, key_attached=False)
        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0].severity, "WARNING")
        self.assertIn("NOT ATTACHED", faults[0].message)

    def test_key_without_record_is_an_error(self):
        faults = detect_authority_faults(record_exists=False, key_attached=True)
        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0].severity, "ERROR")
        self.assertIn("inconsistent", faults[0].message)

    def test_consistent_state_produces_no_fault(self):
        self.assertEqual(detect_authority_faults(record_exists=True, key_attached=True), [])
        self.assertEqual(detect_authority_faults(record_exists=False, key_attached=False), [])

    def test_faults_are_rendered(self):
        from observatory.audit import AuditReport

        text = AuditReport(faults=[Fault("ERROR", "Authority state is inconsistent.")]).render()
        self.assertIn("ERROR: Authority state is inconsistent.", text)

    def test_no_faults_is_stated_explicitly(self):
        from observatory.audit import AuditReport

        self.assertIn("no inconsistencies detected", AuditReport().render())


class TestIsolationClaims(unittest.TestCase):
    def test_not_implemented_is_reported_as_observed_not_verified(self):
        claims, _ = isolation_claims(fake_isolation())
        statuses = [c.text for c in claims]
        self.assertIn("OS isolation: NOT_IMPLEMENTED", statuses)

    def test_absent_write_attempt_yields_an_unverified_claim(self):
        _, unverified = isolation_claims(fake_isolation())
        self.assertTrue(
            any(c.label is Label.UNVERIFIED for c in unverified),
            "with no attempted-and-denied write there must be an UNVERIFIED claim",
        )

    def test_proven_denial_is_reported_as_observed(self):
        report = IsolationReport(
            status=IsolationStatus.VERIFIED,
            layer=EnforcementLayer.OS_FILE_PERMISSIONS,
            write_attempt_performed=True,
            write_attempt_denied=True,
            reasons=("a write was attempted and denied",),
        )
        claims, unverified = isolation_claims(report)
        self.assertTrue(
            any("attempted and denied" in c.text for c in claims if c.label is Label.OBSERVED)
        )
        self.assertFalse(any(c.label is Label.UNVERIFIED for c in unverified))


class TestBirthReadiness(unittest.TestCase):
    def test_every_required_prerequisite_is_reported(self):
        report = assess_readiness(isolation=fake_isolation())
        names = {p.name for p in report.prerequisites}
        for required in PREREQUISITE_NAMES:
            self.assertIn(required, names)

    def test_never_ready_while_os_isolation_is_not_implemented(self):
        report = assess_readiness(isolation=fake_isolation())
        self.assertFalse(report.ready)
        self.assertEqual(
            report.state_of("OS ISOLATION READY"), PrereqState.NOT_IMPLEMENTED
        )

    def test_render_says_blocked_with_a_reason(self):
        report = assess_readiness(isolation=fake_isolation())
        text = report.render()
        self.assertIn("BIRTH READINESS: BLOCKED", text)
        self.assertIn("Reason:", text)
        self.assertNotIn("BIRTH READINESS: READY", text)

    def test_unverified_is_never_reported_as_pass(self):
        report = assess_readiness(isolation=fake_isolation())
        self.assertEqual(
            report.state_of("MODEL RUNTIME VERIFIED"), PrereqState.UNVERIFIED
        )
        self.assertNotIn("PASS", report.render())

    def test_runtime_not_executed_blocks_readiness(self):
        report = assess_readiness(
            isolation=fake_isolation(), model_runtime_executed=False
        )
        self.assertFalse(report.ready)

    def test_mock_runtime_does_not_satisfy_runtime_verified(self):
        """A successful mock is not a real runtime; only execution verifies it."""
        report = assess_readiness(isolation=fake_isolation(), model_runtime_executed=False)
        detail = next(
            p.detail for p in report.prerequisites if p.name == "MODEL RUNTIME VERIFIED"
        )
        self.assertIn("never been executed", detail)

    def test_identity_not_separated_blocks_readiness(self):
        report = assess_readiness(
            isolation=fake_isolation(), baby_ai_identity_separated=False
        )
        self.assertEqual(
            report.state_of("BABY_AI IDENTITY READY"), PrereqState.NOT_IMPLEMENTED
        )

    def test_every_prerequisite_reports_its_source(self):
        report = assess_readiness(isolation=fake_isolation())
        for p in report.prerequisites:
            with self.subTest(prereq=p.name):
                self.assertTrue(p.source, f"{p.name} must say where its state came from")

    def test_ready_requires_every_prerequisite(self):
        report = ReadinessReport(
            prerequisites=[Prerequisite("X", PrereqState.VERIFIED, "ok", "src")]
        )
        self.assertTrue(report.ready)
        report.prerequisites.append(
            Prerequisite("Y", PrereqState.UNVERIFIED, "no", "src")
        )
        self.assertFalse(report.ready)

    def test_empty_readiness_is_not_ready(self):
        self.assertFalse(ReadinessReport().ready)


class TestReadinessAgainstRealHost(LabTestCase):
    def test_this_host_is_blocked_for_real_birth(self):
        isolation = assess_isolation(
            [
                self.paths.human_control,
                self.paths.provenance_ledger,
                self.paths.event_store,
            ],
            write_attempt_performed=False,
            write_attempt_denied=False,
        )
        report = assess_readiness(isolation=isolation)
        self.assertFalse(report.ready)
        self.assertIn("BIRTH READINESS: BLOCKED", report.render())


if __name__ == "__main__":
    unittest.main()
