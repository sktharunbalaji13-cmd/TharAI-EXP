"""Terminal observer command line.

    python -m observer.cli                       # replay history, then follow
    python -m observer.cli --no-follow           # replay and exit
    python -m observer.cli --namespace system    # only system.* events
    python -m observer.cli --type security.human_control.verified
    python -m observer.cli --summary             # aggregate counts, not a stream
    python -m observer.cli --max-history 200 --detail
"""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from babylab.errors import BabyLabError
from babylab.paths import default_paths
from observer.format import RenderOptions, supports_colour
from observer.terminal import TerminalObserver


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m observer.cli",
        description="Terminal observer for the Baby AI laboratory event stream.",
    )
    parser.add_argument(
        "--no-follow",
        action="store_true",
        help="replay existing events and exit instead of following the log",
    )
    parser.add_argument(
        "--max-history",
        type=int,
        default=None,
        metavar="N",
        help="replay only the most recent N events",
    )
    parser.add_argument(
        "--namespace",
        action="append",
        default=None,
        metavar="NS",
        help="only show events in this namespace (repeatable)",
    )
    parser.add_argument(
        "--type",
        action="append",
        default=None,
        dest="types",
        metavar="TYPE",
        help="only show this exact event type (repeatable)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="aggregate by category and event type instead of streaming lines",
    )
    parser.add_argument("--detail", action="store_true", help="include the full payload")
    parser.add_argument("--source", action="store_true", help="show the producing component")
    parser.add_argument("--hash", action="store_true", help="show event id and hash prefix")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=0,
        metavar="N",
        help="print a throughput note every N displayed events",
    )
    parser.add_argument("--poll-interval", type=float, default=0.25)
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    return parser


def _force_utf8(stream: TextIO) -> None:
    """Make the observer survive Windows console code pages.

    A research stream gets piped into files, `Select-Object`, and log collectors
    all day. Under those conditions Python picks the ANSI code page, and a
    single ellipsis or box-drawing character becomes a replacement glyph -
    which quietly corrupts the very record the observer exists to show. Forcing
    UTF-8 with ``errors="replace"`` means the worst case is one visible ``?``
    rather than mis-decoded bytes.
    """
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):  # pragma: no cover - exotic streams
        pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    stream = sys.stdout
    options = RenderOptions(
        colour=supports_colour(stream) and not args.no_color,
        detail=args.detail,
        show_source=args.source,
        show_hash=args.hash,
    )
    observer = TerminalObserver(
        paths=default_paths(),
        stream=stream,
        options=options,
        follow=not args.no_follow,
        poll_interval=args.poll_interval,
        max_history=args.max_history,
        namespaces=args.namespace,
        types=args.types,
        summary_mode=args.summary,
        progress_every=args.progress_every,
    )
    try:
        observer.run()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print()
        return 130
    except BabyLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
