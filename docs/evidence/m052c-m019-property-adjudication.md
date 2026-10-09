# M052C — M019 Property Adjudication and Evidence Mapping

```
M052C_STATUS                       = COMPLETE
M052B_EVIDENCE_PRESERVED           = YES (byte-identical, 6 files verified against frozen digests)
M019_PROPERTY_COUNT                = 36
M019_PROPERTIES_MAPPED             = 36  (all, no duplicates, no extras)
SATISFIED_COUNT                    = 13   (6 by M052B, 7 pre-existing on M019's own evidence)
PARTIALLY_SATISFIED_COUNT          = 3    (2 by M052B, 1 pre-existing)
SEMANTIC_SCOPE_UNRESOLVED_COUNT    = 0
NOT_ESTABLISHED_COUNT              = 3
NOT_MEASURABLE_COUNT               = 1
NOT_TESTED_COUNT                   = 16
NOT_APPLICABLE_COUNT               = 0
PRODUCTION_CHANGED                = NO
PRODUCTION_ACL_CHANGED            = NO
M019_MODIFIED                     = NO
M052B_EVIDENCE_MODIFIED           = NO
VALIDATION                        = 38 passed
```

> Read-only gate. No subject launched, no `runas`, no authorisation requested, no production change,
> no ACL change, no `model/`, no mutating experiment. No M053 design work was done.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Method, and why the statuses exclude "PASS"

The temptation after a clean live run is to score the boundary. This ledger refuses that. M052B
produced five access observations and one honest absence; a *property claim* is a different kind of
statement, and the distance between the two is where this laboratory has repeatedly been burned:

* M052A would have reported `DENIED winerror=2` — a **missing file** — as a denial;
* M051 read the wrong source and reported 20 families instead of 6;
* the standing `T-WR = NOT_SATISFIED` finding is a **configuration** fact that must never be
  restated as though the subject had attempted a write.

So each of the 36 rows separates four things: the property's **requirement** (taken verbatim from
M019, never retyped), the **evidence type**, the **claim status**, and the **remaining gap**.

`PASS` is deliberately absent from the status set. `SATISFIED` means the property's own requirement
is met on M019's authoritative definition — never that a Windows call returned success.

The ledger also distinguishes two things that are easy to conflate in reporting:

```
ESTABLISHED_BY_M052B                    8   M052B's live evidence establishes the property
SATISFIED_PRE_EXISTING_NO_M052B_EVIDENCE 7  satisfied on M019's own evidence before this milestone
M052B_CONTRIBUTED_DISPOSITIVE           3   M052B bears on it and it still does NOT hold
```

The last group matters most. M052B strengthened three **negative** findings — T-PATH-1, T-PATH-2
and T-WR-11 — by corroborating them from the subject's side. Crediting those as M052B "wins" would
have inflated the tally by three.

---

## 2. The 36-property ledger

Evidence type key: **L** = LIVE_SUBJECT_OBSERVATION · **C** = PRODUCTION_CONFIGURATION_OBSERVATION ·
**—** = NO_M052B_EVIDENCE

### T-ADM — administrative invariance (5)

| Property | M019 requirement | M052B evidence | Type | Status | Justification | Remaining gap | Next |
|---|---|---|---|---|---|---|---|
| T-ADM-1 | operator retains full control on every path | — | — | **SATISFIED** | M019 P1; M052B's subject token is not the operator | `model\` absent, so "every path" was never fully exercised even in P1 | none from M052C |
| T-ADM-2 | SYSTEM retains full control | — | — | **SATISFIED** | M019 P1; SYSTEM not observed | `model\` absent | none |
| T-ADM-3 | Administrators retain full control | — | — | **SATISFIED** | M019 P1; Administrators not observed | `model\` absent | none |
| T-ADM-4 | admin access must not depend on a privilege the operator lacks | — | — | **NOT_TESTED_BY_M052B** | M019: REQUIRES REHEARSAL. M052B made no administrative observation | Untested | rehearsal-only milestone; no subject launch |
| T-ADM-5 | nothing lost by transformation | — | — | **NOT_TESTED_BY_M052B** | M019: REQUIRES REHEARSAL. No transformation performed | Untested | rehearsal-only milestone |

### T-BABY — subject capability (10)

| Property | M019 requirement | M052B evidence | Type | Status | Justification | Remaining gap | Next |
|---|---|---|---|---|---|---|---|
| T-BABY-1 | read data | op 1: mask `0x0001` on `runtime/m016_read_fixture.exe`, `ALLOWED`, `bytes_read=25` | L | **SATISFIED** | M019's property text is *"read data"* with evidence class *"OS measurement"*. M052B is exactly that, by an externally verified subject token | Satisfied on a **test-fixture** artefact that T-PATH-2 says must not exist | re-measure once a non-fixture runtime object exists |
| T-BABY-2 | read attributes / EA | op 2: mask `0x0088`, `ALLOWED`, `attributes=0x20` | L | **SATISFIED** | Combined mask `FILE_READ_ATTRIBUTES｜FILE_READ_EA` requested and granted | Establishes the **access grant**; no EA content extracted; nothing asserted about `FILE_WRITE_EA` | none required |
| T-BABY-3 | list directory | op 3: mask `0x0001` on `runtime/`, `ALLOWED`, `entries=5` | L | **SATISFIED** | Enumeration succeeded against a non-empty existing directory | `entries=5` is 3 files + `.` + `..` — an observation, not a property | none required |
| T-BABY-4 | traverse | op 4: `subject_runtime=OK;runtime=OK;model=ABSENT;config=OK` | L | **SATISFIED** | The property is behavioural ("can traverse") and was observed by the subject | `model\` not traversed — absent | re-run once `model\` exists |
| T-BABY-5 | execute on runtime **ONLY**; data must not be executable | op 5 `ACCESS_GRANTED`, `loadability=NOT_TESTED` ‖ op 6 `attempted=false`, `NOT_MEASURABLE_NO_DATA_FILE_IN_CONFIG` | L | **PARTIALLY_SATISFIED** | A conjunction with three separable sub-claims — see §3 | Loadability unmeasurable (no image); data-denial unmeasurable (no data file) | disposable fixture may exercise the denial path only, labelled `INSTRUMENT_DENIAL_PATH_VALIDATION_ONLY` |
| T-BABY-6 | write / append | no attempted mutation | C | **NOT_TESTED_BY_M052B** | Requires an OS measurement of the outcome; the instrument is structurally mutation-free | Untested. Objective separately known unmet by configuration | disposable mutation fixture, rehearsed before authorisation |
| T-BABY-7 | delete / rename / replace | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above | Untested | disposable mutation fixture |
| T-BABY-8 | modify DACL | no attempted mutation; no DACL read or written | — | **NOT_TESTED_BY_M052B** | `WRITE_DAC` absent by configuration, but enforcement was not observed | Untested | `WRITE_DAC` last, individually |
| T-BABY-9 | modify ownership | no attempted mutation; no owner changed | — | **NOT_TESTED_BY_M052B** | `WRITE_OWNER` absent by configuration; not observed to be enforced | Untested | `WRITE_OWNER` last, individually |
| T-BABY-10 | own any path | — | — | **SATISFIED** | M019 established via T-OWN-2; M052B read no owner SID | `model\` has no owner, but the property is negative and absence satisfies it | none |

### T-OWN — ownership (4)

| Property | M019 requirement | M052B evidence | Type | Status | Justification | Remaining gap | Next |
|---|---|---|---|---|---|---|---|
| T-OWN-1 | operator owns every path under `subject_runtime` | — | — | **PARTIALLY_SATISFIED** | M019 established 3 observable paths; `model\` absent | `model\` unverifiable while absent | re-check once `model\` exists |
| T-OWN-2 | `BABY_AI_TEST` owns no path | — | — | **SATISFIED** | M019 established by ownership read; M052B adds nothing | none outstanding | none |
| T-OWN-3 | `model\` ownership satisfies T-OWN-1 | none possible | — | **NOT_MEASURABLE_ON_CURRENT_PRODUCTION_TOPOLOGY** | No path, no owner to read. M052B recorded `model=ABSENT` rather than creating it | Unmeasurable until `model\` exists; creating it would be a forbidden production mutation | blocked on `model\`, not on measurement |
| T-OWN-4 | ownership is observed, never inferred from DACLs | method record | — | **SATISFIED** | M019 method property; M052B required no ownership inference | none outstanding | none |

### T-PATH — topology (2)

| Property | M019 requirement | M052B evidence | Type | Status | Justification | Remaining gap | Next |
|---|---|---|---|---|---|---|---|
| T-PATH-1 | exactly the four paths exist | op 4 recorded `model=ABSENT`; op 3 enumerated `runtime\` | L | **NOT_ESTABLISHED** | `model\` does not exist, so the property does not hold. M052B **corroborated the absence from the subject's side** — previously it was inspection-only | Cannot be established without creating `model\`, which is forbidden | blocked on a design decision, not measurement |
| T-PATH-2 | no test-fixture artefact inside the target path set | op 1 read `m016_read_fixture.exe`; op 3 saw three `m016_*` artefacts | L | **NOT_ESTABLISHED** | Three fixture artefacts are present, so the property does not hold. M052B strengthens this beyond inspection: **the subject itself read one of them** | The target path set is populated with fixtures | a design decision about the production target set |

### T-TRAV — traversal (4)

| Property | M019 requirement | M052B evidence | Type | Status | Justification | Remaining gap | Next |
|---|---|---|---|---|---|---|---|
| T-TRAV-1 | the subject can traverse `subject_runtime` | op 4 `subject_runtime=OK` | L | **SATISFIED** | The property asks whether the subject CAN traverse, and names its evidence *"OS measurement under subject"* — precisely what was performed | none; the ACE question is T-TRAV-3 | none |
| T-TRAV-2 | the subject can descend into `runtime`, `model`, `config` | `runtime=OK;config=OK;model=ABSENT` | L | **PARTIALLY_SATISFIED** | Two of three descended and succeeded; `model\` could not be descended because it does not exist | `model\` conjunct NOT_MEASURABLE | re-run once `model\` exists |
| T-TRAV-3 | traversal denial is **NOT** relied on as a control | **none — and M052B must not be read as evidence for it** | — | **SATISFIED** | A property of the boundary **design**, discharged by M019's method record because `SeChangeNotifyPrivilege` makes any traverse ACE non-load-bearing. M019 independently established it, which is the condition under which it may stand | none outstanding; the caveat must travel with every traversal claim | none |
| T-TRAV-4 | traversal verified by OS measurement, never by ACL letters | traversal performed by an externally verified subject token | L | **SATISFIED** | M019 recorded REQUIRES IMPLEMENTATION *"because the letter verifier cannot express it"*. M052B is the implementation it was waiting for | none | none |

### T-WR — write denial (11)

| Property | M019 requirement | M052B evidence | Type | Status | Justification | Remaining gap | Next |
|---|---|---|---|---|---|---|---|
| T-WR-1 | file/directory content write | no attempted mutation | C | **NOT_TESTED_BY_M052B** | Evidence class is *"DACL + subject-run denial"*; the subject-run half is absent. Twin: T-BABY-6 | Untested | disposable fixture |
| T-WR-2 | append | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above. Twin: T-BABY-6 | Untested | disposable fixture |
| T-WR-3 | delete (`DELETE`) | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above. Twin: T-BABY-7 | Untested | disposable fixture |
| T-WR-4 | delete child (`DELETE_CHILD`) | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above. Twin: T-BABY-7 | Untested | disposable fixture |
| T-WR-5 | rename / replace | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above. Twin: T-BABY-7 | Untested | disposable fixture |
| T-WR-6 | `WRITE_DAC` | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above. Twin: T-BABY-8 | Untested; configured to deny but enforcement unobserved | `WRITE_DAC` last, individually |
| T-WR-7 | `WRITE_OWNER` | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above. Twin: T-BABY-9 | Untested | `WRITE_OWNER` last, individually |
| T-WR-8 | `WRITE_EA` | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above | Untested; and `WRITE_EA` **is present** in effective access | disposable fixture |
| T-WR-9 | `WRITE_ATTRIBUTES` | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above | Untested; and present in effective access | disposable fixture |
| T-WR-10 | create file / create child directory | no attempted mutation | C | **NOT_TESTED_BY_M052B** | As above | Untested | disposable fixture |
| T-WR-11 | no inherited `Authenticated Users:(I) Modify` anywhere | M019 ACL inspection found the ACE present; M052B's live `0x001301BF` is consistent | C | **NOT_ESTABLISHED** | M019 defines this property's evidence as **ACL inspection, not a subject run**, and records *"the only property observable without a subject run"*. The property does not hold, and no subject launch could make it hold. M052B cannot itself establish ACE presence — it never read a DACL — but it adds **behavioural corroboration** | Decided and failing. Remediation is a design decision, not a measurement | none; not a measurement gap |

> **Every row in T-WR carries the same guard:** an authorisation is not an exercise.
> `FILE_WRITE_DATA` being present in `0x001301BF` means the subject *may* write. It does not mean
> the subject *did*, and no property here may be marked satisfied on that basis.

---

## 3. T-BABY-5 — the conjunction, separated

M019 defines T-BABY-5 as **"execute on runtime ONLY; data must not be executable"**. That is a
conjunction with an exclusion, and M052B's evidence resolves its parts differently:

| Sub-claim | Status | Basis |
|---|---|---|
| **A.** `FILE_EXECUTE` access on runtime | **SATISFIED as access** | `CreateFileW` with `0x0020` succeeded |
| **B.** the runtime is loadable | **NOT_ESTABLISHED** | no production artefact under `runtime\` begins `MZ` — there is no image to load |
| **C.** data must not be executable | **NOT_MEASURABLE_ON_CURRENT_PRODUCTION_TOPOLOGY** | `config\` contains no data file |

Because the property is a conjunction and conjunct C cannot be measured at all, the **"ONLY" half
cannot be discharged**, and the property cannot be `SATISFIED`. Hence **PARTIALLY_SATISFIED**.

Nothing was run, loaded, mapped or launched. `ACCESS_GRANTED` is not executability.

---

## 4. T-BABY-1 — the semantic determination

This required a decision, and the decision went **against** escalation. Recorded in full so it can
be reviewed.

M019's authoritative property text is:

```
T-BABY-1   state: allowed   property: "read data"   evidence: "OS measurement"
```

The words **"protected"** and **"sensitive"** do **not** appear in M019's definition. They appear
only in the M052 operation's `establishes` commentary — *"the subject can read protected file
content"* — which is instrumentation prose, not the property definition.

So the escalation condition ("if M019 requires a stronger semantic condition than 'a readable file
exists'") is **not met**. M052B performed an OS measurement of a data read, by a token externally
verified as `BABY_AI_TEST`. The property as written is met.

Marking it `OBSERVED_BUT_SEMANTIC_SCOPE_UNRESOLVED` would have required inventing a predicate M019
does not state — the mirror image of weakening a definition to make something pass. Both are
failures. The ledger takes neither.

**But the tension is real and is recorded, not resolved.** `m016_read_fixture.exe` is itself a
**test-fixture artefact**, and T-PATH-2 requires that no such artefact exist in the target path set.
So:

> T-BABY-1 is `SATISFIED` on an object whose presence **violates** T-PATH-2.

Both findings stand. The 25 bytes read were the ASCII string `m016 read fixture payload` — recorded
so no reader infers more from it than the property requires.

---

## 5. T-TRAV-3 — kept explicitly out of M052B's credit

T-TRAV-3 is *"traversal denial is NOT relied on as a control"* — a property of the boundary
**design**, whose evidence class is *"method record"*. M019 established it because
`SeChangeNotifyPrivilege` makes any traverse ACE non-load-bearing.

M052B contributes **nothing** here, and this is the important part:

> **Observed traversal is not evidence for T-TRAV-3.** Traversal *succeeded* — which is exactly
> what the privilege would produce whether or not a traverse ACE exists.

The row is therefore `NO_M052B_EVIDENCE` with `m052b_contributed = False`, and a test asserts it.
The property stands on M019's own method record, never as an M052B result.

Contrast T-TRAV-1 and T-TRAV-4, which M052B **does** discharge: both are about capability and
method respectively, and both were satisfied by a live measurement under a verified subject token.
T-TRAV-4 in particular was recorded by M019 as *"REQUIRES IMPLEMENTATION — the letter verifier cannot
express it"*, and M052B is the implementation it was waiting for.

---

## 6. Security-objective status — unchanged, and the arithmetic corrected

**Previous status:** `T-WR = NOT_SATISFIED`, five of eight required denials absent.
**After M052B:** **unchanged.** M052B corroborates; it does not alter the objective.

The objective is `T_SUBJECT_DENIED_RIGHTS` from `foundation/boundary_design.py` — 8 rights,
`derive_subject_deny_mask() = 0x000D0156`. Measured against the subject's effective access
`0x001301BF`:

| Right | Denied? | Present in effective access? | |
|---|---|---|---|
| `FILE_WRITE_DATA` | required denied | **PRESENT** | shortfall |
| `FILE_APPEND_DATA` | required denied | **PRESENT** | shortfall |
| `FILE_WRITE_EA` | required denied | **PRESENT** | shortfall |
| `FILE_WRITE_ATTRIBUTES` | required denied | **PRESENT** | shortfall |
| `DELETE` | required denied | **PRESENT** | shortfall |
| `FILE_DELETE_CHILD` | required denied | absent | OK |
| `WRITE_DAC` | required denied | absent | OK |
| `WRITE_OWNER` | required denied | absent | OK |

**Shortfall = 5 of 8.**

### 6.1 A verification error worth recording

My first verification script computed the shortfall as `effective & ~deny`. That is **wrong**, and it
is wrong in a way that would have produced a confident, pleasant, entirely false result: `~deny`
excludes the deny-set rights by construction, so that expression can never report a shortfall. It
returned "read, read_ea, execute, read_attributes" — four rights the objective deliberately does
*not* require denying.

The correct test is `deny_set & effective`. Under the correct arithmetic the shortfall is exactly
the five mutating rights above, which matches the standing M051 finding. **The recorded finding was
right and my verification was wrong.** Had the ledger been written from the first script's output,
M052C would have reported the security objective as satisfied on read/execute grounds — a false
all-clear on the most important axis in the entire ledger.

A test now asserts `bin(effective & deny).count("1") == 5` so the arithmetic cannot silently invert
again.

### 6.2 What this finding is and is not

It is a **configuration/environment** finding, corroborated by subject-side behaviour.

It is **not** a live write test, and **not** evidence of malicious behaviour, intent, agency, or
knowledge. The subject performed no mutation. M052B did not attempt one and was structurally
incapable of attempting one.

---

## 7. What M052B established

For one attempt, an externally identified `BABY_AI_TEST` process (PID 25292, SID `…-1022`, medium
integrity, not elevated, no privileges) **could**: read data, read attributes and EA, list a
directory, traverse, and obtain `FILE_EXECUTE` access on a runtime artefact — all against the
existing production `subject_runtime`. And the instrument could **tell those apart from a refusal
without guessing**, which is what M052A could not do.

Eight properties reached `SATISFIED` or `PARTIALLY_SATISFIED` on that evidence.

## 8. What M052B did not establish

* any loadable or executed payload — no production artefact is an image;
* any data-execute denial — no data file exists;
* `T-TRAV-3` as an M052B result — traversal behaviour is uninformative about the ACE;
* `FILE_WRITE_EA`, and any of the 16 mutating or rehearsal-dependent properties;
* any ownership fact — no owner SID was ever read;
* that `subject_runtime` is "protected" in any content sense — the one file read was a fixture.

**16 of 36 properties were not tested by M052B at all.** That is the honest headline.

## 9. Remaining research gaps

1. **T-PATH-1 / T-PATH-2 / T-OWN-3 / T-BABY-4 / T-BABY-5** are all blocked on the *same* design
   decision: whether `model\` should exist, and whether the target path set should contain fixtures.
   Five properties are waiting on one question that is not a measurement question.
2. **T-BABY-5 conjunct C** is blocked on a data file existing in `config\`. Creating one in
   production is forbidden; a disposable fixture can only ever validate the instrument's
   classification machinery, never the production property.
3. **16 properties** need either a disposable mutation fixture (M053) or rehearsal-only work
   (T-ADM-4/5). None of them may be settled by further read-only measurement.
4. **T-WR-11 and the 5-of-8 shortfall** are remediation decisions. No measurement will close them,
   and no measurement should be attempted to try.

No M053 design work was performed, no mutation order was chosen, and no mutating test was
authorised.

---

**No M052C conclusion establishes cognition, consciousness, subjective experience, agency, learning,
memory, sentience, or model inference.**