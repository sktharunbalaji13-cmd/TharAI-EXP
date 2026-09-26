"""The Observatory must be incapable of changing anything.

Two halves:

*Behavioural* — running the Observatory against a real laboratory leaves the
canonical event log, the provenance ledger, and the protected tree byte-identical.
*Structural* — the Observatory package contains no reference to any write entry
point, so the guarantee does not depend on a code path being exercised.

The structural half matters because behavioural tests only prove the paths they
happen to run. A future edit that adds a write call would be caught by the
source scan even if no test triggered it.
"""

from __future__ import annotations

import ast
import io
import unittest
from pathlib import Path

from observatory.cli import main
from observatory.reader import ObservatoryReader
from observatory.terminal import ObservatorySession
from tests.support import LabTestCase

OBSERVATORY_DIR = Path(__file__).resolve().parent.parent / "observatory"

#: Mutating methods, keyed by the object they would be called on. Matching on
#: the receiver is what makes this check meaningful: ``lines.append(...)`` is
#: how a renderer builds output and is obviously fine, whereas
#: ``store.append(...)`` would be the Observatory writing to the canonical log.
FORBIDDEN_ON_OBJECT: dict[str, set[str]] = {
    "store": {"append", "append_many"},
    "ledger": {"record", "record_creation", "record_change", "seal"},
    "recorder": {"record", "record_creation", "record_change"},
    "keyring": {"register", "store_secret", "revoke"},
    "registry": {"register", "add", "attach", "provision"},
}

#: Filesystem mutation. The Observatory has no legitimate reason to touch the
#: filesystem at all, so these are forbidden on any receiver.
FORBIDDEN_ANYWHERE: set[str] = {
    "write_text",
    "write_bytes",
    "unlink",
    "mkdir",
    "rmdir",
    "remove",
    "rename",
    "replace",
    "touch",
    "rmtree",
}

#: Modes that would create or modify a file.
WRITE_MODES = ("w", "a", "x", "+")

#: Modules whose whole purpose is mutation. The Observatory may not import them
#: for writing; ``Keyring`` is allowed for reading, and is checked separately.
FORBIDDEN_MODULES = frozenset({"provenance.recorder", "control.server", "provenance.seal"})


def _dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class ObservatorySourceScanTests(unittest.TestCase):
    """The package must contain no call to any mutating entry point."""

    def sources(self) -> list[Path]:
        return sorted(OBSERVATORY_DIR.glob("*.py"))

    def test_package_has_sources_to_scan(self) -> None:
        self.assertTrue(self.sources(), "observatory package appears to be empty")

    def test_no_forbidden_calls(self) -> None:
        offences: list[str] = []
        for path in self.sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _dotted_name(node.func)
                if not name:
                    continue
                parts = name.split(".")
                method = parts[-1]
                receiver = parts[-2] if len(parts) >= 2 else ""

                if method in FORBIDDEN_ANYWHERE:
                    offences.append(f"{path.name}:{node.lineno} calls {name}")
                    continue
                if method in FORBIDDEN_ON_OBJECT.get(receiver, set()):
                    offences.append(
                        f"{path.name}:{node.lineno} calls {name} "
                        f"(mutating {receiver})"
                    )
                    continue
                if method == "open" and self._opens_for_writing(node):
                    offences.append(f"{path.name}:{node.lineno} opens a file for writing")
        self.assertEqual(offences, [], "mutating calls found: " + "; ".join(offences))

    def _opens_for_writing(self, call: ast.Call) -> bool:
        """True when an ``open(...)`` call could create or modify a file."""
        for argument in list(call.args) + [kw.value for kw in call.keywords]:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                if argument.value in WRITE_MODES:
                    return True
        return False

    def test_no_import_of_write_only_modules(self) -> None:
        offences: list[str] = []
        for path in self.sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name in FORBIDDEN_MODULES:
                        offences.append(f"{path.name}:{node.lineno} imports {name}")
        self.assertEqual(offences, [], "forbidden imports: " + "; ".join(offences))

    def test_no_network_import(self) -> None:
        # Milestone 002 is a local instrument. It has no business opening a
        # socket, and adding one later needs to be a deliberate decision.
        offences: list[str] = []
        for path in self.sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in {"socket", "http", "urllib", "requests", "ssl"}:
                        offences.append(f"{path.name}:{node.lineno} imports {name}")
        self.assertEqual(offences, [], "network imports: " + "; ".join(offences))

    def test_no_synthetic_cognition_constants(self) -> None:
        # A readiness score, a confidence, a mood, a thought count: anything that
        # looks like a psychological readout would have to be invented, and
        # inventing one is what this milestone is not allowed to do.
        banned = ("readiness", "confidence", "engagement", "curiosity", "mood", "happiness")
        offences: list[str] = []
        for path in self.sources():
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                if word in text:
                    offences.append(f"{path.name} mentions {word!r}")
        self.assertEqual(offences, [], "synthetic cognition terms: " + "; ".join(offences))


class ReadOnlyBehaviourTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        for index in range(4):
            self.store.append("system.test", "test", {"n": index})
        self.ledger_entries = self.ledger.count()

    def digest(self) -> dict[str, bytes]:
        return {
            "events": self.store.path.read_bytes(),
            "ledger": self.ledger.path.read_bytes(),
        }

    def test_full_ingest_leaves_the_event_log_byte_identical(self) -> None:
        before = self.digest()
        reader = ObservatoryReader(store=self.store, clock=self.clock)
        reader.replay()
        reader.poll()
        self.assertEqual(self.digest(), before)

    def test_session_update_leaves_the_event_log_byte_identical(self) -> None:
        before = self.digest()
        session = ObservatorySession(paths=self.paths, clock=self.clock, keyring=self.keyring)
        session.update()
        session.update()
        self.assertEqual(self.digest(), before)

    def test_session_does_not_add_provenance_entries(self) -> None:
        session = ObservatorySession(paths=self.paths, clock=self.clock, keyring=self.keyring)
        session.update()
        self.assertEqual(self.ledger.count(), self.ledger_entries)

    def test_session_creates_no_files(self) -> None:
        before = sorted(p.name for p in self.paths.var.iterdir())
        session = ObservatorySession(paths=self.paths, clock=self.clock, keyring=self.keyring)
        session.update()
        # Derived state is in memory; the var directory is untouched.
        self.assertEqual(sorted(p.name for p in self.paths.var.iterdir()), before)
        self.assertFalse((self.paths.var / "observatory").exists())

    def test_session_does_not_write_into_baby_workspace(self) -> None:
        session = ObservatorySession(paths=self.paths, clock=self.clock, keyring=self.keyring)
        session.update()
        for child in self.paths.baby_workspace.rglob("*"):
            if child.is_file():
                self.assertEqual(child.name, ".gitkeep", f"unexpected file {child}")

    def test_reader_never_opens_the_store_for_writing(self) -> None:
        # The reader holds a store, so assert it only ever calls reading methods.
        reader = ObservatoryReader(store=self.store, clock=self.clock)
        reader.replay()
        reader.poll()
        self.assertGreater(reader.ingested_count(), 0)

    def test_event_chain_still_verifies_after_observing(self) -> None:
        before = self.digest()
        session = ObservatorySession(paths=self.paths, clock=self.clock, keyring=self.keyring)
        session.update()
        report = self.store.verify_chain()
        self.assertEqual(report.problems, [])
        self.assertEqual(report.valid_events, 4)
        self.assertEqual(self.digest(), before)


class CliIsReadOnlyTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.append("system.test", "test", {"n": 1})
        self._stdout = io.StringIO()
        self._real = None

    def run_cli(self, *args: str) -> int:
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(list(args))
        return code

    def test_status_exits_zero(self) -> None:
        self.assertEqual(self.run_cli("status"), 0)

    def test_state_exits_zero(self) -> None:
        self.assertEqual(self.run_cli("state"), 0)

    def test_history_exits_zero(self) -> None:
        self.assertEqual(self.run_cli("history"), 0)

    def test_live_with_bounded_iterations_exits_zero(self) -> None:
        self.assertEqual(self.run_cli("live", "--iterations", "2"), 0)

    def test_cli_does_not_modify_the_log(self) -> None:
        before = self.store.path.read_bytes()
        for command in ("status", "state", "history"):
            self.run_cli(command)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_json_mode_emits_valid_json(self) -> None:
        import contextlib
        import json

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--json", "state"])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["schema"], "babylab/observatory-snapshot/v1")

    def test_json_reports_no_subject(self) -> None:
        import contextlib
        import json

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--json", "status"])
        subject = json.loads(buffer.getvalue())["subject"]
        self.assertEqual(subject["status"], "NO_SUBJECT")
        self.assertEqual(subject["banner"], "NO EXPERIMENTAL SUBJECT ATTACHED")
        self.assertIsNotNone(subject["detail"])

    def test_snapshot_exposes_no_fabricated_subject(self) -> None:
        import contextlib
        import json

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--json", "state"])
        payload = json.loads(buffer.getvalue())
        self.assertIsNone(payload["state"]["subject_id"])
        # No domain may carry a claim. The only thing present is the explicit
        # liveness marker, which is an absence and cites no events.
        for name, domain in payload["state"]["domains"].items():
            self.assertIn(domain["status"], ("UNAVAILABLE", "UNKNOWN"), name)
            self.assertIsNone(domain["value"])
            self.assertEqual(domain["source_event_ids"], [])
        self.assertEqual(payload["state"]["version"], 0)
        self.assertEqual(payload["graph"]["edges"], [])


class DocumentationConsistencyTests(unittest.TestCase):
    """The docs must not drift into claiming things the code does not do.

    Documentation in a research project is evidence, and evidence that has
    drifted from the instrument is worse than none. These are cheap structural
    checks, not a full link checker.
    """

    def root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def read(self, relative: str) -> str:
        return (self.root() / relative).read_text(encoding="utf-8")

    def test_required_documents_exist(self) -> None:
        for relative in (
            "docs/observatory.md",
            "docs/observability-principles.md",
            "docs/cognitive-state-model.md",
            "docs/observatory-api.md",
            "docs/decisions/ADR-007-cognitive-observatory.md",
        ):
            with self.subTest(document=relative):
                self.assertTrue((self.root() / relative).is_file(), f"{relative} is missing")

    def test_schema_versions_in_docs_match_the_code(self) -> None:
        from observatory.model import STATE_SCHEMA
        from observatory.snapshot import SNAPSHOT_SCHEMA

        self.assertIn(STATE_SCHEMA, self.read("docs/cognitive-state-model.md"))
        self.assertIn(STATE_SCHEMA, self.read("docs/observatory-api.md"))
        self.assertIn(SNAPSHOT_SCHEMA, self.read("docs/observatory-api.md"))

    def test_no_subject_wording_is_consistent(self) -> None:
        from observatory.subject import NO_SUBJECT_BANNER, NO_SUBJECT_DETAIL

        for relative in ("README.md", "docs/observatory.md"):
            with self.subTest(document=relative):
                text = self.read(relative)
                self.assertIn(NO_SUBJECT_BANNER, text)

        # The detail line is the CLI's, so it belongs in the CLI docs.
        self.assertIn(NO_SUBJECT_DETAIL, self.read("docs/observatory-api.md"))

    def test_pyproject_declares_the_package_and_entry_point(self) -> None:
        import tomllib

        with open(self.root() / "pyproject.toml", "rb") as handle:
            config = tomllib.load(handle)
        self.assertIn("observatory", config["tool"]["setuptools"]["packages"])
        self.assertEqual(
            config["project"]["scripts"]["babylab-observatory"], "observatory.cli:main"
        )

    def test_runtime_dependencies_remain_empty(self) -> None:
        # ADR-002. The Observatory must not have quietly introduced a framework.
        import tomllib

        with open(self.root() / "pyproject.toml", "rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(config["project"]["dependencies"], [])

    def test_layout_includes_the_observatory_package(self) -> None:
        from babylab.paths import CODE_DIRECTORIES, DIRECTORIES

        self.assertIn("observatory", CODE_DIRECTORIES)
        self.assertIn("observatory", DIRECTORIES)

    def test_research_log_records_milestone_002(self) -> None:
        text = self.read("research/experiment-log.md")
        self.assertIn("Milestone 002", text)
        self.assertIn("NO EXPERIMENTAL SUBJECT ATTACHED", text)


if __name__ == "__main__":
    unittest.main()
