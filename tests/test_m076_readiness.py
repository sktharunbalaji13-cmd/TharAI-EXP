"""M076 -- readiness-doc structure tests. Read-only; no operational impact."""

from __future__ import annotations

from pathlib import Path

DOC = Path("docs/evidence/m076-auth1-readiness.md")


def test_readiness_exists_with_required_content():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "## 1. Proposed account",
        "## 2. Auth-1 scope",
        "## 3. Recovery and safety review",
        "## 4. Authorization process",
        "## 5. Human fields required",
        "## 6. Readiness",
        "## 7. Authority statement",
    ):
        assert section in text, section
    assert "babyai-subject" in text
    assert "UNRESOLVED" in text


def test_no_fabricated_authorization_or_credentials():
    text = DOC.read_text(encoding="utf-8")
    for claim in ("Gate 1 is OPEN", "Gate 2 is OPEN", "launch is authorized",
                  "birth is authorized", "hereby authorize", "PROV-000019",
                  "password is ", "Password:"):
        assert claim not in text, claim
    assert 'conversational "yes" is not permission' in text
