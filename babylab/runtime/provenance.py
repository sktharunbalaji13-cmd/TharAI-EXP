"""Provenance for runtime output, using the M003 authorship classification.

The distinction this module refuses to collapse
-----------------------------------------------
Foundation-model output and Baby-AI-authored change are different things, and
the ledger must be able to tell them apart forever. M003 already made that
distinction in :mod:`birth.authorship`: a model is ``INHERITED_PRETRAINED``,
structurally, because that is what a weight file produced by a third party
before the experiment began *is*. M006 does not introduce a new vocabulary; it
uses that one.

Why the model cannot claim authorship
-------------------------------------
Every record here is produced by the laboratory from external facts: which
adapter ran, which artifact digest was verified, which runtime emitted the text,
and when. The model's text is *content being recorded*, never a statement about
who wrote it. A model that emits the literal string ``"I wrote this"`` changes
nothing: the text is stored as text, and the authorship class beside it is
derived from the key that signed the record.

Therefore the classification here is a function of the recording identity, and
the model has no way to supply it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from babylab.runtime.contract import InferenceRequest, InferenceResponse
from birth.authorship import ArtifactKind, AuthorshipClass, Role

#: The class a foundation model always carries, structurally. Not a default that
#: a caller can override, and not something the model can assert.
MODEL_OUTPUT_CLASS = AuthorshipClass.INHERITED_PRETRAINED

#: Role used to sign runtime-produced records. The SYSTEM key is laboratory
#: infrastructure; the subject has no key and never will in this milestone.
RUNTIME_RECORD_ROLE = Role.SYSTEM


@dataclass(frozen=True)
class RuntimeOutputRecord:
    """One generation, recorded from the laboratory's side of the event."""

    request_id: str
    output_sha256: str
    output_chars: int
    prompt_sha256: str
    prompt_chars: int
    generation_parameters: dict[str, Any]
    model_identity: dict[str, Any]
    runtime_identity: dict[str, Any]
    authorship: AuthorshipClass
    authorship_basis: str
    finish_reason: str
    recorded_at: str
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "babylab/runtime-output/v1",
            "request_id": self.request_id,
            "output_sha256": self.output_sha256,
            "output_chars": self.output_chars,
            "prompt_sha256": self.prompt_sha256,
            "prompt_chars": self.prompt_chars,
            "generation_parameters": self.generation_parameters,
            "model_identity": self.model_identity,
            "runtime_identity": self.runtime_identity,
            "authorship": self.authorship.value,
            "authorship_basis": self.authorship_basis,
            "finish_reason": self.finish_reason,
            "recorded_at": self.recorded_at,
            "metrics": self.metrics,
            "error": self.error or None,
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_output_record(
    request: InferenceRequest,
    response: InferenceResponse,
    recorded_at: str,
) -> RuntimeOutputRecord:
    """Derive a provenance record from a request and its response.

    Only digests and lengths of the prompt and output are carried, not the text
    itself. The text is available to whoever asked for the generation; the
    permanent record keeps enough to prove two runs produced the same bytes
    without turning the ledger into a transcript store.
    """
    return RuntimeOutputRecord(
        request_id=request.request_id,
        output_sha256=_sha256_text(response.text),
        output_chars=len(response.text),
        prompt_sha256=_sha256_text(request.prompt),
        prompt_chars=len(request.prompt),
        generation_parameters={
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "top_k": request.top_k,
            "stop": list(request.stop),
            "seed": request.seed,
            "timeout_seconds": request.timeout_seconds,
            "intent": request.intent,
        },
        model_identity=response.model_identity,
        runtime_identity=response.runtime_identity,
        authorship=MODEL_OUTPUT_CLASS,
        authorship_basis=(
            "Foundation-model output. Classified structurally as inherited "
            "pretrained, not read from the artifact: the text was emitted by a "
            "pretrained runtime over inherited weights, and the recording "
            "identity is the laboratory SYSTEM key. The model cannot assert "
            "authorship of itself or of anything else."
        ),
        finish_reason=response.finish_reason.value,
        recorded_at=recorded_at,
        metrics={
            "prompt_tokens": response.prompt_tokens.to_dict(),
            "completion_tokens": response.completion_tokens.to_dict(),
            "inference_duration_ms": response.inference_duration_ms.to_dict(),
            "load_duration_ms": response.load_duration_ms.to_dict(),
            "tokens_per_second": response.tokens_per_second.to_dict(),
            "resources": {k: v.to_dict() for k, v in response.resources.items()},
        },
        error=response.error,
    )


def record_model_artifact(
    declaration_dict: dict[str, Any],
    recorder: Any,
    recorded_at: str,
    path: str,
) -> Any:
    """Record the foundation model itself in the provenance ledger.

    The artifact is classified ``INHERITED_PRETRAINED`` because that is a
    structural fact about a pretrained weight file. Recording it here means a
    later reader can tell which exact bytes produced a result, without trusting
    the model's own metadata.
    """
    content_sha256 = declaration_dict.get("sha256", "")
    size_bytes = declaration_dict.get("model_size_bytes") or 0
    return recorder.record_creation(
        path=path,
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        artifact_kind=ArtifactKind.MODEL_WEIGHTS,
        reason=(
            "Foundation model artifact configured for the M006 runtime. "
            "Authorship is INHERITED_PRETRAINED: a third party produced these "
            "weights before the experiment began."
        ),
        experiment_id="M006",
        actor=RUNTIME_RECORD_ROLE,
        metadata={
            "adapter_id": declaration_dict.get("adapter_id"),
            "model_family": declaration_dict.get("model_family"),
            "model_name": declaration_dict.get("model_name"),
            "quantization": declaration_dict.get("quantization"),
            "context_length": declaration_dict.get("context_length"),
            "license": declaration_dict.get("license") or "UNKNOWN",
            "license_url": declaration_dict.get("license_url") or "UNKNOWN",
            "source_url": declaration_dict.get("source_url") or "UNKNOWN",
            "runtime_version": declaration_dict.get("runtime_version") or "UNKNOWN",
            "declared_by": declaration_dict.get("declared_by") or "UNATTRIBUTED",
            "recorded_at": recorded_at,
        },
    )


def record_runtime_configuration(
    configuration: dict[str, Any],
    recorder: Any,
    recorded_at: str,
    path: str,
) -> Any:
    """Record the runtime configuration, hashed so a change is detectable."""
    canonical = _canonical_json(configuration)
    return recorder.record_creation(
        path=path,
        content_sha256=hashlib.sha256(canonical).hexdigest(),
        size_bytes=len(canonical),
        artifact_kind=ArtifactKind.MODEL_CONFIGURATION,
        reason="M006 runtime configuration. Identity derived by the laboratory.",
        experiment_id="M006",
        actor=RUNTIME_RECORD_ROLE,
        metadata={"recorded_at": recorded_at, "adapter_ids": configuration.get("adapters")},
    )


def _canonical_json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = [
    "MODEL_OUTPUT_CLASS",
    "RUNTIME_RECORD_ROLE",
    "RuntimeOutputRecord",
    "build_output_record",
    "record_model_artifact",
    "record_runtime_configuration",
]
