"""The fourteen prerequisite checks, each against live machine state.

The discipline every check follows
-----------------------------------
Read the machine; report what was found; never assume. In particular:

* A missing model is ``FAIL`` (observed absence), not ``UNKNOWN``.
* A check that would need a side effect to be thorough says what it checked
  instead of performing the side effect. Writing to the event store to prove it
  is writable would itself be a mutation of research evidence.
* Security checks re-inspect the current filesystem. They do not read a previous
  milestone's evidence file and call that a check.
"""

from __future__ import annotations

from typing import Any

from birth.gate import GateResult, PrerequisiteResult


def _result(name: str, result: GateResult, detail: str, **evidence: Any) -> PrerequisiteResult:
    return PrerequisiteResult(name=name, result=result, detail=detail,
                              evidence=dict(evidence))


def check_model_runtime_availability() -> PrerequisiteResult:
    """Is a runtime binary named and executable?"""
    from babylab.runtime.config import load_configuration

    try:
        from babylab.paths import default_paths

        candidate = (default_paths().human_control / "experiment_config"
                     / "runtime.json")
    except Exception:  # noqa: BLE001 - paths must never break the gate
        candidate = None
    loaded = load_configuration(candidate)
    if not loaded.configured:
        return _result(
            "model_runtime_availability", GateResult.FAIL,
            "MODEL_NOT_CONFIGURED: no runtime configuration exists; the "
            "laboratory does not search for, download, or substitute a runtime",
            configuration_path=str(candidate),
        )
    binary = loaded.configuration.declaration.runtime_binary
    if not binary:
        return _result(
            "model_runtime_availability", GateResult.FAIL,
            "MODEL_RUNTIME_UNVERIFIED: the configuration names no runtime binary",
            configuration_path=str(candidate),
        )
    from pathlib import Path

    if not Path(binary).is_file():
        return _result(
            "model_runtime_availability", GateResult.FAIL,
            f"MODEL_RUNTIME_UNVERIFIED: configured binary not found at {binary}",
            binary=binary,
        )
    return _result(
        "model_runtime_availability", GateResult.PASS,
        f"configured runtime binary exists at {binary}", binary=binary)


def check_model_artifact_identity() -> PrerequisiteResult:
    """Does the configuration name an artifact with a usable identity?"""
    from babylab.runtime.config import load_configuration

    try:
        from babylab.paths import default_paths

        candidate = (default_paths().human_control / "experiment_config"
                     / "runtime.json")
    except Exception:  # noqa: BLE001
        candidate = None
    loaded = load_configuration(candidate)
    if not loaded.configured:
        return _result(
            "model_artifact_identity", GateResult.FAIL,
            "MODEL_NOT_CONFIGURED: no artifact is named",
            configuration_path=str(candidate),
        )
    declaration = loaded.configuration.declaration
    if not declaration.model_path or len(declaration.sha256) != 64:
        return _result(
            "model_artifact_identity", GateResult.FAIL,
            "MODEL_IDENTITY_UNVERIFIED: the configuration names no usable "
            "artifact path and digest",
        )
    return _result(
        "model_artifact_identity", GateResult.PASS,
        f"artifact named at {declaration.model_path} with a 64-char digest",
        model_path=declaration.model_path,
        digest_prefix=declaration.sha256[:16],
    )


def check_model_artifact_digest() -> PrerequisiteResult:
    """Does the named artifact exist with the named digest?"""
    from pathlib import Path

    from babylab.runtime.config import load_configuration

    try:
        from babylab.paths import default_paths

        candidate = (default_paths().human_control / "experiment_config"
                     / "runtime.json")
    except Exception:  # noqa: BLE001
        candidate = None
    loaded = load_configuration(candidate)
    if not loaded.configured:
        return _result(
            "model_artifact_digest", GateResult.FAIL,
            "MODEL_NOT_CONFIGURED: nothing to verify",
            configuration_path=str(candidate),
        )
    declaration = loaded.configuration.declaration
    target = Path(declaration.model_path)
    if not target.is_file():
        return _result(
            "model_artifact_digest", GateResult.FAIL,
            f"MODEL_IDENTITY_UNVERIFIED: artifact not found at {target}",
            model_path=str(target),
        )
    from babylab.runtime.llamacpp_adapter import sha256_file

    actual = sha256_file(target)
    if actual.lower() != declaration.sha256.lower():
        return _result(
            "model_artifact_digest", GateResult.FAIL,
            "MODEL_IDENTITY_UNVERIFIED: digest mismatch; refusing to proceed",
            observed_prefix=actual[:16], expected_prefix=declaration.sha256[:16],
        )
    return _result(
        "model_artifact_digest", GateResult.PASS,
        "artifact digest verified against the configured value",
        digest_prefix=actual[:16], size_bytes=target.stat().st_size,
    )


def check_runtime_verification() -> PrerequisiteResult:
    """Can the configured runtime actually execute?"""
    from babylab.runtime.config import load_configuration
    from babylab.runtime.llamacpp_adapter import LlamaCppAdapter

    try:
        from babylab.paths import default_paths

        candidate = (default_paths().human_control / "experiment_config"
                     / "runtime.json")
    except Exception:  # noqa: BLE001
        candidate = None
    loaded = load_configuration(candidate)
    if not loaded.configured:
        return _result(
            "runtime_verification", GateResult.FAIL,
            "MODEL_RUNTIME_UNVERIFIED: no runtime is configured",
            configuration_path=str(candidate),
        )
    adapter = LlamaCppAdapter(
        binary=loaded.configuration.declaration.runtime_binary or None)
    available, detail = adapter.probe()
    if not available:
        return _result(
            "runtime_verification", GateResult.FAIL,
            f"MODEL_RUNTIME_UNVERIFIED: {detail}")
    return _result(
        "runtime_verification", GateResult.PASS,
        f"runtime probe succeeded: {detail}")


def check_subject_identity_capability() -> PrerequisiteResult:
    """Can this laboratory derive a subject identity at all?

    Exercises the M008 mechanism with a throwaway derivation. Deriving an
    identity is not creating a subject: nothing is registered, nothing is
    persisted, and the throwaway record is discarded. What is being checked is
    that the machinery works.
    """
    from subject.identity import derive_identity

    try:
        identity = derive_identity(
            subject_id="gate-probe", issuer="LABORATORY",
            derivation_basis="birth-gate capability probe (discarded)")
    except Exception as exc:  # noqa: BLE001
        return _result(
            "subject_identity_capability", GateResult.FAIL,
            f"identity derivation failed: {type(exc).__name__}: {exc}")
    if len(identity.identity_hash) != 64:
        return _result(
            "subject_identity_capability", GateResult.FAIL,
            "identity derivation produced a malformed record")
    return _result(
        "subject_identity_capability", GateResult.PASS,
        "identity derivation works; the probe record was discarded",
        schema=identity.schema_version)


def check_key_custody() -> PrerequisiteResult:
    """Is key custody decided, one way or the other?

    The prerequisite is the *decision*, not a key. M009's ceremony needs no
    signing -- provenance is laboratory-generated -- so the decision is
    NOT_REQUIRED, and that decision being explicit and recorded is what passes.
    An undecided custody question would be UNKNOWN, and would block.
    """
    from birth.keycustody import evaluate_key_custody

    try:
        decision = evaluate_key_custody(requires_signing=False)
    except Exception as exc:  # noqa: BLE001
        return _result(
            "key_custody", GateResult.UNKNOWN,
            f"custody evaluation raised {type(exc).__name__}: {exc}; an "
            "unevaluated custody question blocks")
    if decision.decision == "NOT_REQUIRED":
        return _result(
            "key_custody", GateResult.PASS,
            "custody decided: no signing key required for this ceremony; "
            "no key was provisioned",
            decision=decision.decision, reasons=decision.reasons)
    return _result(
        "key_custody", GateResult.UNKNOWN,
        f"custody decision is {decision.decision}; only an explicit "
        "NOT_REQUIRED or a verified PROVISIONED passes",
        decision=decision.decision)


def check_environment_availability() -> PrerequisiteResult:
    """Can the deterministic environment be constructed?"""
    try:
        from environment.deterministic import create_deterministic_environment

        environment = create_deterministic_environment()
    except Exception as exc:  # noqa: BLE001
        return _result(
            "environment_availability", GateResult.FAIL,
            f"environment construction failed: {type(exc).__name__}: {exc}")
    return _result(
        "environment_availability", GateResult.PASS,
        "deterministic environment constructs cleanly",
        environment_type=environment.identity.environment_type,
        implementation_version=environment.identity.implementation_version)


def check_environment_version() -> PrerequisiteResult:
    """Is the environment the version this ceremony was written for?"""
    try:
        from environment.deterministic import FIXTURE_VERSION
    except Exception as exc:  # noqa: BLE001
        return _result(
            "environment_version", GateResult.UNKNOWN,
            f"fixture version unreadable: {type(exc).__name__}: {exc}")
    from birth.ceremony import EXPECTED_ENVIRONMENT_VERSION

    if FIXTURE_VERSION != EXPECTED_ENVIRONMENT_VERSION:
        return _result(
            "environment_version", GateResult.FAIL,
            f"fixture is {FIXTURE_VERSION}, ceremony expects "
            f"{EXPECTED_ENVIRONMENT_VERSION}; refusing to run against a "
            "different world than the one reviewed",
            fixture_version=FIXTURE_VERSION,
            expected=EXPECTED_ENVIRONMENT_VERSION)
    return _result(
        "environment_version", GateResult.PASS,
        f"fixture version {FIXTURE_VERSION} matches the ceremony",
        fixture_version=FIXTURE_VERSION)


def check_subject_interface_availability() -> PrerequisiteResult:
    """Does the subject interface exist with the expected version?"""
    try:
        from subject.interface import INTERFACE_VERSION, SubjectInterface
    except Exception as exc:  # noqa: BLE001
        return _result(
            "subject_interface_availability", GateResult.FAIL,
            f"interface unimportable: {type(exc).__name__}: {exc}")
    from birth.ceremony import EXPECTED_INTERFACE_VERSION

    if INTERFACE_VERSION != EXPECTED_INTERFACE_VERSION:
        return _result(
            "subject_interface_availability", GateResult.FAIL,
            f"interface is {INTERFACE_VERSION}, ceremony expects "
            f"{EXPECTED_INTERFACE_VERSION}",
            interface_version=INTERFACE_VERSION,
            expected=EXPECTED_INTERFACE_VERSION)
    return _result(
        "subject_interface_availability", GateResult.PASS,
        f"interface {INTERFACE_VERSION} available",
        interface_version=INTERFACE_VERSION)


def check_provenance_availability() -> PrerequisiteResult:
    """Are the provenance stores readable and internally consistent?

    Read-only: the gate never writes to prove writability, because writing
    would itself mutate research evidence.
    """
    try:
        from babylab.clock import Clock
        from babylab.paths import default_paths
        from events.store import EventStore
        from provenance.keyring import Keyring
        from provenance.ledger import ProvenanceLedger

        paths = default_paths()
        keyring = Keyring(paths.keyring, paths.private_key_dir, clock=Clock())
        ledger = ProvenanceLedger(paths.provenance_ledger, keyring,
                                  clock=Clock(), seal_dir=paths.protected_provenance)
        store = EventStore(paths.event_store, clock=Clock())
    except Exception as exc:  # noqa: BLE001
        return _result(
            "provenance_availability", GateResult.FAIL,
            f"provenance stores unreadable: {type(exc).__name__}: {exc}")
    verification = store.verify_chain()
    if not verification.intact:
        return _result(
            "provenance_availability", GateResult.FAIL,
            f"event chain broken: {verification.problems[:2]}",
            problems=verification.problems[:3])
    return _result(
        "provenance_availability", GateResult.PASS,
        f"event chain intact ({store.count()} events), ledger readable "
        f"({ledger.count()} entries)",
        events=store.count(), ledger_entries=ledger.count())


def check_protected_evidence_integrity() -> PrerequisiteResult:
    """Do the protected artifacts verify right now?

    Records current digests so the ceremony can compare before/after. The check
    itself passes when every expected artifact is present and readable; it makes
    no claim about history, only about the current state being intact enough to
    start from.
    """
    try:
        from babylab.osboundary import protected_paths, verify_evidence_unchanged

        digests = verify_evidence_unchanged()
        names = [entry.name for entry in protected_paths()]
        missing = [n for n in names
                   if n not in ("birth_records", "protected_configuration")
                   and n not in digests]
    except Exception as exc:  # noqa: BLE001
        return _result(
            "protected_evidence_integrity", GateResult.FAIL,
            f"evidence unreadable: {type(exc).__name__}: {exc}")
    if missing:
        return _result(
            "protected_evidence_integrity", GateResult.FAIL,
            f"expected protected artifacts absent: {missing}",
            missing=missing)
    return _result(
        "protected_evidence_integrity", GateResult.PASS,
        f"{len(digests)} protected artifacts present and readable",
        artifact_count=len(digests))


def check_m005_isolation_status() -> PrerequisiteResult:
    """Does the BABY_AI_TEST boundary hold *right now*?

    Re-inspects the ACLs directly. Reading M005's evidence file would be
    assuming security from a previous milestone; this check looks at the
    filesystem.
    """
    try:
        import os
        import subprocess

        from babylab.osboundary import protected_paths, subject_workspace_paths
    except Exception as exc:  # noqa: BLE001
        return _result(
            "m005_isolation_status", GateResult.UNKNOWN,
            f"boundary inventory unreadable: {type(exc).__name__}: {exc}")

    def _deny_count(path: str) -> int:
        try:
            completed = subprocess.run(
                ["icacls", path], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return -1
        if completed.returncode != 0:
            return -1
        return sum(1 for line in completed.stdout.splitlines()
                   if "BABY_AI_TEST" in line and "(DENY)" in line)

    missing: list[str] = []
    errors: list[str] = []
    for entry in protected_paths():
        if not os.path.exists(entry.path):
            continue
        count = _deny_count(str(entry.path))
        if count < 0:
            errors.append(entry.name)
        elif count < 1:
            missing.append(entry.name)
    if errors:
        return _result(
            "m005_isolation_status", GateResult.UNKNOWN,
            f"ACLs unreadable for: {errors}; an uninspectable boundary blocks",
            unreadable=errors)
    if missing:
        return _result(
            "m005_isolation_status", GateResult.FAIL,
            f"boundary absent on: {missing}; OS isolation does not currently hold",
            missing=missing)
    leaked = []
    for workspace in subject_workspace_paths():
        count = _deny_count(str(workspace.path))
        if count > 0:
            leaked.append(workspace.name)
    if leaked:
        return _result(
            "m005_isolation_status", GateResult.FAIL,
            f"subject workspace incorrectly denied: {leaked}",
            leaked=leaked)
    return _result(
        "m005_isolation_status", GateResult.PASS,
        "every existing protected path carries a BABY_AI_TEST deny; both "
        "workspaces carry none",
        checked=sum(1 for e in protected_paths() if os.path.exists(e.path)))


def check_observatory_availability() -> PrerequisiteResult:
    """Does the Observatory answer?"""
    try:
        import subprocess
        import sys

        from babylab.paths import default_paths

        completed = subprocess.run(
            [sys.executable, "-m", "observatory.cli", "--no-color", "status"],
            capture_output=True, text=True, timeout=60,
            cwd=str(default_paths().root))
    except Exception as exc:  # noqa: BLE001
        return _result(
            "observatory_availability", GateResult.FAIL,
            f"observatory could not be invoked: {type(exc).__name__}: {exc}")
    if completed.returncode != 0:
        return _result(
            "observatory_availability", GateResult.FAIL,
            f"observatory exited {completed.returncode}",
            stderr=(completed.stderr or "")[:300])
    if "NO EXPERIMENTAL SUBJECT ATTACHED" not in completed.stdout:
        return _result(
            "observatory_availability", GateResult.UNKNOWN,
            "observatory answered but its subject state is unreadable; an "
            "observatory that cannot say what it sees blocks",
            output=(completed.stdout or "")[:300])
    return _result(
        "observatory_availability", GateResult.PASS,
        "observatory answers and reports no subject attached")


def check_configuration_integrity() -> PrerequisiteResult:
    """Is the birth configuration itself well formed?"""
    from birth.ceremony import CeremonyConfig

    try:
        config = CeremonyConfig.default()
        problems = config.validate()
    except Exception as exc:  # noqa: BLE001
        return _result(
            "configuration_integrity", GateResult.FAIL,
            f"birth configuration unreadable: {type(exc).__name__}: {exc}")
    if problems:
        return _result(
            "configuration_integrity", GateResult.FAIL,
            f"birth configuration invalid: {problems[0]}",
            problems=problems)
    return _result(
        "configuration_integrity", GateResult.PASS,
        "birth configuration validates",
        configuration_hash=config.configuration_hash())


def default_checks() -> dict:
    """The real checks, by prerequisite name."""
    return {
        "model_runtime_availability": check_model_runtime_availability,
        "model_artifact_identity": check_model_artifact_identity,
        "model_artifact_digest": check_model_artifact_digest,
        "runtime_verification": check_runtime_verification,
        "subject_identity_capability": check_subject_identity_capability,
        "key_custody": check_key_custody,
        "environment_availability": check_environment_availability,
        "environment_version": check_environment_version,
        "subject_interface_availability": check_subject_interface_availability,
        "provenance_availability": check_provenance_availability,
        "protected_evidence_integrity": check_protected_evidence_integrity,
        "m005_isolation_status": check_m005_isolation_status,
        "observatory_availability": check_observatory_availability,
        "configuration_integrity": check_configuration_integrity,
    }


__all__ = ["default_checks"]
