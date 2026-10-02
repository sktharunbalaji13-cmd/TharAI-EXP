# M016 — Exact Subject Deny Mask: 8-Path Production-Shape ACL Rehearsal

**PRODUCTION_MUTATED = NO**

This is a **DISPOSABLE ACL REHEARSAL**. It is not a Baby AI experience, not a
birth, not a subject event, not model execution, and not production verification.

## 1. HEAD

`3c91b340e9a5d28c32b351700d4f7b3d514f1cf4`, unchanged. Nothing committed.

## 2. Working tree

```
 M .gitignore                                          <- pre-existing, not ours
?? docs/evidence/m016-subject-deny-mask.md
?? foundation/subject_deny.py
?? tests/test_subject_deny.py
```

`.agents/`, `.claude/`, `.claude-flow/`, `.swarm/`, `.mcp.json`, `CLAUDE.md`
untouched.

## 3. Production shape, read live

Not inferred from source. Read from `C:\dev\TharAI-EXP\subject_runtime` by a
read-only inspector. Eight paths, depth 2:

| path | type | depth | prot | allow | deny | explicit subject ACEs |
|---|---|---|---|---|---|---|
| `.` | dir | 0 | True | `0x00120089` | `0x00110156` | 2 |
| `config` | dir | 1 | True | `0x00120089` | `0x00110156` | 2 |
| `config\m016_delete_target` | dir | 2 | False | `0x00120089` | `0x00110156` | **0** |
| `model` | dir | 1 | True | `0x00120089` | `0x00110156` | 2 |
| `runtime` | dir | 1 | True | `0x001200a9` | `0x00110156` | 2 |
| `runtime\m016_disposable_target.exe` | file | 2 | False | `0x001200a9` | `0x00110156` | **0** |
| `runtime\m016_read_fixture.exe` | file | 2 | False | `0x001200a9` | `0x00110156` | **0** |
| `runtime\m016_subjectrun_fixture.exe` | file | 2 | False | `0x001200a9` | `0x00110156` | **0** |

Four inheritance boundaries (protection on, explicit ACEs); four descendants
(protection off, zero explicit subject ACEs, inheriting everything).

## 4. Proof the mirror matches production

`compare_shape.py` ran **82 structural checks, 0 mismatches**, comparing
production and mirror on: path set, type, inheritance-protection flag, subject
allow mask, subject deny mask, subject allow/deny ACE counts, explicit subject
ACE tuples (type+mask+inheritance flags), inherited subject ACE tuples, and
**complete DACL SDDL string equality**. Both sides read from disk with the same
inspector.

The mirror is *constructed* through the governed mechanism, not copied from
production's ACLs; production was only read as a specification.

## 5. Implementation changes

**FIX 1 — apply only at inheritance boundaries.** Added `boundary_paths()` (the
staging root plus one per `SUBTREES` entry, derived from the same map
`apply_boundary` uses) and `inherited_paths()` as its complement. `apply_subject_deny`
now targets boundaries only. Isolation-measured: `/remove:d` then the native
rewrite on a boundary does *not* pin children (cases E and F), so excluding
descendants from the target list is what keeps them inheriting.

**FIX 2 — descriptor-exact rollback.** Added `_ace_structure()` and `_allow_masks()`.
The snapshot now records each path's SDDL, explicit/inherited deny counts, and
inheritance-protection flag, not just the mask. `_restore_dacls` processes
descendants first (clear the explicit deny, re-enable inheritance where the
snapshot recorded none, so the restored parent flows the deny back in), then
boundaries via the measured-exact `icacls` token set. Added `verify_rollback()`,
which **rereads the live descriptor and decides** — deliberately separate from
the write path so a bug in the restore cannot certify itself.

**FIX 3 — verifier checks ACE origin.** `verify_subject_deny` now reports `role`
(`boundary` / `inherited_descendant`) and asserts the right origin per role:
one explicit deny and nothing inherited on a boundary; zero explicit and exactly
one inherited on a descendant. It also checks the subject allow mask is preserved
(`0x00120089` or `0x001200a9`) and that no `Authenticated Users` write ACE exists.

**FIX 4 — 22 focused tests**, including `test_apply_does_not_pin_inherited_descendants`,
`test_rollback_restores_the_complete_descriptor_not_just_the_mask`,
`test_rollback_removes_an_explicit_ace_the_snapshot_did_not_have`,
`test_verify_rollback_fails_when_the_descriptor_does_not_match`, and
`test_rehearsal_gate_end_to_end`.

The test fixture was rebuilt to the production shape (9 paths, nested directory,
three files under `runtime`, `runtime` granted RX). Previously it granted `R`
everywhere and never severed inheritance on the subtrees, so it could not have
caught either defect.

## 6. Boundaries and descendants

Boundaries (explicit deny, exactly one): `subject_runtime`, `runtime`, `model`,
`config`.

Descendants (no explicit deny, inherit exactly one): `config\m016_delete_target`,
`config\m016_delete_target\deep.bin` (test fixture only),
`runtime\m016_disposable_target.exe`, `runtime\m016_read_fixture.exe`,
`runtime\m016_subjectrun_fixture.exe`.

## 7. Post-apply ACE structure — descendants stay inheritance-only

```
.                                    boundary   explicit=1 inherited=0
config                               boundary   explicit=1 inherited=0
config\m016_delete_target            descendant explicit=0 inherited=1
model                                boundary   explicit=1 inherited=0
runtime                              boundary   explicit=1 inherited=0
runtime\m016_disposable_target.exe   descendant explicit=0 inherited=1
runtime\m016_read_fixture.exe        descendant explicit=0 inherited=1
runtime\m016_subjectrun_fixture.exe  descendant explicit=0 inherited=1
```

This is the defect the previous rehearsal caught. It pinned the three runtime
files (deny ACE count 1 → 2, explicit 0 → 1). Fixed and now asserted per path
against the live descriptor.

## 8–13. Post-conditions, all 8 paths

| condition | result |
|---|---|
| exact mask `0x000d0156` | PASS on all 8 |
| SYNCHRONIZE absent | PASS on all 8 (`sync bit set=False`) |
| `WRITE_DAC` denied | PASS on all 8 |
| `WRITE_OWNER` denied | PASS on all 8 |
| `FILE_WRITE_ATTRIBUTES` denied | PASS on all 8 |
| `FILE_WRITE_EA` denied | PASS on all 8 |
| write-data / append / delete / delete-child denied | PASS on all 8 |
| read bits not denied | PASS on all 8 |
| execute bit not denied | PASS on all 8 |
| subject allow preserved (`0x00120089`/`0x001200a9`) | PASS on all 8 |
| no `Authenticated Users` write ACE | PASS on all 8 |
| verifier verdict | `SUBJECT_DENY_VERIFIED`, all correct: True |

## 14. Rollback — descriptor-exact

Independent verification (`verify_rollback`, a separate reread):

```
all_restored        : True
  all_masks_match   : True
  all_sddl_match    : True
  all_structure     : True
  sddl exact strings: False
```

Every path: before `0x00110156` → applied `0x000d0156` → restored `0x00110156`,
daclMatch True, protKept True.

**One documented non-determinism.** Descendant SDDL does not match as an exact
*string* after rollback; it matches as an ACE *set*. Measured cause:

```
pre     (D 0x110156)(A 0x1200a9)(A FA BA)(A FA SY)(A FA 1001)
restored(D 0x110156)(A FA SY)(A FA BA)(A FA 1001)(A 0x1200a9)
```

Same five ACEs, same masks, same flags — only Windows' canonical ordering moved.
Windows re-canonicalises ACE order on every rewrite, so exact string equality is
not a correctness test. `canonical_aces()` compares `type|mask|sid|inheritance|
propagation` as a sorted multiset, keeping the flags because inheriting vs
non-inheriting is the distinction this whole change turns on. Boundaries — which
are rewritten in place — match the exact string, and that is asserted separately.

## 15. Gate result

```
checks failed            : 0
PRODUCTION_MUTATED = NO
```

Production verified untouched by SDDL comparison before *and* after: all 8 paths
still `0x00110156`, DACL byte-identical, path count unchanged.

## 16. Test counts

- `tests/test_subject_deny.py` — **22 passed**
- `tests/test_m010_boundary.py` + `test_m016_launch.py` + `test_staging_boundary.py`
  — 71 passed, 1 failed (the known `test_no_model_was_selected_or_staged`)
- Full portable — **1971 passed, 11 failed**, 749 subtests. All 11 verified by
  name against the baseline at `3c91b34`; **no new failures**.

## 17. Remaining NOT_TESTABLE

- Unattended subject launch.
- Runtime execution under the subject.
- Model execution — no model selected or staged.
- M005 byte-identity — unchanged, 7 tests pass.
- Subject-side enforcement. This rehearsal verified **ACL structure only**. Whether Windows refuses an actual operation is unmeasured here; that needs the interactive `runas` probe with the operator's password, which was not requested or recorded.

## 18. Defects found and fixed in this iteration

1. **Pinning (FIX 1).** Explicit deny written onto inherited descendants.
2. **Mask-only rollback (FIX 2).** Descriptor residue survived the restore. This supersedes the earlier "bit-exact rollback" claim: it was mask-exact, not descriptor-exact.
3. **SDDL string comparison too strict (FIX 2).** ACE re-canonicalisation made a correct restore look wrong. Now an ACE-set comparison with exact-string equality reported separately.
4. **Restore self-certified (FIX 2).** `_restore_dacls` computed its own pass/fail. Now delegates to `verify_rollback`.
5. **Verifier blind to ACE origin (FIX 3).** A pinned descendant with the right mask read as correct.
6. **Test fixture could not catch either defect (FIX 4).** It granted `R` everywhere and never severed subtree inheritance, so no descendant ever inherited.

## 19. Residual, not fixed

Root, `model` and `config` carry an allow mask of `R`, which lacks
`FILE_TRAVERSE`, so the subject cannot descend the tree at all. Preserving the
existing allow mask was a stated constraint; reported rather than silently
broadened. Fixing it is a separate governed decision.

## 20. Next step

Production correction is **not** authorised by this document. This rehearsal
establishes that apply and rollback behave correctly on the real hierarchy. Any
production change remains a separate step requiring review of this result.