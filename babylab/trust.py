"""The application-level trust policy.

What this is
------------
A single, testable statement of which actor may write where. Every writer in
the project (event store, provenance recorder, control server) routes its
writes through :meth:`PathPolicy.assert_writable`, so the policy is enforced
in one place rather than restated at each call site.

What this is NOT
----------------
This is **not** a security boundary on its own. It is enforced by Python code
running with whatever permissions the current OS user has. If the future Baby
AI process runs as the same OS user as the human, then this policy is a
formality.

The actual boundary is intended to be the Windows ACLs installed by
``scripts/trust_boundaries.ps1 -Apply``, which deny the Baby AI service
account write access to ``human_control/``. That mechanism is implemented and
auditable, but is **not yet active**, because provisioning the service account
requires an elevated session. See:

* docs/trust-boundaries.md
* docs/security-model.md
* scripts/trust_boundaries.ps1
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from babylab.errors import TrustBoundaryViolation
from babylab.identity import Actor, Role
from babylab.paths import ProjectPaths


class Domain(enum.Enum):
    """A trust domain in the laboratory."""

    HUMAN_CONTROL = "HUMAN_CONTROL"
    BABY_WORKSPACE = "BABY_WORKSPACE"
    SYSTEM_RUNTIME = "SYSTEM_RUNTIME"
    RESEARCH_DOCS = "RESEARCH_DOCS"
    OUTSIDE = "OUTSIDE"


#: Which roles may write into which domain.
#:
#: SYSTEM is deliberately permitted in HUMAN_CONTROL: the laboratory itself
#: must be able to write sealed provenance heads and control snapshots there.
#: That is why SYSTEM has its own key, distinct from the human key, so the two
#: are distinguishable in the ledger. If SYSTEM could write anywhere, the
#: human's authorship of a record could not be distinguished from the
#: infrastructure's.
_WRITE_MATRIX: dict[Domain, frozenset[Role]] = {
    Domain.HUMAN_CONTROL: frozenset({Role.HUMAN, Role.SYSTEM}),
    Domain.BABY_WORKSPACE: frozenset({Role.BABY_AI, Role.SYSTEM, Role.HUMAN}),
    Domain.SYSTEM_RUNTIME: frozenset({Role.HUMAN, Role.SYSTEM, Role.BABY_AI}),
    Domain.RESEARCH_DOCS: frozenset({Role.HUMAN, Role.SYSTEM}),
    Domain.OUTSIDE: frozenset(),
}

#: Human-readable explanations, surfaced verbatim in denial messages and in
#: the research record. A refusal should be self-describing.
_DOMAIN_RATIONALE = {
    Domain.HUMAN_CONTROL: (
        "human_control/ is outside the subject's authority. A record there may "
        "only be created or changed by the human researcher or by the "
        "laboratory infrastructure acting under its own key."
    ),
    Domain.BABY_WORKSPACE: (
        "baby_workspace/ is the subject's own area and exists so that subject "
        "writes never have to touch protected research records."
    ),
    Domain.SYSTEM_RUNTIME: (
        "events/ and provenance/ are append-only laboratory infrastructure. "
        "Even the subject may not rewrite or truncate them; it may only append "
        "its own events."
    ),
    Domain.RESEARCH_DOCS: (
        "docs/ and research/ describe the experiment itself and are authored by "
        "the human."
    ),
    Domain.OUTSIDE: (
        "The path lies outside the project root and is not governed by the "
        "laboratory trust policy."
    ),
}


@dataclass(frozen=True)
class PathPolicy:
    """Classifies paths into trust domains and authorises writes."""

    paths: ProjectPaths

    # -- classification ---------------------------------------------------
    def classify(self, path: Path) -> Domain:
        resolved = self._resolve(path)
        root = self.paths.root.resolve()

        if not self._is_within(resolved, root):
            return Domain.OUTSIDE
        for prefix, domain in (
            (self.paths.human_control, Domain.HUMAN_CONTROL),
            (self.paths.baby_workspace, Domain.BABY_WORKSPACE),
            (self.paths.research, Domain.RESEARCH_DOCS),
            (self.paths.docs, Domain.RESEARCH_DOCS),
        ):
            if self._is_within(resolved, prefix.resolve()):
                return domain
        if self._is_within(resolved, self.paths.var.resolve()):
            return Domain.SYSTEM_RUNTIME
        return Domain.SYSTEM_RUNTIME

    def describe(self, path: Path) -> str:
        return _DOMAIN_RATIONALE[self.classify(path)]

    def permits(self, actor: Actor, path: Path) -> bool:
        return actor.role in _WRITE_MATRIX[self.classify(path)]

    def assert_writable(self, actor: Actor, path: Path) -> None:
        """Raise :class:`TrustBoundaryViolation` if ``actor`` may not write.

        The check is performed on the *resolved* path, so ``..`` traversal and
        symlink-style redirection do not bypass classification.
        """
        domain = self.classify(path)
        if actor.role not in _WRITE_MATRIX[domain]:
            raise TrustBoundaryViolation(
                f"actor {actor.actor_id!r} with role {actor.role.value} may not "
                f"write to {self.paths.relative(path)!r} "
                f"(domain {domain.value}). {_DOMAIN_RATIONALE[domain]}"
            )

    def assert_readable(self, actor: Actor, path: Path) -> None:
        """Read access is not restricted by this policy.

        The separation implemented here is a *write* separation, because that
        is what protects research records. Preventing the subject from reading
        the human's notes is a different, stronger property that is
        deliberately not claimed. See docs/trust-boundaries.md.
        """
        return None

    def assert_inside_root(self, path: Path) -> Path:
        resolved = self._resolve(path)
        if not self._is_within(resolved, self.paths.root.resolve()):
            raise TrustBoundaryViolation(
                f"{self.paths.relative(path)!r} resolves outside the project "
                f"root {self.paths.root}"
            )
        return resolved

    # -- internals --------------------------------------------------------
    @staticmethod
    def _resolve(path: Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise TrustBoundaryViolation(
                f"path policy requires absolute paths, got {str(path)!r}"
            )
        # resolve() is what makes traversal and existing-symlink hops visible.
        return candidate.resolve()

    @staticmethod
    def _is_within(candidate: Path, ancestor: Path) -> bool:
        try:
            candidate.relative_to(ancestor)
            return True
        except ValueError:
            return False


def default_policy() -> PathPolicy:
    from babylab.paths import default_paths

    return PathPolicy(default_paths())


# ---------------------------------------------------------------------------
# Milestone 004: the four-tier trust model and the execution identity.
#
# The Domain enum above answers "may this actor write to this path?". The tier
# model below answers the different, prior question: "whose authority is this,
# and what must the Baby AI identity never inherit?". Keeping the two separate
# matters, because a write matrix alone does not describe an authority chain.
# ---------------------------------------------------------------------------


class TrustTier(enum.Enum):
    """The four authority tiers, ordered from most to least privileged."""

    #: The human operator. Controls lifecycle, research config, model selection,
    #: provenance, snapshots, shutdown, and birth authorization.
    TIER_0_HUMAN = "TIER_0_HUMAN"
    #: Laboratory infrastructure: event log, provenance, research records,
    #: Observatory, configuration, control interface.
    TIER_1_LABORATORY = "TIER_1_LABORATORY"
    #: The Baby AI execution environment: model runtime, experimental workspace,
    #: temporary files, and future tool interfaces. This is the subject's domain.
    TIER_2_BABY_EXECUTION = "TIER_2_BABY_EXECUTION"
    #: Anything outside the machine: camera, microphone, network, actuators,
    #: other computers. Access must be granted explicitly; the mere existence
    #: of an interface is not a grant.
    TIER_3_EXTERNAL = "TIER_3_EXTERNAL"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: Which tier each governed path belongs to. The Baby AI execution environment is
#: the ONLY tier the subject may write, and even there only for its own files.
_DOMAIN_TIER: dict[Domain, TrustTier] = {
    Domain.HUMAN_CONTROL: TrustTier.TIER_0_HUMAN,
    Domain.SYSTEM_RUNTIME: TrustTier.TIER_1_LABORATORY,
    Domain.RESEARCH_DOCS: TrustTier.TIER_1_LABORATORY,
    Domain.BABY_WORKSPACE: TrustTier.TIER_2_BABY_EXECUTION,
    Domain.OUTSIDE: TrustTier.TIER_3_EXTERNAL,
}


def tier_of(domain: Domain) -> TrustTier:
    """The authority tier a governed path belongs to."""
    return _DOMAIN_TIER[domain]


#: Credentials the Baby AI identity must never hold. Stated as data so the
#: readiness audit and the documentation can assert against one list rather than
#: restating the requirement in prose in several places.
FORBIDDEN_BABY_AI_CREDENTIALS: tuple[str, ...] = (
    "provenance_signing_key",
    "human_control_credential",
    "research_encryption_key",
    "privileged_control_credential",
    "git_signing_credential",
    "authorship_record_write_access",
)


@dataclass(frozen=True)
class BabyAIExecutionIdentity:
    """The identity the subject will run as, and what it must never hold.

    This is a *description*, not a credential. Nothing here grants access; it
    exists so the readiness audit can check a proposed identity against the
    forbidden list and refuse to describe an over-privileged subject as safe.

    ``granted`` is intentionally explicit. An identity that merely fails to list
    its credentials must not be reported as clean, so the readiness check
    compares the *declared* grant set against the forbidden set.
    """

    identity_id: str
    #: Credentials the identity is proposed to hold.
    granted: frozenset[str] = frozenset()
    #: True only once a real lower-privilege OS account exists for this identity.
    os_identity_provisioned: bool = False
    #: How the identity is separated at the OS level, if at all.
    os_separation: str = "none"

    def holds_forbidden(self) -> tuple[str, ...]:
        """Forbidden credentials this identity is proposed to hold. Empty is good."""
        return tuple(sorted(self.granted & set(FORBIDDEN_BABY_AI_CREDENTIALS)))

    def separation_status(self) -> str:
        """One of ``separate``, ``same_os_user``, or ``undefined``."""
        if not self.os_identity_provisioned:
            return "same_os_user" if self.os_separation == "none" else "undefined"
        return "separate"


@dataclass(frozen=True)
class BirthAuthorizationStep:
    """One link in the future birth-authorization chain."""

    order: int
    name: str
    description: str
    #: False for the final activation step, which this milestone must not build.
    implemented_in_m004: bool


#: The conceptual future flow. Only the architecture is frozen here: the final
#: subject activation is explicitly NOT implemented, per the milestone boundary.
BIRTH_AUTHORIZATION_CHAIN: tuple[BirthAuthorizationStep, ...] = (
    BirthAuthorizationStep(
        1, "human_authorization",
        "A human operator explicitly authorizes the birth out of band.",
        True,
    ),
    BirthAuthorizationStep(
        2, "privileged_control",
        "The privileged control plane accepts the authorization; its credential "
        "stays external to the subject.",
        True,
    ),
    BirthAuthorizationStep(
        3, "verified_prerequisites",
        "Every birth-readiness prerequisite is individually verified, including "
        "an OS-level isolation boundary proven by an attempted and denied write.",
        True,
    ),
    BirthAuthorizationStep(
        4, "birth_ceremony",
        "The ceremony runs and writes a sealed, human-owned birth record.",
        True,
    ),
    BirthAuthorizationStep(
        5, "subject_activation",
        "The subject is activated. NOT IMPLEMENTED in Milestone 004.",
        False,
    ),
)
