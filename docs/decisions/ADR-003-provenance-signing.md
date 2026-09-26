# ADR-003: Provenance signing - HMAC now, Ed25519 deferred

- Status: **ACCEPTED (deferred)** - HMAC-SHA256 retained for Milestone 002;
  Ed25519 to be adopted before any external verification
- Date: 2026-09-26
- Milestone: 001, revisited at the Milestone 002 architecture checkpoint

## Context

The provenance ledger must distinguish `HUMAN`, `SYSTEM`, and eventually
`BABY_AI` authorship, and it must make forgery detectable. That requires
asymmetric signatures, or at least something stronger than a bare hash.

Two candidates:

| | HMAC-SHA256 | Ed25519 |
| --- | --- | --- |
| Dependency | standard library (`hmac`) | `cryptography` |
| Signer holds | the secret | the private key |
| Verifier holds | **the same secret** | the public key |
| Verifier can forge | **yes** | no |
| Key theft impact | total for that role | total for that role |
| Leaked public key | fatal | harmless |

The decisive problem with HMAC here is specific to this system: **the verifier
is the same operator as the signer.** A researcher who can run
`provenance.cli verify` can also write a fabricated entry that verifies
perfectly. In a single-operator laboratory that is a real limitation, and
`docs/provenance-model.md` states it in a threat-model table rather than
burying it.

Ed25519 fixes it: the private key signs, the public key verifies, and a
third party can check the ledger without being able to extend it.

## Decision

**Milestone 001 uses HMAC-SHA256.** The cost is a documented limitation, not a
hidden one.

At the Milestone 002 architecture checkpoint the researcher was asked directly
whether anyone outside this machine will ever verify this laboratory's
provenance ledger, and answered: **yes, eventually.**

Therefore:

- **HMAC-SHA256 is retained for Milestone 002.** No migration is performed now.
  There is no subject, no third party, and no ledger to re-sign, so a migration
  would be ceremony with no effect on any real assurance claim.
- **Ed25519 is adopted before any external verification takes place.** The
  threshold is concrete and is not "someday": it is the moment the laboratory
  asks anyone outside the operator's own machine to check a signature.
- Accepting the `cryptography` dependency at that point is an accepted cost, not
  a trade to be re-litigated.

The deferral is deliberate and bounded. It is not a decision to keep symmetric
signing indefinitely, and the condition for changing it is known.

## What this decision blocks

Nothing in Milestone 002. There is no subject and no third party, so nothing in
the Cognitive State Observatory depends on non-forgeable signatures.

It blocks exactly one thing: the point at which the laboratory claims anything
to someone outside the operator's own machine. Until Ed25519 is adopted, the
laboratory's provenance is verifiable by the operator and by nobody else
independently.

## Interim mitigation

Until Ed25519 is adopted:

- The keyring stores private material under `human_control/security/keys/private/`
  with restricted ACLs and is `.gitignore`d.
- `provenance.cli keyring` audits key material and reports anything loose.
- `docs/security-model.md` lists "operator can forge their own roles" as
  residual risk, and `docs/provenance-model.md` includes it in the threat table.
- Any report produced while HMAC is in use must state that its signatures are
  operator-verifiable only, and are therefore not independent evidence.
- The migration path is a single module: `provenance/keyring.py` is the only
  place that touches key bytes, so swapping the algorithm means changing one
  file and re-signing the existing ledger once.

## Reopen condition

This ADR is reopened, and the migration performed, if any of the following
becomes true:

1. An independent party is asked to verify this laboratory's provenance.
2. A second operator is granted access to verify or produce records.
3. The ledger is published, shared outside the operator's machine, or used as
   evidence in any external context.

Until one of those happens, HMAC-SHA256 is an honest, documented, and adequate
choice.
