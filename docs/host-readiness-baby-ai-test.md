# Host readiness — real `BABY_AI_TEST` execution

An investigation, not a milestone. Nothing here births, creates a subject, sets a
`T_birth`, appends an experience, provisions a key, or selects a model. The
laboratory state is unchanged and was verified unchanged.

## The question

M014 reported two blockers. The first is that no human has selected a model, and
that one is a decision, not a defect. The second is that the Python harness cannot
impersonate `BABY_AI_TEST`.

The second turned out to be a narrower problem than it looked, and narrowing it is
the substance of this document. The harness cannot *become* the account, but it
does not need to. It needs to be able to *observe* a process that Windows made
into the account — and that works, unelevated, with no privilege and no stored
secret.

## Findings

### The account

| | |
|---|---|
| Account | `THARUNBALAJI-LA\BABY_AI_TEST` |
| SID | `S-1-5-21-2406520953-1060965512-844951592-1022` — **matches expected** |
| Enabled | yes |
| Local group membership | **NONE** |
| Global group membership | none |
| Password required | no |
| Last logon | 2026-09-27 22:04:51 |
| Profile directory | `C:\Users\BABY_AI_TEST` exists |

Two things worth stating plainly.

**It is in no local group at all** — not even `Users`. So it inherits nothing: no
administrators' rights, no user rights, nothing. The deny ACEs on the repository
are therefore the *only* thing constraining it, which is exactly the M005 design
and exactly why those ACEs must not be touched.

**It has logged on before.** `C:\Users\BABY_AI_TEST` exists and `Last logon` is
set. The operator cannot even list that directory — access denied — so the profile
is real and separate. This corroborates M005, which recorded a *human-executed
cross-process* probe as `BABY_AI_TEST` with `OS_DENIED` on protected paths and
`ALLOWED` on the workspace. **The mechanism this investigation recommends has
already worked once.**

### The harness

| | |
|---|---|
| Account | `THARUNBALAJI-LA\k.tharun balaji` (SID `…-1001`) |
| Integrity | Medium (`Mandatory Label\Medium Mandatory Level`, `S-1-16-8192`) |
| Elevation | not elevated; in `Administrators` but as a *deny-only* filtered token |
| Notable privileges held | **none** |
| Token privileges present | 5, all stock user defaults |

`SeImpersonatePrivilege` and `SeAssignPrimaryTokenPrivilege` are **absent from the
token entirely** — not present-but-disabled. M005 observed `ERROR_NOT_ALL_ASSIGNED`
(1300) when trying to enable them, which is the expected result for a privilege
the token does not carry. There is nothing to enable.

### What could not be read

Both refusals are honest gaps, and neither is evidence of absence:

- **`secedit /export` requires elevation.** The subject account's own *granted*
  privilege set (`SeBatchLogonRight`, `SeInteractiveLogonRight`, and so on) lives
  in the LSA policy and is **NOT_TESTABLE** from this session. M014's
  restricted-account status therefore rests on the token facts above and on M005's
  human-executed evidence, not on a read of the account's rights.
- **The Security event log is unreadable non-elevated.** Logon events (4624/4625)
  for the account could not be retrieved, so there is no independent audit-log
  corroboration available. `NOT_TESTABLE`.

### WSL — ruled out

M005 already measured it: the WSL identity is
`uid=1000(sktharun_balaji) gid=1000(sktharun_balaji) …`, reached over 9p/DrvFs
with `uid=1000`. A WSL process holds the **operator's** Windows token. It cannot
be the subject account, and it is not a candidate. Recorded rather than
re-investigated.

### The new capability: independent token observation

This is the finding that changes the design.

`foundation/token_observation.py` opens a process handle with
`PROCESS_QUERY_LIMITED_INFORMATION` and reads `TokenUser` and
`TokenIntegrityLevel` through `OpenProcessToken(TOKEN_QUERY)`. **All of that works
non-elevated**, and it was verified here against a real process the operator
spawned:

```
status            : VERIFIED
user_sid          : S-1-5-21-2406520953-1060965512-844951592-1001
account_name      : THARUNBALAJI-LA\k.tharun balaji
integrity_label   : MEDIUM
elevated          : False
notable privileges: []
```

So the laboratory does not need impersonation to *confirm* a subject process. It
needs a handle, and Windows grants `TOKEN_QUERY` without special privilege. The
identity comes from the token, not from anything the process says about itself —
which is the requirement, and which a program printing `BABY_AI_TEST` would not
satisfy.

**What remains unverified:** whether `OpenProcess` succeeds against a process
running under *different* credentials. Windows' default process DACL grants
`Everyone` `SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION`, which suggests it
will, but it has not been tested here because testing it requires launching as
`BABY_AI_TEST`, which requires a credential this investigation will not ask for.
`observe_process` returns `NOT_TESTABLE` rather than assuming success, and a
caller that receives `NOT_TESTABLE` must not treat the identity as confirmed.

## Mechanisms considered

| Mechanism | Verdict | Why |
|---|---|---|
| Impersonation via `SeImpersonatePrivilege` | **FAILED / refused** | Absent from the token. Acquiring it would let any process in the session assume any identity — a larger hole than the one it closes. |
| `CreateProcessWithLogonW` | **FAILED / refused** | Absent, and refused. It is credential-equivalent: whoever holds it can mint a token for any local account without that account's password. |
| S4U (`LOGON32_LOGON_S4U2`) | **FAILED / refused** | Attractive precisely because it needs no password — and it needs `SeImpersonatePrivilege` to call and `SeTcbPrivilege` to register. Both absent, both refused. |
| Task Scheduler task for the account | **NOT_TESTABLE / rejected** | Needs the password in Task Scheduler's store, or an elevated S4U registration. Also a *persistent* execution path — more capability than a one-shot launch needs. |
| Windows service | **FAILED / rejected** | Cannot run as an ordinary local account without a stored password; creating one needs elevation. Also a standing always-on path. |
| WSL | **FAILED** | Runs as the operator, not the subject. |
| **Human-launched process, `Start-Process -Credential`** | **NOT_TESTABLE** | Viable and already used in M005. Not verified here because this investigation did not perform a launch. |

## Recommendation

**The human launches; the laboratory observes.**

```
Human operator
  │  Start-Process -Credential … -Credential (Get-Credential …)
  │  ← password typed at a Windows prompt, never into a tool
  ▼
Windows establishes the process token          ← the identity is Windows', not ours
  │
  ▼
Real llama.cpp runtime runs as BABY_AI_TEST
  │
  ├── model file
  ├── permitted workspace (baby_workspace)
  └── DENIED: events, provenance, keys, human control, protected research
  │
  ▼
Operator reads that PID's token               ← independent of anything it printed
  └── foundation.token_observation.observe_process(pid, expected_sid=…-1022)
```

The exact command the human runs:

```powershell
Start-Process -FilePath "py" `
  -ArgumentList "-3", "scripts/subject_boundary_probe.py" `
  -Credential (Get-Credential -UserName "THARUNBALAJI-LA\BABY_AI_TEST" `
               -Message "BABY_AI_TEST boundary probe (M014)") `
  -WorkingDirectory .
```

### Why this preserves M005

- The M005 deny ACEs are **untouched**. Nothing in this plan modifies an ACL, a
  group, a privilege, or UAC. The mechanism runs the subject *against* the
  boundary that already exists, which is the only way that boundary can be
  observed doing its job.
- The account's properties are **unchanged**: still no local groups, still
  non-administrator.
- The probe **reads no protected evidence.** It attempts a *create* at each
  protected path and records whether the OS refused. The refusal is the evidence;
  a successful read would be the failure.
- `boundary_meaningful` is set by the **operator**, from the token, and never by
  the probe. The probe writes `"boundary_meaningful": None` and says in the file
  that it cannot establish this, because a process cannot prove its own identity.

### Why it needs no unnecessary privilege

- The harness acquires **nothing**. `SeImpersonatePrivilege` and
  `SeAssignPrimaryTokenPrivilege` are recorded as *refused*, and
  `assess_subject_account` reports `operator_execution_accepted_as_subject: False`
  unconditionally so the claim cannot be quietly dropped later.
- The password is entered by the human at a **Windows** prompt. The laboratory
  never receives it, never stores it, never receives it as an argument, and never
  writes it to a file. A test asserts the launch command contains no
  `ConvertTo-SecureString` and no `Password` literal.
- The read-back path (`observe_process`) asks only for
  `PROCESS_QUERY_LIMITED_INFORMATION` and `TOKEN_QUERY` — the documented minimum
  for reading a token. A test walks the AST to confirm it never references
  `PROCESS_ALL_ACCESS`, and that it cannot write to or terminate a process.

## The probe

`scripts/subject_boundary_probe.py`, stdlib-only so that lab imports
cannot colour its own result. It reports its identity and PID, attempts one create
per protected path, does a create/read-back/delete round trip in the workspace, and
writes its report to `baby_workspace/subject_boundary_probe.json`. It contains no
birth code and imports none.

**It has not been run.** Running it is the human action below.

## The future probe design

M014's boundary criterion needs a `boundary_meaningful = true` probe run as the
subject. The mechanism:

1. Human launches the probe with `-Credential`. Windows makes the token.
2. Probe attempts a create at each of the 16 protected directories and reports
   `OS_DENIED` for each.
3. Probe does the workspace round trip and reports `ALLOWED`, proving the boundary
   is not "deny everything".
4. Operator reads the probe's PID token with `observe_process(..., expected_sid=…-1022)`.
5. **Only when step 4 returns `VERIFIED` with that SID** is
   `boundary_meaningful = true`.

If step 4 returns `NOT_TESTABLE`, the criterion stays unmet. There is no path where
a self-report sets it.

## Required human action

Exactly one thing, and it is not performed here:

1. Run the `Start-Process -Credential` command above, entering `BABY_AI_TEST`'s
   password at the Windows prompt.
2. Then, from the operator's own session, confirm the token of the printed PID.

Nothing else is required. In particular the human does **not** need to grant a
privilege, elevate a terminal, edit an ACL, create a task, or create a service.

## Limitations

- The account's granted logon rights (`SeBatchLogonRight` etc.) are unreadable
  non-elevated. `NOT_TESTABLE`.
- Logon audit events are unreadable non-elevated. `NOT_TESTABLE`.
- Cross-credential `OpenProcess` is untested. `NOT_TESTABLE`.
- The subject path has therefore **never been executed by the laboratory** and
  remains `NOT_TESTABLE` end to end.

## What was not touched

Verified after the investigation:

- Event store: 20 events, chain intact, **0 appended**.
- Provenance ledger: 14 entries, **0 appended**.
- No `BIRTH.json`. No `model/` directory. No subject key.
- Keyring unchanged; `HK-*.key` and `SK-*.key` are the M004 keys.
- All 14 protected directories still carry their `BABY_AI_TEST` deny ACE, asserted
  by name in the test suite so a silent removal fails it.
- No privilege granted. No group changed. No task or service created. No ACL
  modified. No model selected.
