"""Internal, immutable phase-I retrieval contracts; never a learner DTO."""
from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.grounding.subject_contracts import KNOWN_SUBJECT_FACETS

Stage = Literal["plan_preflight", "lesson_authoring", "tutor_focus", "practice", "review"]
CoverageStatus = Literal["satisfied", "partial", "insufficient", "unavailable"]
ReasonCode = Literal[
    "SUBJECT_UNKNOWN", "FACET_INVALID", "CORPUS_MISSING", "CORPUS_UNPUBLISHED",
    "CORPUS_RETIRED", "CORPUS_STALE", "CORPUS_POLICY_UNSUPPORTED", "VERSION_MISMATCH", "SOURCE_SCOPE_EMPTY",
    "FACET_MISSING", "SOURCE_DIVERSITY_LOW", "BUDGET_EXHAUSTED", "EMBEDDING_UNAVAILABLE",
]
_HASH = r"^[0-9a-f]{64}$"


def stable_hash(value: object) -> str:
    """Canonical identity excludes timestamps and floating point scores."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ActiveCorpusSelector(_Frozen):
    kind: Literal["active"] = "active"
    expected_generation: int | None = Field(default=None, ge=1)
    expected_summary_hash: str | None = Field(default=None, pattern=_HASH)


class ExactCorpusSelector(_Frozen):
    kind: Literal["exact"] = "exact"
    corpus_id: UUID
    expected_summary_hash: str = Field(pattern=_HASH)


class GroundingRetrievalRequest(_Frozen):
    subject_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
    subject_version: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
    corpus_selector: ActiveCorpusSelector | ExactCorpusSelector = Field(discriminator="kind")
    query_text: str = Field(min_length=1, max_length=300)
    required_facets: tuple[str, ...] = Field(min_length=1, max_length=24)
    optional_facets: tuple[str, ...] = Field(default=(), max_length=24)
    stage: Stage
    budget_profile: Literal["standard", "compact"] = "standard"
    embedding_mode: Literal["disabled", "optional"] = "disabled"

    @model_validator(mode="after")
    def validate_scope(self) -> GroundingRetrievalRequest:
        if (not self.query_text.strip() or any(ord(char) < 32 for char in self.query_text)
                or len(self.required_facets) != len(set(self.required_facets))
                or len(self.optional_facets) != len(set(self.optional_facets))
                or set(self.required_facets) & set(self.optional_facets)
                or (set(self.required_facets) | set(self.optional_facets)) - KNOWN_SUBJECT_FACETS):
            raise ValueError("invalid retrieval query or facet scope")
        return self


class EvidenceBudgetPolicy(_Frozen):
    max_chunks: int = Field(ge=1, le=24)
    max_characters: int = Field(ge=1, le=32000)
    max_estimated_tokens: int = Field(ge=1, le=8000)
    per_facet_limit: int = Field(ge=1, le=16)
    per_channel_limit: int = Field(ge=1, le=96)


class GroundingRetrievalPlan(_Frozen):
    request_hash: str
    plan_hash: str
    subject_id: str
    subject_version: str
    corpus_id: UUID
    corpus_summary_hash: str
    corpus_content_hash: str
    registry_digest: str
    retrieval_policy_version: str
    coverage_policy_version: str
    stage: Stage
    required_facets: tuple[str, ...]
    optional_facets: tuple[str, ...]
    allowed_source_ids: tuple[str, ...]
    allowed_trust_tiers: tuple[Literal["official", "trusted_de_facto"], ...]
    minimum_source_diversity: int
    budget: EvidenceBudgetPolicy
    synthetic_fixture: bool


class RetrievalCandidate(_Frozen):
    chunk_id: str
    source_id: str
    document_id: str
    title: str
    section_path: str
    content: str
    facets: tuple[str, ...]
    trust_tier: Literal["official", "trusted_de_facto"]
    source_hash: str
    document_hash: str
    chunk_hash: str
    fts_rank: int | None = None
    embedding_rank: int | None = None


class SelectedGroundingEvidence(_Frozen):
    chunk_id: str
    source_id: str
    document_id: str
    title: str
    section_path: str
    content: str
    facets: tuple[str, ...]
    trust_tier: Literal["official", "trusted_de_facto"]
    source_hash: str
    document_hash: str
    chunk_hash: str
    estimated_tokens: int


class CoverageReport(_Frozen):
    request_hash: str
    corpus_summary_hash: str | None
    registry_digest: str | None
    status: CoverageStatus
    subject_id: str
    subject_version: str
    corpus_id: UUID | None
    required_facets: tuple[str, ...]
    covered_facets: tuple[str, ...]
    missing_facets: tuple[str, ...]
    source_count: int
    trust_tiers: tuple[str, ...]
    freshness_state: Literal["current", "stale", "unavailable"]
    version_state: Literal["exact", "mismatch", "unavailable"]
    budget_state: Literal["within", "exhausted", "unavailable"]
    used_characters: int
    used_estimated_tokens: int
    used_chunks: int
    reason_codes: tuple[ReasonCode, ...]
    report_hash: str


class GroundingRetrievalResultV2(_Frozen):
    request_hash: str
    plan: GroundingRetrievalPlan | None
    evidence: tuple[SelectedGroundingEvidence, ...]
    coverage: CoverageReport
    result_hash: str
