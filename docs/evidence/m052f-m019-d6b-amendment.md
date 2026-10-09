# M052F — Formal M019 Amendment A1 for D6-B

```
M052F_STATUS                  = M019_D6B_AMENDMENT_COMPLETE
D6_DECISION                   = RESCOPE_T_BABY_1_NAMESPACE (explicitly selected; recorded in M052E)
M019_VERSION_BEFORE           = M019-unversioned
M019_HASH_BEFORE              = 33dde443a6d35542f157f8027a18b6d0e68d27432d90eef082e6f3013a9139c0
M019_BYTES_BEFORE             = 32602
M019_VERSION_AFTER            = M019+A1
SECTIONS_CHANGED              = 3  (amendment history block [new]; §8 T-BABY-1 row [pointer only]; §19 [new])
SECTIONS_UNCHANGED            = 18 (§1–§18 preserved verbatim)
T_BABY_1_CHANGE               = PERMITTED OBSERVATION SOURCE ONLY — requirement, state and evidence class unchanged
T_PATH_2_CHANGE               = NONE
CANONICAL_T_CHANGE            = NONE
SECURITY_OBJECTIVE_CHANGE     = NONE
M052B_HISTORICAL_EVIDENCE     = UNCHANGED AND IMMUTABLE
PROVENANCE_RULE               = 5 mandatory fields per observation object (§19.3)
MEASUREMENT_NAMESPACE_RULE    = T_OBSERVATION_NAMESPACE — defined, OUTSIDE canonical T, NOT created
SUBJECT_WRITE_RULE            = namespace confers NO write/append/delete/WRITE_DAC/WRITE_OWNER/WRITE_EA/WRITE_ATTRIBUTES
FIXTURE_RULE                  = m016_* remain T-PATH-2 VIOLATIONS; not promoted
DEPENDENCY_GRAPH_EFFECT       = T-BABY-1 SATISFIED -> NOT_ESTABLISHED / IMPLEMENTATION-BLOCKED / REQUIRES_FRESH_MEASUREMENT
PRODUCTION_CHANGED            = NO
PRODUCTION_ACL_CHANGED        = NO
SUBJECT_LAUNCH                = NOT_ATTEMPTED
AUTHORIZATION_REQUESTED       = NO
MEASUREMENT_NAMESPACE_IMPLEMENTED = NO
```

> **T remains unchanged. T-PATH-2 remains unchanged. D6-B changes the allowed observation namespace
> for T-BABY-1 only. No production namespace is created by this milestone.**
>
> No production mutation occurred. No ACL changed. No subject was launched. No M052B evidence was
> rewritten. No downstream security implementation occurred.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Why an amendment was required

T-BABY-1 and T-PATH-2 were **jointly unsatisfiable** on the current topology:

* **T-BABY-1** requires an object the subject can read;
* **T-PATH-2** forbids every test artefact from inside the canonical target set;
* the only files under `runtime\` are `m016_*` fixtures.

M052D classified this as a **property-contract contradiction, not an instrumentation problem**. M052E
recorded the director's explicit selection of **D6-B**. A1 is the governed documentation amendment
D6-B requires.

D6-A (author content into canonical production) and D6-C (amend §11 to admit fixtures) were both
rejected. D6-C remains the more dangerous of the two rejected options: it is the only one that can
convert a *prohibition* into a *permission*, which would let T-PATH-2 be satisfied by definition
rather than by measurement.

---

## 2. Exactly what changed in M019

Three edits, all **additive**. Sections 1–18 are byte-preserved.

| # | Location | Change | Additive? |
|---|---|---|---|
| 1 | top of document | **Amendment history** block: A1, decision `D6-B`, date, sections changed, pre-amendment hash, links to the M052E and M052F records | new block, nothing removed |
| 2 | §8, T-BABY-1 row | status cell gains `— observation source governed by **A1** (§19); intent columns unchanged` | **pointer only.** Property text `read data`, state `allowed`, and all three intent columns (`yes/yes/yes`) untouched |
| 3 | end of document | **§19 Amendment A1** — full text | new section |

### 2.1 What was deliberately *not* changed

| | |
|---|---|
| §11 canonical topology language | **verbatim** — `subject_runtime`, `runtime`, `model`, `config` — and **only** those |
| T-PATH-1, T-PATH-2 text | **verbatim** |
| T-BABY-1 `property` / `state` / `evidence` | **verbatim** — `read data` / `allowed` / `OS measurement` |
| T-OWN-*, T-TRAV-*, T-WR-* | **verbatim** |
| §10 security-objective derivation | **verbatim** — `T_SUBJECT_DENIED_RIGHTS`, 8 rights |
| T-BABY-2…10, T-ADM-*, T-PATH-1 | **verbatim** |

**No original requirement was deleted, weakened, or redefined.** A1 relocates an *observation
source*; it does not touch a *requirement*.

---

## 3. The governed measurement namespace — defined, NOT created

### 3.1 Location

`T_OBSERVATION_NAMESPACE` is a **governed identifier, not a filesystem path**. A1 deliberately does
not fix a concrete location. Naming a production path here would convert a governance decision into
an implementation and would place a new artefact class adjacent to the frozen boundary before its
governance is settled. A concrete location requires its own freeze-and-rehearse milestone.

Outside canonical T: not inside `subject_runtime`, `runtime`, `model` or `config`.

### 3.2 Ownership

Owned by the **laboratory/operator**. **Never by `BABY_AI_TEST`** — the subject does not own a
namespace it may read. Ownership follows M019 §7's same-SID and principal-wide prohibitions.

### 3.3 Provenance — five mandatory fields per observation object

1. experiment identifier
2. creation provenance
3. content hash
4. author/source classification
5. immutable association with the measurement it serves

### 3.4 Mutability

The subject gains **no** `FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `FILE_DELETE_CHILD`, `DELETE`,
`WRITE_DAC`, `WRITE_OWNER`, `FILE_WRITE_EA` or `FILE_WRITE_ATTRIBUTES` right by the namespace
existing. It is a **measurement input, not a subject workspace.**

### 3.5 Separation

Observation objects must not be conflated with subject memory, subject experience, canonical subject
state, model weights, runtime code, or provenance evidence.

### 3.6 Fixtures

Disposable test fixtures remain disposable test fixtures. They are **not** promoted to canonical or
governed-legitimate status by the existence of a namespace.

### 3.7 The six categories A1 keeps distinct

The contradiction arose from two of these being blurred. None may be silently reclassified:

| # | category | may source T-BABY-1? |
|---|---|---|
| 1 | canonical subject state | yes — inside T, kept artefact-free by T-PATH-2 |
| 2 | environment/content supplied for legitimate observation | **yes, only** via `T_OBSERVATION_NAMESPACE` under §3.3 provenance |
| 3 | research instrumentation | no — an instrument *performs* the observation |
| 4 | disposable test fixtures | **no** — prohibited inside T by T-PATH-2 |
| 5 | subject-generated content | no — evidence *of* the subject, never an input to it |
| 6 | provenance/evidence artifacts | no — evidence *of* a measurement, never its subject |

---

## 4. T-BABY-1 — historical M052B treatment

### 4.1 What M052B measured

```
target        : runtime/m016_read_fixture.exe
target location: INSIDE canonical subject_runtime
target status  : a T-PATH-2 VIOLATION (an m016_* test fixture)
mask          : 0x0001
result        : ALLOWED, bytes_read = 25, winerror 0
attempt       : e978330eb5e746c0, subject PID 25292, externally verified
```

### 4.2 What follows — and only that

* The **access observation is valid historical experimental evidence.** An externally identified
  `BABY_AI_TEST` token obtained `FILE_READ_DATA` on an existing object, by OS-level measurement,
  exactly as M019's evidence class requires.
* It was **not obtained under `T_OBSERVATION_NAMESPACE`**, which did not exist.
* M052B is **not retroactively transformed into a compliant D6-B experiment**.
* It therefore **does not discharge** T-BABY-1 under A1.

```
T-BABY-1 (post-A1) = REQUIRES_FRESH_MEASUREMENT
```

### 4.3 This is a provenance finding, not a retraction

Nothing about what the subject did in attempt `e978330eb5e746c0` is in dispute. The read succeeded;
25 bytes were returned; the token was externally verified. **Only whether that attempt used a
compliant observation source is at issue, and it did not.**

M052B's evidence, adjudication, and preservation copies are **byte-identical and untouched**. Its
property-level *interpretation* changed — and only because a formal amendment now governs the
observation source. That is the correct order: decision → amendment → re-interpretation, never
re-interpretation → justification.

---

## 5. Dependency graph effect

```
D6-B decision (M052E)
  -> A1 amendment (M052F)                      [ THIS MILESTONE ]
     -> T_OBSERVATION_NAMESPACE implementation  [ NOT DONE ]
        -> fresh T-BABY-1 measurement          [ NOT DONE ]
           -> T-BABY-1 adjudication            [ NOT DONE ]
```

**A definition change makes a property MEASURABLE. It does not perform the measurement.**

### 5.1 Blocking states kept distinct (M052F step 7)

Collapsing these into one generic "blocked" is exactly how a definitional gap becomes a fake result.

| state | count | meaning | example |
|---|---|---|---|
| **IMPLEMENTATION-BLOCKED** | 1 | decision made; the thing does not exist yet | **T-BABY-1** — `T_OBSERVATION_NAMESPACE` is defined, not built |
| **DECISION-BLOCKED** | 22 | waiting on a director decision | T-WR-1…11, T-BABY-6…9 (D3/D4); T-PATH-1/2, T-OWN-1/3, T-TRAV-2, T-BABY-4/5 (D1/D2) |
| **REHEARSAL-BLOCKED** | 2 | needs rehearsal work, not a decision | T-ADM-4, T-ADM-5 |
| **MEASUREMENT-BLOCKED** | 0 | everything exists; the observation simply has not been made | — |
| **NOT_BLOCKED** | 11 | closed, or needing no architectural change | T-ADM-1…3, T-BABY-2/3/10, T-OWN-2/4, T-TRAV-1/3/4 |

T-BABY-1 is `IMPLEMENTATION-BLOCKED`, **not** `MEASUREMENT-BLOCKED`, because the namespace does not
exist yet. Calling it measurement-blocked would imply everything needed is in place and the work is
merely outstanding — which would invite someone to run a measurement against a namespace that is
not there.

### 5.2 Ledger transition

| | pre-A1 (M052C) | post-A1 (M052F) |
|---|---|---|
| `SATISFIED` | 13 | **12** |
| `NOT_ESTABLISHED` | 3 | **4** |
| `ESTABLISHED_BY_M052B` | 8 | **7** |
| `M052B_CONTRIBUTED_DISPOSITIVE` | 3 | **4** |
| T-BABY-1 status | `SATISFIED` | **`NOT_ESTABLISHED`** |
| T-BABY-1 blocking | — | **`IMPLEMENTATION-BLOCKED`** |

T-BABY-1 joins T-PATH-1, T-PATH-2 and T-WR-11 as a property M052B touched and that still does not
hold — which is the honest outcome. M052B's contribution count is unchanged at 11; what changed is
that one of them no longer yields credit.

The **M052C evidence record is historical and was not rewritten.** Only the ledger row reflects A1.

---

## 6. Security objective — explicitly unchanged

A1 alters **none** of: required deny rights; effective-access interpretation; subject boundary;
operator boundary; `WRITE_DAC` requirements; `WRITE_OWNER` requirements; ownership requirements.

```
deny set        : 8 rights, derive_subject_deny_mask() = 0x000D0156
subject effective: 0x001301BF
shortfall       : 5 of 8 required denials absent
objective status: NOT SATISFIED  (unchanged)
```

Present: `FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `FILE_WRITE_EA`, `FILE_WRITE_ATTRIBUTES`, `DELETE`.
Absent: `FILE_DELETE_CHILD`, `WRITE_DAC`, `WRITE_OWNER`.

That is a **D3** matter. D3 remains an independent, unresolved decision and is **not** advanced,
derived, rehearsed, or implemented here.

---

## 7. What this milestone explicitly did not do

* Did **not** legitimise the three `m016_*` artefacts — they remain **T-PATH-2 violations** until D1.
* Did **not** create, populate, or grant access to any namespace.
* Did **not** grant the subject any new right.
* Did **not** select or implement a deny mask; did **not** touch `0x000D0156` vs `0x00110156`.
* Did **not** use `icacls`, alter inheritance, or change ownership or permissions.
* Did **not** launch a subject, invoke `runas`, or take a live measurement.
* Did **not** modify M052B evidence, M052C's record, or M052D/M052E.
* Did **not** introduce a *"protected data"* predicate — T-BABY-1 remains *"read data"*.
* Did **not** advance D1, D2, D3, D4 or D5.

---

## 8. Read-only validation — 20 checks

| # | check | result |
|---|---|---|
| 1 | all 36 M019 properties present, none deleted | PASS |
| 2 | no duplicate property | PASS |
| 3 | ledger row count = 36 | PASS |
| 4 | T-PATH-2 present | PASS |
| 5 | T-BABY-1 present | PASS |
| 6 | canonical T text unchanged | PASS |
| 7 | D3 unresolved, mask still `0x000D0156` | PASS |
| 8 | security objective unchanged (8 rights, shortfall 5) | PASS |
| 9 | M052B evidence byte-identical | PASS |
| 10 | M052C record intact | PASS |
| 11 | M052D / M052E records intact | PASS |
| 12 | production fingerprints exact | PASS |
| 13 | production ACL unchanged (0 of 8 explicit ACEs) | PASS |
| 14 | **no measurement namespace created** | PASS |
| 15 | no subject launched | PASS |
| 16 | T-BABY-1 requirement/state/evidence unchanged | PASS |
| 17 | T-PATH-2 text unchanged | PASS |
| 18 | amendment recorded in the document (`§19`, `A1_STATUS`) | PASS |
| 19 | namespace defined, not created | PASS |
| 20 | **`m016_*` still classified as T-PATH-2 violations** | PASS |

---

## 9. Status

```
M052F_STATUS                     = M019_D6B_AMENDMENT_COMPLETE
T_BABY_1_STATUS_AFTER_AMENDMENT  = REQUIRES_FRESH_MEASUREMENT (NOT_ESTABLISHED, IMPLEMENTATION-BLOCKED)
T_PATH_2_STATUS_AFTER_AMENDMENT  = UNCHANGED — still a prohibition; m016_* still violations
CANONICAL_T_STATUS               = UNCHANGED
SECURITY_OBJECTIVE_STATUS        = UNCHANGED — NOT SATISFIED, 5 of 8 absent
T_BABY_1_FRESH_MEASUREMENT_REQUIRED = YES
MEASUREMENT_NAMESPACE_IMPLEMENTED    = NO
PRODUCTION_CHANGED                   = NO
PRODUCTION_ACL_CHANGED               = NO
SUBJECT_LAUNCH                       = NOT_ATTEMPTED
AUTHORIZATION_REQUESTED              = NO
```

**Next milestone** is `T_OBSERVATION_NAMESPACE` implementation, under the same freeze-and-rehearse
discipline as M052B — and it must not grant the subject any right beyond read access to a governed
object.

This amendment establishes only the formal governance relationship between T-BABY-1 and its future
measurement namespace. It does not establish a new live measurement, does not validate the subject's
access to a future namespace, does not remove the existing `m016_*` T-PATH-2 violations, and does not
select or implement a deny mask. It establishes nothing about cognition, consciousness, subjective
experience, agency, learning, memory, sentience, or model inference.