"""Persistent ONE demand task, domain-separated DATA and process-only frames."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.services.learning.item_supply.storage_contracts import StorageContract
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1

PersistentSlot = Literal["practice-1", "practice-2", "assessment-1", "assessment-2", "guided-remediation"]
PhaseKind = Literal["candidate", "relation_pack"]
SLOTS: tuple[PersistentSlot, ...] = ("practice-1", "practice-2", "assessment-1", "assessment-2", "guided-remediation")
PROTOCOL = "persistent_pack_runtime_v1"


class PersistentPackPending(ValueError):
    """Closed safe reasons; not provider/source exception bodies."""


class PersistentPackIntentV1(StorageContract):
    schema_version: Literal["persistent_pack_intent_v1"] = "persistent_pack_intent_v1"
    enhancement: Literal["base_only", "prefer_private"] = "base_only"


class PersistentPackTaskRef(StorageContract):
    schema_version: Literal["persistent_pack_task_ref_v1"] = "persistent_pack_task_ref_v1"
    pack_task_id: UUID
    user_id: UUID
    epoch: int = Field(ge=1)
    scope_id: UUID
    mapping_receipt_id: UUID
    demand_id: UUID
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_task_id: UUID


class PersistentPackSlotRef(StorageContract):
    schema_version: Literal["persistent_pack_slot_ref_v1"] = "persistent_pack_slot_ref_v1"
    slot_id: UUID
    logical_item_id: UUID
    slot: PersistentSlot
    public_slot_id: UUID


class PersistentPackTaskRecord(StorageContract):
    schema_version: Literal["persistent_pack_task_record_v1"] = "persistent_pack_task_record_v1"
    ref: PersistentPackTaskRef
    slots: tuple[PersistentPackSlotRef, ...] = Field(min_length=5, max_length=5)
    enhancement: Literal["base_only", "prefer_private"]


class PersistentPublicTaskRecord(StorageContract):
    schema_version: Literal["persistent_public_task_v1"] = "persistent_public_task_v1"
    public_task_id: UUID
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_id: Literal["python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"]
    target_definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_slots: tuple[UUID, ...] = Field(min_length=5, max_length=5)


class PersistentPublicVersionRecord(StorageContract):
    schema_version: Literal["persistent_public_version_v1"] = "persistent_public_version_v1"
    public_task_id: UUID
    public_slot_id: UUID
    slot: PersistentSlot
    revision_id: UUID
    revision_seq: int = Field(ge=1)
    parent_revision_id: UUID | None
    candidate_id: UUID
    specification: FiniteCandidateSpecV1
    root_id: UUID
    artifact_id: UUID | None = None
    published_version_id: UUID | None = None


class PersistentPublicPhaseRecord(StorageContract):
    schema_version: Literal["persistent_public_phase_v1"] = "persistent_public_phase_v1"
    public_task_id: UUID
    public_slot_id: UUID | None
    phase_id: UUID
    revision_id: UUID | None
    kind: PhaseKind
    operation_key: str = Field(min_length=3, max_length=160)
    job_id: UUID
    root_id: UUID
    batch_id: UUID
    lease: JobLeaseV1
    valid_until: datetime
    frame_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_version_id: UUID | None = None
    candidate_version_ids: tuple[UUID, ...] = Field(default=(), max_length=16)


class PersistentPhaseOutcome(StorageContract):
    schema_version: Literal["persistent_phase_outcome_v1"] = "persistent_phase_outcome_v1"
    phase_id: UUID
    status: Literal["qualified", "quality_failed", "blocked", "outcome_unknown", "relation_ready"]
    safe_reason: str = Field(min_length=1, max_length=160)
    artifact_id: UUID | None = None
    published_version_id: UUID | None = None
    relation_receipt_id: UUID | None = None
    usage_state: Literal["known", "unknown"] = "unknown"


class PersistentPackStatus(StorageContract):
    schema_version: Literal["persistent_pack_status_v1"] = "persistent_pack_status_v1"
    status: Literal["preparing", "ready", "blocked", "paused"]
    reason: str = Field(min_length=1, max_length=160)
    qualified_slots: int = Field(ge=0, le=5)
    current_version_ids: tuple[UUID, ...] = Field(max_length=5)
    pack_task_id: UUID


@dataclass(frozen=True)
class IssuedPackPhase:
    """Never serialize or reconstruct. Exact issuing owner validates identity."""
    record: PersistentPublicPhaseRecord
    task: PersistentPackTaskRef = field(repr=False)
    version: PersistentPublicVersionRecord | None = field(repr=False)
    owner: Any = field(repr=False)
    prepared: Any = field(repr=False, default=None)


@dataclass(frozen=True)
class BlockedPackPhase:
    safe_reason: str
    pack_task_id: UUID
