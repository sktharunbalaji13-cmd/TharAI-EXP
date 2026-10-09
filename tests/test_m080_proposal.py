"""M080 -- proposal-record structure tests. Read-only; no operational impact."""

from __future__ import annotations

import json
from pathlib import Path

from babylab.hashing import canonical_bytes, sha256_hex

DOC = Path("docs/evidence/m080-credential-policy-proposal.json")


def _rec() -> dict:
    return json.loads(DOC.read_text(encoding="utf-8"))


def test_proposal_is_canonical_and_reproducible():
    assert DOC.exists()
    raw = DOC.read_bytes()
    assert sha256_hex(raw) == sha256_hex(canonical_bytes(_rec()))
    assert len(raw) == 1523


def test_proposal_marks_authority_unresolved_and_grants_nothing():
    rec = _rec()
    assert rec["decision_id"] == "M080-CREDPOL-001"
    assert rec["decision_class"] == "CREDENTIAL_POLICY"
    assert rec["authority_id"] == "UNRESOLVED_HUMAN_DESIGNATION_REQUIRED"
    assert rec["proposal_status"] == "PROPOSAL_UNSIGNED-UNSEALED-NO-AUTHORITY-MINTED"
    assert "final_bytes_note" in rec
    text = DOC.read_text(encoding="utf-8")
    for claim in ("hereby authorize", "Gate 1 is OPEN", "Gate 2 is OPEN",
                  "launch is authorized", "birth is authorized",
                  "password is ", "Password:", "PROV-000020",
                  "130307"):
        assert claim not in text, claim
