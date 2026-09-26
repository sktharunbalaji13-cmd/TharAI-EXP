"""The control server: a separate, authenticated, privileged process.

Responsibilities in Milestone 001
---------------------------------
Own the laboratory's lifecycle state, authorise control requests, emit events
for everything it does, and take a signed snapshot on request.

Responsibilities it does NOT have
---------------------------------
It does not manage an agent, because no agent exists. ``PAUSE`` and ``RESUME``
therefore act on the control process's own state and report honestly that
nothing is attached to them. Inventing a fake subject here would contaminate
the first observations of the real experiment.
"""

from __future__ import annotations

import base64
import re
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from babylab.clock import Clock
from babylab.errors import AuthorizationError, BabyLabError, ValidationError
from babylab.hashing import canonical_json
from babylab.paths import ProjectPaths, default_paths
from babylab.trust import PathPolicy
from control.protocol import (
    PROTOCOL_VERSION,
    STATE_CHANGING,
    Operation,
    Request,
    Response,
    State,
    TRANSITIONS,
    verify_request,
)
from events.store import EventStore

#: Refuse absurd line lengths before allocating for them.
MAX_FRAME_BYTES = 64 * 1024

#: Requests per second, per connection, before the connection is dropped.
RATE_LIMIT_PER_SECOND = 50


def load_token(path: Path) -> bytes:
    """Read the shared authentication token from ``human_control/``.

    Raises rather than defaulting. A control plane with no authentication is
    worse than no control plane, so there is no "development mode" bypass.
    """
    token_path = Path(path)
    if not token_path.exists():
        raise AuthorizationError(
            f"control token not found at {token_path}. Run bootstrap first."
        )
    raw = token_path.read_text(encoding="ascii").strip()
    try:
        return base64.b64decode(raw)
    except Exception as exc:  # noqa: BLE001
        raise AuthorizationError(f"control token at {token_path} is malformed: {exc}") from exc


def load_config(paths: ProjectPaths) -> dict:
    if not paths.control_config.exists():
        return {"host": "127.0.0.1", "port": 0}
    import json

    return json.loads(paths.control_config.read_text(encoding="utf-8"))


@dataclass
class ServerStats:
    requests_total: int = 0
    requests_authorized: int = 0
    requests_rejected: int = 0
    connections_total: int = 0
    connections_rejected: int = 0
    by_operation: dict = field(default_factory=dict)

    def record(self, op: str, authorized: bool) -> None:
        self.requests_total += 1
        if authorized:
            self.requests_authorized += 1
            self.by_operation[op] = self.by_operation.get(op, 0) + 1
        else:
            self.requests_rejected += 1

    def to_dict(self) -> dict:
        return {
            "requests_total": self.requests_total,
            "requests_authorized": self.requests_authorized,
            "requests_rejected": self.requests_rejected,
            "connections_total": self.connections_total,
            "connections_rejected": self.connections_rejected,
            "by_operation": dict(sorted(self.by_operation.items())),
        }


class ControlServer:
    """Loopback TCP control plane with token authentication."""

    def __init__(
        self,
        paths: ProjectPaths | None = None,
        host: str | None = None,
        port: int | None = None,
        clock: Clock | None = None,
        store: EventStore | None = None,
    ):
        self.paths = paths or default_paths()
        self.clock = clock or Clock()
        config = load_config(self.paths)
        self.host = host or config.get("host", "127.0.0.1")
        self.port = int(port if port is not None else config.get("port", 0))
        self.token = load_token(self.paths.control_token)
        self.policy = PathPolicy(self.paths)
        self.store = store or EventStore(self.paths.event_store, clock=self.clock)
        self.state = State.STOPPED
        self.stats = ServerStats()
        self.started_at: str | None = None
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._handlers: dict[Operation, Callable[[Request], dict]] = {
            Operation.PING: self._op_ping,
            Operation.STATUS: self._op_status,
            Operation.INSPECT: self._op_inspect,
            Operation.PAUSE: self._op_pause,
            Operation.RESUME: self._op_resume,
            Operation.SNAPSHOT: self._op_snapshot,
            Operation.SHUTDOWN: self._op_shutdown,
        }

    # -- lifecycle --------------------------------------------------------
    def start(self) -> "ControlServer":
        if self._socket is not None:
            raise BabyLabError("control server is already started")
        self._transition(State.STARTING)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR is deliberately NOT set: a second control server on the
        # same port must fail loudly rather than silently steal the endpoint.
        sock.bind((self.host, self.port))
        sock.listen(8)
        sock.settimeout(0.25)
        self._socket = sock
        self.port = sock.getsockname()[1]
        self.started_at = self.clock.timestamp()
        self._transition(State.RUNNING)
        self._emit(
            "control.server.started",
            {
                "headline": "Control process started",
                "host": self.host,
                "port": self.port,
                "protocol": PROTOCOL_VERSION,
                "authentication": MAC_LABEL,
            },
        )
        self._thread = threading.Thread(
            target=self._serve, name="control-server", daemon=True
        )
        self._thread.start()
        return self

    def serve_forever(self) -> None:  # pragma: no cover - interactive
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        if self.state not in (State.STOPPED, State.SHUTDOWN):
            self._transition(State.STOPPED)
        self._emit("control.server.stopped", {"headline": "Control process stopped"})

    def __enter__(self) -> "ControlServer":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # -- request handling -------------------------------------------------
    def handle_request(self, request: Request) -> Response:
        """Authorise and execute one request.

        Exposed separately from the socket loop so the test suite can exercise
        authorisation without opening a port.
        """
        authorized = verify_request(self.token, request)
        with self._lock:
            self.stats.record(request.op.value, authorized)
        if not authorized:
            # Recorded as a security event: unauthorised control attempts are
            # exactly the kind of thing a later reader of this experiment
            # needs to be able to find.
            self._emit(
                "security.control.request_rejected",
                {
                    "headline": "Unauthorised control request rejected",
                    "operation": request.op.value,
                    "reason": "authentication tag missing or invalid",
                },
            )
            return Response(
                ok=False,
                nonce=request.nonce,
                op=request.op.value,
                error=(
                    "unauthorised: the request carried no valid authentication tag. "
                    "This attempt has been recorded as a security event."
                ),
                error_code="UNAUTHORIZED",
                server_state=self.state.value,
            )

        if request.protocol != PROTOCOL_VERSION:
            return Response(
                ok=False,
                nonce=request.nonce,
                op=request.op.value,
                error=f"unsupported protocol {request.protocol!r}; expected {PROTOCOL_VERSION}",
                error_code="BAD_PROTOCOL",
                server_state=self.state.value,
            )

        handler = self._handlers.get(request.op)
        if handler is None:  # pragma: no cover - Request validation prevents this
            return Response(
                ok=False,
                nonce=request.nonce,
                op=request.op.value,
                error=f"operation {request.op} is not implemented",
                error_code="NOT_IMPLEMENTED",
                server_state=self.state.value,
            )
        try:
            result = handler(request)
        except BabyLabError as exc:
            return Response(
                ok=False,
                nonce=request.nonce,
                op=request.op.value,
                error=str(exc),
                error_code=type(exc).__name__,
                server_state=self.state.value,
            )
        return Response(
            ok=True, nonce=request.nonce, op=request.op.value, result=result,
            server_state=self.state.value,
        )

    # -- operations -------------------------------------------------------
    def _op_ping(self, request: Request) -> dict:
        return {"pong": True, "server_time": self.clock.timestamp()}

    def _op_status(self, request: Request) -> dict:
        return {
            "state": self.state.value,
            "started_at": self.started_at,
            "host": self.host,
            "port": self.port,
            "subject_attached": False,
            "uptime_note": "no subject process is supervised in Milestone 001",
        }

    def _op_inspect(self, request: Request) -> dict:
        requested = request.args.get("include")
        event_summary = self.store.summary()
        payload = {
            "state": self.state.value,
            "server": self.stats.to_dict(),
            "events": event_summary,
            "paths": {
                "root": str(self.paths.root),
                "event_store": self.paths.relative(self.paths.event_store),
                "provenance_ledger": self.paths.relative(self.paths.provenance_ledger),
                "human_control": self.paths.relative(self.paths.human_control),
                "baby_workspace": self.paths.relative(self.paths.baby_workspace),
            },
            "subject_attached": False,
        }
        if requested in (None, "provenance"):
            try:
                ledger = self._provenance_ledger()
                payload["provenance"] = ledger.summary()
            except BabyLabError as exc:
                payload["provenance"] = {"error": str(exc)}
        return payload

    def _op_pause(self, request: Request) -> dict:
        self._transition(State.PAUSED)
        self._emit(
            "control.paused",
            {
                "headline": "Control process paused",
                "note": NO_SUBJECT_NOTE,
                "requested_by": "authenticated control client",
            },
        )
        return {
            "state": self.state.value,
            "subject_attached": False,
            "note": NO_SUBJECT_NOTE,
        }

    def _op_resume(self, request: Request) -> dict:
        self._transition(State.RUNNING)
        self._emit(
            "control.resumed",
            {
                "headline": "Control process resumed",
                "note": NO_SUBJECT_NOTE,
            },
        )
        return {
            "state": self.state.value,
            "subject_attached": False,
            "note": NO_SUBJECT_NOTE,
        }

    def _op_snapshot(self, request: Request) -> dict:
        """Write a state snapshot into human_control/ and anchor it in the ledger.

        The snapshot is a *record of laboratory state*, not a copy of the
        subject's memory. Nothing in Milestone 001 is a subject, so there is
        nothing else it could be.

        Authorship matters: the snapshot body is not itself signed, but its
        SHA-256 digest is written into the HMAC-signed provenance ledger by the
        SYSTEM key. Altering the file afterwards breaks that anchor, which
        ``provenance.cli verify`` detects. See docs/security-model.md.
        """
        requested = request.args.get("label") or uuid.uuid4().hex[:8]
        label = _safe_label(requested)
        stamp = _filename_stamp(self.clock.timestamp())
        target = self.paths.snapshots / f"snapshot-{stamp}-{label}.json"
        # Defence in depth: the sanitised label should already prevent escape,
        # but the write goes straight to disk, so containment is checked too.
        _require_contained(self.paths.snapshots, target)
        body = {
            "schema": "babylab/snapshot/v1",
            "label": label,
            "requested_label": requested if isinstance(requested, str) else None,
            "taken_at": self.clock.timestamp(),
            "control_state": self.state.value,
            "subject_attached": False,
            "event_store": self.store.summary(),
            "server": self.stats.to_dict(),
            "note": NO_SUBJECT_NOTE,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        from babylab.storage import atomic_write_text

        atomic_write_text(target, canonical_json(body) + "\n")
        self._record_snapshot_in_provenance(target, label)
        self._emit(
            "control.snapshot.taken",
            {
                "headline": "Snapshot taken",
                "path": self.paths.relative(target),
                "label": label,
            },
        )
        return {
            "path": self.paths.relative(target),
            "absolute_path": str(target),
            "label": label,
        }

    def _record_snapshot_in_provenance(self, target: Path, label: str) -> None:
        """Sign the snapshot with the SYSTEM key.

        The control process writes into ``human_control/`` but does not hold
        the human key. Recording its own artefacts under the SYSTEM role is
        what keeps "the infrastructure did this" distinguishable from "the
        researcher did this" in the ledger.

        A failure here is reported but does not fail the snapshot: losing the
        audit trail is bad, but refusing to honour an authenticated human
        request because the ledger hiccuped is worse, and the missing entry
        will be visible in ``provenance.cli verify``.
        """
        try:
            from babylab.identity import Role
            from provenance.keyring import Keyring
            from provenance.ledger import ProvenanceLedger
            from provenance.recorder import ProvenanceRecorder

            keyring = Keyring(self.paths.keyring, self.paths.private_key_dir, clock=self.clock)
            ledger = ProvenanceLedger(
                self.paths.provenance_ledger,
                keyring,
                clock=self.clock,
                seal_dir=self.paths.protected_provenance,
            )
            system_entry = keyring.key_for_role(Role.SYSTEM)
            recorder = ProvenanceRecorder(ledger, keyring, self.policy, clock=self.clock)
            recorder.record_creation(
                target,
                keyring.actor_of(system_entry.key_id),
                experiment_id="CONTROL-SNAPSHOT",
                reason=f"Control-plane snapshot labelled {label!r}, taken on authenticated request.",
                metadata={"control_state": self.state.value, "snapshot_label": label},
            )
        except Exception as exc:  # noqa: BLE001
            import sys

            print(
                f"control: WARNING snapshot {target.name} was not recorded in the "
                f"provenance ledger ({exc})",
                file=sys.stderr,
            )

    def _op_shutdown(self, request: Request) -> dict:
        self._transition(State.SHUTTING_DOWN)
        self._emit(
            "control.shutdown.requested",
            {
                "headline": "Control shutdown requested",
                "requested_by": "authenticated control client",
            },
        )
        self._transition(State.SHUTDOWN)
        self._stop.set()
        return {"state": self.state.value, "message": "control process is shutting down"}

    # -- internals --------------------------------------------------------
    def _transition(self, target: State) -> None:
        allowed = TRANSITIONS.get(self.state, frozenset())
        if target not in allowed:
            raise BabyLabError(
                f"illegal control state transition {self.state.value} -> {target.value}; "
                f"allowed: {sorted(item.value for item in allowed) or 'none'}"
            )
        self.state = target

    def _provenance_ledger(self):
        from provenance.keyring import Keyring
        from provenance.ledger import ProvenanceLedger

        keyring = Keyring(self.paths.keyring, self.paths.private_key_dir, clock=self.clock)
        return ProvenanceLedger(
            self.paths.provenance_ledger,
            keyring,
            clock=self.clock,
            seal_dir=self.paths.protected_provenance,
        )

    def _emit(self, event_type: str, payload: dict) -> None:
        try:
            self.store.append(event_type, "control.server", payload)
        except Exception:  # noqa: BLE001
            # The control plane must not die because the event log is
            # unavailable. It reports the failure loudly on stderr instead.
            import sys

            print(
                f"control: WARNING could not append event {event_type}",
                file=sys.stderr,
            )

    # -- socket loop ------------------------------------------------------
    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                conn, address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                self.stats.connections_total += 1
            threading.Thread(
                target=self._handle_connection,
                args=(conn, address),
                name="control-conn",
                daemon=True,
            ).start()

    def _handle_connection(self, conn: socket.socket, address) -> None:
        conn.settimeout(5.0)
        buffer = b""
        window_start = time.monotonic()
        window_count = 0
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > MAX_FRAME_BYTES:
                    self._send(
                        conn,
                        Response(
                            ok=False,
                            nonce="",
                            error="request frame too large",
                            error_code="FRAME_TOO_LARGE",
                            server_state=self.state.value,
                        ),
                    )
                    break
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    now = time.monotonic()
                    if now - window_start >= 1.0:
                        window_start, window_count = now, 0
                    window_count += 1
                    if window_count > RATE_LIMIT_PER_SECOND:
                        with self._lock:
                            self.stats.connections_rejected += 1
                        self._send(
                            conn,
                            Response(
                                ok=False,
                                nonce="",
                                error="rate limit exceeded; connection closed",
                                error_code="RATE_LIMITED",
                                server_state=self.state.value,
                            ),
                        )
                        self._emit(
                            "security.control.rate_limited",
                            {
                                "headline": "Control client rate limited",
                                "peer": f"{address[0]}:{address[1]}",
                            },
                        )
                        return

                    response = self._dispatch_line(line.decode("utf-8", errors="replace"))
                    self._send(conn, response)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _dispatch_line(self, text: str) -> Response:
        try:
            request = Request.from_json(text)
        except ValidationError as exc:
            return Response(
                ok=False,
                nonce="",
                error=str(exc),
                error_code="MALFORMED",
                server_state=self.state.value,
            )
        return self.handle_request(request)

    @staticmethod
    def _send(conn: socket.socket, response: Response) -> None:
        try:
            conn.sendall((response.to_json() + "\n").encode("utf-8"))
        except OSError:
            pass


MAC_LABEL = "hmac-sha256 request authentication over a shared 256-bit token"

NO_SUBJECT_NOTE = (
    "No experimental subject is attached in Milestone 001. This operation "
    "changed the control process's own state only. No simulated behaviour was "
    "produced."
)


def _filename_stamp(timestamp: str) -> str:
    """``2026-09-26T14:47:04.493Z`` -> ``20260926T144704Z``.

    Filenames must be safe on Windows, so the separators and the fractional
    seconds are removed. The full timestamp is still inside the snapshot body.
    """
    from babylab.clock import parse_timestamp

    moment = parse_timestamp(timestamp)
    return moment.strftime("%Y%m%dT%H%M%SZ")


#: Characters allowed in a snapshot label once it is used as a filename.
#: Deliberately strict: no separators, no dots that could form ``..``, no
#: characters Windows rejects or silently rewrites.
_LABEL_SAFE = re.compile(r"[^A-Za-z0-9_-]+")
_LABEL_MAX = 48


def _safe_label(requested: object) -> str:
    """Reduce an operator-supplied label to a safe filename component.

    The control plane is authenticated, but "authenticated" is not "trusted":
    a compromised or careless operator client must not be able to steer the
    write outside ``human_control/snapshots/`` with ``..`` or a path separator.
    A label that sanitises to nothing falls back to a random component, so the
    snapshot is still taken and the refusal is visible in the event log rather
    than turning into a silent failure.
    """
    if not isinstance(requested, str):
        return uuid.uuid4().hex[:8]
    cleaned = _LABEL_SAFE.sub("-", requested).strip("-_")
    if not cleaned:
        return uuid.uuid4().hex[:8]
    return cleaned[:_LABEL_MAX]


def _require_contained(parent: Path, target: Path) -> None:
    """Refuse to write outside ``parent`` even if a future bug lets one through."""
    parent_resolved = parent.resolve()
    target_resolved = target.resolve()
    if not target_resolved.is_relative_to(parent_resolved):
        raise ValidationError(
            f"refusing to write {target_resolved} outside {parent_resolved}"
        )
