"""Recording the life of files in protected research areas.

This is the layer a future experiment actually calls: "the subject produced
this artifact" becomes a signed, versioned, tamper-evident ledger entry.

Two responsibilities
--------------------
1. **Version linkage.** Every ``MODIFY`` names the entry that recorded the
   previous state of the same path, so the history of any file can be walked
   backwards without gaps.
2. **Write authorisation.** Every write is checked against
   :class:`babylab.trust.PathPolicy` before the file is touched. A refusal is
   itself recorded (``Action.DENY``) so that attempts are part of the research
   record, not invisible.

What "protected" means here
---------------------------
Only files inside ``human_control/`` and ``research/`` are recorded. Files in
``baby_workspace/`` are the subject's own and are deliberately *not* in the
protected ledger - they are covered by the event stream instead, which is the
correct home for "the subject did a thing". See docs/provenance.md,
section "What Is And Is Not Recorded".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from babylab.clock import Clock
from babylab.errors import TrustBoundaryViolation
from babylab.hashing import file_sha256
from babylab.identity import Actor
from babylab.paths import ProjectPaths
from babylab.trust import PathPolicy
from provenance.keyring import Keyring
from provenance.ledger import Action, LedgerEntry, ProvenanceLedger

#: Sentinel used for the content hash of a file that does not exist. Using a
#: real digest-shaped value keeps the field type stable in the ledger.
ABSENT_SHA256 = "0" * 64


@dataclass(frozen=True)
class FileState:
    """What the recorder believes about a path at a point in time."""

    path: str
    exists: bool
    sha256: str
    size_bytes: int

    @classmethod
    def of(cls, path: str) -> "FileState":
        candidate = Path(path)
        if not candidate.exists():
            return cls(path=path, exists=False, sha256=ABSENT_SHA256, size_bytes=0)
        if candidate.is_dir():
            return cls(path=path, exists=True, sha256=ABSENT_SHA256, size_bytes=0)
        return cls(
            path=path,
            exists=True,
            sha256=file_sha256(candidate),
            size_bytes=candidate.stat().st_size,
        )


class ProvenanceRecorder:
    """Records creation and modification of protected research artifacts."""

    def __init__(
        self,
        ledger: ProvenanceLedger,
        keyring: Keyring,
        policy: PathPolicy,
        clock: Clock | None = None,
    ):
        self.ledger = ledger
        self.keyring = keyring
        self.policy = policy
        self.clock = clock or Clock()

    # -- public API -------------------------------------------------------
    def record_creation(
        self,
        path: Path,
        actor: Actor,
        experiment_id: str,
        reason: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Record that ``path`` was created by ``actor``."""
        return self._record(Action.CREATE, path, actor, experiment_id, reason, metadata)

    def record_modification(
        self,
        path: Path,
        actor: Actor,
        experiment_id: str,
        reason: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Record that ``path`` was changed by ``actor``.

        Refuses to record a modification of a path whose file has vanished,
        because the honest record of that event is a deletion, not a
        modification. Silently relabelling it would corrupt the version chain
        that later analysis depends on.
        """
        relative = self.policy.paths.relative(path)
        existing = self.ledger.latest_for_path(relative)
        if existing is not None and not Path(path).exists():
            raise ValueError(
                f"cannot record a modification of {relative!r}: the ledger has a "
                f"history for it but the file is gone. Record the deletion instead."
            )
        return self._record(Action.MODIFY, path, actor, experiment_id, reason, metadata)

    def record_deletion(
        self,
        path: Path,
        actor: Actor,
        experiment_id: str,
        reason: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        return self._record(Action.DELETE, path, actor, experiment_id, reason, metadata)

    def record_denial(
        self,
        path: Path,
        actor: Actor,
        experiment_id: str,
        reason: str,
        detail: str,
    ) -> LedgerEntry:
        """Record a refused write.

        The refused operation did not happen, so the content hash recorded is
        the *unchanged* current state. The point of the entry is the attempt.

        This intentionally bypasses :meth:`PathPolicy.assert_writable`: a
        denial that could itself be denied would leave no trace of the attempt,
        which is the one thing the researcher most needs to see.
        """
        relative = self.policy.paths.relative(path)
        state = FileState.of(str(Path(self.policy.paths.root) / relative))
        return self.ledger.record(
            action=Action.DENY,
            path=relative,
            content_sha256=state.sha256,
            size_bytes=state.size_bytes,
            experiment_id=experiment_id,
            reason=reason,
            actor=actor,
            prev_version_id=self._previous_version(relative),
            metadata={
                "denial_detail": detail,
                "path_domain": self.policy.classify(path).value,
            },
        )

    # -- verification -----------------------------------------------------
    def untracked_by_design(self) -> list[tuple[Path, str]]:
        """Files inside protected areas that the ledger deliberately ignores.

        Each exclusion states its reason, and :meth:`verify_paths` callers can
        print them, so an exclusion cannot quietly become a hole. An exclusion
        nobody reviews is an exclusion nobody is holding to account.
        """
        return [
            (
                self.policy.paths.private_key_dir,
                "secret signing-key material. Publishing a digest of a secret in "
                "a research record serves no research purpose and creates an "
                "offline oracle for guessing it. Key integrity is instead "
                "checked by the keyring fingerprint audit.",
            ),
            (
                self.policy.paths.protected_provenance,
                "the ledger's own seals. A seal is derived from the ledger head, "
                "so recording it inside the ledger would be circular. Seals are "
                "verified directly by ProvenanceLedger.verify_seal().",
            ),
        ]

    def verify_paths(self, paths: list[Path] | None = None) -> list[str]:
        """Check the ledger and the protected areas against each other.

        Both directions are checked, because each catches a different failure:

        * A file the ledger records that has since changed, or vanished, means
          an unrecorded modification or deletion.
        * A file present in a protected area that the ledger does not know
          about means an unrecorded creation - the exact thing the protected
          areas exist to prevent.

        Returns a list of human-readable discrepancies; empty means intact.
        """
        problems: list[str] = []
        excluded = [
            root.resolve()
            for root, _ in self.untracked_by_design()
            if Path(root).exists()
        ]

        if paths is None:
            paths = self._protected_files()

        checked: set[str] = set()
        for target in paths:
            resolved = Path(target).resolve()
            if any(_is_within(resolved, root) for root in excluded):
                continue
            relative = self.policy.paths.relative(target)
            checked.add(relative)
            latest = self.ledger.latest_for_path(relative)
            if latest is None:
                problems.append(
                    f"{relative}: present in a protected area but absent from the "
                    f"ledger (unrecorded creation)"
                )
                continue
            if latest.action is Action.DENY:
                continue
            state = FileState.of(str(target))
            if state.sha256 != latest.content_sha256:
                problems.append(
                    f"{relative}: content differs from {latest.entry_id} "
                    f"(recorded {latest.content_sha256[:12]}..., "
                    f"on disk {state.sha256[:12]}...)"
                )

        # The reverse direction: anything the ledger claims that is not on
        # disk. Deletions can only be detected here, because the forward pass
        # can only see files that still exist.
        for entry in self.ledger.iter_entries():
            if entry.action in (Action.DENY, Action.DELETE):
                continue
            relative = entry.path
            if relative in checked:
                continue
            candidate = Path(self.policy.paths.root) / relative
            if any(_is_within(candidate.resolve(), root) for root in excluded):
                continue
            if not candidate.exists():
                problems.append(
                    f"{relative}: recorded by {entry.entry_id} but missing from "
                    f"disk (unrecorded deletion)"
                )
        return problems

    def _protected_files(self) -> list[Path]:
        """Every file currently inside the protected domains."""
        found: list[Path] = []
        roots = [
            self.policy.paths.human_control,
            self.policy.paths.research,
        ]
        for root in roots:
            if not root.exists():
                continue
            for candidate in sorted(root.rglob("*")):
                if candidate.is_file():
                    found.append(candidate)
        return found

    # -- internals --------------------------------------------------------
    def _record(
        self,
        action: Action,
        path: Path,
        actor: Actor,
        experiment_id: str,
        reason: str,
        metadata: dict | None,
    ) -> LedgerEntry:
        relative = self.policy.paths.relative(path)
        try:
            self.policy.assert_writable(actor, path)
        except TrustBoundaryViolation as exc:
            if actor.key_id is not None:
                # The attempt is research data. Record it if we can.
                try:
                    self.record_denial(path, actor, experiment_id, reason, str(exc))
                except Exception:  # noqa: BLE001 - never mask the original error
                    pass
            raise

        state = FileState.of(str(path))
        combined = dict(metadata or {})
        combined["path_domain"] = self.policy.classify(path).value
        return self.ledger.record(
            action=action,
            path=relative,
            content_sha256=state.sha256,
            size_bytes=state.size_bytes,
            experiment_id=experiment_id,
            reason=reason,
            actor=actor,
            prev_version_id=self._previous_version(relative),
            metadata=combined,
        )

    def _previous_version(self, relative: str) -> str | None:
        previous = self.ledger.latest_for_path(relative)
        return previous.entry_id if previous is not None else None


def _is_within(candidate: Path, ancestor: Path) -> bool:
    try:
        candidate.relative_to(ancestor)
        return True
    except ValueError:
        return False
