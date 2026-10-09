# M052S — Director Decision Intake, Provenance-Sealed Governance Record, and Recovery Gate Preparation

```
M052S_STATUS                       = DECISION_REQUIRED
M052S_NEXT_GATE                    = RECOVERY_GOVERNANCE_DECISION_REQUIRED

RECOVERY_GOVERNANCE_DECISION       = NONE
DECISION_AUTHORITY                 = NOT_SUPPLIED
PROVENANCE_SEAL_ID                 = NOT_SUPPLIED
PROVENANCE_VALIDATION              = NOT_APPLICABLE (nothing supplied to verify)
SELECTED_BY_OPERATOR               = NO

PRODUCTION_CHANGED                 = NO
PRODUCTION_RECOVERY_PERFORMED      = NO
RECOVERY_AUTHORISATION             = NOT_ISSUED
RECOVERY_CAPABILITY_FOR_PRODUCTION = NO
ACCIDENTAL_ACE                     = STILL PRESENT (DENY …-1022, 0x00000001, explicit)

D3 = NOT_APPLIED   SUBJECT_LAUNCH = NOT_ATTEMPTED   D4 = NOT_IMPLEMENTED
GATE_1 = CLOSED   GATE_2 = CLOSED   A/B/C = NONE
SECURITY_OBJECTIVE = NOT_SATISFIED — 5 of 8 forbidden rights present
T-BABY-1 = SATISFIED (M052H, unchanged)
```

> **No decision was supplied, so none was recorded.** M052S did not search again — M052R already
> established that repeating the search cannot produce one. It built the surface that will *receive*
> a decision when the director supplies one, and proved that surface cannot manufacture one.
> Production is descriptor-for-descriptor identical to the M052P start state.

---

## 1. What changed, and why this is not another STOP

M052Q searched for a decision. M052R searched again and proved the search was exhausted. A third
search would produce the same answer, so M052S stops searching and starts *receiving*.

The deliverable is `tests/m052s_intake.py`: an intake that validates, cryptographically verifies and
freezes a director decision — with no code path that produces one.

```
tests/m052s_intake.py     intake, verification, next-gate derivation, 43-case negative matrix
tests/test_m052s_intake.py  37 tests, 110 subtests
```

The asymmetry is structural, not stylistic:

| | Intake (what M052S built) | Selection (what M052S cannot do) |
|---|---|---|
| Function of | the director's submitted input | — |
| Produces | a validated, verified, frozen decision record | nothing |
| Fails by | refusing ambiguous language, unsealed content, non-HUMAN keys, ambiguous bindings | — |

`selected_option` can only ever be `None`, or a value carried in a submitted record that a
HUMAN-signed ledger entry binds by content hash.

## 2. Three properties enforced by construction, not convention

**Ambiguity resolves to absent, never to probably.** `parse_selection` accepts only an explicit
`choose/select/decide R1|R2|R3` form or a bare `R1|R2|R3`. Each phrase the prompt enumerates is
refused with its own reason: *"probably R1"* is a probability; *"use your recommendation"*, *"pick the
safest"*, *"proceed"*, *"you decide"* all delegate the selection to the model; *"authorize recovery"*
authorises an operation, not a governance class; *"recovery can use its own gate"* is not the written
policy R3 requires. Prose that merely names an option is prose.

**A seal must bind the decision, not merely exist.** Verification requires a ledger entry whose
`path` is the decision record, whose `content_sha256` equals the SHA-256 of the submitted bytes, whose
MAC verifies over `canonical_bytes(entry.signed_body())` under a key the keyring attributes to role
**HUMAN**, whose recomputed hash matches, and whose key fingerprint is intact. This is why
`PROV-000014` cannot be borrowed: it records a modification to `research/experiment-log.md`, and its
content hash will never match a governance decision record.

**Intake cannot mint authority.** The module contains no call to `Keyring.register`,
`ProvenanceLedger.record`, or `.seal()`, and assigns to no entry field. Provenance is opened to
*verify*, never to write. This is asserted over the parsed AST, not by substring search — a substring
test would either fail on the module's own docstring (which names those methods in order to explain
their absence) or pass if the explanation were deleted.

## 3. Four real defects found and fixed while building it

The intake was wrong four times. Each was found by a test, and each is now a permanent guard.

**1. Intake was completely inert.** `_normalise` lower-cased the submitted text and the selection
patterns matched `R[123]` case-sensitively, so *"I choose R1"* matched nothing. Every legitimate
selection was being refused. The failure was silent — intake would have reported `DECISION_REQUIRED`
forever and looked correct while doing it. Fixed by matching the verb case-insensitively and the
option case-preservingly, upper-casing the captured token. Guarded by
`test_selection_matching_is_case_insensitive`.

**2. MAC verification was silently skipped.** The code called `entry.signed_body_canonical()` — a
method that does not exist — inside a `hasattr` guard, so `mac_ok` became `None` and the MAC check was
dropped without ever being reported. A verification step that quietly degrades to *unknown* is worse
than one that fails. Now recomputed explicitly with `canonical_bytes(entry.signed_body())`, with a new
`entry_hash_recomputes` check alongside it. Guarded by
`test_provenance_checks_are_recorded_individually`.

**3. A dict had no well-defined content identity.** The hash was taken over `str(dict)`, which depends
on Python's `repr` and could never match a ledger entry produced by the repository's own tooling.
Defined instead as the canonical JSON encoding — the same form the ledger hashes.

**4. A duplicated seal id resolved to the wrong decision.** The lookup took the *first* entry matching
the seal id. Two decisions sharing a `seal_id` meant the second silently validated against the first's
seal. The lookup now collects every candidate and requires exactly one, preferring a path match only
when that is unambiguous among them; otherwise it refuses as ambiguous. Guarded by
`test_duplicate_seal_id_is_refused_as_ambiguous`.

A fifth issue was a test-harness defect rather than an intake defect, but it hid a real one: the
disposable harness reused one `decision_path` across subtests, breaking the ledger's per-path version
continuity. Fixing the harness is what exposed defect 4.

## 4. Negative matrix — 43/43 correct

`UNKNOWN` is never counted as a pass.

| group | cases | result |
|---|---|---|
| no submission (the actual state) | 1 | refused |
| ambiguous / delegating language | 9 | all refused |
| option mentioned, not selected | 2 | refused |
| conflicting selections | 1 | refused |
| structurally complete but unsigned | 1 | refused |
| borrowing the current head seal | 1 | refused |
| non-existent seal | 1 | refused |
| **every real repository seal, offered as authority** | **10** | **all refused** |
| missing required field | 7 | refused |
| scope assertion absent / false | 2 | refused |
| wrong decision class, out-of-range option, empty exclusions | 3 | refused |
| prompt text offered as a decision | 1 | refused |
| real seal id **plus** a real ledger path | 1 | refused |
| real seal id plus metadata mimicry | 1 | refused |
| authority smuggled into prose alongside a correct assertion | 1 | refused |
| empty submission | 1 | refused |

The two hardest cases are the last-but-three and the metadata mimicry: a submission naming a **genuine
existing seal id** and a **genuine path in the ledger**. Both fail on one check —
`seal_binds_submitted_content` — because the content hash, not the identifier, is what binds a seal to
a decision.

## 5. Option-specific next gates, derived not chosen

`next_gate_for` maps a *verified* option to its gate and never to a production recovery authorisation:

| option | classification | next gate | blocked on |
|---|---|---|---|
| R1 | distinct remediation class | `RECOVERY_AUTHORISATION_REQUIRED` | a fresh explicit `RecoveryAuthorisation` |
| R2 | subject to ordinary A/B/C | `A_B_C_DECISION_REQUIRED` | A/B/C, which M052S does not decide |
| R3 | distinct, own second gate | `RECOVERY_GATE_2_POLICY_REQUIRED` | a written policy, never inferred from R3 |
| none | — | `RECOVERY_GOVERNANCE_DECISION_REQUIRED` | the director |

No branch produces `AUTHORIZED`, `AUTHORISED`, or `READY`. Even a fully valid decision freezes with
`authorises_production_recovery = False`, `recovery_authorisation_status = NOT_ISSUED`,
`recovery_capability_for_production = NO`, `production_recovery_performed = False` — asserted for all
three options on disposable sealed records.

## 6. Production immutability — 12/12 read-only

No `Set-Acl`, `SetNamedSecurityInfo`, `RemoveAccessRuleSpecific`, `icacls`, `_apply_mask_to_path`,
`_clear_deny`, `_restore_dacls`, `recover_ace`, `execute_recovery`, `apply_subject_deny` or
`apply_boundary` was invoked. Refusal was proven by descriptor comparison; the intake's refusal paths
were exercised against the real ledger read-only and disposable fixtures only.

| # | condition | observed |
|---|---|---|
| 1 | accidental ACE present | explicit DENY, mask `0x00000001`, SID `…-1022` |
| 2 | target | `subject_runtime/runtime/m016_read_fixture.exe` |
| 3 | owner | `THARUNBALAJI-LA\k.tharun balaji` |
| 4 | DACL protection | `access_rules_protected = False`, unchanged |
| 5 | content | 25 bytes, sha256 `55250a71209a4d39…` — matches M052O/M052P/M052Q |
| 6 | fingerprints | v1 `8a0a66323bb4eb3b…`, v2 `7d592c7a03bf7a6f…` — **identical to M052P start** |
| 7 | D3 absent | no `0x000D0156` ACE |
| 8 | reconciliation | **18/18**, `production_mutated_by_m052p = False` |
| 9 | security objective | `NOT_SATISFIED`, shortfall 5 of 8 |
| 10 | recovery path | `execute_recovery()` → `AWAITING_EXPLICIT_RECOVERY_AUTHORISATION` |
| 11 | subject | not launched; password value never read |
| 12 | preservation copies | 17 `TharAI_M*` roots intact in `%LOCALAPPDATA%\Temp` |

```
incident-state v1   8a0a66323bb4eb3b…    pre-incident v1   f73eaf783ffb2698…   PRESERVED
incident-state v2   7d592c7a03bf7a6f…    pre-incident v2   1684a02f028412e1…   PRESERVED
incident v1 != pre-incident v1 : True
```

The accidental state and the pre-incident fingerprint both remain historical facts. Neither was
rewritten, and they were not made equal by rewriting either.

## 7. Provenance mechanism — verified read-only, untouched

```
ledger entries : 14 valid, 0 malformed, 0 problems
sealed head    : PROV-000014, 0 problems
HEAD.json      : unchanged (still PROV-000014, signing_role HUMAN)
ledger written : NO — verified only
```

The repository's established chain verifies cleanly, which is what makes a future director decision
verifiable. No entry was appended, no seal was created, `control.token` and `control.json` were not
modified, and no key material was loaded for writing, printed, or transmitted.

## 8. Regression — nothing weakened, nothing new broken

```
M052S + M052K/L/N/O/P suite : 267 passed, 7 failed
  (230 passed before M052S; +37 new tests all passing)
standing red baseline        : 12 failed, 65 passed
```

The same 7 failures, all incident-caused M052K/M052L pre-incident-fingerprint assertions:
`test_production_is_unchanged_by_the_milestone`, `test_guard_passes_against_live_production`,
`test_all_fourteen_authorisation_conditions_pass`, `test_m019_a1_taxonomy_untouched`,
`test_full_validation_passes` (M052K); `test_production_is_unchanged`,
`test_full_validation_passes` (M052L).

These assert a fingerprint that no longer holds because of the M052M incident. They are evidence, not
defects. They were **not** weakened, skipped, or deleted. The standing red baseline is unchanged.
**M052S introduced no new failures.**

M052S ran no disposable recovery test, so there was no disposable state requiring restoration.

## 9. Git / provenance

```
HEAD   : 6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555
branch : master
staged : 0 files
committed this milestone : NONE — nothing committed, amended, rebased, reset, pushed, or cleaned
```

Modified tracked files: 8, unchanged from M052Q — `docs/evidence/m019-intended-production-boundary.md`,
`foundation/security_verify.py`, `foundation/staging.py`, `foundation/subject_deny.py`,
`tests/guarded.py`, `tests/test_boundary_harness.py`, `tests/test_subject_boundary_run.py`,
`tests/test_subject_deny.py`. M052S modified no tracked file.

New untracked files, 3: `docs/evidence/m052s-recovery-governance-decision.md`,
`tests/m052s_intake.py`, `tests/test_m052s_intake.py`. No historical evidence was deleted, rewritten,
or reconciled away. The 7 pre-existing stray files from earlier shell quoting accidents were left
untouched — deletion requires instruction.

## 10. Final status

```
M052S_STATUS    = DECISION_REQUIRED
M052S_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED
PRODUCTION_RECOVERY_PERFORMED = NO
```

To advance, supply an explicit `RECOVERY_GOVERNANCE` decision selecting exactly one of R1 / R2 / R3,
carrying `decision_id`, `authority_id`, `authority_type`, `rationale`, `scope`,
`effective_for_milestone`, `exclusions`, `incident_reference`, `repository_HEAD`,
`predecessor_decision_reference`, `supersedes`, an assertion that it is classification only, and a
`provenance_seal_id` backed by a HUMAN-signed ledger entry binding that exact content. M052S will
verify and freeze it, and will still not execute recovery.

---

## Non-cognitive scope

M052S concerns human governance, recovery classification, provenance, authorisation separation,
filesystem recovery policy, and production ACL safety. It establishes nothing about cognition,
consciousness, subjective experience, agency, learning, memory, intelligence, developmental stage,
sentience, or model inference. No option was selected, no authority was manufactured or reused, no
`RecoveryAuthorisation` or production capability was created, no gate was opened, D3 was not applied,
the subject was not launched, and no production descriptor was altered.