# ADR-002: Standard library only at runtime

- Status: Accepted
- Date: 2026-09-26
- Milestone: 001

## Context

The laboratory must keep running for years, possibly on an offline machine,
possibly on a machine nobody maintains. Every runtime dependency is a future
failure mode: a version conflict, a wheel that will not build on a new Python, a
transitive package with a CVE, a resolver that needs network access to start.

The specific need that could have forced a dependency — cryptographic signing —
has a standard-library option in `hmac` and `hashlib`.

## Decision

Runtime code uses the Python standard library only. No third-party packages in
`babylab/`, `events/`, `provenance/`, `observer/`, or `control/`.

`pyproject.toml` declares `pytest==8.3.4` as an **optional** development extra.
The canonical test command is `python -m unittest discover -s tests -t .`, which
requires nothing installed.

## Consequences

- The laboratory runs on a bare Python install with no network access.
- Provenance signing uses HMAC-SHA256 rather than Ed25519, because
  `cryptography` is not in the standard library. This is a real security
  compromise; see `ADR-003`.
- Windows file locking is implemented directly against `msvcrt.locking` rather
  than via `portalocker` or `filelock`.
- Some conveniences are unavailable and were written by hand instead: canonical
  JSON, atomic writes, the cross-process lock, and the terminal renderer.
- Test count and coverage are ours to maintain, with no upstream maintenance of
  the test framework.
