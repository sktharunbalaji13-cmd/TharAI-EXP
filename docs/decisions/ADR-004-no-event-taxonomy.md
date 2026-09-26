# ADR-004: No event taxonomy

- Status: Accepted
- Date: 2026-09-26
- Milestone: 001

## Context

An event system invites a schema. The obvious move is to define the namespaces a
subject is allowed to use — `learning.*`, `memory.*`, `goal.*`, `tool.*`,
`self.*` — and validate against it.

The temptation is strong because a closed schema feels like rigour, and
predefined categories feel like they make the eventual analysis easier.

## Decision

`EventStore` accepts **arbitrary** `event_type` strings and imposes no taxonomy.
The only requirements are that the type is a non-empty string and, by
convention, dotted (`namespace.verb.detail`).

The observer's `--namespace` filter accepts any prefix, so filtering works
without a central registry of what namespaces exist.

## Rationale

The alternative is a serious methodological problem, not just a style question.

1. **It is a claim about a system that does not exist yet.** Naming a
   `self_modification` category asserts that the subject will modify itself.
   Milestone 001 has no subject, and the specification is explicitly not
   Milestone 002. Encoding a guess about the experiment's outcome into its
   instrumentation is the exact failure this project is trying to avoid.

2. **A closed schema is a curriculum.** It tells the subject what it is allowed
   to report, which is an intervention on the thing being observed. If the
   schema lacks the right category, the natural response is to extend the schema
   — which means the schema was always going to grow, so it was never a
   constraint, only a delay.

3. **It forecloses unanticipated behaviour.** The most scientifically valuable
   events are the ones nobody predicted. A rejecting schema either discards them
   or pressures the instrument to be extended after the fact, at which point it
   is no longer a pre-registered schema.

4. **The categories are recoverable, the omissions are not.** Counts can be
   grouped by namespace at analysis time, in one query, forever. Events that were
   rejected at write time are gone.

## Consequences

- `observer.cli --summary` groups by whatever namespaces appear, so useful
  aggregation still works without a registry.
- Unusual or malformed types are visible rather than blocked, which is what an
  observer needs.
- The laboratory has no built-in list of what the subject is *for*. That is
  intentional. `research/experiment-log.md` records what is actually being run,
  in prose, where a human is responsible for the framing.
- If a real schema is ever needed — for a downstream consumer, say — it belongs
  in a read-side view over the log, not in the write path.
