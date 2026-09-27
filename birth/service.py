"""The birth ceremony: the one function that creates a subject.

Order of operations, and why it is that order
---------------------------------------------
1. Resolve the configuration. Absent configuration is ``NOT_CONFIGURED`` and
   nothing else happens.
2. Verify the installation. Absent weights are ``MODEL_NOT_INSTALLED`` and
   nothing is written, no record, no event, no subject. **This is the most
   important line in the milestone**: an unconfigured or uninstalled laboratory
   must end with no subject, not with a plausible one.
3. Assemble the record in memory, which is where its ``birth_id`` comes from.
4. Append ``system.baby_ai.born``, naming that ``birth_id``.
5. Seal the record with the new event's id and write it **once**.
6. Record the created file in the provenance ledger.

Step 4 before step 5, which is the reverse of the obvious order and is worth
justifying. The event cannot contain the record's hash, because at the moment the
event is written the record does not exist yet; and the record must contain the
event's id, which is what makes the announcement and the record point at each
other. Announcing first and writing the complete record afterwards resolves the
circularity in one direction only, and it has a second benefit: the bytes of the
birth record are written once and never rewritten, so the record is genuinely
immutable rather than immutable-after-two-writes. The earlier order also left the
event citing a digest that the backfill had already invalidated, which a verifier
following the event would have hit as a hash mismatch.

The two artefacts link by stable id in both directions: the record names the
event, and the event payload names the record's ``birth_id``.

The event is laboratory-generated
---------------------------------
:data:`BIRTH_EVENT_TYPE` is ``system.baby_ai.born`` and its ``source`` is
``birth.service``. The subject is named in the payload; it does not emit its own
birth. That is not a formality — an event log in which a subject could announce
its own existence would have no way to distinguish a birth from a claim.

The event type
--------------
``system.baby_ai.born`` is chosen over a new namespace such as ``birth.*``
because ADR-004 keeps the namespace list to laboratory infrastructure, and the
birth of the experimental subject *is* laboratory infrastructure announcing an
experiment. A new top-level namespace would have looked like a new taxonomy.

No subject is created for a fake
--------------------------------
:func:`birth_ceremony` has no ``force`` parameter and no ``allow_fake`` flag, and
it refuses a configuration whose runtime is :data:`~birth.config.RuntimeKind.FAKE`
outright. A fake runtime is a test double that happens to be running in-process;
recording a subject against it would put an identity into ``human_control/`` that
describes nothing, and there would be no later moment at which anyone could tell
that apart from a real birth. Tests therefore exercise the ceremony against a
real configured weights file that really exists on disk under a temporary root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from babylab.clock import Clock
from babylab.errors import BabyLabError
from babylab.identity import Actor, Role
from babylab.paths import ProjectPaths, default_paths
from birth.birth_record import (
    BirthRecord,
    build_record,
    load_record,
    record_path,
    write_record,
)
from birth.cognitive import CapabilityRegistry
from birth.config import ConfigurationError, FoundationConfig, RuntimeKind, load_config
from birth.environment import unattached_environment
from birth.identity import InstallationReport, ModelStatus, resolve_model_identity
from birth.llamacpp import LlamaCppModel
from birth.status import (
    TERMINAL_STATUSES,
    InspectionResult,
    birth_status,
    inspect,
    workspace_state_of,
)
from birth.workspace import CodeWorkspace
from events.store import EventStore

#: The canonical birth event. Dotted lowercase, per events/model.py.
BIRTH_EVENT_TYPE = "system.baby_ai.born"

#: The component that emits it. The subject does not.
BIRTH_EVENT_SOURCE = "birth.service"

#: Alias kept for callers that expect the inspection result to carry the
#: ceremony's shape. They are the same object; the ceremony adds birth-specific
#: fields to a result that exists whether or not a birth is being attempted.
Inspection = InspectionResult


@dataclass
class CeremonyResult:
    """What a ceremony did, or why it did nothing."""

    status: ModelStatus
    detail: str
    born: bool = False
    record: BirthRecord | None = None
    record_path: str = ""
    event_id: str = ""
    event_hash: str = ""
    provenance_entries: tuple[str, ...] = ()
    installation: InstallationReport | None = None
    capability_registry_hash: str = ""
    environment_id: str = ""
    environment_connected: bool = False
    workspace_state: str = ""
    #: Every event the ceremony appended. Usually one.
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "detail": self.detail,
            "born": self.born,
            "record_path": self.record_path,
            "subject_id": self.record.subject_id if self.record else "",
            "birth_id": self.record.birth_id if self.record else "",
            "event_id": self.event_id,
            "event_hash": self.event_hash,
            "provenance_entries": list(self.provenance_entries),
            "capability_registry_hash": self.capability_registry_hash,
            "environment_id": self.environment_id,
            "environment_connected": self.environment_connected,
            "workspace_state": self.workspace_state,
            "installation": self.installation.to_dict() if self.installation else None,
            "events": list(self.events),
        }

    def describe(self) -> str:
        if self.born and self.record:
            return f"born {self.record.subject_id}: {self.status.value}"
        return f"not born ({self.status.value}): {self.detail}"


def _birth_actor(recorder) -> Actor:
    """The actor a birth is recorded under.

    When a provenance recorder is present, the actor is derived from the
    human-owned keyring's active ``SYSTEM`` key, because the ledger signs every
    entry and a keyless process assertion is not a signature. Deriving it from
    the keyring is also what makes the authorship of the birth record
    ``SYSTEM_GENERATED`` rather than asserted: same principle as
    :mod:`birth.authorship`, applied to the ceremony.

    Without a keyring there is no system key to derive, and the actor falls back
    to a process assertion. Recording then fails loudly at the ledger rather than
    succeeding unsigned, which is the correct direction for that failure.
    """
    if recorder is not None:
        keyring = getattr(recorder, "keyring", None)
        if keyring is not None:
            try:
                return keyring.actor_of(keyring.key_for_role(Role.SYSTEM).key_id)
            except BabyLabError:
                pass
    return Actor.system(actor_id="system:birth")


def birth_ceremony(
    subject_id: str = "baby-ai:subject-001",
    experiment_id: str = "EXP-BIRTH-001",
    paths: ProjectPaths | None = None,
    registry: CapabilityRegistry | None = None,
    runtime_probe=None,
    recorder=None,
    actor: Actor | None = None,
    notes: str = "",
    now: Any = None,
) -> CeremonyResult:
    """Create the experimental subject, or explain why not.

    ``recorder`` is an optional
    :class:`provenance.recorder.ProvenanceRecorder`. It is a parameter rather
    than a construction so that this function has no import dependency on the
    provenance package, which keeps the birth path usable in a minimal
    installation.
    """
    root = paths or default_paths()
    registry = registry or CapabilityRegistry()
    environment = unattached_environment()
    workspace = CodeWorkspace.create(root)
    actor = actor or _birth_actor(recorder)
    moment = now if now is not None else Clock().now()
    existing = load_record(root)
    if existing is not None:
        return CeremonyResult(
            status=ModelStatus.READY,
            detail=(
                f"a subject already exists: {existing.subject_id} born "
                f"{existing.born_at}. Milestone 003 permits exactly one birth; "
                "re-running the ceremony is refused rather than repeated."
            ),
            born=False,
            record=existing,
            record_path=str(record_path(root)),
            event_id=existing.birth_event_id,
            capability_registry_hash=registry.registry_hash(),
            environment_id=environment.environment_id,
            environment_connected=environment.connected,
            workspace_state=workspace.state().value,
        )

    # -- verify before writing anything -----------------------------------
    try:
        config = load_config(root)
    except ConfigurationError as exc:
        return CeremonyResult(
            status=ModelStatus.NOT_CONFIGURED,
            detail=str(exc),
            capability_registry_hash=registry.registry_hash(),
            environment_id=environment.environment_id,
            environment_connected=environment.connected,
            workspace_state=workspace.state().value,
        )

    if config.runtime is RuntimeKind.FAKE:
        return CeremonyResult(
            status=ModelStatus.RUNTIME_UNAVAILABLE,
            detail=(
                f"the configuration names the {config.runtime.value!r} runtime, "
                "which is a test double and not a model. A birth record is an "
                "identity, and an identity written against a stand-in would be "
                "indistinguishable from a real one later. Configure "
                f"{RuntimeKind.LLAMA_CPP.value!r} with a verified weights file to "
                "hold a ceremony."
            ),
            capability_registry_hash=registry.registry_hash(),
            environment_id=environment.environment_id,
            environment_connected=environment.connected,
            workspace_state=workspace.state().value,
        )

    if runtime_probe is None:
        runtime_probe = lambda cfg: _default_runtime_probe(cfg, root)

    report = resolve_model_identity(
        config, root, runtime_probe=runtime_probe, now=str(moment)
    )
    if not report.status.is_usable:
        return CeremonyResult(
            status=report.status,
            detail=report.detail,
            installation=report,
            capability_registry_hash=registry.registry_hash(),
            environment_id=environment.environment_id,
            environment_connected=environment.connected,
            workspace_state=workspace.state().value,
        )

    # -- announce, then write the record exactly once ----------------------
    draft = build_record(
        report=report,
        registry=registry,
        environment=environment,
        workspace=workspace,
        subject_id=subject_id,
        notes=notes,
        paths=root,
        now=moment,
    )
    store = EventStore(root.event_store, clock=_clock_for(moment))
    payload = _birth_event_payload(draft, environment, workspace, registry, root)
    event = store.append(BIRTH_EVENT_TYPE, BIRTH_EVENT_SOURCE, payload)

    record = draft.with_birth_event(event.event_id)
    target = write_record(record, root)
    entries: list[str] = []

    if recorder is not None:
        entry = recorder.record_creation(
            target,
            actor,
            experiment_id,
            "birth record written by the birth ceremony; immutable thereafter",
            metadata={
                "birth_id": record.birth_id,
                "subject_id": record.subject_id,
                "birth_event_id": record.birth_event_id,
                "model_sha256": record.model.model_sha256,
                "schema": record.schema,
                "hash": record.hash,
            },
        )
        entries.append(entry.entry_id)

    return CeremonyResult(
        status=ModelStatus.READY,
        detail=(
            f"{record.subject_id} born from {record.model.model_name} "
            f"({record.model.short_hash()}, {record.model.authorship.value}). "
            f"No cognitive capability is implemented; every contract in the "
            f"registry is absent, which is the truthful state of a birth."
        ),
        born=True,
        record=record,
        record_path=str(target),
        event_id=event.event_id,
        event_hash=event.hash,
        provenance_entries=tuple(entries),
        installation=report,
        capability_registry_hash=registry.registry_hash(),
        environment_id=environment.environment_id,
        environment_connected=environment.connected,
        workspace_state=workspace.state().value,
        events=[event.to_dict()],
    )


def _birth_event_payload(
    record: BirthRecord,
    environment,
    workspace,
    registry: CapabilityRegistry,
    root: ProjectPaths,
) -> dict[str, Any]:
    """The payload of ``system.baby_ai.born``.

    Contains what happened and what did not. Notably absent: any assessment of
    the subject. ``capabilities`` reports status values, and the payload says in
    ``note`` that their order means nothing, because a reader skimming a birth
    event six months from now will otherwise read a capability list as a
    capability *ranking*.

    The payload carries no ``birth_record_hash``. It cannot: the record is
    written after this event, and a digest of a document that does not yet exist
    is a thing that can only be wrong. The event names ``birth_id`` and the
    record names this event's id, which is a two-way link between two documents
    that can both verify themselves.
    """
    return {
        "headline": (
            f"Experimental subject {record.subject_id} born from "
            f"{record.model.model_name} ({record.model.short_hash()})"
        ),
        "birth_id": record.birth_id,
        "subject_id": record.subject_id,
        "subject_class": "EXPERIMENTAL_SUBJECT",
        "born_at": record.born_at,
        "model": record.model.to_dict(),
        "authored_by": record.authored_by.value,
        "authored_by_basis": record.authored_by_basis,
        "configuration_hash": record.configuration_hash,
        "capability_registry_hash": record.capability_registry_hash,
        "capabilities": {
            contract.kind.value: contract.status.value for contract in registry
        },
        "capability_order_is_meaningless": True,
        "environment": {
            "environment_id": environment.environment_id,
            "connected": environment.connected,
            "reason": environment.reason(),
        },
        "workspace": {
            "root": root.relative(workspace.root),
            "state": workspace.state().value,
            "subject_written_file_count": workspace.subject_written_file_count(),
        },
        "birth_record_path": root.relative(record_path(root)),
        "birth_record_written_after_this_event": True,
        "note": (
            "The model is inherited pretrained substrate, not the subject's "
            "experience. No capability is implemented, no environment is "
            "connected, and no claim is made about the subject's inner states. "
            "The birth record is written after this event and names it by id; "
            "verify the pair through the birth record, which carries its own hash."
        ),
    }


def _default_runtime_probe(
    config: FoundationConfig, paths: ProjectPaths
) -> tuple[bool, str, str]:
    """Probe the configured runtime for real, unless the caller supplies a probe.

    The ceremony must not treat "the weights are on disk" as sufficient. A
    ceremony that recorded a subject for a runtime which cannot actually load the
    model would be recording a birth that could never be tested, and
    ``RUNTIME_UNAVAILABLE`` is the only place that fact can be reported
    honestly. Tests pass their own probe rather than reaching for a real
    subprocess.
    """
    return LlamaCppModel(config, paths).probe()


def _clock_for(moment) -> Clock:
    class _Fixed(Clock):
        def now(self):
            return moment

    return _Fixed()


__all__ = [
    "BIRTH_EVENT_SOURCE",
    "BIRTH_EVENT_TYPE",
    "TERMINAL_STATUSES",
    "CeremonyResult",
    "InspectionResult",
    "birth_ceremony",
    "birth_status",
    "inspect",
    "workspace_state_of",
]
