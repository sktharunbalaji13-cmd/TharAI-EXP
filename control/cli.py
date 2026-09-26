"""Control-plane command line.

    python -m control.cli serve            # run the control process (foreground)
    python -m control.cli status           # query a running control process
    python -m control.cli inspect          # detailed state
    python -m control.cli pause
    python -m control.cli resume
    python -m control.cli snapshot --label before-run
    python -m control.cli shutdown
    python -m control.cli wait             # block until the server answers

Every subcommand except ``serve`` talks to an already-running control process
over the authenticated loopback channel. None of them can be invoked by a
process that cannot read the token in ``human_control/security/``.
"""

from __future__ import annotations

import argparse
import json
import sys

from babylab.errors import BabyLabError
from control.client import ControlClient
from control.protocol import Operation
from control.server import ControlServer


def _client(args: argparse.Namespace) -> ControlClient:
    return ControlClient(host=args.host, port=args.port)


def _run(args: argparse.Namespace, op: Operation, **kwargs) -> int:
    client = _client(args)
    try:
        response = getattr(client, op.value)(**kwargs)
    except BabyLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(response.to_dict(), indent=2, sort_keys=True))
    elif response.ok:
        print(json.dumps(response.result, indent=2, sort_keys=True))
    else:
        print(f"error [{response.error_code}]: {response.error}", file=sys.stderr)
    return 0 if response.ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        server = ControlServer(host=args.host, port=args.port)
    except BabyLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"control process listening on {server.host}:{server.port}")
    print("press Ctrl+C to stop")
    server.serve_forever()
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    client = _client(args)
    ready = client.wait_for_server(attempts=args.attempts)
    print("control process is answering" if ready else "control process did not answer")
    return 0 if ready else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m control.cli",
        description="Privileged control plane for the Baby AI laboratory.",
    )
    parser.add_argument("--host", default=None, help="override control host")
    parser.add_argument("--port", type=int, default=None, help="override control port")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the control process in the foreground")
    serve.set_defaults(func=cmd_serve)

    sub.add_parser("ping", help="check that the control process is alive").set_defaults(
        func=lambda a: _run(a, Operation.PING)
    )
    sub.add_parser("status", help="report control process state").set_defaults(
        func=lambda a: _run(a, Operation.STATUS)
    )
    sub.add_parser("inspect", help="detailed state, counters and event summary").set_defaults(
        func=lambda a: _run(a, Operation.INSPECT)
    )
    sub.add_parser("pause", help="pause the experiment").set_defaults(
        func=lambda a: _run(a, Operation.PAUSE)
    )
    sub.add_parser("resume", help="resume the experiment").set_defaults(
        func=lambda a: _run(a, Operation.RESUME)
    )

    snapshot = sub.add_parser(
        "snapshot", help="write a state snapshot anchored in the signed ledger"
    )
    snapshot.add_argument("--label", default=None, help="human-readable label")
    snapshot.set_defaults(func=lambda a: _run(a, Operation.SNAPSHOT, label=a.label))

    sub.add_parser("shutdown", help="shut the control process down").set_defaults(
        func=lambda a: _run(a, Operation.SHUTDOWN)
    )

    wait = sub.add_parser("wait", help="block until the control process answers")
    wait.add_argument("--attempts", type=int, default=20)
    wait.set_defaults(func=cmd_wait)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130
    except BabyLabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
