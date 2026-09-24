"""Claim-scoped scoring evidence; metadata and model assertions are not verification."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates, check_access
from .contracts import FrozenContract, HASH, HANDLE, RagEvidenceBinding, SubjectScope
from .source_policy import SourceAssessment, SourceAuthorization, SourceAuthorizationResolver, check_source


class ExecutionScope(FrozenContract):
    runtime_profile: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9._-]*$")
    input_hash: str = Field(pattern=HASH)
    semantics_hash: str = Field(pattern=HASH)


class VerifiedClaim(FrozenContract):
    """Claim identity and reference only, not a model-verifiable receipt."""
    claim_hash: str = Field(pattern=HASH)
    scope: SubjectScope
    binding: RagEvidenceBinding
    claim_receipt_id: str = Field(pattern=HANDLE)
    applicability: str = Field(min_length=1, max_length=240)
    execution_scope: ExecutionScope | None = None

    @model_validator(mode="after")
    def aligned(self) -> VerifiedClaim:
        if (self.binding.scope != self.scope
                or self.binding.purpose != "assessment_evidence"
                or self.binding.claim_receipt_id != self.claim_receipt_id):
            raise ValueError("claim binding mismatch")
        return self


class ClaimEvidenceReceipt(FrozenContract):
    """Only a trusted resolver may supply this reviewed receipt."""
    receipt_id: str = Field(pattern=HANDLE)
    demand_hash: str = Field(pattern=HASH)
    purpose: Literal["assessment_evidence"]
    admission_receipt_id: str = Field(pattern=HANDLE)
    claim_hash: str = Field(pattern=HASH)
    scope: SubjectScope
    source_handle: str = Field(pattern=HANDLE)
    document_handle: str = Field(pattern=HANDLE)
    document_revision: str = Field(min_length=1, max_length=80)
    document_hash: str = Field(pattern=HASH)
    applicability: str = Field(min_length=1, max_length=240)
    method: Literal["independent_source", "isolated_execution"]
    primary_lineage_family: str | None = Field(default=None, pattern=HANDLE)
    independent_lineage_family: str | None = Field(default=None, pattern=HANDLE)
    independent_source_handle: str | None = Field(default=None, pattern=HANDLE)
    independent_document_handle: str | None = Field(default=None, pattern=HANDLE)
    independent_document_revision: str | None = Field(default=None, min_length=1, max_length=80)
    independent_document_hash: str | None = Field(default=None, pattern=HASH)
    independent_lineage_verified: bool = False
    execution_receipt_id: str | None = Field(default=None, pattern=HANDLE)
    execution_scope: ExecutionScope | None = None
    verified: bool
    revoked: bool


class ClaimReceiptResolver(Protocol):
    def resolve(self, receipt_id: str) -> ClaimEvidenceReceipt | None: ...


class ExecutionReceipt(FrozenContract):
    """Server-resolved actual execution result, not a claim or model assertion."""
    receipt_id: str = Field(pattern=HANDLE)
    claim_hash: str = Field(pattern=HASH)
    demand_hash: str = Field(pattern=HASH)
    scope: SubjectScope
    source_handle: str = Field(pattern=HANDLE)
    document_handle: str = Field(pattern=HANDLE)
    document_revision: str = Field(min_length=1, max_length=80)
    document_hash: str = Field(pattern=HASH)
    execution_scope: ExecutionScope
    verified: bool
    revoked: bool


class ExecutionReceiptResolver(Protocol):
    def resolve(self, receipt_id: str) -> ExecutionReceipt | None: ...


class ClaimDecision(FrozenContract):
    allowed: bool
    reason: str


def check_claim(
    claim: VerifiedClaim, assessment: SourceAssessment, *,
    source_resolver: SourceAuthorizationResolver | None,
    claim_resolver: ClaimReceiptResolver | None,
    execution_resolver: ExecutionReceiptResolver | None = None,
) -> ClaimDecision:
    """Require current exact admission and an independently reviewed claim receipt."""
    try:
        item = VerifiedClaim.model_validate(claim.model_dump(mode="python"))
        binding = item.binding
        reviewed = SourceAssessment.model_validate(assessment.model_dump(mode="python"))
        if (binding.scope != reviewed.scope or binding.source_handle != reviewed.source_handle
                or binding.document_handle != reviewed.document_handle
                or binding.document_revision != reviewed.document_revision
                or binding.document_hash != reviewed.document_hash
                or binding.admission_receipt_id != reviewed.admission_receipt_id):
            return ClaimDecision(allowed=False, reason="BINDING_MISMATCH")
        source = check_source(reviewed, purpose="assessment_evidence", resolver=source_resolver)
        if not source.allowed:
            return ClaimDecision(allowed=False, reason=source.reason)
        if source_resolver is None:
            return ClaimDecision(allowed=False, reason="AUTHORITY_MISSING")
        primary_found = source_resolver.resolve(binding.source_handle, binding.document_handle)
        if primary_found is None:
            return ClaimDecision(allowed=False, reason="AUTHORITY_MISSING")
        primary = SourceAuthorization.model_validate(primary_found.model_dump(mode="python"))
        if (primary.revoked or not primary.readable or primary.scope != binding.scope
                or primary.source_handle != binding.source_handle
                or primary.document_handle != binding.document_handle
                or primary.document_revision != binding.document_revision
                or primary.document_hash != binding.document_hash
                or primary.origin != reviewed.origin
                or primary.reading_level != reviewed.reading_level
                or not primary.reviewed
                or primary.admission_receipt_id != binding.admission_receipt_id
                or primary.storage_receipt_id != reviewed.storage_receipt_id
                or primary.policy_generation != reviewed.policy_generation
                or "assessment_evidence" not in primary.allowed_usages):
            return ClaimDecision(allowed=False, reason="SOURCE_STALE")
        if claim_resolver is None:
            return ClaimDecision(allowed=False, reason="CLAIM_RECEIPT_MISSING")
        found = claim_resolver.resolve(item.claim_receipt_id)
        if found is None:
            return ClaimDecision(allowed=False, reason="CLAIM_RECEIPT_MISSING")
        receipt = ClaimEvidenceReceipt.model_validate(found.model_dump(mode="python"))
        binding = item.binding
        if (not receipt.verified or receipt.revoked
                or receipt.receipt_id != item.claim_receipt_id
                or receipt.demand_hash != binding.demand_hash
                or receipt.purpose != binding.purpose
                or receipt.admission_receipt_id != binding.admission_receipt_id
                or receipt.claim_hash != item.claim_hash or receipt.scope != item.scope
                or receipt.source_handle != binding.source_handle
                or receipt.document_handle != binding.document_handle
                or receipt.document_revision != binding.document_revision
                or receipt.document_hash != binding.document_hash
                or receipt.applicability != item.applicability):
            return ClaimDecision(allowed=False, reason="CLAIM_SCOPE_STALE")
        if receipt.method == "independent_source":
            if (not receipt.independent_lineage_verified or not receipt.primary_lineage_family
                    or receipt.primary_lineage_family != primary.lineage_family
                    or not receipt.independent_lineage_family
                    or receipt.primary_lineage_family == receipt.independent_lineage_family
                    or not receipt.independent_source_handle
                    or not receipt.independent_document_handle
                    or not receipt.independent_document_revision
                    or receipt.independent_source_handle == binding.source_handle
                    or not receipt.independent_document_hash
                    or receipt.independent_document_hash == binding.document_hash
                    or receipt.execution_receipt_id
                    or receipt.execution_scope or item.execution_scope):
                return ClaimDecision(allowed=False, reason="INDEPENDENCE_UNVERIFIED")
            independent_found = source_resolver.resolve(
                receipt.independent_source_handle, receipt.independent_document_handle,
            )
            if independent_found is None:
                return ClaimDecision(allowed=False, reason="INDEPENDENCE_UNVERIFIED")
            independent = SourceAuthorization.model_validate(independent_found.model_dump(mode="python"))
            if (independent.revoked or not independent.readable or not independent.reviewed
                    or independent.scope != binding.scope
                    or independent.source_handle != receipt.independent_source_handle
                    or independent.document_handle != receipt.independent_document_handle
                    or independent.document_revision != receipt.independent_document_revision
                    or independent.document_hash != receipt.independent_document_hash
                    or independent.policy_generation != primary.policy_generation
                    or independent.lineage_family != receipt.independent_lineage_family
                    or independent.lineage_family == primary.lineage_family
                    or not independent.storage_receipt_id or not independent.admission_receipt_id
                    or "assessment_evidence" not in independent.allowed_usages):
                return ClaimDecision(allowed=False, reason="INDEPENDENCE_UNVERIFIED")
        elif (not receipt.execution_receipt_id or not receipt.execution_scope
              or receipt.execution_scope != item.execution_scope
              or receipt.independent_source_handle or receipt.independent_document_hash
              or receipt.independent_document_handle or receipt.independent_document_revision
              or receipt.primary_lineage_family or receipt.independent_lineage_family
              or receipt.independent_lineage_verified):
            return ClaimDecision(allowed=False, reason="EXECUTION_UNVERIFIED")
        if receipt.method == "isolated_execution":
            if execution_resolver is None or receipt.execution_receipt_id is None:
                return ClaimDecision(allowed=False, reason="EXECUTION_UNVERIFIED")
            execution_found = execution_resolver.resolve(receipt.execution_receipt_id)
            if execution_found is None:
                return ClaimDecision(allowed=False, reason="EXECUTION_UNVERIFIED")
            execution = ExecutionReceipt.model_validate(execution_found.model_dump(mode="python"))
            if (not execution.verified or execution.revoked
                    or execution.receipt_id != receipt.execution_receipt_id
                    or execution.claim_hash != item.claim_hash
                    or execution.demand_hash != binding.demand_hash
                    or execution.scope != item.scope
                    or execution.source_handle != binding.source_handle
                    or execution.document_handle != binding.document_handle
                    or execution.document_revision != binding.document_revision
                    or execution.document_hash != binding.document_hash
                    or execution.execution_scope != item.execution_scope):
                return ClaimDecision(allowed=False, reason="EXECUTION_UNVERIFIED")
        return ClaimDecision(allowed=True, reason="CLAIM_VERIFIED_REFERENCE")
    except Exception:  # read-only resolver failure is closed
        return ClaimDecision(allowed=False, reason="INVALID_CONTRACT")


def authorize_assessment_claim(
    claim: VerifiedClaim, assessment: SourceAssessment, *,
    request: AccessRequest, gates: AutonomousGates | None,
    authority_resolver: AuthorityResolver | None,
    source_resolver: SourceAuthorizationResolver | None,
    claim_resolver: ClaimReceiptResolver | None,
    execution_resolver: ExecutionReceiptResolver | None = None,
    now: datetime,
) -> ClaimDecision:
    """Final assessment entrypoint: actor/budget, source usage, exact claim receipt."""
    access = check_access(request, gates=gates, resolver=authority_resolver, now=now)
    if not access.allowed:
        return ClaimDecision(allowed=False, reason=access.reason)
    try:
        item = VerifiedClaim.model_validate(claim.model_dump(mode="python"))
        req = AccessRequest.model_validate(request.model_dump(mode="python"))
        if (req.action != "consume" or req.demand_hash != item.binding.demand_hash
                or req.scope != item.scope or req.purpose != "assessment_evidence"):
            return ClaimDecision(allowed=False, reason="CLAIM_DEMAND_MISMATCH")
        return check_claim(item, assessment, source_resolver=source_resolver, claim_resolver=claim_resolver,
                           execution_resolver=execution_resolver)
    except Exception:  # read-only resolver failure is closed
        return ClaimDecision(allowed=False, reason="INVALID_CONTRACT")