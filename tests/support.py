"""Shared test fixtures.

Every test runs against a throwaway laboratory in a temporary directory,
selected by setting ``BABYAI_HOME``. Nothing in this suite reads or writes the
real research records. That separation is what makes the suite safe to run at
any time, including in the middle of an experiment.

    python -m unittest discover -s tests -v

No third-party test runner is required. The suite is written against
``unittest`` from the standard library so that the dependency budget stays at
zero. It is also compatible with ``pytest`` if that is preferred.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from babylab.clock import FixedClock  # noqa: E402
from babylab.identity import Actor, Role  # noqa: E402
from babylab.paths import ENV_HOME, ProjectPaths  # noqa: E402
from babylab.trust import PathPolicy  # noqa: E402
from events.store import EventStore  # noqa: E402
from provenance.keyring import Keyring  # noqa: E402
from provenance.ledger import ProvenanceLedger  # noqa: E402
from provenance.recorder import ProvenanceRecorder  # noqa: E402


class LabTestCase(unittest.TestCase):
    """Base class giving each test its own isolated laboratory."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="babylab-test-")
        self.root = Path(self._tmp).resolve()
        self._previous_home = os.environ.get(ENV_HOME)
        os.environ[ENV_HOME] = str(self.root)
        self.addCleanup(self._restore_home)
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.paths = ProjectPaths(self.root)
        self.paths.ensure_directories()
        self.policy = PathPolicy(self.paths)
        self.clock = FixedClock()

        self.store = EventStore(self.paths.event_store, clock=self.clock)
        self.keyring = Keyring(self.paths.keyring, self.paths.private_key_dir, clock=self.clock)
        self._bootstrap_keyring()
        self.ledger = ProvenanceLedger(
            self.paths.provenance_ledger,
            self.keyring,
            clock=self.clock,
            seal_dir=self.paths.protected_provenance,
        )
        self.recorder = ProvenanceRecorder(
            self.ledger, self.keyring, self.policy, clock=self.clock
        )
        # Mirror bootstrap: the keyring's creation is itself recorded, so that
        # a protected-area audit starts from a clean, faithful baseline.
        self.recorder.record_creation(
            self.paths.keyring, self.human, "MILESTONE-001", "test keyring"
        )
        self.control_token = self._provision_control_token()
        self.recorder.record_creation(
            self.paths.control_token,
            self.human,
            "MILESTONE-001",
            "test control-plane authentication token",
        )
        #: Entries the fixture itself contributed. Tests assert on deltas
        #: against this, so that changing the fixture does not silently
        #: invalidate absolute counts elsewhere.
        self.baseline_entries = self.ledger.count()

    def _restore_home(self) -> None:
        if self._previous_home is None:
            os.environ.pop(ENV_HOME, None)
        else:
            os.environ[ENV_HOME] = self._previous_home

    def _bootstrap_keyring(self) -> None:
        self.keyring._entries = {}
        self.keyring._loaded = True
        self.human_key = self.keyring.register(Role.HUMAN, "human:operator", "test human key")
        self.system_key = self.keyring.register(Role.SYSTEM, "system:lab", "test system key")

    def _provision_control_token(self) -> bytes:
        """Mirror bootstrap: a shared secret the control plane authenticates with."""
        import base64
        import secrets

        from babylab.storage import atomic_write_text

        token = secrets.token_bytes(32)
        atomic_write_text(
            self.paths.control_token, base64.b64encode(token).decode("ascii") + "\n"
        )
        return token

    # -- actors -----------------------------------------------------------
    @property
    def human(self) -> Actor:
        return self.keyring.actor_of(self.human_key.key_id)

    @property
    def system(self) -> Actor:
        return self.keyring.actor_of(self.system_key.key_id)

    def provision_baby_ai(self, actor_id: str = "baby-ai:subject") -> Actor:
        """Mint a BABY_AI key the way the human eventually would.

        Only tests call this. There is deliberately no runtime path that
        provisions a BABY_AI key, because doing so is a human research
        decision, not something the laboratory should do on its own.
        """
        entry = self.keyring.register(Role.BABY_AI, actor_id, "test subject key")
        return self.keyring.actor_of(entry.key_id)

    # -- helpers ----------------------------------------------------------
    def write(self, relative: str, content: str = "x") -> Path:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def rewrite_ledger(self, transform) -> None:
        """Apply ``transform`` to the raw ledger text, simulating tampering.

        Deliberately crude: it edits the file the way a party with write
        access would, not the way the library would. That is the point - the
        verification code must catch an outsider's edit, not just its own.
        """
        original = self.ledger.path.read_text(encoding="utf-8")
        self.ledger.path.write_text(transform(original), encoding="utf-8")

    def rewrite_events(self, transform) -> None:
        """Apply ``transform`` to the raw event log, simulating tampering."""
        original = self.store.path.read_text(encoding="utf-8")
        self.store.path.write_text(transform(original), encoding="utf-8")

    def read_ledger_lines(self) -> list[str]:
        if not self.ledger.path.exists():
            return []
        return [
            line
            for line in self.ledger.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def read_event_lines(self) -> list[str]:
        if not self.store.path.exists():
            return []
        return [
            line
            for line in self.store.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


__all__ = ["LabTestCase", "Actor", "Role", "ROOT"]
