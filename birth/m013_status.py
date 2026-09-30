"""M013 read surface for the Observatory.

Reads a declaration. **Executes nothing** -- no probe, no inference, no
compatibility load, no identity launch, and no ceremony. M011 established that a
view which can launch the thing it observes is not a view; M012 kept that boundary
when it added a deployment panel; this module keeps it when a birth gate is added.

The consequence is stated plainly rather than worked around: the gate cannot be
shown as READY from this surface. A READY verdict needs evidence that only the
verification command produces, so a display panel that never verifies can only
ever report the prerequisites it can read from a file. Everything execution-
dependent renders as BLOCKED, which is the honest answer and also the safe one.

The alternative -- letting the panel run verification so it could show a green
gate -- would mean opening a display was enough to execute a model, hash a
multi-gigabyte artifact, and probe an executable. The gate's own signature
prevents a caller from asking it to perform a ceremony; this module prevents one
from asking it to perform a verification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: The M013 modules that can execute something. Named so the import-graph tests
#: can assert none of them is reachable from this read surface.
M013_EXECUTION_MODULES: tuple[str, ...] = (
    "ceremony13.py",
    "replay13.py",
)


def _readable_ledger(root: str | Path | None = None) -> dict[str, Any]:
    """The subset of an M012 ledger that a file read can establish.

    Assembled from the human's declaration only. Criteria whose evidence requires
    running something are simply absent, and the gate reads an absent criterion
    as BLOCKED -- which is the correct reading of "nobody checked", and the
    reason this surface cannot report READY.
    """
    from foundation.deployment import deployment_path, load_declaration

    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root

    declaration = load_declaration(deployment_path(Path(root)))
    payload = declaration.to_dict()
    model = payload.get("model") or {}
    runtime = payload.get("runtime") or {}
    selection = payload.get("selection") or {}

    def criterion(name: str, satisfied: bool, detail: str) -> dict[str, Any]:
        return {
            "name": name,
            "state": "SATISFIED" if satisfied else "NOT_REACHED",
            "detail": detail,
            "evidence": {},
        }

    declared_model = bool(model.get("path"))
    declared_runtime = bool(runtime.get("path"))
    declared_by_a_human = bool(selection.get("declared_by")) and bool(
        selection.get("rationale"))

    criteria: list[dict[str, Any]] = [
        criterion(
            "human_model_selection", declared_model,
            "a human named a model in the deployment declaration"
            if declared_model else
            "no human named a model in the deployment declaration",
        ),
        criterion(
            "human_runtime_selection", declared_runtime,
            "a human named a runtime in the deployment declaration"
            if declared_runtime else
            "no human named a runtime in the deployment declaration",
        ),
        criterion(
            "selection_attributed", declared_by_a_human,
            "the declaration records who chose the model and why"
            if declared_by_a_human else
            "the declaration records no attributable reason for the selection",
        ),
        criterion(
            "model_artifact_identity", False,
            "the declaration names a model path, but identifying the artifact "
            "requires hashing its bytes, which a file read does not do",
        ),
        criterion(
            "model_sha256_verified", False,
            "the declaration states a digest; verifying it requires hashing the "
            "artifact, which a file read does not do",
        ),
        criterion(
            "runtime_identity", False,
            "the declaration names a runtime path and an expected version; "
            "establishing the runtime's own identity requires running it",
        ),
    ]

    return {
        "schema": "babylab/m013-status/v1",
        "source": "declaration_only",
        "deployment": {
            "state": declaration.state.value,
            "model": {"path": model.get("path") or "",
                      "sha256": model.get("sha256") or ""},
            "runtime": {"path": runtime.get("path") or ""},
            "selection": {
                "declared_by": selection.get("declared_by") or "",
                "rationale": selection.get("rationale") or "",
                "attributed": declared_by_a_human,
            },
        },
        "artifact": {
            "model_path": model.get("path") or "",
            "sha256": model.get("sha256") or "",
            "family_declared": model.get("family") or "",
            "name_declared": Path(model.get("path") or "x").name,
            "quantization_declared": model.get("quantization") or "",
            "verified": False,
            "external_supplied": bool(model.get("external_digest")),
            "external_source": model.get("external_digest_source") or "none",
        },
        "runtime": {
            "binary_path": runtime.get("path") or "",
            "binary_sha256": "",
            "version": runtime.get("expected_version") or "",
        },
        "criteria": criteria,
    }


def ceremony_only(root: str | Path | None = None) -> dict[str, Any]:
    """The M013 birth-gate verdict, evaluated from files alone. Performs no birth."""
    from birth.gate13 import evaluate_birth_gate

    ledger = _readable_ledger(root)
    gate = evaluate_birth_gate(ledger)

    payload = gate.to_dict()
    payload.update({
        "schema": "babylab/m013-status/v1",
        "source": "declaration_only",
        "real_birth": "NOT_PERFORMED",
        "subject": "NONE",
        "first_experience": "NOT_PERFORMED",
        "t_birth": "UNAVAILABLE",
        "note": (
            "the gate is evaluated from the deployment declaration alone. This "
            "panel performs no ceremony, runs no verification, and cannot report "
            "READY: the evidence READY requires is produced by the verification "
            "command, not by a file read. Naming a model in a declaration "
            "establishes the human's choice, not the artifact's identity -- the "
            "latter needs the bytes hashed -- so model_identity, model_digest and "
            "runtime_identity all read BLOCKED here even with a valid declaration. "
            "That is the correct reading of 'not established here'."
        ),
    })
    return payload


__all__ = ["M013_EXECUTION_MODULES", "ceremony_only"]
