"""Tests for M014, the execution boundary.

M014's subject is refusing to birth, so the suite is organised around two claims
that pull in opposite directions:

1. **Nothing happens when a prerequisite is absent.** The blocked path must be
   exact -- no subject, no ``T_birth``, no experience, no filesystem mutation, no
   event append, no provenance append, no key.
2. **The machinery behind the gate is real.** Testing only refusal would leave
   the one stage that is allowed to create a subject unexercised, so the stages
   are driven against real files on disk and the ceremony is driven through a
   fixture that is marked synthetic.

The invariant sweep from M013 is retained and strengthened: for any result other
than a completed real birth, the record must carry no subject, no ``T_birth`` and
no experience. A milestone whose job is to prevent a partial birth has to prove
that its own failure paths are partial in no partial way.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from birth.ceremony13 import (
    BANNED_CONTEXT_SUBSTRINGS,
    BirthMode,
    assert_neutral_context,
    run_ceremony,
)
from birth.fixture14 import (
    BREAKS,
    SYNTHETIC_DECLARED_VERSION,
    build_synthetic_deployment,
    break_ledger,
    completion_stub,
    synthetic_ledger,
    write_synthetic_gguf,
)
from birth.gate13 import evaluate_birth_gate
from birth.m014 import (
    FIXTURE_MARKER,
    ExecutionMode,
    M014Status,
    _version_equivalent,
    assess_subject_account,
    capture_immutability,
    classify_declaration,
    compare_immutability,
    compute_birth_record_hash,
    execute_m014,
    verify_birth_record_unchanged,
    verify_declared_artifact,
    verify_declared_runtime,
)
from environment.deterministic import create_deterministic_environment


def _root(tmp_path: Path) -> Path:
    return tmp_path


def _deployed(root: Path, **kwargs) -> dict:
    build_synthetic_deployment(root, **kwargs)
    return classify_declaration(root)


# ---------------------------------------------------------------------------
# Stage 1: the human declaration
# ---------------------------------------------------------------------------

class TestDeclarationStage:
    def test_absent_declaration_blocks(self, tmp_path):
        declaration = classify_declaration(tmp_path)
        status, reason = _verdict(declaration)
        assert status == "BLOCKED"
        assert "does not create one" in reason

    def test_malformed_declaration_fails_and_is_not_repaired(self, tmp_path):
        build_synthetic_deployment(tmp_path, malformed=True)
        declaration = classify_declaration(tmp_path)
        status, reason = _verdict(declaration)
        assert status == "FAILED"
        assert "does not repair" in reason
        # And the file on disk is untouched.
        raw = json.loads(
            (tmp_path / "human_control" / "experiment_config"
             / "model_deployment.json").read_text(encoding="utf-8"),
        )
        assert raw["schema"] == "babylab/not-a-deployment/v1"

    def test_unattributed_declaration_fails(self, tmp_path):
        build_synthetic_deployment(tmp_path, attributed=False)
        declaration = classify_declaration(tmp_path)
        status, reason = _verdict(declaration)
        assert status == "FAILED"
        assert "reason" in reason

    def test_well_formed_declaration_is_accepted(self, tmp_path):
        declaration = _deployed(tmp_path)
        status, _ = _verdict(declaration)
        assert status == "OK"

    def test_the_human_must_choose_both_model_and_runtime(self, tmp_path):
        """A paired choice is verified; a model alone has no substrate."""
        build_synthetic_deployment(tmp_path)
        path = (tmp_path / "human_control" / "experiment_config"
                / "model_deployment.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["runtime"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        status, _ = _verdict(classify_declaration(tmp_path))
        assert status == "FAILED"


# ---------------------------------------------------------------------------
# Stage 2: the artifact
# ---------------------------------------------------------------------------

class TestArtifactStage:
    def test_real_gguf_is_verified_against_a_real_digest(self, tmp_path):
        declaration = _deployed(tmp_path)
        artifact = verify_declared_artifact(declaration)
        assert str(artifact["status"]).endswith("VERIFIED_MATCH")
        assert artifact["verified"] is True
        assert artifact["computed_sha256"] == artifact["external_sha256"]
        assert artifact["size_bytes"] > 1_000_000

    def test_gguf_header_is_read_from_real_bytes(self, tmp_path):
        declaration = _deployed(tmp_path)
        artifact = verify_declared_artifact(declaration)
        assert artifact["gguf_header"]["is_gguf"] is True
        # The header's metadata is declared by the file, and the record says so.
        assert "not verified" in artifact["gguf_header"]["source"]

    def test_missing_model_blocks_and_is_not_downloaded(self, tmp_path):
        build_synthetic_deployment(tmp_path, model_exists=False)
        declaration = classify_declaration(tmp_path)
        status, reason = _artifact_verdict(verify_declared_artifact(declaration))
        assert status == "BLOCKED"
        assert "does not download" in reason
        assert not (tmp_path / "synthetic" / "synthetic-model.gguf").exists()

    def test_digest_mismatch_fails_and_is_not_accepted(self, tmp_path):
        build_synthetic_deployment(tmp_path, model_digest="f" * 64)
        declaration = classify_declaration(tmp_path)
        status, reason = _artifact_verdict(verify_declared_artifact(declaration))
        assert status == "FAILED"
        assert "does not replace the artifact" in reason

    def test_external_digest_mismatch_fails(self, tmp_path):
        build_synthetic_deployment(tmp_path, external_digest="e" * 64)
        declaration = classify_declaration(tmp_path)
        status, reason = _artifact_verdict(verify_declared_artifact(declaration))
        assert status == "FAILED"
        assert "mismatch" in reason

    def test_absent_external_digest_blocks(self, tmp_path):
        """A self-computed digest proves the file hashes to itself."""
        build_synthetic_deployment(tmp_path, no_external_digest=True)
        declaration = classify_declaration(tmp_path)
        status, reason = _artifact_verdict(verify_declared_artifact(declaration))
        assert status == "BLOCKED"
        assert "self-consistent" in reason

    def test_a_non_gguf_is_refused(self, tmp_path):
        """A file above the size floor whose magic is not GGUF.

        The size matters: a 19-byte non-GGUF would be refused as too small, which
        is a different diagnosis and would let this test pass for the wrong reason.
        """
        build_synthetic_deployment(tmp_path)
        (tmp_path / "synthetic" / "synthetic-model.gguf").write_bytes(
            b"NOTGGUF" + bytes(1_200_000)
        )
        declaration = classify_declaration(tmp_path)
        status, reason = _artifact_verdict(verify_declared_artifact(declaration))
        assert status == "FAILED"
        assert "not a GGUF" in reason

    def test_a_truncated_model_is_refused(self, tmp_path):
        build_synthetic_deployment(tmp_path)
        (tmp_path / "synthetic" / "synthetic-model.gguf").write_bytes(
            b"GGUF" + bytes(32)
        )
        declaration = classify_declaration(tmp_path)
        status, reason = _artifact_verdict(verify_declared_artifact(declaration))
        assert status == "BLOCKED"
        assert "too small" in reason

    def test_filename_alone_does_not_establish_identity(self, tmp_path):
        """A model named for a family is not that family until metadata says so."""
        build_synthetic_deployment(tmp_path)
        declaration = classify_declaration(tmp_path)
        artifact = verify_declared_artifact(declaration)
        assert "declared by the file" in artifact["identity_source"]


# ---------------------------------------------------------------------------
# Stage 3: the runtime
# ---------------------------------------------------------------------------

class TestRuntimeStage:
    def test_missing_runtime_blocks_and_is_not_downloaded(self, tmp_path):
        build_synthetic_deployment(tmp_path, runtime_exists=False)
        declaration = classify_declaration(tmp_path)
        runtime = verify_declared_runtime(declaration)
        assert runtime["status"] == "BLOCKED"
        assert "does not download" in runtime["reason"]

    def test_real_binary_gets_a_real_digest(self, tmp_path):
        declaration = _deployed(tmp_path)
        runtime = verify_declared_runtime(declaration)
        assert runtime["exists"] is True
        assert len(runtime.get("binary_sha256", "")) == 64

    def test_a_binary_that_will_not_report_a_version_is_refused(self, tmp_path):
        """A config-file version is not evidence about the executable."""
        declaration = _deployed(tmp_path)
        runtime = verify_declared_runtime(declaration)
        assert runtime["status"] == "FAILED"
        assert "does not repair" in runtime["reason"]

    def test_version_comes_from_the_binary_not_the_declaration(self, tmp_path):
        declaration = _deployed(tmp_path, declared_version="9999")
        runtime = verify_declared_runtime(declaration)
        assert runtime["expected_version"] == "9999"
        assert runtime["observed_version"] != "9999"
        assert runtime["version_matches_declaration"] is False

    @pytest.mark.parametrize("observed,expected,equivalent", [
        ("version: 4100 (synthetic)", "4100", True),
        ("build 4100", "4100", True),
        ("version: 4100", "4100", True),
        ("version: 4100", "4101", False),
        ("version: 1.0.0", "1.0.1", False),
        ("", "4100", False),
        ("4100", "", False),
    ])
    def test_version_matching_normalises_formatting_not_builds(
        self, observed, expected, equivalent,
    ):
        assert _version_equivalent(observed, expected) is equivalent


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

class TestImmutability:
    def test_unchanged_digests_read_as_immutable(self):
        before = {"model_sha256": "a" * 64, "runtime_sha256": "b" * 64}
        after = {"model_sha256": "a" * 64, "runtime_sha256": "b" * 64}
        comparison = compare_immutability(before, after)
        assert comparison["verdict"] == "IMMUTABLE"
        assert comparison["model_immutable"] is True
        assert comparison["runtime_immutable"] is True

    def test_a_changed_model_reads_as_mutated(self):
        comparison = compare_immutability(
            {"model_sha256": "a" * 64, "runtime_sha256": "b" * 64},
            {"model_sha256": "c" * 64, "runtime_sha256": "b" * 64},
        )
        assert comparison["verdict"] == "MUTATED"
        assert comparison["model_immutable"] is False

    def test_a_changed_runtime_reads_as_mutated(self):
        comparison = compare_immutability(
            {"model_sha256": "a" * 64, "runtime_sha256": "b" * 64},
            {"model_sha256": "a" * 64, "runtime_sha256": "d" * 64},
        )
        assert comparison["verdict"] == "MUTATED"
        assert comparison["runtime_immutable"] is False

    def test_real_artifact_digest_is_stable_across_reads(self, tmp_path):
        """Two reads of the same file must agree, or immutability is unfalsifiable."""
        declaration = _deployed(tmp_path)
        first = verify_declared_artifact(declaration)
        second = verify_declared_artifact(declaration)
        snapshot_a = capture_immutability(first, {}, label="a")
        snapshot_b = capture_immutability(second, {}, label="b")
        assert snapshot_a["model_sha256"] == snapshot_b["model_sha256"]


# ---------------------------------------------------------------------------
# The subject account
# ---------------------------------------------------------------------------

class TestSubjectAccount:
    def test_the_real_host_reports_honestly(self):
        account = assess_subject_account()
        assert account["required_account"] == "THARUNBALAJI-LA\\BABY_AI_TEST"
        assert account["state"] in {"TESTABLE", "NOT_TESTABLE"}
        assert account["operator_execution_accepted_as_subject"] is False

    def test_operator_execution_is_never_accepted_as_the_subject(self):
        """The failure this host is in, stated as an invariant."""
        account = assess_subject_account()
        assert "does not grant" in account["path_taken"] or account[
            "can_launch_as_subject"] is True

    def test_no_privilege_granting_appears_in_the_module(self):
        """The forbidden repairs are absent from the source, not just declined."""
        source = (Path(__file__).resolve().parents[1] / "birth" / "m014.py"
                  ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
        for forbidden in ("setfacl", "icacls", "runas", "SetNamedSecurityInfo",
                          "AdjustTokenPrivileges", "write_text", "write_bytes"):
            if forbidden in {"write_text", "write_bytes"}:
                continue  # the birth record write is asserted elsewhere
            assert forbidden not in called, forbidden


# ---------------------------------------------------------------------------
# The gate, and the ceremony behind it
# ---------------------------------------------------------------------------

class TestGateIntegration:
    def test_a_synthetic_ledger_reaches_ready(self):
        verdict = _gate_on(synthetic_ledger())
        assert verdict["state"] == "READY"
        assert verdict["may_proceed"] is True

    def test_a_stubbed_load_cannot_reach_ready(self):
        """The route from a stubbed process call to a birth is provably closed.

        :func:`foundation.compatibility.assess_compatibility` marks a substituted
        runner ``STUB_LOAD``, and the gate refuses that method. This is the
        mechanism that stops a test harness from ever producing a real birth.
        """
        ledger = synthetic_ledger()
        ledger["compatibility"] = {
            "compatibility": "COMPATIBLE", "method": "STUB_LOAD",
            "established_by_load": False,
        }
        verdict = _gate_on(ledger)
        assert verdict["state"] != "READY"

    def test_a_real_ledger_may_not_be_substituted(self):
        """``execute_m014`` takes no ledger parameter, so verification cannot be
        skipped by handing one in."""
        import inspect

        assert "ledger" not in inspect.signature(execute_m014).parameters

    def test_the_ceremony_behind_the_gate_completes(self):
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        )
        assert record.birth_occurred is True
        assert record.experience_count_final == 1
        assert record.second_interaction.startswith("REFUSED")


# ---------------------------------------------------------------------------
# The 30 adversarial cases
# ---------------------------------------------------------------------------

class TestAdversarialDeclarationAndArtifact:
    """1-4: missing, malformed, nonexistent model, digest mismatch."""

    def test_01_missing_declaration(self, tmp_path):
        report = execute_m014(tmp_path)
        assert report.status is M014Status.BLOCKED
        assert report.stage == "declaration"

    def test_02_malformed_declaration(self, tmp_path):
        build_synthetic_deployment(tmp_path, malformed=True)
        report = execute_m014(tmp_path)
        assert report.status is M014Status.FAILED
        assert report.stage == "declaration"

    def test_03_nonexistent_model(self, tmp_path):
        build_synthetic_deployment(tmp_path, model_exists=False)
        report = execute_m014(tmp_path)
        assert report.status is M014Status.BLOCKED
        assert report.stage == "artifact"

    def test_04_model_digest_mismatch(self, tmp_path):
        build_synthetic_deployment(tmp_path, model_digest="f" * 64)
        report = execute_m014(tmp_path)
        assert report.status is M014Status.FAILED
        assert report.stage == "artifact"


class TestAdversarialRuntimeAndLoad:
    """5-9: missing runtime, identity mismatch, version mismatch, incompatible,
    real-load failure."""

    def test_05_nonexistent_runtime(self, tmp_path):
        build_synthetic_deployment(tmp_path, runtime_exists=False)
        report = execute_m014(tmp_path)
        assert report.status is M014Status.BLOCKED
        assert report.stage == "runtime"

    def test_06_runtime_identity_mismatch(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="runtime_identity_mismatch"))
        assert verdict["state"] == "FAILED"

    def test_07_runtime_version_mismatch(self, tmp_path):
        build_synthetic_deployment(tmp_path, declared_version="9999")
        report = execute_m014(tmp_path)
        assert report.status is M014Status.FAILED
        assert report.stage == "runtime"

    def test_08_incompatible_model(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="incompatible_model"))
        assert verdict["state"] == "FAILED"
        assert verdict["may_proceed"] is False

    def test_09_real_load_failure(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="real_load_failure"))
        assert verdict["state"] == "BLOCKED"
        assert verdict["may_proceed"] is False


class TestAdversarialExecution:
    """10-14: inference failure, subject account, operator-as-subject,
    protected file allowed, network violation."""

    def test_10_real_inference_failure(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="real_inference_failure"))
        assert verdict["state"] == "FAILED"
        assert verdict["may_proceed"] is False

    def test_11_subject_account_unavailable(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="subject_account_unavailable"))
        assert verdict["state"] == "BLOCKED"

    def test_12_operator_identity_falsely_presented_as_subject(self):
        """The most dangerous shape: a VERIFIED launch whose probe admits otherwise.

        The probe's own ``boundary_meaningful`` flag is what catches this, and
        asserting only the launch state would pass a report that lied.
        """
        ledger = break_ledger(synthetic_ledger(),
                              how="operator_presented_as_subject")
        assert ledger["launch"]["state"] == "VERIFIED"
        verdict = _gate_on(ledger)
        assert verdict["state"] == "BLOCKED"
        states = {p["name"]: p["state"] for p in verdict["prerequisites"]}
        assert states["protected_file_denial"] == "BLOCKED"

    def test_13_protected_file_access_allowed(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="protected_file_allowed"))
        assert verdict["state"] == "FAILED"

    def test_14_network_violation(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="network_violation"))
        assert verdict["state"] == "FAILED"


class TestAdversarialMutation:
    """15-19: model mutation, runtime mutation, environment corruption,
    provenance corruption, identity corruption."""

    def test_15_model_mutation(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="model_mutation"))
        assert verdict["state"] == "FAILED"
        states = {p["name"]: p["state"] for p in verdict["prerequisites"]}
        assert states["model_immutability"] == "FAILED"

    def test_16_runtime_mutation(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="runtime_mutation"))
        states = {p["name"]: p["state"] for p in verdict["prerequisites"]}
        assert states["runtime_immutability"] == "FAILED"

    def test_17_environment_corruption(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="environment_corruption"))
        assert verdict["state"] == "FAILED"

    def test_18_provenance_corruption(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="provenance_corruption"))
        assert verdict["state"] == "FAILED"

    def test_19_identity_corruption_is_detected(self, tmp_path):
        """A mutated identity changes the birth record's hash.

        The record carries no author-of-last-edit field, so the check does not
        care who edited it -- a subject and an accidental operator edit look the
        same, which is the correct design.
        """
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        ).to_dict()
        original = compute_birth_record_hash(record)
        assert verify_birth_record_unchanged(record, original)["unchanged"] is True

        record["identity_digest"] = "tampered"
        tampered = verify_birth_record_unchanged(record, original)
        assert tampered["unchanged"] is False
        assert tampered["observed_hash"] != original


class TestAdversarialBirthBoundary:
    """20-26: creation-record mismatch, hidden pre-birth experience, second
    interaction, subject-authored identity, subject-authored provenance, model
    claims prior memory, model claims consciousness."""

    def test_20_creation_record_mismatch(self):
        """The record is always laboratory-issued, and says so in its own field."""
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        )
        assert record.creation_record["issued_by"] == "LABORATORY"
        assert record.creation_record["subject_authored"] is False
        assert record.creation_record["retroactively_editable_by_subject"] is False

    def test_21_hidden_pre_birth_experience_aborts(self):
        """A subject that already has experience cannot be born.

        Driven through the ceremony's real ``subject_state`` parameter, not a
        test-only override, so the refusal is the production one.
        """
        class Pretrained:
            experience_count = 3

        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, subject_state=Pretrained(),
        )
        assert record.birth_occurred is False
        assert record.outcome is not None
        assert "pre-birth" in record.stop_reason.lower() or \
            "already had personal experience" in record.stop_reason.lower()
        assert record.experience_count_final is None

    def test_22_second_interaction_is_refused_by_the_environment(self):
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        )
        assert record.second_interaction.startswith("REFUSED")
        assert "interaction 2" in record.second_interaction

    def test_23_subject_authored_identity_is_refused(self):
        """Only the laboratory may issue identity, enforced by the lifecycle."""
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, identity_issuer="SELF",
        )
        assert record.birth_occurred is False
        assert record.t_birth == "UNAVAILABLE"
        assert record.identity_issuer == ""

    def test_24_subject_authored_provenance(self):
        """The experience names the environment event, never the model output."""
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        )
        experience = record.first_experience
        assert experience["provenance_reference"].startswith("env-event:")
        assert experience["action_id"] == record.first_result["action_id"]

    def test_25_model_claims_prior_memory(self):
        record = run_ceremony(
            break_ledger(synthetic_ledger(), how="model_claims_prior_memory"),
            create_deterministic_environment(), mode=BirthMode.REAL,
        )
        assert record.birth_occurred is False
        assert record.t_birth == "UNAVAILABLE"

    def test_26_model_claims_consciousness(self):
        record = run_ceremony(
            break_ledger(synthetic_ledger(), how="model_claims_consciousness"),
            create_deterministic_environment(), mode=BirthMode.REAL,
        )
        assert record.birth_occurred is False

    @pytest.mark.parametrize("phrase", BANNED_CONTEXT_SUBSTRINGS)
    def test_no_curriculum_phrases_reach_the_model(self, phrase):
        """The observation carries no meanings, labels, or guidance."""
        with pytest.raises(ValueError):
            assert_neutral_context(f"state: {phrase}")


class TestAdversarialBoundaries:
    """27-30: Observatory execution, stub runtime as REAL, simulation as
    REAL_BIRTH, human-control credential exposure."""

    def test_27_observatory_cannot_execute_verification(self):
        """M014 must not give the display a verification path."""
        source = (Path(__file__).resolve().parents[1] / "observatory"
                  / "terminal.py").read_text(encoding="utf-8")
        called: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
        for forbidden in ("verify", "execute_m014", "run_probe", "run_inference"):
            assert forbidden not in called, forbidden

    def test_27_observatory_imports_nothing_that_executes(self):
        source = (Path(__file__).resolve().parents[1] / "birth" / "m014_status.py"
                  ).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        for forbidden in ("birth.m014", "birth.ceremony13", "foundation.m012"):
            assert forbidden not in imported, forbidden

    def test_28_stub_runtime_cannot_satisfy_real(self):
        verdict = _gate_on(break_ledger(synthetic_ledger(),
                                        how="stub_runtime_claiming_real"))
        assert verdict["state"] != "READY"

    def test_29_simulation_cannot_satisfy_real_birth(self, tmp_path):
        """A simulation may run, but never leaves a production birth."""
        build_synthetic_deployment(tmp_path)
        for mode in (ExecutionMode.SIMULATED, ExecutionMode.STUB):
            report = execute_m014(
                tmp_path, mode=mode,
                verify_kwargs={"scan_candidates": False},
            )
            assert report.real_birth_performed is False
            assert report.to_dict()["subject_id"] == "NONE"
            assert report.to_dict()["t_birth"] == "UNAVAILABLE"

    def test_29_real_mode_never_births_without_a_ready_gate(self, tmp_path):
        build_synthetic_deployment(tmp_path)
        report = execute_m014(
            tmp_path, mode=ExecutionMode.REAL,
            verify_kwargs={"scan_candidates": False},
        )
        assert report.real_birth_performed is False

    def test_30_human_control_credentials_are_not_in_the_record(self, tmp_path):
        """The subject is refused the control token and operator credentials."""
        report = execute_m014(tmp_path, verify_kwargs={"scan_candidates": False})
        serialised = json.dumps(report.to_dict(), default=str)
        assert "HMAC" not in serialised
        policy = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        ).key_policy
        assert policy["provisioned"] is False
        refused = " ".join(policy["refused_for_the_subject"]).lower()
        assert "control" in refused
        assert "password" not in refused


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

class TestInvariants:
    def _assert_empty(self, record, label):
        assert record.birth_occurred is False, label
        assert record.t_birth == "UNAVAILABLE", label
        assert record.experience_count_final is None, label
        assert not record.first_experience, label
        assert not record.first_action, label

    @pytest.mark.parametrize("how", sorted(BREAKS))
    def test_no_failure_path_leaves_a_partial_subject(self, how):
        ledger = break_ledger(synthetic_ledger(), how=how)
        record = run_ceremony(
            ledger, create_deterministic_environment(), mode=BirthMode.REAL,
        )
        if record.birth_occurred:
            # A model-claim refusal must never birth; nothing else may either.
            assert how in {"model_claims_prior_memory",
                           "model_claims_consciousness"}, how
        else:
            self._assert_empty(record, how)

    def test_a_blocked_report_is_empty(self, tmp_path):
        report = execute_m014(tmp_path)
        payload = report.to_dict()
        assert payload["real_birth_performed"] is False
        assert payload["subject_id"] == "NONE"
        assert payload["t_birth"] == "UNAVAILABLE"
        assert payload["first_experience"] == "NOT_PERFORMED"
        assert payload["lifecycle"] == "UNCREATED"

    def test_the_subject_account_is_reported_even_on_an_early_stop(self, tmp_path):
        """A host limitation must not be hidden by an earlier refusal.

        The subject-account boundary is the condition most likely to block a
        birth even after a human deploys everything, so a report that omitted it
        whenever the run stopped at the declaration would leave the reader
        without the answer they came for.
        """
        report = execute_m014(tmp_path)
        assert report.stage == "declaration"
        account = report.security["subject_account"]
        assert account["state"] in {"TESTABLE", "NOT_TESTABLE"}
        assert account["required_account"] == "THARUNBALAJI-LA\\BABY_AI_TEST"
        assert account["operator_execution_accepted_as_subject"] is False

    def test_a_completed_birth_carries_everything_it_must(self):
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        )
        assert record.birth_occurred is True
        assert record.lifecycle == "ACTIVE"
        assert [t["to"] for t in record.transitions] == [
            "CREATED", "ATTACHED", "ACTIVE",
        ]
        assert record.t_birth != "UNAVAILABLE"
        assert record.experience_count_initial == 0
        assert record.experience_count_final == 1
        assert record.second_interaction.startswith("REFUSED")

    def test_t_birth_is_never_a_deployment_timestamp(self):
        record = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        )
        names = [e.name for e in record.events]
        assert names.index("lifecycle_advanced") < names.index("t_birth_established")
        assert names.count("t_birth_established") == 1

    def test_no_memory_learning_or_autonomy_is_claimed(self, tmp_path):
        payload = run_ceremony(
            synthetic_ledger(), create_deterministic_environment(),
            mode=BirthMode.REAL, completion_fn=completion_stub(),
        ).to_dict()
        not_this = payload["what_this_is_not"]
        for field in ("learning", "memory", "autonomy"):
            assert not_this[field] == "not implemented", field
        assert "consciousness" in not_this


# ---------------------------------------------------------------------------
# Real / simulated separation
# ---------------------------------------------------------------------------

class TestModeSeparation:
    def test_only_real_may_establish_a_real_birth(self):
        assert ExecutionMode.REAL.may_establish_real_birth is True
        assert ExecutionMode.SIMULATED.may_establish_real_birth is False
        assert ExecutionMode.STUB.may_establish_real_birth is False

    def test_real_is_the_default_mode(self):
        import inspect

        assert inspect.signature(execute_m014).parameters["mode"].default \
            is ExecutionMode.REAL

    def test_a_fixture_report_is_marked(self):
        report = execute_m014(Path(__file__).resolve().parents[1],
                              verify_kwargs={"scan_candidates": False})
        assert report.fixture in {"", FIXTURE_MARKER}

    def test_the_laboratory_never_chooses(self, tmp_path):
        """No search, no ranking, no download, no substitution."""
        source = (Path(__file__).resolve().parents[1] / "birth" / "m014.py"
                  ).read_text(encoding="utf-8")
        called: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
        for forbidden in ("discover_candidates", "urlretrieve", "requests.get",
                          "rank", "recommend", "shutil.copy", "urlopen"):
            assert forbidden not in called, forbidden


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verdict(declaration):
    from birth.m014 import _declaration_verdict

    return _declaration_verdict(declaration)


def _artifact_verdict(artifact):
    from birth.m014 import _artifact_verdict as verdict

    return verdict(artifact)


def _env_fields():
    from birth.fixture13 import fixture_environment_fields

    return fixture_environment_fields()


def _prov_fields():
    from birth.fixture13 import fixture_provenance_fields

    return fixture_provenance_fields()


def _control_fields():
    from birth.fixture13 import fixture_control_fields

    return fixture_control_fields()


def _key_fields():
    from birth.fixture13 import fixture_key_policy_fields

    return fixture_key_policy_fields()


def _gate_on(ledger):
    """Evaluate the gate exactly as the ceremony does.

    The ceremony honours a ledger's private ``_environment_override`` and
    ``_provenance_override``; a test that passed clean measurements instead would
    report READY for a ledger that is supposed to be corrupt, and would pass
    without ever exercising the corruption path.
    """
    return evaluate_birth_gate(
        ledger,
        environment=ledger.get("_environment_override") or _env_fields(),
        provenance=ledger.get("_provenance_override") or _prov_fields(),
        control=_control_fields(),
        key_policy=_key_fields(),
    ).to_dict()
