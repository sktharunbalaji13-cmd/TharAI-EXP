# M016 Correction — Exact Subject Deny Mask: Implementation Evidence

**Status: implementation complete on a scratch tree. Production NOT modified.**
Date: 2026-10-01. HEAD at time of work: `3c91b340e9a5d28c32b351700d4f7b3d514f1cf4`.

Intended mask: `0x000d0156` — `FILE_WRITE_DATA`, `FILE_APPEND_DATA`,
`FILE_WRITE_EA`, `FILE_DELETE_CHILD`, `FILE_WRITE_ATTRIBUTES`, `DELETE`,
`WRITE_DAC`, `WRITE_OWNER`. `SYNCHRONIZE` (`0x00100000`) deliberately absent.

## Why the mask was unreachable before

`icacls` builds masks from permission tokens, and the token carrying
`FILE_WRITE_ATTRIBUTES` (`W`) also carries `FILE_SYNCHRONIZE`. Every token list
that denies attribute writes therefore also denies SYNCHRONIZE. Measured:

| tokens | measured mask | note |
|---|---|---|
| `W,D,DC` | `0x00110156` | the pre-existing M015 shorthand |
| `WD,AD,W,D,DC` | `0x00110156` | same expansion |
| `WDAC,WO,DC,WD,AD,W` | `0x001c0156` | carries an unrequested SYNCHRONIZE |
| `WO,WDAC,DC,AD,WD` | `0x000c0046` | omits WriteEA **and** WriteAttributes |
| `S` | `0x00100000` | exact |

So `icacls` cannot express `0x000d0156`, at any token combination.

## The write-path asymmetry

No single write path on this host is exact for both masks. Established by
measurement, not assumption:

| path | `0x000d0156` (apply) | `0x00110156` (restore) |
|---|---|---|
| native .NET `FileSystemAccessRule` | **exact** | **lossy** — strips `0x00100000` |
| `icacls` | **impossible** | **exact** (`W,D,DC`) |

Native bit fidelity, measured:

| wrote | got | exact |
|---|---|---|
| `0x000d0156` | `0x000d0156` | yes |
| `0x00110156` | `0x00010156` | **no** |
| `0x00100000` | `0x00000000` | **no** |
| `0x00120089` | `0x00020089` | **no** |
| `0x00110157` | `0x00010157` | **no** |

Hence: **apply with the native path, restore with `icacls`.** `Set-Acl` is
unusable — it round-trips the audit section and demands `SeSecurityPrivilege`.
The native path binds to `AccessControlSections::Access` only:

```
DirectoryInfo.GetAccessControl(AccessControlSections::Access)
DirectoryInfo.SetAccessControl(acl)
```

### Rejected mechanisms, and why

| mechanism | result |
|---|---|
| `Set-Acl` | `SeSecurityPrivilege` required |
| `SetSecurityDescriptorSddlForm` + `SetAccessControl` | `SeSecurityPrivilege` required |
| `icacls /save` + `/restore` | "Not all privileges or groups referenced are assigned to the caller"; 0 files processed |
| raw DACL P/Invoke (`SetNamedSecurityInfoW`) | `1338` / `1340`; **stripped the caller's own FullControl ACE and locked the test directory**. Recovered with `icacls /reset`. Not usable. |

## Rehearsal result (scratch tree, production untouched)

Apply:

```
applied    : True | failure: None
verify     : SUBJECT_DENY_VERIFIED | all correct: True
  subject_runtime  0x000d0156 exact=True sync=False
  runtime          0x000d0156 exact=True sync=False
  model            0x000d0156 exact=True sync=False
  config           0x000d0156 exact=True sync=False
  artifact.bin     0x000d0156 exact=True sync=False
```

Apply then restore:

```
snapshot masks: ['0x00110156']
applied    : True | verify: SUBJECT_DENY_VERIFIED
masks now  : ['0x000d0156']

all_restored: True
  subject_runtime  0x00110156 -> 0x00110156 restored=True
  runtime          0x00110156 -> 0x00110156 restored=True
  model            0x00110156 -> 0x00110156 restored=True
  config           0x00110156 -> 0x00110156 restored=True
  artifact.bin     0x00110156 -> 0x00110156 restored=True

after rollback masks: ['0x00110156']
every path == snapshot: True
```

Rollback is bit-exact on every path, including a pre-existing file.

## Fail-closed properties

- `apply_subject_deny` refuses without `confirm=True`.
- Refuses again if any live mask is not the recorded pre-change mask — a change is
  never applied to a state it was not written against.
- `applied` requires **no failures AND** full verification. An earlier version
  derived it from verification alone and reported VERIFIED for an aborted run.
- A mask with no measured-exact `icacls` token set is reported as not restorable
  rather than approximated.
- Every path is verified against the snapshot after restore; a mismatch is not
  rounded up to success.

## Defects found and fixed during this work

1. **Partial apply reported VERIFIED.** The loop broke on first error and `applied`
   came from the verification alone, so an aborted run passed because the paths it
   had reached were correct. Now every path is attempted and both conditions gate.
2. **`write_ok` was unreliable.** `_ps` returns non-zero when PowerShell emits any
   error record; a write reported failure while the descriptor was in fact correct.
   `matches_snapshot` is now the sole authority.
3. **File writes rejected inheritance flags.** `SetAccessRule` on a FILE raises
   "No flags can be set", aborting the apply. Files now get `InheritanceFlags::None`;
   the mask is identical either way.
4. **Restore read-back was broken.** `subject_deny_masks(path)` routes through
   `staging_root`, which appends `subject_runtime`; passing a *file* produced a
   nonexistent path and an empty reading. Split out `_mask_reading(targets)`.
5. **M010 violation: stdin left attached.** M010 requires every `subprocess.run` in
   `foundation/` to pass `stdin=`, so a child cannot inherit a console and block on
   a prompt. All three call sites in `subject_deny.py` violated this. Fixed with
   `stdin=subprocess.DEVNULL`.

## Test results

- `tests/test_subject_deny.py` — **14 passed** (was 11; three added for the round
  trip and the mechanism asymmetry).
- M010 — **12 passed**, including the stdin rule that had caught defect 5.
- Full portable — **1964 passed, 11 failed, 2 warnings, 749 subtests**.
  The 11 failures are the pre-existing set recorded at `3c91b34` (old
  `traverse_directory` / `read_disposable_file` operation-name expectations, and
  staged fixture assertions). **No new failures.**
- Host-security — not re-run; unchanged at 15 failed / 10 passed.

## Production state

Unchanged and verified after all of the above:

```
status: SUBJECT_DENY_NOT_VERIFIED
masks : ['0x00110156']
paths : 7
```

`WRITE_DAC` and `WRITE_OWNER` remain **unenforced in production**. The
measurement substrate is corrected; the production boundary is not.

## NOT_TESTABLE

- Unattended subject launch.
- Runtime execution under the subject.
- Model execution under the subject — no model has been selected or staged.
- `M005` byte-identity: unchanged, 13 paths, 5 digests.

## Residual, not fixed here

Root, `model` and `config` carry an allow mask of `R`, which lacks
`FILE_TRAVERSE`, so the subject cannot descend the tree at all. Preserving the
existing allow mask was a stated constraint, so this is reported rather than
silently broadened. Fixing it is a separate governed decision.
