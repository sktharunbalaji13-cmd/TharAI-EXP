"""The birth record: one immutable statement of what a subject was born as.

One subject, one record, written once
-------------------------------------
Milestone 003 permits exactly one experimental subject, so there is exactly one
birth record at ``human_control/birth_records/BIRTH.json``. :func:`load_record`
refuses a second one; :func:`write_record` refuses to overwrite. The reasons are
worth stating, because a second record would be a serious problem:

* It would give the experiment two subjects without the design saying so.
* It would invite "which one is real?", and the honest answer would be that the
  laboratory had quietly grown a second one.
* The record's content is derived from the model installation, so a second
  record would have to differ in model, and a silent model change is precisely
  what this project refuses.

What is in it, and what is not
------------------------------
In: the model identity by digest, the configuration hash, the capability registry
hash, the environment and workspace state, and the event that announced the
birth.

Not in it: anything about the subject's character, progress, mood, or future.
Those are the things Milestones 004 and 005 are supposed to earn, and putting
placeholders in the record now would make an empty field look like a measurement.

The chain
---------
Each record carries ``prev_hash`` and its own ``hash``, exactly as an event does.
Modifying the record breaks the chain at that point. The difference from an event
is that a birth record is not append-only but *immutable*: there is no second
version to append, so a modified file is simply wrong, and
:func:`verify_record` says so.

There is no function in this module that updates a record on disk.
:func:`write_record` creates it once and refuses to overwrite, and the ceremony
assembles the complete record — including the id of the event that announced the
birth — before that single write. An earlier design wrote the record, appended
the event, then rewrote the record to backfill the event id; that made the bytes
of a supposedly immutable document change underneath their own hash, and left the
announcement citing a digest that no longer existed on disk. The record is now
written exactly once, so its hash describes the only bytes it will ever have.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from babylab.clock import Clock, format_timestamp
from babylab.errors import IntegrityError, ValidationError
from babylab.hashing import canonical_bytes, sha256_hex
from babylab.paths import ProjectPaths, default_paths
from birth.authorship import AuthorshipClass
from birth.cognitive import CapabilityRegistry
from birth.identity import InstallationReport, ModelIdentity, ModelStatus

BIRTH_RECORD_SCHEMA = "babylab/birth-record/v1"

#: Recorded inside the birth event so a reader does not have to guess whether the
#: ceremony produced a subject or a rehearsal.
SUBJECT_CLASS = "EXPERIMENTAL_SUBJECT"

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class BirthRecord:
    """One immutable birth."""

    birth_id: str
    subject_id: str
    born_at: str
    model: ModelIdentity
    model_status: ModelStatus
    model_path: str
    #: Digest of the weights as actually observed on disk, which must equal
    #: ``model.model_sha256``. Kept separately so a mismatch is visible in the
    #: record rather than hidden by equality.
    observed_model_sha256: str
    configuration_hash: str
    capability_registry_hash: str
    capability_summary: dict[str, str]
    environment_id: str
    environment_connected: bool
    environment_hash: str
    workspace_root: str
    workspace_state: str
    authored_by: AuthorshipClass = AuthorshipClass.INHERITED_PRETRAINED
    authored_by_basis: str = ""
    #: Id of the event announcing this birth. The record is built *after* the
    #: event is appended, so this is never empty in a written record, and there
    #: is no on-disk path that can fill it in later.
    birth_event_id: str = ""
    notes: str = ""
    prev_hash: str = GENESIS_HASH
    hash: str = ""
    schema: str = BIRTH_RECORD_SCHEMA

    def __post_init__(self) -> None:
        if not self.birth_id:
            raise ValidationError("birth_id must be a non-empty string")
        if not self.subject_id:
            raise ValidationError("subject_id must be a non-empty string")
        if not self.model.model_sha256:
            raise ValidationError("a birth record must name a model by digest")
        if self.observed_model_sha256 and self.observed_model_sha256 != self.model.model_sha256:
            raise ValidationError(
                "observed_model_sha256 does not match the recorded model digest; "
                "the record would describe a model that was not the one present"
            )

    # -- hashing ----------------------------------------------------------
    def hashed_body(self) -> dict[str, Any]:
        """Fields covered by the record hash. ``hash`` and ``prev_hash`` excluded."""
        body = self.to_dict()
        body.pop("hash", None)
        body.pop("prev_hash", None)
        return body

    def compute_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.hashed_body()))

    def seal(self) -> "BirthRecord":
        sealed = self.compute_hash()
        return BirthRecord(**{**self.__dict__, "hash": sealed})

    def with_birth_event(self, event_id: str) -> "BirthRecord":
        """Return a resealed record that names the announcing event.

        Called *before* the record is written, and only then. The event is
        appended first precisely so that this can be an in-memory operation: the
        record is then written once, complete and sealed, and there is no code
        path anywhere that modifies the file afterwards. An earlier design wrote
        the record, announced the birth, and then rewrote the record to backfill
        the event id; that made the bytes of a supposedly immutable record change
        under their own hash and left the event pointing at a digest that no
        longer existed on disk.
        """
        if not event_id:
            raise ValidationError("event_id must be a non-empty string")
        if self.birth_event_id and self.birth_event_id != event_id:
            raise ValidationError(
                f"record already names birth event {self.birth_event_id}; "
                f"refusing to rename it to {event_id}"
            )
        return BirthRecord(**{**self.__dict__, "birth_event_id": event_id}).seal()

    def verify_hash(self) -> bool:
        return self.compute_hash() == self.hash

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "birth_id": self.birth_id,
            "subject_id": self.subject_id,
            "subject_class": SUBJECT_CLASS,
            "born_at": self.born_at,
            "model": self.model.to_dict(),
            "model_status": self.model_status.value,
            "model_path": self.model_path,
            "observed_model_sha256": self.observed_model_sha256,
            "configuration_hash": self.configuration_hash,
            "capability_registry_hash": self.capability_registry_hash,
            "capability_summary": dict(self.capability_summary),
            "environment_id": self.environment_id,
            "environment_connected": self.environment_connected,
            "environment_hash": self.environment_hash,
            "workspace_root": self.workspace_root,
            "workspace_state": self.workspace_state,
            "authored_by": self.authored_by.value,
            "authored_by_basis": self.authored_by_basis,
            "birth_event_id": self.birth_event_id,
            "notes": self.notes,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "BirthRecord":
        if not isinstance(data, dict):
            raise ValidationError("birth record must be a JSON object")
        schema = data.get("schema")
        if schema != BIRTH_RECORD_SCHEMA:
            raise ValidationError(
                f"unsupported birth record schema {schema!r}; expected {BIRTH_RECORD_SCHEMA!r}"
            )
        model_data = data.get("model")
        if not isinstance(model_data, dict):
            raise ValidationError("birth record is missing its model identity")
        return cls(
            birth_id=data["birth_id"],
            subject_id=data["subject_id"],
            born_at=data["born_at"],
            model=ModelIdentity.from_dict(model_data),
            model_status=ModelStatus(data["model_status"]),
            model_path=data.get("model_path", ""),
            observed_model_sha256=data.get("observed_model_sha256", ""),
            configuration_hash=data["configuration_hash"],
            capability_registry_hash=data["capability_registry_hash"],
            capability_summary=data.get("capability_summary", {}),
            environment_id=data.get("environment_id", ""),
            environment_connected=bool(data.get("environment_connected", False)),
            environment_hash=data.get("environment_hash", ""),
            workspace_root=data.get("workspace_root", ""),
            workspace_state=data.get("workspace_state", ""),
            authored_by=AuthorshipClass(
                data.get("authored_by", AuthorshipClass.INHERITED_PRETRAINED.value)
            ),
            authored_by_basis=data.get("authored_by_basis", ""),
            birth_event_id=data.get("birth_event_id", ""),
            notes=data.get("notes", ""),
            prev_hash=data.get("prev_hash", GENESIS_HASH),
            hash=data.get("hash", ""),
            schema=schema,
        )

    # -- narrative --------------------------------------------------------
    def describe(self) -> str:
        return (
            f"{self.subject_id} born {self.born_at} from "
            f"{self.model.model_name} ({self.model.short_hash()}, "
            f"{self.model.authorship.value}); capabilities: "
            f"{sum(1 for value in self.capability_summary.values() if value == 'IMPLEMENTED')}"
            f"/{len(self.capability_summary)} implemented; environment connected: "
            f"{self.environment_connected}"
        )


def build_record(
    report: InstallationReport,
    registry: CapabilityRegistry,
    environment,
    workspace,
    subject_id: str = "baby-ai:subject-001",
    notes: str = "",
    event_id: str = "",
    paths: ProjectPaths | None = None,
    now: Any = None,
) -> BirthRecord:
    """Assemble a sealed birth record from verified state.

    ``report`` must be a *usable* installation. There is deliberately no
    ``allow_unusable`` flag: a record describing a model that is not installed
    would be a birth of nothing, and the specification is explicit that a
    ceremony without a real model reports ``MODEL_NOT_INSTALLED`` instead of
    inventing a subject.

    ``event_id`` is the id of the event announcing the birth. It is a parameter
    rather than a later backfill so that the returned record is complete and
    sealed the moment it exists, and the ceremony can write it exactly once.

    Paths inside the record are stored relative to the project root. An absolute
    path would embed one machine's directory layout in a sealed, hashed document
    and make the record unverifiable anywhere else, which is a poor property for
    the one artefact that has to remain checkable years from now.

    Provenance is deliberately *not* stored inside the record. A provenance entry
    carries the digest of the file it describes, so a record naming its own entry
    would have to contain a digest of a digest of itself. The entry is found in
    the ledger by path instead, which is where a verifier should look and which
    is signed.
    """
    if not report.status.is_usable or report.identity is None:
        raise ValidationError(
            "refusing to write a birth record: "
            f"{report.describe()}. A birth requires an installed, verified model."
        )
    root = paths or default_paths()
    moment = now if now is not None else Clock().now()
    return BirthRecord(
        birth_id=f"BIRTH-{uuid.uuid4().hex[:12]}",
        subject_id=subject_id,
        born_at=format_timestamp(moment),
        model=report.identity,
        model_status=report.status,
        model_path=root.relative(report.model_path) if report.model_path else "",
        observed_model_sha256=report.observed_sha256,
        configuration_hash=report.identity.configuration_hash,
        capability_registry_hash=registry.registry_hash(),
        capability_summary={
            contract.kind.value: contract.status.value for contract in registry
        },
        environment_id=environment.environment_id,
        environment_connected=environment.connected,
        environment_hash=environment.content_hash(),
        workspace_root=root.relative(workspace.root),
        workspace_state=workspace.state().value,
        authored_by=AuthorshipClass.INHERITED_PRETRAINED,
        authored_by_basis=(
            "The foundation model is third-party pretrained substrate. Nothing in "
            "this record is BABY_AI_AUTHORED, and no field in the system can make "
            "it so: authorship is derived from the artifact's kind and from the "
            "keyring, never from a value the artifact supplies."
        ),
        birth_event_id=event_id,
        notes=notes
        or (
            "Born with no implemented cognitive capability. Every contract in the "
            "registry is UNAVAILABLE or NOT_YET_IMPLEMENTED, and the capability "
            "registry is an unordered set, so no developmental order is implied."
        ),
    ).seal()


def record_path(paths: ProjectPaths | None = None) -> Path:
    return (paths or default_paths()).birth_record


def load_record(paths: ProjectPaths | None = None) -> BirthRecord | None:
    """Read the birth record, or ``None`` when the laboratory has no subject."""
    target = record_path(paths)
    if not target.exists():
        return None
    import json

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError(
            f"birth record at {target} is not valid JSON: {exc}. The record is "
            "immutable, so this is corruption rather than an in-progress write."
        ) from exc
    return BirthRecord.from_dict(data)


def write_record(record: BirthRecord, paths: ProjectPaths | None = None) -> Path:
    """Write the record, refusing to overwrite an existing one.

    A second birth is refused here rather than permitted and then audited. The
    cost of a legitimate need for a second subject — restarting the experiment —
    is much lower than the cost of a quietly duplicated subject.
    """
    from babylab.storage import atomic_write_text
    from babylab.hashing import canonical_json

    target = record_path(paths)
    if target.exists():
        existing = load_record(paths)
        raise IntegrityError(
            f"a birth record already exists at {target}"
            + (f" for {existing.subject_id}" if existing else "")
            + ". Milestone 003 permits exactly one subject; refusing to write a "
            "second one. Removing this file is a deliberate act and will show up "
            "as a provenance deletion."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, canonical_json(record.to_dict()) + "\n")
    return target


def verify_record(paths: ProjectPaths | None = None) -> tuple[bool, list[str]]:
    """Check the on-disk record. Returns ``(ok, problems)``."""
    target = record_path(paths)
    if not target.exists():
        return False, [f"no birth record at {target}"]
    try:
        record = load_record(paths)
    except (IntegrityError, ValidationError) as exc:
        return False, [str(exc)]
    assert record is not None
    problems: list[str] = []
    if not record.verify_hash():
        problems.append(
            f"birth record hash mismatch: stored {record.hash[:12]}..., computed "
            f"{record.compute_hash()[:12]}.... The record has been modified since "
            "it was sealed."
        )
    if not record.birth_event_id:
        problems.append(
            "birth record names no birth event. A ceremony that did not announce "
            "itself is incomplete."
        )
    if not record.observed_model_sha256:
        problems.append(
            "birth record records no observed model digest, so the presence of "
            "the model at birth cannot be corroborated"
        )
    if record.model_status is not ModelStatus.READY:
        problems.append(
            f"birth record was written with model status "
            f"{record.model_status.value}; a birth requires READY"
        )
    return (not problems), problems


__all__ = [
    "BIRTH_RECORD_SCHEMA",
    "GENESIS_HASH",
    "SUBJECT_CLASS",
    "BirthRecord",
    "build_record",
    "load_record",
    "record_path",
    "verify_record",
    "write_record",
]
