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

## Follow-up: identity verified interactively, integrity bug found and fixed

### Identity is now empirically verified

A human ran the probe through the interactive `runas.exe` route and observed:

```
identity_framework=THARUNBALAJI-LA\BABY_AI_TEST
user_sid=S-1-5-21-2406520953-1060965512-844951592-1022
account_name=THARUNBALAJI-LA\BABY_AI_TEST
```

This is the missing empirical result from M016: a **real** process ran under
`BABY_AI_TEST`, and it read that identity from its own live token via
`OpenProcessToken`/`GetTokenInformation` — not from arguments, configuration, or
executable path. `...-1022` is the subject; `...-1001` is the operator.

So the unattended-launch blocker is resolved in practice: it needs a human at a
keyboard, not a privilege change. No privilege was granted and no ACL was
modified.

### `integrity_level=UNPROTECTED` was a probe bug, not a token property

That same run reported `integrity_level=UNPROTECTED`, which cannot be true of a
Medium token. It was **not** reinterpreted as MEDIUM — it was diagnosed.

A mandatory-label SID is `S-1-16-<RID>`, and its header is **8 bytes**:

```
offset 0  BYTE  Revision
offset 1  BYTE  SubAuthorityCount
offset 2  BYTE  IdentifierAuthority[6]     <-- the bug was here
offset 8  DWORD SubAuthority[SubAuthorityCount]
```

The probe read the RID from offset `2 + (n-1)*4`. Offset 2 is inside the
6-byte identifier authority, whose bytes are `00 00 00 00 00 10` for S-1-16 —
so the low DWORD is `0`, which maps to `UNPROTECTED`.

Measured directly on the operator's own Medium token:

```
offset 2  -> 0x0000    (what the probe reported: UNPROTECTED)
offset 8  -> 0x2000    (correct: MEDIUM, = 8192)
whoami /groups: S-1-16-8192  Mandatory Label\Medium Mandatory Level
```

**This was a regression I introduced.** The M016 report claimed a byte-by-byte
SID-parse bug had been fixed. What I actually fixed was the *stride*; I left the
*base offset* wrong. The old code read the identifier authority and reported the
zeros it found as an integrity level — and because zero is a legitimate RID
value, the failure was silent.

Corrected behaviour:

- RID read from offset `8 + (n-1)*4`.
- A **second, independent path** reads the same token via
  `ConvertSidToStringSid` and parses the RID from the string. The probe now
  prints `integrity_level`, `integrity_level_independent`, and
  `integrity_paths_agree`.
- A parse failure returns `<no-label>` or `<unreadable-sid>` and emits
  `integrity_note=PARSE_FAILED`. **`UNPROTECTED` can now only be printed when a
  real RID of 0 was read.**
- Disagreement between the two paths is reported explicitly.

Operator-side result now: `integrity_level=MEDIUM`,
`integrity_level_independent=MEDIUM`, `integrity_paths_agree=true`, cross-checked
against `whoami /groups`.

### No filesystem boundary test has occurred yet

The probe interface is extended and the harness is prepared, but **nothing has
been run as the subject against `subject_runtime`**. No `OS_DENIED` for the
subject has been observed, recorded, or claimed.

### Two further harness bugs found while preparing the test

Both were found by negative controls, and both would have produced false results:

1. **PowerShell drops empty-string arguments.** Passing `""` as a positional slot
   shifted every later value by one, so the workspace test ran against an option
   string and reported a spurious `NotSupportedException`. The harness now uses
   `-` as an explicit "not supplied" placeholder.
2. **An implicit path fallback** derived `..\runtime` from the scratch argument
   when `--enumerate-runtime` was absent. A run with a bogus scratch path still
   "tested" the real staging directory, reporting `OS_ALLOWED` for a case it never
   targeted. There is no fallback now; an unsupplied option reports
   `NOT_TESTABLE reason=no_path_supplied`.

A third defect was my own test setup: a negative control using `C:\nope_a`
reported `OS_ALLOWED` because that path genuinely existed — the probe had created
it at the volume root during an earlier run. The probe was truthful; my
assumption was wrong. The stray directory was removed.

## Boundary test preparation

The probe now supports the full read/write matrix as disposable paths:

| Operation | How it is reached |
|---|---|
| traverse | `--traverse=<dir>` |
| enumerate runtime / model / config | `--enumerate-{runtime,model,config}=<dir>` |
| read a permitted file | `--read-file=<path>` |
| write / append / delete / rename / replace | positional `<scratch> <staged>` |
| create / delete child directory | positional `<scratch>` |
| modify ACL | `--acl-target=<path>`, positional `<protected>` |
| workspace write / read / delete | positional `<workspace>` |

Results are classified strictly as `OS_ALLOWED`, `OS_DENIED`, `PATH_ERROR`,
`NOT_TESTABLE`, `ERROR`. A finding whose target was never reached is marked
`reached_target: false` and is not evidence about any ACL.

### Operator positive control (real, run here)

The operator holds full control, so every operation must report `OS_ALLOWED` —
17 of 17 did. This is what makes any later `OS_DENIED` meaningful. Two mutation
tests confirm the control has teeth: a probe modified to always report
`OS_DENIED`, and one modified to always report `UNPROTECTED`, both cause the
suite to fail.

## Boundary harness correction: ReadOnly, not the ACL

### The historical failure

An operator dry run of the boundary harness returned `OS_DENIED` for
`modify`, `append`, `delete`, `rename` and `replace` — for an account holding
`(F)` on the target directory. A denial the operator cannot perform is not a
working boundary; it is a broken fixture.

**Initial hypothesis (wrong):** the destructive-operation copies were being
created in the scratch directory, `subject_runtime\config`, which is `R`-only for
the subject. The copies would then inherit *config's* ACL rather than the
runtime subtree's, so the operations were testing the wrong directory.

**Investigation disproved it.** The hypothesis was plausible and the code change
that followed is defensible, but it was not the cause. Two observations
overturned it:

- `destructive_scratch_dir` already reported `subject_runtime\runtime`, and
  `create_child_executable_beside_runtime` — which writes into that same
  directory — returned `OS_ALLOWED`. The directory was writable.
- `icacls` reported the copy's ACL as correct. If the ACL had been the problem,
  it would have said so.

**Actual cause.** The fixture carried the **`ReadOnly` DOS attribute**. The
probe's own `modify_acl` test sets that attribute and had not restored it. The
ReadOnly bit is *not part of the ACL*, so every ACL report stayed clean while
every write failed — for the operator as well as the subject.

The propagation mechanism was then confirmed directly:

```
source readonly BEFORE File.Copy : True
copy    readonly AFTER  File.Copy : True   <- File.Copy carries the attribute
operator can WRITE the copy      : False
after attrib -R, write works     : True
```

`File.Copy` propagates DOS attributes from source to copy, so a ReadOnly target
yields ReadOnly copies. **Clearing `ReadOnly` on the fixture made all five
operations `OS_ALLOWED`.**

### The lesson, and why the harness now reports both

ACL state and file attributes are separate security dimensions. Evidence that
mixes them is unreliable in both directions: a sound ACL can appear to fail, and
a broken ACL can appear to pass. The probe now reports both independently:

```
staged_target_attributes=Normal
staged_target_readonly=False
```

and the readiness gate refuses to run when the fixture is not writable.

### What was retained, and why

The destructive-operation copies are still created in **the staged file's own
directory** rather than the scratch directory. This is retained as **test
isolation and hardening**, on its own merits: a copy used to test an object
should inherit the ACL regime of the object under test, not that of some
unrelated directory. It is *not* claimed to be the fix for the denials.

The probe reports where it is working:

```
destructive_scratch_dir=C:\dev\TharAI-EXP\subject_runtime\runtime
```

### Fixture ownership

Ownership is by **creation**, not by filename prefix:

- each invocation derives a `run_token` from its process id and start time;
- the files it creates are named `m016_copy_<token>_*`;
- cleanup enumerates only names carrying that token, and reports failures as
  `cleanup_owned_copies_failed=N` rather than swallowing them;
- `m016_disposable_target.exe`, any pre-existing artefact, and any model or
  config file are never candidates for deletion.

This replaced an earlier design in which a test used the operator's
`m016_disposable_target.exe` as its own fixture and deleted it — which left
`subject_runtime` empty and the boundary test with no target. That is the defect
the ownership model exists to prevent.

Tests assert that a pre-existing target survives, that unrelated files survive,
that a file *resembling* a probe artefact but not created by the run also
survives, and that two invocations never share a token.

### A third defect, found by the full suite

Compiling the probe embedded its source in a PowerShell command line. That
worked while the probe was small and then failed with `WinError 206` (command
line too long) once the source grew. The tests now compile by **path**, which
has no such ceiling.

### Corrected operator positive control

With the attribute handled and the fixture owned, the operator run reports
`OS_ALLOWED` for all six destructive operations, and readiness reports `READY`:

```
modify / append / delete / rename / replace / child-create : OS_ALLOWED
destructive_scratch_dir : C:\dev\TharAI-EXP\subject_runtime\runtime
cleanup_owned_copies_failed : 0
pre-existing target survives : True
RESULT: READY
```

A ReadOnly fixture is now reported as `staged_target_readonly=True` and its
probe-owned copies are normalised, so the cause stays attributable to an
attribute rather than being read as a permission result.

## First real subject boundary run: PARTIALLY_VERIFIED

A human ran the harness interactively via `runas.exe`. This is the first time a
real process ran inside the M015 boundary and asked Windows questions.

**Classification: `SUBJECT_BOUNDARY_STATUS = PARTIALLY_VERIFIED`.** Not
`STAGING_VERIFIED_BY_SUBJECT`, not `FULL_BOUNDARY_PASS`.

### Identity: verified

```
user_sid=S-1-5-21-2406520953-1060965512-844951592-1022
account_name=THARUNBALAJI-LA\BABY_AI_TEST
integrity_level=MEDIUM
integrity_level_independent=MEDIUM
integrity_paths_agree=true
```

Read from the live token. Not inferred from arguments or configuration.

### What the OS actually established — and stands

The subject **could not**, anywhere inside `subject_runtime`:

```
traverse_directory  enumerate_runtime  enumerate_model  enumerate_config
modify_acl  create_file_in_staging_scratch
modify_staged_executable  append_staged_executable  delete_staged_executable
rename_staged_executable  replace_staged_executable
create_child_executable_beside_runtime  create_child_directory
```

all `OS_DENIED winerror=5`. And it retained full use of the intentionally
writable `baby_workspace`: `workspace_write`, `workspace_read`, `workspace_delete`
all `OS_ALLOWED`.

These are genuine observations against real objects and are not retracted.

### Four defects the run exposed

**1. `read_disposable_file=OS_ALLOWED` was true but tested the wrong object.**
The target was `baby_workspace\m016_probe.exe` — the *writable* experimentation
area — not anything in `subject_runtime`. Nothing in the output named the file, so
the line sat next to thirteen denials and read as evidence about the boundary. The
probe now echoes `read_file_target=` and `read_file_bytes_observed=` so the object
is named in the output itself.

**2. `delete_child_directory=OS_ALLOWED` was a no-op reported as success.** The
directory had never been created — creation had been denied — and the delete was
guarded by `if (Directory.Exists(...))` *inside the lambda that counted success*.
The guard skipped the work; the lambda still counted it. So "the subject could not
create a directory" was reported as "the subject could delete a directory", which
is the opposite of the truth. The subject has **no** directory-delete capability
here; the harness never established that.

Two distinct fixtures now exist, the delete fixture is created through the same
guarded path as the create fixture, and an absent fixture reports
`NOT_TESTABLE reason=fixture_absent`.

**3. `restore_acl_target_attributes=ERROR` was correct behaviour reported as a
fault.** The subject holds no `FILE_WRITE_ATTRIBUTES` under M015, so it cannot
undo the `ReadOnly` bit the ACL test set. **That refusal is evidence the boundary
works.** It is now reported as `EXPECTED_OS_DENIED` with a note that operator-side
restoration is required. No privilege was added to let the subject tidy up after
itself — that would have granted the exact capability the boundary withholds.

**4. The crash.** `Directory.GetFiles` reports access-denied as a plain
`IOException` carrying `ERROR_ACCESS_DENIED`, but the probe's `Run` only caught
`UnauthorizedAccessException`. The subject cannot list `runtime\`, so the unguarded
cleanup call threw — *after* every result had been recorded. The 21 results
survived in the output file; the cleanup report and the process exit did not.

`Run` now handles `IOException` and classifies winerror 5 as `OS_DENIED`.

### Cleanup design under a subject that cannot enumerate

The subject cannot list its own scratch directory, so it cannot discover its own
artefacts there. The ACL is **not** weakened to work around this. Instead:

```
cleanup_state=CLEANUP_NOT_PERMITTED
cleanup_operator_followup=m016_copy_<run_token>_*
```

The probe names the exact prefix so an operator can finish the job afterwards, and
reports `cleanup_owned_copies_removed` / `_failed` separately. In this run the
subject created nothing, so there was nothing to clean — a fact the report now
states rather than one that surfaces as a crash.

Ownership is unchanged: every artefact name embeds the per-invocation `run_token`,
so cleanup can only ever match what that invocation created.

### What a corrected subject run would still need to establish

The read test *inside* `subject_runtime`, a delete test with a fixture that
actually exists, and a completed cleanup report. Until those run, the boundary is
constrained but not fully characterised.

## Final harness correction: the three remaining blockers

This closes the three gaps left by the first subject run. It does **not** rerun the
subject account, and it does not retroactively upgrade what that run proved.

### 1. The read test now targets the boundary

The read test pointed at `baby_workspace\m016_probe.exe` — the intentionally
writable experimentation area. `OS_ALLOWED` there was true and irrelevant to
`subject_runtime`.

The read target is now an operator-created fixture inside
`subject_runtime\runtime\`, and the probe reports both the path and whether it
lies inside the staging root:

```
read_file_target=C:\dev\TharAI-EXP\subject_runtime\runtime\m016_read_fixture.exe
read_file_in_staging=True
read_file_bytes_observed=26
```

`read_file_in_staging` is a computed comparison against the staging root, not an
assertion. A read aimed elsewhere is still permitted — an operator may
legitimately check the workspace — but it is labelled, so a workspace read can
never again sit beside staging denials and be read as staging evidence. `IsUnder`
requires a path separator after the root, so `subject_runtime_evil` does not
count as inside `subject_runtime`.

A read target that does not exist reports `NOT_TESTABLE`, never `OS_ALLOWED`.

### 2. The delete test uses an operator-owned, pre-existing fixture

Three successive versions of this operation were wrong:

1. One shared name, with the delete behind `if (Directory.Exists(...))` inside the
   counting lambda — a refused creation produced `OS_ALLOWED` for a delete that
   never happened.
2. The probe then created its own delete fixture through the same guarded path —
   which meant the target could *appear during the very run* meant to test
   deleting a pre-existing object.
3. A non-recursive `Directory.Delete` against a fixture holding a sentinel file
   returned `winerror 145` (directory not empty), a `PATH_ERROR` about the
   fixture's contents that says nothing about whether the account may delete the
   directory.

The probe now **never creates** the directory it intends to delete. The operator
supplies it via `--delete-fixture`, and the probe reports what it found:

```
create_child_directory_target=...\config\m016_child_create_dir
delete_child_directory_target=...\config\m016_delete_target
delete_child_directory_target_preexisted=True
probe=delete_child_directory result=OS_ALLOWED
```

Absent fixture → `NOT_TESTABLE reason=delete_fixture_absent`. No fixture supplied
→ `NOT_TESTABLE reason=no_delete_fixture_supplied`. Neither is ever `OS_ALLOWED`,
and no skip is ever counted as a success.

### 3. Cleanup is reported, not required, from the subject side

The subject cannot list its own scratch directory, and that is the boundary
working. No cleanup privilege is granted.

```
cleanup_state=CLEANUP_NOT_PERMITTED
cleanup_operator_followup=m016_copy_<run_token>_*
cleanup_owned_copies_removed=0
cleanup_owned_copies_failed=0
```

`CLEAN` is reported when the account could enumerate and clean; `CLEANUP_NOT_PERMITTED`
when it could not; `PARTIAL` when some deletions failed. The prefix names exactly
what an operator should remove. Ownership is unchanged — every artefact name
embeds the per-invocation `run_token`.

### Operator positive control

Every intended operation genuinely executes: **18 `OS_ALLOWED`, zero
`OS_DENIED`, zero `NOT_TESTABLE`**, `delete_child_directory_target_preexisted=True`,
`read_file_in_staging=True`, `cleanup_state=CLEAN`, no unhandled exception.

That is the evidence that a following subject run's `OS_DENIED` results would be
about the boundary rather than about an unexercisable operation.

### What is still not claimed

`SUBJECT_BOUNDARY_STATUS` remains **`PARTIALLY_VERIFIED`**. The three blockers are
now *resolved in the harness*; they are only *observed* once the subject run
happens. Nothing here upgrades the previous run's evidence.

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