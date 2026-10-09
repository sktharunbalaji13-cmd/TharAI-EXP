# M052D — Canonical Subject Topology and Property Dependency Decision Gate

```
M052D_STATUS                     = COMPLETE_AWAITING_DIRECTOR_DECISIONS
GATE_VERDICT                     = CONSISTENT
DECISIONS_TAKEN_BY_THIS_GATE     = NONE
QUESTIONS_ALREADY_SETTLED_BY_M019 = 5
GENUINELY_OPEN_DECISIONS         = 6
M019_PROPERTIES_TOTAL            = 36
  decision-gated                 = 23
  rehearsal-gated                = 2
  ungated / already closed       = 11
HIGHEST_LEVERAGE_DECISION        = D3 (deny-mask selection) — unblocks 15 properties
SUBJECT_LAUNCH                   = NOT_ATTEMPTED
HUMAN_AUTHORIZATION              = NOT_REQUESTED
PRODUCTION_CHANGED               = NO
PRODUCTION_ACL_CHANGED           = NO
MODEL_PRESENT                    = NO
M052C_EVIDENCE_PRESERVED         = YES
```

> Design-only gate. No experiment designed, no mutation order chosen, no mutating test authorised,
> no authorisation requested. Production untouched.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. The headline: three of the eight questions were never open

M052D was asked eight questions. On reading M019's authoritative text, **three are already answered,
and the current production state violates all three.** Reporting that is more useful than
re-deliberating them — a gate that reopens settled questions to look busy is worse than no gate.

| Question asked | M019's answer | Citation | Current state |
|---|---|---|---|
| What is the canonical topology? | Exactly `subject_runtime`, `runtime`, `model`, `config` — **and only those** | §11 | `model\` **absent**; 3 `m016_*` files inside `runtime\` |
| Are the `m016_*` files legitimate or contamination? | **Contamination.** *"No `m016_*` fixture path, no artifact created by a test."* | §11, §13 row 1 | three present in the target path set |
| Does T-PATH-2 prohibit the fixture used for T-BABY-1? | **Yes, explicitly and by construction** | §11, T-PATH-2 | M052B measured T-BABY-1 on exactly such an artefact |

Two more are also settled and, if anything, *improved* by M052B:

| Question | M019 | Now |
|---|---|---|
| Verify traversal by ACL letters or OS measurement? | OS measurement under the subject, never letters (§12) | **discharged by M052B** — T-TRAV-4 was M019's REQUIRES IMPLEMENTATION item |
| Is traversal denial relied on as a control? | No — `SeChangeNotifyPrivilege` makes the ACE non-load-bearing | unchanged; M052B correctly claimed nothing from observed traversal |

**So the canonical topology is not an open design question. It is a fixed contract, and production
does not currently meet it.**

I also checked whether the fixtures are actively regenerating — i.e. whether the test harness
re-contaminates production on every run, which would make T-PATH-2 permanently unachievable. They are
not. The harness's mutating paths were already relocated to `tmp_path` ("one of three call sites that
mutated"), and the one remaining reference to production paths builds an argument string without
executing the probe. The `m016_*` files are **legacy debris from M016**, not a live contamination
mechanism.

---

## 2. The architectural contradiction

M019 requires two things that **cannot both hold** on the current topology:

* **T-BABY-1** — the subject can read data, so something readable must exist in the target set;
* **T-PATH-2** — no test-fixture artefact may be inside the target path set.

The only files under `runtime\` *are* fixtures. Therefore:

> **T-BABY-1 can currently be satisfied only on an object whose presence violates T-PATH-2.**

M052B measured precisely that. M052C recorded the tension without resolving it. Three ways out, none
of them a measurement question:

| | Option | Consequence |
|---|---|---|
| **A** | the target set legitimately contains non-fixture content at this stage | something must be **authored into production** — a mutation the freeze forbids |
| **B** | it does not | T-BABY-1 has no compliant target; it must be re-scoped to a namespace outside `subject_runtime` |
| **C** | T-PATH-2 governs only *test-created* debris, so M052B's target was legitimate | M019 §11's wording must change |

**This is D6**, and it is the decision I would take first. Option B — a
`subject_runtime_measurement\` namespace beside the canonical set, mirroring production topology and
never counted as production evidence — is the only option that satisfies T-PATH-2 *and* still permits
measurement, and it makes D1 cosmetic rather than load-bearing.

---

## 3. The six genuinely open decisions

| id | Question | Why open | Unblocks |
|---|---|---|---|
| **D1** | Remove the three `m016_*` artefacts? | M019 §16.9: *"Their removal is a production mutation and is **not decided here**."* | 2 |
| **D2** | Should `model\` exist while no model is configured? | M019 requires four paths; it is absent; creating it is a mutation | **6** |
| **D3** | Which deny mask reaches the security objective? | M019 §16.1: *"REQUIRES DESIGN DECISION"* — deliberately deferred so properties settle first | **15** |
| **D4** | Close T-WR-1..10 by subject run, or by remediation + descriptor re-read? | M019 assigns "DACL + subject-run denial"; the freeze bars the subject-run half | 14 |
| **D5** | Add `SYNCHRONIZE` to the deny set? | M019 §16.10: *"NOT ESTABLISHED"* | 0 (component of D3) |
| **D6** | Separate measurement namespace outside `subject_runtime`? | M019 admits no test-created artefact, but measurement needs targets | 3 |

### D3 is the precondition for the entire mutation question

Until the deny mask is chosen, **T-WR cannot be closed by either route** — and a mutation experiment
would be measuring an objective that has not been defined. That is the concrete answer to your
question 8.

### D2 is the highest-leverage topology decision

Five of the six topology-blocked properties sit behind it. But note carefully:

> An **empty** `model\` would satisfy T-PATH-1 and T-OWN-1/3. It would **not** satisfy T-BABY-5's
> loadability conjunct, which needs a real image.

Creating a directory is cheap and is a one-line change. Obtaining a model is a separate and much
larger decision that this laboratory has repeatedly declined to make. Do not let D2 quietly become
model acquisition.

---

## 4. Answer to question 8 — no mutation experiment, and here is the argument

> *"Does the current effective-access finding require a security-boundary decision before any
> mutation experiment can responsibly occur?"*

**Yes — and more strongly than that: no mutation experiment should be run against production under
any circumstances, because a subject-run write against production *is* a production mutation.** There
is no containment and no recovery here. The experiment and the violation are the same act.

The deeper point is that such an experiment has **almost no marginal information value**:

| | |
|---|---|
| Deny set | 8 rights, `derive_subject_deny_mask() = 0x000D0156` |
| Subject effective access | `0x001301BF` |
| Required-denied but present | **5 of 8** — `FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `FILE_WRITE_EA`, `FILE_WRITE_ATTRIBUTES`, `DELETE` |
| Already established by descriptor | Whether each objective-denied right is granted. `effective_access()` resolves allow/deny precedence, so an unshadowed granted right is *present* in effective access |
| What a subject run would add | Only that the grant is **functional**. On NTFS a granted, unshadowed standard right is functional by construction — close to tautological |
| Risk on a disposable tree | Low, but ACL composition would differ (explicit grants vs inherited group ACEs), so a denial there would not transfer |
| Risk on production | Total and irreversible |

**Recommendation (D4 option 1): close T-WR by remediation under D3, then re-read the descriptor.** No
subject run required. That converts ten properties from "unmeasured" to "measured by descriptor"
without exposing production to a single byte of mutation.

A new status may be needed for this closure route — closing a property by remediation-plus-verification
rather than by observing the subject refuse. That is a taxonomy question for D3/D4 to settle, and I
have deliberately **not** invented a status for it.

---

## 5. Dependency graph

```
D3 (deny mask)      15  T-WR-1..10, T-WR-11, T-BABY-6..9
D4 (closure method) 14  T-WR-1..10, T-BABY-6..9
D2 (model\)          6  T-PATH-1, T-OWN-1, T-OWN-3, T-TRAV-2, T-BABY-4, T-BABY-5
D6 (namespace)       3  T-BABY-1, T-PATH-2, T-BABY-5
D1 (fixture removal) 2  T-PATH-1, T-PATH-2
D5 (SYNCHRONIZE)     0  component of D3
rehearsal-only       2  T-ADM-4, T-ADM-5
ungated             11  closed, or closed subject to no architectural decision
```

`23 + 2 + 11 = 36`. The gate accounts for every M019 property, and `validate_gate()` returns
`CONSISTENT` with no unreachable gates.

One modelling correction made during this gate: `T-ADM-4` and `T-ADM-5` were initially listed in the
gated map with *empty* blocker tuples, which made them appear gated yet unreachable — they are gated
on rehearsal work, not on any architectural decision. They are now modelled separately. A gate that
cannot distinguish "blocked by a decision" from "blocked by work" is not a dependency graph.

---

## 6. Answers to the eight questions, condensed

1. **Canonical topology?** Already fixed by M019: four paths, only those. Currently violated.
2. **`m016_*` legitimate or contamination?** Contamination, by M019's explicit wording. Legacy M016 debris, not actively regenerating.
3. **Should `model\` exist?** **D2 — open.** Empty `model\` satisfies T-PATH-1/T-OWN-1/3 but not T-BABY-5 loadability.
4. **Which properties are inherently blocked?** 23 decision-gated, listed above; D2 and D3 dominate.
5. **Which should become `NOT_MEASURABLE_ON_CURRENT_DEVELOPMENTAL_TOPOLOGY`?** I have **not** invented this label. My M052C ledger already uses `NOT_MEASURABLE_ON_CURRENT_PRODUCTION_TOPOLOGY`, which is accurate — the blocker is the production topology's *contents*, not a developmental stage. Proliferating labels for the same condition would make the ledger harder to read, not easier. Flagged for your call.
6. **Does T-PATH-2 prohibit the T-BABY-1 fixture?** Yes, explicitly. M052B had no compliant alternative available.
7. **Separate measurement namespace?** **D6 — open.** Recommended: yes, `subject_runtime_measurement\`.
8. **Boundary decision before mutation?** **Yes — D3 first.** And no mutation experiment against production ever; close T-WR by remediation plus descriptor re-read.

---

## 7. What this gate did not do

* It took no decision. `decision_taken_by_this_gate = False`.
* It changed no production content, no ACL, no property definition, and no status vocabulary.
* It designed no mutation experiment and selected no mutation order.
* It requested no authorisation and launched nothing.
* It did not resolve the T-BABY-1 / T-PATH-2 tension. It identified it, attributed it, and named the
  three exits.

---

## 8. Recommended sequence, for your decision

1. **D6** first — the measurement namespace. It is cheap, it removes the T-BABY-1/T-PATH-2
   contradiction, and it makes D1 cosmetic.
2. **D3 + D5 together** — deny-mask selection including `SYNCHRONIZE`. This is the precondition for
   the entire mutating family and must precede any authorisation.
3. **D4** — closure method, which on the analysis above should be remediation plus descriptor re-read.
4. **D2** — `model\` existence, explicitly *not* model acquisition.
5. **D1** — fixture removal, bundled with D3 if D3 proceeds.

D3 is the one that unblocks the most and the one that touches production. It deserves a milestone of
its own, with the same discipline as M052: freeze, rehearse disposably, and only then act.

No M052D conclusion establishes cognition, consciousness, subjective experience, agency, learning,
memory, sentience, or model inference.