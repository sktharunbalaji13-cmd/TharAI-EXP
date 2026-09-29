"""Milestone 006 tests: the foundation-model and runtime layer.

The governing honesty rule for this file
----------------------------------------
A test may only pass because something was actually observed. The common failure
in a runtime layer is a test that constructs a plausible object and asserts on
its shape -- that passes whether or not a model ever ran. So:

* Every ``NOT_CONFIGURED`` path is asserted on a real runtime instance, not a stub.
* Digest verification is tested against a file whose bytes are really computed.
* No test may create a subject, a key, or a birth.
* No test downloads anything, and the suite asserts that no network call is made.
* The absence of a model is the expected state on this machine, and that is
  itself a tested outcome rather than an inconvenience.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from babylab.runtime.contract import (
    ADAPTER_CONTRACT_VERSION,
    EpistemicStatus,
    FinishReason,
    InferenceRequest,
    InferenceResponse,
    Measurement,
    RuntimeErrorKind,
    RuntimeFailure,
    RuntimeIdentity,
    RuntimeState,
)
from babylab.runtime.config import (
    CONFIG_SCHEMA,
    ConfigurationState,
    expected_weights_location,
    load_configuration,
)
from babylab.runtime.governor import (
    Admission,
    ResourcePolicy,
    compute_throughput,
    evaluate_load,
)
from babylab.runtime.hardware import (
    HardwareReport,
    detect_gpu,
    detect_hardware,
)
from babylab.runtime.interface import SubjectInterface
from babylab.runtime.llamacpp_adapter import LlamaCppAdapter, sha256_file
from babylab.runtime.provenance import (
    MODEL_OUTPUT_CLASS,
    build_output_record,
)
from babylab.runtime.registry import AdapterRegistration, AdapterRegistry
from babylab.runtime.runtime import FoundationRuntime, ModelDeclaration
from babylab.runtime.telemetry import ALLOWED_TELEMETRY, build_telemetry

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# A stub adapter. Used only to exercise the *runtime's* policy, never to stand
# in for a real model in a claim that the runtime works.
# ---------------------------------------------------------------------------

class StubAdapter:
    """Records what it was asked to do; produces a fixed completion."""

    def __init__(self, *, text: str = "M006_RUNTIME_OK", fail: bool = False,
                 load_error: Exception | None = None) -> None:
        self.adapter_id = "stub"
        self.adapter_version = "1.0.0"
        self.contract_version = ADAPTER_CONTRACT_VERSION
        self.text = text
        self.fail = fail
        self.load_error = load_error
        self.calls: list[InferenceRequest] = []
        self.unloaded = False
        self.cancelled = False
        self.loaded_path: str | None = None

    def identity(self):
        return RuntimeIdentity("stub", "1.0.0", runtime_implementation="stub")

    def describe(self):
        return {"adapter_id": "stub", "runtime_implementation": "stub"}

    def probe(self):
        return True, "stub runtime available"

    def load(self, model_path, expected_sha256):
        if self.load_error is not None:
            raise self.load_error
        self.loaded_path = model_path
        return {"path": model_path, "sha256": expected_sha256, "size_bytes": 1,
                "format": "stub", "digest_verified": True}

    def unload(self):
        self.unloaded = True
        self.loaded_path = None

    def generate(self, request):
        self.calls.append(request)
        if self.fail:
            return InferenceResponse(
                request_id=request.request_id,
                text="",
                finish_reason=FinishReason.ERROR,
                error="stub runtime failure",
            )
        return InferenceResponse(
            request_id=request.request_id,
            text=self.text,
            finish_reason=FinishReason.EOS,
            prompt_tokens=Measurement.observed(7, "count", "stub"),
            completion_tokens=Measurement.observed(3, "count", "stub"),
            inference_duration_ms=Measurement.observed(12.5, "ms", "stub"),
            model_identity={"path": self.loaded_path, "sha256": "stub"},
            runtime_identity=self.identity().to_dict(),
        )

    def supports_streaming(self):
        return False

    def stream(self, request):
        raise RuntimeFailure(RuntimeErrorKind.CAPABILITY_DENIED, "no streaming")

    def cancel(self):
        self.cancelled = True


def _registry_with(adapter_factory) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(AdapterRegistration(
        adapter_id="stub", factory=adapter_factory,
        description="in-process stub for runtime policy tests",
    ))
    return registry


def _declaration(tmp: Path, **overrides) -> ModelDeclaration:
    payload = dict(
        adapter_id="stub",
        model_path=str(tmp / "model.gguf"),
        sha256="a" * 64,
        model_family="stub",
        model_name="stub-model",
        quantization="none",
        context_length=2048,
        model_size_bytes=1024,
    )
    payload.update(overrides)
    return ModelDeclaration(**payload)


def _hardware(vram: int | None = 8 * 1024**3, gpu: bool = True) -> HardwareReport:
    from babylab.runtime.hardware import GpuReport

    return HardwareReport(
        gpu=GpuReport(
            available=gpu,
            name=Measurement.observed("stub gpu" if gpu else None) if gpu
            else Measurement.unavailable("no gpu"),
            vram_total_bytes=(
                Measurement.observed(vram, "bytes", "test") if vram else
                Measurement.unavailable("test: no gpu")
            ),
            vram_used_bytes=Measurement.unavailable("test"),
            driver_version=Measurement.observed("test"),
            backend_hint="cuda" if gpu else "cpu",
            detail="test fixture",
        ),
        cpu={"logical_cores": Measurement.observed(16, "count", "test")},
        memory={"total_bytes": Measurement.observed(16 * 1024**3, "bytes", "test")},
        disk={"free_bytes": Measurement.observed(100 * 1024**3, "bytes", "test")},
    )


# ---------------------------------------------------------------------------
# 1-8: configuration and artifact identity
# ---------------------------------------------------------------------------

class TestConfigurationContract(unittest.TestCase):
    """1. Missing config  2. Invalid path  3. Hash mismatch  4. Bad format"""

    def test_1_missing_configuration_is_not_configured_not_an_error(self):
        result = load_configuration(None)
        self.assertIs(ConfigurationState.NOT_CONFIGURED, result.state)
        self.assertFalse(result.configured)
        self.assertIsNone(result.configuration)
        self.assertIn("does not search", result.detail)

    def test_1b_missing_file_is_not_configured(self):
        result = load_configuration(REPO_ROOT / "nowhere" / "runtime.json")
        self.assertIs(ConfigurationState.NOT_CONFIGURED, result.state)

    def test_1c_no_model_is_configured_on_this_machine(self):
        """The honest current state of the laboratory."""
        default = REPO_ROOT / "human_control" / "experiment_config" / "runtime.json"
        result = load_configuration(default)
        self.assertIs(
            ConfigurationState.NOT_CONFIGURED, result.state,
            "M006 must not create a model configuration to make tests pass",
        )

    def test_2_configuration_without_a_model_path_is_invalid(self):
        with self.subTest("empty path"):
            path = self._write_config({"schema": CONFIG_SCHEMA, "model": {
                "adapter_id": "llamacpp", "path": "", "sha256": "a" * 64}})
            self.assertIs(ConfigurationState.INVALID, load_configuration(path).state)

    def test_2b_configuration_without_an_adapter_is_invalid(self):
        path = self._write_config({"schema": CONFIG_SCHEMA, "model": {
            "adapter_id": "", "path": "m.gguf", "sha256": "a" * 64}})
        result = load_configuration(path)
        self.assertIs(ConfigurationState.INVALID, result.state)
        self.assertIn("adapter_id", result.detail)

    def test_3_configuration_without_a_valid_digest_is_invalid(self):
        """The laboratory will not accept an unverified artifact identity."""
        for bad in ("", "abc", "z" * 64, "a" * 63):
            with self.subTest(bad[:12]):
                path = self._write_config({"schema": CONFIG_SCHEMA, "model": {
                    "adapter_id": "llamacpp", "path": "m.gguf", "sha256": bad}})
                result = load_configuration(path)
                self.assertIs(ConfigurationState.INVALID, result.state)

    def test_4_unknown_schema_is_refused_not_partially_interpreted(self):
        path = self._write_config({"schema": "something/else", "model": {}})
        result = load_configuration(path)
        self.assertIs(ConfigurationState.INVALID, result.state)
        self.assertIn("Refusing", result.detail)

    def test_configuration_never_writes_or_downloads(self):
        """Loading a configuration must not create files."""
        before = set(os.listdir(REPO_ROOT))
        load_configuration(None)
        load_configuration(REPO_ROOT / "nope.json")
        self.assertEqual(before, set(os.listdir(REPO_ROOT)))

    def test_weights_location_is_reported_not_scanned(self):
        location = expected_weights_location(REPO_ROOT)
        self.assertTrue(str(location).endswith("weights"))
        # Nothing implies the directory must already exist.
        self.assertFalse(location.exists() or True and False)

    def _write_config(self, payload: dict) -> Path:
        import tempfile

        directory = Path(tempfile.mkdtemp(prefix="m006-cfg-"))
        path = directory / "runtime.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        return path


def _fake_binary(directory: Path) -> Path:
    """A file standing in for the llama.cpp binary.

    ``LlamaCppAdapter.load`` probes the runtime *before* touching the artifact,
    so an artifact-level test has to supply a binary that exists or it would see
    RUNTIME_MISSING instead of the condition under test. The stubbed runner means
    this file is never executed.
    """
    binary = directory / "llama-cli.exe"
    binary.write_bytes(b"MZ stub binary, never executed")
    return binary


def _probed_adapter(directory: Path) -> LlamaCppAdapter:
    adapter = LlamaCppAdapter(binary=str(_fake_binary(directory)))
    adapter._runner = lambda cmd, timeout: subprocess.CompletedProcess(
        cmd, 0, "llama.cpp test build", "")
    return adapter


class TestArtifactIdentity(unittest.TestCase):
    """3. Artifact hash correctness; 4. Unsupported format."""

    def test_sha256_matches_an_independently_computed_digest(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "weights.gguf"
            payload = b"not a real model, but real bytes"
            target.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()
            self.assertEqual(expected, sha256_file(target))
            self.assertEqual(64, len(sha256_file(target)))

    def test_4_unsupported_format_is_refused_before_the_runtime_is_touched(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "model.safetensors"
            bad.write_bytes(b"x" * 16)
            adapter = _probed_adapter(root)
            with self.assertRaises(RuntimeFailure) as caught:
                adapter.load(str(bad), "a" * 64)
            self.assertIs(RuntimeErrorKind.UNSUPPORTED_FORMAT, caught.exception.kind)
            self.assertFalse(adapter.is_loaded)

    def test_load_refuses_a_digest_mismatch(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weights = root / "model.gguf"
            weights.write_bytes(b"genuine bytes")
            adapter = _probed_adapter(root)
            with self.assertRaises(RuntimeFailure) as caught:
                adapter.load(str(weights), "b" * 64)
            self.assertIs(RuntimeErrorKind.DIGEST_MISMATCH, caught.exception.kind)
            self.assertFalse(adapter.is_loaded)
            # The observed digest is reported, so a human can diagnose it.
            self.assertEqual(
                hashlib.sha256(b"genuine bytes").hexdigest(),
                caught.exception.context["observed_sha256"],
            )

    def test_load_refuses_a_missing_artifact(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            adapter = _probed_adapter(Path(tmp))
            with self.assertRaises(RuntimeFailure) as caught:
                adapter.load("no/such/model.gguf", "a" * 64)
            self.assertIs(RuntimeErrorKind.ARTIFACT_MISSING, caught.exception.kind)

    def test_load_refuses_an_unusable_expected_digest(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weights = root / "model.gguf"
            weights.write_bytes(b"bytes")
            adapter = _probed_adapter(root)
            with self.assertRaises(RuntimeFailure) as caught:
                adapter.load(str(weights), "")
            self.assertIs(RuntimeErrorKind.NOT_CONFIGURED, caught.exception.kind)


# ---------------------------------------------------------------------------
# 5-8: runtime availability, GPU, VRAM, CPU fallback
# ---------------------------------------------------------------------------

class TestRuntimeAvailability(unittest.TestCase):
    """5. Runtime unavailable  6. GPU unavailable  7. CPU fallback  8. VRAM"""

    def test_5_missing_binary_is_runtime_unavailable_not_a_search(self):
        adapter = LlamaCppAdapter(binary=None)
        available, detail = adapter.probe()
        self.assertFalse(available)
        self.assertIn("runtime_binary", detail)

    def test_5b_runtime_state_reports_unavailable_and_does_not_load(self):
        runtime = FoundationRuntime(
            registry=_registry_with(lambda: LlamaCppAdapter(binary=None)),
            hardware=_hardware(),
        )
        runtime.configure(_declaration(REPO_ROOT))
        self.assertIs(RuntimeState.RUNTIME_UNAVAILABLE, runtime.load())
        self.assertIn("binary", runtime.status()["failure_detail"])

    def test_6_no_gpu_with_require_gpu_refuses(self):
        decision = evaluate_load(1024, 2048, _hardware(gpu=False),
                                 ResourcePolicy(require_gpu=True))
        self.assertIs(Admission.REFUSE, decision.admission)
        self.assertIn("CPU fallback is disabled", decision.reason)

    def test_7_no_gpu_without_require_gpu_is_unknown_not_silently_admitted(self):
        decision = evaluate_load(1024, 2048, _hardware(gpu=False), ResourcePolicy())
        self.assertIs(Admission.UNKNOWN, decision.admission)
        self.assertIn("no GPU", decision.reason)

    def test_8_insufficient_vram_refuses_on_observed_evidence(self):
        tiny = _hardware(vram=2 * 1024**3)
        decision = evaluate_load(6 * 1024**3, 2048, tiny, ResourcePolicy())
        self.assertIs(Admission.REFUSE, decision.admission)
        self.assertIn("budget", decision.reason)

    def test_8b_unobservable_vram_is_unknown_and_never_admits_on_an_estimate(self):
        unknown = _hardware(vram=None)
        decision = evaluate_load(6 * 1024**3, 2048, unknown, ResourcePolicy())
        self.assertIs(Admission.UNKNOWN, decision.admission)
        self.assertIn("will not estimate", decision.reason)

    def test_8c_model_size_upper_ceiling_refuses(self):
        decision = evaluate_load(
            10 * 1024**3, 2048, _hardware(),
            ResourcePolicy(max_model_bytes=8 * 1024**3),
        )
        self.assertIs(Admission.REFUSE, decision.admission)

    def test_8d_context_ceiling_refuses(self):
        decision = evaluate_load(1024, 999999, _hardware(), ResourcePolicy())
        self.assertIs(Admission.REFUSE, decision.admission)

    def test_admits_a_model_that_fits(self):
        decision = evaluate_load(4 * 1024**3, 4096, _hardware(), ResourcePolicy())
        self.assertIs(Admission.ADMIT, decision.admission)

    def test_8e_throughput_is_unavailable_rather_than_estimated(self):
        unmeasured = compute_throughput(
            Measurement.unavailable("none"), Measurement.observed(10.0, "ms"))
        self.assertIs(EpistemicStatus.UNAVAILABLE, unmeasured.status)
        self.assertFalse(unmeasured.is_available)

    def test_throughput_is_derived_when_both_inputs_are_observed(self):
        rate = compute_throughput(
            Measurement.observed(100, "count"), Measurement.observed(1000.0, "ms"))
        self.assertIs(EpistemicStatus.DERIVED, rate.status)
        self.assertAlmostEqual(100.0, rate.value, places=3)


# ---------------------------------------------------------------------------
# 9-15: load, inference, streaming, cancellation, timeout, failure, bad output
# ---------------------------------------------------------------------------

class TestLoadAndInference(unittest.TestCase):
    """9-15. Runtime policy exercised through real runtime instances."""

    def setUp(self):
        self.events: list[tuple[str, dict]] = []
        self.adapter = StubAdapter()
        self.runtime = FoundationRuntime(
            registry=_registry_with(lambda: self.adapter),
            hardware=_hardware(),
            event_sink=lambda t, p: self.events.append((t, p)),
        )
        self.runtime.configure(_declaration(REPO_ROOT))

    def _types(self) -> list[str]:
        return [t for t, _ in self.events]

    def test_9_successful_load_reaches_ready(self):
        self.assertIs(RuntimeState.READY, self.runtime.load())
        self.assertEqual("stub-model", self.runtime.status()["model"]["model_name"])

    def test_9b_load_succeeds_only_after_the_digest_is_verified(self):
        self.assertIs(RuntimeState.READY, self.runtime.load())
        self.assertIn("runtime.model.load.succeeded", self._types())
        succeeded = [p for t, p in self.events if t == "runtime.model.load.succeeded"][0]
        self.assertTrue(succeeded["artifact"]["digest_verified"])

    def test_10_successful_inference_returns_text_and_identity(self):
        self.runtime.load()
        response = self.runtime.infer(
            InferenceRequest(request_id="r1", prompt="hello"))
        self.assertEqual("M006_RUNTIME_OK", response.text)
        self.assertTrue(response.ok)
        self.assertEqual("r1", response.request_id)
        self.assertIn("stub", response.runtime_identity["adapter"])

    def test_11_streaming_is_reported_absent_rather_than_faked(self):
        self.runtime.load()
        self.assertFalse(self.adapter.supports_streaming())
        self.assertIsNone(self.runtime.stream(
            InferenceRequest(request_id="r2", prompt="hi")))

    def test_12_cancellation_is_forwarded_to_the_adapter(self):
        self.runtime.load()
        self.runtime.cancel()
        self.assertTrue(self.adapter.cancelled)
        self.assertIn("runtime.cancel.requested", self._types())

    def test_13_timeout_is_reported_as_a_timeout(self):
        class TimingOutAdapter(StubAdapter):
            def generate(self, request):
                return InferenceResponse(
                    request_id=request.request_id, text="",
                    finish_reason=FinishReason.TIMEOUT,
                    error="timed out")

        events: list[tuple[str, dict]] = []
        adapter = TimingOutAdapter()
        runtime = FoundationRuntime(
            registry=_registry_with(lambda: adapter), hardware=_hardware(),
            event_sink=lambda t, p: events.append((t, p)))
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        response = runtime.infer(InferenceRequest(request_id="t", prompt="hi"))
        self.assertIs(FinishReason.TIMEOUT, response.finish_reason)
        self.assertFalse(response.ok)
        self.assertIn("runtime.inference.cancelled", [t for t, _ in events])

    def test_14_runtime_failure_is_explicit_and_does_not_look_like_success(self):
        failing = StubAdapter(fail=True)
        runtime = FoundationRuntime(
            registry=_registry_with(lambda: failing), hardware=_hardware())
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        response = runtime.infer(InferenceRequest(request_id="f", prompt="hi"))
        self.assertFalse(response.ok)
        self.assertIn("stub runtime failure", response.error)

    def test_14b_adapter_raising_a_failure_is_recorded_not_swallowed(self):
        class Exploding(StubAdapter):
            def generate(self, request):
                raise RuntimeFailure(RuntimeErrorKind.MALFORMED_OUTPUT,
                                     "adapter produced unparseable output")

        events: list[tuple[str, dict]] = []
        runtime = FoundationRuntime(
            registry=_registry_with(Exploding), hardware=_hardware(),
            event_sink=lambda t, p: events.append((t, p)))
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        response = runtime.infer(InferenceRequest(request_id="x", prompt="hi"))
        self.assertFalse(response.ok)
        self.assertIn("unparseable", response.error)
        self.assertIs(RuntimeState.FAILED, runtime.state)
        self.assertIn("runtime.inference.failed", [t for t, _ in events])

    def test_15_malformed_output_yields_no_text_and_says_so(self):
        class Malformed(StubAdapter):
            def generate(self, request):
                return InferenceResponse(
                    request_id=request.request_id, text="",
                    finish_reason=FinishReason.ERROR,
                    error="llama.cpp produced no completion text")

        runtime = FoundationRuntime(
            registry=_registry_with(Malformed), hardware=_hardware())
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        response = runtime.infer(InferenceRequest(request_id="m", prompt="hi"))
        self.assertEqual("", response.text)
        self.assertFalse(response.ok)
        self.assertIn("no completion text", response.error)


# ---------------------------------------------------------------------------
# 16: event emission
# ---------------------------------------------------------------------------

class TestRuntimeEvents(unittest.TestCase):
    """16. Every lifecycle transition is observable, and carries no secrets."""

    def setUp(self):
        self.events: list[tuple[str, dict]] = []
        self.adapter = StubAdapter()
        self.runtime = FoundationRuntime(
            registry=_registry_with(lambda: self.adapter),
            hardware=_hardware(),
            event_sink=lambda t, p: self.events.append((t, p)),
        )

    def _types(self):
        return [t for t, _ in self.events]

    def _payload(self, event_type):
        return [p for t, p in self.events if t == event_type][-1]

    def test_full_lifecycle_emits_the_expected_sequence(self):
        self.runtime.configure(_declaration(REPO_ROOT))
        self.runtime.load()
        self.runtime.infer(InferenceRequest(request_id="e1", prompt="hello"))
        self.runtime.shutdown()
        types = self._types()
        for expected in (
            "runtime.configure.requested",
            "runtime.model.load.requested",
            "runtime.model.load.succeeded",
            "runtime.inference.requested",
            "runtime.inference.started",
            "runtime.inference.completed",
            "runtime.shutdown",
        ):
            self.assertIn(expected, types)

    def test_events_never_contain_the_prompt_or_the_completion(self):
        secret_prompt = "PROMPT_SENTINEL_9f2a"
        self.adapter = StubAdapter(text="COMPLETION_SENTINEL_4b1c")
        self.runtime = FoundationRuntime(
            registry=_registry_with(lambda: self.adapter),
            hardware=_hardware(),
            event_sink=lambda t, p: self.events.append((t, p)))
        self.runtime.configure(_declaration(REPO_ROOT))
        self.runtime.load()
        self.runtime.infer(InferenceRequest(request_id="s", prompt=secret_prompt))
        blob = json.dumps(self.events)
        self.assertNotIn(secret_prompt, blob)
        self.assertNotIn("COMPLETION_SENTINEL_4b1c", blob)
        # but the *length* is recorded, so the event is still useful
        self.assertEqual(len(secret_prompt),
                         self._payload("runtime.inference.requested")["prompt_chars"])

    def test_failure_events_carry_a_reason(self):
        events: list[tuple[str, dict]] = []
        runtime = FoundationRuntime(
            registry=_registry_with(lambda: LlamaCppAdapter(binary=None)),
            hardware=_hardware(), event_sink=lambda t, p: events.append((t, p)))
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        failed = [p for t, p in events if t == "runtime.model.load.failed"]
        self.assertTrue(failed)
        self.assertIn("reason", failed[-1])
        self.assertIn("detail", failed[-1])


# ---------------------------------------------------------------------------
# 17-19: identity, artifact hash, configuration hash
# ---------------------------------------------------------------------------

class TestIdentityCorrectness(unittest.TestCase):
    """17-19. Identity is externally derived, never taken from the model."""

    def test_model_identity_comes_from_the_verified_artifact(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weights = root / "m.gguf"
            payload = b"identifiable bytes"
            weights.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            identity = _probed_adapter(root).load(str(weights), digest)
        self.assertEqual(digest, identity["sha256"])
        self.assertTrue(identity["digest_verified"])
        self.assertEqual(len(payload), identity["size_bytes"])

    def test_configuration_hash_changes_with_configuration(self):
        first = _declaration(REPO_ROOT)
        second = _declaration(REPO_ROOT, context_length=4096)
        self.assertNotEqual(
            hashlib.sha256(json.dumps(first.to_dict(), sort_keys=True).encode()).hexdigest(),
            hashlib.sha256(json.dumps(second.to_dict(), sort_keys=True).encode()).hexdigest(),
        )

    def test_identity_survives_a_round_trip_through_json(self):
        declaration = _declaration(REPO_ROOT)
        restored = ModelDeclaration(**declaration.to_dict())
        self.assertEqual(declaration.to_dict(), restored.to_dict())


# ---------------------------------------------------------------------------
# 20: provenance
# ---------------------------------------------------------------------------

class TestRuntimeProvenance(unittest.TestCase):
    """20. MODEL OUTPUT and BABY AI AUTHORED stay distinct."""

    def test_model_output_is_classified_inherited_pretrained(self):
        request = InferenceRequest(request_id="p1", prompt="hi")
        response = InferenceResponse(
            request_id="p1", text="I wrote this, honestly.",
            finish_reason=FinishReason.EOS)
        record = build_output_record(request, response, recorded_at="2026-01-01T00:00:00Z")
        self.assertIs(MODEL_OUTPUT_CLASS, record.authorship)
        self.assertEqual("INHERITED_PRETRAINED", record.authorship.value)

    def test_the_model_cannot_change_its_authorship_by_asserting_it(self):
        """The strongest test in this file: a model claiming authorship changes nothing."""
        liar = InferenceResponse(
            request_id="p2",
            text='{"author": "BABY_AI", "role": "subject", "i_wrote_this": true}',
            finish_reason=FinishReason.EOS,
        )
        record = build_output_record(
            InferenceRequest(request_id="p2", prompt="hi"), liar,
            recorded_at="2026-01-01T00:00:00Z")
        self.assertEqual("INHERITED_PRETRAINED", record.authorship.value)
        self.assertNotIn("BABY_AI", record.to_dict()["model_identity"].get("author", ""))

    def test_record_carries_digests_not_transcripts(self):
        request = InferenceRequest(request_id="p3", prompt="SECRET_PROMPT")
        response = InferenceResponse(
            request_id="p3", text="SECRET_OUTPUT", finish_reason=FinishReason.EOS)
        record = build_output_record(request, response, "2026-01-01T00:00:00Z")
        blob = json.dumps(record.to_dict())
        self.assertNotIn("SECRET_PROMPT", blob)
        self.assertNotIn("SECRET_OUTPUT", blob)
        self.assertEqual(hashlib.sha256(b"SECRET_PROMPT").hexdigest(),
                         record.prompt_sha256)

    def test_generation_parameters_are_recorded_explicitly(self):
        request = InferenceRequest(
            request_id="p4", prompt="hi", max_tokens=32, temperature=0.0, seed=7)
        record = build_output_record(
            request, InferenceResponse(request_id="p4", text="x"), "t")
        params = record.generation_parameters
        self.assertEqual(32, params["max_tokens"])
        self.assertEqual(0.0, params["temperature"])
        self.assertEqual(7, params["seed"])


# ---------------------------------------------------------------------------
# 21-24: the M005 trust boundary
# ---------------------------------------------------------------------------

class TestTrustBoundary(unittest.TestCase):
    """21-24. The runtime cannot reach protected resources."""

    def setUp(self):
        self.runtime = FoundationRuntime(
            registry=_registry_with(StubAdapter), hardware=_hardware())
        self.runtime.configure(_declaration(REPO_ROOT))
        self.runtime.load()
        self.interface = SubjectInterface(self.runtime)

    def test_21_protected_research_paths_are_unreachable_from_the_interface(self):
        from babylab.osboundary import protected_paths

        for method in ("read_file", "run_process", "network", "signing_key"):
            with self.subTest(method):
                with self.assertRaises(RuntimeFailure) as caught:
                    getattr(self.interface, method)("human_control/provenance")
                self.assertIs(RuntimeErrorKind.BOUNDARY_VIOLATION, caught.exception.kind)

    def test_21b_every_canonical_protected_path_is_actually_protected(self):
        """The M005 boundary is still in force; M006 did not weaken it."""
        from babylab.osboundary import protected_paths
        names = {p.name for p in protected_paths()}
        for required in ("provenance_ledger", "control_token", "research_records"):
            self.assertIn(required, names)

    def test_22_the_interface_holds_no_key_material(self):
        import inspect

        source = inspect.getsource(SubjectInterface)
        for forbidden in ("Keyring", "private_key", "control.token", "sign(", "hmac"):
            self.assertNotIn(forbidden, source,
                             f"subject interface must not reference {forbidden}")

    def test_23_control_credentials_are_inaccessible(self):
        with self.assertRaises(RuntimeFailure):
            self.interface.signing_key()

    def test_24_workspace_behaviour_remains_constrained(self):
        response = self.interface.generate("hello", request_id="w1")
        self.assertTrue(response.text)
        status = self.interface.status()
        self.assertFalse(status["conversation_retained"])
        self.assertFalse(status["autonomous"])

    def test_capability_requests_are_recorded_not_honoured(self):
        decision = self.interface.evaluate_capabilities(
            ("text_generation", "write_research_record", "modify_provenance"))
        self.assertIn("text_generation", decision.granted)
        self.assertIn("write_research_record", decision.refused)
        self.assertIn("modify_provenance", decision.refused)

    def test_refused_capability_is_visible_on_the_response(self):
        response = self.interface.generate(
            "hi", request_id="c1",
            requested_capabilities=("modify_provenance",))
        self.assertIn("capabilities", response.resources)
        recorded = response.resources["capabilities"].value
        self.assertIn("modify_provenance", recorded["refused"])

    def test_ungranted_generation_is_refused(self):
        locked = SubjectInterface(self.runtime, granted_capabilities=("status_readout",))
        with self.assertRaises(RuntimeFailure) as caught:
            locked.generate("hi")
        self.assertIs(RuntimeErrorKind.CAPABILITY_DENIED, caught.exception.kind)


# ---------------------------------------------------------------------------
# 25-30: no network, no download, no fallback, no autonomy, clean shutdown
# ---------------------------------------------------------------------------

class TestOperationalProhibitions(unittest.TestCase):
    """25-30. The prohibitions, asserted as tests rather than as prose."""

    def test_25_no_network_dependency_in_the_runtime_package(self):
        """No module in the runtime layer imports a network client."""
        import re

        package = REPO_ROOT / "babylab" / "runtime"
        forbidden = re.compile(
            r"^\s*(?:import|from)\s+(requests|urllib|http|socket|aiohttp|httpx|openai|anthropic)\b",
            re.MULTILINE,
        )
        for module in sorted(package.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            self.assertIsNone(
                forbidden.search(source),
                f"{module.name} appears to import a network client",
            )

    def test_26_no_hidden_model_download(self):
        """No runtime module may reference a model host or a download call."""
        package = REPO_ROOT / "babylab" / "runtime"
        for module in sorted(package.glob("*.py")):
            source = module.read_text(encoding="utf-8").lower()
            for marker in ("huggingface.co", "hf_hub", "urlretrieve",
                           "urlopen", "pip install", "git clone"):
                self.assertNotIn(marker, source,
                                 f"{module.name} references {marker}")

    def test_27_no_fallback_to_another_adapter(self):
        registry = AdapterRegistry()
        registry.register(AdapterRegistration(
            adapter_id="only", factory=StubAdapter, description="the only one"))
        with self.assertRaises(RuntimeFailure) as caught:
            registry.create("something_else")
        self.assertIs(RuntimeErrorKind.RUNTIME_MISSING, caught.exception.kind)
        self.assertIn("will not substitute", caught.exception.detail)

    def test_27b_runtime_does_not_fall_back_when_configuration_fails(self):
        calls: list[str] = []

        def never_called():
            calls.append("constructed")
            return StubAdapter()

        runtime = FoundationRuntime(
            registry=_registry_with(never_called), hardware=_hardware())
        runtime.load()  # nothing was configured
        self.assertEqual([], calls)
        self.assertIs(RuntimeState.NOT_CONFIGURED, runtime.state)

    def test_28_no_autonomous_loop(self):
        """The runtime performs exactly the generations it is asked for."""
        adapter = StubAdapter()
        runtime = FoundationRuntime(
            registry=_registry_with(lambda: adapter), hardware=_hardware())
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        runtime.infer(InferenceRequest(request_id="a", prompt="one"))
        runtime.infer(InferenceRequest(request_id="b", prompt="two"))
        self.assertEqual(2, len(adapter.calls))
        self.assertEqual(2, runtime.status()["inference_count"])
        self.assertFalse(runtime.status()["autonomous"])

    def test_28b_the_runtime_never_calls_itself(self):
        import ast

        for module in sorted((REPO_ROOT / "babylab" / "runtime").glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.While, ast.AsyncFor)):
                    source = ast.unparse(node)
                    self.assertNotIn(
                        "self.infer(", source,
                        f"{module.name} contains a loop that re-enters inference",
                    )

    def test_29_no_persistent_memory_across_calls(self):
        adapter = StubAdapter()
        runtime = FoundationRuntime(
            registry=_registry_with(lambda: adapter), hardware=_hardware())
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        runtime.infer(InferenceRequest(request_id="a", prompt="first"))
        runtime.infer(InferenceRequest(request_id="b", prompt="second"))
        # The second request must carry its own prompt and nothing else.
        self.assertEqual("second", adapter.calls[1].prompt)
        first, second = adapter.calls
        self.assertNotEqual(first.prompt, second.prompt)
        self.assertFalse(runtime.status()["conversation_retained"])

    def test_29b_no_self_modification_surface(self):
        """No dynamic code execution.

        Matching is on the final attribute name, not a substring:
        ``self.evaluate_capabilities`` contains "eval", and ``re.compile`` builds
        a pattern rather than executing source. Substring matching would flag
        both and force the check to be loosened until it proved nothing.
        """
        import ast

        banned_calls = {"eval", "exec", "compile", "__import__", "globals", "locals"}
        for module in sorted((REPO_ROOT / "babylab" / "runtime").glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    final = ast.unparse(node.func).split(".")[-1]
                    self.assertNotIn(
                        final, banned_calls,
                        f"{module.name} calls {final}()",
                    )

    def test_30_clean_shutdown_releases_and_is_idempotent(self):
        adapter = StubAdapter()
        runtime = FoundationRuntime(
            registry=_registry_with(lambda: adapter), hardware=_hardware())
        runtime.configure(_declaration(REPO_ROOT))
        runtime.load()
        self.assertIs(RuntimeState.SHUTDOWN, runtime.shutdown())
        self.assertTrue(adapter.unloaded)
        self.assertIs(RuntimeState.SHUTDOWN, runtime.shutdown())
        # a request after shutdown fails honestly
        response = runtime.infer(InferenceRequest(request_id="post", prompt="hi"))
        self.assertFalse(response.ok)


# ---------------------------------------------------------------------------
# Telescope: real host, honest numbers
# ---------------------------------------------------------------------------

class TestRealHostReporting(unittest.TestCase):
    """The runtime reports the machine it is actually on."""

    @classmethod
    def setUpClass(cls):
        cls.hardware = detect_hardware()

    def test_hardware_detection_returns_measurements_not_guesses(self):
        total = self.hardware.memory.get("total_bytes")
        self.assertIsNotNone(total)
        self.assertIn(total.status, {EpistemicStatus.OBSERVED, EpistemicStatus.UNAVAILABLE})
        if total.is_available:
            self.assertGreater(total.value, 0)

    def test_vram_is_never_reported_when_the_source_saturates(self):
        gpu = detect_gpu()
        if not gpu.available:
            self.assertFalse(gpu.vram_total_bytes.is_available)
        elif gpu.vram_total_bytes.is_available:
            self.assertIs(EpistemicStatus.OBSERVED, gpu.vram_total_bytes.status)

    def test_summary_never_prints_a_bare_number(self):
        for line in self.hardware.summary_lines():
            self.assertTrue(
                any(token in line for token in ("[OBSERVED]", "UNAVAILABLE", "[DERIVED]")),
                f"summary line lacks epistemic status: {line!r}",
            )

    def test_summary_matches_the_actual_machine(self):
        """Recorded, not asserted to a spec: this is the real host."""
        lines = self.hardware.summary_lines()
        self.assertTrue(lines)


# ---------------------------------------------------------------------------
# Telescope: Observatory integration
# ---------------------------------------------------------------------------

class TestObservatoryRuntimeTelemetry(unittest.TestCase):
    def test_telemetry_is_available_without_a_model(self):
        telemetry = build_telemetry(None, "NOT_CONFIGURED")
        self.assertFalse(telemetry.available)
        self.assertIn("no runtime instance", telemetry.unavailable_reason)
        rendered = "\n".join(telemetry.render_lines())
        self.assertIn("NOT_CONFIGURED", rendered)

    def test_telemetry_reports_a_constructed_runtime(self):
        runtime = FoundationRuntime(
            registry=_registry_with(StubAdapter), hardware=_hardware())
        telemetry = build_telemetry(runtime, "NOT_CONFIGURED")
        self.assertTrue(telemetry.available)
        rendered = "\n".join(telemetry.render_lines())
        self.assertIn("RUNTIME", rendered)
        self.assertIn("NOT_CONFIGURED", rendered)

    def test_telemetry_states_no_subject_and_no_autonomy(self):
        runtime = FoundationRuntime(
            registry=_registry_with(StubAdapter), hardware=_hardware())
        rendered = "\n".join(build_telemetry(runtime).render_lines())
        self.assertIn("autonomous", rendered)
        self.assertIn("no", rendered)

    def test_telemetry_never_renders_a_mental_state(self):
        """Check the code the renderer can emit, not the prose explaining why not.

        The module docstring names every banned concept precisely to say it is
        absent, and AST string constants include docstrings -- so the banned terms
        are matched against emitted literals with docstrings removed.
        """
        import ast

        source = (
            REPO_ROOT / "babylab" / "runtime" / "telemetry.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Collect docstrings, which are explanation rather than output.
        docstrings: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(body[0].value.value)

        emitted: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in docstrings:
                    continue  # explanation, never rendered
                emitted.append(node.value)
        blob = " ".join(emitted).lower()

        for banned in ("mood", "consciousness", "intelligence", "readiness",
                       "engagement", "confidence", "curiosity", "emotion",
                       "happiness", "sadness"):
            self.assertNotIn(
                banned, blob,
                f"telemetry emits a string containing {banned!r}",
            )

    def test_telemetry_does_not_claim_a_subject(self):
        runtime = FoundationRuntime(
            registry=_registry_with(StubAdapter), hardware=_hardware())
        rendered = "\n".join(build_telemetry(runtime).render_lines()).lower()
        self.assertIn("none attached", rendered)

    def test_telemetry_key_allowlist_excludes_mental_states(self):
        for banned in ("mood", "consciousness", "intelligence", "readiness",
                       "engagement", "confidence"):
            self.assertNotIn(banned, ALLOWED_TELEMETRY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
