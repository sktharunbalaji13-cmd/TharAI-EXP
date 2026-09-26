# Observer interface

The observer is the only component whose output a researcher is expected to
read, so it is deliberately the most boring thing in the repository.

## What it can and cannot do

| | |
| --- | --- |
| Reads | `var/events/events.jsonl` |
| Writes | nothing, ever |
| Holds a signing key | no |
| Privileged operations | none |

There is no code path in `observer/` that opens a file for writing or calls into
`provenance/`. That is the point: the human's view of the experiment cannot
influence the experiment.

## Invocation

```
python -m observer.cli
```

Streams new events as they are appended, and replays the existing log first.
Ctrl-C stops following; the process exits `130`.

Convenience wrappers live in `scripts/start_observer.ps1`.

## Options

| Option | Effect |
| --- | --- |
| `--no-follow` | Replay what exists and exit. For scripting and CI. |
| `--max-history N` | Replay only the most recent N events. |
| `--namespace NS` | Only events whose type begins with `NS.`. Repeatable. |
| `--type TYPE` | Only this exact event type. Repeatable. |
| `--summary` | Aggregate counts by category and event type instead of streaming. |
| `--detail` | Include the full payload for each event. |
| `--source` | Show which component produced the event. |
| `--hash` | Show the event ID and a hash prefix. |
| `--progress-every N` | Print a throughput note every N displayed events. |
| `--poll-interval S` | Seconds between tail polls. Default `0.5`. |
| `--no-color` | Disable ANSI colour. |

`--namespace`, `--type`, `--detail`, `--source` and `--hash` combine. Filtering
is applied while streaming, not after, so a narrow filter over a long session
stays cheap.

## Line format

```
[14:47:04] SYSTEM      Baseline written
[14:47:18] CONTROL     Control process stopped
[19:04:12] SECURITY    Control request rejected (shutdown)
         └─ system.control · ev_000012 · 4f3a9c2e
```

- `[HH:MM:SS]` is UTC. The full millisecond-precision timestamp is in the event
  record, not the line, because the line is for scanning and the record is for
  citing.
- The category column is a fixed 11 characters so that every event in a session
  lines up. A category longer than the column is right-truncated with `…`
  rather than allowed to push the headline out of alignment; `--source` and
  `--detail` still show the full `event_type`, so nothing is lost.
- Colour is used only to separate categories, never to encode state. Colour is
  disabled automatically when stdout is not a terminal, and honours `NO_COLOR`.

## Following

The observer tails by byte offset, so it can be stopped and restarted without
re-reading the whole log, and it never re-reads a line it has already shown.
When the file shrinks, or its identity changes, the observer says so and resets
rather than silently continuing at a stale offset.

## Faults are visible

A malformed line does not stop the stream. It is rendered in place, marked
`MALFORMED`, with the reason and an excerpt of the offending line, and the exit
code is non-zero at the end. Silently skipping a corrupt record in a research
log would be the worst possible behaviour: the gap would look like an absence
of events.

## Performance

`EventStore` keeps a head-entry cache keyed on the log's size, so sequential
appends are not quadratic. The observer's high-volume tests exist to keep this
honest: they append tens of thousands of events and assert that throughput does
not collapse. The provenance ledger uses the same technique, with the
deliberate exception that **verification always reads from disk** and never
consults the cache, because a cache is a performance detail and not a source of
truth.

## Windows note

Output is forced to UTF-8 with `errors="replace"`. A research stream gets piped
into files and log collectors constantly, and under the default ANSI code page a
single `…` would become a replacement glyph, quietly corrupting the record the
observer exists to display. The worst case after this fix is one visible `?`.
