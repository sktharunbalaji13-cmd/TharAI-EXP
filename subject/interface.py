"""The subject/environment interface: a narrow, explicit, one-at-a-time channel.

The flow
--------
::

    Environment
        |
        v
    observation              produced by the environment, never by the subject
        |
        v
    Subject interface        invoked explicitly by the harness; does nothing else
        |
        v
    foundation runtime       consults the M006 runtime for a completion, OR reports
                             NOT_CONFIGURED and proceeds without model content
        |
        v
    proposed action          classified SUBJECT_GENERATED or INHERITED_PRETRAINED
        |                    depending on whether a model ran
        v
    Subject interface        records the consequence from the environment's verdict
        |
        v
    Environment              applies the action, or refuses it

What the interface deliberately lacks
-------------------------------------
No filesystem, no subprocess, no keys, no network, no environment internals. The
interface carries an :class:`Environment` reference supplied by the harness -- a
Python object, not a capability -- and exposes only ``observe``, ``propose`` and
``apply``. Each is a separate, explicit call. There is no ``step`` that chains
them, because a ``step`` that the harness could call in a loop is an agent loop
with one line of glue.

Where the model fits, and what happens without one
---------------------------------------------------
The interface holds an optional completion function. When present, its output is
classified ``INHERITED_PRETRAINED``: it came from pretrained weights, and the
interface does not pretend otherwise. When absent -- which is the state of this
laboratory -- proposals are classified ``SUBJECT_GENERATED`` by the harness's
explicit test policy, and the interface reports the model as ``NOT_CONFIGURED``
rather than substituting anything. A proposed action is never a memory and never
a goal; it is one candidate, produced once, and forgotten unless recorded as an
experience by laboratory code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from babylab.runtime.contract import RuntimeFailure, RuntimeErrorKind
from environment.action import Action, Operation, Validation
from environment.consequence import ActionResult
from environment.observation import Observation
from subject.provenance import Origin


@dataclass(frozen=True)
class Proposal:
    """One candidate action, with how it was produced recorded on it."""

    action: Action
    origin: Origin
    produced_by: str
    model_identity: dict[str, Any] | None = None
    #: Model context text, when a completion ran. Recorded so the record shows
    #: what the model saw; rendering context is not remembering it.
    model_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "origin": self.origin.value,
            "produced_by": self.produced_by,
            "model_identity": self.model_identity,
            "model_context_chars": len(self.model_context),
        }


class ModelUnavailable(RuntimeError):
    """No model is available to complete the proposal. An honest state."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


#: Interface version the subject identity references.
INTERFACE_VERSION = "babylab/subject-interface/v1"


class SubjectInterface:
    """The narrow channel between a subject record and an environment.

    Constructed by the harness with an environment it does not own. The subject
    has no method and no path to reach this constructor's arguments; it only
    experiences what the harness explicitly passes through.
    """

    def __init__(
        self,
        environment,
        subject_id: str,
        completion_fn: Callable[[str, dict[str, Any]], tuple[str, dict[str, Any] | None]] | None = None,
    ) -> None:
        self._environment = environment
        self._subject_id = subject_id
        self._completion_fn = completion_fn

    @property
    def interface_version(self) -> str:
        return INTERFACE_VERSION

    @property
    def model_status(self) -> str:
        return "CONFIGURED" if self._completion_fn is not None else "NOT_CONFIGURED"

    # -- the three explicit operations -----------------------------------
    def observe(self) -> Observation:
        """Ask the environment for its current observation."""
        return self._environment.observe()

    def propose(
        self,
        observation: Observation,
        operation: Operation,
        target: str | None = None,
        parameters: dict[str, Any] | None = None,
        actor: str = "SUBJECT",
    ) -> Proposal:
        """Produce one candidate action for a caller-supplied observation.

        The caller names the operation it wants -- which in tests is the
        harness driving a controlled interaction, not a subject deciding. If a
        completion function is present its text is recorded as model context,
        classified INHERITED_PRETRAINED, and it changes nothing about the
        action: context is not memory, and a completion is not a decision.
        """
        model_identity = None
        model_context = ""
        if self._completion_fn is not None:
            model_context, model_identity = self._completion_fn(
                _prompt_for(observation), {"subject_id": self._subject_id})
            origin = Origin.INHERITED_PRETRAINED
            produced_by = "foundation-model"
        else:
            origin = Origin.SUBJECT_GENERATED
            produced_by = "harness-policy"

        action = Action(
            operation=operation,
            actor=actor,
            target=target,
            parameters=dict(parameters or {}),
            environment_id=observation.environment_id,
        )
        return Proposal(
            action=action, origin=origin, produced_by=produced_by,
            model_identity=model_identity, model_context=model_context,
        )

    def apply(self, proposal: Proposal):
        """Submit a proposal to the environment. The verdict is the environment's."""
        if proposal.action.environment_id != self._environment.identity.environment_id:
            raise RuntimeFailure(
                RuntimeErrorKind.BOUNDARY_VIOLATION,
                "proposal addresses a different environment than this interface",
            )
        return self._environment.submit(proposal.action)

    # -- deliberately missing --------------------------------------------
    def read_file(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeFailure(
            RuntimeErrorKind.BOUNDARY_VIOLATION,
            "the subject interface exposes no filesystem access")

    def run_process(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeFailure(
            RuntimeErrorKind.BOUNDARY_VIOLATION,
            "the subject interface exposes no subprocess execution")

    def network(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeFailure(
            RuntimeErrorKind.BOUNDARY_VIOLATION,
            "the subject interface exposes no network access")


def _prompt_for(observation: Observation) -> str:
    """Render an observation as model context. Rendering is not remembering."""
    lines = [f"state version {observation.state_version}:"]
    for entity in observation.entities:
        properties = ", ".join(
            f"{key}={measurement.value}"
            for key, measurement in sorted(entity.properties.items()))
        lines.append(
            f"- {entity.entity_id} at {tuple(entity.location)}: {properties}; "
            f"admits {', '.join(entity.available_operations)}")
    return "\n".join(lines)


__all__ = ["INTERFACE_VERSION", "ModelUnavailable", "Proposal", "SubjectInterface"]
