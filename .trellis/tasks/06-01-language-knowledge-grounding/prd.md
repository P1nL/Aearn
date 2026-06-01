# Language knowledge grounding

## Goal

Upgrade RAG from internal lesson chunks to language-aware official documentation grounding across mainstream languages with source governance and citations.

## Requirements

- Upgrade the current internal lesson-chunk RAG path into language-aware knowledge grounding.
- Support mainstream language source registration for Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS.
- Fetch only allowlisted official or explicitly trusted documentation sources; do not add agent runtime web search.
- Normalize fetched documentation into stable, source-attributed chunks with language/topic metadata.
- Retrieve material by language, topic, knowledge point, and source trust tier.
- Expose citations to agents so grounded answers can identify where supporting material came from.
- Keep fetch/index failures isolated from the primary learning flow.

## Acceptance Criteria

- [x] Source registry defines allowlisted providers, source trust tiers, seed policy, and mainstream language coverage.
- [x] Fetcher can index configured source pages without letting agents browse arbitrary web content at runtime.
- [x] Chunks include title, section path, canonical URL, language, source type, fetched timestamp, and content hash.
- [x] Retrieval filters/ranks by language and topic and degrades gracefully when no official chunk exists.
- [x] Agent-facing retrieval results include enough citation metadata for transparent sourced answers.
- [x] Fixtures and tests cover all target mainstream languages at smoke level.
- [x] Reindex command or service path exposes useful status and does not block normal lesson/session startup on external fetch failures.

## Task Tree

```text
language-knowledge-grounding
├─ grounding-source-registry
├─ official-docs-fetcher
├─ docs-cleaning-and-chunking
├─ language-aware-retrieval
├─ agent-citation-integration
├─ mainstream-language-fixtures
└─ grounding-reindex-observability
```

## Notes

- Completed through archived child tasks:
  - `grounding-source-registry`
  - `official-docs-fetcher`
  - `docs-cleaning-and-chunking`
  - `language-aware-retrieval`
  - `agent-citation-integration`
  - `mainstream-language-fixtures`
  - `grounding-reindex-observability`
