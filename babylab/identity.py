"""Actors, roles, and how a role is *established*.

The rule this module exists to enforce
--------------------------------------
An actor's role is never read from the content of a record. In particular a
payload such as ``{"author": "HUMAN"}`` is not evidence of anything, because
the future Baby AI will be able to write payload fields.

Instead, a role is derived from **key material that lives in
``human_control/``**:

* To act as ``HUMAN`` you must present the human signing key (or be the local
  operator running a human-only entry point).
* To act as ``SYSTEM`` you must present the system key, provisioned by the
  human at bootstrap.
* To act as ``BABY_AI`` you must present a key that the human has explicitly
  registered in the keyring for the ``BABY_AI`` role.

Nobody, including a future version of this code running with the Baby AI's
filesystem permissions, can mint a new key for a role: the keyring is inside
``human_control/`` and the HMAC key material inside
``human_control/security/keys/private/``.

Milestone 001 limitation, stated plainly
----------------------------------------
Key possession is checked by :mod:`provenance.keyring`, which is
application-level code executing with the *operator's* permissions. Until a
separate low-privilege OS account exists for the Baby AI process (see
docs/security-model.md, "Planned OS-Level Enforcement"), a Baby AI process
that could read ``human_control/security/keys/private/`` could impersonate
HUMAN. The ACL script and the separate service account are the mitigation,
and that mitigation is **not yet active**. See docs/trust-boundaries.md,
section "Current Verified Status".
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Role(enum.Enum):
    """The three authorship domains of the experiment."""

    HUMAN = "HUMAN"
    BABY_AI = "BABY_AI"
    SYSTEM = "SYSTEM"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class Actor:
    """A caller of the laboratory infrastructure.

    Attributes
    ----------
    role:
        The asserted authorship domain.
    actor_id:
        Stable identifier for the concrete caller, e.g.
        ``"human:operator"`` or ``"baby-ai:subject-001"``.
    key_id:
        The keyring key this actor presents, when the actor is acting under a
        key. ``None`` means the actor is relying on a process-level assertion
        (see ``basis``).
    basis:
        How the role was established. Recorded verbatim in provenance entries
        so that a reader can see the strength of the claim, not just its
        conclusion.
    """

    role: Role
    actor_id: str
    key_id: str | None = None
    basis: str = "process-assertion"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.actor_id:
            raise ValueError("actor_id must be a non-empty string")

    def to_record(self) -> dict:
        return {
            "role": self.role.value,
            "actor_id": self.actor_id,
            "key_id": self.key_id,
            "basis": self.basis,
        }

    @classmethod
    def human_operator(cls, key_id: str | None = None) -> "Actor":
        """The human researcher.

        ``basis`` records that this is a *process-level assertion* backed by
        the operator's OS session, not a cryptographic proof. Stating that
        honestly in every record is deliberate: an overstated provenance claim
        would corrupt the experiment's findings later.
        """
        return cls(
            role=Role.HUMAN,
            actor_id="human:operator",
            key_id=key_id,
            basis="os-session+key" if key_id else "os-session",
        )

    @classmethod
    def system(cls, actor_id: str = "system:lab", key_id: str | None = None) -> "Actor":
        """The laboratory infrastructure acting on its own behalf."""
        return cls(
            role=Role.SYSTEM,
            actor_id=actor_id,
            key_id=key_id,
            basis="key" if key_id else "process-assertion",
        )

    @classmethod
    def baby_ai(cls, key_id: str, actor_id: str = "baby-ai:subject") -> "Actor":
        """The future experimental subject.

        Requires a key id. There is deliberately no way to construct this
        actor without naming a key that the human keyring must contain.
        """
        if not key_id:
            raise ValueError("a BABY_AI actor must name the key it presents")
        return cls(
            role=Role.BABY_AI,
            actor_id=actor_id,
            key_id=key_id,
            basis="key",
        )
