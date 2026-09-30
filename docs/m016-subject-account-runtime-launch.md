# M016 — Subject-Account Native Runtime Launch and Boundary Proof

Status: **`SUBJECT_PROCESS_NOT_TESTABLE`**

Nothing was launched as `BABY_AI_TEST`. No runtime was selected or staged. This is
the milestone's honest answer, and the section "Why" below records it in full.

## The question this milestone asked

> Can an explicitly human-selected native runtime execute as `BABY_AI_TEST`, while
> the operating system prevents that process from modifying the staged
> runtime/model/config and existing protected evidence?

**Answer on this host: not testable with the current operator token.** The
mechanism that would work is blocked by a privilege the operator does not hold,
and every alternative either requires a stored credential or an interactive
prompt. Neither was substituted for proof.

## Why

### The token

The operator token was read directly, not assumed:

| Fact | Value |
|---|---|
| Privileges held | 5 (`SeChangeNotifyPrivilege`, `SeIncreaseWorkingSetPrivilege`, `SeShutdownPrivilege`, `SeTimeZonePrivilege`, `SeUndockPrivilege`) |
| `SeImpersonatePrivilege` | **absent** |
| `SeAssignPrimaryTokenPrivilege` | **absent** |
| Elevated | no — `BUILTIN\Administrators` is present but marked *deny only* |

Elevation was read from the group attributes rather than from the presence of an
`Administrators` entry, because an unelevated token carries that group as deny-only
and its presence proves nothing.

### Mechanisms investigated

| Mechanism | Requirement | Outcome |
|---|---|---|
| `CreateProcessWithLogonW` | `SeImpersonatePrivilege` | **unavailable** — privilege absent. This is the mechanism that would otherwise satisfy the milestone, because it needs no stored password. |
| `CreateProcessAsUser` / `DuplicateTokenEx` | `SeAssignPrimaryTokenPrivilege` or a duplicated token | **unavailable** — privilege absent, no token to reuse. |
| Scheduled task (`schtasks /create /ru BABY_AI_TEST`) | stored credentials, or an interactive prompt | **blocked** — attempted, refused: `Access is denied` for this non-elevated operator. Supplying `/RP` would persist the password, which the milestone forbids. |
| Windows service (`sc.exe create`) | stored service credentials + elevation to install | **rejected by design** — a service runs as its own identity, not an interactive user, and needs the password stored. |
| `runas.exe` | interactive GUI credential prompt | **interactive only** — binary present, but cannot be driven non-interactively, so an automated run cannot confirm it. |
| `Start-Process -Credential` | a `SecureString` at the call site | **interactive only** — same constraint. |
| WSL / `docker exec` | a Linux or container identity | **rejected by design** — these produce a different identity and would answer a different question. |

`automatable_mechanisms_remaining` is empty. That is the finding, not a gap in
the search.

### Credentials

No password was requested, supplied, stored, or logged. The account's
`PasswordRequired=False` is recorded as a host fact — it means an empty password
would satisfy logon — and was deliberately **not** exploited and **not** changed.
`Get-LocalUser` metadata only; the password value is never read.

## The native probe

A native C# probe was built and verified. It is **not** staged in
`subject_runtime`, and CPython was not staged as a subject runtime.

It compiles with the C# compiler already present in PowerShell 5.1 via
`Add-Type`; no toolchain was installed.

### Identity it reports, and how

All read from the running process token via `OpenProcessToken` and
`GetTokenInformation` — never from arguments or configuration:

- `user_sid`, `account_name`
- `integrity_level`, decoded from the mandatory label
- `groups`, and `privileges` / `privilege_count` from the token's LUID array

Its cross-check against `whoami /priv` agrees on all five held privileges, which
is what makes it trustworthy for the subject run when that becomes possible.

### Filesystem outcomes

Four outcomes, never conflated: `OS_ALLOWED`, `OS_DENIED`, `PATH_ERROR`,
`NOT_TESTABLE`. `OS_DENIED` means winerror 5 and nothing else.

Operations covered: create file, modify staged executable, append, delete,
rename, replace, create child executable beside the runtime, create/delete child
directory, modify ACL, and workspace write/read/delete.

### Four defects found while building it

The probe was run against the **operator** — who holds `(F)` on
`subject_runtime` — as a positive control. Anything other than `OS_ALLOWED` there
would be a probe bug. It found four:

1. **`LookupPrivilegeName` declared with two parameters instead of four.** The
   output-buffer and length arguments were never passed, so the call read an
   uninitialised register and crashed with an access violation inside `advapi32`.
2. **A hand-rolled `LookupAccountSid` crashed on its buffer-sizing pass.** Replaced
   with `System.Security.Principal`, which wraps the same Win32 call correctly — a
   probe that cannot run reports nothing at all.
3. **The mandatory-label RID was read byte-by-byte**, walking past the end of the
   SID. It must be read as the final DWORD of the single sub-authority. This
   reported `UNPROTECTED` for a Medium-integrity token.
4. **`OS_DENIED` was returned for winerror 2 and 183.** With no staged runtime,
   an empty path resolved to the current directory and reported a *genuine*
   access-denied that had nothing to do with any ACL — so "nothing was staged"
   could have masqueraded as "the OS protected the runtime". Path errors are now
   `PATH_ERROR`, and staged-file operations are skipped with
   `NOT_TESTABLE reason=no_staged_executable_supplied` when no runtime is staged.

Two ordering bugs were also fixed: each destructive operation used to share one
file, so a real rename denial was masked by the earlier delete; and the rename
target reused its source name, hitting winerror 183 (name collision).

The probe now reports `OS_ALLOWED` for all nine filesystem operations as the
operator, which is the evidence that it is not hardwired to report denial.

## What was NOT tested, and why

Every subject-side outcome is **untested**, because no subject process exists:

| Claim | Status |
|---|---|
| process identity is `BABY_AI_TEST` | `NOT_TESTABLE` |
| staged executable readable/executable by the subject | `NOT_TESTABLE` |
| subject write/delete/rename/replace denied | `NOT_TESTABLE` |
| subject child creation denied | `NOT_TESTABLE` |
| subject ACL modification denied | `NOT_TESTABLE` |
| workspace writable by the subject | `NOT_TESTABLE` |

The M015 boundary remains `STAGING_VERIFIED` — but that is operator-side ACL
observation, exactly as M015 stated. **The empirical bridge between "the ACL
design is correct" and "the subject process runs inside it" is still missing.**
That gap is what this milestone was built to characterise, and characterising it
is the result.

## Regression

- **M005:** all 13 protected paths present and readable (5 digests), unchanged.
- **M015 boundary:** still `STAGING_VERIFIED` after all probe activity.
- **Workspace:** `baby_workspace` still writable.
- **Full portable suite:** 1861 passed, 2 warnings, 749 subtests (was 1825; +36
  new M016 tests).
- **Host security:** 15 failed / 10 passed / 13 subtests — unchanged from
  baseline, every failure `NOT_TESTABLE` for the same impersonation reason.
- No birth: `BIRTH.json` absent. No model: no `.gguf` anywhere. No network
  isolation claimed. No signing key created.

## Observed vs derived vs proposed vs not-testable

- **Observed:** the token's five privileges; the absence of the two impersonation
  privileges; non-elevation; the account's metadata; `Access is denied` on
  scheduled-task registration; the probe's own output as the operator.
- **Derived:** that unattended launch as another local user is impossible from
  this token, because every mechanism without stored credentials requires one of
  the two absent privileges.
- **Proposed:** `runas.exe` at an interactive session is the most likely route,
  since it needs no stored password. **Unverified** — it requires a human at a
  keyboard, and this milestone did not fake one.
- **NOT_TESTABLE:** everything in the table above.

## Residual blockers

1. `SeImpersonatePrivilege` absent → blocks `CreateProcessWithLogonW`.
2. `SeAssignPrimaryTokenPrivilege` absent → blocks `CreateProcessAsUser`.
3. Non-elevation → blocks scheduled-task registration and service install.
4. Credential prompt required by `runas.exe` / `Start-Process -Credential` →
   not automatable.

## Exact prerequisites for an M014 rerun

In order:

1. **A human-selected runtime.** Create `human_control/experiment_config/runtime_selection.json`
   naming `source_path` and `selected_by`. Nothing is staged until then.
2. **Stage it through M015's deployment path**, verifying source/destination
   SHA-256 equality and re-running the M015 verifier.
3. **Launch capability.** Either:
   - run `runas.exe /user:THARUNBALAJI-LA\BABY_AI_TEST <staged.exe>` from an
     interactive session, entering the password at the prompt; or
   - grant `SeImpersonatePrivilege` **to the operator** (not to
     `BABY_AI_TEST`) so `CreateProcessWithLogonW` becomes usable.

   The second option does not weaken the subject boundary: it grants nothing to
   `BABY_AI_TEST` and does not touch any ACL. It is nonetheless a privilege change
   and should be a deliberate decision.
4. **Run the probe as the subject** against the staged tree, and only then record
   `SUBJECT_PROCESS_VERIFIED` with real `OS_DENIED` outcomes.

Until step 4 completes, no subject-side claim in this document is supported.