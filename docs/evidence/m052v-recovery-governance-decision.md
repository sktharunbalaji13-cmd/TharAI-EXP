# M052V — Final Governance-Decision Intake Gate

```
M052V_STATUS    = DECISION_REQUIRED
M052V_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED

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
GATE_1 = CLOSED   GATE_2 = CLOSED   A/B_C = NONE
```

> **The current human input carries no decision.** It is the M052V master prompt — a specification of
> what a decision would look like, not a decision. M052V is the final intake gate, and ingestion
> requires input. There was none, so it stopped at validation step 1.
>
> **A critical defect was found and fixed during this milestone.** The parser initially returned
> **R1** from the M052V prompt, because the prompt contains the line
> `If the human supplies only "I choose R1" but does not supply the required authority/provenance
> material: STOP at DECISION_RECORD_INCOMPLETE.` The quoted first-person string inside that
> conditional was read as a genuine selection. Acting on it would have manufactured a director
> decision out of a specification of a case to refuse — the exact failure this entire gate chain
> exists to prevent, arriving through the gate meant to catch it. The defect is fixed and guarded.

---

## 1. Human decision input

**The M052V master prompt. Nothing else.**

The prompt defines the 12-field contract, the 20-step validation sequence, and the provenance
requirement. It states its own rule: *"Do NOT treat this prompt as a decision."*

Submitted to the intake parser, the prompt returns:

```
parse_selection(M052V prompt) -> None
reason: submission is framed hypothetically or as an example, not as a decision
```

No option is extracted. A specification is not a submission.

## 2–15. Decision record fields

| field | value |
|---|---|
| selected option | **NONE** |
| decision_id | NOT_SUPPLIED |
| decision_class | `RECOVERY_GOVERNANCE` (required of a real decision; none exists) |
| authority_id | NOT_SUPPLIED |
| authority_type | NOT_SUPPLIED |
| rationale | NOT_SUPPLIED |
| scope | NOT_SUPPLIED |
| effective_for_milestone | NOT_SUPPLIED |
| exclusions | NOT_SUPPLIED |
| incident reference | M052M — the unauthorized production mutation |
| repository HEAD | `6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555` |
| predecessor decision | M052U |
| supersedes | nothing superseded |
| `authorises_production_recovery` | required to be `FALSE` of a real decision; none exists to carry it |
| provenance seal ID | NOT_SUPPLIED |
| cryptographic verification | NOT_APPLICABLE — nothing submitted |
| canonical-content binding | NOT_APPLICABLE — no content to bind |
| conflict check | NOT_APPLICABLE — no decision to conflict with |

No field was populated from model assumptions. No substantive content was added.

**Stop classifications evaluated and not triggered**, because there was no submission to classify:
`DECISION_AMBIGUOUS`, `INVALID_RECOVERY_GOVERNANCE_OPTION`, `DECISION_RECORD_INCOMPLETE`,
`DECISION_AUTHORITY_MISSING`, `PROVENANCE_SEAL_MISSING`, `DECISION_PROVENANCE_MISMATCH`,
`DECISION_PROVENANCE_AMBIGUOUS`. None was converted to PASS; each would have been a stop.

## 16–20. Validation sequence

```
STEP 1  Human supplied explicit decision : NO
  -> Stop at step 1. Steps 2-20 are not reachable.
```

Steps 2–20 (option uniqueness, decision class, mandatory fields, classification-only assertion,
scope, exclusions, authority, seal existence, HUMAN role, MAC verification, content binding, field
matching, HEAD relation, seal uniqueness, conflict check) were not evaluated because step 1 failed.
`UNKNOWN` was not converted to PASS anywhere.

## 21. R1/R2/R3 result

None interpreted. No option was selected, so no classification was recorded and no option-specific
processing ran. R1's architecture preconditions were measured as **readiness only** in M052U and
remain unchanged:

```
RecoveryAuthorisationContract : 32 fields    RecoveryCapabilityContract : 14 fields
authorisation_cannot_express_d3                : True
authorisation_cannot_express_rollback          : True
capability_is_distinct_type                    : True
authority_conferring_fields_absent             : deny_mask, arbitrary_mask/target/principal,
                                                 add_ace, restore_ace, generic_acl_operation
guard_fields_present_and_false_pinned          : allow_production, grants_d3, grants_rollback,
                                                 grants_add, owner_take, recursive
```

This says the architecture *would* satisfy R1's separation requirements. It is not evidence that R1
was chosen, and technical readiness is not permission.

**R3 policy status: NOT_APPLICABLE.** No R3 selection exists, so no `RECOVERY_GATE_2_POLICY` was
requested, generated, or inferred.

## 22–25. A/B/C, authorisation, capability, gates

```
A_B_C                            = NONE      (M052V did not decide it)
RECOVERY_AUTHORISATION           = NOT_ISSUED
RECOVERY_CAPABILITY_FOR_PRODUCTION = NO
GATE_1 = CLOSED                   GATE_2 = CLOSED
```

Unconditional in M052V. Even a fully valid R1/R2/R3 would leave all four exactly as they stand.

## 26–29. Production, ACE, D3, subject — 14/14 read-only

| # | condition | result |
|---|---|---|
| 1 | target unchanged | PASS — `m016_read_fixture.exe` |
| 2 | ACE unchanged | PASS — exactly one |
| 3 | SID unchanged | PASS — `S-1-5-21-…-844951592-1022` |
| 4 | mask unchanged | PASS — `0x00000001` |
| 5 | content unchanged | PASS — 25 bytes, sha256 `55250a71209a4d39…` |
| 6 | owner unchanged | PASS — `THARUNBALAJI-LA\k.tharun balaji` |
| 7 | DACL protection unchanged | PASS — `access_rules_protected = False` |
| 8 | unrelated ACEs unchanged | PASS — v1 `8a0a66323bb4eb3b…`, v2 `7d592c7a03bf7a6f…` |
| 9 | D3 absent | PASS — no `0x000D0156` ACE |
| 10 | Gate 1 unchanged | PASS — `CLOSED` |
| 11 | Gate 2 unchanged | PASS — `AWAITING_DIRECTOR_DECISION` |
| 12 | no `RecoveryAuthorisation` | PASS |
| 13 | no production capability | PASS |
| 14 | subject not launched | PASS — password value never read |

Reconciliation **18/18**, `production_mutated_by_m052p = False`. Security objective `NOT_SATISFIED`,
shortfall 5 of 8. All 17 `TharAI_M*` preservation roots intact.

```
incident-state v1  8a0a66323bb4eb3b…   pre-incident v1  f73eaf783ffb2698…  PRESERVED
incident-state v2  7d592c7a03bf7a6f…   pre-incident v2  1684a02f028412e1…  PRESERVED
incident v1 != pre-incident v1 : True
```

The accidental state and the pre-incident fingerprint remain separate historical facts. The ACE was
neither removed nor restored; recovery was not tested against production. No `Set-Acl`,
`SetNamedSecurityInfo`, `RemoveAccessRuleSpecific`, `icacls`, `_apply_mask_to_path`, `_clear_deny`,
`_restore_dacls`, `recover_ace`, `execute_recovery`, `apply_subject_deny` or `apply_boundary` was
invoked. M052H remains the authoritative live evidence for T-BABY-1; no new measurement was taken.

## Provenance: read-only, untouched

```
ledger          : 14 valid, 0 malformed, 0 problems
sealed head     : PROV-000014, 0 problems
seals on disk   : 10
entries appended by M052V : 0
```

No entry appended, no seal minted or altered, no signing identity replaced, no historical provenance
touched. `HEAD.json`, `control.token` and `control.json` unmodified — `git status` over
`human_control/` and `var/` is empty. No key material was loaded for writing, printed, or
transmitted.

## Critical defect found and fixed: quoted-hypothetical false positive

**The failure.** The M052V prompt contains:

```
If the human supplies only "I choose R1" but does not supply the required
authority/provenance material: STOP at DECISION_RECORD_INCOMPLETE.
```

The parser matched `i choose r1` inside the quoted string and returned **R1**. The prompt was
*describing a case to refuse*; the parser read it as a selection of that case.

**Why this is the worst possible failure.** Every milestone in this chain exists to prevent the model
from manufacturing a director decision. Had the parser's output been acted on, M052V would have
recorded `RECOVERY_GOVERNANCE_DECISION = R1` — a fabricated decision — from a prompt that explicitly
says to stop. The gate designed to catch exactly this failure would have been the mechanism that
caused it.

**Why M052U did not catch it.** The M052U prompt contains no quoted first-person conditional, so it
returned `None` by coincidence of phrasing. The parser was sensitive to specification wording, which
is a live hazard: the next prompt that quotes a selection string would be read as one.

**The fix.** Two guards, applied before any selection is looked for:

1. **Quoted spans are removed.** A selection inside quotation marks is an example being shown, not
   a decision being made. Double quotes, single quotes, backticks and Unicode quotes are all handled.
2. **Hypothetical framing is refused.** `if`, `would`, `were`, `suppose`, `assume`, `hypothetical`,
   `for example`, `e.g.`, and similar framing cause an immediate refusal with a specific reason.

A selection found only inside quotation marks is refused with an explicit reason rather than silently
dropped.

**Verification.** The M052V prompt now returns `None`. The M052U prompt still returns `None`. All
genuine unquoted selections still parse. All quoted, hypothetical and example forms are refused.
Five new tests, including one that runs both milestone prompts through the parser and asserts neither
yields a selection.

## 30. Regression — nothing weakened, nothing new broken

```
M052S + M052K/L/N/O/P suite : 275 passed, 7 failed   (270 before; +5 new tests)
negative matrix              : 46/46 correct         (43 before; +3 quoted-hypothetical cases)
standing red baseline        : 12 failed, 65 passed — unchanged
```

Identical to M052U. The same 7 incident-caused M052K/M052L fingerprint assertions
(`test_production_is_unchanged_by_the_milestone`, `test_guard_passes_against_live_production`,
`test_all_fourteen_authorisation_conditions_pass`, `test_m019_a1_taxonomy_untouched`,
`test_full_validation_passes` in M052K; `test_production_is_unchanged`,
`test_full_validation_passes` in M052L). Evidence of the incident, not defects. Not weakened,
skipped, or deleted. **M052V introduced no new failures.**

## 31. Git

```
HEAD   : 6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555
branch : master
staged : 0
committed : NONE — nothing committed, amended, rebased, reset, pushed, or cleaned
modified tracked : 8, unchanged since M052Q; M052V modified no tracked file
```

New untracked: `docs/evidence/m052v-recovery-governance-decision.md`. M052S's two modules modified in
place (`tests/m052s_intake.py`, `tests/test_m052s_intake.py`). The seven pre-existing stray files were
left in place, not deleted for cleanliness. No historical evidence deleted or rewritten.

## 32. Next gate

```
M052V_STATUS    = DECISION_REQUIRED
M052V_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED
PRODUCTION_RECOVERY_PERFORMED = NO
```

The remaining blocker is a missing human input, not a missing mechanism. The intake accepts and
verifies a decision; the parser accepts every established valid form and now refuses quoted and
hypothetical ones; R1's structural separation is already in place; the provenance chain verifies
cleanly. Nothing further can be built that would change this outcome.

To advance, supply in the conversation:

1. an explicit selection — `I select R1.`, `My RECOVERY_GOVERNANCE decision is R2.`, or
   `I select R3 as the recovery governance class.`
2. the full 12-field record — `decision_id`, `authority_id`, `authority_type`, `rationale`, `scope`,
   `effective_for_milestone`, `exclusions`, `incident_reference`, `repository_HEAD`,
   `predecessor_decision_reference`, `supersedes`, with `authorises_production_recovery = FALSE`
3. a `provenance_seal_id` referring to an existing HUMAN-signed provenance entry whose canonical
   content hash equals the canonical JSON of that record.

M052V will verify and freeze it, and still will not execute recovery. Under R2 an A/B/C decision must
follow; under R3 a written `RECOVERY_GATE_2_POLICY` must follow.

---

## Non-cognitive scope

M052V concerns human governance, provenance, recovery classification, authority separation, ACL
recovery safety, and incident remediation. It establishes nothing about cognition, consciousness,
subjective experience, agency, learning, memory, intelligence, developmental stage, sentience, or
model inference. No option was selected or recommended as selected, no authority was manufactured or
reused, nothing was appended to the provenance ledger, no `RecoveryAuthorisation` or production
capability was created, no gate was opened, the accidental ACE was neither removed nor restored, D3
was not applied, the subject was not launched, and no production descriptor was altered.
