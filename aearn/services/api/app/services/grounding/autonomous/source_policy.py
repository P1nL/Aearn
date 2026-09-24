"""Storage and per-purpose source admission are separate from candidate metadata."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates, check_access
from .contracts import (
    FrozenContract, HASH, HANDLE, RagEvidenceBinding, SourceAssessment,
    SubjectScope, Usage,
)


class SourceAuthorization(FrozenContract):
    """Current resolver-owned storage and admission coordinates."""
    scope: SubjectScope
    source_handle: str = Field(pattern=HANDLE)
    lineage_family: str = Field(pattern=HANDLE)
    origin: Literal["official", "maintainer", "tutorial", "repository", "community", "blog"]
    reading_level: Literal["beginner", "intermediate", "advanced"]
    reviewed: bool
    document_handle: str = Field(pattern=HANDLE)
    document_revision: str = Field(min_length=1, max_length=80)
    document_hash: str = Field(pattern=HASH)
    storage_receipt_id: str | None = Field(default=None, pattern=HANDLE)
    admission_receipt_id: str | None = Field(default=None, pattern=HANDLE)
    allowed_usages: tuple[Usage, ...] = Field(max_length=3)
    policy_generation: int = Field(ge=1)
    revoked: bool
    readable: bool


class SourceAuthorizationResolver(Protocol):
    def resolve(self, source_handle: str, document_handle: str) -> SourceAuthorization | None: ...


class SourceDecision(FrozenContract):
    allowed: bool
    reason: str


def check_source(
    assessment: SourceAssessment, *, purpose: Usage | None,
    resolver: SourceAuthorizationResolver | None,
) -> SourceDecision:
    """None purpose checks storage only; usage requires reviewed exact admission."""
    try:
        current_assessment = SourceAssessment.model_validate(assessment.model_dump(mode="python"))
        if resolver is None:
            return SourceDecision(allowed=False, reason="AUTHORITY_MISSING")
        found = resolver.resolve(current_assessment.source_handle, current_assessment.document_handle)
        if found is None:
            return SourceDecision(allowed=False, reason="AUTHORITY_MISSING")
        current = SourceAuthorization.model_validate(found.model_dump(mode="python"))
        if (current.revoked or not current.readable or current.scope != current_assessment.scope
                or current.source_handle != current_assessment.source_handle
                or current.document_handle != current_assessment.document_handle
                or current.document_revision != current_assessment.document_revision
                or current.document_hash != current_assessment.document_hash
                or current.origin != current_assessment.origin
                or current.reading_level != current_assessment.reading_level
                or current.policy_generation != current_assessment.policy_generation):
            return SourceDecision(allowed=False, reason="SOURCE_STALE")
        if (not current.storage_receipt_id
                or current.storage_receipt_id != current_assessment.storage_receipt_id):
            return SourceDecision(allowed=False, reason="STORAGE_DENIED")
        if purpose is None:
            return SourceDecision(allowed=True, reason="STORAGE_ALLOWED")
        if (current_assessment.status != "reviewed" or not current.reviewed
                or not current.admission_receipt_id
                or current.admission_receipt_id != current_assessment.admission_receipt_id
                or len(set(current.allowed_usages)) != len(current.allowed_usages)
                or purpose not in current.allowed_usages
                or purpose not in current_assessment.allowed_usages):
            return SourceDecision(allowed=False, reason="USAGE_DENIED")
        return SourceDecision(allowed=True, reason="USAGE_ALLOWED")
    except Exception:  # read-only resolver failure is closed
        return SourceDecision(allowed=False, reason="INVALID_CONTRACT")


def check_binding(
    binding: RagEvidenceBinding, assessment: SourceAssessment, *,
    resolver: SourceAuthorizationResolver | None,
) -> SourceDecision:
    try:
        item = RagEvidenceBinding.model_validate(binding.model_dump(mode="python"))
        current_assessment = SourceAssessment.model_validate(assessment.model_dump(mode="python"))
        if (item.scope != current_assessment.scope
                or item.source_handle != current_assessment.source_handle
                or item.document_handle != current_assessment.document_handle
                or item.document_revision != current_assessment.document_revision
                or item.document_hash != current_assessment.document_hash
                or item.admission_receipt_id != current_assessment.admission_receipt_id):
            return SourceDecision(allowed=False, reason="BINDING_MISMATCH")
        if item.purpose == "assessment_evidence":
            return SourceDecision(allowed=False, reason="CLAIM_VERIFICATION_REQUIRED")
        return check_source(current_assessment, purpose=item.purpose, resolver=resolver)
    except Exception:  # read-only resolver failure is closed
        return SourceDecision(allowed=False, reason="INVALID_CONTRACT")


def authorize_binding(
    binding: RagEvidenceBinding, assessment: SourceAssessment, *,
    request: AccessRequest, gates: AutonomousGates | None,
    authority_resolver: AuthorityResolver | None,
    source_resolver: SourceAuthorizationResolver | None, now: datetime,
) -> SourceDecision:
    """Exact demand/scope/action plus current per-purpose admission, both required."""
    access = check_access(request, gates=gates, resolver=authority_resolver, now=now)
    if not access.allowed:
        return SourceDecision(allowed=False, reason=access.reason)
    try:
        item = RagEvidenceBinding.model_validate(binding.model_dump(mode="python"))
        req = AccessRequest.model_validate(request.model_dump(mode="python"))
        if (req.action != "consume" or req.demand_hash != item.demand_hash
                or req.scope != item.scope or req.purpose != item.purpose):
            return SourceDecision(allowed=False, reason="BINDING_DEMAND_MISMATCH")
        return check_binding(item, assessment, resolver=source_resolver)
    except Exception:  # read-only resolver failure is closed
        return SourceDecision(allowed=False, reason="INVALID_CONTRACT")