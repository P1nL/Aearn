# Agent RAG Retrieval

## Goal

Give the learning agent access to a searchable knowledge base of teaching materials, documentation, and code examples. Currently `lesson_sources_json` is just a list of URLs stuffed into the prompt with no retrieval, no indexing, and no citation grounding.

After this task, the agent can search for relevant documentation, retrieve specific code examples, and cite sources in its explanations — making its teaching grounded in real materials rather than parametric knowledge alone.

## Context

- Current state: `lesson_sources_json` in `knowledge_points` contains URLs. These are injected verbatim into the agent's system prompt. No content is fetched, indexed, or searched.
- `tools_web.py` has `web_search` (Exa) and `fetch_doc_toc` (HTML heading extractor) — but these are only wired into plan generation, not teaching.
- No vector database exists in the infrastructure (only Postgres + Redis).
- `plan_generation_agent.py` already uses `source_urls` and requires attribution — the pattern exists but isn't available during teaching.
- Dependency: `agent-write-tools` (agent needs the tool-call loop to invoke retrieval mid-conversation).

## Requirements

### Knowledge Base
- Index teaching materials per knowledge point:
  - Official documentation sections (from `lesson_sources_json` URLs)
  - Code examples (from exercises, seed banks, or curated examples)
  - Concept explanations (from past successful teaching turns, if available)
- Use vector embeddings for semantic search (not just keyword matching).
- Storage: pgvector extension in existing Postgres (avoids adding a new service).
- Indexing can be async (Celery task triggered when a knowledge point is created or updated).

### Retrieval Tool
- Add a `search_teaching_materials(query, knowledge_point_id?, top_k=3)` tool to the learning agent.
- Tool returns: relevant text chunks with source attribution (URL, section title, relevance score).
- Agent can call this tool mid-conversation when it needs to reference specific documentation or examples.
- Results must be concise enough to fit in the agent's context without overwhelming it.

### Citation
- When the agent uses retrieved content in its response, it should cite the source.
- Citation format: inline reference that the frontend can render as a link or tooltip.
- The agent must not fabricate citations — only cite content actually returned by the retrieval tool.

### Indexing Pipeline
- Fetch and chunk content from `lesson_sources_json` URLs.
- Generate embeddings (via the configured LLM provider or a dedicated embedding model).
- Store chunks + embeddings in pgvector.
- Re-index when knowledge point sources change.
- Handle fetch failures gracefully (mark as unavailable, don't block teaching).

## Acceptance Criteria

- [ ] A vector index exists in Postgres (pgvector) with teaching material chunks.
- [ ] The agent can call `search_teaching_materials` and receive relevant chunks with sources.
- [ ] Retrieved content is semantically relevant (not just keyword-matched) — verified by test with known queries.
- [ ] The agent cites sources when using retrieved content in explanations.
- [ ] Indexing runs async and does not block API requests.
- [ ] At least one integration test demonstrates: agent encounters a question → calls retrieval → uses the result in its response with citation.
- [ ] Fetch failures for source URLs are handled gracefully (logged, not crashed).
- [ ] No new infrastructure services required — uses existing Postgres + Celery.
- [ ] Existing teaching flow works without retrieval (retrieval is additive, not required).

## Out of Scope

- Real-time web search during teaching (existing Exa integration in plan generation is separate).
- User-uploaded documents or custom knowledge bases.
- Multi-modal retrieval (images, videos).
- Retrieval for review/notes agents (follow-up work).
- Frontend rendering of citations (can be plain text links initially).

## Technical Options (to be decided in design.md)

1. **pgvector**: add extension to existing Postgres, store embeddings alongside chunks. Simple, no new services.
2. **Redis vector search**: use RediSearch module on existing Redis. Fast but less mature for large datasets.
3. **External service (Qdrant/Pinecone)**: most capable but adds infrastructure complexity.

Recommendation: pgvector for MVP — minimal infrastructure change, sufficient for per-KP teaching materials.

## Dependencies

- Requires: `agent-write-tools` (agent needs multi-turn tool loop to call retrieval).
- Complements: `agent-persistent-memory` (retrieval can be personalized based on learner profile).
- Uses: existing Celery + Redis for async indexing, existing `lesson_sources_json` as source data.
