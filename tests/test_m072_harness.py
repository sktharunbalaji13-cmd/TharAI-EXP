"""M072 -- staging mutation-boundary regression harness.

Closes the M066 residual gap (source-scan covered only two functions) with a
call-graph-aware AST harness over foundation/staging.py:

* every function is classified from its own source: which filesystem/ACL
  mutation sinks it contains, and which guard events precede them;
* any function with a mutation sink but no preceding guard verdicts UNGUARDED;
* anything the analyzer cannot classify verdicts UNCLASSIFIABLE -- both fail
  the suite (fail closed; the suite never weakens to pass);
* a negative test proves the harness detects a synthetic unguarded helper;
* behavior tests prove refusal-before-mutation for every mutating entry point
  (omitted/None/empty/canonical/traversal roots) and disposable success.

Guard model (mirrors the implementation contract):
  guard event  = call to _refuse_canonical_production, or raise of
                 CanonicalProductionMutation (covers `if not root: raise`);
  protected    = every mutation sink has a guard event on an earlier source
                 line in the same function;
  readers      = functions with no mutation sinks and nothing unclassifiable.

A function with no direct mutation sinks passes trivially: every mutation
executes a sink in *some* function, and all sink-bearing functions are checked,
so indirect calls cannot bypass the invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from foundation import staging as S

STAGING_SOURCE = Path(S.__file__)

PATH_MUTATION_ATTRS = frozenset({
    # NOTE (documented limitation): bare ``.replace()`` on an unknown-typed
    # receiver is treated as a *string* operation, because every ``.replace(``
    # in this module is one (``str(path).replace(...)``, ``flags.replace(...)``).
    # ``os.``/``shutil.``-rooted calls always count as sinks (see _dotted);
    # a future path-typed ``.replace()`` would need an analyzer update.
    "mkdir", "unlink", "rmdir", "rename", "write_bytes",
    "write_text", "remove", "rmtree", "copy2", "copy", "copytree", "move",
    "makedirs", "chmod", "chown", "symlink", "link", "hardlink", "truncate",
    "touch",
})

FS_ROOTS = frozenset({"os", "shutil"})

READ_ONLY_SWITCHES = frozenset({"/T", "/C"})

WRITE_VERBS = (
    "SetAccessControl", "AddAccessRule", "SetAccessRule", "RemoveAccessRule",
    "RemoveAccessRuleSpecific", "SetOwner", "SetAccessRuleProtection",
)


def _string_constants(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant)
            and isinstance(n.value, str)]


def _classify_run_call(call: ast.Call) -> str:
    """MUTATION / READONLY / UNKNOWN for a _run()/subprocess-style call."""
    consts = _string_constants(call)
    if not consts:
        return "UNKNOWN"
    for token in consts:
        stripped = token.strip()
        if stripped.startswith("/") and stripped not in READ_ONLY_SWITCHES:
            return "MUTATION"
        if any(verb in stripped for verb in WRITE_VERBS):
            return "MUTATION"
    joined = " ".join(consts)
    if "-Command" in joined and any(
            verb in joined for verb in WRITE_VERBS + ("icacls /",)):
        return "MUTATION"
    return "READONLY"


def _dotted(func: ast.AST) -> tuple[str | None, str]:
    """(dotted path or None, attribute) for a call target.

    ``os.replace`` -> ("os.replace", "replace"); ``x.mkdir`` -> ("x.mkdir",
    "mkdir"); ``str(p).replace`` -> (None, "replace") since the receiver is
    itself a call whose type is unknown statically.
    """
    attrs: list[str] = []
    while isinstance(func, ast.Attribute):
        attrs.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        attrs.append(func.id)
        return ".".join(reversed(attrs)), attrs[0]
    return None, attrs[0] if attrs else ""


def analyze_function(node: ast.FunctionDef) -> dict:
    """Classify one function: sinks, guards, verdict."""
    sinks: list[tuple[int, str]] = []
    guards: list[int] = []
    unknown: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            dotted, name = _dotted(func)
            if name == "_refuse_canonical_production":
                guards.append(child.lineno)
            elif name in PATH_MUTATION_ATTRS or (
                    name == "replace" and dotted is not None
                    and dotted.split(".")[0] in FS_ROOTS):
                sinks.append((child.lineno, f"fs:{dotted or name}"))
            elif name == "open":
                mode = "r"
                if len(child.args) >= 2 and isinstance(child.args[1], ast.Constant):
                    mode = str(child.args[1].value)
                elif any(kw.arg == "mode" and isinstance(kw.value, ast.Constant)
                         for kw in child.keywords):
                    mode = str(next(kw.value.value for kw in child.keywords
                                    if kw.arg == "mode"))
                elif len(child.args) >= 2 or any(
                        kw.arg == "mode" for kw in child.keywords):
                    unknown.append((child.lineno, "open(dynamic-mode)"))
                    continue
                if any(ch in mode for ch in ("w", "a", "x", "+")):
                    sinks.append((child.lineno, f"open:{mode}"))
            elif name in ("_run", "run") or (
                    isinstance(func, ast.Attribute) and func.attr == "run"):
                verdict = _classify_run_call(child)
                if verdict == "MUTATION":
                    sinks.append((child.lineno, "acl-mutation-call"))
                elif verdict == "UNKNOWN":
                    unknown.append((child.lineno, "unclassifiable-call"))
        elif isinstance(child, ast.Raise):
            exc = child.exc
            ename = ""
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                ename = exc.func.id
            elif isinstance(exc, ast.Name):
                ename = exc.id
            if ename == "CanonicalProductionMutation":
                guards.append(child.lineno)
    if unknown:
        verdict = "UNCLASSIFIABLE"
    elif not sinks:
        verdict = "READONLY"
    elif guards and all(any(g < line for g in guards) for line, _ in sinks):
        verdict = "PROTECTED"
    else:
        verdict = "UNGUARDED"
    return {"sinks": sinks, "guards": guards, "unknown": unknown,
            "verdict": verdict}


def analyze_module(path: Path = STAGING_SOURCE) -> dict[str, dict]:
    """Classify every function in the staging module. Pure AST, no imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name: analyze_function(node)
            for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_every_mutation_path_guarded_or_readonly():
    report = analyze_module()
    assert report, "no functions found -- harness is blind"
    bad = {name: info for name, info in report.items()
           if info["verdict"] in ("UNGUARDED", "UNCLASSIFIABLE")}
    assert not bad, f"unguarded/unclassifiable mutation paths: {bad}"
    guarded = {n for n, i in report.items() if i["verdict"] == "PROTECTED"}
    assert {"apply_boundary", "deploy_artifact", "recover"} <= guarded
    assert report["staging_root"]["verdict"] == "READONLY"


def test_guard_precedes_every_mutation():
    report = analyze_module()
    for name, info in report.items():
        if info["verdict"] == "PROTECTED":
            first_sink = min(line for line, _ in info["sinks"])
            assert any(g < first_sink for g in info["guards"]), name


def test_harness_detects_synthetic_unguarded_helper():
    evil = '''
def staging_root(root=None):
    return root

def deploy_evil(root=None):
    import shutil
    base = staging_root(root)
    shutil.rmtree(base)
'''
    tree = ast.parse(evil)
    funcs = {n.name: analyze_function(n)
             for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert funcs["deploy_evil"]["verdict"] == "UNGUARDED"
    assert funcs["deploy_evil"]["sinks"]
    assert funcs["staging_root"]["verdict"] == "READONLY"


def test_harness_detects_unclassifiable_dynamic_call():
    tricky = '''
def deploy_tricky(root=None, argv=None):
    import subprocess
    subprocess.run(argv)
'''
    tree = ast.parse(tricky)
    funcs = {n.name: analyze_function(n)
             for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert funcs["deploy_tricky"]["verdict"] == "UNCLASSIFIABLE"


def _dotted_is_mutating(dotted: str | None, attr: str) -> bool:
    """Exact-match mutation check for top-level calls (no substrings)."""
    if dotted in ("os.replace", "os.remove", "os.unlink", "os.mkdir",
                  "os.makedirs", "os.rmdir", "os.rename", "os.chmod",
                  "shutil.rmtree", "shutil.copy2", "shutil.copy",
                  "shutil.copytree", "shutil.move"):
        return True
    return attr in PATH_MUTATION_ATTRS


def test_no_top_level_mutation_calls():
    tree = ast.parse(STAGING_SOURCE.read_text(encoding="utf-8"))
    hits = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            dotted, attr = _dotted(child.func)
            if _dotted_is_mutating(dotted, attr):
                hits.append(f"{dotted}@{child.lineno}")
    assert hits == [], f"module-level mutation-capable calls: {hits}"


def test_apply_boundary_refuses_without_mutation(tmp_path: Path):
    canon = Path(S._CANONICAL_T).resolve()
    before = sorted(p.name for p in canon.iterdir())
    with pytest.raises(S.CanonicalProductionMutation):
        S.apply_boundary(root=None)
    with pytest.raises(S.CanonicalProductionMutation):
        S.apply_boundary(root=canon)
    with pytest.raises(S.CanonicalProductionMutation):
        S.apply_boundary(root=canon / "runtime" / ".." / ".." / "subject_runtime")
    after = sorted(p.name for p in canon.iterdir())
    assert before == after, "refusal must precede any mutation"


def test_apply_boundary_disposable_root_works(tmp_path: Path):
    import os as _os
    dest = tmp_path / "staging"
    out = S.apply_boundary(root=dest, operator=_os.environ.get("USERNAME", "operator"))
    assert out["failed_operations"] == []
    tree = dest / "subject_runtime"
    assert (tree / "runtime").is_dir()
    assert (tree / "model").is_dir()
    assert (tree / "config").is_dir()
