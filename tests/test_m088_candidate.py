"""M088 -- v3 candidate + procedure structure tests. Read-only; no impact."""

from __future__ import annotations

import json
from pathlib import Path

from babylab.hashing import canonical_bytes, sha256_hex, file_sha256

CANDIDATE = Path("docs/evidence/m088-credential-policy-candidate-v3.json")
PROCEDURE = Path("docs/evidence/m088-credential-procedure.md")


def _rec() -> dict:
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


def test_v3_is_canonical_and_reproducible():
    assert CANDIDATE.exists()
    raw = CANDIDATE.read_bytes()
    assert sha256_hex(raw) == sha256_hex(canonical_bytes(_rec()))
    assert len(raw) == 2578


def test_v3_preserves_policy_with_unresolved_authority():
    rec = _rec()
    assert rec["decision_id"] == "M088-CREDPOL-003"
    assert rec["authority_id"] == "UNRESOLVED_HUMAN_DESIGNATION_REQUIRED"
    assert rec["proposal_status"] == "CANDIDATE-V3-UNSIGNED-UNSEALED-NO-AUTHORITY-MINTED"
    assert "130307" not in CANDIDATE.read_text(encoding="utf-8")
    assert "m088-credential-procedure.md" in rec["procedure_reference"]
    for claim in ("hereby authorize", "Gate 1 is OPEN", "Gate 2 is OPEN",
                  "launch is authorized", "birth is authorized",
                  "Password:", "pwd=", "PROV-000021",
                  "FORMALLY_SIGNED", "DULY_SEALED", "SIGNATURE:", "SEAL_ID"):
        assert claim not in CANDIDATE.read_text(encoding="utf-8"), claim


def test_procedure_documented_without_secrets_or_execution():
    assert PROCEDURE.exists()
    text = PROCEDURE.read_text(encoding="utf-8")
    for section in ("## 1. Interface decision", "## 2. Exact primary procedure",
                    "## 3. Observable outcomes", "## 4. Abort conditions",
                    "## 5. Secret handling"):
        assert section in text, section
    assert "Windows 11 Home" in text
    assert "lusrmgr.msc" in text
    for claim in ("Password:", "pwd=", "account was created", "setup completed"):
        assert claim not in text, claim


def test_historical_records_untouched():
    assert file_sha256("docs/evidence/m080-credential-policy-proposal.json") == (
        "64357dc785c3bef7863cba49892b512dd6cdd9c497c251d87457d8f4e10a4d15")
    assert file_sha256("docs/evidence/m081-credential-policy-candidate.json") == (
        "39b40642484aba540045c5658478ba548202b25bf47bf7a162c2b890211cafcd")
    assert file_sha256("docs/evidence/m087-credential-policy-candidate-v2.json") == (
        "158aabb09939db8a6205ff20c525baac42d360def05ebf340fa8ab17dd5803d4")
