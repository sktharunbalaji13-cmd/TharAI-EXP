# ADR-005: Keys and runtime data live under `var/`, secrets excluded from Git

- Status: Accepted
- Date: 2026-09-26
- Milestone: 001

## Context

The first layout put `events/` and `provenance/` at the repository root as both
package and data directories, so `events/events.jsonl` sat next to
`events/model.py`.

That is a collision waiting to happen. Importing a package should never be able
to mutate data, a stray `rm events/*` would take out the source, and backups
would capture the two together. A research project accumulates a lot of data
over time, which makes it worse rather than better.

Separately, there is a question of what belongs under version control at all.

## Decision

**1. Runtime data lives under `var/`.**

| Path | Contents |
| --- | --- |
| `var/events/events.jsonl` | Event log |
| `var/provenance/ledger.jsonl` | Signed provenance ledger |

The top-level package directories are now pure code and contain no data.

**2. Git tracks code and documentation, not data or secrets.**

| Tracked | Not tracked |
| --- | --- |
| `babylab/` `events/` `provenance/` `observer/` `control/` `tests/` | `var/` |
| `scripts/` `docs/` `research/` | `human_control/security/keys/private/**` |
| `LICENSE` `README.md` `pyproject.toml` `.gitignore` | `human_control/security/control.token` |
| | `human_control/` records, baseline, snapshots, seals |
| | `baby_workspace/` |

**3. Private keys are stored as files with restricted ACLs, unencrypted.**

## Rationale for unencrypted keys

Encrypting the private keys with a passphrase would protect them only if the
passphrase lived somewhere other than the repository. If it is in the repository,
it protects nothing. If it is in the operator's head, then a compromise requiring
neither the file nor the passphrase is out of scope for a local research
laboratory, and the complexity is not justified.

Key custody here is therefore *filesystem permissions* — which is tier 2, which
is **not active** in this environment. That is stated plainly in
`docs/security-model.md#key-custody` rather than implied to be otherwise.

## Consequences

- Importing `events` cannot touch `var/`, and the failure mode is structural
  rather than a convention.
- `.gitignore` is the only thing standing between a private key and a commit, so
  it is reviewed rather than written once. `tests/test_trust_boundaries.py`
  asserts that the sensitive paths are covered.
- A fresh clone has no keys, no token, and no ledger. `bootstrap.ps1` provisions
  them, deliberately, because a key committed to a repository is a key in every
  clone of it.
- Backups must capture `human_control/` and `var/` **together**. They are two
  halves of one record; a backup of the ledger alone proves nothing.
- The unsealed-key risk is real and enumerated as residual risk 1 in the security
  model. The mitigation is tier 2, not this file.
