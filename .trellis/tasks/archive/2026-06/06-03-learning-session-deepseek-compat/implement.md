# Implementation Plan

## Before Editing

- Read backend specs:
  - `.trellis/spec/backend/directory-structure.md`
  - `.trellis/spec/backend/error-handling.md`
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/backend/logging-guidelines.md`
- Inspect the existing direct provider pattern:
  - `aearn/services/api/app/services/llm/llm_client.py`
  - `aearn/services/api/app/agents/onboarding/plan_generation_agent.py`
- Inspect failing learning paths:
  - `aearn/services/api/app/agents/learning/learning_conversation_agent.py`
  - `aearn/services/api/app/agents/learning/learning_concept_agent.py`
  - `aearn/services/api/app/services/conversations/learning_conversation.py`
  - `aearn/services/api/app/routes/learning_sessions.py`

## Ordered Checklist

- [x] Add provider-aware direct concept JSON client support for DeepSeek in `learning_concept_agent.py`, reusing `OpenAICompatibleClient.complete_json()`.
- [x] Add provider-aware direct learning text stream support for DeepSeek in `learning_conversation_agent.py`, reusing `OpenAICompatibleClient.complete_text_stream()`.
- [x] Update `learning_conversation.py` client selection so `llm_type=deepseek` uses the direct clients and does not instantiate Agents SDK handoffs for learning message text.
- [x] Confirm implementation does not require model-selected tools for DeepSeek; no Chat Completions tool-call loop was added.
- [x] Preserve OpenAI provider behavior through the existing Agents SDK client.
- [x] Add unit tests in `tests/test_llm_integration.py` for DeepSeek direct JSON and direct streaming client behavior.
- [x] Confirm no DeepSeek tool-call loop was added, so no `tools` / `tool_choice` / assistant `tool_calls` tests are required in this task.
- [x] Add learning-session tests in `tests/test_learning_sessions_m3.py` for DeepSeek direct learning messages and concept repair SSE without `MODEL_UNAVAILABLE`.
- [x] Confirm `show_code_exercise` remains deterministic/backend-generated and does not depend on model text generation.
- [x] Add a SQL practice-card regression so `language=sql` / `runtime_tier=sql_query_test` does not fall through to the browser/JavaScript fallback template.
- [x] Add a SQL learning-session unlock/run regression proving the materialized exercise is SQL and passes `sql_query_test`.
- [x] Keep user-facing errors stable and avoid logging secrets or raw provider payloads.

## Validation Commands

Run from repository root unless noted:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_adaptive_exercise_templates.py tests/test_sql_query_runner.py tests/test_learning_sessions_m3.py::test_sql_learning_session_unlocks_query_exercise -q
```

If focused tests pass, run:

```powershell
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
```

If database-heavy tests deadlock or local services are unavailable, record the exact blocker and rerun the smallest non-DB tests first.

## Implementation Results

- Added `DirectConceptClient` for DeepSeek concept intro/check JSON through `OpenAICompatibleClient.complete_json()`.
- Added `DirectLearningConversationClient` for DeepSeek learning-message text streaming through `OpenAICompatibleClient.complete_text_stream()`.
- Updated `learning_conversation.py` provider selection so DeepSeek does not instantiate `AgentsSDKLearningConversationClient`; OpenAI still uses the existing Agents SDK path.
- Added regressions for DeepSeek direct concept generation, direct text streaming, provider selection, and concept-repair SSE no-`MODEL_UNAVAILABLE`.
- Added a SQL deterministic exercise template using SQLite `setup_sql`, SQL `SELECT` starter/solution code, and `sql_query_test` metadata so SQL sessions no longer materialize the browser/JavaScript fallback.
- Added regressions for SQL adaptive template selection and SQL learning-session practice unlock/run.
- Updated `.trellis/spec/backend/quality-guidelines.md` with reusable contracts for DeepSeek learning-session direct Chat Completions paths and exercise-template runtime alignment.

Verified:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py -q
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
uv --directory .\aearn\services\api run python -m pytest tests/test_adaptive_exercise_templates.py tests/test_sql_query_runner.py tests/test_learning_sessions_m3.py::test_sql_learning_session_unlocks_query_exercise -q
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py tests/test_adaptive_exercise_templates.py tests/test_sql_query_runner.py -q
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-03-learning-session-deepseek-compat
git diff --check
```

## Rollback Points

- Revert changes in `learning_concept_agent.py` if JSON validation or prompt construction regresses.
- Revert changes in `learning_conversation_agent.py` and `learning_conversation.py` if provider selection breaks existing OpenAI SDK tests.
- Do not touch `.claude/skills/grill-me/`; it is unrelated untracked local state.

## Start Gate

Do not run `task.py start` or edit production code until the user approves this planning package.
