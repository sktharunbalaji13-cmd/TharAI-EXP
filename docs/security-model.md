# Security model

## Purpose

This document states what the laboratory's trust boundaries actually are, which
of them are in force, and what they fail to stop. It is written to be read by
someone deciding whether to trust the resulting data.

Short version: **one of three boundary tiers is active, and it is the weakest
one.** The OS-level boundaries are scriptable but not enabled, and the
strongest tier is not implemented. That is the honest position of Milestone 001.

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

### Tier 2 — OS file permissions (SCRIPTABLE, NOT ACTIVE)

NTFS ACLs would grant the subject's service account read-and-execute on the
observable paths and deny it write access to `human_control/` and
`var/provenance/`. Unlike tier 1, the kernel enforces this, so it holds even
against code that does not want to cooperate.

`scripts/trust_boundaries.ps1` implements both the audit and the apply path.
**It has not been applied.** Enabling it requires two things this environment
does not have:

- An elevated session. `Test-Elevated` returns `False` here.
- A second Windows principal. Creating one failed:
  `net user babylab_probe_xyz /add` → `Access is denied.`

Until an operator runs the script from an elevated console *and* verifies the
denial by actually running something as the restricted account, tier 2 is
**NOT VERIFIED**. It is not reported as passing anywhere in this project.

### Tier 3 — OS account isolation (NOT IMPLEMENTED)

Running the subject as a separate low-privilege principal, and optionally inside
a container or a restricted token, is the only tier that meaningfully contains a
determined adversary. It is out of scope for Milestone 001 and there is no code
for it. `PathPolicy` is not a substitute, and this document does not pretend
otherwise.

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

Milestone 001 provisions no `BABY_AI` key, because there is no subject to own
one. Provisioning it now would create a signing identity for a system that does
not exist, which is precisely the kind of pretense this project avoids.

Private keys are stored as files with restricted ACLs and are `.gitignore`d.
They are **not** encrypted with a passphrase, because a passphrase in the same
repository protects nothing. Key custody here is filesystem permissions, which
are tier 2, which is not active. See `docs/decisions/ADR-005`.

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

## What a subject will be able to do in Milestone 002

Not yet decided, and recorded as an open question rather than decided by
fiat. The design intent is:

- Read its own code and its own observable event stream.
- Append events to the event log.
- **Not** read `human_control/security/keys/private/`, `var/provenance/`, or the
  control token — enforced by tier 2 once a second account exists.
- **Not** drive the control protocol, because it does not hold the token.

Until tier 2 is verified, that last two bullets are aspirations, not
guarantees, and this section must not be read as claiming otherwise.

## Residual risks, enumerated

1. A subject sharing the OS user can read private keys and the control token.
   *Mitigation: tier 2. Status: not applied.*
2. HMAC is symmetric, so the operator can forge any role they hold a key for.
   *Mitigation: Ed25519. Status: open decision, ADR-003.*
3. Seals are stored in the same trust domain as the ledger they anchor.
   *Mitigation: an external witness. Status: not implemented.*
4. No nonce-replay cache in the control protocol.
   *Mitigation: loopback-only binding plus short-lived processes. Status:
   accepted for Milestone 001.*
5. `PathPolicy` is advisory to anyone who does not choose to call it.
   *Mitigation: tier 2 and tier 3. Status: not implemented.*
6. A snapshot is written by the control process without a passphrase-protected
   copy, so a determined local user with tier 2 removed can edit it and re-seal.
   *Mitigation: the same as risk 3. Status: not implemented.*
