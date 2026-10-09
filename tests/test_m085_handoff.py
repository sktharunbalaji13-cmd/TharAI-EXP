"""M085 -- handoff-doc structure tests. Read-only; no operational impact."""

from __future__ import annotations

from pathlib import Path

DOC = Path("docs/evidence/m085-human-auth1-execution-handoff.md")


def test_handoff_exists_with_required_content():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "## 1. Purpose and scope",
        "## 2. Preflight",
        "## 3. Execution reference",
        "## 4. Credential handling",
        "## 5. Post-setup verification",
        "## 6. Evidence capture",
        "## 7. Stop conditions",
        "## 8. Human execution record template",
        "## 9. Explicit exclusions",
        "## 10. Authority statement",
    ):
        assert section in text, section
    assert "babyai-subject" in text
    assert "FINAL_RESULT: PASS / FAIL / BLOCKED / INCONCLUSIVE" in text
    assert "No Auth-1 setup implementation" in text or "NO dedicated Auth-1" in text or "no dedicated Auth-1" in text or "There is NO repository implementation" in text


def test_no_execution_or_secret_claims():
    text = DOC.read_text(encoding="utf-8")
    for claim in ("Gate 1 is OPEN", "Gate 2 is OPEN", "launch is authorized",
                  "birth is authorized", "hereby authorize", "PROV-000021",
                  "password is ", "Password:", "account was created",
                  "setup completed", "isolation proven"):
        assert claim not in text, claim
