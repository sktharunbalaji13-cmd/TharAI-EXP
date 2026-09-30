"""Tests for the M013 Observatory panel.

The property worth defending here is structural, not cosmetic: the Observatory
reads the birth gate and cannot cause a birth. If a display panel could reach a
ceremony, then opening the display would be enough to create a subject, and every
guarantee about controlled births would depend on nobody opening a terminal.

So the tests assert two things. That the gate's signature offers no way to ask for
a ceremony. And that reading the panel performs no environment interaction.
"""

from __future__ import annotations

import inspect

import pytest

from birth.ceremony13 import BirthMode, run_ceremony
from birth.fixture13 import build_ready_ledger
from birth.gate13 import PREREQUISITES, evaluate_birth_gate
from observatory.render import ObservatoryRenderer, RenderOptions
from observatory.snapshot import ObservatorySnapshot
from environment.deterministic import create_deterministic_environment


def _snapshot(birth_ceremony: dict | None = None) -> ObservatorySnapshot:
    """A minimal snapshot, matching how the other milestone tests build one."""
    from observatory.graph import StateGraph
    from observatory.model import CognitiveState

    return ObservatorySnapshot(
        subject_status="NO_SUBJECT",
        subject_banner="NO EXPERIMENTAL SUBJECT ATTACHED",
        subject_detail=None,
        state=CognitiveState.empty(),
        graph=StateGraph(),
        birth_ceremony=birth_ceremony or {},
    )


def _render(birth_ceremony: dict, *, detail: bool = True) -> str:
    return ObservatoryRenderer(RenderOptions(color=False, detail=detail)).render(
        _snapshot(birth_ceremony),
    )


def _blocked_panel() -> dict:
    return evaluate_birth_gate({}, environment=None).to_dict()


class TestPanelSeesWithoutCausing:
    def test_the_gate_offers_no_way_to_ask_for_a_ceremony(self):
        """The separation is structural, not a convention someone could ignore.

        If this fails, the guarantee that the Observatory cannot cause a birth is
        gone, and every other claim about controlled birth depends on it.

        Asserted as an allow-list rather than a deny-list: a deny-list only
        catches the names someone thought of. Naming what the gate legitimately
        accepts means a future parameter has to be classified before it lands.
        """
        parameters = set(inspect.signature(evaluate_birth_gate).parameters)
        assert parameters == {
            "m012", "environment", "key_policy", "control", "provenance",
        }

    def test_evaluating_the_gate_performs_no_interaction(self):
        environment = create_deterministic_environment()
        before = environment.snapshot().state_hash
        evaluate_birth_gate(build_ready_ledger())
        assert environment.snapshot().state_hash == before

    def test_the_gate_never_mints_a_subject(self):
        verdict = evaluate_birth_gate(build_ready_ledger(), environment=None)
        payload = verdict.to_dict()
        assert "subject_id" not in payload
        assert "t_birth" not in payload

    def test_reading_the_panel_leaves_the_environment_unchanged(self):
        from babylab.paths import default_paths
        from observatory.terminal import ObservatorySession

        environment = create_deterministic_environment()
        before = environment.snapshot().state_hash
        ObservatorySession(default_paths())  # constructs every panel
        assert environment.snapshot().state_hash == before

    def test_the_observatory_module_never_names_the_verifier(self):
        """M011's import-graph discipline, extended to the birth gate.

        Regression: the first version of this panel called
        ``foundation.m012.verify`` to obtain a ledger, which made opening the
        display able to run verification. M011's test caught it; the fix was a
        read-only surface, not a suppression.
        """
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "observatory" / "terminal.py"
        ).read_text(encoding="utf-8")
        called: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
        for forbidden in ("verify", "run_ceremony", "run_probe", "run_inference"):
            assert forbidden not in called, (
                f"the Observatory references {forbidden!r}; a view that can perform "
                "the thing it observes is not a view"
            )

    def test_the_read_surface_cannot_reach_the_ceremony(self):
        """`m013_status` must not import anything that can execute."""
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "birth" / "m013_status.py"
        ).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        for forbidden in ("birth.ceremony13", "birth.replay13", "foundation.m012"):
            assert forbidden not in imported, (
                f"the M013 read surface imports {forbidden!r}, which can execute"
            )

    def test_a_real_declaration_lifts_only_the_declaration_itself(self):
        """A declaration lifts one prerequisite, and no more.

        Naming a model is not identifying one. The declaration supplies a path and
        a claimed digest; establishing the artifact's identity requires hashing the
        bytes, and establishing the runtime's identity requires running it and
        reading its own version. So ``model_identity`` and ``runtime_identity``
        stay BLOCKED even with a perfectly valid declaration, which is the correct
        reading rather than a shortfall in the read surface.

        The test exists because a vacuously-BLOCKED panel would also be "correct"
        -- it would pass a weaker assertion while never proving it had read the
        declaration at all.
        """
        import json
        from pathlib import Path
        from tempfile import mkdtemp

        from birth.m013_status import ceremony_only
        from foundation.deployment import DEPLOYMENT_SCHEMA

        root = Path(mkdtemp())
        target = root / "human_control" / "experiment_config"
        target.mkdir(parents=True)
        (target / "model_deployment.json").write_text(json.dumps({
            "schema": DEPLOYMENT_SCHEMA,
            "model": {"path": "C:/models/x.gguf", "sha256": "a" * 64,
                      "family": "qwen", "quantization": "Q4_K_M",
                      "external_digest": None},
            "runtime": {"path": "C:/bin/llama-server.exe",
                        "expected_version": "build 1",
                        "implementation": "llama.cpp"},
            "selection": {"declared_by": "the operator", "rationale": "because",
                          "attributed": True},
        }), encoding="utf-8")

        payload = ceremony_only(root)
        ready = {p["name"] for p in payload["prerequisites"]
                 if p["state"] == "READY"}
        assert ready == {"human_declaration"}
        # Everything requiring a hash, a run, or a probe stays BLOCKED.
        for blocked in ("model_identity", "model_digest", "runtime_identity",
                        "real_runtime", "real_inference"):
            assert blocked not in ready, blocked
        assert payload["state"] == "BLOCKED"
        assert payload["may_proceed"] is False

    def test_the_read_surface_cannot_report_ready(self):
        """A file read cannot establish the evidence READY needs.

        Stated as a test because the tempting "fix" -- letting the panel verify so
        it can show a green gate -- would quietly restore the ability to execute
        from a display.
        """
        from birth.m013_status import ceremony_only

        payload = ceremony_only()
        assert payload["state"] in {"BLOCKED", "FAILED"}
        assert payload["may_proceed"] is False
        assert payload["source"] == "declaration_only"

    def test_the_read_surface_performs_no_birth(self):
        from birth.m013_status import ceremony_only

        payload = ceremony_only()
        assert payload["real_birth"] == "NOT_PERFORMED"
        assert payload["subject"] == "NONE"
        assert payload["t_birth"] == "UNAVAILABLE"
        assert payload["first_experience"] == "NOT_PERFORMED"

    def test_a_ready_gate_still_does_not_create_a_subject(self):
        """Even a READY verdict is only a verdict; the display stops there."""
        from birth.fixture13 import (
            fixture_control_fields,
            fixture_environment_fields,
            fixture_key_policy_fields,
            fixture_provenance_fields,
        )

        verdict = evaluate_birth_gate(
            build_ready_ledger(),
            environment=fixture_environment_fields(),
            provenance=fixture_provenance_fields(),
            control=fixture_control_fields(),
            key_policy=fixture_key_policy_fields(),
        )
        assert verdict.may_proceed is True
        payload = verdict.to_dict()
        # READY means "may proceed", not "did proceed".
        assert "subject_id" not in payload
        assert "first_experience" not in payload


class TestPanelRendering:
    def test_blocked_gate_is_rendered(self):
        text = _render(_blocked_panel())
        assert "BIRTH GATE" in text
        assert "BLOCKED" in text

    def test_panel_states_that_no_birth_occurred(self):
        """The line a reader needs most, in the terms they need it in."""
        text = _render(_blocked_panel())
        assert "NOT_PERFORMED" in text
        assert "NONE" in text
        assert "UNAVAILABLE" in text

    def test_prerequisites_are_counted(self):
        panel = _blocked_panel()
        text = _render(panel)
        assert "prerequisites" in text
        assert "BLOCKED" in text

    @pytest.mark.parametrize("state", ["READY", "BLOCKED", "FAILED"])
    def test_the_three_states_are_each_rendered(self, state):
        panel = {
            "state": state,
            "prerequisites": [{"name": "human_declaration", "state": state}],
        }
        text = _render(panel)
        assert state in text

    def test_states_are_not_collapsed_into_one(self):
        """BLOCKED and FAILED mean different things and must both be visible."""
        panel = evaluate_birth_gate(
            {"deployment": {"state": "NOT_CONFIGURED"},
             "criteria": [{"name": "model_sha256_verified", "state": "FAILED",
                           "detail": "mismatch", "evidence": {}}]},
            environment=None,
        ).to_dict()
        tally = {}
        for prerequisite in panel["prerequisites"]:
            tally[prerequisite["state"]] = tally.get(prerequisite["state"], 0) + 1
        assert "BLOCKED" in tally
        assert "FAILED" in tally

    def test_absent_panel_renders_nothing(self):
        text = ObservatoryRenderer(RenderOptions(color=False)).render(_snapshot())
        assert "BIRTH GATE" not in text

    def test_note_is_shown_in_detail_mode(self):
        panel = dict(_blocked_panel())
        panel["note"] = "this panel performs no ceremony and runs no verification."
        assert "performs no ceremony" in _render(panel)

    def test_note_is_hidden_outside_detail_mode(self):
        """Detail text is opt-in, so a compact render stays readable."""
        panel = dict(_blocked_panel())
        panel["note"] = "this panel performs no ceremony and runs no verification."
        assert "performs no ceremony" not in _render(panel, detail=False)

    def test_snapshot_serialises_the_panel(self):
        payload = _snapshot(_blocked_panel()).to_dict()
        assert "birth_ceremony" in payload
        assert payload["birth_ceremony"]["state"] == "BLOCKED"

    def test_panel_survives_a_broken_subsystem(self):
        """A corrupt or missing birth subsystem must not take down the display."""
        from babylab.paths import default_paths
        from observatory.terminal import ObservatorySession

        session = ObservatorySession(default_paths())
        session._birth_ceremony = {
            "state": "UNAVAILABLE",
            "note": "the birth-ceremony panel could not be read",
        }
        text = session.render(RenderOptions(color=False))
        assert "UNAVAILABLE" in text


class TestSnapshotPlumbing:
    def test_compose_snapshot_accepts_the_panel(self):
        from observatory.snapshot import compose_snapshot

        signature = inspect.signature(compose_snapshot)
        assert "birth_ceremony" in signature.parameters

    def test_default_is_empty_not_guessed(self):
        assert _snapshot().birth_ceremony == {}

    def test_all_sixteen_prerequisites_are_represented(self):
        panel = evaluate_birth_gate(build_ready_ledger(), environment=None).to_dict()
        assert len(panel["prerequisites"]) == len(PREREQUISITES) == 16
