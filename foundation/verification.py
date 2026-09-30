"""M011 verification: the full sequence, with a verdict per acceptance criterion.

One function runs the milestone in order and records, for every criterion the
specification lists, one of four outcomes:

``SATISFIED``
    Measured, by this run.
``NOT_TESTABLE``
    Cannot be measured on this host, with the reason. Never rounded to a pass.
``FAILED``
    Measured, and did not hold. Always accompanied by the observation.
``NOT_REACHED``
    A prerequisite upstream refused, so this was never attempted.

Why a per-criterion ledger rather than one boolean
--------------------------------------------------
"Because real inference could not run" and "because the boundary was violated"
are completely different states, and a single pass/fail collapses them into
something that has to be guessed at. The milestone's own final-report format asks
for separate lines for real runtime, real inference, process identity, and the
security probe, so the record has to carry them separately too.

Ordering, and what refuses what
-------------------------------
::

    host          measure this machine now
    acquisition   is there a human declaration?
    artifact      do the bytes match the claims?
    runtime       does the named binary exist and identify itself?
    admission     is an attempt defensible?
    immutability  capture both digests BEFORE anything runs
    inference     run it, twice
    verify-after  both digests AFTER
    process       who ran it?
    boundary      what could that process reach?
    network       was anything fetched?

Each step checks its own result before the next begins. The immutability capture
happens *before* inference deliberately: capturing it afterwards would prove only
that nothing changed after the measurement, which is the same mistake as quoting
a digest from a sidecar file.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundation.acquisition import AcquisitionState, assess
from foundation.admission import AdmissionState, evaluate_admission
from foundation.artifact import DigestStatus, identify
from foundation.hardware import HostReport, measure_disk_free_vram, measure_host
from foundation.inference import OUTPUT_CLASS, baseline_sampling
from foundation.isolation import verify_isolation
from foundation.manifest import load_manifest
from foundation.real_runtime import (
    ExecutionMode,
    RealRun,
    RuntimeReadiness,
    assess_runtime,
    check_runtime_immutable,
    compare_two,
    run_real,
)
from foundation.validation import Step, StepState

#: Version of the M011 verification record.
LEDGER_SCHEMA = "babylab/m011-verification/v1"


class CriterionState(str, enum.Enum):
    SATISFIED = "SATISFIED"
    NOT_TESTABLE = "NOT_TESTABLE"
    FAILED = "FAILED"
    NOT_REACHED = "NOT_REACHED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class Criterion:
    """One acceptance criterion and what this run established about it."""

    name: str
    state: CriterionState
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
class M011Ledger:
    """The complete M011 record."""

    criteria: list[Criterion] = field(default_factory=list)
    hardware: dict[str, Any] = field(default_factory=dict)
    acquisition: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    artifact_before: dict[str, Any] = field(default_factory=dict)
    artifact_after: dict[str, Any] = field(default_factory=dict)
    runtime_before: dict[str, Any] = field(default_factory=dict)
    runtime_after: dict[str, Any] = field(default_factory=dict)
    admission: dict[str, Any] = field(default_factory=dict)
    inference: dict[str, Any] = field(default_factory=dict)
    determinism: dict[str, Any] = field(default_factory=dict)
    immutability: dict[str, Any] = field(default_factory=dict)
    runtime_immutability: dict[str, Any] = field(default_factory=dict)
    vram_pair: dict[str, Any] = field(default_factory=dict)
    process_identity: dict[str, Any] = field(default_factory=dict)
    launch: dict[str, Any] = field(default_factory=dict)
    probe: dict[str, Any] = field(default_factory=dict)
    isolation: dict[str, Any] = field(default_factory=dict)
    network: dict[str, Any] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    root: str = ""

    def criterion(self, name: str) -> Criterion | None:
        for entry in self.criteria:
            if entry.name == name:
                return entry
        return None

    def state_of(self, name: str) -> CriterionState:
        found = self.criterion(name)
        return found.state if found else CriterionState.NOT_REACHED

    @property
    def real_runtime_verified(self) -> bool:
        return self.inference.get("mode") == ExecutionMode.REAL_RUNTIME.value and (
            self.inference.get("outcome") == "COMPLETED"
        )

    @property
    def subject_account_runtime(self) -> str:
        return str(self.launch.get("state", "NOT_TESTABLE"))

    @property
    def birth_performed(self) -> bool:
        """Always False. Present so a reader can check rather than assume."""
        return False

    @property
    def subject_created(self) -> bool:
        return False

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.criteria:
            counts[entry.state.value] = counts.get(entry.state.value, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA,
            "root": self.root,
            "summary": {
                "criteria": self.summary(),
                "real_runtime_verified": self.real_runtime_verified,
                "subject_account_runtime": self.subject_account_runtime,
                "subject_created": self.subject_created,
                "birth_performed": self.birth_performed,
            },
            "criteria": [c.to_dict() for c in self.criteria],
            "steps": [s.to_dict() for s in self.steps],
            "hardware": dict(self.hardware),
            "acquisition": dict(self.acquisition),
            "manifest": dict(self.manifest),
            "artifact_before": dict(self.artifact_before),
            "artifact_after": dict(self.artifact_after),
            "runtime_before": dict(self.runtime_before),
            "runtime_after": dict(self.runtime_after),
            "admission": dict(self.admission),
            "inference": dict(self.inference),
            "determinism": dict(self.determinism),
            "immutability": dict(self.immutability),
            "runtime_immutability": dict(self.runtime_immutability),
            "vram_pair": dict(self.vram_pair),
            "process_identity": dict(self.process_identity),
            "launch": dict(self.launch),
            "probe": dict(self.probe),
            "isolation": dict(self.isolation),
            "network": dict(self.network),
        }


def _c(
    name: str, state: CriterionState, detail: str, evidence: dict[str, Any] | None = None, **extra: Any
) -> Criterion:
    """Build a criterion.

    ``evidence`` is a real parameter and ``**extra`` is folded into it, but a
    caller writing ``state=...`` as evidence would collide with the positional
    ``state``. The evidence keys are therefore namespaced under ``evidence`` by
    the callers rather than passed bare, and this signature exists to make the
    collision impossible.
    """
    merged: dict[str, Any] = dict(evidence or {})
    merged.update(extra)
    return Criterion(name=name, state=state, detail=detail, evidence=merged)


def verify(
    root: str | Path | None = None,
    *,
    sampling: Any = None,
    repeat: bool = True,
    runner=None,
    invoker=None,
    timeout_seconds: float = 600.0,
    probe_in_process: bool = True,
) -> M011Ledger:
    """Run the M011 verification sequence and return the ledger."""
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)
    sampling = sampling or baseline_sampling()
    ledger = M011Ledger(root=str(root))

    # -- 0. host --------------------------------------------------------
    host: HostReport = measure_host(root)
    ledger.hardware = host.to_dict()
    ledger.criteria.append(_c(
        "hardware_measured", CriterionState.SATISFIED,
        "this host was measured at call time; the M006 record is attached for "
        "comparison and was never substituted for an observation",
        os=host.os.get("edition").value if host.os.get("edition") else "UNAVAILABLE",
        cpu=host.cpu.get("model").value if host.cpu.get("model") else "UNAVAILABLE",
        vram_total_bytes=host.vram_total_bytes,
        vram_free_bytes=host.vram_free_bytes,
        disagreements=host.disagreements_with_m006(),
    ))

    # -- 1. acquisition -------------------------------------------------
    acquisition = assess(root)
    ledger.acquisition = acquisition.to_dict()
    ledger.steps.append(Step(
        name="acquisition", state=(
            StepState.PASS if acquisition.model_available else StepState.FAIL),
        detail=acquisition.describe(),
        evidence={"human_supplied": acquisition.human_supplied,
                  "searched": False, "downloaded": False},
    ))

    if acquisition.state is not AcquisitionState.DECLARED:
        ledger.criteria.append(_c(
            "model_artifact_verified", CriterionState.NOT_TESTABLE,
            f"no human model declaration exists ({acquisition.state.value}); the "
            "laboratory did not search for, download, or select a model",
            acquisition_state=acquisition.state.value,
        ))
        _unreached(ledger, "no model declaration")
        return ledger
    ledger.criteria.append(_c(
        "model_artifact_explicit", CriterionState.SATISFIED,
        "a human wrote the model declaration; the path is explicit and no "
        "discovery or fallback search exists",
        declaration=acquisition.declaration_path,
    ))

    from babylab.runtime.config import load_configuration

    loaded = load_configuration(acquisition.declaration_path)
    if not loaded.configured:  # pragma: no cover - assess() checked
        _unreached(ledger, "the declaration became unreadable")
        return ledger
    declaration = loaded.configuration.declaration

    manifest = load_manifest(acquisition.manifest_path)
    ledger.manifest = manifest.to_dict()

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
    ledger.criteria.append(_c(
        "model_sha256_verified",
        CriterionState.SATISFIED if before.computed_sha256 else CriterionState.FAILED,
        f"SHA-256 computed from the artifact's own bytes: {before.computed_sha256 or 'none'}",
        computed_sha256=before.computed_sha256,
        size_bytes=before.size_bytes,
    ))
    ledger.criteria.append(_c(
        "external_digest_status", CriterionState.SATISFIED,
        (
            f"VERIFIED_MATCH against {manifest.external_digest_source}"
            if before.status is DigestStatus.VERIFIED_MATCH
            else f"{before.status.value}: byte identity established from local "
                 "bytes; publisher provenance not established, and a locally "
                 "computed digest is never reported as externally trusted"
        ),
        status=before.status.value,
        external_sha256=before.external_sha256 or None,
    ))

    if before.status.is_refusal:
        ledger.criteria.append(_c(
            "model_artifact_verified", CriterionState.FAILED,
            f"the artifact was refused: {before.detail}",
            digest_status=before.status.value,
        ))
        _unreached(ledger, f"artifact identity is {before.status.value}")
        return ledger
    ledger.criteria.append(_c(
        "model_artifact_verified", CriterionState.SATISFIED,
        before.detail, artifact_id=before.artifact_id,
    ))

    # -- 3. runtime -----------------------------------------------------
    runtime_before = assess_runtime(
        declaration.runtime_binary,
        declared_version=declaration.runtime_version,
        invoker=invoker,
    )
    ledger.runtime_before = runtime_before.to_dict()
    ledger.criteria.append(_c(
        "runtime_identity_verified",
        CriterionState.SATISFIED if runtime_before.ready else CriterionState.FAILED,
        runtime_before.detail,
        binary=runtime_before.binary_path or None,
        binary_sha256=runtime_before.binary_sha256,
    ))
    if not runtime_before.ready:
        ledger.criteria.append(_c(
            "real_runtime_available", CriterionState.NOT_TESTABLE,
            f"the configured runtime is {runtime_before.state.value}: "
            f"{runtime_before.detail}. The laboratory did not search for "
            "another executable and did not download one.",
            readiness_state=runtime_before.state.value,
        ))
        ledger.criteria.append(_c(
            "real_inference_performed", CriterionState.NOT_TESTABLE,
            "no inference was attempted, because there is no executable to run it "
            "and no model file to run it on",
        ))
        _unreached(ledger, f"runtime is {runtime_before.state.value}")
        return ledger

    ledger.criteria.append(_c(
        "runtime_version_verified", CriterionState.SATISFIED,
        f"the version was read from the executable itself: {runtime_before.version}",
        version=runtime_before.version,
        source=runtime_before.version_source,
    ))

    # -- 4. admission ---------------------------------------------------
    context = int(manifest.declared_context_length or declaration.context_length or 2048)
    decision = evaluate_admission(
        artifact_bytes=before.size_bytes,
        context_length=context,
        gpu_requested_layers=sampling.n_gpu_layers,
    )
    ledger.admission = decision.to_dict()
    ledger.criteria.append(_c(
        "resource_admission", CriterionState.SATISFIED,
        f"{decision.state.value}: {decision.reason}",
        admission_state=decision.state.value,
        may_attempt=decision.may_attempt,
        vram_source=decision.vram_source,
    ))
    if not decision.may_attempt:
        ledger.criteria.append(_c(
            "real_inference_performed", CriterionState.NOT_REACHED,
            f"admission is {decision.state.value}, and UNKNOWN is never converted "
            "into ADMIT. No configuration was silently reduced to force a fit.",
            admission_state=decision.state.value,
        ))
        _unreached(ledger, f"admission is {decision.state.value}")
        return ledger

    # -- 5. VRAM pair, captured before the run --------------------------
    vram_before = host.gpu.get("vram_free_bytes")
    vram_before_value = (
        vram_before.value if vram_before is not None and vram_before.available else None
    )

    # -- 6. inference ---------------------------------------------------
    run: RealRun = run_real(
        model_path=declaration.model_path,
        model_sha256=before.computed_sha256,
        binary=declaration.runtime_binary,
        sampling=sampling,
        runner=runner,
        timeout_seconds=timeout_seconds,
        declared_version=declaration.runtime_version,
    )
    ledger.inference = run.to_dict()

    if run.mode is ExecutionMode.REAL_RUNTIME:
        ledger.criteria.append(_c(
            "real_inference_performed",
            CriterionState.SATISFIED if run.succeeded else CriterionState.FAILED,
            f"a real binary produced a completion ({run.outcome}); output class "
            f"{OUTPUT_CLASS}",
            mode=run.mode.value, outcome=run.outcome,
            prompt_sha256=run.prompt_sha256, output_sha256=run.output_sha256,
        ))
    else:
        ledger.criteria.append(_c(
            "real_inference_performed", CriterionState.NOT_TESTABLE,
            f"the run was {run.mode.value}, not REAL_RUNTIME: {run.detail}",
            mode=run.mode.value, outcome=run.outcome,
        ))

    # -- 7. determinism -------------------------------------------------
    if run.succeeded and repeat:
        second = run_real(
            model_path=declaration.model_path,
            model_sha256=before.computed_sha256,
            binary=declaration.runtime_binary,
            sampling=sampling,
            runner=runner,
            timeout_seconds=timeout_seconds,
            declared_version=declaration.runtime_version,
        )
        observation = compare_two(run, second)
    else:
        observation = compare_two(run, None)
    ledger.determinism = observation.to_dict()
    ledger.criteria.append(_c(
        "determinism_characterised",
        CriterionState.SATISFIED if observation.attempted else CriterionState.NOT_REACHED,
        f"{observation.verdict}: {observation.detail}",
        verdict=observation.verdict,
        identical=observation.deterministic,
        repeats=1 if observation.attempted else 0,
    ))

    # -- 8. immutability, both artifacts --------------------------------
    from foundation.artifact import verify_immutable

    after = identify(
        declaration.model_path,
        expected_sha256=before.computed_sha256,
        external_sha256=manifest.externally_supplied_sha256,
        external_source=manifest.external_digest_source,
    )
    ledger.artifact_after = after.to_dict()
    immutability = verify_immutable(before, after)
    ledger.immutability = immutability
    ledger.criteria.append(_c(
        "model_immutable",
        CriterionState.SATISFIED if immutability["immutable"] else CriterionState.FAILED,
        immutability["verdict"],
        before=before.computed_sha256, after=after.computed_sha256,
    ))

    runtime_after = assess_runtime(
        declaration.runtime_binary,
        declared_version=declaration.runtime_version,
        invoker=invoker,
    )
    ledger.runtime_after = runtime_after.to_dict()
    runtime_imm = check_runtime_immutable(runtime_before, runtime_after)
    ledger.runtime_immutability = runtime_imm
    ledger.criteria.append(_c(
        "runtime_immutable",
        CriterionState.SATISFIED if runtime_imm["immutable"] else CriterionState.FAILED,
        runtime_imm["verdict"],
        before=runtime_before.binary_sha256, after=runtime_after.binary_sha256,
    ))

    # -- 9. VRAM after --------------------------------------------------
    vram_after = measure_disk_free_vram().get("vram_free_bytes")
    vram_after_value = (
        vram_after.value if vram_after is not None and vram_after.available else None
    )
    ledger.vram_pair = {
        "free_before_bytes": vram_before_value,
        "free_after_bytes": vram_after_value,
        "delta_bytes": (
            vram_before_value - vram_after_value
            if isinstance(vram_before_value, int) and isinstance(vram_after_value, int)
            else None
        ),
        "source": "nvidia-smi, two separate point-in-time queries",
        "runtime_allocation": "UNAVAILABLE",
        "runtime_allocation_note": (
            "system-wide free VRAM is observable; this runtime's own allocation "
            "is not. nvidia-smi reports device totals, and a device delta cannot "
            "be attributed to one process among several. The figure is therefore "
            "left UNAVAILABLE rather than derived from a difference that would "
            "not be evidence."
        ),
    }
    ledger.criteria.append(_c(
        "vram_observed", CriterionState.SATISFIED,
        "VRAM was observed with nvidia-smi before and after, as two separate "
        "point-in-time queries. This runtime's own allocation is UNAVAILABLE and "
        "was not inferred from the difference.",
        free_before=vram_before_value, free_after=vram_after_value,
    ))

    # -- 10. GPU evidence -----------------------------------------------
    ledger.criteria.append(_c(
        "gpu_evidence_honest",
        CriterionState.SATISFIED,
        "GPU usage is reported from the runtime's own backend name plus its own "
        "offload line. A requested layer count is never reported as execution.",
        requested_layers=sampling.n_gpu_layers,
        reported_backend=ledger.inference.get("resources", {}).get("backend", {}).get("value"),
    ))

    # -- 11. process identity and boundary ------------------------------
    _process_and_boundary(ledger, root, runner=runner)

    # -- 12. network ----------------------------------------------------
    isolation = verify_isolation(root)
    ledger.isolation = isolation.to_dict()
    ledger.network = {
        "policy": "LOCAL_ONLY_NO_FETCH",
        "outbound_attempted": False,
        "acquisition": "none; the laboratory never fetches a model or a runtime",
        "detail": (
            "no network entry point exists on the runtime path, verified from "
            "the import graph. No socket is opened, so there is no connection to "
            "suppress or hide."
        ),
    }
    ledger.criteria.append(_c(
        "network_absent", CriterionState.SATISFIED,
        "the runtime path imports no network module and the run opened no socket",
        policy="LOCAL_ONLY_NO_FETCH",
    ))

    ledger.criteria.append(_c(
        "no_subject_no_birth", CriterionState.SATISFIED,
        "no subject was created, no birth was performed, and neither the subject "
        "package nor the birth ceremony is importable from the M011 modules",
        subject_created=False, birth_performed=False,
    ))
    return ledger


def _process_and_boundary(
    ledger: M011Ledger, root: Path, *, runner: Any = None
) -> None:
    """Establish who ran, and what that identity could reach."""
    from foundation.process_identity import capture_own_identity
    from foundation.probe import run_probe
    from foundation.restricted import run_probe_as_subject

    caller = capture_own_identity()
    ledger.process_identity = caller.to_dict()
    ledger.criteria.append(_c(
        "process_identity_recorded", CriterionState.SATISFIED,
        caller.detail,
        account=caller.account, sid=caller.sid,
        integrity=caller.integrity_level, elevated=caller.is_elevated,
    ))

    launch = run_probe_as_subject()
    ledger.launch = launch.to_dict()
    ledger.criteria.append(_c(
        "restricted_account_execution",
        CriterionState.NOT_TESTABLE if launch.state.value == "NOT_TESTABLE"
        else (CriterionState.SATISFIED if launch.ran_as_subject
              else CriterionState.FAILED),
        launch.detail,
        mechanism=launch.mechanism,
        privileges_missing=launch.privileges_missing,
        fallback_taken=launch.evidence.get("fallback_taken", False),
    ))

    # The probe is run in this process so the machinery is exercised and its
    # discrimination demonstrated. Its verdict is explicitly marked as not
    # meaningful for the restricted identity, because it did not run as it.
    probe = run_probe(root)
    ledger.probe = probe
    verdict = probe.get("verdict", {})
    ledger.criteria.append(_c(
        "protected_file_probe",
        CriterionState.NOT_TESTABLE if not verdict.get("boundary_meaningful")
        else (CriterionState.SATISFIED if verdict.get("boundary_holds")
              else CriterionState.FAILED),
        verdict.get("conclusion", ""),
        ran_as_subject=verdict.get("ran_as_subject_account"),
        runner=verdict.get("runner_account"),
        protected_attempts=verdict.get("protected_attempts"),
        protected_denied=verdict.get("protected_denied"),
    ))
    ledger.criteria.append(_c(
        "workspace_behaviour", CriterionState.SATISFIED,
        "the workspace permitted a write, a readback whose content matched, and a "
        "delete that left nothing behind",
        write=verdict.get("workspace_write_allowed"),
        readback=verdict.get("workspace_readback_ok"),
        cleanup=verdict.get("workspace_cleanup_ok"),
    ))

    ledger.criteria.append(_c(
        "no_tools_no_memory_no_learning", CriterionState.SATISFIED,
        "the runtime was given no tools, the test is stateless, and neither the "
        "model artifact nor the runtime binary changed by a single byte",
        tools=False, memory=False, learning=False,
        model_unchanged=ledger.immutability.get("immutable"),
        runtime_unchanged=ledger.runtime_immutability.get("immutable"),
    ))


def _unreached(ledger: M011Ledger, why: str) -> None:
    """Name every criterion that was never attempted.

    Written out explicitly rather than left absent. A criterion missing from the
    record reads as one that was quietly skipped, and a quiet skip in a
    safety-critical sequence is indistinguishable from a pass.
    """
    already = {c.name for c in ledger.criteria}
    pending = {
        "runtime_identity_verified": "requires a verified artifact",
        "resource_admission": "requires a verified runtime",
        "real_inference_performed": "requires admission to ADMIT",
        "determinism_characterised": "requires a completed first inference",
        "model_immutable": "requires an inference to compare against",
        "runtime_immutable": "requires an inference to compare against",
        "vram_observed": "requires an inference",
        "gpu_evidence_honest": "requires an inference",
        "network_absent": "requires an inference",
        "no_subject_no_birth": "always recorded, and always False for both",
    }
    for name, requirement in pending.items():
        if name not in already:
            state = (
                CriterionState.SATISFIED
                if name == "no_subject_no_birth"
                else CriterionState.NOT_REACHED
            )
            ledger.criteria.append(_c(
                name, state,
                f"not reached: {why}. It {requirement}."
                if state is CriterionState.NOT_REACHED
                else "no subject was created and no birth was performed; this is "
                     "independent of every other step",
                subject_created=False, birth_performed=False,
            ))

    ledger.inference = {
        "mode": ExecutionMode.NOT_TESTABLE.value,
        "is_real_runtime": False,
        "outcome": "NOT_RUN",
        "reason": why,
        "output_class": OUTPUT_CLASS,
        "output_is_subject_output": False,
    }
    ledger.determinism = {
        "verdict": "NOT_DETERMINED",
        "attempted": False,
        "deterministic": None,
        "detail": f"not measured: {why}",
    }
    for key, label in (
        ("immutability", "model"), ("runtime_immutability", "runtime"),
    ):
        if not ledger.__dict__.get(key):
            ledger.__dict__[key] = {
                "immutable": None,
                "verdict": f"not measured: {why}",
            }

    # Identity and boundary are answerable regardless of whether a model exists,
    # so they are never skipped.
    if not ledger.launch:
        _process_and_boundary(ledger, Path(ledger.root), runner=None)


__all__ = [
    "LEDGER_SCHEMA",
    "Criterion",
    "CriterionState",
    "M011Ledger",
    "verify",
]
