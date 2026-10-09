"""M081 -- candidate-record structure tests. Read-only; no operational impact."""

from __future__ import annotations

import json
from pathlib import Path

from babylab.hashing import canonical_bytes, sha256_hex, file_sha256

CANDIDATE = Path("docs/evidence/m081-credential-policy-candidate.json")
PROPOSAL = Path("docs/evidence/m080-credential-policy-proposal.json")


def _rec() -> dict:
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


def test_candidate_is_canonical_and_reproducible():
    assert CANDIDATE.exists()
    raw = CANDIDATE.read_bytes()
    assert sha256_hex(raw) == sha256_hex(canonical_bytes(_rec()))
    assert len(raw) == 1728


def test_candidate_carries_supplied_designation_and_nothing_more():
    rec = _rec()
    prop = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    assert rec["decision_id"] == "M080-CREDPOL-001"
    assert rec["decision_class"] == "CREDENTIAL_POLICY"
    assert rec["authority_id"] == "130307"
    assert rec["authority_type"] == "HUMAN"
    assert rec["proposal_status"] == "CANDIDATE-UNSIGNED-UNSEALED-AWAITING-EXACT-BYTE-APPROVAL"
    for key in ("selected_policy", "execution_environment", "prohibitions",
                "fail_closed", "scope", "exclusions", "relationships"):
        assert rec[key] == prop[key], key
    text = CANDIDATE.read_text(encoding="utf-8")
    for claim in ("hereby authorize", "Gate 1 is OPEN", "Gate 2 is OPEN",
                  "launch is authorized", "birth is authorized",
                  "password is ", "Password:", "PROV-000020",
                  "FORMALLY_SIGNED", "DULY_SEALED", "SIGNATURE:",
                  "SEAL_ID", "hereby sign"):
        assert claim not in text, claim


def test_proposal_preserved_byte_identical():
    assert file_sha256(PROPOSAL) == (
        "64357dc785c3bef7863cba49892b512dd6cdd9c497c251d87457d8f4e10a4d15")
