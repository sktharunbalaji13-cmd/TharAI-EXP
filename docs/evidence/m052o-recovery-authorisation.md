# M052O — Recovery Authorisation Architecture and Governance Gate

```
M052O_STATUS                        = AWAITING_RECOVERY_GOVERNANCE_DECISION

PRODUCTION_CHANGED                  = NO
PRODUCTION_RECOVERY_PERFORMED       = NO
ACCIDENTAL_ACE_STATUS               = STILL PRESENT
ACCIDENTAL_ACE_DISPOSITION          = PRESERVED_PENDING_EXPLICIT_RECOVERY_AUTHORISATION

GATE_1 = CLOSED    GATE_2 = CLOSED    GOVERNANCE_DECISION = NONE

D3_DENY            = NOT_APPLIED
SECURITY_OBJECTIVE = NOT_SATISFIED — shortfall 5 of 8 (unchanged)
T_BABY_1           = SATISFIED (M052H, unchanged)
SUBJECT_LAUNCH     = NOT_ATTEMPTED
D4                 = NOT_IMPLEMENTED

RECOVERY_WRITER_STATUS       = HARDENED, PRODUCTION REFUSED
RECOVERY_DISPOSABLE_REHEARSAL= EXACT_RECOVERY_AND_ROLLBACK_PROVEN
RECOVERY_AUTHORIZATION_STATUS= ABSENT

VALIDATION = 24/24 PASS · 36 tests · 21/21 matrix cases correct
```

> **This milestone prepared recovery and stopped.** The accidental ACE is still in production, exactly
> as M052N left it. No production ACL was read for anything other than evidence.

---

## 1. Incident state re-verified (read-only)

```
subject_runtime\runtime\m016_read_fixture.exe
  DENY  S-1-5-21-…-1022  mask=0x00000001  EXPLICIT     <- still present
  content  25 bytes  sha256 55250a71…    <- unchanged
  owner    S-1-5-21-…-1001              <- unchanged
  protected False                        <- unchanged
```

Full-tree audit: **this file is the only path carrying a subject ACE.** Root, `runtime`, `config`,
and the other two `m016_*` files all carry zero. No unexpected difference was found, so no stop was
triggered.

---

## 2. Three states, never conflated

| | Label | Content |
|---|---|---|
| **A** | `PRE_INCIDENT_REFERENCE` | v1 `f73eaf78…`, v2 `1684a02f…` — `HISTORICAL_PRESERVED_NEVER_REWRITTEN` |
| **B** | `INCIDENT_STATE` | current production: 1 accidental ACE on 1 file |
| **C** | `EXPECTED_RECOVERY_STATE` | B minus exactly that ACE — `exists_in_production: false` |

**C is built by subtracting the named ACE from B**, never by copying an old descriptor onto
production. A wholesale copy would silently revert anything else that had changed — the same class
of error as the incident itself.

### A projection error I made and corrected

My first `expected_recovery_state` hashed the incident's `subject_effective` and `subject_denied`
forward into the expectation. Those *necessarily change* when a deny is removed
(`0x001301BE → 0x001301BF`, denied `0x00000001 → 0x0`), so the expectation was unreachable by
construction and `EXACT_RECOVERY_PROVEN` failed for a reason that had nothing to do with the recovery.

The projection now covers only what recovery preserves — ACE list, owner, protection flag — and
reports effective access as a *consequence* of recovery rather than an input to it.

---

## 3. Recovery is a separate authority from D3

`ProductionAuthorisation` **cannot** represent recovery: it carries `deny_mask` and no
`expected_poststate`. It can neither name an ACE to *remove* nor bind a poststate. So a separate type:

```python
RecoveryAuthorisation(
    operation, target, principal_sid, ace_type, ace_mask, ace_scope,
    ace_inheritance_flags, expected_prestate_fingerprint,
    expected_poststate_fingerprint, mechanism_digest, nonce,
    failure_behaviour, issued_by, issued_at, milestone,
    recovery_is_not_d3=True, no_d3_application=True, owner_take=False, …)
```

Verified three ways: no `deny_mask` field exists; `recover_ace` has no code path that *adds* an ACE;
and a grant bearing the D3 mask is refused (matrix case 05).

`recover_ace` and `_ADD_SCRIPT` are separate constants — a writer that can only remove cannot apply
D3, and cannot restore a deny either.

---

## 4. Two real holes found by the matrix

Both were found **by execution**, not inspection. Both are fixed at the writer.

**Hole 1 — an empty prestate disabled the prestate check.** The guard read:

```python
if grant.prestate_fingerprint and _descriptor_hash(current) != grant.prestate_fingerprint:
```

A hand-built grant with `prestate_fingerprint=""` passed every other guard and **performed the
removal** (matrix case 11 returned `ACCEPTED_MUTATION`). A missing binding is not a satisfied
binding; the empty case is now an explicit violation.

**Hole 2 — grants were replayable.** The grant was a frozen dataclass and the writer never recorded
its use, so the same object performed two writes (matrix case 20 returned `ERROR` — raised *and*
mutated). Grants are now consumed **before** the write, so a failed recovery cannot be retried with
the same authority.

**A third defect, caught by a test rather than the matrix:** single-use was tracked with
`id(grant)`, and CPython reuses object addresses after collection — so a spent grant's address could
land on a *fresh* grant and wrongly refuse it. Now tracked by a `uuid4` token minted per grant.

---

## 5. Recovery matrix — 21 cases, all correct

Every refusal proven by descriptor comparison, never by a return value.

```
01_exact_valid_recovery          ACCEPTED_MUTATION      <- the only mutation
02_wrong_target                 REFUSED
03_wrong_sid                    REFUSED
04_wrong_mask                   REFUSED
05_d3_mask                      REFUSED
06_wrong_ace_type               REFUSED
07_wrong_inheritance            REFUSED
08_wrong_prestate               REFUSED
09_wrong_mechanism_digest       REFUSED
10_wrong_operation              REFUSED
11_no_grant                     REFUSED     <- was ACCEPTED_MUTATION before the fix
12_malformed_grant              REFUSED
13_forged_grant_wrong_target    REFUSED
14_spent_grant                  REFUSED
15_nonce_reuse                  REFUSED
16_production_target            REFUSED
17_second_recovery_after_success ERROR      <- first removal succeeded, second refused
18_broad_principal_grant        REFUSED
19_authorisation_invalid_op     REFUSED
20_replay_of_a_used_grant       ERROR      <- first removal succeeded, replay refused
21_replay_refused_in_isolation  REFUSED     <- clean single-use proof
```

Cases 17 and 20 are `ERROR` **correctly**: a first recovery succeeds, so the descriptor legitimately
moves during the case, and the refusal happens after. `ERROR` means "raised and mutated" — the honest
report when both occurred. Case 21 isolates the replay refusal against an unchanged descriptor.

---

## 6. Recovery and its rollback, both exact

```
incident  ──►  recovered  ──►  incident        (disposable fixture)
VERDICT = EXACT_RECOVERY_AND_ROLLBACK_PROVEN

recovery_exact              True    recovered == expected (B minus one ACE)
rollback_exact              True    returned to the incident hash exactly
unrelated_aces_preserved     True    4 inherited allows intact
owner_unchanged / protection_unchanged / content_unchanged   True
```

Recovery authority is **one-directional**: a `RESTORE_EXACT_ACE` authorisation is not mintable,
because `RECOVERY_OPERATION` is the only operation the schema accepts. The rollback therefore needs
its own authority, which is correct — it is a different production mutation.

---

## 7. Governance requirements — recorded, not decided

Recovery needs its own authorisation, its own capability, and its own interlock grant. All three
exist as of M052O; all three are closed.

**Unresolved:** whether recovery additionally requires the A/B/C decision. A/B/C governs how Gate 2
is opened for *future* production mutation; recovery is remediation of a *past* unauthorised one. If
the project requires A/B/C to authorise any production ACL write, recovery depends on it. If
remediation is a distinct class, it does not. **Recorded as a decision required, not decided.**

`GOVERNANCE_DECISION = NONE`. A/B/C remains `NONE`. This milestone did not decide it and the incident
does not authorise choosing.

---

## 8. Unchanged

- `control.json` — read-only, `NON_LOAD_BEARING`, not modified. Conclusion preserved from M052N.
- M052M and M052N evidence — not rewritten.
- Pre-incident fingerprints — preserved as historical reference.
- Production — no ACL, owner, inheritance, or artifact changed by M052O.
- 15 D3-gated properties remain DECISION-BLOCKED. No property promoted.
- `0x00000001` is `FILE_READ_DATA`, **not** one of the eight objective rights, so the accidental ACE
  contributes **no credit** toward D3.

---

## Non-claims

M052O concerns filesystem authorisation and governance only. It establishes nothing about cognition,
consciousness, subjective experience, agency, learning, memory, intelligence, developmental stage,
sentience, or model inference. A recovery procedure was designed and proved on disposable state; it
establishes nothing about any mind.
