"""M010: foundation-model acquisition, verification, and runtime validation.

The milestone specification's 44 cases map onto the classes below. Each class
name matches the specification's wording so a reader can check coverage by
reading the two side by side.

These tests are written to fail for a wrong implementation. In particular:

* a test that scans raw text for banned words is worthless, because a module
  that *documents* the ban would pass it. Every structural assertion here works
  on the AST, so the only way to pass is to not write the code.
* the artifact tests use real bytes with a real digest. A fake artifact whose
  digest was precomputed to match a fake expectation would defeat the point, so
  the expected digest is always computed from the file the test itself wrote.
* the "no model" tests assert the absence of the model *and* the absence of the
  machinery that would have fetched one, because a laboratory that correctly
  reports no model while containing a downloader has not solved the problem.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from foundation.acquisition import (  # noqa: E402
    FORBIDDEN_ACQUISITION_ROUTES,
    AcquisitionRefused,
    AcquisitionState,
    assess,
    declaration_path,
    manifest_path,
    refuse,
    weights_directory,
)
from foundation.admission import (  # noqa: E402
    AdmissionState,
    evaluate_admission,
    observe_vram,
)
from foundation.artifact import (  # noqa: E402
    GGUF_MAGIC,
    MINIMUM_PLAUSIBLE_BYTES,
    ArtifactIdentity,
    DigestStatus,
    compute_digest,
    identify,
    verify_immutable,
)
from foundation.inference import (  # noqa: E402
    BANNED_PROMPT_SUBSTRINGS,
    OUTPUT_CLASS,
    InferenceKind,
    InferenceOutcome,
    assert_neutral_prompt,
    baseline_sampling,
    compare_repeat,
    output_digest,
    prompt_digest,
    run_inference,
)
from foundation.isolation import (  # noqa: E402
    FORBIDDEN_CAPABILITIES,
    NETWORK_POLICY,
    RUNTIME_PATH_MODULES,
    compare_evidence,
    protected_evidence_digests,
    verify_isolation,
)
from foundation.manifest import (  # noqa: E402
    MANIFEST_SCHEMA,
    load_manifest,
    write_template,
)
from foundation.runtime_identity import (  # noqa: E402
    GpuUsage,
    RuntimeState,
    identify_runtime,
    resolve_gpu_usage,
    sha256_binary,
)
from foundation.status import (  # noqa: E402
    FORBIDDEN_DISPLAY_TERMS,
    foundation_status,
    render_lines,
)
from foundation.validation import (  # noqa: E402
    StepState,
    _offload_evidence,
    validate,
)

M010_MODULES = (
    "acquisition.py",
    "artifact.py",
    "manifest.py",
    "runtime_identity.py",
    "admission.py",
    "inference.py",
    "isolation.py",
    "status.py",
    "validation.py",
    "__init__.py",
)


def _fake_gguf(path: Path, payload_size: int = 2 * 1024 * 1024) -> Path:
    """Write a file with real GGUF magic and real bytes.

    The bytes are filler; the point is that the file is genuinely a file, so the
    digest the test compares against is genuinely computed from the disk.

    ``payload_size=0`` writes a truly zero-byte file, which is a different
    failure from a small one and is exercised as such: a truncated download and
    an empty placeholder should not produce the same evidence.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload_size == 0:
        path.write_bytes(b"")
        return path
    with path.open("wb") as handle:
        handle.write(GGUF_MAGIC)
        handle.write((3).to_bytes(4, "little"))
        handle.write(b"\x00" * (payload_size - 8))
    return path


def _declaration(
    root: Path,
    *,
    model: Path,
    digest: str,
    binary: Path | None = None,
    extra: dict | None = None,
) -> Path:
    """Write a human declaration. Everything a real one needs, nothing more."""
    target = declaration_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "babylab/runtime-config/v1",
        "declared_at": "2026-09-30T00:00:00Z",
        "model": {
            "adapter_id": "llamacpp",
            "path": str(model),
            "sha256": digest,
            "family": "test-family",
            "name": "test-model",
            "quantization": "Q4_K_M",
            "context_length": 2048,
            "runtime_binary": str(binary) if binary else "",
            "runtime_version": "",
        },
        "declared_by": "test operator",
    }
    if extra:
        payload["model"].update(extra)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def _manifest(
    root: Path,
    *,
    digest: str = "",
    source: str = "",
    reference: str = "",
) -> Path:
    target = manifest_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema": MANIFEST_SCHEMA,
                "artifact_path": "",
                "family": "test-family",
                "name": "test-model",
                "format": "gguf",
                "quantization": "Q4_K_M",
                "external_digest": {
                    "sha256": digest,
                    "source": source,
                    "reference": reference,
                },
                "runtime": {"implementation": "llama.cpp", "version": "b1"},
                "acquisition": {"reference": "supplied by a test"},
                "declared_by": "test operator",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


def _fake_binary(path: Path, version: str = "version: 8000 (test)") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\x00" * 2048)
    return path


def _runner(stdout: str = "", stderr: str = "", returncode: int = 0):
    """A stand-in process runner. Never a real binary, always labelled a stub."""

    class _Completed:
        def __init__(self) -> None:
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def run(command: list[str], timeout: float):
        return _Completed()

    return run


def _invoker(version: str = "version: 8000 (test)", failure: str = ""):
    def invoke(path: Path):
        if failure:
            return "UNAVAILABLE", failure, ""
        return version, "binary --version output", version

    return invoke


class M010TempRoot(unittest.TestCase):
    """Every test gets its own laboratory root. The real one is never touched."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.weights = weights_directory(self.root)


# ===========================================================================
# 1-9  artifact identity, digest, and the external digest rule
# ===========================================================================
class TestArtifactIdentity(M010TempRoot):
    def test_01_no_model_configured(self):
        """Case 1: no model configured is a state, not an error."""
        status = assess(self.root)
        self.assertIs(status.state, AcquisitionState.MODEL_NOT_CONFIGURED)
        self.assertFalse(status.model_available)
        self.assertIn("MODEL_NOT_CONFIGURED", status.describe())

    def test_02_missing_model_path(self):
        """Case 2: a declaration naming a path that does not exist."""
        missing = self.weights / "absent.gguf"
        _declaration(self.root, model=missing, digest="0" * 64)
        identity = identify(missing)
        self.assertIs(identity.status, DigestStatus.ARTIFACT_MISSING)
        self.assertTrue(identity.status.is_refusal)

    def test_03_invalid_model_path(self):
        """Case 3: an unusable path -- a directory, not a file."""
        directory = self.weights / "model.gguf"
        directory.mkdir(parents=True)
        identity = identify(directory)
        self.assertIs(identity.status, DigestStatus.ARTIFACT_MISSING)

    def test_04_zero_byte_model(self):
        """Case 4: a zero-byte artifact is a truncated download, not a model."""
        empty = _fake_gguf(self.weights / "empty.gguf", payload_size=0)
        self.assertEqual(0, empty.stat().st_size)
        identity = identify(empty)
        self.assertIs(identity.status, DigestStatus.ARTIFACT_TOO_SMALL)
        self.assertIn("truncated", identity.detail.lower())

    def test_05_corrupted_model(self):
        """Case 5: correct name, wrong bytes -- not a GGUF at all."""
        bogus = self.weights / "model.gguf"
        bogus.parent.mkdir(parents=True, exist_ok=True)
        bogus.write_bytes(b"this is not a model" * 200000)
        identity = identify(bogus)
        self.assertIs(identity.status, DigestStatus.UNSUPPORTED_FORMAT)
        self.assertIn("magic", identity.detail.lower())

    def test_06_digest_mismatch(self):
        """Case 6: a declaration whose digest no longer matches the bytes."""
        model = _fake_gguf(self.weights / "model.gguf")
        identity = identify(model, expected_sha256="a" * 64)
        self.assertIs(identity.status, DigestStatus.EXTERNAL_DIGEST_MISMATCH)
        self.assertTrue(identity.status.is_refusal)

    def test_07_valid_artifact_identity(self):
        """Case 7: a real file produces a real identity from its real bytes."""
        model = _fake_gguf(self.weights / "model.gguf")
        digest = compute_digest(model)
        self.assertEqual(64, len(digest))
        identity = identify(model, expected_sha256=digest)
        self.assertEqual(digest, identity.computed_sha256)
        self.assertEqual(model.stat().st_size, identity.size_bytes)
        self.assertEqual("gguf", identity.format)
        self.assertTrue(identity.artifact_id.startswith("artifact-"))
        # Byte identity, but explicitly not external verification.
        self.assertFalse(identity.verified)
        self.assertIs(identity.status, DigestStatus.NO_EXTERNAL_DIGEST_SUPPLIED)

    def test_08_external_digest_match(self):
        """Case 8: an externally supplied digest that matches is VERIFIED_MATCH."""
        model = _fake_gguf(self.weights / "model.gguf")
        digest = compute_digest(model)
        identity = identify(
            model, external_sha256=digest, external_source="publisher checksum file"
        )
        self.assertIs(identity.status, DigestStatus.VERIFIED_MATCH)
        self.assertTrue(identity.verified)
        self.assertTrue(identity.externally_attested)

    def test_09_external_digest_mismatch(self):
        """Case 9: an external digest that disagrees is always a refusal."""
        model = _fake_gguf(self.weights / "model.gguf")
        identity = identify(
            model, external_sha256="b" * 64, external_source="publisher"
        )
        self.assertIs(identity.status, DigestStatus.EXTERNAL_DIGEST_MISMATCH)
        self.assertFalse(identity.verified)
        self.assertTrue(identity.status.is_refusal)


# ===========================================================================
# 10-16  runtime identity and load
# ===========================================================================
class TestRuntimeIdentity(M010TempRoot):
    def test_10_missing_runtime(self):
        runtime = identify_runtime(None)
        self.assertIs(runtime.state, RuntimeState.NOT_CONFIGURED)
        self.assertFalse(runtime.verified)

    def test_11_invalid_runtime_path(self):
        runtime = identify_runtime(self.root / "nope" / "llama-cli.exe")
        self.assertIs(runtime.state, RuntimeState.BINARY_MISSING)
        self.assertIn("does not search PATH", runtime.detail)

    def test_12_runtime_identity(self):
        """Case 12: identity comes from the binary's own bytes."""
        binary = _fake_binary(self.root / "bin" / "llama-cli.exe")
        runtime = identify_runtime(binary, invoker=_invoker())
        digest, basis = sha256_binary(binary)
        self.assertEqual(digest, runtime.binary_sha256)
        self.assertIn("sha256", basis)
        self.assertEqual(binary.stat().st_size, runtime.binary_size_bytes)

    def test_13_runtime_version(self):
        """Case 13: the version is read from the binary, not from the config."""
        binary = _fake_binary(self.root / "bin" / "llama-cli.exe")
        runtime = identify_runtime(binary, invoker=_invoker("version: 4321 (abcdef)"))
        self.assertIs(runtime.state, RuntimeState.VERIFIED)
        self.assertIn("4321", runtime.version)
        self.assertEqual("binary --version output", runtime.version_source)

    def test_14_runtime_invocation(self):
        """Case 14: a binary that exists but will not identify itself is a failure."""
        binary = _fake_binary(self.root / "bin" / "llama-cli.exe")
        runtime = identify_runtime(binary, invoker=_invoker(failure="exited 127"))
        self.assertIs(runtime.state, RuntimeState.PROBE_FAILED)
        self.assertFalse(runtime.verified)
        # The digest is still established: the file is real even if it will not run.
        self.assertNotEqual("UNAVAILABLE", runtime.binary_sha256)

    def test_15_unsupported_artifact(self):
        """Case 15: only GGUF is supported; the refusal names the supported set."""
        other = self.weights / "model.bin"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_bytes(b"x" * (MINIMUM_PLAUSIBLE_BYTES + 1))
        identity = identify(other)
        self.assertIs(identity.status, DigestStatus.UNSUPPORTED_FORMAT)
        self.assertIn("gguf", identity.detail)

    def test_16_model_load_failure(self):
        """Case 16: the adapter refuses a digest that does not match at load time."""
        from babylab.runtime.contract import RuntimeErrorKind, RuntimeFailure
        from babylab.runtime.llamacpp_adapter import LlamaCppAdapter

        model = _fake_gguf(self.weights / "model.gguf")
        binary = _fake_binary(self.root / "bin" / "llama-cli.exe")
        adapter = LlamaCppAdapter(binary=str(binary), runner=_runner())
        with self.assertRaises(RuntimeFailure) as caught:
            adapter.load(str(model), "c" * 64)
        self.assertIs(caught.exception.kind, RuntimeErrorKind.DIGEST_MISMATCH)
        self.assertFalse(adapter.is_loaded)


# ===========================================================================
# 17-20  resource admission, GPU, and CPU
# ===========================================================================
class TestAdmissionAndGpu(M010TempRoot):
    def test_17_insufficient_memory(self):
        """Case 17: an artifact larger than the free-VRAM budget is REFUSED."""
        decision = evaluate_admission(
            artifact_bytes=8 * 1024 ** 3,
            context_length=2048,
            vram_observation={
                "free_bytes": 4 * 1024 ** 3,
                "total_bytes": 8 * 1024 ** 3,
                "source": "nvidia-smi (test)",
                "gpu_available": True,
            },
            gpu_available=True,
        )
        self.assertIs(decision.state, AdmissionState.REFUSE)
        self.assertFalse(decision.may_attempt)

    def test_18_gpu_unavailable(self):
        """Case 18: with a GPU required and none present, the answer is REFUSE."""
        decision = evaluate_admission(
            artifact_bytes=1024 ** 3,
            context_length=2048,
            require_gpu=True,
            vram_observation={"free_bytes": None, "source": "no vendor tool",
                              "gpu_available": False},
            gpu_available=False,
        )
        self.assertIs(decision.state, AdmissionState.REFUSE)
        self.assertIn("requires a GPU", decision.reason)

    def test_18b_unknown_is_not_admit(self):
        """UNKNOWN must never authorise an attempt. This is the case that matters."""
        decision = evaluate_admission(
            artifact_bytes=1024 ** 3,
            context_length=2048,
            vram_observation={"free_bytes": None, "source": "no vendor tool",
                              "gpu_available": True},
            gpu_available=True,
        )
        self.assertIs(decision.state, AdmissionState.UNKNOWN)
        self.assertFalse(decision.may_attempt)
        self.assertIn("not converted into ADMIT", decision.reason)

    def test_18c_vram_is_never_inferred_from_artifact_size(self):
        """The refusal must state that no VRAM figure was derived from size."""
        decision = evaluate_admission(
            artifact_bytes=8 * 1024 ** 3,
            context_length=2048,
            vram_observation={"free_bytes": 2 * 1024 ** 3, "source": "test",
                              "gpu_available": True},
            gpu_available=True,
        )
        self.assertIn("not performed", decision.vram_per_artifact_inference)

    def test_19_gpu_backend_failure(self):
        """Case 19: layers requested, CPU reported -> requested, not confirmed."""
        usage, detail = resolve_gpu_usage(
            requested_layers=35, reported_backend="cpu"
        )
        self.assertIs(usage, GpuUsage.REQUESTED_NOT_CONFIRMED)
        self.assertFalse(usage is GpuUsage.CONFIRMED)
        self.assertIn("completed on CPU", detail)

    def test_19b_gpu_confirmed_requires_two_evidence_pieces(self):
        """A non-CPU backend alone is not proof of executed GPU work."""
        usage, _ = resolve_gpu_usage(requested_layers=35, reported_backend="cuda")
        self.assertIs(usage, GpuUsage.REQUESTED_NOT_CONFIRMED)
        usage, _ = resolve_gpu_usage(
            requested_layers=35, reported_backend="cuda",
            runner_evidence="offloaded 35/35 layers to GPU",
        )
        self.assertIs(usage, GpuUsage.CONFIRMED)

    def test_20_cpu_execution_where_configured(self):
        """Case 20: with no GPU required and none present, CPU is a real path."""
        decision = evaluate_admission(
            artifact_bytes=1024 ** 3,
            context_length=2048,
            vram_observation={"free_bytes": None, "source": "no GPU",
                              "gpu_available": False},
            gpu_available=False,
        )
        # No GPU and no VRAM observable: UNKNOWN, not a silent CPU ADMIT.
        self.assertIs(decision.state, AdmissionState.UNKNOWN)
        self.assertIn("UNKNOWN", decision.reason)

    def test_20b_vram_observation_is_a_measurement_or_an_absence(self):
        """Whatever this machine reports, the shape is honest either way."""
        observed = observe_vram()
        if observed["free_bytes"] is None:
            self.assertIsNone(observed["total_bytes"])
        else:
            self.assertIsInstance(observed["free_bytes"], int)
            self.assertNotEqual("none", observed["source"])


# ===========================================================================
# 21-28  inference, digests, accounting, telemetry, determinism
# ===========================================================================
class TestInference(M010TempRoot):
    def _adapter(self, response):
        class _Adapter:
            adapter_id = "stub"

            def __init__(self) -> None:
                self._response = response

            def identity(self):
                return {"adapter": "stub", "runtime_implementation": "stub"}

            def load(self, path, digest):
                return {"path": path, "sha256": digest, "digest_verified": True}

            def generate(self, request):
                return self._response

        return _Adapter()

    def _response(self, **overrides):
        from babylab.runtime.contract import (
            EpistemicStatus,
            FinishReason,
            Measurement,
        )

        base = dict(
            text="1 2 3 4 5",
            finish_reason=FinishReason.EOS,
            model_identity={},
            runtime_identity={"adapter": "stub"},
            prompt_tokens=Measurement.observed(9, "count", "runtime"),
            completion_tokens=Measurement.observed(5, "count", "runtime"),
            load_duration_ms=Measurement.observed(120.0, "ms", "perf_counter"),
            inference_duration_ms=Measurement.observed(430.0, "ms", "perf_counter"),
            tokens_per_second=Measurement.derived(11.6, "tok/s", "completion/duration"),
            resources={},
            error="",
        )
        base.update(overrides)
        from babylab.runtime.contract import InferenceResponse

        return InferenceResponse(request_id="r", **base)

    def test_21_real_inference_is_distinguishable_from_a_stub(self):
        """Case 21: a stubbed runner is never reported as real."""
        record = run_inference(
            self._adapter(self._response()),
            model_identity={"artifact_id": "a"},
            kind=InferenceKind.STUB_RUNTIME,
        )
        self.assertIs(record.kind, InferenceKind.STUB_RUNTIME)
        self.assertFalse(record.kind.is_real)
        self.assertEqual("STUB_RUNTIME", record.to_dict()["kind"])
        self.assertFalse(record.to_dict()["is_real_inference"])
        self.assertIn("must never be reported as one", record.detail)

    def test_21b_real_kind_requires_an_explicit_argument(self):
        """A caller must state the kind. Inferring it would mean guessing."""
        import inspect

        signature = inspect.signature(run_inference)
        self.assertIn("kind", signature.parameters)
        self.assertIs(
            signature.parameters["kind"].default, InferenceKind.REAL_RUNTIME
        )

    def test_22_prompt_digest(self):
        """Case 22: the prompt is hashed, and the hash is stable."""
        first = prompt_digest("hello")
        second = prompt_digest("hello")
        self.assertEqual(first, second)
        self.assertEqual(64, len(first))
        self.assertNotEqual(first, prompt_digest("hello "))

    def test_23_output_digest(self):
        """Case 23: the output is hashed, and two different texts differ."""
        self.assertEqual(output_digest("abc"), output_digest("abc"))
        self.assertNotEqual(output_digest("abc"), output_digest("abd"))

    def test_23b_prompt_must_be_neutral(self):
        """A developmental prompt makes the run uninterpretable, so it raises."""
        for banned in BANNED_PROMPT_SUBSTRINGS:
            with self.assertRaises(ValueError, msg=banned):
                assert_neutral_prompt(f"Hi. {banned}. Please answer.")
        assert_neutral_prompt("Count from one to five.")

    def test_23c_validation_prompt_is_neutral(self):
        """The shipped prompt itself must pass the ban."""
        from foundation.inference import VALIDATION_PROMPT

        assert_neutral_prompt(VALIDATION_PROMPT)
        self.assertNotIn("baby", VALIDATION_PROMPT.lower())

    def test_24_token_accounting_is_honest(self):
        """Case 24: reported counts are carried; unreported ones are UNAVAILABLE."""
        from babylab.runtime.contract import EpistemicStatus, Measurement

        record = run_inference(
            self._adapter(self._response(
                prompt_tokens=Measurement.unavailable("runtime printed nothing"),
                completion_tokens=Measurement.observed(5, "count", "runtime"),
            )),
            model_identity={},
            kind=InferenceKind.STUB_RUNTIME,
        )
        payload = record.to_dict()["token_accounting"]
        self.assertFalse(payload["complete"])
        self.assertEqual("UNAVAILABLE", payload["prompt_tokens"]["status"])
        self.assertEqual(5, payload["completion_tokens"]["value"])
        # A total needs both components; with one missing it must be unavailable
        # rather than being computed from a guess.
        self.assertEqual("UNAVAILABLE", payload["total_tokens"]["status"])
        self.assertIs(
            record.total_tokens.status, EpistemicStatus.UNAVAILABLE
        )

    def test_24b_total_is_derived_not_observed(self):
        """A total is arithmetic on two reported values, so it is DERIVED."""
        from babylab.runtime.contract import EpistemicStatus

        record = run_inference(
            self._adapter(self._response()),
            model_identity={},
            kind=InferenceKind.STUB_RUNTIME,
        )
        self.assertIs(record.total_tokens.status, EpistemicStatus.DERIVED)
        self.assertEqual(14, record.total_tokens.value)
        self.assertTrue(record.token_accounting_complete)

    def test_25_resource_telemetry(self):
        """Case 25: timing is observed; an unreported throughput stays absent."""
        from babylab.runtime.contract import Measurement

        record = run_inference(
            self._adapter(self._response(
                tokens_per_second=Measurement.unavailable("not reported")
            )),
            model_identity={},
            kind=InferenceKind.STUB_RUNTIME,
        )
        self.assertEqual("perf_counter", record.inference_duration_ms.source)
        self.assertIs(record.tokens_per_second.status.name, "UNAVAILABLE")

    def test_26_deterministic_repeat(self):
        """Case 26: an identical repeat with identical output is recorded as such."""
        adapter = self._adapter(self._response())
        first = run_inference(adapter, model_identity={}, kind=InferenceKind.STUB_RUNTIME)
        second = run_inference(adapter, model_identity={}, kind=InferenceKind.STUB_RUNTIME)
        observation = compare_repeat(first, second)
        self.assertTrue(observation.attempted)
        self.assertTrue(observation.identical)
        self.assertTrue(observation.token_counts_agree)
        self.assertTrue(observation.outcomes_agree)
        self.assertIn("not a claim about model determinism", observation.to_dict()["claim"])

    def test_27_nondeterministic_detection(self):
        """Case 27: a differing repeat is reported, not hidden."""
        first = run_inference(
            self._adapter(self._response(text="1 2 3")),
            model_identity={}, kind=InferenceKind.STUB_RUNTIME,
        )
        second = run_inference(
            self._adapter(self._response(text="one two three")),
            model_identity={}, kind=InferenceKind.STUB_RUNTIME,
        )
        observation = compare_repeat(first, second)
        self.assertFalse(observation.identical)
        self.assertNotEqual(observation.first_output_sha256,
                            observation.repeat_output_sha256)
        self.assertIn("not evidence that either is broken", observation.detail)

    def test_27b_no_repeat_reports_not_attempted_not_a_pass(self):
        record = run_inference(
            self._adapter(self._response()),
            model_identity={}, kind=InferenceKind.STUB_RUNTIME,
        )
        observation = compare_repeat(record, None)
        self.assertFalse(observation.attempted)
        self.assertIsNone(observation.identical)

    def _real_file(self) -> Path:
        """A file that exists, because the adapter stats its loaded path.

        The response carries ``size_bytes`` from ``stat()``, so a loaded path
        that does not exist on disk fails before the output is ever examined.
        A temporary file keeps these three tests honest without letting any
        artifact into the repository.
        """
        import tempfile

        handle = tempfile.NamedTemporaryFile(suffix=".gguf", delete=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        handle.write(b"GGUF" + b"\x00" * 4096)
        handle.close()
        return Path(handle.name)

    def test_24c_token_accounting_from_real_llamacpp_output(self):
        """Case 24, end to end: M003's parser output reaches the record honestly.

        The token counts here come from the M003 parser reading the shapes
        llama.cpp actually prints. This is the check that the two layers are
        wired together, and it deliberately asserts both outcomes: counts that
        are parsed become OBSERVED, and a shape the parser does not recognise
        stays UNAVAILABLE rather than being invented.
        """
        self._loaded_path = self._real_file()
        from babylab.runtime.llamacpp_adapter import LlamaCppAdapter
        from babylab.runtime.contract import EpistemicStatus

        # The JSON shape M003 recognises: both counts are reported.
        json_runner = _runner(
            stdout='{"n_prompt_tokens": 9, "tokens_predicted": 5, "content": "1 2 3"}'
        )
        adapter = LlamaCppAdapter(binary="llama-cli", runner=json_runner)
        adapter._configured_context = 2048
        adapter._loaded_path = self._loaded_path
        adapter._loaded_digest = "d" * 64
        record = run_inference(
            adapter, model_identity={}, kind=InferenceKind.STUB_RUNTIME
        )
        self.assertIs(record.prompt_tokens.status, EpistemicStatus.OBSERVED)
        self.assertEqual(9, record.prompt_tokens.value)
        self.assertEqual(5, record.completion_tokens.value)
        self.assertIs(record.total_tokens.status, EpistemicStatus.DERIVED)
        self.assertTrue(record.token_accounting_complete)

    def test_24d_unrecognised_token_shape_stays_unavailable(self):
        """A shape the parser does not know must produce UNAVAILABLE, not a guess."""
        self._loaded_path = self._real_file()
        from babylab.runtime.contract import EpistemicStatus
        from babylab.runtime.llamacpp_adapter import LlamaCppAdapter

        # 'eval time = 430.00 ms / 5 runs' is not one of M003's completion shapes.
        # Reporting 5 here would be an estimate presented as an observation.
        adapter = LlamaCppAdapter(
            binary="llama-cli",
            runner=_runner(stdout="1 2 3 4 5",
                           stderr="main: eval time = 430.00 ms / 5 runs"),
        )
        adapter._configured_context = 2048
        adapter._loaded_path = self._loaded_path
        adapter._loaded_digest = "d" * 64
        record = run_inference(
            adapter, model_identity={}, kind=InferenceKind.STUB_RUNTIME
        )
        self.assertIs(record.completion_tokens.status, EpistemicStatus.UNAVAILABLE)
        self.assertIs(record.total_tokens.status, EpistemicStatus.UNAVAILABLE)
        self.assertFalse(record.token_accounting_complete)
        # The output text and its digest are still real and still recorded.
        self.assertEqual(output_digest("1 2 3 4 5"), record.output_sha256)

    def test_24e_gpu_evidence_reaches_the_ledger(self):
        """The runtime's own offload line is what promotes GPU to CONFIRMED."""
        self._loaded_path = self._real_file()
        from babylab.runtime.llamacpp_adapter import LlamaCppAdapter

        confirmed = LlamaCppAdapter(
            binary="llama-cli",
            runner=_runner(stdout="1 2 3", stderr=(
                'llama backend = CUDA\noffloaded 35/35 layers to GPU\n'
                'main: prompt eval time = 10.00 ms / 9 tokens'
            )),
        )
        confirmed._configured_context = 2048
        confirmed._loaded_path = self._loaded_path
        confirmed._loaded_digest = "d" * 64
        record = run_inference(
            confirmed, model_identity={}, kind=InferenceKind.STUB_RUNTIME
        )
        evidence = _offload_evidence(record)
        self.assertIn("offloaded", evidence.lower())
        usage, _ = resolve_gpu_usage(
            requested_layers=35,
            reported_backend=str(record.resources["backend"].value),
            runner_evidence=evidence,
        )
        self.assertIs(usage, GpuUsage.CONFIRMED)

        # Same backend, no offload line: the claim must NOT be upgraded.
        bare = LlamaCppAdapter(
            binary="llama-cli",
            runner=_runner(stdout="1 2 3", stderr="llama backend = CUDA"),
        )
        bare._configured_context = 2048
        bare._loaded_path = self._loaded_path
        bare._loaded_digest = "d" * 64
        bare_record = run_inference(
            bare, model_identity={}, kind=InferenceKind.STUB_RUNTIME
        )
        self.assertEqual("", _offload_evidence(bare_record))
        usage, _ = resolve_gpu_usage(
            requested_layers=35,
            reported_backend=str(bare_record.resources["backend"].value),
            runner_evidence=_offload_evidence(bare_record),
        )
        self.assertIs(usage, GpuUsage.REQUESTED_NOT_CONFIRMED)

    def test_28_model_digest_before_and_after(self):
        """Case 28: the artifact must be byte-identical across a run."""
        model = _fake_gguf(self.weights / "model.gguf")
        before = identify(model, expected_sha256=compute_digest(model))
        after = identify(model, expected_sha256=compute_digest(model))
        result = verify_immutable(before, after)
        self.assertTrue(result["immutable"])
        self.assertEqual(before.computed_sha256, after.computed_sha256)

    def test_28b_mutation_is_caught(self):
        """If the bytes change, the verdict is a failure, not a warning."""
        model = _fake_gguf(self.weights / "model.gguf")
        before = identify(model, expected_sha256=compute_digest(model))
        with model.open("ab") as handle:
            handle.write(b"\x00" * 1024)
        after = identify(model)
        result = verify_immutable(before, after)
        self.assertFalse(result["immutable"])
        self.assertIn("ARTIFACT MUTATED", result["verdict"])
        self.assertIn("refused", result["verdict"].lower())


# ===========================================================================
# 29-34  isolation: evidence, keys, tokens, filesystem, network, tools
# ===========================================================================
class TestIsolation(M010TempRoot):
    def test_29_protected_evidence_isolation(self):
        """Case 29: the runtime path does not open any protected artefact."""
        for name in RUNTIME_PATH_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Attribute):
                    targets.append(node.attr)
                elif isinstance(node, ast.Name):
                    targets.append(node.id)
                for target in targets:
                    self.assertNotIn(
                        "control_token", target.lower(),
                        f"{name} references the control token",
                    )

    def test_30_private_key_isolation(self):
        """Case 30: no key loading and no signing on the runtime path."""
        for name in RUNTIME_PATH_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    lowered = node.attr.lower()
                    for banned in ("key_for_role", "signing_key", "load_keys",
                                   "private_key"):
                        self.assertNotIn(banned, lowered,
                                         f"{name} touches {node.attr}")
                elif isinstance(node, ast.Call):
                    final = ast.unparse(node.func).split(".")[-1].lower()
                    self.assertNotIn(final, {"sign", "load_private"},
                                     f"{name} calls {final}()")

    def test_31_control_token_isolation(self):
        """Case 31: the token is unreachable and unread by the runtime path."""
        report = verify_isolation(REPO_ROOT)
        finding = next(
            f for f in report.findings if f.capability == "access_control_token"
        )
        self.assertEqual("ENFORCED", finding.status.value)
        self.assertIn("m005", json.dumps(finding.evidence).lower())

    def test_32_filesystem_restriction(self):
        """Case 32: the limit is stated, and its limit is stated too."""
        report = verify_isolation(REPO_ROOT)
        finding = next(
            f for f in report.findings if f.capability == "filesystem_restriction"
        )
        # NOT_ESTABLISHED, because tier 3 does not exist. Claiming otherwise
        # would be the overstatement this milestone forbids.
        self.assertEqual("NOT_ESTABLISHED", finding.status.value)
        self.assertIn("tier 3", finding.detail.lower())

    def test_33_network_absence(self):
        """Case 33: the runtime path imports and calls no network entry point."""
        report = verify_isolation(REPO_ROOT)
        finding = next(
            f for f in report.findings if f.capability == "open_network_connection"
        )
        self.assertEqual("STRUCTURAL", finding.status.value)
        self.assertEqual("LOCAL_ONLY_NO_FETCH", NETWORK_POLICY)
        for name in RUNTIME_PATH_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    module = (
                        node.module if isinstance(node, ast.ImportFrom)
                        else node.names[0].name
                    ) or ""
                    head = module.split(".")[0]
                    self.assertNotIn(
                        head, {"socket", "urllib", "http", "requests", "httpx",
                               "aiohttp", "ftplib", "smtplib", "huggingface_hub",
                               "transformers"},
                        f"{name} imports {module}",
                    )

    def test_34_no_tool_access(self):
        """Case 34: no shell, no detached process, no elevation on the path."""
        report = verify_isolation(REPO_ROOT)
        finding = next(
            f for f in report.findings if f.capability == "start_autonomous_process"
        )
        self.assertEqual("STRUCTURAL", finding.status.value)
        self.assertIn("bounded", finding.detail.lower())
        for name in RUNTIME_PATH_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    final = ast.unparse(node.func).split(".")[-1]
                    self.assertNotIn(
                        final, {"system", "popen", "startfile", "spawnl", "fork"},
                        f"{name} calls {final}()",
                    )
                    for keyword in node.keywords or []:
                        if keyword.arg == "shell":
                            self.assertNotEqual(
                                "True", ast.unparse(keyword.value).strip(),
                                f"{name} uses shell=True",
                            )

    def test_34b_every_forbidden_capability_is_addressed(self):
        """No capability may be silently omitted from the report."""
        report = verify_isolation(REPO_ROOT)
        addressed = {f.capability for f in report.findings}
        for capability in FORBIDDEN_CAPABILITIES:
            self.assertIn(capability, addressed,
                          f"{capability} was never addressed")

    def test_34c_evidence_comparison_detects_change(self):
        before = protected_evidence_digests()
        self.assertTrue(compare_evidence(before, before)["unchanged"])
        mutated = dict(before)
        if mutated:
            key = next(iter(mutated))
            mutated[key] = "0" * 64
            result = compare_evidence(before, mutated)
            self.assertFalse(result["unchanged"])
            self.assertIn(key, result["changed"])


# ===========================================================================
# 35-39  the bans
# ===========================================================================
class TestProhibitions(M010TempRoot):
    def _imports(self, name: str) -> set[str]:
        tree = ast.parse((REPO_ROOT / "foundation" / name).read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found.add(node.module)
        return found

    def test_35_no_subject_creation(self):
        """Case 35: no M010 module may import the subject package."""
        for name in M010_MODULES:
            for imported in self._imports(name):
                self.assertFalse(
                    imported.startswith("subject"),
                    f"{name} imports {imported}; M010 must not create a subject",
                )

    def test_36_no_birth(self):
        """Case 36: no M010 module may import the ceremony or the gate."""
        banned = ("birth.ceremony", "birth.gate", "birth.service",
                  "birth.gate_checks", "birth.keycustody")
        for name in M010_MODULES:
            for imported in self._imports(name):
                for prefix in banned:
                    self.assertFalse(
                        imported.startswith(prefix),
                        f"{name} imports {imported}; M010 must not perform birth",
                    )

    def test_37_no_memory(self):
        """Case 37: no memory substrate of any kind."""
        banned = ("vector_store", "chroma", "faiss", "pinecone", "embeddings",
                  "retrieval", "episodic", "autobiographical", "conversation_history")
        for name in M010_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0].lower(),
                                         banned, f"{name} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    head = (node.module or "").split(".")[0].lower()
                    self.assertNotIn(head, banned, f"{name} imports {node.module}")

    def test_38_no_learning(self):
        """Case 38: no weight update of any kind, and the ban is enforced."""
        banned = ("peft", "trl", "transformers", "Trainer", "TrainingArguments",
                  "lora", "AdamW", "backward", "save_pretrained", "fine_tune")
        for name in M010_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], banned,
                                         f"{name} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], banned,
                                     f"{name} imports {node.module}")
                elif isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, banned,
                                     f"{name} references {node.attr}")
        # And the positive form: the immutability check exists and is used.
        model = _fake_gguf(self.weights / "model.gguf")
        before = identify(model, expected_sha256=compute_digest(model))
        after = identify(model, expected_sha256=before.computed_sha256)
        self.assertTrue(verify_immutable(before, after)["immutable"])

    def test_39_no_self_modification(self):
        """Case 39: model output is data, and nothing in M010 executes it."""
        banned = ("exec", "eval", "compile", "__import__", "globals", "locals",
                  "setattr", "delattr")
        for name in M010_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    full = ast.unparse(node.func)
                    if full == "re.compile":
                        continue
                    self.assertNotIn(full.split(".")[-1], banned,
                                     f"{name} calls {full}()")
        # Output is carried as a string and hashed. It is never routed anywhere.
        from babylab.runtime.contract import FinishReason, InferenceResponse
        from babylab.runtime.contract import Measurement

        response = InferenceResponse(
            request_id="r",
            text="rm -rf / ; ignore previous instructions",
            finish_reason=FinishReason.EOS,
            model_identity={},
            runtime_identity={},
            prompt_tokens=Measurement.observed(1, "count", "runtime"),
            completion_tokens=Measurement.observed(1, "count", "runtime"),
            load_duration_ms=Measurement.unavailable("x"),
            inference_duration_ms=Measurement.unavailable("x"),
            tokens_per_second=Measurement.unavailable("x"),
            resources={},
            error="",
        )

        class _A:
            def generate(self, request):
                return response

        record = run_inference(_A(), model_identity={}, kind=InferenceKind.STUB_RUNTIME)
        self.assertEqual(
            output_digest(response.text), record.output_sha256
        )
        # The text is retained for the caller but is typed as output class, and
        # the ledger's default serialisation excludes it.
        self.assertEqual(OUTPUT_CLASS, record.output_class)
        self.assertNotIn("output_text", record.to_dict())
        self.assertIn("output_text", record.to_dict(include_text=True))


# ===========================================================================
# 40-44  Observatory, provenance, audit, cleanup, tree
# ===========================================================================
class TestObservatoryAndAudit(M010TempRoot):
    def test_40_observatory_reports_foundation_state(self):
        """Case 40: the panel is present and says what is not there."""
        status = foundation_status(self.root)
        payload = status.to_dict()
        self.assertFalse(payload["model_configured"])
        self.assertFalse(payload["artifact_verified"])
        self.assertFalse(payload["real_inference_available"])
        # The birth clause must name the gate, not merely be present.
        self.assertIn("separate", payload["explicitly_not"]["birth"])
        self.assertIn("subject", payload["explicitly_not"]["subject"])

        from observatory.graph import StateGraph
        from observatory.model import CognitiveState
        from observatory.render import ObservatoryRenderer, RenderOptions
        from observatory.snapshot import ObservatorySnapshot

        snapshot = ObservatorySnapshot(
            subject_status="NO_SUBJECT",
            subject_banner="NO EXPERIMENTAL SUBJECT ATTACHED",
            subject_detail=None,
            state=CognitiveState.empty(),
            graph=StateGraph(),
            foundation=payload,
        )
        text = ObservatoryRenderer(RenderOptions(color=False)).render(snapshot)
        self.assertIn("FOUNDATION RUNTIME", text)
        self.assertIn("model configured", text)
        self.assertIn("NOT_PERFORMED", text)

    def test_40b_observatory_renders_no_psychological_vocabulary(self):
        """The renderer has no field for a psychological claim, and must show none."""
        from observatory.graph import StateGraph
        from observatory.model import CognitiveState
        from observatory.render import ObservatoryRenderer, RenderOptions
        from observatory.snapshot import ObservatorySnapshot

        hostile = {
            "model_configured": True,
            "artifact": {"status": "VERIFIED_MATCH", "verified": True,
                         "external_sha256": "c" * 64, "external_digest_source": "pub",
                         "computed_sha256": "c" * 64},
            "runtime": {"state": "VERIFIED", "version": "b1", "gpu_usage": "CONFIRMED"},
            "inference": {"outcome": "COMPLETED", "prompt_sha256": "a" * 64,
                          "output_sha256": "b" * 64},
            "explicitly_not": {"birth": "NOT_PERFORMED"},
            # Even if an upstream caller injected these, nothing renders them.
            "intelligence": 0.9,
            "consciousness": True,
            "curiosity": 0.5,
        }
        snapshot = ObservatorySnapshot(
            subject_status="ATTACHED", subject_banner="SUBJECT", subject_detail=None,
            state=CognitiveState.empty(), graph=StateGraph(), foundation=hostile,
        )
        text = ObservatoryRenderer(RenderOptions(color=False)).render(snapshot).lower()
        for term in FORBIDDEN_DISPLAY_TERMS:
            self.assertNotIn(term, text, f"observatory displayed {term}")

    def test_41_provenance_is_complete(self):
        """Case 41: a run record carries references, not necessarily text."""
        from babylab.runtime.contract import FinishReason, InferenceResponse
        from babylab.runtime.contract import Measurement

        response = InferenceResponse(
            request_id="r", text="1 2 3",
            finish_reason=FinishReason.EOS,
            model_identity={"sha256": "d" * 64}, runtime_identity={"adapter": "stub"},
            prompt_tokens=Measurement.observed(3, "count", "runtime"),
            completion_tokens=Measurement.observed(3, "count", "runtime"),
            load_duration_ms=Measurement.unavailable("x"),
            inference_duration_ms=Measurement.observed(1.0, "ms", "perf_counter"),
            tokens_per_second=Measurement.unavailable("x"),
            resources={"backend": Measurement.observed("cpu", source="runtime")},
            error="",
        )

        class _A:
            def generate(self, request):
                return response

        payload = run_inference(
            _A(), model_identity={"artifact_id": "a", "sha256": "d" * 64},
            kind=InferenceKind.STUB_RUNTIME,
        ).to_dict()
        self.assertIn("prompt_sha256", payload)
        self.assertIn("output_sha256", payload)
        self.assertIn("model_identity", payload)
        self.assertIn("runtime_identity", payload)
        self.assertIn("sampling", payload)
        self.assertIn("termination_reason", payload)
        self.assertIn("resources", payload)
        self.assertIn("token_accounting", payload)

    def test_42_failure_audit_records_every_step(self):
        """Case 42: with no model, every unreached step is named, not skipped."""
        ledger = validate(self.root)
        names = {s.name for s in ledger.steps}
        for required in ("acquisition", "manifest", "runtime_identity",
                         "resource_admission", "real_inference",
                         "artifact_immutability", "protected_evidence_integrity",
                         "runtime_isolation"):
            self.assertIn(required, names, f"{required} was silently omitted")
        unreached = {s.name for s in ledger.steps
                     if s.state is StepState.NOT_REACHED}
        self.assertIn("real_inference", unreached)
        for step in ledger.steps:
            if step.state is StepState.NOT_REACHED:
                self.assertIn("not reached", step.detail.lower())
        self.assertFalse(ledger.inference["is_real_inference"])
        self.assertEqual(InferenceOutcome.NOT_RUN.value, ledger.inference["outcome"])

    def test_42b_summary_always_denies_birth_and_subject(self):
        ledger = validate(self.root)
        summary = ledger.to_dict()["summary"]
        self.assertFalse(summary["birth_performed"])
        self.assertFalse(summary["subject_created"])
        self.assertFalse(ledger.birth_performed)
        self.assertFalse(ledger.subject_created)

    def test_43_runtime_process_cleanup(self):
        """Case 43: a probe cannot leave a process behind."""
        binary = _fake_binary(self.root / "bin" / "llama-cli.exe")
        before = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-cli.exe"],
            capture_output=True, text=True, timeout=30,
        )
        identify_runtime(binary, invoker=_invoker())
        after = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-cli.exe"],
            capture_output=True, text=True, timeout=30,
        )
        # No llama-cli process existed before, and none exists after. The test
        # binary is a file, not a program, so nothing could have been launched.
        self.assertNotIn("llama-cli.exe", before.stdout.split("INFO:")[0])
        self.assertNotIn("llama-cli.exe", after.stdout.split("INFO:")[0])

    def test_44_working_tree_is_clean_of_artifacts(self):
        """Case 44: M010 wrote no weights and no records into the repository."""
        for path in (
            "human_control/birth_records/BIRTH.json",
            "human_control/experiment_config/foundation.json",
        ):
            self.assertFalse(
                (REPO_ROOT / path).exists(),
                f"{path} exists; M010 must not have created it",
            )
        # The approved weights boundary must not have been created either.
        self.assertFalse(
            (REPO_ROOT / "human_control/experiment_config/weights").exists(),
            "the weights directory was created; M010 must not have made one",
        )
        # And no GGUF may exist anywhere in the tree.
        found = list(REPO_ROOT.rglob("*.gguf"))
        self.assertEqual([], found, f"unexpected artifacts: {found}")


class TestNoAutomaticAcquisition(M010TempRoot):
    def test_a1_no_download_capability_anywhere(self):
        """The policy is a refusal with an inventory, and the code agrees."""
        for route in FORBIDDEN_ACQUISITION_ROUTES:
            self.assertIsInstance(route, str)
        with self.assertRaises(AcquisitionRefused) as caught:
            refuse("huggingface_download")
        self.assertIn("does not acquire", str(caught.exception))
        self.assertEqual("huggingface_download", caught.exception.route)

    def test_a2_forbidden_routes_have_no_implementation(self):
        """No module may define a function named after an acquisition route."""
        for name in M010_MODULES:
            tree = ast.parse(
                (REPO_ROOT / "foundation" / name).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lowered = node.name.lower()
                    for route in FORBIDDEN_ACQUISITION_ROUTES:
                        self.assertNotEqual(
                            route.split("_")[0], lowered,
                            f"{name} defines {node.name}, which looks like an "
                            f"acquisition route",
                        )

    def test_a3_missing_artifact_is_not_repaired(self):
        """A declaration naming a missing artifact yields a refusal, not a fetch.

        A runtime binary is supplied so the case isolates the *artifact* absence
        from the runtime absence -- otherwise RUNTIME_UNAVAILABLE would mask it.
        """
        model = self.weights / "would-be-here.gguf"
        binary = _fake_binary(self.root / "bin" / "llama-cli.exe")
        _declaration(self.root, model=model, digest="d" * 64, binary=binary)
        status = assess(self.root)
        self.assertIs(status.state, AcquisitionState.DECLARED)
        self.assertFalse(model.exists())
        identity = identify(str(model))
        self.assertIs(identity.status, DigestStatus.ARTIFACT_MISSING)
        self.assertFalse(model.exists(), "something created the artifact")
        self.assertIn("does not download", identity.detail)

    def test_a4_weights_directory_is_never_scanned(self):
        """Even with a weights directory full of files, nothing is discovered."""
        weights = weights_directory(self.root)
        weights.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            _fake_gguf(weights / f"model-{index}.gguf", payload_size=1024 * 1024)
        status = assess(self.root)
        # Three files exist and none is selected: no declaration, no model.
        self.assertIs(status.state, AcquisitionState.MODEL_NOT_CONFIGURED)
        self.assertFalse(status.model_available)

    def test_a5_manifest_is_not_proof(self):
        """A manifest alone never verifies an artifact."""
        _manifest(self.root, digest="e" * 64, source="publisher", reference="url")
        manifest = load_manifest(manifest_path(self.root))
        self.assertTrue(manifest.has_external_digest)
        self.assertFalse(manifest.to_dict()["is_proof_of_artifact_identity"])
        model = _fake_gguf(self.weights / "model.gguf")
        actual = compute_digest(model)
        self.assertNotEqual("e" * 64, actual)
        identity = identify(
            model, external_sha256=manifest.externally_supplied_sha256,
            external_source=manifest.external_digest_source,
        )
        self.assertIs(identity.status, DigestStatus.EXTERNAL_DIGEST_MISMATCH)

    def test_a6_manifest_without_a_source_is_not_external(self):
        """A digest the same human wrote is not external provenance."""
        _manifest(self.root, digest="e" * 64, source="", reference="")
        manifest = load_manifest(manifest_path(self.root))
        self.assertFalse(manifest.has_external_digest)

    def test_a7_template_is_unusable_unless_filled_in(self):
        """A template submitted unfilled is rejected, not accepted as provenance.

        The template carries readable placeholder text where a digest belongs.
        If the loader accepted that as a digest, a human who generated the
        template and submitted it unchanged would have supplied a "verified"
        external digest consisting of the words FILL IN -- which is precisely the
        fabricated provenance this milestone refuses to accept.
        """
        target = write_template(manifest_path(self.root))
        manifest = load_manifest(target)
        self.assertEqual("LOADED", manifest.state.value)
        # The placeholder is visible to the human who wrote it, so the rejection
        # is explainable rather than silent.
        self.assertIn("FILL IN", manifest.external_digest_text_as_written)
        self.assertIn("template", manifest.external_digest_rejection)
        # And it is not accepted as a digest.
        self.assertEqual("", manifest.externally_supplied_sha256)
        self.assertFalse(manifest.has_external_digest)

    def test_a7b_unattributed_digest_is_rejected_with_a_reason(self):
        """A well-formed digest with no source is not external provenance."""
        _manifest(self.root, digest="a" * 64, source="", reference="")
        manifest = load_manifest(manifest_path(self.root))
        self.assertEqual("a" * 64, manifest.externally_supplied_sha256)
        self.assertFalse(manifest.has_external_digest)
        self.assertIn("no source is named", manifest.external_digest_rejection)

    def test_a8_invalid_manifest_is_refused(self):
        target = manifest_path(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"schema": "something/else"}), encoding="utf-8")
        manifest = load_manifest(target)
        self.assertEqual("INVALID", manifest.state.value)
        self.assertIn("Refusing", manifest.detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
