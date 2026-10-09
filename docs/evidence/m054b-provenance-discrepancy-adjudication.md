# M054B — Pre-Existing Provenance Integrity Discrepancy Adjudication

```
M054B_STATUS              = PREEXISTING_AND_SIGNING_PERMITTED
CLASSIFICATION            = A = PRE_EXISTING_AND_SIGNING_PERMITTED

PROTECTING_ENTRY          = PROV-000014
RECORDED_DIGEST           = a16dec3afe1f8c794d8f3542a69bc0976d81ce020676d763d7d351434b564a6e
CURRENT_DISK_DIGEST       = 07efda7adb6ee30f17e5ef8e8de96eb547206f470f67d2568e5502ab6be8a608

PREEXISTING_BEFORE_M054   = TRUE

CANONICALIZATION_BLOCKED  = NO
SIGNING_BLOCKED           = NO
LEDGER_RECORD_BLOCKED     = NO
SEAL_VERIFICATION_BLOCKED = NO
GLOBAL_INTEGRITY_STATUS   = ledger INTACT, seal OK, keyring OK, 1 protected-file discrepancy

M054_LEDGER_ENTRY         = NONE
M054_SEAL                 = NONE

PRODUCTION_MUTATIONS      = 0
D3                        = NOT_APPLIED
RECOVERY_AUTHORISATION    = NOT_ISSUED
RECOVERY_CAPABILITY       = NONE
GATE_1                    = CLOSED
GATE_2                    = CLOSED

EXACT_FILES_CHANGED       = NONE
NEXT_GATE                 = HUMAN_PROVENANCE_SIGNING
```

> The single protected-file discrepancy (`research/experiment-log.md`) is **pre-existing**, was
> **never touched by M054**, and **does not block** the R1 signing ceremony. The governance ledger
> chain, the seal, and the keyring are all intact. Nothing was repaired in this milestone.

## Part 1 — Reproduced state

```
ledger entries         = 14
malformed lines        = 0
head                   = PROV-000014
chain + MACs           = INTACT
seal                   = OK
keyring                = OK
protected files        = 1 problem
  research/experiment-log.md: content differs from PROV-000014
                              (recorded a16dec3afe1f…, on disk 07efda7adb6e…)
```

Exactly one discrepancy. No additional failures.

## Part 2 — Protecting entry

```
PROTECTING_ENTRY    = PROV-000014
RECORDED_DIGEST     = a16dec3afe1f8c794d8f3542a69bc0976d81ce020676d763d7d351434b564a6e
CURRENT_DISK_DIGEST = 07efda7adb6ee30f17e5ef8e8de96eb547206f470f67d2568e5502ab6be8a608
```

`research/experiment-log.md` carries a version history of 8 ledger entries
(`PROV-000006` CREATE, then `PROV-000008`…`PROV-000014` MODIFY). `PROV-000014` is the latest and is
the ledger head. The recorded digest is `a16dec3a…`; the file on disk hashes to `07efda7a…`.

## Part 3 — Pre-existing? TRUE

| evidence | value |
|---|---|
| file mtime | **2026-09-30T22:09:49** |
| `PROV-000014` timestamp | 2026-09-27T05:36:23Z |
| M054 conversation date | **2026-10-07** |
| git status for the file | clean (no staged/unstaged change) |
| git diff --stat for the file | empty (no diff) |

The file was last modified **2026-09-30**, a full week **before** the M054 conversation began
(2026-10-07). The working tree is clean, so the on-disk content is the committed content. The
discrepancy therefore predates M054 by construction of timestamps and git state. No M042–M054
evidence references this path as a drift introduced by any of those milestones.

**PREEXISTING_BEFORE_M054 = TRUE.**

## Part 4 — Does it block M054 signing?

| step | blocked? | why |
|---|---|---|
| canonicalization of the M054 record | **NO** | canonicalization is a pure function of the 13-field record (`provenance.ledger.canonical_bytes`); it never reads `experiment-log.md` |
| HUMAN signing | **NO** | `cmd_seal` uses `keyring.key_for_role(Role.HUMAN)` → `ledger.seal(...)` and does **not** call `verify_paths` |
| ledger recording | **NO** | `ProvenanceRecorder._record` does **not** call `verify_paths`; it only checks the target path's write policy and hashes the target file |
| seal verification | **NO** | `verify_seal` compares the ledger head to the sealed head; the protected-file audit is a separate concern |
| global integrity verification | **reports the discrepancy** | `cmd_verify` calls `recorder.verify_paths()` and prints the problem, but `verify_paths` **returns a list** and does **not raise** |

`cmd_verify` is the only entry point that inspects protected files, and it is an **audit/report**
command. None of `seal`, `record`, or the ledger mechanisms consult the protected-file set.

## Part 5 — Is the discrepancy authorization-relevant?

**No.** The signing mechanism does not require the full protected-file set to be clean. `cmd_seal`
and `record` operate on the HUMAN key and the target file independently of the `research/` audit.
The existing contract is: **verification reports discrepancies; it does not gate signing on them.**

No implementation was changed, no verification weakened, no exception added.

## Part 6 — Production safety recheck (0 mutations)

```
accidental ACE unchanged  : PASS (single explicit DENY 0x00000001)
content sha256            : 55250a71209a4d39… (25 bytes)
owner / protection        : THARUNBALAJI-LA\k.tharun balaji / access_rules_protected = False
v1/v2                     : 8a0a66323bb4eb3b… / 7d592c7a03bf7a6f…
D3 absent                 : PASS
RecoveryAuthorisation     : NOT_ISSUED
RecoveryCapability        : None
Gate 1                    : CLOSED
Gate 2                    : CLOSED / AWAITING_DIRECTOR_DECISION
reconciliation            : 18/18, production_mutated_by_m052p = False
M054 ledger entry         : NONE (head still PROV-000014)
M054 seal                 : NONE
PRODUCTION_MUTATIONS      : 0
```

## Part 7 — Decision: A = PRE_EXISTING_AND_SIGNING_PERMITTED

The discrepancy predates M054 and does not block signing. The safe next steps (prepared, **not
executed**) are the same as M054A's ceremony, and they do not touch `experiment-log.md`:

1. Write the exact 1010-byte canonical R1 record to
   `docs/m052m/recovery-governance-decision-M054-R1-001.json` (must hash to `0b7148e0…ac14c96`).
2. `python -m provenance.cli record --path docs/m052m/recovery-governance-decision-M054-R1-001.json --milestone M054 --reason "..."` (records under the HUMAN key).
3. `python -m provenance.cli seal --reason "M054 R1 governance decision"` (anchors the new head under the HUMAN key).

`experiment-log.md` remains untouched. Its pre-existing drift is a **separate** matter for a **separate**
milestone; it is not part of the R1 governance decision and must not be "fixed" as a side effect of
signing.

## Non-cognitive scope

M054B concerns provenance integrity, governance adjudication, and ACL safety. It establishes nothing
about cognition, consciousness, subjective experience, agency, learning, memory, intelligence,
developmental stage, sentience, or model inference.
