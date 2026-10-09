# M076 — Auth-1 Human Authorization Readiness (Tier-3 Identity Setup)

**Status: READINESS PACKAGE ONLY.** No account created, no credential issued, no
group/privilege/ACL change, no probe run, no birth/launch authorized. Signature
requires a separate explicit human signing ceremony through the established
process; a conversational "yes" is not permission.

**Baseline (verified 2026-10-09, read-only):** branch `master`, HEAD `69c3766`
== `origin/master`; clean tracked tree; ledger 18 entries, head `PROV-000018`,
chain/MAC/seal intact; Gate 1 CLOSED (D3), Gate 2 CLOSED, holds ACTIVE; no
subject, birth, launch, model/runtime selection, or credentials.

## 1. Proposed account (PROPOSED — not approved, not created)

- Name: `babyai-subject` (user-stated preference, recorded as proposal only).
- Availability (read-only check 2026-10-09): absent (`NET HELPMSG 2221`, user
  name could not be found) — no conflict, no claim of suitability beyond absence.
- Distinct from operator (`k.tharun balaji`, SID `...-1001`) and from the Tier-2
  ACL stand-in (`BABY_AI_TEST`, SID `...-1022`, which exists and is untouched).
- Type: local standard user; non-administrative; Medium integrity or lower.
- Approval of the name itself remains an explicit human decision at signing.

## 2. Auth-1 scope (action-by-action; setup + immediate verification ONLY)

| Operation | Target / resource | Privilege needed | Expected state change | Verification evidence | Recovery action | Forbidden side effects |
|---|---|---|---|---|---|---|
| Create local account | name from §1 (human-confirmed) | elevated human session | one enabled non-admin account | `net user` record + SID read | disable account (separate auth if contested) | admin membership; extra groups; password storage |
| Verify group baseline | new account | read-only | none (observation) | group list = Users-equivalent minimum | n/a (read) | privilege grants |
| Verify workspace reachability | subject workspace paths | read-only (+ controlled create/delete on disposable scratch only) | at most disposable scratch files | command + raw output + timestamp | remove scratch files | touching protected paths |
| Verify token readability | new account (interactive session) | human session | none | token SID read == provisioned SID | n/a (read) | accepting operator token |
| Record evidence | evidence docs + M073 fields | none (files only) | two review artifacts at most | hashes + reviewer sign-off | n/a | ledger/seal writes without signing ceremony |
| Refuse fallbacks | every step | none | refusal records where triggered | NOT READY / refusal log | n/a | operator-as-subject acceptance |

Excluded in full: real Tier-2 probes; production ACL changes beyond the
two-parent deny scope (which itself needs its own authorization + rollback
plan); network changes; model/runtime selection/deployment; birth; launch;
credential issuance to any party; gate movement; hold removal; any item not
listed above. Anything unlistable here is unresolved, not permitted.

## 3. Recovery and safety review (design verified, never executed)

- Missing/conflicting account name → refusal before any privileged call.
- Unexpected membership/privileges → stop; no remediation in-band.
- Post-setup SID captured and compared to intended identity; mismatch → stop.
- Token mismatch never falls back (established refusal pattern, tested).
- Operator recovery access preserved (per-SID denies only; `UNSAFE_DENY_TARGETS`
  honored; operator manageability re-verified after every change).
- Credentials never printed, committed, or placed in evidence (interactive entry
  only; storage prohibited).
- Partial setup reported explicitly as incomplete, never as success.

## 4. Authorization process (established M054/M056/M064 precedent)

1. Canonical JSON decision record (exact fields, canonical bytes + SHA).
2. Explicit human round 1: authority ID designation (never inherited).
3. Explicit human round 2: signing approval of exact bytes (record + seal).
4. `record --action create` under the HUMAN key + `seal` (mechanism only, no
   invented seal/decision IDs — IDs assigned from the human's stated decision).
5. Verification (chain, MAC, seal, bindings) before the milestone closes.

## 5. Human fields required (all UNRESOLVED until the ceremony)

Authority ID + role; account-name confirmation (`babyai-subject` or replacement);
Auth-1 scope approval (table above verbatim or amended); forbidden-operations
acknowledgment; signing approval for record + seal. Decision ID assigned at
signing from the human's stated decision (format `M076-AUTH1-XXX`).

## 6. Readiness: READY FOR HUMAN SIGNATURE

The package is complete and reviewable; every gate, refusal, recovery, and
forbidden item is specified. Blocked items: NONE technical — all remaining
inputs are human decisions exercised AT signing (name confirmation, scope
approval, seal approval). Until a valid Auth-1 record exists (sealed, HUMAN
key), Tier-2 probe sessions, provisioning, and all downstream work remain
BLOCKED. A conversational "yes" authorizes nothing.

## 7. Authority statement

M076 creates no account, issues no credential, authorizes no probe, establishes
no launch readiness, and grants no authority for production, ACL, network,
deployment, birth, launch, or gate changes. Auth-2 (Tier-2 sessions) stays
separate and unauthorized.
