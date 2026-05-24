# Implementation Plan

## Status

This task is in `planning`. Do not implement until it is explicitly started with `task.py start`.

## Preconditions

1. Finish `05-23-sdk-teaching-tools-guardrails`.
2. Read:
   - `.trellis/spec/backend/index.md`
   - `.trellis/spec/backend/quality-guidelines.md`
   - `docs/product/user-flows.md`
   - `docs/architecture/api-contract.md`
   - `docs/architecture/langgraph-state-machine.md`
   - `docs/qa/acceptance-test-plan.md`
3. Inspect:
   - `aearn/services/api/app/routes/notes.py`
   - `aearn/services/api/app/services/note_repository.py`
   - `aearn/services/api/models/notes.py` or `aearn/services/api/app/models/notes.py`
   - `aearn/services/api/tests/test_notes_m5.py`
   - `aearn/services/api/tests/test_llm_integration.py`

## Phase 1: Preserve Current Contracts

1. Lock current JSON and SSE behavior in tests where missing.
2. Add tests proving `content_markdown` remains user-owned.
3. Add tests proving CodeDraft terms/routes are not reintroduced.

## Phase 2: SDK Note Assist Client

1. Add `app/agents/note_assist_agent.py`.
2. Build safe context from bounded note and attempt summaries.
3. Reuse shared guardrail helpers to block hidden-test, provider-error, full-note-rewrite, and CodeDraft leakage.

## Phase 3: Wire Generation

1. Replace direct `OpenAICompatibleClient` note draft calls with SDK Note Assist through a small adapter.
2. Keep deterministic fallback chunks available.
3. Preserve current SSE event names and `agent_draft_content` storage timing.

## Phase 4: Validation

Run:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_notes_m5.py
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py
uv --directory .\aearn\services\api run python -m mypy app/agents app/services/note_repository.py app/routes/notes.py
uv --directory .\aearn\services\api run ruff check app/agents app/services/note_repository.py app/routes/notes.py tests/test_notes_m5.py tests/test_llm_integration.py
uv --directory .\aearn\services\api lock --check
```

## Rollback

Revert `note_assist_agent.py` and the note draft wiring. Keep Note CRUD and deterministic note draft generation intact.
