"""C claim review delegates final evidence checks to A's existing contracts.

No receipt is minted from model text, a lineage label, or an unrun execution.
Implementations of these ports must be repository-backed and independently audited.
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field

from .assessment_contracts import (
    ClaimDecision, ClaimEvidenceReceipt, ClaimReceiptResolver, ExecutionReceiptResolver,
    VerifiedClaim, check_claim,
)
from .contracts import FrozenContract, HASH, HANDLE, SourceAssessment, SubjectScope
from .source_policy import SourceAuthorizationResolver


class IndependentLineageReview(FrozenContract):
    """Independent reviewer finding tied to one exact claim and both revisions."""

    claim_receipt_id: str = Field(pattern=HANDLE)
    claim_hash: str = Field(pattern=HASH)
    demand_hash: str = Field(pattern=HASH)
    scope: SubjectScope
    primary_source_handle: str = Field(pattern=HANDLE)
    primary_document_handle: str = Field(pattern=HANDLE)
    primary_document_revision: str = Field(min_length=1, max_length=80)
    primary_document_hash: str = Field(pattern=HASH)
    primary_lineage_family: str = Field(pattern=HANDLE)
    independent_source_handle: str = Field(pattern=HANDLE)
    independent_document_handle: str = Field(pattern=HANDLE)
    independent_document_revision: str = Field(min_length=1, max_length=80)
    independent_document_hash: str = Field(pattern=HASH)
    independent_lineage_family: str = Field(pattern=HANDLE)
    review_receipt_id: str = Field(pattern=HANDLE)
    status: Literal["confirmed", "unresolved", "rejected", "revoked"]


class _ConsistentClaimResolver:
    """Reject a receipt changed between C review and A current-source check."""

    def __init__(self, port: ClaimReceiptResolver, expected: ClaimEvidenceReceipt):
        self.port = port
        self.expected = expected

    def resolve(self, receipt_id: str) -> ClaimEvidenceReceipt | None:
        found = self.port.resolve(receipt_id)
        if found is None:
            return None
        current = ClaimEvidenceReceipt.model_validate(found.model_dump(mode="python"))
        return current if current == self.expected else None


class IndependentLineageResolver(Protocol):
    """Current evidence-based lineage review, never a URL/author comparison alone."""

    def resolve(self, claim_receipt_id: str) -> IndependentLineageReview | None: ...


def review_claim(
    claim: VerifiedClaim, assessment: SourceAssessment, *,
    source_resolver: SourceAuthorizationResolver | None,
    claim_resolver: ClaimReceiptResolver | None,
    lineage_resolver: IndependentLineageResolver | None,
    execution_resolver: ExecutionReceiptResolver | None,
) -> ClaimDecision:
    """Review exact scoring evidence; A remains the sole consumer check.

    A separate persisted claim receipt must already exist. For independent-source
    claims C additionally checks current lineage evidence; for execution claims A
    requires its independently resolved actual execution receipt and exact scope.
    """
    try:
        item = VerifiedClaim.model_validate(claim.model_dump(mode="python"))
        reviewed = SourceAssessment.model_validate(assessment.model_dump(mode="python"))
        if claim_resolver is None:
            return ClaimDecision(allowed=False, reason="CLAIM_RECEIPT_MISSING")
        found = claim_resolver.resolve(item.claim_receipt_id)
        if found is None:
            return ClaimDecision(allowed=False, reason="CLAIM_RECEIPT_MISSING")
        receipt = ClaimEvidenceReceipt.model_validate(found.model_dump(mode="python"))
        if receipt.method == "independent_source":
            if lineage_resolver is None:
                return ClaimDecision(allowed=False, reason="INDEPENDENCE_UNVERIFIED")
            lineage_found = lineage_resolver.resolve(item.claim_receipt_id)
            if lineage_found is None:
                return ClaimDecision(allowed=False, reason="INDEPENDENCE_UNVERIFIED")
            lineage = IndependentLineageReview.model_validate(lineage_found.model_dump(mode="python"))
            binding = item.binding
            if (lineage.status != "confirmed"
                    or lineage.claim_receipt_id != item.claim_receipt_id
                    or lineage.claim_hash != item.claim_hash
                    or lineage.demand_hash != binding.demand_hash or lineage.scope != item.scope
                    or lineage.primary_source_handle != binding.source_handle
                    or lineage.primary_document_handle != binding.document_handle
                    or lineage.primary_document_revision != binding.document_revision
                    or lineage.primary_document_hash != binding.document_hash
                    or lineage.primary_lineage_family != receipt.primary_lineage_family
                    or lineage.independent_source_handle != receipt.independent_source_handle
                    or lineage.independent_document_handle != receipt.independent_document_handle
                    or lineage.independent_document_revision != receipt.independent_document_revision
                    or lineage.independent_document_hash != receipt.independent_document_hash
                    or lineage.independent_lineage_family != receipt.independent_lineage_family
                    or lineage.primary_lineage_family == lineage.independent_lineage_family
                    or lineage.primary_source_handle == lineage.independent_source_handle):
                return ClaimDecision(allowed=False, reason="INDEPENDENCE_UNVERIFIED")
        elif execution_resolver is None:
            return ClaimDecision(allowed=False, reason="EXECUTION_UNVERIFIED")
        return check_claim(item, reviewed, source_resolver=source_resolver,
                           claim_resolver=_ConsistentClaimResolver(claim_resolver, receipt),
                           execution_resolver=execution_resolver)
    except Exception:  # missing/stale/malformed trusted evidence is never success
        return ClaimDecision(allowed=False, reason="INVALID_CONTRACT")
