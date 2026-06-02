from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.services.grounding.grounding_retrieval import GroundingRetrievalResult
from app.services.grounding.grounding_sources import SourceContentType, SourceTrustTier


@dataclass(frozen=True, slots=True)
class GroundingCitation:
    citation_id: str
    source_id: str
    title: str
    section_path: tuple[str, ...]
    canonical_url: str
    source_type: SourceContentType
    source_trust_tier: SourceTrustTier
    content_hash: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class AgentGroundingItem:
    content: str
    citation: GroundingCitation
    relevance_score: float
    match_reasons: tuple[str, ...]


def grounding_results_for_agent(
    results: tuple[GroundingRetrievalResult, ...],
    *,
    max_items: int = 4,
    max_content_chars: int = 800,
) -> tuple[AgentGroundingItem, ...]:
    if max_items <= 0 or max_content_chars <= 0:
        return ()

    items: list[AgentGroundingItem] = []
    for result in results[:max_items]:
        chunk = result.chunk
        citation = GroundingCitation(
            citation_id=_citation_id(chunk.canonical_url, chunk.section_path, chunk.content_hash),
            source_id=chunk.source_id,
            title=chunk.title,
            section_path=chunk.section_path,
            canonical_url=chunk.canonical_url,
            source_type=chunk.source_type,
            source_trust_tier=chunk.source_trust_tier,
            content_hash=chunk.content_hash,
            fetched_at=chunk.fetched_at,
        )
        items.append(
            AgentGroundingItem(
                content=_bounded_content(chunk.text, max_content_chars=max_content_chars),
                citation=citation,
                relevance_score=result.relevance_score,
                match_reasons=result.match_reasons,
            ),
        )
    return tuple(items)


def _citation_id(canonical_url: str, section_path: tuple[str, ...], content_hash: str) -> str:
    body = "\n".join((canonical_url, "/".join(section_path), content_hash))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


def _bounded_content(text: str, *, max_content_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_content_chars:
        return normalized
    if max_content_chars <= 3:
        return "." * max_content_chars
    return normalized[: max_content_chars - 3].rstrip() + "..."
