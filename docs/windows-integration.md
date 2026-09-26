# Windows integration

The laboratory targets Windows 11 and uses the standard library only. This
document records the platform-specific decisions and the environment this was
actually built and verified in.

## Verified environment

| | |
| --- | --- |
| OS | Windows 11 |
| Python | 3.14.3 |
| Git | 2.52.0 |
| Shell | PowerShell 5.1 |
| Console encoding | Not UTF-8 by default — see below |
| Elevated session | **No** |
| Second Windows principal | **No** (`net user` → `Access is denied.`) |

## Why no third-party dependencies

Every runtime dependency is a future failure mode: a version conflict, a wheel
that will not build, a transitive package with a CVE, an offline machine that
cannot resolve it. For a research instrument that must still be running in five
years, the standard library is the more durable choice.

This is why provenance signing uses HMAC-SHA256 rather than Ed25519:
`hmac` and `hashlib` are in the standard library, and `cryptography` is not. The
trade-off is documented honestly in
[provenance-model.md](provenance-model.md#consequences-of-using-hmac) and the
alternative is recorded in `docs/decisions/ADR-003`.

`pyproject.toml` lists `pytest==8.3.4` as an **optional** development extra
only. The canonical suite is `python -m unittest discover -s tests -t .` and
needs nothing installed.

## File locking

`babylab/storage.py` implements `exclusive_lock(path)`, a cross-process advisory
lock built on `msvcrt.locking` on Windows and `fcntl.flock` elsewhere. It is used
around every append and every read-modify-write of the shared logs.

It is **advisory**: a process that does not take the lock is not stopped. That is
the same limitation as tier 1 in the security model, and it is why the OS-level
boundary in `scripts/trust_boundaries.ps1` exists as a separate concept.

## Timestamps

`babylab/clock.py` emits UTC with millisecond precision:
`2026-09-26T19:04:12.482Z`. UTC rather than local time, because a research log
that shifts meaning when the researcher changes timezone or crosses a daylight
saving boundary is a research log that cannot be trusted later. Local time is
available for display only.

## Filenames

Snapshot filenames strip colons and fractional seconds
(`2026-09-26T19:04:12.482Z` → `20260926T144704Z`) because colons are illegal in
Windows filenames. Operator-supplied labels are additionally sanitised to
`[A-Za-z0-9_-]` and capped, then checked for path containment.

## Console encoding

This one cost real debugging time, so it is recorded.

PowerShell 5.1 does not use UTF-8 by default. When the observer's output is
piped — into a file, into `Select-Object`, into any log collector — Python
selects the ANSI code page, and a single `…` or `—` becomes `\ufffd`. The
visible symptom is a corrupted research record in exactly the tool whose job is
to display the record faithfully.

Both observer streams are therefore reconfigured to UTF-8 with
`errors="replace"` at CLI entry, so the worst case is one visible `?` rather
than mis-decoded bytes. Colour is disabled automatically when stdout is not a
terminal.

## Running as a restricted account

The design intends the future subject to run as its own low-privilege Windows
account. That is not yet possible here, and the boundary is therefore not
enforced:

```powershell
# Audit only. Safe, no elevation needed.
.\scripts\trust_boundaries.ps1

# Apply. Requires an elevated session AND -AiServiceAccount.
.\scripts\trust_boundaries.ps1 -Apply -AiServiceAccount BABYAI
```

To create the account first (elevated):

```powershell
net user BABYAI <strong password> /passwordchg
```

After applying, verify enforcement rather than assuming it: run something as
`BABYAI` and confirm it cannot write to `human_control\`. Until that test passes,
tier 2 is **NOT VERIFIED** and must not be reported as working.

## Long paths

The repository path is short enough that `MAX_PATH` is not a concern today. If
the project is ever cloned deeper, the same scripts will hit the 260-character
limit; enable `LongPathsEnabled` in the registry or clone shallower.

## Process management

The control process is a plain foreground Python process. `start_control.ps1`
can background it and prints the PID; `python -m control.cli shutdown` is the
graceful stop. `Stop-Process -Id <pid>` is the blunt one. There is no Windows
service wrapper, because a service would need its own account and that is
tier 2, which is not yet in place.
