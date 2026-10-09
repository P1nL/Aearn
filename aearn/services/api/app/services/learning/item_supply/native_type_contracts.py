"""Private native projections. Only the owning process issues capabilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.native_publication_contracts import NativeConsumptionProofV1, NativePublicationProofV1
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.diagnostic_policy import diagnostic_warnings
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.pack_contracts import PackSnapshotV2
from app.services.learning.item_supply.review_contracts_v2 import ProviderRunV2
from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.item_supply.type_evidence import ContentIdentityV2, RelationshipRoleV2


class NativeTypeEvidencePending(ValueError):
    """Fixed private failure code; never include source/provider bodies."""


@dataclass(frozen=True)
class NativeResolvedContent:
    source: LearningItemSourceV1
    spec: FiniteCandidateSpecV1
    publication: NativePublicationProofV1
    content: ContentIdentityV2
    facts: IssuedSharedAdmissionFactsV1
    consumption: NativeConsumptionProofV1 | None = None

    @property
    def diagnostic_warnings(self) -> tuple[str, ...]:
        return diagnostic_warnings(self.facts.evaluation)


class NativeRelationReference(StorageContract):
    version_id: UUID
    pointer: Literal["/public", "/verified_answer", "/decision"]
    value_hash: Digest


class NativeRelationJudgment(StorageContract):
    binding_hash: Digest
    conclusion: Literal["nonredundant", "conflict", "uncertain"]
    rationale_evidence_hash: Digest
    references: tuple[NativeRelationReference, ...] = Field(min_length=2, max_length=8)


class NativeRelationReport(StorageContract):
    receipt_id: UUID
    role: RelationshipRoleV2
    actor_id: UUID
    run: ProviderRunV2
    judgments: tuple[NativeRelationJudgment, ...] = Field(min_length=1, max_length=120)
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def bound_interval(self) -> NativeRelationReport:
        if (self.checked_at.tzinfo is None or self.valid_until.tzinfo is None
                or self.checked_at >= self.valid_until
                or len({j.binding_hash for j in self.judgments}) != len(self.judgments)):
            raise ValueError("native_relation_report_invalid")
        return self

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self, NativeRelationReport).model_dump(mode="json"))


class IssuedNativePackCapability:
    """Opaque identity checked against owner registry; constructing one grants nothing."""
    __slots__ = ("eligibility_id", "snapshot")

    def __init__(self, eligibility_id: UUID, snapshot: PackSnapshotV2) -> None:
        self.eligibility_id, self.snapshot = eligibility_id, snapshot
