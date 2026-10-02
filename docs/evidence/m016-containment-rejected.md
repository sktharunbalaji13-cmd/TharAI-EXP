# M016 — Containment design REJECTED

**STATUS = REJECTED** (not blocked, not pending)
**PRODUCTION_ACL_MUTATED_BY_THIS_TASK = NO**
**PRODUCTION_TOUCHED = NO**

The M016 containment design is permanently rejected. Do not apply it to
production, and do not run further `/inheritance:d` experiments against it.

## 1. Why it is rejected

The proposed sequence was:

```
operator grant  →  /inheritance:d  →  /remove:g "NT AUTHORITY\Authenticated Users"
```

rollback being `/inheritance:e` → remove explicit SYSTEM → Administrators →
operator.

The defect is in the **second step**, and it is a property of `/inheritance:d` on
this host, not of the surrounding design.

### The decisive experiment

A disposable tree was built to reproduce the production operator ACL exactly,
using the inheritance mechanism production actually uses:

| stage | state |
|---|---|
| repo parent | `operator 0x00120089` explicit, `OI,CI`, inheritable |
| `subject_runtime` | `operator 0x00120089` **inherited**, **no** explicit operator ACE |
| then | temporary explicit `operator 0x001f01ff` `OI,CI` added to the child |

Immediately before the freeze the child held **two distinguishable operator Allow
ACEs on the same SID**:

```
operator ACEs: 0x00120089/inh , 0x001f01ff/exp
```

After `/inheritance:d`:

```
D:PAI(A;OICI;0x1301bf;;;AU)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-...-1001)
```

**Only one operator ACE survives, at `0x001f01ff`. The `0x00120089` ACE is gone.**

### The consequence

`/inheritance:d` does **not** preserve distinct inherited and newly introduced
Allow ACEs for the same principal. It collapsed the two into one.

`0x00120089` is a read-only mask (`0x120089` = read data + read EA + read
attributes + read control + synchronize). Losing it removes the operator's
**read** access, not merely a duplicate.

Therefore the sequence destroys pre-existing operator access **at the freeze
step**, before the AU removal it was designed to perform. Rollback cannot repair
it: `/inheritance:e` restores the *parent's* inherited ACEs, but the explicit
`0x00120089` copy no longer exists to be reconciled with anything.

### Why this was invisible for so long

Every earlier rehearsal exercised `/inheritance:d` with **one ACE per principal**.
For a single ACE, "copies inherited to explicit" and "collapses same-SID ACEs" are
indistinguishable. The collapse only appears with two ACEs on one SID — which is
exactly the production operator case, and exactly what the earlier single-level
and multi-level rehearsals did not construct.

`/inheritance:d` therefore remains **valid for principals with a single ACE**, and
was correctly gated as PASS in those rehearsals. The rejection is specifically
about the same-SID case.

## 2. Stage E was never validly tested

Exact-ACE removal (`RemoveExact`, targeting only `0x001f01ff`) was **not**
exercised against the two-ACE state, because that state does not survive Stage C.

It was run against a single-ACE tree, returned `1`, and removed the only operator
ACE present — leaving none. That result is **inconclusive, not a capability gap**.

**Do not record "managed ACL cannot remove an exact ACE" as established.** The
required fixture is constructible (`AddExact` builds it correctly and Stage A/B
pass); it is `/inheritance:d` that destroys it. Any future exact-ACE question must
test `RemoveExact` against a **directly constructed** two-ACE DACL with no freeze
step. That experiment was deliberately **not** run: it cannot rescue the rejected
design, so it was dropped rather than treated as progress.

## 3. Mechanisms catalogued (read-only audit, no selection)

Production state at audit time: `subject_runtime` fully inherited,
**zero explicit ACEs**, `model\` absent.

| # | mechanism | changes `subject_runtime`? | closes AU write? | main consequence |
|---|---|---|---|---|
| 1 | `/inheritance:e` | yes | **no** | reverts exposure; only undoes a boundary |
| 2 | explicit AU deny on child | yes | yes | AU **Allow survives**; deny added above it |
| 3 | remove AU at repository source | **no** | yes | repository-wide policy change |
| 4 | AU deny at parent, child inherits | no | yes | changes broader inherited policy |
| 5 | SID-only deny (subject) | yes | **no** | leaves AU open for all other AU members |

### Notes that constrain the choice

- **Mechanism 3 is not "cheapest to reverse."** `subject_runtime` is untouched, so
  the ACL-level change is trivially reversible — but it alters security policy at
  `C:\dev\TharAI-EXP` for **every** descendant inheriting that ACE. That is a
  repository-wide policy change wearing a small diff.
- **Mechanism 2 does not restore the intended descriptor.** It leaves both the
  `Authenticated Users` Allow (`0x001301bf`) **and** a new
  `Deny 0x00000156` in the same DACL. Effective rights are closed; the descriptor
  is not the original. Any future audit asking "does an AU Modify ACE exist here?"
  still answers yes.
- **None of 2, 3 or 4 is equivalent to the original M015 state.** All three alter
  the descriptor or the inherited policy rather than restoring it.
- Mechanism 5 is relevant to the M016 subject deny only; it does nothing about AU
  exposure generally.

### Property any containment deny must have

Observed during cleanup: the mechanism-2 deny mask (`0x342`, `DELETE` +
`DELETE_CHILD`) **blocked deletion of its own directory**, including by the
operator. Removing the deny still succeeded because `WRITE_DAC` was deliberately
outside the deny mask.

**A containment deny that includes `WRITE_DAC` or `DELETE` is unrecoverable by
construction.** `WRITE_DAC` must stay outside any deny mask, or the deny cannot be
undone by anyone.

## 4. Gate defects found, now covered by regression tests

Two comparison gates were defective. In both cases the defect made a gate weaker
than it appeared, and in both cases the weakness was invisible because a correct
result and a broken result produced the same output.

| defect | symptom |
|---|---|
| `$protA` / `$protE` declared, never assigned | protected-state comparison was vacuous; contributed nothing to the verdict |
| `Compare-Object (Canon $p) (Canon $p)` | compared live state to itself; reported "0 differing" while the tree fingerprint disagreed |

`tests/test_acl_gate_regression.py` — **14 passed**. Each test corrupts exactly one
field and requires the gate to fail:

- protected flag flipped, **ACE diff asserted empty** (proves it is an independent
  condition, not folded into the multiset);
- inherited → explicit origin flip, caught via the ACE term with
  `protected_mismatch=False` — this is the `/inheritance:d` damage;
- mask, principal, type, inheritance flags, propagation flags, loss, addition;
- **duplication** — invisible to set semantics, so ACE count is its own term;
- ACE **order is not** a difference (Windows re-canonicalises order; the first
  SDDL string comparison produced a false alarm here);
- self-comparison is proven unable to detect a real change.

## 5. Established state

| fact | status |
|---|---|
| original `/inheritance:d` containment design | **rejected, permanently** |
| harness structurally protected against the incident mechanism | done, 33 negative tests |
| protected-state gate regression coverage | done, 14 tests |
| multi-level descendant behaviour | investigated; not the blocker |
| production ACL since the incident | **unchanged** |
| `subject_runtime` | fully inherited, zero explicit ACEs |
| `model\` | absent |
| authoritative desired state | `prod_fingerprint_before.json`, `02c5e4c4…` |
| **faithful production restoration** | **unresolved** |
| `foundation/subject_deny.py` | experimental, **unintegrated**, not a deployment mechanism |

## 6. Open items

1. **Decision milestone, not implementation.** Define what containment must
   accomplish while the damaged ACL exists, then choose explicitly between
   **minimum blast radius** (mechanism 2) and **minimum deviation from the
   intended ACL model** (mechanism 3). These are different objectives with
   different scopes; the trade is a governance decision, not a technical one.
2. **Restoration is a separate track.** It stays separate by design: containment
   and recovery have different acceptance criteria, and a containment mechanism
   must not be presented as a recovery mechanism. Restoration remains blocked —
   no DACL-only write mechanism on this host avoids `SeSecurityPrivilege`, and
   `apply_boundary()` would reconstruct rather than restore.
3. ~~**Residual harness gap.**~~ **CLOSED.** `tests/guarded.py` classified the
   probe's `staged` and `workspace` positional slots as read-only; both are mutated
   by the launched process. A contract audit found a **third**: `protected` sets
   attributes on an arbitrary child. All three are now WRITE-scoped, the
   classification lives in one table checked against the probe source, and the
   reasons are regression-tested. See
   `docs/evidence/m015-harness-incident.md` §9. The audit finding was never the
   incident mechanism — no test passed production paths through those arguments —
   but the guard was not the complete boundary it appeared to be.
4. `subject_deny.py` exact-mask apply/verify/rollback logic remains reusable for a
   future boundary. The **deployment** plan is rejected; the logic is not.

## 7. Test results

| suite | result |
|---|---|
| `test_acl_gate_regression.py` | **14 passed** |
| `test_harness_write_isolation.py` | **33 passed** |
| `test_m005_acl_recovery.py` | **7 passed** |
| `test_host_readiness.py` | **48 passed** |
| full portable | 2017 passed, 16 failed, 2 warnings, 749 subtests |

The 16 failures outside the 11-item baseline are read-only checks correctly
reporting the damaged production. They are the alarm working and must not be
"fixed" by repairing production from a test.