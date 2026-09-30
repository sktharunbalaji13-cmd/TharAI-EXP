"""M012 compatibility: can this runtime load this artifact?

The three answers
-----------------
``COMPATIBLE``
    The runtime loaded the artifact and said so.
``INCOMPATIBLE``
    The runtime refused it, and the refusal is reported verbatim.
``UNKNOWN``
    The question could not be settled, and the reason is given.

What is deliberately **not** evidence
-------------------------------------
The filename. ``model.gguf`` with a ``.gguf`` extension is a strong hint and
nothing more -- llama.cpp rejects plenty of files that end in ``.gguf``, and it
would happily try to load files that do not. So:

* an extension match alone is ``UNKNOWN`` with the reason "the filename suggests
  a format, which establishes nothing about whether this runtime can read it";
* a GGUF magic-number check narrows the *format*, and narrows nothing about
  *compatibility*;
* only an actual load settles it.

This is the specific error the milestone names -- interpreting
``file extension = compatibility`` -- and it is worth being blunt about how easy
it is to write by accident. Every code path that would return ``COMPATIBLE``
without a load attempt returning success is a path this module does not have.

Why the failure stays a failure
-------------------------------
A load failure is recorded as ``INCOMPATIBLE`` with the runtime's own message and
a non-zero exit code. It is not retried with a smaller context, a lower layer
count, or a different file, and nothing is substituted. A deployment that cannot
load its declared foundation is a deployment that does not work, and saying so is
the entire value of this module.
"""

from __future__ import annotations

import enum
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundation.artifact import GGUF_MAGIC

#: A load probe must not run for long. The ceiling is generous because a cold
#: page cache on a spinning disk can be slow, and a timeout here would be
#: indistinguishable from a hang.
LOAD_PROBE_TIMEOUT_SECONDS = 300.0

#: A ``--version`` probe loads no weights at all.
VERSION_PROBE_TIMEOUT_SECONDS = 30.0


class Compatibility(str, enum.Enum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class CompatibilityResult:
    """Whether the selected runtime can load the selected artifact."""

    compatibility: Compatibility
    reason: str
    method: str = "none"
    format_check: str = "UNAVAILABLE"
    model_path: str = ""
    runtime_path: str = ""
    exit_code: int | None = None
    duration_ms: float | None = None
    runtime_message: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def established_by_load(self) -> bool:
        """True only when a real load settled it.

        The single predicate that separates a measured answer from a guess, and
        the one an acceptance criterion should read.
        """
        return self.method == "runtime_load_attempt" and self.compatibility in {
            Compatibility.COMPATIBLE, Compatibility.INCOMPATIBLE
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatibility": self.compatibility.value,
            "established_by_load": self.established_by_load,
            "reason": self.reason,
            "method": self.method,
            "format_check": self.format_check,
            "model_path": self.model_path,
            "runtime_path": self.runtime_path,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "runtime_message": self.runtime_message,
            "filename_is_not_evidence": (
                "a .gguf extension establishes a naming convention, not "
                "compatibility; only a load attempt settles the question"
            ),
            "evidence": dict(self.evidence),
        }


def check_format(path: str | Path) -> dict[str, Any]:
    """Narrow the *format* of an artifact. Never narrows compatibility."""
    target = Path(path)
    if not target.is_file():
        return {
            "is_gguf": False,
            "detail": f"{target} does not exist",
        }
    try:
        with target.open("rb") as handle:
            magic = handle.read(4)
    except OSError as exc:  # pragma: no cover
        return {"is_gguf": False, "detail": f"could not be read: {exc}"}
    if magic != GGUF_MAGIC:
        return {
            "is_gguf": False,
            "detail": (
                f"{target.name} does not begin with the GGUF magic, so it is not "
                "a GGUF whatever it is called"
            ),
        }
    return {
        "is_gguf": True,
        "detail": (
            f"{target.name} carries the GGUF magic. That establishes the format "
            "and nothing more; whether this runtime can load it is a separate "
            "question answered only by a load attempt."
        ),
    }


def assess_compatibility(
    *,
    model_path: str | Path | None,
    runtime_path: str | Path | None,
    runner=None,
    probe_timeout: float = LOAD_PROBE_TIMEOUT_SECONDS,
) -> CompatibilityResult:
    """Establish whether the declared runtime can load the declared artifact.

    ``runner`` substitutes the process call for tests. When it is supplied the
    result is marked ``STUB_LOAD`` in ``method`` and
    :attr:`CompatibilityResult.established_by_load` is False, so a stubbed probe
    can never be reported as a real compatibility answer.
    """
    if not model_path or not Path(model_path).is_file():
        return CompatibilityResult(
            compatibility=Compatibility.UNKNOWN,
            reason=(
                f"no model artifact is present at {model_path}. Compatibility "
                "cannot be established for an artifact that does not exist, and "
                "the laboratory will not go looking for one."
            ),
            method="none",
            model_path=str(model_path or ""),
        )

    if not runtime_path or not Path(runtime_path).is_file():
        return CompatibilityResult(
            compatibility=Compatibility.UNKNOWN,
            reason=(
                f"no runtime executable is present at {runtime_path}. The "
                "laboratory does not search for one, download one, or substitute "
                "another."
            ),
            method="none",
            model_path=str(model_path),
            runtime_path=str(runtime_path or ""),
        )

    model = Path(model_path)
    binary = Path(runtime_path)
    fmt = check_format(model)

    if runner is not None:
        return _probe(
            model, binary, runner, fmt, method="STUB_LOAD",
            reason_prefix=(
                "a caller-supplied process stand-in answered the load probe, so "
                "this is not a real compatibility result"
            ),
            probe_timeout=probe_timeout,
        )

    def real_runner(command: list[str], timeout: float):
        return subprocess.run(
            command,
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, shell=False,
        )

    return _probe(
        model, binary, real_runner, fmt, method="runtime_load_attempt",
        reason_prefix="", probe_timeout=probe_timeout,
    )


#: Markers a llama.cpp build prints when it has read a model's header. The
#: presence of one is the runtime saying it parsed the file, which is the whole
#: point of the probe.
_LOAD_MARKERS = (
    "file format", "gguf", "arch ", "n_ctx", "n_embd", "model size",
    "llama_model_loader", "load_tensors", "print_info",
)

#: Markers that mean the loader refused. Reported verbatim rather than mapped to
#: a friendly phrase, because the runtime's own diagnosis is the useful artefact.
_REFUSAL_MARKERS = (
    "failed to load model", "unknown model", "invalid model",
    "unsupported", "error loading", "failed to open", "no such file",
    "unknown architecture", "file is not a gguf",
)


def _probe(
    model: Path,
    binary: Path,
    runner,
    fmt: dict[str, Any],
    *,
    method: str,
    reason_prefix: str,
    probe_timeout: float,
) -> CompatibilityResult:
    """Run a load probe and classify what came back."""
    # The probe asks for the smallest generation that still forces a load. A
    # larger request would measure speed rather than compatibility, and a
    # smaller one that skips the load would measure nothing.
    command = [
        str(binary), "--model", str(model),
        "--prompt", "x", "--n-predict", "1", "--seed", "0",
        "--temp", "0", "--no-display-prompt",
    ]

    started = time.perf_counter()
    try:
        completed = runner(command, probe_timeout)
    except subprocess.TimeoutExpired:
        return CompatibilityResult(
            compatibility=Compatibility.UNKNOWN,
            reason=(
                f"{reason_prefix}the load probe did not finish within "
                f"{probe_timeout:.0f}s. A timeout is not a compatibility answer: "
                "it could be a slow disk, a large model, or a hung runtime, and "
                "the laboratory will not guess which or retry with a smaller "
                "configuration."
            ).strip(),
            method=method,
            format_check=fmt["detail"],
            model_path=str(model),
            runtime_path=str(binary),
            duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )
    except OSError as exc:
        return CompatibilityResult(
            compatibility=Compatibility.UNKNOWN,
            reason=(
                f"{reason_prefix}the runtime could not be executed: {exc}"
            ).strip(),
            method=method,
            format_check=fmt["detail"],
            model_path=str(model),
            runtime_path=str(binary),
            duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )

    duration = round((time.perf_counter() - started) * 1000.0, 3)
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    exit_code = int(getattr(completed, "returncode", 1) or 0)
    combined = f"{stdout}\n{stderr}"
    lowered = combined.lower()

    refusal = next(
        (marker for marker in _REFUSAL_MARKERS if marker in lowered), None
    )
    if exit_code != 0 or refusal:
        message = _tail(combined)
        return CompatibilityResult(
            compatibility=Compatibility.INCOMPATIBLE,
            reason=(
                f"{reason_prefix}the runtime refused the artifact "
                f"(exit {exit_code}"
                + (f", reporting {refusal!r}" if refusal else "")
                + "). A failed load remains a failed load: no smaller context, "
                  "no lower layer count, and no substitute file was tried."
            ).strip(),
            method=method,
            format_check=fmt["detail"],
            model_path=str(model),
            runtime_path=str(binary),
            exit_code=exit_code,
            duration_ms=duration,
            runtime_message=message,
            evidence={"refusal_marker": refusal},
        )

    loaded = any(marker in lowered for marker in _LOAD_MARKERS)
    if loaded or stdout.strip():
        return CompatibilityResult(
            compatibility=Compatibility.COMPATIBLE,
            reason=(
                f"{reason_prefix}the runtime loaded the artifact and produced "
                f"output (exit {exit_code})."
            ).strip(),
            method=method,
            format_check=fmt["detail"],
            model_path=str(model),
            runtime_path=str(binary),
            exit_code=exit_code,
            duration_ms=duration,
            runtime_message=_tail(combined),
            evidence={"load_marker_found": loaded},
        )

    # Exit 0, no output, no marker. The runtime accepted the command and said
    # nothing, which establishes nothing.
    return CompatibilityResult(
        compatibility=Compatibility.UNKNOWN,
        reason=(
            f"{reason_prefix}the runtime exited {exit_code} without printing "
            "either a load confirmation or a refusal. Silence is not a "
            "compatibility answer, so the result is UNKNOWN rather than "
            "COMPATIBLE."
        ).strip(),
        method=method,
        format_check=fmt["detail"],
        model_path=str(model),
        runtime_path=str(binary),
        exit_code=exit_code,
        duration_ms=duration,
        runtime_message=_tail(combined),
    )


def _tail(text: str, lines: int = 6) -> str:
    """The last few lines of runtime output, verbatim and truncated.

    The runtime's own words are the evidence. Summarising them into a friendly
    phrase would discard the part a human needs in order to act.
    """
    tail = [line.strip() for line in str(text).splitlines() if line.strip()]
    return " | ".join(tail[-lines:])[:600]


__all__ = [
    "LOAD_PROBE_TIMEOUT_SECONDS",
    "VERSION_PROBE_TIMEOUT_SECONDS",
    "Compatibility",
    "CompatibilityResult",
    "assess_compatibility",
    "check_format",
]
