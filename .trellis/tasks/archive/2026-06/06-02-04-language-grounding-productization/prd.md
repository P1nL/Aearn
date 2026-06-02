# 04 Language grounding productization

## Goal

Productize Aearn's official/trusted language documentation grounding so learning conversations can use locally indexed docs evidence with safe citation metadata. This child connects the existing `grounding_*` service layer to durable local indexing, learning-agent context preparation, response metadata, and deterministic regression/eval coverage.

This is not live web RAG. Runtime chat must not crawl or search arbitrary web content. Documentation grounding is available only from allowlisted sources that have been fetched through deterministic reindexing or seeded through fixtures.

## User Value

- Learners get language explanations grounded in official/trusted documentation when that evidence is available.
- The product can show or carry citation metadata for docs-grounded answers without exposing raw prompts, hidden tests, provider payloads, or internal implementation details.
- Local development has a deterministic fixture seed/reindex path, so grounding behavior can be tested without network access.
- Grounding failures degrade safely to internal lesson context instead of breaking learning chat.

## Confirmed Facts

- Internal lesson RAG already exists through `teaching_chunks`, sourced from knowledge point outlines, lesson sources, exercise prompts, and knowledge point descriptions.
- Official/trusted docs grounding already has service-layer modules for source registry, allowlisted fetching, processing, retrieval, citation packaging, fixtures, and reindex reports.
- Existing `grounding_*` services currently return in-memory chunks/reports; they are not yet persisted as a product index.
- Learning conversation context already carries `rag_context`, but it is currently lesson/internal RAG oriented and does not carry official/trusted docs citations.
- The parent task requires grounding index persistence, learning-agent integration, citation UX/metadata, and grounding observability/evals.
- This child depends on the language capability matrix and existing `grounding_*` service layer.

## Requirements

- Add a durable local grounding index for allowlisted official/trusted docs chunks and reindex reports.
- Support deterministic fixture seeding/reindexing for local development and tests without network access.
- Support source-scoped and language-scoped retrieval from persisted grounding chunks.
- Integrate official/trusted docs grounding into learning message preparation without replacing internal lesson RAG.
- Keep prompt context explicit: lesson/internal context and official/trusted docs context are separate evidence sections.
- Add safe citation/grounding metadata to agent responses when official/trusted docs grounding is used.
- Persist learner-safe grounding metadata in learning message metadata or response payloads.
- Expose observability fields for grounding availability, chunk counts, citation counts, fallback reason, and source mode.
- Ensure grounding failures do not crash chat and do not trigger arbitrary live web search.
- Add tests for persistence, deterministic fixture seed, learning-agent integration, citation metadata, and no-live-search fallback behavior.

## Acceptance Criteria

- [x] A local database table or repository persists docs grounding chunks with source id, language id, canonical URL, section path, trust tier, content hash, fetched timestamp, text, and topic tags.
- [x] Reindexing can persist fixture-generated grounding chunks for all language capabilities without network access.
- [x] Reindexing can replace stale chunks for a source/language deterministically rather than accumulating duplicates.
- [x] Learning message preparation retrieves docs grounding from the persisted index for the current knowledge point language when available.
- [x] Learning prompt input distinguishes `lesson_rag_context` from `official_docs_grounding` or equivalent safe sections.
- [x] Agent response payloads include learner-safe citation metadata when docs grounding is used.
- [x] Stored `learning_messages.metadata` or response metadata includes citation ids/URLs/trust tiers/content hashes without raw prompt or hidden data.
- [x] If no persisted docs grounding exists, the learning conversation still succeeds and records a safe fallback reason.
- [x] Runtime chat does not instantiate the live docs fetcher or perform arbitrary web search.
- [x] Focused grounding, teaching chunk, graph/runtime, and learning session tests pass.

## Out of Scope

- Arbitrary live web search during learner chat.
- Vector database integration or embedding-based semantic search.
- Automatic background crawling of documentation sites.
- Install guidance templates or environment doctor behavior; those belong to child `05`.
- Expanding L3 execution support; runner work belongs to child `06`.
- Desktop visual redesign beyond safe citation/metadata plumbing needed for this child.

## Notes

- Canonical planning artifacts stay English. `review.zh.md` provides the Chinese review summary requested by the user.
- The user explicitly asked to proceed directly through the remaining children, so implementation may start after artifacts validate instead of waiting for a separate review turn.
