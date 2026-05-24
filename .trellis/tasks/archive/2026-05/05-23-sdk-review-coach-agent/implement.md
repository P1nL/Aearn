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
   - `docs/architecture/fsrs-scheduling-spec.md`
   - `docs/qa/acceptance-test-plan.md`
3. Inspect:
   - `aearn/services/api/app/routes/reviews.py`
   - `aearn/services/api/app/services/review_repository.py`
   - `aearn/services/api/app/services/review_scheduler.py`
   - `aearn/services/api/tests/test_reviews_m4.py`
   - `aearn/services/api/tests/test_llm_integration.py`

## Phase 1: Lock Review State Boundaries

1. Add or confirm tests proving `reviews/today` ordering is deterministic.
2. Add or confirm tests proving `REVIEW_NOT_DUE` is not affected by SDK behavior.
3. Add tests that review submit still updates `ReviewState` only through scheduler code.

## Phase 2: SDK Review Coach

1. Add `app/agents/review_coach_agent.py`.
2. Implement review startup text and variant reason generation with safe context.
3. Reuse shared guardrail helpers for no hidden-test, no direct-answer, and no provider-error leakage.

## Phase 3: Wire Review Start

1. Wire SDK generation into `start_review_session(...)` text fields.
2. Keep deterministic `_variant_reason(...)` and initial message as fallback.
3. Ensure SDK failure cannot rollback or block safe deterministic review session creation.

## Phase 4: Validation

Run:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run python -m mypy app/agents app/services/review_repository.py app/services/review_scheduler.py
uv --directory .\aearn\services\api run ruff check app/agents app/services/review_repository.py app/services/review_scheduler.py tests/test_reviews_m4.py tests/test_llm_integration.py
uv --directory .\aearn\services\api lock --check
```

## Rollback

Revert `review_coach_agent.py` and review text wiring. Do not revert scheduler or FSRS logic unless a separate regression proves it was changed.
