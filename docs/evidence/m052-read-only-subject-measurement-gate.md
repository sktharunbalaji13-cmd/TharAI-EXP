# M052 — Read-Only Subject Measurement: Taxonomy Corrected, Six Operations Frozen

```
M052_STATUS                    = IMPLEMENTED_VALIDATED_AWAITING_HUMAN_AUTHORISATION
M050_IDENTITY_PREREQUISITE     = SATISFIED
TAXONOMY_FAMILIES              = 6
TAXONOMY_PROPERTIES            = 36
TAXONOMY_GAPS                  = 0_ALL_RESOLVED_FROM_M019_SOURCE
READ_ONLY_OPERATIONS           = 6
READ_ONLY_OPERATIONS_VALIDATED = 6
DISPOSABLE_VALIDATION          = NOT_REQUIRED_READ_ONLY
HARNESS_SAFETY                 = PASS
LIVE_AUTHORIZATION_REQUIRED    = YES
LIVE_ATTEMPT_PERFORMED         = NO
PRODUCTION_CHANGED             = NO
PRODUCTION_ACL_CHANGED         = NO
PRODUCTION_FINGERPRINTS        = UNCHANGED_EXACT
M046_EVIDENCE                  = PRESERVED
M050_EVIDENCE                  = PRESERVED
T_WR_STATUS                    = NOT_MEASURED_BY_M052
SECURITY_OBJECTIVE_STATUS      = NOT_SATISFIED
STANDING_RED_TESTS             = preserved
NEXT_GATE                      = EXPLICIT_AUTHORISATION_FOR_ONE_READ_ONLY_LIVE_LAUNCH
```

> **No live launch occurred.** M052 stops at the authorisation gate, as the milestone requires.
> Production untouched, no mask selected, no mutation, no model.
>
> **The material result is that M051's taxonomy was wrong, and Phase 0 corrected it.**

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Phase 0 — M051's taxonomy was derived from the wrong source

M051 reported `20 families / 23 defined properties / 2 numbering gaps`. That count came from
`foundation/boundary_design.py` — which enumerates only the **rights** needed to compute the deny
mask, not the **properties**. The authoritative property table is in the **M019
intended-boundary record**.

Enumerating every `T-*` identifier in the repository:

```
distinct identifiers : 36, across 6 families
T-PATH 1-2   T-WR 1-11   T-TRAV 1-4   T-BABY 1-10   T-OWN 1-4   T-ADM 1-5
```

### The "numbering gaps" were never gaps

| Property | Occurrences | Status |
|---|---|---|
| `T-WR-5` | 22 | **DEFINED** — rename / replace, denied, OS measurement |
| `T-WR-10` | 14 | **DEFINED** — create file / create child directory, denied |
| `T-WR-11` | 9 | **DEFINED** — *and M051 never mentioned it* |

They are absent from `boundary_design.py`'s rights dict because rename and create map onto
`DELETE` and `FILE_WRITE_DATA` rather than carrying unique bits of their own. That is a property of
a *rights-derived mask*, not evidence that the requirements are undefined.

### T-WR-11 is the property that matters most right now

> **`T-WR-11` — no inherited `Authenticated Users:(I)` Modify anywhere — required state: ABSENT.**

M019 recorded it as **already violated in production**, and singled it out:

> *"T-WR-11 is the only property whose violation is currently observable without a subject run,
> because P1 still carries inherited AU Modify."*

M051's independent measurement of effective access `0x001301BF` **re-derives exactly that
violation** — the inherited `Authenticated Users` Modify is the mechanism behind the five absent
T-WR denials. So M051's finding is **corroboration of an M019 record, not a new discovery**, and
`TAXONOMY_GAPS = 0_ALL_RESOLVED_FROM_M019_SOURCE`.

### Two T-BABY assignments were also wrong

```
T-BABY-3 : M051 said "read attributes and READ_CONTROL"  ->  authoritative: LIST DIRECTORY
T-BABY-4 : M051 said "read model/config data as data"    ->  authoritative: TRAVERSE
```

All six corrections are recorded in `M051_CORRECTIONS` rather than quietly folded in, and a test
fails if they are removed. A taxonomy that drifts silently is how a laboratory ends up measuring
the wrong thing.

## 2. Phase 1 — the six read-only operations, derived not assumed

| # | Operation | T-properties | Target | Access | Expected |
|---|---|---|---|---|---|
| 1 | `read_protected_data` | T-BABY-1 | `subject_runtime\runtime` | `0x0001` | allowed |
| 2 | `read_attributes_and_ea` | T-BABY-2 | `subject_runtime\runtime` | `0x0088` | allowed |
| 3 | `list_directory` | T-BABY-3 | `subject_runtime\runtime` | `0x0001` | allowed |
| 4 | `traverse_and_descend` | T-BABY-4, T-TRAV-1/2/4 | `subject_runtime\runtime` | `0x0020` | allowed — by privilege, not by the ACE |
| 5 | `execute_runtime_payload` | T-BABY-5 | `subject_runtime\runtime` | `0x0020` | allowed — runtime must be loadable |
| 6 | `execute_data_denied` | T-BABY-5 | `subject_runtime\config` | `0x0020` | **DENIED** — data must not be executable |

Each carries the exact API, access mask, expected result, the Windows errors it may produce, what it
**establishes**, and what it **does not**. Three distinctions are baked in:

- **Traversal** does not claim the traverse ACE is present — `T-TRAV-3` established
  `SeChangeNotifyPrivilege` makes that ACE non-load-bearing, so its absence is not a denial.
  `T-TRAV-4` explicitly requires this to be verified by OS measurement, not by reading the DACL.
- **Execute** does not claim the image is runnable — M039 established `runtime/payload.bin` is
  deliberately `b"MZ" + 512 null bytes` and classifies `INVALID_IMAGE`. An open there is about
  **access**, not executability.
- **A denied execute is not evidence about `T-WR`** — it says nothing about write capability.

## 3. Phase 2 — read-only means read-only

Each operation requests the **minimum** access, never `GENERIC_WRITE`. The validator refuses any
mutating bit, `GENERIC_WRITE`, `GENERIC_ALL`, undeclared bits, or a declared state change — and
tests prove the guard *can* fail, by feeding it each of the eight mutating bits individually. A
read-only gate that cannot fail is not a read-only gate.

Two test failures during drafting were a real defect (a `frozenset` used where a bitmask was
required) rather than a wording problem. Fixed in the module.

## 4. Phase 3 — production is observed, never mutated, and never manufactured

`model/` is **absent** and is **not created** to make a test possible. Consequences recorded rather
than papered over:

- `T-BABY-5`'s model half → `NOT_MEASURABLE_ON_CURRENT_PRODUCTION_TOPOLOGY`. The same prohibition
  is exercised on `config/`, but the model half is recorded as unmeasurable, **not satisfied by
  proxy**.
- `T-OWN-3` → `NOT_ESTABLISHED` (path absent).
- `T-PATH-1` → `REQUIRES_IMPLEMENTATION` (model absent; 3 fixture artefacts present).
- `T-WR-1..11` → `OUT_OF_SCOPE_FOR_M052`. **A read-only measurement cannot establish any of them.**

A test asserts no operation targets the absent `model/` path.

## 5. Phase 11 — interpretation discipline

`T_WR_STATUS = NOT_MEASURED_BY_M052`. The M051 effective-access reading stands unchanged at
`NOT_SATISFIED`; nothing in M052 alters it.

A successful read does not prove write capability. A denied read does not prove write denial. An
execute result does not prove filesystem modification. Every conclusion stays property-specific,
and a test fails if the module ever asserts satisfaction of any objective.

## 6. Phase 8 — tests

```
tests/test_m052_readonly.py    35 passed in 1.59s
```

Covering the full Phase 8 list: six operations exactly; every operation mapped to authoritative
properties; no mutating bit, `GENERIC_WRITE` or `GENERIC_ALL`; no state change; `model/` absence
recorded and not fabricated; execute-denial carried by an existing path; mutating properties declared
out of scope rather than dropped; gaps resolved with no `UNRESOLVED_SPECIFICATION_GAP` anywhere;
M051's corrections recorded and T-BABY-3/4 authoritative; identity evidence refused from
`whoami`/`LastLogon`/session number; no privilege or mutation surface in the module.

**Not repaired:** the standing M046 baseline reconciliation issue.
`REGRESSION_VERDICT` remains `REVIEW` solely because `last_logon_unchanged` is `False` — the expected
consequence of the authorised M046 and M050 logons.

## 7. Integrity

```
production fingerprint v1/v2    UNCHANGED, exact
production subject ACEs         0 of 8
verify_boundary()              STAGING_BLOCKED
M046 evidence                  PRESERVED
M050 evidence                  PRESERVED
HEAD                           6766c5b, nothing staged
modified tracked files         the same 4, all predating M042
```

No production guard was weakened. No live attempt. No mask. No model.

## 8. The epistemic boundary

M050 answered *"which account owns the live subject process?"* → `BABY_AI_TEST`, independently
observed.

M052 asks *"what can an independently identified process read, list, traverse and execute without
changing state?"* Those are different questions and M052 does not merge them.

There is still **no model, no inference, no cognitive substrate, and no consciousness claim**.
Baby AI has still not been born. A verified subject *account* is not a mind, and a permitted read
is not thought.

## 9. Phase 9 — the authorisation gate

M052 stops here. No live launch. To proceed, a human must authorise **exactly**:

> *"I authorize exactly one M052 live read-only subject measurement launch covering the six
> specified read-only operations."*

On that authorisation, and only then, the sequence is:

1. `python -m tests.m044_preflight --gate` — require zero drift.
2. Preserve M046 and M050 evidence before the launch.
3. Launch exactly **one** new subject process.
4. **Observe its token independently** — M050's PID `8972` is *not* reusable; a new process needs a
   new observation, and without one, filesystem behaviour is **not** adjudicated as a verified
   subject measurement.
5. Execute exactly the six predeclared operations — no opportunistic extras.
6. Capture operation-level evidence; exact Windows errors preserved.
7. Stop after the six.

Confirmation for the authoriser:

- production ACLs will **not** change;
- **no** mutation operation will occur — the validator rejects all eight mutating bits;
- **no** model, no inference, no mask, no birth;
- cleanup requirement: **none** — every operation is read-only.

## 10. Next gate

```
NEXT_GATE = EXPLICIT HUMAN AUTHORISATION FOR ONE READ-ONLY LIVE LAUNCH
```

The taxonomy that was ambiguous before M052 is now canonical, and the six operations are frozen
with their access masks. What remains is a human decision to spend one launch — and nothing in
M052 should be read as having already spent it.

**A standing caution.** M052's taxonomy work found that the previous milestone's property table was
derived from the wrong artefact and that two properties were missing entirely, one of which
(`T-WR-11`) documents a production violation already known to M019. Before authorising a live launch
on this taxonomy, it is worth confirming that the six operations really are the six that matter —
not because they are wrong, but because they were chosen *after* the table was corrected, and the
correction is recent.