# M052M — HALTED: PRODUCTION MUTATED BY A VERIFICATION PROBE

```
M052M_STATUS            = HALTED_PRODUCTION_MUTATED
PRODUCTION_CHANGED      = YES
PRODUCTION_ACL_CHANGED  = YES — exactly one ACE, on one file
GATE_1_STATUS           = CLOSED
GATE_2_STATUS           = CLOSED
D3_DENY                 = NOT_APPLIED (the D3 deny is NOT what was written)
SUBJECT_LAUNCH          = NOT_ATTEMPTED
D4                      = NOT_IMPLEMENTED
T_BABY_1                = SATISFIED (M052H, untouched)
SECURITY_OBJECTIVE      = NOT_SATISFIED — shortfall 5 of 8, unchanged
GOVERNANCE_DECISION     = NONE — A/B/C still unanswered
```

> **I mutated canonical production.** Not the D3 deny, and not through the M052K mechanism — but a
> real ACL change on a production file, written by my own verification probe while trying to prove
> the probe was safe. This record exists so the exact state and the exact cause are on the record
> before anything else happens.

---

## 1. What was written

One file. One ACE. Explicit. Nothing else on production changed.

```
path      C:\dev\TharAI-EXP\subject_runtime\runtime\m016_read_fixture.exe
owner     S-1-5-21-…-1001   (unchanged)
protected False             (unchanged)

before sddl  D:AI(A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1301bf;;;AU)(A;ID;0x1200a9;;;BU)

after  sddl  D:AI(D;;CC;;;S-1-5-21-2406520953-1060965512-844951592-1022)
               (A;ID;FA;;;BA)(A;ID;FA;;;SY)(A;ID;0x1301bf;;;AU)(A;ID;0x1200a9;;;BU)

added ACE    DENY  S-1-5-21-…-1022   mask=0x00000001   EXPLICIT   no inheritance flags
```

`0x00000001` is `FILE_READ_DATA` — a single bit, and **not one of the eight objective rights**. The
D3 mask is `0x000D0156`; this is `0x00000001`. It denies the subject the ability to *read* one
evidence file. It is not a partial D3 boundary; it is the wrong bit entirely, written by a probe
intended to write `0x1` to a disposable tree.

### Fingerprint state

```
v1  f73eaf78… -> UNCHANGED   (v1 carries no owner field and did not include this file's SDDL delta)
v2  1684a02f… -> 7d592c7a…   CHANGED
```

`sr.check_production_fingerprints()` now reports **`v1: False` and `v2: False`** against the recorded
values. That is the correct signal and it must not be suppressed: production is no longer the state
M052J/M052K froze against.

---

## 2. Cause — and it is not the bug I was hunting

I was verifying that the private descriptor writers in `foundation/subject_deny.py` could not reach
production. I ran:

```python
sd._apply_mask_to_path(T/'runtime'/'m016_read_fixture.exe', 0x1, deny=True)
```

with `T` = the **production** root, to confirm the backstop refused it.

The backstop `_assert_writer_is_reachable_from_a_guarded_caller()` is defined — but I had wired it
into **`apply_subject_deny` only**, never into the three private writers it was written to protect. So
the guard existed, was named correctly, was described in its own docstring as guarding them, and did
not run.

The first run of this same probe **returned `OK` and I read that as success** rather than as damage. I
then checked a *different* artifact (`same_sid_topology`, `m052k` fingerprints) and concluded nothing
had been written. That conclusion was wrong: it rested on fingerprints that do not include this file's
SDDL change in v1, and I did not look at the file I had just written to.

Three separate failures, in order:

1. **The guard was not called.** Declared, documented, wired to one caller out of four.
2. **I ran a mutating call against production to test a guard.** The probe should have targeted a
   disposable tree, as every rehearsal in this project does. Testing a refusal by performing the
   forbidden action is not a test; it is the action.
3. **I misread `OK` as safe.** A mutation helper returning `OK` means it wrote. Nothing about that
   string meant "refused".

The M052M lesson is the one this project has kept relearning: *a guard that is not exercised on the
path that matters is a comment*. The counter-lesson here is worse — **a guard that is written, named,
documented and not called is worse than no guard, because it is trusted.**

---

## 3. What I have NOT done

Per the standing failure behaviour (`STOP_LEAVE_DENY_IN_PLACE`) and §20 of the M052M prompt:

- **I have not rolled it back.** The prompt forbids improvised recovery, and no frozen rollback
  procedure exists for this artifact. Inventing one would be a second unlogged production mutation.
- **I have not touched `control.token` or `HEAD.json`** — measured read-only only.
- **I have not applied the D3 deny.** `0x00000001` is not `0x000D0156`, and this ACE does not close
  any T-WR property.
- **I have not created a `GovernanceDecision`.** A/B/C remains unanswered.
- **I have not marked any property.** The objective is still `NOT_SATISFIED`, shortfall 5 of 8.
- **I have not committed anything.**

---

## 4. Findings that stand, independent of the damage

The inventory work was sound and its results are unaffected:

- `foundation/staging.py` and `foundation/subject_deny.py` both defaulted to **canonical production**
  via `staging_root()` and carried **zero** guards. `apply_boundary()` would have run
  `icacls /inheritance:r /T /C` recursively over production. Now refused by
  `_refuse_canonical_production`. **That fix is real and remains in place.**
- 70 mutation-syntax paths classified; **0 residual unsafe**; **0 UNKNOWN**. 55 are read-only, 6
  test-only, 9 are private helpers proven unreachable from a production default — *except* the three
  in `subject_deny`, which this incident proves were reachable. The inventory's `residual_unsafe`
  check was **wrong**: it treated a `return`ed value as a refusal. Fixed logic is required, and until
  it is, that check must not be trusted.
- `control.json`: effective `0x001301BF`, DELETE held, **no explicit subject deny**, names
  `token_file`. Load-bearing under **B only**; not under A or C.
- Option consequences worked through across 14 dimensions. **A remains recommended. Not decided.**

---

## 5. Required before any further work

1. **Decide the disposition of this ACE.** Remove it, or record it as evidence. Removing it is a
   production mutation and needs its own explicit authorisation — including a *rollback procedure
   that exists before it is needed*, which is precisely what M052K established for the D3 deny and
   what does not exist here.
2. **Wire the backstop into all three writers**, not one. Then prove it by attempting a *disposable*
   call, never a production one.
3. **Fix the inventory's refusal detection.** A returned value is not a refusal.
4. **Re-freeze the production fingerprints**, because the recorded ones no longer describe reality.
5. **Then, and only then, answer A / B / C.**

Until (1) is decided, no production milestone should run. The state is documented, not repaired.

---

## Non-claims

M052M concerns execution-path governance and filesystem authorization only. It establishes nothing
about cognition, consciousness, subjective experience, agency, learning, memory, intelligence,
developmental stage, sentience, or model inference. An ACE was written to a file by a mistaken probe.
That is a governance and process failure, and it says nothing about any mind.
