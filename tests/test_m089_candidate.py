"""M089 -- designated-candidate structure tests. Read-only; no operational impact."""

from __future__ import annotations

import json
from pathlib import Path

from babylab.hashing import canonical_bytes, sha256_hex, file_sha256

CANDIDATE = Path("docs/evidence/m089-credential-policy-designated.json")


def _rec() -> dict:
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


def test_designated_candidate_is_canonical_and_reproducible():
    assert CANDIDATE.exists()
    raw = CANDIDATE.read_bytes()
    assert sha256_hex(raw) == sha256_hex(canonical_bytes(_rec()))
    assert len(raw) == 2790


def test_designation_exact_and_nothing_signed():
    rec = _rec()
    assert rec["decision_id"] == "M088-CREDPOL-003"
    assert rec["authority_id"] == "130307"
    assert rec["authority_type"] == "HUMAN"
    assert rec["proposal_status"] == "CANDIDATE-DESIGNATED-UNSIGNED-UNSEALED-AWAITING-EXACT-BYTE-APPROVAL"
    text = CANDIDATE.read_text(encoding="utf-8")
    for claim in ("hereby authorize", "Gate 1 is OPEN", "Gate 2 is OPEN",
                  "launch is authorized", "birth is authorized",
                  "Password:", "pwd=", "PROV-000021",
                  "FORMALLY_SIGNED", "DULY_SEALED", "SIGNATURE:", "SEAL_ID"):
        assert claim not in text, claim


def test_v3_proposal_preserved_byte_identical():
    assert file_sha256("docs/evidence/m088-credential-policy-candidate-v3.json") == (
        "81b85badf50b472d991f5ac65fcb0ec61aae4a638388099d51b86df4dd96d086")
