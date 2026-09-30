"""M011 real runtime: the execution path, with no stub escape hatch.

What makes a run "real" here
----------------------------
Three things must all be true, and the milestone is explicit that any one of
them being false is not enough:

1. the configured executable exists and is the one named;
2. it is the *actual* configured path, not a search result;
3. the completion came from that process, and a runner function was never
   supplied.

:class:`ExecutionMode` records which of the three obtained. There is no code path
that produces ``REAL_RUNTIME`` from a substituted runner: the mode is computed
from what was actually invoked, and :func:`_mode_for` will not return
``REAL_RUNTIME`` when a runner was passed.

Why this matters more than it looks
-----------------------------------
The tempting shortcut is to accept a callable that stands in for the binary, so
the pipeline can be exercised without a model. That is fine for a unit test and
unacceptable for a milestone whose whole subject is whether a real process really
ran. So the stub path exists, is fully functional, and is *named* ``STUB_RUNTIME``
in every record it touches -- and this milestone's acceptance can therefore never
be satisfied by it.

Immutability of both artifacts
------------------------------
The model digest and the *runtime binary* digest are each captured before and
after. M010 checked the model; M011 adds the binary, because a runtime that
rewrote itself would invalidate every identity claim made about it, and a
laboratory that only checked the model would miss exactly that.
"""

from __future__ import annotations

import enum
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from babylab.runtime.contract import (
    EpistemicStatus,
    Measurement,
    RuntimeErrorKind,
    RuntimeFailure,
)

#: Wall-clock ceiling for a real generation. A hang must be a reported timeout,
#: not a wedged laboratory.
DEFAULT_TIMEOUT_SECONDS = 600.0

#: Ceiling for the `--version` probe.
PROBE_TIMEOUT_SECONDS = 30.0


class ExecutionMode(str, enum.Enum):
    """Which of the three reality conditions obtained."""

    #: The configured binary ran and produced the text.
    REAL_RUNTIME = "REAL_RUNTIME"
    #: A caller-supplied callable stood in for the binary.
    STUB_RUNTIME = "STUB_RUNTIME"
    #: A fixture ran, with no real model artifact.
    SIMULATED = "SIMULATED"
    #: Nothing ran; a prerequisite was absent or refused.
    NOT_TESTABLE = "NOT_TESTABLE"
    #: Something ran and failed.
    FAILED = "FAILED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_real(self) -> bool:
        return self is ExecutionMode.REAL_RUNTIME


class RealRuntimeState(str, enum.Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    BINARY_MISSING = "BINARY_MISSING"
    BINARY_EMPTY = "BINARY_EMPTY"
    PROBE_FAILED = "PROBE_FAILED"
    READY = "READY"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class RuntimeReadiness:
    """Whether the configured executable can be executed at all."""

    state: RealRuntimeState
    binary_path: str = ""
    binary_sha256: str = "UNAVAILABLE"
    binary_size_bytes: int = 0
    version: str = "UNAVAILABLE"
    version_source: str = "none"
    implementation: str = "llama.cpp"
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.state is RealRuntimeState.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "ready": self.ready,
            "binary_path": self.binary_path,
            "binary_sha256": self.binary_sha256,
            "binary_size_bytes": self.binary_size_bytes,
            "version": self.version,
            "version_source": self.version_source,
            "implementation": self.implementation,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


def assess_runtime(
    binary: str | Path | None,
    *,
    declared_version: str = "",
    invoker=None,
) -> RuntimeReadiness:
    """Check the configured executable exists, hashes, and identifies itself.

    No ``PATH`` search and no fallback to a different executable. A named binary
    that is absent yields ``BINARY_MISSING``; the laboratory does not go looking
    for another one, because a runtime that silently swaps its executor is not
    the runtime that was declared.
    """
    from foundation.runtime_identity import sha256_binary

    if not binary:
        return RuntimeReadiness(
            state=RealRuntimeState.NOT_CONFIGURED,
            detail=(
                "no runtime binary is named. The laboratory does not search the "
                "filesystem, does not search PATH, and does not install one."
            ),
        )

    path = Path(binary)
    if not path.is_file():
        return RuntimeReadiness(
            state=RealRuntimeState.BINARY_MISSING,
            binary_path=str(path),
            detail=(
                f"the configured runtime binary is not present at {path}. The "
                "laboratory does not search for another executable and does not "
                "download one."
            ),
        )

    size = path.stat().st_size
    if size == 0:
        return RuntimeReadiness(
            state=RealRuntimeState.BINARY_EMPTY, binary_path=str(path),
            detail=f"the configured runtime binary at {path} is zero bytes",
        )

    digest, basis = sha256_binary(path)

    if invoker is None:
        from foundation.runtime_identity import probe_version

        version, source, raw = probe_version(path)
    else:
        version, source, raw = invoker(path)

    if version == "UNAVAILABLE":
        return RuntimeReadiness(
            state=RealRuntimeState.PROBE_FAILED, binary_path=str(path),
            binary_sha256=digest, binary_size_bytes=size,
            version="UNAVAILABLE", version_source=source,
            detail=(
                f"the binary exists and hashed, but did not report a version: "
                f"{source}"
            ),
            evidence={"raw_probe_output": raw, "digest_basis": basis},
        )

    note = ""
    if declared_version and declared_version not in version:
        note = (
            f" The declaration states {declared_version!r}, which the binary's "
            "own output does not contain; the binary's answer is authoritative."
        )

    return RuntimeReadiness(
        state=RealRuntimeState.READY,
        binary_path=str(path),
        binary_sha256=digest,
        binary_size_bytes=size,
        version=version,
        version_source=source,
        detail=(
            f"the configured binary executed and identified itself as {version}."
            f"{note} This establishes the runtime only."
        ),
        evidence={"raw_probe_output": raw, "digest_basis": basis,
                  "declared_version": declared_version},
    )


def _mode_for(
    *, runner_supplied: bool, artifact_is_real: bool, ran: bool
) -> ExecutionMode:
    """Derive the mode from what actually happened.

    ``REAL_RUNTIME`` is unreachable whenever a runner was supplied, which is the
    whole point: the mode is computed from the invocation, not declared by the
    caller.
    """
    if not ran:
        return ExecutionMode.NOT_TESTABLE
    if runner_supplied:
        return ExecutionMode.STUB_RUNTIME
    if artifact_is_real:
        return ExecutionMode.REAL_RUNTIME
    return ExecutionMode.SIMULATED


@dataclass
class RealRun:
    """One real (or explicitly not-real) execution."""

    mode: ExecutionMode
    outcome: str = "NOT_RUN"
    state: RealRuntimeState = RealRuntimeState.NOT_CONFIGURED
    prompt_sha256: str = ""
    output_sha256: str = ""
    output_bytes: int = 0
    finish_reason: str = ""
    termination_reason: str = ""
    command: list[str] = field(default_factory=list)
    model_identity: dict[str, Any] = field(default_factory=dict)
    runtime_identity: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    completion_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    total_tokens: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    load_duration_ms: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    inference_duration_ms: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    tokens_per_second: Measurement = field(
        default_factory=lambda: Measurement.unavailable("no run")
    )
    resources: dict[str, Measurement] = field(default_factory=dict)
    error: str = ""
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_real(self) -> bool:
        return self.mode.is_real

    @property
    def succeeded(self) -> bool:
        return self.outcome == "COMPLETED"

    @property
    def token_accounting_complete(self) -> bool:
        return (
            self.prompt_tokens.is_available
            and self.completion_tokens.is_available
            and self.prompt_tokens.status is EpistemicStatus.OBSERVED
            and self.completion_tokens.status is EpistemicStatus.OBSERVED
        )

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode.value,
            "is_real_runtime": self.mode.is_real,
            "outcome": self.outcome,
            "state": self.state.value,
            "prompt_sha256": self.prompt_sha256,
            "output_sha256": self.output_sha256,
            "output_bytes": self.output_bytes,
            "finish_reason": self.finish_reason,
            "termination_reason": self.termination_reason,
            "model_identity": dict(self.model_identity),
            "runtime_identity": dict(self.runtime_identity),
            "token_accounting": {
                "prompt_tokens": self.prompt_tokens.to_dict(),
                "completion_tokens": self.completion_tokens.to_dict(),
                "total_tokens": self.total_tokens.to_dict(),
                "complete": self.token_accounting_complete,
            },
            "timing": {
                "load_duration_ms": self.load_duration_ms.to_dict(),
                "inference_duration_ms": self.inference_duration_ms.to_dict(),
                "tokens_per_second": self.tokens_per_second.to_dict(),
            },
            "resources": {k: v.to_dict() for k, v in self.resources.items()},
            "error": self.error,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }
        if include_text:
            payload["output_text"] = self.evidence.get("output_text", "")
        return payload


def _counts(prompt: int | None, completion: int | None) -> tuple:
    """Token accounting, copied from what the runtime printed and nothing else."""
    prompt_m = (
        Measurement.observed(prompt, "count", "runtime-reported")
        if prompt is not None
        else Measurement.unavailable(
            "the runtime printed no prompt token count; the laboratory does not "
            "estimate one"
        )
    )
    completion_m = (
        Measurement.observed(completion, "count", "runtime-reported")
        if completion is not None
        else Measurement.unavailable(
            "the runtime printed no completion token count; the laboratory does "
            "not estimate one"
        )
    )
    if prompt is not None and completion is not None:
        total = Measurement.derived(
            prompt + completion, "count",
            "sum of the two runtime-reported counts",
        )
    else:
        total = Measurement.unavailable("one or both component counts are unavailable")
    return prompt_m, completion_m, total


def run_real(
    *,
    model_path: str | Path | None,
    model_sha256: str,
    binary: str | Path | None,
    sampling: Any = None,
    prompt: str | None = None,
    runner=None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    declared_version: str = "",
    artifact_is_real: bool = True,
) -> RealRun:
    """Execute the configured runtime against the configured model.

    When ``runner`` is supplied the mode is ``STUB_RUNTIME`` no matter what else
    is true. That is computed in :func:`_mode_for` rather than asserted, so a
    future caller cannot accidentally claim a real run from a substituted
    runner.
    """
    from foundation.inference import (
        VALIDATION_PROMPT,
        assert_neutral_prompt,
        output_digest,
        prompt_digest,
    )

    text_prompt = prompt if prompt is not None else VALIDATION_PROMPT
    assert_neutral_prompt(text_prompt)
    digest = prompt_digest(text_prompt)

    # The artifact is checked *before* the binary is probed, and the order is
    # deliberate on two counts. There is nothing to run without a model, so a
    # missing artifact is the more fundamental fact to report. And probing means
    # executing the executable, so probing first would run a program in order to
    # discover there was nothing for it to do.
    if not model_path or not Path(model_path).is_file():
        return RealRun(
            mode=ExecutionMode.NOT_TESTABLE,
            outcome="NOT_RUN",
            state=RealRuntimeState.NOT_CONFIGURED,
            prompt_sha256=digest,
            model_identity={"path": str(model_path) if model_path else "",
                            "sha256": model_sha256 or "UNAVAILABLE"},
            detail=(
                f"no model artifact is present at {model_path}. The laboratory "
                "does not download, search for, or substitute one."
            ),
            evidence={"reason": "ARTIFACT_MISSING"},
        )

    if runner is not None:
        # A stub still needs a binary to describe, but nothing is executed.
        readiness = assess_runtime(binary, declared_version=declared_version,
                                   invoker=lambda p: ("stub", "caller-supplied", ""))
        readiness.state = RealRuntimeState.PROBE_FAILED
        readiness.detail = "a caller-supplied runner replaced the binary"
    else:
        readiness = assess_runtime(binary, declared_version=declared_version)

    if not readiness.ready and runner is None:
        return RealRun(
            mode=ExecutionMode.NOT_TESTABLE,
            outcome="NOT_RUN",
            state=readiness.state,
            prompt_sha256=digest,
            command=[],
            model_identity={"path": str(model_path), "sha256": model_sha256},
            runtime_identity=readiness.to_dict(),
            detail=readiness.detail,
            evidence={"reason": readiness.state.value},
        )

    from birth.llamacpp import build_command, parse_llama_output
    from babylab.runtime.config import load_configuration
    from babylab.runtime.llamacpp_adapter import _MinimalConfig, _MinimalSampling, _ResolvedPaths

    if sampling is None:
        from foundation.inference import baseline_sampling

        sampling = baseline_sampling()

    config = _MinimalConfig(
        context_length=sampling.context_length, sampling=_MinimalSampling()
    )
    paths = _ResolvedPaths(binary=Path(str(binary)), model=Path(str(model_path)))
    command = build_command(
        config, paths,
        prompt=text_prompt,
        max_tokens=sampling.max_tokens,
        temperature=sampling.temperature,
        top_p=sampling.top_p,
        top_k=sampling.top_k,
        repeat_penalty=sampling.repeat_penalty,
        seed=sampling.seed,
        stop=tuple(sampling.stop),
        n_gpu_layers=sampling.n_gpu_layers,
        threads=sampling.threads,
    )

    load_started = time.perf_counter()
    try:
        if runner is not None:
            completed = runner(command, timeout_seconds)
        else:
            completed = subprocess.run(
                command,
                capture_output=True, text=True, timeout=timeout_seconds,
                stdin=subprocess.DEVNULL, shell=False,
            )
    except subprocess.TimeoutExpired:
        mode = _mode_for(runner_supplied=runner is not None,
                         artifact_is_real=artifact_is_real, ran=True)
        return RealRun(
            mode=ExecutionMode.FAILED if mode.is_real else mode,
            outcome="TIMEOUT", state=readiness.state, prompt_sha256=digest,
            command=list(command),
            model_identity={"path": str(model_path), "sha256": model_sha256},
            runtime_identity=readiness.to_dict(),
            termination_reason="timeout",
            error=(
                f"the runtime did not finish within {timeout_seconds:.0f}s and "
                "was terminated. The configuration was not silently reduced and "
                "the run was not retried with different settings."
            ),
            detail="a timeout is a reported failure, not a reason to shrink the model",
            evidence={"timeout_seconds": timeout_seconds},
        )
    except OSError as exc:
        mode = _mode_for(runner_supplied=runner is not None,
                         artifact_is_real=artifact_is_real, ran=True)
        return RealRun(
            mode=ExecutionMode.FAILED if mode.is_real else mode,
            outcome="ERROR", state=readiness.state, prompt_sha256=digest,
            command=list(command),
            model_identity={"path": str(model_path), "sha256": model_sha256},
            runtime_identity=readiness.to_dict(),
            termination_reason="exec-error",
            error=f"the runtime could not be executed: {exc}",
            evidence={"exception": type(exc).__name__},
        )

    elapsed_ms = (time.perf_counter() - load_started) * 1000.0
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    parsed = parse_llama_output(stdout, stderr)

    mode = _mode_for(runner_supplied=runner is not None,
                     artifact_is_real=artifact_is_real, ran=True)

    prompt_m, completion_m, total_m = _counts(
        parsed.prompt_tokens, parsed.completion_tokens
    )

    produced_text = bool(parsed.text and parsed.text.strip())
    outcome = "COMPLETED" if produced_text else (
        "MALFORMED_OUTPUT" if (parsed.error and not produced_text) else "ERROR"
    )

    duration = Measurement.observed(round(elapsed_ms, 3), "ms", "perf_counter")
    throughput = Measurement.unavailable(
        "no runtime-reported completion token count, so no throughput is derived"
    )
    if completion_m.is_available and duration.is_available and duration.value > 0:
        throughput = Measurement.derived(
            round(int(completion_m.value) / (float(duration.value) / 1000.0), 3),
            "tok/s", "runtime-reported tokens divided by measured wall clock",
        )

    resources = {
        "backend": Measurement.observed(parsed.backend, source="runtime stderr"),
        "stderr_tail": Measurement.observed(
            parsed.diagnostics.get("stderr_tail", []), source="runtime stderr"
        ),
        "exit_code": Measurement.observed(
            int(getattr(completed, "returncode", 0) or 0), source="process"
        ),
    }

    return RealRun(
        mode=mode,
        outcome=outcome,
        state=readiness.state,
        prompt_sha256=digest,
        output_sha256=output_digest(parsed.text) if parsed.text else "",
        output_bytes=len(parsed.text.encode("utf-8")) if parsed.text else 0,
        finish_reason=parsed.finish_reason or "UNKNOWN",
        termination_reason=parsed.finish_reason or outcome,
        command=list(command),
        model_identity={
            "path": str(model_path),
            "sha256": model_sha256,
            "size_bytes": Path(model_path).stat().st_size,
        },
        runtime_identity=readiness.to_dict(),
        prompt_tokens=prompt_m,
        completion_tokens=completion_m,
        total_tokens=total_m,
        load_duration_ms=Measurement.observed(
            round(float(parsed.diagnostics.get("load_time_ms", 0.0)), 3)
            if isinstance(parsed.diagnostics.get("load_time_ms"), (int, float))
            else float("nan"),
            "ms", "runtime-reported",
        ) if isinstance(parsed.diagnostics.get("load_time_ms"), (int, float))
        else Measurement.unavailable("the runtime printed no load time"),
        inference_duration_ms=duration,
        tokens_per_second=throughput,
        resources=resources,
        error=parsed.error,
        detail=(
            "a real binary produced this text. It is foundation model output: "
            "not a subject, not an experience, and not evidence of memory or "
            "learning."
            if mode.is_real
            else f"a {mode.value} run produced this text; it does not satisfy the "
                 "M011 real-runtime criterion"
        ),
        evidence={
            "finish_reason": parsed.finish_reason,
            "stderr_tail": parsed.diagnostics.get("stderr_tail", []),
            "output_text": parsed.text,
            "argv_is_vector": True,
            "shell_used": False,
        },
    )


def check_runtime_immutable(
    before: RuntimeReadiness, after: RuntimeReadiness
) -> dict[str, Any]:
    """Compare the runtime binary's identity across a run.

    A runtime that rewrote itself would invalidate every identity claim made
    about it, so this is checked with the same rigour as the model artifact and
    with the same failure consequence.
    """
    same = (
        bool(before.binary_sha256)
        and before.binary_sha256 == after.binary_sha256
        and before.binary_size_bytes == after.binary_size_bytes
    )
    return {
        "immutable": same,
        "before_sha256": before.binary_sha256,
        "after_sha256": after.binary_sha256,
        "before_size_bytes": before.binary_size_bytes,
        "after_size_bytes": after.binary_size_bytes,
        "verdict": (
            "the runtime executable is byte-identical before and after the run"
            if same
            else "RUNTIME MUTATED: the executable's bytes changed during the run. "
                 "Every identity claim made about this runtime is now void."
        ),
    }


@dataclass
class DeterminismVerdict:
    """What two identical attempts produced, in M011's vocabulary.

    The verdict names are scoped to the tested configuration on purpose.
    ``DETERMINISTIC_FOR_TEST_CONFIGURATION`` is a statement about one seed, one
    prompt, one hardware, one runtime build -- not about the model, and not about
    determinism in general. A general claim would be both unfalsifiable here and
    wrong in general.
    """

    verdict: str
    attempted: bool
    first_output_sha256: str = ""
    repeat_output_sha256: str = ""
    token_counts_agree: bool | None = None
    outcomes_agree: bool | None = None
    detail: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def deterministic(self) -> bool | None:
        if not self.attempted:
            return None
        return self.verdict == "DETERMINISTIC_FOR_TEST_CONFIGURATION"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "attempted": self.attempted,
            "deterministic": self.deterministic,
            "first_output_sha256": self.first_output_sha256,
            "repeat_output_sha256": self.repeat_output_sha256,
            "token_counts_agree": self.token_counts_agree,
            "outcomes_agree": self.outcomes_agree,
            "configuration": dict(self.configuration),
            "detail": self.detail,
            "scope": (
                "this verdict covers exactly the recorded configuration on this "
                "host with this runtime build. It is not a claim about the model "
                "and not a claim about determinism in general."
            ),
            "evidence": dict(self.evidence),
        }


def compare_two(first: RealRun, second: RealRun | None) -> DeterminismVerdict:
    """Compare two attempts at the same configuration.

    ``second`` is ``None`` when a repeat was not possible, which is reported as
    ``NOT_DETERMINED`` rather than as a pass.
    """
    if second is None:
        return DeterminismVerdict(
            verdict="NOT_DETERMINED",
            attempted=False,
            first_output_sha256=first.output_sha256,
            detail=(
                "no repeat attempt was made, so determinism was not established "
                "in either direction. This is not a pass."
            ),
        )

    identical = bool(
        first.output_sha256 and first.output_sha256 == second.output_sha256
    )
    token_agree: bool | None = None
    if (first.completion_tokens.is_available
            and second.completion_tokens.is_available):
        token_agree = first.completion_tokens.value == second.completion_tokens.value
    outcome_agree = first.outcome == second.outcome

    verdict = (
        "DETERMINISTIC_FOR_TEST_CONFIGURATION"
        if identical
        else "NONDETERMINISTIC_FOR_TEST_CONFIGURATION"
    )
    detail = (
        "two attempts at the identical recorded configuration produced "
        "byte-identical output"
        if identical
        else "two attempts at the identical recorded configuration produced "
             "different output. Recorded as an observation about this runtime and "
             "model pair on this host; it is not evidence that either is broken, "
             "and it is not suppressed."
    )
    return DeterminismVerdict(
        verdict=verdict,
        attempted=True,
        first_output_sha256=first.output_sha256,
        repeat_output_sha256=second.output_sha256,
        token_counts_agree=token_agree,
        outcomes_agree=outcome_agree,
        detail=detail,
        configuration={
            "prompt_sha256": first.prompt_sha256,
            "argv": first.command,
            "seed": first.evidence.get("seed"),
            "runtime_binary": first.runtime_identity.get("binary_path"),
            "runtime_sha256": first.runtime_identity.get("binary_sha256"),
            "model_sha256": first.model_identity.get("sha256"),
        },
        evidence={
            "first_outcome": first.outcome,
            "repeat_outcome": second.outcome,
            "first_mode": first.mode.value,
            "repeat_mode": second.mode.value,
        },
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "PROBE_TIMEOUT_SECONDS",
    "DeterminismVerdict",
    "ExecutionMode",
    "RealRun",
    "RealRuntimeState",
    "RuntimeReadiness",
    "assess_runtime",
    "check_runtime_immutable",
    "compare_two",
    "run_real",
]
