# M017 — Production Security Objective and Recovery Decision Record

**STATUS = DECISION BOUNDARY RECORDED. NO MECHANISM SELECTED.**
**PRODUCTION_TOUCHED = NO**
**HARNESS_SAFETY = VERIFIED**
**M016_CONTAINMENT = REJECTED**
**PRODUCTION_RECOVERY = NOT_VERIFIED**

Read-only milestone. No ACL, privilege, account, group or production state was
changed. Date: 2026-10-01. HEAD at time of work:
`3c91b340e9a5d28c32f351700d4f7b3d514f1cf4` (no commit made).

---

## 1. Scope

This document separates three objectives that became entangled during M015/M016 and
records the boundary between them. It selects nothing.

| track | question | status |
|---|---|---|
| **A — immediate containment** | what minimum security property is needed *now*, while the damaged ACL persists? | defined, mechanism not selected |
| **B — faithful restoration** | what does "restored" mean, exactly? | acceptance criteria defined; **blocked** |
| **C — future M015 boundary** | what is the *intended* policy, independent of both? | defined, not started |

These have different acceptance criteria and must not substitute for one another. A
containment mechanism is not a recovery mechanism, and neither is a reconstruction
of the intended policy.

## 2. Authoritative production state

Damaged, and unchanged since the incident. Verified read-only at the close of this
milestone:

```
subject_runtime   AreAccessRulesProtected = False
subject_runtime   explicit ACE count     = 0
Authenticated Users 0x001301bf  (I)       = present, inherited
Authenticated Users 0xSDGXGWGR  (I)(OI)(CI)(IO) = present, inherited
BUILTIN\Users     0x001200a9  (I)       = present, inherited
model\                                 = ABSENT
BABY_AI_TEST explicit ACEs              = 0
PRODUCTION_RECOVERY_VERIFIED            = NO
```

Current descriptor:

```
D:AI(A;ID;FA;;;BA)(A;OICIIOID;GA;;;BA)(A;ID;FA;;;SY)(A;OICIIOID;GA;;;SY)
  (A;ID;0x1301bf;;;AU)(A;OICIIOID;SDGXGWGR;;;AU)
  (A;ID;0x1200a9;;;BU)(A;OICIIOID;GXGR;;;BU)
```

Current path count: **6**. `PRODUCTION_RECOVERY_VERIFIED = NO`.

**This state must not be silently altered to make tests green.** Four read-only
regression tests currently fail *because* they report this damage. That is the
alarm working.

### 2.1 The stated restoration target is not clean

The restoration target is
`outputs/evidence/m016-subject-deny/prod_fingerprint_before.json`. It is referred to
in prior documents as "authoritative". Two properties of it must be settled before
any restoration is attempted — see §14, items **I1** and **I2**:

- **4 of its 8 paths are harness fixture debris** created by the tests that caused the
  incident: `m016_delete_target`, `m016_disposable_target.exe`, `m016_read_fixture.exe`,
  `m016_subjectrun_fixture.exe`. Restoring to this target byte-for-byte would
  **recreate test artifacts in production**.
- **It contains no fingerprint field.** The file is `{status, paths}`. The value
  `02c5e4c473c2deacbbb8dd6636fb5ab7adfbc735f816fb1b9c2ede5da0bae54d` appears only as
  prose in two documents, never as stored data.

Only 4 of the 8 paths are genuine `subject_runtime` structure:
`subject_runtime`, `runtime`, `model`, `config`.

## 3. Incident correction

The production boundary was destroyed by an M015/M016 **test run**. The mechanism was
**not** `apply_boundary()`.

| function | call sites | argument | safe |
|---|---|---|---|
| `apply_boundary()` | `test_staging_boundary.py:65` only | `tmp_path` | yes |
| `apply_subject_deny()` | `test_subject_deny.py` only | `scratch_root` (tmp) | yes |

The real cause was three call sites using production paths as test fixtures:

1. `tests/test_boundary_harness.py:314` — created and deleted
   `subject_runtime/runtime/m016_harness_fixture_<token>.exe`.
2. `tests/test_boundary_harness.py:333` — created and `rmtree`'d
   `subject_runtime/config/m016_harness_delete_target`, including in a `finally`.
3. `tests/test_m016_launch.py:354` — wrote `subject_runtime/runtime/m016_control.exe`
   and ran the **full subject probe** with `scratch=subject_runtime/config`.

Site 3 was the severe one: the mutation happened inside a **child process**, so "the
Python test did not mutate production" was true and irrelevant.

An earlier claim in this investigation — that a test called `apply_boundary()`
against production as setup — was **wrong** and is corrected here.

## 4. Harness safety status: **VERIFIED / CLOSED**

A central write-scoped mutation boundary now prevents the incident mechanism:

- `tests/path_policy.py` — canonical repository policy; component-wise, case-folded
  comparison (so `TharAI-EXP-evil` is correctly external); non-strict `resolve()` so a
  **nonexistent** future production path is still classified.
- `tests/guarded.py` — every mutation-capable surface routes through it **before** any
  filesystem, ACL or subprocess work.
- `tests/test_probe_argument_contract.py` (17) — the probe's path-argument contract,
  checked against the probe source.
- `tests/test_harness_write_isolation.py` (46) — negative tests including a tripwire on
  `subprocess.run` proving rejection happens **before launch**.

Production **reads** remain deliberately permitted: the read-only checks are what
detected the incident, and removing them would remove the alarm.

A post-audit found the guard was not the complete boundary it appeared to be: the
positional slots `staged`, `protected` and `workspace` were classified READ_ONLY while
the launched probe mutates all three (`protected` sets attributes on an arbitrary
enumerated child). All three are now WRITE-scoped, with the classification held in one
table verified against `subject_probe.cs`. This was **not** the incident cause — no test
passed production paths through those arguments — but a guard that looks complete while
having a hole is worse than a visibly narrow one.

## 5. M016 containment: **REJECTED**

> On the tested Windows host, `/inheritance:d` cannot be relied upon to preserve distinct
> inherited and newly introduced Allow ACEs for the same principal. In the
> production-shaped operator ACL, freezing inheritance causes the temporary FullControl
> operator ACE to replace the pre-existing inherited `0x00120089` operator ACE.
> Consequently, `operator grant → /inheritance:d → remove AU` is not a safe containment
> transformation.

`0x00120089` is a read mask, so the freeze destroys operator **read** access — before
the AU removal the sequence existed to perform. Rollback cannot repair it.

**Why it was invisible until late:** every earlier rehearsal exercised `/inheritance:d`
with **one ACE per principal**, where "copies inherited to explicit" and "collapses
same-SID ACEs" are indistinguishable. `/inheritance:d` remains valid for single-ACE
principals; the rejection is specifically the same-SID case.

**Hard boundary: do not apply this sequence to production. Do not run further
`/inheritance:d` experiments against it.**

## 6. Evidence summary

Recorded explicitly, preserving prior conclusions without strengthening them:

1. The incident was caused by test/probe paths pointing at production, **not** by
   `apply_boundary()`.
2. Harness write isolation is **CLOSED / VERIFIED**.
3. The original M016 containment design is **REJECTED**.
4. The rejection is specifically that `/inheritance:d` is lossy for same-SID inherited
   + temporary Allow ACEs on this host.
5. **"Exact ACE removal is impossible" is NOT established.** The two-ACE state the
   experiment needed was destroyed by `/inheritance:d` before `RemoveExact` could be
   exercised against it. The correct fixture *is* constructible
   (`CORRECT_TWO_ACE_FIXTURE = PASS`, with both `0x20089/inh` and `0x1f01ff/exp`
   simultaneously present). `RemoveExact` then ran against a single-ACE tree and
   returned `1`, removing the only operator ACE present. **Inconclusive, not a gap.**
   See §14 item **I3**.
6. The exact production-topology rehearsal established that `/inheritance:e`
   **automatically restores inherited AU** — no manual re-grant required.
7. The four-step rollback was **rejected** because principal-wide
   `/remove:g operator` also removes the operator's pre-existing `0x00120089` access.
   `EXACT_TOPOLOGY_RUN_1 = FAIL`, `EXACT_TOPOLOGY_RUN_2 = FAIL`, deterministic.
8. **Faithful production restoration remains unresolved.**
9. **`apply_boundary()` is NOT a faithful restoration mechanism.** It reconstructs a
   policy; it does not restore the recorded descriptor. It would also recreate
   `model\`, which the snapshot records as part of the target.
10. The five mechanisms catalogued by the read-only design audit remain **distinct**
    and unranked: `/inheritance:e`, explicit AU deny, remove AU at inherited source,
    deny at parent, SID-only deny.
11. **None of them is authorized for production.**
12. Production state must not be altered merely to make tests green.

Exact-mask machinery (`foundation/subject_deny.py`) is **experimental and
unintegrated**. Its mask logic (`0x000d0156`, applied natively, restored via `icacls`)
is reusable; its deployment plan is rejected.

## 7. Objective A — immediate containment

**Question.** If the inherited `Authenticated Users` Modify exposure is considered
unacceptable *before* faithful restoration is solvable, what is the minimum security
property that must hold?

**Minimum property, stated without selecting a mechanism:** no principal outside the
intended subject boundary can obtain write, append, delete, rename, replace,
`WRITE_DAC`, `WRITE_OWNER`, `WRITE_EA` or `WRITE_ATTRIBUTES` on any path under
`subject_runtime`, while operator, SYSTEM and Administrators retain administrative
access and `BABY_AI_TEST` gains nothing it did not previously hold.

Two properties are **deliberately not** part of the containment objective, because
they belong to tracks B and C:

- descriptor fidelity to the pre-incident snapshot (that is restoration);
- the M015 boundary policy as an intended design (that is the future boundary).

Per-mechanism properties are tabulated in §10. No ranking is offered.

**Containment gate.** Production must not be called "contained" merely because
effective write access is denied. Four facts are recorded **separately** and
independently:

| fact | current value for any candidate |
|---|---|
| effective access | must be closed — this alone is insufficient |
| descriptor state | will differ from both the snapshot and the M015 model |
| inheritance state | must be recorded; the rejected design changed it |
| reversibility | must be demonstrated on topology-equivalent disposable state |

A containment mechanism that leaves a deliberately added deny residue **is**
containment, not restoration.

## 8. Objective B — faithful restoration

**Acceptance criterion, defined independently of any mechanism:** the production ACL
tree returns to the exact pre-incident state recorded in the snapshot — exact ACE
semantics, inherited/explicit status, masks, inheritance and propagation flags,
protected state, and path coverage. **No reconstructed approximation.**

Two clarifications the evidence forces:

- **The snapshot target must first be corrected as a target.** Per §2.1 it contains
  four harness fixture artifacts and stores no fingerprint. Restoring to it literally
  would recreate test debris and match nothing that was ever verified. Correcting the
  *target* is a decision for this track; it is not a licence to alter production.
- **The snapshot is not the M015 model.** Its boundary descriptors carry the legacy deny
  `0x00110156`, which lacks `WRITE_DAC` and `WRITE_OWNER` — the exact-mask finding.
  Boundaries are `D:PA` with `explicit: 1`, i.e. a boundary already applied, not a
  clean inherited tree. Restoring it therefore reproduces a **superseded
  implementation** of the intended policy. This is the concrete reason tracks B and C
  cannot be merged.

**Current blocker.** Privilege-free faithful DACL writing has **not** been demonstrated.

Recorded as the currently identified blocker under investigation, **not** as proof that
`SeSecurityPrivilege` is the only possible route:

| mechanism | result |
|---|---|
| `Set-Acl` | requires `SeSecurityPrivilege` (round-trips the audit section) |
| `SetSecurityDescriptorSddlForm` + `SetAccessControl` | requires `SeSecurityPrivilege` |
| `icacls /save` + `/restore` | "Not all privileges or groups referenced are assigned"; 0 files processed |
| raw DACL P/Invoke (`SetNamedSecurityInfoW`) | `1338`/`1340`; **stripped the caller's own FullControl ACE and locked the directory**. Not usable. |

Native `AccessControlSections::Access` binding is bit-exact for apply but is *lossy for
restore* (`0x00110156 → 0x00010156`); `icacls` is exact for restore. Neither alone is a
faithful whole-tree restore.

**Recovery gate.** Production must not be called "recovered" unless
`PRODUCTION_RECOVERY_VERIFIED = YES` **and** the final canonical fingerprint and
semantic tree match the recorded pre-incident state.

## 9. Objective C — future M015 boundary

An **intended policy**, separate from immediate containment and from recovery:

- the subject can execute and read what it needs;
- the subject cannot modify the protected runtime / model / config boundary;
- human/operator remains administratively capable;
- provenance and evidence remain protected;
- the boundary is **independently verified under the actual subject identity**.

Constraints on this track:

- the damaged production ACL is **not** the canonical design;
- a containment mechanism is **not** a substitute for M015 reconstruction;
- the recorded snapshot is **not** the canonical design either — it encodes the legacy
  `0x00110156` deny mask (§8);
- verification requires a real interactive subject launch. Unattended subject launch
  and runtime/model execution under the subject remain **NOT_TESTABLE**.

## 10. Candidate mechanisms and their known properties

Catalogued by the read-only design audit. **Not ranked. None authorized.**

Production state at audit time: fully inherited, zero explicit ACEs, `model\` absent.
All probing was on disposable trees.

| property | `/inheritance:e` | explicit AU deny | remove AU at source | deny at parent | SID-only deny |
|---|---|---|---|---|---|
| paths affected | `subject_runtime` + descendants | `subject_runtime` | repository root | repository root | `subject_runtime` |
| descriptor effect | removes protection; rejoins parent | adds `Deny 0x00000156` **above** the existing `AU Allow 0x001301bf` | removes AU ACEs at the parent | adds AU deny at parent, inherited downward | adds `Deny` + `Allow` for `BABY_AI_TEST` only |
| inheritance effect | **changed** (unprotects) | **unchanged** (`protected` stays `False`) | **unchanged**; child never touched | **unchanged** | **unchanged** |
| closes AU write exposure | **no** — exposure returns | yes | yes | yes | **no** — leaves AU open for all other AU members |
| blast radius | boundary subtree | boundary subtree | **everything inheriting from the repository root** | **everything inheriting from the repository root** | boundary subtree, one principal |
| reversibility | re-freeze, but `/inheritance:d` is lossy (see §5) | yes — `icacls /remove:d` demonstrated during cleanup | yes — re-add at the parent | yes — `icacls /remove:d` | yes |
| preserves M015 intended model | no | no — descriptor holds both an AU allow and an AU deny | no — repository-wide policy change | no — changes broader inherited policy | partially — closest to the M015 shape, but does not close AU |
| requires exact-ACE editing | no | no | at one path, principal-wide | no | no |
| requires elevated privileges | no | no | no | no | no |
| empirically rehearsed | yes (disposable) | yes (disposable) | yes (disposable) | yes (disposable) | yes (disposable) |
| production authorization | **none** | **none** | **none** | **none** | **none** |

Three properties that constrain any future choice:

- **Mechanism 3 is not "cheapest to reverse."** `subject_runtime` is untouched, so the
  ACL change is trivially reversible — but it alters security policy at
  `C:\dev\TharAI-EXP` for **every** descendant inheriting that ACE. A
  repository-wide policy change wearing a small diff.
- **Mechanism 2 does not restore the intended descriptor.** The AU Allow survives and a
  deny is added above it. Effective rights close; the descriptor is not the original.
  Any future audit asking "does an AU Modify ACE exist here?" still answers yes.
- **None of 2, 3, 4 or 5 is equivalent to the original M015 state.** All alter the
  descriptor or the inherited policy rather than restoring it.

**None of the containment candidates depends on the unresolved exact-ACE capability
gap** (§11, G3). That gap blocks the *rejected* rollback path, not these. All were
rehearsed without elevated privileges.

**Property any containment deny must have:** the mechanism-2 deny mask (`0x342`,
`DELETE` + `DELETE_CHILD`) **blocked deletion of its own directory**, including by the
operator; removing the deny still succeeded only because `WRITE_DAC` was deliberately
outside the deny mask. **A containment deny that includes `WRITE_DAC` or `DELETE` is
unrecoverable by construction.** `WRITE_DAC` must stay outside any deny mask, or the
deny cannot be undone by anyone.

## 11. Known capability gaps

| id | gap | status |
|---|---|---|
| **G1** | privilege-free faithful whole-tree DACL restore | **not demonstrated**; blocker recorded in §8 |
| **G2** | `/inheritance:d` same-SID ACE preservation | **demonstrated lossy** on this host; design permanently rejected |
| **G3** | exact single-ACE removal for one SID + mask | **NOT TESTED CONCLUSIVELY.** Fixture constructible; destroyed by `/inheritance:d` before the experiment. Not a proven impossibility |
| **G4** | unattended subject launch; runtime/model execution under the subject | **NOT_TESTABLE** |
| **G5** | root / `model` / `config` allow mask `R` lacks `FILE_TRAVERSE` | reported, not fixed; broadening it is a separate governed decision |
| **G6** | no canonical stored fingerprint for the restoration target, and no recorded *recipe* for one | see §14 **I2**. Observed concretely during this milestone's own verification: an ad-hoc fingerprint omitting the path-type term produced `0fb72590…` against a recorded `70055d54…`, which reads as production having changed when it had not. Recomputing with the identical recipe matched exactly. **A fingerprint without a stated recipe is not reproducible, and a mismatch is not evidence of a change until the recipe is confirmed identical.** |

## 12. Explicitly unauthorized actions

Not authorized by this milestone, and not to be performed by any task acting under it:

- any ACL change under `C:\dev\TharAI-EXP` or on `subject_runtime`;
- any change to the repository-root ACL;
- any `model\` or `subject_runtime` state change;
- `apply_boundary()`, `apply_subject_deny()`, `_restore_dacls()`;
- any containment mechanism from §10;
- any `/inheritance:d` or `/inheritance:r` experiment;
- running the subject probe against production;
- attempting faithful restoration;
- granting privileges, or changing Windows accounts, groups or privileges;
- altering production to make tests pass.

## 13. Required acceptance gates for future work

Every future **production-changing** task must explicitly prove all of:

1. exact target paths identified;
2. production fingerprint captured **immediately before** mutation;
3. mutation mechanism rehearsed on **topology-equivalent** disposable state;
4. rollback / recovery mechanism rehearsed on the same disposable state;
5. operator administrative access preserved;
6. SYSTEM and Administrators preserved;
7. `BABY_AI_TEST` does not gain unintended access;
8. M005 protected paths unchanged;
9. provenance / evidence paths unchanged;
10. production postcondition **independently reread** by a second reader;
11. production fingerprint captured afterward;
12. no test-harness mutation surface can point at production;
13. no cleanup operation can delete outside the disposable tree.

Independence matters at item 10: the fingerprint reader must not be the same code path
that performed the mutation, or a bug in one reader can hide a change from the other.

**Gate strength.** `tests/test_acl_gate_regression.py` (14) exists because two comparison
gates in earlier rehearsals were defective and both defects made a gate *weaker than it
appeared*: one compared live state to itself and reported zero differences while the tree
fingerprint disagreed; another declared two protected-state variables and never assigned
either, so the protection state contributed nothing. Each regression test corrupts one
field and requires the gate to fail. Any gate used to accept future production work must
likewise be shown able to fail — a gate asserted only by reading it is not evidence.

## 14. Inconsistencies found in existing evidence

Recorded for review. **Not silently corrected**, per instruction. None was altered in
producing this record.

**I1 — the "authoritative" restoration target contains harness fixture debris.**
`prod_fingerprint_before.json` lists 8 paths; 4 are artifacts created by the
incident-causing tests (`m016_delete_target`, `m016_disposable_target.exe`,
`m016_read_fixture.exe`, `m016_subjectrun_fixture.exe`), all marked
`role: inherited_descendant`. Restoring to it literally would recreate them. Referenced
as "authoritative" in `m015-harness-incident.md` §8 and `m016-containment-rejected.md`
§5. **Needs a decision before track B proceeds.**

**I2 — the cited fingerprint value has no stored artifact.**
`02c5e4c473c2deacbbb8dd6636fb5ab7adfbc735f816fb1b9c2ede5da0bae54d` occurs only as prose
in `m015-harness-incident.md:165` and `m016-containment-rejected.md:166`. It is absent
from `prod_fingerprint_before.json`, which stores only `{status, paths}`. The single
canonical restoration target does not currently exist as data.

**I3 — an evidence artifact asserts a capability gap the later run invalidated.**
`outputs/evidence/m016-subject-deny/exact_ace_feasibility.txt` concludes
`managed exact-mask removal: NOT CAPABLE`. That run used an **invalid fixture** (one
operator ACE, because `icacls /grant` replaced the rule instead of adding a second).
`outputs/evidence/m016-subject-deny/two_ace_retry.txt` then established
`CORRECT_TWO_ACE_FIXTURE = PASS`. Per §6 item 5 the capability gap is **not** recorded
as established; the earlier artifact's summary line overstates the evidence and should
be annotated rather than left to be read as a finding.

**I4 — the incident document's rehearsal section reads as if the rejected design
works.** `m015-harness-incident.md` §10 states `/inheritance:d` "copies inherited ACEs to
explicit … AU was then removable in isolation". True for its single-ACE-per-principal
fixture, incomplete for the same-SID case that caused the rejection. §8 item 3 was
struck and points at the rejection; §10 was not updated. **Superseded conclusion, not a
factual contradiction** — flagged so a reader does not take §10 as current guidance.

**I5 — recorded test counts are historical, not current.** `m015-harness-incident.md`
§4 states `test_harness_write_isolation.py` — **33 passed**; §9 of the same document
states 46 after the contract work. `m016-subject-deny-mask.md` states
`test_subject_deny.py` — **14 passed** and full portable **1964 passed, 11 failed**;
later runs record 22 and 2017/16. All accurate for their respective moments. Stale, not
contradictory.

**I6 — `m016-subject-deny-mask.md` describes a now-superseded production state.**
Its header records `Production NOT modified … paths: 7` with the subject deny verified.
That was true when written, before the incident. The authoritative snapshot has **8**
paths, so the count changed between the two records. The document must not be read as a
current statement of production state.

## 15. Read-only verification at close

```
PRODUCTION_TOUCHED       = NO
production fingerprint   = count=6 sha=70055d5451247ecdeed013d4339e580db3129d577bd74498597a8347601ee18f
                           (identical before and after this milestone)
recipe                   = per path: FullName | PSObject type | Access-section SDDL | AreAccessRulesProtected
AreAccessRulesProtected  = False   (all 6 paths)
explicit ACE count       = 0
model\ present           = False
HARNESS_SAFETY           = VERIFIED
M016_CONTAINMENT         = REJECTED
PRODUCTION_RECOVERY      = NOT_VERIFIED
```

Current production contents, read-only:

```
subject_runtime/                          dir   prot=False
subject_runtime/config/                   dir   prot=False
subject_runtime/runtime/                  dir   prot=False
subject_runtime/runtime/m016_disposable_target.exe    prot=False
subject_runtime/runtime/m016_read_fixture.exe         prot=False
subject_runtime/runtime/m016_subjectrun_fixture.exe   prot=False
model\                                    ABSENT
```

Three of the four fixture artifacts named in the restoration target (§14 **I1**)
are **still present in production right now**; the fourth,
`m016_delete_target`, was deleted during the incident.

M018 implementation is **not** begun and is not authorized by this record.