"""Read-only exact-corpus PostgreSQL FTS with synthetic-only optional augmentation.

No operator imports, provider, network, pgvector, or learner-facing adapter live here.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from psycopg import Connection
from pydantic import Field

from app.services.grounding.coverage import select_evidence, unavailable_report
from app.services.grounding.retrieval_contracts import (
    _Frozen, GroundingRetrievalPlan, GroundingRetrievalRequest,
    GroundingRetrievalResultV2, RetrievalCandidate, stable_hash,
)
from app.services.grounding.retrieval_planner import resolve_plan


class SyntheticEmbeddingConfig(_Frozen):
    """Server-owned fake config; no receipt exists in the phase-I database."""

    model_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    dimension: int = Field(ge=1, le=4096)
    normalization_version: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")


def synthetic_embedding_receipt(plan: GroundingRetrievalPlan, config: SyntheticEmbeddingConfig) -> str:
    """Explicit fake receipt bound to immutable corpus; not production index evidence."""
    return stable_hash(("synthetic-fixture-v1", plan.corpus_id, plan.corpus_content_hash,
                        plan.registry_digest, plan.corpus_summary_hash, config.model_id,
                        config.dimension, config.normalization_version))


class EmbeddingSearchRequest(_Frozen):
    corpus_id: UUID
    subject_id: str
    subject_version: str
    allowed_source_ids: tuple[str, ...]
    allowed_trust_tiers: tuple[str, ...]
    required_facets: tuple[str, ...]
    query_text: str
    limit: int
    synthetic_receipt: str
    model_id: str
    dimension: int
    normalization_version: str


class EmbeddingCandidate(_Frozen):
    corpus_id: UUID
    chunk_id: str = Field(min_length=1, max_length=160)
    chunk_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    synthetic_receipt: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str
    dimension: int
    normalization_version: str


class EmbeddingRetrieverPort(Protocol):
    def search(self, request: EmbeddingSearchRequest) -> tuple[EmbeddingCandidate, ...]: ...


class DisabledEmbeddingRetriever:
    def search(self, request: EmbeddingSearchRequest) -> tuple[EmbeddingCandidate, ...]:
        return ()


class DeterministicFakeEmbeddingRetriever:
    """Test-only ordered IDs, no text vectorization or real search claim."""

    def __init__(self, candidates: Sequence[EmbeddingCandidate]) -> None:
        self.candidates = tuple(candidates)

    def search(self, request: EmbeddingSearchRequest) -> tuple[EmbeddingCandidate, ...]:
        return self.candidates[:request.limit]


# Parameters are always values, never interpolated SQL or model-selected table/column names.
_CHUNK_SCOPE = """FROM grounding_corpus_chunks c
 JOIN grounding_corpus_source_snapshots s
   ON (s.corpus_version_id,s.source_id,s.subject_id,s.subject_version,s.source_hash,s.trust_tier)
    = (c.corpus_version_id,c.source_id,c.subject_id,c.subject_version,c.source_hash,c.trust_tier)
 JOIN grounding_corpus_documents d
   ON (d.corpus_version_id,d.document_id,d.source_id,d.subject_id,d.subject_version,d.source_hash,d.trust_tier,d.document_hash)
    = (c.corpus_version_id,c.document_id,c.source_id,c.subject_id,c.subject_version,c.source_hash,c.trust_tier,c.document_hash)
 WHERE c.corpus_version_id=%s AND c.subject_id=%s AND c.subject_version=%s
   AND c.source_id=ANY(%s) AND c.trust_tier=ANY(%s) AND d.parse_status='parsed'
   AND s.facets_json ?| %s AND c.facets_json ?| %s"""
_SELECT = """SELECT c.chunk_id,c.source_id,c.document_id,c.title,c.section_path,c.content,
 c.facets_json,c.trust_tier,c.source_hash,c.document_hash,c.chunk_hash """


def _scope_args(plan: GroundingRetrievalPlan) -> tuple[object, ...]:
    facets = list((*plan.required_facets, *plan.optional_facets))
    return (plan.corpus_id, plan.subject_id, plan.subject_version,
            list(plan.allowed_source_ids), list(plan.allowed_trust_tiers), facets, facets)


def _candidate(row: dict[str, Any], *, fts_rank: int | None = None,
               embedding_rank: int | None = None) -> RetrievalCandidate | None:
    if hashlib.sha256(row["content"].encode("utf-8")).hexdigest() != row["chunk_hash"]:
        return None
    return RetrievalCandidate(
        chunk_id=row["chunk_id"], source_id=row["source_id"], document_id=row["document_id"],
        title=row["title"], section_path=row["section_path"], content=row["content"],
        facets=tuple(row["facets_json"]), trust_tier=row["trust_tier"],
        source_hash=row["source_hash"], document_hash=row["document_hash"],
        chunk_hash=row["chunk_hash"], fts_rank=fts_rank, embedding_rank=embedding_rank,
    )


def _fts(conn: Connection[dict[str, Any]], plan: GroundingRetrievalPlan,
         query_text: str) -> dict[str, RetrievalCandidate]:
    output: dict[str, RetrievalCandidate] = {}
    for facet in (*plan.required_facets, *plan.optional_facets):
        if len(output) >= plan.budget.per_channel_limit:
            break
        # The facet is both an authorized JSON scope and the FTS clause. User text
        # only refines rank; an irrelevant query cannot authorize a different facet.
        rows = conn.execute(
            _SELECT + _CHUNK_SCOPE + """
              AND s.facets_json ? %s AND c.facets_json ? %s
              AND c.search_vector @@ plainto_tsquery('simple',%s)
              ORDER BY (ts_rank(c.search_vector,plainto_tsquery('simple',%s)) +
                        ts_rank(c.search_vector,plainto_tsquery('simple',%s))) DESC,
                       CASE c.trust_tier WHEN 'official' THEN 0 ELSE 1 END,
                       c.source_id,c.chunk_id LIMIT %s""",
            (*_scope_args(plan), facet, facet, facet.replace("-", " "),
             facet.replace("-", " "), query_text,
             min(plan.budget.per_facet_limit, plan.budget.per_channel_limit - len(output))),
        ).fetchall()
        for row in rows:
            candidate = _candidate(row)
            if candidate is not None and candidate.chunk_id not in output:
                output[candidate.chunk_id] = candidate.model_copy(update={"fts_rank": len(output) + 1})
    return output


def _embedding(
    conn: Connection[dict[str, Any]], plan: GroundingRetrievalPlan, query_text: str,
    port: EmbeddingRetrieverPort, config: SyntheticEmbeddingConfig,
) -> dict[str, RetrievalCandidate] | None:
    receipt = synthetic_embedding_receipt(plan, config)
    search = EmbeddingSearchRequest(
        corpus_id=plan.corpus_id, subject_id=plan.subject_id,
        subject_version=plan.subject_version, allowed_source_ids=plan.allowed_source_ids,
        allowed_trust_tiers=plan.allowed_trust_tiers, required_facets=plan.required_facets,
        query_text=query_text, limit=plan.budget.per_channel_limit,
        synthetic_receipt=receipt, model_id=config.model_id, dimension=config.dimension,
        normalization_version=config.normalization_version,
    )
    try:
        candidates = port.search(search)
        if not isinstance(candidates, tuple) or not candidates or len(candidates) > search.limit:
            return None
        # Reconstruct strict immutable DTOs before using any port-supplied identity
        # in SQL. model_copy and protocol implementations may bypass validation.
        candidates = tuple(EmbeddingCandidate.model_validate(item.model_dump()) for item in candidates)
        if (len({item.chunk_id for item in candidates}) != len(candidates)
                or any(item.corpus_id != plan.corpus_id or item.synthetic_receipt != receipt
                       or item.model_id != config.model_id or item.dimension != config.dimension
                       or item.normalization_version != config.normalization_version for item in candidates)):
            return None
    except Exception:
        # A throwing/malformed optional adapter cannot interrupt the FTS path.
        return None
    # Database failures remain visible to the caller, never disguised as adapter failure.
    rows = conn.execute(
        _SELECT + _CHUNK_SCOPE + " AND c.chunk_id=ANY(%s) ORDER BY c.chunk_id LIMIT %s",
        (*_scope_args(plan), [item.chunk_id for item in candidates], len(candidates)),
    ).fetchall()
    by_id = {row["chunk_id"]: row for row in rows}
    if len(by_id) != len(candidates):
        return None
    output: dict[str, RetrievalCandidate] = {}
    try:
        for rank, item in enumerate(candidates, 1):
            row = by_id[item.chunk_id]
            if item.chunk_hash != row["chunk_hash"]:
                return None
            candidate = _candidate(row, embedding_rank=rank)
            if candidate is None:
                return None
            output[item.chunk_id] = candidate
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return output


def retrieve_grounding_v2(
    conn: Connection[dict[str, Any]], request: GroundingRetrievalRequest, *,
    embedding: EmbeddingRetrieverPort | None = None,
    synthetic_config: SyntheticEmbeddingConfig | None = None,
) -> GroundingRetrievalResultV2:
    """Caller-owned DB transaction; resolves one immutable published identity."""
    request_hash = stable_hash(request.model_dump(mode="json"))
    plan, reason = resolve_plan(conn, request)
    if plan is None:
        assert reason is not None
        coverage = unavailable_report(request, reason)
        return GroundingRetrievalResultV2(
            request_hash=request_hash, plan=None, evidence=(), coverage=coverage,
            result_hash=stable_hash((request_hash, coverage.report_hash)),
        )
    fts = _fts(conn, plan, request.query_text)
    embedding_unavailable = False
    if request.embedding_mode == "optional":
        if not plan.synthetic_fixture or embedding is None or synthetic_config is None:
            embedding_unavailable = True
        else:
            augmented = _embedding(conn, plan, request.query_text, embedding, synthetic_config)
            if augmented is None:
                embedding_unavailable = True
            else:
                for chunk_id, candidate in augmented.items():
                    fts[chunk_id] = candidate.model_copy(update={"fts_rank": fts[chunk_id].fts_rank}) if chunk_id in fts else candidate
    evidence, coverage = select_evidence(plan, tuple(fts.values()), embedding_unavailable=embedding_unavailable)
    return GroundingRetrievalResultV2(
        request_hash=request_hash, plan=plan, evidence=evidence, coverage=coverage,
        result_hash=stable_hash((plan.plan_hash, coverage.report_hash,
                                tuple(item.model_dump(mode="json") for item in evidence))),
    )
