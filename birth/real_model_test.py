"""Explicit real-model integration check.

This is **not** part of the unit test suite. It loads real weights, allocates real
VRAM, and takes real time, and a test suite that did that would be unusable. It
is a separate command that a person runs deliberately:

::

    python -m birth.real_model_test

What it checks, in order
------------------------
1. A configuration exists. Otherwise it stops and reports ``NOT_CONFIGURED``.
2. The weight file is present and its SHA-256 matches. Otherwise
   ``MODEL_NOT_INSTALLED`` or ``MODEL_INTEGRITY_MISMATCH``.
3. The runtime binary is present and answers a version query. Otherwise
   ``RUNTIME_UNAVAILABLE``.
4. A deterministic smoke generation runs, with ``temperature=0`` and a fixed
   seed, and the result is recorded whether or not it is any good.
5. The model is unloaded and the process is left clean.

What it will not do
-------------------
It will not pick a model, download weights, install a runtime, or judge the
output. A poor completion is a successful check, because the point is that the
pipeline works, not that the model is intelligent.

Metrics
-------
Only what was actually observed. When a number was not reported, the field is
``UNAVAILABLE`` — see :data:`UNAVAILABLE` and the module's note in
:mod:`birth.llamacpp`. Wall-clock duration is measured by this process and is
always available; token counts, VRAM use, and GPU utilisation depend on the
runtime and are frequently absent.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass, field
from typing import Any

from babylab.clock import Clock
from babylab.errors import BabyLabError
from babylab.hashing import canonical_json
from babylab.paths import ProjectPaths, default_paths
from birth.config import RuntimeKind, load_config
from birth.identity import ModelStatus, resolve_model_identity
from birth.llamacpp import LlamaCppModel, gpu_availability
from birth.runtime import ObservationStatus, OutputKind, PromptRequest, build_invocation_record

#: The literal reported for anything this run could not measure. A string, not a
#: zero, so that it can never be averaged in.
UNAVAILABLE = "UNAVAILABLE"

#: A fixed, boring prompt. It exists to produce tokens, not to elicit insight.
SMOKE_PROMPT = "Reply with the single word: laboratory."


@dataclass
class RealModelReport:
    """The outcome of a real-model check. Every field is observed or UNAVAILABLE."""

    status: str
    detail: str
    model_installed: bool = False
    backend: str = UNAVAILABLE
    backend_declared: str = UNAVAILABLE
    gpu_name: str = UNAVAILABLE
    gpu_memory_bytes: Any = UNAVAILABLE
    gpu_memory_total_bytes: Any = UNAVAILABLE
    model_sha256: str = ""
    model_name: str = ""
    configuration_hash: str = ""
    runtime: str = ""
    runtime_version: str = ""
    platform: str = ""
    python: str = ""
    prompt_tokens: Any = UNAVAILABLE
    completion_tokens: Any = UNAVAILABLE
    total_tokens: Any = UNAVAILABLE
    #: Time to confirm the binary and the weight file are present and correct.
    #: Named for what it measures: this adapter holds no resident model, so there
    #: is no separate weight-load phase to time. Calling it a load time would
    #: report a number for something that never happened.
    verification_duration_ms: Any = UNAVAILABLE
    generation_duration_ms: Any = UNAVAILABLE
    output_text: str = ""
    finish_reason: str = ""
    unloaded: bool = False
    command: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    invocation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "model_installed": self.model_installed,
            "backend": self.backend,
            "backend_declared": self.backend_declared,
            "gpu_name": self.gpu_name,
            "gpu_memory_bytes": self.gpu_memory_bytes,
            "gpu_memory_total_bytes": self.gpu_memory_total_bytes,
            "model_name": self.model_name,
            "model_sha256": self.model_sha256,
            "configuration_hash": self.configuration_hash,
            "runtime": self.runtime,
            "runtime_version": self.runtime_version,
            "platform": self.platform,
            "python": self.python,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "verification_duration_ms": self.verification_duration_ms,
            "generation_duration_ms": self.generation_duration_ms,
            "output_text": self.output_text,
            "finish_reason": self.finish_reason,
            "unloaded": self.unloaded,
            "command": list(self.command),
            "notes": list(self.notes),
            "invocation_record": dict(self.invocation_record),
        }

    def render(self) -> str:
        lines = [
            f"REAL MODEL TEST   {self.status}",
            f"  detail         {self.detail}",
            f"  model          {self.model_name or UNAVAILABLE}",
            f"  model sha256   {self.model_sha256 or UNAVAILABLE}",
            f"  config hash    {self.configuration_hash or UNAVAILABLE}",
            f"  runtime        {self.runtime or UNAVAILABLE} {self.runtime_version or ''}".rstrip(),
            f"  backend        observed={self.backend} declared={self.backend_declared}",
            f"  gpu            {self.gpu_name} ({_bytes(self.gpu_memory_bytes)})",
            f"  prompt tokens  {_num(self.prompt_tokens)}",
            f"  output tokens  {_num(self.completion_tokens)}",
            f"  total tokens   {_num(self.total_tokens)}",
            f"  verify ms      {_num(self.verification_duration_ms)}  (binary + weights present, no resident load)",
            f"  generate ms    {_num(self.generation_duration_ms)}",
            f"  output         {self.output_text!r}",
            f"  finish reason  {self.finish_reason or UNAVAILABLE}",
            f"  unloaded       {self.unloaded}",
            f"  platform       {self.platform} / python {self.python}",
        ]
        for note in self.notes:
            lines.append(f"  note           {note}")
        return "\n".join(lines)


def _num(value: Any) -> str:
    return UNAVAILABLE if value is None or value == UNAVAILABLE else str(value)


def _bytes(value: Any) -> str:
    if value is None or value == UNAVAILABLE:
        return UNAVAILABLE
    return f"{int(value) / (1024 ** 2):.0f} MiB"


def run_check(
    paths: ProjectPaths | None = None,
    prompt: str = SMOKE_PROMPT,
    now: Any = None,
) -> RealModelReport:
    """Perform the check. Never raises for an absent model; reports it."""
    root = paths or default_paths()
    notes: list[str] = []
    gpu = gpu_availability()

    report = RealModelReport(
        status=ModelStatus.NOT_CONFIGURED.value,
        detail="",
        backend=UNAVAILABLE,
        backend_declared=UNAVAILABLE,
        gpu_name=gpu.get("gpu_name") or UNAVAILABLE,
        gpu_memory_bytes=gpu.get("gpu_memory_bytes", UNAVAILABLE) or UNAVAILABLE,
        gpu_memory_total_bytes=gpu.get("gpu_memory_bytes", UNAVAILABLE) or UNAVAILABLE,
        platform=f"{platform.system()} {platform.release()}",
        python=platform.python_version(),
    )

    try:
        config = load_config(root)
    except BabyLabError as exc:
        report.detail = str(exc)
        report.notes.append(
            "No model was configured, so nothing was loaded and no metrics were "
            "measured. This is the expected result on a fresh installation."
        )
        return report

    report.model_name = config.model_name
    report.model_sha256 = config.model_sha256
    report.configuration_hash = config.configuration_hash()
    report.runtime = config.runtime.value
    report.runtime_version = config.runtime_version
    report.backend_declared = config.hardware.backend.value

    if config.runtime is RuntimeKind.FAKE:
        report.status = ModelStatus.ERROR.value
        report.detail = (
            "the configuration names the fake runtime. This check exists to test "
            "a real model, so it will not run against a fake."
        )
        return report

    probe_model = LlamaCppModel(config, root)
    installation = resolve_model_identity(
        config, root, runtime_probe=probe_model.probe
    )
    report.status = installation.status.value
    report.detail = installation.detail
    report.model_installed = installation.status.is_usable
    if not installation.status.is_usable:
        report.notes.extend(installation.notes)
        return report

    identity = installation.identity
    assert identity is not None
    request = PromptRequest(
        prompt=prompt,
        max_tokens=32,
        temperature=config.generation.temperature,
        top_p=config.generation.top_p,
        top_k=config.generation.top_k,
        stop=tuple(config.sampling.stop),
        seed=config.generation.seed,
        intent="real-model-smoke-test",
    )

    load_started = time.perf_counter()
    try:
        probe_model.load()
    except BabyLabError as exc:
        report.status = ModelStatus.ERROR.value
        report.detail = f"load failed: {exc}"
        return report
    report.verification_duration_ms = round(
        (time.perf_counter() - load_started) * 1000.0, 3
    )
    report.notes.append(
        "verification_duration_ms is the time to confirm the binary and weight "
        "file are present and correct. This adapter starts a fresh subprocess "
        "per generation, so there is no resident weight load to measure."
    )

    response = probe_model.generate(request)
    report.backend = response.backend or UNAVAILABLE
    report.output_text = response.text
    report.finish_reason = response.finish_reason
    report.generation_duration_ms = response.duration_ms
    report.command = probe_model.last_command()
    report.prompt_tokens = (
        response.prompt_tokens if response.prompt_tokens is not None else UNAVAILABLE
    )
    report.completion_tokens = (
        response.completion_tokens if response.completion_tokens is not None else UNAVAILABLE
    )
    report.total_tokens = (
        response.total_tokens if response.total_tokens is not None else UNAVAILABLE
    )
    if response.total_tokens is None:
        report.notes.append(
            "the runtime did not report a token count, so token metrics are "
            f"{UNAVAILABLE}. They are not estimated."
        )

    observation = ObservationStatus.PARSED if response.text else ObservationStatus.ERROR
    invocation = build_invocation_record(
        invocation_id="REAL-TEST-0001",
        identity=identity,
        request=request,
        response=response,
        observation=observation,
        output_kind=OutputKind.RAW if response.text else OutputKind.NONE,
        error=response.error,
        now=(now if now is not None else Clock().now()),
    )
    report.invocation_record = invocation.to_dict()

    probe_model.unload()
    report.unloaded = not probe_model.is_loaded
    if response.error:
        report.status = ModelStatus.ERROR.value
        report.detail = response.error
    else:
        report.status = ModelStatus.READY.value
        report.detail = (
            f"smoke generation completed via {report.runtime} on "
            f"{report.backend}. The output is recorded as observed; this check "
            "makes no claim about its quality."
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = __import__("argparse").ArgumentParser(
        prog="python -m birth.real_model_test",
        description=(
            "Explicit real-model integration check. Loads real weights on "
            "purpose. Not part of the unit test suite."
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--prompt", default=SMOKE_PROMPT, help="override the smoke prompt")
    args = parser.parse_args(argv)

    report = run_check(prompt=args.prompt)
    if args.json:
        print(canonical_json(report.to_dict()))
    else:
        print(report.render())
    # Exit status follows the report's own status, not whether weights were
    # present. A run where the model was installed and the generation then failed
    # has not verified anything, and returning 0 for it would let a broken
    # pipeline be recorded as a working one.
    return 0 if report.status == ModelStatus.READY.value else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
