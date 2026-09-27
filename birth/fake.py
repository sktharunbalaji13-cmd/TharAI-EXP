"""A deterministic stand-in for a real model.

What this is
------------
Enough of a :class:`~birth.runtime.FoundationModel` to exercise the plumbing:
load, generate, unload, plus a health query. Its output is a fixed function of
the prompt, so two runs with the same prompt are identical.

What this is emphatically not
-----------------------------
A model. It does not learn, it does not reason, and it has no more insight than
the string it was handed. It exists so that tests can prove the birth record,
the invocation record, the action boundary, and the observatory plumbing work
*before* anyone spends money on weights.

The naming is deliberate and load-bearing
-----------------------------------------
:class:`FakeModel.status` reports ``READY`` in the same way a real runtime
does, but :attr:`FakeModel.is_real_model` is ``False`` and the identity it
reports carries the model family ``"fake"``. Every artifact it touches records
which one it was. A fake that could be mistaken for a real model would be worse
than no fake at all, because the error would only surface in the analysis.
"""

from __future__ import annotations

import hashlib
from typing import Any

from birth.config import FoundationConfig, RuntimeKind
from birth.identity import ModelIdentity
from birth.runtime import (
    ModelResponse,
    ObservationStatus,
    PromptRequest,
    OutputKind,
    build_invocation_record,
)


def fake_config(
    model_name: str = "fake-substrate",
    context_length: int = 2048,
) -> FoundationConfig:
    """A configuration describing the fake, for tests and dry runs.

    The digest is the digest of a fixed, obviously-not-a-model string, so a
    record that accidentally escaped into the research log cannot be mistaken for
    a real installation.
    """
    marker = b"babylab-fake-foundation-model-not-real-weights"
    return FoundationConfig(
        model_family="fake",
        model_name=model_name,
        model_revision="fake-v1",
        quantization="none",
        model_file="fake/does-not-exist.gguf",
        model_sha256=hashlib.sha256(marker).hexdigest(),
        model_size_bytes=len(marker),
        runtime=RuntimeKind.FAKE,
        runtime_version="fake-1",
        context_length=context_length,
        source_url="",
        license="NONE-fake",
        notes="Deterministic stand-in. Not a model. Never use for findings.",
        declared_by="babylab.tests",
    )


class FakeModel:
    """A :class:`FoundationModel` whose output depends only on its input."""

    is_real_model = False

    def __init__(self, config: FoundationConfig | None = None, reply: str | None = None):
        self._config = config or fake_config()
        self._loaded = False
        self._reply = reply
        #: Set by tests to force a failure path.
        self.fail_with = ""
        self._calls: list[PromptRequest] = []

    # -- FoundationModel --------------------------------------------------
    def load(self) -> None:
        self._loaded = True

    def generate(self, request: PromptRequest) -> ModelResponse:
        if not self._loaded:
            raise RuntimeError("FakeModel.generate called before load()")
        self._calls.append(request)
        if self.fail_with:
            return ModelResponse(text="", error=self.fail_with, finish_reason="error")
        if self._reply is not None:
            text = self._reply
        else:
            text = f"fake-response:{request.prompt}"
        # Deterministic, and clearly not a real token count: derived from the
        # prompt, not measured.
        tokens = len(text.split())
        return ModelResponse(
            text=text,
            finish_reason="stop",
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=tokens,
            total_tokens=len(request.prompt.split()) + tokens,
            duration_ms=0.0,
            backend="fake",
            diagnostics={"engine": "deterministic", "is_real_model": False},
        )

    def unload(self) -> None:
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def identity(self) -> ModelIdentity:
        return ModelIdentity.from_config(self._config)

    # -- introspection for tests -----------------------------------------
    def probe(self, config: FoundationConfig) -> tuple[bool, str, str]:
        return True, "fake runtime is always available", "fake"

    def call_count(self) -> int:
        return len(self._calls)

    def status(self) -> str:
        return "READY"

    def satisfies_protocol(self) -> bool:
        """Whether this object really implements the FoundationModel interface."""
        from birth.runtime import FoundationModel

        return isinstance(self, FoundationModel)


def interpret_json_output(text: str) -> tuple[ObservationStatus, OutputKind, dict[str, Any], str]:
    """Try to read a model output as JSON.

    Returns ``(observation, output_kind, interpretation, error)``.

    The point of this function is that a failure is a *recorded* result. A model
    that answers with prose where JSON was wanted has produced an observation:
    it was asked, it answered, and the answer was not usable. Retrying until
    something parses would replace that fact with a nicer-sounding one.
    """
    import json

    stripped = text.strip()
    if not stripped:
        return ObservationStatus.UNPARSED, OutputKind.RAW, {}, "empty output"
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return (
            ObservationStatus.UNPARSED,
            OutputKind.RAW,
            {},
            f"output is not JSON: {exc.msg} at position {exc.pos}",
        )
    if not isinstance(value, dict):
        return (
            ObservationStatus.UNPARSED,
            OutputKind.VALIDATION_ERROR,
            {},
            f"parsed JSON is a {type(value).__name__}, expected an object",
        )
    return ObservationStatus.PARSED, OutputKind.INTERPRETATION, value, ""


def record_fake_call(
    invocation_id: str,
    model: FakeModel,
    request: PromptRequest,
    now: Any = None,
) -> tuple[Any, ObservationStatus, OutputKind]:
    """Run one fake call and return the invocation record for it."""
    response = model.generate(request)
    if response.is_error:
        observation, output_kind, interpretation, error = (
            ObservationStatus.ERROR,
            OutputKind.NONE,
            {},
            response.error,
        )
    else:
        observation, output_kind, interpretation, error = interpret_json_output(response.text)
    record = build_invocation_record(
        invocation_id=invocation_id,
        identity=model.identity(),
        request=request,
        response=response,
        observation=observation,
        output_kind=output_kind,
        interpretation=interpretation,
        error=error,
        now=now,
    )
    return record, observation, output_kind


__all__ = [
    "FakeModel",
    "fake_config",
    "interpret_json_output",
    "record_fake_call",
]
