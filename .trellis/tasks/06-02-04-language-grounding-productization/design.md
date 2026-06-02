# 04 Language Grounding Productization Design

## Scope

This child productizes official/trusted documentation grounding. It keeps the existing internal lesson RAG contract intact and adds a second, clearly labeled docs-grounding path.

The two evidence layers are:

- `lesson_rag_context`: existing internal teaching chunks from local lesson, exercise, and knowledge-point material.
- `official_docs_grounding`: persisted allowlisted language documentation chunks with citation metadata.

Runtime chat may use only already persisted docs grounding. Fetching/crawling belongs to reindex flows, not learner message generation.

## Data Model

Add additive schema for local docs grounding:

- `grounding_chunks`
  - `chunk_id` primary key from deterministic chunk hashing.
  - `source_id`, `language_id`, `title`, `section_path`, `canonical_url`.
  - `source_type`, `source_trust_tier`, `fetched_at`, `content_hash`, `content`, `topic_tags`.
  - `metadata_json`, `created_at`, `updated_at`.
  - simple full-text search vector for local retrieval.
- `grounding_reindex_runs`
  - run id, mode (`fixture` or `fetch`), status, totals, source reports, timestamps.

The schema is additive and should not alter existing `teaching_chunks`, `learning_messages`, or learning session tables beyond using existing metadata fields.

## Repository and Service Contracts

Introduce a repository module for durable grounding index operations:

- `replace_grounding_chunks(conn, chunks, mode, source_ids=None)` persists a deterministic replacement set.
- `run_and_persist_fixture_grounding_reindex(conn)` runs existing fixture reindex and stores report/chunks.
- `search_persisted_grounding_chunks(conn, query)` loads matching chunks and reuses `retrieve_grounding_chunks`.
- `grounding_metadata_for_agent(items, status)` serializes learner-safe citation payloads.

Existing pure services remain reusable and testable:

- `grounding_sources.py` owns allowlisted source registry.
- `grounding_fetcher.py` owns allowlisted fetch behavior and must not be called from chat generation.
- `grounding_processing.py` owns cleaning/chunk conversion.
- `grounding_retrieval.py` owns ranking.
- `grounding_citations.py` owns citation objects.
- `grounding_reindex.py` owns in-memory reindex reports.

## Learning Agent Integration

Learning message preparation should:

1. Build the existing learning context and internal `rag_context`.
2. Determine the current runtime/language from the learning session context.
3. Query persisted docs grounding for the current language and learner message/topic.
4. Convert results into bounded `AgentGroundingItem` records.
5. Attach a safe `official_docs_grounding` object to `LearningConversationContext.rag_context`.
6. Persist safe metadata in the agent message response.

Prompt input must make evidence boundaries explicit:

- Internal lesson chunks are current local course material.
- Official/trusted docs chunks are external docs that require citation metadata.
- If docs grounding is absent, the model should not imply it consulted docs.

## Citation Metadata Contract

Learner-safe citation metadata includes:

- `citation_id`
- `source_id`
- `title`
- `section_path`
- `canonical_url`
- `source_type`
- `source_trust_tier`
- `content_hash`
- `fetched_at`
- `relevance_score`
- `match_reasons`

It must not include raw prompts, hidden tests, solution references, provider payloads, secrets, or unbounded content.

## Observability

Add a compact grounding status object:

- `status`: `used`, `empty`, `disabled`, or `failed`.
- `source_mode`: `persisted_index`.
- `language_id`
- `query`
- `retrieved_chunk_count`
- `citation_count`
- `fallback_reason`
- `source_ids`

This object is safe to store in metadata and return to the desktop/API caller.

## Failure Behavior

- Missing index returns `status=empty` and `fallback_reason=no_persisted_grounding`.
- Unknown language returns `status=empty` and `fallback_reason=unsupported_language`.
- Repository/search failures are bounded to `status=failed` and do not crash chat generation.
- Chat generation never performs live fetches to compensate for missing index.

## Compatibility

- Existing `teaching_chunks` tests must keep passing.
- Existing learning session API shape remains backward-compatible; new grounding/citation fields are additive.
- Existing graph runtime `rag_context` remains valid and receives a richer docs-grounding subobject.
- Fixture seeding should be deterministic so tests can run without network.

## Rollback

- Drop usage of the repository integration to return to lesson-only RAG.
- The schema is additive; existing tables and flows continue to work if grounding chunks are empty.
- Fixture seed can repopulate docs grounding after local data reset.
