"""M012 discovery: report candidates, never promote one.

The rule this module exists to enforce
--------------------------------------
> Filesystem discovery may be used ONLY to report candidates to the human.
> It must never automatically promote a candidate to SELECTED_MODEL or
> SELECTED_RUNTIME.

M011 found a real `llama-server.exe` in a Docker bin directory and correctly left
it unselected. That behaviour is easy to preserve by accident and easy to lose
the first time someone adds a convenience -- an `--auto` flag, a "use the first
one found if only one exists" branch, a default path that fills in a missing
declaration. Each of those is one small convenience and a completely different
laboratory.

So the separation here is structural rather than disciplinary:

* :class:`Candidate` has **no field** that could hold a selection decision. It
  carries observations about a file and nothing that any other function reads as
  a decision.
* :func:`discover_candidates` returns a :class:`CandidateReport` whose
  ``promotable`` is a hard-coded ``False``, with a note saying why.
* :func:`foundation.deployment.load_declaration` is the only function in the
  package that produces a :class:`~foundation.deployment.Deployment`, and it
  takes a path a human wrote. It has no parameter a candidate could be passed
  through.
* :func:`assert_not_selected` is the runtime guard: it is called with any
  candidate about to be used, and it raises if the candidate was not named in the
  declaration. So even a future caller that skips the obvious checks hits a hard
  stop rather than an unselected binary getting executed.

What a scan is allowed to do
----------------------------
Look at a bounded set of conventional locations, record what is there, and stop.
It does not hash multi-gigabyte files (that would be doing the verification the
human's declaration is supposed to authorise), does not execute anything, and
does not follow a discovered path into any further scan.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Conventional places a human might have put a foundation. Checked only to
#: *report*; nothing here is a search path the laboratory will use.
MODEL_CANDIDATE_DIRECTORIES: tuple[str, ...] = (
    "human_control/experiment_config/weights",
    "var/models",
)

#: Executable-name patterns that would be recognised as a llama.cpp build. Used
#: for reporting only.
RUNTIME_NAME_PATTERNS: tuple[str, ...] = (
    "llama-cli", "llama-server", "llama-perplexity",
    "llama-simple", "main",
)

#: Depth limit. A recursive walk of a user profile is not a bounded scan, and an
#: unbounded scan is how a "quick check" becomes a five-minute stall.
MAX_DEPTH = 3

#: Never more than this many candidates reported per category. A truncated report
#: is stated as truncated rather than silently shortened.
MAX_CANDIDATES = 20


class CandidateKind(str, enum.Enum):
    MODEL = "MODEL"
    RUNTIME = "RUNTIME"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Candidate:
    """An observation about a file that exists. Not a decision.

    Deliberately has no ``selected``, ``approved``, or ``chosen`` field. The
    absence is the design: there is nowhere for a decision to be recorded on a
    candidate, so no later function can read one off it.
    """

    kind: CandidateKind
    path: str
    filename: str
    size_bytes: int
    extension: str
    observations: dict[str, Any] = field(default_factory=dict)

    @property
    def is_model_candidate(self) -> bool:
        return self.kind is CandidateKind.MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "path": self.path,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "extension": self.extension,
            "observations": dict(self.observations),
            "is_selected": False,
            "selection_possible_here": False,
            "note": (
                "an observation, not a selection. This file is not used, not "
                "hashed, and not executed unless a human names it in the "
                "deployment declaration."
            ),
        }


@dataclass(frozen=True)
class CandidateReport:
    """The result of a scan. Reports; never promotes."""

    models: tuple[Candidate, ...] = ()
    runtimes: tuple[Candidate, ...] = ()
    directories_scanned: tuple[str, ...] = ()
    truncated: bool = False
    detail: str = ""

    @property
    def promotable(self) -> bool:
        """Always False.

        A property with no branch, so there is no code path -- including a
        future one -- in which a scan yields something selectable.
        """
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "babylab/candidate-report/v1",
            "promotable": False,
            "promotion_policy": (
                "filesystem discovery reports candidates to a human and nothing "
                "else. Promotion requires a human writing the deployment "
                "declaration, which is the only route to a Deployment object."
            ),
            "models": [c.to_dict() for c in self.models],
            "runtimes": [c.to_dict() for c in self.runtimes],
            "model_count": len(self.models),
            "runtime_count": len(self.runtimes),
            "directories_scanned": list(self.directories_scanned),
            "truncated": self.truncated,
            "detail": self.detail,
        }


def _bounded_walk(directory: Path, max_depth: int = MAX_DEPTH):
    """Walk at most ``max_depth`` levels, yielding files.

    The depth cap is what makes this a *report* rather than a search: a scan that
    can recurse without bound eventually reaches every file on the machine, and a
    scan that reaches every file on the machine is a search.
    """
    if not directory.is_dir():
        return
    base_depth = len(directory.parts)
    for candidate in directory.glob("**/*"):
        try:
            if len(candidate.parts) - base_depth > max_depth:
                continue
            if candidate.is_file():
                yield candidate
        except OSError:  # pragma: no cover - unreadable entry
            continue


def discover_candidates(
    root: str | Path | None = None,
    *,
    extra_runtime_directories: tuple[str, ...] = (),
) -> CandidateReport:
    """Report what is on the machine. Select nothing.

    The optional ``extra_runtime_directories`` is for a *human* to name a place
    they built llama.cpp. It is not a search: the caller had to know the
    directory, and nothing is executed from it.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)

    models: list[Candidate] = []
    runtimes: list[Candidate] = []
    scanned: list[str] = []
    truncated = False

    for relative in MODEL_CANDIDATE_DIRECTORIES:
        directory = root / relative
        if not directory.is_dir():
            continue
        scanned.append(str(directory))
        for path in _bounded_walk(directory):
            if path.suffix.lower() != ".gguf":
                continue
            if len(models) >= MAX_CANDIDATES:
                truncated = True
                break
            try:
                size = path.stat().st_size
            except OSError:  # pragma: no cover
                continue
            models.append(Candidate(
                kind=CandidateKind.MODEL,
                path=str(path),
                filename=path.name,
                size_bytes=size,
                extension=path.suffix.lower(),
                observations={
                    "size_is_plausible_for_a_model": size >= (1 << 20),
                    "hashed": False,
                    "hashed_why": (
                        "hashing here would perform the verification that the "
                        "human's declaration is supposed to authorise, against a "
                        "file the human has not yet chosen"
                    ),
                },
            ))

    runtime_directories = [root / relative for relative in ()]
    runtime_directories.extend(Path(d) for d in extra_runtime_directories)
    for directory in runtime_directories:
        if not directory.is_dir():
            continue
        scanned.append(str(directory))
        for path in _bounded_walk(directory):
            stem = path.stem.lower()
            if not any(stem.startswith(pattern) for pattern in RUNTIME_NAME_PATTERNS):
                continue
            if not path.suffix.lower() in {".exe", ""}:
                continue
            if len(runtimes) >= MAX_CANDIDATES:
                truncated = True
                break
            try:
                size = path.stat().st_size
            except OSError:  # pragma: no cover
                continue
            runtimes.append(Candidate(
                kind=CandidateKind.RUNTIME,
                path=str(path),
                filename=path.name,
                size_bytes=size,
                extension=path.suffix.lower(),
                observations={
                    "executable_bit_observed": False,
                    "version_read": False,
                    "version_read_why": (
                        "executing an unselected binary to read its version is "
                        "running a program nobody chose to run"
                    ),
                },
            ))

    return CandidateReport(
        models=tuple(models),
        runtimes=tuple(runtimes),
        directories_scanned=tuple(scanned),
        truncated=truncated,
        detail=(
            f"reported {len(models)} model candidate(s) and {len(runtimes)} "
            "runtime candidate(s). None is selected, hashed, or executed. "
            "Selection requires a human writing the deployment declaration."
        ),
    )


class UnselectedCandidate(RuntimeError):
    """Raised when something tries to use a candidate that was never selected.

    The runtime guard. A future convenience that reaches for the first discovered
    executable hits this instead of quietly running it.
    """


def assert_not_selected(candidate: Candidate, declared_paths: tuple[str, ...]) -> None:
    """Refuse to use a candidate the human did not name.

    Called with the candidate and the paths from the declaration. Equality is on
    the resolved absolute path, so a candidate reached by a different relative
    spelling is still recognised as the same file -- the check is about the file,
    not about the string used to reach it.
    """
    if not declared_paths:
        raise UnselectedCandidate(
            f"{candidate.path} is a discovered candidate and no deployment "
            "declaration exists, so nothing is selected. Executing it would be "
            "running a binary no human chose."
        )
    resolved = {str(Path(p).resolve()) for p in declared_paths if p}
    if str(Path(candidate.path).resolve()) not in resolved:
        raise UnselectedCandidate(
            f"{candidate.path} was discovered but is not named in the deployment "
            "declaration. A file merely existing is not a selection."
        )


__all__ = [
    "MAX_CANDIDATES",
    "MAX_DEPTH",
    "MODEL_CANDIDATE_DIRECTORIES",
    "RUNTIME_NAME_PATTERNS",
    "Candidate",
    "CandidateKind",
    "CandidateReport",
    "UnselectedCandidate",
    "assert_not_selected",
    "discover_candidates",
]
