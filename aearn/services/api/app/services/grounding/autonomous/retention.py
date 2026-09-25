"""Exact, server-resolved storage limits for untrusted discovered material.

This is an internal admission-to-staging check, not teaching/source admission.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from .access_policy import (
    AccessRequest, AuthorityResolver, AutonomousGates, check_candidate_access,
)
from .contracts import FrozenContract, HASH, HANDLE, SourceCandidate, SubjectScope, revalidate

CaptureKind = Literal["none", "prefix", "full"]
_CAPTURE_RANK = {"none": 0, "prefix": 1, "full": 2}


class StorageGrant(FrozenContract):
    """Trusted resolver result for one candidate, never model-supplied authority."""

    demand_hash: str = Field(pattern=HASH)
    scope: SubjectScope
    discovery_receipt_id: str = Field(pattern=HANDLE)
    candidate_url_sha256: str = Field(pattern=HASH)
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    allowed_capture: CaptureKind
    max_captured_bytes: int = Field(ge=0, le=10_000_000)
    license_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$")
    retention_until: datetime
    revoked: bool


class StorageGrantResolver(Protocol):
    def resolve(self, candidate: SourceCandidate, request: AccessRequest) -> StorageGrant | None: ...


class StorageDecision(FrozenContract):
    allowed: bool
    reason: str
    retention_until: datetime | None = None
    license_id: str | None = None


def check_storage(
    candidate: SourceCandidate, request: AccessRequest, *,
    intended_capture: CaptureKind, planned_bytes: int,
    gates: AutonomousGates | None, authority_resolver: AuthorityResolver | None,
    storage_resolver: StorageGrantResolver | None, now: datetime,
) -> StorageDecision:
    """Check current exact authority before capture or any durable content write.

    Call again at staging commit: grants and budget references can be revoked or
    expire while network I/O is outside the database transaction.
    """
    access = check_candidate_access(candidate, request, gates=gates,
                                    resolver=authority_resolver, now=now)
    if not access.allowed:
        return StorageDecision(allowed=False, reason=access.reason)
    try:
        item = revalidate(candidate, SourceCandidate)
        req = revalidate(request, AccessRequest)
        if (req.action != "store" or intended_capture not in _CAPTURE_RANK
                or type(planned_bytes) is not int or not 0 <= planned_bytes <= 10_000_000
                or (intended_capture == "none") != (planned_bytes == 0)
                or now.tzinfo is None or storage_resolver is None):
            return StorageDecision(allowed=False, reason="STORAGE_POLICY_MISSING")
        resolved = storage_resolver.resolve(item, req)
        if resolved is None:
            return StorageDecision(allowed=False, reason="STORAGE_POLICY_MISSING")
        grant = revalidate(resolved, StorageGrant)
        if (grant.revoked or grant.demand_hash != item.demand_hash or grant.scope != item.scope
                or grant.discovery_receipt_id != item.discovery_receipt_id
                or grant.candidate_url_sha256 != hashlib.sha256(item.url.encode("utf-8")).hexdigest()
                or grant.policy_id != req.policy_id or grant.policy_generation != req.policy_generation
                or grant.retention_until.tzinfo is None or grant.retention_until <= now):
            return StorageDecision(allowed=False, reason="STORAGE_POLICY_STALE")
        if (_CAPTURE_RANK[intended_capture] > _CAPTURE_RANK[grant.allowed_capture]
                or planned_bytes > grant.max_captured_bytes
                or (intended_capture != "none" and grant.max_captured_bytes == 0)):
            return StorageDecision(allowed=False, reason="STORAGE_SCOPE_DENIED")
        return StorageDecision(allowed=True, reason="STORAGE_AUTHORIZED",
                               retention_until=grant.retention_until, license_id=grant.license_id)
    except Exception:
        return StorageDecision(allowed=False, reason="INVALID_STORAGE_POLICY")
