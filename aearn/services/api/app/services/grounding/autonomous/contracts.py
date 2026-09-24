"""Strict internal material DTOs. Model-authored data is never authority."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.grounding.subject_registry import get_grounding_subject

Hash = str
Usage = Literal["main_teaching", "supplementary_explanation", "assessment_evidence"]
Action = Literal["discover", "probe", "store", "activate", "consume"]
HASH = r"^[0-9a-f]{64}$"
HANDLE = r"^[a-z][a-z0-9._:-]{2,159}$"
VERSION = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$"


T = TypeVar("T", bound="FrozenContract")


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def revalidate(value: T, kind: type[T]) -> T:
    """Recheck nested objects and after-validators bypassed by copy/construct."""
    if type(value) is not kind:
        raise ValueError("invalid contract type")
    return kind.model_validate(value.model_dump(mode="python"))


class SubjectScope(FrozenContract):
    subject_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
    subject_version: str = Field(min_length=1, max_length=80, pattern=VERSION)
    facets: tuple[str, ...] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def known_scope(self) -> SubjectScope:
        subject = get_grounding_subject(self.subject_id)
        if (subject is None or subject.subject_id != self.subject_id
                or len(set(self.facets)) != len(self.facets)
                or set(self.facets) - set(subject.required_facets + subject.optional_facets)):
            raise ValueError("invalid subject facet scope")
        return self


class LearningMaterialDemand(FrozenContract):
    scope: SubjectScope
    demand_hash: Hash = Field(pattern=HASH)
    plan_ref: str = Field(pattern=HANDLE)
    node_ref: str = Field(pattern=HANDLE)
    draft_revision: int = Field(ge=1, le=1_000_000)
    purpose: Usage
    reading_level: Literal["beginner", "intermediate", "advanced"]
    language: Literal["zh", "en"]


class SourcePreference(FrozenContract):
    kind: Literal["source_handle", "site", "author"]
    value: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def bounded(self) -> SourcePreference:
        if (self.value != self.value.strip() or any(ord(c) < 32 for c in self.value)
                or self.kind == "source_handle" and not re.fullmatch(HANDLE, self.value)):
            raise ValueError("invalid preference")
        return self


def valid_query_terms(terms: tuple[str, ...]) -> bool:
    return (len(set(terms)) == len(terms) and all(
        bool(t.strip()) and t == t.strip() and len(t) <= 60
        and re.fullmatch(r"[\w .+\-]+", t, re.UNICODE) is not None for t in terms
    ))


class SourceDiscoverySuggestion(FrozenContract):
    demand_hash: Hash = Field(pattern=HASH)
    query_terms: tuple[str, ...] = Field(min_length=1, max_length=8)
    reason: Literal["coverage_gap", "reading_level", "version_stale", "conflict"]
    preferences: tuple[SourcePreference, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def bounded(self) -> SourceDiscoverySuggestion:
        if (not valid_query_terms(self.query_terms)
                or len({(p.kind, p.value) for p in self.preferences}) != len(self.preferences)):
            raise ValueError("invalid discovery suggestion")
        return self


class RagBudgetDelegation(FrozenContract):
    """Server-resolved accounting reference, not a balance or reservation."""
    root_id: str = Field(pattern=HANDLE)
    delegation_id: str = Field(pattern=HANDLE)
    generation: int = Field(ge=1)
    expires_at: datetime


class SourceDiscoveryDemand(FrozenContract):
    """Server-issued projection; its references must still be resolved on use."""
    demand_hash: Hash = Field(pattern=HASH)
    scope: SubjectScope
    query_terms: tuple[str, ...] = Field(min_length=1, max_length=8)
    actor_id: str = Field(pattern=HANDLE)
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    budget: RagBudgetDelegation

    @model_validator(mode="after")
    def safe_projection(self) -> SourceDiscoveryDemand:
        if not valid_query_terms(self.query_terms):
            raise ValueError("invalid reviewed query projection")
        return self


class ContentCapture(FrozenContract):
    kind: Literal["none", "prefix", "full"]
    captured_bytes: int = Field(ge=0, le=10_000_000)
    prefix_sha256: Hash | None = Field(default=None, pattern=HASH)
    full_sha256: Hash | None = Field(default=None, pattern=HASH)

    @model_validator(mode="after")
    def integrity_scope(self) -> ContentCapture:
        if ((self.kind == "none" and (self.captured_bytes != 0 or self.prefix_sha256 or self.full_sha256))
                or (self.kind == "prefix" and (self.captured_bytes == 0 or not self.prefix_sha256 or self.full_sha256))
                or (self.kind == "full" and (self.captured_bytes == 0 or not self.full_sha256 or self.prefix_sha256))):
            raise ValueError("capture hash does not describe captured scope")
        return self


class SourceCandidate(FrozenContract):
    """Untrusted URL confined to discovery; a landing page is not textbook body."""
    kind: Literal["landing", "document", "repo_page", "repo_file"]
    demand_hash: Hash = Field(pattern=HASH)
    scope: SubjectScope
    url: str = Field(min_length=9, max_length=2048, pattern=r"^https://")
    discovery_receipt_id: str = Field(pattern=HANDLE)
    declared_version: str | None = Field(default=None, max_length=80)
    repo_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    repo_path: str | None = Field(default=None, min_length=1, max_length=400)
    capture: ContentCapture

    @model_validator(mode="after")
    def coherent(self) -> SourceCandidate:
        if ((self.kind == "repo_file" and (self.repo_commit is None or self.repo_path is None))
                or (self.kind != "repo_file" and (self.repo_commit is not None or self.repo_path is not None))
                or self.kind in {"landing", "repo_page"} and self.capture.kind != "none"
                or self.repo_path is not None and
                (self.repo_path.startswith(("/", "\\")) or "\\" in self.repo_path or ".." in self.repo_path.split("/"))):
            raise ValueError("invalid candidate kind or immutable revision")
        return self


class SourceAssessment(FrozenContract):
    scope: SubjectScope
    source_handle: str = Field(pattern=HANDLE)
    document_handle: str = Field(pattern=HANDLE)
    document_revision: str = Field(min_length=1, max_length=80)
    document_hash: Hash = Field(pattern=HASH)
    origin: Literal["official", "maintainer", "tutorial", "repository", "community", "blog"]
    reading_level: Literal["beginner", "intermediate", "advanced"]
    status: Literal["candidate", "reviewed", "quarantined", "revoked"]
    allowed_usages: tuple[Usage, ...] = Field(max_length=3)
    storage_receipt_id: str | None = Field(default=None, pattern=HANDLE)
    admission_receipt_id: str | None = Field(default=None, pattern=HANDLE)
    policy_generation: int = Field(ge=1)

    @model_validator(mode="after")
    def coherent(self) -> SourceAssessment:
        if (len(set(self.allowed_usages)) != len(self.allowed_usages)
                or self.status != "reviewed" and (self.allowed_usages or self.admission_receipt_id)
                or self.status == "reviewed" and (not self.storage_receipt_id or not self.admission_receipt_id)):
            raise ValueError("incoherent source admission")
        return self


class RagEvidenceRequest(FrozenContract):
    """Handle-only formal request; extra URL/SQL/DB/command fields are forbidden."""
    scope: SubjectScope
    demand_hash: Hash = Field(pattern=HASH)
    purpose: Usage
    source_handles: tuple[str, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_handles(self) -> RagEvidenceRequest:
        if (len(set(self.source_handles)) != len(self.source_handles)
                or any(not re.fullmatch(HANDLE, h) for h in self.source_handles)):
            raise ValueError("invalid source handles")
        return self


class RagEvidenceBinding(FrozenContract):
    scope: SubjectScope
    demand_hash: Hash = Field(pattern=HASH)
    purpose: Usage
    source_handle: str = Field(pattern=HANDLE)
    document_handle: str = Field(pattern=HANDLE)
    document_revision: str = Field(min_length=1, max_length=80)
    document_hash: Hash = Field(pattern=HASH)
    admission_receipt_id: str = Field(pattern=HANDLE)
    claim_receipt_id: str | None = Field(default=None, pattern=HANDLE)
