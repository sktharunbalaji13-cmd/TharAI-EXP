"""Tests for the PE import reader and the staging-design invariants.

Two groups.

The PE reader is real code that read a real import table, so it is tested against
real binaries -- and against deliberately malformed input, because a parser that
raises ``struct.error`` on a truncated file is a parser that will eventually meet
one.

The staging-design tests assert the *design constraints* as executable statements.
They deliberately do not test a staging directory, because none exists: creating
one is the implementation this investigation was told not to perform. What they
do assert is that the design's stated preconditions still hold -- in particular
that the parent ACL has not quietly changed into something that would hand the
subject write, which is the failure mode the whole design is built to avoid.

**No test here claims `BABY_AI_TEST` execution.** Subject-side read/write/execute
behaviour is `NOT_TESTABLE` until a human performs a launch.
"""

from __future__ import annotations

import ast
import struct
from pathlib import Path

import pytest

from foundation.pe_inspect import (
    PEError,
    dependency_report,
    imported_dlls,
    imported_symbols,
    machine_architecture,
)

REPO = Path(__file__).resolve().parents[1]

#: A real Windows binary, always present, used so the parser is tested against
#: something genuinely executable rather than a fixture.
SYSTEM32 = Path(r"C:\Windows\System32")
KERNEL32 = SYSTEM32 / "kernel32.dll"

#: The runtime M010 reported as unselected. Used read-only, and never selected.
UNSELECTED_RUNTIME_DIR = Path(
    r"C:\Users\k.tharun balaji\.docker\bin\inference")


# ---------------------------------------------------------------------------
# The PE reader
# ---------------------------------------------------------------------------

class TestPEReader:
    def test_it_reads_a_real_windows_binary(self):
        assert imported_dlls(KERNEL32), "expected kernel32.dll to import something"

    def test_it_reports_the_architecture(self):
        architecture = machine_architecture(KERNEL32.read_bytes())
        assert architecture in {"x64", "x86", "arm64"}

    def test_it_is_deterministic(self):
        assert imported_dlls(KERNEL32) == imported_dlls(KERNEL32)

    def test_it_returns_a_list_not_a_set(self):
        """Order matters for a diff between two staged copies."""
        assert isinstance(imported_dlls(KERNEL32), list)

    def test_a_non_pe_file_is_refused(self, tmp_path):
        target = tmp_path / "not.exe"
        target.write_bytes(b"this is plainly not an executable")
        with pytest.raises(PEError):
            imported_dlls(target)

    def test_a_truncated_pe_is_refused_not_crashed(self, tmp_path):
        """A truncated file must raise PEError, never struct.error.

        Real staged artifacts can plausibly arrive truncated -- a partial copy, a
        full disk, an interrupted download -- and a parser that raises
        ``struct.error`` on one of those reports the wrong problem entirely.

        Truncating *inside* the section table is the interesting case: the MZ and
        PE signatures are intact, so the file looks valid until the reader walks
        off the end. Cutoff sizes are swept rather than guessed, because the
        interesting failures happen at different offsets.
        """
        data = KERNEL32.read_bytes()
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        cutoffs = [0x40, 0x100, pe_offset, pe_offset + 24, pe_offset + 200,
                   len(data) // 2]
        for index, cutoff in enumerate(cutoffs):
            target = tmp_path / f"truncated{index}.exe"
            target.write_bytes(data[:cutoff])
            with pytest.raises(PEError):
                imported_dlls(target)

    def test_a_pe_with_a_corrupt_header_is_refused(self, tmp_path):
        data = bytearray(KERNEL32.read_bytes())
        offset = struct.unpack_from("<I", data, 0x3C)[0]
        data[offset:offset + 4] = b"XXXX"
        target = tmp_path / "corrupt.exe"
        target.write_bytes(bytes(data))
        with pytest.raises(PEError):
            imported_dlls(target)

    def test_an_empty_file_is_refused(self, tmp_path):
        target = tmp_path / "empty.exe"
        target.write_bytes(b"")
        with pytest.raises(PEError):
            imported_dlls(target)

    def test_symbols_are_reported_per_dll(self):
        pairs = imported_symbols(KERNEL32)
        assert pairs, "expected at least one imported symbol"
        assert all(isinstance(dll, str) and isinstance(sym, str)
                   for dll, sym in pairs)


class TestDependencyReport:
    def test_it_distinguishes_local_from_system_imports(self):
        report = dependency_report(KERNEL32, SYSTEM32)
        assert report["import_count"] == len(report["imports"])
        assert report["architecture"] in {"x64", "x86", "arm64"}

    def test_a_report_on_a_missing_search_dir_still_lists_imports(self):
        report = dependency_report(KERNEL32, Path(r"C:\nonexistent"))
        assert report["imports"], "imports should be read from the file itself"
        # With nothing beside it, everything is "not in the search dir", which is
        # the honest answer rather than an error.
        assert report["satisfiable_from_search_dir"] == []

    @pytest.mark.skipif(
        not UNSELECTED_RUNTIME_DIR.is_dir(),
        reason="the reported llama.cpp runtime is not present on this host",
    )
    def test_the_unselected_runtime_closure_is_the_direct_imports(self):
        """Verifies the design's §3 closure claim, not a selection.

        The runtime is reported, never chosen. This confirms what the design
        document states: five local files, with the VC++ runtime already
        present system-wide.
        """
        executable = UNSELECTED_RUNTIME_DIR / "llama-server.exe"
        report = dependency_report(executable, UNSELECTED_RUNTIME_DIR)
        local = set(report["satisfiable_from_search_dir"])
        assert {"llama.dll", "ggml.dll", "ggml-base.dll", "mtmd.dll"} <= local
        # The VC runtime resolves from System32, so staging it is unnecessary.
        assert "MSVCP140.dll" not in local
        assert (SYSTEM32 / "MSVCP140.dll").is_file()
        assert (SYSTEM32 / "VCRUNTIME140.dll").is_file()


# ---------------------------------------------------------------------------
# The staging design's preconditions
# ---------------------------------------------------------------------------

class TestStagingPreconditions:
    """Assertions about the host that the design depends on.

    None of these tests the staging area, because none exists. They test the
    premises. If the parent directory's ACL is ever loosened in a way that hands
    the subject write, the design's central requirement -- break inheritance
    explicitly -- is what prevents a breach, and this test is what notices the
    change.
    """

    @pytest.fixture(scope="class")
    def parent_acl(self) -> str:
        import subprocess

        result = subprocess.run(
            ["icacls", str(REPO)], capture_output=True, text=True, timeout=60,
            shell=False, stdin=subprocess.DEVNULL,
        )
        return result.stdout or ""

    def test_the_parent_grants_authenticated_users_modify(self, parent_acl):
        """The reason the design must break inheritance.

        If this ever stops being true the design could be simplified, and the
        test should fail so the simplification is a deliberate decision.
        """
        assert "Authenticated Users:(I)(M)" in parent_acl

    def test_the_parent_grants_users_read_execute(self, parent_acl):
        assert "BUILTIN\\Users:(I)(RX)" in parent_acl

    def test_the_subject_account_has_no_ace_at_the_parent(self, parent_acl):
        """No explicit grant: the subject's access comes from Authenticated
        Users, which is exactly why it carries Modify."""
        assert "BABY_AI_TEST" not in parent_acl

    def test_the_subject_account_is_authenticated(self):
        """The premise behind all of the above.

        ``BABY_AI_TEST`` is enabled and has logged on, so it holds
        ``NT AUTHORITY\\Authenticated Users`` and therefore Modify.
        """
        from foundation.host_readiness import survey_account

        survey = survey_account()
        assert survey["read_failed"] is False
        assert survey["sid_matches"] is True
        assert str(survey["observed"]["enabled"]).lower() == "true"
        assert survey["observed"]["last_logon"], "no recorded logon"

    def test_no_runtime_or_model_was_staged(self):
        """The staging tree holds no runtime and no model.

        M015 creates the boundary; it does not select or copy anything into it.
        The single permitted exception is the *empty* disposable target the M016
        boundary test operates on -- an empty file carries no model and no
        program, and exists so the OS can be asked a question about the ACL.

        What must never appear is a real runtime, a model, or any llama binary,
        anywhere in the repository.
        """
        permitted = {"m016_disposable_target.exe", "m016_subjectrun_fixture.exe"}
        staging = REPO / "subject_runtime"
        if staging.exists():
            assert list(staging.rglob("*")), "the boundary should have subtrees"
            for item in staging.rglob("*"):
                if not item.is_file():
                    continue
                assert item.name in permitted, \
                    f"artifact staged without human selection: {item}"
                assert item.stat().st_size == 0, \
                    f"the disposable target must be empty: {item}"

    def test_no_artifact_was_copied_into_the_repository(self):
        for name in ("llama-server.exe", "llama.dll", "ggml.dll",
                     "mtmd.dll", "ggml-base.dll"):
            assert not list(REPO.rglob(name)), f"{name} was copied into the repo"

    def test_no_gguf_exists_in_the_repository(self):
        assert not list(REPO.rglob("*.gguf"))


# ---------------------------------------------------------------------------
# The design document's own claims
# ---------------------------------------------------------------------------

class TestDesignDocument:
    @pytest.fixture(scope="class")
    def design(self) -> str:
        return (REPO / "docs" / "subject-runtime-staging-design.md").read_text(
            encoding="utf-8")

    def test_every_required_section_is_present(self, design):
        for heading in (
            "Problem",
            "Current ACL findings",
            "Runtime dependency analysis",
            "Python is not a subject capability",
            "Proposed staging boundary",
            "Model placement",
            "Immutability",
            "M005 preservation",
            "Empirical verification plan",
            "Copy versus move",
            "Security risks",
            "Remaining human decisions",
        ):
            assert heading in design, heading

    def test_claims_are_tagged(self, design):
        """OBSERVED / DERIVED / PROPOSED / NOT_TESTABLE, as the brief required.

        Checked on the word rather than the bold span, because a design that tags
        its claims inconsistently would defeat the point of tagging them.
        """
        for tag in ("OBSERVED", "DERIVED", "PROPOSED", "NOT_TESTABLE"):
            assert design.count(tag) >= 5, tag

    def test_it_makes_no_selection_claim(self, design):
        """The design must not read as having chosen a runtime."""
        assert "unselected" in design.lower()
        assert "no model has been selected" in design.lower()
        assert "none has been" in design.lower()

    def test_it_records_the_previous_commit(self, design):
        """The design must be traceable to the finding that prompted it."""
        assert "e766f85" in design or "commit" in design.lower()

    def test_it_lists_the_unrelated_working_tree_state(self, design):
        for item in (".agents/", ".claude/", ".claude-flow/", ".swarm/",
                     ".mcp.json", "CLAUDE.md"):
            assert item in design, item

    def test_it_warns_that_model_confidentiality_is_not_provided(self, design):
        """A boundary claim that is quietly wrong is worse than no claim.

        The design must state plainly that the subject can read the model --
        because it must -- and must not let a reader infer confidentiality it
        cannot provide.
        """
        assert "the model is not\nsecret from the subject" in design or \
            "the model is not secret from the subject" in design
        assert "confidentiality" in design.lower()
        assert "not a property this boundary provides" in design

    def test_it_records_that_acl_cannot_enforce_no_network(self, design):
        assert "No ACL prevents that" in design


# ---------------------------------------------------------------------------
# Nothing was changed
# ---------------------------------------------------------------------------

class TestNothingWasChanged:
    def test_the_m005_boundary_is_intact(self):
        denied = set()
        for directory in REPO.rglob("*"):
            if not directory.is_dir() or ".git" in directory.parts:
                continue
            import subprocess

            result = subprocess.run(
                ["icacls", str(directory)], capture_output=True, text=True,
                timeout=30, shell=False, stdin=subprocess.DEVNULL,
            )
            for line in (result.stdout or "").splitlines():
                if "BABY_AI_TEST" in line and "(DENY)" in line:
                    denied.add(directory.relative_to(REPO).as_posix())
        expected = {
            "docs", "human_control", "research",
            "docs/decisions", "docs/evidence",
            "human_control/provenance", "human_control/research_records",
            "human_control/security", "human_control/snapshots",
            "human_control/provenance/seals", "human_control/security/keys",
            "human_control/security/keys/private",
            "var/events", "var/provenance",
        }
        assert expected <= denied, f"missing: {sorted(expected - denied)}"

    def test_no_birth_artifact_exists(self):
        from babylab.paths import default_paths

        paths = default_paths()
        assert not (paths.birth_records / "BIRTH.json").exists()
        assert not paths.model_dir.exists()

    def test_the_event_log_is_unchanged(self):
        from babylab.clock import Clock
        from babylab.paths import default_paths
        from events.store import EventStore

        store = EventStore(default_paths().event_store, clock=Clock())
        assert store.count() == 20
        assert bool(store.verify_chain().intact)

    def test_the_pe_reader_cannot_execute_anything(self):
        """It reads headers. It must not be able to load an image."""
        source = (REPO / "foundation" / "pe_inspect.py").read_text(encoding="utf-8")
        called: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
        for forbidden in ("ctypes.WinDLL", "ctypes.cdll", "LoadLibrary",
                          "subprocess", "os.system"):
            assert forbidden not in called, forbidden