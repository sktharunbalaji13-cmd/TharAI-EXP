# M015 — Subject Runtime Staging Boundary

Status: `STAGING_VERIFIED` (ACL observation only)
Enforcement: `NOT_TESTABLE` — no `BABY_AI_TEST` process was run.
Network isolation: **not established** by this milestone.

## What was done

Created `C:\dev\TharAI-EXP\subject_runtime\` with `runtime\`, `model\`, and
`config\`, and applied an explicit allow-list ACL to all four paths. Nothing was
copied into it. No model or runtime was selected.

The tree exists so that a human-selected artifact can later be staged there under
an ACL that does not permit the subject to write, delete, or change permissions.

## The specific defect this had to fix

The parent, `C:\dev\TharAI-EXP`, grants:

```
NT AUTHORITY\Authenticated Users:(I)(M)
BUILTIN\Users:(I)(RX)
```

`BABY_AI_TEST` is an authenticated user and has logged on, so it inherits
`(M)` — full write — from the parent on every new child directory. Merely adding
a deny for the subject would not be sufficient as evidence, because the inherited
grant would still be present and would need the deny to be neutralised. The
boundary therefore **removes inheritance** and verifies that no
`Authenticated Users` entry remains on any path.

## Resulting ACL, identical in shape on all four paths

| Principal | Rights | Meaning |
|---|---|---|
| `THARUNBALAJI-LA\k.tharun balaji` | `(OI)(CI)(F)` | operator, full control |
| `NT AUTHORITY\SYSTEM` | `(OI)(CI)(F)` | system, for recovery |
| `BUILTIN\Administrators` | `(OI)(CI)(F)` | administrators |
| `THARUNBALAJI-LA\BABY_AI_TEST` | `(OI)(CI)(R)` / `(RX)` | read (execute only under `runtime\`) |
| `THARUNBALAJI-LA\BABY_AI_TEST` | `(OI)(CI)(DENY)(W,D,DC,WD,AD)` | write/delete/ACL backstop |

The per-subtree split is deliberate:

| Path | Subject rights | Why |
|---|---|---|
| `runtime\` | `RX` | it is a program; without execute it will not load |
| `model\` | `R` | it is data; execute would let the subject run model bytes |
| `config\` | `R` | immutable configuration |

The root carries `R` plus the deny, so it gates access to all three subtrees
without itself granting write.

Ownership is the operator's on all four paths, and the verifier checks it.

## Verification

`verify_boundary()` reports `STAGING_VERIFIED` only when all four of these hold
on every path:

- no inherited `Authenticated Users:(M)`;
- the subject's expanded permission set **equals** the expected set — not a
  superset, not a containment test;
- the write/delete backstop deny is present;
- the subject is not the owner.

All four currently hold. The report is explicitly labelled
`ACL_OBSERVATION_ONLY`.

### The verifier is itself tested by trying to defeat it

A verifier that cannot fail is worthless, so each of these tamperings was applied
to a clean disposable tree and confirmed to flip the verdict to
`STAGING_BLOCKED`:

| Tampering | Detected |
|---|---|
| grant `(M)` on `model\` | yes |
| grant `(F)` on `runtime\` | yes |
| grant `(W)` on `config\` | yes |
| grant `(WD)` on `config\` | yes |
| grant `(DC)` on `model\` | yes |
| grant `(RX)` on `model\` | yes |
| remove the deny from `model\` | yes |

The `(WD)` case is the one a naive check misses: the subject keeps a correct `R`
grant, so "does it have R?" still answers yes. Only set equality over the union
of all its grant ACEs catches it. These are locked in as tests in
`tests/test_staging_boundary.py`.

## Host facts established while doing this

- `icacls` prints **no owner marker**, so ownership cannot be read from it —
  an implementation that looked there would get `''` for every path and pass
  vacuously. `dir /q` prints an 8.3-truncated owner that cannot be compared
  reliably. Ownership is read via `Get-Acl`, and an unreadable owner is treated
  as *unverified*, never as "not the subject".
- Windows **refused** `/setowner BABY_AI_TEST` on this host
  ("This security ID may not be assigned as the owner of this object") because
  the operator token lacks `SeRestorePrivilege`. Ownership therefore stayed with
  the operator. This is recorded as a test that documents the refusal and asserts
  the comparison logic, rather than pretending a transfer happened.
- `COMPUTERNAME\SYSTEM` does not resolve; `SYSTEM` is not a local account. The
  grant silently failed with "No mapping between account names and security IDs",
  leaving the tree without the system access needed for recovery. The well-known
  name `NT AUTHORITY\SYSTEM` is used instead.
- Principal names contain spaces (`THARUNBALAJI-LA\k.tharun balaji`), so a
  whitespace split would truncate the operator's own grant to
  `THARUNBALAJI-LA\k.tharun` — an account that does not exist.

## What is deliberately NOT claimed

- **No `BABY_AI_TEST` execution.** Whether the OS actually enforces these rights
  for that account is `NOT_TESTABLE` here: the harness holds neither
  `SeImpersonatePrivilege` nor `SeAssignPrimaryTokenPrivilege`, and the
  operator's Python installation is itself inaccessible to the subject. The ACLs
  are observed as the operator, which is a different claim from enforcement.
- **No network isolation.** `llama-server.exe` accepts `--model-url`, so a staged
  runtime would retain network capability. Filesystem ACLs cannot express this.
  `LOCAL_ONLY_NO_FETCH` remains a separate gate.
- **No confidentiality.** The subject must read the model to run it. This
  boundary provides integrity, not confidentiality.
- **No artifact selection.** The unselected runtime under
  `%USERPROFILE%\.docker\bin\inference\` was not copied and not selected.
- **No birth.** M014 remains `BLOCKED`; this milestone does not change that.

## Test results

- `tests/test_staging_boundary.py`: 24 passed (new)
- full portable suite: **1825 passed**, 2 warnings, 749 subtests passed
- `tests/host_security`: 15 failed, 10 passed, 13 subtests passed — unchanged
  from baseline, every failure `NOT_TESTABLE` for the impersonation reason above.

The full suite count rose from 1801 to 1825: +24 new boundary tests, adjusted for
the one design-phase precondition test that asserted the tree did not yet exist.

## Recovery

`recover(confirm=True)` removes the staging tree and nothing else. It refuses
without `confirm`, and it will not delete a tree that is not the staging root.

## Reproducing

```powershell
$env:PYTHONPATH="C:\dev\TharAI-EXP"
py -3 -c "from foundation.staging import apply_boundary, verify_boundary; apply_boundary(); verify_boundary()"
```