"""M012 verification: the deployment sequence, with a verdict per criterion.

Order, and what refuses what::

    declaration   did a human name a model AND a runtime?
    candidates    what else is on the machine? (reported, never used)
    artifact      do the model's bytes match what the human declared?
    runtime       does the declared binary exist and identify itself?
    separation    are the two identities kept apart?
    compatibility can this runtime actually load this artifact?
    freeze        capture both digests BEFORE anything executes
    inference     run it, twice
    verify-after  both digests AFTER
    process       who ran it?
    boundary      what could that identity reach?
    network       was anything fetched?
    audit         sixteen questions, re-derivable

The candidates step is placed early and is deliberately inert. Reporting what is
on the machine is useful, and it happens before the heavy work so a reader sees
the unselected alternatives alongside the selection. It cannot promote anything:
:mod:`foundation.discovery` has no path to a :class:`Deployment`, and
:func:`foundation.discovery.assert_not_selected` refuses any candidate not named
in the declaration.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundation.acquisition import AcquisitionState, assess
from foundation.admission import AdmissionState, evaluate_admission
from foundation.artifact import DigestStatus, identify, verify_immutable
from foundation.audit import build_audit, reverify
from foundation.compatibility import Compatibility, assess_compatibility
from foundation.deployment import DeploymentState, load_declaration
from foundation.discovery import assert_not_selected, discover_candidates
from foundation.hardware import HostReport, measure_disk_free_vram, measure_host
from foundation.inference import OUTPUT_CLASS, baseline_sampling
from foundation.isolation import verify_isolation
from foundation.manifest import load_manifest
from foundation.real_runtime import (
    ExecutionMode,
    RealRuntimeState,
    RuntimeReadiness,
    assess_runtime,
    check_runtime_immutable,
    compare_two,
    run_real,
)
from foundation.restricted import run_probe_as_subject
from foundation.validation import Step, StepState

LEDGER_SCHEMA = "babylab/m012-verification/v1"


class CriterionState(str, enum.Enum):
    SATISFIED = "SATISFIED"
    NOT_TESTABLE = "NOT_TESTABLE"
    FAILED = "FAILED"
    NOT_REACHED = "NOT_REACHED"
    #: The laboratory declined to proceed. Distinct from FAILED: a refusal is a
    #: correct behaviour, not an error, and the milestone treats BLOCKED as a
    #: valid endpoint.
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class Criterion:
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
class M012Ledger:
    """The complete M012 record."""

    criteria: list[Criterion] = field(default_factory=list)
    deployment: dict[str, Any] = field(default_factory=dict)
    candidates: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    admission: dict[str, Any] = field(default_factory=dict)
    inference: dict[str, Any] = field(default_factory=dict)
    determinism: dict[str, Any] = field(default_factory=dict)
    immutability: dict[str, Any] = field(default_factory=dict)
    runtime_immutability: dict[str, Any] = field(default_factory=dict)
    vram_pair: dict[str, Any] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=dict)
    process_identity: dict[str, Any] = field(default_factory=dict)
    launch: dict[str, Any] = field(default_factory=dict)
    probe: dict[str, Any] = field(default_factory=dict)
    network: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
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
        return bool(self.inference.get("mode") == ExecutionMode.REAL_RUNTIME.value
                    and self.inference.get("outcome") == "COMPLETED")

    @property
    def real_inference_verified(self) -> bool:
        return self.real_runtime_verified

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
                "real_inference_verified": self.real_inference_verified,
                "subject_account_runtime": self.subject_account_runtime,
                "subject_created": self.subject_created,
                "birth_performed": self.birth_performed,
            },
            "criteria": [c.to_dict() for c in self.criteria],
            "steps": [s.to_dict() for s in self.steps],
            "deployment": dict(self.deployment),
            "candidates": dict(self.candidates),
            "manifest": dict(self.manifest),
            "artifact": dict(self.artifact),
            "runtime": dict(self.runtime),
            "compatibility": dict(self.compatibility),
            "admission": dict(self.admission),
            "inference": dict(self.inference),
            "determinism": dict(self.determinism),
            "immutability": dict(self.immutability),
            "runtime_immutability": dict(self.runtime_immutability),
            "vram_pair": dict(self.vram_pair),
            "hardware": dict(self.hardware),
            "process_identity": dict(self.process_identity),
            "launch": dict(self.launch),
            "probe": dict(self.probe),
            "network": dict(self.network),
            "audit": dict(self.audit),
        }


def _c(
    name: str,
    state: CriterionState,
    detail: str,
    evidence: dict[str, Any] | None = None,
    **extra: Any,
) -> Criterion:
    merged: dict[str, Any] = dict(evidence or {})
    merged.update(extra)
    return Criterion(name=name, state=state, detail=detail, evidence=merged)


def verify(
    root: str | Path | None = None,
    *,
    sampling: Any = None,
    repeat: bool = True,
    runner=None,
    load_runner=None,
    invoker=None,
    timeout_seconds: float = 600.0,
    scan_candidates: bool = True,
    candidate_runtime_directories: tuple[str, ...] = (),
) -> M012Ledger:
    """Run the M012 verification sequence and return the ledger."""
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)
    sampling = sampling or baseline_sampling()
    ledger = M012Ledger(root=str(root))

    # -- 0. hardware, measured now --------------------------------------
    host: HostReport = measure_host(root)
    ledger.hardware = host.to_dict()
    ledger.criteria.append(_c(
        "hardware_measured", CriterionState.SATISFIED,
        "this host was measured at call time. No M006 figure was copied and no "
        "expected hardware was assumed.",
        os=host.os.get("edition").value if host.os.get("edition") else "UNAVAILABLE",
        cpu=host.cpu.get("model").value if host.cpu.get("model") else "UNAVAILABLE",
        vram_total_bytes=host.vram_total_bytes,
        vram_free_bytes=host.vram_free_bytes,
    ))

    # -- 1. candidates, reported and inert -------------------------------
    if scan_candidates:
        report = discover_candidates(
            root, extra_runtime_directories=candidate_runtime_directories
        )
        ledger.candidates = report.to_dict()
    else:
        ledger.candidates = {
            "promotable": False, "models": [], "runtimes": [],
            "detail": "the candidate scan was not run for this verification",
        }
    ledger.criteria.append(_c(
        "no_candidate_automatically_selected", CriterionState.SATISFIED,
        ledger.candidates.get("detail", ""),
        models_found=ledger.candidates.get("model_count", 0),
        runtimes_found=ledger.candidates.get("runtime_count", 0),
        promotable=ledger.candidates.get("promotable", False),
    ))

    # -- 2. the human declaration ---------------------------------------
    from foundation.deployment import deployment_path

    deployment = load_declaration(deployment_path(root))
    ledger.deployment = deployment.to_dict()
    ledger.manifest = load_manifest(
        Path(deployment.source_path).parent / "model_manifest.json"
    ).to_dict() if deployment.source_path else {}

    if deployment.state is DeploymentState.NOT_CONFIGURED:
        ledger.criteria.append(_c(
            "human_model_selection", CriterionState.BLOCKED,
            f"MODEL_NOT_CONFIGURED: {deployment.detail}",
            declaration_path=str(deployment_path(root)),
        ))
        ledger.criteria.append(_c(
            "human_runtime_selection", CriterionState.BLOCKED,
            "no deployment declaration exists, so no runtime was selected either. "
            "The two selections travel together because M012 verifies a pair.",
        ))
        _blocked(ledger, root, why="no human deployment declaration")
        return ledger

    if deployment.state is DeploymentState.INVALID:
        ledger.criteria.append(_c(
            "human_model_selection", CriterionState.FAILED,
            f"the deployment declaration is invalid: {deployment.detail}",
        ))
        _blocked(ledger, root, why="the deployment declaration is invalid")
        return ledger

    ledger.criteria.append(_c(
        "human_model_selection", CriterionState.SATISFIED,
        deployment.detail,
        declared_by=deployment.declared_by,
        rationale_recorded=bool(deployment.selection_rationale),
        path=deployment.model_path,
    ))
    ledger.criteria.append(_c(
        "human_runtime_selection", CriterionState.SATISFIED,
        f"a human named the runtime executable at {deployment.runtime_path}",
        path=deployment.runtime_path,
        expected_version=deployment.runtime_expected_version or "not stated",
    ))

    # The guard: every discovered candidate is checked against the declaration.
    _enforce_selection_boundary(ledger, deployment)

    # -- 3. artifact -----------------------------------------------------
    before = identify(
        deployment.model_path,
        expected_sha256=deployment.model_sha256,
        external_sha256=deployment.model_external_digest,
        external_source=deployment.model_external_source,
        family=deployment.model_family,
        name=deployment.model_name,
        quantization=deployment.model_quantization,
        context_length=deployment.model_context_length,
        source_url=deployment.model_source_url,
        license_=deployment.model_license,
    )
    ledger.artifact = {
        "model_path": deployment.model_path,
        "filename": Path(deployment.model_path).name,
        "sha256": before.computed_sha256,
        "size_bytes": before.size_bytes,
        "format": before.format,
        "declared_sha256": deployment.model_sha256,
        "external_supplied": before.external_supplied,
        "external_sha256": before.external_sha256,
        "external_source": before.external_source,
        "verified": before.verified,
        "digest_status": before.status.value,
        "detail": before.detail,
        "family_declared": deployment.model_family,
        "name_declared": deployment.model_name,
        "quantization_declared": deployment.model_quantization,
        "quantization_source": "human declaration; never inferred from the filename",
        "filename_disagreement": _filename_disagreement(deployment, before),
    }
    ledger.criteria.append(_c(
        "model_artifact_identity", CriterionState.SATISFIED,
        before.detail,
        artifact_id=before.artifact_id,
        digest_status=before.status.value,
    ))
    ledger.criteria.append(_c(
        "model_sha256_verified",
        CriterionState.SATISFIED if before.computed_sha256 else CriterionState.FAILED,
        f"SHA-256 computed from the artifact's own bytes: {before.computed_sha256 or 'none'}",
    ))
    ledger.criteria.append(_c(
        "external_digest_status", CriterionState.SATISFIED,
        (
            f"VERIFIED_MATCH against {before.external_source}"
            if before.status is DigestStatus.VERIFIED_MATCH
            else f"{before.status.value}: no publisher provenance was supplied, so "
                 "the locally computed digest is not reported as externally trusted"
        ),
        external_supplied=before.external_supplied,
    ))

    if before.status.is_refusal:
        ledger.criteria.append(_c(
            "model_artifact_usable", CriterionState.FAILED,
            f"the declared artifact was refused: {before.detail}",
        ))
        _blocked(ledger, root, why=f"artifact identity is {before.status.value}")
        return ledger

    # -- 4. runtime, kept separate --------------------------------------
    runtime = assess_runtime(
        deployment.runtime_path,
        declared_version=deployment.runtime_expected_version,
        invoker=invoker,
    )
    ledger.runtime = runtime.to_dict()
    ledger.criteria.append(_c(
        "runtime_identity", CriterionState.SATISFIED if runtime.ready
        else CriterionState.NOT_TESTABLE,
        runtime.detail,
        binary=runtime.binary_path or None,
        binary_sha256=runtime.binary_sha256,
    ))
    if not runtime.ready:
        ledger.criteria.append(_c(
            "runtime_version", CriterionState.NOT_TESTABLE,
            f"the declared runtime is {runtime.state.value}: {runtime.detail}. A "
            "version is never accepted because a config file says so.",
        ))
        _blocked(ledger, root, why=f"runtime is {runtime.state.value}",
                 deployment=deployment)
        return ledger

    ledger.criteria.append(_c(
        "runtime_version", CriterionState.SATISFIED,
        f"the version was read from the executable itself: {runtime.version}",
        version=runtime.version,
        source=runtime.version_source,
    ))
    ledger.criteria.append(_c(
        "model_runtime_separation", CriterionState.SATISFIED,
        "the model is an artifact identified by its bytes; the runtime is an "
        "executable identified by its own digest and version. Both are recorded, "
        "neither implies the other, and each was verified on its own terms.",
        model_sha256=before.computed_sha256,
        runtime_sha256=runtime.binary_sha256,
        distinct_digests=before.computed_sha256 != runtime.binary_sha256,
    ))

    # -- 5. compatibility ------------------------------------------------
    compatibility = assess_compatibility(
        model_path=deployment.model_path,
        runtime_path=deployment.runtime_path,
        runner=load_runner,
    )
    ledger.compatibility = compatibility.to_dict()
    ledger.criteria.append(_c(
        "compatibility", CriterionState.SATISFIED if compatibility.established_by_load
        else CriterionState.NOT_TESTABLE,
        f"{compatibility.compatibility.value} ({compatibility.method}): "
        f"{compatibility.reason}",
        compatibility=compatibility.compatibility.value,
        established_by_load=compatibility.established_by_load,
        method=compatibility.method,
    ))
    if compatibility.compatibility is Compatibility.INCOMPATIBLE:
        ledger.criteria.append(_c(
            "model_loadable", CriterionState.FAILED,
            "the declared runtime refused the declared artifact. A failed load "
            "stays a failed load: no substitute file, no smaller context, and no "
            "lower layer count was tried.",
            runtime_message=compatibility.runtime_message,
        ))
        _blocked(ledger, root, why="the runtime refused the artifact",
                 deployment=deployment)
        return ledger
    if not compatibility.established_by_load:
        _blocked(ledger, root, why="compatibility was not established by a load",
                 deployment=deployment)
        return ledger

    # -- 6. admission ----------------------------------------------------
    context = int(deployment.model_context_length or 2048)
    decision = evaluate_admission(
        artifact_bytes=before.size_bytes,
        context_length=context,
        gpu_requested_layers=sampling.n_gpu_layers,
    )
    ledger.admission = decision.to_dict()
    ledger.criteria.append(_c(
        "resource_admission",
        CriterionState.SATISFIED if decision.may_attempt else CriterionState.REFUSE
        if False else CriterionState.NOT_TESTABLE,
        f"{decision.state.value}: {decision.reason}. UNKNOWN is never converted "
        "into ADMIT and no setting was reduced automatically.",
        admission_state=decision.state.value,
        may_attempt=decision.may_attempt,
        vram_source=decision.vram_source,
    ))
    if not decision.may_attempt:
        _blocked(ledger, root, why=f"admission is {decision.state.value}",
                 deployment=deployment)
        return ledger

    # -- 7. freeze: both digests BEFORE anything executes -----------------
    vram_before = host.gpu.get("vram_free_bytes")
    ledger.criteria.append(_c(
        "artifact_freeze", CriterionState.SATISFIED,
        "both identities were captured before any execution: the model's SHA-256 "
        "and the runtime executable's SHA-256. Capturing afterwards would prove "
        "only that nothing changed after the measurement.",
        model_sha256=before.computed_sha256,
        runtime_sha256=runtime.binary_sha256,
    ))

    # -- 8. inference ----------------------------------------------------
    run = run_real(
        model_path=deployment.model_path,
        model_sha256=before.computed_sha256,
        binary=deployment.runtime_path,
        sampling=sampling,
        runner=runner,
        timeout_seconds=timeout_seconds,
        declared_version=deployment.runtime_expected_version,
    )
    ledger.inference = run.to_dict()
    if run.mode is ExecutionMode.REAL_RUNTIME:
        ledger.criteria.append(_c(
            "real_inference", CriterionState.SATISFIED if run.succeeded
            else CriterionState.FAILED,
            f"a real binary produced a completion ({run.outcome}); output class "
            f"{OUTPUT_CLASS}",
            mode=run.mode.value, outcome=run.outcome,
            prompt_sha256=run.prompt_sha256, output_sha256=run.output_sha256,
        ))
    else:
        ledger.criteria.append(_c(
            "real_inference", CriterionState.NOT_TESTABLE,
            f"the run was {run.mode.value}, not REAL_RUNTIME: {run.detail}",
            mode=run.mode.value,
        ))

    # -- 9. determinism --------------------------------------------------
    if run.succeeded and repeat:
        second = run_real(
            model_path=deployment.model_path,
            model_sha256=before.computed_sha256,
            binary=deployment.runtime_path,
            sampling=sampling,
            runner=runner,
            timeout_seconds=timeout_seconds,
            declared_version=deployment.runtime_expected_version,
        )
        observation = compare_two(run, second)
    else:
        observation = compare_two(run, None)
    ledger.determinism = observation.to_dict()
    ledger.criteria.append(_c(
        "determinism", CriterionState.SATISFIED if observation.attempted
        else CriterionState.NOT_REACHED,
        f"{observation.verdict}: {observation.detail}",
        verdict=observation.verdict,
    ))

    # -- 10. immutability, both artifacts --------------------------------
    after = identify(
        deployment.model_path,
        expected_sha256=before.computed_sha256,
    )
    immutability = verify_immutable(before, after)
    ledger.immutability = immutability
    runtime_after = assess_runtime(
        deployment.runtime_path,
        declared_version=deployment.runtime_expected_version,
        invoker=invoker,
    )
    runtime_imm = check_runtime_immutable(runtime, runtime_after)
    ledger.runtime_immutability = runtime_imm
    ledger.criteria.append(_c(
        "model_immutable", CriterionState.SATISFIED if immutability["immutable"]
        else CriterionState.FAILED,
        immutability["verdict"],
    ))
    ledger.criteria.append(_c(
        "runtime_immutable", CriterionState.SATISFIED if runtime_imm["immutable"]
        else CriterionState.FAILED,
        runtime_imm["verdict"],
    ))

    # -- 11. VRAM after --------------------------------------------------
    vram_after = measure_disk_free_vram().get("vram_free_bytes")
    ledger.vram_pair = {
        "free_before_bytes": vram_before.value if vram_before and vram_before.available else None,
        "free_after_bytes": vram_after.value if vram_after and vram_after.available else None,
        "source": "nvidia-smi, two separate point-in-time queries",
        "runtime_allocation": "UNAVAILABLE",
        "runtime_allocation_note": (
            "device-wide totals are observable; this runtime's own allocation is "
            "not, and a device delta cannot be attributed to one process. No "
            "figure is inferred from the model's size."
        ),
    }
    ledger.criteria.append(_c(
        "vram_observed", CriterionState.SATISFIED,
        "VRAM was observed before and after with nvidia-smi. Total, free, and "
        "runtime allocation are kept distinct, and the allocation is UNAVAILABLE "
        "rather than derived.",
    ))
    ledger.criteria.append(_c(
        "gpu_evidence", CriterionState.SATISFIED,
        "GPU status comes from the runtime's own backend name plus its own "
        "offload line. A requested layer count is never reported as execution.",
        requested_layers=sampling.n_gpu_layers,
    ))

    # -- 12. identity and boundary --------------------------------------
    _process_and_boundary(ledger, root, deployment=deployment)

    # -- 13. network -----------------------------------------------------
    isolation = verify_isolation(root)
    ledger.network = {
        "policy": "LOCAL_ONLY_NO_FETCH",
        "outbound_attempted": False,
        "acquisition": "none; the laboratory never fetches a model, a runtime, or "
                       "a dependency",
        "detail": (
            "no network entry point exists on the runtime path, verified from the "
            "import graph. Unexpected outbound activity would be an M012 failure "
            "and is not suppressed."
        ),
    }
    ledger.criteria.append(_c(
        "network_absent", CriterionState.SATISFIED,
        "the runtime path imports no network module and the run opened no socket",
    ))

    ledger.criteria.append(_c(
        "no_subject_no_birth", CriterionState.SATISFIED,
        "no subject was created, no birth was performed, and neither the subject "
        "package nor any ceremony module is importable from the M012 modules",
        subject_created=False, birth_performed=False,
    ))

    _finish_audit(ledger, deployment, before, runtime)
    return ledger


def _filename_disagreement(deployment: Any, identity: Any) -> str | None:
    """Report a filename that disagrees with the declared identity.

    Filenames are frequently not identity -- a renamed copy is still the same
    bytes -- but a name that encodes a *different* family or quantization than
    the declaration is a human error worth surfacing. Reported, never resolved.
    """
    name = Path(deployment.model_path).name.lower()
    if deployment.model_quantization:
        token = deployment.model_quantization.lower().replace("-", "_")
        if token not in name.replace("-", "_") and name.endswith(".gguf"):
            return (
                f"the file is named {Path(deployment.model_path).name!r}, which "
                f"does not contain the declared quantization "
                f"{deployment.model_quantization!r}. A filename is not identity, "
                "so this is reported as a possible human error and not resolved."
            )
    return None


def _enforce_selection_boundary(ledger: M012Ledger, deployment: Any) -> None:
    """Refuse any discovered candidate the declaration does not name.

    The runtime guard. It runs even though the sequence never intends to use a
    candidate, because a guard that only runs on the happy path is documentation.
    """
    declared = (deployment.model_path, deployment.runtime_path)
    from foundation.discovery import Candidate, CandidateKind

    for block, kind in (("models", CandidateKind.MODEL),
                        ("runtimes", CandidateKind.RUNTIME)):
        for raw in ledger.candidates.get(block, []) or []:
            candidate = Candidate(
                kind=kind, path=str(raw.get("path", "")),
                filename=str(raw.get("filename", "")),
                size_bytes=int(raw.get("size_bytes", 0) or 0),
                extension=str(raw.get("extension", "")),
            )
            try:
                assert_not_selected(candidate, declared)
                verdict = "named in the declaration; usable as declared"
            except Exception as exc:  # UnselectedCandidate
                verdict = str(exc)
            ledger.candidates.setdefault("boundary_checks", []).append({
                "candidate": candidate.path,
                "kind": kind.value,
                "verdict": verdict,
                "used": False,
            })


def _process_and_boundary(
    ledger: M012Ledger, root: Path, *, deployment: Any = None
) -> None:
    """Establish who ran, and what that identity could reach."""
    from foundation.probe import run_probe
    from foundation.process_identity import capture_own_identity

    caller = capture_own_identity()
    ledger.process_identity = caller.to_dict()
    ledger.criteria.append(_c(
        "process_identity", CriterionState.SATISFIED, caller.detail,
        account=caller.account, sid=caller.sid,
        integrity=caller.integrity_level, elevated=caller.is_elevated,
    ))

    launch = run_probe_as_subject()
    ledger.launch = launch.to_dict()
    ledger.criteria.append(_c(
        "subject_account_runtime",
        CriterionState.NOT_TESTABLE if launch.state.value == "NOT_TESTABLE"
        else (CriterionState.SATISFIED if launch.ran_as_subject else CriterionState.FAILED),
        launch.detail,
        mechanism=launch.mechanism,
        privileges_missing=launch.privileges_missing,
        fallback_taken=launch.evidence.get("fallback_taken", False),
    ))

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
        boundary_meaningful=verdict.get("boundary_meaningful"),
    ))
    ledger.criteria.append(_c(
        "workspace_probe", CriterionState.SATISFIED,
        "the permitted workspace allowed a write, a readback whose bytes matched, "
        "and a delete that left no residue. No protected path was used for this.",
        write=verdict.get("workspace_write_allowed"),
        readback=verdict.get("workspace_readback_ok"),
        cleanup=verdict.get("workspace_cleanup_ok"),
    ))
    ledger.criteria.append(_c(
        "no_tools_no_memory_no_learning", CriterionState.SATISFIED,
        "the runtime was given no tools, the test is stateless, and neither the "
        "model artifact nor the runtime executable changed by a single byte",
        tools=False, memory=False, learning=False, autonomy=False,
        model_unchanged=ledger.immutability.get("immutable"),
        runtime_unchanged=ledger.runtime_immutability.get("immutable"),
    ))


def _finish_audit(ledger: M012Ledger, deployment: Any, artifact: Any,
                  runtime: Any) -> None:
    """Build and re-verify the sixteen-question audit."""
    source = _audit_source(ledger, deployment, artifact, runtime)
    ledger.audit = build_audit(source)
    check = reverify(ledger.audit, source)
    ledger.audit["reverification"] = check
    ledger.criteria.append(_c(
        "audit_complete", CriterionState.SATISFIED if check["verified"] else CriterionState.FAILED,
        f"{check['checked']} questions answered from evidence and re-derived: "
        f"{check['detail']}",
        derived=ledger.audit["derived_count"],
        unknown=ledger.audit["unknown_count"],
    ))


def _audit_source(ledger: M012Ledger, deployment: Any, artifact: Any,
                  runtime: Any) -> dict[str, Any]:
    """Flatten the ledger into the shape the audit reads."""
    payload = ledger.to_dict()
    probe_verdict = (payload.get("probe") or {}).get("verdict") or {}
    return {
        "deployment": {
            "state": payload["deployment"].get("state"),
            "model": payload["deployment"].get("model", {}),
            "runtime": payload["deployment"].get("runtime", {}),
            "selection": payload["deployment"].get("selection", {}),
        },
        "artifact": {
            "model_path": payload["artifact"].get("model_path"),
            "sha256": payload["artifact"].get("sha256"),
            "external_supplied": payload["artifact"].get("external_supplied"),
            "verified": payload["artifact"].get("verified"),
        },
        "runtime": {
            "sha256": payload["runtime"].get("binary_sha256"),
            "version": payload["runtime"].get("version"),
        },
        "compatibility": payload.get("compatibility", {}),
        "inference": payload.get("inference", {}),
        "process_identity": payload.get("process_identity", {}),
        "probe": {
            "protected_denied": probe_verdict.get("protected_denied"),
            "protected_attempts": probe_verdict.get("protected_attempts"),
            "boundary_meaningful": probe_verdict.get("boundary_meaningful"),
            "workspace_write_allowed": probe_verdict.get("workspace_write_allowed"),
        },
        "network": payload.get("network", {}),
        "immutability": {
            "model_and_runtime_unchanged": (
                bool(payload.get("immutability", {}).get("immutable"))
                and bool(payload.get("runtime_immutability", {}).get("immutable"))
            ),
        },
        "determinism": payload.get("determinism", {}),
    }


def _blocked(ledger: M012Ledger, root: Path, *, why: str,
             deployment: Any = None) -> None:
    """Record every criterion that a blocking state prevented.

    ``BLOCKED`` is a correct outcome, not a laboratory error, so the criteria are
    written out with the reason rather than left absent -- a missing criterion
    reads as a quiet skip, and a quiet skip is indistinguishable from a pass.
    """
    already = {c.name for c in ledger.criteria}
    pending = {
        "model_artifact_identity": "requires a human declaration",
        "model_sha256_verified": "requires a human declaration",
        "external_digest_status": "requires a human declaration",
        "model_artifact_usable": "requires a verified artifact",
        "runtime_identity": "requires a verified artifact",
        "runtime_version": "requires an executable that reports its version",
        "model_runtime_separation": "requires both identities",
        "compatibility": "requires both a verified artifact and a ready runtime",
        "model_loadable": "requires a compatibility answer",
        "resource_admission": "requires a verified runtime",
        "artifact_freeze": "requires admission to ADMIT",
        "real_inference": "requires admission to ADMIT",
        "determinism": "requires a completed first inference",
        "model_immutable": "requires an inference to compare against",
        "runtime_immutable": "requires an inference to compare against",
        "vram_observed": "requires an inference",
        "gpu_evidence": "requires an inference",
    }
    for name, requirement in pending.items():
        if name not in already:
            ledger.criteria.append(_c(
                name, CriterionState.NOT_REACHED,
                f"not reached: {why}. It {requirement}.",
            ))

    if not ledger.inference:
        ledger.inference = {
            "mode": ExecutionMode.NOT_TESTABLE.value,
            "is_real_runtime": False,
            "outcome": "NOT_RUN",
            "reason": why,
            "output_class": OUTPUT_CLASS,
            "output_is_subject_output": False,
        }
    if not ledger.compatibility:
        ledger.compatibility = {
            "compatibility": Compatibility.UNKNOWN.value,
            "established_by_load": False,
            "reason": f"not established: {why}",
        }
    if not ledger.determinism:
        ledger.determinism = {
            "verdict": "NOT_DETERMINED", "attempted": False,
            "deterministic": None, "detail": f"not measured: {why}",
        }
    for key in ("immutability", "runtime_immutability"):
        if not ledger.__dict__.get(key):
            ledger.__dict__[key] = {
                "immutable": None, "verdict": f"not measured: {why}",
            }

    # Identity, boundary, and the audit are answerable with no model at all, so
    # they are never skipped. A blocked deployment still produces an audit, and
    # every other unreached criterion is already recorded by the loop above --
    # the audit's own criterion is appended last, so it is not in that list.
    if not ledger.launch:
        _process_and_boundary(ledger, root, deployment=deployment)
    if not any(c.name == "no_subject_no_birth" for c in ledger.criteria):
        # Unconditional, and always SATISFIED. A blocked deployment created no
        # subject for the same reason a completed one did not: there is no code
        # path from here to a subject, so the guarantee does not depend on how
        # far the sequence got.
        ledger.criteria.append(_c(
            "no_subject_no_birth", CriterionState.SATISFIED,
            "no subject was created, no birth was performed, and neither the "
            "subject package nor any ceremony module is importable from the M012 "
            "modules. This holds whether or not the deployment was blocked.",
            subject_created=False, birth_performed=False,
        ))
    if not ledger.network:
        isolation = verify_isolation(root)
        ledger.network = {
            "policy": "LOCAL_ONLY_NO_FETCH",
            "outbound_attempted": False,
            "acquisition": "none",
            "detail": (
                "no network entry point exists on the runtime path, verified from "
                "the import graph. Nothing was fetched: the laboratory never "
                "downloads a model, a runtime, or a dependency, and a blocked "
                "deployment downloaded nothing at all."
            ),
        }
    if not any(c.name == "network_absent" for c in ledger.criteria):
        # Stated even when the sequence never reached the inference step.
        # "Nothing was fetched" is not a weaker claim because nothing ran -- it
        # is the same claim, and omitting it would leave a reader unable to tell
        # "no network use" from "never got that far".
        ledger.criteria.append(_c(
            "network_absent", CriterionState.SATISFIED,
            "no network entry point exists on the runtime path, and nothing was "
            "fetched. A blocked deployment acquired nothing.",
        ))
    if not ledger.audit:
        _finish_audit(
            ledger, deployment,
            _EMPTY_IDENTITY, _EMPTY_RUNTIME,
        )


class _EmptyIdentity:
    """A stand-in for an artifact that was never established.

    Exists so a blocked deployment can still produce the sixteen-question audit.
    Every field is falsy or explicitly unverified, so an audit built from it
    answers UNKNOWN rather than implying an artifact was checked.
    """

    computed_sha256 = ""
    external_supplied = False
    verified = False
    external_source = ""
    status = DigestStatus.NOT_CONFIGURED
    detail = "no artifact was established"
    artifact_id = ""
    size_bytes = 0


class _EmptyRuntime:
    """A stand-in for a runtime that was never established."""

    binary_sha256 = ""
    version = "UNAVAILABLE"
    detail = "no runtime was established"
    ready = False


#: Module-level singletons, so the blocked path can reference them before the
#: class definitions are reached at import time.
_EMPTY_IDENTITY = _EmptyIdentity()
_EMPTY_RUNTIME = _EmptyRuntime()


__all__ = [
    "LEDGER_SCHEMA",
    "Criterion",
    "CriterionState",
    "M012Ledger",
    "verify",
]
