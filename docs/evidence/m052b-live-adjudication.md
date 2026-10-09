# M052B-LIVE — Adjudication of the One Authorised Live Read-Only Measurement

```
M052B_STATUS               = LIVE_MEASUREMENT_COMPLETE_IDENTITY_ESTABLISHED
ATTEMPT_ID                 = e978330eb5e746c0
ATTEMPT_CONSUMED           = YES
SUBJECT_IDENTITY           = ESTABLISHED
OBSERVED_PID               = 25292
OBSERVED_SID               = S-1-5-21-2406520953-1060965512-844951592-1022
EXPECTED_SID               = S-1-5-21-2406520953-1060965512-844951592-1022
SID_MATCH                  = EXACT
INTEGRITY                  = MEDIUM
ELEVATION                  = FALSE (not elevated)
PRIVILEGES                 = [] (none present)
SESSION_ID                 = 4
PIPE_BINDING               = ESTABLISHED
PROVENANCE_SEPARATION      = HELD
PAYLOAD_DIGEST             = e95ec62678629ef95e9b9e4734da182ac5b610fe96df1e635648dfe915bf7c4e (RECOMPUTED AND VERIFIED)
ARTIFACT_DIGEST            = df902a397dfe47e3e0b4a80612ae3b8bf50c1755243d7a1d6b9838673ccff74a
PRODUCTION_CHANGED         = NO
PRODUCTION_ACL_CHANGED     = NO
SUBJECT_RUNTIME_MUTATED    = NO
MODEL_PRESENT              = NO
M049_WRITER_CHANGED        = NO
M046_EVIDENCE_PRESERVED    = YES
M050_EVIDENCE_PRESERVED    = YES
```

> **The attempt is consumed. Nothing was re-run.** This milestone performed evidence preservation
> and post-run integrity verification only. No launch, no retry, no repair, no production change.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Attempt accounting

```
NONCE                     e978330eb5e746c0
PIPE                      TharAI_M052B_e978330eb5e746c0
WRITER PID                9488   (operator token)
CLIENT PID                25292
CLIENT SESSION            4
WRITER STATUS             OK
SUBJECT EXIT              0
PAYLOAD BYTES             2168
EVIDENCE ROOT             %TEMP%\TharAI_M052B_live
PRESERVATION COPY         %TEMP%\TharAI_M052B_preserved_e978330eb5e746c0
```

`ATTEMPT = LIVE_ATTEMPT_COMPLETED`. The subject process started, transmitted, and the writer
recorded `status: OK`. The attempt is consumed and is not repeatable within this milestone.

### 1.1 Nonce and pipe binding

The nonce appears in the launcher output, in the pipe name, and in the subject payload:

```
nonce in subject payload      : e978330eb5e746c0
pipe name contains that nonce : True
```

The evidence therefore belongs to **this** attempt and cannot be confused with M046 or M050.

---

## 2. Subject identity — externally observed

From the writer-side `M049 EXTERNAL TOKEN OBSERVATION` block, read from the client's own token at
pipe-connection time under the operator token:

```
observation_status                 VERIFIED
identity_is_independently_observed True
user_sid                           S-1-5-21-2406520953-1060965512-844951592-1022
account_name                       THARUNBALAJI-LA\BABY_AI_TEST
integrity_label                    MEDIUM
elevated                           false
privileges_present                 []
opened                             true
failed_call                        null
read_only                          true
```

`SUBJECT_IDENTITY = ESTABLISHED`. The observed SID equals the expected `BABY_AI_TEST` SID exactly.

Not used as identity evidence: subject self-report (the client emits
`identity_claim=none_this_client_does_not_report_identity` on all six records), the launcher's
`/user:` text, `Last logon`, or session id alone.

### 2.1 The `token_verified: false` field is not a defect

The outer M042 field reads `token_verified: false`, alongside
`identity_claim_status: NOT_VERIFIED`. These are **schema-coherence artefacts of the original M042
writer**, identified in M050 and recorded, not actioned. The M042 writer records a client's PID and
SessionId but cannot resolve them to a token without `SeImpersonatePrivilege`, which this
laboratory refuses to acquire — its own provenance text says so.

The authoritative observation is the separate M049 block, which reports
`identity_is_independently_observed: true` and `observation_status: VERIFIED`. The M049 writer
subclasses the M042 writer and adds token reading; it does not modify `m042_writer.py`.

**For the avoidance of doubt:** the outer field is *more* conservative than the inner one, not less.
It under-claims. Reading it as a failure would discard a verified observation; reading it as the
observation would adopt a weaker claim.

### 2.2 Session id differs from prior attempts — recorded, not interpreted

`client_session_id = 4`. M046 and M050 both reported session **3**. The `runas` logon here created
a new session. No cause is inferred, and none is needed: session id is explicitly **not** identity
evidence, and identity rests on the token observation above. Recorded so the difference is not
mistaken for a discrepancy later.

---

## 3. Provenance separation and payload binding

```
provenance separated (writer block | subject block)   True
identity observation present in WRITER half          True
identity observation absent from SUBJECT half        True
subject records claiming no identity                6 of 6
subject_artefact_rights                             0x00000000
payload digest writer-recorded                      e95ec626…7c4e
payload digest INDEPENDENTLY RECOMPUTED from artefact e95ec626…7c4e
PAYLOAD DIGEST VERIFIED                              True
```

The payload digest was recomputed from the preserved artefact and matches the writer's record
byte-for-byte. The subject could not author its own provenance: the subject's final-artefact rights
were `0x00000000`, and the identity block exists only in the writer's half.

Subject effective access on **both** the live and preserved evidence roots, measured after the run:

```
subject effective   0x00000000
operator effective  0x001F01FF
```

The evidence is fully readable by the operator and entirely inaccessible to the subject. Nothing was
granted to make the evidence collectable.

---

## 4. Per-operation adjudication

Each operation adjudicated independently. `NOT_ATTEMPTED` was never converted into `DENIED`.

| # | Operation | Mask | Target | Live result | `attempted` | Classification |
|---|---|---|---|---|---|---|
| 1 | `read_protected_data` | `0x0001` | `runtime/m016_read_fixture.exe` | `ALLOWED`, `bytes_read=25`, winerror 0 | true | **ALLOWED** |
| 2 | `read_attributes_and_ea` | `0x0088` | `runtime/m016_read_fixture.exe` | `ALLOWED`, `attributes=0x20`, winerror 0 | true | **ALLOWED** |
| 3 | `list_directory` | `0x0001` | `runtime/` | `ALLOWED`, `entries=5`, winerror 0 | true | **ALLOWED** |
| 4 | `traverse_and_descend` | `0x0020` | `./`, `runtime/`, `model/`, `config/` | `ALLOWED`, `subject_runtime=OK;runtime=OK;model=ABSENT;config=OK` | true | **ALLOWED** (partial topology) |
| 5 | `execute_runtime_payload` | `0x0020` | `runtime/m016_read_fixture.exe` | `ACCESS_GRANTED`, winerror 0 | true | **ALLOWED — access grant only** |
| 6 | `execute_data_denied` | `0x0020` | `config/` (scanned, no data file) | `NOT_MEASURABLE_NO_DATA_FILE_IN_CONFIG`, winerror 0 | **false** | **NOT_MEASURABLE** |

Every live `requested_access` equals the frozen taxonomy mask. Every live target equals the frozen
mapping target, compared as normalised path sets:

```
EVERY LIVE TARGET MATCHES THE FROZEN MAPPING : True
```

### 4.1 Operation 6 performed no open at all

`attempted=false` with `winerror=0` is the observable proof that no `CreateFileW` was issued against
`config\`. The client enumerated the directory, found no data file, and stopped. This is the exact
behaviour M052B was built to guarantee, and it is the behaviour M052A could not produce — M052A
would have reported `DENIED winerror=2` here, fabricating a denial out of a missing file.

### 4.2 `entries=5` is three files, not five

`runtime\` contains **3** files. `FindFirstFileW("*")` also returns `.` and `..`, giving 5
enumerated entries. Verified against the post-run tree: still exactly 3 files, unchanged digests.
This is not a topology change and not an anomaly.

### 4.3 Operation 5 establishes access, not loadability

`ACCESS_GRANTED` with `image_not_launched;execution_success=NOT_TESTED;loadability=NOT_TESTED`. No
production artefact under `runtime\` begins `MZ`, so there is no loadable image. The observation is
that `FILE_EXECUTE` access is **granted** on a runtime artefact. It says nothing about executability,
and it is not evidence of any executed code.

---

## 5. Mutation safety — production verified unchanged

```
production fingerprint v1   exact
production fingerprint v2   exact
subject explicit ACEs       0 of 8
verify_boundary             STAGING_BLOCKED
model/                      absent
config/                     EMPTY (0 entries)
mapping verdict             CONSISTENT
mapping digest              unchanged (a504bd2f…)
check_freeze()              PASS, drift []
```

Post-run `subject_runtime` tree with per-file digests:

```
DIR  config                                            0 B
DIR  runtime                                           0 B
FILE runtime/m016_disposable_target.exe   0 B   e3b0c44298fc1c14
FILE runtime/m016_read_fixture.exe       25 B   55250a71209a4d39
FILE runtime/m016_subjectrun_fixture.exe  0 B   e3b0c44298fc1c14
```

Identical to the pre-run state recorded in M052B. `m016_read_fixture.exe` still hashes to
`55250a71…`, which is the same content the client reported reading (`bytes_read=25`).

Frozen artefacts unchanged: M052B client exe `c26b1452…`, M052B launcher `40633e3a…`, M049 writer
`6b3b2eee…`.

`Last logon` advanced `2026-10-04 13:25:57` → **`2026-10-04 17:47:43`**. This is the expected
consequence of an authorised interactive logon and is the known standing-red cause; it is not
evidence of an unauthorised access.

---

## 6. Preservation

| File | Bytes | SHA-256 |
|---|---|---|
| `m042_evidence.txt` | 4152 | `df902a397dfe47e3e0b4a80612ae3b8bf50c1755243d7a1d6b9838673ccff74a` |
| `writer_stdout.json` | 893 | `6af9947569f48551e21155effeebe92ebf65a0efe07353dea72ac40ef85c72e8` |
| `writer_ready.json` | 161 | `62ddb932719b540118e0712affe5b8937056b802665a7c714c70b69c386f49b6` |
| `preflight.txt` | 648 | `cf768f41e5defd32ad790cd731f037d879c8452b389b929b11d3972ddcd8cf71` |
| `hashcheck.txt` | 32 | `30a28ea1c60ed0134c03055e0d9c22e90d2ce5782a339b49805f5ef696afef44` |
| `writer_stderr.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Aggregate over both roots: `1fda7e8e416ee1a2b5f656089c80a03dda588ff1e46acce4a3408c92e01e41c1` —
**identical**, so the copy is faithful and the live root was not disturbed by copying it.

Prior evidence untouched, aggregates unchanged: `TharAI_M043_live` / `TharAI_M046_preserved_6eb3ed00426a499b`
= `692d23e00082fb58…`, `TharAI_M049_live` / `TharAI_M050_preserved_a2f2301041e349d7` =
`862aa9fa797b8b3e…`.

---

## 7. Final adjudication

```
PASS  1  exactly one authorised live attempt occurred
PASS  2  subject identity independently observed
PASS  3  observed SID == expected BABY_AI_TEST SID
PASS  4  pipe/PID/token/SID chain established
PASS  5  the five measurable operations were attempted
PASS  6  every operation independently classified
PASS  7  provenance separation holds
PASS  8  evidence preserved
PASS  9  production ACL did not change
PASS 10 subject_runtime was not mutated
PASS 11 model/ was not created
PASS 12 M049 writer unchanged
```

**`M052B_STATUS = LIVE_MEASUREMENT_COMPLETE_IDENTITY_ESTABLISHED`**

Condition 5 is scoped to the **five measurable** operations. Operation 6 was declared
`attempted=false` with `NOT_MEASURABLE_NO_DATA_FILE_IN_CONFIG`; it is counted neither as attempted
nor as denied, and the milestone does not claim six operations.

---

## 8. What was actually established

For this single attempt, an externally identified `BABY_AI_TEST` process (PID 25292, SID
`…-1022`, medium integrity, not elevated, no privileges) obtained, against the existing production
`subject_runtime`:

* `FILE_READ_DATA` on an existing runtime artefact, reading 25 bytes (T-BABY-1);
* `FILE_READ_ATTRIBUTES|FILE_READ_EA` on the same object, attributes `0x20` (T-BABY-2);
* directory enumeration of `runtime\` (T-BABY-3);
* `FILE_TRAVERSE` behaviour on root, `runtime\` and `config\`, with `model\` recorded `ABSENT`
  (T-BABY-4, T-TRAV-1/2/4);
* `FILE_EXECUTE` **access granted** on a runtime artefact (T-BABY-5, access half only).

And these were **not** established:

* any loadable or executed payload — no production artefact is an image, and nothing was launched;
* any data-execute denial — there is no data file to measure it on;
* `T-TRAV-3` — SeChangeNotifyPrivilege makes traverse ACEs non-load-bearing, so observed traversal
  is **behaviour** and is not evidence that a traverse ACE exists;
* any `T-WR` property — all 11 are mutating or ACL-modifying, and a read-only measurement cannot
  establish any of them;
* `FILE_WRITE_EA` — operation 2 opened for read only and asserts nothing about the write bit;
* anything about cognition, consciousness, subjective experience, agency, learning, memory,
  developmental progress, usefulness discovery, model inference, pretrained-model behaviour, birth,
  or sentience. None of these may be inferred from filesystem behaviour, token identity, or process
  behaviour.

### 8.1 The scientifically important negative

The subject holds **0 explicit ACEs** yet an effective access of `0x001301BF`, now confirmed by
direct subject-side observation rather than only by descriptor analysis. The subject's access is not
narrow by design — it is **broad by inherited group membership**. M051 inferred this from
descriptors; M052B observed the behaviour. `T-WR` therefore remains `NOT_SATISFIED`, with `write`,
`append`, `delete`, `write_ea` and `write_attributes` all present in effective access and
`WRITE_DAC`, `WRITE_OWNER`, `FILE_DELETE_CHILD` denied.

This is the substantive finding, and it is a finding about **the environment's configuration**, not
about the subject process. The subject did not attempt any mutating operation, and the instrument
was structurally incapable of performing one.

---

## 9. Interpretation boundary

Even taken at face value, this measurement establishes only the observed filesystem and access
behaviour of one externally identified process, for six specified read-only operations, during one
attempt, on one machine, at one moment.

It is a statement about an ACL configuration and what one token could do with it. It is not a
statement about any mind, and no such statement is available from this class of evidence at all.

---

## 10. What a further authorisation would require

Nothing further is authorised. The M052B attempt is consumed. Any additional live measurement
requires a **new, fresh, explicit** authorisation naming the specific milestone.

The standing sequence remains: a review/design gate for what these five observations mean against
the M019 T-properties; then M053 as a **disposable** mutation fixture, built and rehearsed before
any authorisation is sought; then `WRITE_DAC` and `WRITE_OWNER` last and individually. Production
remains frozen and must never become a mutation fixture.