# Provenance model

## The claim being made

Every protected file in the laboratory is described by a ledger entry that says
**who** made the change, **when**, **to what**, and **what the content was**.
This document explains what makes that claim checkable and, just as
importantly, what it does not make checkable.

## Two logs, deliberately different

| | Event log | Provenance ledger |
| --- | --- | --- |
| Path | `var/events/events.jsonl` | `var/provenance/ledger.jsonl` |
| Authored by | anyone with write access | privileged writers, via a key |
| Integrity | SHA-256 hash chain | SHA-256 hash chain **plus** HMAC-SHA256 |
| Purpose | the narrative | the accountability record |
| Loss tolerance | a gap is visible | a gap is evidence of tampering |

The event log is a narrative: it says what happened, in order. The provenance
ledger is an accountability record: it says who vouched for what. Adding
signatures to the event log would have cost a key on the read path, for a log
whose job is to be *read*. Splitting them keeps the observer's job trivial and
the accountability strong.

## Chain construction

Each entry hashes the previous entry's hash:

```
entry_hash = SHA256(canonical_json({
    "seq":          n,
    "prev_hash":    entry[n-1].entry_hash,
    "timestamp":    "2026-09-26T19:04:12.482Z",
    "action":       "create",
    "path":         "human_control/baseline/layout.json",
    "sha256":       SHA256(file_bytes),
    "author":       "HUMAN",
    "author_key":   "HK-86ac3dc595e9",
    "milestone":    "MILESTONE-001",
    "reason":       "record the expected directory layout",
    "metadata":     {...}
}))
```

`canonical_json` sorts keys and uses fixed separators, so the same logical entry
always produces the same digest regardless of dictionary ordering. `entry_hash`
goes into both `entry_hash` and `entry_mac` inputs, so altering any field
invalidates the chain link *and* the signature.

The genesis entry has `prev_hash: null`.

## Signing

`entry_mac = HMAC_SHA256(keyring[author_key].secret, entry_hash)`

The signature covers the whole entry, including the `seq` and `prev_hash`, which
means a valid signature cannot be replayed at a different position in the
chain.

## Authorship is derived, never declared

This is the single most important design decision in the ledger, and it is worth
stating plainly because the naive version is wrong.

The obvious design is for the caller to pass `author="HUMAN"` to a recording
call. That design is worthless: any code that can call `record_creation` can also
claim to be the human. The provenance ledger would then faithfully record lies,
and worse, record them *with a valid signature*.

So authorship is derived from a key ID, and key possession is the claim:

```python
# The caller may supply a key ID. It may NOT supply a role.
entry = ledger.record(
    path=target,
    action="create",
    author_key=keyring.for_role(role),   # resolves role -> key ID
    ...
)
```

`provenance/keyring.py` resolves `HK-86ac3dc595e9` to the `HUMAN` secret. If a
caller passes `author="BABY_AI"` alongside a `HUMAN` key ID, the declared author
is **discarded**, the key-derived author wins, and the conflict is recorded in
the entry's metadata as `declared_author_conflict`. The lie is preserved as
evidence, not silently corrected. See `docs/decisions/ADR-003`.

## Consequences of using HMAC

HMAC is symmetric. The verifier and the signer share the secret. Therefore:

- **The verifier can forge.** Anyone who can run `provenance.cli verify` in this
  repository can also sign a new entry that verifies. For a single-operator
  research laboratory with no adversary, this is acceptable and buys a
  zero-dependency implementation.
- **Key theft is total compromise for that role.** There is no "public" half to
  leak.
- **Verification and signing must be understood as the same trust domain.**

Ed25519 would fix all three: the private key signs, the public key verifies, and
a leaked public key is harmless. It costs one dependency. This is recorded as an
open decision in `docs/decisions/ADR-003` and should be revisited before any
adversarial component is added.

## The seal

A seal is the digest of the entire ledger at a moment in time, copied into
`human_control/provenance/seals/`. Because the seal is stored in a different
directory from the ledger, it anchors the ledger against whole-file replacement:
rewriting the ledger means recomputing every entry and every link, and the seal
no longer matches.

`ProvenanceLedger.seal(reason)` writes one. `provenance.cli seal` exposes it to
an operator.

**Limitation, stated because it matters:** a seal held in the same repository by
the same operator detects *accidental* corruption and *partial* tampering. It
does not detect a wholesale rewrite by someone who also updates the seal. Only
an external, independently controlled witness (a co-signature, an offline copy
in a different trust domain, a transparency log) closes that gap. Until one
exists, "unsealed tail" means tail truncation is undetectable.

## What verification checks

`provenance.cli verify` reads every line from disk — never from the in-memory
index cache, because a cache is a performance detail and not a source of truth
— and reports:

| Check | Detects |
| --- | --- |
| JSON parses | corruption, partial writes |
| Required fields present | truncation, hand-editing |
| `seq` increments by 1 | deletions, reorderings |
| `prev_hash` matches the prior entry's hash | edits in the middle of the chain |
| `entry_hash` recomputes | any field alteration |
| `entry_mac` verifies under the declared key | forgery without the secret |
| Referenced file digest matches the recorded digest | out-of-band file edits |
| Seal matches the chain head | whole-ledger replacement |

`ProvenanceRecorder.verify_paths()` adds a bidirectional check that the ledger's
picture of `human_control/` and `var/` matches what is actually on disk. It
reports unrecorded creations, unrecorded modifications, and recorded-but-missing
files. `provenance.cli audit` runs it.

## Threat model summary

| Adversary | Detected? | By what |
| --- | --- | --- |
| Accidental edit by a human | yes | digest mismatch on verify |
| Buggy code writing to `human_control/` | yes | digest mismatch, plus `PathPolicy` refusal |
| Truncation or deletion from the middle | yes | broken `prev_hash` link |
| Reordering | yes | broken `seq` |
| Forgery without the key | yes | HMAC failure |
| Forgery **with** the key (same operator) | **no** | HMAC is symmetric; see ADR-003 |
| Wholesale ledger rewrite plus seal update | **no** | same operator controls both |
| Compromise of a `BABY_AI` key | partly | that role's entries become forgeable; `HUMAN` and `SYSTEM` keys are unaffected |
