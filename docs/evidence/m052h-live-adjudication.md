# M052H — Post-Live Evidence Preservation and Adjudication

```
M052H_STATUS            = LIVE_MEASUREMENT_COMPLETE_T_BABY_1_SATISFIED
ATTEMPT_CONSUMED        = YES  (exactly one, nonce 0ff26391838144f5)
T_BABY_1_FINAL_STATUS   = SATISFIED

SUBJECT_PID             = 21044
SUBJECT_SESSION         = 4
SUBJECT_SID_OBSERVED    = S-1-5-21-2406520953-1060965512-844951592-1022
SUBJECT_SID_EXPECTED    = S-1-5-21-2406520953-1060965512-844951592-1022   EXACT MATCH
TOKEN_OBSERVATION_STATUS= VERIFIED  (identity_is_independently_observed = true)
INTEGRITY_LEVEL         = MEDIUM
ELEVATED                = FALSE
PRIVILEGES              = []  (none)

TARGET_PATH             = C:\ProgramData\TharAI\observation\T_OBSERVATION_NAMESPACE\observation_input.v1
TARGET_HASH_EXPECTED    = e8bc90c43df7430c0ac556187dc0e052985a683ed80ea6325d01cd09ca92d50c
TARGET_HASH_OBSERVED    = e8bc90c43df7430c0ac556187dc0e052985a683ed80ea6325d01cd09ca92d50c   MATCH
TARGET_BYTES_EXPECTED   = 319
TARGET_BYTES_OBSERVED   = 319
READ_RESULT             = ALLOWED   (winerror 0, attempted=true)
READ_BYTES              = 319

PAYLOAD_HASH            = b841703e50fe83cd28da214527821571d2454cf817f5d64101682710ff51fbc2  (recomputed)
EVIDENCE_DIRECTORY_DIGEST = 1f46da64cb26ffcb800a4f40e9b873c17e278ed74f2adcac9b0ff43d0578140a
PRESERVATION_COPY_DIGEST = 1f46da64cb26ffcb800a4f40e9b873c17e278ed74f2adcac9b0ff43d0578140a  IDENTICAL
PROVENANCE_ARTIFACT_HASH  = f469da570002fbd94c0f370b5b6189a309846a30b813dec14d44d464d735b843
INSTRUMENT_HASH         = 132cdc5d26486884cdfa4c7aa1206974037e593a5e20cb47d4e056614b54a948
LAUNCHER_HASH           = 8fe6e906f09c532b53612bb1726c455696410859bd093480e7ddbf8961d1b997
WRITER_HASH             = 6b3b2eee75455a9479dbabcc0933cbb19b08678765bc41df8d204dbab1a3e6d3

OBSERVATION_OBJECT_CHANGED = NO      NAMESPACE_CHANGED      = NO
NAMESPACE_ACL_CHANGED       = NO      PROVENANCE_CHANGED     = NO
CANONICAL_T_CHANGED         = NO      PRODUCTION_CHANGED    = NO
M016_CHANGED                = NO      MODEL_PRESENT         = NO
CONFIG_CHANGED              = NO
```

> **The attempt is consumed. There is no retry.** Nothing was launched again, repaired, rebuilt or
> regenerated. Adjudication was performed from the preserved evidence directory, not from the
> console transcript.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Preservation — done first, before any inspection

```
LIVE      : %TEMP%\TharAI_M052H_live                        6 files
PRESERVED : %TEMP%\TharAI_M052H_preserved_0ff26391838144f5  6 files
aggregate : 1f46da64cb26ffcb800a4f40e9b873c17e278ed74f2adcac9b0ff43d0578140a  (both)
```

| File | Bytes | SHA-256 |
|---|---|---|
| `m042_evidence.txt` | 2783 | `f469da570002fbd94c0f370b5b6189a309846a30b813dec14d44d464d735b843` |
| `writer_stdout.json` | 892 | `0fb0548239edc5d47d84436e6fee8fe07ae2bde8b4f3732ca12337bbb23f072b` |
| `writer_ready.json` | 162 | `3a34b82ce67d57728b6c0eadc357781b1676c5030b06879d4bfeb3fa2d4f475d` |
| `preflight.txt` | 648 | `ca02d1dd63b7882ca23f549845cbc71575280db44162c740a711bbb2e5dda352` |
| `hashcheck.txt` | 36 | `def0dbfe77729fe7464b1f2d13e67494a1c7cae72541ed370847ba635e30767a` |
| `writer_stderr.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Copy is **byte-identical**; the live root was neither deleted nor altered.

### Payload hash independently recomputed

The subject payload was extracted from the preserved artefact and re-hashed:

```
writer-recorded : b841703e50fe83cd28da214527821571d2454cf817f5d64101682710ff51fbc2
recomputed      : b841703e50fe83cd28da214527821571d2454cf817f5d64101682710ff51fbc2   MATCH
payload bytes   : 799  (writer recorded 799)
```

---

## 2. Identity — externally observed, and only externally

```
launcher  ->  client PID 21044  ->  process token  ->  SID
writer client_pid            : 21044
M049 block client_pid        : 21044      (agree)
client_session_id            : 4
observation_status           : VERIFIED
identity_is_independently_observed : true
user_sid                     : S-1-5-21-2406520953-1060965512-844951592-1022
expected                     : S-1-5-21-2406520953-1060965512-844951592-1022   EXACT
opened / failed_call / read_only : true / null / true
```

### What was *not* accepted as identity evidence

| rejected source | why |
|---|---|
| launcher text | it asserts a username; it does not observe a token |
| subject self-report | the client emits `identity_claim=none_this_client_does_not_report_identity` |
| expected-SID argument | a guard passed to the writer, not an observation |
| `whoami` alone | reports the operator, and would not run as the subject |
| operator-side rehearsal | the operator's token is not the subject's token |
| console transcript | not the evidence artefact |

Verified by inspection of the artefact itself: the M049 block appears **only** in the writer's half,
and the subject half contains **no SID and no PID**. That is the correct shape — the client cannot
report its own identity even if it wanted to.

### The legacy `token_verified: false` field

The outer M042 field still reads `false`. As recorded in M050 and M052B, this is a **schema-coherence
artefact of the older M042 writer**, whose own provenance text states it cannot resolve a token
without `SeImpersonatePrivilege` — a privilege this laboratory refuses to acquire. The M049 block was
added precisely to establish this fact and does so. The legacy field *under*-claims relative to the
M049 block; it is not a competing negative finding.

---

## 3. The read — an actual data read, not a successful open

```
op                : read_protected_data        t_property : T-BABY-1
requested_access  : 0x00000001                 attempted  : true
result            : ALLOWED                    winerror   : 0

bytes_read                            = 319
expected_bytes                        = 319
observed_sha256                       = e8bc90c43df7430c0ac556187dc0e052985a683ed80ea6325d01cd09ca92d50c
expected_sha256                       = e8bc90c43df7430c0ac556187dc0e052985a683ed80ea6325d01cd09ca92d50c
length_match                          = true
hash_match                            = true
hash_computed_over_bytes_actually_read = true
open_success_alone_is_not_a_pass      = (stated by the instrument)
```

The hash was computed **over the bytes the subject actually received**, and matches the frozen
object exactly. A successful `CreateFile` alone would not have discharged this property — and the
instrument records that distinction itself.

Single operation, no fallback, no target argument:
`target_binding = COMPILED_IN_CONSTANTS`, `mutation = none`, `mutation_performed = false`.

---

## 4. Post-run integrity — nothing moved

| check | result |
|---|---|
| observation object SHA-256 | `e8bc90c4…` **unchanged** |
| observation object length | 319 **unchanged** |
| namespace owner (all levels) | operator `…-1001` **unchanged** |
| namespace ACL — sealed at all 5 levels | **unchanged** |
| subject effective on governed object | `0x00120089` **unchanged** |
| subject forbidden rights at all levels | **none present** |
| provenance subject access | `0x00000000` **unchanged** |
| namespace freeze gate | `PASS` |
| canonical T | `UNTOUCHED`; namespace paths under T: **NONE** |
| `model/` | **absent** |
| `config/` | **empty** |
| `m016_*` | **3 present, unchanged** |
| production fingerprints | **exact / exact** |
| production subject explicit ACEs | **0 of 8** |
| `verify_boundary()` | `STAGING_BLOCKED` |
| M019 | `M019+A1` `7dceb7a5…` **unchanged**, amendment validation `PASS` |
| D3 | untouched — mask still `0x000D0156` |

`Last logon` advanced to `2026-10-04 19:36:35`, the expected consequence of an authorised interactive
logon.

---

## 5. Security interpretation — measured, not assumed

No write probe was performed, and none was needed. The no-write conclusion comes from **M052G's
frozen measured access contract**, verified again post-run:

```
subject read : FILE_READ_DATA, FILE_READ_ATTRIBUTES, FILE_READ_EA   (effective 0x00120089)
absent       : FILE_WRITE_DATA, FILE_APPEND_DATA, DELETE, FILE_DELETE_CHILD,
               FILE_WRITE_EA, FILE_WRITE_ATTRIBUTES, WRITE_DAC, WRITE_OWNER
provenance   : subject effective 0x00000000 -- unreachable, not merely unwritable
```

*"The program did not attempt to write"* is **not** the security evidence. The evidence is the
measured effective-access contract, which M052G established and this milestone re-verified after the
live run.

---

## 6. Conditions A–K

| | condition | verdict | evidence |
|---|---|---|---|
| **A** | frozen namespace used | **PASS** | `namespace_identifier=T_OBSERVATION_NAMESPACE`, `target_binding=COMPILED_IN_CONSTANTS`; target path is the frozen one |
| **B** | frozen observation object used | **PASS** | observed SHA-256 equals the frozen `e8bc90c4…` |
| **C** | live subject process observed | **PASS** | PID 21044, session 4, token read at pipe-connection time while the process existed |
| **D** | exact `BABY_AI_TEST` SID externally observed | **PASS** | `…-1022`, `VERIFIED`, `identity_is_independently_observed = true` |
| **E** | actual object read occurred | **PASS** | `attempted=true`, 319 bytes, hash over bytes actually read |
| **F** | all 319 bytes read | **PASS** | `bytes_read=319`, `length_match=true` |
| **G** | observed hash matches frozen hash | **PASS** | both `e8bc90c4…` |
| **H** | external provenance established | **PASS** | writer provenance + M049 block; payload separated; `subject_artefact_rights 0x00000000` |
| **I** | no mutation occurred | **PASS** | object, ACLs, owner, provenance, canonical T, production all unchanged |
| **J** | canonical T unchanged | **PASS** | `UNTOUCHED` |
| **K** | production unchanged | **PASS** | fingerprints exact, 0 of 8 ACEs, `STAGING_BLOCKED` |

All eleven independently established. **No condition was inferred from another.**

---

## 7. Historical separation — M052B and M052H are not merged

| | M052B | M052H |
|---|---|---|
| topology | pre-A1 | M019+A1 |
| target | `runtime/m016_read_fixture.exe` | governed `T_OBSERVATION_NAMESPACE` object |
| location | **inside canonical T** | **outside canonical T** |
| bytes | 25 | 319 |
| nonce | `e978330eb5e746c0` | `0ff26391838144f5` |
| PID / session | 25292 / 4 | 21044 / 4 |
| A1-compliant | **no** | **yes** |
| status | historically valid; **not** T-BABY-1 evidence | dispositive for T-BABY-1 |

M052B's evidence is **byte-identical and unmodified** (`df902a39…`). The ledger records
`m052b_contributed = False` for T-BABY-1 and `established_by = M052H`, so the basis is named and
cannot later drift into M052B's credit.

---

## 8. Ledger update

`T-BABY-1`: `NOT_ESTABLISHED` → **`SATISFIED`**, `blocking_state` → `NOT_BLOCKED`,
`established_by` → `M052H`. It left the blocking map entirely.

```
SATISFIED                13   (7 pre-existing on M019's evidence, 6 established by M052B, 1 by M052H)
PARTIALLY_SATISFIED       3
NOT_ESTABLISHED           3   T-PATH-1, T-PATH-2, T-WR-11
NOT_MEASURABLE            1   T-OWN-3
NOT_TESTED_BY_M052B      16
BLOCKED_TOTAL            24   (22 decision-gated, 2 rehearsal-gated, 0 implementation-gated)
```

**M019+A1 was not modified. T-PATH-2 was not altered. D3 was not touched.**

Three corrections were needed to keep the ledger honest, each caught by its own tests rather than by
inspection: T-BABY-1 had to leave the blocking map (it was being re-marked blocked by a map written
for the pre-M052H world); the tally had to report *all* blocking states including zeros, because a
key that vanishes reads worse than a `0`; and three tests asserted the pre-M052H state of a property
that has since been established.

---

## 9. What this establishes — and only this

> The externally identified `BABY_AI_TEST` subject process successfully read the governed
> observation object under the measured OS access contract.

**T-BABY-1 is established**: the subject can read data within the boundary, observed at OS level by a
token externally verified as `BABY_AI_TEST`, against a governed, provenance-bound, non-fixture object
outside canonical T, with the read verified by content hash rather than by a successful open.

It establishes **nothing** about cognition, consciousness, subjective experience, agency, learning,
memory, intelligence, developmental stage, sentience, model inference, or self-awareness. A
filesystem read is evidence about a permission and an object. It is not evidence about a mind, and no
amount of this class of evidence would be.

---

## 10. STOP

Adjudication complete. Not proceeding to D3, ACL remediation, model acquisition, model inference,
birth, or any cognitive or developmental experiment.

The next milestone must be **designed from this evidence state**, not assumed in advance. The
honest starting position is that one of thirty-six properties is now established by direct live
observation; twenty-four remain gated on decisions this laboratory has deliberately not yet taken.