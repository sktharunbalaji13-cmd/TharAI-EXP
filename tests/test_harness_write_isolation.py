"""Negative regression tests for the test-harness write isolation.

An M015/M016 test run destroyed the production staging boundary. The mechanism was
NOT ``apply_boundary()`` -- audit established it is called exactly once, from
``test_staging_boundary.py``, with ``tmp_path``. The real mechanism was that test
fixtures and the subject probe were pointed at production paths, and the probe
runs as operator, so it created, renamed and deleted objects in production from a
child process the test never directly called ``mkdir`` on.

These tests pin the replacement: a central, write-scoped path policy that refuses
a repository path BEFORE any filesystem, ACL or subprocess work runs.

Production is currently DAMAGED, so these tests must not restore it and must not
"clean up" afterwards. The entire claim is that the mutation never happens. That is
verified by fingerprinting production read-only before and after a series of
deliberate attempts, and asserting the fingerprints are unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.path_policy import (  # noqa: E402
    MUTATING_PROBE_FLAGS,
    MUTATING_PROBE_OPTIONS,
    ProductionPathViolation,
    assert_test_write_path,
    assert_test_write_paths,
    canonical,
    is_inside_repo,
    read_production_for_verification,
    repo_root,
)

SUBJECT_RUNTIME = "subject_runtime"


# ---------------------------------------------------------------------------
# A. the canonical path policy
# ---------------------------------------------------------------------------

def test_repository_root_is_derived_not_hardcoded():
    """The policy must follow the checkout, not a user-specific literal."""
    root = repo_root()
    assert root.is_dir()
    assert root == REPO, (
        f"repo_root() resolved to {root}, expected {REPO}; the policy would be "
        f"checking the wrong tree"
    )


def test_a_prefix_sibling_is_not_inside_the_repository():
    """``C:\\dev\\TharAI-EXP-evil`` shares a string prefix and is NOT inside.

    This is the reason comparison is component-wise rather than ``startswith``. A
    prefix test would classify the sibling as repository-contained and refuse to
    mutate a perfectly disposable directory; worse, a future sibling named to
    dodge a check would be a way around it.
    """
    root = repo_root()
    sibling = root.with_name(root.name + "-evil")
    assert sibling != root
    assert str(sibling).lower().startswith(str(root).lower()), (
        "the fixture must actually share the string prefix for this test to mean "
        "anything"
    )
    assert is_inside_repo(sibling, root) is False


@pytest.mark.parametrize("rel", [
    "",
    SUBJECT_RUNTIME,
    f"{SUBJECT_RUNTIME}/runtime",
    f"{SUBJECT_RUNTIME}/model",
    f"{SUBJECT_RUNTIME}/config",
    f"{SUBJECT_RUNTIME}/a_future_path_that_does_not_exist",
    "foundation",
    "docs/evidence",
])
def test_repository_and_descendants_are_inside(rel):
    assert is_inside_repo(REPO / rel) is True


def test_a_nonexistent_descendant_is_classified():
    """A path that does not exist yet must still be refused.

    ``resolve()`` is non-strict on Windows, so the missing tail is normalised
    rather than raising. Without that, a test could validate a path, then create
    the directory inside production afterwards.
    """
    future = REPO / SUBJECT_RUNTIME / "not_yet" / "deeper" / "still_not_yet.exe"
    assert not future.exists()
    assert is_inside_repo(future) is True
    with pytest.raises(ProductionPathViolation):
        assert_test_write_path(future)


def test_dot_and_dotdot_are_normalised():
    """``..`` must not be a way out of, or back into, the repository."""
    inside = REPO / SUBJECT_RUNTIME / ".." / SUBJECT_RUNTIME / "config"
    assert is_inside_repo(inside) is True
    escaped = REPO / SUBJECT_RUNTIME / ".." / ".." / ".." / "etc"
    assert is_inside_repo(escaped) is False
    # And the canonical form is what the policy actually compares.
    assert str(canonical(inside)).lower().endswith("subject_runtime\\config")


def test_relative_paths_resolve_against_the_cwd():
    """A relative path must be classified, not waved through."""
    import os

    assert is_inside_repo("." if os.getcwd() == str(REPO) else SUBJECT_RUNTIME)


def test_case_insensitive_comparison_on_windows():
    """Windows paths compare case-insensitively; the policy must too."""
    if sys.platform != "win32":
        pytest.skip("Windows path semantics")
    shouted = REPO / SUBJECT_RUNTIME
    mixed = Path(str(shouted).upper())
    assert is_inside_repo(mixed) is True


def test_read_only_helper_permits_production():
    """Read-only production access stays permitted, and is named as such."""
    resolved = read_production_for_verification(REPO / SUBJECT_RUNTIME)
    assert resolved == canonical(REPO / SUBJECT_RUNTIME)
    # It grants reading only. The mutation guard still refuses the same path.
    with pytest.raises(ProductionPathViolation):
        assert_test_write_path(REPO / SUBJECT_RUNTIME)


# ---------------------------------------------------------------------------
# B. the mutation guard refuses repository paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "",
    SUBJECT_RUNTIME,
    f"{SUBJECT_RUNTIME}/runtime",
    f"{SUBJECT_RUNTIME}/model",
    f"{SUBJECT_RUNTIME}/config",
    f"{SUBJECT_RUNTIME}/future_dir",
    f"{SUBJECT_RUNTIME}/future_dir/deep.bin",
])
def test_mutation_guard_rejects_repository_paths(rel):
    with pytest.raises(ProductionPathViolation):
        assert_test_write_path(REPO / rel)


def test_violation_carries_diagnostic_evidence():
    """The refusal must be diagnosable without re-deriving the paths."""
    with pytest.raises(ProductionPathViolation) as excinfo:
        assert_test_write_path(REPO / SUBJECT_RUNTIME / "config",
                               what="fixture")
    violation = excinfo.value
    assert violation.supplied.endswith("config")
    assert violation.repository_root == str(canonical(REPO))
    assert "inside the repository" in violation.reason
    assert str(canonical(REPO / SUBJECT_RUNTIME / "config")) == violation.resolved


def test_repository_root_is_named_distinctly_from_a_descendant():
    """Refusing the root is worth distinguishing: it is a different mistake."""
    with pytest.raises(ProductionPathViolation) as excinfo:
        assert_test_write_path(REPO)
    assert "repository root itself" in excinfo.value.reason


def test_named_mapping_identifies_the_offending_argument():
    """With six paths, the refusal must say which one."""
    with pytest.raises(ProductionPathViolation) as excinfo:
        assert_test_write_paths({
            "scratch": Path("C:\\temp\\ok"),
            "delete_fixture": REPO / SUBJECT_RUNTIME / "config" / "target",
        })
    assert "delete_fixture" in str(excinfo.value)


def test_disposable_paths_are_authorised(tmp_path):
    """The guard must not be vacuous: real disposable state is allowed."""
    assert assert_test_write_path(tmp_path) == canonical(tmp_path)
    assert assert_test_write_path(tmp_path / "not_yet" / "deeper") == canonical(
        tmp_path / "not_yet" / "deeper")


# ---------------------------------------------------------------------------
# C. every mutation surface refuses before mutating
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_every_mutation_helper_refuses_production(tmp_path):
    """Each guarded helper must refuse, and refuse before doing any work."""
    from tests import guarded

    runtime = REPO / SUBJECT_RUNTIME / "runtime"
    config = REPO / SUBJECT_RUNTIME / "config"

    with pytest.raises(ProductionPathViolation):
        guarded.make_fixture_file(runtime)
    with pytest.raises(ProductionPathViolation):
        guarded.make_fixture_dir(config)
    with pytest.raises(ProductionPathViolation):
        guarded.remove_tree(REPO / SUBJECT_RUNTIME)
    with pytest.raises(ProductionPathViolation):
        guarded.guarded_probe_argv(scratch=config, staged=None, protected=None,
                                   workspace=tmp_path)
    with pytest.raises(ProductionPathViolation):
        guarded.guarded_probe_argv(scratch=tmp_path, staged=None,
                                   protected=None, workspace=tmp_path,
                                   delete_fixture=config)
    with pytest.raises(ProductionPathViolation):
        guarded.guarded_probe_argv(scratch=tmp_path, staged=None,
                                   protected=None, workspace=tmp_path,
                                   staging_root=runtime)
    with pytest.raises(ProductionPathViolation):
        guarded.guarded_probe_argv(
            scratch=tmp_path, staged=None, protected=None, workspace=tmp_path,
            acl_target=runtime / "m016_disposable_target.exe")
    with pytest.raises(ProductionPathViolation):
        guarded.apply_boundary_guarded(REPO)
    with pytest.raises(ProductionPathViolation):
        guarded.apply_subject_deny_guarded(REPO)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_probe_launch_is_refused_before_any_process_starts(tmp_path, monkeypatch):
    """A refused launch must not reach subprocess.run at all.

    The incident's mutations happened in a child process, so "the Python test did
    not mutate it" was true and irrelevant. Proving the process is never spawned
    is the point of guarding the argv.
    """
    from tests import guarded

    launched: list = []
    monkeypatch.setattr(guarded.subprocess, "run",
                        lambda *a, **k: launched.append(a) or None)
    with pytest.raises(ProductionPathViolation):
        guarded.run_probe_guarded(Path("probe.exe"),
                                  scratch=REPO / SUBJECT_RUNTIME / "config",
                                  staged=None, protected=None, workspace=tmp_path)
    assert launched == [], "the probe was launched despite a refused path"


def test_restore_dacls_guard_validates_the_snapshot(tmp_path):
    """A snapshot carrying repository paths must be refused."""
    from foundation.subject_deny import SubjectDenySnapshot
    from tests import guarded

    snapshot = SubjectDenySnapshot(captured_at="test", paths={
        str(REPO / SUBJECT_RUNTIME / "config"): {
            "mask": 0, "mask_hex": "0x0", "sddl": "D:", },
    })
    with pytest.raises(ProductionPathViolation):
        guarded.restore_dacls_guarded(snapshot, root=tmp_path)


# ---------------------------------------------------------------------------
# D. repository-wide audit
# ---------------------------------------------------------------------------

#: Test modules and how they are permitted to name production paths.
#:   read-only  -> verification assertions only
#:   disposable -> every mutation is under tmp_path
_PRODUCTION_REFERENCES = {
    "test_m016_launch.py": "read-only plus one disposable probe run",
    "test_boundary_harness.py": "read-only verification plus disposable harness",
    "test_staging_boundary.py": "read-only verification",
    "test_subject_runtime_staging.py": "read-only verification",
    "test_subject_boundary_run.py": "read-only verification",
    "test_subject_deny.py": "read-only verification",
    "test_subject_probe_measurement.py": "read-only verification",
    "test_m005_acl_recovery.py": "read-only verification",
}


def test_no_test_helpers_mutate_production_subject_runtime():
    """No test module may combine a production subject_runtime with a mutation.

    Checked by scanning for production paths near mutation calls, because a
    textual list of "dangerous" names alone would miss the pairing that actually
    caused the incident: a read-only-looking path expression feeding a helper
    that mutates.
    """
    offenders: list[str] = []
    for path in sorted((REPO / "tests").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if SUBJECT_RUNTIME not in source:
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            if SUBJECT_RUNTIME not in line:
                continue
            # A line naming production next to a filesystem or subprocess mutation.
            mutating = any(token in line for token in (
                ".mkdir(", ".write_bytes(", ".write_text(", "rmtree",
                ".unlink(", "icacls", "attrib", "subprocess.run",
            ))
            if mutating:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "test code mutates a production subject_runtime path:\n  "
        + "\n  ".join(offenders))


def test_no_test_launches_the_probe_with_a_production_mutating_path():
    """A production path may reach an argv string, never a launched process.

    Several tests build probe argv purely to assert on the string -- placeholder
    handling, absolute-path propagation -- and one of those names a production
    path. That is harmless: no process is started and the probe is not the thing
    holding the path. The invariant that matters is about LAUNCHES, because the
    incident's mutations happened inside a launched probe running as operator.

    So this scans for a production path and a subprocess launch in the same call
    expression, rather than banning the string.
    """
    offenders: list[str] = []
    # Match the production path EXPRESSION, not the bare word. Three things would
    # false-positive on a word match and all three exist in this tree: docstrings
    # describing the incident, and `tmp_path / "subject_runtime"` disposable trees
    # that deliberately reuse the production shape.
    production = ('REPO / "' + SUBJECT_RUNTIME + '"',
                  'REPO / \'' + SUBJECT_RUNTIME + '\'',
                  'REPO / f"' + SUBJECT_RUNTIME,
                  'REPO_ROOT / "' + SUBJECT_RUNTIME + '"',
                  'REPO_ROOT / f"' + SUBJECT_RUNTIME)
    for path in sorted((REPO / "tests").glob("*.py")):
        if path.name == "test_harness_write_isolation.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''", "*")):
                continue      # a comment or docstring line cannot launch anything
            if not any(token in line for token in production):
                continue
            # Look ahead over the whole call expression, which may span lines.
            window = " ".join(lines[lineno:lineno + 12])
            launches = ("subprocess.run", "run_probe_guarded", "Popen",
                        "os.system", "check_output")
            if any(token in window for token in launches):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, (
        "a test appears to launch a process while naming a production path:\n  "
        + "\n  ".join(offenders))


def test_mutating_probe_option_names_match_the_builder_keywords():
    """The guard's option list must use the BUILDER's keyword spelling.

    This is not pedantry. The list previously carried the CLI flag spelling
    (``--delete-fixture``) while the guard looks the values up by keyword name
    (``delete_fixture``), so every lookup missed and the guard skipped every probe
    option while still appearing to check them. A guard that silently passes is
    worse than no guard, because it is mistaken for a control.
    """
    from foundation.boundary_test import build_probe_argv

    import inspect

    signature = set(inspect.signature(build_probe_argv).parameters)
    for name in MUTATING_PROBE_OPTIONS:
        assert name in signature, (
            f"path_policy.MUTATING_PROBE_OPTIONS names {name!r}, which is not a "
            f"build_probe_argv parameter; the guard would silently skip it"
        )
    # And the CLI spelling must still be recognised as the same option.
    for flag, name in zip(MUTATING_PROBE_FLAGS, MUTATING_PROBE_OPTIONS):
        assert flag == "--" + name.replace("_", "-")


# ---------------------------------------------------------------------------
# E. production immutability across deliberate attempts
# ---------------------------------------------------------------------------

def _production_fingerprint() -> dict:
    """Read-only canonical fingerprint of the production staging tree.

    Deliberately independent of the probe and of foundation.subject_deny: this is
    a second opinion, so a bug in one reader cannot hide a change from the other.
    """
    base = REPO / SUBJECT_RUNTIME
    entries: list[str] = []
    if base.exists():
        for path in [base, *sorted(base.rglob("*"))]:
            try:
                sddl = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     f"(Get-Acl -LiteralPath '{path}').GetSecurityDescriptorSddlForm("
                     "[System.Security.AccessControl.AccessControlSections]::Access)"],
                    capture_output=True, text=True, shell=False, timeout=120,
                    stdin=subprocess.DEVNULL).stdout.strip()
            except Exception as exc:                      # noqa: BLE001
                sddl = f"UNREADABLE:{exc.__class__.__name__}"
            entries.append(f"{path.relative_to(base)}|{path.is_dir()}|{sddl}")
    return {"paths": sorted(entries), "count": len(entries)}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_deliberate_production_mutation_attempts_change_nothing():
    """Attempt production mutation through every surface; change nothing.

    Production is damaged and must NOT be repaired here. The claim under test is
    that the attempt is refused BEFORE the mutation, so there is nothing to clean
    up afterwards -- and this test deliberately does no cleanup, because a cleanup
    step would be indistinguishable from the very repair we must not perform.
    """
    from tests import guarded

    before = _production_fingerprint()
    attempts = 0

    for target in (REPO, REPO / SUBJECT_RUNTIME,
                   REPO / SUBJECT_RUNTIME / "runtime",
                   REPO / SUBJECT_RUNTIME / "model",
                   REPO / SUBJECT_RUNTIME / "config"):
        for helper, args, kwargs in (
            (guarded.make_fixture_file, (target,), {}),
            (guarded.make_fixture_dir, (target,), {}),
            (guarded.remove_tree, (target,), {}),
            (guarded.apply_boundary_guarded, (target,), {}),
            (guarded.apply_subject_deny_guarded, (target,), {}),
            (guarded.guarded_probe_argv,
             (), {"scratch": target, "staged": None, "protected": None,
                  "workspace": REPO}),
        ):
            with pytest.raises(ProductionPathViolation):
                helper(*args, **kwargs)
            attempts += 1

    after = _production_fingerprint()
    assert attempts == 30, f"expected 30 refusal attempts, made {attempts}"
    assert after == before, (
        "production changed while every mutation attempt was supposed to be "
        f"refused:\n  before: {before}\n  after:  {after}"
    )
    assert after["count"] == before["count"], (
        "a production path appeared or disappeared during refused mutations")


def test_read_only_production_checks_are_preserved():
    """The checks that DETECTED the incident must still exist.

    Migrating them to a recorded snapshot was considered and deferred. They are
    the alarm: if they go, the next clobber is silent.
    """
    harness = (REPO / "tests" / "test_boundary_harness.py").read_text(encoding="utf-8")
    launch = (REPO / "tests" / "test_m016_launch.py").read_text(encoding="utf-8")
    assert "def test_m015_boundary_is_untouched" in harness, (
        "the M015 read-only regression check must remain")
    assert "def test_m015_boundary_still_verifies_after_m016_work" in launch, (
        "the M016 read-only regression check must remain")
    assert "def test_no_runtime_or_model_is_staged" in harness


# ---------------------------------------------------------------------------
# F. every mutation-capable probe argument, including the three slots that were
#    previously misclassified READ_ONLY.
#
#    Each case proves the refusal happens BEFORE any process is launched, by
#    monkeypatching subprocess.run to raise if it is reached. The real probe is
#    never invoked against production -- demonstrating a refusal must not require
#    performing the thing being refused.
# ---------------------------------------------------------------------------

def _exploding_subprocess(monkeypatch):
    """Replace subprocess.run with a tripwire that fails if a process is spawned."""
    from tests import guarded

    def _boom(*args, **kwargs):
        raise AssertionError(
            "subprocess.run was reached: a refused probe argument must be caught "
            "before launch, not inside the child process"
        )

    monkeypatch.setattr(guarded.subprocess, "run", _boom)


def _argv(tmp_path, **overrides):
    """A guarded argv with disposable defaults, overridden per case."""
    from tests import guarded

    base = {
        "scratch": tmp_path / "scratch",
        "staged": tmp_path / "runtime" / "disposable.exe",
        "protected": tmp_path / "config",
        "workspace": tmp_path / "workspace",
    }
    base.update(overrides)
    return guarded.guarded_probe_argv(**base)


@pytest.mark.parametrize("arg,value", [
    ("staged",    "subject_runtime/runtime/probe.exe"),
    ("protected", "subject_runtime/config"),
    ("workspace", "subject_runtime/runtime"),
    ("scratch",   "subject_runtime/config"),
])
def test_write_capable_probe_slots_refuse_production_before_launch(
        tmp_path, monkeypatch, arg, value):
    """The three previously READ_ONLY slots now refuse, before any launch."""
    from tests import guarded

    _exploding_subprocess(monkeypatch)
    production = REPO / value
    defaults = _disposable_defaults(tmp_path)
    defaults[arg] = production
    with pytest.raises(ProductionPathViolation):
        guarded.run_probe_guarded(Path("probe.exe"), **defaults)


def _disposable_defaults(tmp_path):
    return {
        "scratch": tmp_path / "scratch",
        "staged": tmp_path / "runtime" / "disposable.exe",
        "protected": tmp_path / "config",
        "workspace": tmp_path / "workspace",
    }


def test_write_capable_probe_options_refuse_production_before_launch(tmp_path, monkeypatch):
    """staging_root / acl_target / delete_fixture refuse, before any launch."""
    from tests import guarded

    _exploding_subprocess(monkeypatch)
    runtime = REPO / SUBJECT_RUNTIME / "runtime"
    for option, value in (
        ("staging_root", runtime),
        ("acl_target", runtime / "probe.exe"),
        ("delete_fixture", REPO / SUBJECT_RUNTIME / "config" / "del"),
    ):
        with pytest.raises(ProductionPathViolation):
            guarded.run_probe_guarded(Path("probe.exe"),
                                      **{option: value},
                                      **_disposable_defaults(tmp_path))


@pytest.mark.parametrize("description,build", [
    ("nonexistent production descendant",
     lambda tmp_path, repo: repo / "subject_runtime" / "model" / "future_dir"),
    ("nonexistent nested production descendant",
     lambda tmp_path, repo: repo / "subject_runtime" / "runtime" / "a" / "b" / "c.exe"),
    ("upper-case production descendant",
     lambda tmp_path, repo: Path(str(repo).upper()) / "subject_runtime" / "config"),
    ("mixed-case production descendant",
     lambda tmp_path, repo: Path(str(repo)[:6].upper() + str(repo)[6:].lower())
     / "subject_runtime"),
])
def test_future_and_case_variant_production_paths_refuse(tmp_path, monkeypatch,
                                                          description, build):
    """Nonexistent and case-variant production paths are refused too.

    resolve() is non-strict, so a path that does not exist yet still canonicalises
    -- otherwise a test could create a new directory inside production after
    validation.
    """
    from tests import guarded

    _exploding_subprocess(monkeypatch)
    value = build(tmp_path, REPO)
    for slot in ("scratch", "staged", "protected", "workspace"):
        with pytest.raises(ProductionPathViolation):
            _argv(tmp_path, **{slot: value})


def test_relative_production_descendant_is_refused(tmp_path, monkeypatch):
    """A relative path resolving inside production is refused.

    ``canonical()`` resolves a relative path against the process CWD, so the test
    chdirs to the repository's parent: ``TharAI-EXP/subject_runtime/config`` is then
    a relative string that resolves straight into production.
    """
    from tests import guarded

    _exploding_subprocess(monkeypatch)
    monkeypatch.chdir(REPO.parent)
    rel = os.path.join(REPO.name, SUBJECT_RUNTIME, "config")
    assert not Path(rel).is_absolute()
    for slot in ("scratch", "staged", "protected", "workspace"):
        with pytest.raises(ProductionPathViolation):
            _argv(tmp_path, **{slot: rel})


def test_prefix_similar_external_path_is_accepted(tmp_path, monkeypatch):
    """``TharAI-EXP-evil`` shares a string prefix and must NOT be refused.

    The guard compares path COMPONENTS, not raw strings. If it compared prefixes it
    would refuse this path -- and a guard that refuses legitimate external paths
    invites a bypass by renaming a disposable directory.
    """
    external = REPO.parent / (REPO.name + "-evil")
    argv = _argv(tmp_path, scratch=external / "scratch")
    assert any(str(external) in part for part in argv)


def test_disposable_paths_still_build_an_argv(tmp_path):
    """Sanity: the guard is not simply refusing everything."""
    argv = _argv(tmp_path, staging_root=tmp_path / "root",
                 acl_target=tmp_path / "a.exe",
                 delete_fixture=tmp_path / "del",
                 read_file=tmp_path / "r.txt",
                 traverse=tmp_path / "traverse")
    assert argv[0] == str(tmp_path / "scratch")
    assert any(a.startswith("--read-file=") for a in argv)