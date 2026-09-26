# Control protocol

## Purpose

The control plane is the laboratory's privileged process: it owns the
laboratory's lifecycle, it is the only component allowed to take state
snapshots, and it emits an event for everything it does.

It is a **separate process** on purpose. A control surface that shares an
address space with the thing it controls cannot be used to stop that thing.

## What it does not do

It does not manage a subject, because there is none. `PAUSE` and `RESUME` act
on the control process's own lifecycle state and say so:

> No experimental subject is attached in Milestone 001. This operation changed
> the control process's own state only. No simulated behaviour was produced.

## Transport

| | |
| --- | --- |
| Address | `127.0.0.1` only. Never a remote interface. |
| Framing | One JSON object per line, UTF-8, `\n` terminated. |
| Max frame | 64 KiB. Larger frames are refused without being parsed. |
| Timeout | 5 s per request, so a wedged server cannot hang an operator. |

## Request authentication

Every request carries a tag over the shared token from
`human_control/security/control.token`:

```
auth = HMAC_SHA256(token, canonical_json({
    "protocol": "babylab/control/v1",
    "op":       "snapshot",
    "nonce":    "<32 fresh hex characters>",
    "args":     {"label": "before-run"}
}))
```

The token never crosses the wire; only the tag does.

The tag covers the operation, the nonce, **and** the arguments, which is what
stops an authorisation for one action being replayed as another:

| Replay attempt | Result |
| --- | --- |
| `ping` tag reused for `shutdown` | rejected, `args` and `op` both differ |
| `snapshot` tag reused with a different label | rejected, `args` differ |
| Same request sent twice | **accepted** — see below |

There is no seen-nonce cache, so a captured request can be replayed within the
token's lifetime. For a loopback-only, single-operator control plane this is an
accepted limitation, and it is listed in
[security-model.md](security-model.md#residual-risks-enumerated) rather than
omitted.

## Operations

| Operation | Effect |
| --- | --- |
| `ping` | Liveness. Returns `{"pong": true}`. |
| `status` | Current state, subject-attached flag, uptime, counters. |
| `inspect` | `status` plus event-store summary, key IDs, and resolved paths. |
| `pause` | `RUNNING` → `PAUSED`. Reports that no subject is attached. |
| `resume` | `PAUSED` → `RUNNING`. |
| `snapshot` | Writes a state snapshot into `human_control/snapshots/`, anchors its digest in the signed ledger under the `SYSTEM` key, emits `control.snapshot.taken`. |
| `shutdown` | Graceful: `RUNNING` → `SHUTTING_DOWN` → `SHUTDOWN`, then the listener closes. |

## Lifecycle state machine

```
                 start()
   STOPPED ──────────────────────► STARTING ──► RUNNING ──┬──► PAUSED
      ▲                                                   │      │
      │                                          pause()   │      │ resume()
      │                                                   ▼      │
      └────────────────── STOPPED ◄── stop() ────── SHUTTING_DOWN ◄──┘
                                    │                  │
                                    │                  │ shutdown()
                                    ▼                  ▼
                                 STOPPED            SHUTDOWN
```

Transitions are enforced by a table, not by scattered `if` statements, and the
table is tested directly in
`tests/test_control.py::ProtocolTests::test_illegal_transitions_are_refused_by_the_guard`
— every state/target pair is exercised, and every illegal one must raise.

`RUNNING` cannot jump straight to `SHUTDOWN`; it must pass through
`SHUTTING_DOWN` so that the shutdown is observable in the event log rather than
being a socket close with no explanation.

## Response

```json
{
  "protocol": "babylab/control/v1",
  "ok": true,
  "nonce": "<echoed from the request>",
  "result": { "state": "RUNNING", "subject_attached": false },
  "error": null,
  "error_code": null
}
```

An authorisation failure is **not** an exception at the client: it comes back
as `ok: false` with `error_code: "UNAUTHORIZED"`, because "you are not allowed"
is an answer, not a malfunction. A connection failure *is* an exception, because
silently returning a fabricated success would be worse than crashing.

| `error_code` | Meaning |
| --- | --- |
| `UNAUTHORIZED` | Missing, malformed, or wrong tag. Recorded as a security event. |
| `MALFORMED` | Frame was not a valid request object. |
| `FRAME_TOO_LARGE` | Frame exceeded the size limit; not parsed. |
| `BAD_PROTOCOL` | Protocol string mismatch. |
| `UNKNOWN_OP` | Operation not in the vocabulary. |
| `ILLEGAL_STATE` | The operation is not valid from the current state. |
| `INTERNAL` | Unexpected server-side failure. |

## Authorship

The control process signs its provenance entries with the `SYSTEM` key, never
the `HUMAN` key. `tests/test_control.py` asserts this, because a control plane
that could forge the operator's signature would make the entire provenance
ledger worthless.

## CLI

```powershell
# server
python -m control.cli serve
python -m control.cli serve --port 8765

# client
python -m control.cli ping
python -m control.cli status
python -m control.cli inspect
python -m control.cli pause
python -m control.cli resume
python -m control.cli snapshot --label before-run
python -m control.cli shutdown
python -m control.cli wait

# machine-readable
python -m control.cli --json status
```

If the token file is missing or corrupt, `serve` **refuses to start**. There is
no unauthenticated mode.

## Snapshot labels

An operator-supplied `--label` reaches the filesystem, so it is reduced to a safe
filename component (`[A-Za-z0-9_-]`, 48 characters) and the resolved path is
checked for containment inside `human_control/snapshots/`. Both layers exist
because "authenticated" is not "trusted": a compromised client should not be
able to steer a write outside the protected area with `..` or a path separator.

The original label is preserved as `requested_label` in the snapshot body, so
sanitising the filename never erases what the operator actually asked for.
