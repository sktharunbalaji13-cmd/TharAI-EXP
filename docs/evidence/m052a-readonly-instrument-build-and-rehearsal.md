# M052A — Read-Only Instrument Built and Disposably Rehearsed

```
M052A_STATUS                  = INSTRUMENT_BUILT_AND_DISPOSABLY_VALIDATED
SUBJECT_LAUNCH                = NOT_ATTEMPTED
LIVE_AUTHORIZATION_CONSUMED   = NO
SIX_OPERATIONS                = FROZEN
DISPOSABLE_REHEARSAL          = PASS
MUTATION_PATH                 = ABSENT_AND_TESTED
PRODUCTION_CHANGED            = NO
PRODUCTION_ACL_CHANGED        = NO
M046_EVIDENCE                 = PRESERVED
M050_EVIDENCE                 = PRESERVED
IDENTITY_OBSERVATION          = M049_MECHANISM_REUSED_AND_VALIDATED
CLIENT_SOURCE_HASH            = ede087fd1379d9537cf2662451630178ee976690775c544dc662ba3ba889a193
CLIENT_EXE_HASH               = 63893e34a7700bce0780bf2a2ef88ecfbd10ef1d0b6fee6484f945ec088a90ba
LAUNCHER_HASH                 = NOT_BUILT_M052A_DELIBERATELY_DEFERS_IT
WRITER_HASH                   = UNCHANGED_M049_REUSED
TEST_RESULT                   = 107_passed_3_skipped
```

> **No subject was launched and the M052 authorisation was not consumed.** `Last logon` is
> unchanged. Production untouched. The instrument exists, is statically proven mutation-free, and
> has executed all six frozen operations end to end against the real writer.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Why M052A existed

M052 froze six read-only operations and a validator, and reported
`IMPLEMENTED_VALIDATED_AWAITING_HUMAN_AUTHORISATION`. That label was **wrong**: the *taxonomy* and
*validator* existed, but no instrument did. Phase 3 of M052 therefore had nothing to launch —
`m043_pipe_client.exe` only sends a nonce payload and touches no filesystem path, and the M027 probe
cannot substitute because **14 of its 21 operations mutate**.

Spending a one-shot authorisation on that would have bought first-run debugging. M052A builds and
proves the instrument instead, and defers the launcher to the live milestone.

## 2. Phase 1–2 — the client, and why "read-only" is structural

`foundation/m052a_readonly_client.cs`. Every filesystem handle is obtained through one function:

```csharp
private static IntPtr OpenReadOnly(string path, uint access)
{
    if ((access & FORBIDDEN_MASK) != 0)
        throw new InvalidOperationException(...);   // refuses BEFORE the handle exists
    return CreateFileW(path, access, ...);
}
```

`FORBIDDEN_MASK` covers `FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `FILE_WRITE_EA`,
`FILE_DELETE_CHILD`, `FILE_WRITE_ATTRIBUTES`, `DELETE`, `WRITE_DAC`, `WRITE_OWNER`,
`GENERIC_WRITE` and `GENERIC_ALL`. The guarantee does not depend on any caller having chosen well.

**The six frozen masks are used verbatim** — `0x0001`, `0x0088`, `0x0001`, `0x0020`, `0x0020`,
`0x0020`. No frozen value was changed, so no governance discrepancy arose.

## 3. Phase 1 — static validation proves absence, not intent

`tests/m052a_instrument.py::validate_static` strips comments and string literals, then scans the
remaining code for **35 forbidden APIs** and three forbidden access-mask names. Result:

```
mutation_path                 ABSENT_AND_STATICALLY_PROVEN
forbidden APIs checked        35
aliased pipe send sites       1
guard precedes handle         True
operations present            6
```

Two points worth stating plainly:

- **`GENERIC_WRITE` and `GENERIC_ALL` are deliberately not even *named*** as constants in the
  source. Their values are already refused inside `FORBIDDEN_MASK`; declaring them would have put
  the identifiers into the file for no benefit.
- **The one legitimate write is to a pipe, not a file.** The `WriteFile` export is aliased to
  `SendToPipe`, so the source shows exactly one send site and no filesystem `WriteFile` at all.

Tests prove the validator **can fail** (fed a synthetic source calling `DeleteFileW`) and that a
name mentioned only in a **comment does not satisfy it** — the sixth-recurring prose-vs-code trap,
now covered explicitly.

## 4. Phase 8 — the rehearsal caught a crash that a live launch would have spent the attempt on

First rehearsal run: `AccessViolationException` in `SendToPipe`, writer `REFUSED:
empty_submission`.

Cause: the `WriteFile` P/Invoke was declared with **three** parameters instead of five, leaving
the argument list misaligned. `FlushPipe` was also declared without an `EntryPoint`, so it named
an export that does not exist.

**This is the entire argument for M052A.** A one-shot live authorisation would have been consumed
to discover a three-argument P/Invoke.

Fixed, rebuilt, re-rehearsed: `client_exit_code 0`, `writer_status OK`, all six operations
reported, provenance separated.

## 5. Phase 7 — the disposable topology had to *reproduce the ACL shape*, not merely exist

The first passing rehearsal was **not sufficient**. It returned `ACCESS_GRANTED` for
`execute_data_denied`, because a plain temp directory grants execute on everything — so the
**denial branch was never exercised**, and the instrument would have looked validated with one of
its two outcomes untested.

The fixture now shapes the ACLs:

```
runtime/payload.bin : (RX)   execute allowed   -- T-BABY-5 runtime half
config/config.bin   : (R)    execute absent    -- T-BABY-5 data half
```

Final rehearsal — every operation at its frozen mask, with the expected classification:

| Operation | Access | Result |
|---|---|---|
| `read_protected_data` | `0x0001` | `ALLOWED` |
| `read_attributes_and_ea` | `0x0088` | `ALLOWED` |
| `list_directory` | `0x0001` | `ALLOWED` |
| `traverse_and_descend` | `0x0020` | `ALLOWED` |
| `execute_runtime_payload` | `0x0020` | `ACCESS_GRANTED` |
| `execute_data_denied` | `0x0020` | **`DENIED`** |

**Both T-BABY-5 branches are now exercised.** Payload 1740 bytes; provenance separated; identity
observation in the writer half; `mutation=none` on all six; `identity_claim=none` on all six.

`model/` is **not** created — the rehearsal reproduces production's absence so the client's
`model=ABSENT` branch is exercised honestly rather than manufacturing topology.

## 6. Phase 5 — provenance separation holds

Reused **unchanged**: `m049_writer.IdentityObservingWriter(tw.WriterConfig(...))`. No new trust
boundary, and the identity observation stays exactly where M050 validated it. A test asserts the
M049 writer contains no reference to M052.

```
provenance_separated                True
identity_observation_in_writer_half True
nonce_in_subject_half               True
no_identity_claim_in_subject        True
payload digest independently recomputable  True
```

## 7. Phase 11 — build provenance

```
compiler            C:\WINDOWS\Microsoft.NET\Framework64\v4.0.30319\csc.exe
compiler_version    Microsoft (R) Visual C# Compiler version 4.8.9221.0
source_sha256       ede087fd1379d9537cf2662451630178ee976690775c544dc662ba3ba889a193
binary_sha256       63893e34a7700bce0780bf2a2ef88ecfbd10ef1d0b6fee6484f945ec088a90ba
bytes               10752
pe_classification   VALID_NATIVE_PE
```

**Byte-reproducibility is not claimed.** `csc` embeds a timestamp and MVID, so the binary digest
identifies *this build*, as recorded for M039 and M043.

## 8. What the rehearsal does NOT prove

```
EVIDENCE_CLASS = DISPOSABLE_PROTOCOL_VALIDATION_NOT_PRODUCTION_MEASUREMENT
```

The rehearsal ran with the **operator** token, not `BABY_AI_TEST`. It demonstrates:

- pipe connection, client protocol, writer behaviour, token-observation plumbing;
- operation execution machinery and result classification;
- provenance separation, payload hashing, renderer behaviour.

It demonstrates **nothing** about what the real subject can do on production. Those results are
`DISPOSABLE_*` and are labelled as such in the freeze record.

## 9. Phase 13 — freeze

```
milestone                    M052A
operations                   6 frozen
access_masks                 all six verbatim
mutation_path                ABSENT_AND_STATICALLY_PROVEN
disposable_rehearsal_pass    true
subject_launch_attempted     false
live_authorization_consumed  false
freeze gate                  PASS, drift []
```

## 10. Integrity

```
production fingerprint v1/v2   UNCHANGED, exact
production subject ACEs        0 of 8
verify_boundary()             STAGING_BLOCKED
model                         absent
M046 evidence                 PRESERVED
M050 evidence                 PRESERVED
HEAD                          6766c5b, nothing staged
Last logon                    unchanged — no subject launched
```

No production guard weakened. No ACL change. No mask. No model. No inference. No M053.

## 11. Tests

```
tests/test_m052a_instrument.py  +  tests/test_m052_readonly.py
107 passed, 3 skipped in 5.56s
```

The 3 skips are the build-provenance tests, which skip when the client is already built because
provenance is recorded at build time.

Three failures during drafting were **my tests being wrong**, not the instrument's: one asserted
that a prose-only file passes full validation (it should fail for other reasons — the assertion now
targets the specific forbidden-API finding), one passed a `str` where a `Path` was expected, and
one flagged the harness's own `FORBIDDEN_APIS` denylist as a privilege call — the sixth-recurring
prose-vs-code trap, now fixed by tokenising the Python and stripping literals from the C#.

## 12. Phase 14 — the human gate

**The M052 authorisation was not consumed and must not be silently reused.**

```
M052_LIVE_AUTHORIZATION_STATUS = REQUIRES_FRESH_HUMAN_EXECUTION
```

The next authorisation must explicitly read:

> *"I authorize exactly one M052 live read-only subject measurement launch using the frozen M052A
> instrument and covering the six specified read-only operations."*

**`LAUNCHER_HASH = NOT_BUILT_M052A_DELIBERATELY_DEFERS_IT`.** No `m052_launch.cmd` exists. Writing
it is the first act of the live milestone, because a launcher must bake in the absolute paths and
be rehearsed in its final form — building it here and freezing it would create a second untested
artefact.

### Before the live launch, two things must still happen

1. **Write and rehearse `m052_launch.cmd`**, reusing the M049 writer path and the M044 rehearsal
   pattern, so the launcher's own plumbing is proven before a human is asked for a password.
2. **Re-run the freeze gate.** It already detects drift in the client source and executable.

## 13. Epistemic boundary

Unchanged. There is **no model, no inference, no cognitive substrate, and no consciousness claim**.
Baby AI has still not been born. A verified subject *account* is not a mind, and a readable file is
not thought.

M052A built and proved an instrument. It moved no evidence about the subject whatsoever.