"""Native shared validation staging, never admission or publication authority."""
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID
from app.services.learning.item_bank.contracts import LearningItemSourceV1
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import FiniteCandidateValidationInputsV1
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2


@dataclass(frozen=True)
class PreparedSharedValidation:
    preparation_id: UUID
    lease: JobLeaseV1
    artifact_id: UUID
    artifact_hash: str
    source: LearningItemSourceV1
    request: GenerationRequestV2
    spec: FiniteCandidateSpecV1
    inputs: FiniteCandidateValidationInputsV1
    resources: ResourceAmounts | None
    reservation_id: UUID | None


@dataclass(frozen=True)
class SharedValidationResult:
    validation: CandidateValidationV2 | None
    actual: ResourceAmounts | None
    terminal_receipts: tuple[dict[str, object], ...]
    safe_reason: str


@dataclass(frozen=True)
class SharedValidationStageResult:
    state: str
    safe_reason: str
    validation_receipt_id: UUID | None = None
    evidence_id: UUID | None = None
