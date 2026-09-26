"""Subject identity: NO SUBJECT versus a real, key-backed subject.

What this registry is
---------------------
The Observatory's answer to "whose cognitive state is this?" It answers it by
consulting the **human-owned keyring**, which is the only component in the
project permitted to establish an authorship role
(:meth:`provenance.keyring.Keyring.role_of`).

Why not read it off the events
------------------------------
Because an event payload is written by whoever produced the event, and the
future subject will be able to write payloads. An event claiming
``{"author": "BABY_AI"}`` is therefore not evidence of anything — the same
reasoning that ``babylab/identity.py`` gives for never reading a role out of a
record. Subject identity here comes from key material the human registered, or
it does not exist.

Current state: there is no subject
----------------------------------
Milestone 002 ships with an **empty registry**. No ``BABY_AI`` key is
provisioned, no subject ID is invented, and nothing here can create one. The
registry has no ``register()`` method and no write path of any kind; that is a
deliberate design choice, verified by
``tests/test_observatory_security.py``.

Attribution of a subject's existence is a human research decision, made when a
real subject exists, in the same way and at the same ceremony as provisioning
a signing key. An instrument that can conjure the thing it is measuring is not
an instrument.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from babylab.errors import IntegrityError
from babylab.identity import Role


class SubjectStatus(str, enum.Enum):
    """Whether a subject is attached to the laboratory."""

    NO_SUBJECT = "NO_SUBJECT"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: The one line a human must be able to read at a glance and know that nothing
#: is being faked. Referenced by the renderer and asserted in tests, so it
#: cannot be reworded into something more reassuring by accident.
NO_SUBJECT_BANNER = "NO EXPERIMENTAL SUBJECT ATTACHED"

#: Shown under the banner. The distinction matters: telemetry is not merely
#: absent, the machinery to receive it has no input.
NO_SUBJECT_DETAIL = "Cognitive telemetry unavailable"


@dataclass(frozen=True)
class SubjectRef:
    """A real, key-backed subject, as established by the human keyring."""

    subject_id: str
    key_id: str
    actor_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"subject_id": self.subject_id, "key_id": self.key_id, "actor_id": self.actor_id}


class SubjectRegistry:
    """Read-only view of whether a subject exists.

    Constructed from a :class:`provenance.keyring.Keyring`. Has no mutating
    methods by design.
    """

    def __init__(self, keyring: Any | None = None):
        self._keyring = keyring

    # -- queries ----------------------------------------------------------
    @property
    def status(self) -> SubjectStatus:
        return SubjectStatus.NO_SUBJECT

    def subject(self) -> SubjectRef | None:
        """The attached subject, or ``None``.

        ``None`` is the correct answer for the whole of Milestone 002, and is
        not an error condition. Callers must handle it explicitly, which is the
        point: there is no code path in which "no subject" quietly becomes an
        empty-but-valid-looking subject.
        """
        if self._keyring is None:
            return None
        try:
            if not self._keyring.has_role(Role.BABY_AI):
                return None
            entry = self._keyring.key_for_role(Role.BABY_AI)
        except (IntegrityError, Exception):
            # A missing, unreadable, or inconsistent keyring means we cannot
            # establish a subject. That is "no subject", not "assume a subject".
            return None
        return SubjectRef(
            subject_id=entry.actor_id,
            key_id=entry.key_id,
            actor_id=entry.actor_id,
        )

    def is_attached(self) -> bool:
        return self.subject() is not None

    def describe(self) -> str:
        subject = self.subject()
        if subject is None:
            return NO_SUBJECT_BANNER
        return f"SUBJECT: {subject.subject_id}"

    def to_dict(self) -> dict[str, Any]:
        subject = self.subject()
        return {
            "status": self.status.value,
            "subject": subject.to_dict() if subject else None,
            "banner": self.describe(),
            "detail": None if subject else NO_SUBJECT_DETAIL,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"SubjectRegistry({self.describe()})"
