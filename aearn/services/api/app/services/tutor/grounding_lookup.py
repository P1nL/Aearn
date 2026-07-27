"""Injected registry-only grounding lookup contracts for the Tutor capability gateway."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.grounding.grounding_citations import grounding_results_for_agent
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery, retrieve_grounding_chunks


@dataclass(frozen=True)
class GroundingLookupQuery:
    language_id_or_alias: str
    query_text: str
    topic_tags: tuple[str, ...] = ()
    top_k: int = 4

    def __post_init__(self) -> None:
        if not self.language_id_or_alias.strip() or not self.query_text.strip():
            raise ValueError("grounding lookup query requires language and text")
        if not 1 <= self.top_k <= 4:
            raise ValueError("grounding lookup top_k must be between 1 and 4")
        object.__setattr__(self, "topic_tags", tuple(self.topic_tags))


@dataclass(frozen=True)
class GroundingLookupItem:
    source_id: str
    language_id: str
    citation_id: str
    title: str
    canonical_url: str
    section_path: tuple[str, ...]
    trust_tier: str
    content_hash: str
    content: str
    relevance_score: float
    match_reasons: tuple[str, ...]


class GroundingLookup(Protocol):
    def lookup(
        self,
        *,
        query: GroundingLookupQuery,
        source_ids: tuple[str, ...],
    ) -> tuple[GroundingLookupItem, ...]: ...


class InMemoryGroundingLookup:
    """Pure deterministic adapter over supplied chunks; it performs no I/O."""

    def __init__(self, chunks: tuple[GroundingChunk, ...] = ()) -> None:
        self._chunks = tuple(chunks)
        self.calls: list[tuple[GroundingLookupQuery, tuple[str, ...]]] = []

    def lookup(
        self,
        *,
        query: GroundingLookupQuery,
        source_ids: tuple[str, ...],
    ) -> tuple[GroundingLookupItem, ...]:
        normalized_source_ids = tuple(sorted(set(source_ids)))
        self.calls.append((query, normalized_source_ids))
        scoped_chunks = tuple(chunk for chunk in self._chunks if chunk.source_id in normalized_source_ids)
        retrieval = retrieve_grounding_chunks(
            scoped_chunks,
            GroundingRetrievalQuery(
                language_id_or_alias=query.language_id_or_alias,
                query_text=query.query_text,
                topic_tags=query.topic_tags,
                top_k=query.top_k,
            ),
        )
        items = grounding_results_for_agent(retrieval, max_items=query.top_k, max_content_chars=180)
        return tuple(
            GroundingLookupItem(
                source_id=item.citation.source_id,
                language_id=next(
                    (result.chunk.language_id for result in retrieval if result.chunk.content_hash == item.citation.content_hash),
                    "",
                ),
                citation_id=item.citation.citation_id,
                title=item.citation.title,
                canonical_url=item.citation.canonical_url,
                section_path=item.citation.section_path,
                trust_tier=item.citation.source_trust_tier,
                content_hash=item.citation.content_hash,
                content=item.content,
                relevance_score=item.relevance_score,
                match_reasons=item.match_reasons,
            )
            for item in items
        )