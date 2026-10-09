# Baby AI Project Status Dashboard

Evidence date: **2026-10-09** · GIT_HEAD: `6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555` · Ledger: **18 entries, head PROV-000018, sealed**.

> Read-only status artifact: this page asserts nothing, authorizes nothing, and changes nothing. Full-color local version: `docs/m067-status-dashboard.html` (open in a browser).

## Live-verified headline state

| Fact | Live value |
| --- | --- |
| `ledger_entries` | `18` |
| `ledger_head` | `PROV-000018` |
| `chain_intact` | `True` |
| `seal_intact` | `True` |
| `gate_1` | `CLOSED` |
| `gate_2_open` | `False` |
| `explog_drift` | `07efda7adb6ee30f` |
| `m064_sha` | `e2a3939e77a55200` |
| `runtime_selection` | `False` |
| `model_deployment` | `False` |
| `birth_record` | `False` |
| `production_descriptor` | `d63ff646bec494c198db9031491558f2744ea40bb2b1af016090e980865c1f27` |
| `production_content` | `55250a71209a4d397dc51f3f12da105455a5d20ace53062416d26079fded0cdf` |

## Progress by track (exact fractions; no blended percent asserted)

Rules: categorical milestones only; HOLD counts as complete (hold fulfilled its purpose); specifications excluded from implementation counts; tests never count as authorization; readiness never counts as operation.

| Track | Scope | Progress |
| --- | --- | --- |
| Recovery governance & execution | M052J–M057 + M054B (decision iterations counted once as M052Q–Y) | `██████████` 15/15 |
| Post-recovery review & reconciliation | M058–M061 | `██████████` 4/4 |
| Developmental governance & safety | M062–M068 | `█████████░` 6/7 |
| Laboratory foundation, instruments & holds | M001–M052I (machinery, instruments, sessions, holds; statuses per own evidence) | `██████████` 62/63 |

## Workstream map (dot color only; no weighting)

| Workstream | Status | Note | As of |
| --- | --- | --- | --- |
| Recovery governance & execution | 🟩 COMPLETE | M057 poststate exact; incident closed with audit items | 2026-10-09 |
| Post-recovery reconciliation | 🟩 COMPLETE | M060 dual-mode; live post-recovery PASS | 2026-10-09 |
| Provenance & seals | 🟩 HEALTHY (known drift) | 17 entries intact, head PROV-000018 sealed; exp-log drift accepted (Option A) | 2026-10-09 |
| Isolation & boundaries | 🟨 PARTIAL | Tier 1/2 partial; Tier 3 absent; F1 fixed M066; FILE_DELETE_CHILD open | 2026-10-09 |
| Foundation / model / runtime | 🟨 PARTIAL | machinery real; no artifacts selected, nothing staged | 2026-10-09 |
| Birth & lifecycle | 🟨 PARTIAL | machinery complete; BLOCKED (no declaration); no birth | 2026-10-09 |
| Launch & sessions | 🟨 BLOCKED | holds active; no auth; no session; NOT_TESTABLE unattended | 2026-10-09 |
| Observatory & telemetry | 🟨 PARTIAL | read-only pipeline; bans enforced; no INTERPRETATION/HYPOTHESIS split | 2026-10-09 |
| Developmental governance | 🟩 COMPLETE | M064 sealed; implementation deferred; F1 remediated | 2026-10-09 |
| Human control & security posture | 🟨 PARTIAL | separation by design; HMAC/Tier-3/contract caveats carried | 2026-10-09 |

Legend: 🟩 complete/healthy/closed/frozen/pass; 🟨 partial/hold-active/blocked/mitigated (attention, not failure); 🟥 missing/open/fail; ⬜ evidenced-not-reverified / unknown / specification. FAIL on incident-state checks after recovery means 'incident absent', not failure.

## Gates (independent of progress)

| Gate | State | Basis |
| --- | --- | --- |
| D3 Gate 1 (production mutation) | 🟩 CLOSED | no valid ProductionAuthorisation exists |
| Gate 2 (production capability) | 🟩 CLOSED | no GovernanceDecision; in-memory, fresh-process closed |
| Birth gates (M009/M013) | 🟨 BLOCKED | no declaration; MODEL_NOT_CONFIGURED |
| Launch interlocks | 🟨 BLOCKED | no selection; holds; no session |
| Lifecycle | ⬜ UNCREATED | no BIRTH.json |
| A/B/C policy | 🟥 NONE | no decision |
| Network | ⬜ NO NETWORK (loopback pending final policy) | D7 open |

## Authorizations (independent of tests)

| Authorization | State | Note |
| --- | --- | --- |
| M054 R1 governance | FROZEN (PROV-000015) | classification only; authorises no recovery |
| M056 recovery auth 990c6e6f… | SPENT (PROV-000016) | consumed by M057; module self-neutralized |
| M057 execution | CONSUMED (PROV-000017) | one verified ACE removal; poststate exact |
| M064 boundary decision | RECORDED (PROV-000018) | architecture only; grants nothing |
| M031/M052Z/M053 holds | ACTIVE | launch/recovery/D3 BLOCKED by design |
| Launch authorization | NONE | prior auths spent; fresh verbatim words required |
| Birth authorization | NONE | no declaration; M014 BLOCKED |
| A/B/C decision | NONE | ordinary-mutation Gate-2 track untouched |

## Milestones M001–M067

| ID | Title | Status | Basis | Re-verified M067 |
| --- | --- | --- | --- | --- |
| M001 | Laboratory instrumentation | ⬜ EVIDENCED | ledger MILESTONE-001 entries (5) + experiment log | basis only |
| M002 | Cognitive State Observatory | ⬜ EVIDENCED | ledger MILESTONE-002 entries (4) + observatory code | basis only |
| M003 | Birth ceremony / model identity / truthful display | ⬜ EVIDENCED | ledger MILESTONE-003 entries (3) | basis only |
| M004 | Trust boundary architecture | ⬜ EVIDENCED | docs/m004-trust-boundary.md | basis only |
| M005 | OS isolation (Tier 2 verified by human probes) | ⬜ EVIDENCED | m005-final-verification.json (2/11 probed; residuals noted) | basis only |
| M006 | Foundation-model and runtime layer | ⬜ EVIDENCED | docs/evidence/m006 doc era | basis only |
| M007 | Environment and interaction substrate | ⬜ EVIDENCED | docs/m007-environment.md | basis only |
| M008 | Subject architecture boundary | ⬜ EVIDENCED | docs/m008-subject.md | basis only |
| M009 | Birth ceremony + controlled experience | ⬜ EVIDENCED | birth/ceremony.py gate BLOCKED absent model | basis only |
| M010 | Foundation acquisition/verification | ⬜ EVIDENCED | docs evidence era | basis only |
| M011 | Real runtime + subject-account execution | ⬜ EVIDENCED | docs evidence era | basis only |
| M012 | Foundation deployment verification | ⬜ EVIDENCED | m012-deployment-verification.json BLOCKED/NOT_CONFIGURED | basis only |
| M013 | Real birth ceremony / first experience | ⬜ EVIDENCED | birth gate13/ceremony13 machinery, no birth | basis only |
| M014 | First real birth | 🟨 BLOCKED | no model_deployment.json; M014 real result BLOCKED (verified absent 2026-10-09) | YES |
| M015 | Subject-runtime staging boundary | ⬜ EVIDENCED | staging design; nothing staged (verified 2026-10-09) | YES |
| M016 | Subject-account runtime launch feasibility | ⬜ EVIDENCED | BABY_AI_TEST verified; launch NOT_TESTABLE | basis only |
| M017 | Security objective decision | ⬜ EVIDENCED | docs/evidence/m017 doc | basis only |
| M018 | Canonical state reconstruction | ⬜ EVIDENCED | docs/evidence/m018 doc | basis only |
| M019 | Intended production boundary | ⬜ EVIDENCED | docs/evidence/m019 doc | basis only |
| M020 | Security boundary verifier | ⬜ EVIDENCED | docs/evidence/m020 doc | basis only |
| M021 | Boundary implementation design (T/MASK unselected) | ⬜ EVIDENCED | docs/evidence/m021 doc | basis only |
| M022 | Repository state reconciliation | ⬜ EVIDENCED | docs/evidence/m022 doc | basis only |
| M023 | Harness mutation-surface closure | ⬜ EVIDENCED | docs/evidence/m023 doc | basis only |
| M024 | Complete mutation-surface closure | ⬜ EVIDENCED | docs/evidence/m024 doc | basis only |
| M025 | Subject test-fixture resolution | ⬜ EVIDENCED | docs/evidence/m025 doc | basis only |
| M026 | Disposable deployment readiness (INCOMPLETE: unmeasured) | ⬜ EVIDENCED | docs/evidence/m026 doc | basis only |
| M027 | Interactive enforcement measurement (NOT_ATTEMPTED) | ⬜ EVIDENCED | docs/evidence/m027 doc | basis only |
| M028 | Adjudicator + measurement readiness | ⬜ EVIDENCED | docs/evidence/m028 doc | basis only |
| M029 | Human-gated measurement decision | ⬜ EVIDENCED | docs/evidence/m029 doc | basis only |
| M030 | Interactive subject measurement | ⬜ EVIDENCED | docs/evidence/m030 doc | basis only |
| M031 | Experimental hold / human-session handoff | 🟨 HOLD-ACTIVE | hold doc; AUTOMATED_SUBJECT_LAUNCH NOT_AVAILABLE | basis only |
| M032 | Disposable session target reconciliation | ⬜ EVIDENCED | docs/evidence/m032 doc | basis only |
| M033 | Baby-AI test session path investigation | ⬜ EVIDENCED | docs/evidence/m033 doc | basis only |
| M034 | Cached subject-credential disposition | ⬜ EVIDENCED | docs/evidence/m034 doc | basis only |
| M035 | Cached credential removal | ⬜ EVIDENCED | docs/evidence/m035 doc | basis only |
| M036 | Cached credential deletion root cause | ⬜ EVIDENCED | docs/evidence/m036 doc | basis only |
| M037 | Interactive session readiness | ⬜ EVIDENCED | docs/evidence/m037 doc | basis only |
| M038 | First interactive launch analysis | ⬜ EVIDENCED | docs/evidence/m038 doc | basis only |
| M039 | Instrument launcher contract remediation | ⬜ EVIDENCED | docs/evidence/m039 doc | basis only |
| M040A | Launch selection reconciliation | ⬜ EVIDENCED | docs/evidence/m040a doc | basis only |
| M040B | Launcher privilege capture | ⬜ EVIDENCED | docs/evidence/m040b doc | basis only |
| M040C | Two-launch-attempt reconciliation | ⬜ EVIDENCED | docs/evidence/m040c doc | basis only |
| M041 | Handoff access-contract decision | ⬜ EVIDENCED | docs/evidence/m041 doc | basis only |
| M042 | Trusted writer handoff design | ⬜ EVIDENCED | docs/evidence/m042 doc | basis only |
| M043 | Live trusted-writer connection gate | ⬜ EVIDENCED | docs/evidence/m043 doc | basis only |
| M044 | Live trusted-writer attempt | ⬜ EVIDENCED | docs/evidence/m044 doc | basis only |
| M045 | Human live trusted-writer attempt | ⬜ EVIDENCED | docs/evidence/m045 doc | basis only |
| M046 | Live experiment (+result) | ⬜ EVIDENCED | docs/evidence/m046 docs | basis only |
| M047 | Live trusted-writer adjudication | ⬜ EVIDENCED | docs/evidence/m047 doc | basis only |
| M048 | External token observation strategy | ⬜ EVIDENCED | docs/evidence/m048 doc | basis only |
| M049 | Strategy-A authorization gate | ⬜ EVIDENCED | docs/evidence/m049 doc | basis only |
| M050 | Live token observation gate (+result) | ⬜ EVIDENCED | docs/evidence/m050 docs | basis only |
| M051 | Subject-side enforcement measurement design | ⬜ EVIDENCED | docs/evidence/m051 doc | basis only |
| M052 | Live launcher freeze + read-only measurement gate | ⬜ EVIDENCED | m052 freeze docs; auths spent | basis only |
| M052A | Read-only instrument build + rehearsal | ⬜ EVIDENCED | docs/evidence/m052a doc | basis only |
| M052B | Live adjudication + production target mapping | ⬜ EVIDENCED | docs/evidence/m052b docs | basis only |
| M052C | M019 property adjudication | ⬜ EVIDENCED | docs/evidence/m052c doc | basis only |
| M052D | Canonical topology decision gate | ⬜ EVIDENCED | docs/evidence/m052d doc | basis only |
| M052E | D6 topology contract decision | ⬜ EVIDENCED | docs/evidence/m052e doc | basis only |
| M052F | M019 D6B amendment | ⬜ EVIDENCED | docs/evidence/m052f doc | basis only |
| M052G | Observation namespace implementation | ⬜ EVIDENCED | docs/evidence/m052g doc | basis only |
| M052H | T-BABY-1 preflight + live adjudication | ⬜ EVIDENCED | docs/evidence/m052h docs | basis only |
| M052I | Post-M052H governance reconciliation | ⬜ EVIDENCED | docs/evidence/m052i doc | basis only |
| M052J | D3 deny-mask decision (0x000D0156) | ⬜ EVIDENCED | docs/evidence/m052j doc | basis only |
| M052K | D3 implementation (frozen mechanism, gates closed) | ⬜ EVIDENCED | m052k module; no production write path | basis only |
| M052L | Interlock governance (Gate 2 mechanism, unopened) | ⬜ EVIDENCED | m052l module; evaluate() never permits write | basis only |
| M052M | Accidental production ACE incident (governance readiness) | ⬜ EVIDENCED | incident docs; ACE removed by M057 | basis only |
| M052N | Incident exactness proof (disposable) | ⬜ EVIDENCED | m052n module + tests | basis only |
| M052O | Recovery authorisation architecture + disposable proof | ⬜ EVIDENCED | m052o module; 21-case matrix | basis only |
| M052P | Recovery governance gate (40-case matrix, decision NONE) | ⬜ EVIDENCED | m052p module + matrix | basis only |
| M052Q–Y | Recovery-governance decision iterations | ⬜ EVIDENCED | docs/evidence/m052q–y docs | basis only |
| M052Z | Director decision hold | 🟨 HOLD-ACTIVE | hold module; launch/recovery/D3 BLOCKED | basis only |
| M053 | Governance hold finalization | 🟨 HOLD-ACTIVE | hold module; holds active | basis only |
| M054 | R1 governance frozen (HUMAN seal PROV-000015) | 🟩 COMPLETE | canonical digest 0b7148e0… verified live 2026-10-09; ledger+seal | YES |
| M054B | Provenance discrepancy adjudication (pre-existing) | 🟩 COMPLETE | evidence doc; drift confirmed pre-M054 | YES |
| M055 | Recovery authorisation design (unsigned draft) | 🟩 COMPLETE | session report; gaps documented, none repaired | YES |
| M056 | Recovery authorisation issued (HUMAN seal PROV-000016) | 🟩 COMPLETE | canonical 4d5c64e5… verified live 2026-10-09; ledger+seal | YES |
| M057 | Recovery executed + verified (one exact ACE removal) | 🟩 COMPLETE | poststate d63ff646… verified live 2026-10-09; PROV-000017 | YES |
| M058 | Post-recovery security review (module CLASS A) | 🟩 COMPLETE | session report; read-only | YES |
| M059 | Developmental readiness review | 🟩 COMPLETE | session report; read-only | YES |
| M060 | Reconciliation versioned (incident vs post-recovery) | 🟩 COMPLETE | m060 module+tests; live PASS verified 2026-10-09 | YES |
| M061 | Experiment-log drift disposition (Option A accepted) | 🟩 COMPLETE | session report + human disposition; file untouched | YES |
| M062 | Gate-1 preparation package (D3-scoped finding) | 🟩 COMPLETE | session report; no files changed | YES |
| M063 | Developmental gate architecture (no implementation) | 🟩 COMPLETE | session report; SPECIFICATION row, not implementation | YES |
| M064 | Developmental boundary decided (Option C, sealed) | 🟩 COMPLETE | canonical e2a3939e… verified live 2026-10-09; PROV-000018 | YES |
| M065 | Implementation-preparation contract (F1 BLOCKING found) | 🟩 COMPLETE | session report; SPECIFICATION row | YES |
| M066 | F1 staging/recovery remediation (verified) | 🟩 COMPLETE | staging.py guards + 10/10 tests; production unchanged | YES |
| M067 | Status dashboard (this milestone) | 🟩 COMPLETE | report accepted; page+tests delivered | YES |
| M068 | Graphical treemap dashboard | 🟥 OPEN | in progress; completes on accepted report | YES |

## Open human decisions

| Decision | Needed before |
| --- | --- |
| Tier 3 mandate vs accepted risk | before launch |
| Tier-2 credit vs fresh full-coverage proof | before birth-execution/launch per human call |
| FILE_DELETE_CHILD close vs accept | before launch |
| Staging immutability demonstration timing | human call |
| Final network policy | before any launch |
| Model + runtime selection | separate human milestone |
| Birth authorization | after implementation + evidence |
| Launch authorization | after birth + fresh verbatim words |

## Risks

| Risk | State | Note |
| --- | --- | --- |
| F1 staging defaults | CLOSED (M066) | guards + 10/10 tests; production unchanged |
| Misconfigured launch as operator | OPEN | Tier 3 absent; privilege/session path undecided |
| Reconcile 02/05/09 misread as failure | MITIGATED | M060 dual-mode + this dashboard's legend |
| Single-operator HMAC provenance limits | ACCEPTED (documented) | ADR-003; third-party verification blocked |
| Undiscovered writer outside scan patterns | UNKNOWN (bounded) | M062/M066 scans; novel primitives uncovered |

## Next recommended milestone

**M068** — Human review: accept M066 F1 remediation; scope D6/D7/model-runtime decisions for birth-boundary implementation (recommendation only; no authorization)

## Methods & limitations

Headline facts re-verified live via ledger verify + seal check, gate reads, file hashing, and existence checks on 2026-10-09. Earlier milestones marked EVIDENCED carry their own evidence docs' claims, not fresh M067 verification. No blended completion percentage is asserted; the prior informal forty-percent figure is not used.

