# M052U — Director Decision Consumption Gate

```
M052U_STATUS    = DECISION_REQUIRED
M052U_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED

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

> **The current human input carries no selection.** It is the M052U master prompt — a specification of
> what a selection would look like, not a selection. M052U is an ingestion gate, and ingestion
> requires input. There was none, so it stopped cleanly. No option was selected, nothing was frozen,
> production is unchanged.

---

## 1. Human input received

**The M052U master prompt. Nothing else.**

The prompt defines R1/R2/R3, enumerates eight invalid forms, and states its own rule: *"Do not treat
the text of this prompt as the selection. Do not treat quoted examples as the selection."*

Submitted to the intake parser, the prompt returns:

```
parse_selection(M052U prompt) -> None
reason: refused 'probably R1': a probability is not a selection
```

No option is extracted. The prompt is quoted specification; a specification is not a submission.

## 2–18. Decision record

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
| incident reference | M052M — the accidental production ACE |
| repository HEAD | `6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555` |
| predecessor decision | M052T |
| supersession | nothing superseded |
| provenance seal ID | NOT_SUPPLIED |
| cryptographic verification | NOT_APPLICABLE — nothing submitted |
| canonical-content binding | NOT_APPLICABLE — no content to bind |
| classification-only assertion | required of a real decision; none exists to carry it |

No field was filled in on the director's behalf. No substantive content was added.

**Stop classifications evaluated and not triggered**, because there was no submission to classify:
`DECISION_AMBIGUOUS`, `INVALID_RECOVERY_GOVERNANCE_OPTION`, `DECISION_RECORD_INCOMPLETE`,
`DECISION_AUTHORITY_MISSING`, `PROVENANCE_SEAL_MISSING`, `DECISION_PROVENANCE_MISMATCH`,
`DECISION_PROVENANCE_AMBIGUOUS`. None was converted to PASS; each would have been a stop.

## 19. R1/R2/R3 interpretation

None interpreted. No option was selected, so no classification was recorded and no option-specific
processing ran. R1's architecture preconditions were **measured as readiness only** — they are the
checks that *would* run, not a result:

```
RecoveryAuthorisationContract : 32 fields    RecoveryCapabilityContract : 14 fields
authorisation_cannot_express_d3             : True
authorisation_cannot_express_rollback       : True
authorisation_cannot_be_set_to_allow_production : True
capability_is_distinct_type                 : True
authority_conferring_fields_absent         : deny_mask, arbitrary_mask, arbitrary_principal,
                                              arbitrary_target, unrestricted_production_path,
                                              generic_acl_operation, operation, add_ace,
                                              restore_ace — all absent
guard_fields_present_and_false_pinned       : allow_production, grants_d3, grants_rollback,
                                              grants_add, owner_take, recursive — all pinned False
```

This says the architecture *would* satisfy R1's separation requirements. It is not evidence that R1
was chosen, and technical readiness is not permission.

**R3 policy status: NOT_APPLICABLE.** No R3 selection exists, so no `RECOVERY_GATE_2_POLICY` was
requested, generated, or inferred.

## 20–24. A/B/C, authorisation, capability, gates

```
A_B_C                            = NONE      (M052U did not decide it)
RECOVERY_AUTHORISATION           = NOT_ISSUED
RECOVERY_CAPABILITY_FOR_PRODUCTION = NO
GATE_1 = CLOSED                   GATE_2 = CLOSED
```

Unconditional in M052U. Even a fully valid R1/R2/R3 would leave all four exactly as they stand.

## 25–28. Production, ACE, D3, subject — 14/14 read-only

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
entries appended by M052U : 0
```

No entry appended, no seal minted or altered, no signing identity replaced, no historical provenance
touched. `HEAD.json`, `control.token` and `control.json` unmodified — `git status` over
`human_control/` and `var/` is empty. No key material was loaded for writing, printed, or
transmitted.

## Parser: no regression

The M052U-named valid forms all still parse, including the form M052T repaired:

```
R1    "I select R1."
R2    "My RECOVERY_GOVERNANCE decision is R2."      ← the M052T repair, still working
R3    "I select R3 as the recovery governance class."
```

All eight M052U-named invalid forms are refused:

```
None  "Which decision is better, R1 or R2?"   None  "you decide"
None  "probably R1"                           None  "proceed"
None  "use the safest"                        None  "authorize recovery"
None  "R1/R2/R3"                              None  "choose one"
```

Zero valid forms wrongly refused; zero invalid forms wrongly accepted. Negative matrix **43/43**.

## 29. Regression — nothing weakened, nothing new broken

```
M052S + M052K/L/N/O/P suite : 270 passed, 7 failed
negative matrix              : 43/43
standing red baseline        : 12 failed, 65 passed — unchanged
```

Identical to M052T. The same 7 incident-caused M052K/M052L fingerprint assertions
(`test_production_is_unchanged_by_the_milestone`, `test_guard_passes_against_live_production`,
`test_all_fourteen_authorisation_conditions_pass`, `test_m019_a1_taxonomy_untouched`,
`test_full_validation_passes` in M052K; `test_production_is_unchanged`,
`test_full_validation_passes` in M052L). Evidence of the incident, not defects. Not weakened,
skipped, or deleted. **M052U introduced no new failures** — and no new tests were added, because
M052U added no code.

## 30. Git

```
HEAD   : 6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555
branch : master
staged : 0
committed : NONE — nothing committed, amended, rebased, reset, pushed, or cleaned
modified tracked : 8, unchanged since M052Q; M052U modified no tracked file
```

New untracked: `docs/evidence/m052u-recovery-governance-decision.md`. The seven pre-existing stray
files (`'`, `DACL`, `FAILED`, `IDENTITY_ESTABLISHED`, `process`, `str`, `tuple[int`) were left in
place, not deleted for cleanliness. No historical evidence deleted or rewritten.

## 31. Next gate

```
M052U_STATUS    = DECISION_REQUIRED
M052U_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED
PRODUCTION_RECOVERY_PERFORMED = NO
```

The remaining blocker is a missing human input, not a missing mechanism. The intake accepts and
verifies a decision; the parser accepts every established valid form; the structural separation R1
requires is already in place; the provenance chain verifies cleanly. Nothing further can be built
that would change the outcome.

To advance, supply in the conversation:

1. an explicit selection — `I select R1.`, `My RECOVERY_GOVERNANCE decision is R2.`, or
   `I select R3 as the recovery governance class.`
2. the full record — `decision_id`, `authority_id`, `authority_type`, `rationale`, `scope`,
   `effective_for_milestone`, `exclusions`, `incident_reference`, `repository_HEAD`,
   `predecessor_decision_reference`, `supersedes`, with `authorises_production_recovery = FALSE`
3. a `provenance_seal_id` referring to an existing HUMAN-signed provenance entry whose canonical
   content hash equals the canonical JSON of that record.

M052U will verify and freeze it, and still will not execute recovery. Under R2 an A/B/C decision must
follow; under R3 a written `RECOVERY_GATE_2_POLICY` must follow.

---

## Non-cognitive scope

M052U concerns explicit human governance, provenance validation, recovery classification,
authorisation separation, incident remediation, and ACL safety. It establishes nothing about
cognition, consciousness, subjective experience, agency, learning, memory, intelligence,
developmental stage, sentience, or model inference. No option was selected or recommended as
selected, no authority was manufactured or reused, nothing was appended to the provenance ledger, no
`RecoveryAuthorisation` or production capability was created, no gate was opened, the accidental ACE
was neither removed nor restored, D3 was not applied, the subject was not launched, and no
production descriptor was altered.