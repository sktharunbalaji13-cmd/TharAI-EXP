# M052E — Director Decision D6: T-BABY-1 / T-PATH-2 Topology Contradiction

```
M052E_STATUS                  = AWAITING_DIRECTOR_DECISION
DIRECTOR_DECISION             = NONE_SUPPLIED
D6_DECISION                   = NOT_SELECTED
RATIONALE                      = PENDING
M019_SECTIONS_AFFECTED        = PENDING (§11 target path set identified as the locus)
T_BABY_1_EFFECT                = PENDING
T_PATH_2_EFFECT                = PENDING
CANONICAL_T_EFFECT             = PENDING
M052B_HISTORICAL_EVIDENCE_EFFECT = UNCHANGED — no reclassification performed
DOWNSTREAM_DEPENDENCY_EFFECT   = NOT_PROPAGATED — no decision to propagate
D3_EFFECT                      = NONE — D3 untouched
PRODUCTION_CHANGED             = NO
PRODUCTION_ACL_CHANGED         = NO
SUBJECT_LAUNCH                 = NOT_ATTEMPTED
AUTHORIZATION_REQUESTED        = NO
```

> **No decision was made in this milestone.** A recommendation of D6-B exists on the record from
> M052D and was restated by the director, but a recommendation is not a decision. M052D's own brief
> and this milestone's brief both forbid inferring the choice from it.
>
> **No production mutation occurred. No ACL changed. No subject was launched. No M052B evidence was
> rewritten. No downstream security implementation occurred.**

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Why this milestone stops here

The brief is unambiguous:

> *"If no explicit decision is present in the current input, STOP and report:
> `M052E_STATUS = AWAITING_DIRECTOR_DECISION`"*
> *"Do not infer the choice from recommendation, prior discussion, or implementation convenience."*

The input supplied a **recommendation** ("My recommendation remains D6-B") and then explicitly stated
that the gate exists "to wait for your explicit director choice rather than silently adopting it."

| Check | Result |
|---|---|
| Explicit `D6-A` / `D6-B` / `D6-C` selection supplied | **NO** |
| A recommendation was stated | YES (D6-B) |
| Is a recommendation a decision | **No** |
| Decision inferred anyway? | **No** |

Selecting D6-B here would have been the exact failure this milestone was designed to catch: the
recommendation silently hardening into a decision because it was the obvious and convenient answer.

**To proceed, supply one and only one: `D6-A`, `D6-B`, or `D6-C`.**

---

## 2. Validation performed (read-only, as permitted)

| Check | Result |
|---|---|
| M019 unchanged | ledger `COMPLETE`, 36 properties, `m019_modified = False`, id digest `91ae24a5…`, doc 32602 B |
| M052B evidence unchanged | **all 6 files byte-identical** to the digests frozen at adjudication |
| Production fingerprints | exact / exact |
| Production ACL | subject explicit ACEs **0 of 8** |
| `verify_boundary()` | `STAGING_BLOCKED` |
| `model/` | absent |
| `config/` | empty |
| `m016_*` artefacts | **all three still present — none deleted** |
| M052B freeze gate | `PASS` |
| M046 / M050 / M052B preservation | all roots intact |
| Dependency graph | `CONSISTENT`, **not updated** — correctly, since there is no decision to propagate |
| Target tree | `config/`, `runtime/`, three `m016_*` files — byte-identical to M052B pre/post state |

---

## 3. The contradiction, restated for the decision

M019 §11 fixes the canonical target set as `subject_runtime`, `runtime`, `model`, `config` — **and
only those**, explicitly excluding *"any `m016_*` fixture path, no artifact created by a test."*

* **T-BABY-1** requires something readable to exist in the subject's reachable set.
* **T-PATH-2** prohibits test fixtures from existing in the canonical set.
* The only readable files under `runtime\` **are** fixtures.

Therefore no compliant production target for T-BABY-1 currently exists, and M052B measured T-BABY-1
against `m016_read_fixture.exe` — simultaneously a valid live access observation and a T-PATH-2
violation.

---

## 4. The three options, prepared for recording

None is selected. Each is specified to the level this milestone's brief requires, so that whichever
is chosen can be recorded without further analysis.

### D6-A — `AUTHOR_CANONICAL_CONTENT`

Create legitimate non-test content inside the canonical `subject_runtime` namespace so T-BABY-1 has a
compliant object.

Consequences to record: production content changes; content provenance becomes necessary; future
experiments must distinguish authored subject/environment content from test fixtures; **T-PATH-2 is
unchanged**; additional governance is required to define who or what authors the content.

Requirements to answer before any implementation:

| # | Question | Status |
|---|---|---|
| 1 | What is the content? | unanswered |
| 2 | Who authors it? | unanswered |
| 3 | How is it provenance-labelled? | unanswered |
| 4 | Why is it not a test fixture? | unanswered |
| 5 | What makes it legitimate canonical environment state? | unanswered |
| 6 | Who may modify it? | unanswered |
| 7 | Is it immutable? | unanswered |
| 8 | Subject experience, environment state, or research instrumentation? | unanswered |
| 9 | How does T-PATH-2 distinguish it from prohibited test artefacts? | unanswered |

**Not performed.** This would create a new production mutation and therefore cannot occur in M052E.

### D6-B — `RESCOPE_T_BABY_1_NAMESPACE`

Keep the canonical topology unchanged. Define T-BABY-1's readable-data target outside the canonical
`subject_runtime` boundary, in an explicitly governed measurement namespace.

Requirements the brief specifies must be answered:

| # | Requirement |
|---|---|
| 1 | Canonical T remains exactly `subject_runtime/`, `runtime/`, `model/`, `config/` |
| 2 | T-PATH-2 remains unchanged |
| 3 | T-BABY-1's future observation target is **outside** T |
| 4 | The namespace has: explicit owner, explicit provenance, immutable experiment identity, explicit human/environment authorship, no ambiguity with subject state, and no subject mutation unless separately authorised |
| 5 | The namespace must not be used to smuggle test fixtures back into `subject_runtime` |
| 6 | M052B's result against `m016_read_fixture.exe` remains **historically valid** as a live access observation; its property-level status is reclassified only *after* a formal M019 amendment |
| 7 | M052B evidence is not retroactively altered |
| 8 | `m016_*` artefacts are not deleted in this milestone |
| 9 | The namespace is not created in this milestone |
| 10 | No ACL change in this milestone |

**Governance note:** D6-B moves a property's target outside T, which means **M019 itself must be
amended through a separately governed documentation milestone.** Per the brief's preference, this
milestone would record the decision only; the amendment follows as its own milestone.

### D6-C — `AMEND_M019_CANONICAL_TOPOLOGY`

Modify M019 so T-BABY-1 and T-PATH-2 are no longer contradictory.

Must identify exactly: the M019 section, the exact sentence or property affected, old semantics, new
semantics, security implications, provenance implications, whether `m016_*` artefacts become
legitimate, and whether future test artefacts become legitimate.

**Risk to weigh:** D6-C is the only option that can convert a *prohibition* into a *permission*. A
vague amendment such as "allow fixtures" would not resolve the contradiction — it would delete the
security semantics that make T-PATH-2 meaningful, and it would make T-PATH-2 permanently
SATISFIED-by-definition rather than by measurement. Any amendment must preserve a clear distinction
between canonical subject state, environment content, research instrumentation, disposable fixtures,
and provenance.

**No fourth option exists.** In particular, "temporarily ignore T-PATH-2" resolves nothing and is not
available. Neither property may be downgraded to make the ledger consistent.

---

## 5. Conditional dependency effects — for the decision, not decided here

Recalculated for each option so the choice is made with its consequences visible. **The design
dependency graph has not been modified.**

| | D6-A | D6-B | D6-C |
|---|---|---|---|
| **T-BABY-1** | becomes measurable against compliant in-place content | becomes measurable against a governed external namespace | becomes measurable, depending entirely on the amendment's wording |
| **T-PATH-2** | unchanged — still `NOT_ESTABLISHED`, still needs D1 | unchanged as a property; stops being the *blocker* for T-BABY-1 | **may become vacuous** — if relaxed to admit fixtures, the property is satisfied by definition and no longer measures anything |
| **Canonical T** | unchanged in definition; changed in content | **unchanged** | changed — definition is amended |
| **D1 (fixture removal)** | still required | becomes **cosmetic** — the namespace removes the reason to care | may become unnecessary if fixtures are legitimised |
| **D3 independence** | preserved — D3 untouched | preserved — D3 untouched | preserved, but the amended contract becomes the thing D3 must satisfy |
| **Production mutation** | **required** | none | none |
| **New measurement needed for T-BABY-1** | yes, after content exists | yes, against the namespace | yes, against whatever the amendment permits |
| **M052B evidence** | remains historically valid; status reclassified after content exists | remains historically valid; status reclassified after the M019 amendment | remains historically valid; status reclassified after the amendment |
| **M019 amendment needed** | no | **yes — separate governed milestone** | **yes — this option *is* the amendment** |

Two observations that hold regardless of choice:

1. **A decision makes a property MEASURABLE; it does not make it SATISFIED.** No option here changes
   any property's status. Every affected property needs a fresh observation after the decision is
   implemented.
2. **M052B's evidence is not retroactively altered under any option.** Its access observation stands
   as recorded; only its property-level interpretation may later change, and only after a formal
   amendment.

---

## 6. D3 boundary — held

D3 is untouched. No deny mask derived. No choice between `0x000D0156` and `0x00110156`. No ACL
containment rehearsed. No inheritance altered. `icacls`, `SetNamedSecurityInfo`, ownership and
production permissions all untouched.

D6 is a **property-contract** decision. D3 is a **security-boundary implementation** decision. They
require independent provenance and independent decision records, and combining them would make each
unreviewable.

---

## 7. Status

```
M052E_STATUS = AWAITING_DIRECTOR_DECISION
```

**Required to proceed — one and only one of:**

* **`D6-A`** — author canonical content
* **`D6-B`** — re-scope T-BABY-1's namespace
* **`D6-C`** — amend M019's canonical topology contract

No launch authorisation is requested. No M053 implementation is permitted. No production change is
permitted.

This milestone concerns only the formal relationship between M019's property definitions and the
canonical subject topology. It establishes nothing about cognition, consciousness, subjective
experience, agency, learning, memory, sentience, or model inference.