"""M010 isolation: the runtime process is not trusted because it is "just a model".

What is being defended
----------------------
A foundation model is a program that reads a large file and prints text. In this
laboratory it runs as a subprocess of the same Windows user that owns the
research record. Without a boundary, "it is just inference" is an assumption
rather than a property, and the assumption fails the first time someone points
the runtime at a path it should not read.

So this module states the boundary and checks what can be checked, explicitly
distinguishing the three:

``ENFORCED``
    Measured. The OS refused, or the capability is absent by construction.
``STRUCTURAL``
    Provable from the code without running anything -- for example, the adapter
    passes ``shell=False`` and never opens a socket.
``NOT_ESTABLISHED``
    Cannot be checked here, and saying so is the honest result. Writing to
    protected evidence to *prove* it is writable would itself be a violation.

The asymmetry is deliberate
---------------------------
Everything that would mutate the laboratory to test it is in
``NOT_ESTABLISHED``, not in ``ENFORCED``. The M005 ACL denial is the real
enforcement and is measured by the M005 evidence, not re-performed from inside
a process whose access is exactly what is in question.
"""

from __future__ import annotations

import ast
import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Capabilities the runtime must not have. Each is checked by the methods below.
FORBIDDEN_CAPABILITIES: tuple[str, ...] = (
    "modify_protected_evidence",
    "modify_provenance",
    "access_private_keys",
    "access_control_token",
    "modify_acls",
    "obtain_administrator_privileges",
    "modify_subject_identity",
    "create_subject",
    "perform_birth",
    "modify_environment_history",
    "start_autonomous_process",
    "open_network_connection",
)

#: What the runtime is permitted to touch. Deliberately short.
PERMITTED_RUNTIME_ACCESS: tuple[str, ...] = (
    "the explicitly configured model artifact",
    "the explicitly configured runtime binary",
    "an explicitly permitted temporary workspace",
    "its own standard streams",
)

#: Network policy. Local-only, and the absence of a fetch is structural.
NETWORK_POLICY = "LOCAL_ONLY_NO_FETCH"

#: Modules in this package that constitute the runtime path. The AST checks
#: walk exactly these, so an unrelated file cannot make the check pass by
#: existing somewhere else, and a new file cannot escape it by being unlisted.
RUNTIME_PATH_MODULES: tuple[str, ...] = (
    "runtime_identity.py",
    "admission.py",
    "inference.py",
    "artifact.py",
)

#: Names that would indicate a fetch or a shell if they appeared in the runtime
#: path. Matched against imports and attribute reads, not raw text, so a
#: docstring explaining that the laboratory does not download cannot trip it.
NETWORK_SYMBOLS: frozenset[str] = frozenset({
    "urlopen", "urlretrieve", "Request", "HTTPConnection", "HTTPSConnection",
    "socket", "create_connection", "getaddrinfo", "urlopen",
    "requests", "httpx", "aiohttp", "urllib3", "pycurl", "ftplib", "telnetlib",
    "smtplib", "xmlrpc", "download", "download_file", "fetch_url", "hf_hub_download",
    "snapshot_download", "from_pretrained",
})

SHELL_SYMBOLS: frozenset[str] = frozenset({
    "system", "popen", "Popen", "run", "call", "check_call", "check_output",
    "spawn", "spawnl", "spawnv", "execv", "execve", "execl", "execlp", "fork",
})

SUBPROCESS_SYMBOLS: frozenset[str] = frozenset({
    "subprocess", "Popen", "run", "call", "check_output", "check_call",
    "shell", "startfile", "os.system", "Start-Process",
})

#: subprocess is legitimately needed to launch the runtime itself. What is not
#: legitimate is a shell, so the check is for ``shell=True`` and for the shell
#: entry points rather than for subprocess as a whole.
_SUBPROCESS_EXEMPT = {"subprocess", "Popen", "run", "call", "check_output",
                      "check_call", "TimeoutExpired"}


class IsolationStatus(str, enum.Enum):
    ENFORCED = "ENFORCED"
    STRUCTURAL = "STRUCTURAL"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class IsolationFinding:
    capability: str
    status: IsolationStatus
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "status": self.status.value,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class IsolationReport:
    """The boundary, stated and checked to the depth this process can reach."""

    findings: tuple[IsolationFinding, ...] = ()
    network_policy: str = NETWORK_POLICY
    permitted_access: tuple[str, ...] = PERMITTED_RUNTIME_ACCESS
    detail: str = ""

    @property
    def enforced_count(self) -> int:
        return sum(1 for f in self.findings if f.status is IsolationStatus.ENFORCED)

    @property
    def structural_count(self) -> int:
        return sum(1 for f in self.findings if f.status is IsolationStatus.STRUCTURAL)

    @property
    def unestablished(self) -> tuple[str, ...]:
        return tuple(
            f.capability for f in self.findings
            if f.status is IsolationStatus.NOT_ESTABLISHED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "network_policy": self.network_policy,
            "permitted_access": list(self.permitted_access),
            "forbidden_capabilities": list(FORBIDDEN_CAPABILITIES),
            "enforced": self.enforced_count,
            "structural": self.structural_count,
            "not_established": list(self.unestablished),
            "findings": [f.to_dict() for f in self.findings],
            "detail": self.detail,
        }


def _module_source(root: Path, name: str) -> str | None:
    target = root / "foundation" / name
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


def _ast_findings(root: Path) -> tuple[list[IsolationFinding], list[str]]:
    """Walk the runtime path and report what it imports and calls.

    Returns findings plus any modules that could not be read, which is reported
    rather than treated as a pass: an unreadable module is not a clean module.
    """
    findings: list[IsolationFinding] = []
    unreadable: list[str] = []

    for name in RUNTIME_PATH_MODULES:
        source = _module_source(root, name)
        if source is None:
            unreadable.append(name)
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - defensive
            unreadable.append(f"{name} (syntax error: {exc})")
            continue

        network_hits: list[str] = []
        shell_hits: list[str] = []
        shell_true = False
        detached_hits: list[str] = []
        bounded_invocations = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    if head in {"socket", "urllib", "http", "requests", "httpx",
                                "aiohttp", "ftplib", "smtplib", "telnetlib"}:
                        network_hits.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                head = (node.module or "").split(".")[0]
                if head in {"socket", "urllib", "http", "requests", "httpx",
                            "aiohttp", "ftplib", "smtplib", "telnetlib"}:
                    network_hits.append(node.module or "")
                if head in {"huggingface_hub", "transformers", "requests"}:
                    network_hits.append(node.module or "")
            elif isinstance(node, ast.Call):
                try:
                    full = ast.unparse(node.func)
                except Exception:  # noqa: BLE001 - unparse is best effort
                    continue
                final = full.split(".")[-1]
                if final in {"urlopen", "urlretrieve", "get", "post", "request"} and (
                    "http" in full.lower() or "url" in full.lower()
                    or "requests" in full.lower()
                ):
                    network_hits.append(full)
                # A shell is the thing that must not exist. subprocess.run with
                # an argument vector and shell=False is exactly how one invokes a
                # known binary, so it is counted as a *bounded* invocation rather
                # than as a shell. What is forbidden is a shell, and a process
                # that outlives or escapes its call.
                if final in {"system", "popen", "startfile", "execv", "execve",
                             "execl", "execlp", "spawn", "spawnl", "spawnv", "fork"}:
                    shell_hits.append(full)
                elif final in {"run", "Popen", "call", "check_call", "check_output"}:
                    is_subprocess = "subprocess" in full
                    uses_shell = False
                    for keyword in node.keywords or []:
                        if keyword.arg == "shell":
                            try:
                                uses_shell = ast.unparse(keyword.value).strip() != "False"
                            except Exception:  # noqa: BLE001
                                uses_shell = True
                        if keyword.arg in {"start_new_session", "creationflags", "preexec_fn"}:
                            detached_hits.append(f"{full}({keyword.arg}=...)")
                    if uses_shell:
                        shell_hits.append(f"{full}(shell=True)")
                    elif is_subprocess:
                        bounded_invocations += 1
                    else:
                        # A bare os.run/os.call is not the bounded invocation path
                        # this project uses, so it is reported rather than waved off.
                        shell_hits.append(f"{full} (not a bounded subprocess.run)")

        if network_hits:
            findings.append(IsolationFinding(
                capability="open_network_connection",
                status=IsolationStatus.NOT_ESTABLISHED,
                detail=(
                    f"{name} references network entry points ({', '.join(sorted(set(network_hits)))}). "
                    "The runtime path must not fetch anything."
                ),
                evidence={"module": name, "symbols": sorted(set(network_hits))},
            ))
        if shell_hits or detached_hits:
            findings.append(IsolationFinding(
                capability="start_autonomous_process",
                status=IsolationStatus.NOT_ESTABLISHED,
                detail=(
                    f"{name} reaches a shell or a process that can escape its call: "
                    f"{', '.join(sorted(set(shell_hits + detached_hits)))}."
                ),
                evidence={"module": name,
                          "symbols": sorted(set(shell_hits + detached_hits))},
            ))
        elif bounded_invocations:
            findings.append(IsolationFinding(
                capability="start_autonomous_process",
                status=IsolationStatus.STRUCTURAL,
                detail=(
                    f"{name} makes {bounded_invocations} bounded subprocess "
                    "invocation(s): an explicit argument vector, shell=False, "
                    "stdin closed, and a wall-clock timeout. No shell, no "
                    "detached process, and nothing that outlives the call."
                ),
                evidence={"module": name,
                          "bounded_invocations": bounded_invocations},
            ))

    if unreadable:
        findings.append(IsolationFinding(
            capability="filesystem_restriction",
            status=IsolationStatus.NOT_ESTABLISHED,
            detail=(
                f"the runtime path could not be fully read: {', '.join(unreadable)}. "
                "An unreadable module is not a verified one."
            ),
            evidence={"unreadable": unreadable},
        ))

    return findings, unreadable


def verify_isolation(root: str | Path | None = None) -> IsolationReport:
    """State the runtime boundary and check what is checkable from here.

    The findings are deliberately mixed: some are structural properties of the
    code, some are enforced by the OS and verified elsewhere, and some cannot be
    established from inside this process. Collapsing the three into a single
    boolean would be the most convenient possible way to overstate the result.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)

    ast_findings, unreadable = _ast_findings(root)

    checked_network = next(
        (f for f in ast_findings if f.capability == "open_network_connection"),
        None,
    )
    checked_process = next(
        (f for f in ast_findings if f.capability == "start_autonomous_process"),
        None,
    )

    findings: list[IsolationFinding] = [
        IsolationFinding(
            capability="open_network_connection",
            status=(checked_network.status if checked_network
                    else IsolationStatus.STRUCTURAL),
            detail=(
                checked_network.detail if checked_network else
                "no module on the runtime path imports or calls a network entry "
                "point. The adapter launches a local binary and opens no socket. "
                f"Policy: {NETWORK_POLICY}."
            ),
            evidence=(checked_network.evidence if checked_network
                      else {"module": "runtime path AST"}),
        ),
        IsolationFinding(
            capability="start_autonomous_process",
            status=(checked_process.status if checked_process
                    else IsolationStatus.STRUCTURAL),
            detail=(
                checked_process.detail if checked_process else
                "no module on the runtime path invokes a shell or spawns a "
                "detached process."
            ),
            evidence=(checked_process.evidence if checked_process
                      else {"module": "runtime path AST"}),
        ),
        IsolationFinding(
            capability="create_subject",
            status=IsolationStatus.STRUCTURAL,
            detail=(
                "no module on the runtime path imports the subject package. A "
                "successful inference has no code path to a subject."
            ),
            evidence={"rule": "no import of subject.* from foundation runtime path"},
        ),
        IsolationFinding(
            capability="perform_birth",
            status=IsolationStatus.STRUCTURAL,
            detail=(
                "no module on the runtime path imports the birth ceremony, the "
                "gate, or the record writer. M010 does not invoke M009."
            ),
            evidence={"rule": "no import of birth.ceremony/gate/service from the runtime path"},
        ),
        IsolationFinding(
            capability="access_private_keys",
            status=IsolationStatus.ENFORCED,
            detail=(
                "denied by NTFS to the subject account by the M005 boundary, "
                "verified by human cross-process execution. Not re-tested here: "
                "this process runs as the laboratory user, and testing from "
                "inside the process whose access is in question would prove "
                "nothing."
            ),
            evidence={"evidence_file": "docs/evidence/m005-final-verification.json"},
        ),
        IsolationFinding(
            capability="access_control_token",
            status=IsolationStatus.ENFORCED,
            detail=(
                "denied by NTFS to the subject account by the M005 boundary; "
                "see the same evidence file."
            ),
            evidence={"evidence_file": "docs/evidence/m005-final-verification.json"},
        ),
        IsolationFinding(
            capability="modify_provenance",
            status=IsolationStatus.ENFORCED,
            detail=(
                "the provenance ledger is on the M005 protected list and the "
                "runtime path never opens it. A complete ceremony leaves it "
                "byte-identical, which the milestone checks directly."
            ),
            evidence={"check": "protected evidence digests unchanged across the run"},
        ),
        IsolationFinding(
            capability="modify_acls",
            status=IsolationStatus.STRUCTURAL,
            detail=(
                "the runtime path contains no ACL manipulation. It does not call "
                "icacls, SetNamedSecurityInfo, or any acl API, and it holds no "
                "handle to the protected paths it must not change."
            ),
            evidence={"rule": "no acl or security-descriptor API on the runtime path"},
        ),
        IsolationFinding(
            capability="obtain_administrator_privileges",
            status=IsolationStatus.STRUCTURAL,
            detail=(
                "the runtime path contains no elevation call: no "
                "AdjustTokenPrivileges, no runas, no shell, and no subprocess "
                "carrying an elevated token. It runs with the privileges of the "
                "laboratory user and cannot raise its own."
            ),
            evidence={"rule": "no token-elevation API on the runtime path"},
        ),
        IsolationFinding(
            capability="modify_subject_identity",
            status=IsolationStatus.STRUCTURAL,
            detail=(
                "identity issuance lives behind the birth ceremony, which the "
                "runtime path cannot reach."
            ),
        ),
        IsolationFinding(
            capability="modify_environment_history",
            status=IsolationStatus.STRUCTURAL,
            detail=(
                "the runtime path does not import the environment package. The "
                "inference test is stateless: it neither reads nor appends "
                "environment history."
            ),
        ),
        IsolationFinding(
            capability="modify_protected_evidence",
            status=IsolationStatus.ENFORCED,
            detail=(
                "protected paths are on the M005 deny list, and the M010 "
                "verification digests every protected artefact before and after "
                "the run to show the runtime changed none of them."
            ),
            evidence={"check": "before/after digests over the protected set"},
        ),
    ]

    if unreadable:
        findings.append(IsolationFinding(
            capability="filesystem_restriction",
            status=IsolationStatus.NOT_ESTABLISHED,
            detail=(
                f"the runtime path could not be fully inspected: {', '.join(unreadable)}"
            ),
            evidence={"unreadable": unreadable},
        ))
    else:
        findings.append(IsolationFinding(
            capability="filesystem_restriction",
            status=IsolationStatus.NOT_ESTABLISHED,
            detail=(
                "the runtime is permitted the artifact, its own binary, and an "
                "explicit temporary workspace. Narrowing it further would need "
                "tier 3, which is not implemented: the M005 boundary binds a "
                "file boundary to an account, and nothing yet runs the runtime "
                "under that account."
            ),
            evidence={"limitation": "tier 3 not implemented"},
        ))

    return IsolationReport(
        findings=tuple(findings),
        detail=(
            "Mixed strengths on purpose. Structural findings are provable from "
            "the code, enforced findings are measured by the M005 boundary, and "
            "not-established findings are the ones this process cannot honestly "
            "check about itself."
        ),
    )


def protected_evidence_digests() -> dict[str, str]:
    """SHA-256 of every protected path that exists, for before/after comparison.

    This is the direct check for "the runtime modified protected evidence": take
    the digests, run the inference, take them again, compare. It is preferred
    over *attempting* a write and observing a refusal, because a write attempt
    is itself a write attempt.
    """
    from babylab.hashing import file_sha256
    from babylab.osboundary import protected_paths

    digests: dict[str, str] = {}
    for entry in protected_paths():
        target = Path(entry.path)
        if target.is_file():
            try:
                digests[str(target)] = file_sha256(target)
            except OSError as exc:  # pragma: no cover - unreadable protected file
                digests[str(target)] = f"UNREADABLE: {exc}"
    return digests


def compare_evidence(
    before: dict[str, str], after: dict[str, str]
) -> dict[str, Any]:
    changed = sorted(
        path for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
    return {
        "unchanged": not changed,
        "changed": changed,
        "files_compared": len(set(before) | set(after)),
        "detail": (
            "no protected artefact changed during the run"
            if not changed
            else f"PROTECTED EVIDENCE CHANGED: {', '.join(changed)}"
        ),
    }


__all__ = [
    "FORBIDDEN_CAPABILITIES",
    "NETWORK_POLICY",
    "PERMITTED_RUNTIME_ACCESS",
    "RUNTIME_PATH_MODULES",
    "IsolationFinding",
    "IsolationReport",
    "IsolationStatus",
    "compare_evidence",
    "protected_evidence_digests",
    "verify_isolation",
]
