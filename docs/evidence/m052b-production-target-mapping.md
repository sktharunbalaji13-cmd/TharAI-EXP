# M052B — Production Target Mapping Established and the Read-Only Instrument Re-frozen

```
M052B_STATUS                   = READY_FOR_FRESH_HUMAN_AUTHORIZATION
M052A_CLIENT_HASH              = ede087fd1379d9537cf2662451630178ee976690775c544dc662ba3ba889a193 (source)
                                 63893e34a7700bce0780bf2a2ef88ecfbd10ef1d0b6fee6484f945ec088a90ba (exe, 10752 B)
M052B_CLIENT_SOURCE_HASH       = 7f86d852d3a03c5b320fc4168bd4b42acf235f8c7d114a36fc0d40b12719dbc4
M052B_CLIENT_EXE_HASH          = c26b14523c0f48698a7563270752daa8938c04b189b523c2ded4abfd54511b84 (12800 B)
M049_WRITER_HASH               = 6b3b2eee75455a9479dbabcc0933cbb19b08678765bc41df8d204dbab1a3e6d3 (unchanged)
M052B_LAUNCHER_HASH           = 40633e3ae490fea575345e1b8272b8cf0909f173726bf4090fe95fb26487a0b2 (8667 B)
MAPPING_DIGEST                 = a504bd2f25016a9eb7b5be36b403e3d3a8225ff0d3157dece8d8763fd6178122
PRODUCTION_TARGET_MAPPING      = ESTABLISHED_5_MEASURABLE_1_NOT
DISPOSABLE_TARGET_MAPPING      = DERIVED_FROM_PRODUCTION_MAPPING
TARGET_TOPOLOGY_EQUIVALENCE    = PROVEN_NOT_ASSERTED
EXECUTE_DATA_DENIED_STATUS     = NOT_MEASURABLE_ON_CURRENT_PRODUCTION_TOPOLOGY
MUTATION_PATH                  = ABSENT_AND_STATICALLY_PROVEN
DISPOSABLE_REHEARSAL           = PASS_BOTH_QUESTIONS_AND_LAUNCHER
PRODUCTION_CHANGED             = NO
PRODUCTION_ACL_CHANGED         = NO
LIVE_AUTHORIZATION_CONSUMED    = NO
SUBJECT_LAUNCH                 = NOT_ATTEMPTED
M046_EVIDENCE                  = PRESERVED
M050_EVIDENCE                  = PRESERVED
MODEL_PRESENT                  = NO
TEST_RESULT                    = 24_passed_M052B__266_passed_across_M042_to_M052B
```

> **NO PRODUCTION TARGET WAS CREATED TO SATISFY THIS MEASUREMENT.**
>
> **THE PREVIOUS M052 AUTHORIZATION IS VOID AND WAS NOT CONSUMED.**
>
> No subject was launched. `runas` was never executed. `Last logon` is unchanged at
> `2026-10-04 13:25:57` (the M050 baseline). Production fingerprints exact, subject explicit ACEs
> still **0 of 8**, `verify_boundary() = STAGING_BLOCKED`, `model/` still absent, `config/` still
> empty.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. The defect M052B corrects, stated plainly

M052A's client hardcoded two filenames **that the M052A rehearsal fixture had invented**:

```
runtime\payload.bin
config\config.bin
```

Neither has ever existed in production. `payload.bin` and `config.bin` appear **nowhere** in the
repository. So M052A's rehearsal was structurally equivalent to production for *ACL shape* while
silently assuming *target identity*: it proved the client could classify an access decision on a
constructed object, not that it would classify one about the object that actually exists.

Launching M052A would have spent the single authorised attempt on four `FILE_NOT_FOUND` results.

Worse — and this is the part that makes it a methodology failure rather than a fixture bug — M052A
emitted `result=DENIED` for **any** failed `CreateFileW`, without inspecting the Win32 error. So
`execute_data_denied`, whose expected result is `DENIED`, would have reported:

```
result=DENIED  winerror=2
```

`winerror=2` is `FILE_NOT_FOUND`. It is not `ACCESS_DENIED`. The instrument could not tell a
missing file from a refused one, and the one operation whose expected outcome is a denial was the
one most likely to fabricate it.

---

## 2. What production actually offers

```
subject_runtime\
  config\                                    EMPTY  (0 entries)
  runtime\m016_disposable_target.exe          0 B
  runtime\m016_read_fixture.exe              25 B  b"m016 read fixture payload"
  runtime\m016_subjectrun_fixture.exe         0 B
```

Two facts follow, and both constrain the measurement:

1. **No production artefact is a loadable image.** None begins `MZ`. T-BABY-5's *loadability* half
   is therefore unmeasurable on the current production topology.
2. **`config\` contains no data file at all.** T-BABY-5's *data-execute denial* has no object to be
   measured on.

Production subject effective access is `0x001301BF` on every measured object, with `FILE_EXECUTE`
set.

---

## 3. The production target mapping

`tests/m052b_target_mapping.py`, verdict `CONSISTENT`, digest
`a504bd2f25016a9eb7b5be36b403e3d3a8225ff0d3157dece8d8763fd6178122`. Every existence claim is
re-checked against the live tree on each call; if production drifts the verdict becomes `STALE`
rather than quietly disagreeing with the instrument.

| # | Operation | Mask | Production target | Exists | Suitable | Measurable | Scope |
|---|---|---|---|---|---|---|---|
| 1 | `read_protected_data` | `0x0001` | `runtime/m016_read_fixture.exe` | yes | yes | **yes** | FULL |
| 2 | `read_attributes_and_ea` | `0x0088` | `runtime/m016_read_fixture.exe` | yes | yes | **yes** | FULL |
| 3 | `list_directory` | `0x0001` | `runtime/` | yes | yes | **yes** | FULL |
| 4 | `traverse_and_descend` | `0x0020` | `./`, `runtime/`, `config/` (`model/` **expect_absent**) | yes | yes | **yes** | PARTIAL |
| 5 | `execute_runtime_payload` | `0x0020` | `runtime/m016_read_fixture.exe` | yes | yes | **yes** | PARTIAL |
| 6 | `execute_data_denied` | `0x0020` | **none** | **no** | **no** | **NO** | NONE |

### 3.1 A target was not chosen merely because it exists

`runtime/m016_read_fixture.exe` was selected for operations 1, 2 and 5 because it is the **only**
production runtime artefact with non-empty content. The two 0-byte siblings would satisfy a bare
`CreateFileW` and make `read_protected_data` **vacuous**: `bytes_read=0` would prove the *open*
succeeded, not that content is readable. Its content is literally `b"m016 read fixture payload"` —
it is the read fixture. Semantics chose it; existence alone would not have.

Operations 1 and 2 are deliberately bound to the **same object**, so that any disagreement between
them is a property of the access mask rather than of target selection.

### 3.2 Operation 4 — `model/` is expected absent

`traverse_and_descend` declares `expect_absent=("model/",)`. Production has no `model/`, the client
records it as `ABSENT` and continues, and nothing creates it. The mapping's existence check honours
`expect_absent`, because "all declared targets must exist" is the wrong assertion for a directory
whose absence is the point.

### 3.3 Operation 5 — access measurable, loadability not

The `FILE_EXECUTE` **access grant** is measurable and is what the operation observes:
`CreateFileW` with `FILE_EXECUTE` only, never a load, map or launch. T-BABY-5's *loadability* half
is recorded `NOT_MEASURABLE_NO_VALID_IMAGE_IN_PRODUCTION_RUNTIME`. `ACCESS_GRANTED` therefore does
**not** mean loadable and must never be reported as such.

### 3.4 Operation 6 — option (c), and why each alternative was rejected

```
EXECUTE_DATA_DENIED = NOT_MEASURABLE_ON_CURRENT_PRODUCTION_TOPOLOGY
```

`config\` is empty, so there is no data file to attempt.

Rejected alternatives:

* **Point it at the runtime payload.** Operations 5 and 6 would then request the same mask `0x0020`
  on the same object under the same token while expecting **opposite** outcomes. One of those
  expectations is necessarily false. The measurement would be self-contradictory.
* **Point it at the empty `config\` directory.** Directory execute is not data-file execute.
  Substituting one for the other is not a weaker measurement; it is a different question.
* **Create `config\config.bin`, or copy a runtime file into `config\`.** A production mutation.
  Forbidden, and exactly the move the milestone exists to prevent.

A `NOT_MEASURABLE` record is **not** a denial, **not** an `ACCESS_DENIED` observation, and **not** a
failed attempt. It is the absence of an object to measure.

### 3.5 A recorded prediction, explicitly not a measurement

Production subject effective access is `0x001301BF` on every measured object, with `FILE_EXECUTE`
set. So *if* a data file were ever placed in `config\` under inherited ACLs, T-BABY-5's data-execute
denial would probably **not** be enforced.

This is descriptor inference from `BASELINE_SUBJECT_SIDS`. It is **not** an observation by the
subject and **not** a measurement. It is recorded in the module so that the later milestone able to
test it begins from an explicit hypothesis rather than from an assumption.

---

## 4. The four corrections to the instrument

`foundation/m052b_readonly_client.cs` — a **new** file. M052A's source and executable are preserved
untouched as historical evidence, and a test asserts their digests.

1. **Win32 error classification.** Every failed open now routes through `ClassifyOpenFailure()`,
   which maps the error to `DENIED` (only `ACCESS_DENIED`=5 and `PRIVILEGE_NOT_HELD`=1314),
   `TARGET_ABSENT` (`FILE_NOT_FOUND`=2, `PATH_NOT_FOUND`=3), or `ERROR` for everything else. An
   unrecognised code is `ERROR`, never `DENIED`: over-reporting a denial corrupts the T-property
   reading, while under-reporting one merely leaves a gap.
2. **Real production targets.** Operations 1, 2 and 5 bind to `runtime/m016_read_fixture.exe`.
3. **Operation 6 fabricates nothing.** It enumerates `config\`, finds no data file, performs **no
   open**, and emits `NOT_MEASURABLE_NO_DATA_FILE_IN_CONFIG` with `attempted=false`. It references
   no config filename at all, so there is nothing for it to get wrong.
4. **Every record carries `attempted=true|false`**, so an unattempted operation can never be read as
   a refused one.

### 4.1 Execution observation semantics preserved

`execute_runtime_payload` opens an artefact with `FILE_EXECUTE` and does **not** run, load, map or
launch anything. The M052B brief required that if the operation could not measure `FILE_EXECUTE`
without executing code, that be reported as an instrumentation design problem rather than quietly
changed. It does not arise: the operation is an access observation by construction, and no
`CreateProcess`, `ShellExecute`, `LoadLibrary` or `WinExec` appears anywhere — the static scanner
rejects all of them.

### 4.2 Stale target names: a three-tier rule

The validator forbids M052A's fixture filenames with three escalating tiers, because the failures
are not equally serious:

* **hard failure** — a stale name in **code**: a client that would still open an absent path;
* **also a failure** — a stale name in **operational prose**, i.e. after the leading header block.
  Prose sitting next to the constants that replaced the names is how a stale name gets
  reintroduced, so it is reported rather than tolerated;
* **allowed** — a stale name in the **leading header block**, which is where the record of *why* the
  retarget happened belongs, and which the brief permits explicitly.

This rule caught two real occurrences during the build, including one in a comment directly above
`RUNTIME_FILE`. A test deliberately reintroduces a stale name into operational prose and asserts the
validator **raises**, so the guard is proven to fail closed rather than merely to pass.

---

## 5. Two questions, kept apart

The entire correction turns on not conflating these.

### Question A — can the instrument classify an `ACCESS_DENIED` correctly?

**PASS.** Fixture: the production topology **plus** one config data file granted `(R)`, so
`FILE_EXECUTE` is genuinely refused.

```
execute_data_denied -> result=DENIED  winerror=5  attempted=true
evidence_class      = INSTRUMENT_DENIAL_PATH_VALIDATION_ONLY
```

`winerror=5` is a real refusal. This is **not** production evidence and is never reported as a
production denial.

### Question B — does the corresponding production object exist to be measured on?

**NO for `execute_data_denied`.** Fixture: the production topology exactly, with `config\` empty.

```
execute_data_denied -> result=NOT_MEASURABLE_NO_DATA_FILE_IN_CONFIG  winerror=0  attempted=false
evidence_class      = PRODUCTION_SHAPE_REHEARSAL_QUESTION_B
```

`attempted=false` and `winerror=0` are the observable proof that no open was attempted at all.

A green result for A is never reported as a production finding, and B's NO is never softened into a
denial. This discrimination — `winerror 2` versus `winerror 5` — is precisely what M052A could not
make.

---

## 6. Target topology equivalence — proven, not asserted

`assert_topology_equivalence()` compares the fixture against live production for every mapped
target and **hard-fails** on any divergence.

```
topology_equivalent      : True
divergences              : NONE
model_absent_in_both     : True
config_empty_in_both     : True
subject_access_shape     : NOT_REPRODUCIBLE_AND_NOT_ASSERTED
```

Compared: relative path, object type, parent relationship *within the tree*, presence and absence
(including `model\` absent and `config\` empty), and the **bytes** of the one file whose operation
is a content read (`read_protected_data`'s target).

### 6.1 Subject access shape is reported, never asserted

An earlier version of this function compared the subject's effective access in production against
the subject's effective access in the fixture, and it "failed" on every target. That was the
function being wrong, not the fixture: the fixture grants the **operator** stand-in and
deliberately contains **no ACE for `BABY_AI_TEST` at all**, because this milestone must not use the
subject account. It was comparing a real grant against a deliberate absence.

Reproducing the subject's access shape would require the subject account, which is forbidden here.
So production's subject effective access is recorded per row as **descriptor context only** and is
never reported as a rehearsal result.

Exact ACEs deliberately do not match and are not required to: production grants `BABY_AI_TEST`
**0 explicit ACEs** and reaches it through inherited group ACEs — the standing M051 finding — while
the fixture grants explicitly so it *can* shape a denial production does not currently have.

### 6.2 Two comparison bugs the check found in itself

Both were artefacts of the comparison, and both are recorded because a validator that cannot
distinguish its own bugs from the system's is not a validator:

* **parent names.** Comparing `parent.name` compared `TharAI-EXP` against `Temp` and reported the
  tree *root's* parent relationship as a divergence. Neither root has an in-tree parent, so
  both-outside must compare equal.
* **fixture at the wrong path.** The launcher rehearsal built its fixture in a random `mkdtemp`
  while the generated launcher pointed at a fixed root, and the launcher refused with
  `reason=target_root_absent`. That was the launcher's guard working correctly against a wiring
  mistake in the rehearsal.

---

## 7. Disposable rehearsal results

### 7.1 Production-shape rehearsal (question B)

```
client exit / writer status   : 0 / OK
operations reported            : 6
provenance separated           : True
identity observation in writer : True
no mutation declared           : True
REHEARSAL_OK                   : True
```

| Operation | Mask | Target | Result | `attempted` |
|---|---|---|---|---|
| `read_protected_data` | `0x0001` | `runtime/m016_read_fixture.exe` | `ALLOWED` | true |
| `read_attributes_and_ea` | `0x0088` | `runtime/m016_read_fixture.exe` | `ALLOWED` | true |
| `list_directory` | `0x0001` | `runtime/` | `ALLOWED` | true |
| `traverse_and_descend` | `0x0020` | `./,runtime/,model/,config/` | `ALLOWED` | true |
| `execute_runtime_payload` | `0x0020` | `runtime/m016_read_fixture.exe` | `ACCESS_GRANTED` | true |
| `execute_data_denied` | `0x0020` | `config/` | **`NOT_MEASURABLE_NO_DATA_FILE_IN_CONFIG`** | **false** |

### 7.2 Launcher rehearsal

The final launcher, executed exactly as generated, against the production-shape topology:

```
exit_code                       0
hash_guards_passed              True
writer_signalled_ready          True
artefact_created                True
all_six_reported                True
provenance_separated            True
operation6_not_measurable       True
operation6_not_attempted        True
rehearsal_ok                    True
live targets production         True
plumbing identical              True  (26 lines)
```

Live and rehearsal plumbing are byte-identical across all 26 load-bearing lines. The launcher
contains **no** `icacls`, `/grant`, `/deny`, `rd /s`, `rmdir` or `del /s`; it creates only its own
guarded evidence root; and it refuses on hash mismatch, on an absent target root, and on any
pre-existing artefact. The **93/94** exit split is retained: a writer that never came up consumes
nothing, while a subject leg that ran and produced no artefact *is* a consumed attempt.

### 7.3 Batch-template defect avoided

The launcher template is a **raw** string. M052's template was a normal string containing
unintended `\ ` sequences in prose, which produced `SyntaxWarning: invalid escape sequence` and
would become a hard `SyntaxError` in a future Python. Making the literal raw and collapsing `\\` →
`\` preserves every intended single backslash in the emitted batch paths and neutralises the rest.
Verified: `%LIVE_ROOT%\m042_evidence.txt` and `%SystemRoot%\System32\whoami.exe` present, zero
double-backslash paths.

---

## 8. Static mutation safety

```
mutation_path                          ABSENT_AND_STATICALLY_PROVEN
forbidden APIs checked                 40
forbidden access-mask names            GENERIC_WRITE, GENERIC_ALL, MAXIMUM_ALLOWED
guard precedes handle creation         True
aliased pipe send sites                1
stale target names absent from code    True
stale names documented in header       ['payload.bin', 'config.bin']
```

Rejected: `DeleteFile*`, `RemoveDirectory*`, `MoveFile*`, `ReplaceFile*`, `CreateDirectory*`,
`SetFileAttributes*`, `SetFileSecurity`, `SetNamedSecurityInfo*`, `SetSecurityInfo`,
`AddAccessAllowedAce`, `SetEntriesInAclW`, `AdjustTokenPrivileges`, `OpenProcessToken`,
`DuplicateToken`, `ImpersonateNamedPipeClient`, `CreateProcess*`, `ShellExecute`, `WinExec`,
`LoadLibrary`, `WriteProcessMemory`.

The guard is **not** weakened to accommodate target selection: it runs before `CreateFileW` and
refuses any mask carrying a mutating bit. The one write remains the pipe transmission, which is not
a filesystem object.

The M019 taxonomy is unchanged and remains authoritative: **6 families / 36 properties**
(T-ADM 5, T-BABY 10, T-OWN 4, T-PATH 2, T-TRAV 4, T-WR 11). The six frozen operations and their
access masks are unchanged.

---

## 9. Regression accounting — M052B introduced zero regressions

```
266 passed, 11 failed, 3 errors, 2 skipped      (242 passed before M052B; +24 new)
```

The 11 failures and 3 errors are **identical** to the set present before M052B began, and all are
in **M042–M045**:

* `Last logon` advanced through the two *authorised* M046/M050 launches;
* the M046/M050 preservation copies make the evidence-reuse guards fire — correctly. M044's
  `test_the_launcher_plumbing_rehearsal_passes` fails with
  `reason: an artefact already exists in the live root`, which is its guard doing its job.

Tracked modified files are unchanged — still the same four pre-M042 files. M052B added new untracked
files only. These standing reds are left visible and unrepaired, per standing instruction.

---

## 10. Frozen digests

| Artefact | SHA-256 |
|---|---|
| M052A client source *(historical, preserved)* | `ede087fd1379d9537cf2662451630178ee976690775c544dc662ba3ba889a193` |
| M052A client exe *(historical, preserved)* | `63893e34a7700bce0780bf2a2ef88ecfbd10ef1d0b6fee6484f945ec088a90ba` |
| M052B client source | `7f86d852d3a03c5b320fc4168bd4b42acf235f8c7d114a36fc0d40b12719dbc4` |
| M052B client exe (12800 B) | `c26b14523c0f48698a7563270752daa8938c04b189b523c2ded4abfd54511b84` |
| M052B launcher (8667 B) | `40633e3ae490fea575345e1b8272b8cf0909f173726bf4090fe95fb26487a0b2` |
| M049 writer source | `6b3b2eee75455a9479dbabcc0933cbb19b08678765bc41df8d204dbab1a3e6d3` |
| Production target mapping | `a504bd2f25016a9eb7b5be36b403e3d3a8225ff0d3157dece8d8763fd6178122` |

`check_freeze()` = `PASS`, `drift: []`. It verifies the client source, the client executable, the
mapping digest, **and** that live production still matches the mapping — so a production change
after this freeze is detected rather than absorbed.

The M049 writer is byte-identical to the version M050 validated, and the launcher enforces that at
runtime.

`csc` embeds a timestamp and MVID, so these digests identify *a build*, not reproducible content.

A launcher cannot contain its own SHA-256 — a fixed-point problem with no practical solution — so
its digest lives in the freeze record and is verified from outside.

---

## 11. What a live M052 run would and would not establish

**Would establish:** the observed filesystem/access behaviour of the externally identified
`BABY_AI_TEST` process for **five** read-only operations, on the existing production boundary, for
**one** attempt — with `execute_data_denied` recorded as `NOT_MEASURABLE_NO_DATA_FILE_IN_CONFIG`.

**Would not establish:** cognition, consciousness, subjective experience, agency, learning, memory,
developmental progress, usefulness discovery, model inference, pretrained-model behaviour, birth, or
sentience. None of those may be inferred from filesystem behaviour, token identity, or process
behaviour.

Also unchanged: this freeze does **not** upgrade "the M052B instrument is mutation-free" into "the
Baby AI cannot mutate production." The second remains **unmeasured**. And the standing finding
stands — `T-WR = NOT_SATISFIED`, effective access `0x001301BF`, five of eight required denials
absent. M052 observes production; it must never reshape it.

---

## 12. Next gate

```
M052B_STATUS                = READY_FOR_FRESH_HUMAN_AUTHORIZATION
SUBJECT_LAUNCH              = NOT_ATTEMPTED
LIVE_AUTHORIZATION_CONSUMED = NO
```

A **new, fresh** authorisation is required. The previous M052 authorisation is void: it named "the
frozen M052 instrument and launcher", and that instrument no longer exists. It was never consumed.

On receipt, the assistant still **cannot** execute the launch — `runas` requires an interactive
console and `GetConsoleMode` fails with winerr 6. A human runs

```
baby_workspace\m052b_launch.cmd
```

exactly once, types the `BABY_AI_TEST` password into the Windows dialog, and the assistant observes
and adjudicates afterwards. One attempt, no retry; a failure is evidence.

Subsequent milestones remain: M053 disposable-mutation fixture (build and rehearse **before**
authorising), then `WRITE_DAC` / `WRITE_OWNER` last and individually.
