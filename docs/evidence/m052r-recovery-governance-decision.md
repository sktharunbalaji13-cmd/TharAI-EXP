# M052R — Recovery Governance Decision Gate (explicit director selection required)

```
M052R_STATUS                       = DECISION_REQUIRED
M052R_NEXT_GATE                    = RECOVERY_GOVERNANCE_DECISION_REQUIRED

RECOVERY_GOVERNANCE_DECISION       = NONE
DECISION_AUTHORITY                 = NOT_SUPPLIED
PROVENANCE_SEAL_ID                 = NOT_SUPPLIED
DECISION_PROVENANCE                = NOT_APPLICABLE (nothing supplied to verify)

SELECTED_BY_OPERATOR               = NO
OPTION_SELECTED                    = NONE

PRODUCTION_CHANGED                 = NO
PRODUCTION_RECOVERY_PERFORMED      = NO
RECOVERY_AUTHORISATION             = NOT_ISSUED
RECOVERY_CAPABILITY_FOR_PRODUCTION = NO
ACCIDENTAL_ACE                     = STILL PRESENT (DENY …-1022, 0x00000001, explicit)

D3_DENY                            = NOT_APPLIED
SUBJECT_LAUNCH                     = NOT_ATTEMPTED
D4                                = NOT_IMPLEMENTED
GATE_1 = CLOSED    GATE_2 = CLOSED    A/B/C = NONE
T_BABY_1                           = SATISFIED (M052H, unchanged)
SECURITY_OBJECTIVE                 = NOT_SATISFIED — 5 of 8 forbidden rights present
```

> **M052R stopped at the first instruction.** The milestone required an explicit director decision
> selecting R1, R2 or R3 with an authority and a verifiable provenance seal. None was supplied in the
> repository or in the input. No option was selected. No authorisation was created. Production is
> descriptor-for-descriptor identical to the M052P start state.

---

## 1. The required human decision, and its absence

M052R changed the interaction mode: the decision now has to come from the director, explicitly. I
searched for it in every place the repository could legitimately hold one, and searched for
alternatives that would let me infer it. There are none.

| Where searched | Result |
|---|---|
| All `.md`/`.json`/`.py`/`.txt`/`.toml`/`.yml` under the repo (excluding `.git`, `.kilo`, caches) — regex for `RECOVERY_GOVERNANCE_DECISION`, `selected_option`, `RECOVERY_CLASSIFICATION` | only the value **`NONE`** (M052P ×2, M052Q, `m052p_governance.py`) |
| Filenames resembling a governance decision record | only M052J/M052D/M052E/M052M/M052P/M052Q — none is a recovery-governance decision |
| `git grep` over tracked `docs/`, `human_control/`, `foundation/`, `tests/` | 3 matches, all incidental `R1/R2/R3` substrings in unrelated code (`pe_inspect.py`, `test_m006_runtime.py`, `test_m008_subject.py`) |
| Provenance ledger `HEAD.json` | `PROV-000014`, `signing_role: HUMAN`, `total_entries: 14` |
| The 10 seals on disk (`PROV-000004`…`PROV-000014`) | **none** mentions recovery, R1/R2/R3, the incident, or any M052 milestone |
| Untracked tooling decision files (`.vibeskills/tmp/host-decision*.json`) | no R-option present; tool-generated, not human authority |
| The M052R master prompt itself | explicitly "not authorization" |

**The one `R1` string in the corpus is not a selection.** It sits at
`docs/evidence/m052q-recovery-governance-decision.md:143` inside the *schema requirement* line
`selected_option=R1|R2|R3` — a description of what a valid record must contain. Reading it as a
decision would be reading a template as authority.

### Classification

- Exactly one valid decision exists? **No — zero.**
- More than one conflicting decision? **No — nothing exists to conflict.**
- Apparent decision whose seal will not verify? **Not applicable — no seal was supplied.**

→ **`RECOVERY_GOVERNANCE_DECISION_REQUIRED`**, and STOP.

## 2. Statements that were explicitly not treated as a decision

| Input | Why it is not the requested classification |
|---|---|
| "I authorize recovery." | Authorises an *operation*, not a *governance class* |
| "use your recommendation." | Delegates the selection to the model |
| "pick the safest." | Same delegation |
| "proceed." | Same delegation |
| the M052R master prompt | Says of itself: "not authorization" |
| M052Q's comparative analysis | A recommendation is not a decision; M052Q declined to select |
| technical readiness (M052O proved exact recovery) | Readiness is not permission |

None of these appeared as an explicit `R1|R2|R3` selection, so none was acted on. Had one appeared, it
would have been refused as authority and reported.

## 3. Why I could not substitute an authority

The repository's established provenance mechanism is `provenance.ledger.ProvenanceLedger`, which offers
`verify()` (recomputes the chain, verifies every MAC under the named key, checks key fingerprints,
cross-checks recorded author against the keyring-derived role, checks `prev_entry_hash` linkage and
`prev_version_id` continuity) and `verify_seal()` (compares the live head against the last human-signed
`HEAD.json` seal — the only check that detects tail truncation). Both require a `Keyring`; the ledger
will not open without one.

I did **not** construct a `Keyring`, mint a seal, append an entry, or touch `HEAD.json`,
`control.token` or `control.json`. There is no such verification to perform anyway: no seal was
supplied to verify. Creating one would have been manufacturing the authority this milestone exists to
obtain from the director.

`ProvenanceLedger.__init__(path, keyring, ...)` was inspected read-only to describe the mechanism
accurately. No key material was loaded, requested, stored, or transmitted.

## 4. Production immutability — read-only verification, 9 of 9 required conditions

Verified without performing any mutation. No `Set-Acl`, `SetNamedSecurityInfo`,
`RemoveAccessRuleSpecific`, `icacls`, `_apply_mask_to_path`, `_clear_deny`, `_restore_dacls`,
`recover_ace`, `execute_recovery`, `apply_subject_deny` or `apply_boundary` was invoked. Refusal was
proven by descriptor comparison, never by attempting the forbidden operation.

| # | Condition | Observed |
|---|---|---|
| 1 | accidental ACE still present | **PRESENT**, explicit DENY, mask `0x00000001`, `FILE_READ_DATA`, SID `…-1022` |
| 2 | exact target | `subject_runtime/runtime/m016_read_fixture.exe` |
| 3 | owner unchanged | `THARUNBALAJI-LA\k.tharun balaji` |
| 4 | DACL protection unchanged | `access_rules_protected = False`, SDDL `D:AI(D;;CC;;;…-1022)(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1…)` |
| 5 | content unchanged | 25 bytes, sha256 `55250a71209a4d397dc51f3f12da105455a5d20ace53062416d26079fded0cdf` — matches M052O/M052P |
| 6 | unrelated ACEs unchanged | v1 `8a0a66323bb4eb3b18e62fd75cd65e1e`, v2 `7d592c7a03bf7a6f67b9021c307ec0cb` — **byte-identical to M052P start** |
| 7 | D3 absent | no ACE with mask `0x000D0156`; objective `NOT_SATISFIED`, shortfall 5 of 8 |
| 8 | gates unchanged | Gate 1 `CLOSED`; Gate 2 `CLOSED` (`AWAITING_DIRECTOR_DECISION`); A/B/C `NONE` |
| 9 | no authorisation / no capability / subject not launched | `RecoveryAuthorisation = NOT_ISSUED`; no production `RecoveryCapability`; `execute_recovery()` → `AWAITING_EXPLICIT_RECOVERY_AUTHORISATION`, `PRODUCTION_RECOVERY_PERFORMED: false`; subject `NOT_ATTEMPTED`, password value never read, no process running |

M052P's read-only reconciliation: **18/18 pass**, no failing check, `production_mutated_by_m052p = False`.

### The incident is still an incident

```
incident-state v1   8a0a66323bb4eb3b…      pre-incident v1   f73eaf783ffb2698…   PRESERVED
incident-state v2   7d592c7a03bf7a6f…      pre-incident v2   1684a02f028412e1…   PRESERVED
incident v1 != pre-incident v1 : True
```

The accidental state and the pre-incident fingerprint are both historical facts. Neither was rewritten,
and they were **not** made equal by rewriting either record.

### Preservation copies — 17 roots intact, none deleted

`%LOCALAPPDATA%\Temp`: `TharAI_M043_live` (5 files), `TharAI_M046_preserved_6eb3ed00426a499b` (5),
`TharAI_M049_live` (5), `TharAI_M050_preserved_a2f2301041e349d7` (5), `TharAI_M052B_live` (6),
`TharAI_M052B_preserved_e978330eb5e746c0` (6), `TharAI_M052H_live` (6),
`TharAI_M052H_preserved_0ff26391838144f5` (6), plus M030/M039/M042/M049 disposable roots. Nothing was
removed. These copies live in `%LOCALAPPDATA%\Temp`, not in the repository.

## 5. What each option would require — recorded, not chosen

The meanings are fixed. Summarised so the director can choose against something concrete.

**R1 — distinct governance class.** Recovery gets its own `RecoveryAuthorisation`,
`RecoveryCapability`, recovery interlock, exact target/ACE/prestate/poststate binding, mechanism
binding, single-use nonce and capability. Classifies only; authorises nothing. Leaves **A/B/C = NONE**
unless separately decided. Authority must be structurally unable to apply D3, add a deny, restore an
ACE, or target another path/principal/mask. On selection M052R would verify all eleven R1 conditions and
record `RECOVERY_CLASSIFICATION = R1`, `RECOVERY_EXECUTION = NOT_AUTHORIZED`.

**R2 — subject to the ordinary A/B/C Gate-2 policy.** Recovery stays technically distinct
(`RecoveryAuthorisation` ≠ `ProductionAuthorisation`; no authority types collapse), but its production
execution cannot advance until A/B/C is decided. With A/B/C currently `NONE`, selecting R2 yields
`A_B_C_DECISION_REQUIRED` immediately. I would not choose A/B/C either.

**R3 — distinct class with its own second-gate policy.** Requires a written `RECOVERY_GATE_2_POLICY`
that two independent readers could resolve to the same answer, specifying at minimum: what opens the
gate; who may open it; whether a second human approval is required; provenance/seal requirement;
capability requirement and exact scope; target, prestate and poststate binding; single-use semantics;
failure semantics; separation from D3; separation from rollback. A policy is **not** inferred from R3.
Incomplete or missing → `RECOVERY_GATE_2_POLICY_REQUIRED`.

**Costs, stated rather than hidden.** R1 creates a "remediation" precedent that could later be used to
smuggle ordinary mutation. R2 leaves production in the incident state for longer. R3 introduces a third
policy that must be kept consistent with the first two.

**No recommendation, ranking, or default is offered.** M052P already declined to select; technical
readiness is not permission.

## 6. Recovery authorisation remains a later, separate step

Even on a valid selection, `RecoveryAuthorisation` stays `NOT_ISSUED` through M052R. None was created.
A future one must bind exactly: one operation, target, principal SID, ACE type, ACE mask, ACE scope,
ACE inheritance flags, expected prestate fingerprint, expected poststate fingerprint, mechanism digest,
fresh nonce, `failure_behaviour = STOP_LEAVE_STATE_AS_FOUND`, issuer, timestamp and milestone, plus the
explicit negations `recovery_is_not_d3`, `no_d3_application`, `no_subject_launch`,
`no_d4_implementation`, `preserve_owner`, `preserve_inheritance`, `preserve_non_subject_aces`.

Rollback remains a separate authority from recovery.

## 7. Historical evidence

Unmodified: M052J, M052K, M052L, M052M, M052N, M052O, M052P, M052Q, and the pre-incident v1/v2
fingerprints. No historical conclusion was rewritten. No pre-incident fingerprint was altered to make
current state pass. No evidence file was deleted.

## 8. Regression — unchanged, nothing weakened

```
M052K/M052L/M052N/M052O/M052P suite :  230 passed, 7 failed
standing red baseline               :   12 failed, 65 passed
```

All 7 failures are the known incident-caused M052K/M052L pre-incident-fingerprint assertions:

| test | file |
|---|---|
| `test_production_is_unchanged_by_the_milestone` | `test_m052k_implementation.py` |
| `test_guard_passes_against_live_production` | `test_m052k_implementation.py` |
| `test_all_fourteen_authorisation_conditions_pass` | `test_m052k_implementation.py` |
| `test_m019_a1_taxonomy_untouched` | `test_m052k_implementation.py` |
| `test_full_validation_passes` | `test_m052k_implementation.py` |
| `test_production_is_unchanged` | `test_m052l_interlock.py` |
| `test_full_validation_passes` | `test_m052l_interlock.py` |

These assert a production fingerprint that no longer holds, because of the M052M incident. They are
evidence, not defects. They were **not** weakened, skipped, or deleted to obtain green. The standing red
baseline is likewise unchanged. **M052R introduced no new failures.**

M052R ran no disposable recovery test, so there was no disposable state requiring restoration.

## 9. Git / provenance

```
HEAD   : 6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555
branch : master
staged : 0 files
committed this milestone : NONE — nothing committed, amended, rebased, pushed, or cleaned
```

Modified tracked files: 8, unchanged from M052Q — `docs/evidence/m019-intended-production-boundary.md`,
`foundation/security_verify.py`, `foundation/staging.py`, `foundation/subject_deny.py`,
`tests/guarded.py`, `tests/test_boundary_harness.py`, `tests/test_subject_boundary_run.py`,
`tests/test_subject_deny.py`.

Untracked: the accumulated M020–M052Q evidence, modules and tests, including this milestone's single new
file `docs/evidence/m052r-recovery-governance-decision.md`. Also present and left untouched: seven stray
zero/small-byte files (`'`, `DACL`, `FAILED`, `IDENTITY_ESTABLISHED`, `process`, `str`, `tuple[int`,
dated 2026-10-04) from earlier shell quoting accidents. Not deleted — deletion requires instruction.

Provenance ledger untouched: `HEAD.json` still `PROV-000014` / 14 entries / `signing_role: HUMAN`;
`control.token` and `control.json` unmodified.

## 10. Final status

```
M052R_STATUS    = DECISION_REQUIRED
M052R_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED
```

`PRODUCTION_RECOVERY_PERFORMED = NO` in every branch. Not `READY_FOR_PRODUCTION_RECOVERY`.

To advance, supply an explicit `RECOVERY_GOVERNANCE` decision naming exactly one of R1 / R2 / R3, with
`authority_id`, `decision_text`/`rationale`, and a `provenance_seal_id` that is an existing, verifiable
human seal consistent with that selection. Under R2, A/B/C must follow. Under R3, a written
`RECOVERY_GATE_2_POLICY` must follow. Even then, recovery executes only in a later milestone under a
fresh, explicit `RecoveryAuthorisation`.

---

## Non-cognitive scope

M052R concerns governance classification, human authorisation provenance, recovery policy, authority
separation, and ACL recovery governance. It establishes nothing about cognition, consciousness,
subjective experience, agency, learning, memory, intelligence, developmental stage, sentience, model
inference, or subjective state. No option was chosen, no authority was manufactured or reused, no
authorisation or capability was created, no gate was opened, and no production descriptor was altered.