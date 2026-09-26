"""Control-plane client.

Only a process that can read ``human_control/security/control.token`` can
construct an authorised client. That is the whole authorisation model in
Milestone 001, and its limitation is stated in docs/security-model.md.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

from babylab.errors import BabyLabError, ValidationError
from babylab.paths import ProjectPaths, default_paths
from control.protocol import Operation, Request, Response, build_request
from control.server import load_config, load_token


class ControlClient:
    """Synchronous control-plane client, one connection per request.

    Deliberately not persistent: an operation is a discrete human decision, and
    a short-lived connection removes a class of ordering and staleness bugs
    that a long-lived session would introduce.
    """

    def __init__(
        self,
        paths: ProjectPaths | None = None,
        host: str | None = None,
        port: int | None = None,
        token: bytes | None = None,
        timeout: float = 10.0,
    ):
        self.paths = paths or default_paths()
        config = load_config(self.paths)
        self.host = host or config.get("host", "127.0.0.1")
        self.port = int(port if port is not None else config.get("port", 0))
        self._token = token
        self.timeout = timeout

    @property
    def token(self) -> bytes:
        if self._token is None:
            self._token = load_token(self.paths.control_token)
        return self._token

    def call(self, op: Operation, args: dict | None = None) -> Response:
        """Send one authenticated request and return the response.

        A connection failure raises; an authorisation failure returns a
        ``Response`` with ``ok=False``. That distinction matters: a refused
        request is data, a dead server is an error.
        """
        request = build_request(op, self.token, args)
        return self.send(request)

    def send(self, request: Request) -> Response:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                conn.settimeout(self.timeout)
                conn.sendall((request.to_json() + "\n").encode("utf-8"))
                buffer = b""
                while b"\n" not in buffer:
                    chunk = conn.recv(4096)
                    if not chunk:
                        raise BabyLabError(
                            f"control server at {self.host}:{self.port} closed the "
                            f"connection without responding"
                        )
                    buffer += chunk
                line, _ = buffer.split(b"\n", 1)
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            raise BabyLabError(
                f"cannot reach the control process at {self.host}:{self.port}: {exc}. "
                f"Is it running? Start it with 'python -m control.cli serve'."
            ) from exc
        return Response.from_json(line.decode("utf-8", errors="replace"))

    # -- convenience wrappers --------------------------------------------
    def ping(self) -> Response:
        return self.call(Operation.PING)

    def status(self) -> Response:
        return self.call(Operation.STATUS)

    def inspect(self, include: str | None = None) -> Response:
        return self.call(Operation.INSPECT, {"include": include} if include else None)

    def pause(self) -> Response:
        return self.call(Operation.PAUSE)

    def resume(self) -> Response:
        return self.call(Operation.RESUME)

    def snapshot(self, label: str | None = None) -> Response:
        return self.call(Operation.SNAPSHOT, {"label": label} if label else None)

    def shutdown(self) -> Response:
        return self.call(Operation.SHUTDOWN)

    def wait_for_server(self, attempts: int = 20, delay: float = 0.25) -> bool:
        """Poll until the server answers, or give up.

        Used by ``control.cli wait`` so that a script can start the server and
        then immediately issue a command without a race.
        """
        for _ in range(attempts):
            try:
                if self.ping().ok:
                    return True
            except BabyLabError:
                pass
            time.sleep(delay)
        return False

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ControlClient({self.host}:{self.port})"
