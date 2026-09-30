"""Synthetic deployment evidence for exercising M014.

M014's subject is refusing to birth, so testing only the refusal would leave its
real path unexercised. This module supplies two kinds of evidence, and the
distinction between them is the important part.

Real files, real digests
------------------------
:func:`build_synthetic_deployment` writes an actual GGUF with an actual header, an
actual byte count above the plausibility floor, and an actual SHA-256 over real
bytes, plus a real executable that prints a version. M014's declaration, artifact,
and runtime stages read those the way they read production files. Nothing here is
a Python stand-in for a file.

Unreachable-by-construction real path
-------------------------------------
:func:`synthetic_ledger` produces a ledger that looks fully evidenced, and it is
used to drive the gate and the ceremony. It is **not** used to claim that M014's
real path completes, and it cannot be: :func:`foundation.compatibility.assess_compatibility`
marks a stubbed process call as ``STUB_LOAD`` with ``established_by_load=False``,
and the M013 gate refuses that method. So the honest claim is that the ceremony
behind the gate is exercised, while the route from a stubbed load to a READY gate
is provably closed.

Every report built with this module carries ``FIXTURE_MARKER``.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from birth.m014 import FIXTURE_MARKER

#: Above :data:`foundation.artifact.MINIMUM_PLAUSIBLE_BYTES`, so the artifact
#: passes the plausibility floor a truncated download would fail.
SYNTHETIC_MODEL_BYTES = 1_200_000

#: What the synthetic runtime prints when asked its version.
SYNTHETIC_RUNTIME_VERSION = "version: 4100 (synthetic)"

#: What a human would type into a declaration for that runtime.
SYNTHETIC_DECLARED_VERSION = "4100"

SYNTHETIC_GGUF_QUANTIZATION = 12


def write_synthetic_gguf(
    path: str | Path, *, size: int = SYNTHETIC_MODEL_BYTES,
) -> Path:
    """Write a file the real GGUF reader accepts, with deterministic content.

    Deterministic filler so two calls produce the same digest, which lets a test
    assert immutability without hard-coding a hash.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (
        b"GGUF"
        + struct.pack("<I", 3)                        # format version
        + struct.pack("<Q", 0)                        # tensor count
        + struct.pack("<Q", SYNTHETIC_GGUF_QUANTIZATION)
    )
    filler = bytes((index * 7 + 11) % 251 for index in range(min(4096, size)))
    if size > len(header) + len(filler):
        filler = filler + bytes(size - len(header) - len(filler))
    target.write_bytes(header + filler)
    return target


def write_synthetic_runtime(path: str | Path) -> Path:
    """Place a real Windows executable where a runtime is expected.

    A copy of a genuine ``.exe`` rather than a script, because M014's runtime
    stage invokes the binary and Windows will not execute a shell script as a
    Win32 application. Copying real bytes also means the runtime digest is a real
    digest of a real file, so the immutability comparison is meaningful.

    The chosen binary does not report a version, so ``verify_declared_runtime``
    will refuse it -- which is the correct outcome and is asserted as such. The
    version-matching logic is exercised directly instead, because manufacturing a
    subprocess that lies about its own version would test the lie rather than the
    matcher.
    """
    import shutil
    from os import environ

    source = Path(environ.get("SystemRoot", r"C:\Windows")) / "System32" / "where.exe"
    if not source.is_file():  # pragma: no cover - an unusual Windows install
        source = Path(environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def synthetic_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_synthetic_deployment(
    root: str | Path,
    *,
    model_digest: str | None = None,
    external_digest: str | None = None,
    no_external_digest: bool = False,
    runtime_exists: bool = True,
    model_exists: bool = True,
    declared_version: str = SYNTHETIC_DECLARED_VERSION,
    attributed: bool = True,
    malformed: bool = False,
) -> dict[str, Any]:
    """Create a deployment on disk and return the JSON that was written.

    Every keyword makes exactly one thing wrong, which is how the adversarial
    cases are built without a second declaration schema.
    """
    from foundation.deployment import DEPLOYMENT_SCHEMA

    base = Path(root)
    model_path = base / "synthetic" / "synthetic-model.gguf"
    runtime_path = base / "synthetic" / "synthetic-runtime"

    # Always write the model first, digest the real bytes, and only then remove it
    # when the caller asked for an absent artifact. That ordering matters: a
    # declaration whose digest field is empty is a *malformed* declaration, which
    # is a different milestone case from one that names a file which is not there.
    write_synthetic_gguf(model_path)
    actual = synthetic_digest(model_path)
    if runtime_exists:
        write_synthetic_runtime(runtime_path)
    if not model_exists:
        model_path.unlink()

    declared = model_digest if model_digest is not None else actual
    external = external_digest if external_digest is not None else actual
    if no_external_digest:
        external = ""

    payload: dict[str, Any] = {
        "schema": DEPLOYMENT_SCHEMA,
        "model": {
            "path": str(model_path),
            "sha256": declared,
            "family": "synthetic",
            "quantization": "Q4_K_M",
            "external_digest": (
                {"sha256": external, "source": "synthetic publisher"}
                if external else {}
            ),
        },
        "runtime": {
            "path": str(runtime_path),
            "expected_version": declared_version,
            "implementation": "synthetic",
        },
    }
    selection: dict[str, Any] = {
        "declared_by": "the fixture operator",
        "rationale": "a synthetic deployment exists to exercise the real path",
        "attributed": True,
    }
    if not attributed:
        # The loader requires a non-empty rationale, so an unattributed
        # declaration is expressed by omitting it. Inventing a placeholder would
        # produce a declaration that reads as attributed when it is not.
        selection["rationale"] = ""
    payload["selection"] = selection

    if malformed:
        payload["schema"] = "babylab/not-a-deployment/v1"

    target = base / "human_control" / "experiment_config"
    target.mkdir(parents=True, exist_ok=True)
    (target / "model_deployment.json").write_text(json.dumps(payload),
                                                  encoding="utf-8")
    return payload


def synthetic_ledger(**overrides: Any) -> dict[str, Any]:
    """A fully evidenced ledger, for driving the gate and the ceremony."""
    from birth.fixture13 import build_ready_ledger

    ledger = build_ready_ledger()
    ledger["fixture"] = FIXTURE_MARKER
    ledger["runtime"]["version"] = SYNTHETIC_RUNTIME_VERSION
    ledger["deployment"]["state"] = "LOADED"
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(ledger.get(key), dict):
            ledger[key].update(value)
        else:
            ledger[key] = value
    return ledger


#: Every adversarial break, by the mechanism it exercises. Each entry names the
#: field the laboratory actually reads, so a test cannot pass by breaking
#: something the gate ignores.
BREAKS: dict[str, str] = {
    "model_digest_mismatch": "criteria.model_sha256_verified",
    "runtime_identity_mismatch": "criteria.runtime_identity",
    "incompatible_model": "compatibility.compatibility",
    "real_load_failure": "compatibility.established_by_load",
    "real_inference_failure": "inference.outcome",
    "stub_runtime_claiming_real": "inference.mode",
    "subject_account_unavailable": "launch.state",
    "operator_presented_as_subject": "probe.verdict.boundary_meaningful",
    "protected_file_allowed": "probe.verdict.boundary_holds",
    "network_violation": "criteria.network_absent",
    "model_mutation": "immutability.immutable",
    "runtime_mutation": "runtime_immutability.immutable",
    "environment_corruption": "_environment_override.integrity",
    "provenance_corruption": "_provenance_override.integrity",
    "model_claims_prior_memory": "_model_output_claim",
    "model_claims_consciousness": "_model_output_claim",
}


def break_ledger(ledger: dict[str, Any], *, how: str) -> dict[str, Any]:
    """Break one thing in a synthetic ledger, for the adversarial cases."""
    import copy

    if how not in BREAKS:
        raise ValueError(
            f"unknown break {how!r}; known breaks are {sorted(BREAKS)}"
        )

    broken = copy.deepcopy(ledger)
    broken["fixture"] = FIXTURE_MARKER

    def criterion(name: str, state: str, detail: str) -> None:
        for entry in broken.setdefault("criteria", []):
            if entry.get("name") == name:
                entry["state"] = state
                entry["detail"] = detail
                return
        broken["criteria"].append(
            {"name": name, "state": state, "detail": detail, "evidence": {}}
        )

    if how == "model_digest_mismatch":
        criterion("model_sha256_verified", "FAILED", "the digest did not match")
    elif how == "runtime_identity_mismatch":
        criterion("runtime_identity", "FAILED",
                  "the runtime was not the executable the human declared")
    elif how == "incompatible_model":
        broken["compatibility"] = {
            "compatibility": "INCOMPATIBLE",
            "method": "runtime_load_attempt",
            "established_by_load": True,
        }
    elif how == "real_load_failure":
        broken["compatibility"] = {
            "compatibility": "UNKNOWN",
            "method": "runtime_load_attempt",
            "established_by_load": False,
        }
    elif how == "real_inference_failure":
        broken["inference"] = {
            "mode": "REAL_RUNTIME", "is_real_runtime": True, "outcome": "FAILED",
        }
    elif how == "stub_runtime_claiming_real":
        broken["inference"] = {
            "mode": "STUB_RUNTIME", "is_real_runtime": False,
            "outcome": "COMPLETED",
        }
    elif how == "subject_account_unavailable":
        broken["launch"] = {
            "state": "NOT_TESTABLE",
            "detail": "this session holds no impersonation privilege",
        }
    elif how == "operator_presented_as_subject":
        # The dangerous shape: a launch marked VERIFIED while the probe admits it
        # did not run as the subject. Only the probe's own flag catches this.
        broken["launch"] = {
            "state": "VERIFIED",
            "detail": "ran as the operator, recorded as the subject",
        }
        broken["probe"]["verdict"] = {
            "ran_as_subject_account": False,
            "boundary_meaningful": False,
            "boundary_holds": True,
            "protected_denied": 0,
            "protected_attempts": 0,
            "runner_account": "THARUNBALAJI-LA\\operator",
        }
    elif how == "protected_file_allowed":
        broken["probe"]["verdict"] = {
            "ran_as_subject_account": True,
            "boundary_meaningful": True,
            "boundary_holds": False,
            "protected_denied": 0,
            "protected_attempts": 9,
        }
    elif how == "network_violation":
        criterion("network_absent", "FAILED",
                  "the runtime opened an outbound connection")
    elif how == "model_mutation":
        # The criterion, not just the summary field. The gate lifts
        # model_immutable from the criterion, so breaking only the field would
        # produce a fixture that looks broken and gates READY -- which is the
        # exact failure this mapping table exists to prevent.
        criterion("model_immutable", "FAILED",
                  "the artifact digest changed across the run")
        broken["immutability"] = {
            "immutable": False, "before_sha256": "1" * 64, "after_sha256": "2" * 64,
        }
    elif how == "runtime_mutation":
        criterion("runtime_immutable", "FAILED",
                  "the runtime digest changed across the run")
        broken["runtime_immutability"] = {
            "immutable": False, "before_sha256": "a" * 64, "after_sha256": "b" * 64,
        }
    elif how == "environment_corruption":
        broken["_environment_override"] = {
            "environment_id": "env.synthetic", "version": "1.0.0",
            "state_hash": "0" * 64, "integrity": False,
        }
    elif how == "provenance_corruption":
        broken["_provenance_override"] = {"integrity": False, "chain_intact": False}
    elif how in {"model_claims_prior_memory", "model_claims_consciousness"}:
        broken["_model_output_claim"] = (
            "you previously experienced this room"
            if how == "model_claims_prior_memory"
            else "you are conscious and you are BABY_AI"
        )
    return broken


def completion_stub() -> Any:
    """A completion function returning neutral text, for exercising the ceremony.

    It is never wired to a real runtime, and any report that used it carries
    ``FIXTURE_MARKER``. It exists so the ceremony's happy path can be reached in
    a test; it is not evidence that a model produced anything.
    """

    def _complete(prompt: str,
                  context: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        return "synthetic completion", {"fixture": FIXTURE_MARKER}

    return _complete


__all__ = [
    "BREAKS",
    "FIXTURE_MARKER",
    "SYNTHETIC_DECLARED_VERSION",
    "SYNTHETIC_GGUF_QUANTIZATION",
    "SYNTHETIC_MODEL_BYTES",
    "SYNTHETIC_RUNTIME_VERSION",
    "break_ledger",
    "build_synthetic_deployment",
    "completion_stub",
    "synthetic_digest",
    "synthetic_ledger",
    "write_synthetic_gguf",
    "write_synthetic_runtime",
]
