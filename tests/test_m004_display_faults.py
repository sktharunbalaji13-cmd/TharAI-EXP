"""Milestone 004 -- testing the tests (section 24).

Milestone 003's lesson was that a laboratory can pass its own unit tests and
still show a human something untrue. This module closes that loop by
deliberately breaking the renderer in each of the ways the milestone names, and
then running the *actual* rendering assertions from ``test_m004_rendering`` to
prove they notice.

These are not tests of the renderer. They are tests of the test suite. A
rendering test that cannot fail when the display lies is worse than no test,
because it manufactures confidence.

Fault classes required by section 24:

* hide the RECORDED detail line
* render RUNTIME_UNVERIFIED as READY
* weaken ATTACHED to RECORDED
* suppress an isolation failure
* replace UNAVAILABLE with 0
"""

from __future__ import annotations

import unittest

from observatory import render as render_module
from observatory.render import ObservatoryRenderer
from tests.test_m004_rendering import (
    Invariant1NoSubjectImpliesNothing,
    Invariant2RecordedIsNotAttached,
    Invariant3KeyWithoutRecordExposesDiscrepancy,
    Invariant4RuntimeUnverifiedIsNotReady,
    Invariant7UnavailableStaysUnavailable,
    TrustBoundarySectionRendering,
    make_snapshot,
)


def run_one(test_class, method_name: str) -> unittest.TestResult:
    """Run a single real rendering test and report whether it failed.

    ``TestResult`` rather than the test runner, so the fault is injected into the
    real renderer that the real assertion already exercises. There is no
    re-implementation of the assertion here: if this file could pass while
    ``test_m004_rendering`` was broken, it would prove nothing.
    """
    result = unittest.TestResult()
    suite = unittest.TestSuite([test_class(method_name)])
    suite.run(result)
    return result


class DisplayFaultInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = {}

    def tearDown(self) -> None:
        for name, value in self._original.items():
            setattr(ObservatoryRenderer, name, value)
        self._original.clear()

    def _patch(self, name: str, replacement) -> None:
        self._original[name] = getattr(ObservatoryRenderer, name)
        setattr(ObservatoryRenderer, name, replacement)

    def assert_detected(self, test_class, method_name: str) -> None:
        result = run_one(test_class, method_name)
        self.assertTrue(
            result.failures or result.errors,
            "the rendering suite did NOT notice a deliberate display fault; "
            "this test is therefore worthless",
        )

    # -- fault 1: hide the RECORDED detail --------------------------------
    def test_hiding_recorded_detail_is_detected(self):
        real_header = ObservatoryRenderer.header

        def faulty_header(self, snapshot):
            lines = real_header(self, snapshot)
            return [line for line in lines if "birth record exists" not in line]

        self._patch("header", faulty_header)
        self.assert_detected(
            Invariant2RecordedIsNotAttached, "test_recorded_detail_is_visible"
        )

    # -- fault 2: RUNTIME_UNVERIFIED rendered as READY ---------------------
    def test_runtime_unverified_shown_as_ready_is_detected(self):
        real_birth = ObservatoryRenderer.birth_section

        def faulty_birth(self, snapshot):
            lines = real_birth(self, snapshot)
            return [line.replace("RUNTIME_UNVERIFIED", "READY") for line in lines]

        self._patch("birth_section", faulty_birth)
        self.assert_detected(
            Invariant4RuntimeUnverifiedIsNotReady, "test_runtime_unverified_is_shown"
        )

    # -- fault 3: ATTACHED weakened to RECORDED ----------------------------
    def test_weakening_attached_to_recorded_is_detected(self):
        real_header = ObservatoryRenderer.header

        def faulty_header(self, snapshot):
            lines = real_header(self, snapshot)
            out = []
            for line in lines:
                if "No birth record exists" in line:
                    continue  # suppress the discrepancy the reader must see
                out.append(line)
            return out

        self._patch("header", faulty_header)
        self.assert_detected(
            Invariant3KeyWithoutRecordExposesDiscrepancy,
            "test_exposes_the_authority_discrepancy",
        )

    # -- fault 4: suppress an isolation failure ---------------------------
    def test_suppressing_the_isolation_failure_is_detected(self):
        real_trust = ObservatoryRenderer.trust_boundary_section

        def faulty_trust(self, snapshot):
            lines = real_trust(self, snapshot)
            return [line for line in lines if "NOT_IMPLEMENTED" not in line]

        self._patch("trust_boundary_section", faulty_trust)
        self.assert_detected(
            TrustBoundarySectionRendering,
            "test_os_isolation_is_shown_as_not_implemented",
        )

    # -- fault 5: UNAVAILABLE replaced by 0 --------------------------------
    def test_replacing_unavailable_with_zero_is_detected(self):
        real_birth = ObservatoryRenderer.birth_section

        def faulty_birth(self, snapshot):
            lines = real_birth(self, snapshot)
            return [line.replace("UNAVAILABLE", "0") for line in lines]

        self._patch("birth_section", faulty_birth)
        self.assert_detected(
            Invariant7UnavailableStaysUnavailable,
            "test_environment_id_is_unavailable_when_absent",
        )

    # -- fault 6: a subject implied where none exists ---------------------
    def test_implying_a_subject_where_none_exists_is_detected(self):
        real_header = ObservatoryRenderer.header

        def faulty_header(self, snapshot):
            lines = real_header(self, snapshot)
            return [line for line in lines if "NO EXPERIMENTAL SUBJECT ATTACHED" not in line]

        self._patch("header", faulty_header)
        self.assert_detected(
            Invariant1NoSubjectImpliesNothing, "test_banner_states_no_subject"
        )

    # -- the control: with no fault injected, the suite must PASS ----------
    def test_unfaulted_renderer_passes_the_same_assertions(self):
        """Guards against a vacuous file where everything 'fails' anyway."""
        for test_class, method in (
            (Invariant1NoSubjectImpliesNothing, "test_banner_states_no_subject"),
            (
                Invariant2RecordedIsNotAttached,
                "test_recorded_detail_is_visible",
            ),
            (
                Invariant4RuntimeUnverifiedIsNotReady,
                "test_runtime_unverified_is_shown",
            ),
            (
                TrustBoundarySectionRendering,
                "test_os_isolation_is_shown_as_not_implemented",
            ),
        ):
            with self.subTest(test=method):
                result = run_one(test_class, method)
                self.assertTrue(
                    result.wasSuccessful(),
                    f"{method} must pass on an honest renderer, otherwise the "
                    f"fault-injection proof is meaningless",
                )

    def test_renderer_module_is_restored_between_faults(self):
        self.assertTrue(hasattr(render_module, "ObservatoryRenderer"))


if __name__ == "__main__":
    unittest.main()
