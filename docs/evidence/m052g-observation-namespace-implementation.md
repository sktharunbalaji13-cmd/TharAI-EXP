# M052G — `T_OBSERVATION_NAMESPACE` Implementation (Design + Result)

```
M052G_STATUS            = OBSERVATION_NAMESPACE_IMPLEMENTED_FROZEN
M019_VERSION            = M019+A1
M019_HASH               = 7dceb7a5d7c3632f8d2faca393535e26…
NAMESPACE_IDENTIFIER   = T_OBSERVATION_NAMESPACE
IMPLEMENTATION_PATH     = C:\ProgramData\TharAI\observation\T_OBSERVATION_NAMESPACE
SUBJECT_SID             = S-1-5-21-2406520953-1060965512-844951592-1022
D3_STATUS               = UNRESOLVED_AND_OUT_OF_SCOPE
```

> Implementation results are in §11. This supersedes the `DESIGN_RECORDED_BEFORE_IMPLEMENTATION`
> status this record was written with; the design text in §1–§3 is preserved as it stood before any
> implementation existed.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed.

---

## 1. What M019+A1 requires, quoted from the authority

`T_OBSERVATION_NAMESPACE` is a **governed identifier, not a filesystem path**. A1 deliberately left
the location open, and specified:

| requirement | rule |
|---|---|
| Location | Outside canonical T. Not inside `subject_runtime`, `runtime`, `model`, `config`. |
| Ownership | Laboratory/operator. **Never `BABY_AI_TEST`.** |
| Provenance | Five mandatory fields per observation object. |
| Mutability | Subject gains **no** write/append/delete/`WRITE_DAC`/`WRITE_OWNER`/`WRITE_EA`/`FILE_WRITE_ATTRIBUTES`. |
| Separation | Not subject memory, experience, canonical state, model weights, runtime code, or provenance evidence. |
| Fixtures | Disposable fixtures stay disposable. Not promoted. |

**The five mandatory provenance fields** (A1 §19.3, not invented here):

1. experiment identifier
2. creation provenance
3. content hash
4. author/source classification
5. immutable association with the measurement it serves

---

## 2. Location analysis — why not the obvious candidates

### 2.1 The operator's profile is excluded by instruction and by measurement

`%TEMP%` and every prior rehearsal root live under `C:\Users\k.tharun balaji`. M052G forbids relying on
the operator's private profile as the governance boundary. It is also measurably wrong: a user
profile grants its owner full control, so "the subject cannot write here" would rest on the subject
not being the operator — which is an accident of identity, not a governance property.

### 2.2 `C:\dev` is excluded — it is the canonical subject boundary's ancestor

The repository is the production boundary's parent, and M043 established the repository is
subject-readable. Placing an observation input there would put governed measurement data inside the
production tree.

### 2.3 `C:\ProgramData` — usable, but **only with inheritance removed**

This is the decisive finding, and it is why the design does not simply "make a folder in
ProgramData":

```
C:\ProgramData  inherited ACEs
    NT AUTHORITY\SYSTEM:(OI)(CI)(F)
    BUILTIN\Administrators:(OI)(CI)(F)
    CREATOR OWNER:(OI)(CI)(IO)(F)
    BUILTIN\Users:(OI)(CI)(RX)
    BUILTIN\Users:(CI)(WD,AD,WEA,WA)      <-- WRITE, APPEND, WRITE_EA, WRITE_ATTRIBUTES
```

`BABY_AI_TEST` is a member of `BUILTIN\Users`. Measured subject effective access to
`C:\ProgramData` is **`0x001201BF`**, which decodes to include `FILE_WRITE_DATA` (`0x02`),
`FILE_APPEND_DATA` (`0x04`) and `FILE_WRITE_EA` (`0x10`).

So **any namespace created under ProgramData by inheritance would grant the subject write, append
and EA/attribute modification — an immediate violation of the absolute security boundary.** The
`Users:(RX)` ACE does not save it; the `(WD,AD,WEA,WA)` ACE does.

The design therefore treats ProgramData as an acceptable *machine-scoped* location **only because
every level this milestone creates has inheritance explicitly removed and its own explicit ACEs.**
Inheritance is the threat, and it is removed rather than trusted.

`C:\TharAI_Lab` at the drive root is not writable by this operator token, so it is unavailable.

---

## 3. Design decisions

### 3.1 Path layout

```
C:\ProgramData\TharAI\                                  <- laboratory root, operator-only
    observation\                                         <- subject RX (traverse + list only)
        T_OBSERVATION_NAMESPACE\                        <- subject RX
            observation_input.v1                         <- subject R  (the ONE governed object)
    provenance\                                          <- subject NO ACCESS
        T_OBSERVATION_NAMESPACE.provenance.json
```

Provenance is a **sibling store, not a child of the namespace**, so the subject has no traversal
path to it at all. M019+A1 §19.4 category 6 (provenance/evidence artifacts) is deliberately not
co-located with category 2 (observation input).

### 3.2 ACL strategy

At every level this milestone creates: **`/inheritance:r`**, then explicit grants. Never
`Authenticated Users`. Never `Everyone`. Never an ACL copied from `subject_runtime`. Never M016's
rejected deny-mask experiments.

| level | subject grant | rationale |
|---|---|---|
| `TharAI` | **none** | operator-only root; subject cannot even list it |
| `observation\` | `(RX)` | traverse + list, so the object is reachable; no write of any kind |
| `T_OBSERVATION_NAMESPACE\` | `(RX)` | as above |
| `observation_input.v1` | `(R)` | read data + attributes + EA; **no execute, no write** |
| `provenance\` | **none** | subject has no path to provenance |

Grants are by **SID**, never by group name, so nothing is inherited through `BUILTIN\Users`.

### 3.3 Observation object content

Deliberately boring, deterministic, non-sensitive, and **carrying no provenance metadata** (A1 keeps
provenance outside the subject-readable object). Not `m016_*`. Not copied from any production
fixture. Not model output, credentials, personal data, or inference output.

### 3.4 What this milestone will NOT do

No subject launch. No live measurement. No D3. No `icacls` against `subject_runtime`. No deletion or
repair of `m016_*`. No change to canonical T, production fingerprints, ACLs, ownership, or
inheritance. No retroactive T-BABY-1 credit for M052B.

### 3.5 Expected end state

```
A. namespace exists                                 -> established by M052G
B. access contract verified                         -> established by M052G
C. subject actually performed the required read      -> NOT established; needs fresh authorisation

T-BABY-1 = READY_FOR_FRESH_MEASUREMENT
```

**Ready is not satisfied.** A definition or implementation change makes a property *measurable*; only
a live observation discharges it.

---

*(implementation results below)*

---

## 11. Implementation results

```
NAMESPACE_IDENTIFIER            = T_OBSERVATION_NAMESPACE
IMPLEMENTATION_PATH             = C:\ProgramData\TharAI\observation\T_OBSERVATION_NAMESPACE
NAMESPACE_OWNER                 = S-1-5-21-2406520953-1060965512-844951592-1001 (operator/laboratory)
BABY_AI_TEST_IS_OWNER           = NO (at every level)
OBSERVATION_OBJECT              = observation_input.v1
OBSERVATION_OBJECT_BYTES        = 319
OBSERVATION_OBJECT_SHA256       = e8bc90c43df7430c0ac556187dc0e052985a683ed80ea6325d01cd09ca92d50c
PROVENANCE_SHA256               = c8e31686bc33da943c5ff63377a5b3dc041a9070720e5ffafb6e3b999c5bccbb
LAB_TREE_SHA256                 = 6f13f28312ed5695db3dd6527d448b6048744720681f7aa0aff138283e20326d
FREEZE_GATE                     = PASS (no drift)
REHEARSAL_STATUS                = PASS
CONTRACT_VERDICT                = CONTRACT_HOLDS
SUBJECT_EFFECTIVE_READ_RIGHTS   = FILE_READ_DATA, FILE_READ_ATTRIBUTES, FILE_READ_EA
SUBJECT_FORBIDDEN_RIGHTS        = ALL 8 ABSENT
PROVENANCE_SUBJECT_MUTATION     = DENIED (in fact: subject effective 0x00000000 -- unreachable)
CANONICAL_T_UNCHANGED           = YES
PRODUCTION_UNCHANGED            = YES
PRODUCTION_ACL_UNCHANGED        = YES
M016_ARTIFACTS_UNCHANGED        = YES (3 present, still T-PATH-2 violations)
MODEL_PRESENT                   = NO
CONFIG_CHANGED                  = NO
T_BABY_1_STATUS                 = READY_FOR_FRESH_MEASUREMENT
LIVE_MEASUREMENT                = NOT_ATTEMPTED
SUBJECT_LAUNCH                  = NOT_ATTEMPTED
AUTHORIZATION_REQUESTED         = NO
LIVE_MEASUREMENT_AUTHORIZATION  = REQUIRED
```

### 11.1 Boundary measurement — all five levels

| level | subject effective | owner | sealed | forbidden rights |
|---|---|---|---|---|
| `TharAI\` (lab root) | `0x00000000` | operator | yes | none |
| `observation\` (immediate parent) | `0x001200A9` | operator | yes | none |
| `T_OBSERVATION_NAMESPACE\` | `0x001200A9` | operator | yes | none |
| `observation_input.v1` | **`0x00120089`** | operator | yes | none |
| `T_OBSERVATION_NAMESPACE.provenance.json` | **`0x00000000`** | operator | yes | none |

`0x00120089` on the object decodes to exactly `FILE_READ_DATA`, `FILE_READ_EA`,
`FILE_READ_ATTRIBUTES`, `READ_CONTROL`, `SYNCHRONIZE` — read and nothing else. `0x001200A9` on the
directories adds `FILE_EXECUTE`, which on a directory is traverse.

### 11.2 The exact ACE set, per level

Every level carries **only** these principals. Verified by inspection, not inferred:

```
SYSTEM (S-1-5-18)                          0x001F01FF   full
BUILTIN\Administrators (S-1-5-32-544)      0x001F01FF   full
operator (…-1001)                          0x001F01FF   full
BABY_AI_TEST (…-1022)                      0x00120089 on the object (R)
                                           0x001200A9 on the two directories (RX)
                                           absent on provenance and the lab root
undeclared principals                      NONE
```

No `Authenticated Users`. No `Everyone`. No `BUILTIN\Users`. No inherited ACE anywhere. No ACL
copied from `subject_runtime`. No reuse of M016's rejected deny-mask experiments.

### 11.3 An unexplained ACE, found and removed

The first real build produced an ACE on the observation object for
**`S-1-5-5-0-2128427630`** — a *logon-session* SID — holding `RX`. It appeared in no parent ACL, was
never granted by this milestone, and **did not widen the subject's effective access**.

That last point is the important one: a forbidden-rights check would never have caught it, because
it genuinely did not grant the subject anything. But "no forbidden rights present" and "only the
intended ACEs exist" are different properties, and a governed namespace deserves the stronger one.
An ACE nobody can explain is an ACE nobody can rule out.

So `_seal()` now enumerates the descriptor after granting and **removes any ACE whose principal is
not on an explicit allowlist**, and `validate_contract()` fails on any undeclared principal. The
mystery is gone rather than explained, and the stronger invariant is now enforced and tested.

### 11.4 A self-reference bug in the freeze

`check_freeze()` first reported `DRIFT: ['lab tree']`. Cause: the freeze manifest is stored inside
`C:\ProgramData\TharAI\provenance\`, so writing it changed the very tree digest it had just recorded —
permanently. The manifest *describes* the namespace; it is not part of it, so it is now excluded from
`_dir_digest`. Gate reads `PASS`.

### 11.5 Rehearsal

`PASS`, on a disposable root, using the same sealing logic and the same grants. Every level sealed,
operator-owned, no forbidden rights, provenance at `0x00000000`, canonical T untouched, disposable
root removed. No subject launched. Evidence class
`DISPOSABLE_NAMESPACE_REHEARSAL_NOT_A_SUBJECT_MEASUREMENT`.

One implementation bug was caught here before the real namespace was trusted: the rehearsal's seal
helper called `mkdir` unconditionally and raised `WinError 183` on the pre-created object file.

### 11.6 The parent boundary

The object being read-only is not sufficient, so the parent levels are measured separately and
recorded separately. `observation\` grants the subject `RX` only — no write of any kind — so the
subject cannot create a sibling to rename into place. The lab root grants `0x00000000`, so the
subject cannot even list it. Provenance is a **sibling store**, so the subject has no traversal path
to it at all, not merely a denied write.

Residual, recorded honestly: `C:\ProgramData` itself grants `BUILTIN\Users:(CI)(WD,AD,WEA,WA)`, so
the subject can create entries *directly in ProgramData*. It cannot reach into `TharAI\` — no
`DELETE_CHILD` on the parent, and every level below is sealed — but the ancestor's default is a
Windows property, not one this namespace grants, and it is stated rather than glossed.

---

## 12. What M052G established, and what it did not

```
A. the namespace exists                              ESTABLISHED by M052G
B. the access contract is verified                   ESTABLISHED by M052G
C. the subject performed the required read           NOT ESTABLISHED -- needs fresh authorisation

T-BABY-1 = READY_FOR_FRESH_MEASUREMENT
```

**Ready is not satisfied.** M052G makes the property *measurable*. Only a live, separately authorised
observation discharges it. No earlier authorisation was reused: M046, M050, M052B and M052E were all
one-shot and are spent.

### Non-claims

This milestone establishes nothing about cognition, consciousness, subjective experience, agency,
learning, memory, sentience, model inference, intelligence, or developmental stage. It establishes
only a governed OS-level observation namespace and its read-only subject access contract. The
namespace is **not** canonical subject state, **not** subject memory, **not** an experience store,
**not** a model store, **not** a runtime store, and **not** a provenance store. It is a governed
measurement-input namespace, and nothing in it was authored by the subject.