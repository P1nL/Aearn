# Language aware retrieval

## Goal

Filter and rank RAG results by language, topic, knowledge point, source trust, and current learning context.

## Confirmed Facts

- `grounding_processing.py` now produces metadata-rich `GroundingChunk` values.
- This task can stay in-memory and deterministic; persistence/indexing orchestration is later.
- Existing `teaching_chunks.search_chunks()` remains scoped to internal knowledge-point RAG and must not be replaced here.

## Requirements

- Add a retrieval service that accepts a candidate chunk collection and returns ranked, language-scoped results.
- Retrieval input must support language/alias, query text, topic tags, preferred trust tiers, optional knowledge point id/title, and top-k.
- Results must include chunk metadata plus a deterministic relevance score and match reasons.
- Retrieval must filter by canonical language id before ranking.
- Empty queries or no lexical matches must degrade to best same-language chunks rather than raising.
- Unknown languages must return an empty tuple.

## Acceptance Criteria

- [ ] Query results never include another language's chunks.
- [ ] Exact query terms and topic tags improve ranking.
- [ ] Preferred trust tiers improve ranking without hiding all same-language fallback results.
- [ ] Unknown language returns no results.
- [ ] Empty/no-hit queries return bounded same-language fallback results.
- [ ] Result metadata remains sufficient for downstream citations.

## Out of Scope

- Vector embeddings.
- Database full-text search.
- Agent-facing citation formatting.
- Runtime graph integration.
