# Cognitive State Observatory

**Status:** implemented, Milestone 002
**Last updated:** 2026-09-26

The Observatory is a read-only consumer of the canonical event log. It answers
one question — *what has the subject said about itself?* — and it is built so
that the honest answer is also the easy one.

Milestone 002 ships with **no subject**. `observatory.cli status` says
`NO EXPERIMENTAL SUBJECT ATTACHED` and that is the correct output, not a failure
state.

---

## 1. What this is

```
  var/events/events.jsonl          canonical, append-only, hash-chained
          |
          |  read only
          v
  ObservatoryReader                 incremental, offset-based, fault-tolerant
          |
          v
  Attributor                        who produced this record, and on what basis
          |
          v
  StateDeriver                      folds subject reports into state versions
          |
          v
  CognitiveState + StateGraph       the state, and the relationships reported
          |
          v
  ObservatorySnapshot               one serialisable object: the API
          |
          v
  ObservatoryRenderer               terminal now; a browser later
```

The event log is the source of truth. The Observatory holds derived state in
memory and writes nothing, anywhere, ever.

## 2. Commands

```bash
python -m observatory.cli status                  # one-shot summary
python -m observatory.cli state                   # one-shot state render
python -m observatory.cli live                    # follow, redrawing
python -m observatory.cli history                 # state transitions and causes
python -m observatory.cli --json state            # the API contract
python -m observatory.cli --detail state          # with source event IDs
```

Global flags: `--no-color`, `--detail`, `--json`, `--subject-namespace NS`
(repeatable), `--subject-label LABEL`.

The subject flags declare which event namespaces a real subject may write under.
They are configuration supplied by the human and are never inferred from events.

## 3. The four guarantees

### 3.1 An absence is never drawn as a value

This is the reason `observatory/model.py` refuses to construct a `StateValue`
with a status of `OBSERVED` or `DERIVED` and no value, and refuses an absence
status that carries one. The specification's example is the test case:

```
memory_activity: unavailable      <- correct
memory_activity: []               <- a lie
```

An empty list and an unreported list are different facts. Rendering the first as
the second would let a reader conclude *the subject checked its memory and found
nothing*, when the truth is *the subject never said anything about its memory*.

`CognitiveState.get()` returns a marked `StateValue`, never a raw `None`, so a
caller cannot accidentally treat a missing domain as a falsy value.

### 3.2 Every displayed value traces to an event

`StateValue.source_event_ids` is required for any claimed value and must be
empty for an absence. `StateTransition.cause_event_ids` must cite at least one
event — a change with no cause is not a change, it is a fabrication.
`ObservatorySnapshot.traceable_event_ids()` collects the IDs behind everything a
view can display, so "where did this number come from?" always has an answer.

### 3.3 Event provenance is not identity

`Event.source` is a component name. A future subject will be able to write
events, and therefore will be able to set `source` to anything, and to put
`{"author": "BABY_AI"}` in a payload. Neither is evidence of anything.

Subject identity comes from the human-owned keyring, or it does not exist. The
`Attributor` reports one of three kinds:

| Kind | Meaning |
|---|---|
| `INFRASTRUCTURE` | Came from a known laboratory namespace. Says what produced the record, not who is accountable. |
| `SUBJECT` | A namespace the human declared for a key-backed subject. |
| `UNATTRIBUTED` | Origin cannot be established. Named as unknown rather than assumed. |

### 3.4 It cannot change anything

`tests/test_observatory_security.py` asserts this two ways:

- **Behaviourally** — a full ingest leaves the event log and the provenance
  ledger byte-identical, adds no ledger entries, and creates no files.
- **Structurally** — an AST scan of the package finds no call to a mutating
  method on `store`, `ledger`, `recorder`, `keyring`, or `registry`, no
  filesystem mutation on any receiver, no `open()` for writing, no network
  import, and no synthetic-cognition vocabulary.

The structural half matters because behavioural tests only prove the paths they
happen to run.

## 4. Epistemic status

| Status | Meaning |
|---|---|
| `OBSERVED` | Present verbatim in a subject event payload. |
| `DERIVED` | Computed by the Observatory from one or more events. Source IDs always carried. |
| `UNAVAILABLE` | The subject exists but did not report this. Absence is not zero. |
| `UNKNOWN` | Not determinable even in principle with the telemetry available. |

The only value the deriver computes is `liveness`, from event timestamps. It is
labelled `DERIVED` and cites its events. With no subject attached, liveness is
`UNAVAILABLE`, because reporting "not currently active" would describe an entity
that does not exist.

## 5. No curriculum, no pipeline

Domains are free strings. `CONVENTIONAL_DOMAINS` in `model.py` is a
*presentation ordering*, not a required set and not a validation list. A subject
reporting only `tooling` is represented faithfully, and an unrecognised domain
is still displayed — hiding it would be a form of censorship.

There is no assumed `perception -> memory -> context -> action -> environment`
chain. Event types do not imply state: `tool.use` does not mean the subject was
thinking about tools, it means a tool was used. See
[ADR-004](decisions/ADR-004-no-event-taxonomy.md).

State arrives through a single reserved payload key, `state`, mapping domain
names to reported values. Adding a domain requires no code change.

## 6. Relationships

`StateGraph` contains only relationships the subject actually reported, via a
`links` list inside a domain's value. Every edge cites its source events. A link
naming a domain that was never reported is dropped rather than drawn to a node
we would have to invent, and the dangling reference stays visible as an
unreferenced domain.

The renderer emits a plain-text adjacency listing rather than a box-drawing
diagram. An adjacency listing cannot be misread as a picture of something it is
not, and the point of this module is that a "brain visualisation" must not be
decorative. A pretty picture of a head is read as data; the scientific
literature's central methodological complaint about brain imagery is exactly
that.

## 7. Incremental consumption

`ObservatoryReader` resumes from a byte offset, so a live session costs work
proportional to new events rather than to log size. It handles:

| Condition | Behaviour |
|---|---|
| Empty log | Nothing ingested. `NO SUBJECT` if no subject is attached. |
| New events | Picked up on the next `poll()`. |
| Duplicate record | Recognised by event ID, counted, not applied twice. |
| Out-of-order event | Accepted and flagged, never dropped. A laboratory remembers what it saw. |
| Malformed line | Counted and retained for display. Never raises; the rest of the log is still observed. |
| Truncated final line | Counted as malformed. The log is still readable. |
| Partially written line | Held in a buffer, not parsed until its newline arrives. A record in flight is not a fault. |
| Log truncated or replaced | Reset reported. Detection uses both file size and file identity, because a swap to a *longer* file is invisible to a size check. |
| Process restart | A new reader over the same canonical log reaches the same state. |

Ingest is idempotent, so the derived state is a pure function of the event log.
That property is what lets the rest of the system be reasoned about.

## 8. Performance

Measured on the development machine; see the research log for the recorded run.

| Workload | Result |
|---|---|
| Full ingest of 100,000 events | Whole Observatory module is 181 tests in ~14s; the 100k ingest test itself is well under its 120s budget |
| 200 incremental polls over a 20,000-event log | Under 1x the cost of a single full replay, confirming no per-poll re-read |
| Snapshot construction (100 snapshots) | Under 5s; does not scan the log |

The test suite times polls separately from writes. `EventStore.append` fsyncs
every line, so timing "append then poll" measures the disk, not the reader.

## 9. Persistence

None. Derived state is in memory, rebuilt from the log on start. Nothing is
written by the Observatory, including to `var/observatory/` — that path does not
exist. `baby_workspace/` is untouched and holds only its `.gitkeep` placeholders.

If persistence is ever justified it belongs in a separate, rebuildable location
(`var/observatory/`), must be disposable at any time, and must never become a
second source of truth.

## 10. The future web interface

`ObservatorySnapshot.to_dict()` is the API contract, versioned as
`babylab/observatory-snapshot/v1`. A future browser view subscribes to
snapshots and never reads the event log itself, so the read logic has exactly one
implementation.

No web server, framework, or dependency is introduced in this milestone. ADR-002
keeps the runtime standard-library-only, and a terminal that works everywhere is
worth more than a browser view that needs a toolchain.

## 11. Module map

| Module | Responsibility |
|---|---|
| `observatory/model.py` | `EpistemicStatus`, `StateValue`, `StateTransition`, `CognitiveState`. The absence-is-not-a-value enforcement. |
| `observatory/subject.py` | `SubjectRegistry`. Whether a subject exists, from the keyring only. |
| `observatory/attribution.py` | `Attributor`, `AttributionKind`. Event provenance versus identity. |
| `observatory/reader.py` | Incremental, fault-tolerant consumption. |
| `observatory/derive.py` | `StateDeriver`. Folds subject reports into state versions. |
| `observatory/graph.py` | `StateGraph`, `build_graph`. Reported relationships only. |
| `observatory/snapshot.py` | `ObservatorySnapshot`. The serialisable contract. |
| `observatory/render.py` | `ObservatoryRenderer`. Text output, colour-optional. |
| `observatory/terminal.py` | `ObservatorySession`. Wires the components together. |
| `observatory/cli.py` | `status`, `state`, `live`, `history`. |

The package is flat, matching the convention of `events/`, `provenance/`, and
`observer/`, rather than the nested layout used elsewhere in the specification.
The components are small and independently testable; a nested layout would add
import ceremony without adding clarity.

## 12. Related documents

- [Observability principles](observability-principles.md) — the rules above, stated normatively.
- [Cognitive state model](cognitive-state-model.md) — schema and serialisation.
- [Observatory API](observatory-api.md) — the snapshot contract.
- [ADR-007](decisions/ADR-007-cognitive-observatory.md) — why this shape.
- [ADR-004](decisions/ADR-004-no-event-taxonomy.md) — why there is no fixed taxonomy.
- [Event model](../events/model.py) — the canonical record.
