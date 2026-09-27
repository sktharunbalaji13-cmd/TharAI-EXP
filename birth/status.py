"""Read-only inspection of the birth subsystem.

Why this module is separate from :mod:`birth.service`
-----------------------------------------------------
The ceremony writes; this only looks. They are separated so that a *reader* can
depend on the birth subsystem without acquiring a write path.

Concretely: the Cognitive State Observatory must display whether a subject
exists, which model it was born from, and what its capability contracts say. If
it imported :func:`birth.birth_ceremony.birth_ceremony` to get that, it would
transitively import :class:`events.store.EventStore` — the event log's append
path — into a component whose entire claim is that it is read-only. The
separation keeps that claim structurally true rather than a matter of discipline:
nothing reachable from here can append an event, create a birth record, or record
provenance.

:mod:`birth.service` re-exports :func:`inspect`, :func:`birth_status`,
:func:`workspace_state_of`, and :class:`InspectionResult` from here, so callers
that already import the ceremony keep working and the split costs no
compatibility. The dependency only ever points this way.

What "no subject" looks like here
---------------------------------
An unconfigured laboratory reports ``NOT_CONFIGURED`` and ``subject_exists:
False``. Those are not errors and not warnings; they are the expected state of a
fresh installation, and the payload says so in ``detail`` rather than leaving a
reader to infer it from a missing field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from babylab.clock import Clock
from babylab.errors import BabyLabError
from babylab.paths import ProjectPaths, default_paths
from birth.birth_record import load_record
from birth.cognitive import CapabilityRegistry
from birth.config import ConfigurationError, load_config
from birth.environment import unattached_environment
from birth.identity import InstallationReport, ModelStatus, resolve_model_identity
from birth.workspace import CodeWorkspace

#: Statuses that are a legitimate outcome of inspection rather than an error.
#: They are reported, not raised, because "no model installed" is a fact about
#: the laboratory and not a failure of the code.
TERMINAL_STATUSES = (
    ModelStatus.NOT_CONFIGURED,
    ModelStatus.MODEL_NOT_INSTALLED,
    ModelStatus.MODEL_INTEGRITY_MISMATCH,
    ModelStatus.RUNTIME_UNAVAILABLE,
)


@dataclass
class InspectionResult:
    """What a ceremony would find. Reads only; writes nothing."""

    status: ModelStatus
    detail: str
    installation: InstallationReport | None = None
    capability_registry_hash: str = ""
    environment_id: str = ""
    environment_connected: bool = False
    workspace_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "detail": self.detail,
            "capability_registry_hash": self.capability_registry_hash,
            "environment_id": self.environment_id,
            "environment_connected": self.environment_connected,
            "workspace_state": self.workspace_state,
            "installation": self.installation.to_dict() if self.installation else None,
        }

    def describe(self) -> str:
        return f"{self.status.value}: {self.detail}"


def inspect(
    paths: ProjectPaths | None = None,
    runtime_probe=None,
    registry: CapabilityRegistry | None = None,
    now: Any = None,
) -> InspectionResult:
    """Report what a ceremony currently finds, writing nothing.

    This is the function the ``status`` command calls. It is separated from
    :func:`birth.service.birth_ceremony` so that looking at the laboratory can
    never have a side effect — a check that could birth something is not a check.
    """
    root = paths or default_paths()
    registry = registry or CapabilityRegistry()
    environment = unattached_environment()
    workspace_state = workspace_state_of(root)
    moment = now if now is not None else Clock().now()

    try:
        config = load_config(root)
    except ConfigurationError as exc:
        report = resolve_model_identity(None, root, now=str(moment))
        return InspectionResult(
            status=ModelStatus.NOT_CONFIGURED,
            detail=str(exc),
            installation=report,
            capability_registry_hash=registry.registry_hash(),
            environment_id=environment.environment_id,
            environment_connected=environment.connected,
            workspace_state=workspace_state,
        )

    report = resolve_model_identity(
        config, root, runtime_probe=runtime_probe, now=str(moment)
    )
    return InspectionResult(
        status=report.status,
        detail=report.detail,
        installation=report,
        capability_registry_hash=registry.registry_hash(),
        environment_id=environment.environment_id,
        environment_connected=environment.connected,
        workspace_state=workspace_state,
    )


def workspace_state_of(root: ProjectPaths) -> str:
    """The workspace's state as a fact, or why it could not be determined.

    A read-only check must not create directories as a side effect, so this
    reports ``UNAVAILABLE`` rather than calling
    :meth:`~birth.workspace.CodeWorkspace.create`. The ceremony does create it,
    because a birth genuinely needs the directory to exist.
    """
    try:
        return CodeWorkspace(
            root=root.baby_code, repository_root=root.root
        ).state().value
    except BabyLabError as exc:
        return f"UNAVAILABLE: {exc}"


def birth_status(paths: ProjectPaths | None = None, now: Any = None) -> dict[str, Any]:
    """The birth subsystem's status, for the observatory and the CLI.

    Four independent facts, reported separately on purpose, because any two of
    them can be true while the others are false:

    ``subject_exists``
        A sealed birth record is on disk.
    ``model_installed``
        The weight file is present and its digest matches the configuration.
    ``model_usable``
        The weights are installed *and* the runtime was found and healthy, so a
        real load could plausibly succeed.
    ``model_status``
        The fine-grained reason, for a human who needs to know which of the
        above failed.

    Collapsing ``installed`` and ``usable`` would have been shorter and wrong. A
    laboratory can have verified weights on disk and no working runtime, and a
    dashboard that called that "installed" would be promising more than it knows.
    """
    root = paths or default_paths()
    record = load_record(root)
    result = inspect(root, now=now)

    if record is not None:
        identity = record.model
        installed = True
        usable = True
        status = ModelStatus.READY.value
        # The detail must come from the record, not from this inspection. The
        # inspection never runs the runtime, so borrowing its wording here would
        # print "READY" and "the runtime was NOT checked" in adjacent lines.
        # A record exists only because a ceremony verified the runtime, so that
        # is the fact to report.
        detail = (
            f"birth record {record.birth_id} was written on {record.born_at} by a "
            "ceremony that verified the weights and the runtime"
        )
    else:
        report = result.installation
        identity = report.identity if report else None
        # Weights are installed when a file was found whose digest matched; the
        # runtime question is separate and lives in the status.
        installed = bool(identity is not None and report and report.observed_sha256)
        usable = result.status.is_usable
        status = result.status.value
        detail = result.detail

    payload: dict[str, Any] = {
        "subject_exists": record is not None,
        "subject_id": record.subject_id if record else "",
        "born_at": record.born_at if record else "",
        "birth_id": record.birth_id if record else "",
        "birth_event_id": record.birth_event_id if record else "",
        "model_status": status,
        "model_detail": detail,
        "model_installed": installed,
        "model_usable": usable,
        "capability_registry_hash": result.capability_registry_hash,
        "capability_statuses": (dict(record.capability_summary) if record else {}),
        "environment_id": result.environment_id,
        "environment_connected": result.environment_connected,
        "workspace_state": result.workspace_state,
        "model": identity.to_dict() if identity else None,
    }
    if record is not None:
        payload["birth_record_hash"] = record.hash
    return payload


__all__ = [
    "TERMINAL_STATUSES",
    "InspectionResult",
    "birth_status",
    "inspect",
    "workspace_state_of",
]
