"""Command line interface for the Cognitive State Observatory.

Subcommands
-----------
``status``
    One-shot summary. Integrity, subject attachment, ingest counters.
``state``
    One-shot cognitive state render.
``live``
    Follow the canonical event log, redrawing as events arrive.
``history``
    Every state transition, with the events that caused it (§13).

All four are read-only. None of them opens the event store for writing, and
``tests/test_observatory_security.py`` asserts that the module does not even
import a write entry point.
"""

from __future__ import annotations

import argparse
import json
import sys

from babylab.clock import Clock
from babylab.paths import default_paths
from observer.cli import _force_utf8
from observatory.render import RenderOptions, default_options
from observatory.terminal import ObservatorySession
from provenance.keyring import Keyring


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m observatory.cli",
        description="Observe subject state from the canonical event log. Read-only.",
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument("--detail", action="store_true", help="show source event IDs")
    parser.add_argument("--json", action="store_true", help="emit the snapshot as JSON")
    parser.add_argument(
        "--subject-namespace",
        action="append",
        default=None,
        metavar="NS",
        help=(
            "event namespace a real subject is permitted to write under "
            "(repeatable). Declared by the human; never inferred from events."
        ),
    )
    parser.add_argument(
        "--subject-label",
        default=None,
        help="display label for the subject, once one is attached",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="one-shot summary")
    sub.add_parser("state", help="one-shot cognitive state")

    live = sub.add_parser("live", help="follow the event log")
    live.add_argument("--refresh", type=float, default=0.2, help="seconds between redraws")
    live.add_argument("--iterations", type=int, default=None, help="stop after N redraws")

    history = sub.add_parser("history", help="show state transitions")
    history.add_argument("--limit", type=int, default=20, help="transitions to show")
    return parser


def _session(args: argparse.Namespace) -> ObservatorySession:
    # Root resolution honours BABYAI_HOME, exactly as every other command does.
    paths = default_paths()
    clock = Clock()
    # The keyring is the only authority on whether a subject exists, so the CLI
    # must consult it rather than assuming. With no BABY_AI key this yields
    # NO SUBJECT, which is the correct answer for this milestone.
    keyring = Keyring(paths.keyring, paths.private_key_dir, clock=clock)
    return ObservatorySession(
        paths=paths,
        clock=clock,
        keyring=keyring,
        subject_namespace=frozenset(args.subject_namespace or ()),
        subject_label=args.subject_label,
    )


def _options(args: argparse.Namespace) -> RenderOptions:
    return default_options(color=False if args.no_color else None, detail=args.detail)


def _cmd_status(session: ObservatorySession, args: argparse.Namespace) -> int:
    snapshot = session.update()
    if args.json:
        print(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
        return 0
    registry = session.registry
    reader = session.reader
    print("=" * 72)
    print("  BABY LAB :: COGNITIVE STATE OBSERVATORY :: STATUS")
    print("=" * 72)
    print(f"  {'subject':<24}{snapshot.subject_banner}")
    if snapshot.subject_detail:
        print(f"  {'':<24}{snapshot.subject_detail}")
    print(f"  {'event log':<24}{session.paths.event_store}")
    print(f"  {'events ingested':<24}{reader.ingested_count()}")
    print(f"  {'state versions':<24}{session.deriver.version()}")
    print(f"  {'reported domains':<24}{len(session.deriver.snapshot(0).reported())}")
    print(f"  {'integrity':<24}{'read-only consumer'}")
    print("=" * 72)
    return 0


def _cmd_state(session: ObservatorySession, args: argparse.Namespace) -> int:
    snapshot = session.update()
    if args.json:
        print(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
        return 0
    from observatory.render import ObservatoryRenderer

    print(ObservatoryRenderer(_options(args)).render(snapshot))
    return 0


def _cmd_live(session: ObservatorySession, args: argparse.Namespace) -> int:
    session.refresh = args.refresh
    return session.follow(render_options=_options(args), iterations=args.iterations)


def _cmd_history(session: ObservatorySession, args: argparse.Namespace) -> int:
    session.update()
    transitions = session.deriver.history()
    if args.json:
        print(
            json.dumps(
                {
                    "schema": "babylab/observatory-history/v1",
                    "transitions": [t.to_dict() for t in transitions],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print("=" * 72)
    print("  STATE TRANSITION HISTORY")
    print("=" * 72)
    if not transitions:
        print("  No state transitions.")
        print("  " + ("No subject attached, so none are possible." if not session.registry.is_attached()
                        else "The subject has not reported any state yet."))
        return 0
    for transition in transitions[-args.limit :]:
        print(f"  v{transition.version}  {transition.timestamp}")
        print(f"      {transition.reason}")
        for event_id in transition.cause_event_ids:
            print(f"      caused by: {event_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    args = build_parser().parse_args(argv)
    session = _session(args)
    handlers = {
        "status": _cmd_status,
        "state": _cmd_state,
        "live": _cmd_live,
        "history": _cmd_history,
    }
    return handlers[args.command](session, args)


if __name__ == "__main__":
    sys.exit(main())
