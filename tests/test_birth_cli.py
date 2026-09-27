"""Tests for the explicit real-model check and the birth CLI.

Neither of these loads weights in this suite. What is tested here is the
behaviour that matters when a real model is *absent*, because that is the state
every fresh installation is in, and because a report that invents a number when
it cannot measure one is the failure mode this project exists to avoid.
"""

from __future__ import annotations

import io
import json
import re
import unittest
from contextlib import redirect_stdout

from tests.support import LabTestCase
from birth import cli
from birth.real_model_test import UNAVAILABLE, run_check


class TestRealModelCheckWithoutAModel(LabTestCase):
    def test_unconfigured_laboratory_reports_not_configured(self) -> None:
        report = run_check(paths=self.paths)
        self.assertEqual(report.status, "NOT_CONFIGURED")
        self.assertFalse(report.model_installed)

    def test_no_model_metric_is_reported_as_zero(self) -> None:
        """Every model-derived measurement is the literal, never a number.

        A zero here would be averaged into a later summary as though the runtime
        had reported no tokens rather than never having said anything. The GPU
        fields are exempt: they are observed from the host by
        ``nvidia-smi`` whether or not a model exists, so they may legitimately
        hold a real number.
        """
        report = run_check(paths=self.paths).to_dict()
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "verification_duration_ms",
            "generation_duration_ms",
        ):
            self.assertEqual(report[field], UNAVAILABLE, field)

    def test_gpu_fields_are_observed_or_unavailable_and_never_zero(self) -> None:
        report = run_check(paths=self.paths).to_dict()
        for field in ("gpu_memory_bytes", "gpu_memory_total_bytes"):
            value = report[field]
            self.assertTrue(
                value == UNAVAILABLE or (isinstance(value, int) and value > 0),
                f"{field} was {value!r}",
            )

    def test_no_model_output_is_invented(self) -> None:
        report = run_check(paths=self.paths)
        self.assertEqual(report.output_text, "")
        self.assertEqual(report.invocation_record, {})

    def test_a_fake_configuration_is_refused(self) -> None:
        from birth.fake import fake_config
        from birth.config import save_config

        save_config(fake_config(), self.paths)
        report = run_check(paths=self.paths)
        self.assertEqual(report.status, "ERROR")
        self.assertIn("fake runtime", report.detail)

    def test_the_report_renders_and_every_field_is_present(self) -> None:
        text = run_check(paths=self.paths).render()
        for label in ("model sha256", "total tokens", "unloaded", "backend"):
            self.assertIn(label, text)
        self.assertIn(UNAVAILABLE, text)


class TestRealModelCheckExitStatus(unittest.TestCase):
    """The exit code follows the status, not merely whether weights existed."""

    def test_a_report_that_is_not_ready_exits_nonzero(self) -> None:
        from birth.real_model_test import RealModelReport, main

        original = run_check

        def fake_run_check(*args, **kwargs):
            return RealModelReport(
                status="ERROR",
                detail="generation failed",
                model_installed=True,
            )

        import birth.real_model_test as module

        module.run_check = fake_run_check
        try:
            with redirect_stdout(io.StringIO()):
                code = main([])
        finally:
            module.run_check = original
        self.assertEqual(
            code, 1, "an installed model whose generation failed has verified nothing"
        )


class TestBirthCli(LabTestCase):
    def _run(self, *args: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(list(args))
        return code, buffer.getvalue()

    def test_status_on_an_empty_laboratory(self) -> None:
        code, output = self._run("status")
        self.assertEqual(code, 0)
        self.assertIn("NOT_CONFIGURED", output)
        self.assertIn("no birth record", output)
        self.assertIn("subject        none", output)

    def test_model_on_an_empty_laboratory_exits_nonzero(self) -> None:
        code, output = self._run("model")
        self.assertEqual(code, 1)
        self.assertIn("NOT_CONFIGURED", output)

    def test_capabilities_lists_contracts_without_ranking_them(self) -> None:
        code, output = self._run("capabilities")
        self.assertEqual(code, 0)
        self.assertIn("unordered", output.lower())

    def test_no_capability_is_claimed_implemented(self) -> None:
        """``NOT_YET_IMPLEMENTED`` contains the word but is not a claim."""
        _, output = self._run("capabilities")
        self.assertIsNone(
            re.search(r"(?<![\w_])IMPLEMENTED(?![\w_])", output),
            "no contract may report IMPLEMENTED",
        )

    def test_ceremony_in_an_unconfigured_laboratory_creates_nothing(self) -> None:
        code, output = self._run("ceremony")
        self.assertEqual(code, 1)
        self.assertIn("NOT_CONFIGURED", output)
        self.assertFalse(self.paths.birth_record.exists())
        self.assertEqual(self.read_event_lines(), [])

    def test_verify_with_no_record_reports_the_absence(self) -> None:
        code, output = self._run("verify")
        self.assertEqual(code, 1)
        self.assertIn("no birth record", output.lower())

    def test_json_output_is_parseable(self) -> None:
        code, output = self._run("status", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertIn("status", payload)
        self.assertEqual(payload["status"], "NOT_CONFIGURED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
