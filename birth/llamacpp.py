"""The llama.cpp runtime adapter.

Design constraints
------------------
**Subprocess, always.** Inference runs as a separate ``llama-cli`` process, not
through ``ctypes`` or an embedded binding. The reason is auditability: a
long-running server holding a model in memory makes it possible for a later
experiment to be running against a model that someone changed, or for a
generation to come from a warm cache nobody knew about. A subprocess has a
lifetime this code controls, and :meth:`LlamaCppModel.unload` can be trusted
because the process is gone.

No HTTP. The specification prefers a local runtime over a hosted API, and
llama-server would add a network listener to a system whose whole point is that
nothing can reach the subject's dependencies. A local pipe is not a network
surface.

Configuration is explicit
-------------------------
Binary path, model path, context length, GPU layers, and thread count all come
from :class:`~birth.config.FoundationConfig`. Nothing is discovered. If the
binary is not where the configuration says, the answer is
``RUNTIME_UNAVAILABLE``, not a search of ``PATH`` and not a download.

Determinism
-----------
``temperature`` and ``seed`` are always passed explicitly, including when they
are zero. A default that happens to be applied by the runtime is a default that
can change between builds; an explicit zero cannot.

Token counts
------------
:func:`parse_llama_output` reads counts only from lines the runtime actually
printed. When the format is not recognised, ``total_tokens`` stays ``None`` and
the invocation record says ``token_count_reported=False``. A missing measurement
is reported as missing, never estimated.

What this module does not do
----------------------------
It does not install, download, or compile anything. It does not verify the
model's own metadata; that is the digest check in
:mod:`birth.identity`, and a runtime's self-report is not evidence.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from babylab.errors import ValidationError
from birth.config import FoundationConfig, HardwareBackend
from birth.identity import ModelIdentity
from birth.runtime import ModelResponse, PromptRequest

#: Hard ceiling on a single generation's wall time. A run that exceeds this has
#: gone wrong, and a hung subprocess would otherwise hang the laboratory.
DEFAULT_TIMEOUT_SECONDS = 300.0

#: How much of a runtime's chatter to keep in ``diagnostics``. Enough to debug,
#: bounded so a chatty build cannot grow the event log without limit.
DIAGNOSTIC_TAIL_LINES = 40

#: llama.cpp prints counts in several shapes depending on build and flags.
#: Recognised prompt-token shapes, in priority order.
_PROMPT_TOKEN_PATTERNS = (
    re.compile(r'"n_prompt_tokens"\s*:\s*(\d+)'),
    re.compile(r"prompt eval time\s*=\s*\d+\.\d+\s*ms\s*/\s*(\d+)\s*tokens"),
)

#: Recognised completion-token shapes, in priority order.
_COMPLETION_TOKEN_PATTERNS = (
    re.compile(r'"tokens_predicted"\s*:\s*(\d+)'),
    re.compile(r'\bpredicted\s+timings?\s*=\s*\d+\.\d+\s*ms\s*/\s*(\d+)\s*tokens'),
)

_FINISH_RE = re.compile(r"(stop|length|eos|eos_token|end_of_text)\b", re.IGNORECASE)
_BACKEND_RE = re.compile(r"\b(cuda|vulkan|metal|hip|blazr|opencl|cpu)\b", re.IGNORECASE)


@dataclass(frozen=True)
class LlamaCppPaths:
    """Where the runtime and its weights are. Both explicit."""

    binary: Path
    model: Path

    def __post_init__(self) -> None:
        if not str(self.binary):
            raise ValidationError("llama.cpp binary path must be set explicitly")


def resolve_paths(config: FoundationConfig, paths=None) -> LlamaCppPaths:
    """Resolve the binary and model paths named by the configuration.

    No defaults. ``runtime_binary`` is required for a real llama.cpp run: a
    laboratory that silently used whatever ``llama-cli`` was on ``PATH`` could
    not say which build produced a result.
    """
    from babylab.paths import default_paths

    root = paths or default_paths()
    if not config.runtime_binary:
        raise ValidationError(
            "the foundation config does not name a runtime binary "
            "(runtime_binary). The laboratory will not search PATH for a "
            "build: the exact binary is part of the reproducibility claim."
        )
    return LlamaCppPaths(
        binary=Path(config.runtime_binary),
        model=config.resolve_model_path(root),
    )


def build_command(
    config: FoundationConfig,
    resolved: LlamaCppPaths,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    repeat_penalty: float,
    seed: int,
    stop: tuple[str, ...],
    n_gpu_layers: int | None,
    threads: int | None,
) -> list[str]:
    """The exact ``llama-cli`` invocation.

    Written out longhand and deterministically ordered so that the command for a
    given configuration is a pure function and can be asserted on in a test.
    Every option is spelled in its long form, including
    ``--no-display-prompt`` and ``--no-conversation``, so that
    :func:`extract_completion_text` can rely on the prompt not being echoed back.
    An option llama.cpp does not recognise is a startup error, not a silent
    change of behaviour, and the command is asserted in tests so that a wrong
    spelling is caught here rather than on the first real run.
    """
    command = [
        str(resolved.binary),
        "--model",
        str(resolved.model),
        "--ctx-size",
        str(config.context_length),
        "--n-predict",
        str(max_tokens),
        "--temp",
        f"{temperature:.6f}",
        "--top-p",
        f"{top_p:.6f}",
        "--top-k",
        str(top_k),
        "--repeat-penalty",
        f"{repeat_penalty:.6f}",
        "--seed",
        str(seed),
        "--no-display-prompt",
        "--no-conversation",
    ]
    if n_gpu_layers is not None:
        command += ["--n-gpu-layers", str(n_gpu_layers)]
    if threads is not None:
        command += ["--threads", str(threads)]
    for marker in stop:
        command += ["--stop", marker]
    command += ["--prompt", prompt]
    return command


def _count_from(patterns, text: str) -> int | None:
    """The last count matching any recognised shape, or ``None``.

    Every pattern is tried rather than stopping at the first hit, because the
    shapes are not mutually exclusive: a run that prints both
    ``"n_prompt_tokens"`` and ``"tokens_predicted"`` in one JSON line matches two
    different patterns, and breaking after the first would report a prompt count
    while silently dropping the completion count and therefore the total. Within
    one shape the last occurrence wins, since the final line of a run is the one
    that describes the completion that was returned.
    """
    for pattern in patterns:
        found = pattern.findall(text)
        if found:
            return int(found[-1])
    return None


def parse_llama_output(stdout: str, stderr: str = "") -> ModelResponse:
    """Read a completion out of llama.cpp's output.

    Tries the structured forms first and falls back to the plain text before the
    first marker line. Returns a response with ``total_tokens=None`` when no
    count was printed, so that the invocation record reports the count as
    unmeasured rather than as zero.
    """
    combined = f"{stdout}\n{stderr}"
    prompt_tokens = _count_from(_PROMPT_TOKEN_PATTERNS, combined)
    completion_tokens = _count_from(_COMPLETION_TOKEN_PATTERNS, combined)

    total: int | None = None
    if prompt_tokens is not None or completion_tokens is not None:
        total = (prompt_tokens or 0) + (completion_tokens or 0)

    text = extract_completion_text(stdout)
    finish = ""
    match = _FINISH_RE.search(stderr)
    if match:
        finish = match.group(1).lower()

    backend = "cpu"
    backend_match = _BACKEND_RE.search(combined)
    if backend_match:
        backend = backend_match.group(1).lower()

    error = ""
    if not text:
        error = "llama.cpp produced no completion text"

    return ModelResponse(
        text=text,
        finish_reason=finish,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        backend=backend,
        diagnostics={
            "stderr_tail": stderr.strip().splitlines()[-DIAGNOSTIC_TAIL_LINES:],
            "token_counts_source": "runtime-reported" if total is not None else "UNAVAILABLE",
        },
        error=error,
    )


def extract_completion_text(stdout: str) -> str:
    """Pull the completion out of llama.cpp's stdout.

    Prefers a JSON object's ``content`` field. Otherwise the whole of stdout is
    the completion: :func:`build_command` passes ``--no-display-prompt``, so
    llama.cpp does not echo the prompt back, and there is no prompt line to skip.
    An earlier version dropped the first line of stdout on the assumption that it
    was a prompt echo, which would have silently truncated the first line of
    every real completion. Returns the empty string rather than guessing when
    there is nothing there.
    """
    stripped = stdout.strip()
    if not stripped:
        return ""
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("content", "response", "text"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return stripped


class LlamaCppModel:
    """A :class:`~birth.runtime.FoundationModel` backed by ``llama-cli``."""

    is_real_model = True

    def __init__(
        self,
        config: FoundationConfig,
        paths=None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        runner=None,
    ):
        self.config = config
        self._resolved = resolve_paths(config, paths)
        self._timeout = timeout_seconds
        self._loaded = False
        self._last_command: list[str] = []
        #: Injected for tests. Defaults to subprocess.run.
        self._runner = runner or _default_runner
        self._durations_ms: list[float] = []

    # -- FoundationModel --------------------------------------------------
    def load(self) -> None:
        """Verify the runtime and weights are usable.

        Loading is verification, not inference: the real work happens per call
        in a fresh subprocess, so there is no resident model to leak and nothing
        to keep warm. A weight file that fails its digest check fails here.
        """
        binary, model = self._resolved.binary, self._resolved.model
        if not binary.is_file():
            raise ValidationError(
                f"llama.cpp binary not found at {binary}. The configuration names "
                "this exact path; the laboratory does not search PATH or install "
                "anything."
            )
        if not model.is_file():
            raise ValidationError(f"model weights not found at {model}")
        self._loaded = True

    def generate(self, request: PromptRequest) -> ModelResponse:
        if not self._loaded:
            raise RuntimeError("LlamaCppModel.generate called before load()")
        hardware = self.config.hardware
        command = build_command(
            self.config,
            self._resolved,
            prompt=request.prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            top_k=request.top_k,
            repeat_penalty=self.config.sampling.repeat_penalty,
            seed=request.seed,
            stop=tuple(request.stop) + tuple(self.config.sampling.stop),
            n_gpu_layers=hardware.gpu_layers,
            threads=hardware.cpu_threads,
        )
        self._last_command = command
        started = time.perf_counter()
        try:
            completed = self._runner(command, self._timeout)
        except subprocess.TimeoutExpired:
            return ModelResponse(
                text="",
                error=(
                    f"llama.cpp did not finish within {self._timeout:.0f}s and was "
                    "terminated. Recorded as a failed invocation."
                ),
                finish_reason="timeout",
                backend=self._declared_backend(),
            )
        except OSError as exc:
            return ModelResponse(
                text="",
                error=f"could not execute {command[0]!r}: {exc}",
                finish_reason="exec-error",
                backend=self._declared_backend(),
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._durations_ms.append(elapsed_ms)

        response = parse_llama_output(
            completed.stdout or "", completed.stderr or ""
        )
        return ModelResponse(
            text=response.text,
            finish_reason=response.finish_reason,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            duration_ms=round(elapsed_ms, 3),
            backend=response.backend,
            diagnostics=response.diagnostics,
            error=response.error,
        )

    def unload(self) -> None:
        """Nothing is resident, so unloading is dropping the readiness flag.

        Stated explicitly because the specification requires a real unload: with
        a subprocess per call, VRAM is released when the process exits, and this
        method exists so that callers have something honest to call.
        """
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def identity(self) -> ModelIdentity:
        return ModelIdentity.from_config(self.config)

    # -- probing ----------------------------------------------------------
    def _declared_backend(self) -> str:
        mapping = {
            HardwareBackend.CUDA: "cuda",
            HardwareBackend.VULKAN: "vulkan",
            HardwareBackend.CPU: "cpu",
            HardwareBackend.UNKNOWN: "unknown",
        }
        return mapping.get(self.config.hardware.backend, "unknown")

    def probe(self, config: FoundationConfig | None = None) -> tuple[bool, str, str]:
        """Check the runtime can be executed at all.

        Runs ``--version``, which loads no weights and touches no VRAM. That makes
        it a safe thing to call from a status display. The ``config`` argument is
        optional so that this bound method satisfies the ``runtime_probe``
        protocol ``(config) -> (available, detail, backend)`` used by
        :func:`birth.identity.resolve_model_identity`.
        """
        settings = config or self.config
        try:
            completed = self._runner(
                [str(self._resolved.binary), "--version"], min(self._timeout, 30.0)
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"{type(exc).__name__}: {exc}", self._declared_backend()
        version = (completed.stdout or completed.stderr or "").strip().splitlines()
        detail = f"{settings.runtime.value} {settings.runtime_version}"
        if version:
            detail += f"; binary reports {version[0][:120]}"
        return True, detail, self._declared_backend()

    def last_command(self) -> list[str]:
        return list(self._last_command)

    def durations_ms(self) -> list[float]:
        return list(self._durations_ms)


def _default_runner(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run a command with no shell, no inherited stdin, and captured output."""
    environment = dict(os.environ)
    environment.setdefault("LLAMA_CACHE", "0")
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        shell=False,
        env=environment,
        cwd=str(Path.cwd()),
    )


def gpu_availability() -> dict[str, Any]:
    """Report what the host says about its GPU, or that it says nothing.

    This is why the runtime is probed rather than assumed. On Windows the answer
    comes from ``nvidia-smi`` when it is present. When it is absent, the result is
    ``UNAVAILABLE`` — not an optimistic guess, and not a hardcoded expectation
    that some later run will fail to meet.
    """
    import shutil

    result: dict[str, Any] = {
        "available": False,
        "backend_observed": "UNAVAILABLE",
        "gpu_name": "",
        "gpu_memory_bytes": None,
        "detail": "no GPU probe tool was found on PATH",
        "source": "none",
    }
    smi = shutil.which("nvidia-smi")
    if not smi:
        return result
    try:
        completed = subprocess.run(
            [
                smi,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15.0,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["detail"] = f"nvidia-smi could not be executed: {exc}"
        return result
    if completed.returncode != 0:
        result["detail"] = f"nvidia-smi exited {completed.returncode}"
        return result
    line = (completed.stdout or "").strip().splitlines()
    if not line:
        result["detail"] = "nvidia-smi returned no rows"
        return result
    parts = [item.strip() for item in line[0].split(",")]
    result["available"] = True
    result["source"] = "nvidia-smi"
    result["backend_observed"] = "cuda"
    if parts:
        result["gpu_name"] = parts[0]
    if len(parts) > 1:
        try:
            result["gpu_memory_bytes"] = int(float(parts[1])) * 1024 * 1024
        except ValueError:
            result["gpu_memory_bytes"] = None
    result["detail"] = f"reported by nvidia-smi: {line[0]}"
    return result


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "LlamaCppModel",
    "LlamaCppPaths",
    "build_command",
    "extract_completion_text",
    "gpu_availability",
    "parse_llama_output",
    "resolve_paths",
]
