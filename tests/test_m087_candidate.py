"""M087 -- v2 candidate structure tests. Read-only; no operational impact."""

from __future__ import annotations

import json
from pathlib import Path

from babylab.hashing import canonical_bytes, sha256_hex, file_sha256

CANDIDATE = Path("docs/evidence/m087-credential-policy-candidate-v2.json")


def _rec() -> dict:
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


def test_v2_is_canonical_and_reproducible():
    assert CANDIDATE.exists()
    raw = CANDIDATE.read_bytes()
    assert sha256_hex(raw) == sha256_hex(canonical_bytes(_rec()))
    assert len(raw) == 2405


def test_v2_records_preferences_without_authority_or_secrets():
    rec = _rec()
    assert rec["decision_id"] == "M087-CREDPOL-002"
    assert rec["decision_class"] == "CREDENTIAL_POLICY"
    assert rec["authority_id"] == "UNRESOLVED_HUMAN_DESIGNATION_REQUIRED"
    assert rec["proposal_status"] == "CANDIDATE-V2-UNSIGNED-UNSEALED-NO-AUTHORITY-MINTED"
    assert "BLOCKED_MISSING_EXACT_PROCEDURE" in rec["execution_procedure_status"]
    assert "130307" not in CANDIDATE.read_text(encoding="utf-8")
    for claim in ("hereby authorize", "Gate 1 is OPEN", "Gate 2 is OPEN",
                  "launch is authorized", "birth is authorized",
                  "Password:", "pwd=", "PROV-000021",
                  "FORMALLY_SIGNED", "DULY_SEALED", "SIGNATURE:", "SEAL_ID"):
        assert claim not in CANDIDATE.read_text(encoding="utf-8"), claim


def test_historical_records_untouched():
    assert file_sha256("docs/evidence/m080-credential-policy-proposal.json") == (
        "64357dc785c3bef7863cba49892b512dd6cdd9c497c251d87457d8f4e10a4d15")
    assert file_sha256("docs/evidence/m081-credential-policy-candidate.json") == (
        "39b40642484aba540045c5658478ba548202b25bf47bf7a162c2b890211cafcd")
