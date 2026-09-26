# ADR-006: A seal is not a witness

- Status: Accepted (acknowledged limitation), with a follow-up recorded
- Date: 2026-09-26
- Milestone: 001

## Context

`ProvenanceLedger.seal()` writes the digest of the entire ledger into
`human_control/provenance/seals/`. This looks like it protects the ledger
against wholesale replacement: rewriting every entry and every link would
produce a different head, and the seal would no longer match.

It does protect against that, but only against someone who does **not** also
update the seal.

## Decision

Implement the seal as specified, and document its limit explicitly rather than
letting the name imply more than it delivers.

`provenance-model.md` states: a seal held in the same repository, by the same
operator, detects accidental corruption and partial tampering. It does not
detect a wholesale rewrite by someone who also updates the seal. Only an
external, independently controlled witness closes that gap.

`provenance.cli verify` reports an unsealed tail as detectable-but-unproven: no
seal means tail truncation cannot be ruled out, and the report says so rather
than passing silently.

## Why this is documented rather than fixed

The fix is not a code change; it is a change in who holds the copy. Options:

| Option | Cost |
| --- | --- |
| Second offline copy, different physical location | Manual, forgettable |
| Co-signature from a second person or key | Requires a second trusted party |
| Public transparency log (timestamping service) | Network dependency, privacy cost |
| Periodic publication of the head hash | Needs a recipient who checks it |

None of these can be set up unilaterally by a single researcher on one machine,
which is the current situation. Recording the requirement is the honest
Milestone 001 outcome.

## Consequences

- `verify` is honest: "the ledger is internally consistent and matches its last
  seal" is a real statement, and it is not the same as "the ledger is
  unmodified".
- Sealing before and after each significant run converts "something changed at
  some point" into "something changed between these two points", which is worth
  doing even without a witness.
- Never delete files from `human_control/provenance/seals/`. They are anchors.
- When a second party becomes available, re-signing the existing head under
  their key and storing it outside this repository is the migration. The
  ledger format already carries the fields needed for it.

## Related

- `ADR-003` covers the symmetric-versus-asymmetric signing question, which is
  the same underlying problem: who is able to vouch for the record.
