"""The inference runtime: policy, lifecycle, events, and honest failure.

Where this sits
---------------
Above the adapter. The adapter knows how to run one model. This layer decides
*whether* it may run, *under what limits*, *what gets recorded*, and *what the
subject is allowed to ask for*. Keeping that above the adapter is what makes the
trust boundary meaningful: a new runtime cannot arrive already holding privilege,
because privilege is not the adapter's to hold.

What it guarantees
------------------
* A missing model is :attr:`RuntimeState.NOT_CONFIGURED`, never a fabricated
  model and never a substitute one.
* Every lifecycle transition emits an event to the existing :class:`EventStore`,
  so the M002 Observatory sees runtime activity with no new plumbing.
* No prompt text, no generated text, and no file content is written to the event
  log. Identity, metrics and outcomes only.
* No conversation is retained between calls. ``InferenceRequest`` is complete on
  its own; there is no session object, no memory, and no hidden state.
* No autonomous behaviour. Nothing here loops, schedules, retries on its own, or
  decides to run again.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from babylab.runtime.contract import (
    EpistemicStatus,
    FinishReason,
    InferenceRequest,
    InferenceResponse,
    Measurement,
    ModelAdapter,
    RuntimeErrorKind,
    RuntimeFailure,
    RuntimeIdentity,
    RuntimeState,
)
from babylab.runtime.governor import Admission, ResourcePolicy, evaluate_load
from babylab.runtime.hardware import HardwareReport, detect_hardware
from babylab.runtime.registry import AdapterRegistry, DEFAULT_REGISTRY

#: Event source name. A component name, not an authorship claim.
RUNTIME_SOURCE = "babylab.runtime"


@dataclass
class ModelDeclaration:
    """What the configuration says about a model. Never discovered at runtime.

    ``sha256`` is the artifact's externally derived identity. The runtime
    verifies the file against it; it is not taken from the model, and not
    accepted from the model as evidence of anything.
    """

    adapter_id: str
    model_path: str
    sha256: str
    model_family: str = ""
    model_name: str = ""
    quantization: str = ""
    context_length: int = 2048
    model_size_bytes: int | None = None
    runtime_binary: str | None = None
    runtime_version: str = ""
    license: str = ""
    license_url: str = ""
    source_url: str = ""
    declared_by: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "model_path": self.model_path,
            "sha256": self.sha256,
            "model_family": self.model_family,
            "model_name": self.model_name,
            "quantization": self.quantization,
            "context_length": self.context_length,
            "model_size_bytes": self.model_size_bytes,
            "runtime_binary": self.runtime_binary,
            "runtime_version": self.runtime_version,
            "license": self.license,
            "license_url": self.license_url,
            "source_url": self.source_url,
            "declared_by": self.declared_by,
            "notes": self.notes,
        }


class FoundationRuntime:
    """One runtime instance: load, infer, observe, shut down.

    Not a singleton and not a service. Constructing one has no side effects beyond
    probing the host, and :meth:`shutdown` releases everything it held.
    """

    def __init__(
        self,
        registry: AdapterRegistry | None = None,
        policy: ResourcePolicy | None = None,
        hardware: HardwareReport | None = None,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._registry = registry if registry is not None else DEFAULT_REGISTRY
        self._policy = policy or ResourcePolicy()
        self._hardware = hardware if hardware is not None else detect_hardware()
        self._event_sink = event_sink
        self._adapter: ModelAdapter | None = None
        self._declaration: ModelDeclaration | None = None
        self._state = RuntimeState.NOT_CONFIGURED
        self._instance_id = f"runtime-{uuid.uuid4().hex[:12]}"
        self._last_response: InferenceResponse | None = None
        self._inference_count = 0
        self._failure_detail = ""

    # -- observation -----------------------------------------------------
    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def state(self) -> RuntimeState:
        return self._state

    @property
    def policy(self) -> ResourcePolicy:
        return self._policy

    @property
    def hardware(self) -> HardwareReport:
        return self._hardware

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit an event. Never emits prompt or completion text."""
        if self._event_sink is None:
            return
        self._event_sink(event_type, payload)

    def _identity_payload(self) -> dict[str, Any]:
        if self._adapter is None:
            return {}
        try:
            return self._adapter.identity().to_dict()
        except Exception:  # noqa: BLE001 - identity must never break the runtime
            return {}

    # -- lifecycle -------------------------------------------------------
    def configure(self, declaration: ModelDeclaration) -> RuntimeState:
        """Admit or refuse a declared model. No discovery, no substitution."""
        self._declaration = declaration
        self._emit("runtime.configure.requested", {
            "instance": self._instance_id,
            "adapter": declaration.adapter_id,
            "model_name": declaration.model_name or "(undeclared)",
            "quantization": declaration.quantization or "(undeclared)",
            "declared_sha256": declaration.sha256 or "(none)",
            "declared_by": declaration.declared_by or "(unattributed)",
        })

        try:
            self._registry.describe(declaration.adapter_id)
        except RuntimeFailure as failure:
            self._state = RuntimeState.NOT_CONFIGURED
            self._failure_detail = failure.detail
            self._emit("runtime.configure.refused", {
                "instance": self._instance_id,
                "adapter": declaration.adapter_id,
                "reason": failure.kind.value,
                "detail": failure.detail,
            })
            return self._state

        decision = evaluate_load(
            declaration.model_size_bytes,
            declaration.context_length,
            self._hardware,
            self._policy,
        )
        self._emit("runtime.admission.evaluated", {
            "instance": self._instance_id,
            **decision.to_dict(),
        })
        if decision.admission is Admission.REFUSE:
            self._state = RuntimeState.NOT_CONFIGURED
            self._failure_detail = decision.reason
            self._emit("runtime.configure.refused", {
                "instance": self._instance_id,
                "reason": "admission_refused",
                "detail": decision.reason,
            })
            return self._state
        if decision.admission is Admission.UNKNOWN:
            # Reported, not treated as permission. Configuration can still
            # proceed; the uncertainty is recorded so it is visible later.
            self._emit("runtime.admission.uncertain", {
                "instance": self._instance_id,
                "detail": decision.reason,
            })

        self._emit("runtime.configure.accepted", {
            "instance": self._instance_id,
            "adapter": declaration.adapter_id,
            "model_path": declaration.model_path,
        })
        self._state = RuntimeState.NOT_CONFIGURED  # not loaded yet
        return self._state

    def load(self) -> RuntimeState:
        """Instantiate the adapter and verify the artifact's identity."""
        if self._declaration is None:
            self._state = RuntimeState.NOT_CONFIGURED
            self._failure_detail = "no model was declared"
            self._emit("runtime.model.load.failed", {
                "instance": self._instance_id,
                "reason": RuntimeErrorKind.NOT_CONFIGURED.value,
                "detail": "no model was declared; the laboratory does not "
                          "search for one, download one, or substitute one",
            })
            return self._state

        declaration = self._declaration
        self._state = RuntimeState.LOADING
        self._emit("runtime.model.load.requested", {
            "instance": self._instance_id,
            "adapter": declaration.adapter_id,
            "model_path": declaration.model_path,
        })

        try:
            adapter = self._registry.create(declaration.adapter_id)
            adapter = _configure_adapter(adapter, declaration)
            available, detail = adapter.probe()
            if not available:
                raise RuntimeFailure(
                    RuntimeErrorKind.RUNTIME_MISSING, detail,
                    adapter_id=declaration.adapter_id,
                )
            identity = adapter.load(declaration.model_path, declaration.sha256)
        except RuntimeFailure as failure:
            self._adapter = None
            self._state = (
                RuntimeState.RUNTIME_UNAVAILABLE
                if failure.kind is RuntimeErrorKind.RUNTIME_MISSING
                else RuntimeState.NOT_CONFIGURED
            )
            self._failure_detail = failure.detail
            self._emit("runtime.model.load.failed", {
                "instance": self._instance_id,
                "reason": failure.kind.value,
                "detail": failure.detail,
                "context": failure.context,
            })
            return self._state
        except Exception as exc:  # noqa: BLE001 - a crash is a failure, not a pass
            self._adapter = None
            self._state = RuntimeState.FAILED
            self._failure_detail = f"{type(exc).__name__}: {exc}"
            self._emit("runtime.model.load.failed", {
                "instance": self._instance_id,
                "reason": RuntimeErrorKind.GENERATION_FAILED.value,
                "detail": f"{type(exc).__name__}: {exc}",
            })
            return self._state

        self._adapter = adapter
        self._state = RuntimeState.READY
        self._emit("runtime.model.load.succeeded", {
            "instance": self._instance_id,
            "runtime": self._identity_payload(),
            "artifact": {
                "path": identity.get("path"),
                "sha256": identity.get("sha256"),
                "size_bytes": identity.get("size_bytes"),
                "format": identity.get("format"),
                "digest_verified": identity.get("digest_verified"),
            },
            "model": {
                "family": declaration.model_family,
                "name": declaration.model_name,
                "quantization": declaration.quantization,
                "context_length": declaration.context_length,
                "license": declaration.license or "UNKNOWN",
            },
        })
        return self._state

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        """One generation. No memory, no loop, no autonomous continuation."""
        if self._adapter is None or self._state is not RuntimeState.READY:
            failure = RuntimeFailure(
                RuntimeErrorKind.NOT_CONFIGURED,
                self._failure_detail
                or f"runtime is {self._state.value}, not READY",
            )
            self._emit("runtime.inference.failed", {
                "instance": self._instance_id,
                "request_id": request.request_id,
                "reason": failure.kind.value,
                "detail": failure.detail,
            })
            return InferenceResponse(
                request_id=request.request_id,
                finish_reason=FinishReason.ERROR,
                error=failure.detail,
                runtime_identity=self._identity_payload(),
            )

        if self._state is RuntimeState.GENERATING:
            detail = "a generation is already in flight; the runtime is single-flight"
            self._emit("runtime.inference.failed", {
                "instance": self._instance_id,
                "request_id": request.request_id,
                "reason": RuntimeErrorKind.CAPABILITY_DENIED.value,
                "detail": detail,
            })
            return InferenceResponse(
                request_id=request.request_id,
                finish_reason=FinishReason.ERROR,
                error=detail,
            )

        if request.max_tokens > self._policy.max_context_length:
            detail = (
                f"max_tokens {request.max_tokens} exceeds the policy ceiling "
                f"{self._policy.max_context_length}"
            )
            self._emit("runtime.inference.failed", {
                "instance": self._instance_id,
                "request_id": request.request_id,
                "reason": RuntimeErrorKind.CAPABILITY_DENIED.value,
                "detail": detail,
            })
            return InferenceResponse(
                request_id=request.request_id,
                finish_reason=FinishReason.ERROR,
                error=detail,
            )

        self._inference_count += 1
        self._state = RuntimeState.GENERATING
        self._emit("runtime.inference.requested", {
            "instance": self._instance_id,
            "request_id": request.request_id,
            "intent": request.intent,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "seed": request.seed,
            # Length only. The text itself is never written to the event log.
            "prompt_chars": len(request.prompt),
        })
        self._emit("runtime.inference.started", {
            "instance": self._instance_id,
            "request_id": request.request_id,
            "runtime": self._identity_payload(),
        })

        started = time.perf_counter()
        try:
            response = self._adapter.generate(request)
        except RuntimeFailure as failure:
            # A hard adapter failure leaves the runtime FAILED rather than READY:
            # the `finally` below restores READY only when it did not already
            # record a worse state, so an exception is not silently forgotten.
            self._state = RuntimeState.FAILED
            self._emit("runtime.inference.failed", {
                "instance": self._instance_id,
                "request_id": request.request_id,
                "reason": failure.kind.value,
                "detail": failure.detail,
            })
            return InferenceResponse(
                request_id=request.request_id,
                finish_reason=FinishReason.ERROR,
                error=failure.detail,
                runtime_identity=self._identity_payload(),
            )
        finally:
            if self._state is RuntimeState.GENERATING:
                self._state = RuntimeState.READY

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response = _with_measured_duration(response, elapsed_ms)

        event_type = {
            FinishReason.CANCELLED: "runtime.inference.cancelled",
            FinishReason.TIMEOUT: "runtime.inference.cancelled",
        }.get(response.finish_reason, "runtime.inference.completed")

        self._emit(event_type, {
            "instance": self._instance_id,
            "request_id": request.request_id,
            "runtime": response.runtime_identity,
            "model": response.model_identity,
            "finish_reason": response.finish_reason.value,
            "prompt_tokens": response.prompt_tokens.to_dict(),
            "completion_tokens": response.completion_tokens.to_dict(),
            "inference_duration_ms": response.inference_duration_ms.to_dict(),
            "tokens_per_second": response.tokens_per_second.to_dict(),
            "completion_chars": len(response.text),
            "error": response.error or None,
        })
        self._last_response = response
        return response

    def stream(self, request: InferenceRequest) -> Any:
        """Streaming, when the adapter supports it. Absent is reported as absent."""
        if self._adapter is None or not self._adapter.supports_streaming():
            return None
        return self._adapter.stream(request)

    def cancel(self) -> None:
        """Ask an in-flight generation to stop. Never initiates anything."""
        if self._adapter is not None:
            self._adapter.cancel()
        self._emit("runtime.cancel.requested", {"instance": self._instance_id})

    def shutdown(self) -> RuntimeState:
        """Release everything. Idempotent."""
        if self._adapter is not None:
            try:
                self._adapter.unload()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                self._emit("runtime.shutdown.unload_failed", {
                    "instance": self._instance_id,
                    "detail": f"{type(exc).__name__}: {exc}",
                })
        self._adapter = None
        self._state = RuntimeState.SHUTDOWN
        self._emit("runtime.shutdown", {
            "instance": self._instance_id,
            "inference_count": self._inference_count,
        })
        return self._state

    # -- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """A status display may call this. It never raises."""
        return {
            "instance": self._instance_id,
            "state": self._state.value,
            "failure_detail": self._failure_detail,
            "runtime": self._identity_payload(),
            "model": (self._declaration.to_dict() if self._declaration else None),
            "inference_count": self._inference_count,
            "last_response": (
                self._last_response.to_dict() if self._last_response else None
            ),
            "policy": self._policy.to_dict(),
            "hardware": self._hardware.to_dict(),
            "conversation_retained": False,
            "autonomous": False,
        }


def _configure_adapter(adapter: ModelAdapter, declaration: ModelDeclaration) -> ModelAdapter:
    """Hand the declared runtime details to an adapter that accepts them."""
    if declaration.runtime_binary:
        try:
            adapter._binary = declaration.runtime_binary  # noqa: SLF001
        except AttributeError:
            pass
    if declaration.runtime_version:
        try:
            adapter._runtime_version = declaration.runtime_version  # noqa: SLF001
        except AttributeError:
            pass
    try:
        adapter._configured_context = declaration.context_length  # noqa: SLF001
    except AttributeError:
        pass
    return adapter


def _with_measured_duration(
    response: InferenceResponse, elapsed_ms: float
) -> InferenceResponse:
    """Fill in a duration the adapter did not measure itself."""
    if response.inference_duration_ms.status is EpistemicStatus.UNAVAILABLE:
        from dataclasses import replace

        response = replace(
            response,
            inference_duration_ms=Measurement.observed(
                round(elapsed_ms, 3), "ms", "perf_counter around adapter call"
            ),
        )
    return response


__all__ = ["FoundationRuntime", "ModelDeclaration", "RUNTIME_SOURCE"]
