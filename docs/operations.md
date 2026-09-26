# Operations

Day-to-day use of the laboratory. Every command here has been run; nothing is
aspirational.

## Initialise

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

Creates the layout, provisions `HUMAN` and `SYSTEM` keys, records the baseline in
the signed ledger, and emits the first events. Idempotent: existing keys and
ledger data are never overwritten. Re-run with `-Force` only if you intend the
non-destructive steps to repeat.

Equivalent manual form:

```powershell
python -m babylab.bootstrap
```

## Watch the stream

```powershell
python -m observer.cli                              # follow, colour
python -m observer.cli --no-follow --max-history 50  # last 50, then exit
python -m observer.cli --summary                     # counts by type
python -m observer.cli --namespace security         # one namespace
python -m observer.cli --detail --source --hash      # everything
```

Read-only. Ctrl-C to stop. Wrapper: `scripts\start_observer.ps1`.

## Check integrity

```powershell
python -m provenance.cli verify
powershell -ExecutionPolicy Bypass -File scripts\verify_integrity.ps1
```

Exit code `0` means the chain, every signature, every referenced file digest,
and the seal all agree. Anything else means **treat the ledger as untrustworthy
until a human explains the difference.** Do not "fix" it by re-sealing: re-sealing
destroys the evidence that something changed.

Also available:

```powershell
python -m provenance.cli summary     # entry counts by author and action
python -m provenance.cli keyring     # registered keys, and an audit of their material
python -m provenance.cli seal --reason "before experiment run 1"
python -m provenance.cli record --reason "wrote the run notes"
```

`verify` prints, every time, the list of things inside protected areas that the
ledger deliberately does not track, with the reason for each. An exclusion
nobody is shown is an exclusion nobody is reviewing.

## Recording a file you created yourself

Creating a research file outside the recorder is normal — an operator writes the
experiment log in an editor, not through an API. `verify` will then correctly
report an *unrecorded creation*. The fix is to record it, not to weaken the
audit:

```powershell
python -m provenance.cli record --reason "wrote the run notes"
python -m provenance.cli seal   --reason "run notes recorded"
```

With no `--path`, `record` picks up every unrecorded creation the audit finds.
It signs under the `HUMAN` key, because a human did the writing.

Do **not** reach for `--fast` to make a failing verify pass. `--fast` skips MAC
verification and exists for throughput measurement, not for reassurance.

## Run the control process

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_control.ps1   # background
python -m control.cli status
python -m control.cli inspect
python -m control.cli snapshot --label before-run
python -m control.cli shutdown
```

The server refuses to start if the token is missing or corrupt. There is no
unauthenticated mode.

## Run the tests

```powershell
python -m unittest discover -s tests -t .
powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
```

Safe to run against a live laboratory: every test uses an isolated temporary
`BABYAI_HOME`.

## Audit trust boundaries

```powershell
powershell -ExecutionPolicy Bypass -File scripts\trust_boundaries.ps1
```

Read-only. Reports the elevation state, whether tier 2 is configured, and the
current ACLs. Passing `-Apply` without `-AiServiceAccount`, or without
elevation, is refused rather than partially applied.

## A research session, end to end

```powershell
# 1. Confirm the laboratory is intact before you trust anything it says.
python -m provenance.cli verify

# 2. Anchor the current state so post-run differences are attributable.
python -m provenance.cli seal --reason "pre-run baseline"

# 3. Start the control process.
powershell -ExecutionPolicy Bypass -File scripts\start_control.ps1

# 4. Take a labelled snapshot.
python -m control.cli snapshot --label "pre-run"

# 5. Watch.
python -m observer.cli --detail

# 6. Snapshot the end state and stop cleanly.
python -m control.cli snapshot --label "post-run"
python -m control.cli shutdown

# 7. Verify and seal again.
python -m provenance.cli verify
python -m provenance.cli seal --reason "post-run baseline"
```

## What to do when verification fails

1. **Stop.** Do not append to the ledger and do not re-seal.
2. Read the reported problem. `provenance.cli verify` names the sequence number
   and what disagreed.
3. Determine whether the cause is corruption (a truncated write, a full disk) or
   tampering. `verify_paths` distinguishes *unrecorded modification* from
   *unrecorded creation* from *recorded but missing*.
4. If it is an unrecorded creation that you caused — writing a research note
   outside the recorder — record it (`provenance.cli record`) and re-seal. That
   is a bookkeeping fix, not tampering.
5. Copy the ledger somewhere immutable before investigating anything you did not
   cause. You will want the original bytes.
6. Record the finding in `research/experiment-log.md`, including the time, what
   you found, and what you did. A laboratory that quietly repairs its own
   evidence teaches its operator nothing.

## Routine maintenance

- **Back up `human_control/` and `var/` together.** They are two halves of one
  record; a backup containing only the ledger proves nothing.
- **Never delete `var/provenance/seals/`.** They are the anchors.
- **Seal before and after every significant run.** It costs a second and turns
  "something changed" into "something changed between these two points".
- **Do not edit JSONL by hand.** `verify` will detect it, but detection after the
  fact does not restore the original.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `Control token not found` | `bootstrap.ps1` has not been run. |
| `refusing to write ... outside ...` | A snapshot label escaped its directory. Should be impossible; the label is sanitised. |
| Observer shows `MALFORMED` lines | A partially written line, or hand-editing. The observer continues by design. |
| `cannot reach control process` | The server is not running, or the port in `human_control/experiment_config/control.json` does not match. |
| `Address already in use` | Another control process is running. `python -m control.cli status` will find it. |
| Garbled `…` or `—` in piped output | Resolved: output is forced to UTF-8. If you still see it, you are running an old copy. |
| `Access is denied` from `trust_boundaries.ps1 -Apply` | Not elevated. Open PowerShell as Administrator. |
