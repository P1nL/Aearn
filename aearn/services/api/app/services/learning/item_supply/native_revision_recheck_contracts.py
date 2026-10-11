"""Partial historical-clause bindings, strictly DATA and never discharge authority."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2
from app.services.learning.item_supply.review_deliberation_contracts import ReviewDisputeV1
from app.services.learning.item_supply.storage_contracts import StorageContract


class NativeRevisionDisputeEvidenceV1(StorageContract):
    original_dispute: ReviewDisputeV1
    new_binding: CandidateBindingV2
    validation_receipt_id: UUID
    validation_hash: Digest
    review_receipt_id: UUID
    review_hash: Digest
    state: Literal["check_supported", "unsupported", "unresolved"]
    supported_check: Literal["finite_kc_unique_truth_v1"] | None = None
    issuer_evidence_hash: Digest | None = None
    safe_reason: Literal["finite_property_only_not_claim_resolution", "no_clause_specific_adapter", "new_material_dispute_retained"]
    historical_finding_resolved: Literal[False] = False
    publication_enabled: Literal[False] = False

    @model_validator(mode="after")
    def bounded_check(self) -> NativeRevisionDisputeEvidenceV1:
        if (self.state == "check_supported" and (self.supported_check is None or self.issuer_evidence_hash is None)) or (
                self.state != "check_supported" and (self.supported_check is not None or self.issuer_evidence_hash is not None)):
            raise ValueError("partial check evidence mismatch")
        reasons = {"check_supported": "finite_property_only_not_claim_resolution",
                   "unsupported": "no_clause_specific_adapter",
                   "unresolved": "new_material_dispute_retained"}
        if self.safe_reason != reasons[self.state]:
            raise ValueError("partial check state/reason mismatch")
        return self
