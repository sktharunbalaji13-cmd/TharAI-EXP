# Observability principles

**Status:** normative, Milestone 002
**Last updated:** 2026-09-26

These are the rules the Observatory is built to keep. They are stated
separately from the implementation so that a future change can be checked
against them rather than against whatever the code happens to do.

Each principle carries the test that enforces it. A principle with no test is a
wish.

---

## 1. Observation must not alter what is observed

The Observatory opens the event log for reading. It holds no writer, and
`tests/test_observatory_security.py` asserts both that a full ingest leaves the
log and ledger byte-identical, and that the package contains no call capable of
changing them.

*Enforced by:* `ReadOnlyBehaviourTests`, `ObservatorySourceScanTests`.

## 2. An unreported thing is not an empty thing

A domain the subject has not reported renders as `UNAVAILABLE`. Never as `[]`,
`0`, `None`, `-`, or a blank line.

The distinction is not pedantry. "The subject checked its memory and found
nothing" and "the subject never mentioned its memory" are different claims about
a mind, and a display that collapses them is not a slightly inaccurate
instrument — it is an instrument that will eventually be believed.

*Enforced by:* `StateValue.validate` refusing an absence that carries a value,
`StateValue.display` always returning the placeholder for an absence, and
`test_observatory_model.py::StateValueTests` / `::CognitiveStateTests`.

## 3. Every displayed value traces to the event log

A claimed value carries the event IDs it came from. A state transition carries
the events that caused it, and must cite at least one — a change with no cause is
not a change, it is a fabrication.

`ObservatorySnapshot.traceable_event_ids()` collects the IDs behind everything a
view can display, so that "where did this number come from?" always has an
answer that points at the canonical store.

*Enforced by:* `StateValue.validate`, `StateTransition.__post_init__`,
`test_observatory_model.py`.

## 4. Provenance is not identity

`Event.source` is a component label, and a payload is written by whoever produced
the event. A future subject can write both, so neither can be evidence of
authorship.

Subject identity comes from the human-owned keyring or it does not exist. Where
an event's origin cannot be established, the Observatory reports
`UNATTRIBUTED` rather than guessing.

*Enforced by:* `test_observatory_attribution.py`, including the cases where an
event's `source` is literally `baby_ai` and its payload asserts
`{"author": "BABY_AI"}`.

## 5. No subject, no subject data

There is no subject in Milestone 002. Consequently:

- `SubjectRegistry` has no mutation method, so nothing can attach one.
- A `CognitiveState` with no subject may not carry a claimed domain.
- Liveness is `UNAVAILABLE`, not `False`. Describing an entity that does not
  exist is how a laboratory starts reporting on a ghost.
- The banner reads `NO EXPERIMENTAL SUBJECT ATTACHED`, and the state section
  says there is nothing to display.

*Enforced by:* `test_observatory_subject.py`, `CognitiveState.__post_init__`,
`test_observatory_terminal.py::NoSubjectRenderingTests`.

## 6. No fixed taxonomy, no developmental curriculum

Domains are free strings. `perception`, `memory`, `context`, `action`,
`environment` are conventions for presentation, not a required set, not a
validation list, and emphatically not a sequence a subject is expected to
traverse.

A subject reporting one domain is represented faithfully. An unrecognised domain
is displayed rather than filtered.

*Enforced by:* `test_observatory_graph.py::GraphHasNoFixedPipelineTests`, which
asserts that a single reported domain produces exactly one node and no invented
neighbours.

## 7. Event types do not imply mental state

`tool.use` does not mean the subject was thinking about tools. An event records
that something happened, not what it meant. The only route from an event to a
cognitive claim is an explicit `state` payload the subject wrote about itself.

*Enforced by:* `test_observatory_state.py::test_event_type_alone_implies_no_state`.

## 8. Uncertainty is shown, not smoothed over

`OBSERVED`, `DERIVED`, `UNAVAILABLE`, and `UNKNOWN` are distinct and are rendered
distinctly. Colour never carries meaning on its own; every line is legible in
plain text.

*Enforced by:* `test_observatory_model.py::EpistemicStatusTests`,
`test_observatory_terminal.py::test_plain_text_has_no_escape_codes`.

## 9. Gaps are recorded, not smoothed

A malformed line, a duplicate, an out-of-order event, a rotated log: each is
counted and surfaced. The Observatory never raises on a corrupt record, because
one bad line must not blind it to the rest of the history; and it never silently
drops one, because a gap in a research log looks exactly like an absence of
events.

*Enforced by:* `test_observatory_reader.py`, particularly
`test_a_gap_does_not_stop_later_events_being_seen`.

## 10. Decoration is a form of false claim

A picture of a brain, an animated pulse, a mood ring, a confidence score: these
are read as data by everyone who sees them, which is why they are absent.

Relationships are rendered as a plain-text adjacency listing, because a listing
cannot be mistaken for an anatomical picture. No psychological vocabulary
appears anywhere in the package, and a source scan enforces it — this is what
stops a well-meant `readiness` field from appearing later and quietly becoming
the thing this milestone refused to build.

*Enforced by:* `test_observatory_security.py::test_no_synthetic_cognition_constants`,
`test_observatory_graph.py::test_ascii_listing_names_each_edge_and_its_source`.

## 11. A limitation is reported as a limitation

The Observatory does not implement a subject, a model, a memory, a curriculum,
or autonomy, and it does not implement OS-level isolation. These are reported as
absent rather than stubbed. A placeholder that renders as a plausible number is
worse than an empty screen, because it will eventually be mistaken for a
measurement.

*Enforced by:* the milestone-002 completion report; see
`research/experiment-log.md`.
