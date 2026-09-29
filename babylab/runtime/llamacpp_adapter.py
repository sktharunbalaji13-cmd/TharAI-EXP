"""The llama.cpp binding for the Milestone 006 adapter contract.

This is a *binding*, not a reimplementation. The actual invocation, output
parsing and determinism rules already exist in :mod:`birth.llamacpp` from
Milestone 003, and that module stays the single place those decisions live.
M006 adds only what the contract requires and M003 did not have: externally
derived identity, digest verification before use, explicit failure kinds, and
honest token accounting.

Security posture
----------------
* Subprocess with ``shell=False`` and no inherited stdin. The model never
  receives a shell, and the command is a fixed argument vector built from a
  validated configuration -- not a string.
* No network listener. ``llama-server`` is deliberately not used.
* No download, no ``PATH`` search, no model substitution. The binary and weights
  are exactly the paths named by the configuration; anything else is a
  :class:`RuntimeFailure`.
* No prompt, no generated text, and no file content is written to the event log.
  The runtime records identity and metrics; the text stays in the caller's
  hands unless provenance is explicitly recorded.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Iterator

from babylab.errors import ValidationError
from babylab.runtime.contract import (
    ADAPTER_CONTRACT_VERSION,
    EpistemicStatus,
    FinishReason,
    InferenceRequest,
    InferenceResponse,
    Measurement,
    RuntimeErrorKind,
    RuntimeFailure,
    RuntimeIdentity,
)

#: Wall-clock ceiling for a single generation.
DEFAULT_TIMEOUT_SECONDS = 300.0

#: Probe ceiling for ``--version``. Loads no weights, touches no VRAM.
PROBE_TIMEOUT_SECONDS = 30.0

#: Extensions this adapter will hand to llama.cpp. Anything else is refused
#: before the runtime is touched, so an unsupported artifact produces a clear
#: UNSUPPORTED_FORMAT rather than a subprocess failure.
SUPPORTED_SUFFIXES = (".gguf",)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Streamed SHA-256. Used for artifact identity; never a runtime self-report."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class LlamaCppAdapter:
    """Adapter for llama.cpp, driven through the M003 invocation builder."""

    adapter_id = "llamacpp"
    adapter_version = "1.0.0"
    contract_version = ADAPTER_CONTRACT_VERSION

    def __init__(
        self,
        binary: str | None = None,
        runtime_version: str = "",
        runner=None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._binary = Path(binary) if binary else None
        self._runtime_version = runtime_version
        self._runner = runner
        self._timeout = timeout_seconds
        self._loaded_path: Path | None = None
        self._loaded_digest: str | None = None
        self._cancelled = False
        self._load_duration_ms: Measurement = Measurement.unavailable("not loaded")

    # -- helpers ---------------------------------------------------------
    def _run(self, command: list[str], timeout: float):
        if self._runner is not None:
            return self._runner(command, timeout)
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
        )

    def identity(self) -> RuntimeIdentity:
        return RuntimeIdentity(
            adapter=self.adapter_id,
            adapter_version=self.adapter_version,
            runtime_implementation="llama.cpp",
            runtime_version=self._runtime_version or "UNKNOWN",
        )

    # -- ModelAdapter ----------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "contract_version": self.contract_version,
            "runtime_implementation": "llama.cpp",
            "runtime_version": self._runtime_version or "UNKNOWN",
            "binary": str(self._binary) if self._binary else None,
            "network_access": "none (subprocess, no listener)",
            "acquisition": "none (never downloads, never searches PATH)",
        }

    def probe(self) -> tuple[bool, str]:
        """Can the named binary be executed? Loads no weights."""
        if self._binary is None:
            return False, "no runtime binary configured (runtime_binary is empty)"
        if not self._binary.is_file():
            return False, (
                f"llama.cpp binary not found at {self._binary}. The laboratory "
                "does not search PATH and does not install anything."
            )
        try:
            completed = self._run([str(self._binary), "--version"], PROBE_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if completed.returncode != 0:
            return False, f"binary exited {completed.returncode}"
        first = (completed.stdout or completed.stderr or "").strip().splitlines()
        return True, first[0][:200] if first else "binary reported no version"

    def load(self, model_path: str, expected_sha256: str) -> dict[str, Any]:
        """Verify artifact identity before any weight is read.

        Order matters: existence, then format, then digest. Nothing is loaded
        until the digest matches, so a substituted artifact cannot be executed
        on the strength of its own metadata.
        """
        available, detail = self.probe()
        if not available:
            raise RuntimeFailure(
                RuntimeErrorKind.RUNTIME_MISSING, detail, adapter_id=self.adapter_id
            )

        path = Path(model_path)
        if not path.is_file():
            raise RuntimeFailure(
                RuntimeErrorKind.ARTIFACT_MISSING,
                f"model artifact not found at {path}. The laboratory does not "
                "download, search, or substitute an artifact.",
                path=str(path),
            )
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise RuntimeFailure(
                RuntimeErrorKind.UNSUPPORTED_FORMAT,
                f"unsupported artifact format {path.suffix!r}; this adapter "
                f"accepts {', '.join(SUPPORTED_SUFFIXES)}",
                path=str(path),
            )

        if not expected_sha256 or len(expected_sha256) != 64:
            raise RuntimeFailure(
                RuntimeErrorKind.NOT_CONFIGURED,
                "no usable expected SHA-256 was supplied; the laboratory will "
                "not load an artifact of unverified identity",
                path=str(path),
            )

        started = time.perf_counter()
        actual = sha256_file(path)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if actual.lower() != expected_sha256.lower():
            raise RuntimeFailure(
                RuntimeErrorKind.DIGEST_MISMATCH,
                f"artifact digest {actual} does not match the configured "
                f"{expected_sha256}. Refusing to load.",
                path=str(path),
                observed_sha256=actual,
                expected_sha256=expected_sha256,
            )

        self._loaded_path = path
        self._loaded_digest = actual
        self._load_duration_ms = Measurement.observed(
            round(elapsed_ms, 3), "ms", "verified at load; weights are read per call"
        )
        return {
            "path": str(path),
            "sha256": actual,
            "size_bytes": path.stat().st_size,
            "format": path.suffix.lower().lstrip("."),
            "digest_verified": True,
        }

    def unload(self) -> None:
        """Nothing is resident between calls, so this drops the loaded handle."""
        self._loaded_path = None
        self._loaded_digest = None
        self._load_duration_ms = Measurement.unavailable("unloaded")

    @property
    def is_loaded(self) -> bool:
        return self._loaded_path is not None

    def supports_streaming(self) -> bool:
        """False. The M003 invocation collects a single completion.

        Claiming streaming here would be a lie the caller could act on; the
        contract says to report the absence instead.
        """
        return False

    def stream(self, request: InferenceRequest) -> Iterator[str]:
        raise RuntimeFailure(
            RuntimeErrorKind.CAPABILITY_DENIED,
            "this adapter does not support streaming; it performs one "
            "non-interactive completion per call",
            adapter_id=self.adapter_id,
        )

    def cancel(self) -> None:
        """Flag cancellation.

        The M003 invocation is a bounded subprocess, so the honest guarantee is
        that the *next* operation observes this flag. Killing an in-flight
        child would need the process handle, which this binding does not retain.
        """
        self._cancelled = True

    def generate(self, request: InferenceRequest) -> InferenceResponse:
        if not self.is_loaded:
            raise RuntimeFailure(
                RuntimeErrorKind.NOT_CONFIGURED,
                "generate() called before a verified load()",
                adapter_id=self.adapter_id,
            )
        if self._cancelled:
            self._cancelled = False
            return InferenceResponse(
                request_id=request.request_id,
                finish_reason=FinishReason.CANCELLED,
                runtime_identity=self.identity().to_dict(),
                model_identity={"path": str(self._loaded_path),
                                "sha256": self._loaded_digest},
                error="cancelled before generation started",
            )

        from birth.llamacpp import build_command, parse_llama_output
        from birth.runtime import PromptRequest

        inner = PromptRequest(
            prompt=request.prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            top_k=request.top_k,
            stop=request.stop,
            seed=request.seed,
            intent=request.intent,
        )
        command = build_command(
            _MinimalConfig(
                context_length=self._context_length(request),
                sampling=_MinimalSampling(),
            ),
            _ResolvedPaths(binary=self._binary, model=self._loaded_path),
            prompt=inner.prompt,
            max_tokens=inner.max_tokens,
            temperature=inner.temperature,
            top_p=inner.top_p,
            top_k=inner.top_k,
            repeat_penalty=1.0,
            seed=inner.seed,
            stop=tuple(inner.stop),
            n_gpu_layers=None,
            threads=None,
        )

        timeout = request.timeout_seconds or self._timeout
        started = time.perf_counter()
        try:
            completed = self._run(command, timeout)
        except subprocess.TimeoutExpired:
            return InferenceResponse(
                request_id=request.request_id,
                finish_reason=FinishReason.TIMEOUT,
                runtime_identity=self.identity().to_dict(),
                model_identity={"path": str(self._loaded_path),
                                "sha256": self._loaded_digest},
                error=f"llama.cpp did not finish within {timeout:.0f}s and was terminated",
            )
        except OSError as exc:
            return InferenceResponse(
                request_id=request.request_id,
                finish_reason=FinishReason.ERROR,
                runtime_identity=self.identity().to_dict(),
                model_identity={"path": str(self._loaded_path),
                                "sha256": self._loaded_digest},
                error=f"could not execute the runtime: {exc}",
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        parsed = parse_llama_output(completed.stdout or "", completed.stderr or "")

        from babylab.runtime.governor import compute_throughput

        prompt_tokens = (
            Measurement.observed(parsed.prompt_tokens, "count", "runtime-reported")
            if parsed.prompt_tokens is not None
            else Measurement.unavailable("runtime printed no prompt token count")
        )
        completion_tokens = (
            Measurement.observed(parsed.completion_tokens, "count", "runtime-reported")
            if parsed.completion_tokens is not None
            else Measurement.unavailable("runtime printed no completion token count")
        )
        duration = Measurement.observed(round(elapsed_ms, 3), "ms", "perf_counter")

        return InferenceResponse(
            request_id=request.request_id,
            text=parsed.text,
            finish_reason=_map_finish(parsed.finish_reason),
            runtime_identity=self.identity().to_dict(),
            model_identity={
                "path": str(self._loaded_path),
                "sha256": self._loaded_digest,
                "size_bytes": self._loaded_path.stat().st_size,
            },
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            load_duration_ms=self._load_duration_ms,
            inference_duration_ms=duration,
            tokens_per_second=compute_throughput(completion_tokens, duration),
            resources={"backend": Measurement.observed(parsed.backend, source="runtime")},
            error=parsed.error,
        )

    def _context_length(self, request: InferenceRequest) -> int:
        # The adapter is constructed by the runtime, which knows the configured
        # context; fall back to the request's own bound when constructed bare.
        return getattr(self, "_configured_context", 2048)


class _MinimalSampling:
    repeat_penalty = 1.0
    stop: tuple[str, ...] = ()


class _MinimalConfig:
    """The two fields :func:`birth.llamacpp.build_command` actually reads."""

    def __init__(self, context_length: int, sampling: _MinimalSampling) -> None:
        self.context_length = context_length
        self.sampling = sampling


class _ResolvedPaths:
    def __init__(self, binary: Path, model: Path) -> None:
        self.binary = binary
        self.model = model


def _map_finish(reported: str) -> FinishReason:
    text = (reported or "").lower()
    if not text:
        return FinishReason.UNKNOWN
    if "stop" in text:
        return FinishReason.STOP_SEQUENCE
    if "length" in text:
        return FinishReason.LENGTH
    if "eos" in text or "end_of_text" in text:
        return FinishReason.EOS
    return FinishReason.UNKNOWN


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "SUPPORTED_SUFFIXES",
    "LlamaCppAdapter",
    "sha256_file",
]
