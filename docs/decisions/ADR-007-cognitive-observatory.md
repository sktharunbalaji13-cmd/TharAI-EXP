# ADR-007: The Cognitive State Observatory as a read-only projection

- Status: **ACCEPTED**
- Date: 2026-09-26
- Milestone: 002

## Context

Milestone 001 built a trustworthy event log, a provenance ledger, a control
plane, and a terminal observer. What it did not build is any way to answer the
question the project is actually for: *what is the subject thinking, and how do
we know that?*

The specification for Milestone 002 asks for a Cognitive State Observatory
capable of live observation, state snapshots, and history, and it attaches three
constraints that pull against each other:

1. Every displayed cognitive element must be traceable to the canonical event
   log, including derived state.
2. Missing telemetry must remain visible as unavailable and must never be
   inferred.
3. The system must be extensible enough to display a "brain" visualisation
   without ever fabricating one.

The tension is that a visualiser is a machine for manufacturing impressions. A
dashboard with empty panels invites a reader to fill them in mentally. The
scientific literature's central methodological complaint about brain imagery is
that decorative renderings get read as data. Building an instrument that reports
on a mind is exactly the situation where that failure mode does the most damage.

There is also a second, quieter question: where does the Observatory's
authority to call something "the subject's state" come from?

## Decision

**The Observatory is a read-only projection over the canonical event log, and
it may only display what a subject has explicitly reported about itself.**

Four consequences, each of which is a deliberate refusal:

### 1. Single source of truth, no derived store

Derived state lives in memory and is rebuilt from the log on start. Nothing is
persisted. A rebuildable cache is a legitimate future optimisation; a second
store that can disagree with the log is not, and nothing in this milestone needs
one.

### 2. Absence is a first-class value, not a missing field

The model refuses to represent an absence as a value. `UNAVAILABLE` and
`UNKNOWN` are distinct from `OBSERVED` and `DERIVED`, and the renderer has no
path by which an unreported domain can appear as `[]`, `0`, or a blank.

This is enforced in the type, not by convention. `StateValue` cannot be
constructed in a state that would display an absence as a claim.

### 3. Provenance is not identity

`Event.source` is a component label, and payloads are written by whoever
produces the event. A future subject can write both, so neither establishes
authorship. Subject identity comes from the human-owned keyring, and events
whose origin cannot be established are `UNATTRIBUTED` rather than assumed to be
the subject's.

This is the decision most likely to be quietly relaxed later, because reading
the namespace off the event is simpler and would make the graphs look better. It
is written down here so that relaxing it is a visible change rather than a
refactor.

### 4. No decorative rendering, ever

Relationships are a plain-text adjacency listing. There is no brain image, no
animation, no psychological vocabulary anywhere in the package, and a source
scan fails the build if one appears.

A test asserting the absence of `readiness`, `confidence`, `mood`, and similar
terms is a strange-looking test. It is included deliberately: the most likely
future addition to this package is a well-meant "helpfulness" field, and it
would be an invention wearing a UI.

## Alternatives considered

**Write derived state to `var/observatory/`.** Rejected for now. It adds an
invalidation problem and a second source of truth for no measured benefit, and
the log is the only thing a reader should have to trust. Revisit if a 100,000
event rebuild ever becomes a measured problem.

**Read subject identity from the event payload.** Rejected. A subject asserting
its own identity proves nothing, and the specification explicitly forbids a
subject-event category with no real source.

**A fixed domain schema (`perception`, `memory`, `context`, `action`,
`environment`).** Rejected, consistent with
[ADR-004](ADR-004-no-event-taxonomy.md). Domains are free strings; a required
set would smuggle a curriculum back in through the read side. The conventional
names survive only as a presentation ordering.

**A web dashboard.** Deferred. ADR-002 keeps the runtime standard-library-only,
and the specification asks for an API that a future view can be built against,
not a browser application in this milestone. The snapshot contract is versioned
and documented so the client can be built later without touching the read path.

**A nested package layout** (`observatory/model/model.py` and so on). Rejected
in favour of the flat convention the existing packages use. The components are
small and independently testable; nesting adds import ceremony without adding
clarity. This is a deviation from the layout sketched in the specification and is
recorded here rather than left as a silent inconsistency.

## Consequences

- The Observatory cannot corrupt the record, because it cannot write.
- Everything it shows can be traced to events a reader can independently open.
- It will look sparse. With no subject it shows a banner and an honest empty
  state, and that is the intended appearance.
- Adding a domain requires no code change and no new event type: a subject
  reports it under the reserved `state` payload key.
- Extending attribution when a real subject exists means the human declares the
  subject's namespaces. The mechanism is configuration, not a code change, and
  is not a schema.
- A future maintainer who wants to make the display prettier will meet a test
  suite that treats decoration as a correctness problem. That is intentional.

## Related

- [ADR-002](ADR-002-no-runtime-dependencies.md) - standard-library-only runtime.
- [ADR-004](ADR-004-no-event-taxonomy.md) - no fixed taxonomy or curriculum.
- [ADR-003](ADR-003-provenance-signing.md) - signing, and the forgeability limit.
- [ADR-006](ADR-006-key-ownership-separation.md) - who holds which keys.
- [Observability principles](../observability-principles.md) - the rules, with the test that enforces each.
- [Cognitive State Observatory](../observatory.md) - implementation.
