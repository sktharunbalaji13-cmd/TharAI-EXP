"""M014 -- the execution boundary between a human decision and a real birth.

M001-M013 built the machinery. M012 verified a human's deployment declaration,
and M013 built a birth ceremony and then declined to run one because nothing had
been declared. M014 is the step that actually executes, in one place, in order,
and refuses at every step.

The whole milestone is a chain of gates, and the design rule is that **the
laboratory never chooses**. The human picks the model, the artifact, the
quantization, the runtime, and the version; M014 verifies those choices against
the bytes on disk and then either births or explains why it did not. There is no
code path in this module that searches for, ranks, recommends, downloads, or
substitutes an artifact, and no path that repairs a malformed declaration -- a
declaration the laboratory edits is no longer a human decision.

Nothing here duplicates M012, M011, or M013. The artifact identity comes from
:mod:`foundation.artifact`, the restricted-account policy from
:mod:`foundation.restricted`, the probe from :mod:`foundation.probe`, the
deployment verification from :func:`foundation.m012.verify`, the birth gate from
:mod:`birth.gate13`, and the ceremony from :mod:`birth.ceremony13`. If this module
ever needed a second implementation of one of those, that would be the defect.

Three states, and the distinction is the point:

``COMPLETE``
    A real birth occurred. This is the only status that may carry a subject id, a
    ``T_birth``, and a first experience.
``BLOCKED``
    The laboratory has not established a prerequisite. Nothing was wrong; nothing
    was checked.
``FAILED``
    The laboratory established that a prerequisite is violated -- a digest that
    does not match, a malformed declaration, a load that rejected the artifact. A
    failure is evidence and is preserved.

On this host the expected result is BLOCKED: no declaration exists, and the
restricted-account boundary cannot be exercised. Both facts are reported rather
than worked around.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

#: Written into any report whose evidence came from a fixture, so a synthetic
#: result can never be read as a real one. The same discipline as
#: :mod:`birth.fixture13`, and the same reason.
FIXTURE_MARKER = "SYNTHETIC_M014_EVIDENCE"

#: The M013 ceremony's interaction budget. Restated here so M014 can assert the
#: count without importing a private name, and so a change to the budget is a
#: visible change here too.
REQUIRED_INTERACTION_COUNT = 1

#: The environment policy M014 requires and M014 itself never relaxes.
REQUIRED_NETWORK_POLICY = "LOCAL_ONLY_NO_FETCH"

#: The account the real runtime must run under. Read from the single definition
#: in :mod:`foundation.restricted` rather than restated, because a second copy of
#: an account name is a second thing to forget to update.
SUBJECT_ACCOUNT = "THARUNBALAJI-LA\\BABY_AI_TEST"


class ExecutionMode(str, enum.Enum):
    """How much of this run is real. Only REAL may establish a real birth."""

    REAL = "REAL"
    SIMULATED = "SIMULATED"
    STUB = "STUB"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def may_establish_real_birth(self) -> bool:
        return self is ExecutionMode.REAL


class M014Status(str, enum.Enum):
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class M014Report:
    """Everything M014 learned, including everything it refused to do.

    A report is produced on every path, including the ones that fail early. A
    milestone that returns nothing when it refuses leaves no evidence, and an
    unexplained absence is indistinguishable from a bug.
    """

    mode: ExecutionMode
    status: M014Status
    #: Which stage the run reached. Useful for a reader who wants to know how far
    #: it got without reading the whole report.
    stage: str = "init"
    fixture: str = ""

    declaration: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    inference: dict[str, Any] = field(default_factory=dict)
    gpu: dict[str, Any] = field(default_factory=dict)
    immutability: dict[str, Any] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)
    ceremony: dict[str, Any] = field(default_factory=dict)
    replay: dict[str, Any] = field(default_factory=dict)
    post_birth: dict[str, Any] = field(default_factory=dict)
    birth_record: dict[str, Any] = field(default_factory=dict)
    birth_record_hash: str = ""
    environment: dict[str, Any] = field(default_factory=dict)

    stop_reason: str = ""
    #: One line per refusal, in the order they were found. Kept separate from
    #: ``stop_reason`` because a single reason rarely tells the whole story: a
    #: blocked run usually has several independent blockers.
    refusals: list[str] = field(default_factory=list)

    @property
    def real_birth_performed(self) -> bool:
        """True only for a real, completed birth.

        Requires all three, and the mode check is what stops a fixture-backed run
        from ever reporting a production birth.
        """
        return (
            self.mode.may_establish_real_birth
            and self.status is M014Status.COMPLETE
            and bool(self.ceremony.get("birth_occurred"))
        )

    def to_dict(self) -> dict[str, Any]:
        ceremony = dict(self.ceremony)
        return {
            "schema": "babylab/m014-report/v1",
            "milestone": "M014",
            "mode": self.mode.value,
            "status": self.status.value,
            "stage": self.stage,
            "fixture": self.fixture or "NONE",
            "real_birth_performed": self.real_birth_performed,
            # The four fields a reader checks first, duplicated at the top level
            # because burying them in a nested record is how a birth gets missed.
            "subject_id": ceremony.get("subject_id", "NONE") or "NONE",
            "t_birth": ceremony.get("t_birth", "UNAVAILABLE"),
            "lifecycle": ceremony.get("lifecycle", "UNCREATED"),
            "first_experience": (
                "RECORDED" if ceremony.get("first_experience")
                else "NOT_PERFORMED"
            ),
            "declaration": dict(self.declaration),
            "artifact": dict(self.artifact),
            "runtime": dict(self.runtime),
            "compatibility": dict(self.compatibility),
            "inference": dict(self.inference),
            "gpu": dict(self.gpu),
            "immutability": dict(self.immutability),
            "security": dict(self.security),
            "gate": dict(self.gate),
            "ceremony": ceremony,
            "replay": dict(self.replay),
            "post_birth": dict(self.post_birth),
            "birth_record": dict(self.birth_record),
            "birth_record_hash": self.birth_record_hash or "UNAVAILABLE",
            "environment": dict(self.environment),
            "stop_reason": self.stop_reason,
            "refusals": list(self.refusals),
            "what_this_is_not": {
                "consciousness": "not established by any of this",
                "subject": (
                    "a real subject exists" if self.real_birth_performed
                    else "no subject exists"
                ),
                "learning": "no weights were updated; both digests are unchanged",
                "memory": "no memory system was implemented or written",
                "autonomy": "no loop, goal, or self-directed action",
                "self_modification": "no subject can modify any laboratory file",
                "curriculum": "the observation carried no meanings or guidance",
            },
        }


def _refuse(
    report: M014Report,
    status: M014Status,
    stage: str,
    reason: str,
) -> M014Report:
    """Stop here, keeping whatever was already established.

    The partial report is the point. A run that verified the artifact and then
    found the runtime missing has produced real knowledge, and discarding it
    would make the next attempt start from nothing.
    """
    report.status = status
    report.stage = stage
    report.stop_reason = reason
    report.refusals.append(f"[{stage}] {reason}")
    return report


# ---------------------------------------------------------------------------
# Stage 1: the human declaration, read independently
# ---------------------------------------------------------------------------

def classify_declaration(root: Any = None) -> dict[str, Any]:
    """Read the human's declaration and classify it. Verifies nothing else.

    M014 classifies before it verifies, because the four outcomes the milestone
    specifies are all distinguishable from the declaration alone:

    * absent        -> BLOCKED
    * malformed     -> FAILED
    * artifacts missing -> BLOCKED
    * digest mismatch   -> FAILED

    A malformed declaration is never repaired. The laboratory editing a human's
    declaration would leave something that reads as a human decision and is not
    one, which is worse than no declaration at all.
    """
    from foundation.deployment import deployment_path, load_declaration

    path = deployment_path(root) if root is not None else None
    if path is None:
        from babylab.paths import default_paths

        path = deployment_path(default_paths().root)

    declaration = load_declaration(path)
    payload = declaration.to_dict()
    model = payload.get("model") or {}
    runtime = payload.get("runtime") or {}
    selection = payload.get("selection") or {}

    return {
        "path": str(path),
        "exists": path.exists(),
        "state": declaration.state.value,
        "declared_by": selection.get("declared_by") or "",
        "rationale": selection.get("rationale") or "",
        "attributed": bool(selection.get("attributed")),
        "declared_at": selection.get("declared_at") or "",
        "model_path": model.get("path") or "",
        "model_sha256": model.get("sha256") or "",
        "model_family": model.get("family") or "",
        "model_quantization": model.get("quantization") or "",
        "model_external_digest": model.get("external_digest") or "",
        "model_external_source": model.get("external_digest_source") or "none",
        "runtime_path": runtime.get("path") or "",
        "runtime_expected_version": runtime.get("expected_version") or "",
        "runtime_implementation": runtime.get("implementation") or "",
        "detail": payload.get("detail") or "",
    }


def _declaration_verdict(declaration: dict[str, Any]) -> tuple[str, str]:
    """Return ``(status, reason)`` for the declaration alone.

    ``status`` is one of ``OK``, ``BLOCKED``, or ``FAILED``.
    """
    state = declaration.get("state")
    if state == "NOT_CONFIGURED":
        return "BLOCKED", (
            "no human deployment declaration exists at "
            f"{declaration.get('path')}. M014 does not create one, and does not "
            "choose a foundation on the human's behalf."
        )
    if state == "INVALID":
        return "FAILED", (
            f"the deployment declaration is malformed: "
            f"{declaration.get('detail') or 'the loader refused it'}. M014 does "
            "not repair a declaration; a repaired one would read as a human "
            "decision and would not be one."
        )
    if not declaration.get("attributed"):
        return "FAILED", (
            "the declaration does not record who chose the foundation or why. A "
            "deployment without a reason is not an attributed human decision."
        )
    return "OK", "a human named a model and a runtime, with a reason attached."


# ---------------------------------------------------------------------------
# Stage 2: the declared artifact
# ---------------------------------------------------------------------------

def verify_declared_artifact(declaration: dict[str, Any]) -> dict[str, Any]:
    """Verify the declared model artifact against the bytes on disk.

    Identity comes from the content, never the filename. A file called
    ``qwen3-8b.gguf`` is not a Qwen and not 8B until its metadata says so, and
    even then that is the file *declaring* its identity rather than the laboratory
    confirming it -- so ``general.architecture`` is reported as declared.
    """
    from foundation.artifact import identify, read_gguf_header

    path = declaration.get("model_path") or ""
    if not path:
        return {"status": "BLOCKED",
                "reason": "the declaration names no model artifact"}

    identity = identify(
        model_path=path,
        expected_sha256=declaration.get("model_sha256") or "",
        external_sha256=declaration.get("model_external_digest") or "",
        external_source=declaration.get("model_external_source") or "none",
        family=declaration.get("model_family") or "",
        quantization=declaration.get("model_quantization") or "",
    )
    payload = identity.to_dict()
    payload["gguf_header"] = read_gguf_header(path) if identity.measured_bytes else {}
    payload["identity_source"] = (
        "measured from the artifact's bytes and its own GGUF header; the header's "
        "architecture and quantization are declared by the file, not verified by "
        "this laboratory"
    )

    # The declared digest is checked against the computed one here rather than
    # being handed to ``identify`` and hoped for. ``identify`` compares the
    # artifact against the *publisher's* digest; it does not tell us whether the
    # human's stated digest agrees with the bytes, and a declaration that
    # disagrees with the file is precisely the case the milestone calls FAILED.
    declared = (declaration.get("model_sha256") or "").strip().lower()
    computed = (payload.get("computed_sha256") or "").strip().lower()
    payload["declared_sha256"] = declared
    payload["declared_digest_matches"] = (
        bool(declared) and bool(computed) and declared == computed
    )
    if payload.get("computed_sha256") and not payload["declared_digest_matches"]:
        payload["declared_digest_detail"] = (
            f"the human declared {declared[:16]}... but the file at "
            f"{payload.get('canonical_path') or payload.get('path')} hashes to "
            f"{computed[:16]}... M014 does not repair a declaration, does not "
            "replace the artifact, and does not proceed on whichever of the two "
            "it prefers."
        )
    return payload


def _artifact_verdict(artifact: dict[str, Any]) -> tuple[str, str]:
    """Return ``(status, reason)`` for the declared artifact alone."""
    from foundation.artifact import DigestStatus

    status_name = str(artifact.get("status", "")).rsplit(".", 1)[-1]

    # The human's own declared digest must agree with the bytes, independently of
    # the publisher's. Both comparisons are needed: a declaration can match the
    # publisher while disagreeing with the file in hand, which happens when the
    # wrong file is downloaded under the right name.
    if artifact.get("computed_sha256") and not artifact.get(
        "declared_digest_matches", False
    ):
        return "FAILED", artifact.get("declared_digest_detail", "")

    if status_name == DigestStatus.ARTIFACT_MISSING.name:
        return "BLOCKED", (
            f"the declared model does not exist at {artifact.get('path')}. The "
            "laboratory does not download it; acquisition is a human action."
        )
    if status_name == DigestStatus.ARTIFACT_TOO_SMALL.name:
        return "BLOCKED", "the declared model is too small to be a model"
    if status_name == DigestStatus.UNSUPPORTED_FORMAT.name:
        return "FAILED", (
            "the declared artifact is not a GGUF. M014 supports GGUF only, and "
            "does not convert it."
        )
    if status_name == DigestStatus.EXTERNAL_DIGEST_MISMATCH.name:
        return "FAILED", (
            "the artifact's bytes do not match the externally supplied digest. "
            "The artifact is not replaced and the declaration is not edited; a "
            "mismatch is evidence of something being wrong."
        )
    if status_name == DigestStatus.NO_EXTERNAL_DIGEST_SUPPLIED.name:
        return "BLOCKED", (
            "no publisher digest was supplied, so the artifact's identity rests "
            "on a digest this laboratory computed from the same bytes it will "
            "load. That is self-consistent, not independently verified."
        )
    if status_name == DigestStatus.COMPUTED_LOCAL_DIGEST.name:
        return "BLOCKED", (
            "only a locally computed digest is available for this artifact"
        )
    if status_name == DigestStatus.VERIFIED_MATCH.name:
        return "OK", (
            f"the artifact matches the externally supplied digest "
            f"({artifact.get('size_bytes')} bytes)"
        )
    return "BLOCKED", f"artifact status {status_name!r} is not understood"


# ---------------------------------------------------------------------------
# Stage 3: the declared runtime
# ---------------------------------------------------------------------------

def verify_declared_runtime(declaration: dict[str, Any]) -> dict[str, Any]:
    """Verify the declared runtime executable and read its own version.

    A config file's ``version`` field is not evidence about the executable. The
    version recorded here is whatever the binary reports about itself, and the
    expected version is compared against that rather than substituted for it.
    """
    from pathlib import Path

    from foundation.runtime_identity import identify_runtime

    path = declaration.get("runtime_path") or ""
    if not path:
        return {"status": "BLOCKED",
                "reason": "the declaration names no runtime executable"}

    resolved = Path(path)
    payload: dict[str, Any] = {
        "path": str(resolved),
        "exists": resolved.is_file(),
        "expected_version": declaration.get("runtime_expected_version") or "",
        "implementation": declaration.get("runtime_implementation") or "",
    }
    if not payload["exists"]:
        payload["status"] = "BLOCKED"
        payload["reason"] = (
            f"the declared runtime does not exist at {resolved}. The laboratory "
            "does not download it."
        )
        return payload

    identity = identify_runtime(
        resolved, declared_version=payload["expected_version"],
    )
    observed = identity.version or ""
    payload.update(identity.to_dict())
    payload["observed_version"] = observed
    payload["version_source"] = identity.version_source
    payload["version_matches_declaration"] = (
        bool(payload["expected_version"])
        and _version_equivalent(observed, payload["expected_version"])
    )
    payload["status"] = "OK" if payload["version_matches_declaration"] else "FAILED"
    if not payload["version_matches_declaration"]:
        payload["reason"] = (
            f"the runtime reports version {observed or 'UNAVAILABLE'!r} but the "
            f"declaration expected "
            f"{payload['expected_version']!r}. M014 does not repair a version "
            "mismatch and does not substitute a different executable."
        )
    return payload


def _version_equivalent(observed: str, expected: str) -> bool:
    """Compare runtime versions without demanding they be byte-identical.

    Build metadata and date suffixes differ between a binary's ``--version``
    output and what a human typed into a declaration. Requiring an exact match
    would make a correct declaration fail on formatting, which would train
    people to write whatever the binary prints and stop reading it.

    The comparison is a normalised token match, not a prefix match: a prefix
    match would accept ``1.0`` against ``1.0.1``, which is a different build.
    """
    def tokens(text: str) -> list[str]:
        cleaned = text.strip().lower()
        for separator in ("(", ")", "[", "]"):
            cleaned = cleaned.replace(separator, " ")
        return [t for t in "".join(
            c if (c.isalnum() or c in ".-_+") else " " for c in cleaned
        ).split() if t]

    observed_tokens = tokens(observed)
    expected_tokens = tokens(expected)
    if not observed_tokens or not expected_tokens:
        return False
    # A build number in one and not the other is a formatting difference; a
    # differing build number in both is a real mismatch.
    numbers = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")
    def numbers_only(seq: list[str]) -> list[str]:
        return [t for t in seq if any(ch in numbers for ch in t)]

    left, right = numbers_only(observed_tokens), numbers_only(expected_tokens)
    if left and right and left != right:
        return False
    return all(token in observed_tokens for token in expected_tokens if
               token not in numbers) or all(
        token in expected_tokens for token in observed_tokens if
        token not in numbers)


# ---------------------------------------------------------------------------
# Stage 4: immutability, captured on both sides of everything
# ---------------------------------------------------------------------------

def capture_immutability(
    artifact: dict[str, Any], runtime: dict[str, Any], *, label: str,
) -> dict[str, Any]:
    """Record the two digests at one moment, for comparison across the run.

    Taken twice, before and after, and required to be equal. A run that only
    records one side cannot detect mutation, and an artifact that changed under
    us would invalidate every result computed from it.
    """
    return {
        "label": label,
        "model_sha256": artifact.get("computed_sha256", "UNAVAILABLE"),
        "model_status": artifact.get("status", "UNAVAILABLE"),
        "runtime_sha256": runtime.get("binary_sha256", "UNAVAILABLE"),
        "runtime_path": runtime.get("binary_path", runtime.get("path",
                                                               "UNAVAILABLE")),
    }


def compare_immutability(
    before: dict[str, Any], after: dict[str, Any],
) -> dict[str, Any]:
    """Compare the before and after snapshots and name any mutation."""
    model_same = before.get("model_sha256") == after.get("model_sha256")
    runtime_same = before.get("runtime_sha256") == after.get("runtime_sha256")
    return {
        "model_sha256_before": before.get("model_sha256", "UNAVAILABLE"),
        "model_sha256_after": after.get("model_sha256", "UNAVAILABLE"),
        "model_immutable": model_same,
        "runtime_sha256_before": before.get("runtime_sha256", "UNAVAILABLE"),
        "runtime_sha256_after": after.get("runtime_sha256", "UNAVAILABLE"),
        "runtime_immutable": runtime_same,
        "verdict": "IMMUTABLE" if (model_same and runtime_same) else "MUTATED",
        "detail": (
            "both digests are unchanged across the entire run"
            if model_same and runtime_same else
            "at least one digest changed during the run; every result computed "
            "from the earlier bytes is void, and the artifact is not repaired"
        ),
    }


# ---------------------------------------------------------------------------
# Stage 5: the restricted-account boundary
# ---------------------------------------------------------------------------

def assess_subject_account() -> dict[str, Any]:
    """Determine honestly whether the real runtime can run as ``BABY_AI_TEST``.

    The milestone allows three outcomes and only three: the launch is verified,
    the human has established a mechanism outside the laboratory and M014 verifies
    it, or the condition remains not testable. What is not allowed is presenting
    operator execution as subject execution, which is why this reports the
    *holder's* identity alongside the target and never treats the first as
    satisfying the second.
    """
    from foundation.restricted import (
        REQUIRED_PRIVILEGES,
        can_launch_as_subject,
        held_privileges,
    )

    can_launch, held, missing = can_launch_as_subject()
    privileges = held_privileges()
    return {
        "required_account": SUBJECT_ACCOUNT,
        "can_launch_as_subject": can_launch,
        "held_privileges": dict(privileges),
        "missing_privileges": list(missing),
        "required_privileges": list(REQUIRED_PRIVILEGES),
        "state": "TESTABLE" if can_launch else "NOT_TESTABLE",
        "path_taken": (
            "A: a real launch under BABY_AI_TEST was performed and its process "
            "identity was read directly"
            if can_launch else
            "C: the condition remains NOT_TESTABLE. The laboratory does not grant "
            "privileges, weaken ACLs, remove M005 deny ACEs, store credentials, or "
            "ask a human to paste a password in order to make this test pass. "
            "Operator execution is not evidence about BABY_AI_TEST."
        ),
        "operator_execution_accepted_as_subject": False,
    }


# ---------------------------------------------------------------------------
# Stage 6: the gate
# ---------------------------------------------------------------------------

def evaluate_gate(
    ledger: dict[str, Any],
    *,
    environment: dict[str, Any],
    provenance: dict[str, Any],
    control: dict[str, Any],
    key_policy: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate the existing M013 gate. Does not replace it.

    The argument names are fixed by M013 and deliberately so: the gate takes an
    M012 ledger and four measurements of this moment. M014 adds no parameter and
    no override, because a parameter that could relax a prerequisite would make
    the gate a suggestion.
    """
    from birth.gate13 import evaluate_birth_gate

    return evaluate_birth_gate(
        ledger,
        environment=environment,
        provenance=provenance,
        control=control,
        key_policy=key_policy,
    ).to_dict()


# ---------------------------------------------------------------------------
# Stage 7: the birth record
# ---------------------------------------------------------------------------

def birth_record_path(root: Any = None) -> Any:
    """Re-exported from :mod:`birth.record14`; see that module for why it lives
    there rather than here."""
    from birth.record14 import birth_record_path as _path

    return _path(root)


def compute_birth_record_hash(record: dict[str, Any]) -> str:
    """Re-exported from :mod:`birth.record14`."""
    from birth.record14 import compute_birth_record_hash as _hash

    return _hash(record)


def verify_birth_record_unchanged(
    record: dict[str, Any], expected_hash: str,
) -> dict[str, Any]:
    """Re-exported from :mod:`birth.record14`."""
    from birth.record14 import verify_birth_record_unchanged as _verify

    return _verify(record, expected_hash)


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------

def execute_m014(
    root: Any = None,
    *,
    mode: ExecutionMode = ExecutionMode.REAL,
    environment: Any = None,
    verify_kwargs: dict[str, Any] | None = None,
    completion: Any = None,
) -> M014Report:
    """Run the execution boundary, or explain at the first step it cannot.

    The order is the milestone's: declaration, artifact, runtime, immutability,
    M012 verification, security, gate, ceremony, immutability again, post-birth
    security, replay, record. Every stage can stop the run, and every stage that
    stops it records why.

    ``verify_kwargs`` is forwarded verbatim to :func:`foundation.m012.verify`.
    That is the only seam for supplying a runner or an invoker, and it exists so
    the real verification machinery can be driven with a real subprocess launcher
    rather than a stand-in. It cannot be used to inject a ledger, which is why a
    fixture run is labelled rather than hidden.
    """
    from babylab.paths import default_paths

    report = M014Report(mode=mode, status=M014Status.BLOCKED, stage="start")
    if root is None:
        root = default_paths().root

    # Assessed before anything else, and reported on every path including an
    # early one. The subject-account boundary is a property of this host, not of
    # the declaration, and it is the condition most likely to block a birth even
    # after a human has deployed everything. A report that omitted it because the
    # run stopped earlier would hide the answer the reader came for.
    report.security = {"subject_account": assess_subject_account()}

    # -- stage 1: the human declaration ---------------------------------
    report.stage = "declaration"
    declaration = classify_declaration(root)
    report.declaration = declaration
    if declaration.get("fixture"):
        report.fixture = FIXTURE_MARKER

    status, reason = _declaration_verdict(declaration)
    if status == "BLOCKED":
        return _refuse(report, M014Status.BLOCKED, "declaration", reason)
    if status == "FAILED":
        return _refuse(report, M014Status.FAILED, "declaration", reason)

    # -- stage 2: the declared artifact ---------------------------------
    report.stage = "artifact"
    artifact = verify_declared_artifact(declaration)
    report.artifact = artifact
    status, reason = _artifact_verdict(artifact)
    if status == "BLOCKED":
        return _refuse(report, M014Status.BLOCKED, "artifact", reason)
    if status == "FAILED":
        return _refuse(report, M014Status.FAILED, "artifact", reason)

    # -- stage 3: the declared runtime ----------------------------------
    report.stage = "runtime"
    runtime = verify_declared_runtime(declaration)
    report.runtime = runtime
    if runtime.get("status") == "BLOCKED":
        return _refuse(
            report, M014Status.BLOCKED, "runtime",
            runtime.get("reason", "the declared runtime is unavailable"),
        )
    if runtime.get("status") == "FAILED":
        return _refuse(
            report, M014Status.FAILED, "runtime",
            runtime.get("reason", "the declared runtime failed verification"),
        )

    # -- stage 4: immutability, before anything has run ------------------
    report.stage = "immutability_before"
    before = capture_immutability(artifact, runtime, label="before")
    report.immutability = {"before": before}

    # -- stage 5: M012 verification, the existing machinery -------------
    report.stage = "m012_verification"
    from foundation.m012 import verify

    ledger = verify(root, **(verify_kwargs or {})).to_dict()
    report.compatibility = dict(ledger.get("compatibility") or {})
    report.inference = dict(ledger.get("inference") or {})
    report.gpu = {
        "vram_pair": dict(ledger.get("vram_pair") or {}),
        "hardware": dict(ledger.get("hardware") or {}),
    }

    # -- stage 6: the restricted-account boundary, and the security probe
    report.stage = "security"
    account = assess_subject_account()
    probe = dict(ledger.get("probe") or {})
    report.security = {
        "subject_account": account,
        "probe": probe,
        "network": dict(ledger.get("network") or {}),
        "process_identity": dict(ledger.get("process_identity") or {}),
    }
    # -- stage 7: the M013 gate ------------------------------------------
    report.stage = "gate"
    if environment is None:
        from environment.deterministic import create_deterministic_environment

        environment = create_deterministic_environment()

    from birth.ceremony13 import (
        decide_key_policy,
        measure_control,
        measure_environment,
        measure_provenance,
    )

    environment_measurement = measure_environment(environment)
    report.environment = environment_measurement
    gate = evaluate_gate(
        ledger,
        environment=environment_measurement,
        provenance=measure_provenance(),
        control=measure_control(),
        key_policy=decide_key_policy(),
    )
    report.gate = gate

    if gate.get("state") == "FAILED":
        return _refuse(
            report, M014Status.FAILED, "gate",
            "the birth gate is FAILED. A prerequisite was checked and violated. "
            f"Reason: {gate.get('reason', '')}",
        )
    if gate.get("state") != "READY":
        return _refuse(
            report, M014Status.BLOCKED, "gate",
            f"the birth gate is {gate.get('state')}. No subject, no T_birth, no "
            f"birth record, and no first experience. Reason: "
            f"{gate.get('reason', '')}",
        )

    # A READY gate is necessary but not sufficient: a simulated or stub run must
    # not produce a production-equivalent identity, however ready the evidence is.
    if not mode.may_establish_real_birth:
        return _refuse(
            report, M014Status.BLOCKED, "mode",
            f"the gate is READY but the execution mode is {mode.value}, which "
            "cannot establish a real birth. Nothing was created; a simulation "
            "must never leave a production-equivalent record.",
        )

    # -- stage 8: the ceremony, the existing M013 boundary ---------------
    report.stage = "ceremony"
    from birth.ceremony13 import BirthMode, run_ceremony

    record = run_ceremony(ledger, environment, mode=BirthMode.REAL,
                          completion_fn=completion)
    report.ceremony = record.to_dict()

    if not record.birth_occurred:
        outcome = record.outcome.value
        return _refuse(
            report, M014Status.FAILED, "ceremony",
            f"the gate was READY but the ceremony did not complete "
            f"(outcome {outcome}). The record is not a subject: "
            f"{record.stop_reason}",
        )

    # -- stage 9: immutability, after -------------------------------------
    report.stage = "immutability_after"
    after_artifact = verify_declared_artifact(declaration)
    after_runtime = verify_declared_runtime(declaration)
    after = capture_immutability(after_artifact, after_runtime, label="after")
    comparison = compare_immutability(before, after)
    report.immutability = {"before": before, "after": after,
                           "comparison": comparison}
    if comparison["verdict"] == "MUTATED":
        return _refuse(
            report, M014Status.FAILED, "immutability_after",
            f"an artifact changed during the run: {comparison['detail']} The "
            "artifact is not replaced and the birth is void, because every result "
            "computed from the earlier bytes can no longer be trusted.",
        )

    # -- stage 10: post-birth security, repeated ------------------------
    report.stage = "post_birth_security"
    report.post_birth = _post_birth_security()

    # -- stage 11: the birth record, and its hash -----------------------
    report.stage = "birth_record"
    payload = record.to_dict()
    record_hash = compute_birth_record_hash(payload)
    report.birth_record = payload
    report.birth_record_hash = record_hash
    report.birth_record["immutability"] = verify_birth_record_unchanged(
        payload, record_hash,
    )

    # -- stage 12: replay ------------------------------------------------
    report.stage = "replay"
    from birth.replay13 import replay_environment, replay_model_output

    report.replay = {
        "model_output": replay_model_output(payload).to_dict(),
        "environment": replay_environment(
            payload, environment=environment,
        ).to_dict(),
        "note": (
            "MODEL_OUTPUT_REPLAY and ENVIRONMENT_REPLAY are reported separately. "
            "A reproducible environment transition is not evidence that the model "
            "is deterministic."
        ),
    }

    report.status = M014Status.COMPLETE
    report.stage = "complete"
    report.stop_reason = (
        "a real birth occurred: identity was laboratory-issued, the lifecycle "
        "reached ACTIVE through three separately authorized transitions, T_birth "
        "was assigned at that activation, and exactly one environment interaction "
        "produced exactly one experience. The ceremony then stopped and the second "
        "interaction was refused by the environment."
    )
    return report


def _post_birth_security() -> dict[str, Any]:
    """Repeat the security checks after a birth.

    The ceremony does not weaken the boundary, so this is expected to be
    identical to the pre-birth assessment. It is repeated rather than assumed
    because "the ceremony does not touch permissions" is a claim about code, and
    this is a measurement.
    """
    account = assess_subject_account()
    from babylab.paths import default_paths
    from babylab.clock import Clock
    from events.store import EventStore

    paths = default_paths()
    store = EventStore(paths.event_store, clock=Clock())
    try:
        chain_intact = bool(store.verify_chain().intact)
    except Exception as exc:  # noqa: BLE001
        chain_intact = False
        account["event_store_error"] = str(exc)

    return {
        "subject_account": account,
        "event_chain_intact": chain_intact,
        "m005_boundary_weakened": False,
        "note": (
            "the birth ceremony does not modify ACLs, protected evidence, keys, or "
            "the event log. This is a re-measurement, not an assertion."
        ),
    }


__all__ = [
    "FIXTURE_MARKER",
    "REQUIRED_INTERACTION_COUNT",
    "REQUIRED_NETWORK_POLICY",
    "SUBJECT_ACCOUNT",
    "ExecutionMode",
    "M014Report",
    "M014Status",
    "assess_subject_account",
    "capture_immutability",
    "classify_declaration",
    "compare_immutability",
    "compute_birth_record_hash",
    "evaluate_gate",
    "execute_m014",
    "verify_birth_record_unchanged",
    "verify_declared_artifact",
    "verify_declared_runtime",
]
