# M079 — Credential-Policy Evidence & Auth-1 Retry Readiness

**Status: POLICY EVIDENCE + READINESS CHECKLIST.** No Auth-1 operation executed,
no account created, no secret generated/requested/displayed/stored, no privilege/
ACL/network change, no gate moved, no provenance appended. This document records
a user-selected preference and the conditions for a future retry; it is not a
signed governance decision and authorizes nothing.

**Baseline (verified 2026-10-09, read-only):** branch `master`, HEAD `c2667d2`
== `origin/master`; clean tracked tree; Auth-1 digest recomputed EXACT
(`ed992f56…c1234`, 6 scope rows, 10 forbiddens); `PROV-000019` HUMAN/sealed,
chain 19 intact; Gate 1 CLOSED, Gate 2 CLOSED; `babyai-subject` absent
(re-checked); session NOT elevated; no subject/birth/launch/model/runtime.

## 1. Selected credential policy (preference, NOT a signed decision)

**POLICY_PREFERENCE_SELECTED — FORMAL_GOVERNANCE_STATUS: TO_BE_VERIFIED.**
Preference: secure interactive credential entry through an approved OS mechanism
(e.g. human-typed entry at a Windows credential dialog during a human-controlled
elevated interactive session). Secrets must never appear in prompts, source files,
command-line arguments, logs, commits, evidence artifacts, or provenance records.
If no safe interactive mechanism is available at execution time: fail closed, run
nothing. No password has been supplied or stored; none may be invented.
Elevation is an environmental prerequisite, never authorization by itself.

## 2. M078 stop record (why execution has not occurred)

M078 stopped twice before any system change: (a) session not elevated, (b) no
lawful password value and no formal credential-policy resolution at the time.
Zero of six Auth-1 operations executed; nothing to roll back. The preference in
§1 resolves (b) as a *planning input*; formal governance status remains
TO_BE_VERIFIED (criterion BLOCKED, honestly reported — see §5).

## 3. Retry-readiness checklist (all mandatory, fail-closed)

1. Human-controlled elevated interactive session actually available (re-check,
   do not assume).
2. Credential-entry mechanism approved for that session; no forbidden channels.
3. Auth-1 digest, 6-row scope, 10 forbiddens, authority binding, MAC, chain, seal
   freshly re-verified (recompute, never trust filenames).
4. `babyai-subject` confirmed absent immediately before setup (absence not reserved).
5. Operator confirms account name + authorized scope at execution time.
6. Only the six permitted operations run, unexpanded.
7. Post-setup SID/groups/privileges verified against intent.
8. Process-token verification performed independently (existence ≠ isolation).
9. Workspace checks stay within Auth-1 scope.
10. Any unexpected/partial state → immediate stop + precise report, no improvised
    recovery.
11. Auth-2 separate and unauthorized; no Tier-2 probes under Auth-1.
12. Gates, holds, and all downstream restrictions unchanged.

## 4. Stop conditions (retry aborts if ANY hold)

Missing elevated session; unsafe credential channel; digest/scope/MAC/chain/seal
mismatch; account present or ambiguous; unlisted operation requested; privilege
beyond minimum; operator recovery risk; unexpected identity state; any Tier-2/
network/model/birth/launch/gate step entailed.

## 5. Authority statement

This document is evidence of a preference and a checklist. It is NOT a signed
governance decision, NOT a seal, NOT Auth-1 execution, and NOT authorization for
Tier-2 probes, network/model/runtime changes, birth, launch, or gate movement.
Formal signing (authority designation + exact-byte approval + record + seal +
verify) remains a separate explicit ceremony. Holds ACTIVE; gates CLOSED.
