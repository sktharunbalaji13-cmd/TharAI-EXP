# M052J — D3 Deny-Mask Selection Decision

```
M052J_STATUS            = D3_DECISION_COMPLETE
D3_DECISION             = SELECTED
SELECTED_MASK           = 0x000D0156
SECURITY_OBJECTIVE      = COMPLETE COVERAGE (8 of 8 required rights)
M019_VERSION            = M019+A1   7dceb7a5d7c3632f8d2faca393535e26…

ACL_IMPLEMENTATION      = NOT_PERFORMED
PRODUCTION_CHANGED      = NO
PRODUCTION_ACL_CHANGED  = NO
PRODUCTION_FINGERPRINT  = UNCHANGED
SUBJECT_LAUNCH          = NOT_ATTEMPTED
T_BABY_1                = SATISFIED (established_by M052H, unchanged)
M019+A1                 = UNCHANGED
D4_STATUS               = NOW_ELIGIBLE_TO_BE_DECIDED
VALIDATION              = 12/12 PASS  (20 tests)
```

> **This milestone selects a security design. It does not modify production.**
>
> No ACL was changed, no deny ACE was added, no inheritance or ownership was touched, no subject
> was launched, no mask was implemented. The selected mask is an **approved design input** for a
> future implementation milestone.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. The question, reconstructed from the records

Not from memory of earlier mask discussion. The objective is stated as **rights**, and the mask is
derived **from** it, so the constant can never become the specification by being the only thing read:

```
write            0x00000002   T-WR-1     write_dac         0x00040000   T-WR-6
append           0x00000004   T-WR-2     write_owner       0x00080000   T-WR-7
write_ea         0x00000010   T-WR-8     delete            0x00010000   T-WR-3
delete_child     0x00000040   T-WR-4     write_attributes  0x00000100   T-WR-9

OR of all eight  ->  0x000D0156
cross-check: derive_subject_deny_mask() == 0x000D0156   AGREE
```

The property list and the mask agree, independently derived. That is the only reason the numeric
constant can be trusted as an *output*.

---

## 2. Rights matrix

Decoded from `foundation.security_verify.BIT_NAMES`, never from a hand-written table:

| Right | Bit | Required by objective | Denied by `0x000D0156` | Unintended deny |
|---|---|---|---|---|
| FILE_WRITE_DATA | `0x00000002` | yes | yes | — |
| FILE_APPEND_DATA | `0x00000004` | yes | yes | — |
| FILE_WRITE_EA | `0x00000010` | yes | yes | — |
| FILE_DELETE_CHILD | `0x00000040` | yes | yes | — |
| FILE_WRITE_ATTRIBUTES | `0x00000100` | yes | yes | — |
| DELETE | `0x00010000` | yes | yes | — |
| WRITE_DAC | `0x00040000` | yes | yes | — |
| WRITE_OWNER | `0x00080000` | yes | yes | — |
| READ_CONTROL | `0x00020000` | no | **no** | none |
| FILE_READ_DATA | `0x00000001` | no | **no** | none |
| FILE_READ_ATTRIBUTES | `0x00000080` | no | **no** | none |
| FILE_READ_EA | `0x00000008` | no | **no** | none |
| FILE_EXECUTE | `0x00000020` | no | **no** | none |
| SYNCHRONIZE | `0x00100000` | no | **no** | none |

`GENERIC_*` folding was applied (`expand_generic`) before comparison, so a full-control grant read as
concrete bits rather than triggering a false violation on every `(F)` ACE.

---

## 3. Candidate comparison — verdicts before ranking

| Candidate | Mask | Coverage | Missing | Extra | Verdict |
|---|---|---|---|---|---|
| **A** deny_backstop_protected | `0x000D0156` | COMPLETE | — | — | **SATISFIES_T** |
| **B** deny_backstop_inherited | `0x000D0156` | COMPLETE | — | — | **SATISFIES_T** |
| **C** allow_list_only | `0x00000000` | INCOMPLETE | all 8 | — | DOES_NOT_SATISFY_T |
| **D** legacy_deny_00110156 | `0x00110156` | INCOMPLETE | `write_dac`, `write_owner` | `SYNCHRONIZE` | DOES_NOT_SATISFY_T |
| **E** exact_deny_no_synchronize | `0x000D0156` | COMPLETE | — | — | **SATISFIES_T** |
| **F** admin_via_group_only | `0x000D0156` | COMPLETE | — | — | DOES_NOT_SATISFY_T |

**Candidate D — the mask named in the brief — fails.** It omits `WRITE_DAC` and `WRITE_OWNER`, so
T-WR-6 and T-WR-7 are unsatisfied. Its bundled `SYNCHRONIZE` is *inert* (§4).

**Candidate C** denies nothing and relies on absent grants. Production currently *grants* those
rights through an inherited `Authenticated Users:(I) Modify` ACE, so absence is not the state; an
allow-list would be a broader rewrite, not a narrower boundary.

**Candidate F** has complete deny coverage but rests administrative access on group membership alone,
which fails **T-ADM-4** — the observed operator token's Administrators group is filtered, so
membership confers no authority.

### 3.1 The trap this avoids

Five of the eight objective rights are present in production today. A candidate denying exactly those
five would score perfectly against the current configuration while failing T-WR-6 and T-WR-7.
Coverage is therefore scored against the **objective**, never against the incident.

---

## 4. SYNCHRONIZE — measured, not assumed

M020 recorded that this host's normalisation is asymmetric: an Allow ACE written without SYNCHRONIZE
gains it; a Deny ACE written **with** it loses it. That was re-measured on a disposable fixture:

| Candidate | Requested | **Stored by Windows** | Equal? | S req | S stored |
|---|---|---|---|---|---|
| A | `0x000D0156` | `0x000D0156` | yes | false | false |
| B | `0x000D0156` | `0x000D0156` | yes | false | false |
| E | `0x000D0156` | `0x000D0156` | yes | false | false |
| **D** | `0x00110156` | **`0x00010156`** | **no** | true | **false** |

Candidate D requested SYNCHRONIZE and Windows **removed it**. So D cannot be credited with denying
SYNCHRONIZE at all — the bit is inert, and numeric arithmetic alone would have claimed otherwise.

This also converts a previously-assumed claim into an observation: `boundary_design` predicted that A
and E converge on the same stored descriptor. They do — both store `0x000D0156` exactly.

M020's second finding is carried too: **same-SID Allow ACEs coalesce on addition**, so no candidate's
correctness may depend on two distinct same-SID Allow ACEs being kept apart.

---

## 5. Recovery analysis

The mask denies `WRITE_DAC` and `WRITE_OWNER` **to the subject**. It does not deny them to the
operator. Subject (`…-1022`) and operator (`…-1001`) are **disjoint SIDs**, so a per-subject deny
leaves the operator's own `WRITE_DAC` intact and the deny removable — which is exactly what T-ADM-1
requires.

```
recovery_verdict = RECOVERABLE
```

**But recovery is a property of how the deny is applied, not of the mask.** M016 recorded a
containment deny that became unrecoverable. The same mask would become unrecoverable if applied
group-wide, or to any principal the operator also belongs to.

> **CONSTRAINT ON M052K:** apply the deny **per-SID against `BABY_AI_TEST` only**. Never name
> Everyone, Authenticated Users, Users, or BUILTIN\Administrators.

**Not tested here.** No deny was applied to production, so recovery is *argued* from principal
disjointness plus M019's measured operator authority — not demonstrated end to end. Demonstrating it
is M052K's work, on a disposable fixture first.

---

## 6. Administrative access

The operator is **not** elevated by being in Administrators; the observed token's group is filtered.
Administrative access must therefore come from explicit ACL authority — which is exactly why
candidate F is scored as failing T-ADM-4 rather than accepted.

A per-subject deny does not reach the operator (no SID overlap). A deny naming a broader principal
would violate T-ADM-1 through T-ADM-3. **The mask alone cannot prevent that**, so M052K must apply it
per-SID and verify on a disposable fixture that operator effective access is unchanged afterwards.

---

## 7. Disposable rehearsal

The only mutation performed anywhere in this milestone. Location: system temp, disposable,
per-candidate, authorised by `tests.path_policy.assert_test_write_path` — the project's single
mutation gate, which refuses any path inside the repository *before* any filesystem, ACL or subprocess
work happens. Fixture verified outside the repository; removed after each candidate.

```
production_touched : False
evidence_class     : DISPOSABLE_CANDIDATE_REHEARSAL_NOT_PRODUCTION
```

Post-rehearsal production re-verified: fingerprints exact, subject ACEs **0 of 8**, `STAGING_BLOCKED`.

---

## 8. The decision

```
D3_DECISION              = SELECTED
SELECTED_MASK            = 0x000D0156
selected candidates       = A_deny_backstop_protected
                            B_deny_backstop_inherited
                            E_exact_deny_no_synchronize
DERIVATION               = OR of the eight T-WR objective rights, decoded from the
                           authoritative Windows definitions; cross-checks against
                           derive_subject_deny_mask()
SECURITY_OBJECTIVE       = COMPLETE (8 of 8)
RECOVERY_CONSTRAINT      = per-subject, per-SID application only — a constraint on M052K
ADMIN_CONSTRAINT         = must not name a principal the operator belongs to — M052K
SUBJECT_CONSTRAINT       = read, attribute, EA and runtime execute retained; T-BABY-5's
                           data-execute conjunct remains unmeasurable (config\ is empty)
```

The three satisfying candidates carry **the same mask** and differ only in *strategy* — protected
descriptor, inherited, or explicit-without-SYNCHRONIZE. The mask decision is therefore unanimous. The
strategy choice belongs to M052K and is not made here.

### 8.1 What this decision does not do

It authorises nothing. Not `icacls`, not `SetNamedSecurityInfo`, not a PowerShell ACL modification,
not an inheritance change, not an ownership change, not production containment. It also does not
change the standing finding: the security objective remains **NOT SATISFIED**, 5 of 8 required
denials absent, because selecting a mask does not apply one.

---

## 9. Dependency impact — recomputed, nothing marked satisfied

```
D3 gates            : 15 properties
D4 status           : NOW_ELIGIBLE_TO_BE_DECIDED  (depends on D3)
marked SATISFIED    : []
```

D4 asks *how* T-WR-1..10 are closed, and that cannot be answered before the objective is defined — so
D4 becomes decidable now. M052I's analysis indicates the route is remediation plus a descriptor
re-read rather than a subject-run mutation experiment.

**No property moves to SATISFIED.** D3 defines an objective; it measures nothing. Every T-WR property
remains unestablished until M052K applies a mask and the descriptor is re-read.

---

## 10. Validation — 12/12 PASS

```
 1 masks decoded from authoritative definitions        PASS
 2 required rights represented correctly              PASS
 3 candidate comparison is deterministic               PASS
 4 SYNCHRONIZE semantics not assumed                  PASS
 5 WRITE_DAC recovery risk represented                 PASS
 6 DELETE / DELETE_CHILD implications represented      PASS
 7 same-SID coalescing represented                     PASS
 8 production paths never passed to mutation helpers   PASS
 9 no production ACL mutation occurred                 PASS
10 D3 decision reproducible from the matrix           PASS
11 no downstream property falsely marked satisfied     PASS
12 T-BABY-1 still SATISFIED by M052H                   PASS
```

20 tests pass. Two failures during this milestone were both in **my** work, not the evidence: a
malformed assertion, and a genuine gap where the admin constraint failed to name M052K as the
milestone that must satisfy it — now recorded as a constraint on that milestone.

---

## 11. Status

```
M052J_STATUS           = D3_DECISION_COMPLETE
D3_DECISION            = SELECTED
SELECTED_MASK          = 0x000D0156
PRODUCTION_CHANGED     = NO
PRODUCTION_ACL_CHANGED = NO
SUBJECT_LAUNCH         = NOT_ATTEMPTED
T_BABY_1               = SATISFIED
M019+A1                = UNCHANGED
NEXT_GATE              = M052K — implementation of the selected mask, disposable rehearsal
                          first, with the per-SID constraint above binding.
```

**D3 concerns filesystem authorization only.** It establishes nothing about cognition, consciousness,
subjective experience, agency, learning, memory, intelligence, developmental stage, sentience, or
model inference. The mask was selected because eight named rights must be denied — not because
anything was learned about a mind.