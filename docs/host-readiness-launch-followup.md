# Host-readiness follow-up — direct executable launch

A launch-mechanism investigation. No model selected, nothing downloaded, no
runtime executed, no birth, no subject. M014 birth behaviour is untouched.

## Why the human's command failed

```powershell
Start-Process -FilePath "py" ...   →  InvalidOperationException:
                                       "The file cannot be accessed by the system."
```

`py` is not the interpreter. It is the **Python Launcher**, and on this host it
resolves to an **App Execution Alias**:

```
C:\Users\k.tharun balaji\AppData\Local\Microsoft\WindowsApps\py.exe
C:\Users\k.tharun balaji\AppData\Local\Microsoft\WindowsApps\python.exe
```

App Execution Aliases are **per-user shims**. They resolve only for the account
that created them, so `BABY_AI_TEST` cannot launch one, and Windows reports that
as *"the file cannot be accessed by the system."* This is not a fact about
`BABY_AI_TEST`, and it is not a birth problem.

They are also **zero-length reparse points** — there are no bytes behind them,
which is why they cannot be hashed and why `Start-Process` refuses them.

## The real interpreter

| | |
|---|---|
| Path | `C:\Users\k.tharun balaji\AppData\Local\Python\pythoncore-3.14-64\python.exe` |
| SHA-256 | `cce21c0e8710e304273e98ac4b2b0f5aceb639acbcd2343cbaa5c4e81619c45b` |
| Size | 106,328 bytes |
| Architecture | x64 (`0x8664`, read from the PE header) |
| Version | CPython 3.14.3 |
| App Execution Alias | no |

`py -3` reports this path via `sys.executable`; `C:\Users\k.tharun balaji\AppData\Local\Python\bin\python.exe`
is a hard link to the same binary, not a separate installation.

## Pointing at it is necessary but not sufficient

**This is the substantive finding.** The interpreter is correct, absolute, and
still unusable, because it lives inside the operator's private profile:

```
C:\Users\k.tharun balaji\AppData\Local\Python\pythoncore-3.14-64\python.exe
  NT AUTHORITY\SYSTEM:(F)
  BUILTIN\Administrators:(F)
  THARUNBALAJI-LA\k.tharun balaji:(F)
```

Three principals, and `BABY_AI_TEST` is not one. Worse, **no directory in the
chain has a `BUILTIN\Users` ACE at all** — not `pythoncore-3.14-64`, not
`Python`, not `AppData\Local`, not `AppData`, not `k.tharun balaji`. The account
cannot even *traverse* into the path, so no command naming this executable can
work.

A file can be world-readable and still be unreachable because a parent is private.
`reachable_by_subject()` checks every ancestor for exactly this reason.

## What else is and is not reachable

| Path | Reachable by `BABY_AI_TEST` | Why |
|---|---|---|
| `C:\dev\TharAI-EXP` (repository) | **yes** | `C:\dev` grants `BUILTIN\Users:(RX)` and `Authenticated Users:(M)`; M005's ACEs deny only *writes* |
| `C:\dev\TharAI-EXP\scripts\subject_boundary_probe.py` | **yes** | inherits the repository's read grant |
| the interpreter | **no** | private profile, no `Users` ACE above it |
| `llama-server.exe` (M010's unselected runtime) | **no** | same three-principal ACL, under `.docker\bin\inference\` |

So the fault is isolated and precise: **the target is fine, the interpreter is
not reachable.** That is the single blocker.

It also bites M014 harder than it bites this probe. The llama runtime that a real
birth would need is confined to the same private profile. Whatever makes the
interpreter reachable must eventually apply to the runtime and model too.

### The one other Python on this host

`C:\Program Files\MySQL\MySQL Workbench 8.0\python.exe` has a permissive
`BUILTIN\Users:(RX)` ACL, so it is reachable — but it is a **relocatable build**
that needs `PYTHONHOME`. Without it, it infers its prefix from the *current
working directory* and dies with `ModuleNotFoundError: No module named
'encodings'`; with it set, it still fails because the Workbench does not ship a
usable stdlib layout.

Even if it worked, it could not be used here: `-Credential` makes Windows build a
**new environment block** from the target user's profile, so `PYTHONHOME` set in
the operator's shell would not propagate — and PowerShell 5.1's `Start-Process`
has **no `-Environment`** parameter to inject it. This was checked, not assumed.

There is no system-wide Python on this host. The only entry in the registry is the
per-user `HKCU\...\pythoncore-3.14-64`.

## The launch command

`foundation/subject_launch.py` builds it, and **returns
`UNAVAILABLE (see blocking)`** rather than emitting a command that cannot work.
A command that looks right and fails with a permissions error is worse than no
command, because it sends the next person looking in the wrong place.

The moment the interpreter becomes reachable, this is what it produces:

```powershell
Start-Process -FilePath "<ABSOLUTE_PYTHON_EXE>" `
  -ArgumentList "C:\dev\TharAI-EXP\scripts\subject_boundary_probe.py" `
  -Credential (Get-Credential -UserName "THARUNBALAJI-LA\BABY_AI_TEST" `
               -Message "BABY_AI_TEST boundary probe (M014)") `
  -WorkingDirectory "C:\dev\TharAI-EXP"
```

No shell anywhere: absolute executable → absolute probe. That preserves the
project's standing `shell=False` rule and keeps the launched program the actual
interpreter rather than a command processor running a string.

## Independent verification is unchanged

Still token-based, and still necessary, because a process printing its identity
proves nothing:

```
OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)
  → OpenProcessToken(TOKEN_QUERY)
    → GetTokenInformation(TokenUser / TokenIntegrityLevel / TokenElevation / TokenPrivileges)
```

The operator then reads the printed PID's token. Only a token whose SID is
`S-1-5-21-2406520953-1060965512-844951592-1022` sets `boundary_meaningful = true`.

## A bug this work found: a false privilege claim

While checking the launch, my own token reader reported that the harness **held
`SeRestorePrivilege`**. It does not. `whoami /priv` lists five privileges and
`SeRestorePrivilege` is not among them.

The cause was a wrong struct layout. Windows declares `LUID` as **two 32-bit
halves**, so `LUID_AND_ATTRIBUTES` is 12 bytes and the `TOKEN_PRIVILEGES` array
begins at offset 4. I had declared `Luid` as a 64-bit integer, which aligns to 8,
making the struct 16 bytes and the array read from the wrong offset with the wrong
stride. A misaligned read happened to produce that privilege's LUID.

A verifier that invents a privilege the process does not have is worse than one
that reports none, so the layout is now pinned by a positive control:
`test_7d_the_privilege_reader_agrees_with_whoami` parses `whoami /priv` and
requires the reader to find **every** privilege it reports, while
`test_7e` requires `SeImpersonatePrivilege` to be reported **absent**. Both pass,
and `SeRestorePrivilege` no longer appears.

The correct finding, now that the layout is right: the harness holds **no**
notable privileges.

## What was not changed

- No privilege granted. No group changed. No ACL, policy, password or UAC setting
  modified. No task or service created.
- `BABY_AI_TEST`: unchanged — SID matches, enabled, non-admin, in no local group.
- M005 boundary intact: all 14 protected directories still carry their
  `BABY_AI_TEST` deny ACE, asserted by name.
- Event store 20 events, chain intact. Provenance ledger 14 entries. No
  `BIRTH.json`. No `model/` directory. No subject key.
- M014 still `BLOCKED` at stage `declaration`. Host readiness still `NOT_TESTABLE`.

## What the human would need to do next

Not decided here, and not a laboratory action: the interpreter — and eventually
the runtime and model — need to live somewhere `BABY_AI_TEST` can reach. The
existing deny ACEs must stay exactly as they are; only the *location* of the
executable would change. Until that is done, this remains `NOT_TESTABLE`, and no
launch command is offered.