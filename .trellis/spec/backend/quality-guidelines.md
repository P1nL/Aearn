# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Backend work must preserve the narrow Aearn MVP loop defined by `docs/plans/learning-agent-implementation-plan.md`. The formal API service currently pins dependencies only; implementation begins in Milestone 1 and must follow the documented API, database, runtime, FSRS, and LangGraph contracts.

The dependency source for the API service is `aearn/services/api/pyproject.toml`, which already includes `pytest`, `pytest-asyncio`, `httpx`, `ruff`, and `mypy` in the dev dependency group.

---

## Forbidden Patterns

- Do not write formal MVP backend code in historical `01_` through `07_` tutorial directories.
- Do not upgrade LangChain, LangGraph, FastAPI, Redis, Celery, or Tauri-related versions casually. Version compatibility is part of this repository's contract.
- Do not expose `Attempt(run)` / `Attempt(submit)` as user-facing UI concepts; those are backend facts.
- Do not let settings APIs modify scoring rules, required Attempt facts, or FSRS scheduling rules.
- Do not duplicate `Attempt`, `ReviewState`, or `ReviewLog` writes on retry.
- Do not commit real `.env` files or LLM secrets.

---

## Required Patterns

- Run backend commands from the owning subproject, typically through `uv --directory .\aearn\services\api ...`.
- Check API changes against `docs/architecture/api-contract.md` before implementation.
- Check persistence changes against `docs/architecture/database-schema.md` before implementation.
- Check runner and scoring changes against `docs/architecture/code-completion-evaluation-spec.md`.
- Check LangGraph node and write timing changes against `docs/architecture/langgraph-state-machine.md`.
- Keep local defaults in `.env.example`; never use real external service secrets as examples.

---

## Testing Requirements

- For Milestone 0 dependency checks, run the service-local `uv` commands and Docker Compose health checks documented in the database guidelines.
- For API endpoints, add smoke or contract tests that assert status codes, response envelopes, error codes, and idempotency behavior.
- For database migrations, verify repeatability and core inserts for the tables touched by the task.
- For runner/evaluation logic, test `success`, `runtime_error`, `timeout`, and `unsupported` separately.
- For review scheduling, test that retries do not double-increment review counters.

---

## Code Review Checklist

- The change runs from the correct subproject directory and does not rely on a repository-root Python environment.
- API fields, enums, and error shapes match the contract.
- Database fields, constraints, indexes, and write timing match the schema and state-machine documents.
- Any write operation with retry risk has an idempotency story.
- User content, code submissions, notes, and secrets are not logged.
- P0 acceptance cases from `docs/qa/acceptance-test-plan.md` remain satisfied for the touched flow.

## Scenario: M2 Onboarding Plan APIs

### 1. Scope / Trigger

- Trigger: implementing or changing onboarding profile APIs, course catalog APIs, deterministic plan draft generation, or confirmed plan creation.
- Scope: `aearn/services/api/app/routes/users.py`, `courses.py`, `plans.py`, service/repository modules, and `idempotency_records`.

### 2. Signatures

- `POST /api/users` creates a local user profile.
- `GET /api/users/{user_id}` reads a local user profile.
- `PATCH /api/users/{user_id}/preferences` updates only user preference fields.
- `GET /api/language-courses` returns the seed catalog and runtime capability metadata.
- `POST /api/plans/generate` returns `plan_draft` only; it must not create `learning_plans`.
- `POST /api/plans` persists `learning_plans`, `plan_modules`, `knowledge_points`, and initial `review_states` in one transaction.
- `GET /api/plans/{plan_id}` returns persisted plan detail.
- DB idempotency signature: `idempotency_records(key, operation, request_hash, response_json, created_at)`.

### 3. Contracts

- Preference updates allow only `display_name`, `learning_style`, `teaching_preference`, `encouragement_preference`, `profession`, `background_context`, `preferred_time_slots`, and `reminder_preference`.
- Preference updates must reject scoring, Attempt persistence, FSRS parameter, and `due_at` fields with `VALIDATION_ERROR`.
- `POST /api/plans/generate` validates `goal_based.goal_text` or `material_based.materials[*].content`, then reads `users`, `language_courses`, and `runtime_profiles`.
- JS/HTML/CSS/Python drafts must expose `browser_preview` or `python_stdout_test`; Java/C++ drafts may be returned only with `compiled_sandbox_later` notices.
- Confirmed plans normalize `target_level=beginner_to_intermediate` to the DB-supported `beginner` value.
- Confirm plan default idempotency key is `confirm-plan:{user_id}:{plan_draft.draft_id}` unless `Idempotency-Key` is provided.

### 4. Validation & Error Matrix

- Unknown user -> `USER_NOT_FOUND` with 404.
- Unknown course -> `COURSE_NOT_FOUND` with 404.
- Missing goal/material input -> `VALIDATION_ERROR` with 400.
- Invalid `plan_draft` shape, user mismatch, no modules, or no non-skippable core module -> `PLAN_DRAFT_INVALID` with 422.
- Same idempotency key with a different request hash -> `IDEMPOTENCY_CONFLICT` with 409.
- FastAPI/Pydantic validation errors must be normalized to the documented error envelope.

### 5. Good/Base/Bad Cases

- Good: generate draft, confirm once, replay same request, and receive the existing plan without duplicate modules or review states.
- Base: Java/C++ course is visible in catalog and draft generation returns an unsupported runtime notice without promising execution.
- Bad: a settings request modifies `fsrs_parameters`, a plan draft creates `Attempt` rows, or `POST /api/plans/generate` writes formal plan rows.

### 6. Tests Required

- Assert user create/get/preference update success.
- Assert forbidden preference fields return `VALIDATION_ERROR`.
- Assert catalog includes Java/C++ `compiled_sandbox_later` entries.
- Assert goal and material generation success, insufficient input, unknown user, and unknown course.
- Assert confirm plan creates plan/module/knowledge point rows and one `review_states` row per knowledge point.
- Assert idempotent replay returns the original plan and conflicting request body returns `IDEMPOTENCY_CONFLICT`.

### 7. Wrong vs Correct

#### Wrong

```python
@router.get("/api")
def route() -> dict[str, object] | JSONResponse:
    ...
```

FastAPI tries to build a response model from the union and can fail during app import.

#### Correct

```python
@router.get("/api", response_model=None)
def route() -> dict[str, object] | JSONResponse:
    ...
```

When a route may return both normal JSON and `JSONResponse` error envelopes, disable response model inference explicitly.
