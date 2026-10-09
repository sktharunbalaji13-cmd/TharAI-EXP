# M070 — Security Prerequisite Work Plan & Evidence Sequencing

**Status: SPECIFICATION / PREPARATION ONLY.** This document plans work; it proves
nothing, signs nothing, and authorizes nothing — no birth, launch, deployment,
network change, ACL change, gate movement, or new capability.

**Direction inputs (planning premises from M069/human, not new decisions):**
M066 F1 remediation accepted with its residual prevention gap tracked separately;
Tier 3 required before launch (operator-rights execution not the default); Tier 2
fresh direct probes planned for all 11 paths with the 2-vs-9 distinction preserved;
FILE_DELETE_CHILD scoped remediation designed, not applied; staging-immutability
proof deferred but hard-gated before birth execution and launch; provisional
no-network/loopback-only intent with no enforcement claimed.

**Baseline (verified 2026-10-09, read-only):** HEAD `c4753e2` == `origin/master`;
ledger 18 entries, head `PROV-000018`, chain/MAC/seal intact; Gate 1 CLOSED (D3
scope), Gate 2 CLOSED; production fixture descriptor
`d63ff646…` / content `55250a71…` exact, accidental ACE absent; experiment-log
drift `07efda7a…` preserved per M061 Option A; M064 record `e2a3939e…` intact; no
`runtime_selection.json`, `model_deployment.json`, or `BIRTH.json`; no subject.

## 0. Terminology (binding on this plan)

- **Verified fact:** re-checked against repository state on the evidence date.
- **Proposal:** designed but unexecuted and unauthorized.
- **Unknown:** cannot be established from current evidence; marked, never smoothed.
- **Declaration** (policy text, e.g. `LOCAL_ONLY_NO_FETCH`) ≠ **enforcement**
  (mechanism) ≠ **observed evidence** (measurement) ≠ **authorization** (human grant).

## 1. M066 residual gap (accepted fix + tracked remainder)

- **Accepted:** `deploy_artifact()` and `recover()` in `foundation/staging.py`
  refuse omitted/falsy roots before anything else and pass explicit roots through
  `_refuse_canonical_production` (verified in source; 10/10 tests green;
  production triple-baseline identical; zero callers depend on any default).
- **Tracked remainder (NOT implemented here):** the source-scan test covers only
  those two functions. A future mutating helper calling `staging_root()` without
  a guard would not be detected. Candidate future designs (compare, do not build):
  - (a) Extend source-level checks to every mutating helper. Low code churn;
    failure mode is scan-pattern drift (new primitive spellings evade the list);
    needs negative tests per helper; false assurance if the list rots.
  - (b) Centralize root resolution behind a guarded mutation interface (one
    `resolve_mutation_root()` that refuses canonical production; readers keep raw
    `staging_root()`). Stronger single choke point; larger refactor touching all
    mutating callers; needs migration audit of every caller.
  - (c) Keep per-function guards as convention + mandatory scan in review
    checklists. Cheapest; weakest (relies on humans, exactly the failure mode).
- Recommendation for later: (b), with (a) as its test harness. No code changed now.

## 2. Workstream A — Tier 3 identity and token separation

- **Current evidence:** none exists. No Tier-3 code; `SeImpersonatePrivilege` /
  `SeAssignPrimaryTokenPrivilege` absent; unattended subject token path impossible;
  any launch today would run with operator rights (security-model:137-144; M026/M027).
- **Missing proof:** dedicated low-privilege account + process token read as that
  identity (M052H pattern) + denied-protected-operations table + allowed-workspace
  table + credential/lifecycle separation statement.
- **Safe boundary:** no account creation, credential issuance, privilege change, or
  process launch in any planning or test step; all evidence gathered by human
  interactive session or read-only inspection.
- **Verification criteria:** token SID read matches dedicated account; protected
  probes OS_DENIED cross-process; workspace probes ALLOWED; control token and keys
  unreadable from subject context; lifecycle actions refuse subject identity.
- **Rollback/recovery:** N/A (nothing created); if a wrong account is provisioned,
  disable it and re-prove — separate human decision.
- **Stop conditions:** any step requiring privilege escalation without explicit
  human authorization; any attempt to reuse operator rights as "equivalent".

## 3. Workstream B — Tier 2 direct verification (11-path matrix)

- **Current evidence:** 2 paths directly probed as subject
  (`var/provenance`, `human_control/security` — m005-final-verification.json) + 9
  by `icacls` inspection only; stale contradicting headers in `trust.py` /
  `trust_boundaries.ps1` / m005 doc vs closure claims. The 2-vs-9 distinction is
  load-bearing and must be preserved until new evidence exists.
- **Matrix (per path):** required subject-token context (interactive human session
  as the Tier-3 or current subject principal); expected OS-level denial verbatim
  (`Access is denied.`); expected workspace ALLOWED behavior where the path has a
  workspace counterpart; evidence capture (command, raw output, timestamp, operator);
  freshness rule (re-probe after ANY ACE change on that path or ancestors).
- **Inconclusive/inaccessible/contradictory handling:** unreadable probe target →
  INCONCLUSIVE (never PASS); operator-vs-subject context confusion → discard run;
  inspection-vs-probe conflict → probe wins, inspection demoted to stale.
- **Safe boundary:** read-only probes + workspace create/delete probes on
  disposable or designated workspace files only; no production mutation to "test".
- **Stop conditions:** probe executed as operator presented as subject evidence;
  any direct probe skipped and backfilled from inspection.

## 4. Workstream C — FILE_DELETE_CHILD

- **Exposure (verified boundaries):** repo root and private-key parent lack explicit
  `FILE_DELETE_CHILD` deny; leaf/file denies do not cover parent-granted child
  deletion; fixture-level pins pass (`test_m005_parent_directory_boundary.py`);
  subject-attempted delete NEVER measured (T-WR-3/4 NOT_MEASURED).
- **Smallest viable remediation design (not applied):** explicit `(D)` deny ACEs on
  the two parent directories for the subject principal, honoring
  `UNSAFE_DENY_TARGETS` (never Everyone/Authenticated Users/Users) and verifying
  operator manageability after application (read/write/append spot checks).
- **Test plan:** disposable replica tree proving delete-child refused + operator
  read/write retained; then, only under separate explicit authorization, production
  application with before/after `icacls` capture and immediate operator-access
  re-verification; rollback = remove added ACEs (separate authorization as well).
- **Stop conditions:** any deny targeting a broad principal; operator lockout on
  rehearsal; DACL reconstruction instead of additive ACEs.

## 5. Workstream D — staging immutability (deferred proof, hard precondition)

- **Current state:** NOTHING staged (production tree holds only 3 m016 fixtures,
  no `model/`; `STAGING_BLOCKED` = nothing created). Proof therefore cannot and
  must not be produced now.
- **Proof required when staging exists:** model/runtime digests captured before AND
  after staging under the actual subject token; ownership read (never subject) +
  write-denial checks under subject token; deny-backstop behavior on write/delete/
  replace attempts; any digest/owner/ACL/identity change → gate FAILED + void;
  anti-substitution rule (declaration names the staged path, never the source;
  post-verification substitution check before any use).
- **Failure handling:** mismatch aborts the dependent milestone; no repair-in-place;
  re-stage from sources under a new authorization.
- **Stop conditions:** digests measured once and trusted thereafter; substitution
  check skipped; proof attempted before anything is staged.

## 6. Workstream E — network enforcement

- **Declaration:** `LOCAL_ONLY_NO_FETCH` (isolation.py) — policy text only.
- **Enforcement:** NOT_ESTABLISHED / NOT_TESTABLE (staging states; no socket policy,
  no egress filter in tree). Loopback control plane exists with documented weakness
  (any local process can reach 127.0.0.1; token-file ACL is the entire boundary; no
  nonce-replay cache — accepted single-operator risk).
- **Observed evidence:** none (no subject sockets exist; proving refusal would
  require making one — never attempted, correctly).
- **Minimum proof for loopback-only:** subject-context socket inventory showing no
  listener and no non-loopback connection capability + control-plane bind audit
  (127.0.0.1, no 0.0.0.0) + token-file inaccessibility from subject context.
  Broader connectivity needs an explicit future human policy + equivalent proof.
- **Threat note:** other local processes share loopback; a subject-adjacent process
  could observe or contend the control port (no authentication beyond token + HMAC,
  no replay cache). Classify as accepted-risk-or-mitigate at policy decision time.
- **Stop conditions:** any egress attempt, firewall/socket change, or "declaration
  proves isolation" reasoning.

## 7. Birth and launch preconditions (separate lists)

**Birth-authorization proposal prerequisites:** human model + runtime declarations
attributed; digests verified (computed==declared==external); compatibility
established by real load; immutability captured; isolation posture decided (D1–D4
per human calls above); staging proof IF artifacts staged; Observatory NO_SUBJECT
baseline shown; named shutdown/recovery procedure bound; 14+16 gates evaluated live.
**Additional launch-authorization prerequisites:** everything above PLUS fresh
verbatim human launch authorization; interactive session with typed password (no
stored credential); privilege-or-session path proven; path reachability
(`launch_readiness.ready`); frozen instrument; holds lifted by name; network policy
final; Tier-3 mandate satisfied (per D1 decision). Model selection ≠ deployment ≠
birth ≠ launch — collapsing any pair is a defect in a future proposal.

## 8. Phased milestone sequence (proposed, unauthorized)

- **P1 (read-only):** re-probe Tier-2 matrix design review + F1-scan extension
  design (from §1). No privilege, no production contact.
- **P2 (disposable-only tests):** FILE_DELETE_CHILD rehearsal on replica trees;
  staging-immutability harness on disposable trees; network inventory tooling on
  lab-owned fixtures. No production, no elevation beyond current rights.
- **P3 (human interactive, explicitly authorized separately):** Tier-2 9-path
  direct probes; Tier-3 account provisioning + token proof; subject-token
  enforcement measurement (M027 instrument). Each step its own authorization.
- **P4 (governed production change, explicitly authorized separately):**
  FILE_DELETE_CHILD deny application with rollback plan; NOTHING else.
- **P5 (human decisions):** D1–D7 scoping calls on P1–P4 evidence; model/runtime
  selection files (human-authored).
- **P6+ (only after P5):** birth-authorization proposal, then launch-authorization
  proposal — each gated on all prior evidence. Per-phase stop conditions in §§2–6
  apply; any phase may end BLOCKED without failing the plan.

## 9. Human-decision checklist

- [ ] Accept M066 F1 remediation (this plan recommends acceptance).
- [ ] Extend or centralize the future-helper scan (§1a vs §1b).
- [ ] Tier 3: mandate before launch vs accepted risk + compensations.
- [ ] Tier 2: credit closure vs order fresh 9-path probes.
- [ ] FILE_DELETE_CHILD: authorize production deny application (with rollback plan) or retain.
- [ ] Staging proof timing: at-staging (recommended) vs earlier.
- [ ] Final network policy + enforcement proof scope.
- [ ] Model + runtime selection (separate human-authored files).
- [ ] Interaction model for P3 (who sits the interactive sessions, credential handling).
- [ ] Birth-authorization shape (when evidence complete). Launch-authorization shape (after birth).

## 10. Authority statement

M070 grants NO operational authority: no birth, launch, deployment, network change,
ACL change, gate movement, capability, credential, subject, or provenance mutation.
Phases P3–P4 each require their own SEPARATE explicit human authorization before
execution; this document is not that authorization. Holds remain ACTIVE; gates
remain CLOSED.
