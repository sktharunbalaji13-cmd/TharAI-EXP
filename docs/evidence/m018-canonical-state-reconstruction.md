# M018 — Canonical Production State Reconstruction and Recovery-Target Preparation

**M018_CANONICAL_STATE = PASS**
**PRODUCTION_TOUCHED = NO**
**P0_RECONSTRUCTED = YES** · **P1_RECONSTRUCTED = YES** · **R_RECONSTRUCTED = YES** · **C_RECONSTRUCTED = YES**
**R_VS_C_DELTA = COMPLETE**
**EXACT_ACE_STATUS = NOT_ESTABLISHED**
**HARNESS_SAFETY = VERIFIED**
**PRODUCTION_RECOVERY = NOT_ATTEMPTED**
**MECHANISM_SELECTED = NO**

Read-only milestone. No production ACL, file, privilege, account or group was
changed; no mechanism was selected; no recovery was attempted. Date 2026-10-01.
HEAD `3c91b340e9a5d28c32f351700d4f7b3d514f1cf4`, nothing committed.

---

## 1. Scope and non-mutation declaration

Reconstruct the production security states relevant to M015/M016/M017 as four
**distinct, evidence-backed objects**, and make the difference between the recorded
historical state and the intended policy explicit.

**Not done in this milestone:** any production ACL or file change; any containment
mechanism; any recovery or restoration; any inheritance experiment against
production; any probe run against production; any privilege grant; any selection of
a recovery target or mechanism.

Two rules observed throughout:

- **This milestone does not choose whether R or C becomes the eventual recovery
  target.** That decision gets its own governance gate.
- **Historical artifacts are not rewritten.** Where an earlier artifact overstates
  its evidence, the overstatement is corrected in this record and the original is
  left in place (§10).

## 2. Canonical fingerprint recipe

M017 finding **G6**: a fingerprint recorded only as prose, with no stored artifact
and no recipe, is not reproducible. During M017's close-out an ad-hoc fingerprint
omitted the path-type term and produced `0fb72590…` against a recorded
`70055d54…` — which reads as "production changed" when it had not.

The recipe is now **code**, not prose:

- implementation — `tests/canonical_state.py`
- tests — `tests/test_canonical_state.py` (33 passed)

```
RECIPE_ID  babylab/production-acl-fingerprint/v1

per-path record, in serialisation order:
  relative_path            posix, relative to subject_runtime; "." for the root
  path_type                "dir" | "file"
  exists
  access_sddl              AccessControlSections::Access ONLY (no owner, no audit)
  access_rules_protected

ordering      case-folded relative path, root first
serialisation one '|'-joined line per path, fields in the order above,
              booleans as true/false, newline-separated, UTF-8
digest        SHA-256, with RECIPE_ID hashed in as the first line
```

Properties asserted by test, not by comment:

| property | why it matters |
|---|---|
| deterministic across runs | two reads of unchanged state produce the same value |
| every field affects the value | a field recorded but never compared would be invisible; a test covers all five |
| `path_type` is included | a file replacing a directory must not collide — this is the exact term whose omission caused the M017 false alarm |
| `RECIPE_ID` is hashed in | two recipes cannot collide by coincidence |
| the record carries its recipe id and field list | a cross-recipe comparison is visibly invalid rather than silently wrong |

**Standing rule adopted from G6:** a fingerprint comparison is meaningful only when
the complete recipe — including path-type treatment — is identical. A mismatch is
not evidence of a change until the recipes are confirmed identical.

**Superseded.** The M017 close-out value `70055d54…` was produced by an ad-hoc
PowerShell recipe (path | type | SDDL | protected) that is **not** this recipe. It
remains valid as evidence that production was unchanged *within M017*, and it is
**not comparable** to any `v1` value. P1 below is the first value under the
canonical recipe.

## 3. P0 — recorded pre-incident production state

**Epistemic status: RECORDED.** Not observed by this milestone; reconstructed from
`outputs/evidence/m016-subject-deny/prod_fingerprint_before.json`. Preserved exactly
as evidence. Not normalised, not reinterpreted, not corrected.

| path | role | deny | allow | explicit | inherited | descriptor |
|---|---|---|---|---|---|---|
| `subject_runtime` | boundary | `0x00110156` | `0x00120089` | 1 | 0 | `D:PAI` |
| `runtime` | boundary | `0x00110156` | `0x001200a9` | 1 | 0 | `D:PAI` |
| `model` | boundary | `0x00110156` | `0x00120089` | 1 | 0 | `D:PAI` |
| `config` | boundary | `0x00110156` | `0x00120089` | 1 | 0 | `D:PAI` |
| `m016_delete_target` | inherited_descendant | `0x00110156` | `0x00120089` | 0 | 1 | `D:AI` |
| `m016_disposable_target.exe` | inherited_descendant | `0x00110156` | `0x001200a9` | 0 | 1 | `D:AI` |
| `m016_read_fixture.exe` | inherited_descendant | `0x00110156` | `0x001200a9` | 0 | 1 | `D:AI` |
| `m016_subjectrun_fixture.exe` | inherited_descendant | `0x00110156` | `0x001200a9` | 0 | 1 | `D:AI` |

`status` field: `SUBJECT_DENY_NOT_VERIFIED`.

Four genuine structural paths (`subject_runtime`, `runtime`, `model`, `config`);
four fixture artifacts (§4).

## 4. P0 contamination analysis

**Four of eight P0 paths are harness fixture artifacts**, per M017 finding I1:

| path | origin |
|---|---|
| `m016_delete_target` | `tests/test_boundary_harness.py:333` — created and `rmtree`'d |
| `m016_disposable_target.exe` | probe `acl_target` / M016 launch fixture |
| `m016_read_fixture.exe` | probe `read_file` fixture |
| `m016_subjectrun_fixture.exe` | `tests/test_m016_launch.py:354` — operator control fixture |

These are the artifacts of the tests that caused the incident. Consequences, stated
plainly:

1. **P0 is not a clean description of the intended production state.** Half its
   paths are debris.
2. **A byte-for-byte restoration to P0 would recreate test artifacts in
   production** and would reproduce the debris as "the desired state".
3. The debris is not uniformly classified: `m016_delete_target` is marked
   `inherited_descendant` like the genuine structure, so **the snapshot's own
   `role` field does not distinguish debris from production paths.** Any consumer
   filtering on `role` would wrongly retain `m016_delete_target`.

**P0 is evidence of what was observed. It is not a specification.** Nothing here
removes or reinterprets these entries; this section exists so a later reader cannot
adopt P0 as a target by accident.

## 5. P1 — current production state

**Epistemic status: OBSERVED by this milestone.** Read-only inspection.
Artifact: `outputs/evidence/m018-canonical-state/P1_current_production.json`.

```
recipe_id   babylab/production-acl-fingerprint/v1
path_count  6
fingerprint f73eaf783ffb2698087a3053fbf90f261f832b5036d78d3a88a0a6526380e0d5
```

| relative path | type | `access_rules_protected` |
|---|---|---|
| `.` | dir | false |
| `config` | dir | false |
| `runtime` | dir | false |
| `runtime/m016_disposable_target.exe` | file | false |
| `runtime/m016_read_fixture.exe` | file | false |
| `runtime/m016_subjectrun_fixture.exe` | file | false |

Observed descriptor facts:

- **no explicit ACEs anywhere** — all six paths are fully inherited;
- **`Authenticated Users` Modify inherited** (`0x001301bf` plain,
  `SDGXGWGR` inheritable) from `C:\dev\TharAI-EXP`;
- `BUILTIN\Users` `0x001200a9` inherited;
- `BABY_AI_TEST` explicit ACE count **0**;
- `model\` **absent**;
- `m016_delete_target` **absent** (deleted during the incident) — the only P0 path
  that no longer exists.

P1 is **not comparable** to the M017 close-out value (§2). It is the first P1 under
the canonical recipe and is the baseline for future comparisons.

**Provenance caveat, stated rather than hidden.** `outputs/` is gitignored
(`.gitignore:95`), so `P1_current_production.json` exists on disk but **would not be
committed**. That matters because M017 finding I2 was precisely that a value recorded
only outside version control is not a durable artifact — the P1 record would repeat
that weakness. The fingerprint value is additionally inlined in §5 of this document,
which *is* tracked, so the value survives in version control even though the full
record does not. Resolving this properly belongs to the next governance gate, not to
a unilateral change here.

## 6. R — historical restoration candidate

**Epistemic status: RECORDED.** Derived from the same single artifact as P0.
Represents the historical restoration candidate **as the evidence that exists**.

R is characterised by what it *is*, not by what it is called. It is **not** described
as correct, desired, clean, intended, or canonical: the evidence supports none of
those characterisations.

Properties of R as an artifact:

- it contains **path and descriptor state data**, not a restorable filesystem image;
  the files' contents are not recorded, only their ACLs and existence;
- the fingerprint value `02c5e4c4…` **is not stored in it** and is **not a
  restoration image** — it is a hash of descriptor readings that, per §2, was
  produced by a recipe that no longer matches the canonical one;
- it includes the four fixture paths (§4);
- its ACL implementation uses the **legacy deny `0x00110156`**;
- boundaries are `D:PAI` with `explicit: 1`.

**R inherits P0's contamination.** R and P0 share one source artifact, so any defect
of that artifact is a defect of both. R is therefore a candidate *subject to* §4 and
§12, not a target.

## 7. C — intended M015 boundary specification

**Epistemic status: SPECIFIED**, derived from the M015 implementation and its
verification contract — `foundation/staging.py`, `verify_boundary()` and
`apply_boundary()`. Not implemented. Not inferred from the contaminated snapshot.

### Established invariants

| # | invariant | source |
|---|---|---|
| C1 | paths are exactly `subject_runtime` + `runtime`, `model`, `config` | `SUBTREES`, `apply_boundary` |
| C2 | inherited `Authenticated Users:(I)` **absent** on every path; `Authenticated Users` and `BUILTIN\Users` must hold no `(M)` or `(W)` | `verify_boundary.inherited_modify_absent_everywhere` |
| C3 | subject's grant set must **equal** exactly `{R,X}` on `runtime` and `{R}` on root / `model` / `config` — a superset fails | `verify_boundary.subject_rights_exact_everywhere` |
| C4 | subject holds a **non-empty deny** on every path, and the deny must not itself grant | `verify_boundary.subject_deny_backstop_present_everywhere` |
| C5 | owner is **non-empty and not the subject** — an unreadable owner is *unverified*, never "not the subject" | `verify_boundary.subject_is_not_owner_everywhere` |
| C6 | operator, SYSTEM, Administrators each `(OI)(CI)(F)` | `apply_boundary.per_subtree` |
| C7 | `enforcement = ACL_OBSERVATION_ONLY`; OS enforcement is **NOT_TESTABLE** until a real `BABY_AI_TEST` process is launched and refused | `verify_boundary.enforcement_note` |
| C8 | confidentiality **NOT PROVIDED**; network **NOT ESTABLISHED** | module constants |

### NOT ESTABLISHED — recorded as unresolved design choices

| property | status |
|---|---|
| the exact deny **mask** C requires | **NOT ESTABLISHED.** C4 requires "a deny, not granting". The legacy implementation uses `0x00110156`; M016 produced `0x000d0156` as an exact candidate. **Choosing between them is a design decision, not a recovery fact.** |
| whether `FILE_TRAVERSE` must be present on root / `model` / `config` | **NOT ESTABLISHED.** `verify_boundary` compares icacls *letters*, and traverse is not representable in the letter set used, so the specification cannot express it. R's recorded masks omit it (§8). This is G5, still open. |
| whether the `AI` (auto-inherited) descriptor flag on a protected descriptor is acceptable | **NOT ESTABLISHED.** R carries `D:PAI`; C specifies `inherited Modify absent` but says nothing about `AI`. |
| confidentiality / network isolation requirements | **NOT ESTABLISHED**; C8 records only that they are not provided by ACLs. |

### Out of scope for C

The damaged production ACL is **not** the canonical design. A containment mechanism
is **not** a substitute for C. R is **not** C (§8, §9).

## 8. R versus C delta

Neither side is declared the winner. Computed from the recorded snapshot against the
invariants in §7.

| # | property | R (recorded) | C (specified) | verdict |
|---|---|---|---|---|
| 1 | **test-fixture paths** | 4 of 8 paths are harness artifacts | C1 defines 4 paths, none of them artifacts | **R violates.** Fixture debris has no place in the intended boundary. |
| 2 | missing / extra paths | 8 paths | 4 paths | **R violates.** R's extra 4 are exactly the §4 debris. |
| 3 | **deny mask** | `0x00110156` on all 8 | NOT ESTABLISHED; must deny write/delete and not grant | **Undecidable.** R is one candidate; it is not disqualified on the mask alone. |
| 4 | `WRITE_DAC` in deny | **absent** | NOT ESTABLISHED at spec level | **R does not enforce it.** The M016 finding. |
| 5 | `WRITE_OWNER` in deny | **absent** | NOT ESTABLISHED at spec level | **R does not enforce it.** |
| 6 | `WRITE_EA` in deny | present (`0x10`) | required by intent | R satisfies. |
| 7 | `WRITE_ATTRIBUTES` in deny | present (`0x100`) | required by intent | R satisfies. |
| 8 | `DELETE` in deny | present (`0x10000`) | required by intent | R satisfies. |
| 9 | `DELETE_CHILD` in deny | present (`0x40`) | required by intent | R satisfies. |
| 10 | `SYNCHRONIZE` in deny | **present** (`0x100000`) | NOT ESTABLISHED | **R denies `SYNCHRONIZE`**, which is outside the M016 intended set. Flagged, not judged. |
| 11 | **inheritance mode** | boundaries `D:PAI` (protected + auto-inherited), descendants `D:AI` (unprotected, inherited) | C2 requires inherited Modify absent; says nothing about `AI` | **Partially undecidable.** R satisfies C2; the `AI` flag is unspecified. |
| 12 | **explicit vs inherited origin** | boundaries `explicit: 1`; debris `explicit: 0, inherited: 1` | C3/C4 need explicit subject entries | R satisfies for genuine paths. |
| 13 | subject allow, root / `model` / `config` | `0x00120089` | letters `{R}` | R satisfies at the letter level. |
| 14 | subject allow, `runtime` | `0x001200a9` | letters `{R,X}` | R satisfies. |
| 15 | **`FILE_TRAVERSE` on root** | **absent** (`0x00120089` has no `0x20`) | NOT ESTABLISHED, but C's intent requires the subject to *reach* the subtrees | **R is internally inconsistent with C's intent.** With no traverse on the root, the subject cannot descend into `runtime`/`model`/`config` at all — so R would satisfy C3's letter test while denying the access C exists to provide. **This is G5 and it is a specification gap, not only an R defect.** |
| 16 | operator access | `FA` explicit at boundaries | C6 | R satisfies. |
| 17 | SYSTEM access | `FA` explicit at boundaries | C6 | R satisfies. |
| 18 | Administrators access | `FA` explicit at boundaries | C6 | R satisfies. |
| 19 | `Authenticated Users` Modify | **absent from the snapshot entirely** | C2 requires absent | R satisfies. |
| 20 | **`BABY_AI_TEST` ownership** | **NOT RECORDED** — the snapshot stores only `allow, deny, role, explicit, inherited, sddl` | C5 requires the subject not be owner | **R CANNOT SATISFY C5.** The artifact has no owner field, so this invariant is unverifiable from R by construction. A new observation is required. |
| 21 | OS enforcement | not measured | C7 requires a real subject launch and refusal | **Both NOT_ESTABLISHED.** |

**Delta summary.** R violates C on fixture paths (1, 2), does not enforce
`WRITE_DAC`/`WRITE_OWNER` (4, 5), cannot demonstrate C5 at all (20), and carries an
unresolved `SYNCHRONIZE` deny (10) and an unresolved `AI` flag (11). R satisfies C
on subject allow letters (13, 14), the write/delete/EA/attribute denies (6–9),
explicit origin (12), operator/SYSTEM/Administrators access (16–18), and AU absence
(19). Two items are **specification gaps rather than R defects**: the deny mask (3)
and `FILE_TRAVERSE` (15).

## 9. Historical evidence versus intended policy

| dimension | P0 / R | P1 | C |
|---|---|---|---|
| epistemic status | RECORDED | OBSERVED (this milestone) | SPECIFIED |
| epoch | pre-incident | post-incident, unchanged since | forward |
| contamination | 4 fixture artifacts | 3 fixture artifacts still present | none by definition |
| boundary present | yes, `explicit: 1` | **no**, zero explicit ACEs | required |
| AU Modify | absent | **present, inherited** | must be absent |
| deny mask | legacy `0x00110156` | none | NOT ESTABLISHED |
| owner recorded | **no** | not recorded by the canonical recipe | C5 requires it |
| restorable | descriptor readings only | n/a | n/a |

Three consequences:

1. **P1 is not R.** They differ on almost every security property.
2. **R is not C.** §8.
3. **R cannot serve as the definition of C**, because R contains debris (4, 20) and
   encodes a superseded implementation of the boundary (`0x00110156`, missing
   `WRITE_DAC`/`WRITE_OWNER`). This is the concrete evidence for M017's conclusion
   that tracks B and C must remain separate.

**Gap in the canonical recipe, stated rather than hidden:** the recipe records DACL
state, not **owner**. C5 requires owner, so **the canonical recipe as written cannot
fully express C**. Adding owner is a recipe change requiring a new `RECIPE_ID`; it is
deliberately not made here, because changing the recipe mid-milestone would
invalidate the P1 value this milestone exists to establish.

## 10. Exact-ACE feasibility evidence status

**EXACT_ACE_STATUS = NOT_ESTABLISHED.**

Stated precisely, with the historical artifacts left unmodified:

1. `outputs/evidence/m016-subject-deny/exact_ace_feasibility.txt` concludes
   `managed exact-mask removal: NOT CAPABLE`. That conclusion came from an **invalid
   fixture**: `icacls /grant` *replaced* the operator rule instead of adding a
   second one, so only one operator ACE (`0x001f01ff`) existed and there was no
   `0x00120089` to preserve.
2. `outputs/evidence/m016-subject-deny/two_ace_retry.txt` **invalidated that
   specific conclusion** by building the fixture correctly:
   `CORRECT_TWO_ACE_FIXTURE = PASS`, with `0x20089/inh` and `0x1f01ff/exp`
   simultaneously present on the same SID.
3. That correct fixture was then destroyed by `/inheritance:d`, which collapsed the
   two same-SID ACEs into one. `RemoveExact` therefore ran against a single-ACE tree,
   returned `1`, and removed the only operator ACE present.
4. **Capability was not demonstrated either.** The no-match case behaved correctly,
   but the discriminating case was never exercised.

Therefore: not "impossible", not "possible" — **NOT ESTABLISHED**. No further
production or inheritance experiment was run to resolve it, per instruction.

Correction applied to the evidence model without rewriting history: the
`NOT CAPABLE` line in `exact_ace_feasibility.txt` is **superseded** and must not be
read as a finding. This mirrors M017 finding I3.

## 11. Evidence provenance and confidence

| claim | source | status |
|---|---|---|
| P0 contents | `prod_fingerprint_before.json` | RECORDED — artifact-contaminated (§4) |
| P1 contents | this milestone, canonical recipe v1 | OBSERVED — high confidence, recipe tested |
| R properties | derived from P0's artifact | RECORDED |
| C invariants C1–C8 | `foundation/staging.py` | SPECIFIED — read from code, not inferred |
| C deny mask | — | **NOT ESTABLISHED** |
| C `FILE_TRAVERSE` requirement | — | **NOT ESTABLISHED** |
| C owner invariant C5 | `verify_boundary` | SPECIFIED, but **unverifiable from R** |
| `/inheritance:d` same-SID loss | `two_ace_retry.txt` | OBSERVED on this host |
| exact-ACE capability | — | **NOT ESTABLISHED** |
| OS enforcement | — | **NOT_TESTABLE** (C7) |
| P0 fingerprint `02c5e4c4…` | prose only | **no stored artifact** (M017 I2) |
| M017 close-out `70055d54…` | ad-hoc recipe | valid within M017; **not comparable to v1** |

Confidence is deliberately asymmetric: P1 and C rest on directly observed or
directly read sources; P0/R rest on a single artifact with known defects. Nothing
above is upgraded beyond its source.

## 12. Unresolved questions

1. Should the recovery target be R, C, or a third object that is C's invariants
   applied to a corrected path set? **This milestone does not answer it.**
2. What is the deny mask C requires? (`0x00110156` vs `0x000d0156` vs other.)
3. Must `FILE_TRAVERSE` be granted on root / `model` / `config` so the subject can
   reach the subtrees? (G5.)
4. Should the `AI` flag on a protected descriptor be accepted?
5. Who owns `subject_runtime`, and may C5 be verified from a fresh observation?
   Requires a recipe change to record owner.
6. Is exact-mask removal possible, and does anything still depend on it? (Only the
   rejected rollback path did.)
7. Should `P1`'s three surviving fixture artifacts be removed? **Not decided here**,
   and not touched — removal is a production mutation.

## 13. Prohibited conclusions

Explicitly **not** concluded by this milestone:

- that R is the correct, desired, clean, intended or canonical production target;
- that C is implementable as specified today (two properties are NOT ESTABLISHED);
- that P0 was ever a clean description of the intended state;
- that exact-ACE removal is impossible, or that it is possible;
- that restoration is or is not achievable on this host;
- that any containment mechanism is appropriate;
- that the 9 red tests should be made green;
- that `PRODUCTION_RECOVERY_VERIFIED` may be set to anything but `NO`.

## 14. M018 acceptance criteria

| criterion | result |
|---|---|
| canonical fingerprint recipe established and recorded | PASS — code + tests, `v1` |
| fingerprints compared only under identical recipes | PASS — M017 value explicitly marked non-comparable |
| P0 reconstructed as evidence, contamination marked | PASS — §3, §4 |
| P1 reconstructed read-only under the canonical recipe | PASS — §5 |
| R represented without endorsement | PASS — §6 |
| C derived from M015 evidence, not from R | PASS — §7 |
| R↔C delta explicit, neither side declared the winner | PASS — §8, 21 properties |
| `NOT ESTABLISHED` used where evidence is absent | PASS — §7, §11, §12 |
| exact-ACE status corrected without rewriting artifacts | PASS — §10 |
| M018 tooling cannot mutate production | PASS — §15 |
| no mechanism selected | PASS |
| untracked tooling untouched | PASS — §15 |

## 15. M018 final status

**M018_CANONICAL_STATE = PASS.** Four canonical objects exist and are kept distinct:
P0 (recorded, contaminated), P1 (observed, current), R (recorded, not endorsed),
C (specified, two properties unresolved). The R↔C delta is complete and shows R
cannot define C. **No production recovery target has been selected — that is the
next governance gate.**

### Harness safety for M018 itself

The inspection tooling points itself at production on every run, so its read-only
property is enforced rather than asserted:

- `tests/canonical_state.py::_run` rejects any argv containing an icacls switch from
  `ICACLS_MUTATING_FLAGS` **before** launching. The set covers `/grant`, `/deny`,
  `/remove:*`, `/inheritance:*`, `/setowner`, `/reset`, `/save`, `/restore`,
  `/delete`, and the recursive/force switches. Parametrised test asserts each one is
  refused.
- A bare `icacls <path>` listing carries no switch and is permitted; a test asserts
  the argv is exactly that, with a fake `subprocess.run` proving the check happens
  pre-launch.
- `dump()` refuses to write inside the repository, so an evidence artifact cannot
  land in production.
- The module reuses the existing policy: production **reads** via
  `read_production_for_verification`, writes refused via `assert_test_write_path`.
- `tests/test_canonical_state.py` — **33 passed**.

### The 9 red tests remain red

Not fixed, not bypassed, not made green. They remain the standing alarm reporting
damaged production. M018 added no production mutation to silence them and did not
attempt to alter the state they report.

### Untracked tooling untouched

`.agents/`, `.claude/`, `.claude-flow/`, `.swarm/`, `.mcp.json`, `CLAUDE.md` — not
modified, not deleted, not committed. The pre-existing `.gitignore` change was left
alone. Nothing committed.

```
PRODUCTION_TOUCHED      = NO
P0_RECONSTRUCTED        = YES
P1_RECONSTRUCTED        = YES   fingerprint f73eaf783ffb2698087a3053fbf90f261f832b5036d78d3a88a0a6526380e0d5
R_RECONSTRUCTED         = YES
C_RECONSTRUCTED         = YES
R_VS_C_DELTA            = COMPLETE
EXACT_ACE_STATUS        = NOT_ESTABLISHED
HARNESS_SAFETY          = VERIFIED
PRODUCTION_RECOVERY     = NOT_ATTEMPTED
MECHANISM_SELECTED      = NO
```

M019 — the R-versus-C target decision — is **not** begun and is not authorized here.