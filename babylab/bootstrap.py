"""One-time initialisation of the laboratory.

Run by ``scripts/bootstrap.ps1``. Idempotent: safe to run again, and it will
report what it skipped rather than overwriting.

What bootstrap creates
----------------------
* The directory skeleton.
* A keyring with one HUMAN key and one SYSTEM key, both provisioned here, by
  the operator, before any experiment exists.
* A control-plane authentication token.
* The control-plane configuration file.
* A ``baseline/`` record describing the state of the laboratory at t=0.
* The first events in the log, and a signed provenance seal.

Deliberately NOT created
------------------------
No ``BABY_AI`` key. That key is provisioned by the human at the moment a
subject actually exists, so that the act of provisioning is itself a dated,
attributable research decision. Minting it now would be a small, quiet
assumption about the future experiment.
"""

from __future__ import annotations

import base64
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from babylab.clock import Clock
from babylab.errors import ConfigurationError
from babylab.hashing import canonical_json
from babylab.identity import Actor, Role
from babylab.paths import DIRECTORIES, ProjectPaths, default_paths
from babylab.storage import atomic_write_text
from babylab.trust import PathPolicy
from events.store import EventStore
from provenance.keyring import Keyring
from provenance.ledger import ProvenanceLedger
from provenance.recorder import ProvenanceRecorder

MILESTONE = "MILESTONE-001"
CONTROL_TOKEN_BYTES = 32
DEFAULT_CONTROL_HOST = "127.0.0.1"
DEFAULT_CONTROL_PORT = 47311


@dataclass
class BootstrapResult:
    paths: ProjectPaths
    created: list[str]
    skipped: list[str]
    human_key_id: str
    system_key_id: str
    event_count: int

    def render(self) -> str:
        lines = ["Laboratory bootstrap complete", "=" * 60]
        for item in self.created:
            lines.append(f"  created : {item}")
        for item in self.skipped:
            lines.append(f"  skipped : {item} (already present)")
        lines.append(f"  HUMAN key : {self.human_key_id}")
        lines.append(f"  SYSTEM key: {self.system_key_id}")
        lines.append(f"  events    : {self.event_count}")
        return "\n".join(lines)


def bootstrap(root: Path | None = None, quiet: bool = False) -> BootstrapResult:
    paths = ProjectPaths(Path(root).resolve()) if root else default_paths()
    clock = Clock()
    created: list[str] = []
    skipped: list[str] = []

    # -- directories ------------------------------------------------------
    before = {d for d in _existing_dirs(paths)}
    paths.ensure_directories()
    after = {d for d in _existing_dirs(paths)}
    for item in sorted(after - before):
        created.append(item)
    if not after - before:
        skipped.append("directory skeleton")

    # -- keyring ----------------------------------------------------------
    keyring = Keyring(paths.keyring, paths.private_key_dir, clock=clock)
    if paths.keyring.exists():
        keyring.load()
        skipped.append("keyring")
    else:
        keyring._entries = {}  # start empty; load() would fail
        keyring._loaded = True
        keyring.register(
            Role.HUMAN,
            actor_id="human:operator",
            note="Human researcher. Provisioned at laboratory bootstrap, before "
            "any subject existed.",
        )
        keyring.register(
            Role.SYSTEM,
            actor_id="system:lab",
            note="Laboratory infrastructure. Distinct from the human key so that "
            "infrastructure authorship stays distinguishable from human "
            "authorship in the ledger.",
        )
        created.append("keyring with HUMAN and SYSTEM keys")

    human_entry = keyring.key_for_role(Role.HUMAN)
    system_entry = keyring.key_for_role(Role.SYSTEM)

    # -- control token ----------------------------------------------------
    if paths.control_token.exists():
        skipped.append("control authentication token")
    else:
        token = base64.b64encode(secrets.token_bytes(CONTROL_TOKEN_BYTES)).decode("ascii")
        atomic_write_text(paths.control_token, token + "\n")
        created.append("control authentication token")

    # -- control configuration -------------------------------------------
    if paths.control_config.exists():
        skipped.append("control configuration")
    else:
        atomic_write_text(
            paths.control_config,
            canonical_json(
                {
                    "schema": "babylab/control-config/v1",
                    "host": DEFAULT_CONTROL_HOST,
                    "port": DEFAULT_CONTROL_PORT,
                    "token_file": paths.relative(paths.control_token),
                    "bind_note": (
                        "Loopback only. A future Baby AI process on the same "
                        "machine can reach this port, so the token file must be "
                        "unreadable to that process. See docs/security-model.md."
                    ),
                }
            )
            + "\n",
        )
        created.append("control configuration")

    # -- event log --------------------------------------------------------
    store = EventStore(paths.event_store, clock=clock)
    if store.head() is not None:
        skipped.append("event log")
    else:
        store.append_many(
            [
                (
                    "system.observer.started",
                    "babylab.bootstrap",
                    {
                        "headline": "Observer started",
                        "milestone": MILESTONE,
                        "note": "Terminal observer is available; no subject is attached.",
                    },
                ),
                (
                    "system.research.environment_initialized",
                    "babylab.bootstrap",
                    {
                        "headline": "Research environment initialized",
                        "milestone": MILESTONE,
                        "root": str(paths.root),
                        "python": sys.version.split()[0],
                        "platform": sys.platform,
                    },
                ),
                (
                    "security.human_control.verified",
                    "babylab.bootstrap",
                    {
                        "headline": "Human control area verified",
                        "boundary": "application",
                        "note": (
                            "Application-level path policy initialised. The "
                            "operating-system ACL boundary is defined but NOT "
                            "yet applied; see scripts/trust_boundaries.ps1 -Audit."
                        ),
                    },
                ),
                (
                    "provenance.keyring.provisioned",
                    "babylab.bootstrap",
                    {
                        "headline": "Provenance keyring provisioned",
                        "human_key_id": human_entry.key_id,
                        "system_key_id": system_entry.key_id,
                        "algorithm": human_entry.algorithm,
                    },
                ),
            ]
        )
        created.append("initial event log entries")

    # -- provenance baseline ---------------------------------------------
    policy = PathPolicy(paths)
    ledger = ProvenanceLedger(
        paths.provenance_ledger, keyring, clock=clock, seal_dir=paths.protected_provenance
    )
    recorder = ProvenanceRecorder(ledger, keyring, policy, clock=clock)
    human = Actor.human_operator(key_id=human_entry.key_id)

    if ledger.count() == 0:
        recorder.record_creation(
            paths.keyring,
            human,
            experiment_id=MILESTONE,
            reason="Laboratory bootstrap: register human and system signing keys.",
        )
        recorder.record_creation(
            paths.control_token,
            human,
            experiment_id=MILESTONE,
            reason=(
                "Laboratory bootstrap: provision control-plane authentication "
                "token. The token's digest is recorded here so that later "
                "substitution is detectable. This is safe because the ledger is "
                "excluded from version control; see docs/provenance.md."
            ),
        )
        recorder.record_creation(
            paths.control_config,
            human,
            experiment_id=MILESTONE,
            reason="Laboratory bootstrap: control-plane configuration.",
        )
        created.append("provenance baseline entries")
    else:
        skipped.append("provenance baseline entries")

    # -- baseline record --------------------------------------------------
    baseline_path = paths.baseline / "BASELINE.json"
    if baseline_path.exists():
        skipped.append("baseline record")
    else:
        atomic_write_text(
            baseline_path,
            canonical_json(
                {
                    "schema": "babylab/baseline/v1",
                    "milestone": MILESTONE,
                    "recorded_by": human.to_record(),
                    "root": str(paths.root),
                    "python": sys.version.split()[0],
                    "platform": sys.platform,
                    "keyring_commitment": keyring.commitment(),
                    "keys": {
                        "HUMAN": human_entry.key_id,
                        "SYSTEM": system_entry.key_id,
                        "BABY_AI": None,
                    },
                    "event_log_head": (store.head().hash if store.head() else None),
                    "provenance_head": (ledger.head().hash if ledger.head() else None),
                    "subject_present": False,
                    "ai_present": False,
                    "note": (
                        "Machine-specific facts. Recorded so that a later "
                        "divergence in environment is detectable rather than "
                        "mysterious."
                    ),
                }
            )
            + "\n",
        )
        created.append("baseline record")

    # The baseline is written after the first ledger entries, so record it last.
    if ledger.latest_for_path(paths.relative(baseline_path)) is None:
        recorder.record_creation(
            baseline_path,
            human,
            experiment_id=MILESTONE,
            reason="Laboratory bootstrap: record the t=0 state of the laboratory.",
        )

    if not quiet:
        store.append(
            "provenance.baseline.recorded",
            "babylab.bootstrap",
            {"headline": "Repository integrity verified", "milestone": MILESTONE},
        )

    # -- seal (last, so it covers every bootstrap entry) ------------------
    if ledger.count() > 0:
        ledger.seal(human, note="bootstrap baseline")

    result = BootstrapResult(
        paths=paths,
        created=created,
        skipped=skipped,
        human_key_id=human_entry.key_id,
        system_key_id=system_entry.key_id,
        event_count=store.count(),
    )
    return result


def _existing_dirs(paths: ProjectPaths) -> list[str]:
    return [d for d in DIRECTORIES if (paths.root / d).is_dir()]


def _self_check() -> int:  # pragma: no cover - operator convenience
    """Verify that the artefacts bootstrap claims to have created are present."""
    paths = default_paths()
    problems: list[str] = []
    for required in (paths.keyring, paths.control_token, paths.control_config):
        if not required.exists():
            problems.append(f"missing file: {required}")
    for relative in DIRECTORIES:
        directory = paths.root / relative
        if not directory.is_dir():
            problems.append(f"missing directory: {directory}")
    for problem in problems:
        print(f"  ! {problem}")
    if not problems:
        print(f"layout OK: {len(DIRECTORIES)} directories present at {paths.root}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m babylab.bootstrap",
        description="Initialise the Baby AI laboratory. Idempotent.",
    )
    parser.add_argument("--root", type=Path, default=None, help="project root override")
    parser.add_argument("--self-check", action="store_true", help="only verify layout")
    args = parser.parse_args(argv)

    if args.self_check:
        return _self_check()
    try:
        result = bootstrap(root=args.root)
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(result.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
