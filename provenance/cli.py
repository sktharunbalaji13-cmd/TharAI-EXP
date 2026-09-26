"""Integrity verification command line.

    python -m provenance.cli verify
    python -m provenance.cli verify --json
    python -m provenance.cli seal --reason "end of session"
    python -m provenance.cli keyring
    python -m provenance.cli summary

Exit codes
----------
0  everything verified
1  an integrity problem was found
2  the laboratory is not initialised, or configuration is unusable

A non-zero exit code is the point: this command is meant to be run from a
scheduled task or a pre-commit hook, where a human or a machine will notice.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from babylab.errors import BabyLabError
from babylab.identity import Actor, Role
from babylab.paths import default_paths
from babylab.trust import PathPolicy
from provenance.keyring import Keyring
from provenance.ledger import ProvenanceLedger
from provenance.recorder import ProvenanceRecorder, classify_problem, problem_path


def _components():
    paths = default_paths()
    keyring = Keyring(paths.keyring, paths.private_key_dir)
    ledger = ProvenanceLedger(
        paths.provenance_ledger, keyring, seal_dir=paths.protected_provenance
    )
    policy = PathPolicy(paths)
    recorder = ProvenanceRecorder(ledger, keyring, policy)
    return paths, keyring, ledger, policy, recorder


def cmd_verify(args: argparse.Namespace) -> int:
    paths, keyring, ledger, policy, recorder = _components()
    report = ledger.verify(deep=not args.fast)
    seal_report = ledger.verify_seal()
    path_problems = recorder.verify_paths()
    key_problems = keyring.audit()

    if args.json:
        import json

        print(
            json.dumps(
                {
                    "ledger": report.to_dict(),
                    "seal": seal_report.to_dict() if seal_report else None,
                    "protected_files": path_problems,
                    "keyring_audit": key_problems,
                    "untracked_by_design": [
                        {"path": paths.relative(root), "reason": reason}
                        for root, reason in recorder.untracked_by_design()
                    ],
                    "untracked_placeholders": [
                        {"name": name, "reason": reason}
                        for name, reason in recorder.untracked_placeholders()
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("Provenance integrity verification")
        print("=" * 60)
        print(f"  ledger          : {paths.provenance_ledger}")
        print(f"  entries         : {report.valid_entries}")
        print(f"  malformed lines : {report.malformed_lines}")
        print(f"  head            : {report.head_entry_id}")
        print(f"  chain + MACs    : {'INTACT' if report.intact else 'COMPROMISED'}")
        if seal_report is None:
            print("  seal            : none found (tail truncation undetectable)")
        else:
            print(f"  seal            : {'OK' if seal_report.intact else 'COMPROMISED'}")
        print(f"  keyring         : {'OK' if not key_problems else 'PROBLEMS'}")
        print(
            f"  protected files : "
            f"{'OK' if not path_problems else str(len(path_problems)) + ' PROBLEMS'}"
        )
        for problem in report.problems:
            print(f"    ! {problem}")
        if seal_report is not None:
            for problem in seal_report.problems:
                print(f"    ! {problem}")
        for problem in path_problems:
            print(f"    ! {problem}")
        for problem in key_problems:
            print(f"    ! {problem}")
        # Print the exclusions every time. An exclusion nobody is shown is an
        # exclusion nobody is reviewing, and a hole in the report that nobody
        # can see is the worst kind.
        print("")
        print("  Deliberately not tracked inside protected areas:")
        for root, reason in recorder.untracked_by_design():
            print(f"    - {paths.relative(root)}/")
            print(f"        {reason}")
        for name, reason in recorder.untracked_placeholders():
            print(f"    - {name} (any protected directory)")
            print(f"        {reason}")

    ok = report.intact and (seal_report is None or seal_report.intact)
    ok = ok and not path_problems and not key_problems
    return 0 if ok else 1


def cmd_seal(args: argparse.Namespace) -> int:
    _, keyring, ledger, _, _ = _components()
    entry = keyring.key_for_role(Role.HUMAN)
    actor = Actor.human_operator(key_id=entry.key_id)
    path = ledger.seal(actor, note=args.reason)
    print(f"sealed head {ledger.head().entry_id} -> {path}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """Bring the ledger up to date with what is actually on disk.

    This exists because creating *or editing* a research file outside the
    recorder is normal: an operator writes the experiment log in an editor, not
    through an API. The audit then correctly reports an unrecorded creation or
    modification, and the fix is to record it under the human key, never to
    weaken the audit.

    The action is chosen per file from what the audit reports, so ``record``
    with no ``--path`` does the right thing for whatever drifted. Naming a file
    explicitly overrides that, which is what you want when you know you edited
    something and want to be explicit about it.
    """
    paths, keyring, ledger, _, recorder = _components()
    entry = keyring.key_for_role(Role.HUMAN)
    actor = Actor.human_operator(key_id=entry.key_id)

    problems = recorder.verify_paths()

    def action_for(relative: str) -> str | None:
        """Which action the audit says this relative path needs."""
        for problem in problems:
            if problem_path(problem) != relative:
                continue
            action = classify_problem(problem)
            if action is not None:
                return action
        return None

    targets: list[tuple[Path, str]] = []
    if args.path:
        for raw in args.path:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = paths.root / candidate
            relative = paths.relative(candidate)
            action = action_for(relative) or (
                None if args.action == "auto" else args.action
            )
            if action is None:
                # Naming a file that the audit considers intact is a mistake
                # worth surfacing: recording it anyway would put a false entry
                # in a research record.
                if not candidate.exists():
                    print(f"error: no such file: {raw}", file=sys.stderr)
                else:
                    print(
                        f"error: {relative} needs no recording: the ledger already "
                        f"matches what is on disk. Pass --action "
                        f"create|modify|delete to record it anyway.",
                        file=sys.stderr,
                    )
                return 2
            targets.append((candidate, action))
    else:
        for problem in problems:
            action = classify_problem(problem)
            if action is not None:
                targets.append((paths.root / problem_path(problem), action))

    if not targets:
        print("nothing to record: every protected file is already in the ledger")
        return 0

    reason = args.reason or "recorded by operator"
    for target, action in sorted(set(targets)):
        relative = paths.relative(target)
        if action == "modify":
            recorded = recorder.record_modification(target, actor, args.milestone, reason)
        elif action == "delete":
            recorded = recorder.record_deletion(target, actor, args.milestone, reason)
        else:
            recorded = recorder.record_creation(target, actor, args.milestone, reason)
        print(f"recorded {action} of {relative} as {recorded.entry_id} ({recorded.author.value})")

    print("")
    print("Now re-seal so the new head is anchored:")
    print(f"  python -m provenance.cli seal --reason \"{args.reason or 'post-record'}\"")
    return 0


def cmd_keyring(args: argparse.Namespace) -> int:
    _, keyring, _, _, _ = _components()
    if args.json:
        import json

        print(json.dumps([entry.to_dict() for entry in keyring.entries()], indent=2))
        return 0
    print(f"Keyring: {keyring.public_path}")
    print("=" * 60)
    for entry in keyring.entries():
        print(f"  {entry.key_id}")
        print(f"    role        : {entry.role.value}")
        print(f"    actor       : {entry.actor_id}")
        print(f"    algorithm   : {entry.algorithm}")
        print(f"    fingerprint : {entry.fingerprint}")
        print(f"    state       : {entry.state}")
    problems = keyring.audit()
    for problem in problems:
        print(f"    ! {problem}")
    return 1 if problems else 0


def cmd_summary(args: argparse.Namespace) -> int:
    _, keyring, ledger, _, _ = _components()
    import json

    print(json.dumps(ledger.summary(), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m provenance.cli",
        description="Provenance integrity tools for the Baby AI laboratory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="verify the provenance ledger and protected files")
    verify.add_argument("--json", action="store_true", help="machine-readable output")
    verify.add_argument(
        "--fast",
        action="store_true",
        help="skip per-entry MAC verification (chain hashes only)",
    )
    verify.set_defaults(func=cmd_verify)

    seal = sub.add_parser("seal", help="anchor the current ledger head under the human key")
    seal.add_argument("--reason", default="", help="note stored with the seal")
    seal.set_defaults(func=cmd_seal)

    record = sub.add_parser(
        "record",
        help="record protected files whose on-disk state differs from the ledger",
    )
    record.add_argument(
        "--path",
        action="append",
        help=(
            "specific file to record; repeatable. Default: every file the audit "
            "reports as unrecorded"
        ),
    )
    record.add_argument(
        "--action",
        choices=("auto", "create", "modify", "delete"),
        default="auto",
        help=(
            "how to record a named file. 'auto' (default) takes the action the "
            "audit reports; the others record it explicitly"
        ),
    )
    record.add_argument("--milestone", default="MILESTONE-001")
    record.add_argument(
        "--reason", default="", help="why these files were created, changed, or removed"
    )
    record.set_defaults(func=cmd_record)

    keyring_cmd = sub.add_parser("keyring", help="list registered keys and audit their material")
    keyring_cmd.add_argument("--json", action="store_true")
    keyring_cmd.set_defaults(func=cmd_keyring)

    summary = sub.add_parser("summary", help="entry counts by author and action")
    summary.set_defaults(func=cmd_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BabyLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
