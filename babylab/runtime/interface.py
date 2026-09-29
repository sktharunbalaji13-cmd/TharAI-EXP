"""The constrained surface a subject may actually call.

Why this layer exists
---------------------
The adapter can run a model and the runtime can hold one. Neither is a boundary.
A subject handed a :class:`~babylab.runtime.runtime.FoundationRuntime` could ask
it to load any artifact it liked, or read a configuration that named a protected
path. This interface is the narrow door: it exposes generation, status and
shutdown, and nothing else.

What is structurally absent
--------------------------
* No filesystem access of any kind. There is no method that takes a path.
* No key material. The interface holds no reference to the keyring, the control
  token, or the provenance private keys, so it cannot hand them out.
* No provenance mutation. Recording happens *into* the laboratory, and the
  subject cannot supply or alter an authorship claim.
* No network, no subprocess, no environment, no arbitrary callback.
* No loop. A call returns a response; nothing here decides to call again.

Capabilities are declared, not implied
--------------------------------------
A caller may request a capability by name, but a request is a *statement of
intent* recorded in the response, never an authorisation. Anything not explicitly
granted by the laboratory's policy is refused and the refusal is visible. This
mirrors the M003/M004 trust model, where naming a capability was never the same
as holding it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from babylab.runtime.contract import (
    InferenceRequest,
    InferenceResponse,
    RuntimeErrorKind,
    RuntimeFailure,
    RuntimeState,
)

#: Capabilities a caller may *name*. Naming is recorded, not honoured.
DECLARABLE_CAPABILITIES = frozenset({
    "text_generation",
    "streaming",
    "cancellation",
    "status_readout",
    "shutdown",
})


@dataclass(frozen=True)
class CapabilityRequest:
    """What the caller believes it is asking for. Not an authorisation."""

    requested: tuple[str, ...]
    granted: tuple[str, ...]
    refused: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": list(self.requested),
            "granted": list(self.granted),
            "refused": list(self.refused),
            "note": "a request is a statement of intent, never an authorisation",
        }


class SubjectInterface:
    """The only surface a future subject is given.

    Constructed with a runtime it does not own and cannot replace. Swapping the
    model behind it changes the adapter, not this class.
    """

    def __init__(
        self,
        runtime,
        granted_capabilities: tuple[str, ...] = ("text_generation", "cancellation",
                                                  "status_readout", "shutdown"),
    ) -> None:
        self._runtime = runtime
        self._granted = frozenset(granted_capabilities)

    # -- what a subject may do -------------------------------------------
    def generate(self, prompt: str, *, request_id: str | None = None,
                 max_tokens: int = 256, temperature: float = 0.0,
                 seed: int = 0, stop: tuple[str, ...] = (),
                 timeout_seconds: float | None = None,
                 intent: str = "unspecified",
                 requested_capabilities: tuple[str, ...] = ()) -> InferenceResponse:
        """One generation. Stateless from the caller's point of view.

        There is no conversation object and no history: two calls with the same
        prompt and seed produce the same request, because nothing was remembered
        from the previous one.
        """
        if "text_generation" not in self._granted:
            raise RuntimeFailure(
                RuntimeErrorKind.CAPABILITY_DENIED,
                "this interface was not granted text_generation",
            )
        request = InferenceRequest(
            request_id=request_id or _new_request_id(),
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            stop=stop,
            timeout_seconds=timeout_seconds,
            intent=intent,
        )
        response = self._runtime.infer(request)
        decision = self.evaluate_capabilities(requested_capabilities)
        if decision.refused:
            # Visible refusal, appended to the response rather than hidden.
            response = _annotate(response, decision)
        return response

    def status(self) -> dict[str, Any]:
        """Telemetry only. No hidden state, no inferred mental quantities."""
        payload = self._runtime.status()
        payload["granted_capabilities"] = sorted(self._granted)
        return payload

    def cancel(self) -> None:
        if "cancellation" in self._granted:
            self._runtime.cancel()

    def shutdown(self) -> RuntimeState:
        if "shutdown" in self._granted:
            return self._runtime.shutdown()
        raise RuntimeFailure(
            RuntimeErrorKind.CAPABILITY_DENIED,
            "this interface was not granted shutdown",
        )

    # -- capability accounting ------------------------------------------
    def evaluate_capabilities(self, requested: tuple[str, ...]) -> CapabilityRequest:
        """Record what was asked for and what was actually available."""
        granted = tuple(c for c in requested if c in self._granted)
        refused = tuple(c for c in requested if c not in self._granted)
        return CapabilityRequest(tuple(requested), granted, refused)

    # -- what is deliberately missing ------------------------------------
    def read_file(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeFailure(
            RuntimeErrorKind.BOUNDARY_VIOLATION,
            "the subject interface exposes no filesystem access",
        )

    def run_process(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeFailure(
            RuntimeErrorKind.BOUNDARY_VIOLATION,
            "the subject interface exposes no subprocess execution",
        )

    def network(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeFailure(
            RuntimeErrorKind.BOUNDARY_VIOLATION,
            "the subject interface exposes no network access; inference is local",
        )

    def signing_key(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeFailure(
            RuntimeErrorKind.BOUNDARY_VIOLATION,
            "the subject interface holds no signing or control credential, and "
            "cannot be given one",
        )


def _annotate(response: InferenceResponse, decision: CapabilityRequest) -> InferenceResponse:
    """Attach capability accounting to a response, visibly."""
    from dataclasses import replace

    from babylab.runtime.contract import Measurement

    return replace(
        response,
        resources={
            **response.resources,
            "capabilities": Measurement.observed(
                decision.to_dict(), source="subject interface capability accounting"
            ),
        },
    )


def _new_request_id() -> str:
    import uuid

    return f"req-{uuid.uuid4().hex[:12]}"


__all__ = ["CapabilityRequest", "DECLARABLE_CAPABILITIES", "SubjectInterface"]
