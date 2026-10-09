# M052K — D3 Implementation: Rehearsed, Proven, Frozen

```
M052K_PHASE              = FROZEN_READY_FOR_PRODUCTION
M052K_STATUS             = AWAITING_EXPLICIT_HUMAN_AUTHORISATION
D3_MASK                  = 0x000D0156
TARGET_PRINCIPAL         = BABY_AI_TEST  S-1-5-21-2406520953-1060965512-844951592-1022
PRODUCTION_TARGET        = subject_runtime
INHERITANCE_FLAGS        = ContainerInherit, ObjectInherit   (load-bearing, not optional)

PRODUCTION_CHANGED       = NO
PRODUCTION_ACL_CHANGED   = NO
PRODUCTION_FINGERPRINT   = UNCHANGED (v1 f73eaf78… / v2 1684a02f… exact)
PRODUCTION_OWNER         = S-1-5-21-…-1001 (unchanged)
PRODUCTION_INHERITANCE   = unprotected, 8 inherited ACEs, 0 explicit (unchanged)
PRODUCTION_SUBJECT_ACES  = 0
SUBJECT_LAUNCH           = NOT_ATTEMPTED
T_BABY_1                 = SATISFIED (established_by M052H, unchanged)
M019+A1                  = UNCHANGED (7dceb7a5…, amendment PASS)
SECURITY_OBJECTIVE       = NOT_SATISFIED — shortfall 5 of 8
D4                       = NOT IMPLEMENTED
VALIDATION               = 38/38 PASS   (87 tests)
REGRESSION               = 360 passed, 2 skipped (pre-existing); 12 standing reds unchanged
```

> **This milestone built and proved an implementation. It did not apply it.**
>
> Every one of the fourteen Step-11 authorisation conditions passes. The single production ACL write
> is gated behind **two independent interlocks**, both closed. `production_application()` returns
> `AWAITING_EXPLICIT_HUMAN_AUTHORISATION` and cannot do otherwise: no authorisation object exists,
> and the module interlock is `False` in the committed tree even if one did.

---

## 0. Why this milestone stops here

The brief's closing note asked whether this lab's governance requires explicit human approval for
every production mutation, and said that if it does, the agent should stop at
`FROZEN_READY_FOR_PRODUCTION` and request approval.

It does, and the reasons are not procedural habits — they are load-bearing:

1. **Every prior production-affecting act in this project was human-gated.** M029 was an explicit
   human-gated measurement decision; M031 an experimental hold pending human session handoff; M042
   onward each required a human to supply the authorisation token before a live attempt. Live
   attempts have been treated as one-shot authorisations.
2. **M052J explicitly authorised nothing.** It selected a mask and recorded that it does not permit
   `icacls`, `SetNamedSecurityInfo`, inheritance changes, ownership changes, or containment. Treating
   a design decision as permission to implement it would invert the decision/implementation separation
   this project exists to maintain.
3. **A standing authorisation must never be silently reused.** D3's selection is not D3's
   application.
4. **This would be the first mutation of canonical production in the project's history.** M016
   established that a containment deny can become unrecoverable. M052K has *proved* rollback on a
   disposable topology, but proving it there is not the same as having done it here.

So the milestone ends frozen. What follows is the evidence that would support an authorisation
decision, not a record of a write.

---

## 1. Production prestate (read-only)

Canonical `subject_runtime` is **inside the repository**, so the project's existing mutation gate
already refuses it — verified, not assumed:

```
assert_test_write_path("C:\dev\TharAI-EXP\subject_runtime")
  -> ProductionPathViolation: the path is inside the repository (mutation)
```

M052K's guard is layered on top of that rather than relying on it. The earlier probe of
`C:\ProgramData\TharAI\subject_runtime` — a wrong guess about where production lives — came back
`ALLOWED`, and that is recorded here because it nearly produced a false sense of coverage.

| | `.` | `runtime` | `model` | `config` |
|---|---|---|---|---|
| exists | yes | yes | **no** | yes |
| owner | `…-1001` (operator) | `…-1001` | unreadable | `…-1001` |
| protected | no | no | — | no |
| **explicit ACEs** | **0** | **0** | — | **0** |
| subject ACEs | **0** | 0 | — | 0 |
| SDDL | `D:AI(A;ID;FA;;;BA)(A;OICIIOID;GA;;;BA)(A;ID;FA;;;SY)(A;OICIIOID;GA;;;SY)(A;ID;0x1301bf;;;AU)(A;OICIIOID;SDGXGWGR;;;AU)(A;ID;0x1200a9;;;BU)(A;OICIIOID;GXGR;;;BU)` | (same) | — | (same) |

Every ACE is inherited; **not one of them names the operator SID**. Section 5 explains why that
matters more than it looks.

---

## 2. The mechanism — and a claim of mine that measurement refuted

I entered this milestone believing `icacls /deny` could not express the mask. The project's own
`ICACLS_DENY_CANNOT_EXPRESS` is `(0x40000, 0x80000)` = `WRITE_DAC | WRITE_OWNER`, which looked like a
prior measurement of exactly this limitation.

**Measurement refutes it.**

```
icacls probe:  icacls <tree> /deny *S-1-5-21-…-1022:(WD,AD,WEA,WA,DE,DC,WDAC,WO)
  rc 0 · "Successfully processed" · principal resolved
  requested  0x000D0156
  STORED     0x000D0156      <- exact
  verdict    ICACLS_DENY_EXPRESSES_MASK
```

The probe's *first* run appeared to confirm the constant, and that appearance was entirely my own
error: I had hand-mapped the letters as `(WD,AD,WDAC,WO,MA,DC,WA)`. `MA` is not DELETE — that is `DE`
— and `WA` is write-*attributes*, not write-*EA*, which is `WEA`. icacls accepted the wrong letters,
printed success, and stored `0x000C0146`: silently narrower than requested, missing DELETE and
WRITE_EA.

That is M020's SYNCHRONIZE lesson again — score what Windows **stored**, never what was requested —
and it is why the probe's verdict is computed from the stored mask and the corrected letters are
asserted against the stored result.

### The actual justification for .NET

Not the mask. **The rollback.**

| | icacls | .NET `AddAccessRule` / `RemoveAccessRuleSpecific` |
|---|---|---|
| express the mask | yes (measured) | yes (measured) |
| add one per-SID deny | yes | yes |
| **remove exactly that deny ACE** | **no such verb** | yes |
| removal scope | principal-wide (`/remove`) | per-rule |

icacls' removal verbs are principal-wide, and M019 §7 records principal-wide removal as *not* an
acceptable administrative operation — it is exactly the operation that could take an operator baseline
ACE with it. M052J's binding constraint is a per-SID removal that provably preserves every
pre-existing ACE. `RemoveAccessRuleSpecific` does that, and `prove_rollback` demonstrates it.

Both mechanisms are frozen; only the .NET pair is authorised for use.

---

## 3. Disposable topology — material fidelity, honestly graded

Production's *entire* descriptor is inherited, so reproducing it required reproducing a parent. Two
things were not guessable and had to be read:

- **The repo root has zero explicit ACEs.** Production's chain is inherited up to a higher directory.
  The first attempt copied the parent's explicit ACEs, got an empty list, and produced a fixture with
  no ACL at all — which then failed `icacls` with `Access is denied` and read back as `exists: False`.
- **`/inheritance:r` on the fixture parent strips it to `D:PAI`**, orphaning the child. This is M021's
  documented hazard reached from the fixture side. The fix is ordering: **build the tree first, then
  seed the parent**, letting inheritance propagate down — the same mechanism production itself used.

The grants are read from production's observed inherited set at build time and asserted against it, so
this is a derivation with a cross-check rather than a transcription.

**Material properties — all 8 match:**

| Property | Result |
|---|---|
| subject has no ACE | ✓ |
| descriptor unprotected | ✓ |
| all ACEs inherited | ✓ |
| Administrators full control `0x001F01FF` | ✓ |
| SYSTEM full control `0x001F01FF` | ✓ |
| Authenticated Users `0x001301BF` | ✓ |
| BUILTIN\Users `0x001200A9` | ✓ |
| no explicit ACEs on the root | ✓ |

**`exact_match` is `False`, and is not expected to hold.** Production carries 8 ACEs; the fixture
carries 4. The 4-entry delta is cosmetic and originates above the repository: production has
`InheritOnly` copies whose masks drop `FILE_WRITE_EA` (`0x001F01FF` → `0x001F01EF`) and an
`S-1-5-3-4` entry from further up the chain. Those are artifacts of inheritance from a directory this
milestone cannot and should not reconstruct. The full delta is reported verbatim in the record rather
than smoothed away.

---

## 4. Apply and effective access

```
MECHANISM                 DOTNET_ADD_ACCESS_RULE_PER_SID_NON_RECURSIVE
stored subject deny       0x000D0156        (exactly the objective mask)
extra rights stored       none
owner changed             NO
inheritance protection    unchanged (False)
non-subject ACEs changed  NONE
SYSTEM ACE                present
Administrators ACE        present
```

All eight objective rights denied in **effective** access, not merely in DACL representation:

```
forbidden_present        []           <- all eight absent
retained_rights_lost     []           <- FILE_READ_DATA / READ_ATTRIBUTES / READ_EA all retained
subject_denied           0x000D0156
```

The absence is credited to the **explicit deny**, not to an absent grant — production's
`Authenticated Users` grant would otherwise have supplied five of the eight, which is precisely the
"blocks what happens to be present today" trap M052J refused.

---

## 4a. Addendum — subtree coverage, and a specification gap in the authorisation

Added after the freeze, on the director's review. **No production change; disposable fixtures only.**

M052K's original `all_eight_forbidden_absent` check was **root-scoped**. It measured the descriptor of
`subject_runtime` and nothing below it. That is an incomplete test, and the way it is incomplete is
the precise failure mode this project keeps refusing: a deny on the root directory looks like progress
while everything underneath it stays writable.

Measured on the faithful disposable topology, both variants, all six paths:

| Path | `inheritable=True` | `inheritable=False` |
|---|---|---|
| `.` | 0 forbidden, denied `0x000D0156` | 0 forbidden, denied `0x000D0156` |
| `runtime` | 0 forbidden | **5 forbidden**, `eff=0x001301BF` |
| `runtime/m016_read_fixture.exe` | 0 forbidden | **5 forbidden** |
| `model` | 0 forbidden | **5 forbidden** |
| `config` | 0 forbidden | **5 forbidden** |
| `config/config.json` | 0 forbidden | **5 forbidden** |

The deny lands **correctly on the root in both variants** — which is exactly why root-only checking
proved nothing. With `None` inheritance the deny stops at the directory object and the five forbidden
rights `write, append, write_ea, write_attributes, delete` remain present everywhere beneath.

Five is the same count the standing shortfall already reports. A non-inheritable deny would therefore
reproduce the status quo underneath while *appearing* to reduce the number at the root — the
"blocks what happens to be present today" trap in its purest form.

### Consequence for the authorisation

The drafted authorisation text specifies the **mask** and the **principal** but says nothing about the
**inheritance flags on the new ACE**. Those flags are load-bearing, so the authorisation must name
them, or my default silently decides something material:

> …apply **one explicit DENY ACE** for principal `BABY_AI_TEST` SID
> `S-1-5-21-2406520953-1060965512-844951592-1022` with mask `0x000D0156` and
> inheritance flags **`ContainerInherit, ObjectInherit`**…

**Forward commitment, to be acknowledged:** an inheritable deny also applies to objects created under
`subject_runtime` **after** the write. The boundary would hold for future content, not only present
content. That is desirable here — but it is a standing commitment, not a one-off, and should be
recognised as one.

Nothing about rollback is reopened by this: the rollback proof in §6 was performed with the
**inheritable** variant and restored the exact prestate fingerprint.

Tests added: subtree coverage across all six paths, the `m016_read_fixture.exe` payload path
specifically, and a pin on the inheritance-flag sensitivity so neither the root-only check nor a silent
flag change can recur.

**Validation 38/38 · 87 tests.**

---

## 8a. Guard audit — 11 negative cases, all fail closed

The master prompt asked for adversarial proof rather than assertions, so each unsafe parameter was
**attempted**. All eleven refused, and the correct parameters were still accepted — a guard that
refuses everything is not a guard, it is an outage.

| Case | Refused | Reason |
|---|---|---|
| wrong principal SID (`…-544`) | yes | principal must be the subject SID |
| `Everyone` principal | yes | principal must be the subject SID |
| `Authenticated Users` principal | yes | principal must be the subject SID |
| mask `0xFFFFFFFF` | yes | must be `0x000D0156` |
| legacy mask `0x00110156` | yes | must be `0x000D0156` |
| **missing inheritance flags** | yes | non-inheritable variant is not authorised |
| production target via direct helper | yes | production requires the authorisation-gated path |
| production **subpath** via direct helper | yes | same, and subpaths are covered too |
| rollback with operator SID | yes | principal must be the subject SID |
| rollback without inheritance flags | yes | as above |
| **reparse / junction target** | yes | target is a reparse point |
| *(correct parameters)* | **accepted** | stored `0x000D0156` |

The junction case is real, not theoretical: `os.symlink` created an actual directory link to the
fixture root, and the guard refused it on the reparse-attribute check.

### The defect this exposed

`production_mutation_guard()` was a **pre-flight check a caller could simply not call**. It was
advice, not a control. `apply_script` accepted an arbitrary `sid`, `mask` and `inheritable`, so this
would have been accepted by the code:

```python
apply_script(production_root, sid=ADMIN_SID, mask=0xFFFFFFFF, inheritable=False)
```

Parameter validation now lives **inside** the helpers (`_assert_mutation_parameters`) and runs before
`_ps` is reached, so a rejected call performs no filesystem, ACL or subprocess work.

### The one legitimate bypass

`inheritance_flag_sensitivity()` must *build* the non-inheritable variant in order to demonstrate that
it fails. That is permitted only by passing `REHEARSAL_BYPASS_TOKEN =
"DISPOSABLE_SENSITIVITY_DEMONSTRATION"` — a named constant, not a boolean, so every use is visible at
the call site and in the evidence. **Demonstrating that the non-inheritable variant fails is
legitimate; choosing it is not.** Combining a bypass with `allow_production=True` is refused
unconditionally, by a separate check.

---

## 6D. Future-object inheritance — the standing commitment, measured

The inheritable deny was verified to work on objects that existed at the time. That is not the whole
claim: an inheritable ACE is a commitment about the **future**.

```
created AFTER the deny:  runtime\m052k_future_dir\  and  ...\m052k_future_payload.exe
  denied            0x000D0156   (both)
  forbidden_present []           (both)
  read retained     True         (both)
verdict             FUTURE_DESCENDANTS_BOUND
```

The boundary holds for content that does not exist yet, and read access survives so the deny does not
make the subtree opaque either. Recorded as a **standing commitment** — and it is one of the
acknowledgements the authorisation must carry.

---

## 6K. Reapply rehearsal — the mechanism is not a one-shot

A mechanism that works once is an accident, not a boundary.

```
cycle 1: stored ['0x000D0156']  exact=True covered=True rollback_exact=True residual=[]
cycle 2: stored ['0x000D0156']  exact=True covered=True rollback_exact=True residual=[]
final fingerprint matches base: True
verdict: REAPPLY_CLEAN
```

Install, withdraw cleanly to the exact prestate, install again, land on the identical measured result
both times, with no residual deny after either rollback.

---

## 9. The authorisation object

The previous signature was `production_application(authorization: str | None)`. A string cannot state
inheritance semantics, failure behaviour, or the future-descendant commitment — and the dimensions it
*could* state (mask, principal) are not the ones that were decisive. It has been replaced by
`ProductionAuthorisation`, a frozen dataclass carrying all **17** material dimensions:

```
target · principal_sid · deny_mask · inheritance_flags · binds_future_descendants ·
preserve_owner · preserve_inheritance · preserve_non_subject_aces · no_subject_launch ·
no_d4_implementation · verification_required · failure_behaviour · mechanism_digest ·
issued_by · issued_at · nonce · milestone
```

Every field is checked, and a missing or wrong one is **refused rather than defaulted**, because a
default is a decision nobody made — which is exactly how the inheritance gap survived the first draft.
`mechanism_digest` must match the frozen mechanism, so an authorisation cannot be carried across a
code change. `nonce` is single-use, so a stale authorisation cannot be re-presented later even if
every other dimension still matches.

`failure_behaviour` must equal the named constant `STOP_LEAVE_DENY_IN_PLACE` — named rather than free
text so it cannot be paraphrased into something weaker.

### Four distinguishable outcomes

| Input | Status | Changed |
|---|---|---|
| `None` | `AWAITING_EXPLICIT_HUMAN_AUTHORISATION` | NO |
| wrong type (string, mask, SID, bool) | `REFUSED` + type violation | NO |
| invalid object | `REFUSED` + full violation list | NO |
| valid object | `BLOCKED_BY_MODULE_INTERLOCK` | NO |

A caller must never be able to read "no authorisation supplied" as "authorised"; a test asserts the
refusal paths produce three *distinct* statuses.

The wrong-type path was itself a defect: `production_application("some string")` raised
`AttributeError` instead of refusing. §10 requires fail-closed, and a crash is not a refusal.

---

## 5. Where the operator's authority actually lives

The single most consequential finding of this milestone.

**`sv.effective_access(descriptor, (OPERATOR_SID,))` is `0x00000000` on production — before and after
any change.** No ACE names `…-1001`. Comparing that number would "prove" operator access preserved
while measuring nothing at all.

So three readings are recorded separately, and the vacuous one is labelled:

| Operator token model | Before | After | Unchanged |
|---|---|---|---|
| `sid_only` | `0x00000000` | `0x00000000` | ✓ (**vacuous — cannot observe authority**) |
| `sid_plus_granting_groups` | `0x001F01FF` | `0x001F01FF` | ✓ |
| `unelevated_filtered_admins` | `0x001F01FF` | `0x001F01FF` | ✓ |

Three things are true and only the first is in the descriptor:

1. the group grants the operator's token carries;
2. **ownership** — the operator owns the root, and Windows grants an owner `READ_CONTROL` and
   `WRITE_DAC` irrespective of the DACL unless `OWNER_RIGHTS` is present. `sv.effective_access` models
   the DACL only and is **blind to this**;
3. the empirical fact that the operator can remove the deny again.

Ownership being unchanged is therefore *necessary but not sufficient*. The empirical half is section 6.

The unelevated reading is kept separate deliberately: filtered Administrators membership is never
reported as if it were authority.

This also explains **why a per-SID deny is needed at all**. The subject's baseline token is Everyone +
Authenticated Users + Users — the same set the operator's token carries by membership. Their
DACL-derived access on production is *identical*. Ownership is the only thing separating them, and
ownership is not a grant.

---

## 6. Rollback — M016's regression guard, demonstrated

Not argued (M052J argued it, from principal disjointness). Demonstrated.

```
fingerprint before deny   …
fingerprint after deny    …  (different)
fingerprint after rollback  == before deny      <- EXACT MATCH
residual subject deny ACEs   []
owner after rollback         S-1-5-21-…-1001   (unchanged)
inheritance protected        False             (unchanged)
```

Rollback used no ownership change, no `SetOwner`, no inheritance modification, no `/inheritance`, and
no DACL replacement. The exact fingerprint restoration is also the proof that the
read-modify-write mechanism collaterally damages nothing else on the way through.

M016's unrecoverable-by-construction case — removing the very access needed to undo the operation — is
unreachable by this mechanism, and that is now a tested property rather than a hope.

---

## 7. Same-SID safety

**Production has no operator ACE to coalesce with**, because it has no operator ACE at all. Step 8's
scenario therefore has no production instance, and M026/M021 record it as a standing regression
anyway. It gets its own disposable topology: explicit operator ACE `0x001F01FF` **plus** an explicit
subject allow ACE `0x001201BF` — the harder case, since a subject that already holds rights is exactly
where an add could merge into, or replace, something.

```
operator ACE before          0x001F01FF  explicit
operator ACE after           0x001F01FF  explicit      unchanged, count 1 -> 1
non-subject ACEs changed     NONE
after rollback: subject deny removed   TRUE
                subject allow SURVIVED TRUE
                operator ACE           still present
verdict                      SAME_SID_SAFE
```

`AddAccessRule` is used rather than `SetAccessRule` precisely so an existing same-SID allow cannot be
replaced — the write is additive.

---

## 8. Target narrowness

```
mechanism recurses              NO   (no /T, no -Recurse, no Get-ChildItem, no ForEach)
targets exactly one path        YES  (Get-Item -LiteralPath $env:D3_TARGET)
wildcards in mechanism          NO
target is a reparse point       NO
owner / inheritance touched     NO
SetAccessRule (replace)         NO
broad principal literals        NONE
principal supplied by caller    YES
verdict                         NARROW_TARGET_OK
```

Every value reaches PowerShell by environment variable, so no principal, mask, or path is ever
interpolated into PowerShell source.

---

## 9. Step 11 — all fourteen conditions pass

```
 1 disposable application passed                      PASS
 2 disposable effective-access verification passed    PASS
 3 operator access preserved                         PASS
 4 SYSTEM preserved                                  PASS
 5 Administrators preserved                          PASS
 6 same-SID regression passed                        PASS
 7 rollback passed                                   PASS
 8 exact prestate restoration                        PASS
 9 reparse/recursion guard passed                    PASS
10 mutation target is subject_runtime                PASS
11 production fingerprint matches prestate           PASS
12 selected mask unchanged (0x000D0156)               PASS
13 target SID is BABY_AI_TEST                        PASS
14 no M052G / M052H / M019 drift                      PASS
```

**PASS — `PRODUCTION_APPLICATION_BLOCKED` is not the verdict; the gate is satisfied and the remaining
blocker is the authorisation, not the evidence.**

---

## 10. Failure semantics — fail closed

If a future authorised production write succeeds but any post-mutation invariant fails, the required
behaviour is **STOP, and leave the deny in place**. Specifically not permitted:

- improvising a different ACL command;
- broadening permissions;
- removing the deny blindly;
- principal-wide removal (`/remove`, `/remove:g`) — M019 §7;
- changing inheritance or ownership;
- "repairing" manually;
- retrying with a different mask.

The failed state is preserved as evidence. The only permitted recovery is the frozen, proven
`RemoveAccessRuleSpecific` procedure, and only when the authorisation's own rules permit it. A
rejected rollback leaves the deny installed **deliberately** — an unrecoverable boundary is better
than an improvise one, which is M016's whole lesson.

---

## 11. Frozen artefacts

```
mechanism                    DOTNET_ADD_ACCESS_RULE_PER_SID_NON_RECURSIVE
selected_mask                0x000D0156
target_principal             S-1-5-21-2406520953-1060965512-844951592-1022  (BABY_AI_TEST)
production_target            subject_runtime
inheritable                  True (so the deny reaches runtime\ and config\)
apply_script_sha256          recorded in freeze()
rollback_script_sha256       recorded in freeze()
mechanism_combined_sha256    recorded in freeze()
phase                        FROZEN_READY_FOR_PRODUCTION
```

---

## 12. What was not done

- **No production ACL was changed.** Production still has **0 explicit ACEs**, **0 subject ACEs**,
  fingerprints exact, `STAGING_BLOCKED`, owner unchanged.
- **The security objective remains `NOT_SATISFIED`, shortfall 5 of 8.** Building a mechanism that
  satisfies the objective satisfies nothing.
- **No property was marked SATISFIED.** 36 properties unchanged; the 15 D3-gated properties remain
  DECISION-BLOCKED until a deny is actually applied and a descriptor re-read.
- **D4 was not implemented.** `D3 SELECTED` → `D3 IMPLEMENTED` → *boundary exists* is not
  `D3 IMPLEMENTED` → *every property proven*. D4 remains `NOW_ELIGIBLE_TO_BE_DECIDED`.
- **No subject was launched.** No credential was read.
- **M019+A1 and M052H evidence are untouched.**

---

## 13. Standing red tests and regression classification

Unchanged and unweakened: `foundation/security_verify.py`, `tests/guarded.py`,
`tests/test_boundary_harness.py`, `tests/test_subject_boundary_run.py`. Not repaired — they were red
before M052K and are red after, for their own reasons. M052K modified none of them; `git diff --stat`
over those four files is byte-identical to the baseline captured at the start of this milestone.

**The 12 standing reds** (`test_boundary_harness.py` 6, `test_subject_boundary_run.py` 6) are the
pre-existing baseline, not new failures. No test was weakened, deleted, or skipped to obtain a PASS,
and M052K added no skip markers.

**Regression run:**

```
M052K suite                     87 passed
M052I + M052J + M052K + M052H
  + M052G + M052C + M052B
  + M052A + M052 + M051        360 passed, 2 skipped (pre-existing)
standing reds                    12 failed (pre-existing, unchanged)
```

The 2 skips are pre-existing and in files M052K did not touch.

---

## 14. Provenance

Frozen mechanism — **unchanged from the baseline captured at the start of this milestone**, which
matters because `ProductionAuthorisation.mechanism_digest` is checked against it:

```
mechanism                 DOTNET_ADD_ACCESS_RULE_PER_SID_NON_RECURSIVE
apply_script_sha256       00e4262037b9242f5373824a4cdfbe67adf61b771e00b6747bb9d6a3a9f0880b
rollback_script_sha256    0062cf3c1bd423f655ae668c9951d563460358a1ab62f86b1f08944f78d3ae17
mechanism_combined_sha256 f3514e7324ab5f804ded316269800178158a6d380c72b38d521c2c23c739e9f7
```

Source, tests and records:

```
tests/m052k_implementation.py            836dcdb8a629100cce99c268e8830ae7
tests/test_m052k_implementation.py       c3f8554f49197b2d16326d917fba890e
docs/evidence/m052k-d3-implementation.md dad2908799c8ac1dd718e7afdb2cccf1
docs/evidence/m052j-d3-deny-mask-decision.md 47701d8dd7d6b195fa148dee62d3140c
```

Unchanged and re-verified: production fingerprint v1 `f73eaf78…`, v2 `1684a02f…`; M019+A1
`7dceb7a5…` with amendment `PASS`; M052B and M052H evidence; the observation namespace.

---

## 15. Requested authorisation

To proceed, an explicit milestone-scoped authorisation is required naming:

1. canonical `subject_runtime` as the target;
2. the principal `BABY_AI_TEST` SID **only**;
3. the mask `0x000D0156` **only**;
4. acknowledgement that ownership and inheritance stay untouched;
5. acknowledgement that a denied or failed verification leaves the deny in place deliberately rather
   than triggering an improvised recovery.

```
M052K_STATUS            = AWAITING_EXPLICIT_HUMAN_AUTHORISATION
PRODUCTION_CHANGED      = NO
NEXT_GATE               = explicit authorisation carrying all 17 dimensions, then the single
                          guarded ACL write
```

---

## Non-claims

M052K concerns filesystem authorization only. It establishes nothing about cognition, consciousness,
subjective experience, agency, learning, memory, intelligence, developmental stage, sentience, or model
inference. A deny ACE was rehearsed because eight named rights must be withheld from one SID — not
because anything was learned about a mind.