# M074 — Tier-3 Isolation Design & Proof Plan

**Status: DESIGN / TEST-PLANNING ONLY.** No account provisioned, no credential
issued, no privilege altered, no subject launched, no probe executed, no ACL/file/
network change, no gate moved, no provenance appended. This document designs work;
it authorizes nothing.

**Baseline (verified 2026-10-09, read-only):** branch `master`, HEAD `9bfccd7`
== `origin/master`; clean tracked tree; ledger 18 entries, head `PROV-000018`,
chain/MAC/seal intact; Gate 1 CLOSED (D3), Gate 2 CLOSED, holds ACTIVE; no subject,
birth, launch, model/runtime selection, or credentials.

## 1. Execution-pathway inventory (from source, current tree)

| # | Entry point / caller | Mechanism | Identity today | Privileges needed | Mode | Operator-fallback risk | Isolation bypass? | Refuse conditions |
|---|---|---|---|---|---|---|---|---|
| 1 | `restricted.launch_as_subject` → `win32.create_process_as_user` | `DuplicateTokenEx` + `CreateProcessAsUserW` from live PID | subject IFF live subject PID exists | `SeImpersonate`/`SeAssignPrimaryToken` (absent) | unavailable | none (returns `NO_SUBJECT_PROCESS`) | no | missing privilege or no live PID |
| 2 | `subject_process` MECHANISMS table (M016 ledger) | `CreateProcessWithLogonW` / dup-token / `schtasks` / service / `runas` / `Start-Process` / WSL | subject only via interactive logon rows; service/container rows are wrong-identity by design | varies; impersonation rows refused | interactive-only or blocked | `schtasks`/service rejected by design; WSL rejected (wrong principal) | no | absent privilege, non-elevation, stored-credential prohibition |
| 3 | `subject_launch.build_launch_command` + `launch_readiness` | command construction + readiness probe (never executes) | unresolved (`ready:False`; interpreter unreachable) | N/A (builds only) | N/A | none (executes nothing) | no | `ready:False` always at present |
| 4 | `host_readiness` candidates + `HUMAN_LAUNCH_COMMAND` | `Start-Process -Credential` (human-typed password) | genuine subject token, human-established | none for lab (human session) | interactive human session | lab never sees/stores credential | no | any stored-credential or unattended variant |
| 5 | `boundary_test.runas_command` + `scripts/subject_boundary_probe.py` | interactive `runas.exe` (`/savecred` omitted) | genuine subject token (prior observed success) | none for lab | interactive human session | none | no | automation attempt |
| 6 | Measurement-only (`process_identity`, `token_observation`, `observe_process`) | caller-identity capture | reports caller (today: operator) | none | read-only | never inferred as subject (explicit `NOT_ESTABLISHED` + Win32 error) | no | cross-account read without rights |

No pathway can silently run as the subject today; every unattended route is
`NOT_TESTABLE`/`BLOCKED`/`UNAVAILABLE` with `fallback_taken:False`. A documented
account (`BABY_AI_TEST`, SID `...-1022`) is an ACL stand-in, NOT proof of a
restricted process token — that confusion is explicitly refused throughout.

## 2. Tier-3 security contract (future identity must satisfy ALL)

1. Dedicated low-privilege identity, distinct from the operator (new or repurposed
   account ONLY via explicit human provisioning; never the operator account).
2. Explicit process-token + SID verification at execution time (live token read,
   compared to intended SID; `boundary_meaningful` pattern).
3. Refusal on any token mismatch (observed ≠ intended → refuse before execution).
4. No implicit operator fallback (operator execution never accepted as subject
   evidence; no stored credentials; no `/savecred`; no service-identity substitution).
5. Subject execution separated from human/lab lifecycle control (control plane,
   keys, and lifecycle transitions stay outside subject reach).
6. No subject credential issuance, authorization-policy modification, or
   self-provisioning (key custody refuses; no registration path).
7. Defined workspace with least privilege (subject workspace writable; protected
   paths denied; append-only streams preserved).
8. Pause/shutdown/recovery/evidence-capture independent of subject cooperation
   (lab-driven terminate; snapshots; branch-not-rewind restore).
9. Fail-closed on missing privilege, unavailable identity, malformed config, or
   token-verification failure (UNKNOWN/absence never PASS).
10. Auditable binding of every result to exact identity, process, target,
    operation, and environment (feeds M073 `ProbeRecord` fields).

Filesystem permissions, process isolation, network isolation, and governance
authorization stay distinct controls. Tier 3 alone resolves NONE of the network/
loopback exposure (stated here so it is never claimed later).

## 3. Implementation options (compared, none selected)

**Option A — dedicated account + explicit token verification (RECOMMENDED as
narrowest sufficient):** OS enforcement = account ACL boundary + live token reads.
Provisioning = human-created local account (elevated session once) + password
discipline (interactive only). Compatible with pathways 4–5 (the only observed
genuine-token routes). Credential handling = human-typed, never stored.
Lockout/recovery risk = LOW for lab (new account, not operator's); operator
lockout only if broad denies used — forbidden by `UNSAFE_DENY_TARGETS`.
Disposable tests: token-read harness on fixtures; allow/deny matrix under the new
account on replica trees. Acceptance evidence: live token SID match + protected
denials + workspace allows, all cross-process observed. Limits: file boundary
only (no restricted token/job object); does not constrain in-memory process
behavior; needs Tier-2 re-probe to mean anything.
**Option B — restricted token / job object / AppContainer:** stronger
OS-enforced containment; requires custom native code + elevated setup + careful
allow-listing (risk of breaking legitimate reads); credential story harder
(token must be minted, not typed); lockout risk higher; disposable tests need
fixture processes under restriction. Evidence bar HIGHER than A with unclear
marginal gain for file-ACL enforcement. Evaluate separately AFTER A works.
**Option C — staged (A now, B later):** A establishes identity separation and
unblocks Tier-2 probes; B evaluated on measured need. Recommended sequencing,
not a weaker standard: B's acceptance criteria stay written down now.

## 4. Verification plan (disposable-only; binds to M073 contract)

Sequence (each step refuses closed on failure; order is dependency order):
V1 token-identity read on fixture process → M073 `token_sid` + `token_verified`
fields (negative: wrong-SID fixture refused). V2 non-operator proof (token ≠
operator SID; `runas`-equivalent provenance of identity). V3 protected-operation
denials on replica tree (mirrors Tier-2 matrix shape; expected `OS_DENIED`).
V4 workspace allows on replica (proves not deny-everything; M073 workspace
control). V5 no self-authorization (attempt mint/register/transition as subject
context → refused; key custody intact). V6 lifecycle-external check (pause/
terminate paths lab-only; subject interface has no such call). V7 mismatch
injection (wrong token, missing account, malformed config → refusal before any
probe body). V8 evidence capture (timestamps, method, raw output, reviewer) mapped
1:1 onto `ProbeRecord`; non-permission errors recorded INCONCLUSIVE, never PASS.
No step touches production, ACLs, privileges, or live accounts; no step launches
a subject (fixture processes are lab-owned throwaways asserting plumbing, and any
step needing a real subject token stops with NOT READY).

## 5. Dependency and authorization map

Human review of M072/M073 → approve Tier-3 scope (this design is input, not
approval) → separately authorized identity/token implementation → disposable
verification (V1–V8) → human review of Tier-3 proof → separately authorized
Tier-2 probe sessions → evidence review → birth/launch proposals (each gated on
all prior evidence + D-decisions + selections). Readiness ≠ implementation ≠
evidence ≠ acceptance ≠ authorization — five distinct states tracked per item.

## 6. Residual risks (kept open)

Tier-2 staleness + leaf-vs-directory granularity; FILE_DELETE_CHILD exposure;
staging proof pending artifacts; network/loopback unenforced; model/runtime
unselected; M066/M072 analyzer maintenance burden; any launch path defaulting to
operator rights (the risk Tier 3 exists to close). Tier 3 addresses identity
separation ONLY; each other risk needs its own work.

## 7. Human decisions required

Endorse M072 closure; approve Tier-3 scope (A now, B later, or alternative);
provision the account (elevated human act); approve each interactive probe
session; decide D2/D3/network/model/runtime/birth/launch per M069/M071 registers.
No decision is inferred here.

## 8. Authority statement

M074 implements nothing and authorizes nothing: no Tier-3 code, account,
credential, privilege, probe, ACL, network, model/runtime, subject, birth,
launch, gate, or provenance change. Holds ACTIVE; gates CLOSED.
