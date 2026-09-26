# Cognitive state model

**Status:** implemented, Milestone 002
**Schema version:** `babylab/cognitive-state/v1`
**Last updated:** 2026-09-26

---

## Shape

```json
{
  "schema": "babylab/cognitive-state/v1",
  "subject_id": null,
  "version": 0,
  "timestamp": "2026-09-26T15:28:04.024Z",
  "last_event_id": null,
  "last_event_seq": 0,
  "domains": {}
}
```

With no subject attached, `subject_id` is `null`, `version` is `0`, and every
domain is either absent or an explicit absence marker. A state that carries
claimed domains while `subject_id` is `null` is rejected at construction.

## Domains

```json
{
  "memory": {
    "domain": "memory",
    "status": "OBSERVED",
    "value": {"count": 2, "links": ["perception"]},
    "source_event_ids": ["EVENT-000004"],
    "note": ""
  },
  "perception": {
    "domain": "perception",
    "status": "UNAVAILABLE",
    "value": null,
    "source_event_ids": [],
    "note": "not reported by the subject"
  }
}
```

| Field | Rule |
|---|---|
| `domain` | Non-empty string. Free-form; not validated against a list. |
| `status` | One of `OBSERVED`, `DERIVED`, `UNAVAILABLE`, `UNKNOWN`. |
| `value` | Required for `OBSERVED`/`DERIVED`. Must be `null` for the absence statuses. |
| `source_event_ids` | Required, non-empty for `OBSERVED`/`DERIVED`. Must be empty for an absence. |
| `note` | Human-readable explanation. Rendered in `--detail`, never in the value column. |

The value/status pairing is enforced in `StateValue.validate`, at construction.
There is no way to build an object that displays an absence as a claim, so the
guarantee does not depend on a caller remembering to check.

## Transitions

```json
{
  "version": 2,
  "cause_event_ids": ["EVENT-000007"],
  "reason": "subject reported memory, perception",
  "changed_domains": ["memory", "perception"],
  "timestamp": "2026-09-26T15:31:12.884Z"
}
```

`version` starts at `1`; `0` means nothing has been reported, and is not a
numbered version of anything. `cause_event_ids` must be non-empty.

A transition is recorded when a reported value *changes*. Re-reporting an
identical value is not a transition, but the cited event ID moves forward so a
reader can cite the most recent statement.

## How a subject reports state

A subject reports through a single reserved payload key:

```json
{
  "event_type": "baby.report",
  "payload": {
    "state": {
      "memory": {"count": 2},
      "perception": {"summary": "a wall", "links": ["memory"]}
    }
  }
}
```

One reserved key rather than a new event type per domain, so that adding a
domain requires no code change, no new event type, and no ADR. See
[ADR-004](decisions/ADR-004-no-event-taxonomy.md).

### Rules for the payload

- A missing `state` key means the event reported nothing. An event happening is
  not a mental state, whatever its type says.
- A `state` key that is not an object is ignored rather than interpreted.
- A `state` object that is empty means the subject reported nothing, which is
  recorded as such and is not treated as an error.
- Domain values are passed through verbatim. The Observatory does not normalise,
  coerce, or validate their contents.

## Derived values

One domain is computed: `liveness`, whether the subject reported within the last
60 seconds, derived from event timestamps.

```json
"liveness": {
  "domain": "liveness",
  "status": "DERIVED",
  "value": true,
  "source_event_ids": ["EVENT-000007"],
  "note": "time since last report"
}
```

With no subject attached it is `UNAVAILABLE`, with the note *no subject is
attached, so it cannot be active*. With a subject attached but no report yet it
is `UNAVAILABLE` with the note *the subject has never reported* — a subject
known to have said nothing is not the same as a subject known to be inactive.

The 60-second window is a constant, not a tunable. A tunable threshold invites
tuning it until the answer looks good.

## Relationships

A domain's value may carry a `links` list naming other domains it refers to:

```json
"perception": {"summary": "a wall", "links": ["memory"]}
```

This is the only source of edges. The Observatory does not infer relationships
from co-occurrence, from ordering, or from a conventional pipeline.

A link naming a domain that has never been reported produces no edge. The missing
end is not invented to complete the picture; the referring domain is recorded as
unreferenced instead, so the discrepancy stays visible.

## Reading a state

`CognitiveState.get(domain)` returns a `StateValue`, never a raw value. For a
domain that was not reported it returns an explicit
`UNAVAILABLE` marker with the note *not reported by the subject*. A caller
therefore cannot treat a missing domain as a falsy value without handling the
absence deliberately.

`reported()` returns only the domains that carry a claim — the right input for a
graph, an export, or a count, since an absence must never be counted as an
observation.

`ordered_domains()` puts the conventional domains first and sorts the rest
alphabetically. This is presentation only; the conventional list is a
convenience, not a schema.
