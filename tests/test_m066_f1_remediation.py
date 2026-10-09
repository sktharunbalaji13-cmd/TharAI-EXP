"""M066 -- F1 remediation tests: staging helpers must fail closed on defaults.

F1: ``deploy_artifact()`` and ``recover()`` in foundation/staging.py resolved
an omitted ``root=None`` to the canonical production ``subject_runtime`` tree
(``deploy`` would copy into it, ``recover`` would ``rmtree`` it).

The remediation: an omitted/falsy root raises CanonicalProductionMutation
before anything else, and an explicitly supplied root still passes through
_refuse_canonical_production. Tests use disposable temp trees plus refusal
cases that name production paths without ever mutating them (refusal always
precedes mutation).

CASES (per M066 Part 7):
A. deploy_artifact(root=None) -> fail closed before mutation.
B. recover(root=None) -> fail closed before mutation (even with confirm=True).
C. deploy_artifact(explicit disposable root) -> works (STAGED, hashes match).
D. recover(explicit disposable root) -> works (tree removed).
E. explicit canonical production root without authorization -> fail closed.
F. dot-dot-normalized alias of production -> fail closed.
G. malformed root ("") -> fail closed.
H. caller omits root entirely (no kwarg) -> fail closed, no production access.
I. recovery failure path on disposable -> no destructive production contact.
J. source-level: dangerous default-to-production semantics absent.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from foundation import staging as S


def _canon() -> Path:
    return Path(S._CANONICAL_T).resolve()


def _source_file(tmp_path: Path, name: str = "artifact.bin") -> Path:
    src = tmp_path / name
    src.write_bytes(b"m066-disposable-artifact\n")
    return src


def test_a_deploy_none_root_fails_closed(tmp_path: Path):
    src = _source_file(tmp_path)
    with pytest.raises(S.CanonicalProductionMutation):
        S.deploy_artifact("runtime", src, root=None, human_selected=True)


def test_b_recover_none_root_fails_closed_even_when_confirmed():
    with pytest.raises(S.CanonicalProductionMutation):
        S.recover(root=None, confirm=True)
    with pytest.raises(S.CanonicalProductionMutation):
        S.recover(root=None, confirm=False)


def test_c_deploy_explicit_disposable_root_works(tmp_path: Path):
    src = _source_file(tmp_path)
    dest_root = tmp_path / "staging"
    rec = S.deploy_artifact("runtime", src, root=dest_root, human_selected=True)
    assert rec.result == "STAGED", rec.detail
    assert rec.hashes_match
    assert Path(rec.staged_path).is_file()
    assert Path(rec.staged_path).read_bytes() == src.read_bytes()


def test_d_recover_explicit_disposable_root_works(tmp_path: Path):
    dest_root = tmp_path / "staging"
    tree = dest_root / "subject_runtime"
    (tree / "runtime").mkdir(parents=True)
    (tree / "runtime" / "x.bin").write_bytes(b"x")
    out = S.recover(root=dest_root, confirm=True)
    assert out["removed"] is True
    assert not tree.exists()
    assert dest_root.exists(), "only the staging tree is removed, not the given root"


def test_e_explicit_production_root_fails_closed(tmp_path: Path):
    src = _source_file(tmp_path)
    canon = _canon()
    with pytest.raises(S.CanonicalProductionMutation):
        S.deploy_artifact("runtime", src, root=canon, human_selected=True)
    with pytest.raises(S.CanonicalProductionMutation):
        S.recover(root=canon, confirm=True)
    assert canon.exists(), "production tree must still exist"


def test_f_dotdot_alias_of_production_fails_closed(tmp_path: Path):
    src = _source_file(tmp_path)
    canon = _canon()
    alias = canon / "runtime" / ".." / ".." / "subject_runtime"
    assert alias.resolve() == canon
    with pytest.raises(S.CanonicalProductionMutation):
        S.deploy_artifact("runtime", src, root=alias, human_selected=True)
    with pytest.raises(S.CanonicalProductionMutation):
        S.recover(root=alias, confirm=True)


def test_g_malformed_empty_root_fails_closed(tmp_path: Path):
    src = _source_file(tmp_path)
    with pytest.raises(S.CanonicalProductionMutation):
        S.deploy_artifact("runtime", src, root="", human_selected=True)
    with pytest.raises(S.CanonicalProductionMutation):
        S.recover(root="", confirm=True)


def test_h_omitted_root_kwarg_fails_closed(tmp_path: Path):
    src = _source_file(tmp_path)
    with pytest.raises(S.CanonicalProductionMutation):
        S.deploy_artifact("runtime", src, human_selected=True)
    with pytest.raises(S.CanonicalProductionMutation):
        S.recover(confirm=True)


def test_i_recovery_failure_paths_stay_disposable(tmp_path: Path):
    dest_root = tmp_path / "staging"
    out = S.recover(root=dest_root, confirm=False)
    assert out["removed"] is False
    out = S.recover(root=dest_root / "absent", confirm=True)
    assert out["removed"] is False
    assert _canon().exists()


def test_j_no_bare_default_resolution_in_dangerous_functions():
    for name in ("deploy_artifact", "recover"):
        source = inspect.getsource(getattr(S, name))
        assert "_refuse_canonical_production" in source, name
        assert "staging_root(root)" in source, name
    deploy_src = inspect.getsource(S.deploy_artifact)
    recover_src = inspect.getsource(S.recover)
    assert "if not root" in deploy_src
    assert "if not root" in recover_src
    assert "CanonicalProductionMutation" in deploy_src
    assert "CanonicalProductionMutation" in recover_src
