# M071 — Read-Only Security Evidence Audit

**Status: READ-ONLY AUDIT.** No controls implemented, no probes run, no subjects
launched, no ACL/file/network/credential changes, no gate or provenance changes.
This document inventories evidence; it authorizes nothing.

**Baseline (verified 2026-10-09, read-only):** branch `master`, HEAD `c4753e2`
== `origin/master` (no divergence); worktree holds only pre-existing untracked
files (preserved); ledger 18 entries, head `PROV-000018`, chain/MAC/seal intact;
Gate 1 CLOSED (D3 scope), Gate 2 CLOSED, holds ACTIVE; subject absent; no
`runtime_selection.json`, `model_deployment.json`, or `BIRTH.json`; no launch.

## 1. Tier-2 11-path evidence matrix (authoritative source: code + closure JSONs)

Canonical set: `babylab/osboundary.py:127-169` `protected_paths()` (13 entries,
2 absent: `human_control/birth_records`, `foundation.json` — no birth, no model).
Applied deny list: `docs/evidence/m005-os-evidence-v3.json:24-36` (`deny_count:11`).
Direct-probe record: `docs/evidence/m005-final-verification.json:11-32,61`
(2 paths probed, 9 inspection-only — load-bearing distinction, preserved here).
Neither closure JSON carries its own capture timestamp (see §8 unknowns).

| # | Path (repo-relative) | Evidence type | Source | Date in source | Currency |
|---|---|---|---|---|---|
| 1 | `var/events/events.jsonl` | INSPECT (+parent-dir PROBE as mechanism) | v3:25 + final-verification:12-18 | none in file (closure 2026-09-27 per log) | STALE-BY-AGE, uncontradicted |
| 2 | `var/provenance/ledger.jsonl` | INSPECT (leaf) + PROBE (parent dir) | v3:26 + final-verification:12-18 | none | STALE-BY-AGE, uncontradicted |
| 3 | `human_control/provenance` | INSPECT | v3:27 | none | STALE-BY-AGE, uncontradicted |
| 4 | `human_control/security/keys/keyring.json` | INSPECT (+parent-dir PROBE) | v3:28 + final-verification:19-25 | none | STALE-BY-AGE, uncontradicted |
| 5 | `human_control/security/keys/private` | INSPECT | v3:29 | none | STALE-BY-AGE, uncontradicted |
| 6 | `human_control/security/control.token` | INSPECT (leaf) + PROBE (sibling-create in dir) | v3:30 + final-verification:19-25 | none | STALE-BY-AGE, uncontradicted |
| 7 | `human_control/research_records` | INSPECT | v3:31 | none | STALE-BY-AGE, uncontradicted |
| 8 | `human_control/snapshots` | INSPECT | v3:32 | none | STALE-BY-AGE, uncontradicted |
| 9 | `docs` | INSPECT | v3:33 | none | STALE-BY-AGE, uncontradicted |
| 10 | `research/experiment-log.md` | INSPECT | v3:34 | none | STALE-BY-AGE, uncontradicted |
| 11 | `.git` | INSPECT (OS deny; unenforced by app policy) | v3:35 | none | STALE-BY-AGE, uncontradicted |
| — | `baby_workspace[/temporary]` (permitted) | PROBE (ALLOWED create/read/delete) | final-verification:26-32 | none | STALE-BY-AGE, uncontradicted |

Expected behavior: protected writes OS_DENIED; workspace create/read/delete
ALLOWED (proves not deny-everything); append-only split for paths 1–2
(`osboundary.py:138-143`). Contradictory stale headers preserved as contradictions
(NOT resolved): `trust.py:17-25` "not yet active"; `trust_boundaries.ps1:6-26`
boilerplate; `m005-os-isolation.md:18-20` pre-closure NOT_IMPLEMENTED — vs closure
`VERIFIED (human-executed, cross-process)`. Fresh proof needed: per-path
subject-token OS_DENIED (+ workspace ALLOWED) with command, raw output, timestamp,
operator recorded; re-probe after ANY ACE change on a path or its ancestors.

## 2. Tier-3 identity and token separation: ABSENT (source), intended (docs)

- **Source absence (verified):** no restricted-token/job-object/AppContainer code;
  no `CreateProcessWithLogonW`/`LogonUser`/`S4U` calls (only refusal text);
  `SeImpersonatePrivilege`/`SeAssignPrimaryTokenPrivilege` never granted
  (`privileges_granted==[]` asserted); one `CreateProcessAsUser` path exists
  (`foundation/win32.py:151-237`) but requires a live subject PID + privileges it
  does not have → `NO_SUBJECT_PROCESS`; key provisioning refused by design.
- **Configured intent:** Tier model (`trust.py:193-208`), `BABY_AI_TEST` exists as
  ACL stand-in (enabled, logged on before), interactive `runas`/`Start-Process
  -Credential` the only observed genuine-token path (human-typed password).
- **Tested behavior:** harnesses return `NOT_TESTABLE` with `fallback_taken:False`;
  operator execution never accepted as subject evidence.
- **Observed OS proof:** human cross-process denials (2 paths) + workspace ALLOWED;
  live token read as `...-1022` in prior interactive sessions; subject launch
  pathways all `NOT_TESTABLE`/`UNAVAILABLE`/`BLOCKED` (no unattended mechanism).
- Launch would execute as: privileged-duplication path (needs absent privileges),
  interactive logon (needs human session), or — if misconfigured — operator rights
  (the risk Tier 3 exists to close).

## 3. FILE_DELETE_CHILD: exposure confirmed, remediation unapplied

- **Exposure:** repo root grants `Authenticated Users:(M)`; `BABY_AI_TEST` holds it
  (enabled + logged on → DERIVED Modify over root and non-overriding subdirs);
  root/private-key-parent `FILE_DELETE_CHILD` has no explicit deny
  (security-model:252-259; architecture:299-303; README:257-262;
  m005-final-verification.json:64-65). Basis: ACL inspection + NTFS inference +
  pre-fix direct subject-token WRITE SUCCEEDED ×2 (failures preserved in evidence).
- **Fixture pins prove:** ACE text shape, trustee/rights/inheritance, verifier
  tamper-flips, `UNSAFE_DENY_TARGETS` never denied (per-SID-only remediation
  required so the operator is not locked out). They do NOT prove production
  enforcement (operator ALLOWED proves nothing; enforcement NOT_TESTABLE until a
  real subject attempt with token read).
- **Narrowest candidate remediation (PROPOSAL, not applied):** per-SID
  `BABY_AI_TEST:(D)` denies on the two parents + operator-access re-verification.
  Risks: lockout on error; DACL-reconstruction temptation (forbidden — additive
  ACEs only). Minimum evidence + authorization before any future ACL mutation:
  disposable rehearsal + before/after `icacls` capture + separate explicit human
  authorization with rollback plan.

## 4. Staging immutability: design proposed, proof not yet possible

- **Design (§7 checks + tamper table):** digests after staging, declaration names
  staged path, subject `RX/R` + deny backstop, owner never subject,
  `MODEL_SHA256_BEFORE==AFTER`, mismatch → FAILED + void, copy-not-move.
- **Disposable results:** tamper flips all `BLOCKED`; ownership/Get-Acl pins;
  `compare_immutability` synthetic flips; `deploy_artifact` hash-equality on
  scratch; empty-tree inventory expectations.
- **Production observations:** tree EMPTY (only 3 m016 fixtures, no `model/`);
  `STAGING_BLOCKED` = nothing created; no subject-token before/after run exists;
  M015 enforcement explicitly `NOT_TESTABLE`/`ACL_OBSERVATION_ONLY`.
- **M066 residual gap: CONFIRMED UNIMPLEMENTED.** The source-scan test iterates
  only `deploy_artifact`/`recover`; a future mutating helper using
  `staging_root()` without a guard would NOT be detected. Not repaired in M071
  (out of read-only scope by instruction). Candidates recorded in M070 §1.

## 5. Network: declared intent, no enforcement, no subject to test

- **Declared:** `LOCAL_ONLY_NO_FETCH` (isolation.py) + M014 requirement + M064 D7
  `NO NETWORK / LOOPBACK-ONLY PENDING EXPLICIT FINAL POLICY`.
- **Implemented:** no firewall/egress/socket policy in tree; loopback control plane
  (127.0.0.1 bind, HMAC auth, no replay cache — documented single-operator risk);
  structural AST import scans (not OS blocking); `llama-server --model-url` fetch
  capability OBSERVED in binary (staging explicitly does not fix it).
- **Observed:** `outbound_attempted:False` is non-attempt, never a refusal proof; no
  subject-socket inventory exists (no subject exists).
- **Authorized:** nothing (M064 withholds; M070 grants nothing).
- Minimum loopback-only proof (missing): subject-context socket inventory + bind
  audit (no 0.0.0.0) + token-file inaccessibility from subject context.

## 6. Model/runtime, birth, launch preconditions (unchanged, restated)

- No `runtime_selection.json`, `model_deployment.json`, `BIRTH.json`, subject
  identity, staged model, or launch authorization exists (verified absent).
- Strict loaders refuse absence/inference/substitution (verified pattern, not
  re-executed here). Birth gates BLOCKED (no declaration); launch BLOCKED/
  NOT_TESTABLE (holds active; privileges absent; no session).
- Birth prerequisites: declarations + verified digests + compatibility + isolation
  posture + staging proof (when applicable) + Observatory baseline + shutdown
  procedure. Launch adds: fresh verbatim authorization + interactive session +
  reachability + frozen instrument + holds lifted + final network policy.

## 7. Dependency register (abridged; full rationale in M070 §§2–6)

Tier-2 fresh probes depend on: interactive human session (+ Tier-3 account for
subject-token validity) → then birth/launch proposals may cite them. Tier-3
account precedes any subject-token measurement. FILE_DELETE_CHILD production fix
depends on: disposable rehearsal + explicit authorization + rollback plan.
Staging proof depends on: artifacts existing to stage (none do). Network proof
depends on: subject context existing. Birth-auth proposal depends on: all of the
above decided/evidenced. Launch-auth proposal depends on: birth + fresh words.
Read-only work may continue freely; disposable testing needs its own milestone;
production/privileged work needs explicit separate authorization. Stop on: any
required mutation, missing authorization, or irresolvable evidence conflict.

## 8. Unknowns and contradictions (preserved, not smoothed)

- Closure JSONs carry no capture timestamps (only era dating via logs).
- Leaf-vs-directory probe granularity (probed strings ≠ ledger identifiers).
- Stale headers vs closure claims (§1 list).
- `eol:lf` attribute vs observed CRLF expansion (M061-quantified, mechanism secondary).
- Whether 9 inspection-only paths match their inspected text today (no re-probe).

## 9. Authority statement

M071 grants NO operational authority. No birth, launch, deployment, network, ACL,
gate, capability, credential, subject, or provenance change. Holds ACTIVE; gates
CLOSED. Next step is human review, never automatic implementation.
