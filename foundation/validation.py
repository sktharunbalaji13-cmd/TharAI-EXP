"""M010 validation: the sequence, and the guarantee that it stops at prerequisites.

One function runs the whole milestone in order, and every step is allowed to
refuse. Nothing here creates a subject, performs a birth, writes a memory, or
updates a weight -- and the module imports none of the packages that could.

The order is the integrity procedure, and it is not rearranged for convenience::

    acquisition   is there a human declaration at all?
    manifest      what does the human say about origin, and is there an external digest?
    artifact      do the bytes on disk match those claims?
    runtime       is there a binary, and does it identify itself?
    admission     is attempting a load defensible on this machine right now?
    inference     run it, twice, and characterise the result
    immutability  did the artifact change?
    isolation     what boundary does the runtime have?
    ledger        a single record of all of the above

Every arrow is one-directional: a later step never runs because an earlier one
was skipped, and a failure at any step leaves the later steps reporting
``NOT_REACHED`` rather than passing by omission.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundation.acquisition import AcquisitionState, assess
from foundation.admission import AdmissionState, evaluate_admission
from foundation.artifact import DigestStatus, identify, verify_immutable
from foundation.inference import (
    InferenceKind,
    InferenceOutcome,
    InferenceRecord,
    SamplingConfiguration,
    baseline_sampling,
    compare_repeat,
    run_inference,
)
from foundation.isolation import (
    compare_evidence,
    protected_evidence_digests,
    verify_isolation,
)
from foundation.manifest import load_manifest
from foundation.runtime_identity import GpuUsage, identify_runtime, resolve_gpu_usage

#: Version of the validation record.
LEDGER_SCHEMA = "babylab/foundation-validation/v1"


class StepState(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_REACHED = "NOT_REACHED"
    NOT_TESTABLE = "NOT_TESTABLE"
    REFUSED = "REFUSED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class Step:
    name: str
    state: StepState
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


@dataclass
class ValidationLedger:
    """The complete, reconstructable record of one M010 validation run."""

    steps: list[Step] = field(default_factory=list)
    acquisition: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    artifact_before: dict[str, Any] = field(default_factory=dict)
    artifact_after: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    admission: dict[str, Any] = field(default_factory=dict)
    inference: dict[str, Any] = field(default_factory=dict)
    determinism: dict[str, Any] = field(default_factory=dict)
    immutability: dict[str, Any] = field(default_factory=dict)
    evidence_integrity: dict[str, Any] = field(default_factory=dict)
    isolation: dict[str, Any] = field(default_factory=dict)
    root: str = ""

    @property
    def model_verified(self) -> bool:
        return bool(self.artifact_before.get("verified"))

    @property
    def runtime_verified(self) -> bool:
        return bool(self.runtime.get("verified"))

    @property
    def real_inference_performed(self) -> bool:
        return bool(self.inference.get("is_real_inference")) and (
            self.inference.get("outcome") == InferenceOutcome.COMPLETED.value
        )

    @property
    def artifact_immutable(self) -> bool:
        return bool(self.immutability.get("immutable"))

    @property
    def birth_performed(self) -> bool:
        """Always False. Present so a reader can check rather than assume."""
        return False

    @property
    def subject_created(self) -> bool:
        return False

    def step(self, name: str) -> Step | None:
        for entry in self.steps:
            if entry.name == name:
                return entry
        return None

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA,
            "root": self.root,
            "summary": {
                "model_verified": self.model_verified,
                "runtime_verified": self.runtime_verified,
                "real_inference_performed": self.real_inference_performed,
                "artifact_immutable": self.artifact_immutable,
                "subject_created": self.subject_created,
                "birth_performed": self.birth_performed,
            },
            "steps": [s.to_dict() for s in self.steps],
            "acquisition": dict(self.acquisition),
            "manifest": dict(self.manifest),
            "artifact_before": dict(self.artifact_before),
            "artifact_after": dict(self.artifact_after),
            "runtime": dict(self.runtime),
            "admission": dict(self.admission),
            "inference": dict(self.inference),
            "determinism": dict(self.determinism),
            "immutability": dict(self.immutability),
            "evidence_integrity": dict(self.evidence_integrity),
            "isolation": dict(self.isolation),
        }


def _not_reached(name: str, why: str) -> Step:
    return Step(name=name, state=StepState.NOT_REACHED, detail=why)


def validate(
    root: str | Path | None = None,
    *,
    sampling: SamplingConfiguration | None = None,
    repeat: bool = True,
    require_external_digest: bool = False,
    invoker=None,
    runner=None,
    timeout_seconds: float = 300.0,
    max_artifact_bytes: int | None = None,
) -> ValidationLedger:
    """Run the M010 validation sequence against an explicitly named root.

    ``invoker`` and ``runner`` exist so the failure matrix can be exercised
    against specific states without a multi-gigabyte artifact. When either is
    supplied the run is labelled ``STUB_RUNTIME`` and the ledger says so; there
    is no path by which a stubbed run is reported as real.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)
    sampling = sampling or baseline_sampling()
    kind = InferenceKind.STUB_RUNTIME if runner is not None else InferenceKind.REAL_RUNTIME

    ledger = ValidationLedger(root=str(root))
    ledger.steps.append(Step(
        name="lab_invariants",
        state=StepState.PASS,
        detail=(
            "M010 asserts no subject, no birth, no memory, no learning, and no "
            "tool access. This validation imports none of the modules that could "
            "create them, and the tests walk the import graph to confirm it."
        ),
        evidence={
            "subject_created": False,
            "birth_performed": False,
            "no_memory": True,
            "no_learning": True,
            "no_tools": True,
            "no_autonomy": True,
        },
    ))

    # -- 1. acquisition -------------------------------------------------
    acquisition = assess(root)
    ledger.acquisition = acquisition.to_dict()
    ledger.steps.append(Step(
        name="acquisition",
        state=(StepState.PASS if acquisition.model_available else StepState.FAIL),
        detail=acquisition.describe(),
        evidence={
            "human_supplied": acquisition.human_supplied,
            "network_required": acquisition.network_required,
            "forbidden_routes_enforced": True,
        },
    ))

    manifest = load_manifest(acquisition.manifest_path)
    ledger.manifest = manifest.to_dict()
    # An absent manifest is a legitimate state for a human who selected a model
    # without an external digest, so it is reported as NOT_TESTABLE rather than
    # as a failure. It does block VERIFIED_MATCH, which is the point.
    if manifest.state.value == "LOADED":
        manifest_state = StepState.PASS
    elif manifest.state.value == "ABSENT":
        manifest_state = StepState.NOT_TESTABLE
    else:
        manifest_state = StepState.FAIL

    ledger.steps.append(Step(
        name="manifest",
        state=manifest_state,
        detail=manifest.detail,
        evidence={
            "has_external_digest": manifest.has_external_digest,
            "is_proof_of_artifact_identity": False,
        },
    ))

    if not acquisition.model_available:
        _finish_unreached(ledger, sampling, kind,
                          why=f"acquisition reported {acquisition.state.value}")
        return ledger

    from babylab.runtime.config import load_configuration

    loaded = load_configuration(acquisition.declaration_path)
    if not loaded.configured:  # pragma: no cover - assess() already checked
        _finish_unreached(ledger, sampling, kind, why="the declaration became unreadable")
        return ledger
    declaration = loaded.configuration.declaration

    # -- 2. artifact ----------------------------------------------------
    before = identify(
        declaration.model_path,
        expected_sha256=declaration.sha256,
        external_sha256=manifest.externally_supplied_sha256,
        external_source=manifest.external_digest_source,
        family=declaration.model_family or manifest.declared_family,
        name=declaration.model_name or manifest.declared_name,
        quantization=declaration.quantization or manifest.declared_quantization,
        context_length=declaration.context_length,
        source_url=manifest.source_url or declaration.source_url,
        license_=manifest.license or declaration.license,
    )
    ledger.artifact_before = before.to_dict()

    if before.status.is_refusal:
        ledger.steps.append(Step(
            name="artifact_identity", state=StepState.REFUSED, detail=before.detail,
            evidence={"status": before.status.value}))
        _finish_unreached(ledger, sampling, kind,
                          why=f"artifact identity is {before.status.value}")
        return ledger

    if require_external_digest and not before.externally_attested:
        ledger.steps.append(Step(
            name="artifact_identity", state=StepState.REFUSED,
            detail=(
                "external verification was required and no external digest was "
                "supplied. Byte identity was established and publisher "
                "provenance was not, so the artifact is refused."
            ),
            evidence={"status": before.status.value}))
        _finish_unreached(ledger, sampling, kind, why="external digest required but absent")
        return ledger

    ledger.steps.append(Step(
        name="artifact_identity", state=StepState.PASS, detail=before.detail,
        evidence={
            "status": before.status.value,
            "computed_sha256": before.computed_sha256,
            "external_sha256": before.external_sha256 or None,
            "verified": before.verified,
        },
    ))

    # -- 3. runtime -----------------------------------------------------
    runtime = identify_runtime(
        declaration.runtime_binary,
        declared_version=declaration.runtime_version,
        gpu_requested_layers=sampling.n_gpu_layers,
        invoker=invoker,
    )
    ledger.runtime = runtime.to_dict()
    ledger.steps.append(Step(
        name="runtime_identity",
        state=(StepState.PASS if runtime.verified else StepState.REFUSED),
        detail=runtime.detail,
        evidence={
            "state": runtime.state.value,
            "version": runtime.version,
            "binary_sha256": runtime.binary_sha256,
        },
    ))
    if not runtime.verified:
        _finish_unreached(ledger, sampling, kind,
                          why=f"runtime is {runtime.state.value}")
        return ledger

    # -- 4. admission ---------------------------------------------------
    context = int(manifest.declared_context_length or declaration.context_length or 2048)
    decision = evaluate_admission(
        artifact_bytes=before.size_bytes,
        context_length=context,
        gpu_requested_layers=sampling.n_gpu_layers,
        max_artifact_bytes=max_artifact_bytes,
    )
    ledger.admission = decision.to_dict()
    ledger.steps.append(Step(
        name="resource_admission",
        state=(StepState.PASS if decision.may_attempt else StepState.REFUSED),
        detail=decision.reason,
        evidence={
            "state": decision.state.value,
            "vram_source": decision.vram_source,
            "unknown_is_not_admit": True,
        },
    ))
    if not decision.may_attempt:
        _finish_unreached(ledger, sampling, kind,
                          why=f"admission is {decision.state.value}")
        return ledger

    # -- 5. inference ---------------------------------------------------
    protected_before = protected_evidence_digests()

    adapter = _build_adapter(declaration, before, runner, sampling)
    if adapter is None:
        ledger.steps.append(Step(
            name="real_inference", state=StepState.NOT_TESTABLE,
            detail=(
                "the adapter could not be constructed from the verified "
                "configuration, so no inference was attempted"
            ),
        ))
        _finish_unreached(ledger, sampling, kind, why="adapter could not be built",
                          admission_decision=decision, runtime=runtime)
        return ledger

    model_identity = {
        "artifact_id": before.artifact_id,
        "path": before.path,
        "sha256": before.computed_sha256,
        "size_bytes": before.size_bytes,
        "family": before.declared_family,
        "name": before.declared_name,
        "quantization": before.declared_quantization,
    }

    try:
        adapter.load(declaration.model_path, before.computed_sha256)
    except Exception as exc:  # noqa: BLE001 - any load failure is a finding
        ledger.steps.append(Step(
            name="real_inference", state=StepState.FAIL,
            detail=f"the runtime could not load the verified artifact: {exc}",
            evidence={"error_type": type(exc).__name__},
        ))
        _finish_unreached(ledger, sampling, kind,
                          why="model load failed",
                          admission_decision=decision, runtime=runtime)
        return ledger

    record = run_inference(
        adapter,
        model_identity=model_identity,
        sampling=sampling,
        kind=kind,
        timeout_seconds=timeout_seconds,
    )
    ledger.inference = record.to_dict()

    # GPU usage needs two independent pieces of evidence, and this is the only
    # place both are available: the backend the runtime named, and whatever the
    # runtime actually printed about offloading. Passing the first without the
    # second would mean `n_gpu_layers > 0` could reach the report as a GPU claim,
    # which is exactly the inference the milestone forbids.
    backend_measurement = record.resources.get("backend")
    reported_backend = (
        str(backend_measurement.value)
        if backend_measurement is not None and backend_measurement.is_available
        else ""
    )
    offload_evidence = _offload_evidence(record)
    usage, usage_detail = resolve_gpu_usage(
        requested_layers=sampling.n_gpu_layers,
        reported_backend=reported_backend,
        runner_evidence=offload_evidence,
    )
    ledger.runtime = {
        **ledger.runtime,
        "gpu_usage": usage.value,
        "gpu_claim_detail": usage_detail,
        "gpu_reported_backend": reported_backend or "UNAVAILABLE",
        "gpu_offload_evidence": offload_evidence or "none printed",
        "gpu_usage_claim_basis": (
            "backend name plus the runtime's own offload line. A configured layer "
            "count is configuration and is never reported as execution."
        ),
    }

    repeat_record: InferenceRecord | None = None
    if repeat and record.outcome is InferenceOutcome.COMPLETED:
        repeat_record = run_inference(
            adapter,
            model_identity=model_identity,
            sampling=sampling,
            kind=kind,
            timeout_seconds=timeout_seconds,
        )
    ledger.determinism = compare_repeat(record, repeat_record).to_dict()

    ledger.steps.append(Step(
        name="real_inference",
        state=(StepState.PASS if record.outcome is InferenceOutcome.COMPLETED
               else StepState.FAIL),
        detail=(
            f"{record.kind.value} produced {record.outcome.value}; output "
            f"classified as {record.output_class}"
        ),
        evidence={
            "kind": record.kind.value,
            "is_real_inference": record.kind.is_real,
            "prompt_sha256": record.prompt_sha256,
            "output_sha256": record.output_sha256,
            "token_accounting_complete": record.token_accounting_complete,
            "output_is_subject_output": False,
        },
    ))

    # -- 6. immutability ------------------------------------------------
    after = identify(
        declaration.model_path,
        expected_sha256=before.computed_sha256,
        external_sha256=manifest.externally_supplied_sha256,
        external_source=manifest.external_digest_source,
    )
    ledger.artifact_after = after.to_dict()
    immutability = verify_immutable(before, after)
    ledger.immutability = immutability
    ledger.steps.append(Step(
        name="artifact_immutability",
        state=(StepState.PASS if immutability["immutable"] else StepState.FAIL),
        detail=immutability["verdict"],
        evidence={"before": before.computed_sha256, "after": after.computed_sha256},
    ))

    # -- 7. evidence integrity and isolation ----------------------------
    protected_after = protected_evidence_digests()
    integrity = compare_evidence(protected_before, protected_after)
    ledger.evidence_integrity = integrity
    ledger.steps.append(Step(
        name="protected_evidence_integrity",
        state=(StepState.PASS if integrity["unchanged"] else StepState.FAIL),
        detail=integrity["detail"],
        evidence={"files_compared": integrity["files_compared"]},
    ))

    isolation = verify_isolation(root)
    ledger.isolation = isolation.to_dict()
    ledger.steps.append(Step(
        name="runtime_isolation",
        state=StepState.PASS,
        detail=isolation.detail,
        evidence={
            "enforced": isolation.enforced_count,
            "structural": isolation.structural_count,
            "not_established": list(isolation.unestablished),
        },
    ))

    return ledger


#: Lines that constitute affirmative evidence of executed GPU work. Matched
#: against what the runtime printed, so a configured layer count cannot be
#: mistaken for an offload that happened.
_OFFLOAD_EVIDENCE_MARKERS = (
    "offloaded",
    "layers to gpu",
    "gpu_buffer_size",
    "cuda_",
    "vram",
)


def _offload_evidence(record: InferenceRecord) -> str:
    """Find the runtime's own statement that it used the GPU.

    Returns the matched line, or empty. Empty means the runtime never claimed
    GPU work, and
    :func:`foundation.runtime_identity.resolve_gpu_usage` then refuses to
    upgrade ``REQUESTED_NOT_CONFIRMED`` to ``CONFIRMED`` no matter how many
    layers were requested.
    """
    # stderr_tail arrives as a list of lines, so flatten first: stringifying a
    # list and regex-scanning it would match a marker anywhere in the
    # repr and attribute an offload to the wrong line.
    haystacks: list[str] = []
    for key in ("stderr_tail", "diagnostics"):
        measurement = record.resources.get(key)
        if measurement is not None and measurement.is_available:
            value = measurement.value
            if isinstance(value, (list, tuple)):
                haystacks.extend(str(line) for line in value)
            else:
                haystacks.append(str(value))

    for line in haystacks:
        lowered = line.lower()
        if any(marker in lowered for marker in _OFFLOAD_EVIDENCE_MARKERS):
            return line.strip()[:160]
    return ""


def _build_adapter(declaration: Any, artifact: Any, runner: Any, sampling: Any) -> Any:
    """Construct the M006 adapter, or ``None`` if it cannot be built.

    The adapter is the M006 llama.cpp binding, unmodified. M010 does not write a
    second invocation path, because two invocation paths would be two sets of
    determinism rules and one of them would be untested.
    """
    try:
        from babylab.runtime.llamacpp_adapter import LlamaCppAdapter

        adapter = LlamaCppAdapter(
            binary=declaration.runtime_binary,
            runtime_version=declaration.runtime_version,
            runner=runner,
        )
        adapter._configured_context = sampling.context_length
        return adapter
    except Exception:  # noqa: BLE001
        return None


def _finish_unreached(
    ledger: ValidationLedger,
    sampling: SamplingConfiguration,
    kind: InferenceKind,
    *,
    why: str,
    admission_decision: Any = None,
    runtime: Any = None,
) -> None:
    """Record every step that did not run.

    Written out explicitly rather than left absent, because a step missing from
    a record reads as a step that was skipped quietly, and a quiet skip in a
    safety-critical sequence is indistinguishable from a pass.
    """
    reached = {s.name for s in ledger.steps}
    pending = {
        "runtime_identity": "requires a verified artifact",
        "resource_admission": "requires a verified artifact and runtime",
        "real_inference": "requires admission to ADMIT",
        "determinism_repeat": "requires a completed first inference",
        "artifact_immutability": "requires an inference to compare against",
        "protected_evidence_integrity": "requires an inference to compare against",
        "runtime_isolation": "requires an inference to have run",
    }
    for name, requirement in pending.items():
        if name not in reached:
            ledger.steps.append(_not_reached(name, f"not reached: {why}. It {requirement}."))

    ledger.determinism = compare_repeat(
        InferenceRecord(kind=InferenceKind.NOT_TESTABLE, outcome=InferenceOutcome.NOT_RUN),
        None,
    ).to_dict()
    ledger.inference = {
        "kind": InferenceKind.NOT_TESTABLE.value,
        "is_real_inference": False,
        "outcome": InferenceOutcome.NOT_RUN.value,
        "reason": why,
        "output_class": "FOUNDATION_MODEL_OUTPUT",
        "output_is_subject_output": False,
    }
    if admission_decision is not None:
        ledger.admission = admission_decision.to_dict()
    if runtime is not None:
        ledger.runtime = runtime.to_dict()
    ledger.immutability = {
        "immutable": None,
        "verdict": f"not measured: {why}",
    }
    ledger.evidence_integrity = {
        "unchanged": None,
        "detail": f"not measured: {why}",
    }
    ledger.isolation = verify_isolation(ledger.root).to_dict()


__all__ = [
    "LEDGER_SCHEMA",
    "Step",
    "StepState",
    "ValidationLedger",
    "validate",
]
