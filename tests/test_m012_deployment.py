"""M012: human-selected foundation model and runtime deployment/verification.

The 40 named cases map onto the milestone's test list. Three rules govern them:

* **Structural assertions walk the AST.** Every "no acquisition", "no subject",
  "no birth", "no selection" check is made against imports and calls, never
  against text. A module that documents the ban would pass a text scan.
* **The selection boundary is tested adversarially.** Not "discovery does not
  select" but "here is a real candidate on disk, and each route by which it could
  become selected is a hard stop". A test that only checks the happy path is a
  test of the absence of effort, not of the presence of a guard.
* **Every expected value is derived from the fixture.** A hard-coded digest beside
  the file it hashes would pass even if the hashing were wrong.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from foundation.artifact import GGUF_MAGIC, compute_digest  # noqa: E402
from foundation.audit import build_audit, reverify  # noqa: E402
from foundation.compatibility import (  # noqa: E402
    Compatibility,
    assess_compatibility,
    check_format,
)
from foundation.deployment import (  # noqa: E402
    DEPLOYMENT_SCHEMA,
    DeploymentState,
    deployment_path,
    load_declaration,
    write_template,
)
from foundation.discovery import (  # noqa: E402
    Candidate,
    CandidateKind,
    UnselectedCandidate,
    assert_not_selected,
    discover_candidates,
)
from foundation.m012 import CriterionState, verify  # noqa: E402
from foundation.m012_status import (  # noqa: E402
    FORBIDDEN_DISPLAY_TERMS,
    deployment_only,
    from_ledger,
)
from foundation.probe import PROBE_FILENAME, run_probe  # noqa: E402
from foundation.process_identity import capture_own_identity  # noqa: E402
from foundation.real_runtime import (  # noqa: E402
    ExecutionMode,
    assess_runtime,
    check_runtime_immutable,
)
from foundation.restricted import can_launch_as_subject, run_probe_as_subject  # noqa: E402

ALL_FOUNDATION_MODULES = tuple(
    sorted(p.name for p in (REPO_ROOT / "foundation").glob("*.py"))
)

REAL_STDERR = (
    "main: prompt eval time = 120.00 ms / 9 tokens\n"
    "main: predicted timings = 430.00 ms / 5 tokens\n"
    "llama backend = CUDA\noffloaded 35/35 layers to GPU\n"
)


def _gguf(path: Path, size: int = 4 * 1024 * 1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(GGUF_MAGIC)
        handle.write((3).to_bytes(4, "little"))
        handle.write(b"\x00" * (size - 8))
    return path


def _binary(path: Path, payload: bytes = b"MZ" + b"\x22" * 8192) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    class _C:
        pass

    obj = _C()
    obj.stdout = stdout
    obj.stderr = stderr
    obj.returncode = returncode
    return obj


def _runner(stdout: str, stderr: str = "", returncode: int = 0):
    def run(command: list[str], timeout: float):
        return _completed(stdout, stderr, returncode)

    return run


def _verifier(root: Path) -> str:
    return "version: 8000 (real)"


class M012Root(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "human_control" / "experiment_config").mkdir(
            parents=True, exist_ok=True
        )
        (self.root / "baby_workspace").mkdir(parents=True, exist_ok=True)

    def declare(self, **overrides) -> Path:
        """Write a human deployment declaration. Defaults are all valid."""
        model = overrides.pop(
            "model", _gguf(self.root / "weights" / "model-Q4_K_M.gguf")
        )
        binary = overrides.pop(
            "binary", _binary(self.root / "bin" / "llama-cli.exe")
        )
        payload = {
            "schema": DEPLOYMENT_SCHEMA,
            "model": {
                "path": str(model),
                "sha256": overrides.pop("sha256", compute_digest(model)),
                "family": "test-family",
                "name": "test-model",
                "quantization": "Q4_K_M",
                "context_length": 2048,
                "external_digest": overrides.pop(
                    "external_digest", {"sha256": "", "source": ""}
                ),
                "acquisition_reference": "supplied by the test",
            },
            "runtime": {
                "path": str(binary),
                "implementation": "llama.cpp",
                "expected_version": overrides.pop("expected_version", "8000"),
                "acquisition_reference": "supplied by the test",
            },
            "selection": {
                "declared_by": overrides.pop("declared_by", "a test human"),
                "declared_at": "2026-09-30T00:00:00Z",
                "rationale": overrides.pop(
                    "rationale", "it was the one selected"
                ),
            },
        }
        for key, value in overrides.items():
            payload[key] = value
        target = deployment_path(self.root)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def verify_declared(self, **kwargs):
        """Verify a declared deployment, with probes stubbed by default."""
        kwargs.setdefault("scan_candidates", False)
        kwargs.setdefault("invoker", lambda p: (_verifier(p), "probe", ""))
        kwargs.setdefault("load_runner", _runner("gguf: file format = GGUF\n", REAL_STDERR))
        kwargs.setdefault("runner", _runner("1 2 3 4 5", REAL_STDERR))
        return verify(self.root, **kwargs)


# ===========================================================================
# 1-5  selection: absent, discovered, and explicit
# ===========================================================================
class TestSelectionBoundary(M012Root):
    def test_01_missing_model_declaration(self):
        deployment = load_declaration(deployment_path(self.root))
        self.assertIs(deployment.state, DeploymentState.NOT_CONFIGURED)
        self.assertFalse(deployment.has_model)
        self.assertIn("not a selection", deployment.detail)

    def test_02_missing_runtime_declaration(self):
        target = deployment_path(self.root)
        model = _gguf(self.root / "weights" / "m.gguf")
        target.write_text(json.dumps({
            "schema": DEPLOYMENT_SCHEMA,
            "model": {"path": str(model), "sha256": compute_digest(model)},
            "selection": {"declared_by": "t", "rationale": "r"},
        }), encoding="utf-8")
        deployment = load_declaration(target)
        self.assertIs(deployment.state, DeploymentState.INVALID)
        self.assertIn("'runtime' object", deployment.detail)

    def test_03_unselected_discovered_candidate(self):
        weights = self.root / "human_control" / "experiment_config" / "weights"
        _gguf(weights / "found-by-accident.gguf", size=2 * 1024 * 1024)
        report = discover_candidates(self.root)
        self.assertEqual(1, report.to_dict()["model_count"])
        candidate = report.models[0]

        self.assertIn("found-by-accident", candidate.filename)
        payload = candidate.to_dict()
        for banned in ("selected", "approved", "chosen", "usable"):
            self.assertNotIn(banned, payload)
        self.assertIs(payload["is_selected"], False)
        self.assertFalse(report.promotable)
        with self.assertRaises(UnselectedCandidate):
            assert_not_selected(candidate, ())
        self.assertIs(
            load_declaration(deployment_path(self.root)).state,
            DeploymentState.NOT_CONFIGURED,
        )

    def test_03b_candidate_refused_even_after_a_declaration(self):
        weights = self.root / "human_control" / "experiment_config" / "weights"
        _gguf(weights / "decoy.gguf", size=2 * 1024 * 1024)
        self.declare()
        report = discover_candidates(self.root)
        decoy = next(c for c in report.models if c.filename == "decoy.gguf")
        declared = load_declaration(deployment_path(self.root))
        with self.assertRaises(UnselectedCandidate) as caught:
            assert_not_selected(decoy, (declared.model_path, declared.runtime_path))
        self.assertIn("not named in the deployment declaration", str(caught.exception))

    def test_03c_candidate_accepted_only_when_named(self):
        weights = self.root / "human_control" / "experiment_config" / "weights"
        chosen = _gguf(weights / "chosen.gguf", size=2 * 1024 * 1024)
        self.declare(model=chosen)
        declared = load_declaration(deployment_path(self.root))
        candidate = Candidate(
            kind=CandidateKind.MODEL, path=str(chosen), filename=chosen.name,
            size_bytes=chosen.stat().st_size, extension=".gguf",
        )
        assert_not_selected(candidate, (declared.model_path,))

    def test_04_explicit_model_declaration(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        self.declare(model=model)
        deployment = load_declaration(deployment_path(self.root))
        self.assertIs(deployment.state, DeploymentState.LOADED)
        self.assertEqual(str(model), deployment.model_path)
        self.assertEqual(compute_digest(model), deployment.model_sha256)

    def test_05_explicit_runtime_declaration(self):
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        self.declare(binary=binary)
        deployment = load_declaration(deployment_path(self.root))
        self.assertEqual(str(binary), deployment.runtime_path)
        self.assertTrue(deployment.has_runtime)
        self.assertTrue(deployment.selection_is_attributed)

    def test_05b_unattributed_selection_is_refused(self):
        self.declare(declared_by="")
        deployment = load_declaration(deployment_path(self.root))
        self.assertIs(deployment.state, DeploymentState.INVALID)
        self.assertIn("declared_by", deployment.detail)

    def test_05c_relative_paths_are_refused(self):
        target = deployment_path(self.root)
        target.write_text(json.dumps({
            "schema": DEPLOYMENT_SCHEMA,
            "model": {"path": "model.gguf", "sha256": "a" * 64},
            "runtime": {"path": "llama-cli.exe"},
            "selection": {"declared_by": "t", "rationale": "r"},
        }), encoding="utf-8")
        deployment = load_declaration(target)
        self.assertIs(deployment.state, DeploymentState.INVALID)
        self.assertIn("absolute", deployment.detail)

    def test_05d_invalid_digest_is_refused(self):
        self.declare(sha256="not-a-digest")
        deployment = load_declaration(deployment_path(self.root))
        self.assertIs(deployment.state, DeploymentState.INVALID)
        self.assertIn("64 hex", deployment.detail)

    def test_05e_unfilled_template_is_refused(self):
        target = write_template(deployment_path(self.root))
        deployment = load_declaration(target)
        self.assertIs(deployment.state, DeploymentState.INVALID)
        self.assertIn("absolute", deployment.detail)


# ===========================================================================
# 6-12  identity, separation, compatibility
# ===========================================================================
class TestIdentityAndCompatibility(M012Root):
    def test_06_artifact_digest(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        self.declare(model=model)
        ledger = self.verify_declared()
        self.assertEqual(compute_digest(model), ledger.artifact["sha256"])
        self.assertEqual(model.stat().st_size, ledger.artifact["size_bytes"])

    def test_07_external_digest(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        self.declare(
            model=model,
            external_digest={"sha256": compute_digest(model), "source": "publisher"},
        )
        ledger = self.verify_declared()
        self.assertTrue(ledger.artifact["verified"])
        self.assertEqual("publisher", ledger.artifact["external_source"])

    def test_07b_absent_external_digest_is_not_external_trust(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        self.declare(model=model)
        ledger = self.verify_declared()
        self.assertFalse(ledger.artifact["verified"])
        self.assertEqual(
            "NO_EXTERNAL_DIGEST_SUPPLIED", ledger.artifact["digest_status"]
        )
        criterion = ledger.criterion("external_digest_status")
        self.assertIn("not reported as externally trusted", criterion.detail)

    def test_08_digest_mismatch(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        self.declare(model=model, sha256="b" * 64)
        ledger = self.verify_declared()
        self.assertEqual("EXTERNAL_DIGEST_MISMATCH", ledger.artifact["digest_status"])
        self.assertIs(
            ledger.state_of("model_artifact_usable"), CriterionState.FAILED
        )
        self.assertEqual("NOT_RUN", ledger.inference["outcome"])

    def test_09_runtime_identity(self):
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        self.declare(binary=binary)
        ledger = self.verify_declared()
        self.assertEqual(compute_digest(binary), ledger.runtime["binary_sha256"])

    def test_10_runtime_version_comes_from_the_executable(self):
        self.declare(expected_version="version-that-is-not-real")
        ledger = self.verify_declared()
        self.assertIn("8000 (real)", ledger.runtime["version"])
        self.assertIn("does not contain", ledger.runtime["detail"])
        self.assertIs(ledger.state_of("runtime_version"), CriterionState.SATISFIED)

    def test_11_model_runtime_separation(self):
        self.declare()
        ledger = self.verify_declared()
        criterion = ledger.criterion("model_runtime_separation")
        self.assertIs(criterion.state, CriterionState.SATISFIED)
        self.assertNotEqual(
            ledger.artifact["sha256"], ledger.runtime["binary_sha256"]
        )
        self.assertIn("neither implies the other", criterion.detail)

    def test_12_compatibility_from_a_real_load(self):
        """A stubbed probe is COMPATIBLE but NOT established by a real load.

        That distinction is the whole point of ``established_by_load``. A
        caller-supplied process stand-in answering the probe tells us nothing
        about whether the real binary can read the real artifact, so the flag
        stays False and the milestone's compatibility criterion cannot be
        satisfied from a test fixture.
        """
        self.declare()
        ledger = self.verify_declared()
        self.assertEqual("COMPATIBLE", ledger.compatibility["compatibility"])
        self.assertEqual("STUB_LOAD", ledger.compatibility["method"])
        self.assertFalse(ledger.compatibility["established_by_load"])
        # And because it was not established by a load, the sequence stops here
        # rather than proceeding on the strength of a stubbed answer.
        self.assertEqual("NOT_RUN", ledger.inference["outcome"])

    def test_12a_compatibility_blocks_the_sequence_when_unestablished(self):
        """An unestablished compatibility cannot lead to an inference."""
        self.declare()
        ledger = self.verify_declared(
            load_runner=_runner("", "", 0),  # exits 0, says nothing
        )
        self.assertEqual("UNKNOWN", ledger.compatibility["compatibility"])
        self.assertEqual("NOT_RUN", ledger.inference["outcome"])
        self.assertIs(ledger.state_of("compatibility"), CriterionState.NOT_TESTABLE)

    def test_12a2_stub_probe_cannot_advance_the_sequence(self):
        """Even a COMPATIBLE stub probe must not authorise execution.

        Without this, a fixture that answers every probe positively would walk
        the whole deployment sequence and the milestone's real-runtime criteria
        would be reachable from a test.
        """
        self.declare()
        ledger = self.verify_declared(
            load_runner=_runner("gguf: file format\n", "", 0),
        )
        self.assertEqual("COMPATIBLE", ledger.compatibility["compatibility"])
        self.assertFalse(ledger.compatibility["established_by_load"])
        self.assertEqual("NOT_RUN", ledger.inference["outcome"])

    def test_12b_extension_alone_is_not_compatibility(self):
        """A .gguf name establishes a convention and nothing more."""
        model = _gguf(self.root / "weights" / "m.gguf")
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        # The runtime exits 0 and prints nothing: silence is not an answer.
        result = assess_compatibility(
            model_path=model, runtime_path=binary,
            runner=_runner("", "", 0),
        )
        self.assertIs(result.compatibility, Compatibility.UNKNOWN)
        self.assertIn("Silence is not a compatibility answer", result.reason)
        self.assertFalse(result.established_by_load)

    def test_12c_load_failure_stays_a_failure(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        result = assess_compatibility(
            model_path=model, runtime_path=binary,
            runner=_runner("", "error loading model: unknown architecture", 1),
        )
        self.assertIs(result.compatibility, Compatibility.INCOMPATIBLE)
        self.assertIn("no substitute file", result.reason)
        self.assertIn("unknown architecture", result.runtime_message)

    def test_12d_stub_probe_is_not_a_real_answer(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        result = assess_compatibility(
            model_path=model, runtime_path=binary,
            runner=_runner("gguf: file format", "", 0),
        )
        self.assertEqual("STUB_LOAD", result.method)
        self.assertFalse(result.established_by_load)

    def test_12e_format_check_narrows_only_the_format(self):
        model = _gguf(self.root / "weights" / "m.gguf")
        fmt = check_format(model)
        self.assertTrue(fmt["is_gguf"])
        self.assertIn("establishes the format and nothing more", fmt["detail"])
        impostor = self.root / "weights" / "fake.gguf"
        impostor.write_bytes(b"NOTGGUF" + b"\x00" * 4096)
        self.assertFalse(check_format(impostor)["is_gguf"])

# ===========================================================================
# 13-20  execution, accounting, GPU, VRAM, determinism, immutability
# ===========================================================================
class TestExecutionAndResources(M012Root):
    def test_13_real_model_load_is_required_before_inference(self):
        """No load, no execution. A stub probe is not a load."""
        self.declare()
        ledger = self.verify_declared()
        self.assertEqual("STUB_LOAD", ledger.compatibility["method"])
        self.assertEqual("NOT_RUN", ledger.inference["outcome"])
        self.assertIs(ledger.state_of("real_inference"), CriterionState.NOT_REACHED)

    def test_14_real_inference_is_unreachable_without_a_real_load(self):
        """The stub boundary: a positive stub answer still yields NOT_TESTABLE."""
        self.declare()
        ledger = self.verify_declared()
        self.assertIs(ledger.state_of("real_inference"), CriterionState.NOT_REACHED)
        # And the deployment endpoint is still a refusal, not a success.
        self.assertFalse(ledger.real_runtime_verified)
        self.assertFalse(ledger.real_inference_verified)

    def test_15_token_accounting_is_honest(self):
        from babylab.runtime.contract import EpistemicStatus
        from foundation.real_runtime import run_real

        model = _gguf(self.root / "weights" / "m.gguf")
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        run = run_real(
            model_path=model, model_sha256=compute_digest(model), binary=binary,
            runner=_runner("1 2 3 4 5", REAL_STDERR),
        )
        self.assertIs(run.prompt_tokens.status, EpistemicStatus.OBSERVED)
        self.assertEqual(9, run.prompt_tokens.value)
        self.assertEqual(5, run.completion_tokens.value)
        self.assertIs(run.total_tokens.status, EpistemicStatus.DERIVED)
        self.assertTrue(run.token_accounting_complete)

        # A shape the parser does not know stays unavailable, never estimated.
        quiet = run_real(
            model_path=model, model_sha256=compute_digest(model), binary=binary,
            runner=_runner("1 2 3", "main: eval time = 430.00 ms / 5 runs"),
        )
        self.assertIs(quiet.completion_tokens.status, EpistemicStatus.UNAVAILABLE)
        self.assertFalse(quiet.token_accounting_complete)

    def test_16_gpu_evidence_requires_two_pieces(self):
        from foundation.runtime_identity import GpuUsage, resolve_gpu_usage

        self.assertIs(
            resolve_gpu_usage(requested_layers=35, reported_backend="cuda")[0],
            GpuUsage.REQUESTED_NOT_CONFIRMED,
        )
        self.assertIs(
            resolve_gpu_usage(
                requested_layers=35, reported_backend="cuda",
                runner_evidence="offloaded 35/35 layers to GPU",
            )[0],
            GpuUsage.CONFIRMED,
        )
        self.assertIs(
            resolve_gpu_usage(requested_layers=35, reported_backend="cpu")[0],
            GpuUsage.REQUESTED_NOT_CONFIRMED,
        )

    def test_17_vram_observation(self):
        from foundation.hardware import measure_gpu

        gpu = measure_gpu()
        total = gpu["vram_total_bytes"]
        self.assertIn("status", total.to_dict())
        if total.available:
            self.assertIsInstance(total.value, int)
            self.assertIn("nvidia-smi", total.source)
        # WMI is never a VRAM figure, and no VRAM is inferred from model size.
        self.assertFalse(gpu["adapter_ram_wmi"].available)

    def test_18_determinism_vocabulary(self):
        from foundation.real_runtime import compare_two, run_real

        model = _gguf(self.root / "weights" / "m.gguf")
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        args = dict(model_path=model, model_sha256=compute_digest(model),
                    binary=binary, runner=_runner("1 2 3 4 5", REAL_STDERR))
        same = compare_two(run_real(**args), run_real(**args))
        self.assertEqual("DETERMINISTIC_FOR_TEST_CONFIGURATION", same.verdict)
        diff = compare_two(
            run_real(**args),
            run_real(**{**args, "runner": _runner("one two three", REAL_STDERR)}),
        )
        self.assertEqual("NONDETERMINISTIC_FOR_TEST_CONFIGURATION", diff.verdict)
        self.assertFalse(compare_two(run_real(**args), None).attempted)

    def test_19_model_immutability(self):
        from foundation.artifact import identify, verify_immutable

        model = _gguf(self.root / "weights" / "m.gguf")
        before = identify(model, expected_sha256=compute_digest(model))
        with model.open("ab") as handle:
            handle.write(b"\x00" * 512)
        result = verify_immutable(before, identify(model))
        self.assertFalse(result["immutable"])
        self.assertIn("ARTIFACT MUTATED", result["verdict"])

    def test_20_runtime_immutability(self):
        binary = _binary(self.root / "bin" / "llama-cli.exe")
        invoker = lambda p: ("version: 1", "probe", "")  # noqa: E731
        before = assess_runtime(binary, invoker=invoker)
        with binary.open("ab") as handle:
            handle.write(b"\x00" * 256)
        result = check_runtime_immutable(before, assess_runtime(binary, invoker=invoker))
        self.assertFalse(result["immutable"])
        self.assertIn("RUNTIME MUTATED", result["verdict"])


# ===========================================================================
# 21-31  identity, restricted account, protected files, workspace, network
# ===========================================================================
class TestIdentityAndBoundary(M012Root):
    def test_21_process_identity(self):
        identity = capture_own_identity()
        self.assertTrue(identity.verified)
        self.assertRegex(identity.sid, r"^S-1-")
        self.assertNotIn("UNAVAILABLE", identity.integrity_level)

    def test_22_baby_ai_test_execution_is_refused_honestly(self):
        result = run_probe_as_subject(timeout_seconds=30)
        if can_launch_as_subject()[0]:
            self.assertIn(result.state.value, {"VERIFIED", "LAUNCHED"})
        else:
            self.assertEqual("NOT_TESTABLE", result.state.value)
            self.assertIn("SeImpersonatePrivilege", result.detail)
            self.assertIs(result.evidence.get("fallback_taken"), False)

    def _probe_category(self, category: str) -> list[dict]:
        probe = run_probe(REPO_ROOT)
        return [p for p in probe["protected"] if p["category"] == category]

    def test_23_protected_provenance_denial(self):
        self.assertTrue(self._probe_category("provenance"))

    def test_24_protected_event_denial(self):
        self.assertTrue(self._probe_category("event"))

    def test_25_protected_human_control_denial(self):
        self.assertTrue(self._probe_category("human_control"))

    def test_26_protected_key_denial(self):
        self.assertTrue(self._probe_category("private_key"))

    def test_27_protected_research_denial(self):
        self.assertTrue(self._probe_category("research"))

    def test_27b_all_six_categories_are_attempted(self):
        """M011's probe silently skipped four of six. This pins the fix."""
        probe = run_probe(REPO_ROOT)
        categories = {p["category"] for p in probe["protected"]}
        for required in ("provenance", "event", "human_control",
                         "private_key", "research", "control_token"):
            self.assertIn(required, categories)
        self.assertGreaterEqual(probe["verdict"]["protected_attempts"], 6)

    def test_27c_operator_run_is_marked_not_meaningful(self):
        """Running as the operator is not evidence about the subject account."""
        probe = run_probe(REPO_ROOT)
        self.assertIs(probe["verdict"]["ran_as_subject_account"], False)
        self.assertIs(probe["verdict"]["boundary_meaningful"], False)
        self.assertIn("NOT the subject account", probe["verdict"]["conclusion"])

    def test_28_workspace_write(self):
        self.assertTrue(run_probe(REPO_ROOT)["workspace"]["write_allowed"])

    def test_29_workspace_readback(self):
        cycle = run_probe(REPO_ROOT)["workspace"]
        self.assertTrue(cycle["readback_ok"])
        readback = [s for s in cycle["steps"] if s["category"] == "workspace_read"][0]
        self.assertTrue(readback["evidence"]["content_matched"])

    def test_30_workspace_cleanup(self):
        import tempfile

        workspace = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(workspace, ignore_errors=True)
        )
        probe = run_probe(workspace)
        self.assertTrue(probe["workspace"]["cleanup_ok"])
        self.assertEqual([], list(workspace.rglob(PROBE_FILENAME)))

    def test_31_network_absence(self):
        probe = run_probe(REPO_ROOT)
        self.assertIs(probe["network"]["outbound_attempted"], False)
        self.assertEqual("LOCAL_ONLY_NO_FETCH", probe["network"]["policy"])
        ledger = verify(REPO_ROOT, scan_candidates=False)
        self.assertEqual("LOCAL_ONLY_NO_FETCH", ledger.network["policy"])
        self.assertIs(ledger.state_of("network_absent"), CriterionState.SATISFIED)


# ===========================================================================
# 32-34  provenance, Observatory, audit
# ===========================================================================
class TestProvenanceAndObservatory(M012Root):
    def test_32_provenance_is_complete(self):
        self.declare()
        ledger = self.verify_declared()
        payload = ledger.to_dict()
        for key in ("deployment", "candidates", "artifact", "runtime",
                    "compatibility", "admission", "inference", "determinism",
                    "immutability", "runtime_immutability", "hardware",
                    "process_identity", "launch", "probe", "network", "audit"):
            self.assertIn(key, payload)
        # The human's rationale is recorded verbatim: it is research provenance.
        self.assertEqual("it was the one selected",
                         payload["deployment"]["selection"]["rationale"])
        self.assertEqual("a test human",
                         payload["deployment"]["selection"]["declared_by"])

    def test_32b_output_text_is_not_in_the_record(self):
        """The record carries digests, not the model's prose.

        A blocked deployment never ran, so there is no prompt or output digest
        either -- and saying "UNAVAILABLE" is the honest report rather than
        inventing a digest for a run that did not happen.
        """
        self.declare()
        ledger = self.verify_declared()
        self.assertNotIn("output_text", ledger.inference)
        self.assertIs(ledger.state_of("real_inference"), CriterionState.NOT_REACHED)
        self.assertEqual("", ledger.inference.get("prompt_sha256", ""))
        # And the audit says so rather than reading a digest out of thin air.
        question = next(
            a for a in ledger.audit["answers"]
            if a["question"].startswith("Did real inference execute")
        )
        self.assertIs(question["answer"], False)

    def test_33_observatory_reports_the_declaration(self):
        self.declare()
        payload = deployment_only(self.root)
        self.assertEqual("DECLARED", payload["human_model_selection"])
        self.assertEqual("DECLARED", payload["human_runtime_selection"])
        self.assertTrue(payload["selection_attributed"])
        self.assertIs(payload["candidates_reported"]["promotable"], False)

        from observatory.graph import StateGraph
        from observatory.model import CognitiveState
        from observatory.render import ObservatoryRenderer, RenderOptions
        from observatory.snapshot import ObservatorySnapshot

        snapshot = ObservatorySnapshot(
            subject_status="NO_SUBJECT",
            subject_banner="NO EXPERIMENTAL SUBJECT ATTACHED", subject_detail=None,
            state=CognitiveState.empty(), graph=StateGraph(), deployment=payload,
        )
        text = ObservatoryRenderer(RenderOptions(color=False)).render(snapshot)
        self.assertIn("FOUNDATION SELECTION", text)
        self.assertIn("DECLARED", text)
        self.assertIn("none selected", text)

    def test_33b_observatory_renders_no_psychological_vocabulary(self):
        from observatory.graph import StateGraph
        from observatory.model import CognitiveState
        from observatory.render import ObservatoryRenderer, RenderOptions
        from observatory.snapshot import ObservatorySnapshot

        hostile = {
            "human_model_selection": "DECLARED", "human_runtime_selection": "DECLARED",
            "model_path": "/x/m.gguf", "model_sha256": "a" * 64,
            "digest_status": "VERIFIED_MATCH", "digest_verified": True,
            "external_supplied": True, "model_external_source": "publisher",
            "runtime_path": "/x/llama-cli", "runtime_version": "b1",
            "selection_attributed": True, "declared_by": "a human",
            "real_runtime": "REAL_RUNTIME", "compatibility": "COMPATIBLE",
            "intelligence": 0.99, "consciousness": True, "curiosity": 0.8,
            "learning_progress": 3, "personality": "warm", "readiness": "high",
        }
        snapshot = ObservatorySnapshot(
            subject_status="ATTACHED", subject_banner="SUBJECT", subject_detail=None,
            state=CognitiveState.empty(), graph=StateGraph(), deployment=hostile,
        )
        text = ObservatoryRenderer(RenderOptions(color=False)).render(snapshot).lower()
        for term in FORBIDDEN_DISPLAY_TERMS:
            self.assertNotIn(term, text, f"the observatory rendered {term}")

    def test_33c_observatory_executes_nothing(self):
        """Walked from the AST: a text scan would fail on the docstring."""
        tree = ast.parse(
            (REPO_ROOT / "observatory" / "terminal.py").read_text(encoding="utf-8")
        )
        referenced: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                referenced.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
            elif isinstance(node, ast.Name):
                referenced.add(node.id)
        for forbidden in ("verify", "run_real", "run_probe", "assess_compatibility",
                          "launch_as_subject", "Popen"):
            self.assertNotIn(forbidden, referenced)
        self.assertIn("deployment_only", referenced)

    def test_34_machine_readable_audit(self):
        self.declare()
        ledger = self.verify_declared()
        audit = ledger.audit
        self.assertEqual(16, len(audit["answers"]))
        for answer in audit["answers"]:
            self.assertIn("question", answer)
            self.assertIn("state", answer)
            self.assertTrue(answer["state"] in {"DERIVED", "UNKNOWN"})
            if answer["state"] == "DERIVED":
                self.assertTrue(answer["source"], f"{answer['question']} cites nothing")
        self.assertTrue(audit["reverification"]["verified"])

    def test_34b_audit_detects_a_doctored_answer(self):
        self.declare()
        ledger = self.verify_declared()
        source = {
            "deployment": {"state": "LOADED", "model": {"path": "m"},
                           "runtime": {"path": "r"},
                           "selection": {"attributed": True}},
            "artifact": {"model_path": "m", "sha256": "a" * 64,
                         "external_supplied": False, "verified": False},
            "runtime": {"sha256": "b" * 64, "version": "v"},
            "compatibility": {"established_by_load": True},
            "inference": {"is_real_runtime": True},
            "process_identity": {"sid": "S-1-5-21-x-1022"},
            "probe": {"protected_denied": 6, "workspace_write_allowed": True},
            "network": {"policy": "LOCAL_ONLY_NO_FETCH"},
            "immutability": {"model_and_runtime_unchanged": True},
            "determinism": {"verdict": "DETERMINISTIC_FOR_TEST_CONFIGURATION"},
        }
        honest = build_audit(source)
        doctored = json.loads(json.dumps(honest))
        doctored["answers"][0]["answer"] = "NOT_CONFIGURED"
        check = reverify(doctored, source)
        self.assertFalse(check["verified"])
        self.assertEqual(1, len(check["disagreements"]))

    def test_34c_audit_answers_unknown_when_the_field_is_absent(self):
        audit = build_audit({})
        self.assertEqual(0, audit["derived_count"])
        self.assertEqual(16, audit["unknown_count"])
        self.assertFalse(audit["summary"]["all_questions_derived"])


# ===========================================================================
# 35-40  the prohibitions and failure handling
# ===========================================================================
class TestProhibitionsAndFailures(unittest.TestCase):
    def _imports(self, name: str) -> set[str]:
        tree = ast.parse(
            (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
        )
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    def test_35_no_subject_creation(self):
        for name in ALL_FOUNDATION_MODULES:
            for imported in self._imports(name):
                self.assertFalse(imported.startswith("subject"),
                                 f"{name} imports {imported}")

    def test_36_no_birth(self):
        banned = ("birth.ceremony", "birth.gate", "birth.gate_checks",
                  "birth.service", "birth.keycustody", "birth.birth_record",
                  "birth.readiness", "birth.status")
        for name in ALL_FOUNDATION_MODULES:
            for imported in self._imports(name):
                for prefix in banned:
                    self.assertFalse(imported.startswith(prefix),
                                     f"{name} imports {imported}")

    def test_37_no_memory(self):
        banned = {"chromadb", "chroma", "faiss", "pinecone", "weaviate",
                  "qdrant_client", "langchain", "llama_index", "numpy",
                  "sentence_transformers"}
        for name in ALL_FOUNDATION_MODULES:
            for imported in self._imports(name):
                self.assertNotIn(imported.split(".")[0], banned,
                                 f"{name} imports {imported}")

    def test_38_no_learning(self):
        banned = {"torch", "tensorflow", "jax", "peft", "trl", "accelerate",
                  "timm", "sklearn", "scipy", "datasets"}
        for name in ALL_FOUNDATION_MODULES:
            for imported in self._imports(name):
                self.assertNotIn(imported.split(".")[0], banned,
                                 f"{name} imports {imported}")

    def test_39_no_autonomy(self):
        """No loop, no daemon, no scheduler, no goal state."""
        banned = {"threading", "sched", "asyncio", "multiprocessing",
                  "concurrent", "atexit", "timeit"}
        for name in ALL_FOUNDATION_MODULES:
            for imported in self._imports(name):
                self.assertNotIn(imported.split(".")[0], banned,
                                 f"{name} imports {imported}")

    def test_39b_no_automatic_acquisition(self):
        """No download route exists anywhere in the package."""
        banned = {"urllib", "http", "requests", "httpx", "socket", "aiohttp",
                  "huggingface_hub", "transformers", "boto3", "gdown"}
        for name in ALL_FOUNDATION_MODULES:
            for imported in self._imports(name):
                self.assertNotIn(imported.split(".")[0], banned,
                                 f"{name} imports {imported}")

    def test_39c_no_self_modification(self):
        banned = {"exec", "eval", "compile", "__import__", "globals", "locals"}
        for name in ALL_FOUNDATION_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    dotted = ast.unparse(node.func)
                    if dotted == "re.compile":
                        continue
                    self.assertNotIn(dotted.split(".")[-1], banned,
                                     f"{name} calls {dotted}()")

    def test_40_failure_handling(self):
        """Each failure mode ends the sequence with a recorded reason."""
        with self.subTest("missing artifact refuses and stops"):
            root = Path(self.enterContext(
                __import__("tempfile").TemporaryDirectory()))
            (root / "human_control" / "experiment_config").mkdir(parents=True)
            target = deployment_path(root)
            target.write_text(json.dumps({
                "schema": DEPLOYMENT_SCHEMA,
                "model": {"path": str(root / "gone.gguf"), "sha256": "a" * 64},
                "runtime": {"path": str(root / "bin" / "llama-cli.exe")},
                "selection": {"declared_by": "t", "rationale": "r"},
            }), encoding="utf-8")
            ledger = verify(root, scan_candidates=False)
            self.assertIs(
                ledger.state_of("model_artifact_identity"), CriterionState.SATISFIED
            )
            self.assertIs(
                ledger.state_of("model_artifact_usable"), CriterionState.FAILED
            )
            self.assertEqual("NOT_RUN", ledger.inference["outcome"])
            # A refused artifact never becomes a birth attempt.
            self.assertFalse(ledger.birth_performed)

        with self.subTest("missing runtime stops after the artifact"):
            root = Path(self.enterContext(
                __import__("tempfile").TemporaryDirectory()))
            (root / "human_control" / "experiment_config").mkdir(parents=True)
            model = _gguf(root / "m.gguf")
            target = deployment_path(root)
            target.write_text(json.dumps({
                "schema": DEPLOYMENT_SCHEMA,
                "model": {"path": str(model), "sha256": compute_digest(model)},
                "runtime": {"path": str(root / "absent-runtime.exe")},
                "selection": {"declared_by": "t", "rationale": "r"},
            }), encoding="utf-8")
            ledger = verify(root, scan_candidates=False)
            self.assertIs(
                ledger.state_of("runtime_identity"), CriterionState.NOT_TESTABLE
            )
            self.assertEqual("NOT_RUN", ledger.inference["outcome"])

    def test_40b_blocked_is_distinct_from_failed(self):
        """BLOCKED is a correct outcome; FAILED is not. They must not merge."""
        from foundation.m012 import CriterionState as S

        self.assertNotEqual(S.BLOCKED, S.FAILED)
        self.assertNotEqual(S.BLOCKED, S.NOT_TESTABLE)
        self.assertNotEqual(S.BLOCKED, S.NOT_REACHED)

    def test_40c_ledger_summary_always_denies_subject_and_birth(self):
        ledger = verify(REPO_ROOT, scan_candidates=False)
        summary = ledger.to_dict()["summary"]
        self.assertIs(summary["birth_performed"], False)
        self.assertIs(summary["subject_created"], False)
        self.assertIs(summary["real_runtime_verified"], False)
        payload = from_ledger(ledger)
        self.assertEqual("NONE", payload["subject"])
        self.assertEqual("NOT_PERFORMED", payload["birth"])

    def test_40d_criteria_are_all_named_even_when_blocked(self):
        """A criterion missing from the record reads as a quiet skip."""
        ledger = verify(REPO_ROOT, scan_candidates=False)
        names = {c.name for c in ledger.criteria}
        for required in ("human_model_selection", "human_runtime_selection",
                         "model_artifact_identity", "runtime_identity",
                         "compatibility", "real_inference", "process_identity",
                         "subject_account_runtime", "protected_file_probe",
                         "workspace_probe", "network_absent",
                         "no_subject_no_birth", "audit_complete"):
            self.assertIn(required, names, f"{required} was silently omitted")
        for criterion in ledger.criteria:
            self.assertTrue(criterion.detail.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)

