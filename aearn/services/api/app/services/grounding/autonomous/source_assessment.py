"""C review projections; only a current trusted port can supply authority.

These immutable facts do not replace persistence, retention enforcement, or A's
consumer-side current source and claim resolvers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from .contracts import FrozenContract, HASH, HANDLE, SourceAssessment, SubjectScope, Usage
from .source_policy import SourceAuthorization


class DocumentCoordinate(FrozenContract):
    scope: SubjectScope
    source_handle: str = Field(pattern=HANDLE)
    document_handle: str = Field(pattern=HANDLE)
    document_revision: str = Field(min_length=1, max_length=80)
    document_hash: str = Field(pattern=HASH)


class DocumentReviewFacts(FrozenContract):
    """Reviewer-observed facts for a complete, pinned document (not a B prefix)."""

    coordinate: DocumentCoordinate
    review_id: UUID
    registered_capture_id: UUID | None = None
    candidate_capture_id: UUID | None = None
    review_receipt_hash: str = Field(pattern=HASH)
    quality_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    license_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$")
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    root_id: str = Field(pattern=HANDLE)
    immutable_history_allowed: bool
    allowed_usages: tuple[Usage, ...] = Field(max_length=3)
    lineage_family: str = Field(pattern=HANDLE)
    origin: Literal["official", "maintainer", "tutorial", "repository", "community", "blog"]
    reading_level: Literal["beginner", "intermediate", "advanced"]
    reading_fit: Literal["suitable", "unsuitable", "unknown"]
    version_fit: Literal["current", "stale", "unknown"]
    technical_status: Literal["correct", "incorrect", "unknown"]
    conflict_status: Literal["resolved", "unresolved", "unknown"]
    known_error: Literal["absent", "present", "unknown"]
    covered_facets: tuple[str, ...] = Field(max_length=24)
    status: Literal["reviewed", "quarantined"]

    @model_validator(mode="after")
    def exact_facets(self) -> DocumentReviewFacts:
        if (len(set(self.covered_facets)) != len(self.covered_facets)
                or set(self.covered_facets) - set(self.coordinate.scope.facets)
                or (self.registered_capture_id is None) == (self.candidate_capture_id is None)
                or len(set(self.allowed_usages)) != len(self.allowed_usages)
                or self.status != "reviewed" and (self.allowed_usages or self.immutable_history_allowed)):
            raise ValueError("review facets outside exact document scope")
        return self


class StorageUseGrant(FrozenContract):
    """Operator permission for this revision, not proof that a claim is true."""

    coordinate: DocumentCoordinate
    review_id: UUID
    active: bool
    revoked: bool
    storage_receipt_id: str = Field(pattern=HANDLE)
    admission_receipt_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    license_status: Literal["granted", "unclear", "denied"]
    retained_until: datetime
    allowed_usages: tuple[Usage, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def coherent(self) -> StorageUseGrant:
        if (self.revoked and self.active or self.retained_until.tzinfo is None
                or self.retained_until.utcoffset() is None
                or len(set(self.allowed_usages)) != len(self.allowed_usages)
                or self.license_status != "granted" and self.allowed_usages):
            raise ValueError("invalid storage/use grant")
        return self


class CurrentReview(FrozenContract):
    facts: DocumentReviewFacts
    grant: StorageUseGrant | None
    revoked: bool


class CurrentReviewResolver(Protocol):
    """Repository-backed current review, grant and revocation in one snapshot."""

    def resolve(self, source_handle: str, document_handle: str) -> CurrentReview | None: ...


class SourceReviewDecision(FrozenContract):
    allowed: bool
    reason: str
    assessment: SourceAssessment | None = None
    authorization: SourceAuthorization | None = None


def assess_document(
    facts: DocumentReviewFacts, *, resolver: CurrentReviewResolver | None, now: datetime,
) -> SourceReviewDecision:
    """Project A contracts only from an exact, current, eligible C review.

    The port must establish reviewer provenance and transaction/lease freshness;
    supplied facts, model text, URLs and domain labels never confer authority.
    """
    def deny(reason: str) -> SourceReviewDecision:
        return SourceReviewDecision(allowed=False, reason=reason)

    try:
        item = DocumentReviewFacts.model_validate(facts.model_dump(mode="python"))
        if now.tzinfo is None or now.utcoffset() is None:
            return deny("INVALID_CONTRACT")
        if resolver is None:
            return deny("AUTHORITY_MISSING")
        found = resolver.resolve(item.coordinate.source_handle, item.coordinate.document_handle)
        if found is None:
            return deny("AUTHORITY_MISSING")
        current = CurrentReview.model_validate(found.model_dump(mode="python"))
        if current.facts != item:
            return deny("SOURCE_STALE")
        if current.revoked:
            return deny("SOURCE_REVOKED")
        if item.status != "reviewed":
            return deny("REVIEW_QUARANTINED")
        if (item.quality_code != "QUALIFIED" or item.version_fit != "current" or item.reading_fit != "suitable"
                or item.technical_status != "correct" or item.conflict_status != "resolved"
                or item.known_error != "absent" or not item.covered_facets):
            return deny("QUALITY_UNVERIFIED")
        if current.grant is None:
            return deny("STORAGE_DENIED")
        grant = StorageUseGrant.model_validate(current.grant.model_dump(mode="python"))
        if (grant.coordinate != item.coordinate or grant.review_id != item.review_id
                or grant.policy_generation != item.policy_generation
                or not grant.active or grant.revoked or grant.license_status != "granted"):
            return deny("STORAGE_DENIED")
        if grant.retained_until <= now:
            return deny("RETENTION_EXPIRED")
        if not grant.allowed_usages or not set(grant.allowed_usages) <= set(item.allowed_usages):
            return deny("USAGE_DENIED")
        coordinate = item.coordinate
        assessment = SourceAssessment(
            scope=coordinate.scope, source_handle=coordinate.source_handle,
            document_handle=coordinate.document_handle,
            document_revision=coordinate.document_revision, document_hash=coordinate.document_hash,
            origin=item.origin, reading_level=item.reading_level, status="reviewed",
            allowed_usages=grant.allowed_usages, storage_receipt_id=grant.storage_receipt_id,
            admission_receipt_id=grant.admission_receipt_id,
            policy_generation=grant.policy_generation,
        )
        authorization = SourceAuthorization(
            scope=coordinate.scope, source_handle=coordinate.source_handle,
            document_handle=coordinate.document_handle,
            document_revision=coordinate.document_revision, document_hash=coordinate.document_hash,
            lineage_family=item.lineage_family, origin=item.origin,
            reading_level=item.reading_level, reviewed=True,
            storage_receipt_id=grant.storage_receipt_id,
            admission_receipt_id=grant.admission_receipt_id,
            allowed_usages=grant.allowed_usages, policy_generation=grant.policy_generation,
            revoked=False, readable=True,
        )
        return SourceReviewDecision(allowed=True, reason="REVIEWED", assessment=assessment,
                                    authorization=authorization)
    except Exception:  # malformed/unavailable trusted port fails closed without leaking details
        return deny("INVALID_CONTRACT")
