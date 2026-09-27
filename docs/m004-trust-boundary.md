# Milestone 004 — Trust Boundary, Isolation Status, and Verification

This document records what the laboratory **measured** about its own isolation
in Milestone 004. It is written to be read by an investigator who wants to know
what the subject can reach, what it cannot, and what has actually been proven —
without reading source code.

> **A software architecture that is intended to be isolated is not equivalent to
> an OS-enforced isolation boundary.**

Every security claim below is labelled with how it was established. Nothing here
is asserted because it was designed that way.

---

## 1. The three truths this milestone keeps apart

| Truth | Question it answers | Established by |
|---|---|---|
| **MACHINE TRUTH** | What do the records and cryptographic mechanisms say? | Seals, hashes, chain verification |
| **DISPLAY TRUTH** | What does the Observatory actually show a human? | Rendering the real output and asserting on the text |
| **EXPERIMENTAL TRUTH** | What has genuinely been exercised here? | An operation actually run in this environment |

A passing unit test proves none of these on its own. A correct display does not
prove the underlying state is real. A successful mock runtime does not prove a
model ran. Milestone 004 adds a layer that tests each separately.

---

## 2. Trust boundary model

Four authority tiers, in `babylab/trust.py` as `TrustTier`:

| Tier | Name | Contains | Subject authority |
|---|---|---|---|
| **Tier 0** | Human authority | Lifecycle, research configuration, model selection, provenance, snapshots, shutdown, birth authorization | **None** |
| **Tier 1** | Laboratory infrastructure | Event log, provenance, research records, Observatory, configuration, control interface | **None** (write refused) |
| **Tier 2** | Baby AI execution environment | Model runtime, experimental workspace, temporary files, future tool interfaces | **Own files only** |
| **Tier 3** | External environment | Camera, microphone, network, physical devices, other computers | **None**; access is never implied by an interface existing |

Governed paths map to tiers via `tier_of(domain)`. `human_control/` is Tier 0,
`docs/` and `research/` are Tier 1, `baby_workspace/` is Tier 2, and anything
outside the project root is Tier 3.

---

## 3. OS isolation status — MEASURED, NOT ASSUMED

**`OS_ISOLATION = NOT_IMPLEMENTED`**
**Enforcement layer actually in force: `application policy`**

Re-runnable at any time:

```python
from babylab.isolation import assess_isolation
from babylab.paths import default_paths
p = default_paths()
report = assess_isolation([p.human_control, p.provenance_ledger, p.event_store])
print(report.status.value, report.layer.value)
```

### What was observed on this host

| Probe | Observed | Source |
|---|---|---|
| Account | `THARUNBALAJI-LA\k.tharun balaji` | `os.environ`, `whoami` |
| Elevated | **No** — medium-integrity token (Administrators group member, no high-integrity token) | `whoami /groups` integrity SIDs |
| Broad write grant | **`Authenticated Users:(I)(M)`** on `human_control/`, `human_control/security/keys/private/`, `var/provenance/`, `var/events/`, `docs/`, `.git/` | `icacls` |
| Dedicated Baby AI account | **None.** Other local accounts are OS/harness accounts (`Administrator`, `Guest`, `WDAGUtilityAccount`, `CodexSandbox*`) | `Get-LocalUser` |
| Container runtime | Client 29.6.1 present, **engine not running** | `docker --version`, `docker info` |
| WSL2 | **Working** (`6.6.87.2-microsoft-standard-WSL2`) | `wsl -e uname -a` |
| Windows Sandbox / Hyper-V | Cannot be queried without elevation | `Get-WindowsOptionalFeature` refused |

### Why it is `NOT_IMPLEMENTED`

1. **NTFS grants `Authenticated Users` Modify on every protected path.** Any
   second local account — including a future Baby AI service account — can write
   the signing keys, the provenance ledger, the event log, the research docs and
   the Git history. No kernel boundary exists on those paths.
2. **The session is not elevated**, so it cannot install the deny ACEs that would
   remove that grant, nor change file ownership.
3. **No dedicated low-privilege execution identity is provisioned.** Reusing the
   harness's own sandbox accounts would not be a research boundary.
4. **The container engine is not running**, so no container boundary exists now.

### The rule that prevents a false `VERIFIED`

`IsolationStatus.VERIFIED` is reachable **only** when a write was actually
attempted from a lower-privilege identity **and** the kernel denied it. Reading
an ACL and seeing that it looks correct can never produce `VERIFIED`. This is
enforced in code (`babylab/isolation.py`) and in
`tests/test_m004_isolation.py::TestAssessNeverOverclaims`.

---

## 4. Baby AI execution identity

`babylab.trust.BabyAIExecutionIdentity` describes the identity the subject will
run as. It is a **description, not a credential** — nothing in it grants access.

It must not hold, per `FORBIDDEN_BABY_AI_CREDENTIALS`:

- `provenance_signing_key`
- `human_control_credential`
- `research_encryption_key`
- `privileged_control_credential`
- `git_signing_credential`
- `authorship_record_write_access`

`separation_status()` returns `same_os_user` until a real lower-privilege
account exists, and `undefined` if a separation is claimed without one being
provisioned. On this host the answer is `same_os_user`.

---

## 5. Human authority

The human operator alone controls laboratory lifecycle, research configuration,
model selection, provenance, snapshots, shutdown, and **birth authorization**.

The control plane authenticates with a token at
`human_control/security/control.token`, which is inside Tier 0. A Baby AI actor
cannot read it (`tests/test_m004_security_boundaries.py::TestBabyAIVsControlPlane`),
and a privileged `ActionIntent` from an uncredentialed subject is refused by
`ActionBoundary.authorize`.

### Birth authorization chain

Only the architecture is frozen; the final activation is **NOT IMPLEMENTED**.

```
human_authorization        (architecture only)
      ↓
privileged_control        (architecture only)
      ↓
verified_prerequisites    (architecture only)
      ↓
birth_ceremony            (exists since M003)
      ↓
subject_activation        NOT IMPLEMENTED
```

Defined as `BIRTH_AUTHORIZATION_CHAIN` in `babylab/trust.py`, with
`implemented_in_m004=False` on the final step.

---

## 6. Evidence protection

Research evidence sits outside the Baby AI trust domain. In
`tests/test_m004_security_boundaries.py::TestProtectedEvidenceIsOutsideSubjectDomain`
these are all refused to the subject: the provenance seals and HEAD, the birth
record, the keyring, the private key directory, the control token, research
records, and snapshots.

### A measured weakness worth recording

The event log's **hash chain is not a content guarantee**. Measured behaviour of
`EventStore.verify_chain()`:

| Tamper | Chain reports intact? |
|---|---|
| Modify an event payload | **True** — not detected |
| Delete the last event | **True** — not detected |
| Truncate the log to empty | **True** — not detected |
| Delete a *leading* event | False — detected (prev_hash breaks) |

The guarantee that event history cannot be rewritten is carried by the
**provenance layer**, which records a content hash of the whole log. All three
undetected-by-chain cases *are* caught by
`ProvenanceRecorder.verify_paths()`. Both halves are asserted in
`TestBabyAIVsEventHistory` so the finding cannot be quietly forgotten.

A second gap: the write matrix does **not** protect the source tree.
`babylab/`, `events/`, `provenance/` etc. classify as `SYSTEM_RUNTIME`, where the
subject may write. What protects source is **Git**. This is asserted as a known
gap in `TestBabyAIVsSourceRepository`, not hidden behind a passing test.

---

## 7. Rendering-level verification

`tests/test_m004_rendering.py` asserts on the **text a human would read**, not on
the model behind it. Every test renders the complete output through the real
`ObservatoryRenderer` and inspects the resulting string.

The seven invariants:

| # | Rule |
|---|---|
| 1 | With no subject, the display must not imply one exists |
| 2 | A record without a key must read `RECORDED`, never `ATTACHED` |
| 3 | A key without a record must not read `NO_SUBJECT`; the discrepancy is shown |
| 4 | An unexecuted runtime must never read `READY`; it reads `RUNTIME_UNVERIFIED` |
| 5 | An uninstalled model must not imply inference is available |
| 6 | An interface-only component must not read `IMPLEMENTED` |
| 7 | An unavailable value must read `UNAVAILABLE`, never `0`/`false`/`[]`/`none` |

---

## 8. Epistemic display labels

`observatory/audit.py` defines nine labels. They are **not** interchangeable, and
each is documented in `LABEL_MEANINGS` and rendered into the audit itself.

| Label | Meaning |
|---|---|
| `OBSERVED` | Measured by a probe run in this process at report time |
| `DERIVED` | Computed from observed values by a stated rule |
| `RECORDED` | Read from a human-owned record file on disk |
| `INHERITED` | Carried from a prior milestone's frozen artifact, not re-measured |
| `UNVERIFIED` | A real claim this milestone has not proven; **never a synonym for PASS** |
| `UNAVAILABLE` | The value could not be obtained; not zero, empty, false or none |
| `DENIED` | An access or operation was refused by policy |
| `FAILED` | An operation was attempted and did not succeed |
| `UNKNOWN` | State was not determined and cannot be inferred |

The audit snapshot (`observatory/audit.py::AuditReport.render`) carries all
twelve required sections, each claim tagged with a label and a **source
reference**, and renders the label definitions inline so a reader never has to
guess what a label licenses them to believe.

---

## 9. Security test methodology

Each boundary is attempted and the outcome labelled with one of four values that
are **never collapsed**:

| Label | Meaning |
|---|---|
| `APPLICATION DENIED` | Refused by laboratory policy running as the operator |
| `OS DENIED` | Refused by the kernel, observed from a lower-privilege identity |
| `NOT TESTABLE` | The attempt cannot be made in this environment |
| `NOT IMPLEMENTED` | No mechanism exists to attempt |

On this host **no** boundary is `OS DENIED`, because no lower-privilege identity
exists. Every refusal below is `APPLICATION DENIED`, and the suite asserts that
`VERIFIED` is unreachable without an observed denial.

### Testing the tests (section 24)

`tests/test_m004_display_faults.py` injects each display fault into the real
renderer and runs the **actual** assertions from `test_m004_rendering` to prove
they fail. It includes a control test asserting the same assertions *pass* on an
honest renderer, so the file cannot pass vacuously.

| Injected fault | Detected by |
|---|---|
| Hide `RECORDED_DETAIL` | `test_recorded_detail_is_visible` |
| `RUNTIME_UNVERIFIED` rendered as `READY` | `test_runtime_unverified_is_shown` |
| `ATTACHED` weakened by hiding the discrepancy | `test_exposes_the_authority_discrepancy` |
| Suppress the isolation failure | `test_os_isolation_is_shown_as_not_implemented` |
| Replace `UNAVAILABLE` with `0` | `test_environment_id_is_unavailable_when_absent` |
| Imply a subject where none exists | `test_banner_states_no_subject` |

---

## 10. Known limitations

1. **No OS-level isolation.** See section 3. `NOT_IMPLEMENTED`.
2. **The event hash chain does not detect content tampering**, suffix deletion or
   truncation. The provenance content hash does. See section 6.
3. **The write matrix does not protect the source tree.** Git does.
4. **The subject may append to the shared event log and runtime ledger.** M004
   section 9 asks for `append arbitrary research event → DENIED`, but M001
   designed the log as append-only and M002's Observatory depends on it.
   Forbidding append would break M002, so the implemented rule is: the subject
   may append, and may not rewrite, delete, truncate, or forge authorship. This
   is a deliberate, documented divergence from the literal wording of section 9.
5. **No real model has been executed and no real birth has occurred.** The
   `MODEL RUNTIME VERIFIED` prerequisite is `UNVERIFIED` permanently until one is.
6. **The `vibe` runtime's router echoes non-ASCII prompts with mojibake**
   (UTF-8 bytes decoded as single-byte). Verified not to reach the frozen
   requirement. Upstream defect, cosmetic for execution.

---

## 11. Prerequisites before a real birth

`birth/readiness.py` reports each of ten prerequisites **individually** and
never returns a single green/red verdict.

```
MODEL CONFIGURED                MODEL HASH VERIFIED
MODEL RUNTIME VERIFIED          SUBJECT RECORD SYSTEM READY
PROVENANCE READY                CONTROL READY
OS ISOLATION READY              BABY_AI IDENTITY READY
ENVIRONMENT BOUNDARY READY      OBSERVATORY READY
```

On this host the audit reports:

```
BIRTH READINESS: BLOCKED
Reason: MODEL RUNTIME VERIFIED is UNVERIFIED
        the model runtime has never been executed; a mock is not a runtime
```

`OS ISOLATION READY` is `NOT_IMPLEMENTED` and independently blocks readiness.

### Concrete prerequisites to reach `READY`

1. An **elevated** session, to install deny ACEs.
2. A **dedicated Baby AI service account**, created by an administrator.
3. Explicit **deny ACEs** on `human_control/`, `var/provenance/`,
   `var/events/`, `docs/` and `.git/` for that account.
4. An **actual write attempt** from that account to a protected path, with the
   denial observed and recorded. This is the only route to `VERIFIED`.
5. Alternatively: start the **container engine**, or enable **Windows Sandbox**
   or a **VM**, and run the subject there.
6. A **real model runtime execution** — a mock is not a runtime.

Until items 1–4 are done, the laboratory must not perform a real Baby AI birth.
That gate is a research safety requirement, not an inconvenience.

---

## 12. Explicitly not done in Milestone 004

No model weights were installed. No foundation model was executed. No `BABY_AI`
signing key was created. No autonomous loop, memory, learning, self-modification,
network, camera, microphone, face recognition, actuator, emotion or personality
exists. No real Baby AI birth occurred.
