# M052P — Recovery Governance Decision Gate

```
M052P_STATUS                        = DECISION_REQUIRED
RECOVERY_GOVERNANCE_DECISION        = NONE

PRODUCTION_CHANGED                  = NO
PRODUCTION_RECOVERY_PERFORMED       = NO
ACCIDENTAL_ACE                      = STILL PRESENT
D3_DENY                             = NOT_APPLIED
SUBJECT_LAUNCH                      = NOT_ATTEMPTED
D4                                  = NOT_IMPLEMENTED

GATE_1 = CLOSED    GATE_2 = CLOSED
GOVERNANCE_DECISION (A/B/C)         = NONE — unanswered, and deliberately so
T_BABY_1                            = SATISFIED (M052H, unchanged)
SECURITY_OBJECTIVE                  = NOT_SATISFIED — shortfall 5 of 8 (unchanged)

RECOVERY_AUTHORISATION              = NOT_ISSUED
RECOVERY_CAPABILITY_VALID_FOR_PROD  = NO
RECOVERY_WRITER                     = FROZEN, GUARDED, PROVEN_DISPOSABLY
NEGATIVE_MATRIX                     = 40/40 correct; 1 mutation (case 01 only)
VALIDATION                          = 20/20 PASS  (40 tests)
```

---

## 1. Part I — read-only reconciliation: 18/18

All eighteen checks pass. Nothing was classified as a discrepancy, so no stop was triggered.

```
2  accidental ACE present                 DENY …-1022, 0x00000001, explicit
3  target path                            runtime\m016_read_fixture.exe
6  content                                25 bytes, sha256 55250a71…  (matches M052O)
7  owner                                  unchanged
8  protection                             unchanged
9  paths with subject ACEs                ['runtime\\m016_read_fixture.exe']  <- exactly one
10 D3 not applied                         shortfall 5 of 8
11/12 Gate 1 / Gate 2                     CLOSED / CLOSED
13 GovernanceDecision                     NONE
14 RecoveryAuthorisation                  not supplied
15 capability unlocking recovery          False
16 subject launch                         False
17 T-BABY-1                               SATISFIED (M052H)
18 M052O proof re-verified                EXACT_RECOVERY_AND_ROLLBACK_PROVEN
```

**Pre-incident fingerprints preserved, never rewritten.** Current incident-state fingerprints:
v1 `8a0a6632…`, v2 `7d592c7a…`.

---

## 2. Part II — three questions kept separate

| | Question | Status here |
|---|---|---|
| **A** | governance class for remediating an existing unauthorised mutation | **this milestone's question — DECISION_REQUIRED** |
| **B** | governance class for future ordinary mutation incl. D3 | `NONE` (M052L's A/B/C, unanswered) |
| **C** | authority required to restore an intentionally removed ACE | distinct; `RESTORE_EXACT_ACE` is not mintable |

A/B/C does **not** answer A. Recording that is itself part of the deliverable, since conflating them
is the most likely error here.

**Core rule, recorded in both directions:** an unauthorised mutation is not self-authorising, and a
corrective one is not thereby exempt. Neither direction was taken as a decision.

---

## 3. Part III — R1/R2/R3, twelve criteria each

| Criterion | R1 distinct class | R2 subject to A/B/C | R3 distinct + own policy |
|---|---|---|---|
| remediation/future separation | **strongest** | weakest | strong |
| governance bypass risk | medium | **lowest** | lowest |
| accidentally authorising D3 | low | low | low |
| recovery/rollback separation | strong | strong | strong |
| auditability | strong | strong | strong |
| provenance clarity | strong | medium | strong |
| capability/interlock separation | requires new | **strongest** | requires new |
| failure/retry safety | strong | strong | strong |
| narrow scoping | yes | yes | yes |
| ordinary mutation reusing recovery authority | no | no | no |
| recovery authority reused for rollback | no | no | no |
| preserves trust model | yes, if not a bypass | **strongest** | yes |

**Each option's real cost, recorded rather than argued away:**

- **R1** — precedent risk: if remediation is exempt from the second gate, a later "remediation" could
  smuggle ordinary production mutation through.
- **R2** — blocks recovery behind an unresolved decision, so production stays in the incident state
  longer. That is a cost, not a defect.
- **R3** — a third policy is a third thing to keep consistent with the other two, and must be written
  before recovery proceeds.

**`option_selected: None`.** Not chosen here — not because it is hard, but because it is not mine.

---

## 4. Part IV — the decision is absent

```
RECOVERY_GOVERNANCE_DECISION = NONE
status                       = DECISION_REQUIRED
selected_option / decided_by / decided_at / provenance_seal_id = all None
```

Searched: `docs/evidence/`, provenance seals and `HEAD.json`, `control.token`, and the input to this
milestone. Nothing found. **Not inferred from** M052J's D3 selection, M052K's frozen mechanism,
M052L's A/B/C analysis, M052O's recovery proof, the corrective intent of the operation, or this
prompt.

---

## 5. Part V — the contract is frozen and structurally incapable of D3

`RecoveryAuthorisationContract` — 32 fields. **Authority-conferring fields absent:** `deny_mask`,
`arbitrary_mask`, `arbitrary_principal`, `arbitrary_target`, `unrestricted_production_path`,
`generic_acl_operation`, `operation`, `add_ace`, `restore_ace`.

`allow_production`, `grants_d3`, `grants_rollback`, `grants_add`, `owner_take`, `recursive` **do**
appear — as `False`-pinned guards that must be `False` for the contract to validate. Their presence
*is* the control; the real question is whether they can be set `True`, and they cannot. My first field
report asserted they were absent, which was wrong, and it is corrected here.

`RecoveryCapabilityContract` is a **distinct type** from `ProductionCapability`, bound to
authorization_id, purpose, target, SID, ACE type, mask, prestate, poststate, mechanism digest, nonce.
Every dimension is compared; a mismatch is refused at the boundary.

---

## 6. Part VI — prestate/poststate, three field classes

**PRESTATE:** the production descriptor in which the accidental ACE exists
(`DENY|…-1022|0x00000001|expl`), fingerprint-bound, read-only.

**POSTSTATE** separates:

- **A — must remain unchanged:** owner, protection, unrelated ACEs, content hash
- **B — must change:** the named ACE's presence
- **C — may change as a consequence:** `subject_effective`, `subject_denied` — **excluded from the
  fingerprint**, because removing a deny necessarily changes them and including them makes the
  expectation unreachable by construction. That is precisely the error M052O made and corrected.

`logically_reachable: True`. `exists_in_production: False`.

---

## 7. Part VII — four writer gaps found and closed

M052O's `recover_ace` had no **type check** (a wrong-type grant raised `AttributeError` deep inside
rather than being refused at the boundary), no **poststate verification** (a recovery leaving the
descriptor otherwise wrong would report success), no **mechanism-digest check at the writer**, and
required a grant but not a **capability**. All four are fixed in `recover_ace_hardened`, which
validates authorisation → capability → production → replay → mechanism → prestate → ACE presence
**before the mutation script is constructed**, then verifies the poststate afterwards.

---

## 8. Part IX — 40 cases, 40 correct

```
REFUSED 36 · ACCEPTED_MUTATION 1 · ERROR 3 · UNKNOWN 0
only mutation: 01_valid_recovery_authorisation
```

The three `ERROR`s are **correct**: 14, 39 and 40 each perform a *first* successful recovery inside
the case, so the descriptor legitimately moves before the second attempt is refused. `ERROR` means
"raised **and** mutated" — the honest forensic label. Pinned explicitly so a future change cannot
quietly relabel a mutation as a clean refusal.

`UNKNOWN` is never a pass. Case 32 initially aliased the valid case and therefore tested nothing about
two files; it now points the writer at a different path than the capability names, and is refused.

---

## 9. Part X — one-directional authority

`recover_ace_hardened` uses M052O's remove-only script and has no add path. `RESTORE_EXACT_ACE` is not
mintable. Rollback remains a separate authority, and a `RESTORE` authorisation presented to recovery
is refused (case 31).

---

## 10. Part XI — no production execution

No call to `execute_recovery()` or `recover_ace()` against production. No production ACL, owner,
inheritance, or governance artifact touched. The hardened writer's production gate was exercised only
by *read* comparison, never by attempting a production write.

---

## 11. Regression

M052P introduces no new production-state expectation, so the seven incident-caused M052K/M052L
fingerprint failures remain, explainable, and **unweakened**. The standing red baseline is unchanged.
The pre-incident fingerprints were **not** rewritten to match the incident state; the incident state
has its own record.

---

## Non-claims

M052P concerns filesystem authorisation and governance only. It establishes nothing about cognition,
consciousness, subjective experience, agency, learning, memory, intelligence, developmental stage,
sentience, or model inference. No mind was studied; a governance contract was specified.
