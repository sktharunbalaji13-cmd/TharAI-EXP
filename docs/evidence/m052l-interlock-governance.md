# M052L — Gate 2 Governance and Execution-Path Resolution

```
M052L_STATUS                = AWAITING_DIRECTOR_DECISION

GATE_1_STATUS               = CLOSED — no ProductionAuthorisation exists
GATE_2_STATUS               = CLOSED — no capability issued; no GovernanceDecision exists

PRODUCTION_CHANGED          = NO
PRODUCTION_ACL_CHANGED      = NO
PRODUCTION_FINGERPRINT      = UNCHANGED (v1 f73eaf78… / v2 1684a02f… exact)
SUBJECT_LAUNCH              = NOT_ATTEMPTED
D4                          = NOT_IMPLEMENTED
T_BABY_1                    = SATISFIED (established_by M052H, unchanged)
D3_DENY                     = NOT YET APPLIED
SECURITY_OBJECTIVE          = NOT_SATISFIED — shortfall 5 of 8

VALIDATION                  = 16/16 PASS (M052L) · 38/38 PASS (M052K after the fix)
TESTS                       = 165 passed across M052L + M052K + M052J + M052I
STANDING_REDS               = 12 failed, 65 passed — unchanged
```

> This milestone resolved the mechanism and **left the question open**. It did not open Gate 2, did
> not fabricate an authorisation, and did not touch production.

---

## 1. A both-gates bypass existed in M052K

Reading the code rather than testing it found this immediately.

`apply_script` and `rollback_script` exported:

```python
allow_production: bool = False
```

That looks like a guard. It was an **opt-out**. The validator it fed
(`_assert_mutation_parameters`) mentioned neither `ProductionAuthorisation` nor
`_PRODUCTION_MUTATION_ENABLED`:

```
mentions ProductionAuthorisation          : False
mentions interlock                        : False
refuses production unless allow_production: True
```

So `apply_script(production_root, sid=ADMIN_SID, mask=0xFFFFFFFF, inheritable=False,
allow_production=True)` would have reached `SetNamedSecurityInfo` on canonical production with
**both gates bypassed** — no authorisation, no interlock, no nonce, no digest, no audit record.

The path was **not exercised and not taken**. Production is untouched, verified below.

### The fix

Canonical production is now refused **unconditionally**. There is no parameter, keyword, flag or
sentinel that lifts it — `allow_production` is gone from the module's code entirely. Consequences,
deliberate and not to be "fixed":

- no exported helper in `m052k_implementation` can mutate canonical production;
- `production_application()` therefore returns a decision state and **never writes**;
- the production write path **does not exist in the committed tree**. A future execution milestone
  must introduce it explicitly under the established governance mechanism, rather than discovering a
  flag that was already sitting there.

---

## 2. The old interlock was a suggestion, not a control

Measured:

```
before        : False
after assign  : True    <-- K._PRODUCTION_MUTATION_ENABLED = True, by any importer
restored      : False
```

A plain module boolean means "production ACL mutations are enabled". That is **broader** than the
single frozen operation M052K authorised, it is **reusable**, and it leaves **no audit record**.

### The replacement

A `ProductionCapability`, bound to every material dimension of the operation it authorises:

```
target · principal_sid · deny_mask · inheritance_flags ·
mechanism_digest · authorization_nonce · issued_by · issued_at · consumed
```

`ProductionCapability.violations(authorization)` compares each field against the authorisation, so a
capability for a different target, principal, mask, inheritance set, digest or nonce **is not this
capability**. It is single-use (`consumed`, plus `_ISSUED_NONCES` preventing a second capability being
minted for the same nonce), and every transition appends to an append-only `InterlockLedger`.

### What the capability is not

It is a governance control against **accidental or mistaken mutation by the operator's own tooling**.

It is **not** a security boundary against `BABY_AI_TEST`, and claiming otherwise would be the
overclaim this laboratory keeps refusing. Production currently *grants* the subject five of the eight
objective-denied rights; the control that actually stops the subject is the D3 ACL deny — which is
the milestone's **objective**, not its interlock. Any process already running as the operator can
defeat an in-memory flag because it can call the OS directly. That is a fact about in-process
authority, not a defect to engineer away, so it is documented rather than papered over.

---

## 3. The twenty questions, answered by measurement

All twenty answered; full table in `interrogate_twenty_questions()`. Summary:

| # | Question | Answer |
|---|---|---|
| 1–2 | What controls it / where | was a module boolean; now `ProductionCapability` + `InterlockLedger` in `tests/m052l_interlock.py` |
| 3 | Who may open it | **nobody yet** — `open_interlock` requires a `GovernanceDecision` and none exists |
| 4 | Evidence required | `decision_id`, `decided_by`, `rationale`, `provenance_seal_id` |
| **5** | **Is opening Gate 2 itself production-affecting?** | **UNRESOLVED — the open question** |
| **6** | **Does it need separate human authorisation?** | **UNRESOLVED — same gap, not assumed either way** |
| 7 | Persistent or single-use | single-use; per-nonce issue ledger prevents replay |
| 8 | Can a stale authorisation reopen it | no — invalid authorisation refused before a capability is built |
| 9 | Can Gate 2 open without Gate 1 | no |
| 10 | Can Gate 1 exist with Gate 2 closed | yes — the current, correct state: `BLOCKED_BY_MODULE_INTERLOCK` |
| 11 | Can Gate 2 exist without Gate 1 | no, by construction |
| 12 | Audit record on change | yes, in-memory ledger; refusals recorded too |
| 13 | Caller manipulation | **PARTIALLY — stated plainly**, see §2 above |
| 14 | env/argv/config/import bypass | none is consulted anywhere; matrix exercises each |
| 15 | Does it enable unrelated mutation | no — bound, not a general licence |
| 16 | Does closing revoke immediately | yes, unconditional and synchronous |
| 17 | Crash leaves it open | no — memory-only, dies with the process |
| 18 | Inherited by another process | no shared state; fresh interpreter starts closed |
| 19 | Replayable | no |
| 20 | Opened for a different SID/mask/target | no — those are capability fields, not parameters |

---

## 4. Lifetime, established by measurement

```
storage      in-memory module state      file-backed      no
process-local  yes                       registry-backed  no
persistent   no                         env-backed       no
survives process exit       no          IPC-backed       no
inheritable by another process  no     expected         fail closed
```

Deliberately the **least persistent** option available. A file- or registry-backed capability would
survive restart and be replayable, which no recorded governance decision currently authorises.

---

## 5. Adversarial matrix — 22 attempts, none permitted a mutation

Every outcome `REFUSED` / `AWAITING_EXPLICIT_HUMAN_AUTHORISATION` / `AWAITING_DIRECTOR_DECISION`
except one, and that one grants nothing:

| Attempt | Outcome |
|---|---|
| `production_application(None)` | AWAITING_EXPLICIT_HUMAN_AUTHORISATION |
| `production_application("apply D3")` / dict / `True` | REFUSED |
| `open_interlock(no decision)` | AWAITING_DIRECTOR_DECISION |
| `open_interlock(decision-shaped, no auth)` | AWAITING_EXPLICIT_HUMAN_AUTHORISATION |
| `evaluate(None)` / `evaluate("string")` | AWAITING / REFUSED |
| environment override (3 vars set) | REFUSED |
| **monkeypatch `K.production_application`** | ACCEPTED — *replaced a function; grants nothing, capability is None* |
| legacy global assignment | REFUSED |
| **direct `_CAPABILITY` assignment** | REFUSED — *forging it does not help, Gate 1 is independently invalid* |
| alternate import path | REFUSED |
| subprocess invocation | REFUSED |
| invalid authorisation × 7 (mask, sid, target, inheritance, digest, nonce, milestone) | REFUSED |

The two bolded rows deserve note: both are **reachable by any in-process caller**, and both are
recorded rather than hidden. Neither grants a mutation. A test asserts the set of ACCEPTED outcomes is
exactly that list, so a future change that makes something *else* succeed will fail loudly.

No valid `ProductionAuthorisation` is constructed anywhere in M052L or its tests. Every
authorisation-shaped object is deliberately invalid and asserted invalid.

---

## 6. Subject isolation on the governance surface — measured, and I was wrong first

My first hypothesis was that the human-control and provenance surface carried an incomplete deny that
`BABY_AI_TEST` could defeat. **Measured with the subject's real baseline token** (Everyone +
Authenticated Users + Users), not by scanning ACEs that name it — an ACE scan is the wrong method here
because the subject's grants arrive through inherited groups:

| File | subject effective | forbidden present | WRITE_DAC | DELETE |
|---|---|---|---|---|
| `human_control/security/control.token` | `0x000200A9` | **none** | no | no |
| `human_control/provenance/HEAD.json` | `0x000200A9` | **none** | no | no |
| `human_control/experiment_config/control.json` | `0x001301BF` | **5** | no | **yes** |

The first two are **properly protected** — all eight objective-denied rights absent. My hypothesis
was wrong and is corrected here rather than quietly dropped.

The real finding is the third file: **`control.json` carries no explicit subject deny at all.** It is
the indirection that names `token_file`, i.e. which token file is authoritative.

Why this is a finding and not a live breach: the subject cannot change an ACL there, because
`0x001301BF` excludes `WRITE_DAC` and `WRITE_OWNER`. So no gate is open today, and Gate 2 is bound to
an in-memory capability rather than to this file, so the subject cannot open Gate 2.

Why it still matters: **under Option B below — where the human-control channel is what opens Gate 2 —
this file becomes load-bearing**, and its subject-writability would have to be closed first. M052L
does not fix it: that requires ACL mutation on the governance surface, which this milestone is not
authorised to perform.

---

## 7. The governance question, left open

> **Is opening Gate 2 — enabling the execution path that can change canonical production ACLs — itself
> an act that requires explicit human authorisation?**

**The repository has no recorded decision.** The surrounding governance *implies* yes: a signed,
hash-chained provenance ledger (`human_control/provenance`, `seal_mac`, `signing_key_id`), a human
control channel (`control.json` → `control.token`), a re-derivable audit (`foundation/audit.py`
`reverify()`), and every prior production-affecting act human-gated.

But an implication is not a decision, and M052L must not manufacture one.

| | Option | Consequence |
|---|---|---|
| **A** | Gate 2 opening requires its own explicit human authorisation, recorded as a provenance seal | two distinct authorisations per mutation; strongest separation; most ceremony |
| **B** | Gate 2 opening delegated to the existing human-control channel under one recorded decision | integrates with the established authority model; one seal covers opening and write |
| **C** | Gate 2 removed as a separate gate; one authorisation both enables and performs the write | fewest steps; **abandons a deliberate safety property for convenience** |

**Recommendation: A**, on the evidence — this laboratory has human-gated every production-affecting
act, and the capability is security-sensitive by construction. **This is a recommendation, not a
decision.** It is labelled as such and has not been acted on.

Note that Option B carries a prerequisite discovered in §6: `control.json` must be protected first.

What was built meanwhile, so the milestone is not idle: the mechanism to implement whichever option
is chosen — a bound, single-use, audited capability that **cannot be opened until a decision exists**.

---

## 8. What did not happen

- No production ACL mutation. Production still has **0 explicit ACEs**, **0 subject ACEs**,
  fingerprints exact, `STAGING_BLOCKED`, owner unchanged, `model` absent, 3 M016 artifacts untouched.
- Gate 2 not opened. No capability issued. `open_interlock()` → `AWAITING_DIRECTOR_DECISION`.
- No authorisation fabricated. No valid `ProductionAuthorisation` exists anywhere.
- Objective still `NOT_SATISFIED`, shortfall **5 of 8**. Building a mechanism satisfies nothing.
- No property marked SATISFIED; the 15 D3-gated properties remain DECISION-BLOCKED.
- Subject not launched; no credential read. D4 not implemented. M019+A1 and M052H evidence untouched.
- Standing reds unchanged and unweakened: 12 failed, 65 passed.

## 9. Git

HEAD `6766c5b` unchanged, 37 commits, nothing staged, same 5 tracked modifications. Nothing committed.
Five untracked M052K/M052L files. No history rewritten, no unrelated work removed.

---

## Non-claims

M052L concerns execution-path governance only. It establishes nothing about cognition, consciousness,
subjective experience, agency, learning, memory, intelligence, developmental stage, sentience, or model
inference. A capability was modelled because a production write needs a governed door — not because
anything was learned about a mind.
