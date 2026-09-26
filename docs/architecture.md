# Architecture

## What this repository is

A research laboratory for observing a self-hosted AI system. Milestone 001
delivers the **instrumentation only**: the event log, the provenance ledger, the
read-only observer, the separated control process, and the tests that prove they
work.

## What this repository is not

It is not an AI. There is no model, no agent loop, no planner, no memory
retrieval, no goal generation, and no self-modification. None of those belong to
Milestone 001, and the absence is deliberate rather than incidental.

The reason is methodological. Everything in this project is an *observation
instrument*. An instrument that also contains the thing it measures cannot be
trusted to report on it: every convenience built into the harness is a
confounder in the first real experiment. So the laboratory has no simulated
subject, no mock subject, and no "placeholder agent" either. When the control
plane is asked to `PAUSE`, it reports honestly that nothing is attached:

> No experimental subject is attached in Milestone 001. This operation changed
> the control process's own state only. No simulated behaviour was produced.

Fabricating a subject later would contaminate the first observations of the real
experiment, which is the one thing this project exists to avoid.

## Component map

```
                     ┌───────────────────────────────────────────┐
                     │            human_control/                  │
                     │  experiment_config/  baseline/  records/   │
                     │  provenance/seals/   security/keys/        │
                     │  snapshots/                               │
                     └───────────────────▲───────────────────────┘
                                         │ read-only, signed
        ┌────────────────┐               │               ┌────────────────┐
        │    observer    │───────────────┼───────────────│    control     │
        │  read-only     │   var/events/ │               │  separate proc │
        │  terminal view │   events.jsonl│               │  loopback TCP  │
        └────────────────┘               │               │  HMAC auth     │
                                         │               └───────┬────────┘
                                         ▼                       │
                                  ┌────────────────┐              │
                                  │  babylab/      │◄─────────────┘
                                  │  storage/hash  │
                                  │  trust/paths   │
                                  │  identity/keys │
                                  └────────────────┘
```

### `babylab/` — shared foundations

| Module | Responsibility |
| --- | --- |
| `paths.py` | The canonical layout. Every path in the project resolves through here. |
| `errors.py` | A small error hierarchy, so callers can distinguish refusal from failure. |
| `hashing.py` | Canonical JSON, SHA-256 digests, HMAC-SHA256, chain links. |
| `clock.py` | UTC timestamps with millisecond precision, injectable for tests. |
| `storage.py` | Atomic writes, cross-process file locks, append-only line writes. |
| `identity.py` | The role vocabulary: `HUMAN`, `SYSTEM`, `BABY_AI`. |
| `trust.py` | `PathPolicy`: the application-level write boundary. |
| `bootstrap.py` | Idempotent laboratory initialisation. |

### `events/` — what happened

An append-only JSON Lines log where every event is hash-chained to its
predecessor. Arbitrary namespaces are permitted: the laboratory does not impose
a curriculum on what a future subject is allowed to say about itself. See
[provenance-model.md](provenance-model.md) and `docs/decisions/ADR-004`.

### `provenance/` — who did it, and can we prove it

A second append-only JSON Lines log, hash-chained *and* HMAC-signed, where
authorship is derived from a key ID looked up in a keyring rather than trusted
from the caller. Key possession is the claim; the ledger is the evidence.

### `observer/` — the only thing a human watches

A read-only terminal renderer. It cannot append to the log, holds no signing
key, and is the only component whose output a researcher is expected to read.

### `control/` — the privileged process

A separate process with a documented lifecycle state machine, reached over
loopback TCP with HMAC-SHA256 request authentication. It owns the lab's
lifecycle and takes state snapshots. It does not own a subject, because there
is none.

## Trust boundaries

Three tiers, described in full in [security-model.md](security-model.md):

1. **Application policy** — always active, catches accidents, bypassable by a
   subject sharing the OS user.
2. **OS file permissions** — scriptable, not active by default, needs an
   elevated session and a second account.
3. **OS account isolation / containers** — not implemented.

The honest summary is that **only tier 1 is in force**, and tier 1 is the
weakest of the three. That is recorded in the completion report rather than
papered over.

## Data placement

Runtime data lives under `var/`, not next to the code:

| Path | Contents |
| --- | --- |
| `var/events/events.jsonl` | The event log. |
| `var/provenance/ledger.jsonl` | The signed provenance ledger. |

This split exists because a research project will eventually generate a lot of
data, and keeping it out of the source tree removes an entire class of accident
(code overwriting data, backups capturing both, `.gitignore` hiding something
important). It is also why the code directories can stay pure: importing
`events` must never be able to mutate `human_control/`.

## Extension points

Deliberately narrow, so that Milestone 002 has an obvious and honest place to
start:

- A subject implements the role `BABY_AI` and gets its own key from the keyring.
- Anything a subject does goes through `EventStore.append`.
- Anything a subject writes into `human_control/` goes through `ProvenanceRecorder`.
- Any privileged action goes through the control protocol.
- Anything a human wants to see goes through the observer.
