# Git integration

## Purpose

Git is used for source control, history, and review. It is **not** used as a
security boundary, and this document explains why in detail, because conflating
the two would undermine the provenance ledger's meaning.

## What Git is not trusted with

A Git commit records an `author` and a `committer` name and email. Those fields
are:

- Typed by the person running `git commit`, into a local config file.
- Entirely self-reported. Nothing verifies them.
- Rewritable afterwards with `git commit --amend` or a filter script.
- Not a cryptographic signature of anything.

So a commit saying `SYSTEM <system@localhost>` is a **label**, not a claim the
ledger will honour. If the laboratory needs SYSTEM authorship, it comes from the
`SYSTEM` key in `human_control/security/keys/`, never from a commit header.

This distinction is enforced by design in `provenance/keyring.py`: authorship is
derived from key material, and a caller-supplied role is discarded and recorded
as a conflict. See [provenance-model.md](provenance-model.md).

## Why the runtime data is not in Git

| Path | Tracked? | Why |
| --- | --- | --- |
| `var/events/events.jsonl` | no | The event log grows without bound and is evidence, not source. |
| `var/provenance/ledger.jsonl` | no | Same, and a committed ledger invites accidental amendment. |
| `human_control/security/keys/private/**` | **no** | Private key material. Never commit, even in a private repository. |
| `human_control/security/control.token` | **no** | Bearer secret. Committing it publishes the control plane. |
| `human_control/**` (records, baseline, snapshots) | no | Operator-generated research records, not code. |
| Source, tests, docs, scripts | yes | The reproducible part of the laboratory. |

The rule is simple: **code and its documentation are versioned; data and secrets
are not.** `baby_workspace/` is the future subject's area and is likewise
untracked by default, because a subject's generated artefacts are observations.

## What is tracked

```
LICENSE  README.md  pyproject.toml  .gitignore
babylab/  events/  provenance/  observer/  control/  tests/
scripts/  docs/  research/
```

Empty directories carry a `.gitkeep`, because Git does not track empty
directories and a missing `human_control/experiment_config/` would be an
inexplicable failure for whoever clones the repository next. `.gitignore`
preserves the directory scaffolding with negation rules while excluding the
contents, which is why a fresh clone still has the expected shape.

## Branching

| Branch | Contains |
| --- | --- |
| `main` | Released, verified milestones. |
| `milestone/001-instrumentation` | The current work. |

Each milestone is one branch, reviewed, then merged. Milestone branches are not
deleted after merge, because the commit that introduced a milestone is itself
part of the record.

## Commit messages

Messages describe what changed and why, referencing the milestone and the
relevant component. They follow the style already in the history, and
AI-authored commits are labelled as such in the message body:

```
control: refuse control-plane start without an auth token

An unauthenticated control plane is worse than none: it looks like a
safety mechanism while providing none. Server now fails closed when
human_control/security/control.token is missing or corrupt.

Milestone: 001
```

## Signing commits

Commit signing (`git commit -S`, GPG) is **not** configured for Milestone 001.
It would be a genuine improvement over an unsigned commit, but it is a separate
mechanism from the provenance ledger and confusing the two would imply the
ledger's guarantees extend to commits, which they do not. If commit signing is
added later it should be documented here as a separate, additional guarantee.

## Cloning the repository

```powershell
git clone <url> TharAI-EXP
cd TharAI-EXP
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
python -m unittest discover -s tests -t .
```

A clone has no keys, no token, and no ledger. `bootstrap.ps1` provisions them
fresh. This is intentional: keys are per-machine, and a key committed to a
repository is a key in every clone of it.

## What Git does not give the experiment

Worth stating explicitly, because it is the tempting gap:

- **No protection against local tampering.** A researcher with write access to
  the working tree can change the source, rerun it, and produce a clean-looking
  result. The provenance ledger records that the protected *data* was not
  altered; it cannot record that the *code that produced it* was not altered.
- **No protection against a rewritten history.** `git reflog expire` and a
  force-push erase the evidence. A pushed-to-remote copy is the mitigation, and
  even that is a matter of trusting the remote host.
- **No timestamp authority.** A commit timestamp is the committer's clock.

Closing these gaps needs the external-witness mechanism described in
`docs/decisions/ADR-006`: the ledger head sealed somewhere the operator cannot
rewrite unilaterally. That is not implemented.
