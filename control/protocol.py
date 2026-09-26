"""Control-plane protocol: framing, authentication, and the operation registry.

Separation of privilege
-----------------------
The control process is a *different process* from anything the subject will
run. It holds the laboratory's authoritative lifecycle state, and it is the
only component permitted to pause, snapshot or shut the experiment down.

Transport
---------
A newline-delimited JSON request/response protocol over a loopback TCP socket.
Framing is one JSON object per line, which keeps the protocol debuggable with
nothing more than a terminal and ``netstat``.

Authentication
--------------
Every request must carry a 256-bit bearer token, compared in constant time.
The token lives in ``human_control/security/control.token``, which the future
subject must not be able to read. Possession of the token is what makes a
caller HUMAN_CONTROL; there is no per-role authorisation layer in Milestone
001 because there is exactly one authorised principal.

.. warning::
   A loopback socket is reachable by *every* process on the machine, including
   a future subject process. The token file's ACL is therefore the entire
   boundary. This is a known, documented weakness of the current design, not
   an oversight - see docs/security-model.md, section "Control Plane".

Why HMAC the request rather than send the token plainly
------------------------------------------------------
The token is sent as an HMAC tag over a client-chosen nonce plus the canonical
request body, keyed by the shared token. The token itself never crosses the
wire, so a passive capture of loopback traffic does not directly yield it. This
is obfuscation-grade, not confidentiality-grade: an attacker who can call the
socket can call ``sign``. It narrows the exposure, and the documentation says
so rather than claiming more.
"""

from __future__ import annotations

import hmac
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from babylab.hashing import MAC_ALGORITHM, canonical_bytes
from babylab.errors import AuthorizationError, ValidationError

PROTOCOL_VERSION = "babylab/control/v1"
MAX_LINE_BYTES = 64 * 1024


class Operation(str, Enum):
    """Privileged operations the control plane exposes.

    Milestone 001 implements every operation as *real* behaviour on real
    laboratory state. None of them simulates a subject. ``PAUSE`` and
    ``RESUME`` act on the control process's own supervised state, which
    currently has nothing attached to it, and they say so in their response
    rather than pretending otherwise.
    """

    PING = "ping"
    STATUS = "status"
    INSPECT = "inspect"
    PAUSE = "pause"
    RESUME = "resume"
    SNAPSHOT = "snapshot"
    SHUTDOWN = "shutdown"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: Operations that change state and therefore require an explicit
#: acknowledgement of their consequence by the caller.
STATE_CHANGING = frozenset(
    {Operation.PAUSE, Operation.RESUME, Operation.SNAPSHOT, Operation.SHUTDOWN}
)


class State(str, Enum):
    """Lifecycle state of the control process."""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    SHUTDOWN = "SHUTDOWN"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: Legal transitions. Encoding these as data rather than as scattered ``if``
#: statements means an illegal transition is impossible to express by mistake.
TRANSITIONS: dict[State, frozenset[State]] = {
    State.STOPPED: frozenset({State.STARTING}),
    State.STARTING: frozenset({State.RUNNING, State.STOPPED}),
    State.RUNNING: frozenset({State.PAUSED, State.SHUTTING_DOWN, State.STOPPED}),
    State.PAUSED: frozenset({State.RUNNING, State.SHUTTING_DOWN, State.STOPPED}),
    State.SHUTTING_DOWN: frozenset({State.SHUTDOWN, State.STOPPED}),
    State.SHUTDOWN: frozenset({State.STARTING}),
}


@dataclass(frozen=True)
class Request:
    """A control-plane request."""

    op: Operation
    nonce: str
    args: dict[str, Any] = field(default_factory=dict)
    auth: str = ""
    protocol: str = PROTOCOL_VERSION

    def body(self) -> dict[str, Any]:
        """The portion of the request covered by the authentication tag."""
        return {"op": self.op.value, "nonce": self.nonce, "args": self.args}

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "auth": self.auth, "protocol": self.protocol}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> "Request":
        if len(text.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValidationError("request exceeds the maximum frame size")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"request is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValidationError("request must be a JSON object")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Request":
        op_value = data.get("op")
        try:
            op = Operation(op_value)
        except ValueError as exc:
            raise ValidationError(
                f"unknown operation {op_value!r}; supported: "
                f"{', '.join(item.value for item in Operation)}"
            ) from exc
        args = data.get("args", {})
        if not isinstance(args, dict):
            raise ValidationError("args must be an object")
        return cls(
            op=op,
            nonce=str(data.get("nonce", "")),
            args=args,
            auth=str(data.get("auth", "")),
            protocol=str(data.get("protocol", PROTOCOL_VERSION)),
        )


@dataclass(frozen=True)
class Response:
    """A control-plane response."""

    ok: bool
    nonce: str
    op: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_code: str = ""
    server_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "nonce": self.nonce,
            "op": self.op,
            "result": self.result,
            "error": self.error,
            "error_code": self.error_code,
            "server_state": self.server_state,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> "Response":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"response is not valid JSON: {exc}") from exc
        return cls(
            ok=bool(data.get("ok")),
            nonce=str(data.get("nonce", "")),
            op=str(data.get("op", "")),
            result=data.get("result", {}) or {},
            error=str(data.get("error", "")),
            error_code=str(data.get("error_code", "")),
            server_state=str(data.get("server_state", "")),
        )


def sign_request(token: bytes, request_body: dict[str, Any]) -> str:
    """Compute the authentication tag for a request body."""
    return hmac.new(token, canonical_bytes(request_body), "sha256").hexdigest()


def verify_request(token: bytes, request: Request) -> bool:
    """Constant-time check of a request's authentication tag."""
    if not request.auth:
        return False
    expected = sign_request(token, request.body())
    return hmac.compare_digest(expected, request.auth)


def new_nonce() -> str:
    """A fresh nonce. Binds each tag to one request, blocking replay."""
    return uuid.uuid4().hex


def build_request(op: Operation, token: bytes, args: dict | None = None) -> Request:
    """Construct a signed request. The only correct way for a client to build one."""
    body = {"op": op.value, "nonce": new_nonce(), "args": args or {}}
    return Request(
        op=op,
        nonce=body["nonce"],
        args=body["args"],
        auth=sign_request(token, body),
    )


__all__ = [
    "PROTOCOL_VERSION",
    "MAC_ALGORITHM",
    "Operation",
    "State",
    "TRANSITIONS",
    "STATE_CHANGING",
    "Request",
    "Response",
    "sign_request",
    "verify_request",
    "new_nonce",
    "build_request",
    "AuthorizationError",
]
