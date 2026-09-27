"""Subject identity: NO SUBJECT versus a recorded subject versus a key-backed one.

What this registry is
---------------------
The Observatory's answer to "whose cognitive state is this?". It has two
independent sources, and the distinction between them is the whole point:

``RECORDED``
    A birth record exists at ``human_control/birth_records/BIRTH.json``. The
    laboratory performed a ceremony and sealed an identity. This is a fact about
    *the laboratory*, established by a human-written, human-owned, once-written
    file.

``ATTACHED``
    The **human-owned keyring** holds an active ``BABY_AI`` key
    (:meth:`provenance.keyring.Keyring.role_of`). The subject can now sign, and
    anything it writes is attributable to it rather than merely labelled as its.

Why the distinction exists
--------------------------
A birth record and a signing key are different grants. The record says a subject
was created; the key says the subject can prove things. Reporting a recorded
subject as an *attached* one would let the Observatory display an attribution
standing the system does not have — every future event would appear to come from
a key-backed subject when no key exists. The registry therefore reports
``SUBJECT_RECORDED, NOT KEY-ATTACHED`` in that state, which is dull and correct.

Why not read either off the events
----------------------------------
Because an event payload is written by whoever produced the event, and the future
subject will be able to write payloads. An event claiming ``{"author": "BABY_AI"}``
is therefore not evidence of anything — the same reasoning that
``babylab/identity.py`` gives for never reading a role out of a record.

Current state: no subject
-------------------------
Milestone 003 ships with an **empty registry** in any laboratory that has not run
a ceremony against a verified model, which is every laboratory that has not
installed one. The registry has no ``register()`` method and no write path of any
kind; that is a deliberate design choice, verified by
``tests/test_observatory_security.py``.

Attribution of a subject's existence is a human research decision, made when a
real subject exists, in the same way and at the same ceremony as provisioning a
signing key. An instrument that can conjure the thing it is measuring is not an
instrument.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from babylab.errors import IntegrityError
from babylab.identity import Role


class SubjectStatus(str, enum.Enum):
    """How a subject came to exist, if it did."""

    NO_SUBJECT = "NO_SUBJECT"
    #: A sealed birth record exists. No signing key is provisioned.
    RECORDED = "RECORDED"
    #: A birth record exists *and* a human-registered ``BABY_AI`` key is active.
    ATTACHED = "ATTACHED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: The one line a human must be able to read at a glance and know that nothing
#: is being faked. Referenced by the renderer and asserted in tests, so it
#: cannot be reworded into something more reassuring by accident.
NO_SUBJECT_BANNER = "NO EXPERIMENTAL SUBJECT ATTACHED"

#: Shown under the banner. The distinction matters: telemetry is not merely
#: absent, the machinery to receive it has no input.
NO_SUBJECT_DETAIL = "Cognitive telemetry unavailable"

#: Shown when a birth record exists but no signing key does. The extra sentence
#: is not decoration: without it a reader would reasonably assume a displayed
#: subject could sign, and would be wrong.
RECORDED_BANNER = "SUBJECT RECORDED, NOT KEY-ATTACHED"
RECORDED_DETAIL = (
    "A birth record exists, so a subject was created. No BABY_AI signing key is "
    "provisioned, so the subject cannot yet author anything attributable."
)


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

    Constructed from a :class:`provenance.keyring.Keyring` and, optionally, the
    read-only birth status payload from :func:`birth.status.birth_status`. Has no
    mutating methods by design.

    The birth payload is passed in rather than imported so that this module
    depends on nothing but a dictionary, and so that a test can construct any
    state without a birth ceremony.
    """

    def __init__(self, keyring: Any | None = None, birth: dict[str, Any] | None = None):
        self._keyring = keyring
        self._birth = birth or {}

    # -- queries ----------------------------------------------------------
    @property
    def status(self) -> SubjectStatus:
        if self._key_attached():
            return SubjectStatus.ATTACHED
        if self._birth.get("subject_exists"):
            return SubjectStatus.RECORDED
        return SubjectStatus.NO_SUBJECT

    def _key_attached(self) -> bool:
        if self._keyring is None:
            return False
        try:
            if not self._keyring.has_role(Role.BABY_AI):
                return False
            self._keyring.key_for_role(Role.BABY_AI)
            return True
        except (IntegrityError, Exception):
            # A missing, unreadable, or inconsistent keyring means we cannot
            # establish a subject. That is "no key", not "assume a key".
            return False

    def _key_ref(self) -> "SubjectRef | None":
        try:
            entry = self._keyring.key_for_role(Role.BABY_AI)  # type: ignore[union-attr]
        except (IntegrityError, Exception):
            return None
        return SubjectRef(
            subject_id=entry.actor_id,
            key_id=entry.key_id,
            actor_id=entry.actor_id,
        )

    def recorded_subject_id(self) -> str:
        """The subject id the birth record names, or the empty string.

        This is *not* proof of authorship. It is the identity a human-readable
        record claims, and it is used for display and for labelling the deriver's
        subject so that a domain reported by a recorded subject is not discarded
        as unattributable.
        """
        return str(self._birth.get("subject_id") or "")

    def subject(self) -> SubjectRef | None:
        """The key-attached subject, or ``None``.

        Keyring only, deliberately. A birth record is a statement by the
        laboratory; a :class:`SubjectRef` is a statement backed by key material,
        and only the second can be attributed. :meth:`recorded_subject_id` is the
        separate, weaker question.
        """
        if not self._key_attached():
            return None
        return self._key_ref()

    def is_attached(self) -> bool:
        """Whether a subject is *key-attached*, the strict reading."""
        return self.subject() is not None

    def is_present(self) -> bool:
        """Whether any subject exists, recorded or attached."""
        return self.status is not SubjectStatus.NO_SUBJECT

    def describe(self) -> str:
        subject = self.subject()
        if subject is not None:
            return f"SUBJECT: {subject.subject_id}"
        if self.status is SubjectStatus.RECORDED:
            return f"{RECORDED_BANNER}: {self.recorded_subject_id()}"
        return NO_SUBJECT_BANNER

    def detail(self) -> str | None:
        status = self.status
        if status is SubjectStatus.NO_SUBJECT:
            return NO_SUBJECT_DETAIL
        if status is SubjectStatus.RECORDED:
            return RECORDED_DETAIL
        return None

    def to_dict(self) -> dict[str, Any]:
        subject = self.subject()
        return {
            "status": self.status.value,
            "subject": subject.to_dict() if subject else None,
            "recorded_subject_id": self.recorded_subject_id(),
            "banner": self.describe(),
            "detail": self.detail(),
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"SubjectRegistry({self.describe()})"
