# Testing

## Running

```powershell
python -m unittest discover -s tests -t .                        # canonical
powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1    # wrapper
```

`pytest` is supported and pinned in `pyproject.toml`, but is **optional**. The
suite uses only `unittest`, so a researcher with a bare Python install and no
network access can still validate the laboratory. The optional runner exists as a
second opinion, not a requirement.

Current state: **189 tests, all passing**, roughly 48 seconds.

## Test tiers

The distinction matters more than the count, because it determines what a
passing run actually proves.

### Tier 1 — Application security tests (always run)

These verify the logic: `PathPolicy` refuses forbidden writes, authorship is
derived from a key rather than a declared string, the chain breaks when a field
is edited, an untagged control request is refused and logged.

They prove the code does what it says. They do **not** prove that a hostile
process cannot get around the code, because every test in this suite runs as the
same Windows user that owns the repository.

### Tier 2 — OS enforcement tests (not implemented)

The only test that would prove the boundary is real is: run something as the
restricted service account and confirm it cannot write to `human_control/`.
That requires an elevated session and a second principal. Neither is available
in this environment (`Test-Elevated` → `False`; `net user` → `Access is denied`),
so this tier is **NOT VERIFIED** and is not simulated or mocked into existence.

`scripts/trust_boundaries.ps1` is the tool that would enable it.

### Tier 3 — Adversarial tests (out of scope)

Running a deliberately hostile subject against the laboratory to find escape
routes. Valuable, and explicitly not part of Milestone 001.

## Layout

| File | Covers |
| --- | --- |
| `tests/support.py` | Isolated `BABYAI_HOME` per test, in-memory clock, provisioned keys and token. No test ever touches the real laboratory. |
| `tests/test_events.py` | Event creation, hash chaining, append, replay, malformed lines, concurrency, high volume. |
| `tests/test_provenance.py` | Keyring derivation, signing, verification, seals, protected-file lifecycle, bidirectional audit. |
| `tests/test_trust_boundaries.py` | `PathPolicy` rules, path containment, namespace and layout invariants. |
| `tests/test_observer.py` | Rendering, filtering, following, column alignment, malformed-line visibility, high volume. |
| `tests/test_control.py` | Protocol authentication, framing, lifecycle transitions, operations, snapshot labelling, token loading. |

## Isolation

Every test runs against a temporary `BABYAI_HOME` created in `setUp` and
registered for cleanup in `tearDown`. This guarantees that no test can read,
corrupt, or depend on the real laboratory in `var/` and `human_control/`.

Two consequences worth noting:

- The suite can be run against a live laboratory without risk.
- A test that accidentally reaches the real paths fails, rather than quietly
  succeeding against whatever happens to be on disk.

## Time and determinism

`tests/support.py` provides a controllable clock, so timestamps in assertions
are exact rather than approximate. Where a test needs a specific instant, it
passes one explicitly; the default is "now" for tests that only care about
ordering.

Assertions on entry counts are written as **deltas against
`self.baseline_entries`**, not absolute numbers. An absolute count silently
becomes a lie the next time the shared fixture gains a step, and the failure
looks like a provenance bug rather than a test-maintenance problem.

## What the tests caught

Recorded because a test suite that has never failed is a test suite nobody
trusts.

| Found | Fix |
| --- | --- |
| `EventStore.append_many` was O(n²): each append rescanned the whole log. | Head-entry cache keyed on file size. High-volume suite went from 110 s to 16 s. |
| A namespace longer than 11 characters pushed the headline out of alignment. | `fit_category()` right-truncates to a fixed column width. |
| `ProvenanceLedger.latest_for_path` rescanned the ledger for every version link. | Index cache, invalidated on size change; verification still reads from disk. |
| A control snapshot label containing `..` or a separator could steer the write outside `human_control/snapshots/`. | Label sanitised to `[A-Za-z0-9_-]` and capped at 48 chars, plus a containment check. |
| Under Windows console code pages, the observer's `…` became `\ufffd` when piped. | stdout/stderr forced to UTF-8 with `errors="replace"`. |
| The control test client hit a TCP RST instead of reading the error response, because it was still writing when the server rejected an oversized frame. | Client half-closes the write side before reading. |

## What is not tested

- OS-level denial (tier 2). Needs a second account.
- Behaviour under real concurrent multi-process load. The suite covers thread
  concurrency with a file lock; process-level contention is exercised only by
  the manual control-plane run.
- Windows console rendering fidelity. The suite strips ANSI codes and asserts on
  text, deliberately, so it does not depend on terminal capabilities.
- Anything about a subject, because no subject exists.
