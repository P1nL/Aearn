# Docs cleaning and chunking

## Goal

Normalize fetched documentation into stable chunks with titles, section paths, canonical URLs, content hashes, and source metadata.

## Confirmed Facts

- `grounding_fetcher.py` returns `GroundingFetchDocument` with source id, language id, canonical URL, final URL, content type, fetched timestamp, raw content, and content hash.
- `grounding_sources.py` owns source trust tier, source type, provider, and topic tags.
- Current `teaching_chunks.py` indexes internal lesson content only; this task should not replace that DB path.
- Retrieval, citation formatting, fixture coverage, and reindex observability are separate child tasks.

## Requirements

- Add a deterministic cleaner/chunker service for fetched documentation.
- The cleaner must extract readable text from basic HTML while ignoring script/style/nav-like noise.
- Chunk output must include source id, language id, title, section path, canonical URL, source type, source trust tier, fetched timestamp, content hash, text, and topic tags.
- Chunk ids and content hashes must be stable for the same source URL/section/text.
- Chunk size must be bounded and deterministic without requiring embeddings.
- Empty or unreadable documents must return an empty tuple, not raise.

## Acceptance Criteria

- [ ] HTML heading/paragraph content is converted into section-aware chunks.
- [ ] Script/style content is excluded.
- [ ] Chunk metadata includes canonical URL, language id, source id, trust tier, source type, fetched timestamp, and content hash.
- [ ] Identical input produces identical chunk ids and hashes.
- [ ] Empty content degrades to no chunks.
- [ ] No database migration or network fetch is added.

## Out of Scope

- Retrieval ranking.
- Agent-facing citation payloads.
- Persisting chunks to `teaching_chunks` or a new table.
- Fetch orchestration and reindex reporting.
