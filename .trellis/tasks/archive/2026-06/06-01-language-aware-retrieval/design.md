# Language aware retrieval design

## Architecture

Add `aearn/services/api/app/services/grounding_retrieval.py`. It ranks in-memory `GroundingChunk` candidates and returns `GroundingRetrievalResult` objects. Future DB/embedding implementations can preserve the same result shape.

## Contracts

Define:

- `GroundingRetrievalQuery(language_id_or_alias, query_text, topic_tags=(), preferred_trust_tiers=(), knowledge_point_id=None, knowledge_point_title=None, top_k=4)`
- `GroundingRetrievalResult(chunk, relevance_score, match_reasons)`
- `retrieve_grounding_chunks(chunks, query) -> tuple[GroundingRetrievalResult, ...]`

## Ranking

Filter candidates by canonical language id first. Score with deterministic weights:

- lexical overlap in title/text/section path
- topic tag overlap
- preferred trust tier
- knowledge point title overlap
- small stable tie-breaker by chunk id

When no positive lexical/topic/trust score exists, return fallback chunks for that language ordered by source trust and chunk id.

## Compatibility

No DB, API, agent, or frontend integration is added in this task.

