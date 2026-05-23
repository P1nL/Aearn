# Implementation Plan

## Status

This task is in `planning`. Do not implement until it is explicitly started with `task.py start`.

## Preconditions

1. Finish `05-23-sdk-teaching-tools-guardrails`.
2. Read:
   - `.trellis/spec/backend/index.md`
   - `.trellis/spec/backend/quality-guidelines.md`
   - `docs/architecture/api-contract.md`
   - `docs/architecture/langgraph-state-machine.md`
   - `docs/architecture/code-completion-evaluation-spec.md`
   - `docs/qa/acceptance-test-plan.md`
3. Inspect:
   - `aearn/services/api/app/services/learning_session_repository.py`
   - `aearn/services/api/app/services/exercise_guidance.py`
   - `aearn/services/api/app/services/llm_explain_error.py`
   - `aearn/services/api/app/routes/learning_sessions.py`
   - `aearn/services/api/tests/test_learning_sessions_m3.py`
   - `aearn/services/api/tests/test_llm_integration.py`

## Phase 1: Context And Contracts

1. Identify exact response shapes for hint, explain-error, and explanation-check.
2. Extract or add safe context builders that exclude hidden tests and full answer material.
3. Add tests that lock current deterministic response shape before SDK wiring.

## Phase 2: SDK Exercise Coach

1. Add `app/agents/exercise_coach_agent.py`.
2. Reuse `sdk_runtime.py`, `tools.py`, and `guardrails.py` from earlier SDK tasks.
3. Add fake-runner tests for valid output, invalid output, model failure, and guardrail block.

## Phase 3: Repository Wiring

1. Wire SDK generation into hint generation with deterministic fallback.
2. Wire SDK generation into explain-error without changing `Attempt` writes.
3. Wire SDK generation into explanation-check without changing the max-two-round rule.
4. Ensure no SDK exception can skip idempotency conflict handling.

## Phase 4: Validation

Run:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run python -m mypy app/agents app/services/learning_session_repository.py
uv --directory .\aearn\services\api run ruff check app/agents app/services/learning_session_repository.py tests/test_llm_integration.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api lock --check
```

## Rollback

Revert the Exercise Coach SDK module and wiring. Keep deterministic builders and existing endpoint behavior intact.
