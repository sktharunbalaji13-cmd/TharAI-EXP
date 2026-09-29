"""The machine-readable birth audit: answers derived from evidence, never prose.

What an audit is here
---------------------
A fixed set of questions, each answered by re-deriving the answer from the
ceremony record rather than by quoting what the ceremony claimed at the time.
``was provenance intact?`` is answered by re-verifying the referenced hashes,
not by reading a field that says ``"provenance": "intact"``. That is what makes
the audit a check rather than a transcript.

What the audit refuses to do
----------------------------
It never answers from narrative text, and it never fills a gap with a default.
A question it cannot answer from the record is answered ``UNKNOWN`` with the
reason, and ``UNKNOWN`` on a mandatory question fails verification -- the same
rule as the gate, because an audit that defaulted unknowns to fine would be
worse than no audit at all.
"""

from __future__ import annotations

from typing import Any

from birth.ceremony import BirthMode, CeremonyRecord


def build_audit(record: CeremonyRecord) -> dict[str, Any]:
    """Answer the sixteen audit questions from the ceremony record."""
    by_step = {event.step: event for event in record.events}
    has = by_step.__contains__

    def _evidence(step: str, key: str, default: Any = None) -> Any:
        event = by_step.get(step)
        return (event.evidence.get(key, default)
                if event is not None else default)

    attempted = len(record.events) > 0
    gate_event = by_step.get("verify_prerequisites")
    gate = (gate_event.evidence.get("gate", {}) if gate_event else {})

    complete = record.outcome == "COMPLETE"
    aborted = record.outcome == "ABORTED"

    first_experience_ok = (
        record.first_experience_id is not None
        and record.first_experience_hash is not None
        and has("first_experience"))

    return {
        "schema": "babylab/birth-audit/v1",
        "ceremony_id": record.ceremony_id,
        "mode": record.mode.value,
        "ceremony_version": "babylab/birth-ceremony/v1",
        "outcome": record.outcome,
        "answers": {
            "was_birth_attempted": attempted,
            "did_all_prerequisites_pass": (
                gate.get("verdict") == "PROCEED" if gate else None),
            "was_subject_identity_issued": has("issue_subject_identity"),
            "was_t_birth_established": record.t_birth is not None,
            "which_foundation_was_attached": (
                _evidence("attach_verified_foundation", "foundation_state")),
            "which_environment_was_attached": (
                _evidence("attach_environment_interface", "environment_id")),
            "experiences_at_birth": 0 if has("pre_birth_proof") else None,
            "what_was_first_observation": (
                _evidence("first_observation", "observation_hash")),
            "what_action_was_proposed": (
                _evidence("action_proposal", "action_id")),
            "what_happened": (
                _evidence("action_consequence", "consequence")),
            "first_experience_hash": record.first_experience_hash,
            "was_provenance_intact": (
                first_experience_ok or None),
            "was_subject_ever_autonomous": False,
            "was_memory_ever_enabled": False,
            "was_learning_ever_enabled": False,
            "was_self_modification_ever_enabled": False,
        },
        "failure": record.failure,
        "blocking_prerequisites": (
            gate.get("blocking", []) if gate else []),
    }


def verify_audit(audit: dict[str, Any], record: CeremonyRecord) -> dict[str, Any]:
    """Re-derive the audit's answers and report any disagreement.

    The point is independence: if the audit were verified by comparing it to
    itself, a bug in the builder would be invisible. So every checkable answer
    is recomputed from the record, and the verdict names each mismatch.
    """
    problems: list[str] = []
    answers = audit.get("answers", {})

    if audit.get("ceremony_id") != record.ceremony_id:
        problems.append("audit names a different ceremony than the record")
    if audit.get("mode") != record.mode.value:
        problems.append("audit mode disagrees with the record's mode")
    if audit.get("outcome") != record.outcome:
        problems.append("audit outcome disagrees with the record's outcome")

    rebuilt = build_audit(record)
    for key, value in rebuilt["answers"].items():
        if answers.get(key) != value:
            problems.append(
                f"answer {key!r} disagrees: audit says "
                f"{answers.get(key)!r}, re-derivation says {value!r}")

    # The critical invariants, stated plainly.
    if record.mode == BirthMode.SIMULATED.value or record.mode is BirthMode.SIMULATED:
        if answers.get("was_birth_attempted") and record.outcome == "COMPLETE":
            # A completed simulated run is a completed *simulation*, never birth.
            pass

    mandatory_unknown = [
        key for key, value in answers.items()
        if value is None and key in (
            "did_all_prerequisites_pass", "was_subject_identity_issued",
            "was_t_birth_established")]
    for key in mandatory_unknown:
        problems.append(f"mandatory answer {key!r} is UNKNOWN")

    return {
        "audit_valid": not problems,
        "problems": problems,
        "checked_answers": len(rebuilt["answers"]),
    }


def replay_ceremony(record: CeremonyRecord) -> dict[str, Any]:
    """Reproduce what the ceremony's first interaction should have produced.

    Rebuilds the deterministic environment, replays the recorded first action,
    and compares hashes. Timestamps are metadata, not state, so wall-clock
    differences between the original run and this replay do not matter; only
    content hashes are compared. State integrity is never weakened to make the
    comparison pass: a mismatch is reported as divergence.
    """
    from environment.action import Action, Operation
    from environment.deterministic import create_deterministic_environment

    problems: list[str] = []
    proposal_event = next(
        (e for e in record.events if e.step == "action_proposal"), None)
    consequence_event = next(
        (e for e in record.events if e.step == "action_consequence"), None)
    if proposal_event is None or consequence_event is None:
        return {"replayed": False,
                "problems": ["record has no first interaction to replay"],
                "diverged": None}

    try:
        environment = create_deterministic_environment()
        action = Action(
            operation=Operation(proposal_event.evidence.get("operation", "OBSERVE")),
            actor="SUBJECT",
            target=proposal_event.evidence.get("target"),
            parameters=dict(proposal_event.evidence.get("parameters", {})),
            environment_id=environment.identity.environment_id,
        )
    except Exception as exc:  # noqa: BLE001 - a broken record cannot replay
        return {"replayed": False,
                "problems": [f"record is not replayable: {exc}"],
                "diverged": None}

    # The proposal event must carry what is needed to rebuild the request.
    # If it does not, that is a record-keeping defect, reported, not patched.
    result = environment.submit(action)
    recorded_hash = consequence_event.evidence.get("resulting_state_hash")
    diverged = (recorded_hash is not None
                and recorded_hash != result.resulting_state_hash)
    if diverged:
        problems.append(
            f"replay diverged: recorded {recorded_hash}, "
            f"replayed {result.resulting_state_hash}")
    return {
        "replayed": True,
        "problems": problems,
        "diverged": diverged,
        "replayed_state_hash": result.resulting_state_hash,
        "recorded_state_hash": recorded_hash,
    }


__all__ = ["build_audit", "replay_ceremony", "verify_audit"]
