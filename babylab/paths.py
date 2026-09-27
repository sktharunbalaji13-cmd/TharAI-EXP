"""Canonical layout of the laboratory on disk.

The project root is discovered, in order, from:

1. an explicit ``root`` argument,
2. the ``BABYAI_HOME`` environment variable,
3. the directory containing this package's parent (i.e. the checkout root).

``BABYAI_HOME`` exists so the automated test suite can run against a throwaway
sandbox instead of the real research records. It is read by tests only; the
running system uses the checkout root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_HOME = "BABYAI_HOME"

#: Directories that make up the laboratory. Created by bootstrap.
DIRECTORIES = (
    "docs",
    "docs/decisions",
    "research",
    "human_control",
    "human_control/baseline",
    "human_control/provenance",
    "human_control/experiment_config",
    "human_control/research_records",
    "human_control/security",
    "human_control/security/keys",
    "human_control/security/keys/private",
    "human_control/snapshots",
    "human_control/birth_records",
    "baby_workspace",
    "baby_workspace/code",
    "baby_workspace/experiments",
    "baby_workspace/generated",
    "baby_workspace/memory",
    "baby_workspace/temporary",
    "observer",
    "observatory",
    "birth",
    "control",
    "events",
    "provenance",
    "babylab",
    "tests",
    "scripts",
    "var",
    "var/events",
    "var/provenance",
    "var/logs",
    "var/models",
)

#: Directories that hold Python packages. They must never contain runtime
#: data, keys, or logs. Enforced by tests/test_trust_boundaries.py.
CODE_DIRECTORIES = (
    "babylab",
    "events",
    "provenance",
    "observer",
    "observatory",
    "birth",
    "control",
    "tests",
)


@dataclass(frozen=True)
class ProjectPaths:
    """Resolved absolute paths for every area of the laboratory.

    Frozen so that a caller cannot repoint a validated path policy at another
    tree partway through an operation.
    """

    root: Path

    # -- top level --------------------------------------------------------
    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def research(self) -> Path:
        return self.root / "research"

    @property
    def human_control(self) -> Path:
        return self.root / "human_control"

    @property
    def baby_workspace(self) -> Path:
        return self.root / "baby_workspace"

    @property
    def var(self) -> Path:
        return self.root / "var"

    # -- trust domains ----------------------------------------------------
    @property
    def baseline(self) -> Path:
        return self.human_control / "baseline"

    @property
    def protected_provenance(self) -> Path:
        """Human-owned provenance area: sealed heads and manifests."""
        return self.human_control / "provenance"

    @property
    def experiment_config(self) -> Path:
        return self.human_control / "experiment_config"

    @property
    def research_records(self) -> Path:
        return self.human_control / "research_records"

    @property
    def security(self) -> Path:
        return self.human_control / "security"

    @property
    def keyring(self) -> Path:
        return self.security / "keys" / "keyring.json"

    @property
    def private_key_dir(self) -> Path:
        return self.security / "keys" / "private"

    @property
    def control_token(self) -> Path:
        return self.security / "control.token"

    @property
    def snapshots(self) -> Path:
        return self.human_control / "snapshots"

    @property
    def birth_records(self) -> Path:
        """Immutable birth records. Written once, at the birth ceremony.

        Inside ``human_control/`` and therefore outside the subject's write
        authority, which is the point: the record of what a subject was born as
        must not be writable by the subject.
        """
        return self.human_control / "birth_records"

    @property
    def birth_record(self) -> Path:
        """The single birth record. Milestone 003 permits at most one."""
        return self.birth_records / "BIRTH.json"

    @property
    def foundation_config(self) -> Path:
        """The explicit foundation-model configuration.

        Configuration is human-owned and protected; model *weights* are not.
        See ``var/models`` below and docs/birth-architecture.md.
        """
        return self.experiment_config / "foundation.json"

    # -- baby workspace ---------------------------------------------------
    @property
    def baby_code(self) -> Path:
        return self.baby_workspace / "code"

    @property
    def baby_experiments(self) -> Path:
        return self.baby_workspace / "experiments"

    @property
    def baby_generated(self) -> Path:
        return self.baby_workspace / "generated"

    @property
    def baby_memory(self) -> Path:
        return self.baby_workspace / "memory"

    @property
    def baby_temporary(self) -> Path:
        return self.baby_workspace / "temporary"

    # -- system runtime ---------------------------------------------------
    # NOTE: runtime data lives under var/, never inside the events/ and
    # provenance/ *code* directories. The specification's suggested layout puts
    # the event log at events/events.jsonl and the ledger at
    # provenance/ledger.jsonl, which would place data and Python packages in
    # the same directory. That was tried and it is a trap: deleting the runtime
    # data silently deletes the source. See docs/architecture.md, "Deviation 1".
    @property
    def runtime(self) -> Path:
        return self.var

    @property
    def event_store(self) -> Path:
        return self.var / "events" / "events.jsonl"

    @property
    def provenance_ledger(self) -> Path:
        return self.var / "provenance" / "ledger.jsonl"

    @property
    def log_dir(self) -> Path:
        return self.var / "logs"

    @property
    def model_dir(self) -> Path:
        """Where model weight files live.

        Under ``var/`` and therefore excluded from version control, because
        model weights are large binary artefacts and a weight file in Git is a
        weight file in every clone forever. The *hash* of the weights is recorded
        in the protected configuration and in the birth record, which is what
        makes the installation reproducible without checking the bytes into
        source control.
        """
        return self.var / "models"

    @property
    def control_config(self) -> Path:
        return self.experiment_config / "control.json"

    @property
    def git_dir(self) -> Path:
        return self.root / ".git"

    # -- helpers ----------------------------------------------------------
    def relative(self, path: Path) -> str:
        """Path relative to the project root, using forward slashes.

        Forward slashes keep recorded provenance paths identical across
        Windows and POSIX, which matters for long-term comparability.
        """
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return resolved.as_posix()

    def ensure_directories(self) -> None:
        for relative in DIRECTORIES:
            (self.root / relative).mkdir(parents=True, exist_ok=True)


def default_paths() -> ProjectPaths:
    """Resolve the project paths for the current environment."""
    override = os.environ.get(ENV_HOME)
    if override:
        return ProjectPaths(Path(override).resolve())
    return ProjectPaths(Path(__file__).resolve().parent.parent)
