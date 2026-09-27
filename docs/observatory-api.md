# Observatory API

**Status:** implemented, Milestone 002; `birth` section added in Milestone 003
**Snapshot version:** `babylab/observatory-snapshot/v1`
**Last updated:** 2026-09-27

`ObservatorySnapshot.to_dict()` is the contract. The terminal renderer and the
test suite are both consumers of it, and a future browser view would be a third.

No web server is implemented in this milestone. ADR-002 keeps the runtime
standard-library-only, and the value of this document is that the client can be
built against a defined contract before any transport exists.

---

## Envelope

```json
{
  "schema": "babylab/observatory-snapshot/v1",
  "generated_at": "2026-09-26T15:28:04.024Z",
  "subject": {
    "status": "NO_SUBJECT",
    "banner": "NO EXPERIMENTAL SUBJECT ATTACHED",
    "detail": "Cognitive telemetry unavailable"
  },
  "birth": { "...": "see below" },
  "state": { "...": "see cognitive-state-model.md" },
  "graph": { "...": "see below" },
  "recent_events": [ ],
  "ingest": { "...": "see below" },
  "reader": { "...": "see below" },
  "deriver": { "processed_events": 18, "state_versions": 0, "reported_domains": 0 },
  "faults": [ ]
}
```

`subject.detail` is `null` only when the subject is both key-attached and
recorded, and a string explaining the gap in every other case: no subject, a
record with no key, or a key with no record. A client should surface it. An
empty dashboard and a dashboard reporting a missing subject are different
situations, and only one of them means the instrument is working.

## subject

| Field | Type | Meaning |
|---|---|---|
| `status` | string | `NO_SUBJECT`, `RECORDED`, or `ATTACHED`. |
| `banner` | string | Human-readable subject line. |
| `detail` | string or null | Why there is no telemetry. |

`ATTACHED` means a human-registered `BABY_AI` key is active. `RECORDED` means a
sealed birth record exists but no such key does. The two must not be collapsed:
the first says the subject can sign things, the second does not. See
[observatory.md](observatory.md) §3.0.

Subject attachment is established from the human-owned keyring. A client must
not derive subject identity from anything in this payload; it is reported, not
inferred, for the same reason the terminal does not.

## birth

Added in Milestone 003. This is a verbatim pass-through of
`birth.status.birth_status`, the birth subsystem's read-only report. It is
present in every snapshot, including in a laboratory with nothing configured,
because "no model and no subject" is the state most installations are actually
in and the display has to be able to say so.

```json
{
  "subject_exists": true,
  "subject_id": "baby-ai:subject-001",
  "born_at": "2026-09-27T04:31:52.197Z",
  "birth_id": "BIRTH-b078793f6610",
  "birth_event_id": "EVENT-000001",
  "model_status": "READY",
  "model_detail": "birth record BIRTH-... was written on ... by a ceremony that verified the weights and the runtime",
  "model_installed": true,
  "model_usable": true,
  "capability_registry_hash": "…",
  "capability_statuses": { "PERCEPTION": "UNAVAILABLE" },
  "environment_id": "env.unattached",
  "environment_connected": false,
  "workspace_state": "EMPTY",
  "model": { "model_name": "…", "model_sha256": "…", "authorship_classification": "INHERITED_PRETRAINED" },
  "birth_record_hash": "…"
}
```

Four of these fields are independent facts, and any two can be true while the
others are false:

| Field | Means |
|---|---|
| `subject_exists` | A sealed birth record is on disk. |
| `model_installed` | The weights are on disk and their digest matches. |
| `model_usable` | The weights are installed *and* a runtime was found and healthy. |
| `model_status` | The fine-grained reason. |

`model_status` is one of `NOT_CONFIGURED`, `MODEL_NOT_INSTALLED`,
`MODEL_INTEGRITY_MISMATCH`, `RUNTIME_UNAVAILABLE`, `RUNTIME_UNVERIFIED`,
`READY`, or `ERROR`.

`RUNTIME_UNVERIFIED` deserves attention, because it is the status the
Observatory reports most often in a configured laboratory. The read-only status
path never executes the runtime binary, so it can establish that the weights are
correct but not that they can be loaded. Reporting `READY` there would tell a
client the model is usable when no process has run it, so it does not. A client
must treat `model_usable: false` as a real answer, not as missing data.

If the birth subsystem cannot be read at all — a corrupt record, a permission
problem — the payload reports `model_status: "UNAVAILABLE"` and a `read_error`
string rather than failing the snapshot. A read-only observer that crashes
because an unrelated subsystem is unhappy is not read-only, it is useless.

None of this is cognitive state. `birth` describes the laboratory's substrate; a
model existing is not a mind existing. Clients must not merge it into `state`.

## state

The `state` object is a `CognitiveState`, serialised under its own schema
identifier `babylab/cognitive-state/v1`. Its fields are specified in
[cognitive-state-model.md](cognitive-state-model.md); note in particular that
`subject_id` is `null` and `version` is `0` when no subject is attached, and
that every domain in a no-subject snapshot is an absence carrying no value and no
source events.

## graph

```json
{
  "nodes": [
    {
      "node_id": "domain:memory",
      "kind": "DOMAIN",
      "label": "memory",
      "status": "OBSERVED",
      "source_event_ids": ["EVENT-000004"]
    }
  ],
  "edges": [
    {
      "source": "domain:perception",
      "target": "domain:memory",
      "kind": "reported",
      "source_event_ids": ["EVENT-000004"]
    }
  ],
  "unreferenced_domains": ["decision"]
}
```

`kind` is `SUBJECT`, `DOMAIN`, `DERIVED`, or `INFRASTRUCTURE` for nodes;
`reported` or `derived` for edges.

An empty `nodes` and `edges` list is a valid, honest result and is what this
milestone produces. A client must render that as *no relationships have been
reported*, not as an empty diagram that looks like a rendering failure.

`unreferenced_domains` lists domains the subject reported without declaring any
relationship. It is worth displaying: it distinguishes *reported in isolation*
from *connected to nothing because it was never connected*.

## recent_events

```json
{
  "kind": "INFRASTRUCTURE",
  "label": "CONTROL",
  "basis": "laboratory infrastructure namespace; no subject is attached, ...",
  "event_id": "EVENT-000009"
}
```

The last ten events with their attribution. `basis` is the human-readable reason
for the attribution and is not decoration: it tells the reader *why* the
Observatory believes what it believes, which is the difference between a claim
and a guess.

## ingest and reader

```json
"ingest": {
  "offset": 8152,
  "generation": 0,
  "ingested": 18,
  "highest_seq": 18,
  "malformed_lines": 0,
  "out_of_order": 0
}
```

The reader's cursor, exposed so a future client can report that it is
following. `generation` increments when the log is detected as rotated or
replaced. `malformed_lines` and `out_of_order` are integrity signals, not
errors: they record that the history has irregularities a reader should know
about.

A client should display non-zero values for these. A gap in a research log looks
exactly like an absence of events, so silently hiding the gap would be the worst
possible behaviour.

## faults

A list of human-readable fault descriptions. Empty in normal operation.

## Traceability

`traceable_event_ids()` returns every event ID behind anything in the snapshot —
state values, graph nodes, graph edges, and the recent-event list, sorted and
deduplicated.

A client can use it to answer "which records support this view?" without
re-deriving anything. It is also the mechanism for the specification's
requirement that every displayed element be traceable: a displayed value whose
event IDs do not appear here came from nowhere.

## Stability

`schema` is versioned. A client should check it and refuse to render an
unrecognised version rather than guess at field meanings.

Within a version, additive fields may appear. Removing a field, renaming one, or
changing an `EpistemicStatus` string requires a new version, because those are
the parts a client makes decisions about. The status strings in particular are
part of the contract, not display text.

## What this API deliberately does not expose

- **No write endpoints.** The Observatory has no mutating operation to expose.
- **No subject registration.** Attaching a subject is a human decision made
  through the keyring, not an API call. An endpoint that could invent a subject
  would undermine the one guarantee this milestone exists to establish.
- **No arbitrary queries over history.** The canonical log is the query surface
  for a milestone that size. A query language would be a new feature, not an
  API.
