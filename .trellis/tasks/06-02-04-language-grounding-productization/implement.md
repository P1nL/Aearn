# 04 Language Grounding Productization Implementation Plan

## Ordered Steps

- [x] Add additive database schema for persisted grounding chunks and reindex runs.
- [x] Implement a grounding index repository with chunk serialization/deserialization, deterministic replacement, fixture seeding, persisted search, and learner-safe metadata serialization.
- [x] Extend `grounding_reindex.py` or a companion service so fixture reindex reports can be persisted without network.
- [x] Integrate persisted docs grounding into learning message preparation after internal lesson RAG is built.
- [x] Add docs-grounding context to tutor prompt input while preserving the existing internal lesson context.
- [x] Add citation/grounding metadata to the built learning response and stored agent message metadata.
- [x] Add focused tests for persistence, fixture seed, replacement/idempotency, retrieval, no-index fallback, citation metadata, and learning-message integration.
- [x] Run focused backend tests and desktop check if API response types affect frontend compilation.
- [ ] Validate and archive the Trellis child after implementation verification passes.

## Validation Commands

```powershell
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-02-04-language-grounding-productization
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_sources.py tests/test_grounding_fetcher.py tests/test_grounding_processing.py tests/test_grounding_retrieval.py tests/test_grounding_citations.py tests/test_grounding_fixtures.py tests/test_grounding_reindex.py tests/test_teaching_chunks.py tests/test_learning_sessions_m3.py tests/test_graph_runtime_contracts.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
git diff --check
```

## Risky Files

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/services/learning_conversation.py`
- `aearn/services/api/app/services/grounding_*.py`
- `aearn/services/api/tests/test_learning_sessions_m3.py`
- New grounding persistence tests

## Guardrails

- Do not call `GroundingDocsFetcher` from learner chat/message generation.
- Do not expose raw prompt, hidden tests, solution references, provider payloads, or unbounded docs content.
- Do not merge official docs grounding with `teaching_chunks`; keep contracts distinct.
- Do not claim live web RAG.
- Keep all changes additive to existing API responses and schema.
