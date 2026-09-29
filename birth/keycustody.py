"""Key custody: decide whether a signing key is required, and say so explicitly.

The decision, not the key
--------------------------
M009's ceremony records experiences through laboratory-generated provenance,
linked by hashes. Nothing in that design requires the subject to sign anything:
there is no BABY_AI-authored content yet, because authoring content that needs
attribution is a later milestone's problem. Provisioning a key "for appearance"
would create the exact tripwire -- an active BABY_AI keyring role -- that makes
the observer report a subject as attached. So the decision here is
``NOT_REQUIRED``, with the reasons written down.

If a future operation genuinely requires subject signing, provisioning is a
separate, reviewed operation -- not something this module does as a side
effect. ``provision_key`` therefore refuses: creating a production identity
key must never happen because a ceremony step called it in passing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CustodyDecision:
    """Whether a BABY_AI signing key is required, and why."""

    decision: str  # "NOT_REQUIRED" or "PROVISIONED"
    reasons: tuple[str, ...] = ()
    provisioned: bool = False
    key_reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reasons": list(self.reasons),
            "provisioned": self.provisioned,
            "key_reference": self.key_reference,
        }


class CustodyError(RuntimeError):
    """A key-custody operation that must not happen here."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def evaluate_key_custody(*, requires_signing: bool) -> CustodyDecision:
    """Decide custody explicitly. The default ceremony needs no signing."""
    if requires_signing:
        return CustodyDecision(
            decision="REQUIRED_BUT_UNPROVISIONED",
            reasons=(
                "the caller declared that signing is required, but no key "
                "exists and this module does not provision production keys; "
                "provisioning is a separate reviewed operation, and the gate "
                "treats this state as blocking",
            ),
        )
    return CustodyDecision(
        decision="NOT_REQUIRED",
        reasons=(
            "experiences are recorded through laboratory-generated provenance, "
            "linked by hashes; no BABY_AI-authored content exists yet",
            "no operation in the M009 ceremony verifies a subject signature",
            "provisioning a key would create an active BABY_AI keyring role, "
            "which is one of the two tripwires that make the observer report "
            "a subject as attached -- and no subject is being attached by a "
            "mere ceremony step",
        ),
    )


def provision_key(*_args: Any, **_kwargs: Any) -> Any:
    """Refuse. Production key creation is never a side effect."""
    raise CustodyError(
        "PROVISIONING_REFUSED",
        "this module never creates a BABY_AI signing key. If a future "
        "milestone genuinely requires subject signing, provisioning happens "
        "through a separately reviewed operation with its own ceremony, not "
        "as a step inside birth.",
    )


__all__ = ["CustodyDecision", "CustodyError", "evaluate_key_custody", "provision_key"]
