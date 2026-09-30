"""Replay the M013 birth ceremony: a model-output replay and an environment replay.

These are two different claims and are kept separate on purpose. ``MODEL_OUTPUT_REPLAY``
asks whether the same input yields the same proposal. ``ENVIRONMENT_REPLAY`` asks whether
the same proposal against the same initial state yields the same event. Conflating them
would hide the one failure that matters for a birth: a proposal that is reproducible while
the environment event that supposedly taught the subject is not.

Replay never re-runs a birth. It reconstructs a ceremony from its record and a supplied
environment, and it verifies a completed ceremony's claims -- it does not mint a new subject,
set a new T_birth, or write an experience. Replaying the laboratory's evidence is a read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReplayVerdict(str, Enum):
    """What a replay established. ``UNVERIFIABLE`` is a real answer, not a failure."""

    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class ReplayCheck:
    """One replayed claim, with the evidence that settled it."""

    claim: str
    verdict: ReplayVerdict
    expected: Any = None
    observed: Any = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "verdict": self.verdict.value,
            "expected": self.expected,
            "observed": self.observed,
            "detail": self.detail,
        }


@dataclass
class ReplayReport:
    """The result of replaying one ceremony record."""

    ceremony_id: str
    replay_kind: str
    verdict: ReplayVerdict
    checks: list[ReplayCheck] = field(default_factory=list)
    note: str = ""

    @property
    def contradicted(self) -> list[ReplayCheck]:
        return [c for c in self.checks if c.verdict is ReplayVerdict.CONTRADICTED]

    @property
    def unverifiable(self) -> list[ReplayCheck]:
        return [c for c in self.checks if c.verdict is ReplayVerdict.UNVERIFIABLE]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ceremony_id": self.ceremony_id,
            "replay_kind": self.replay_kind,
            "verdict": self.verdict.value,
            "checks": [c.to_dict() for c in self.checks],
            "note": self.note,
        }


def _first(verdicts: list[ReplayVerdict]) -> ReplayVerdict:
    """The worst verdict wins, so a single contradiction is never averaged away."""
    if ReplayVerdict.CONTRADICTED in verdicts:
        return ReplayVerdict.CONTRADICTED
    if ReplayVerdict.UNVERIFIABLE in verdicts:
        return ReplayVerdict.UNVERIFIABLE
    return ReplayVerdict.CONFIRMED


def replay_model_output(
    record: dict[str, Any],
    *,
    propose_again: Any = None,
) -> ReplayReport:
    """Replay the model-output half: does the same input yield the same proposal?

    ``propose_again`` receives the recorded first observation and returns a proposal.
    Without it the claim is ``UNVERIFIABLE`` -- which is the honest answer here,
    because this host has no model to re-prompt. Returning ``CONFIRMED`` because no
    contradiction was found would be a claim about a model that was never asked.
    """
    checks: list[ReplayCheck] = []

    if not record.get("birth_occurred"):
        return ReplayReport(
            ceremony_id=record.get("ceremony_id", ""),
            replay_kind="MODEL_OUTPUT_REPLAY",
            verdict=ReplayVerdict.UNVERIFIABLE,
            checks=[ReplayCheck(
                claim="the model produced a proposal",
                verdict=ReplayVerdict.UNVERIFIABLE,
                detail="no birth occurred, so there is no model output to replay",
            )],
            note=(
                "model-output replay needs a completed birth; this ceremony did not "
                "complete, so nothing was replayed"
            ),
        )

    first_action = record.get("first_action") or {}
    expected_operation = first_action.get("operation")

    if propose_again is None:
        checks.append(ReplayCheck(
            claim="the same input yields the same proposal",
            verdict=ReplayVerdict.UNVERIFIABLE,
            expected=expected_operation,
            detail=(
                "no re-prompt was supplied; a completed birth on this host would need "
                "the declared runtime to reproduce the proposal"
            ),
        ))
        return ReplayReport(
            ceremony_id=record.get("ceremony_id", ""),
            replay_kind="MODEL_OUTPUT_REPLAY",
            verdict=ReplayVerdict.UNVERIFIABLE,
            checks=checks,
            note=(
                "the proposal was recorded but not re-derived; recording an output is "
                "not the same as reproducing it"
            ),
        )

    try:
        replayed = propose_again(record.get("first_observation") or {})
    except Exception as exc:  # noqa: BLE001
        checks.append(ReplayCheck(
            claim="the same input yields the same proposal",
            verdict=ReplayVerdict.CONTRADICTED,
            expected=expected_operation,
            detail=f"re-prompting raised {exc}",
        ))
        return ReplayReport(
            ceremony_id=record.get("ceremony_id", ""),
            replay_kind="MODEL_OUTPUT_REPLAY",
            verdict=ReplayVerdict.CONTRADICTED,
            checks=checks,
        )

    observed_operation = _proposal_operation(replayed)
    if observed_operation == expected_operation:
        checks.append(ReplayCheck(
            claim="the same input yields the same proposal",
            verdict=ReplayVerdict.CONFIRMED,
            expected=expected_operation, observed=observed_operation,
        ))
    else:
        checks.append(ReplayCheck(
            claim="the same input yields the same proposal",
            verdict=ReplayVerdict.CONTRADICTED,
            expected=expected_operation, observed=observed_operation,
            detail=(
                "the model proposed a different operation from the same input, so the "
                "recorded first experience is not reproducible"
            ),
        ))

    return ReplayReport(
        ceremony_id=record.get("ceremony_id", ""),
        replay_kind="MODEL_OUTPUT_REPLAY",
        verdict=_first([c.verdict for c in checks]),
        checks=checks,
    )


def replay_environment(
    record: dict[str, Any],
    *,
    environment: Any = None,
) -> ReplayReport:
    """Replay the environment half: same initial state and proposal, same event?

    This is the half that decides whether a first experience is genuine. If the
    proposal reproduces but the event does not, the subject's biography rests on an
    outcome that cannot be re-derived, and the correct answer is CONTRADICTED.
    """
    checks: list[ReplayCheck] = []
    ceremony_id = record.get("ceremony_id", "")

    if not record.get("birth_occurred"):
        return ReplayReport(
            ceremony_id=ceremony_id,
            replay_kind="ENVIRONMENT_REPLAY",
            verdict=ReplayVerdict.UNVERIFIABLE,
            checks=[ReplayCheck(
                claim="the environment event is reproducible",
                verdict=ReplayVerdict.UNVERIFIABLE,
                detail="no birth occurred, so there is no environment event to replay",
            )],
            note=(
                "environment replay needs a completed birth; this ceremony did not "
                "complete, so the environment was never changed"
            ),
        )

    if environment is None:
        checks.append(ReplayCheck(
            claim="the environment event is reproducible",
            verdict=ReplayVerdict.UNVERIFIABLE,
            detail="no environment was supplied to replay against",
        ))
        return ReplayReport(
            ceremony_id=ceremony_id,
            replay_kind="ENVIRONMENT_REPLAY",
            verdict=ReplayVerdict.UNVERIFIABLE,
            checks=checks,
        )

    first_result = record.get("first_result") or {}
    first_consequence = record.get("first_consequence") or {}

    # The replayed environment must be the one the birth was recorded against.
    # Two things are checked, because neither alone is sufficient: the state hash
    # identifies the world state, and the identity identifies the environment
    # that state belongs to. A fresh environment with an identical initial state
    # hashes the same, so the identity check is what distinguishes "the same world"
    # from "a different world that happens to start the same way".
    creation = record.get("creation_record") or {}
    try:
        actual_initial = environment.snapshot().state_hash
    except Exception as exc:  # noqa: BLE001
        checks.append(ReplayCheck(
            claim="the replay environment starts from the recorded state",
            verdict=ReplayVerdict.UNVERIFIABLE,
            detail=f"the environment could not be snapshotted: {exc}",
        ))
        return ReplayReport(
            ceremony_id=ceremony_id,
            replay_kind="ENVIRONMENT_REPLAY",
            verdict=ReplayVerdict.UNVERIFIABLE,
            checks=checks,
        )

    identity = getattr(environment, "identity", None)
    actual_environment_id = str(getattr(identity, "environment_id", "UNAVAILABLE"))
    actual_version = str(getattr(identity, "implementation_version", "UNAVAILABLE"))
    recorded_initial = creation.get("environment_initial_state_hash")
    recorded_environment_id = creation.get("environment_id")
    recorded_version = creation.get("environment_version")

    identity_matches = (
        recorded_environment_id == actual_environment_id
        and recorded_version == actual_version
    )
    if identity_matches:
        checks.append(ReplayCheck(
            claim="the replay environment is the recorded environment",
            verdict=ReplayVerdict.CONFIRMED,
            expected=f"{recorded_environment_id}@{recorded_version}",
            observed=f"{actual_environment_id}@{actual_version}",
        ))
    else:
        checks.append(ReplayCheck(
            claim="the replay environment is the recorded environment",
            verdict=ReplayVerdict.CONTRADICTED,
            expected=f"{recorded_environment_id}@{recorded_version}",
            observed=f"{actual_environment_id}@{actual_version}",
            detail=(
                "the replay targets a different environment than the one the birth "
                "was recorded against, so its events would describe another world"
            ),
        ))
        return ReplayReport(
            ceremony_id=ceremony_id,
            replay_kind="ENVIRONMENT_REPLAY",
            verdict=ReplayVerdict.CONTRADICTED,
            checks=checks,
        )

    if recorded_initial == actual_initial:
        checks.append(ReplayCheck(
            claim="the replay environment starts from the recorded state",
            verdict=ReplayVerdict.CONFIRMED,
            expected=recorded_initial, observed=actual_initial,
        ))
    else:
        checks.append(ReplayCheck(
            claim="the replay environment starts from the recorded state",
            verdict=ReplayVerdict.CONTRADICTED,
            expected=recorded_initial, observed=actual_initial,
            detail=(
                "the replay environment is not in the state the birth was recorded "
                "against, so any event comparison would be meaningless"
            ),
        ))
        return ReplayReport(
            ceremony_id=ceremony_id,
            replay_kind="ENVIRONMENT_REPLAY",
            verdict=ReplayVerdict.CONTRADICTED,
            checks=checks,
        )

    from environment.environment import Action, Operation

    operation = getattr(Operation, first_result.get("operation", "OBSERVE"),
                        Operation.OBSERVE)
    try:
        result = environment.submit(Action(operation=operation, actor="LABORATORY"))
    except Exception as exc:  # noqa: BLE001
        checks.append(ReplayCheck(
            claim="the same proposal yields the same validation",
            verdict=ReplayVerdict.CONTRADICTED,
            expected=first_result.get("validation"),
            detail=f"replaying the action raised {exc}",
        ))
        return ReplayReport(
            ceremony_id=ceremony_id,
            replay_kind="ENVIRONMENT_REPLAY",
            verdict=ReplayVerdict.CONTRADICTED,
            checks=checks,
        )

    replayed_validation = _value_of(getattr(result, "validation", None))
    if replayed_validation == first_result.get("validation"):
        checks.append(ReplayCheck(
            claim="the same proposal yields the same validation",
            verdict=ReplayVerdict.CONFIRMED,
            expected=first_result.get("validation"),
            observed=replayed_validation,
        ))
    else:
        checks.append(ReplayCheck(
            claim="the same proposal yields the same validation",
            verdict=ReplayVerdict.CONTRADICTED,
            expected=first_result.get("validation"),
            observed=replayed_validation,
            detail=(
                "the environment accepted a different outcome from the same action, "
                "so the recorded first experience cannot be re-derived"
            ),
        ))

    recorded_resulting = first_consequence.get("resulting_state_hash")
    try:
        replayed_resulting = environment.snapshot().state_hash
    except Exception as exc:  # noqa: BLE001
        checks.append(ReplayCheck(
            claim="the resulting state hash is reproducible",
            verdict=ReplayVerdict.UNVERIFIABLE,
            detail=f"the environment could not be snapshotted: {exc}",
        ))
    else:
        if replayed_resulting == recorded_resulting:
            checks.append(ReplayCheck(
                claim="the resulting state hash is reproducible",
                verdict=ReplayVerdict.CONFIRMED,
                expected=recorded_resulting, observed=replayed_resulting,
            ))
        else:
            checks.append(ReplayCheck(
                claim="the resulting state hash is reproducible",
                verdict=ReplayVerdict.CONTRADICTED,
                expected=recorded_resulting, observed=replayed_resulting,
            ))

    return ReplayReport(
        ceremony_id=ceremony_id,
        replay_kind="ENVIRONMENT_REPLAY",
        verdict=_first([c.verdict for c in checks]),
        checks=checks,
        note=(
            "the environment event was replayed against the recorded initial state; "
            "this is a read of the laboratory's evidence and minted no subject"
        ),
    )


def _value_of(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _proposal_operation(proposal: Any) -> Any:
    action = getattr(proposal, "action", proposal)
    operation = getattr(action, "operation", None)
    return _value_of(operation)


__all__ = [
    "ReplayCheck",
    "ReplayReport",
    "ReplayVerdict",
    "replay_environment",
    "replay_model_output",
]
