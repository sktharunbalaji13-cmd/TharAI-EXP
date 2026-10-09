"""M079 -- policy-doc structure tests. Read-only; no operational impact."""

from __future__ import annotations

from pathlib import Path

DOC = Path("docs/evidence/m079-credential-policy-readiness.md")


def test_policy_doc_exists_with_required_content():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "## 1. Selected credential policy",
        "## 2. M078 stop record",
        "## 3. Retry-readiness checklist",
        "## 4. Stop conditions",
        "## 5. Authority statement",
    ):
        assert section in text, section
    assert "POLICY_PREFERENCE_SELECTED" in text
    assert "FORMAL_GOVERNANCE_STATUS" in text
    assert "TO_BE_VERIFIED" in text


def test_no_false_signature_or_secret_claims():
    text = DOC.read_text(encoding="utf-8")
    for claim in ("hereby authorize", "Gate 1 is OPEN", "Gate 2 is OPEN",
                  "launch is authorized", "birth is authorized",
                  "password is ", "Password:", "PROV-000020",
                  "FORMALLY_SIGNED", "duly sealed"):
        assert claim not in text, claim
    assert "authorizes nothing" in text
