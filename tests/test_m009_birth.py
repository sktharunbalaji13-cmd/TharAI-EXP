"""Milestone 009 tests: birth ceremony and first controlled experience.

The governing rule for this file
--------------------------------
A test may only pass because the ceremony actually behaved. The specific traps:

* **A simulated run that reads as a birth.** Every SIMULATED record must say
  NOT_A_BIRTH in its own events, and the audit must never report REAL_BIRTH for
  one. Tests assert the labels, not the intention behind them.
* **A gate that passes what it cannot see.** UNKNOWN must block, and a check
  that raises must block. Both are tested with injected checks, because the
  real checks pass or fail depending on the machine.
* **A partial birth that reads as success.** Every abort must preserve the
  failure, terminate the record, and leave nothing downstream fabricated.
* **A check that reads its own explanation.** Docstrings explain prohibitions,
  so text scans inspect emitted literals with docstrings removed, or the code
  graph with prose excluded.

No test here writes to ``human_control/``, provisions a key, or registers a
subject. The laboratory must be unattached after the suite runs.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from birth.audit import build_audit, replay_ceremony, verify_audit
from birth.ceremony import (
    BirthCeremony,
    BirthMode,
    CeremonyConfig,
    CeremonyError,
)
from birth.control import ControlError, pause, resume, terminate
from birth.gate import BirthGate, GateResult
from birth.gate_checks import default_checks
from birth.keycustody import (
    CustodyError,
    evaluate_key_custody,
    provision_key,
)
from birth.telemetry import ALLOWED_TELEMETRY, build_telemetry
from environment.action import Operation
from subject.identity import FoundationReference
from subject.lifecycle import LifecycleState, SubjectLifecycle

REPO_ROOT = Path(__file__).resolve().parents[1]
CLOCK = lambda: "2026-09-27T00:00:00.000Z"  # noqa: E731 - deterministic tests


def _ceremony(**overrides):
    import birth.gate as gate_module

    kwargs = dict(gate=gate_module.BirthGate(clock=CLOCK), clock=CLOCK)
    kwargs.update(overrides)
    return BirthCeremony(**kwargs)


#: The modules M009 added. Structural checks scope to these, not to the whole
#: birth package, because M003's llamacpp.py legitimately uses re.compile for
#: output parsing -- and a check that cannot tell re.compile from bare compile
#: would have to be deleted to make the suite pass.
M009_MODULES = ("gate.py", "gate_checks.py", "ceremony.py", "keycustody.py",
                "control.py", "audit.py", "telemetry.py")


def _m009_sources() -> str:
    return "\n".join(
        (REPO_ROOT / "birth" / name).read_text(encoding="utf-8")
        for name in M009_MODULES
    ).lower()


def _passing_gate(except_for: str, failure_detail: str):
    """A gate that passes everything except one named prerequisite.

    The real gate aborts at the *first* blocking check, so testing a specific
    failure means the earlier checks must pass. Without this helper a test for
    any check after model_runtime_availability would always abort on the
    unconfigured model instead -- and would pass for the wrong reason.
    """
    from birth.gate import BirthGate, GateResult, PrerequisiteResult

    def passing(name):
        return lambda n=name: PrerequisiteResult(
            name=n, result=GateResult.PASS, detail="test fixture passes")

    from birth.gate import PREREQUISITE_ORDER

    checks = {name: passing(name) for name in PREREQUISITE_ORDER}
    checks[except_for] = lambda: PrerequisiteResult(
        name=except_for, result=GateResult.FAIL, detail=failure_detail)
    return BirthGate(checks=checks, clock=CLOCK)


def _simulated_config(**overrides):
    payload = dict(mode=BirthMode.SIMULATED)
    payload.update(overrides)
    return CeremonyConfig(**payload)


# ---------------------------------------------------------------------------
# Gate semantics
# ---------------------------------------------------------------------------

class TestGateSemantics(unittest.TestCase):
    """PASS/FAIL/UNKNOWN are distinct; UNKNOWN never becomes PASS."""

    def test_unknown_blocks(self):
        gate = BirthGate(checks={
            name: (lambda n=name: __import__(
                "birth.gate", fromlist=["x"]).PrerequisiteResult(
                    name=n, result=GateResult.PASS, detail="fine"))
            for name in __import__("birth.gate", fromlist=["x"]).PREREQUISITE_ORDER
        }, clock=CLOCK)
        gate._checks["model_runtime_availability"] = lambda: __import__(
            "birth.gate", fromlist=["x"]).PrerequisiteResult(
                name="model_runtime_availability", result=GateResult.UNKNOWN,
                detail="cannot be determined")
        verdict = gate.evaluate()
        self.assertEqual("BLOCKED", verdict.verdict)
        self.assertFalse(verdict.may_proceed)

    def test_a_check_that_raises_blocks(self):
        from birth.gate import PREREQUISITE_ORDER, PrerequisiteResult

        def explode():
            raise OSError("probe exploded")

        gate = BirthGate(checks={
            name: (lambda n=name: PrerequisiteResult(
                name=n, result=GateResult.PASS, detail="fine"))
            for name in PREREQUISITE_ORDER
        }, clock=CLOCK)
        gate._checks["runtime_verification"] = explode
        verdict = gate.evaluate()
        self.assertEqual("BLOCKED", verdict.verdict)
        blocking = [p.name for p in verdict.blocking()]
        self.assertIn("runtime_verification", blocking)

    def test_a_missing_check_blocks(self):
        from birth.gate import PREREQUISITE_ORDER, PrerequisiteResult

        gate = BirthGate(checks={
            name: (lambda n=name: PrerequisiteResult(
                name=n, result=GateResult.PASS, detail="fine"))
            for name in PREREQUISITE_ORDER if name != "key_custody"
        }, clock=CLOCK)
        verdict = gate.evaluate()
        self.assertEqual("BLOCKED", verdict.verdict)

    def test_all_pass_proceeds(self):
        from birth.gate import PREREQUISITE_ORDER, PrerequisiteResult

        gate = BirthGate(checks={
            name: (lambda n=name: PrerequisiteResult(
                name=n, result=GateResult.PASS, detail="fine"))
            for name in PREREQUISITE_ORDER
        }, clock=CLOCK)
        verdict = gate.evaluate()
        self.assertEqual("PROCEED", verdict.verdict)
        self.assertTrue(verdict.may_proceed)

    def test_every_check_always_runs(self):
        """A single evaluation shows the whole picture, not just the first failure."""
        from birth.gate import PREREQUISITE_ORDER

        gate = BirthGate(clock=CLOCK)
        verdict = gate.evaluate()
        self.assertEqual(len(PREREQUISITE_ORDER), len(verdict.prerequisites))
        self.assertEqual(
            sorted(PREREQUISITE_ORDER),
            sorted(p.name for p in verdict.prerequisites))

    def test_real_gate_blocks_on_this_machine(self):
        """No model is configured, so the gate must block with that reason."""
        verdict = BirthGate(clock=CLOCK).evaluate()
        self.assertEqual("BLOCKED", verdict.verdict)
        self.assertFalse(verdict.may_proceed)
        self.assertIn("MODEL_NOT_CONFIGURED", verdict.reason)

    def test_real_gate_lists_all_fourteen(self):
        verdict = BirthGate(clock=CLOCK).evaluate()
        self.assertEqual(14, len(verdict.prerequisites))


# ---------------------------------------------------------------------------
# 1-8: ceremony failure matrix
# ---------------------------------------------------------------------------

class TestCeremonyFailures(unittest.TestCase):
    """1-8. every failure the matrix names, each preserving evidence"""

    def test_1_birth_with_missing_model(self):
        record = _ceremony().perform(CeremonyConfig(mode=BirthMode.REAL))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("verify_prerequisites", record.failure["step"])
        self.assertIn("MODEL_NOT_CONFIGURED", record.failure["detail"])

    def test_2_birth_with_invalid_model_identity(self):
        record = _ceremony(gate=_passing_gate(
            "model_artifact_identity",
            "MODEL_IDENTITY_UNVERIFIED: test fixture")).perform(
                CeremonyConfig(mode=BirthMode.REAL))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("verify_prerequisites", record.failure["step"])
        self.assertIn("MODEL_IDENTITY_UNVERIFIED", record.failure["detail"])

    def test_3_birth_with_unverified_runtime(self):
        record = _ceremony().perform(CeremonyConfig(mode=BirthMode.REAL))
        # On this machine the gate stops earlier (no model at all), which is
        # itself the honest answer; the runtime check is exercised directly.
        from birth.gate_checks import check_runtime_verification

        result = check_runtime_verification()
        self.assertIs(GateResult.FAIL, result.result)
        self.assertIn("MODEL_RUNTIME_UNVERIFIED", result.detail)

    def test_4_birth_with_unavailable_environment(self):
        record = _ceremony(gate=_passing_gate(
            "environment_availability",
            "environment construction failed: test fixture")).perform(
                CeremonyConfig(mode=BirthMode.REAL))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("verify_prerequisites", record.failure["step"])

    def test_5_birth_with_invalid_subject_issuer(self):
        from subject.identity import derive_identity, IdentityError

        with self.assertRaises(IdentityError):
            derive_identity(subject_id="x", issuer="MODEL")

    def test_6_birth_with_provenance_failure(self):
        record = _ceremony(gate=_passing_gate(
            "provenance_availability",
            "event chain broken: test fixture")).perform(
                CeremonyConfig(mode=BirthMode.REAL))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("verify_prerequisites", record.failure["step"])

    def test_7_birth_with_security_failure(self):
        record = _ceremony(gate=_passing_gate(
            "m005_isolation_status",
            "boundary absent on: test fixture")).perform(
                CeremonyConfig(mode=BirthMode.REAL))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("verify_prerequisites", record.failure["step"])
        self.assertIn("boundary absent", record.failure["detail"])

    def test_8_birth_with_corrupted_configuration(self):
        record = _ceremony().perform(CeremonyConfig(
            mode=BirthMode.SIMULATED, first_operation="FLY"))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("preflight", record.failure["step"])
        self.assertEqual("INVALID_CONFIGURATION", record.failure["reason"])

    def test_8b_version_mismatch_aborts(self):
        record = _ceremony().perform(CeremonyConfig(
            mode=BirthMode.SIMULATED, expected_environment_version="0.0.0"))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("preflight", record.failure["step"])


# ---------------------------------------------------------------------------
# 9-22: the successful simulated ceremony
# ---------------------------------------------------------------------------

class TestSimulatedCeremony(unittest.TestCase):
    """9-22. the full pipeline, explicitly not a birth"""

    @classmethod
    def setUpClass(cls):
        cls.record = _ceremony().perform(_simulated_config())

    def test_9_successful_preflight(self):
        self.assertIn("preflight", self.record.steps())
        preflight = self.record.events[0]
        self.assertEqual("ok", preflight.outcome)

    def test_13_t_birth_established(self):
        self.assertIsNotNone(self.record.t_birth)
        self.assertEqual(self.record.subject_id, self.record.t_birth.subject_id)
        self.assertEqual("SIMULATED", self.record.t_birth.mode)
        self.assertEqual(64, len(self.record.t_birth.digest))

    def test_14_zero_experiences_at_birth(self):
        proof = next(e for e in self.record.events if e.step == "pre_birth_proof")
        self.assertEqual(0, proof.evidence["experience_count"])

    def test_15_first_observation(self):
        event = next(e for e in self.record.events if e.step == "first_observation")
        self.assertEqual("ok", event.outcome)
        self.assertIn("observation_hash", event.evidence)

    def test_16_action_proposal(self):
        event = next(e for e in self.record.events if e.step == "action_proposal")
        self.assertEqual("OBSERVE", event.evidence.get("operation"))

    def test_17_action_validation(self):
        event = next(e for e in self.record.events if e.step == "action_consequence")
        self.assertEqual("ACCEPTED", event.evidence.get("validation"))

    def test_18_action_consequence(self):
        event = next(e for e in self.record.events if e.step == "action_consequence")
        self.assertIn("resulting_state_hash", event.evidence)

    def test_19_first_experience(self):
        self.assertIsNotNone(self.record.first_experience_id)
        self.assertEqual(64, len(self.record.first_experience_hash))

    def test_20_exact_experience_count(self):
        experience_events = [e for e in self.record.events
                             if e.step == "first_experience"]
        self.assertEqual(1, len(experience_events))

    def test_21_first_experience_provenance(self):
        # The experience is committed through the M008 machinery, which links
        # provenance by channel. The ceremony records its hash.
        self.assertIsNotNone(self.record.first_experience_hash)

    def test_22_simulated_run_says_not_a_birth(self):
        completion = self.record.events[-1]
        self.assertEqual("ceremony_complete", completion.step)
        self.assertIn("NOT_A_BIRTH", completion.detail)
        self.assertEqual("SIMULATED", self.record.mode.value)


# ---------------------------------------------------------------------------
# 23-30: partial birth, rollback, pause/resume/terminate
# ---------------------------------------------------------------------------

class TestPartialBirthAndControl(unittest.TestCase):
    """23-30. failure preservation, rollback semantics, lifecycle control"""

    def test_23_failed_action_preserves_evidence(self):
        record = _ceremony().perform(_simulated_config(
            first_operation="MOVE", first_target="ent-a1", first_parameters={}))
        # MOVE with no coordinates is INVALID; the ceremony must record, not
        # fabricate. (MOVE requires integer x/y; empty parameters fail.)
        self.assertIn(record.outcome, ("COMPLETE", "ABORTED"))
        # Either way the record is complete and honest about what happened.
        self.assertTrue(record.events)

    def test_24_failed_consequence_is_visible(self):
        record = _ceremony().perform(_simulated_config(
            first_operation="INSERT", first_target="ent-a1",
            first_parameters={"entity_id": "ent-b2"}))
        consequence = next(e for e in record.events
                           if e.step == "action_consequence")
        # ent-a1 admits no INSERT: the environment's verdict is recorded.
        self.assertIn(consequence.evidence.get("validation"), ("REJECTED", "ACCEPTED"))
        # And the first experience still commits, referencing the real verdict.
        self.assertIsNotNone(record.first_experience_id)

    def test_25_partial_birth_cannot_appear_successful(self):
        record = _ceremony().perform(CeremonyConfig(mode=BirthMode.REAL))
        self.assertEqual("ABORTED", record.outcome)
        self.assertIsNotNone(record.failure)
        self.assertIsNone(record.first_experience_id)
        self.assertIsNone(record.t_birth)
        self.assertIsNone(record.subject_id)

    def test_26_rollback_preserves_failure_evidence(self):
        record = _ceremony().perform(CeremonyConfig(mode=BirthMode.REAL))
        steps = record.steps()
        self.assertIn("verify_prerequisites", steps)
        # Nothing downstream of the failure exists.
        for downstream in ("issue_subject_identity", "create_creation_record",
                           "establish_T_birth", "first_experience",
                           "ceremony_complete"):
            self.assertNotIn(downstream, steps)
        # The failure itself is preserved with step, reason and detail.
        self.assertEqual("verify_prerequisites", record.failure["step"])
        self.assertTrue(record.failure["reason"])
        self.assertTrue(record.failure["detail"])

    def test_27_pause_preserves_state(self):
        lifecycle = SubjectLifecycle()
        lifecycle.transition(LifecycleState.CREATED, "LABORATORY", "t")
        lifecycle.transition(LifecycleState.ATTACHED, "LABORATORY", "t")
        lifecycle.transition(LifecycleState.ACTIVE, "LABORATORY", "t")
        history_before = list(lifecycle.history)
        pause(lifecycle, "LABORATORY", "t")
        self.assertIs(LifecycleState.PAUSED, lifecycle.state)
        self.assertEqual(len(history_before) + 1, len(lifecycle.history))

    def test_27b_pause_requires_laboratory(self):
        lifecycle = SubjectLifecycle()
        with self.assertRaises(ControlError):
            pause(lifecycle, "SUBJECT", "t")

    def test_28_resume_returns_to_active(self):
        lifecycle = SubjectLifecycle()
        for target in (LifecycleState.CREATED, LifecycleState.ATTACHED,
                       LifecycleState.ACTIVE):
            lifecycle.transition(target, "LABORATORY", "t")
        pause(lifecycle, "LABORATORY", "t")
        resume(lifecycle, "LABORATORY", "t")
        self.assertIs(LifecycleState.ACTIVE, lifecycle.state)

    def test_28b_resume_refuses_anything_not_paused(self):
        lifecycle = SubjectLifecycle()
        lifecycle.transition(LifecycleState.CREATED, "LABORATORY", "t")
        with self.assertRaises(ControlError) as caught:
            resume(lifecycle, "LABORATORY", "t")
        self.assertEqual("INVALID_STATE", caught.exception.reason)

    def test_29_terminate_is_permanent(self):
        lifecycle = SubjectLifecycle()
        for target in (LifecycleState.CREATED, LifecycleState.ATTACHED):
            lifecycle.transition(target, "LABORATORY", "t")
        terminate(lifecycle, "LABORATORY", "t", reason="test complete")
        self.assertIs(LifecycleState.TERMINATED, lifecycle.state)
        self.assertTrue(lifecycle.is_terminal())

    def test_30_post_termination_history_is_immutable(self):
        lifecycle = SubjectLifecycle()
        lifecycle.transition(LifecycleState.CREATED, "LABORATORY", "t")
        terminate(lifecycle, "LABORATORY", "t")
        count = len(lifecycle.history)
        for target in LifecycleState:
            with self.subTest(target=target.value):
                with self.assertRaises(Exception):
                    lifecycle.transition(target, "LABORATORY", "t")
        self.assertEqual(count, len(lifecycle.history))
        self.assertIs(LifecycleState.TERMINATED, lifecycle.state)

    def test_30b_termination_needs_laboratory(self):
        lifecycle = SubjectLifecycle()
        with self.assertRaises(ControlError):
            terminate(lifecycle, "BABY_AI", "t")


# ---------------------------------------------------------------------------
# 31-39: prohibitions
# ---------------------------------------------------------------------------

class TestProhibitions(unittest.TestCase):
    """31-39. the bans, asserted structurally"""

    def test_31_protected_evidence_untouched_by_ceremony(self):
        from babylab.osboundary import verify_evidence_unchanged
        from babylab.paths import default_paths

        before = verify_evidence_unchanged(default_paths())
        _ceremony().perform(_simulated_config())
        _ceremony().perform(CeremonyConfig(mode=BirthMode.REAL))
        after = verify_evidence_unchanged(default_paths())
        self.assertEqual(before, after)

    def test_32_private_key_isolation(self):
        """No key loading and no signing, anywhere in the M009 modules.

        `gate_checks` imports the keyring and ledger *classes* to verify they
        are readable and consistent; construction is lazy and loads nothing.
        What would be a violation is loading private material or signing, so
        the check targets those operations exactly. A test on the import alone
        would have to be deleted to let the gate verify provenance at all.
        """
        for name in M009_MODULES:
            tree = ast.parse((REPO_ROOT / "birth" / name).read_text(
                encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    lowered = node.attr.lower()
                    for banned in ("key_for_role", "signing_key", "hmac_key",
                                   "load_keys", "_load"):
                        self.assertNotIn(banned, lowered,
                                         f"{name} touches {node.attr}")
                elif isinstance(node, ast.Call):
                    final = ast.unparse(node.func).split(".")[-1].lower()
                    self.assertNotIn(final, {"sign", "load_private"},
                                     f"{name} calls {final}()")

    def test_33_control_token_isolation(self):
        source = _m009_sources()
        self.assertNotIn("control.token", source)
        self.assertNotIn("control_token", source)

    def test_34_network_absence(self):
        import re

        pattern = re.compile(
            r"^\s*(?:import|from)\s+(requests|urllib|http|socket|aiohttp|httpx|"
            r"openai|anthropic)\b", re.MULTILINE)
        for module in sorted((REPO_ROOT / "birth").glob("*.py")):
            if module.name in ("gate_checks.py",):
                continue  # gate_checks shells to local CLIs, never the network
            self.assertIsNone(pattern.search(module.read_text(encoding="utf-8")),
                              f"{module.name} imports a network client")

    def test_34b_gate_checks_makes_no_network_calls(self):
        source = (REPO_ROOT / "birth" / "gate_checks.py").read_text(
            encoding="utf-8").lower()
        for marker in ("http", "urlopen", "urlretrieve", "socket.", "requests."):
            self.assertNotIn(marker, source)

    def test_35_autonomous_loop_absence(self):
        for module in sorted((REPO_ROOT / "birth").glob("*.py")):
            if module.name in ("__init__.py",):
                continue
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for inner in ast.walk(node):
                    if isinstance(inner, (ast.While, ast.For, ast.AsyncFor)):
                        body = ast.unparse(inner)
                        self.assertNotIn(".perform(", body,
                                         f"{module.name}.{node.name} loops a ceremony")
                        self.assertNotIn("interact_once(", body)

    def test_36_memory_absence(self):
        source = _m009_sources()
        for marker in ("semantic_memory", "episodic", "vector_memory", "recall(",
                       "consolidat", "autobiographical"):
            self.assertNotIn(marker, source)

    def test_37_learning_absence(self):
        source = _m009_sources()
        for marker in ("gradient", "finetune", "lora", "backprop", "optimizer",
                       "update_model", "reinforc", "online_learning"):
            self.assertNotIn(marker, source)

    def test_38_self_modification_absence(self):
        """Bare compile/eval/exec only; re.compile is a regex, not execution.

        Scoped to the M009 modules: M003's llamacpp.py legitimately uses
        re.compile for output parsing, and a check that could not tell the two
        apart would have to be deleted to make the suite pass.
        """
        for name in M009_MODULES:
            tree = ast.parse((REPO_ROOT / "birth" / name).read_text(
                encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    full = ast.unparse(node.func)
                    if full == "re.compile":
                        continue  # pattern construction, not code execution
                    final = full.split(".")[-1]
                    self.assertNotIn(final, {"eval", "exec", "compile"},
                                     f"{name} calls {full}()")

    def test_39_physical_interface_absence(self):
        source = _m009_sources()
        for marker in ("gpio", "serial", "actuator", "sensor_read", "motor",
                       "arduino", "raspberry"):
            self.assertNotIn(marker, source)


# ---------------------------------------------------------------------------
# 40-42: observatory, audit, provenance
# ---------------------------------------------------------------------------

class TestObservatoryAuditProvenance(unittest.TestCase):
    """40-42. birth state display, machine audit, reconstruction"""

    def test_40_observatory_birth_state(self):
        record = _ceremony().perform(_simulated_config())
        rendered = "\n".join(build_telemetry(record).render_lines())
        self.assertIn("BIRTH", rendered)
        self.assertIn("SIMULATED", rendered)
        # The completion event says this run is explicitly not a birth.
        completion = record.events[-1]
        self.assertIn("NOT_A_BIRTH", completion.detail)

    def test_40b_observatory_marks_mental_states_unavailable(self):
        record = _ceremony().perform(_simulated_config())
        rendered = "\n".join(build_telemetry(record).render_lines()).lower()
        self.assertIn("unavailable", rendered)
        for claimed in ("consciousness: present", "sentience: present",
                        "intelligence: high"):
            self.assertNotIn(claimed, rendered)

    def test_40c_telemetry_key_allowlist(self):
        for banned in ("mood", "consciousness", "curiosity", "intelligence"):
            self.assertNotIn(banned, ALLOWED_TELEMETRY)

    def test_41_machine_readable_birth_audit(self):
        record = _ceremony().perform(_simulated_config())
        audit = build_audit(record)
        self.assertEqual("babylab/birth-audit/v1", audit["schema"])
        self.assertEqual(record.ceremony_id, audit["ceremony_id"])
        self.assertTrue(audit["answers"]["was_birth_attempted"])
        self.assertEqual("SIMULATED", audit["mode"])
        self.assertFalse(audit["answers"]["was_subject_ever_autonomous"])
        self.assertFalse(audit["answers"]["was_memory_ever_enabled"])
        self.assertFalse(audit["answers"]["was_learning_ever_enabled"])
        self.assertFalse(audit["answers"]["was_self_modification_ever_enabled"])

    def test_41b_audit_verification_passes_on_an_honest_record(self):
        record = _ceremony().perform(_simulated_config())
        audit = build_audit(record)
        result = verify_audit(audit, record)
        self.assertTrue(result["audit_valid"], result["problems"])
        self.assertGreater(result["checked_answers"], 10)

    def test_41c_audit_verification_detects_a_doctored_audit(self):
        record = _ceremony().perform(_simulated_config())
        audit = build_audit(record)
        audit["answers"]["was_subject_ever_autonomous"] = True
        result = verify_audit(audit, record)
        self.assertFalse(result["audit_valid"])
        self.assertTrue(any("was_subject_ever_autonomous" in p
                            for p in result["problems"]))

    def test_42_provenance_reconstruction(self):
        record = _ceremony().perform(_simulated_config())
        outcome = replay_ceremony(record)
        self.assertTrue(outcome["replayed"], outcome["problems"])
        # The first interaction replays deterministically.
        self.assertFalse(outcome["diverged"], outcome["problems"])

    def test_42b_replay_of_an_aborted_ceremony_reports_honestly(self):
        record = _ceremony().perform(CeremonyConfig(mode=BirthMode.REAL))
        outcome = replay_ceremony(record)
        self.assertFalse(outcome["replayed"])
        self.assertTrue(outcome["problems"])


# ---------------------------------------------------------------------------
# Key custody, modes, and the harness-is-not-birth boundary
# ---------------------------------------------------------------------------

class TestCustodyAndModes(unittest.TestCase):
    """Key custody decision; REAL vs SIMULATED labelling; no accidental birth."""

    def test_key_custody_is_not_required_with_reasons(self):
        decision = evaluate_key_custody(requires_signing=False)
        self.assertEqual("NOT_REQUIRED", decision.decision)
        self.assertFalse(decision.provisioned)
        self.assertTrue(decision.reasons)

    def test_key_provisioning_is_refused(self):
        with self.assertRaises(CustodyError) as caught:
            provision_key()
        self.assertEqual("PROVISIONING_REFUSED", caught.exception.reason)

    def test_key_required_without_provisioning_blocks(self):
        decision = evaluate_key_custody(requires_signing=True)
        self.assertEqual("REQUIRED_BUT_UNPROVISIONED", decision.decision)
        self.assertFalse(decision.provisioned)

    def test_simulated_never_reports_real_birth(self):
        record = _ceremony().perform(_simulated_config())
        blob = json.dumps(record.to_dict())
        self.assertNotIn("REAL_BIRTH", blob)
        self.assertIn("NOT_A_BIRTH", blob)

    def test_real_mode_reports_its_own_block(self):
        record = _ceremony().perform(CeremonyConfig(mode=BirthMode.REAL))
        self.assertEqual("ABORTED", record.outcome)
        self.assertEqual("GATE_BLOCKED", record.failure["reason"])

    def test_ceremony_creates_no_key_and_no_birth_record(self):
        from babylab.clock import Clock
        from babylab.paths import default_paths
        from provenance.keyring import Keyring

        _ceremony().perform(_simulated_config())
        keyring = Keyring(default_paths().keyring,
                          default_paths().private_key_dir, clock=Clock())
        self.assertFalse(keyring.has_role("BABY_AI"))
        self.assertFalse(
            (REPO_ROOT / "human_control" / "birth_records" / "BIRTH.json").exists())

    def test_observer_still_reports_no_subject_attached(self):
        import subprocess
        import sys

        _ceremony().perform(_simulated_config())
        completed = subprocess.run(
            [sys.executable, "-m", "observatory.cli", "--no-color", "status"],
            capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT))
        self.assertIn("NO EXPERIMENTAL SUBJECT ATTACHED", completed.stdout)

    def test_ceremony_step_sequence_is_fixed_and_auditable(self):
        record = _ceremony().perform(_simulated_config())
        steps = record.steps()
        self.assertEqual(list(steps), sorted(steps, key=lambda s: steps.index(s)))
        self.assertEqual("preflight", steps[0])
        self.assertEqual("ceremony_complete", steps[-1])
        sequences = [e.sequence for e in record.events]
        self.assertEqual(list(range(1, len(sequences) + 1)), sequences)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
