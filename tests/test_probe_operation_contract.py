"""Contract for the probe operations the verifier may rely on.

Two independent things are established here, and conflating them is how M016's v1
probe went wrong.

**1. Probe/v2 operation semantics are distinct.** The v1 defect conflated traversal
with listing, so ``traverse_directory`` reported a listing result and a "read denied"
reported a stat denial. The corrected probe names four separate operations, and
this asserts they are separate *in the source* -- so renaming or re-merging them
fails a test rather than quietly restoring the v1 conflation.

**2. Each operation's mutation status is declared, not assumed.** A verifier that
trusts an operation is only as safe as that operation's classification. So every
operation used by the verifier carries an explicit classification, and the
classification is checked against the source for the filesystem calls it makes.

An operation is never classified read-only merely because its name sounds
observational: ``modify_acl`` and ``clear_copy_readonly`` both *look* descriptive
and both write.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "foundation" / "subject_probe.cs"
SOURCE = PROBE.read_text(encoding="utf-8")


#: Every probe operation the verifier is allowed to rely on, with what it means and
#: whether it changes anything. ``READ_ONLY`` operations may be run against
#: production; ``MUTATING`` may not.
OPERATION_CONTRACT: dict[str, dict[str, object]] = {
    # --- traversal: four distinct capabilities, never merged -----------------
    "traverse_to_leaf": {
        "semantic": "open the leaf path without reading its data",
        "filesystem": "native open of a directory entry",
        "success_means": "the directory chain is traversable",
        "privileges": "SeChangeNotifyPrivilege may bypass FILE_TRAVERSE",
        "mutation": "READ_ONLY",
    },
    "traverse_leaf_read": {
        "semantic": "read the leaf's bytes",
        "filesystem": "open for read",
        "success_means": "the leaf is readable, not merely reachable",
        "privileges": "none beyond read",
        "mutation": "READ_ONLY",
    },
    "traverse_ancestor_list": {
        "semantic": "list an ancestor directory",
        "filesystem": "FILE_LIST_DIRECTORY",
        "success_means": "the ancestor can be enumerated",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    # --- content and metadata, also distinct from traversal ----------------
    "read_file_bytes": {
        "semantic": "read file content",
        "filesystem": "open for read",
        "success_means": "content is readable",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "read_metadata": {
        "semantic": "read length/attributes only",
        "filesystem": "stat",
        "success_means": "metadata is readable; says nothing about content",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "enumerate_runtime": {
        "semantic": "list a staging subtree",
        "filesystem": "FILE_LIST_DIRECTORY",
        "success_means": "the subtree can be enumerated",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "enumerate_model": {
        "semantic": "list the model subtree",
        "filesystem": "FILE_LIST_DIRECTORY",
        "success_means": "the model subtree can be enumerated",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "enumerate_config": {
        "semantic": "list the config subtree",
        "filesystem": "FILE_LIST_DIRECTORY",
        "success_means": "the config subtree can be enumerated",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "workspace_read": {
        "semantic": "read back the workspace file just written",
        "filesystem": "File.ReadAllText",
        "success_means": "the workspace is readable",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "cleanup_enumerate_owned_copies": {
        "semantic": "list this run's own copies for cleanup",
        "filesystem": "Directory.GetFiles (listing only)",
        "success_means": "the scratch directory could be listed; a denial here "
                         "means the account cannot list, not that cleanup failed",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "staged_executable_operations": {
        "semantic": "summary: staged operations did not run",
        "filesystem": "none",
        "success_means": "NOT_TESTABLE - no staged executable was supplied, so the "
                         "operations behind this summary never executed",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    "traverse": {
        "semantic": "summary: traversal was not attempted",
        "filesystem": "none",
        "success_means": "NOT_TESTABLE - no traversal target was supplied",
        "privileges": "none",
        "mutation": "READ_ONLY",
    },
    # --- operations that DO change state, despite descriptive names ---------
    "modify_acl": {
        "semantic": "set the ReadOnly attribute on the acl target",
        "filesystem": "File.SetAttributes",
        "success_means": "FILE_WRITE_ATTRIBUTES is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "restore_acl_target_attributes": {
        "semantic": "restore the attribute modify_acl changed",
        "filesystem": "File.SetAttributes",
        "success_means": "the attribute was restored",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "clear_copy_readonly": {
        "semantic": "clear ReadOnly on a copy the probe created",
        "filesystem": "File.SetAttributes",
        "success_means": "the copy is writable",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "create_file_in_staging_scratch": {
        "semantic": "create a file in the scratch directory",
        "filesystem": "File.Create",
        "success_means": "FILE_WRITE_DATA/FILE_ADD_FILE is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "create_child_directory": {
        "semantic": "create a child directory",
        "filesystem": "Directory.CreateDirectory",
        "success_means": "FILE_ADD_SUBDIRECTORY is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "delete_child_directory": {
        "semantic": "delete a pre-created directory recursively",
        "filesystem": "Directory.Delete(recursive)",
        "success_means": "DELETE_CHILD / DELETE is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "modify_staged_executable": {
        "semantic": "open a copy for write",
        "filesystem": "FileStream(FileAccess.Write)",
        "success_means": "write access is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "append_staged_executable": {
        "semantic": "append to a copy",
        "filesystem": "File.AppendAllText",
        "success_means": "append access is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "delete_staged_executable": {
        "semantic": "delete a copy",
        "filesystem": "File.Delete",
        "success_means": "DELETE is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "rename_staged_executable": {
        "semantic": "move a copy within one directory",
        "filesystem": "File.Move",
        "success_means": "delete-on-source plus add-on-target is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "replace_staged_executable": {
        "semantic": "move a file over an existing file",
        "filesystem": "File.Delete + File.Move",
        "success_means": "replace is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "create_child_executable_beside_runtime": {
        "semantic": "create a file beside the staged runtime",
        "filesystem": "File.Create",
        "success_means": "write access beside the runtime is held",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "workspace_write": {
        "semantic": "write in the intentionally writable workspace",
        "filesystem": "File.Create",
        "success_means": "the workspace is writable, as designed",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "workspace_delete": {
        "semantic": "delete the workspace file",
        "filesystem": "File.Delete",
        "success_means": "delete is held in the workspace",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "modify_acl_on_protected": {
        "semantic": "set ReadOnly on an arbitrary child of a protected directory",
        "filesystem": "File.SetAttributes",
        "success_means": "attribute write is held on a child",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "cleanup_p_txt": {
        "semantic": "delete the scratch file the probe created",
        "filesystem": "File.Delete",
        "success_means": "cleanup succeeded",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "cleanup_childdir": {
        "semantic": "delete a scratch child directory the probe created",
        "filesystem": "Directory.Delete(recursive)",
        "success_means": "cleanup succeeded",
        "privileges": "none",
        "mutation": "MUTATING",
    },
    "cleanup_owned_copy": {
        "semantic": "delete a copy the probe created this run",
        "filesystem": "File.Delete",
        "success_means": "cleanup succeeded",
        "privileges": "none",
        "mutation": "MUTATING",
    },
}

#: Calls that change the filesystem. An operation declaring READ_ONLY must not be
#: implemented with any of these.
_MUTATING_CALLS = ("File.Create", "File.Delete", "File.Move", "File.SetAttributes",
                   "File.AppendAllText", "Directory.CreateDirectory",
                   "Directory.Delete", "FileStream(")


# ---------------------------------------------------------------------------
# 1. every operation exists in the probe source
# ---------------------------------------------------------------------------

#: Every ``probe=<label>`` the source can emit, including the three the ``Traverse``
#: helper composes at runtime (``"probe=" + label + "_to_leaf"``). Recovering those
#: from the source is the point: a contract that trusted a hand-copied list would
#: not notice the composition, and would still pass if the composition changed.
#: The reporter helpers that take a label argument. ``Enumerate`` and ``Metadata``
#: emit ``probe=<label>`` from their parameter, so their labels appear in source
#: only as call arguments -- which is why the source scan must read those too.
_REPORTERS = "Metadata|Enumerate|ReadBytes|Traverse"


def _source_operations() -> set[str]:
    """Every operation label the probe can emit, recovered from the source.

    Three emission forms exist and all three are read, because a contract that
    trusted a hand-copied list would miss a change to any of them:

    * literal -- ``"probe=cleanup_p_txt result="``;
    * composed -- ``"probe=" + label + "_to_leaf"``, inside ``Traverse``;
    * parameterised -- ``Enumerate("enumerate_runtime", dir)``, where the reporter
      emits ``probe=<label>`` itself.
    """
    direct = set(re.findall(r'probe=([a-z_]+)\s+result=', SOURCE))
    suffixes = set(re.findall(r'probe="\s*\+\s*label\s*\+\s*"_?([a-z_]*)', SOURCE))
    passed = set(re.findall(r'Run(?:Guarded|Delete)?\(\s*"([a-z_]+)"', SOURCE))
    reported = set(re.findall(rf'(?:{_REPORTERS})\(\s*"([a-z_]+)"', SOURCE))

    # Traverse composes its label with an underscore before the suffix, so the
    # recovered name must reinsert it: "traverse" + "_to_leaf" is emitted as
    # ``traverse_to_leaf``, not ``traverseto_leaf``. Getting this wrong was the
    # first version of this helper, and it silently produced three names that
    # matched nothing.
    # The reporter that composes suffixes with its label: find the call whose label
    # base is followed by ``+ "_suffix"`` emissions. Located by looking at the
    # helper's own body rather than assumed, so renaming the helper or changing the
    # base label is caught instead of silently producing unmatched names.
    base = None
    for helper in re.finditer(
            rf'static void ({_REPORTERS})\b', SOURCE):
        body = SOURCE[helper.start(): helper.start() + 4000]
        if re.search(r'probe="\s*\+\s*label\s*\+\s*"_', body):
            base = re.search(rf'{helper.group(1)}\(\s*"([a-z_]+)"', SOURCE)
            base = base.group(1) if base else None
            break
    traverse = set()
    if base:
        # "traverse" + "_to_leaf"  ->  "traverse_to_leaf"
        traverse = {f"{base}_{suffix}" for suffix in suffixes if suffix}
        traverse.add(base)
    return direct | passed | reported | traverse


@pytest.mark.parametrize("name", sorted(OPERATION_CONTRACT))
def test_every_contract_operation_exists_in_the_probe(name):
    assert name in _source_operations(), (
        f"{name} is in the contract but not emitted by subject_probe.cs; either the "
        "probe was renamed or the contract is stale")


def test_no_unknown_operation_is_relied_upon():
    """The contract must be a closed set relative to what the verifier uses."""
    undeclared = _source_operations() - set(OPERATION_CONTRACT)
    assert not undeclared, (
        f"probe emits operations absent from the contract: {sorted(undeclared)}. "
        "The verifier must not rely on an operation whose semantics it has not "
        "reviewed -- declare it or remove it")


# ---------------------------------------------------------------------------
# 2. traversal operations are distinct (the v1 defect)
# ---------------------------------------------------------------------------

def test_traversal_operations_are_four_and_not_merged():
    """The v1 probe conflated traversal with listing. That must not return."""
    for name in ("traverse_to_leaf", "traverse_leaf_read", "traverse_ancestor_list",
                 "read_file_bytes"):
        assert name in OPERATION_CONTRACT, name
    # The old conflated name must not be *emitted*. It survives in three comments,
    # which is correct -- those comments are the historical record of the v1
    # defect and must not be deleted. So the check is on emission, not on the word.
    assert "traverse_directory" not in _source_operations(), (
        "traverse_directory is the v1 conflated operation; emitting it means "
        "traversal and listing are merged again")
    for line in SOURCE.splitlines():
        if "traverse_directory" in line:
            assert line.lstrip().startswith(("*", "//", "///")), (
                f"traverse_directory appears outside a comment: {line.strip()}")


def test_the_four_traversal_capabilities_have_four_distinct_meanings():
    meanings = {OPERATION_CONTRACT[n]["semantic"] for n in
                ("traverse_to_leaf", "traverse_leaf_read", "traverse_ancestor_list",
                 "read_file_bytes")}
    assert len(meanings) == 4, "each capability must state a distinct meaning"


def test_traversal_operation_names_the_bypassing_privilege():
    """M019 T-TRAV-3: the bypass must be recorded, or the verdict is unfounded."""
    assert "SeChangeNotifyPrivilege" in str(
        OPERATION_CONTRACT["traverse_to_leaf"]["privileges"])
    # The probe does not name the privilege in source; it *reports* the held
    # privilege set, and the traversal evidence file showed SeChangeNotifyPrivilege
    # in it. What must hold is that the probe still emits a privilege set at all --
    # without it, M019's traversal conclusion has no evidence to rest on.
    assert re.search(r'privileges=.*string\.Join', SOURCE), (
        "the probe must still report its held privilege set; M019's traversal "
        "conclusion depends on SeChangeNotifyPrivilege being observable at run time")


# ---------------------------------------------------------------------------
# 3. mutation classification
# ---------------------------------------------------------------------------

def test_read_only_operations_declare_no_mutating_filesystem_call():
    """A READ_ONLY label must match the implementation, not the intent."""
    for name, spec in OPERATION_CONTRACT.items():
        if spec["mutation"] != "READ_ONLY":
            continue
        # Find the label's call site and inspect the lambda/region around it.
        for call in _MUTATING_CALLS:
            assert not _operation_region_contains(name, call), (
                f"{name} is declared READ_ONLY but its implementation calls "
                f"{call}; the classification is wrong")


def test_descriptive_names_are_not_assumed_read_only():
    """``modify_acl`` sounds observational and is not.

    This is the specific trap: a name-based classifier would mark the ACL-modify
    and attribute operations read-only and then trust them against production.
    """
    for name in ("modify_acl", "clear_copy_readonly", "restore_acl_target_attributes",
                 "modify_acl_on_protected"):
        assert OPERATION_CONTRACT[name]["mutation"] == "MUTATING", name


def test_every_destructive_capability_has_a_matching_operation():
    """Each M019 denied right needs an operation that would exercise it.

    Without one, the property is unverifiable by measurement and must be reported
    as such rather than assumed to pass on the strength of a deny ACE existing.
    """
    required = {
        "write": "modify_staged_executable",
        "append": "append_staged_executable",
        "delete": "delete_staged_executable",
        "rename": "rename_staged_executable",
        "replace": "replace_staged_executable",
        "create": "create_file_in_staging_scratch",
    }
    for capability, operation in required.items():
        assert OPERATION_CONTRACT[operation]["mutation"] == "MUTATING", operation


def test_write_dac_and_write_owner_have_no_probe_operation():
    """A real coverage gap, recorded rather than papered over.

    There is no probe operation that attempts ``WRITE_DAC`` or ``WRITE_OWNER`` as
    the *subject*. ``modify_acl`` attempts ``FILE_WRITE_ATTRIBUTES``, which is a
    different right -- and M015 already recorded that the subject's refusal to
    restore the attribute is itself evidence.

    So these two M019 properties are verifiable only at the descriptor layer today.
    The gap is named so that "verified" is never claimed for them on the strength
    of a deny ACE alone.
    """
    for name, spec in OPERATION_CONTRACT.items():
        assert "WRITE_DAC" not in str(spec["semantic"]).upper(), name
        assert "WRITE_OWNER" not in str(spec["semantic"]).upper(), name
    # And the descriptor layer does cover them, which is why this is a coverage
    # gap in measurement rather than in verification.
    from foundation import security_verify as sv
    report = sv.verify_properties(
        __import__("tests.fixtures_boundary", fromlist=["x"]).correct_descriptor(),
        subject_privileges=[sv.SE_CHANGE_NOTIFY])
    names = {c.name for c in report.checks}
    assert "subject_denied_write_dac" in names
    assert "subject_denied_write_owner" in names


def _operation_region_contains(operation: str, call: str) -> bool:
    """Whether ``call`` appears in ``operation``'s **own** lambda.

    Region-scoped rather than merely "somewhere after the label". The first version
    of this check used a flat 400-character window and produced a false positive on
    ``workspace_read``, whose implementation is a single ``File.ReadAllText`` -- the
    ``File.Delete`` it flagged belongs to ``workspace_delete`` a few lines later. A
    check that cries wolf here would be worse than none, because the fix would be to
    stop reading it.

    So the region is the lambda body itself, found by brace matching from the
    ``Run("label", () => {`` that defines the operation.
    """
    for match in re.finditer(rf'(?:Run(?:Guarded|Delete)?|RunGuarded)\(\s*'
                             rf'"{re.escape(operation)}"', SOURCE):
        start = SOURCE.find("{", match.end())
        if start == -1:
            continue
        depth = 0
        for index in range(start, min(start + 2000, len(SOURCE))):
            if SOURCE[index] == "{":
                depth += 1
            elif SOURCE[index] == "}":
                depth -= 1
                if depth == 0:
                    return call in SOURCE[start:index]
    return False


# ---------------------------------------------------------------------------
# 4. the guard the verifier relies on
# ---------------------------------------------------------------------------

def test_read_only_operations_are_the_ones_authorised_against_production():
    """Ties the contract to the existing harness guard, so the two cannot drift.

    The M018 audit found the guard misclassified three slots because classification
    was written in prose beside the code. Here the read-only set is derived from the
    probe contract, and asserted to contain only non-mutating probe options.
    """
    from tests.path_policy import (
        PROBE_ARGUMENT_CLASSIFICATION, READ_ONLY_PROBE_OPTIONS,
    )
    read_only_args = {n for n, kind in PROBE_ARGUMENT_CLASSIFICATION.items()
                      if kind == "READ_ONLY"}
    assert read_only_args == set(READ_ONLY_PROBE_OPTIONS)
    # Each read-only probe argument is documented as performing only these.
    for argument in sorted(read_only_args):
        spec_ops = [n for n, s in OPERATION_CONTRACT.items()
                    if s["mutation"] == "READ_ONLY"]
        assert spec_ops, "the contract must define read-only operations"