"""Command line for the birth subsystem.

Commands
--------
``status``   What does a ceremony currently find? Writes nothing, ever.
``ceremony`` Create the experimental subject, or explain why it could not.
``verify``   Check the birth record's own integrity.
``capabilities``  The unordered capability contracts, with their honest status.
``model``    The configured model identity and its installation status.

``status`` and ``verify`` are read-only by construction: neither is given a
provenance recorder, an event store, or a write path. That is the point. A status
command that could mutate the laboratory is a command nobody can safely run from
a dashboard.
"""

from __future__ import annotations

import argparse
import sys

from babylab.errors import BabyLabError
from babylab.hashing import canonical_json
from babylab.paths import ProjectPaths, default_paths
from birth.birth_record import load_record, record_path, verify_record
from birth.cognitive import CapabilityRegistry
from birth.config import load_config
from birth.identity import resolve_model_identity
from birth.service import birth_ceremony
from birth.status import inspect


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m birth.cli",
        description="Birth subsystem: model installation, birth ceremony, capability contracts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="report what a ceremony would find (read-only)")
    status.add_argument("--json", action="store_true", help="emit JSON")
    status.add_argument("--probe-runtime", action="store_true",
                        help="also execute the configured runtime's version query")

    ceremony = sub.add_parser("ceremony", help="create the experimental subject")
    ceremony.add_argument("--subject-id", default="baby-ai:subject-001")
    ceremony.add_argument("--experiment-id", default="EXP-BIRTH-001")
    ceremony.add_argument("--json", action="store_true", help="emit JSON")
    ceremony.add_argument("--no-provenance", action="store_true",
                          help="write the record without recording it in the ledger "
                               "(for recovery; the record is then unprotected)")
    ceremony.add_argument("--notes", default="")

    verify = sub.add_parser("verify", help="verify the birth record's integrity (read-only)")
    verify.add_argument("--json", action="store_true")

    caps = sub.add_parser("capabilities", help="the capability contracts and their status")
    caps.add_argument("--json", action="store_true")
    caps.add_argument("--status", default="", help="filter by status value")

    model = sub.add_parser("model", help="configured model identity and installation status")
    model.add_argument("--json", action="store_true")
    model.add_argument("--probe-runtime", action="store_true")

    return parser


def _runtime_probe(paths: ProjectPaths):
    """A probe that runs the configured runtime's version query, or says why not."""
    from birth.llamacpp import LlamaCppModel, resolve_paths

    try:
        config = load_config(paths)
        resolved = resolve_paths(config, paths)
    except (BabyLabError, ValueError) as exc:
        def unavailable(_config):
            return False, str(exc), "UNAVAILABLE"

        return unavailable

    probe = LlamaCppModel(config, paths)

    def run(cfg):
        return probe.probe(cfg)

    return run


def cmd_status(args: argparse.Namespace, paths: ProjectPaths) -> int:
    probe = _runtime_probe(paths) if args.probe_runtime else None
    result = inspect(paths, runtime_probe=probe)
    if args.json:
        print(canonical_json(result.to_dict()))
        return 0
    print(f"model status   {result.status.value}")
    print(f"               {result.detail}")
    print(f"capabilities   registry {result.capability_registry_hash[:12]}")
    print(f"environment    {result.environment_id} (connected: {result.environment_connected})")
    print(f"workspace      {result.workspace_state}")
    record = load_record(paths)
    if record:
        print(f"subject        {record.subject_id} born {record.born_at}")
        print(f"               {record.describe()}")
    else:
        print("subject        none: no birth record exists")
    return 0


def cmd_ceremony(args: argparse.Namespace, paths: ProjectPaths) -> int:
    recorder = None
    if not args.no_provenance:
        recorder = _build_recorder(paths, args.experiment_id)
    result = birth_ceremony(
        subject_id=args.subject_id,
        experiment_id=args.experiment_id,
        paths=paths,
        recorder=recorder,
        notes=args.notes,
    )
    if args.json:
        print(canonical_json(result.to_dict()))
        return 0 if result.born or result.record else 1
    print(result.describe())
    if result.born and result.record:
        print(f"record         {result.record_path}")
        print(f"               hash {result.record.hash[:16]}...")
        print(f"event          {result.event_id} ({result.event_hash[:16]}...)")
        if result.provenance_entries:
            print(f"provenance     {', '.join(result.provenance_entries)}")
    return 0 if result.born or result.record else 1


def _build_recorder(paths: ProjectPaths, experiment_id: str):
    from babylab.trust import PathPolicy
    from provenance.keyring import Keyring
    from provenance.ledger import ProvenanceLedger
    from provenance.recorder import ProvenanceRecorder

    try:
        keyring = Keyring(paths.keyring, paths.private_key_dir).load()
        ledger = ProvenanceLedger(paths.provenance_ledger, keyring)
        policy = PathPolicy(paths)
    except BabyLabError as exc:
        print(
            f"provenance unavailable ({exc}); writing the record without ledger "
            "protection",
            file=sys.stderr,
        )
        return None
    return ProvenanceRecorder(ledger, keyring, policy)


def cmd_verify(args: argparse.Namespace, paths: ProjectPaths) -> int:
    ok, problems = verify_record(paths)
    if args.json:
        print(canonical_json({"ok": ok, "problems": problems}))
        return 0 if ok else 1
    if ok:
        print(f"birth record   valid: {record_path(paths)}")
        return 0
    print("birth record   INVALID")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def cmd_capabilities(args: argparse.Namespace, paths: ProjectPaths) -> int:
    registry = CapabilityRegistry()
    if args.json:
        print(canonical_json(registry.to_dict()))
        return 0
    print(f"{len(registry)} capability contracts. The registry is an unordered set;")
    print("this listing is sorted for reproducibility and the order means nothing.\n")
    for contract in registry:
        if args.status and contract.status.value != args.status:
            continue
        print(f"{contract.kind.value:<16} {contract.status.value}")
        print(f"{'':<16} {contract.contract}")
        print(f"{'':<16} why: {contract.reason}")
        print()
    return 0


def cmd_model(args: argparse.Namespace, paths: ProjectPaths) -> int:
    probe = _runtime_probe(paths) if args.probe_runtime else None
    try:
        config = load_config(paths)
    except BabyLabError as exc:
        payload = {
            "configured": False,
            "status": "NOT_CONFIGURED",
            "detail": str(exc),
            "model": None,
            "installed": False,
            "authorship": "INHERITED_PRETRAINED",
        }
        if args.json:
            print(canonical_json(payload))
        else:
            print("configured      no")
            print(f"status          {payload['status']}")
            print(f"                {payload['detail']}")
            print("authorship      INHERITED_PRETRAINED (any model would be)")
        return 1
    report = resolve_model_identity(config, paths, runtime_probe=probe)
    payload = {
        "configured": True,
        "status": report.status.value,
        "detail": report.detail,
        "model": report.identity.to_dict() if report.identity else None,
        "installed": report.status.is_usable,
        "model_path": str(report.model_path) if report.model_path else None,
        "observed_sha256": report.observed_sha256,
        "notes": list(report.notes),
    }
    if args.json:
        print(canonical_json(payload))
        return 0 if report.status.is_usable else 1
    print(f"configured      yes")
    print(f"status          {report.status.value}")
    print(f"                {report.detail}")
    if report.identity:
        identity = report.identity
        print(f"model           {identity.model_name} ({identity.quantization})")
        print(f"                revision {identity.model_revision}")
        print(f"                sha256   {identity.model_sha256}")
        print(f"                runtime  {identity.runtime} {identity.runtime_version}")
        print(f"                config   {identity.configuration_hash[:16]}")
        if identity.license:
            print(f"                license  {identity.license}")
        print(f"authorship      {identity.authorship.value}")
        print(f"                {identity.authorship_basis}")
    for note in report.notes:
        print(f"note            {note}")
    return 0 if report.status.is_usable else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = default_paths()
    handlers = {
        "status": cmd_status,
        "ceremony": cmd_ceremony,
        "verify": cmd_verify,
        "capabilities": cmd_capabilities,
        "model": cmd_model,
    }
    try:
        return handlers[args.command](args, paths)
    except BabyLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
