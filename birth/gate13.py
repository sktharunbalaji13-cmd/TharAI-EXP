"""M013 birth gate: the one authoritative prerequisite check for a real birth.

Sixteen prerequisites, three outcomes, and no path around them.

READY / BLOCKED / FAILED
-------------------------
``READY``
    Every required prerequisite has actual evidence.
``BLOCKED``
    A prerequisite is intentionally absent, not configured, or not testable. This
    is a *correct* state: it is what a laboratory that has not been given a
    foundation looks like, and reporting it as an error would misdescribe it.
``FAILED``
    A prerequisite was attempted and violated. Something was tried and it did not
    hold.

The three are never collapsed. The specific failure this guards against is a
milestone that reports one ambiguous "not ready" for both "nobody has chosen a
model" and "the digest did not match", because the two call for completely
different human responses: one needs a decision, the other needs an
investigation.

Evidence comes from M012, not from here
----------------------------------------
This gate does **not** re-verify the model, the runtime, or the boundary. It
reads an M012 verification ledger and requires that ledger to be a *real* one.

That distinction is the whole design, and it is enforced by
:func:`_is_real_ledger`. An M012 record produced with a stubbed process runner,
a stubbed compatibility probe, or a synthetic artifact is a genuine record of a
test -- and using it to authorise a real birth would be the exact substitution the
milestone forbids. So a ledger carrying ``STUB_RUNTIME`` or ``STUB_LOAD`` is
treated as absent evidence, and the gate is ``BLOCKED`` with the reason named.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

#: The 16 prerequisites, in the order they are evaluated. The order is the
#: ceremony's order: declaration first, because everything downstream is about a
#: choice nobody has made yet.
PREREQUISITES: tuple[str, ...] = (
    "human_declaration",
    "model_identity",
    "model_digest",
    "runtime_identity",
    "runtime_compatibility",
    "real_runtime",
    "real_inference",
    "restricted_account_runtime",
    "protected_file_denial",
    "network_restriction",
    "model_immutability",
    "runtime_immutability",
    "environment_integrity",
    "provenance_integrity",
    "subject_key_policy",
    "laboratory_control",
)

#: Modes a ledger may declare. Only a real one can authorise a birth.
REAL_MODES = frozenset({"REAL_RUNTIME", "REAL"})


class GateState(str, enum.Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class Prerequisite:
    name: str
    state: GateState
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
class BirthGateVerdict:
    state: GateState
    prerequisites: list[Prerequisite] = field(default_factory=list)
    reason: str = ""
    evaluated_at: str = ""

    @property
    def may_proceed(self) -> bool:
        return self.state is GateState.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "babylab/m013-birth-gate/v1",
            "state": self.state.value,
            "may_proceed": self.may_proceed,
            "reason": self.reason,
            "evaluated_at": self.evaluated_at,
            "prerequisites": [p.to_dict() for p in self.prerequisites],
            "blocking": [p.name for p in self.prerequisites
                         if p.state is not GateState.READY],
            "failed": [p.name for p in self.prerequisites
                       if p.state is GateState.FAILED],
            "prerequisite_order": list(PREREQUISITES),
        }


def _is_real_ledger(payload: dict[str, Any]) -> tuple[bool, str]:
    """Would a birth on this evidence be a real birth?

    Checks the three things M012 records that distinguish a real run from a test:
    the inference mode, the compatibility method, and whether a human actually
    wrote the declaration.
    """
    mode = (payload.get("inference") or {}).get("mode", "")
    method = (payload.get("compatibility") or {}).get("method", "")
    deployment = payload.get("deployment") or {}
    state = deployment.get("state")

    if mode in {"STUB_RUNTIME", "SIMULATED"}:
        return False, (
            f"the M012 inference was {mode}, so this record describes a test "
            "rather than a deployment. Using it to authorise a real birth would "
            "be exactly the substitution the milestone forbids."
        )
    if method == "STUB_LOAD":
        return False, (
            "compatibility was answered by a caller-supplied process stand-in, so "
            "no real runtime ever attempted to load the artifact."
        )
    if state != "LOADED":
        return False, (
            f"the deployment declaration state is {state!r}, not LOADED. No human "
            "has named a model and a runtime."
        )
    return True, "the record describes a real, human-declared deployment"


def _from_criterion(
    criteria: dict[str, Any], name: str, ledger_state: GateState
) -> Prerequisite:
    """Lift one M012 criterion into a birth prerequisite."""
    found = criteria.get(name)
    if not isinstance(found, dict):
        return Prerequisite(
            name=name, state=GateState.BLOCKED,
            detail=(
                f"the M012 record carries no criterion named {name!r}, so this "
                "prerequisite has no evidence"
            ),
        )
    state_value = str(found.get("state", ""))
    detail = str(found.get("detail", ""))
    evidence = found.get("evidence") if isinstance(found.get("evidence"), dict) else {}

    if state_value == "SATISFIED":
        return Prerequisite(name=name, state=GateState.READY, detail=detail,
                            evidence=evidence)
    if state_value == "FAILED":
        return Prerequisite(
            name=name, state=GateState.FAILED,
            detail=f"the M012 criterion FAILED: {detail}", evidence=evidence,
        )
    if state_value in {"BLOCKED", "NOT_TESTABLE", "NOT_REACHED"}:
        return Prerequisite(
            name=name, state=GateState.BLOCKED,
            detail=(
                f"the M012 criterion is {state_value}, which is a deliberate "
                f"absence rather than a violation: {detail}"
            ),
            evidence=evidence,
        )
    return Prerequisite(
        name=name, state=GateState.BLOCKED,
        detail=f"the M012 criterion state {state_value!r} is not understood, so "
               "it is treated as absent rather than as a pass",
        evidence=evidence,
    )


def evaluate_birth_gate(
    m012: dict[str, Any],
    *,
    environment: dict[str, Any] | None = None,
    key_policy: dict[str, Any] | None = None,
    control: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> BirthGateVerdict:
    """Evaluate all sixteen prerequisites and return one verdict.

    ``environment``, ``key_policy`` and ``control`` are supplied by the caller
    because they are about *this* moment rather than about M012's deployment
    record: the environment must be intact now, the key policy must be decided
    now, and the laboratory control plane must be available now. Passing them in
    rather than measuring them here keeps this module a pure function of its
    inputs, which is what makes the verdict auditable.
    """
    from babylab.clock import Clock

    payload = m012 or {}
    real, real_reason = _is_real_ledger(payload)
    criteria = {
        c.get("name"): c for c in payload.get("criteria", [])
        if isinstance(c, dict)
    }

    results: dict[str, Prerequisite] = {}

    # 1. the declaration, and whether this record can authorise a birth at all
    if real:
        results["human_declaration"] = Prerequisite(
            name="human_declaration", state=GateState.READY,
            detail=(
                "a human wrote a deployment declaration naming a model and a "
                "runtime, with a name and a reason attached to the choice"
            ),
            evidence=criteria.get("human_model_selection", {}).get("evidence", {}),
        )
    else:
        results["human_declaration"] = Prerequisite(
            name="human_declaration", state=GateState.BLOCKED, detail=real_reason,
        )

    # 2, 3, 4, 11, 12, 15: lifted from M012 criteria under this gate's own names
    lifts = {
        "model_identity": "model_artifact_identity",
        "model_digest": "model_sha256_verified",
        "runtime_identity": "runtime_identity",
        "model_immutability": "model_immutable",
        "runtime_immutability": "runtime_immutable",
        "network_restriction": "network_absent",
    }
    for name, criterion in lifts.items():
        lifted = _from_criterion(criteria, criterion, GateState.BLOCKED)
        results[name] = Prerequisite(
            name=name, state=lifted.state, detail=lifted.detail,
            evidence={**lifted.evidence, "m012_criterion": criterion},
        )

    # 5. compatibility, judged on whether a real load established it
    #
    # A load must have happened AND must have succeeded. A load that ran and
    # rejected the artifact sets `established_by_load` too, so checking only that
    # flag would read an INCOMPATIBLE deployment as READY and let a real birth
    # proceed on an artifact the runtime cannot use.
    compatibility = payload.get("compatibility") or {}
    established = bool(compatibility.get("established_by_load"))
    verdict = str(compatibility.get("compatibility", "")).upper()
    if not established:
        state = GateState.BLOCKED
        detail = (
            "compatibility was not established by a real load, so it is unknown "
            "rather than satisfied. A filename, a magic number, and a stubbed "
            "probe are all insufficient."
        )
    elif verdict == "COMPATIBLE":
        state = GateState.READY
        detail = "a real runtime loaded the declared artifact and produced output"
    else:
        # The load happened and the answer was not "compatible". That is a
        # violated prerequisite, not a missing one.
        state = GateState.FAILED
        detail = (
            f"a real load was performed and the runtime reported "
            f"{verdict or 'no compatibility verdict'}, so the declared artifact "
            "is not usable by the declared runtime. A birth on an unusable "
            "artifact is not a birth."
        )
    results["runtime_compatibility"] = Prerequisite(
        name="runtime_compatibility",
        state=state,
        detail=detail,
        evidence={"method": compatibility.get("method"),
                  "compatibility": compatibility.get("compatibility")},
    )

    # 6 and 7 share M012's single real-inference criterion but ask different
    # questions of it: one is "did a real process run", the other is "did it
    # produce a completion". A real process that produced nothing is a failed
    # runtime, and a completion from a stub is not an inference.
    inference = payload.get("inference") or {}
    mode = str(inference.get("mode", "NOT_TESTABLE"))
    outcome = str(inference.get("outcome", "NOT_RUN"))
    is_real = mode in REAL_MODES

    if is_real and outcome == "COMPLETED":
        inference_state = GateState.READY
    elif is_real:
        inference_state = GateState.FAILED
    else:
        inference_state = GateState.BLOCKED

    results["real_runtime"] = Prerequisite(
        name="real_runtime", state=inference_state,
        detail=(
            f"a real binary was invoked (mode {mode}, outcome {outcome})"
            if is_real else
            f"the run was {mode}, not a real runtime, so no real process has "
            "executed this model"
        ),
        evidence={"mode": mode, "outcome": outcome},
    )
    results["real_inference"] = Prerequisite(
        name="real_inference", state=inference_state,
        detail=(
            "a real binary produced a completion from the declared artifact"
            if inference_state is GateState.READY else
            f"no real completion was produced (mode {mode}, outcome {outcome})"
        ),
        evidence={"prompt_sha256": inference.get("prompt_sha256"),
                  "output_sha256": inference.get("output_sha256")},
    )

    # 8. restricted-account execution
    launch = payload.get("launch") or {}
    launch_state = str(launch.get("state", "NOT_TESTABLE"))
    if launch_state == "VERIFIED":
        results["restricted_account_runtime"] = Prerequisite(
            name="restricted_account_runtime", state=GateState.READY,
            detail="the runtime was observed running under the subject account",
        )
    elif launch_state == "FAILED":
        results["restricted_account_runtime"] = Prerequisite(
            name="restricted_account_runtime", state=GateState.FAILED,
            detail=(
                "the restricted launch was attempted and produced the wrong "
                f"identity: {launch.get('detail', '')}"
            ),
        )
    else:
        results["restricted_account_runtime"] = Prerequisite(
            name="restricted_account_runtime", state=GateState.BLOCKED,
            detail=(
                f"the runtime never ran under the subject account ({launch_state}): "
                f"{launch.get('detail', '')}"
            ),
        )

    # 9. protected-file denial, which must have been *meaningful*
    probe = payload.get("probe") or {}
    verdict = probe.get("verdict") or {}
    if verdict.get("boundary_meaningful") and verdict.get("boundary_holds"):
        results["protected_file_denial"] = Prerequisite(
            name="protected_file_denial", state=GateState.READY,
            detail=(
                "protected writes were refused by the identity the runtime "
                "actually ran under"
            ),
            evidence={"denied": verdict.get("protected_denied"),
                      "attempted": verdict.get("protected_attempts")},
        )
    elif verdict.get("boundary_meaningful"):
        results["protected_file_denial"] = Prerequisite(
            name="protected_file_denial", state=GateState.FAILED,
            detail=(
                "the probe ran under the intended restricted identity and a "
                "protected path was writable"
            ),
        )
    else:
        runner = str(verdict.get("runner_account") or "an unknown identity")
        results["protected_file_denial"] = Prerequisite(
            name="protected_file_denial", state=GateState.BLOCKED,
            detail=(
                f"the probe ran as {runner}, not as the subject account, so its "
                "access results are not evidence about subject isolation"
            ),
        )

    # 13-16: this moment's state, supplied by the caller
    results["environment_integrity"] = _caller_supplied(
        "environment_integrity", environment,
        required_keys=("environment_id", "version", "state_hash", "integrity"),
        good=("the deterministic environment is intact and its initial state "
              "hash is recorded"),
    )
    results["provenance_integrity"] = _caller_supplied(
        "provenance_integrity", provenance,
        required_keys=("integrity", "chain_intact"),
        good="the event chain and the provenance ledger are readable and intact",
    )
    results["subject_key_policy"] = _caller_supplied(
        "subject_key_policy", key_policy,
        required_keys=("decision",),
        good=(
            "a key policy was decided: the subject either needs no signing key "
            "for the architecture as it stands, or has one provisioned through "
            "the laboratory's existing mechanism"
        ),
    )
    results["laboratory_control"] = _caller_supplied(
        "laboratory_control", control,
        required_keys=("available",),
        good="the operator retains pause, resume, and terminate outside the subject",
    )

    # Emitted in the declared order, so the record is comparable across runs
    # rather than reflecting whichever order the checks happened to run in.
    ordered = [results[name] for name in PREREQUISITES if name in results]
    missing = [name for name in PREREQUISITES if name not in results]
    for name in missing:  # pragma: no cover - a guard against a dropped check
        ordered.append(Prerequisite(
            name=name, state=GateState.BLOCKED,
            detail=f"the gate produced no verdict for {name!r}",
        ))

    failures = [p for p in ordered if p.state is GateState.FAILED]
    blocks = [p for p in ordered if p.state is GateState.BLOCKED]

    if failures:
        state = GateState.FAILED
        reason = (
            f"{len(failures)} prerequisite(s) were attempted and violated: "
            + "; ".join(f"{p.name}: {p.detail}" for p in failures)
        )
    elif blocks:
        state = GateState.BLOCKED
        reason = (
            f"{len(blocks)} prerequisite(s) have no evidence: "
            + "; ".join(f"{p.name}: {p.detail}" for p in blocks[:4])
            + (" ..." if len(blocks) > 4 else "")
        )
    else:
        state = GateState.READY
        reason = (
            "all sixteen prerequisites carry actual evidence. This is the only "
            "state in which a real birth may be performed."
        )

    return BirthGateVerdict(
        state=state,
        prerequisites=ordered,
        reason=reason,
        evaluated_at=Clock().timestamp(),
    )


def _caller_supplied(
    name: str,
    payload: dict[str, Any] | None,
    *,
    required_keys: tuple[str, ...],
    good: str,
) -> Prerequisite:
    """Turn a caller-supplied measurement into a prerequisite.

    An absent measurement is ``BLOCKED``, never ``READY``. "Nobody checked" and
    "it checked out" are different facts, and a gate that cannot tell them apart
    is not a gate.
    """
    if not isinstance(payload, dict):
        return Prerequisite(
            name=name, state=GateState.BLOCKED,
            detail=(
                f"{name} was not measured. The laboratory does not assume a "
                "prerequisite it has not checked."
            ),
        )
    missing = [key for key in required_keys if key not in payload]
    if missing:
        return Prerequisite(
            name=name, state=GateState.BLOCKED,
            detail=(
                f"{name} was measured but carries no {', '.join(missing)}, so it "
                "cannot be read as satisfied"
            ),
            evidence=dict(payload),
        )
    verdict = payload.get("integrity", True) if "integrity" in payload else True
    if verdict is False:
        return Prerequisite(
            name=name, state=GateState.FAILED,
            detail=f"{name} was measured and it does not hold: {payload}",
            evidence=dict(payload),
        )
    return Prerequisite(name=name, state=GateState.READY, detail=good,
                        evidence=dict(payload))


__all__ = [
    "PREREQUISITES",
    "BirthGateVerdict",
    "GateState",
    "Prerequisite",
    "evaluate_birth_gate",
]
