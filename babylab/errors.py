"""Exception hierarchy for the laboratory infrastructure.

Every failure mode that a researcher might need to distinguish has its own
type. Collapsing them into a generic ``Exception`` would make it impossible to
tell an integrity failure (a research-integrity incident) from a validation
failure (a programming error). These are kept separate on purpose.
"""


class BabyLabError(Exception):
    """Base class for all errors raised by the laboratory infrastructure."""


class ValidationError(BabyLabError):
    """A record, event or request failed structural validation.

    This indicates malformed input (for example a hand-edited event line).
    It is not a security incident.
    """


class IntegrityError(BabyLabError):
    """A cryptographic or chain integrity check failed.

    This is a research-integrity incident. It means recorded history was
    altered, truncated, reordered, or re-signed with an unexpected key.
    """


class TrustBoundaryViolation(BabyLabError):
    """An actor attempted an operation outside its permitted domain.

    Raised by :mod:`babylab.trust` when, for example, an actor presenting the
    ``BABY_AI`` role attempts to write inside ``human_control/``.

    .. warning::
       In Milestone 001 this is an **application-level** control only. It is
       enforced by this process, not by the operating system. See
       docs/security-model.md, section "Two Layers, Only One Of Which Is
       Enforced By The OS".
    """


class ConfigurationError(BabyLabError):
    """The laboratory is not initialised, or configuration is unusable."""


class AuthorizationError(BabyLabError):
    """A control-plane request was not authorised.

    Also a security event: it is recorded to the event log.
    """
