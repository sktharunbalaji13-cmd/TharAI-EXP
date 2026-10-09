# M052W — Explicit Human Recovery-Governance Submission Gate

```
M052W_STATUS    = DECISION_REQUIRED
M052W_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED

RECOVERY_GOVERNANCE_DECISION = NONE
DECISION_AUTHORITY           = NOT_SUPPLIED
PROVENANCE_SEAL_ID           = NOT_SUPPLIED
SELECTED_BY_OPERATOR         = NO

PRODUCTION_CHANGED                 = NO
PRODUCTION_RECOVERY_PERFORMED      = NO
RECOVERY_AUTHORISATION             = NOT_ISSUED
RECOVERY_CAPABILITY_FOR_PRODUCTION = NO
ACCIDENTAL_ACE                     = STILL PRESENT (DENY …-1022, 0x00000001, explicit)

D3 = NOT_APPLIED   SUBJECT_LAUNCH = NOT_ATTEMPTED
GATE_1 = CLOSED   GATE_2 = CLOSED   A/B/C = NONE
```

> **No human decision was supplied.** The current human input is the M052W master prompt. M052W is a
> governance intake gate; ingestion requires a current human submission. There was none, so it
> stopped cleanly. The technical system cannot legitimately choose R1/R2/R3. The blocker is human
> governance input, not missing implementation. No production recovery authorisation exists. The
> accidental ACE remains intentionally preserved. No production mutation occurred during M052W.

## What M052W is

M052S built the intake mechanism. M052T repaired natural-language declarations. M052V repaired the
quoted-hypothetical false positive. M052W does not extend those mechanics; it narrows the *boundary*
at which a decision may enter.

Only `CURRENT_HUMAN_INPUT` may carry a selection. Repository specification, history, provenance,
fixtures, prior prompts and this prompt are all non-authoritative for the selection itself. They can
verify a decision; they can never manufacture one.

The intake returns exactly one of:

```
NO_DECISION
DECISION_RECORD_INCOMPLETE
INVALID_DECISION
PROVENANCE_BINDING_REQUIRED
DECISION_ACCEPTED
```

`DECISION_ACCEPTED` requires a HUMAN-signed provenance entry that binds the exact canonical JSON of
the submitted record. It never mints a seal, never appends to the ledger, and never opens production
to mutation. A governance decision is *governance class only* -- even on acceptance,
`authorises_production_recovery` is `False` and every production gate stays closed.

## The 13-field record

A selection alone is insufficient. The actual human submission must bind:

```
decision_id, decision_class, selected_option, authority_id, authority_type, rationale,
scope, effective_for_milestone, exclusions, incident_reference, repository_HEAD,
provenance_seal_id, authorises_production_recovery
```

`authorises_production_recovery` must equal `FALSE`. If `TRUE`, classify as
`INVALID_RECOVERY_AUTHORITY_ATTEMPT` and refuse.

Exclusions must explicitly prohibit: D3, production recovery, ACL mutation, subject launch, Gate 2
opening, production capability minting.

The record must not carry hidden authority-conferring fields (`allow_production`, `grants_d3`,
`execute_recovery`, `apply_subject_deny`, `icacls`, etc.).

## Parser boundary

Quoted spans are stripped. Hypothetical framing (`if`, `suppose`, `assume`, `for example`, `would`,
`could`, `should`, `might`, `recommend`, `tell`, `documentation`, `containing`, `previous milestone`)
causes immediate refusal. Imperative `Choose Rn` is refused as a recommendation. A second explicit
selection in the same submission is refused as ambiguous. Repository prose, milestone prompts and
test fixtures are classified as non-authoritative before parsing.

## Adversarial matrix — 20/20

All quoted examples, code blocks, hypothetical forms, recommendations, imperative forms, two
selections, malformed options, and prior-milestone prose are refused. A bare selection is
`DECISION_RECORD_INCOMPLETE`, not `NO_DECISION` and never `DECISION_ACCEPTED`. A record with
`authorises_production_recovery = TRUE`, missing exclusions, or hidden authority fields is
`INVALID_DECISION`. No case produced `DECISION_ACCEPTED`.

## Production safety — 14/14 read-only

| # | condition | result |
|---|---|---|
| 1 | target | `m016_read_fixture.exe` — unchanged |
| 2 | ACE | exactly one, explicit DENY `0x00000001` |
| 3 | SID | `S-1-5-21-…-844951592-1022` — unchanged |
| 4 | mask | `0x00000001` — unchanged |
| 5 | content | 25 bytes, sha256 `55250a71209a4d39…` — unchanged |
| 6 | owner | `THARUNBALAJI-LA\k.tharun balaji` — unchanged |
| 7 | DACL protection | `access_rules_protected = False` — unchanged |
| 8 | related ACEs | v1 `8a0a66323bb4eb3b…`, v2 `7d592c7a03bf7a6f…` — identical |
| 9 | D3 | absent — no `0x000D0156` |
| 10 | Gate 1 | `CLOSED` |
| 11 | Gate 2 | `CLOSED` / `AWAITING_DIRECTOR_DECISION` |
| 12 | RecoveryAuthorisation | `NOT_ISSUED` |
| 13 | production RecoveryCapability | none |
| 14 | subject | not launched; password value never read |

Reconciliation **18/18**, `production_mutated_by_m052p = False`. Security objective `NOT_SATISFIED`,
shortfall 5 of 8. All 17 `TharAI_M*` preservation roots intact. Pre-incident fingerprints preserved.

## Provenance — read-only, untouched

```
ledger: 14 valid, 0 malformed, 0 problems
sealed head: PROV-000014, 0 problems
seals on disk: 10
entries appended by M052W: 0
```

No entry appended, no seal minted or altered, no signing identity replaced. `HEAD.json`,
`control.token`, `control.json` unmodified.

## Validation

```
M052W focused tests   : 13 passed
M052W negative matrix : 20/20 correct
M052S/M052W combined  : 288 passed, 7 failed
standing red baseline : 12 failed, 65 passed — unchanged
```

Same 7 incident-caused M052K/M052L assertions. **M052W introduced no new failures.**

## Git

```
HEAD   : 6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555
branch : master
staged : 0
modified tracked : 8, unchanged since M052Q
new untracked : docs/evidence/m052w-recovery-governance-decision.md,
                tests/m052w_intake.py, tests/test_m052w_intake.py
```

## Next gate

```
M052W_STATUS    = DECISION_REQUIRED
M052W_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED
PRODUCTION_RECOVERY_PERFORMED = NO
```

The blocker is human governance input, not missing implementation. To advance, supply in the
conversation:

1. an explicit selection — `I select R1.`, `My RECOVERY_GOVERNANCE decision is R2.`, or `I select
   R3 as the recovery governance class.`
2. the full 13-field record with `authorises_production_recovery = FALSE`
3. a `provenance_seal_id` backed by an existing HUMAN-signed entry binding the exact canonical JSON
   of that record

M052W will verify and freeze it, and still will not execute recovery.

---

## Non-cognitive scope

M052W concerns human governance, provenance, recovery classification, authority separation, ACL
safety, and incident remediation. It establishes nothing about cognition, consciousness, subjective
experience, agency, learning, memory, intelligence, developmental stage, sentience, or model
inference.
