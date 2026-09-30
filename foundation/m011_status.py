"""M011 read-only status for the Observatory.

A separate module from :mod:`foundation.status` because the two answer different
questions and the distinction is the point:

* :mod:`foundation.status` answers "what is configured" -- M010's question. It
  reads files and can be polled cheaply.
* this module answers "did a real process run, and who was it" -- M011's
  question. Its honest answer on most hosts is that nothing ran, and the
  *reason* is the useful output.

So this module does not run anything, does not probe, and does not launch. It
reads the artifacts a previous verification left, and when there are none it says
so with the reason rather than reporting a default. The live
:func:`foundation.verification.verify` call stays in the CLI's hands, where a
slow, executing operation belongs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Names of the M011 modules, for the import-graph test that proves the view
#: cannot reach the execution machinery.
M011_MODULES = (
    "hardware.py",
    "process_identity.py",
    "restricted.py",
    "win32.py",
    "probe.py",
    "real_runtime.py",
    "verification.py",
)

#: Vocabulary the M011 section must never render. Runtime telemetry cannot
#: establish any of it, and a field for one would have to be invented.
FORBIDDEN_RUNTIME_DISPLAY_TERMS: tuple[str, ...] = (
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
)


def summarise(
    ledger: Any,
) -> dict[str, Any]:
    """Flatten an :class:`~foundation.verification.M011Ledger` for display.

    Accepts the ledger rather than reading files, so the caller decides when the
    verification happens. Nothing here executes anything.
    """
    payload = ledger.to_dict() if hasattr(ledger, "to_dict") else dict(ledger or {})

    inference = payload.get("inference") or {}
    launch = payload.get("launch") or {}
    probe = payload.get("probe") or {}
    verdict = probe.get("verdict") or {}
    accounting = inference.get("token_accounting") or {}

    backend = ""
    gpu_usage = "UNAVAILABLE"
    resources = inference.get("resources") or {}
    backend_block = resources.get("backend") or {}
    if isinstance(backend_block, dict) and backend_block.get("value"):
        backend = str(backend_block["value"])
    runtime_block = payload.get("runtime_before") or {}
    if runtime_block.get("gpu_usage"):
        gpu_usage = str(runtime_block["gpu_usage"])

    return {
        "schema": "babylab/m011-status/v1",
        "inference_mode": inference.get("mode", "NOT_TESTABLE"),
        "inference_outcome": inference.get("outcome", "NOT_RUN"),
        "real_runtime_verified": bool(payload.get("summary", {}).get(
            "real_runtime_verified", False
        )),
        "prompt_sha256": inference.get("prompt_sha256", ""),
        "output_sha256": inference.get("output_sha256", ""),
        "token_accounting": accounting,
        "determinism": (payload.get("determinism") or {}).get("verdict", "NOT_DETERMINED"),
        "model_immutable": (payload.get("immutability") or {}).get("immutable"),
        "runtime_immutable": (payload.get("runtime_immutability") or {}).get("immutable"),
        "process_identity": payload.get("process_identity") or {},
        "restricted_account_runtime": launch.get("state", "NOT_TESTABLE"),
        "restricted_account_reason": launch.get("detail", ""),
        "protected_probe": {
            "protected_attempts": verdict.get("protected_attempts", 0),
            "protected_denied": verdict.get("protected_denied", 0),
            "runner_account": verdict.get("runner_account", "UNAVAILABLE"),
            "boundary_meaningful": verdict.get("boundary_meaningful", False),
        },
        "gpu_usage": gpu_usage,
        "gpu_backend": backend or "UNAVAILABLE",
        "network": (payload.get("network") or {}).get("policy", "LOCAL_ONLY_NO_FETCH"),
        "criteria": {
            c.get("name"): c.get("state")
            for c in payload.get("criteria", [])
            if isinstance(c, dict)
        },
        "subject": "NONE",
        "birth": "NOT_PERFORMED",
        "explicitly_not": {
            "subject": "no subject exists; a verified runtime is not a subject",
            "birth": "birth is a separate gated laboratory event and was not performed",
            "memory": "the runtime test is stateless",
            "learning": "no weight changed; both digests are unchanged",
            "self_modification": "model output is data and was never executed",
        },
        "forbidden_display_terms": list(FORBIDDEN_RUNTIME_DISPLAY_TERMS),
    }


def capability_only(root: str | Path | None = None) -> dict[str, Any]:
    """What the host can do, with nothing executed.

    This is the payload a display can show without running anything: it reads the
    privilege state and the account, and it never touches a model or launches a
    process. Used as the default so that polling the Observatory cannot start an
    inference.
    """
    from foundation.restricted import describe

    status = describe(root) if root is not None else describe()
    return {
        "schema": "babylab/m011-status/v1",
        "inference_mode": "NOT_TESTABLE",
        "inference_outcome": "NOT_RUN",
        "real_runtime_verified": False,
        "restricted_account_runtime": (
            "AVAILABLE" if status.get("can_launch_as_subject") else "NOT_TESTABLE"
        ),
        "restricted_account_reason": (
            "this session can launch a process under the restricted account"
            if status.get("can_launch_as_subject")
            else "this session holds neither SeImpersonatePrivilege nor "
                 "SeAssignPrimaryTokenPrivilege, and this laboratory never "
                 "accepts a password in order to obtain a token"
        ),
        "process_identity": status.get("caller_identity", {}),
        "network": "LOCAL_ONLY_NO_FETCH",
        "subject": "NONE",
        "birth": "NOT_PERFORMED",
        "privileges_held": status.get("privileges_held", []),
        "privileges_missing": status.get("privileges_missing", []),
        "mechanisms_refused": status.get("mechanisms_refused", {}),
        "explicitly_not": {
            "subject": "no subject exists",
            "birth": "birth was not performed",
        },
    }


__all__ = [
    "FORBIDDEN_RUNTIME_DISPLAY_TERMS",
    "M011_MODULES",
    "capability_only",
    "summarise",
]
