# M075 — Tier-3 Implementation Preflight & Authorization Scope

**Status: PREFLIGHT / PLANNING ONLY.** No account provisioned, no credential
issued, no privilege altered, no subject launched, no probe executed, no ACL/
file/network change, no gate moved, no provenance appended. This package prepares
a future separately-authorized implementation milestone; it authorizes nothing.

**Baseline (verified 2026-10-09, read-only):** branch `master`, HEAD `041bada`
== `origin/master`; clean tracked tree; ledger 18 entries, head `PROV-000018`,
chain/MAC/seal intact; Gate 1 CLOSED (D3), Gate 2 CLOSED, holds ACTIVE; no subject,
birth, launch, model/runtime selection, or credentials.

## 1. Implementation surface (smallest change set; read-only inventory)

| File / function | Current behavior | Proposed change | Why necessary | Security property | Test needed | Regression risk | Needs elevation/account/session? | Production impact |
|---|---|---|---|---|---|---|---|---|
| `foundation/win32.py` `create_process_as_user` (exists) | Duplicates token from live PID; returns `NO_SUBJECT_PROCESS` absent PID/privilege | None (reuse as-is) | Already the correct primitive | No minting; needs existing process | Existing refusal tests | None (unchanged) | No (already exists) | None |
| `foundation/restricted.py` `launch_as_subject` (exists) | Returns `NOT_TESTABLE`, `fallback_taken:False` | None (reuse as-is) | Gate already fail-closed | No fallback ever | Existing tests | None | No | None |
| `foundation/host_readiness.py` candidate table (exists) | Enumerates mechanisms incl. human `Start-Process -Credential` | None | Already distinguishes viable vs refused rows | Human-only viable path documented | Existing tests | None | No | None |
| `babylab/osboundary.py` protected/workspace lists (exist) | 13 canonical paths; `UNSAFE_DENY_TARGETS` guard | None (reference only) | Deny-target safety already pinned | Broad-deny lockout prevented | Existing pins | None | No | None |
| NEW thin verifier (proposed, not created) | N/A (absent) | Token-read + SID-compare + workspace allow/deny matrix runner on replica trees | Bind M073 `ProbeRecord.token_sid/token_verified` to live reads | Denial observed under proven identity or INCONCLUSIVE | New disposable tests (V1–V8) | Must not duplicate `observe_process`; reuse it | No elevation; needs the provisioned account present (separate auth) | None (replica trees only) |
| `docs` runbook for interactive sessions (proposed, not created) | N/A | Human-executable probe script + evidence form | Reproducible cross-process evidence | Human-typed credential, never stored | Dry-run parsing test (no execution) | None | Interactive session (separate auth) | None |

No existing implementation file needs modification for option A. If implementation
reveals otherwise, that finding itself is a stop-and-report event.

## 2. Account and privilege preflight

- **Account type:** dedicated local low-privilege account, distinct from operator
  and from `BABY_AI_TEST` (which remains the ACL stand-in for Tier-2 paths).
  Name/SID/password: **UNRESOLVED — HUMAN CHOICE REQUIRED** (nothing invented here).
- **Required:** enabled, non-administrative, Medium integrity or lower; member of
  Users (or equivalent least-privilege baseline) and NOTHING else.
- **Forbidden:** Administrators, Backup/Restore/TakeOwnership/Debug/Security
  operator rights; `SeImpersonatePrivilege`, `SeAssignPrimaryTokenPrivilege`,
  `SeTcbPrivilege` for the lab's own token (evidence shows all absent:
  `m005-capability-probe.json`, `whoami /priv` ERROR 1300 pattern).
- **Workspace permissions:** subject workspace create/read/delete allowed;
  protected paths denied per existing Tier-2 ACEs (verified, not re-applied);
  append-only streams preserved.
- **Separation:** account used ONLY for subject-token evidence; lifecycle control,
  keys, seals, and control token stay operator-only; no shared credential.
- **Token verification:** live `OpenProcessToken` read at probe time, SID compared
  to provisioned account SID; mismatch → refuse before any probe body.
- **No-fallback:** operator execution never accepted as subject evidence
  (established pattern); stored credentials, `/savecred`, service-identity
  substitution, and WSL/container substitution all refused.
- **Lockout avoidance:** deny ACEs per-SID only (`UNSAFE_DENY_TARGETS` honored);
  operator manageability re-verified after every change; rollback = remove added
  ACEs (separately authorized).
- **Pre-creation checks:** name/SID uniqueness, group baseline recorded, workspace
  reachability from operator context, rollback plan written.
- **Post-creation checks:** account enabled + non-admin confirmed; token readable
  in interactive session; zero protected-path writes possible (spot probe);
  operator access unchanged.

## 3. Token-verification design

Read token → extract user SID → compare to provisioned SID → compare integrity
level expectations → record method + raw output + timestamp into M073
`token_sid`/`token_verified`/capture fields. Any step unreadable → INCONCLUSIVE,
never PASS. Verification precedes every probe body; a cached earlier verification
never substitutes for a fresh one (staleness rule).

## 4. Disposable verification procedure (V1–V8 mapped to preconditions)

Each step lists preconditions → fixture → observation → PASS/FAIL/INCONCLUSIVE →
evidence fields → cleanup → stop conditions. V1 token read (needs: interactive
session + provisioned account; fixture: lab-owned throwaway process; refuse if
absent). V2 non-operator proof (compare SIDs; refuse on match-with-operator).
V3 replica-tree denials (disposable tree mirroring protected shapes; expected
`OS_DENIED`). V4 replica allows (proves not deny-everything). V5 no-self-auth
(attempt mint/register/transition in subject context → refused; key custody
intact). V6 lifecycle-external (pause/terminate lab-only; subject interface has
no such call). V7 mismatch injection (wrong token/absent account/malformed
config → refusal pre-body). V8 evidence capture (timestamps/method/raw/reviewer
mapped 1:1 to `ProbeRecord`; non-permission errors INCONCLUSIVE). Steps needing
no account (V5-partial, V6-static, V8-format) are separable from genuine-token
steps (V1–V4, V7); the procedure refuses genuine-token steps when the account
is absent. No production paths as fixtures, ever.

## 5. Recovery and rollback plan

Reversible: removing added deny ACEs; disabling (never deleting-audited) a wrong
account; discarding replica trees. Side-effecting: any production ACL touch
(requires its own authorization + before/after capture + operator re-verify).
Rollback itself needs separate authorization when it touches production or
identities. Interrupted setup: stop, preserve evidence, report exact state; no
improvised cleanup of unknown ACL state (escalate to human).

## 6. Proposed authorization manifest (PROPOSAL ONLY — not signed, not sealed)

**Authorization 1 — identity setup (if approved):** provision ONE named
low-privilege account (name/SID filled by human at signing); no privilege grants;
no other account changes; workspace reachability checks (read-only); rollback =
disable account + remove added ACEs. Explicitly forbidden: broad-deny targets,
service creation, password storage, any production ACL beyond the two deny scopes
with before/after evidence.
**Authorization 2 — Tier-2 probe sessions (separate, later):** per-path interactive
sessions under the M073 contract; evidence review before use; no scope creep into
birth/launch/network/deployment. **Common forbiddens:** operator-rights execution
as evidence; `/savecred`; unattended credential use; Gate-1/2 movement; model/
runtime/birth/launch/network/capability/provenance changes. Manifest existence
grants NOTHING; each authorization needs its own explicit human signature.

## 7. Implementation readiness: READY FOR HUMAN AUTHORIZATION

The repository needs no code change before a human decides: primitives
(token-dup path, readiness tables, interactive probe scripts, contract module)
exist and refuse safely today. What is missing is entirely human-side: account
name/SID/password discipline, interactive sessions, and per-step signatures.
Withholding approval blocks: everything downstream (probes → evidence → birth/
launch proposals). Approval of THIS document authorizes nothing beyond planning.

## 8. Authority statement

M075 provisions no identity, changes no privilege, authorizes no probe, and
establishes no launch readiness. No account/credential/privilege/ACL/network/
model/runtime/subject/birth/launch/gate/provenance change occurred or is granted.
