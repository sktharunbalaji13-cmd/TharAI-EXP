# M019 — Intended Production Boundary Specification

> ## Amendment history
>
> | amendment | decision | date | sections changed | effect |
> |---|---|---|---|---|
> | **A1** | **D6-B** `RESCOPE_T_BABY_1_NAMESPACE` (M052E) | 2026-10-04 | **§19 added** (new); **§8 T-BABY-1 row annotated** (pointer only) | T-BABY-1's permitted **observation source** extended to a governed measurement namespace outside canonical T. **T-PATH-1, T-PATH-2, canonical T, and the security objective are unchanged.** |
>
> **Before A1:** `sha256 = 33dde443a6d35542f157f8027a18b6d0e68d27432d90eef082e6f3013a9139c0`, 32602 B.
> Amendment record: `docs/evidence/m052f-m019-d6b-amendment.md`.
> Decision record: `docs/evidence/m052e-d6-topology-contract-decision.md`.
>
> Sections 1–18 are the original M019 text and are preserved verbatim. A1 is **additive**: it
> annotates one row and appends §19. No original requirement was deleted, weakened, or redefined.

**M019_BOUNDARY_SPEC = PASS**
**PRODUCTION_TOUCHED = NO**
**OWNERSHIP_INVARIANT = ESTABLISHED**
**TRAVERSAL_INVARIANT = ESTABLISHED**
**WRITE_CONTROL_SPEC = COMPLETE**
**ADMIN_ACCESS_SPEC = COMPLETE**
**BABY_AI_BOUNDARY_SPEC = COMPLETE**
**T_DEFINED = YES**
**T_VS_C_DELTA = COMPLETE**
**T_VS_R_DELTA = COMPLETE**
**EXACT_ACE_STATUS = NOT_ESTABLISHED**
**HARNESS_SAFETY = VERIFIED**
**PRODUCTION_RECOVERY = NOT_ATTEMPTED**
**MECHANISM_SELECTED = NO**

Specification milestone. No production ACL, ownership, inheritance or file was
changed; no mechanism or mask was selected; no recovery attempted. Date 2026-10-01.
HEAD `3c91b340e9a5d28c32f351700d4f7b3d514f1cf4`, nothing committed.

---

## 1. Scope and non-mutation declaration

M018 proved the problem is **policy definition**, not implementation. This milestone
resolves the three specification gaps it exposed and defines **T**.

**Not done:** production ACL/ownership/inheritance change; anything created,
deleted, renamed or replaced under production `subject_runtime`; containment;
restoration; recovery-mechanism testing against production; inheritance experiments
against production; selection or implementation of any recovery mechanism or deny
mask.

Two disciplines held throughout:

- **No mask is selected.** Security properties are specified first; mask choice is
  downstream implementation (§10).
- **No conclusion is drawn by inferring OS behaviour from an ACL mask.** Where M018
  did exactly that, this milestone corrects it against measurement (§5).

## 2. Definitions of P0, P1, R, C and T

| symbol | object | epistemic status | established in |
|---|---|---|---|
| **P0** | historical observed production state, pre-incident, **including contamination** | RECORDED | M018 |
| **P1** | current observed production state, canonical recipe v1 | OBSERVED | M018 |
| **R** | historical restoration candidate — the recorded snapshot | RECORDED | M018 |
| **C** | existing M015 boundary specification, as asserted by `verify_boundary` | SPECIFIED (read from code) | M018 |
| **T** | **intended future production boundary target** — testable security invariants plus required evidence | **SPECIFIED by this milestone** | M019 |

**T is a new object.** It is not R adopted, not C implemented mechanically, not an
ACL, and not a procedure. T is what the laboratory *wants the production security
state to be*, expressed as properties that can be falsified.

The relationship that matters: **R cannot serve as the definition of T**, and C is
neither sufficient nor complete. §12 and §13.

## 3. Security objective inherited from M017

M017 Objective A, carried forward unchanged as T's root objective:

> No principal outside the intended subject boundary can obtain write, append,
> delete, rename, replace, `WRITE_DAC`, `WRITE_OWNER`, `WRITE_EA` or
> `WRITE_ATTRIBUTES` on any path under `subject_runtime`, while operator, SYSTEM and
> Administrators retain administrative access, and `BABY_AI_TEST` gains nothing
> beyond its explicitly intended capabilities.

M017 added the constraint that this must be expressed **without** selecting a
mechanism, and that effective access, descriptor state, inheritance state and
reversibility are recorded **separately**. Both are inherited.

## 4. Ownership invariant

### M018's blocker, resolved

M018 found **R cannot establish C5**, because the recorded snapshot has no owner
field — the invariant was unverifiable *by construction*, not merely unobserved.
M019 resolved this by **fresh read-only observation**, not by inference from ACLs or
group membership.

### Observation (read-only, this milestone)

| path | owner | owner SID | expected administrative identity? | owned by `BABY_AI_TEST`? |
|---|---|---|---|---|
| `subject_runtime` | `THARUNBALAJI-LA\k.tharun balaji` | `S-1-5-21-…-1001` | **yes** (operator) | no |
| `subject_runtime/runtime` | `THARUNBALAJI-LA\k.tharun balaji` | `S-1-5-21-…-1001` | **yes** | no |
| `subject_runtime/config` | `THARUNBALAJI-LA\k.tharun balaji` | `S-1-5-21-…-1001` | **yes** | no |
| `subject_runtime/model` | **ABSENT** | — | — | — |

Whole-tree sweep: **no path under `subject_runtime` is owned by `BABY_AI_TEST`.**

- method: `(Get-Acl -LiteralPath <path>).Owner`, then
  `NTAccount → SecurityIdentifier` translation for the SID;
- evidence source: `outputs/evidence/m018-canonical-state/P1_current_production_v2_owner.json`;
- epistemic status: **OBSERVED** for the three present paths;
  **NOT OBSERVABLE** for `model\`, which does not exist.

### T-OWN — the invariant

| property | requirement | status |
|---|---|---|
| **T-OWN-1** | Every path under `subject_runtime` is owned by the operator identity (`S-1-5-21-…-1001`) | **ESTABLISHED** for all 3 observable paths |
| **T-OWN-2** | `BABY_AI_TEST` (`…-1022`) owns **no** path under `subject_runtime` | **ESTABLISHED** |
| **T-OWN-3** | `model\` ownership satisfies T-OWN-1 | **NOT ESTABLISHED** — path absent |
| **T-OWN-4** | Ownership is *observed*, never inferred from DACL entries or group membership | **ESTABLISHED** (method recorded) |

### Why ownership is a first-class invariant

Ownership is a separate capability from the DACL. **An owner may rewrite the DACL
regardless of what the DACL grants**, and a deny on `WRITE_DAC` does not prevent it,
because taking ownership is a different right. A tree the subject owns is a tree the
subject can unlock, so an ACL-only boundary would be bypassable by ownership alone.

### Evidence schema change

The canonical recipe **cannot express ownership**, which is why R could not establish
C5. A new recipe version was added — **v1 was not modified**:

```
v1  babylab/production-acl-fingerprint/v1   5 fields   (unchanged)
v2  babylab/production-acl-fingerprint/v2   7 fields   = v1 + owner, owner_sid
```

v1 remains the default, and a **golden-value test** asserts a fixed v1 input still
hashes to the value it produced before v2 existed. That is the only proof the
addition was not silent.

```
P1 v1  f73eaf783ffb2698087a3053fbf90f261f832b5036d78d3a88a0a6526380e0d5   unchanged
P1 v2  1684a02f028412e1c23fcb8aa2c31e6487409f75bd106f1c57e5926708368e20
```

## 5. Traversal invariant

### M018's finding was an inference, and it is wrong

M018 recorded, from R, that root allow `0x00120089` "lacks `FILE_TRAVERSE`, so the
subject cannot descend the tree at all", and carried it forward as G5.

**That inference is refuted by measurement.** The corrected probe (schema `probe/v2`)
was run against a mirror whose root allow was **exactly `0x00120089`** — identical to
R's root, confirmed in `m016-subject-deny-rehearsal8.md`:

```
probe=traverse_to_leaf       result=OS_ALLOWED  capability=FILE_TRAVERSE
probe=traverse_leaf_read     result=OS_ALLOWED  capability=FILE_TRAVERSE
probe=traverse_ancestor_list result=OS_ALLOWED  capability=FILE_LIST_DIRECTORY
probe=enumerate_runtime      result=OS_ALLOWED  entries=3
probe=read_file_bytes        result=OS_ALLOWED  bytes_observed=14
```

The subject **could** traverse and read a boundary whose root allow mask is
byte-identical to R's. The mechanism is visible in the same run's token:
`SeChangeNotifyPrivilege` is present, and it bypasses `FILE_TRAVERSE` checking.

The earlier, conflicting `traverse_directory result=OS_DENIED` came from the **v1
probe**, whose operation names conflated traversal with listing — a defect the probe
source itself documents. The corrected probe is authoritative.

**Therefore: `0x20` does not need to be added, and must not be added on the strength
of the M018 inference.** Adding a right because a mask appears to lack it, when the
OS measurement shows the behaviour already works, would be changing a working
boundary to satisfy a misreading.

### The semantic requirement

Traversal is required **semantically**, and for a reason independent of any mask: T
must let the subject *reach and read* `runtime`, `model` and `config`. Without
traversal the allow grants in C are unusable, so traversal is entailed by C's own
intent rather than being a separate wish.

### The four representations, kept distinct

| layer | statement | status |
|---|---|---|
| **semantic requirement** | the subject must be able to traverse `subject_runtime` and descend into `runtime`, `model`, `config` | **ESTABLISHED** (entailed by C's intent; corroborated by measurement) |
| **ACL representation** | not expressible in the icacls letter set used by `verify_boundary` (`R`, `RX`, `M`, `F`, …) — `FILE_TRAVERSE` has no letter | **LIMITATION** |
| **verifier representation** | `verify_boundary` compares **expanded letters**, so it cannot assert traversal at all; it would pass a tree where traversal is denied | **LIMITATION** |
| **observed behaviour** | traversal `OS_ALLOWED` under a boundary with root allow `0x00120089` | **OBSERVED**, mirror, corrected probe |

### T-TRAV — the invariant

| property | requirement | status |
|---|---|---|
| **T-TRAV-1** | The subject can traverse `subject_runtime` | **ESTABLISHED** semantically; verification method **REQUIRES IMPLEMENTATION** |
| **T-TRAV-2** | The subject can descend into `runtime`, `model`, `config` | **ESTABLISHED** semantically |
| **T-TRAV-3** | Traversal denial is *not* relied upon as a security control | **ESTABLISHED** — `SeChangeNotifyPrivilege` makes the ACE non-load-bearing, so no invariant may depend on it |
| **T-TRAV-4** | Traversal is verified by **OS measurement under the real subject identity**, never by ACL letter comparison | **REQUIRES IMPLEMENTATION** — the letter-based verifier cannot express it |

**T-TRAV-3 is the important one.** Because `SeChangeNotifyPrivilege` bypasses
`FILE_TRAVERSE`, a design that appears to protect a subtree by withholding that bit
is not protecting anything. Any future proposal relying on it must be rejected.

## 6. Write / control invariants

Expressed at **property level**. No mask appears in this section by design (§10).

| id | property | required state | subject | allowed principals | prohibited principals | evidence required | verification | currently established? |
|---|---|---|---|---|---|---|---|---|
| **T-WR-1** | file/directory content write | **denied** | `BABY_AI_TEST` | operator, SYSTEM, Administrators | `BABY_AI_TEST`, `Authenticated Users`, `Users` | DACL + subject-run denial | OS measurement under subject | **NO** — P1 exposes AU Modify |
| **T-WR-2** | append | **denied** | `BABY_AI_TEST` | as above | as above | as above | OS measurement | **NO** |
| **T-WR-3** | delete (`DELETE`) | **denied** | `BABY_AI_TEST` | as above | as above | as above | OS measurement | **NO** |
| **T-WR-4** | delete child (`DELETE_CHILD`) | **denied** | `BABY_AI_TEST` | as above | as above | as above | OS measurement | **NO** |
| **T-WR-5** | rename / replace | **denied** | `BABY_AI_TEST` | as above | as above | as above | OS measurement | **NO** |
| **T-WR-6** | `WRITE_DAC` | **denied** | `BABY_AI_TEST` | as above | as above | DACL + denial | OS measurement | **NO** — R does not enforce it |
| **T-WR-7** | `WRITE_OWNER` | **denied** | `BABY_AI_TEST` | as above | as above | DACL + denial | OS measurement | **NO** — R does not enforce it |
| **T-WR-8** | `WRITE_EA` | **denied** | `BABY_AI_TEST` | as above | as above | DACL + denial | OS measurement | **NO** — not enforced in P1 |
| **T-WR-9** | `WRITE_ATTRIBUTES` | **denied** | `BABY_AI_TEST` | as above | as above | DACL + denial | OS measurement | **NO** — not enforced in P1 |
| **T-WR-10** | create file / create child directory | **denied** | `BABY_AI_TEST` | as above | as above | DACL + denial | OS measurement | **NO** |
| **T-WR-11** | no inherited `Authenticated Users:(I)` Modify anywhere | **absent** | all | — | AU | DACL | ACL inspection | **NO** — present in P1 |

**T-WR-11 is the only property whose violation is currently observable without a
subject run**, because P1 still carries inherited AU Modify. The rest require a real
subject process and are therefore **NOT_ESTABLISHED** as measurements even where the
ACL nominally covers them.

**Requirement, not candidate:** T requires write/append/delete/rename/replace/
`WRITE_DAC`/`WRITE_OWNER`/`WRITE_EA`/`WRITE_ATTRIBUTES` to be denied to
`BABY_AI_TEST`, and requires `WRITE_DAC`/`WRITE_OWNER` specifically. Which mask
satisfies that is a downstream decision (§10).

## 7. Administrative-access invariants

| id | property | required state | status |
|---|---|---|---|
| **T-ADM-1** | operator (`…-1001`) retains full control on every path under `subject_runtime` | required | **ESTABLISHED** in P1 via explicit/inherited grants; **REQUIRES IMPLEMENTATION** under a new boundary |
| **T-ADM-2** | SYSTEM retains full control on every path | required | **ESTABLISHED** in P1 |
| **T-ADM-3** | `BUILTIN\Administrators` retains full control on every path | required | **ESTABLISHED** in P1 as an ACE; **see T-ADM-4** |
| **T-ADM-4** | Administrative capability must not depend on an unelevated token | required | **ESTABLISHED — currently violated in this session's context** |
| **T-ADM-5** | no administrative access is lost by any future transformation | required | **REQUIRES REHEARSAL** |

### T-ADM-4 — a live observation

The inspecting process reports `IsInRole(Administrator) = **False**`, and
`whoami /groups` shows `BUILTIN\Administrators` as **"Group used for deny only"**.
The operator account is an administrator, but its token in this context is **not
elevated**, so the Administrators SID is present but deny-only.

Two consequences:

1. The operator's administrative access in P1 and R comes from an **explicit ACE**,
   not from group membership. T must not assume the group path works.
2. This independently corroborates M015's blocker: `Set-Acl` and
   `SetSecurityDescriptorSddlForm` demanded `SeSecurityPrivilege`, which an
   unelevated operator token does not hold.

### Explicit prohibitions, carried forward

- **A principal-wide `/remove:g <admin>` is not an acceptable administrative
  operation.** It removed the operator's pre-existing `0x00120089` access in the
  exact-topology rehearsal, which is why that rollback was rejected.
- **No transformation may assume `/inheritance:d` or `/inheritance:e` preserve
  same-SID ACE semantics.** Established lossy on this host (M016, permanently
  rejected).
- **The rejected M016 containment design is not an admissible mechanism** for
  satisfying any T-ADM property.
- **A containment deny that includes `WRITE_DAC` or `DELETE` is unrecoverable by
  construction** — observed when a rehearsal deny blocked its own directory cleanup.
  `WRITE_DAC` must remain outside any deny mask, or the deny cannot be undone.

## 8. BABY_AI_TEST invariants

Defined from M015's **intent** (`apply_boundary`'s per-subtree grants, and C3), not
inferred from the current damaged ACL. Current capabilities are P1, which is
damaged and establishes nothing.

| id | capability | intended for `subject_runtime` | intended for `runtime` | intended for `model` / `config` | status |
|---|---|---|---|---|---|
| **T-BABY-1** | read data | yes | yes | yes | REQUIRES IMPLEMENTATION — observation source governed by **A1** (§19); intent columns unchanged |
| **T-BABY-2** | read attributes / EA | yes | yes | yes | REQUIRES IMPLEMENTATION |
| **T-BABY-3** | list directory | yes | yes | yes | REQUIRES IMPLEMENTATION |
| **T-BABY-4** | traverse | yes | yes | yes | ESTABLISHED semantically (§5) |
| **T-BABY-5** | execute | **no** | **yes** — the runtime must be loadable | **no** — data must not be executable | REQUIRES IMPLEMENTATION |
| **T-BABY-6** | write / append | **no** | no | no | REQUIRES IMPLEMENTATION |
| **T-BABY-7** | delete / rename / replace | **no** | no | no | REQUIRES IMPLEMENTATION |
| **T-BABY-8** | modify DACL (`WRITE_DAC`) | **no** | no | no | REQUIRES IMPLEMENTATION |
| **T-BABY-9** | modify ownership (`WRITE_OWNER`) | **no** | no | no | REQUIRES IMPLEMENTATION |
| **T-BABY-10** | own any path | **no** | no | no | **ESTABLISHED** (T-OWN-2) |

T-BABY-5 is deliberately asymmetric: granting execute on the model or config would
hand the subject the ability to run data as code, and granting read-only on the
runtime would leave it unloadable. Both are over-grants this boundary exists to
prevent, and C3 already treats a superset as a failure.

**Intentionally unavailable, stated explicitly** (per instruction): T-BABY-6 through
T-BABY-9 are *intentionally* withheld. They are not oversights to be closed by
granting, and no future change may widen them without a governance decision.

## 9. Evidence schema requirements

Minimum evidence to verify T. Fields are **not** all fingerprint fields.

### Evidence fields (recorded per path)

`path`, `path_type`, `existence`, `owner`, `owner_sid`, `access_sddl`
(DACL only), `access_rules_protected`.

### Derived verification results (recorded, never fingerprinted)

effective access per operation, traversal behaviour, `BABY_AI_TEST` capability
matrix, administrative-access matrix, `not owner` verdict. These are **outcomes of
running a subject**, not properties of a descriptor, and folding them into a
fingerprint would make the value depend on a process launch rather than on state.

### Fingerprint fields

v1 = 5 fields; **v2 = 7** (adds `owner`, `owner_sid`). Ownership was added because
T carries an ownership invariant and v1 cannot express it — a change forced by a
requirement, not a reflex. No further field was added "while we were here".

### Known schema gaps

| gap | consequence | status |
|---|---|---|
| Traversal is not a descriptor field | must be verified by OS measurement | **REQUIRES IMPLEMENTATION** |
| Effective access is not a descriptor field | ACL observation ≠ enforcement; M015 recorded this distinction | **REQUIRES IMPLEMENTATION** |
| `verify_boundary` compares expanded **letters**, which cannot express `FILE_TRAVERSE`, `WRITE_DAC`, `WRITE_OWNER`, `WRITE_EA` or `WRITE_ATTRIBUTES` individually | several T properties are **unverifiable by the current verifier** | **REQUIRES IMPLEMENTATION** |

That last row is the most consequential: the current verifier cannot check the
properties T actually cares most about. It compares `RX`/`R` letters; `WRITE_DAC`
and `FILE_TRAVERSE` have no letter.

## 10. ACL / mask decision boundary

**Recorded explicitly:**

> **Security properties are specified before ACL mask selection.**

M019 selects **no** mask. `0x00110156`, `0x000d0156` and every other value are
**implementation candidates**, none established by this milestone as a necessary
consequence of T.

| candidate | status |
|---|---|
| `0x00110156` | M015 legacy. Carries `SYNCHRONIZE`; **omits `WRITE_DAC` and `WRITE_OWNER`** — so it cannot satisfy T-WR-6/7 as written |
| `0x000d0156` | M016 exact candidate. Omits `SYNCHRONIZE`; includes `WRITE_DAC`/`WRITE_OWNER`; `icacls` cannot express it |
| neither | the decision is **REQUIRES DESIGN DECISION**, gated on T being approved |

Hazard carried forward as an evidence-backed implementation constraint, **not** as
authorisation for any mask: a deny including `WRITE_DAC` or `DELETE` can interfere
with recovery and cleanup, and is unrecoverable by construction.

## 11. T — intended production boundary target

T is the conjunction of the invariants below over the target path set. Each carries
an explicit status; no item is inferred.

### Target path set

`subject_runtime`, `runtime`, `model`, `config` — and **only** those. No
`m016_*` fixture path, no artifact created by a test.

| id | invariant | status |
|---|---|---|
| **T-PATH-1** | Exactly the four paths above exist under `subject_runtime` | **REQUIRES IMPLEMENTATION** (`model\` absent; 3 fixture artifacts present in P1 and must not be part of the target) |
| **T-PATH-2** | No test-fixture artifact is inside the target path set | **REQUIRES IMPLEMENTATION** |
| **T-OWN-1/2** | operator owns every path; `BABY_AI_TEST` owns none | **ESTABLISHED** (3 of 4 paths; `model\` **NOT ESTABLISHED**) |
| **T-TRAV-1/2/3/4** | subject can traverse and descend; traversal is not a control; traversal verified by OS measurement | **ESTABLISHED** semantically; **REQUIRES IMPLEMENTATION** to verify |
| **T-WR-1…11** | write, append, delete, delete-child, rename/replace, `WRITE_DAC`, `WRITE_OWNER`, `WRITE_EA`, `WRITE_ATTRIBUTES`, create, and absence of inherited AU Modify — all denied to `BABY_AI_TEST` | **REQUIRES IMPLEMENTATION**; none currently established in P1 |
| **T-ADM-1…5** | operator / SYSTEM / Administrators retain control without depending on an elevated token; nothing lost by transformation | **ESTABLISHED** in P1; **REQUIRES REHEARSAL** for T-ADM-5 |
| **T-BABY-1…10** | read/list/traverse everywhere; execute on `runtime` only; write/delete/DACL/ownership withheld | **ESTABLISHED** for 4 and 10; **REQUIRES IMPLEMENTATION** for 1, 2, 3, 5, 6, 7, 8, 9 |

### Not part of T

T is **not** an ACL, **not** a mask, **not** a procedure, **not** a recovery plan,
**not** R, and **not** C. It is a set of falsifiable properties plus the evidence
required to test them.

## 12. T versus C delta

| dimension | C establishes | C fails to establish | M018 revealed | M019 resolves | still unresolved |
|---|---|---|---|---|---|
| ownership | C5: owner non-empty and not the subject | **C5 is unverifiable from R** — R has no owner field | R cannot establish C5 | Fresh observation: operator owns all 3 observable paths; subject owns none; **v2 recipe** carries owner | `model\` ownership |
| traversal | nothing — traverse is not expressible in its letter set | whether the subject can actually descend | G5 inferred traversal was broken from a mask | **G5 refuted by measurement**; semantic requirement established; `SeChangeNotifyPrivilege` makes the ACE non-load-bearing | how to *verify* traversal — letter verifier cannot |
| write control | C4: a deny exists and does not grant | which rights the deny must cover; nothing about `WRITE_DAC`/`WRITE_OWNER` individually | R enforces neither | T-WR-1…11 enumerate the required properties | mask choice |
| AU Modify | C2: inherited AU Modify absent | — | P1 violates it | T-WR-11 states it as a required property | — |
| admin access | C6: operator/SYSTEM/Admin `(OI)(CI)(F)` | that access survives transformation; that it works unelevated | — | T-ADM-1…5; T-ADM-4 records the deny-only Administrators observation | transformation safety |
| verifier | compares expanded letters | cannot express traverse, `WRITE_DAC`, `WRITE_OWNER`, `WRITE_EA`, `WRITE_ATTRIBUTES` | — | documented as a schema limitation | **verifier replacement is REQUIRES IMPLEMENTATION** |
| enforcement | C7: `ACL_OBSERVATION_ONLY`, OS enforcement `NOT_TESTABLE` | — | — | inherited unchanged | a real subject launch |

**Net:** C remains the *intent*; T is C's intent made falsifiable, plus ownership and
traversal made explicit, plus the properties C could not name. C is not wrong — it is
**insufficient**.

## 13. T versus R delta

Why R cannot simply become T:

| # | dimension | R | T | verdict |
|---|---|---|---|---|
| 1 | **fixture debris** | 4 of 8 paths are `m016_*` test artifacts | exactly 4 structural paths | **R violates.** Adopting R recreates test artifacts in production. |
| 2 | **ownership** | **no owner field at all** | T-OWN-1/2 required and observable | **R cannot satisfy.** Unverifiable by construction. |
| 3 | **deny mask** | `0x00110156` — lacks `WRITE_DAC`, `WRITE_OWNER` | T-WR-6/7 require both | **R does not satisfy.** |
| 4 | **`SYNCHRONIZE`** | denied (`0x00100000` set) | not required by T | **R over-denies**, unexamined |
| 5 | **traversal** | root allow lacks `0x20` | T-TRAV requires traversal, but forbids relying on the ACE for it | **R's apparent defect is not real** — measured `OS_ALLOWED` (§5). This is *not* a reason to adopt R; it is a reason M018's inference was wrong. |
| 6 | **descriptor flags** | `D:PAI` on boundaries | `AI` unspecified by T | **REQUIRES DESIGN DECISION** |
| 7 | **path set** | 8 paths incl. debris | 4 paths | **R violates** |
| 8 | **AU Modify** | absent | must be absent (T-WR-11) | R satisfies |
| 9 | **subject allow letters** | `R` / `RX` per subtree | T-BABY-1…5 | R satisfies at letter level |
| 10 | **operator/SYSTEM/Admin** | `FA` explicit | T-ADM-1…3 | R satisfies |
| 11 | **evidence provenance** | one artifact, self-described `role` cannot separate debris from structure (`m016_delete_target` is marked `inherited_descendant`) | — | **R is not self-describing** |

Neither R nor C is ranked. R is *recorded evidence that once existed*; C is *intent
expressed in code*. T is neither, and adopts from each only what survives the deltas
above.

## 14. Verification plan

How T will eventually be verified. **No step below was executed against production in
M019**, and none may be if it can mutate state.

| # | step | method | mutating? |
|---|---|---|---|
| 1 | pre-change state capture | canonical recipe **v2** (owner included), full path set | no |
| 2 | exact target-path set | enumerate and assert exactly the four paths; assert no `m016_*` | no |
| 3 | ownership verification | `(Get-Acl).Owner` + SID translation; assert operator owns all, subject owns none | no |
| 4 | ACL verification | DACL SDDL per path; property-level assertions per T-WR/T-BABY, **not** letter comparison | no |
| 5 | traversal verification | OS measurement under the real subject identity; the letter verifier cannot do this (§9) | no, but **requires a subject launch** |
| 6 | `BABY_AI_TEST` access verification | probe read/list/traverse/execute **allowed**; write/append/delete/rename/replace/`WRITE_DAC`/`WRITE_OWNER`/`WRITE_EA`/`WRITE_ATTRIBUTES` **denied** | no |
| 7 | operator verification | operator retains create/write/delete/DACL on disposable state | disposable only |
| 8 | SYSTEM verification | presence and full control asserted in the descriptor | no |
| 9 | Administrators verification | presence asserted; **plus** the T-ADM-4 unelevated-token check | no |
| 10 | fingerprint generation | recipe id recorded with the value; never compared across recipes | no |
| 11 | rollback verification | topology-equivalent disposable rehearsal; gate must be shown able to fail | disposable only |
| 12 | M005 OS-isolation regression | M005 byte-identity: 13 paths, 5 digests | no |
| 13 | harness-safety regression | `test_harness_write_isolation.py`, `test_probe_argument_contract.py`, `test_canonical_state.py` | no |
| 14 | evidence preservation | snapshot to `outputs/evidence/…` before any change | no |
| 15 | no unintended fixture paths | assert no `m016_*` in the target set | no |

Steps 5 and 6 require a real interactive subject launch. That remains
**NOT_TESTABLE** unattended, and the run must never request or store a password.

## 15. Recovery / implementation prerequisites

None of these is authorized by M019.

1. T approved by a later governance milestone.
2. A verifier that can express the T properties — the current letter comparison
   cannot check `WRITE_DAC`, `WRITE_OWNER`, `WRITE_EA`, `WRITE_ATTRIBUTES` or
   traversal.
3. Exact target-path set established and free of fixture artifacts.
4. Complete pre-change evidence captured under recipe v2.
5. Ownership evidence for all four paths, including a `model\` that exists.
6. Traversal requirement established **and** a verification method that measures it.
7. ACL property specification approved (T-WR, T-BABY) independently of any mask.
8. Mask / implementation design **separately approved** — §10.
9. Topology-equivalent disposable rehearsal, matching the production shape.
10. Rehearsal success, including a rollback rehearsal.
11. Administrative-access preservation demonstrated without an elevated token
    (T-ADM-4).
12. `BABY_AI_TEST` boundary verified under the real subject identity.
13. M005 OS-isolation preserved.
14. Harness safety verified.
15. Production write path **explicitly authorized**.
16. A privilege-free faithful-write mechanism, or an authorized decision to grant
    privileges — currently unresolved.

## 16. Explicitly unresolved questions

1. **Deny mask selection.** Downstream of T; **REQUIRES DESIGN DECISION**.
2. **Traversal verification.** The letter verifier cannot express it; an OS-measurement
   verifier is **REQUIRES IMPLEMENTATION**.
3. **Verifier replacement generally.** The current verifier cannot check the
   properties T cares most about.
4. **`model\` ownership.** Path absent; T-OWN-3 **NOT ESTABLISHED**.
5. **Exact-ACE capability.** **NOT ESTABLISHED** — fixture was destroyed by
   `/inheritance:d` before the discriminating operation could run. Nothing in T
   currently depends on it; only the rejected rollback path did.
6. **Privilege requirement.** Privilege-free faithful DACL writing not demonstrated.
   Corroborated by T-ADM-4: the operator token here is not elevated.
7. **Recovery sequencing.** Unaddressed; depends on 1–6.
8. **`AI` flag on a protected descriptor.** Accepted or not: **NOT ESTABLISHED**.
9. **Fixture artifacts currently in P1** (3 `.exe` files). Their removal is a
   production mutation and is **not decided here**.
10. **`SYNCHRONIZE` in a deny.** Whether denying it is acceptable: **NOT ESTABLISHED**.

## 17. M019 acceptance criteria

| criterion | result |
|---|---|
| Ownership observed read-only, not inferred | PASS — §4, `Get-Acl .Owner` + SID |
| `BABY_AI_TEST` ownership checked tree-wide | PASS — owns nothing |
| Ownership representable in canonical evidence | PASS — recipe **v2**; v1 unchanged, golden-value test |
| v1 not silently modified | PASS — golden fingerprint unchanged |
| Traversal requirement established semantically | PASS — §5 |
| M018's G5 inference corrected against measurement | PASS — refuted; `SeChangeNotifyPrivilege` identified |
| Semantic / ACL / verifier / observed layers distinguished | PASS — §5 table |
| C not silently redefined | PASS — limitation documented as a gap |
| Write/control spec at property level | PASS — T-WR-1…11 |
| Admin spec, with the same-SID and principal-wide prohibitions carried | PASS — §7 |
| `BABY_AI_TEST` capabilities separated; withheld ones stated | PASS — §8 |
| Evidence fields vs fingerprint fields vs derived results distinguished | PASS — §9 |
| No mask selected; properties-before-mask recorded | PASS — §10 |
| T defined as falsifiable invariants | PASS — §11 |
| T vs C and T vs R deltas complete, nothing ranked | PASS — §12, §13 |
| Verification plan present, no step run against production | PASS — §14 |
| Prerequisites listed, none authorized | PASS — §15 |
| Unresolved questions left unresolved | PASS — §16 |
| 9 red tests still red | PASS |
| Untracked tooling untouched; nothing committed | PASS |

## 18. M019 final status

**M019_BOUNDARY_SPEC = PASS.** T is defined as a set of testable security
invariants. No ACL, mask, mechanism or recovery procedure was selected.

### Harness safety

- `tests/canonical_state.py` remains read-only: `_run` refuses every icacls switch in
  `ICACLS_MUTATING_FLAGS` before launch; `dump()` refuses to write inside the
  repository.
- The v2 change added **read** operations only (`Get-Acl .Owner`, SID translation).
  No mutating surface was added, and the default recipe is unchanged.
- The repository audit test `test_no_test_helpers_mutate_production_subject_runtime`
  passes; the one pairing it caught earlier in M018 was fixed at source rather than
  executed.
- `tests/test_canonical_state.py` — **39 passed**. Read-only suites —
  **139 passed**.

### The 9 red tests remain red

Not fixed, not bypassed, not made green. Re-confirmed at exactly **9**. They remain
the standing alarm reporting damaged production.

### Untracked tooling untouched

`.agents/`, `.claude/`, `.claude-flow/`, `.swarm/`, `.mcp.json`, `CLAUDE.md` — not
modified, not deleted, not committed. The pre-existing `.gitignore` change was left
alone. Nothing committed.

```
PRODUCTION_TOUCHED   = NO    (v1 f73eaf78… unchanged; v2 recorded)
OWNERSHIP_INVARIANT  = ESTABLISHED   (3 of 4 paths; model\ NOT ESTABLISHED)
TRAVERSAL_INVARIANT  = ESTABLISHED   (semantically; verification REQUIRES IMPLEMENTATION)
WRITE_CONTROL_SPEC   = COMPLETE
ADMIN_ACCESS_SPEC    = COMPLETE
BABY_AI_BOUNDARY_SPEC= COMPLETE
T_DEFINED            = YES
T_VS_C_DELTA         = COMPLETE
T_VS_R_DELTA         = COMPLETE
EXACT_ACE_STATUS     = NOT_ESTABLISHED
HARNESS_SAFETY       = VERIFIED
PRODUCTION_RECOVERY  = NOT_ATTEMPTED
MECHANISM_SELECTED   = NO
```

M020 — approval of T, or the verifier and mask decisions it depends on — is **not**
begun and is not authorized here.

---

## 19. Amendment A1 (D6-B) — T-BABY-1 observation namespace

**A1_STATUS = RECORDED — GOVERNANCE ONLY, NO MEASUREMENT PERFORMED**

This amendment exists because **T-BABY-1 and T-PATH-2 are jointly unsatisfiable on the current
topology**, and no amount of measurement can fix that. T-BABY-1 requires an object the subject can
read; T-PATH-2 forbids every test artefact from being inside the target path set; the only files
present under `runtime\` are `m016_*` fixtures. M052B therefore measured T-BABY-1 against an object
that was simultaneously a valid read-access observation and a T-PATH-2 violation.

M052D classified this as a **property-contract contradiction, not an instrumentation problem**.
M052E recorded the director's selection of **D6-B**. A1 is the governed documentation amendment that
D6-B requires.

### 19.1 What A1 does and does not change

| | |
|---|---|
| **Canonical T** | **UNCHANGED** — `subject_runtime`, `runtime`, `model`, `config`, and only those (§11) |
| **T-PATH-1** | **UNCHANGED** |
| **T-PATH-2** | **UNCHANGED** — still a prohibition on test artefacts inside T |
| **T-OWN-*** | **UNCHANGED** |
| **T-TRAV-*** | **UNCHANGED** |
| **T-WR-1…11** | **UNCHANGED** |
| **Security objective** (§10 deny-set derivation) | **UNCHANGED** — see §19.7 |
| **T-BABY-1 requirement** | **UNCHANGED** — still *"read data"*, state `allowed`, evidence `OS measurement` |
| **T-BABY-1 observation source** | **EXTENDED** — may be sourced from a governed measurement namespace outside T |

A1 changes **where T-BABY-1's read observation may be sourced**. It changes **nothing** about what
T-BABY-1 requires, and it changes **no other property**.

### 19.2 Why the source had to change

Under §11 and T-PATH-2 there is exactly one compliant observation source for T-BABY-1, and it does
not currently exist:

* authoring content into canonical `subject_runtime` was **D6-A**, rejected — it is a production
  mutation and would leave T-PATH-2 unmet anyway;
* amending §11 to admit fixtures was **D6-C**, rejected — it converts a prohibition into a
  permission and would let T-PATH-2 be satisfied by definition rather than by measurement;
* **D6-B** was selected: source the observation from outside T, under explicit governance.

### 19.3 The governed measurement namespace — defined, NOT created

A1 defines the concept. **No namespace path is chosen and no namespace is created by this
amendment.** Naming a concrete production path here would convert a governance decision into an
implementation, and would place a new artefact class adjacent to the frozen boundary before its
governance is settled.

**Identifier.** `T_OBSERVATION_NAMESPACE` — a governed identifier, not a path. A concrete location
requires its own implementation milestone with the same freeze-and-rehearse discipline as M052B,
and is deliberately left open.

| requirement | rule |
|---|---|
| **Location** | Outside canonical T. Not inside `subject_runtime`, `runtime`, `model` or `config`. Not a path fixed by A1. |
| **Ownership** | Owned by the **laboratory/operator**, never by `BABY_AI_TEST`. The subject does not own a namespace it may read; ownership follows the §7 same-SID and principal-wide prohibitions. |
| **Provenance** | Every observation object must carry: experiment identifier; creation provenance; content hash; author/source classification; immutable association with the measurement it serves. |
| **Mutability** | The subject gains **no** write, append, delete, `WRITE_DAC`, `WRITE_OWNER`, `WRITE_EA` or `FILE_WRITE_ATTRIBUTES` rights by the namespace existing. It is a **measurement input, not a subject workspace.** |
| **Separation** | Observation objects must not be conflated with subject memory, subject experience, canonical subject state, model weights, runtime code, or provenance evidence. |
| **Fixtures** | Disposable test fixtures remain disposable test fixtures. They are **not** promoted to canonical or governed-legitimate status by the existence of a namespace. |

### 19.4 The six categories A1 keeps distinct

The contradiction arose from two categories being blurred. A1 separates them explicitly, and no
category may be silently reclassified as another:

| # | category | may serve as T-BABY-1 observation source? |
|---|---|---|
| 1 | **canonical subject state** | yes — it is inside T, and T-PATH-2 keeps it free of artefacts |
| 2 | **environment/content supplied for legitimate observation** | yes, **only** via `T_OBSERVATION_NAMESPACE` and only under §19.3 provenance |
| 3 | **research instrumentation** | no — an instrument is the thing that *performs* the observation |
| 4 | **disposable test fixtures** | **no** — remains prohibited inside T by T-PATH-2 |
| 5 | **subject-generated content** | no — is evidence of the subject, never an input to it |
| 6 | **provenance/evidence artifacts** | no — evidence of a measurement, never its subject |

### 19.5 Historical M052B treatment — immutable

M052B is **not** rewritten, reclassified, or invalidated.

```
M052B measured : read access (0x0001) to runtime/m016_read_fixture.exe
target location: INSIDE canonical subject_runtime
target status  : a T-PATH-2 VIOLATION (an m016_* test fixture)
result         : ALLOWED, bytes_read = 25
```

What follows from that, and only that:

* the **access observation is valid historical experimental evidence** — an externally identified
  `BABY_AI_TEST` token obtained `FILE_READ_DATA` on an existing object, observed by an OS-level
  measurement, exactly as M019 requires;
* it was **not obtained under `T_OBSERVATION_NAMESPACE`**, which did not exist;
* M052B is therefore **not retroactively transformed into a compliant D6-B experiment**;
* consequently it does **not** discharge T-BABY-1 under A1.

```
T-BABY-1 (post-A1) = REQUIRES_FRESH_MEASUREMENT
```

This is a statement about **evidential provenance**, not a retraction. Nothing about what the subject
did in attempt `e978330eb5e746c0` is in dispute; only whether that attempt used a compliant
observation source. It did not.

### 19.6 What A1 makes possible, and what it does not

```
D6-B decision (M052E)
  -> A1 amendment (M052F)                      [THIS MILESTONE]
     -> T_OBSERVATION_NAMESPACE implementation  [NOT DONE — later milestone]
        -> fresh T-BABY-1 measurement          [NOT DONE — later milestone]
           -> T-BABY-1 adjudication            [NOT DONE — later milestone]
```

**A definition change makes a property MEASURABLE. It does not perform the measurement.** T-BABY-1
is not satisfied by this amendment and cannot be reported as satisfied until a fresh compliant
observation exists.

### 19.7 Security objective — explicitly unchanged

A1 alters **none** of: the required deny rights (`T_SUBJECT_DENIED_RIGHTS`, 8 rights); the
effective-access interpretation; the subject boundary; the operator boundary; `WRITE_DAC`
requirements; `WRITE_OWNER` requirements; ownership requirements.

The security objective remains **NOT SATISFIED** on current production, with **5 of 8** required
denials absent (`FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `FILE_WRITE_EA`, `FILE_WRITE_ATTRIBUTES`,
`DELETE` present; `FILE_DELETE_CHILD`, `WRITE_DAC`, `WRITE_OWNER` absent). That is a D3 matter.
D3 remains an independent, unresolved decision and is **not** advanced, derived, or implemented here.

### 19.8 What A1 explicitly does not do

* It does **not** legitimise the three `m016_*` artefacts. They remain **T-PATH-2 violations** until
  a separate remediation decision (M052D D1) permits their removal.
* It does **not** create, populate, or grant access to any namespace.
* It does **not** grant the subject any new right.
* It does **not** select or implement a deny mask.
* It does **not** launch a subject, run a measurement, or alter any prior evidence record.
* It does **not** introduce a *"protected data"* predicate. T-BABY-1 remains *"read data"*.

### 19.9 Amendment A1 acceptance criteria

| criterion | result |
|---|---|
| All 36 T properties still present, none deleted, none duplicated | PASS |
| T-PATH-2 text unchanged | PASS |
| T-BABY-1 requirement text and state unchanged | PASS |
| Canonical T text unchanged | PASS |
| Security objective unchanged | PASS |
| Prior sections 1–18 preserved verbatim | PASS |
| M052B evidence byte-identical | PASS |
| M052C / M052D / M052E records intact | PASS |
| Namespace **defined, not created** | PASS |
| `m016_*` still classified as violations | PASS |
| No subject launched, no authorisation requested | PASS |