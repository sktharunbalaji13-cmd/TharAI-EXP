# ADR-001: Record decisions, not just code

- Status: Accepted
- Date: 2026-09-26
- Milestone: 001

## Context

This project is an experiment about a self-hosted AI system. The value of its
output depends almost entirely on whether the record of what happened can be
trusted later — by the researcher, by a reviewer, or by whoever inherits the
repository in ten years.

Code alone cannot carry that. A working tree tells you what the program does
now. It does not tell you why a boundary was drawn there, what was rejected, or
which compromises were knowingly accepted.

The failure mode of research codebases is well known: the instrumentation is
quietly shaped to produce the result the investigator wanted, and because the
shaping lives in undocumented choices, nobody notices.

## Decision

Record architecture decisions as numbered ADRs under `docs/decisions/`, and
maintain `research/experiment-log.md` as a dated operational journal.

An ADR is written when a decision is made, not when it is reversed. Superseded
ADRs stay in place with their status changed, because "we used to do X and
stopped" is itself information a future reader needs.

## Consequences

- A reader can find out *why* a boundary exists without reverse-engineering it
  from code.
- Decisions that are genuinely open are recorded as open, rather than being
  quietly resolved by whoever writes the next line of code. `ADR-003`
  (symmetric versus asymmetric signing) is the current example.
- Accepted compromises are written down as compromises. `security-model.md`
  says tier 2 is not verified because the alternative — implying it is — would
  make the whole ledger untrustworthy.
- Cost: real time. Writing these documents took a meaningful fraction of
  Milestone 001. That cost is accepted, because an experiment whose provenance
  is undocumented is not reproducible in any sense that matters.
