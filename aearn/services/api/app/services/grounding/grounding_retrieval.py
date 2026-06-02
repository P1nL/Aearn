from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.grounding.grounding_processing import GroundingChunk
from app.services.grounding.grounding_sources import SourceTrustTier
from app.services.runners.language_capabilities import get_language_capability


@dataclass(frozen=True, slots=True)
class GroundingRetrievalQuery:
    language_id_or_alias: str
    query_text: str
    topic_tags: tuple[str, ...] = ()
    preferred_trust_tiers: tuple[SourceTrustTier, ...] = ()
    knowledge_point_id: str | None = None
    knowledge_point_title: str | None = None
    top_k: int = 4


@dataclass(frozen=True, slots=True)
class GroundingRetrievalResult:
    chunk: GroundingChunk
    relevance_score: float
    match_reasons: tuple[str, ...]


def retrieve_grounding_chunks(
    chunks: tuple[GroundingChunk, ...],
    query: GroundingRetrievalQuery,
) -> tuple[GroundingRetrievalResult, ...]:
    capability = get_language_capability(query.language_id_or_alias)
    if capability is None or query.top_k <= 0:
        return ()

    language_chunks = tuple(chunk for chunk in chunks if chunk.language_id == capability.language_id)
    if not language_chunks:
        return ()

    scored_results = tuple(_score_chunk(chunk, query) for chunk in language_chunks)
    positive_results = tuple(result for result in scored_results if result.relevance_score > 0)

    if positive_results:
        ordered_positive = sorted(positive_results, key=lambda result: (-result.relevance_score, result.chunk.chunk_id))
        positive_ids = {result.chunk.chunk_id for result in ordered_positive}
        fallback_results = [
            GroundingRetrievalResult(chunk=chunk, relevance_score=0.0, match_reasons=("fallback",))
            for chunk in _fallback_chunks(language_chunks)
            if chunk.chunk_id not in positive_ids
        ]
        return tuple([*ordered_positive, *fallback_results][: query.top_k])

    return tuple(
        GroundingRetrievalResult(chunk=chunk, relevance_score=0.0, match_reasons=("fallback",))
        for chunk in _fallback_chunks(language_chunks)[: query.top_k]
    )


def _score_chunk(chunk: GroundingChunk, query: GroundingRetrievalQuery) -> GroundingRetrievalResult:
    score = 0.0
    reasons: list[str] = []
    query_terms = _terms(query.query_text)
    section_terms = _terms(" ".join(chunk.section_path))
    title_terms = _terms(chunk.title)
    text_terms = _terms(chunk.text)

    matched_terms = query_terms & (section_terms | title_terms | text_terms)
    if matched_terms:
        score += len(matched_terms) * 2.0
        if matched_terms & title_terms:
            score += 1.0
        reasons.append("query_terms")

    requested_topics = {_normalize_token(tag) for tag in query.topic_tags if _normalize_token(tag)}
    chunk_topics = {_normalize_token(tag) for tag in chunk.topic_tags if _normalize_token(tag)}
    topic_matches = requested_topics & chunk_topics
    if topic_matches:
        score += len(topic_matches) * 4.0
        reasons.append("topic_tags")

    if query.preferred_trust_tiers and chunk.source_trust_tier in query.preferred_trust_tiers:
        score += 1.5
        reasons.append("trust_tier")

    knowledge_terms = _terms(query.knowledge_point_title or "")
    if knowledge_terms and knowledge_terms & (section_terms | title_terms | text_terms):
        score += 1.0
        reasons.append("knowledge_point_title")

    return GroundingRetrievalResult(chunk=chunk, relevance_score=score, match_reasons=tuple(reasons))


def _fallback_chunks(chunks: tuple[GroundingChunk, ...]) -> tuple[GroundingChunk, ...]:
    return tuple(sorted(chunks, key=lambda chunk: (_trust_rank(chunk.source_trust_tier), chunk.chunk_id)))


def _trust_rank(trust_tier: SourceTrustTier) -> int:
    if trust_tier == "official":
        return 0
    if trust_tier == "trusted_de_facto":
        return 1
    return 2


def _terms(text: str) -> set[str]:
    return {_normalize_token(token) for token in re.findall(r"[A-Za-z0-9_+#-]+", text) if _normalize_token(token)}


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("_", "-")
