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
- API test batches that call `bootstrap_database()` share the same local database and must be run sequentially; do not launch M2/M3/M4 pytest commands in parallel.

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

## Scenario: M3 Learning Session Start, Run, Hint, Explain, Check, and Submit

### 1. Scope / Trigger

- Trigger: implementing or changing `POST /api/learning-sessions/start`, `run`, `hint`, `explain-error`, `check-explanation`, `submit`, their repository/service modules, or the `attempts` / `learning_sessions` schema contracts that back them.
- Scope: `aearn/services/api/app/routes/learning_sessions.py`, `app/services/learning_session_repository.py`, runner/evaluation helpers, `app/services/exercise_guidance.py`, `app/db/schema.sql`, and M3 API tests.

### 2. Signatures

- `POST /api/learning-sessions/start`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint`
- `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`
- `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit`
- Session reuse lookup signature: active `learning_sessions` rows keyed by `(user_id, plan_id, entry_point, session_type='learn', status='active')`
- Run idempotency signature: `run-exercise:{session_id}:{exercise_id}:{code_hash}:{run_mode}`
- Hint idempotency signature: `hint:{attempt_id}:{blank_key}:{hint_level}`
- Explain-error idempotency signature: `explain-error:{attempt_id}:{request_hash}`
- Explanation-check idempotency signature: `check-explanation:{attempt_id}:{round}`
- Submit idempotency signature: `submit-exercise:{session_id}:{exercise_id}:{attempt_id}:{submit_version}`

### 3. Contracts

- `start` reuses an active session only when `user_id`, `plan_id`, and `knowledge_point_id` all match the existing `entry_point`.
- Starting a different knowledge point under the same plan must create a new `learning_sessions` row; it must not rewrite another active session's `entry_point`.
- `run` writes one `Attempt(run)` per unique payload and may therefore create multiple rows for the same `(session_id, exercise_id)` over time.
- `run` must preserve `Attempt(run)` as the fact record that later hint, explain-error, and explanation-check calls attach to; frontend may show natural action labels but backend must keep the attempt traceable.
- `hint` updates `Attempt.hint_usage_count` on the referenced run attempt and returns the new count; replaying the same `(attempt_id, blank_key, hint_level)` must not increment again.
- `explain-error` may update `Attempt.error_cause`, but must not create a new Attempt and must not double-increment `error_count` on replay.
- `check-explanation` writes both `Attempt.explanation_text` and `Attempt.explanation_check_result`; later submit scoring must prefer this stored check result over a raw free-text fallback when the explanation text still matches.
- Retry safety for `run` / `submit` belongs to `idempotency_records` and `request_id`, not to a blanket unique index that blocks valid later attempts.
- Append-only writes with a unique `request_id` column, such as `review_logs`, must normalize placeholder values like `req_unset` and generate a per-write fallback when the client did not send `X-Request-Id`.
- `submit` may read the referenced run attempt, but `run` must not update `ReviewState`.
- `submit` must carry forward the higher of client-reported and stored `hint_usage_count` / `error_count` so later scoring reflects the real learning trace, not only the final request body.

### 4. Validation & Error Matrix

- Same `run` idempotency key with a different request hash -> `IDEMPOTENCY_CONFLICT` with 409.
- Same `hint` idempotency key with a different request hash -> `IDEMPOTENCY_CONFLICT` with 409.
- Same `check-explanation` round key with a different request hash -> `IDEMPOTENCY_CONFLICT` with 409.
- Same `submit` idempotency key with a different request hash -> `IDEMPOTENCY_CONFLICT` with 409.
- Missing session/exercise/attempt -> documented 404 error code (`SESSION_NOT_FOUND`, `EXERCISE_NOT_FOUND`, `ATTEMPT_NOT_FOUND`).
- Invalid `blank_id`, missing error context, or empty explanation -> `VALIDATION_ERROR` with 400.
- Explanation round > 2 -> `EVALUATION_CONFLICT` with 422.
- `compiled_sandbox_later` run -> `runtime_status=unsupported` with a persisted `Attempt(run)`, but no `ReviewState` mutation.
- Unsupported run attempt submitted for scoring -> `ATTEMPT_STATE_CONFLICT` with 409.

### 5. Good/Base/Bad Cases

- Good: repeat `start` for the same knowledge point and receive the existing `session_id`; repeat `run` with a different payload and receive a new `attempt_id`; call `hint` / `check-explanation` on that attempt and see the stored counts reused by `submit`.
- Base: start knowledge point A, then knowledge point B under the same plan, and keep two distinct active sessions instead of mutating A into B.
- Bad: enforcing `(session_id, exercise_id, attempt_type, submit_version)` as a blanket unique key, or recomputing explanation score from arbitrary frontend text after a stored explanation-check already exists.

### 6. Tests Required

- Assert same `user/plan/knowledge_point` start requests reuse the same session.
- Assert different knowledge points under one plan create distinct active sessions.
- Assert distinct run payloads for the same session/exercise create distinct `Attempt(run)` rows.
- Assert replaying the same run payload returns the stored result instead of duplicating the attempt.
- Assert replaying the same hint request returns the stored hint and does not increment `hint_usage_count`.
- Assert `explain-error` maps a real runtime/test failure to a stable `error_cause`.
- Assert `check-explanation` stops after round 2 and stored partial/failed explanation results downgrade submit outcome.
- Assert 3+ hints degrade submit `fsrs_rating` to `Hard` / non-`Easy`.
- Assert unsupported runtime paths persist `Attempt(run)` but leave `KnowledgePoint.last_exercise_result` and `ReviewState` unchanged.

### 7. Wrong vs Correct

#### Wrong

```sql
CREATE UNIQUE INDEX uq_attempts_submit_identity
ON attempts(session_id, exercise_id, attempt_type, submit_version);
```

This turns idempotency into a business-level uniqueness rule and blocks valid later attempts for the same session/exercise.

#### Correct

```sql
CREATE UNIQUE INDEX uq_attempts_request_id
ON attempts(request_id)
WHERE request_id IS NOT NULL;
```

Keep retry safety on request identity and `idempotency_records`, while allowing distinct run/submit payloads to persist as separate `Attempt` rows.

## Scenario: M4 FSRS Review APIs, Scheduler, and Worker Due Counts

### 1. Scope / Trigger

- Trigger: implementing or changing shared review scheduling, `/api/reviews/*`, `review_logs`, `review_states`, or the due-count Celery task.
- Scope: `app/services/review_scheduler.py`, `app/services/review_repository.py`, `app/routes/reviews.py`, `app/models/reviews.py`, `app/db/schema.sql`, `aearn_worker/worker_app.py`, and M4 API tests.

### 2. Signatures

- `GET /api/reviews/today?user_id={user_id}&due_before={iso?}&limit={n}` returns due review items sorted by `ReviewState.due_at`.
- `POST /api/reviews/start` with `{user_id, knowledge_point_id}` starts or reuses an active `LearningSession(session_type='review')`.
- `POST /api/reviews/{session_id}/exercise-result` with `exercise_id`, optional `attempt_id`, `code`, `filled_blanks`, `submit_version`, optional `explanation_check`, hint/error counts, and optional `code_hash` writes `Attempt(review_submit)`.
- Shared scheduler signature: `apply_attempt_review_update(conn, knowledge_point_id, attempt_id, source, request_id)` updates `ReviewState` only from persisted `Attempt(submit|review_submit)`.
- Worker task signature: `review.refresh_due_counts` reads due `review_states` and returns `{"total_due": int, "counts_by_user": {user_id: count}}`.

### 3. Contracts

- `Attempt(run)` must never update `ReviewState` or write `ReviewLog`.
- Learning submit and review submit must both call the shared scheduler instead of duplicating FSRS update logic.
- Scheduler idempotency key defaults to `review:update:{knowledge_point_id}:{attempt_id}:{rating}`; replay by request id or `(attempt_id, rating, source)` returns the existing next state.
- `review_states` storage still uses legacy `reps` / `lapses`, but API payloads must expose `review_count` / `lapse_count` while preserving `reps` / `lapses` compatibility.
- `review_logs.request_id` and `(attempt_id, rating, source)` must be unique to prevent double counter increments.
- Worker due-count queries are read-only; they must not update `ReviewState`, create `ReviewLog`, or prepare variants.

### 4. Validation & Error Matrix

- Unknown user in due list or start -> `USER_NOT_FOUND` with 404.
- Unknown knowledge point for review start -> `KNOWLEDGE_POINT_NOT_FOUND` with 404.
- No due state, future `due_at`, suspended state, or inactive plan -> `REVIEW_NOT_DUE` with 409.
- Review session/exercise mismatch -> `SESSION_CONFLICT` with 409.
- Missing review session, exercise, or run attempt -> documented 404 error code.
- Same review result idempotency key with different payload -> `IDEMPOTENCY_CONFLICT` with 409.
- Invalid scheduling attempt type, rating, user mismatch, or unevaluated attempt -> `ReviewSchedulingError` and no `ReviewState` mutation.

### 5. Good/Base/Bad Cases

- Good: complete a learning submit, force due, start review, submit a review exercise, and see one `Attempt(review_submit)`, one `ReviewLog(source='review_submit')`, incremented `review_count`, backend `due_at`, and `forget_risk`.
- Base: call due-count worker with existing due rows and verify the returned counts while the row snapshot and log count stay unchanged.
- Bad: computing `due_at` from the request body, updating `review_states` from `Attempt(run)`, or inserting a second `ReviewLog` on retry.

### 6. Tests Required

- Assert `GET /api/reviews/today` returns empty state and due items sorted by `due_at`.
- Assert `POST /api/reviews/start` rejects early items and reuses the active due review session.
- Assert review exercise result writes `Attempt(review_submit)` and updates `ReviewState` exactly once.
- Assert replaying the same review result returns `idempotency_replayed=true` without incrementing `reps`.
- Assert `Attempt(run)` leaves review state unchanged.
- Assert `review.refresh_due_counts` is registered, uses `Asia/Shanghai`, and is read-only.

### 7. Wrong vs Correct

#### Wrong

```python
if attempt_type == "run":
    update_review_state(...)
```

This makes exploratory runs change the spaced-repetition schedule.

#### Correct

```python
apply_attempt_review_update(
    conn,
    knowledge_point_id=knowledge_point_id,
    attempt_id=submit_attempt_id,
    source="learn_submit",
    request_id=request_id,
)
```

Only persisted submit facts can move `ReviewState`, and retries reuse `ReviewLog` instead of mutating counters twice.

## Scenario: OpenAI-Compatible LLM Explain-Error Integration

### 1. Scope / Trigger

- Trigger: adding or changing backend model calls for `explain-error`, hints, evaluation, or other Agent-assisted learning feedback.
- Scope: `app/core/config.py`, `app/services/llm_client.py`, feature-level LLM wrappers, learning-session repositories, API response types, and source-of-truth docs that describe model-backed responses.

### 2. Signatures

- Environment configuration:
  - `LLM_TYPE=openai`
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`
  - optional `LLM_TIMEOUT_SECONDS`
- First model-backed API path: `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`.
- Required response fields remain `error_cause`, `explanation`, `fix_suggestion`, `related_knowledge_points`, and `next_action`.
- Optional diagnostics are `generation_source` (`llm` or `deterministic`) and `generation_model`.

### 3. Contracts

- Feature code must not read raw LLM environment variables directly; it must go through `Settings` and the LLM client boundary.
- The LLM client owns provider URL construction, headers, timeout, and JSON parsing.
- Feature wrappers own prompt construction, evidence minimization, response schema validation, and fallback decisions.
- `related_knowledge_points` returned to the frontend must be server-controlled or reconciled against server-loaded rows, not blindly trusted from the model.
- Real API keys, provider error bodies, raw prompts, full code submissions, and hidden test source must not be returned to the frontend or logged.

### 4. Validation & Error Matrix

- `LLM_TYPE` blank/disabled/none/off -> deterministic fallback.
- `LLM_TYPE=openai` with missing key, base URL, or model -> deterministic fallback.
- Unsupported `LLM_TYPE` -> deterministic fallback unless a new adapter is explicitly implemented and tested.
- Provider HTTP error, timeout, network error, invalid provider JSON, invalid model JSON, missing required fields, unsupported `error_cause`, unsupported `next_action`, code-fence/full-answer style output, or hidden case-id leakage -> deterministic fallback.
- Idempotency replay for the same `attempt_id` plus same error context -> return stored response and do not call the model again.

### 5. Good/Base/Bad Cases

- Good: configured OpenAI-compatible provider returns valid JSON, backend validates it, stores the response once, and returns `generation_source=llm`.
- Base: local developer has no key, endpoint still returns the deterministic response with `generation_source=deterministic`.
- Bad: tests call a live model by default, feature code imports `os.getenv("OPENAI_API_KEY")`, or LLM output controls knowledge-point IDs.

### 6. Tests Required

- Unit-test `Settings` configured/incomplete/disabled behavior without real secrets.
- Unit-test the model client with a fake transport, including base URL to `/chat/completions` and JSON parsing.
- Unit-test the feature wrapper for valid model output, invalid JSON/schema fallback, and hidden-test identifier rejection.
- API or repository test idempotency so a repeated `explain-error` request does not call the model twice.
- Keep existing deterministic API tests isolated from live provider calls by mocking or disabling the LLM path.

### 7. Wrong vs Correct

#### Wrong

```python
api_key = os.getenv("OPENAI_API_KEY")
response = call_provider(api_key, prompt)
return response
```

This leaks configuration into feature code and bypasses schema validation, fallback, and test isolation.

#### Correct

```python
response = build_llm_error_explanation(...) or with_deterministic_generation_metadata(
    build_error_explanation_response(...)
)
```

The feature tries the model only through a testable boundary and keeps deterministic fallback as the stable MVP path.

## Scenario: Backend SSE Streaming for Long-Running POST Endpoints

### 1. Scope / Trigger

- Trigger: implementing or changing `Accept: text/event-stream` behavior on long-running API routes.
- Scope: `app/routes/learning_sessions.py`, `app/routes/notes.py`, `app/services/sse.py`, `app/services/llm_client.py`, note/learning repositories, and API tests that assert SSE frames.

### 2. Signatures

- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit`
- `POST /api/notes/{note_id}/agent-draft`
- Trigger header: `Accept: text/event-stream`
- Default behavior without that header: existing JSON response path remains unchanged.

### 3. Contracts

- Use FastAPI `StreamingResponse` with `media_type="text/event-stream"`; do not introduce WebSocket or queue infrastructure for the MVP streaming path.
- Every SSE frame must include `event: <type>` and a single-line JSON `data:` payload.
- Event types are limited to `agent_message`, `tool_status`, `runner_result`, `evaluation_result`, `done`, and `error`.
- Error events must use the documented API error envelope under `data.error`, including `code`, `message`, `details`, `request_id`, and `recoverable`.
- Preserve `X-Request-Id` from the request when present; tests that write rows covered by unique `request_id` indexes must generate unique request IDs per request.
- Keep JSON and SSE paths as content-negotiated branches over the same repository/service functions so idempotency and database write timing do not drift.

### 4. Validation & Error Matrix

- Invalid request body with `Accept: text/event-stream` -> `error` event with `VALIDATION_ERROR`.
- Missing session, exercise, attempt, user, or note -> `error` event with the same stable code the JSON path would return.
- Idempotency conflict -> `error` event with `IDEMPOTENCY_CONFLICT`, `recoverable=false`.
- Unsupported runtime submit -> `error` event with `ATTEMPT_STATE_CONFLICT`, `recoverable=false`.
- Unexpected server failure -> `error` event with `INTERNAL_ERROR`; do not expose raw provider errors, prompts, code submissions, or secrets.

### 5. Good/Base/Bad Cases

- Good: run streams `tool_status -> runner_result -> done`, while the same request without the SSE `Accept` header still returns the existing JSON run response.
- Base: submit streams `tool_status -> runner_result -> evaluation_result -> done`, using the persisted submit Attempt as the source of truth for final runner and evaluation fields.
- Bad: returning partial success before durable writes commit, streaming multi-line `data:` JSON, or implementing a second code path that bypasses idempotency records.

### 6. Tests Required

- Unit-test SSE frame formatting, including event ids and single-line JSON `data`.
- Unit-test LLM text streaming with a fake transport and no real provider calls.
- API-test run SSE success and error event sequences.
- API-test submit SSE success sequence and confirm JSON mode still passes existing M3 tests.
- API-test note agent-draft SSE `agent_message` chunks and final DB persistence.
- Run the existing milestone pytest batch plus `pnpm --dir .\aearn desktop:check`.

### 7. Wrong vs Correct

#### Wrong

```python
if wants_stream(request):
    yield f"data: {json.dumps(response, indent=2)}\n\n"
```

Indented JSON produces multi-line `data:` content that the desktop hook is not required to parse.

#### Correct

```python
yield writer.event("runner_result", runner_result)
```

The shared SSE writer serializes a compact one-line JSON frame and keeps the event id sequence consistent.
