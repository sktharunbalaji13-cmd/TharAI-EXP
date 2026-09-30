# Architecture

## What this repository is

A research laboratory for observing a self-hosted AI system. It is built in
milestones, each adding one layer and proving it:

| Milestone | Delivers |
| --- | --- |
| 001 | Instrumentation: event log, provenance ledger, read-only observer, separated control process |
| 002 | The read-only Cognitive State Observatory |
| 003 | The birth ceremony, model identity verification, and a truthful display |
| 004 | The trust boundary, measured instead of asserted |
| 005 | The OS boundary, applied and verified by human cross-process execution |
| 006 | The runtime layer — model/runtime contracts, hardware probe, governor, adapter |
| 007 | The environment and interaction substrate — deterministic actions and consequences |
| 008 | The subject architecture and the first-experience boundary |
| 009 | The birth ceremony as a gated, auditable transition, plus first controlled experience |

The layers added by 006–009 are **contracts and machinery**. None of them has a
model behind it.

## What this repository is not

It is not an AI. There is no model, no agent loop, no planner, no memory
retrieval, no goal generation, no training, and no self-modification.

Each milestone above is a point where that sentence could easily have stopped
being true, and each was handled the same way: the ability to create a subject
was built, the substrate to run one was built, the gate that decides whether to
create one was built — and the thing itself is still absent. Concretely, on this
machine right now:

```
foundation model     none configured
weights              none on disk
runtime binary       none
BABY_AI key          not created
birth record         absent
subject              none attached
autonomous process   none running
```

The `M009` result is the clearest expression of this. A complete birth ceremony
exists, with a fourteen-prerequisite gate, staged transitions, an immutable
`T_birth`, explicit key custody, and a machine-readable audit. It was run, and
the gate **blocked** on `MODEL_NOT_CONFIGURED`. The laboratory ends with no
subject. Reporting that as a completed birth would have been the easy mistake
and the only dishonest one available.

The absence is deliberate rather than incidental.

The reason is methodological. Everything in this project is an *observation
instrument*. An instrument that also contains the thing it measures cannot be
trusted to report on it: every convenience built into the harness is a
confounder in the first real experiment. So the laboratory has no simulated
subject, no mock subject, and no "placeholder agent" either. When the control
plane is asked to `PAUSE`, it reports honestly that nothing is attached:

> No experimental subject is attached in Milestone 001. This operation changed
> the control process's own state only. No simulated behaviour was produced.

The claim in that message is still true at Milestone 009. The milestone number
in the string is not: `control/server.py` still says `Milestone 001`, and the
test suite asserts only the `No experimental subject` substring rather than the
version. Recorded here as a known stale string in program output rather than
quietly edited, because changing what the control process says is a behaviour
change and not a documentation change.

Fabricating a subject later would contaminate the first observations of the real
experiment, which is the one thing this project exists to avoid.

This is also why `SIMULATED` mode exists as a distinct, loudly labelled value
rather than a flag that can be left on. A simulated run carries
`NOT_A_BIRTH` in its own completion event, and its record can never report
`REAL_BIRTH`. A mode string that could be forgotten is not a safety property.

The same reasoning governs tests. The suite can produce a successful birth, but
it may not produce a *fake* one that looks real: test weights are real bytes
with their real digest, and the runtime is injected as a call argument rather
than configured, so no sealed artefact ever describes a test double as a real
substrate. See [birth-architecture.md](birth-architecture.md).

## Component map

```
                   ┌───────────────────────────────────────────────┐
                   │              human_control/                   │
                   │  experiment_config/  baseline/  records/      │
                   │  provenance/seals/   security/keys/           │
                   │  snapshots/          birth_records/           │
                   └───────────────────▲───────────────────────────┘
                                       │ read-only, signed
      ┌────────────────┐              │              ┌────────────────┐
      │    observer    │──────────────┼──────────────│    control     │
      │  read-only     │  var/events/ │              │  separate proc │
      │  terminal view │  events.jsonl│              │  loopback TCP  │
      └────────────────┘              │              │  HMAC auth     │
                                     ▼              └───────┬────────┘
                              ┌────────────────┐            │
                              │  babylab/      │◄───────────┘
                              │  storage/hash  │
                              │  trust/paths   │
                              │  identity/keys │
                              │  osboundary/   │
                              │  runtime/      │
                              └───────┬────────┘
                                      │
   ┌─────────────────┐       ┌────────┴────────┐       ┌──────────────────┐
   │  observatory    │───────│     birth/     │───────│  control plane   │
   │  read-only      │ reads │  status.py     │ runs  │  pause / resume  │
   │  cognitive      │ status│  (no writes)   │       │  / terminate     │
   │  state + birth  │       │  gate.py       │       └──────────────────┘
   └─────────────────┘       │  ceremony.py   │
                             │  audit.py      │
                             └────────┬───────┘
                                      │ appends
                                      ▼
                          var/events/events.jsonl

   Milestones 006-009, all currently inert — no model, no subject:
   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │  babylab/runtime │   │    environment/  │   │     subject/     │
   │  contracts,      │──▶│  actions,        │◀──│  identity,       │
   │  probe, governor │   │  consequences,   │   │  lifecycle,      │
   │  adapter         │   │  state, replay   │   │  state, harness  │
   └──────────────────┘   └─────────┬────────┘   └──────────────────┘
                                     │ first experience, gated
                                     ▼
                            ┌──────────────────┐
                            │  subject/        │
                            │  experience.py   │
                            │  interface.py    │
                            └──────────────────┘
```

The `birth/` split is load-bearing, not cosmetic. The Observatory must display
whether a subject exists, and the function that knows is the ceremony — which
holds the event store's append path. Importing the ceremony for a read would
hand a read-only component the ability to write. So `birth/status.py` holds
every read, `birth/service.py` holds every write, and
`tests/test_observatory_security.py::ObservatoryImportClosureTests` walks the
import graph to confirm no write-capable module is reachable from the
Observatory.

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
| `osboundary.py` | Tier-2 boundary definition, ACL measurement, evidence integrity. |
| `isolation.py` | The Milestone-004 re-runnable trust-boundary measurement. |
| `bootstrap.py` | Idempotent laboratory initialisation. |
| `runtime/` | The Milestone-006 runtime layer — see below. |

### `babylab/runtime/` — the substrate contract (Milestone 006)

Everything needed to *describe and probe* a model runtime, with nothing running.
`contract.py` holds the typed declarations; `registry.py` the capability
registry in which every capability is `UNAVAILABLE`; `hardware.py` the hardware
probe; `governor.py` the resource governor; `llamacpp_adapter.py` the llama.cpp
adapter behind an interface that is not installed; `provenance.py` and
`telemetry.py` the observability around it; `runtime.py` the facade.

The adapter is written against a real llama.cpp ABI, and the hardware probe
reports what is actually present on the host — an RTX 4060 Laptop GPU with
8188 MiB VRAM, a Ryzen 7 7840HS, 16 logical cores, 15.29 GiB RAM. None of that
makes a model available. Observed hardware is a fact about the machine, not
evidence of a subject.

### `environment/` — the interaction substrate (Milestone 007)

`environment/` is the world a subject would act on and the record of what
followed. `action.py` and `consequence.py` define typed actions and their
outcomes; `environment.py` validates and applies them; `state.py` holds the
authoritative environment state; `snapshot.py` makes it replayable;
`deterministic.py` produces identical runs from a seed; `events.py` appends the
eleven event types that record what happened.

Two properties are load-bearing. Actions are **validated before they are
applied**, with four distinguishable outcomes rather than a boolean, so a
rejected action is recorded as rejected instead of vanishing. And **timestamps
are metadata, never state** — including them in the state hash would make replay
impossible, which is the same rule that lets the M009 replay comparison be
meaningful.

### `subject/` — the subject architecture (Milestone 008)

The description of a subject, with no subject present. `identity.py` issues
identities; `lifecycle.py` holds the explicit `UNCREATED → CREATED → ATTACHED →
ACTIVE` state machine; `state.py` the hash-chained subject state;
`creation.py` the creation record; `provenance.py` the identity/provenance
distinction; `experience.py` the first-experience boundary; `interface.py` the
proposal surface; `harness.py` in-memory test subjects; `telemetry.py` the
report.

The interface is deliberately thin: a subject *proposes* an action, the
environment *disposes* it, and the subject cannot apply anything to itself. There
is no agent loop anywhere in the package — the actor of every call is the
laboratory, which is why nothing runs on its own. `harness.py` creates test
subjects that exist only in memory and can never be mistaken for a born one.

### `birth/gate.py`, `birth/gate_checks.py` — the decision to create (Milestone 009)

The gate is separated from the ceremony so that the decision to create a subject
is a distinct, testable object rather than an early `if` inside the code that
creates one. Fourteen prerequisites — model runtime, artifact identity, artifact
digest, runtime verification, subject identity capability, key custody,
environment availability, environment version, interface availability,
provenance, protected evidence, M005 isolation status, Observatory, and
configuration integrity — each evaluated against **live machine state**, each
returning `PASS`, `FAIL`, or `UNKNOWN`.

Three rules make it a gate rather than a report:

1. `UNKNOWN` never becomes `PASS`. An unknowable prerequisite blocks.
2. Absence is `FAIL`, not `UNKNOWN`. "No model configured" is an observed fact,
   not a gap in knowledge.
3. A check that raises blocks, rather than passing by omission.

Every check always runs, so one evaluation shows all fourteen answers instead of
stopping at the first failure and hiding the rest. Security checks re-inspect the
filesystem rather than reading a previous milestone's evidence file, and a check
that would need a side effect states what it checked instead of performing it.

### `birth/ceremony.py` — the staged transition (Milestone 009)

Preflight → gate → identity → creation → pre-birth proof → foundation →
environment → `T_birth` → `CREATED` → `ATTACHED` → `ACTIVE` → first observation →
proposal → consequence → first experience. Each step records an event. Any
failure aborts *there*, preserves everything gathered, terminates the record, and
fabricates nothing downstream — there is no code path past a failure, so partial
birth cannot present as success.

`T_birth` is one immutable record naming subject, foundation, environment,
ceremony, and mode. Before it, the subject has **zero** experiences, which is
asserted in a `pre_birth_proof` event rather than merely being true by default.
`birth/keycustody.py` decides custody explicitly (`NOT_REQUIRED` here, with
reasons) and refuses to provision a key as a side effect. `birth/control.py`
provides laboratory-only pause/resume/terminate, where termination is permanent
but deletes nothing. `birth/audit.py` answers sixteen questions by re-deriving
them from the record, and `replay_ceremony` replays the recorded first action
against a fresh deterministic environment to compare hashes.

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

### `birth/` — the only thing that creates a subject

Two halves with an enforced direction of dependency. `birth/status.py` is
read-only and reaches no write path; `birth/service.py` holds the ceremony, the
event append, the single record write, and the signed `CREATE` provenance entry.
The model is identified by SHA-256 against an explicitly written configuration,
and the laboratory never chooses one. See
[birth-architecture.md](birth-architecture.md).

### `control/` — the privileged process

A separate process with a documented lifecycle state machine, reached over
loopback TCP with HMAC-SHA256 request authentication. It owns the lab's
lifecycle and takes state snapshots. It does not own a subject, because there
is none.

## Trust boundaries

Three tiers, described in full in [security-model.md](security-model.md):

1. **Application policy** — always active, catches accidents, bypassable by a
   subject sharing the OS user.
2. **OS file permissions** — **applied and verified.** The account
   `THARUNBALAJI-LA\BABY_AI_TEST` (non-administrator, Medium integrity) is denied
   11 protected paths and holds no ACE on either subject workspace, proven by
   human cross-process execution in
   `docs/evidence/m005-final-verification.json`.
3. **OS account isolation / containers** — not implemented. `BABY_AI_TEST` is a
   permissions stand-in, not an execution isolation boundary.

The honest summary is that **tiers 1 and 2 are in force and tier 3 is not**, and
tier 2 has a documented residual hole: a root-level `FILE_DELETE_CHILD`
capability on the private key directory's parent is not denied by an explicit
ACE. Both are recorded in [security-model.md](security-model.md) rather than
papered over, and both are consequences of tier 3 not existing.

## Data placement

Runtime data lives under `var/`, not next to the code:

| Path | Contents |
| --- | --- |
| `var/events/events.jsonl` | The event log. |
| `var/provenance/ledger.jsonl` | The signed provenance ledger. |
| `var/models/` | Model artifacts, if any were ever configured. Currently empty. |
| `var/measurements/` | Runtime and hardware measurement artifacts. |

This split exists because a research project will eventually generate a lot of
data, and keeping it out of the source tree removes an entire class of accident
(code overwriting data, backups capturing both, `.gitignore` hiding something
important). It is also why the code directories can stay pure: importing
`events` must never be able to mutate `human_control/`.

## Extension points

Deliberately narrow, so that each milestone has an obvious and honest place to
start:

- A subject implements the role `BABY_AI` and gets its own key from the keyring.
- Anything a subject does goes through `EventStore.append`.
- Anything a subject writes into `human_control/` goes through `ProvenanceRecorder`.
- Any privileged action goes through the control protocol.
- Anything a human wants to see goes through the observer.
- Anything a subject could act on goes through `environment/`, never directly.
- Whether a subject may exist at all is decided by `birth/gate.py`, never by the
  ceremony's own code path.

The last point is the one added by Milestone 009, and it is the most important
extension point in the repository: the gate is the only component permitted to
answer "may a subject be created", and it answers `NO` whenever it cannot
establish the prerequisites rather than defaulting toward permission.
