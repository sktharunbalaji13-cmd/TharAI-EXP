# Milestone 005 — OS Isolation and Subject Trust Boundary

> **Application-level denial is not OS-level isolation.**

This document records what the operating system actually enforces around the
future Baby AI execution identity, measured on this host. Where a claim could
not be established, it says so and names the missing prerequisite.

---

## 1. The statement this milestone exists to support

> "The future Baby AI process runs here, under this identity, with these
> permissions. It can interact with its experimental workspace, but the
> operating system itself prevents it from rewriting the evidence that describes
> what it did."

**On this host that statement is not yet true.** `OS_ISOLATION =
NOT_IMPLEMENTED`. Everything below is the measurement that establishes it, and
the single prerequisite that would change it.

---

## 2. OS isolation architecture

Two independent layers, and the difference between them is the whole point:

| Layer | Mechanism | Enforced by | Status here |
|---|---|---|---|
| Application policy | `babylab/trust.PathPolicy` | Python, running as the operator | **ACTIVE** |
| OS policy | NTFS ACLs evaluated by the kernel | Windows | **NOT IMPLEMENTED** |

The application layer refuses a write in Python code. The operator could simply
not call that code. Only a refusal observed from a genuinely lower-privileged
identity, by the kernel, is `OS_DENIED`.

The four-layer target defence is:

```
Application policy + OS policy + Cryptographic provenance + Privileged control
```

M005 adds no new protection to the left-hand layers and removes nothing from
them. Each must fail independently.

---

## 3. Windows account model

The future subject must run as a **separate Windows principal**, so the kernel
can deny it independently of any Python check.

Measured on this host:

| Capability | Result |
|---|---|
| Create a local account (`New-LocalUser`) | **`Access denied`** |
| Create a local account (`net user /add`) | **`System error 5: Access is denied`** |
| Token elevation | Not held — medium integrity |
| `SeRestorePrivilege` / `SeTakeOwnershipPrivilege` / `SeSecurityPrivilege` | **All absent** |
| Administrators group membership | Yes, but membership ≠ elevation |
| Owner / implicit `WRITE_DAC` | **Held** — ACLs can be changed and reverted |

Two independent account-creation mechanisms were refused, so this is a stable
host limitation rather than a tool quirk.

---

## 4. Baby AI execution identity

`BABY_AI_TEST` is the reserved name for the security-test principal.

> **This identity is a security test principal, not a Baby AI subject.**

It has no `BABY_AI` cryptographic identity, no model access, no keyring entry,
and no standing beyond proving the OS boundary. `tests/host_security/` asserts
that the real keyring contains no `BABY_AI` role.

---

## 5. ACL model

Captured via `icacls` and parsed by `babylab.osboundary.parse_icacls`, which
extracts the **trustee** rather than the leading path token. Milestone 004
shipped a parser that made exactly that mistake and reported a clean boundary on
a world-writable directory; `test_parse_extracts_trustee_not_path` now pins the
bug class.

**Windows deny-ACE evaluation is the constraint that decides this milestone.**
An explicit DENY beats an explicit ALLOW for the same principal, and deny ACEs
can only name an **existing** principal. The only principals available here are
the human operator and the broad groups the operator belongs to. Denying those
would lock the operator out of their own research record, which section 11
forbids.

`UNSAFE_DENY_TARGETS` records exactly which trustees must never be used as a
deny target for that reason.

---

## 6. Protected paths

Resolved from `babylab.paths.ProjectPaths`, never hard-coded, so the list cannot
drift from the real layout.

| Name | Path | Subject may append? |
|---|---|---|
| `event_log` | `var/events/events.jsonl` | **Yes** (append only) |
| `provenance_ledger` | `var/provenance/ledger.jsonl` | **Yes** (append only) |
| `provenance_seals` | `human_control/provenance/` | No |
| `provenance_keyring` | `human_control/security/keys/keyring.json` | No |
| `provenance_private_keys` | `human_control/security/keys/private/` | No |
| `control_token` | `human_control/security/control.token` | No |
| `birth_records` | `human_control/birth_records/` | No |
| `research_records` | `human_control/research_records/` | No |
| `snapshots` | `human_control/snapshots/` | No |
| `protected_configuration` | `human_control/experiment_config/foundation.json` | No |
| `research_documentation` | `docs/` | No |
| `experiment_log` | `research/experiment-log.md` | No |
| `source_repository` | `.git/` | No |

Subject-writable by design: `baby_workspace/`, `baby_workspace/temporary/`.

The two append-only entries preserve the Milestone 001/002 distinction. The
Observatory depends on the shared append-only stream, so append is permitted
while mutation, deletion and truncation are denied. This is deliberate and
recorded in `ProtectedPath.append_only_for_subject`.

---

## 7. Permission matrix

| Resource | Human | Control | `BABY_AI_TEST` | Layer |
|---|---|---|---|---|
| Append to event log | RW | RW | **append only** | application (OS layer unavailable) |
| Modify / delete / truncate events | RW | RW | **DENY** | application |
| Append to runtime ledger | RW | RW | **append only** | application |
| Provenance seals / HEAD | RW | RW | **DENY** | application |
| Provenance keyring | RW | RW | **DENY** | application |
| Provenance private keys | RW | controlled | **DENY** | application |
| Control token | RW | controlled | **DENY** | application |
| Birth records | RW | controlled | **DENY** | application |
| Human-control records | RW | RW | **DENY** | application |
| Research docs | RW | controlled | **DENY** | application |
| `.git/` | RW | controlled | **DENY** | **Git, not the write matrix** |
| Experimental workspace | RW | controlled | **RW** | application |
| Temporary workspace | RW | controlled | **RW** | application |
| Model cache | controlled | controlled | read-only | not yet applicable |

Every DENY above is an **application** denial. None is an OS denial, because no
distinct principal exists to attempt the operation as.

---

## 8. Actual denial evidence

**There is no `OS_DENIED` evidence for the laboratory, because no attempt could
be made from a distinct principal.**

What *was* proven is that the NTFS layer itself works. A `DENY (W)` ACE applied
to a throwaway file produced a genuine kernel denial:

| Attempting identity | Result |
|---|---|
| Windows, this account | `PermissionError` |
| WSL2, uid 1000 | `WSL_WRITE_DENIED` |
| WSL2, **root** | `WSL_ROOT_DENIED` |

So enforcement is real and testable here. What is missing is a second principal
to scope the denial to. WSL2 is **not** a substitute: `/mnt/c` is a 9p mount
with no metadata option and its Linux user maps to the same Windows account, so
a denial aimed at it hits the operator too.

---

## 9. Positive capability evidence

A boundary that denies everything is not a boundary, it is an outage. The
host-security suite asserts the subject identity can still write
`baby_workspace/` and `baby_workspace/temporary/`, and that the operator retains
read/write on every protected path after any change.

Verified on this host after a live capture/restore cycle:

```
human_control    WRITE OK
docs             WRITE OK
var/events       WRITE OK
baby_workspace   WRITE OK
```

---

## 10. Host-security test methodology

Three suites, deliberately separated:

| Suite | Depends on the host? | Command |
|---|---|---|
| Unit / integration | No | `py -3 -m pytest -q` |
| Host security | **Yes** | `py -3 -m pytest tests/host_security -q` |

`tests/host_security/` is excluded from the default run via `norecursedirs` in
`pyproject.toml`, so the ordinary suite stays portable and deterministic.

Host-security tests either exercise a real OS boundary or **skip with a stated
reason**. Current result: **6 passed, 4 skipped**, the skips naming the missing
principal.

The harness refuses to fake a result in three specific ways:

- `require_distinct_principal()` raises if any attempt claims `OS_DENIED`
  without `cross_process=True`.
- `launch_attempt_as_principal()` returns `NOT_IMPLEMENTED` when the principal
  is absent rather than silently falling back to an in-process attempt.
- A successful write to a protected target is a fault, never a pass.

---

## 11. Recovery procedure

`scripts/restore_permissions.ps1`, a human/control operation:

```powershell
# Before any permission change
pwsh -File scripts/restore_permissions.ps1 -Capture

# If something goes wrong
pwsh -File scripts/restore_permissions.ps1 -Restore
```

Both directions use `icacls` end to end. A composite `FileSystemRights` such as
`GENERIC_ALL` has no single enum name, and PowerShell refuses to cast or
construct it, so a .NET-based round trip aborted partway through the protected
set — leaving the operator worse off than before. That was observed, diagnosed
and fixed; the `icacls` path round-trips correctly.

**Verified round trip on a real path:** applied `DENY (W)` to
`baby_workspace/temporary`, restored, and confirmed the ACL was byte-identical
to the pre-damage state.

Snapshots land in `var/acl-snapshots/`, which is excluded from version control,
so a machine-specific ACL record never enters the research history.

The script is a human/control operation and is not reachable from the subject
trust domain.

---

## 12. Birth safety gate

`birth/readiness.py::OsIsolationEvidence` requires **all seven** conditions
before OS isolation is `VERIFIED`:

1. dedicated low-untust identity exists
2. identity is independently verified
3. protected paths are identified
4. actual writes were attempted from that identity
5. the operating system denied them
6. positive workspace capabilities work
7. protected evidence was unchanged afterwards

An unmeasured condition is `None`, deliberately distinct from `False`:
"we did not check" and "we checked and it failed" are different facts, and
collapsing them is how a safety gate becomes decorative.

The presence of ACL code satisfies none of these. On this host the gate reports
`BIRTH READINESS: BLOCKED`.

---

## 13. Remaining limitations

1. **No OS-level isolation.** Blocked on one prerequisite: an elevated session.
2. **No `OS_DENIED` evidence for the laboratory**, only proof that NTFS enforces.
3. **No second Windows principal**, so WSL2 and Docker cannot substitute.
4. **The source tree is protected by Git, not by the write matrix** (carried
   over from M004).
5. **The event hash chain is not a content guarantee** (carried over from M004);
   the provenance content hash is.

### The single prerequisite

Run one elevated PowerShell session and create the principal:

```powershell
New-LocalUser -Name 'BABY_AI_TEST' -NoPassword -AccountNeverExpires
```

Then re-run `py -3 -m pytest tests/host_security -q`. The four currently-skipped
tests will execute real cross-process attempts, and `OS_ISOLATION` can move to
`VERIFIED` if — and only if — the kernel actually refuses them.
