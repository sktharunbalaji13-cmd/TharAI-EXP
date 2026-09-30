"""M012 read surface for the Observatory.

Reads a declaration and a candidate report. **Executes nothing** -- no probe, no
inference, no compatibility load, no identity launch. A view that could run the
thing it observes is not a view, and M011 established that boundary; this module
exists so M012 does not quietly break it.

Every field is a read of a file a human wrote, or an explicit "not declared".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: The M012 modules that can execute something. Named so the import-graph test
#: can assert none of them is reachable from the read surface.
M012_EXECUTION_MODULES: tuple[str, ...] = (
    "m012.py",
    "real_runtime.py",
    "restricted.py",
    "win32.py",
    "probe.py",
    "compatibility.py",
)

#: Vocabulary the M012 panel must never render. Runtime telemetry cannot
#: establish any of it, and a field for one would have to be invented to fill.
FORBIDDEN_DISPLAY_TERMS: tuple[str, ...] = (
    "intelligence",
    "consciousness",
    "conscious",
    "sentience",
    "sentient",
    "awareness",
    "personality",
    "curiosity",
    "developmental",
    "readiness",
    "learning progress",
    "motivation",
    "goals",
)


def deployment_only(root: str | Path | None = None) -> dict[str, Any]:
    """The declared selection, read from disk. Nothing is verified or executed."""
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)

    from foundation.deployment import deployment_path, load_declaration
    from foundation.discovery import discover_candidates

    deployment = load_declaration(deployment_path(root))
    candidates = discover_candidates(root)

    model = deployment.to_dict().get("model", {})
    runtime = deployment.to_dict().get("runtime", {})
    selection = deployment.to_dict().get("selection", {})

    return {
        "schema": "babylab/m012-status/v1",
        "deployment_state": deployment.state.value,
        "human_model_selection": (
            "DECLARED" if deployment.has_model else "NOT_DECLARED"
        ),
        "human_runtime_selection": (
            "DECLARED" if deployment.has_runtime else "NOT_DECLARED"
        ),
        "model_path": model.get("path") or "UNAVAILABLE",
        "model_sha256": model.get("sha256") or "UNAVAILABLE",
        "model_external_digest": model.get("external_digest") or "NOT SUPPLIED",
        "model_external_source": model.get("external_digest_source") or "none",
        "model_family": model.get("family") or "UNAVAILABLE",
        "model_quantization": model.get("quantization") or "UNAVAILABLE",
        "runtime_path": runtime.get("path") or "UNAVAILABLE",
        "runtime_expected_version": runtime.get("expected_version") or "NOT STATED",
        "runtime_implementation": runtime.get("implementation", "llama.cpp"),
        "selection_attributed": selection.get("attributed", False),
        "declared_by": selection.get("declared_by") or "UNAVAILABLE",
        "rationale_recorded": bool(selection.get("rationale")),
        "candidates_reported": {
            "models": candidates.to_dict()["model_count"],
            "runtimes": candidates.to_dict()["runtime_count"],
            "promotable": candidates.promotable,
        },
        "real_runtime": "NOT_TESTABLE",
        "real_inference": "NOT_TESTABLE",
        "compatibility": "UNKNOWN",
        "network": "LOCAL_ONLY_NO_FETCH",
        "subject": "NONE",
        "birth": "NOT_PERFORMED",
        "note": (
            "read from the deployment declaration only. This panel does not hash "
            "the artifact, probe the runtime, load a model, or run an inference: "
            "verification is a command, and a display that performed it would "
            "make its own refresh rate depend on the work it reports."
        ),
        "forbidden_display_terms": list(FORBIDDEN_DISPLAY_TERMS),
    }


def from_ledger(ledger: Any) -> dict[str, Any]:
    """Flatten a completed :class:`~foundation.m012.M012Ledger` for display."""
    payload = ledger.to_dict() if hasattr(ledger, "to_dict") else dict(ledger or {})
    artifact = payload.get("artifact") or {}
    runtime = payload.get("runtime") or {}
    probe = (payload.get("probe") or {}).get("verdict") or {}
    inference = payload.get("inference") or {}

    digest_status = artifact.get("digest_status", "UNAVAILABLE")
    external_supplied = bool(artifact.get("external_supplied"))

    return {
        "schema": "babylab/m012-status/v1",
        "deployment_state": (payload.get("deployment") or {}).get("state"),
        "human_model_selection": (
            "DECLARED" if (payload.get("deployment") or {})
            .get("model", {}).get("path") else "NOT_DECLARED"
        ),
        "human_runtime_selection": (
            "DECLARED" if (payload.get("deployment") or {})
            .get("runtime", {}).get("path") else "NOT_DECLARED"
        ),
        "model_path": artifact.get("model_path") or "UNAVAILABLE",
        "model_sha256": artifact.get("sha256") or "UNAVAILABLE",
        "digest_status": digest_status,
        "digest_verified": artifact.get("verified", False),
        "external_supplied": external_supplied,
        "model_external_source": artifact.get("external_source") or "none",
        "filename_disagreement": artifact.get("filename_disagreement"),
        "runtime_path": runtime.get("binary_path") or "UNAVAILABLE",
        "runtime_sha256": runtime.get("binary_sha256") or "UNAVAILABLE",
        "runtime_version": runtime.get("version") or "UNAVAILABLE",
        "compatibility": (payload.get("compatibility") or {}).get("compatibility", "UNKNOWN"),
        "compatibility_established_by_load": (
            payload.get("compatibility") or {}
        ).get("established_by_load", False),
        "real_runtime": inference.get("mode", "NOT_TESTABLE"),
        "real_inference": inference.get("outcome", "NOT_RUN"),
        "prompt_sha256": inference.get("prompt_sha256") or "",
        "output_sha256": inference.get("output_sha256") or "",
        "token_accounting": inference.get("token_accounting") or {},
        "determinism": (payload.get("determinism") or {}).get("verdict", "NOT_DETERMINED"),
        "model_immutable": (payload.get("immutability") or {}).get("immutable"),
        "runtime_immutable": (payload.get("runtime_immutability") or {}).get("immutable"),
        "process_identity": payload.get("process_identity") or {},
        "restricted_account_runtime": (
            payload.get("launch") or {}
        ).get("state", "NOT_TESTABLE"),
        "protected_probe": {
            "protected_denied": probe.get("protected_denied", 0),
            "protected_attempts": probe.get("protected_attempts", 0),
            "boundary_meaningful": probe.get("boundary_meaningful", False),
        },
        "workspace": {
            "write": probe.get("workspace_write_allowed"),
            "readback": probe.get("workspace_readback_ok"),
            "cleanup": probe.get("workspace_cleanup_ok"),
        },
        "network": (payload.get("network") or {}).get("policy", "LOCAL_ONLY_NO_FETCH"),
        "audit_derived": (payload.get("audit") or {}).get("derived_count", 0),
        "audit_unknown": (payload.get("audit") or {}).get("unknown_count", 0),
        "audit_reverified": (
            payload.get("audit") or {}
        ).get("reverification", {}).get("verified", False),
        "candidates_reported": {
            "models": (payload.get("candidates") or {}).get("model_count", 0),
            "runtimes": (payload.get("candidates") or {}).get("runtime_count", 0),
            "promotable": (payload.get("candidates") or {}).get("promotable", False),
        },
        "subject": "NONE",
        "birth": "NOT_PERFORMED",
        "forbidden_display_terms": list(FORBIDDEN_DISPLAY_TERMS),
    }


__all__ = [
    "FORBIDDEN_DISPLAY_TERMS",
    "M012_EXECUTION_MODULES",
    "deployment_only",
    "from_ledger",
]
