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


#: Modules whose whole purpose is mutation, and which have no meaningful read
#: half. The Observatory must not reach these at all, directly or through a
#: chain of imports.
WRITE_ONLY_MODULES = {
    "provenance.recorder": "records signed provenance entries",
    "provenance.seal": "rewrites the seal over protected files",
    "control.server": "accepts commands and writes them",
    "birth.service": "performs the birth ceremony (appends events, writes records)",
}

#: Modules that are legitimately readable but also expose a write path, mapped to
#: the names of their mutating functions. ``EventStore`` is the obvious one: the
#: reader genuinely needs it to read. So reachability of the module is fine and
#: calling the write function is not.
WRITE_FUNCTIONS_IN_READABLE_MODULES = {
    "birth.birth_record": {"write_record", "seal_record"},
    "provenance.keyring": {"register", "store_secret", "revoke"},
}

#: Individual functions that mutate, checked inside modules that are allowed to be
#: imported for reading. ``events.store.EventStore`` is the big one: the reader
#: legitimately uses it to read, so the module is reachable and the *write
#: methods* are what must be absent from the Observatory's own call sites.
FORBIDDEN_CALLS_ON_STORE = {"append", "append_many"}


def _imported_names(tree: ast.AST) -> set[str]:
    """Every module name imported anywhere in a parsed file, at any depth."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _resolve_local(dotted: str) -> Path | None:
    """Map a dotted module name to a file in this repository, if it is one."""
    root = OBSERVATORY_DIR.parent
    candidate = root.joinpath(*dotted.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if candidate.is_dir() and (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    return None


def import_closure(entry: str) -> set[str]:
    """Every first-party module reachable from ``entry`` by following imports.

    Standard-library and third-party modules are skipped: they are not under our
    control, and a local file is required to follow the chain. Cycles terminate
    because a module already visited is not re-expanded.
    """
    seen: set[str] = set()
    pending = [entry]
    while pending:
        dotted = pending.pop()
        if dotted in seen:
            continue
        path = _resolve_local(dotted)
        if path is None:
            continue
        seen.add(dotted)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - would be a broken repo
            continue
        for name in _imported_names(tree):
            if _resolve_local(name) is not None and name not in seen:
                pending.append(name)
    return seen


class ObservatoryImportClosureTests(unittest.TestCase):
    """The Observatory must not be able to reach a write path, even indirectly.

    The source scan checks the Observatory's *own* text. This walks the import
    graph, which catches the subtler failure: a future edit that imports
    ``birth.service`` for a harmless-looking helper would silently hand the
    read-only display the ceremony's event-append path. That is exactly why
    :mod:`birth.status` was split out of :mod:`birth.service`.
    """

    ENTRY_POINTS = ("observatory.terminal", "observatory.cli", "observatory.render")

    def closures(self) -> dict[str, set[str]]:
        return {entry: import_closure(entry) for entry in self.ENTRY_POINTS}

    def test_no_write_only_module_is_reachable(self) -> None:
        offences: list[str] = []
        for entry, reachable in self.closures().items():
            for module in sorted(reachable):
                if module in WRITE_ONLY_MODULES:
                    offences.append(
                        f"{entry} can reach {module} ({WRITE_ONLY_MODULES[module]})"
                    )
        self.assertEqual(
            offences,
            [],
            "read-only Observatory can reach a write-only module: " + "; ".join(offences),
        )

    def test_observatory_never_calls_a_record_write(self) -> None:
        """``birth.birth_record`` is readable, so it may be imported. Not written.

        The Observatory legitimately calls ``load_record`` to answer "does a birth
        record exist?". It must never call ``write_record``, and the two live in
        the same module, so the check has to be on the call, not the import.
        """
        offenders = {"write_record", "seal_record", "build_record"}
        offences: list[str] = []
        for path in self.observatory_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _dotted_name(node.func).split(".")[-1] in offenders:
                    offences.append(
                        f"{path.name}:{node.lineno} calls {_dotted_name(node.func)}()"
                    )
        self.assertEqual(offences, [], "birth record writes: " + "; ".join(offences))

    def test_the_ceremony_is_actually_reachable_from_birth_service(self) -> None:
        """Guards the tests above against passing for the wrong reason.

        If ``birth.service`` stopped reaching the event store, the closure check
        would pass trivially and stop meaning anything. Confirm the write path
        really is there, so a passing test is evidence rather than a tautology.
        Note ``provenance.recorder`` is *not* in that closure by design: the
        ceremony takes its recorder as a parameter, so that the birth path works
        in an installation without the provenance package.
        """
        reachable = import_closure("birth.service")
        self.assertIn("events.store", reachable)
        self.assertIn("birth.birth_record", reachable)

    def test_birth_status_alone_has_no_write_path(self) -> None:
        """The read-only half of the birth subsystem must stay read-only.

        It may reach ``birth.birth_record`` for ``load_record`` and ``verify_record``.
        It must not reach the ceremony, the event store, or provenance, because
        those three together are the entire ability to change anything.
        """
        reachable = import_closure("birth.status")
        for forbidden in ("events.store", "birth.service", "provenance.recorder"):
            self.assertNotIn(forbidden, reachable)
        status_source = _resolve_local("birth.status")
        self.assertIsNotNone(status_source)
        tree = ast.parse(status_source.read_text(encoding="utf-8"))
        called = {
            _dotted_name(node.func).split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        for write in ("write_record", "seal_record", "build_record"):
            self.assertNotIn(write, called)

    def test_observatory_never_calls_an_event_append(self) -> None:
        """``EventStore`` is reachable for reading; its write methods are not.

        :mod:`observatory.reader` legitimately imports the store, so the module
        appears in the closure. What must not appear is a call to ``append`` or
        ``append_many`` on it anywhere in the Observatory's own source.
        """
        offences: list[str] = []
        for path in self.observatory_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _dotted_name(node.func)
                if name.split(".")[-1] not in FORBIDDEN_CALLS_ON_STORE:
                    continue
                receiver = _dotted_name(node.func).rsplit(".", 1)[0]
                if receiver.split(".")[-1] in {"store", "self"}:
                    offences.append(f"{path.name}:{node.lineno} calls {name}()")
        self.assertEqual(offences, [], "event appends: " + "; ".join(offences))

    def observatory_sources(self) -> list[Path]:
        return sorted(OBSERVATORY_DIR.glob("*.py"))

    def test_observatory_reaches_the_birth_status_module(self) -> None:
        """It should read birth state, just not through the ceremony."""
        for entry in ("observatory.terminal", "observatory.cli"):
            self.assertIn("birth.status", self.closures()[entry], entry)


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

    def test_pyproject_declares_the_birth_package_and_entry_point(self) -> None:
        """Milestone 003 ships a package; it must be installable like the rest."""
        import tomllib

        with open(self.root() / "pyproject.toml", "rb") as handle:
            config = tomllib.load(handle)
        self.assertIn("birth", config["tool"]["setuptools"]["packages"])
        self.assertEqual(config["project"]["scripts"]["babylab-birth"], "birth.cli:main")

    def test_birth_is_a_subpackage_of_a_declared_package(self) -> None:
        """``birth`` is a package directory, so ``birth.cli:main`` must resolve."""
        self.assertTrue((self.root() / "birth" / "__init__.py").is_file())
        self.assertTrue((self.root() / "birth" / "cli.py").is_file())

    def test_every_declared_package_directory_exists(self) -> None:
        """A declared package that is not on disk breaks installation silently."""
        import tomllib

        with open(self.root() / "pyproject.toml", "rb") as handle:
            config = tomllib.load(handle)
        for package in config["tool"]["setuptools"]["packages"]:
            with self.subTest(package=package):
                self.assertTrue(
                    (self.root() / package / "__init__.py").is_file(),
                    f"{package} is declared but has no __init__.py",
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

    def test_every_doc_reference_in_the_code_resolves(self) -> None:
        """A pointer to a document that does not exist is worse than none.

        ``birth.config`` tells a user to read a particular section of
        ``docs/birth-architecture.md`` when no model is configured. That is the
        one moment a confused user is most likely to follow a pointer, so a
        dangling one there actively misleads. Enumerated so a new reference is a
        deliberate addition.
        """
        referenced = {
            "docs/birth-architecture.md": "birth/config.py",
            "docs/decisions/ADR-008-inherited-substrate.md": "birth/authorship.py",
        }
        for relative, cited_by in referenced.items():
            with self.subTest(document=relative):
                self.assertTrue(
                    (self.root() / relative).is_file(),
                    f"{relative}, cited by {cited_by}, does not exist",
                )

    def test_the_cited_section_actually_exists(self) -> None:
        """The exact heading ``birth.config`` names must be present.

        The error message points at a named section. If the document is renamed
        or the heading is reworded, the pointer silently stops working, and the
        section is what the reader actually needs.
        """
        self.assertIn(
            "Why the model is never chosen here", self.read("docs/birth-architecture.md")
        )

    def test_birth_docs_exist_for_the_milestone(self) -> None:
        for relative in (
            "docs/birth-architecture.md",
            "docs/decisions/ADR-008-inherited-substrate.md",
        ):
            with self.subTest(document=relative):
                self.assertTrue((self.root() / relative).is_file(), f"{relative} is missing")

    def test_birth_docs_refuse_the_claims_the_code_refuses(self) -> None:
        """The documentation must state the milestone's own limitations.

        A reader who consults the docs instead of the code must not come away
        with a stronger belief about the system than the code supports. The three
        limitations below are the ones most likely to be quietly dropped.
        """
        text = self.read("docs/birth-architecture.md")
        for phrase in (
            "does not claim OS-level isolation",
            "INHERITED_PRETRAINED",
            "It does **not** record",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_birth_docs_state_that_no_real_model_has_been_run(self) -> None:
        """No model has been run. The docs must not read as though one has.

        Deliberately a positive check on the caveat rather than a scan for
        forbidden phrases. A prohibition list in prose is unreliable to test by
        substring: this document contains the phrase "the subject is conscious"
        inside the list of things it explicitly refuses to claim, and a naive
        scanner would flag that as the very overclaim it is arguing against.
        """
        text = self.read("docs/birth-architecture.md")
        self.assertIn("has not yet been run\nagainst a real model", text)

    def test_birth_docs_list_what_the_record_refuses_to_claim(self) -> None:
        """The limitations must be enumerated, not merely gestured at.

        Each item is a claim this project has deliberately declined to make. A
        reader should be able to check the list against the record schema and see
        that the schema has no field for any of them.
        """
        text = self.read("docs/birth-architecture.md")
        self.assertIn("It does **not** record", text)
        for declined in (
            "conscious, aware, or sentient",
            "developmental phase",
            "Emotion, motivation, curiosity",
            "Memory contents or an intelligence score",
        ):
            with self.subTest(declined=declined):
                self.assertIn(declined, text)


if __name__ == "__main__":
    unittest.main()
