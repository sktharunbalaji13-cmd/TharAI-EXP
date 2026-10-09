# M085 — Human-Operated Auth-1 Execution Handoff (Runbook)

**Status: HANDOFF DOCUMENT ONLY.** No Auth-1 operation executed here, no account
created, no secret handled, no state changed. A human performs the work below in
a suitable elevated interactive session; a later milestone independently reviews
the returned evidence. This runbook grants nothing beyond Auth-1 `M077-AUTH1-001`
as already signed and sealed (`PROV-000019`).

**Baseline (verified 2026-10-09, read-only):** branch `master`, HEAD `51feb7b`
== `origin/master`; Auth-1 digest recomputed EXACT (`ed992f56…c1234`, 6 scope
rows, 10 forbiddens); signed policy `39b40642…` + seal `PROV-000020` intact;
ledger 20 entries intact; Gate 1 CLOSED, Gate 2 CLOSED; `babyai-subject` absent;
no subject/birth/launch/model/runtime.

## 1. Purpose and scope (from Auth-1 record bytes, not paraphrase)

Auth-1 `M077-AUTH1-001` (HUMAN 130307) authorizes exactly: (1) create local
standard-user account `babyai-subject`; (2) verify group baseline read-only;
(3) workspace reachability checks (disposable scratch only); (4) token
readability check (interactive session); (5) record evidence; (6) refuse
fallbacks and non-conforming states. Forbidden: Tier-2 probes, broad/unlisted
ACL changes, network changes, model/runtime selection/deployment, subject
credentials, birth, launch, gate movement, hold removal, anything unlisted.
One-shot declared. Account creation ≠ isolation proof. Auth-1 execution ≠
Auth-2 authorization. Signed policy ≠ execution permission.

## 2. Preflight (all mandatory, in order)

1. Elevated interactive Windows session under human control (verify: whoami +
   Administrator role read, read-only).
2. Approved credential-entry path: human types the secret at an OS dialog only.
3. Re-verify Auth-1 digest (`ed992f56…`), scope, forbiddens, MAC/chain/seal.
4. Confirm `babyai-subject` absent (`net user babyai-subject` → not found).
5. Confirm operator recovery access baseline (own groups/privileges read).
6. Confirm no Tier-2/auth-2/birth/launch work will occur in this session.

## 3. Execution reference (no dedicated Auth-1 setup script exists in-repo)

There is NO repository implementation of Auth-1 setup to invoke; the human
performs OS-native steps within the authorized scope. Established patterns
cited (not invented): account creation per the `New-LocalUser -Name ...`
prerequisite pattern documented in `m005-os-isolation.md:287` (adapted: name
`babyai-subject`, standard user, NO administrator membership, human-typed
credential at OS dialog — never `/savecred`, never stored); read-only
verification via `net user`, `whoami /user`, `whoami /groups`, `whoami /priv`,
`Get-LocalGroupMember` (all read-only, all established in probe evidence);
workspace checks on disposable scratch files only; token read per M076 §3.
Any step lacking precedent stops: do not improvise syntax.

## 4. Credential handling

Human enters the secret directly at the OS-provided dialog. It must never
appear in chat, prompts, command lines, scripts, logs, commits, evidence files,
or provenance records. This runbook contains no secret and requests none.

## 5. Post-setup verification (observed values only)

Account name, OS-assigned SID (compare ≠ operator `...-1001`, ≠ `...-1022`);
group list (Users-minimum, no Administrators); privilege list (no SeImpersonate/
SeAssignPrimaryToken/SeTcb); token readability + SID match (else NOT VERIFIED,
never PASS-by-existence); in-scope workspace checks; refusal behavior where
triggered. Unexpected membership/privileges → stop, no in-band correction.

## 6. Evidence capture (non-secret only)

Date/time, digests verified, elevation + mechanism confirmation, pre-absence
proof, per-operation outcomes, observed name/SID/groups/privileges, token status,
workspace status, anomalies/partials, evidence locations, final result
(PASS/FAIL/BLOCKED/INCONCLUSIVE). Template fields enumerated in §8. Passwords,
reusable credentials, and sensitive token material must never be captured.

## 7. Stop conditions

Elevation unavailable; dialog unavailable; digest/scope/MAC/chain/seal mismatch;
account unexpectedly present; unexpected privileges; unexpected ACL changes;
partial setup; inconclusive verification. Stop → preserve evidence → report for
separately authorized recovery. No improvised rollback (broad DACL work needs its
own authorization).

## 8. Human execution record template (blank; to be completed locally)

- EXECUTION_DATETIME:
- AUTH1_DIGEST_VERIFIED: (must read `ed992f56…c1234`)
- ELEVATED_SESSION_CONFIRMED: / MECHANISM:
- ACCOUNT_ABSENT_BEFORE: (attach `net user` not-found output)
- OP1_CREATE_ACCOUNT: result / observed SID:
- OP2_GROUP_BASELINE: result / observed groups:
- OP3_WORKSPACE_CHECKS: result / scratch paths:
- OP4_TOKEN_READABILITY: result / token SID or NOT VERIFIED:
- OP5_EVIDENCE_RECORDED: locations:
- OP6_FALLBACK_REFUSALS: triggered?:
- UNEXPECTED_CHANGES_OR_PARTIAL:
- FINAL_RESULT: PASS / FAIL / BLOCKED / INCONCLUSIVE

## 9. Explicit exclusions (restated; violation voids the run)

Tier-2 probes (all 11 paths); network/firewall/socket changes; model/runtime
selection/deployment; subject record/`BIRTH.json`; launch or interactive
developmental sessions; holds lift; Gate 1/Gate 2 movement; subject credentials
or capabilities; anything outside the six Auth-1 rows.

## 10. Authority statement

This runbook executes nothing and authorizes nothing beyond restating signed
Auth-1. Human execution remains pending. Later independent review of the
returned evidence is mandatory before any downstream use. Holds ACTIVE; gates
CLOSED.
