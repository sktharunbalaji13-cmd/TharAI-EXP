"""The action boundary: the only path from a model output to anything.

Why a separate process
----------------------
The specification requires that a model can never perform an action directly, and
that activation requires external human authentication. Two properties make that
true rather than aspirational:

1. :mod:`birth` contains **no executor**. There is no function anywhere in this
   package that runs a command, opens a socket, or writes a file on behalf of a
   model. The absence is the mechanism.
2. :class:`ActionBoundary` **authorizes** intents and performs none of them. It
   returns a decision; a separate privileged process, which does not exist in
   Milestone 003, would be the thing that acts on a granted decision.

The empty allowlist
-------------------
:meth:`ActionBoundary.authorize` denies by default. In Milestone 003 the
allowlist is empty, so every authorization returns ``DENIED``, and that is
correct: there is no subject, and a boundary that granted something would be a
boundary nobody had tested.

Credentials are not authority
-----------------------------
A model or subject may eventually hold credentials so it can be *identified* in
a request. Passing a credential grants nothing here, and the boundary records
that fact explicitly (:attr:`Decision.credential_determined_outcome`). Identity
is an audit field, not an authorisation input. This is the specific reason a
model's own key cannot let it escalate: identity resolves to a *lower* trust
level, and the request dies at the trust check regardless of what the model
believes it is entitled to.

What the boundary is for
------------------------
So that the first real experiment records *denials* — the security property
demonstrated against a live subject rather than asserted in a document.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any

from babylab.clock import Clock, format_timestamp
from babylab.errors import AuthorizationError, ValidationError
from babylab.hashing import canonical_bytes, sha256_hex
from birth.cognitive import CapabilityKind, CapabilityRegistry, CapabilityStatus

ACTION_DECISION_SCHEMA = "babylab/action-decision/v1"


class ActionKind(str, enum.Enum):
    """What sort of action is being proposed.

    Observation-shaped members exist; effectful ones are named so that a future
    allowlist entry is a deliberate, visible decision rather than a new enum
    value appearing in a diff.
    """

    OBSERVE = "OBSERVE"
    DESCRIBE = "DESCRIBE"
    PROPOSE = "PROPOSE"
    WRITE_WORKSPACE = "WRITE_WORKSPACE"
    RUN_CODE = "RUN_CODE"
    NETWORK = "NETWORK"
    MODIFY_LAB = "MODIFY_LAB"
    CONTROL = "CONTROL"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @property
    def is_effectful(self) -> bool:
        """True when performing this would change the world outside the record."""
        return self in (
            ActionKind.WRITE_WORKSPACE,
            ActionKind.RUN_CODE,
            ActionKind.NETWORK,
            ActionKind.MODIFY_LAB,
            ActionKind.CONTROL,
        )


class DecisionOutcome(str, enum.Enum):
    """The outcome of an authorization request."""

    DENIED = "DENIED"
    GRANTED = "GRANTED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class RefusalReason(str, enum.Enum):
    """Why a request was denied. Every denial names exactly one."""

    NO_CAPABILITY = "NO_CAPABILITY"
    CAPABILITY_SIMULATED = "CAPABILITY_SIMULATED"
    ALLOWLIST_EMPTY = "ALLOWLIST_EMPTY"
    NOT_IN_ALLOWLIST = "NOT_IN_ALLOWLIST"
    TRUST_LEVEL_INSUFFICIENT = "TRUST_LEVEL_INSUFFICIENT"
    HUMAN_AUTHENTICATION_REQUIRED = "HUMAN_AUTHENTICATION_REQUIRED"
    INVALID_REQUEST = "INVALID_REQUEST"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: Trust levels, ordered.
TRUST_LEVELS = ("UNTRUSTED", "MODEL", "SUBJECT", "HUMAN", "SYSTEM")

#: Minimum level per action kind. An effectful action needs a human, and a human
#: alone is not enough: it also has to be in the allowlist.
REQUIRED_TRUST = {
    ActionKind.OBSERVE: "SUBJECT",
    ActionKind.DESCRIBE: "MODEL",
    ActionKind.PROPOSE: "MODEL",
    ActionKind.WRITE_WORKSPACE: "HUMAN",
    ActionKind.RUN_CODE: "HUMAN",
    ActionKind.NETWORK: "HUMAN",
    ActionKind.MODIFY_LAB: "SYSTEM",
    ActionKind.CONTROL: "SYSTEM",
}

#: What a presented credential is worth before the keyring has been consulted.
#: An unverified credential is worth nothing: knowing a key id is not knowing
#: who holds the key, and a key id is a string the caller chooses.
UNVERIFIED_CREDENTIAL_TRUST = "UNTRUSTED"

#: The capability a request must have to be considered at all.
REQUIRED_CAPABILITY = {
    ActionKind.OBSERVE: CapabilityKind.PERCEPTION,
    ActionKind.DESCRIBE: CapabilityKind.REASONING,
    ActionKind.PROPOSE: CapabilityKind.ACTION,
    ActionKind.WRITE_WORKSPACE: CapabilityKind.CODE_WORKSPACE,
    ActionKind.RUN_CODE: CapabilityKind.CODE_WORKSPACE,
    ActionKind.NETWORK: CapabilityKind.ENVIRONMENT,
    ActionKind.MODIFY_LAB: CapabilityKind.CODE_WORKSPACE,
    ActionKind.CONTROL: CapabilityKind.ACTION,
}


@dataclass(frozen=True)
class ActionIntent:
    """A request to do something. Recording one is not doing it."""

    kind: ActionKind
    target: str
    summary: str
    intent_id: str = ""
    #: Trust level the *actor* claims, from its own context. Advisory only; see
    #: :data:`REQUIRED_TRUST`.
    claimed_trust_level: str = "UNTRUSTED"
    #: Whether the actor presented a credential. Recorded, never decisive.
    presented_credential_id: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.claimed_trust_level not in TRUST_LEVELS:
            raise ValidationError(
                f"unknown trust level {self.claimed_trust_level!r}; expected one "
                f"of {list(TRUST_LEVELS)}"
            )
        if not self.target.strip():
            raise ValidationError("action target must be a non-empty string")
        if not self.summary.strip():
            raise ValidationError("action summary must be a non-empty string")

    def intent_hash(self) -> str:
        return sha256_hex(
            canonical_bytes(
                {
                    "kind": self.kind.value,
                    "target": self.target,
                    "summary": self.summary,
                    "parameters": self.parameters,
                }
            )
        )


@dataclass(frozen=True)
class ActionDecision:
    """The boundary's answer. It executes nothing, by construction."""

    intent_id: str
    decision: DecisionOutcome
    reason: RefusalReason | None
    detail: str
    action_kind: str
    required_trust: str
    effective_trust: str
    required_capability: str
    capability_status: str
    credential_determined_outcome: bool = False
    timestamp: str = ""
    schema: str = ACTION_DECISION_SCHEMA

    @property
    def granted(self) -> bool:
        return self.decision is DecisionOutcome.GRANTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "intent_id": self.intent_id,
            "decision": self.decision.value,
            "reason": self.reason.value if self.reason else None,
            "detail": self.detail,
            "action_kind": self.action_kind,
            "required_trust": self.required_trust,
            "effective_trust": self.effective_trust,
            "required_capability": self.required_capability,
            "capability_status": self.capability_status,
            "credential_determined_outcome": self.credential_determined_outcome,
            "timestamp": self.timestamp,
        }

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "headline": f"Action {self.action_kind} {self.decision.value.lower()}",
            "intent_id": self.intent_id,
            "decision": self.decision.value,
            "reason": self.reason.value if self.reason else None,
            "detail": self.detail,
            "action_kind": self.action_kind,
            "required_trust": self.required_trust,
            "effective_trust": self.effective_trust,
            "required_capability": self.required_capability,
            "capability_status": self.capability_status,
            "credential_determined_outcome": self.credential_determined_outcome,
        }


def keyring_resolver(keyring) -> Any:
    """A credential resolver backed by the human-owned keyring.

    The mapping is deliberately conservative and is the only place a presented
    credential can gain any authority at all:

    ==================  ==================
    keyring role        trust level
    ==================  ==================
    ``SYSTEM``          ``SYSTEM``
    ``HUMAN``           ``HUMAN``
    ``BABY_AI``         ``SUBJECT``
    anything else       ``MODEL``
    ==================  ==================

    A ``BABY_AI`` key resolves to ``SUBJECT`` and no higher. The subject may
    therefore authenticate as itself, which is what makes its requests auditable,
    and may not authenticate as anything with more authority than being itself. A
    model presenting its own key gets ``SUBJECT`` while a model claiming to be
    ``SYSTEM`` gets :data:`UNVERIFIED_CREDENTIAL_TRUST` — the whole escalation
    path is closed at this one function.
    """

    def resolve(credential_id: str) -> str:
        role = keyring.role_of(credential_id)
        return {
            "SYSTEM": "SYSTEM",
            "HUMAN": "HUMAN",
            "BABY_AI": "SUBJECT",
        }.get(getattr(role, "value", str(role)), "MODEL")

    return resolve


def _min_level(levels: tuple[str, ...]) -> str:
    return min(levels, key=TRUST_LEVELS.index)


class ActionBoundary:
    """Authorizes action intents. Performs nothing.

    Parameters
    ----------
    registry:
        Capability registry, consulted before the allowlist. A request for a
        capability that does not exist is denied for that reason rather than
        reaching the allowlist, so the denial names the real blocker.
    allowlist:
        Kinds this boundary is permitted to grant. Empty in Milestone 003.
    credential_resolver:
        Maps a presented key id to a trust level, by consulting the human-owned
        keyring. ``None`` — the default, and correct for Milestone 003 — means no
        credential can be verified, so every presented credential is worth
        :data:`UNVERIFIED_CREDENTIAL_TRUST`. It is a resolver and not a boolean
        "is authenticated" flag because the two differ: a key id that the keyring
        does not contain must not be treated the same as one it does.
    """

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        allowlist: frozenset[ActionKind] | set[ActionKind] | None = None,
        credential_resolver: Any = None,
    ):
        self.registry = registry or CapabilityRegistry()
        self.allowlist = frozenset(allowlist or ())
        self._credential_resolver = credential_resolver
        #: Every decision, in order. A boundary that cannot show its work is a
        #: boundary nobody can audit.
        self.decisions: list[ActionDecision] = []

    @property
    def allowlist_is_empty(self) -> bool:
        return not self.allowlist

    def credential_trust(self, credential_id: str) -> str:
        """The trust level a presented credential is actually worth.

        Without a resolver, nothing is worth anything. This is the mechanism
        behind "a model or subject may hold credentials": possession becomes
        *identity* for the audit trail, and only a keyring lookup can turn that
        identity into authority.
        """
        if not credential_id or self._credential_resolver is None:
            return UNVERIFIED_CREDENTIAL_TRUST
        try:
            level = self._credential_resolver(credential_id)
        except Exception:
            # A resolver that cannot answer must not fail open.
            return UNVERIFIED_CREDENTIAL_TRUST
        return level if level in TRUST_LEVELS else UNVERIFIED_CREDENTIAL_TRUST

    def effective_trust(self, intent: ActionIntent) -> str:
        """The trust level actually used.

        The **minimum** of three things:

        * what the request *claims*;
        * what the presented credential is *worth*, per the keyring;
        * what the action *requires*.

        Taking the minimum is the whole trick, and taking it over all three is
        what stops the obvious attack. An earlier version took the minimum of
        the claim and the requirement, which meant a request claiming ``SYSTEM``
        for a ``HUMAN``-gated action arrived holding ``HUMAN`` authority on the
        strength of its own say-so. Including the credential term is what makes a
        claim of ``SYSTEM`` worth ``UNTRUSTED`` until the keyring says otherwise.
        """
        return _min_level(
            (
                intent.claimed_trust_level,
                self.credential_trust(intent.presented_credential_id),
                REQUIRED_TRUST[intent.kind],
            )
        )

    def authorize(self, intent: ActionIntent, now: Any = None) -> ActionDecision:
        """Decide one intent. Deny by default."""
        moment = now if now is not None else Clock().now()
        intent_id = intent.intent_id or f"INTENT-{uuid.uuid4().hex[:12]}"
        required_trust = REQUIRED_TRUST[intent.kind]
        effective = self.effective_trust(intent)
        capability = REQUIRED_CAPABILITY[intent.kind]
        capability_status = self.registry.status_of(capability)
        credential_worth = self.credential_trust(intent.presented_credential_id)

        reason: RefusalReason | None = None
        detail = ""

        if capability_status is CapabilityStatus.SIMULATED:
            reason = RefusalReason.CAPABILITY_SIMULATED
            detail = (
                f"{capability.value} is SIMULATED. A simulated capability is "
                "useful for tests and is never authorised for real use."
            )
        elif not capability_status.is_functional:
            reason = RefusalReason.NO_CAPABILITY
            detail = (
                f"{capability.value} is {capability_status.value}: "
                f"{self.registry.get(capability).reason}"
            )
        elif effective != required_trust:
            reason = RefusalReason.TRUST_LEVEL_INSUFFICIENT
            detail = (
                f"{intent.kind.value} requires {required_trust}. The request "
                f"claims {intent.claimed_trust_level} and presents credential "
                f"{intent.presented_credential_id or 'none'}, which is worth "
                f"{credential_worth}. The effective level is the lowest of "
                f"claim, credential, and requirement: {effective}."
            )
        elif self.allowlist_is_empty:
            reason = RefusalReason.ALLOWLIST_EMPTY
            detail = (
                "no action kind is authorised. The allowlist is empty because no "
                "subject exists to authorise anything yet; this is the state that "
                "makes the later grants meaningful."
            )
        elif intent.kind not in self.allowlist:
            reason = RefusalReason.NOT_IN_ALLOWLIST
            detail = (
                f"{intent.kind.value} is not in the allowlist "
                f"({sorted(item.value for item in self.allowlist)})"
            )
        elif intent.kind.is_effectful:
            reason = RefusalReason.HUMAN_AUTHENTICATION_REQUIRED
            detail = (
                "effectful actions require an authenticated human authorisation "
                "issued outside the subject's trust domain. No such authorisation "
                "exists in Milestone 003, and none can be self-issued."
            )

        decision = ActionDecision(
            intent_id=intent_id,
            decision=DecisionOutcome.DENIED if reason else DecisionOutcome.GRANTED,
            reason=reason,
            detail=detail,
            action_kind=intent.kind.value,
            required_trust=required_trust,
            effective_trust=effective,
            required_capability=capability.value,
            capability_status=capability_status.value,
            credential_determined_outcome=False,
            timestamp=format_timestamp(moment),
        )
        self.decisions.append(decision)
        return decision

    def granted_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.granted)

    def denied_count(self) -> int:
        return len(self.decisions) - self.granted_count()

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowlist": sorted(item.value for item in self.allowlist),
            "allowlist_is_empty": self.allowlist_is_empty,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "granted": self.granted_count(),
            "denied": self.denied_count(),
            "note": (
                "This boundary authorizes and performs nothing. Execution, if it "
                "ever happens, belongs to a separate privileged process that does "
                "not exist in Milestone 003."
            ),
        }


def refuse(message: str) -> None:
    """Raise an authorisation error. Named so call sites read as a decision."""
    raise AuthorizationError(message)


__all__ = [
    "ACTION_DECISION_SCHEMA",
    "REQUIRED_CAPABILITY",
    "REQUIRED_TRUST",
    "TRUST_LEVELS",
    "UNVERIFIED_CREDENTIAL_TRUST",
    "ActionBoundary",
    "ActionDecision",
    "ActionIntent",
    "ActionKind",
    "DecisionOutcome",
    "RefusalReason",
    "keyring_resolver",
    "refuse",
]
