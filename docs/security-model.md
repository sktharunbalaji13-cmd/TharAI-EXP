# Security model

## Purpose

This document states what the laboratory's trust boundaries actually are, which
of them are in force, and what they fail to stop. It is written to be read by
someone deciding whether to trust the resulting data.

Short version: **two of three boundary tiers are in force.** Application policy
is active everywhere; the OS file-permission tier is applied and verified by
human cross-process execution. The strongest tier — a dedicated low-privilege
OS account — is still not implemented, so the boundary still has a known
residual hole recorded below rather than papered over.

## Milestone 005 update — tier 2 is applied and empirically verified

Milestone 004 measured the boundary and found it absent. Milestone 005 built it
and proved it:

```
OS_ISOLATION = VERIFIED                     (human-executed, cross-process)
Enforcement layers in force: application policy + NTFS ACLs
```

A second Windows principal was created and used as a stand-in for a future
subject:

| Property | Value |
| --- | --- |
| Account | `THARUNBALAJI-LA\BABY_AI_TEST` |
| SID | `S-1-5-21-2406520953-1060965512-844951592-1022` |
| Administrator | `False` |
| Integrity level | `Medium` |

Because the OpenCode process cannot hold `SeImpersonatePrivilege`, the
cross-process denial was executed **by a human operator** and recorded as
evidence in `docs/evidence/m005-final-verification.json`:

| Probe run as `BABY_AI_TEST` | Result |
| --- | --- |
| read `var/provenance/m005_probe.txt` | `Access is denied.` |
| read `human_control/security/control.token.bak` | `Access is denied.` |
| create/read/delete `baby_workspace/m005_probe.txt` | succeeded |

The third probe matters as much as the two denials: a boundary that denied
everything would prove nothing. The subject account can work in its own
workspace and is refused everywhere it must not go.

Current measurement of the applied boundary: **11/11 protected paths deny the
subject account; both subject workspaces carry zero subject ACEs.**

### Two defects the verification itself found

Building the boundary was not the end of it. Verification found and fixed two
real defects, and their failure history is retained in the evidence file rather
than cleaned up:

1. **A leaf deny left its parents writable.** Denying on
   `var/provenance/` alone did nothing while `var/` remained writable, because
   NTFS inheritance ran the other way. The fix denies the parent and keeps the
   append permission split explicit.
2. **ACL recovery silently destroyed the boundary.** When `icacls` failed
   mid-restore, the recovery path left the tree *more* permissive than before
   rather than failing closed. The parser now fails closed and refuses to save
   when any target is unreadable.

### Automated harness status

`tests/host_security` still reports 15 failures on this host. Those are not
regressions: the harness cannot impersonate `BABY_AI_TEST` and fails closed on
credential prompts by design. It has **never** impersonated the subject and is
reported as `NOT_TESTABLE` — the human evidence above is what carries the claim.

Full detail: **`docs/m005-os-isolation.md`**.

## Milestone 004 — the measurement that preceded it

Milestone 004 replaced assertion with a re-runnable measurement
(`babylab/isolation.py`) and found, at the time, that NTFS granted
**`Authenticated Users:(I)(M)`** — write — on `human_control/`, the private key
directory, `var/provenance/`, `var/events/`, `docs/` and `.git/`, with no
dedicated Baby AI execution account. Milestone 005 exists because of this
document.

The four-tier authority model (Tier 0 human, Tier 1 laboratory, Tier 2 Baby AI
execution, Tier 3 external) is defined in `babylab.trust.TrustTier`. The full
measurement, the security-test methodology, and the known limitations are in
**`docs/m004-trust-boundary.md`**.

Two measured weaknesses recorded in Milestone 004 remain open: the event log's
hash chain does **not** detect payload modification, suffix deletion, or
truncation (the provenance content hash does), and the write matrix does not
protect the source tree (Git does).

## The three tiers

### Tier 1 — Application policy (ACTIVE)

`babylab/trust.py` provides `PathPolicy`, which refuses writes to
`human_control/`, `human_control/security/keys/`, and `var/provenance/` from any
code path that is not an explicitly registered privileged writer. Privileged
writers must name themselves and state a reason; refusals raise and are recorded.

**What it actually buys:** every privileged mutation in this codebase is
attributable to a named caller with a stated reason, and accidental writes from
impatient or unwary code fail loudly instead of quietly corrupting the record.

**What it does not buy:** the subject runs as the same Windows user as the
laboratory. It can call `open()` directly, ignore `PathPolicy`, or run any
program. Tier 1 is a guard rail, not a wall. An adversary who is trying to
subvert the experiment is unaffected by it.

**Verified by:** `tests/test_trust_boundaries.py`, on every test run.

### Tier 2 — OS file permissions (ACTIVE, VERIFIED)

NTFS ACLs grant the subject's service account read-and-execute on the
observable paths and deny it write access to `human_control/` and
`var/provenance/`. Unlike tier 1, the kernel enforces this, so it holds even
against code that does not want to cooperate.

`scripts/trust_boundaries.ps1` implements both the audit and the apply path, and
the apply path has been **run**. The account
`THARUNBALAJI-LA\BABY_AI_TEST` (non-administrator, Medium integrity) is denied
access to 11 protected paths and holds no ACE on either subject workspace.

**Verified by:** a human operator running the probes as that account, in a
separate process, with the raw output recorded in
`docs/evidence/m005-final-verification.json`. Not by this project's test suite,
which cannot impersonate an account and says so.

**What it does not buy:** tier 2 is a *file* boundary. It does not constrain
what the subject process does in memory, does not provide a restricted token or
job object, and does not stop a subject with a different execution path from
doing what tier 3 exists to prevent.

### Tier 3 — OS account isolation (NOT IMPLEMENTED)

Running the subject as a separate low-privilege principal, and optionally inside
a container or a restricted token, is the only tier that meaningfully contains a
determined adversary. There is no code for it. `BABY_AI_TEST` is a
*permissions* stand-in, not an execution isolation boundary: nothing runs under
it automatically, and a `BABY_AI` key is still not created. `PathPolicy` is not
a substitute, and this document does not pretend otherwise.

## Control plane authentication

The control server listens on `127.0.0.1` only and requires every request to
carry a tag:

```
auth = HMAC_SHA256(control.token, canonical_json({
    "protocol": "babylab/control/v1",
    "op":       "snapshot",
    "nonce":    "<32 hex chars, fresh per request>",
    "args":     {...}
}))
```

Properties this gives us:

- The token itself never crosses the wire. Only the tag does.
- The tag is bound to the operation, the nonce, *and* the arguments, so an
  authorisation for `ping` cannot be replayed as `shutdown`, and a `snapshot`
  authorisation for one label cannot be replayed with a different label.
- A missing or wrong tag is refused and recorded as
  `security.control.request_rejected`, including which operation was attempted.
  Unauthorised attempts are research data.

Properties it does not give us:

- **No replay protection within a nonce window.** A captured, valid request can
  be resent; the server does not track seen nonces. Acceptable for a
  single-operator loopback control plane, and it is a real limitation rather
  than an oversight.
- **The token is a bearer secret stored on disk**, under
  `human_control/security/control.token`. Until tier 2 is applied, any process
  running as the same Windows user can read it. The tests in
  `tests/test_control.py::AuthorisationTests` prove the *authentication logic*
  rejects requests without a valid tag; they do **not** prove a second process
  is unable to obtain one. That claim is an OS question, answered by tier 2.
- If the token file is missing or corrupt, the server refuses to start. There is
  no unauthenticated fallback mode, by design.

## Key custody

| Key | Held in | Purpose |
| --- | --- | --- |
| `HK-*` (HUMAN) | `human_control/security/keys/private/` | Operator's authorship |
| `SK-*` (SYSTEM) | `human_control/security/keys/private/` | Control process and tooling |
| `BK-*` (BABY_AI) | **not created** | Reserved for the future subject |

No `BABY_AI` key has been created at any milestone, because there is no subject
to own one. Provisioning it now would create a signing identity for a system that
does not exist, which is precisely the kind of pretense this project avoids — and
Milestone 009 made that structural by refusing key provisioning outright.

Private keys are stored as files with restricted ACLs and are `.gitignore`d.
They are **not** encrypted with a passphrase, because a passphrase in the same
repository protects nothing. Key custody here is filesystem permissions, which
are tier 2, which is now active and verified. See `docs/decisions/ADR-005`.

## Key custody at birth (Milestone 009)

`birth/keycustody.py` makes custody an explicit, reasoned decision instead of an
assumption. On this laboratory it resolves to `NOT_REQUIRED`, because:

- the birth ceremony produces no `BABY_AI`-authored content, so nothing needs
  subject signature;
- provenance is laboratory-generated and hash-linked, so authorship is already
  attributable without a subject key.

`provision_key` **refuses outright**. Provisioning a `BABY_AI` key "for
appearance" would create the active role that makes the Observatory report
`ATTACHED` — a subject that does not exist would look attached, which is exactly
the pretense this project refuses. If a future ceremony declares signing
required while no key is provisioned, custody resolves to
`REQUIRED_BUT_UNPROVISIONED`, and the M009 gate treats that as blocking.

## Snapshot authenticity

Control-plane snapshots are *not* individually signed. What makes them
tamper-evident is that their SHA-256 digest is written into the HMAC-signed
provenance ledger by the `SYSTEM` key. Altering a snapshot breaks that digest
anchor and `provenance.cli verify` reports it. This is described accurately as
"anchored in the signed ledger", not as "signed".

Snapshot labels supplied by an operator are sanitised to a safe filename
component before use, and the write is checked for containment within
`human_control/snapshots/`. An authenticated but careless or compromised client
cannot steer a write outside the protected area with `..` or a path separator.

## What a subject will be able to do

Designed, implemented, and tested as layers through Milestone 009. The design
intent:

- Read its own code and its own observable event stream.
- Append events to the event log.
- **Not** read `human_control/security/keys/private/`, `var/provenance/`, or the
  control token — now enforced by tier 2, verified by human cross-process
  execution.
- **Not** drive the control protocol, because it does not hold the token.

The two negative bullets are now **enforced**, and the evidence is in
`docs/evidence/m005-final-verification.json`. The scope of that claim is worth
stating precisely: the denials are proven for the `BABY_AI_TEST` account on
those paths. They are not proof that a future subject is *running* as that
account, because tier 3 — which is what binds an execution identity to the file
boundary — does not exist yet.

## Residual risks, enumerated

1. **A root-level `FILE_DELETE_CHILD` capability on the parent of the private
   key directory is not guarded by an explicit deny.** The leaf denies hold for
   read and write, and the parent-inheritance defect found in M005 verification
   was fixed, but a delete-child right inherited from higher up is a distinct
   NTFS capability and is not denied by an ACE. *Mitigation: an explicit deny on
   the parent path, or tier 3. Status: known, not fixed.*
2. **Tier 2 binds a file boundary to an account, not to a running process.**
   Nothing in the laboratory yet executes as `BABY_AI_TEST`, so a misconfigured
   future launch would run with the operator's rights and the verified denials
   would never be exercised. *Mitigation: tier 3. Status: not implemented.*
3. HMAC is symmetric, so the operator can forge any role they hold a key for.
   *Mitigation: Ed25519. Status: open decision, ADR-003.*
4. Seals are stored in the same trust domain as the ledger they anchor.
   *Mitigation: an external witness. Status: not implemented.*
5. No nonce-replay cache in the control protocol.
   *Mitigation: loopback-only binding plus short-lived processes. Status:
   accepted for Milestone 001.*
6. `PathPolicy` is advisory to anyone who does not choose to call it.
   *Mitigation: tier 2 and tier 3. Status: tier 2 active for files; tier 3 not
   implemented.*
7. A snapshot is written by the control process without a passphrase-protected
   copy, so a determined local user with tier 2 removed can edit it and re-seal.
   *Mitigation: the same as risk 4. Status: not implemented.*
