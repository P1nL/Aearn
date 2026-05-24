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
   - `aearn/services/api/app/routes/plans.py`
   - `aearn/services/api/app/services/plan_generator.py`
   - `aearn/services/api/app/services/plan_repository.py`
   - `aearn/services/api/app/models/onboarding.py`
   - `aearn/services/api/tests/test_onboarding_m2.py`
   - `aearn/services/api/tests/test_llm_integration.py`

## Phase 1: Lock Existing Plan Contract

1. Confirm `POST /api/plans/generate` deterministic response fields.
2. Confirm `POST /api/plans` idempotency and validation tests.
3. Add missing tests for unsupported runtime claims if not already covered.

## Phase 2: SDK Plan Agent

1. Add `app/agents/onboarding_plan_agent.py`.
2. Build safe course/runtime context tools or summaries.
3. Parse SDK output into existing `PlanDraft` Pydantic models.
4. Add guardrails against unsupported runtime promises and generic subject expansion.

## Phase 3: Route/Service Wiring

1. Wire SDK candidate generation into `POST /api/plans/generate`.
2. Keep deterministic `build_plan_draft(...)` as fallback.
3. Keep `confirm_plan(...)` unchanged except for any necessary validation reuse.

## Phase 4: Validation

Run:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py
uv --directory .\aearn\services\api run python -m pytest tests/test_dashboard_resume_m6.py
uv --directory .\aearn\services\api run python -m mypy app/agents app/services/plan_generator.py app/routes/plans.py
uv --directory .\aearn\services\api run ruff check app/agents app/services/plan_generator.py app/routes/plans.py tests/test_onboarding_m2.py tests/test_llm_integration.py
uv --directory .\aearn\services\api lock --check
```

## Rollback

Revert `onboarding_plan_agent.py` and plan-generation wiring. Keep deterministic plan generation and confirm-plan persistence intact.
