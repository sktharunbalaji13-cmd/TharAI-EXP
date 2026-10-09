"""M057 -- execute the HUMAN-signed RecoveryAuthorisation PROV-000016, once.

Scope is deliberately minimal: this module exists to perform exactly one
authorised production mutation -- REMOVE_EXACT_ACE of the M052M accidental
deny ACE -- and nothing else.

Load-bearing properties, all enforced by construction rather than convention:

* Every value is a module constant. :func:`execute_once` takes no arguments,
  so there is no parameter through which a caller could substitute a target,
  SID, mask, operation, or mechanism.
* There is no code path that adds an ACE, restores an ACE, applies D3, takes
  ownership, changes protection/inheritance, touches file content, recurses,
  launches the subject, or opens any gate. The only script ever executed is
  M052O's remove-only script, whose digest is asserted before use.
* Single-use is enforced before the write: the capability token is consumed
  (process-locally) and any prior M057 execution entry in the ledger naming
  this authorisation refuses a second run. A failed write is still consumed,
  so failure is unretryable with the same authority.
* Poststate is verified after the write. On mismatch the module stops: no
  rollback, no repair, no second attempt. Rollback requires its own
  authorisation, which PROV-000016 does not grant.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from babylab.hashing import canonical_bytes, file_sha256, sha256_hex
from babylab.paths import default_paths
from foundation import security_verify as sv
from provenance.keyring import Keyring
from provenance.ledger import ProvenanceLedger
from tests import m052k_implementation as K
from tests import m052o_recovery as O
from tests import m052p_governance as P
from tests import path_policy as pp

__all__ = [
    "AUTH_ID", "NONCE", "TARGET_ABS", "SID", "MASK", "PRESTATE_FP",
    "POSTSTATE_FP", "MECHANISM_DIGEST", "CONTENT_SHA", "AUTH_FILE",
    "RecoveryRefused", "RecoveryCapability", "execute_once",
]

#: The one authorisation this module may execute. Anything else is refused.
AUTH_ID = "990c6e6fdcd446b28e750b38593e9b7a"
NONCE = "58d50ee922ea40c4bd26e0cd086e4920"
AUTH_SHA256 = "4d5c64e54a65d48e670b89e61936c5029f8ec4e84c2d4bbf43a65db6263da2cd"
AUTH_BYTES = 1202
TARGET_ABS = "C:\\dev\\TharAI-EXP\\subject_runtime\\runtime\\m016_read_fixture.exe"
TARGET_REL = "subject_runtime/runtime/m016_read_fixture.exe"
SID = "S-1-5-21-2406520953-1060965512-844951592-1022"
MASK = 0x00000001
PRESTATE_FP = "742254f88dfb6fd80ec0f2259e610bb03fb7fa6f8393ab6c959bd24fb46d45ff"
POSTSTATE_FP = "d63ff646bec494c198db9031491558f2744ea40bb2b1af016090e980865c1f27"
MECHANISM_DIGEST = "99f058f584279922ba47246f4d3b005c38f33e4ef8baae1793c1ddd32ae45762"
CONTENT_SHA = "55250a71209a4d397dc51f3f12da105455a5d20ace53062416d26079fded0cdf"
OWNER_SID = "S-1-5-21-2406520953-1060965512-844951592-1001"
AUTH_FILE = "docs/m052m/recovery-authorisation-M056-990c6e6f.json"


class RecoveryRefused(RuntimeError):
    """Any M057 gate failure. Raised before the write, or stops after it."""


@dataclass(frozen=True)
class RecoveryCapability:
    """The narrow execution capability for exactly one authorised removal.

    A thin, M057-scoped binding record. It confers nothing on its own: it is
    valid only together with the HUMAN-signed PROV-000016 authorisation it
    mirrors, and it is consumed by a single execution attempt.
    """

    authorization_id: str
    nonce: str
    target_absolute: str
    principal_sid: str
    ace_type: str
    ace_mask: int
    ace_scope: str
    operation: str
    prestate_fingerprint: str
    poststate_fingerprint: str
    mechanism_digest: str
    token: str
    consumed: bool = False

    def violations(self) -> list[str]:
        out: list[str] = []
        if self.authorization_id != AUTH_ID:
            out.append("capability is not for the authorised M056 authorisation")
        if self.nonce != NONCE:
            out.append("capability nonce does not match the authorised nonce")
        if Path(self.target_absolute).resolve() != Path(TARGET_ABS).resolve():
            out.append("capability target is not the authorised production file")
        if self.principal_sid != SID or self.principal_sid != sv.SUBJECT_SID:
            out.append("capability principal is not the authorised subject SID")
        if self.ace_type != "DENY":
            out.append("capability ACE type is not DENY")
        if int(self.ace_mask) != MASK:
            out.append("capability mask is not the authorised accidental mask")
        if int(self.ace_mask) == P.D3_MASK:
            out.append("a recovery capability must never carry the D3 mask")
        if self.ace_scope != "explicit":
            out.append("capability scope is not explicit")
        if self.operation != "REMOVE_EXACT_ACE":
            out.append("capability operation is not the authorised removal")
        if self.prestate_fingerprint != PRESTATE_FP:
            out.append("capability prestate does not match the authorised prestate")
        if self.poststate_fingerprint != POSTSTATE_FP:
            out.append("capability poststate does not match the authorised poststate")
        if self.mechanism_digest != MECHANISM_DIGEST:
            out.append("capability mechanism is not the authorised mechanism")
        if self.consumed:
            out.append("capability has already been consumed; authority is single-use")
        return out


#: Tokens consumed by execution attempts in this process. A failed attempt is
#: still consumed, so failure cannot be retried with the same authority.
_CONSUMED_TOKENS: set[str] = set()


def _refuse(reason: str) -> RecoveryRefused:
    return RecoveryRefused(f"M057 refused: {reason}")


def load_authorization() -> dict[str, Any]:
    """Load the canonical authorisation file and validate it structurally."""
    paths = default_paths()
    target = paths.root / AUTH_FILE
    raw = target.read_bytes()
    if len(raw) != AUTH_BYTES:
        raise _refuse(f"authorisation file is {len(raw)} bytes, not {AUTH_BYTES}")
    if sha256_hex(raw) != AUTH_SHA256:
        raise _refuse("authorisation file digest does not match the M056 canonical SHA-256")
    record = json.loads(raw.decode("utf-8"))
    auth = P.RecoveryAuthorisationContract(
        **{**record, "ace_inheritance_flags": tuple(record["ace_inheritance_flags"])})
    viol = auth.violations()
    if viol:
        raise _refuse("authorisation contract invalid: " + "; ".join(viol))
    if record["authorization_id"] != AUTH_ID or record["nonce"] != NONCE:
        raise _refuse("authorisation identity does not match the M056 issued values")
    if record["issued_by"] != "130307" or record["decided_under"] != "R1":
        raise _refuse("authorisation authority/governance binding unexpected")
    return record


def verify_ledger_binding() -> Any:
    """Confirm PROV-000016 exists, is HUMAN-signed, seals the record, heads the seal."""
    paths = default_paths()
    keyring = Keyring(paths.keyring, paths.private_key_dir)
    ledger = ProvenanceLedger(
        paths.provenance_ledger, keyring, seal_dir=paths.protected_provenance)
    report = ledger.verify(deep=True)
    if not report.intact:
        raise _refuse("ledger chain/MACs not intact: " + "; ".join(report.problems))
    seal = ledger.verify_seal()
    if seal is None or not seal.intact:
        raise _refuse("provenance seal missing or compromised")
    if seal.head_entry_id != "PROV-000016":
        raise _refuse(f"sealed head is {seal.head_entry_id}, not PROV-000016")
    matches = [e for e in ledger.iter_entries() if e.entry_id == "PROV-000016"]
    if len(matches) != 1:
        raise _refuse("PROV-000016 missing or ambiguous in ledger")
    entry = matches[0]
    if entry.key_id != "HK-86ac3dc595e9":
        raise _refuse("PROV-000016 not signed by the HUMAN key")
    if not keyring.verify(entry.key_id, canonical_bytes(entry.signed_body()), entry.mac):
        raise _refuse("PROV-000016 MAC does not verify")
    if entry.content_sha256 != AUTH_SHA256:
        raise _refuse("PROV-000016 does not bind the authorised canonical bytes")
    return entry


def check_replay() -> None:
    """Refuse if this authorisation was already executed or consumed."""
    paths = default_paths()
    keyring = Keyring(paths.keyring, paths.private_key_dir)
    ledger = ProvenanceLedger(
        paths.provenance_ledger, keyring, seal_dir=paths.protected_provenance)
    prior = [e for e in ledger.iter_entries()
             if (e.experiment_id == "M057" or AUTH_ID in (e.reason or ""))
             and e.entry_id != "PROV-000016"]
    if prior:
        raise _refuse("prior execution/consumption evidence: "
                      + ", ".join(e.entry_id for e in prior))
    if NONCE in _CONSUMED_TOKENS:
        raise _refuse("authorisation nonce already consumed in this process")


def rebind_prestate() -> dict[str, Any]:
    """Fresh read-only measurement of the exact production target."""
    target = pp.read_production_for_verification(P.AFFECTED)
    if Path(target).resolve() != Path(TARGET_ABS).resolve():
        raise _refuse("production target does not resolve to the authorised file")
    state = O.incident_state(target)
    if not state.get("readable"):
        raise _refuse(f"target descriptor unreadable: {state.get('error')}")
    if O._descriptor_hash(state) != PRESTATE_FP:
        raise _refuse("live prestate fingerprint differs from the authorised prestate")
    named = f"DENY|{SID}|{MASK:#010x}|expl"
    if named not in state["aces"]:
        raise _refuse("the authorised ACE is absent; nothing to recover, no repair attempted")
    if state.get("owner_sid") != OWNER_SID:
        raise _refuse("owner differs from the authorised prestate")
    if state.get("protected") is not False:
        raise _refuse("protection state differs from the authorised prestate")
    if hashlib.sha256(Path(target).read_bytes()).hexdigest() != CONTENT_SHA:
        raise _refuse("file content differs from the authorised prestate")
    return state


def build_capability() -> RecoveryCapability:
    """The one narrow capability this execution may use."""
    cap = RecoveryCapability(
        authorization_id=AUTH_ID, nonce=NONCE, target_absolute=TARGET_ABS,
        principal_sid=SID, ace_type="DENY", ace_mask=MASK, ace_scope="explicit",
        operation="REMOVE_EXACT_ACE", prestate_fingerprint=PRESTATE_FP,
        poststate_fingerprint=POSTSTATE_FP, mechanism_digest=MECHANISM_DIGEST,
        token=f"m057-{uuid.uuid4().hex}")
    viol = cap.violations()
    if viol:
        raise _refuse("capability invalid: " + "; ".join(viol))
    if cap.token in _CONSUMED_TOKENS:
        raise _refuse("capability token already consumed")
    return cap


def assert_mechanism() -> None:
    """The script to run must be exactly the authorised remove-only mechanism."""
    digest = hashlib.sha256(
        (O.RECOVERY_OPERATION + O._REMOVE_SCRIPT).encode("utf-8")).hexdigest()
    if digest != MECHANISM_DIGEST:
        raise _refuse("mechanism digest mismatch; the writer is not the authorised one")
    if "RemoveAccessRuleSpecific" not in O._REMOVE_SCRIPT:
        raise _refuse("mechanism is not the proven narrow removal")
    if "AddAccessRule" in O._REMOVE_SCRIPT:
        raise _refuse("mechanism contains an ACE-adding path")


def execute_once() -> dict[str, Any]:
    """Run every gate, then perform exactly one authorised ACE removal.

    Validation order: authorisation, ledger binding, replay, prestate,
    capability, mechanism -- all before the single write. The capability is
    consumed before the write, so failure is unretryable. Poststate is
    verified after the write; on mismatch this stops with no rollback.
    """
    record = load_authorization()
    verify_ledger_binding()
    check_replay()
    before = rebind_prestate()
    cap = build_capability()
    assert_mechanism()

    _CONSUMED_TOKENS.add(cap.token)
    _CONSUMED_TOKENS.add(NONCE)
    ok, out = K._ps(O._REMOVE_SCRIPT, {
        "R_TARGET": TARGET_ABS, "R_SID": SID, "R_MASK": str(MASK)})
    if not ok:
        raise _refuse(f"recovery write failed and is consumed: {out[-200:]}")

    after = O.incident_state(Path(TARGET_ABS))
    got = O._descriptor_hash(after) if after.get("readable") else None
    named = f"DENY|{SID}|{MASK:#010x}|expl"
    result = {
        "recovered": got == POSTSTATE_FP,
        "prestate_fingerprint": O._descriptor_hash(before),
        "poststate_fingerprint": got,
        "expected_poststate_fingerprint": POSTSTATE_FP,
        "poststate_matched": got == POSTSTATE_FP,
        "named_ace_absent": named not in (after.get("aces") or []),
        "owner_unchanged": after.get("owner_sid") == before.get("owner_sid"),
        "protection_unchanged": after.get("protected") == before.get("protected"),
        "content_sha256": hashlib.sha256(Path(TARGET_ABS).read_bytes()).hexdigest(),
        "content_unchanged": hashlib.sha256(
            Path(TARGET_ABS).read_bytes()).hexdigest() == CONTENT_SHA,
        "unrelated_aces": sorted(a for a in (after.get("aces") or [])
                                 if not a.startswith("DENY")),
        "capability_token": cap.token,
        "write_output": out[-120:],
    }
    if not result["poststate_matched"]:
        raise _refuse("poststate mismatch after write; state preserved for human "
                      f"review (observed {got}); no rollback, no repair attempted")
    return result
