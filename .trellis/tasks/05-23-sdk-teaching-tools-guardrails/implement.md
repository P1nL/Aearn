# Implementation Plan

## Status

This task is in `planning`. Do not implement until it is explicitly started with `task.py start`.

## Preconditions

1. Confirm `05-23-openai-agents-sdk-foundation` has been committed and archived or is otherwise no longer blocking this task.
2. Read:
   - `.trellis/spec/backend/index.md`
   - `.trellis/spec/backend/quality-guidelines.md`
   - `docs/architecture/api-contract.md`
   - `docs/architecture/langgraph-state-machine.md`
   - `docs/qa/acceptance-test-plan.md`
3. Inspect current files:
   - `aearn/services/api/app/agents/sdk_runtime.py`
   - `aearn/services/api/app/agents/learning_conversation_agent.py`
   - `aearn/services/api/app/services/learning_conversation.py`
   - `aearn/services/api/app/routes/learning_sessions.py`
   - `aearn/services/api/tests/test_llm_integration.py`
   - `aearn/services/api/tests/test_learning_sessions_m3.py`

## Phase 1: Read-Only Tools

1. Add `app/agents/tools.py`.
2. Define safe data structures or helper functions for tool output.
3. Wrap only pre-sanitized `LearningConversationContext` data at first.
4. Add unit tests that assert hidden test IDs, reference answers, and full code are absent.

## Phase 2: Teaching Agent Wiring

1. Add tool factory wiring to `AgentsSDKLearningConversationClient`.
2. Keep `TextCompletionClient.complete_text_stream(...)` unchanged.
3. Preserve deterministic fallback and existing service-level storage.
4. Avoid exposing tool events through public API responses.

## Phase 3: Guardrails

1. Add `app/agents/guardrails.py`.
2. Implement small pure helpers first, then SDK guardrail adapters if practical.
3. Add tests for blocked hidden IDs, provider errors, reference answers, and direct-answer leakage.
4. Make guardrail failures map to existing deterministic fallback or recoverable SSE error behavior.

## Phase 4: Validation

Run:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run python -m mypy app/agents
uv --directory .\aearn\services\api run ruff check app/agents app/services/learning_conversation.py tests/test_llm_integration.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api lock --check
```

If `uv run mypy` hits the Windows trampoline issue, use:

```powershell
uv --directory .\aearn\services\api run python -m mypy app/agents
```

## Rollback

Revert only `tools.py`, `guardrails.py`, and Teaching Agent wiring changes. Keep the first SDK foundation client and dependency intact unless the SDK path itself is the failure source.
