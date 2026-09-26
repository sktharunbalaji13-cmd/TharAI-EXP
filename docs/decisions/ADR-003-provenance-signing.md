# ADR-003: Provenance signing — HMAC now, Ed25519 open

- Status: **OPEN** — HMAC-SHA256 adopted for Milestone 001; revisit before Milestone 002
- Date: 2026-09-26
- Milestone: 001

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

The open question is whether to move to Ed25519 before Milestone 002, and it
turns on something not yet known: whether an independent party will ever verify
this laboratory's data. If the answer is yes, symmetric signing is
unacceptable, because the verifier would necessarily be able to forge. If the
answer is never, HMAC is a reasonable trade for a zero-dependency build.

## What this decision blocks

Nothing in Milestone 001, because there is no subject and no third party. It
blocks the point at which the laboratory claims anything to someone outside the
operator's own machine.

## Interim mitigation

Until this is resolved:

- The keyring stores private material under `human_control/security/keys/private/`
  with restricted ACLs and is `.gitignore`d.
- `provenance.cli keyring` audits key material and reports anything loose.
- `security-model.md` lists "operator can forge their own roles" as residual
  risk 2, and `provenance-model.md` includes it in the threat table.
- The migration path is a single module: `provenance/keyring.py` is the only
  place that touches key bytes, so swapping the algorithm means changing one
  file and re-signing the existing ledger once.

## To resolve

Answer one question: **will anyone outside this machine ever verify this
laboratory's provenance ledger?** If yes, adopt Ed25519 and accept the
dependency. If no, record that decision here and close this ADR.
