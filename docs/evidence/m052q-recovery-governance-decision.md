# M052Q — Recovery Governance Decision Gate

```
M052Q_STATUS                     = RECOVERY_GOVERNANCE_DECISION_REQUIRED
RECOVERY_GOVERNANCE_DECISION     = NONE
DECISION_AUTHORITY               = NOT_SUPPLIED
PROVENANCE_SEAL_ID               = NOT_SUPPLIED

PRODUCTION_CHANGED               = NO
PRODUCTION_RECOVERY_PERFORMED    = NO
ACCIDENTAL_ACE                   = STILL PRESENT
D3_DENY                          = NOT_APPLIED
SUBJECT_LAUNCH                   = NOT_ATTEMPTED
D4                               = NOT_IMPLEMENTED
GATE_1 = CLOSED    GATE_2 = CLOSED    A/B/C = NONE
T_BABY_1                         = SATISFIED (M052H, unchanged)
SECURITY_OBJECTIVE               = NOT_SATISFIED — shortfall 5 of 8
RECOVERY_AUTHORISATION           = NOT_ISSUED
RECOVERY_CAPABILITY_FOR_PRODUCTION = NO
```

> **No option was selected.** This milestone sought one explicit director decision and did not
> receive it. It records the options, the evidence that no decision exists, and exactly what a valid
> decision must carry. Production is untouched.

---

## 1. Current incident state

```
target        subject_runtime\runtime\m016_read_fixture.exe
subject SID   S-1-5-21-2406520953-1060965512-844951592-1022
ACE           explicit DENY, mask 0x00000001 (FILE_READ_DATA)
content       25 bytes, sha256 55250a71209a4d39…   (matches M052O/M052P exactly)
owner         unchanged      protection  unchanged
paths w/ ACE  ['runtime\\m016_read_fixture.exe']  — exactly one
```

`0x00000001` is not the D3 mask (`0x000D0156`) and not one of the eight objective rights, so the
accidental ACE contributes **no credit** toward D3.

## 2. Read-only reconciliation — 18/18 pass

All eighteen M052P checks still pass, including `13_no_governance_decision`,
`14_no_recovery_authorisation`, `15_no_capability_unlocks_recovery`, `16_subject_not_launched`, and
`18_m052o_proof_intact`. Production matches the M052P starting state descriptor-for-descriptor:

```
v1 incident-state   8a0a66323bb4eb3b…
v2 incident-state   7d592c7a03bf7a6f…
pre-incident v1     f73eaf783ffb2698…   PRESERVED, never rewritten
```

## 3–5. The three options, as they stand

### R1 — distinct recovery governance class

Remediation of a documented existing unauthorised mutation is its own governance class, with its own
`RecoveryAuthorisation`, `RecoveryCapability`, recovery interlock, writer, target/ACE/prestate/
poststate binding, mechanism digest, single-use nonce and capability, and fail-closed semantics.

- **R1 classifies only.** It does not authorise recovery; a fresh explicit `RecoveryAuthorisation` is
  still required.
- **R1 does not resolve A/B/C** for ordinary future mutation — that stays `NONE` unless separately
  decided.
- R1 authority must not be able to apply D3, add a deny, restore an ACE, or touch another path,
  principal or mask.

### R2 — recovery subject to A/B/C

Recovery is governed by the same Gate-2 policy as ordinary future mutation, so **A/B/C must be decided
before recovery may advance**. `RecoveryAuthorisation`/`RecoveryCapability` remain structurally
separate from `ProductionAuthorisation`/`ProductionCapability`.

- **R2 collapses nothing**, but it makes A/B/C a hard dependency.
- Under R2 with A/B/C still `NONE`, this milestone would record `A_B_C_DECISION_REQUIRED` and stop.

### R3 — distinct class with its own second-gate policy

Recovery is distinct from ordinary mutation *and* keeps a deliberate second gate, specified by a
written `RECOVERY_GATE_2_POLICY` stating: what opens the gate; who may open it; whether a second human
approval is required; the provenance record/seal; what capability is minted and its exact scope;
single-use requirement; failure handling; D3 separation; rollback separation.

- "Recovery can use its own gate" is **not sufficient**.
- A policy is **not inferred from R3 itself**. Missing or incomplete → `RECOVERY_GATE_2_POLICY_REQUIRED`.

## 6. Comparative governance analysis

Inherited from M052P's twelve-criteria evaluation, restated for the choice:

| | R1 | R2 | R3 |
|---|---|---|---|
| remediation / future separation | strongest | weakest | strong |
| governance bypass risk | medium | lowest | lowest |
| recovery→D3 confusion risk | low | low | low |
| recovery / rollback separation | strong | strong | strong |
| provenance clarity | strong | medium | strong |
| capability & interlock separation | needs new | strongest | needs new |
| blocks recovery today | no | **yes** (needs A/B/C) | no, but needs a policy first |
| new surface created | recovery capability+interlock | none | recovery capability+interlock+policy |

**Costs, not hidden:** R1's risk is precedent — a "remediation" exemption could later smuggle
ordinary mutation. R2's cost is that production stays in the incident state longer. R3's cost is a
third policy to keep consistent.

**No recommendation is made here.** A recommendation is not a decision, and M052P already declined to
select.

## 7–9. Selected option, authority, provenance

```
selected_option        = NONE
authority_id           = NOT_SUPPLIED
authority_type         = NOT_SUPPLIED
provenance_seal_id     = NOT_SUPPLIED
verification_result    = NOT_APPLICABLE — no decision object exists to verify
```

**Searched for a decision, and found none:**

| Where | Result |
|---|---|
| `docs/evidence/*.md` (`selected_option`, `RECOVERY_GOVERNANCE_DECISION`, `decision_class`) | only the value `NONE`, in M052P |
| tracked code (`git grep` recovery_governance) | no match |
| provenance ledger `HEAD.json` | `PROV-000014`, `signing_role: HUMAN`, 14 entries |
| existing seals | 10 ids, `PROV-000004`…`PROV-000014` — **none** mention recovery, R1/R2/R3, or the incident |
| this milestone's input | the prompt, which is explicitly not authorisation |

- **Conflicting decisions:** none — nothing to conflict.
- **Unverifiable seal:** not applicable; no seal was supplied.
- → classification **`RECOVERY_GOVERNANCE_DECISION_REQUIRED`**.

I did **not** reuse `PROV-000014` or any other seal: those record unrelated decisions, and reusing one
would forge provenance.

### What a valid decision must carry

The repository's established authority is the signed provenance chain
(`human_control/provenance/seals/PROV-*.json`, each with `seal_mac`, `signing_key_id`,
`signing_role: HUMAN`, `sealed_at`, `head_seq`). A decision record must therefore include at minimum:

`decision_id` · `decision_class=RECOVERY_GOVERNANCE` · `selected_option=R1|R2|R3` · `authority_id` ·
`authority_type` · `decision_text` · `scope` · `effective_for_milestone` · `exclusions` ·
`provenance_seal_id` (an existing, verifiable seal) · `timestamp` · `issuer_identity` ·
`repository_HEAD` · `incident_reference` · `predecessor_decision_reference` · `supersedes` ·
`rationale`

and must state explicitly that it is **governance classification only** and **does not itself authorise
production recovery**.

## 10–13. A/B/C, authorisation, capability

- **A/B/C = NONE.** M052Q does not decide it. Under R1 it stays `NONE`; under R2 it becomes a
  dependency; under R3 it stays a separate ordinary-production question. R3 is not a covert route to
  deciding it.
- **`RecoveryAuthorisation` = NOT_ISSUED.** A future one must still bind exactly: one target, one SID,
  one ACE, one mask, one prestate, one poststate, one frozen mechanism, one nonce, one purpose, one
  failure policy.
- **`RecoveryCapability` valid for production = NO.**
- **Production mutation = NONE.**

## 14–16. D3, subject, regression

D3 `NOT_APPLIED`; subject `NOT_ATTEMPTED`; D4 `NOT_IMPLEMENTED`; objective still `NOT_SATISFIED` with
shortfall 5 of 8; `T-BABY_1` `SATISFIED` by M052H. M052Q ran no disposable recovery test, so there
was no disposable state to restore. Regression is unchanged from M052P: the 7 incident-caused
M052K/M052L fingerprint failures remain and were **not** weakened; standing reds unchanged at 12
failed / 65 passed.

## 17. Git

HEAD `6766c5b` unchanged; nothing staged; nothing committed; no historical evidence rewritten; no
pre-incident fingerprint altered. This record is a new file.

## 18. Next gate

```
M052Q_NEXT_GATE = RECOVERY_GOVERNANCE_DECISION_REQUIRED
```

Not `READY_FOR_PRODUCTION_RECOVERY` — not because the mechanism is unproven (M052O proved it exact and
M052P's 40-case matrix passed), but because governance prerequisites are unresolved and technical
readiness is not permission.

To advance, supply an explicit `RECOVERY_GOVERNANCE` decision selecting R1, R2 or R3, with an authority
and a verifiable provenance seal id. If R2, A/B/C must follow. If R3, a written
`RECOVERY_GATE_2_POLICY` must follow. Even then, recovery executes only in a later milestone under a
fresh, explicit `RecoveryAuthorisation`.

---

## Non-cognitive scope

M052Q concerns filesystem governance, authorisation, provenance, recovery policy, ACL mutation safety,
and incident remediation. It establishes nothing about cognition, consciousness, subjective
experience, agency, learning, memory, intelligence, developmental stage, sentience, model inference, or
subjective state. No option was chosen, no authorisation issued, and no production descriptor altered.
