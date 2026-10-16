"""PRIVATE native DATA and opaque same-process capabilities; no JSON grants."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.contracts import Digest, require_aware
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pack_contracts import PackSnapshotV2
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvidenceV2
from app.services.learning.item_supply.diagnostic_policy import AdmissionEvaluation, ReviewBundle
from app.services.learning.item_supply.finite_task_ambiguity import FiniteAmbiguityReceiptV1
from app.services.learning.item_supply.storage_contracts import StorageContract
from app.services.learning.item_supply.type_evidence import ContentIdentityV2
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

PRIVATE_AUTHORITY_TABLES = tuple('tutor_item_supply_private_' + n for n in (
    'native_quality_evidence', 'native_publications', 'native_eligibility',
    'native_exposure_origins', 'native_exposure_snapshots', 'native_assessment_reservations',
    'native_consumer_receipts', 'native_artifact_bindings',
))


class PrivateNativePending(ValueError):
    """Constant safe internal reason; never export exception/provider text."""


class PrivateSlotRef(StorageContract):
    pack_task_id: UUID
    slot_id: UUID
    business_item_id: UUID
    root_id: UUID
    mapping_receipt_id: UUID
    user_id: UUID
    epoch: int = Field(ge=1)
    scope_id: UUID
    goal_scope_id: UUID
    slot: Literal['practice', 'assessment', 'remediation']
    parent_version_id: UUID | None = None


class PrivateNativeQualityV1(StorageContract):
    schema_version: Literal['private_native_quality_v1'] = 'private_native_quality_v1'
    receipt_id: UUID
    ref: PrivateSlotRef
    lease: JobLeaseV1
    generation_artifact_id: UUID
    version_id: UUID
    source: LearningItemSourceV1 = Field(repr=False)
    spec: FiniteCandidateSpecV1 = Field(repr=False)
    request: GenerationRequestV2 = Field(repr=False)
    source_receipts: tuple[SourceReceiptV2, ...] = Field(min_length=1, max_length=12, repr=False)
    validation_receipt_id: UUID
    validation: CandidateValidationV2 = Field(repr=False)
    blind_receipt_id: UUID
    review_receipt_id: UUID
    bundle: ReviewBundle = Field(repr=False)
    ambiguity: FiniteAmbiguityReceiptV1 = Field(repr=False)
    machine_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=16)
    clause_proof_hash: Digest
    evidence: AdmissionEvidenceV2 = Field(repr=False)
    evaluation: AdmissionEvaluation = Field(repr=False)
    normal_readmission_id: UUID | None = None
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode='after')
    def exact_private(self) -> PrivateNativeQualityV1:
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if (self.lease.visibility != 'private' or self.lease.owner_id != self.ref.user_id
                or self.lease.owner_epoch != self.ref.epoch
                or not self.checked_at < self.valid_until <= min(self.lease.expires_at, self.lease.parent_deadline)
                or self.spec.allocation.slot != self.ref.slot
                or self.source.blueprint != self.request.blueprint
                or self.validation.source_hash != self.source.source_hash
                or self.validation.content_hash != self.source.content_hash
                or self.evidence.binding != self.bundle.binding
                or self.evaluation.binding != self.bundle.binding
                or self.evaluation.publication_enabled
                or self.evaluation.disposition != 'eligible_internal'):
            raise ValueError('private_native_quality_binding_required')
        return self

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(self.model_dump(mode='json'))


class PrivateNativePublicationV1(StorageContract):
    schema_version: Literal['private_native_publication_v1'] = 'private_native_publication_v1'
    publication_id: UUID
    quality_id: UUID
    ref: PrivateSlotRef
    version_id: UUID
    item_handle: str = Field(pattern=r'^lip:v2:[0-9a-f-]{36}$')
    source_hash: Digest
    content_hash: Digest
    materialization_id: UUID
    exercise_version_id: UUID
    exercise_content_hash: Digest
    rubric_hash: Digest
    materialization_hash: Digest
    quality_hash: Digest
    runner_material: dict[str, Any] = Field(repr=False)
    checked_at: datetime
    producer_valid_until: datetime

    @model_validator(mode='after')
    def historical_authority(self) -> PrivateNativePublicationV1:
        require_aware(self.checked_at)
        require_aware(self.producer_valid_until)
        if self.item_handle != 'lip:v2:' + str(self.version_id) or self.checked_at >= self.producer_valid_until:
            raise ValueError('private_publication_history_invalid')
        return self

    @property
    def publication_hash(self) -> str:
        return canonical_hash(self.model_dump(mode='json'))


@dataclass(frozen=True)
class PrivateResolvedContent:
    publication: PrivateNativePublicationV1
    quality: PrivateNativeQualityV1 = field(repr=False)
    content: ContentIdentityV2
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    source_set_hash: str | None = None


class IssuedPrivatePackCapability:
    """Constructing/copying this object grants nothing; owner identity registry is required."""
    __slots__ = ('eligibility_id', 'snapshot')

    def __init__(self, eligibility_id: UUID, snapshot: PackSnapshotV2) -> None:
        self.eligibility_id, self.snapshot = eligibility_id, snapshot


@dataclass(frozen=True)
class PrivateTeachingDeliveryContext:
    exposure_owner: Any = field(repr=False)
    mapping_receipt_id: UUID
    reservation_id: UUID
    selected_version_id: UUID
    run_id: UUID
    pack_task_id: UUID
    _prepared: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    purpose: Literal['knowledge_check','remediation','transfer_check'] = 'knowledge_check'
    parent_artifact_id: UUID | None = None


@dataclass(frozen=True)
class IssuedPrivateConsumerAuthority:
    owner: Any = field(repr=False)
    receipt_id: UUID
    artifact_id: str
    artifact_version: int
    version_id: UUID
    mode: str
    action: str


@dataclass(frozen=True)
class PrivateEnhancementReady:
    base: Any = field(repr=False)
    capability: IssuedPrivatePackCapability = field(repr=False)
    reservation_id: UUID = field(repr=False)
    task_ref: Any = field(repr=False)
    selection: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class PrivateEnhancementResult:
    """Server-private handoff; export only the original safe .learner projection."""
    learner: Any
    enhancement_status: Literal['ready', 'preparing', 'not_started', 'waiting_ended', 'unavailable']
    base: Any = field(default=None, repr=False)
    ready: PrivateEnhancementReady | None = field(default=None, repr=False)
    diagnostic: str = field(default='current_authority_unavailable', repr=False)
    fallback: Any = field(default=None, repr=False)

