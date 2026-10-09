# M073 — Tier-2 Re-Probe Readiness & Safe Evidence Harness

**Status: READINESS + HARNESS ONLY.** No probes run, no subjects impersonated,
no production contact beyond read-only verification, no ACL/identity/network
changes, no gates moved, no provenance appended. This document + the contract
module + its tests are the milestone outputs.

**Baseline (verified 2026-10-09, read-only):** branch `master`, HEAD `3d62a0e`
== `origin/master`; clean tracked tree; ledger 18 entries, head `PROV-000018`,
chain/MAC/seal intact; Gate 1 CLOSED (D3), Gate 2 CLOSED, holds ACTIVE; no
subject, birth, launch, model/runtime selection, or credentials.

## 1. Canonical Tier-2 matrix (authoritative source: `osboundary.protected_paths`)

13 canonical ids; 11 existing (2 absent: `birth_records`, `protected_configuration`
— no birth has occurred, no model configured). Per-path prior evidence
(M071 audit, preserved here): paths `var/provenance` and `human_control/security`
carry directory-scoped direct probes (highest-risk pair, human cross-process,
2026-09-27 era); the other 9 rest on `icacls` inspection only. Neither closure
JSON carries capture timestamps (era-dated via logs). The 2-vs-9 distinction is
load-bearing: directory mechanism ≠ leaf proof, and inspection ≠ denial test.

## 2. Historical evidence classification (unchanged from M071, restated)

Direct subject-token probe: 2 directories + 1 workspace ALLOWED control.
ACL inspection: 11/11 `deny_ace_present` (+ operator-write retained).
Source inference: append-only split, UNSAFE_DENY_TARGETS constraint, NTFS
parent/child semantics. Unknown: per-path current match to inspected text
(no re-probe exists); exact capture instants. Contradictions preserved:
stale `trust.py` / `trust_boundaries.ps1` / m005-doc headers vs closure claims.

## 3. Direct-probe evidence contract (`tests/m073_probe.py`)

Frozen `ProbeRecord`: probe/path ids, exact target + operation, token SID +
verified flag, start/end timestamps, capture method, expected vs observed OS
result, workspace-control result + requirement flag, ACL-evidence time, failure
detail, evidence refs, reviewer disposition, result. Classifier (pure):
PASS only on observed denial + verified token + complete evidence (+ passing
workspace control where required); unexpected access FAIL; non-permission
outcomes INCONCLUSIVE (never denial proof); unverified token / target mismatch /
failed control / missing timestamps INCONCLUSIVE-or-refused. Evidence log is an
append-only frozen tuple (no overwrite, path-scoped queries).

## 4. Safe runner design (fail-closed by absence of machinery)

`attempt_probe()` runs gates in order — allowlisted-target match, token
verification + SID match, evidence completeness, explicit authorization — then
refuses unconditionally (`NOT READY: no authorized subject-token mechanism;
Tier-3 absent`). There is deliberately NO execution branch: no subprocess,
impersonation, token acquisition, ACL, or network code exists in the module
(source-scan tested). Adding real observation requires a future explicitly
authorized milestone with token separation — never a flag flip here. Refuses
arbitrary paths, unexpected identities, missing evidence/auth; stops on mismatch;
grants the subject nothing; never touches production targets or contents.

## 5. Disposable validation (13/13 green, no production contact)

Contract classifications proven on synthetic records: PASS-only-on-denial;
unexpected-access FAIL; 4 non-permission outcomes INCONCLUSIVE; token
mismatch/unverified refused + INCONCLUSIVE; missing/mismatched/cross-path
targets refused; workspace failure INCONCLUSIVE; missing timestamps refused +
INCONCLUSIVE; append-only retention + path scoping; authorization-missing and
no-mechanism refusals distinct. Canonical ids verified equal to
`protected_paths()` names. Reporting proven state-neutral (watched hashes +
ledger count identical). No elevated privileges needed; nothing to clean up.

## 6. Per-path readiness (all 11 existing paths)

Every existing path: **BLOCKED BY IDENTITY/TOKEN PREREQUISITE** (no subject-token
mechanism exists, so no direct probe can run; harness logic itself is READY as
proven by §5). The 2 previously probed directories are NOT re-labeled leaf proof.
Absent paths (`birth_records`, `protected_configuration`): NOT YET ASSESSED
(nothing to probe until they exist).

## 7. Dependency chain

Tier-3 account + token mechanism → subject-token validity for any probe →
per-path direct probes (11, each separately authorized) → evidence review
(classify + reviewer disposition) → governance use (birth/launch proposals may
cite) . Tier-2 matrix completion is evidence-gathering, not closure: closure
itself remains a human decision on reviewed evidence. Read-only analysis may
continue freely; disposable harness work needs its own milestone; any
production/privileged step needs explicit separate authorization. Stop on:
missing authorization, unverifiable token, target ambiguity, or any step that
would mutate production, ACLs, identities, or credentials.

## 8. Human decisions required (questions + consequences)

- Endorse M072 gap closure (else the prevention gap stays under review).
- Mandate Tier 3 before launch, or record accepted risk (launch-as-operator
  voids Tier-2 meaning — consequence stated, choice is the human's).
- Approve the Tier-2 re-probe plan (11 probes, interactive sessions, evidence
  rules above) or scope it down explicitly (consequence: unprobed paths stay
  inspection-only).
- Authorize each interactive/probe session and any elevated setup separately
  (consequence of bundling: unauditable blanket permission — refused by design).
- Final network policy; model/runtime selection; birth then launch authorizations
  (each gated on prior evidence; none granted here).

## 9. Next-step recommendation (ordered, none automatic)

1. Human review of this package + M072 endorsement (decision, not code).
2. Tier-3 provisioning decision → if mandated, its own authorized milestone.
3. Per-path authorized probe sessions under the contract (P3-style), each
   separately authorized, evidence-reviewed before use.
4. Remaining D-decisions (FILE_DELETE_CHILD production fix with rollback plan;
   staging proof at staging time; final network policy + proof).
5. Birth-authorization proposal only on complete evidence; launch only after
   birth + fresh verbatim words.

## 10. Authority statement

M073 establishes no Tier-2 closure, authorizes no probes, and grants no authority
for production changes, identity provisioning, networking, model/runtime
deployment, birth, launch, or gate movement. Harness readiness ≠ security closure.
