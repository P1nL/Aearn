"""Operator-only, bounded phase-I corpus inputs and immutable receipts.

These models validate storage shape. Semantic source and coverage audit belongs to the
subsequent validator; a stored `validation_passed` is not evidence of live fetching.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CorpusState = Literal["candidate", "validated", "published", "failed", "retired"]
EventKind = Literal[
    "reindex_started", "reindex_completed", "validation_passed", "validation_failed",
    "diff_generated", "activated", "rolled_back", "retired",
]
Hash = str


def _safe_url(value: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment or parts.port is not None
            or "@" in value):
        raise ValueError("URL must be an HTTPS document location without credentials or query data")
    return parts.hostname


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CorpusCandidate(_Frozen):
    corpus_id: UUID
    subject_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9.-]{2,99}$")
    subject_version: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")
    registry_digest: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_policy_version: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    coverage_policy_version: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")


class CorpusSource(_Frozen):
    corpus_id: UUID
    subject_id: str
    subject_version: str
    source_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    source_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    trust_tier: Literal["official", "trusted_de_facto"]
    source_kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    source_version: str = Field(min_length=1, max_length=80)
    allowed_domains: tuple[str, ...] = Field(min_length=1, max_length=24)
    seed_urls: tuple[str, ...] = Field(max_length=24)
    facets: tuple[str, ...] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def bounded_scope(self) -> CorpusSource:
        if any(not value or len(value) > 160 for value in (*self.allowed_domains, *self.facets)):
            raise ValueError("invalid source scope")
        if any(not domain.isascii() or not domain.replace(".", "").replace("-", "").isalnum()
               or domain != domain.lower() or domain.startswith((".", "-")) or domain.endswith((".", "-"))
               for domain in self.allowed_domains):
            raise ValueError("invalid allowed domain")
        if any(len(value) > 2048 or _safe_url(value) not in self.allowed_domains for value in self.seed_urls):
            raise ValueError("invalid seed URL")
        if len(self.allowed_domains) != len(set(self.allowed_domains)) or len(self.facets) != len(set(self.facets)):
            raise ValueError("duplicate source scope")
        return self


class CorpusDocument(_Frozen):
    corpus_id: UUID
    document_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    source_id: str
    subject_id: str
    subject_version: str
    source_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    trust_tier: Literal["official", "trusted_de_facto"]
    canonical_url: str = Field(min_length=8, max_length=2048, pattern=r"^https://")
    final_url: str = Field(min_length=8, max_length=2048, pattern=r"^https://")
    content_type: str = Field(min_length=1, max_length=100)
    document_version: str = Field(min_length=1, max_length=80)
    fetched_at: datetime
    document_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    parse_status: Literal["parsed", "failed", "empty"]
    diagnostic_code: str | None = Field(default=None, max_length=80, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")

    @model_validator(mode="after")
    def parse_diagnostic(self) -> CorpusDocument:
        _safe_url(self.canonical_url)
        _safe_url(self.final_url)
        if (self.parse_status == "failed") != (self.diagnostic_code is not None):
            raise ValueError("parse diagnostic does not match status")
        return self


class CorpusChunk(_Frozen):
    corpus_id: UUID
    chunk_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    document_id: str
    source_id: str
    subject_id: str
    subject_version: str
    source_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    trust_tier: Literal["official", "trusted_de_facto"]
    document_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")
    ordinal: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=300)
    section_path: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=8000)
    facets: tuple[str, ...] = Field(min_length=1, max_length=24)
    topic_tags: tuple[str, ...] = Field(max_length=24)
    chunk_hash: Hash = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def bounded_tags(self) -> CorpusChunk:
        if any(not value or len(value) > 160 for value in (*self.facets, *self.topic_tags)):
            raise ValueError("invalid facet or topic tag")
        if len(self.facets) != len(set(self.facets)) or len(self.topic_tags) != len(set(self.topic_tags)):
            raise ValueError("duplicate facet or topic tag")
        if self.chunk_hash != hashlib.sha256(self.content.encode("utf-8")).hexdigest():
            raise ValueError("chunk content hash mismatch")
        return self


class CorpusVersion(_Frozen):
    corpus_id: UUID
    subject_id: str
    subject_version: str
    registry_digest: Hash
    state: CorpusState
    generation: int
    source_set_hash: Hash | None
    content_hash: Hash | None
    summary_hash: Hash | None
    retrieval_policy_version: str
    coverage_policy_version: str
    coverage_summary: dict[str, str | int | bool]
    validation_summary: dict[str, str | int | bool]


class CorpusEvent(_Frozen):
    event_id: UUID
    corpus_id: UUID
    subject_id: str
    event_kind: EventKind
    operation_id: UUID
    idempotency_key: str
    request_hash: Hash
    summary_hash: Hash | None
    expected_generation: int | None
    observed_generation: int | None
    counts: dict[str, int]
    reason_code: str | None


class ActiveCorpus(_Frozen):
    subject_id: str
    corpus_id: UUID
    generation: int
    activation_event_id: UUID
