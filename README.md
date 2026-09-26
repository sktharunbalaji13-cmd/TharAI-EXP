# Baby AI Laboratory

Research instrumentation for observing a self-hosted AI system.

**Milestone 001 delivers the laboratory only — there is no AI here.** No model,
no agent, no memory, no goals, no self-modification. That absence is
deliberate: an instrument that contains the thing it measures cannot be trusted
to report on it. See [docs/architecture.md](docs/architecture.md) and
[docs/decisions/ADR-004-no-event-taxonomy.md](docs/decisions/ADR-004-no-event-taxonomy.md).

## Requirements

Windows 11 and Python 3.14+. No third-party packages are required; `pytest` is
an optional convenience only.

## Quick start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
python -m unittest discover -s tests -t .
python -m observer.cli
```

## What is here

| Component | Purpose |
| --- | --- |
| `babylab/` | Shared foundations: paths, hashing, storage and locks, clock, identity, trust policy |
| `events/` | Append-only, hash-chained event log |
| `provenance/` | HMAC-signed ledger of who changed what, with sealed heads |
| `observer/` | Read-only terminal view of the event stream |
| `control/` | Separate privileged process: lifecycle, snapshots, HMAC-authenticated loopback control |
| `human_control/` | Operator area: config, baseline, records, snapshots, seals, keys |
| `baby_workspace/` | Reserved for the future subject |
| `var/` | Runtime data: `var/events/`, `var/provenance/` |

Data and secrets are not in Git; code and documentation are. See
[docs/git-integration.md](docs/git-integration.md).

## Common commands

```powershell
# Watch the stream (read-only)
python -m observer.cli
python -m observer.cli --summary
python -m observer.cli --namespace security --detail

# Integrity
python -m provenance.cli verify
python -m provenance.cli seal --reason "pre-run baseline"

# Control process
python -m control.cli serve
python -m control.cli status
python -m control.cli snapshot --label before-run
python -m control.cli shutdown

# Tests
python -m unittest discover -s tests -t .
```

Full walkthrough: [docs/operations.md](docs/operations.md).

## Security posture

Read this before trusting any data this repository produces.

| Tier | Boundary | Status |
| --- | --- | --- |
| 1 | Application policy (`PathPolicy`) | **Active and tested** |
| 2 | OS file permissions (NTFS ACLs) | **Scripted, not applied, not verified** |
| 3 | OS account isolation / container | **Not implemented** |

Only tier 1 is in force, and it is the weakest of the three: it catches
accidents and attributes privileged writes, but a subject sharing the Windows
user can bypass it entirely. Tier 2 needs an elevated session and a second
account, neither of which was available during development
(`IsAdmin` → `False`, `net user` → `Access is denied`).

Provenance signing uses HMAC-SHA256, which is symmetric: the operator who can
verify the ledger can also forge entries. Recorded as open decision
[ADR-003](docs/decisions/ADR-003-provenance-signing.md).

Details and the full threat table: [docs/security-model.md](docs/security-model.md).

## Documentation

| Document | Contents |
| --- | --- |
| [architecture.md](docs/architecture.md) | Components, trust boundaries, data placement, extension points |
| [provenance-model.md](docs/provenance-model.md) | Chain construction, signing, seals, threat model |
| [security-model.md](docs/security-model.md) | The three tiers, control-plane auth, key custody, residual risks |
| [observer-interface.md](docs/observer-interface.md) | CLI reference, line format, following, performance |
| [control-protocol.md](docs/control-protocol.md) | Wire format, authentication, operations, state machine |
| [testing.md](docs/testing.md) | Test tiers, isolation, what the suite caught |
| [windows-integration.md](docs/windows-integration.md) | Locking, encoding, filenames, restricted accounts |
| [git-integration.md](docs/git-integration.md) | What is tracked, and why commits are not identity |
| [operations.md](docs/operations.md) | Day-to-day use, research workflow, troubleshooting |
| [experiment-log.md](research/experiment-log.md) | Dated research journal |
| [decisions/](docs/decisions/) | ADRs, including the ones still open |

## Design commitments

1. **No simulated subject.** The control plane reports honestly that nothing is
   attached to it. A fake subject would contaminate the first real observation.
2. **Authorship is derived from keys, never declared by the caller.** A declared
   author that conflicts with the key is discarded and the conflict recorded.
3. **The observer cannot write.** The human's view cannot influence the
   experiment.
4. **Faults are visible.** A malformed log line is rendered and flagged, never
   silently skipped; a gap in a research log would look like an absence of
   events.
5. **Limitations are written down.** Where a guarantee is not verified, the
   documentation says `NOT VERIFIED` rather than implying otherwise.

## License

MIT — see [LICENSE](LICENSE). The copyright holder is a placeholder pending
confirmation.
