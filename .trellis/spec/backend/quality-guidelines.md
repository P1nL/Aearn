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
- JS/HTML/CSS/Python draft templates must be multi-module routes organized by official learning taxonomies, then adapted to Aearn's executable verification loop:
  - Python follows Python Tutorial-style categories such as basics/value flow, control flow/functions, data structures, modules/I/O, errors/tests, and classes/code review.
  - JavaScript follows MDN JavaScript Guide-style categories such as language basics, control flow/functions, objects/state, DOM events, async/modules, and generated-code verification.
  - HTML/CSS follows MDN learning module-style categories such as HTML structure, forms/accessibility, selectors/cascade/box model, text styling, layout, and responsive review.
- Confirmed plans normalize `target_level=beginner_to_intermediate` to the DB-supported `beginner` value.
- Confirm plan default idempotency key is `confirm-plan:{user_id}:{plan_draft.draft_id}` unless `Idempotency-Key` is provided.
- Onboarding conversation route-ready turns must emit a short `agent_message` plus a persisted `show_learning_route` tool call, not a long plain-text route body.
- Onboarding message idempotency replay must re-emit stored `metadata.tool_calls` so desktop resume/retry rehydrates the same route card.
- Time-budget-only onboarding revisions must update the route tool args and draft identity; missing time budget must not block initial route-card generation.
- Post-MVP dynamic plan generation may replace draft modules with `agent_generated` modules only after a deterministic `PlanDraft` has established user, course, runtime boundary, and draft identity.
- `PLAN_GENERATION_ENABLED=false`, missing model configuration, missing dynamic client, invalid dynamic output, guardrail rejection, or web-tool failure must fall back to server-owned `COURSE_TEMPLATES` or a validated onboarding plan candidate without exposing raw provider/tool errors.
- `EXA_API_KEY` is optional and only enables the web tools used by `plan_generation_agent`; real keys must stay in local `.env`, never in docs, tests, logs, or fixtures.
- Dynamic plan generation must use OpenAI-compatible SDK calls with `temperature=None` unless provider support for sampling parameters is explicitly tested; third-party Responses-compatible providers may reject `temperature` and must not turn route generation into a slow failure path.
- Adding a public language such as TypeScript, Rust, or Go requires updating the Pydantic `Language` literal, database CHECK constraints, catalog seed, runtime boundary, API examples, and acceptance tests. Adding an `AUTHORITATIVE_DOCS` URL alone is not sufficient.

### 4. Validation & Error Matrix

- Unknown user -> `USER_NOT_FOUND` with 404.
- Unknown course -> `COURSE_NOT_FOUND` with 404.
- Missing goal/material input -> `VALIDATION_ERROR` with 400.
- Invalid `plan_draft` shape, user mismatch, no modules, or no non-skippable core module -> `PLAN_DRAFT_INVALID` with 422.
- Invalid dynamic modules -> fallback; invalid dynamic modules plus no safe fallback -> `PLAN_DRAFT_INVALID` with 422.
- Unsupported or unregistered language -> `COURSE_NOT_FOUND` / validation failure; do not synthesize a confirmable plan from web search alone.
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
- Assert supported MVP course templates keep the official-taxonomy module order and do not regress to one-module route cards.
- Assert `PLAN_GENERATION_ENABLED=false` preserves the template path and response shape.
- Assert fake dynamic plan success swaps modules to `agent_generated` while preserving `PlanDraft` identity and runtime boundary.
- Assert malformed dynamic output, unsafe output, missing web tools, and thrown SDK errors fall back without leaking provider/tool details.
- Tests that indirectly call `/api/plans/generate` through `_confirmed_plan()` must monkeypatch dynamic and onboarding plan clients to fake/offline responses; local `.env` may contain real `OPENAI_*` and `EXA_API_KEY`, but routine DB test batches must never call live providers.
- Assert unregistered languages cannot become confirmable plans until language enum, DB constraints, catalog, runtime boundary, API docs, and acceptance tests are updated together.
- Assert confirm plan creates plan/module/knowledge point rows and one `review_states` row per knowledge point.
- Assert idempotent replay returns the original plan and conflicting request body returns `IDEMPOTENCY_CONFLICT`.
- Assert route-ready onboarding SSE stores and replays `show_learning_route` metadata, including time-budget-only revisions.

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
- Optional diagnostics on successful model responses are `generation_source=llm` and `generation_model`.

### 3. Contracts

- Feature code must not read raw LLM environment variables directly; it must go through `Settings` and the LLM client boundary.
- The LLM client owns provider URL construction, headers, timeout, and JSON parsing.
- Feature wrappers own prompt construction, evidence minimization, response schema validation, and model-error mapping.
- `related_knowledge_points` returned to the frontend must be server-controlled or reconciled against server-loaded rows, not blindly trusted from the model.
- Real API keys, provider error bodies, raw prompts, full code submissions, and hidden test source must not be returned to the frontend or logged.

### 4. Validation & Error Matrix

- `LLM_TYPE` blank/disabled/none/off -> `MODEL_UNAVAILABLE`.
- `LLM_TYPE=openai` with missing key, base URL, or model -> `MODEL_UNAVAILABLE`.
- Unsupported `LLM_TYPE` -> `MODEL_UNAVAILABLE` unless a new adapter is explicitly implemented and tested.
- Provider HTTP error, timeout, network error, invalid provider JSON, invalid model JSON, missing required fields, unsupported `error_cause`, unsupported `next_action`, complete-answer style output, or hidden case-id leakage -> `MODEL_UNAVAILABLE`.
- Idempotency replay for the same `attempt_id` plus same error context -> return stored response and do not call the model again.

### 5. Good/Base/Bad Cases

- Good: configured OpenAI-compatible provider returns valid JSON, backend validates it, stores the response once, and returns `generation_source=llm`.
- Base: local developer has no key, model-backed endpoints return `MODEL_UNAVAILABLE`; tests stay model-key-free through fake clients, not local rule-generated substitute content.
- Bad: tests call a live model by default, feature code imports `os.getenv("OPENAI_API_KEY")`, or LLM output controls knowledge-point IDs.

### 6. Tests Required

- Unit-test `Settings` configured/incomplete/disabled behavior without real secrets.
- Unit-test the model client with a fake transport, including base URL to `/chat/completions` and JSON parsing.
- Unit-test the feature wrapper for valid model output, invalid JSON/schema rejection, and hidden-test identifier rejection.
- API or repository test idempotency so a repeated `explain-error` request does not call the model twice.
- Keep API tests isolated from live provider calls by injecting fake model clients.

### 7. Wrong vs Correct

#### Wrong

```python
api_key = os.getenv("OPENAI_API_KEY")
response = call_provider(api_key, prompt)
return response
```

This leaks configuration into feature code and bypasses schema validation, model-error mapping, and test isolation.

#### Correct

```python
response = build_llm_error_explanation(...)
if response is None:
    raise LLMCallError("model output is required")
```

The feature tries the model only through a testable boundary; missing or invalid output becomes `MODEL_UNAVAILABLE`.

## Scenario: SDK Exercise Coach Modules

### 1. Scope / Trigger

- Trigger: adding or changing SDK-backed coaching for learning-session `hint`, `explain-error`, or `check-explanation`.
- Scope: `app/agents/exercise_coach_agent.py`, `app/agents/sdk_runtime.py`, `app/agents/guardrails.py`, `app/services/learning_session_repository.py`, `app/services/exercise_guidance.py`, and M3/LLM integration tests.

### 2. Signatures

- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint`
- `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`
- `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation`
- SDK module signature: `app/agents/exercise_coach_agent.py`
- Repository owner: `app/services/learning_session_repository.py`

### 3. Contracts

- SDK modules may build prompts, call the SDK runner, validate structured output, and apply teaching guardrails.
- SDK modules must not import database connection types or mutate `Attempt`, `ReviewState`, `ReviewLog`, `LearningSession`, `Note`, or `idempotency_records`.
- Repository code owns session/exercise/attempt loading, idempotency lookup/storage, `Attempt.hint_usage_count`, `Attempt.error_cause`, `Attempt.explanation_text`, and `Attempt.explanation_check_result` writes.
- SDK inputs must be safe summaries: bounded exercise metadata, blank metadata, visible-test summaries, bounded runtime/stderr facts, and bounded code excerpts only when needed.
- SDK inputs and outputs must not expose hidden test ids, hidden test source, `solution_reference`, full submitted code, provider raw errors, SDK event names, API keys, or raw prompts.
- SDK output must normalize back to the existing public response shapes.
- `MODEL_UNAVAILABLE` is required when model config is disabled or incomplete, SDK execution fails, output validation fails, or guardrails block output.

### 4. Validation & Error Matrix

- Model config disabled, incomplete, unsupported, or unavailable -> `MODEL_UNAVAILABLE`.
- SDK runner exception, invalid SDK event stream, invalid JSON, missing required fields, unsupported enum, or empty output -> `MODEL_UNAVAILABLE`.
- Guardrail-blocked learner input or model output -> `MODEL_UNAVAILABLE` without leaking block internals.
- Hidden test id/source, `solution_reference`, full answer, provider detail, SDK event name, or API key in output -> `MODEL_UNAVAILABLE`.
- Idempotency replay for the same request key -> return the stored response and do not call the SDK again.
- Idempotency key reused with a different request hash -> existing `IDEMPOTENCY_CONFLICT` behavior.

### 5. Good/Base/Bad Cases

- Good: configured SDK returns valid structured coaching, repository stores the same `Attempt` fields as before, and response shape is unchanged.
- Base: local developer has no model key; hint, explain-error, and check-explanation return `MODEL_UNAVAILABLE`, while tests stay model-key-free through fake SDK clients.
- Bad: SDK code imports `psycopg.Connection`, writes `Attempt` rows, exposes hidden case ids, controls `related_knowledge_points`, or changes public response envelopes.

### 6. Tests Required

- Unit-test fake SDK success for hint, explain-error, and explanation-check without live model credentials.
- Unit-test invalid SDK output and guardrail-blocked leakage returning `MODEL_UNAVAILABLE` at the owning route boundary.
- API-test the learning-session endpoints for unchanged response envelopes, idempotent replay, and repository-owned `Attempt` writes.

### 7. Wrong vs Correct

#### Wrong

```python
agent_response = exercise_coach_agent.update_attempt_and_return_response(conn, attempt_id)
```

This lets the SDK layer own durable product writes and bypasses repository idempotency.

#### Correct

```python
response = build_sdk_hint_response(...) or build_hint_response(...)
```

The SDK layer only proposes validated coaching output; repository code still owns `MODEL_UNAVAILABLE` mapping, writes, and idempotency storage.

## Scenario: Learning Session Message Streaming Conversation

### 1. Scope / Trigger

- Trigger: implementing or changing model-backed learning conversation messages for the active learning workspace.
- Scope: `POST /api/learning-sessions/{session_id}/messages`, `LearningMessageRequest`, `app/services/learning_conversation.py`, `app/services/llm_client.py`, `idempotency_records`, and API tests for JSON and SSE modes.
- SDK-backed Agent modules for this flow belong under `app/agents/`, for example `app/agents/learning_conversation_agent.py` and `app/agents/sdk_runtime.py`.

### 2. Signatures

- `POST /api/learning-sessions/{session_id}/messages`
- Request body: `{ "role": "user", "content": string, "client_message_id": string }`
- Streaming selector: `Accept: text/event-stream`
- Request tracing: optional `X-Request-Id`
- Idempotency key: `learning-message:{session_id}:{client_message_id}`
- Local protocol boundary: `TextCompletionClient.complete_text_stream(messages, temperature=None)`.
- Default configured model path: `AgentsSDKLearningConversationClient.complete_text_stream(...)`, backed by `openai-agents`.
- Dependency signature: `openai-agents==0.17.3` in `aearn/services/api/pyproject.toml`.
- SDK tool factory signature: `app/agents/tools.py::build_teaching_tools(messages) -> list[Tool]`.
- SDK guardrail factory signature: `app/agents/guardrails.py::build_teaching_guardrails() -> tuple[list[InputGuardrail], list[OutputGuardrail]]`.

### 3. Contracts

- JSON mode returns `agent_message`, `session_state`, `generation_source`, and optional `generation_model`.
- SSE mode emits one or more `agent_message` events and exactly one terminal `done` event on success.
- `agent_message` data must include `request_id`, `session_id`, `message_id`, `delta`, and accumulated `content`.
- `done` data must include `request_id`, `session_id`, `message_id`, `generation_source`, `generation_model`, and a `result_ref`.
- Provider configuration, raw provider errors, API keys, hidden test source, hidden case IDs, and reference answers must never be returned or logged.
- The prompt context may include current knowledge point, lesson outline, sanitized current-stage state, safe exercise prompt/starter code, visible run summary, learner message, and safe conversation continuity only.
- Safe conversation continuity is `conversation_context.safe_summary` plus the most recent bounded `recent_safe_messages`; it must be generated or reused after sanitizing stored `learning_messages`, not by injecting full raw chat history.
- `conversation_summary` belongs under `learning_sessions.learning_stage_state_json` as versioned session state. It must include refresh metadata such as message count and stage so the service can avoid every-turn summary refresh.
- Direct-answer requests from learners are not input-guardrail failures by default. Detect them separately and feed `response_policy.direct_answer_requested=true` so the tutor redirects to local hints or checks without giving a full answer.
- Aearn-owned SDK modules may use SDK `Agent`, `Runner.run_streamed`, `ModelSettings`, and `OpenAIProvider`, but product API shapes and durable state remain in Aearn services/repositories.
- Teaching-agent SDK tools may read only the already-sanitized learning evidence prepared by `learning_conversation.py`; they must return bounded summaries and must not read or write repositories directly.
- Teaching-agent SDK tools must not return hidden case IDs, hidden test source, `solution_reference`, full submitted code, provider payloads, raw prompts, API keys, or full note bodies.
- Teaching-agent guardrails must exist at the SDK-agent boundary and at the public response boundary so fake clients and SDK clients both pass through the same leak checks before JSON or SSE output reaches the frontend.
- SDK tracing must be disabled by default for this path unless a dedicated tracing configuration is explicitly designed.
- SDK provider base URL handling must preserve existing `OPENAI_BASE_URL` behavior: both `https://provider.example` and `https://provider.example/v1` must resolve to the OpenAI client base URL ending in `/v1`.
- When model configuration is disabled, incomplete, failing, or produces an invalid/empty stream, return `MODEL_UNAVAILABLE`.

### 4. Validation & Error Matrix

- Blank `content` or `client_message_id` -> `VALIDATION_ERROR` with 400 in JSON mode or one SSE `error` event in streaming mode.
- Missing or inactive learning session -> `SESSION_NOT_FOUND` with 404 in JSON mode or one SSE `error` event in streaming mode.
- Same idempotency key with a different request body -> `IDEMPOTENCY_CONFLICT`, `recoverable=false`.
- Same idempotency key with the same request body -> replay the stored completed assistant message; SSE replay may send it as one `agent_message` plus `done`.
- Model failure before useful output -> `MODEL_UNAVAILABLE`.
- SDK runner exception, invalid SDK event stream, or empty SDK output before useful output -> `MODEL_UNAVAILABLE`.
- Guardrail-blocked learner request or model output before useful output -> `MODEL_UNAVAILABLE`.
- Model stream interruption after partial output -> SSE `error` event with recoverable retry guidance and no stored successful response.
- Guardrail-blocked model output after at least one public SSE `agent_message` chunk -> SSE `error` event with recoverable retry guidance and no stored successful idempotency response.
- Unexpected server failure -> `INTERNAL_ERROR` without raw provider details, prompt text, code submissions, or secrets.

### 5. Good/Base/Bad Cases

- Good: configured OpenAI-compatible provider streams deltas, the route accumulates safe content, stores the final response once, and replays the same `client_message_id` without calling the model again.
- Good: SDK tools summarize current stage, knowledge point, exercise metadata, and visible latest-attempt facts without exposing raw code submissions or hidden identifiers.
- Base: local development has no model key; the endpoint returns `MODEL_UNAVAILABLE` and all tests pass without live provider access via fake clients.
- Bad: adding a durable chat-history table for this MVP, exposing hidden test data in prompt/response, using WebSocket/global chatbot behavior for active learning composer messages, exposing SDK event names directly through the public API, or letting an SDK tool mutate `Attempt`, `ReviewState`, `ReviewLog`, `Note`, `LearningSession`, or `idempotency_records`.

### 6. Tests Required

- API-test JSON success and idempotent replay for a real active learning session.
- API-test SSE success with ordered `agent_message` chunks followed by terminal `done`.
- API-test missing session and validation errors in both JSON and SSE modes.
- API-test LLM-disabled or LLM-failure `MODEL_UNAVAILABLE` and assert provider raw details do not leak.
- API-test guardrail-blocked JSON model output and assert `MODEL_UNAVAILABLE` without leaked hidden IDs, key-like tokens, or complete-answer wording.
- API-test guardrail-blocked SSE output after a partial safe chunk and assert a recoverable `error` event with no stored successful idempotency response.
- API-test safe summary generation, persisted summary reuse below refresh threshold, direct-answer request redirection, and prompt context redaction for hidden IDs, internal reference fields, provider errors, API-key-like tokens, and complete-answer wording.
- Unit-test OpenAI-compatible streaming payload compatibility so unsupported `temperature` is omitted by default.
- Unit-test the SDK-backed client with a fake SDK runner; tests must assert no live model call is required, tracing is disabled, text deltas are extracted, base URLs are normalized, SDK tools are attached, and guardrails are attached.
- Unit-test SDK tool summary helpers and guardrail helpers directly; assert summaries omit hidden case IDs, `solution_reference`, full starter/submitted code, provider errors, and raw prompt content.
- Run the full backend pytest suite and `pnpm --dir .\aearn desktop:check` for cross-layer composer changes.

### 7. Wrong vs Correct

#### Wrong

```python
agent = Agent(name="Teaching", instructions=prompt, model=model)
return Runner.run_streamed(agent, input).stream_events()
```

This leaks SDK event shapes through the feature layer and can bypass `MODEL_UNAVAILABLE` handling, Aearn SSE framing, idempotency storage, and provider error redaction.

#### Correct

```python
chunks = AgentsSDKLearningConversationClient(settings).complete_text_stream(
    messages,
    temperature=None,
)
```

The feature owns safe prompt construction, model-error mapping, idempotency, and SSE framing while the SDK client remains behind the local `TextCompletionClient` boundary.

#### Wrong

```python
@function_tool
def update_attempt_score(attempt_id: str, score: int) -> dict[str, object]:
    return repository.update_score(attempt_id, score)
```

SDK tools in the learning conversation path must not mutate durable Aearn product state; retry safety and writes belong to services/repositories.

#### Correct

```python
tools = build_teaching_tools(messages)
agent = build_agent(..., tools=tools, input_guardrails=input_guardrails)
```

Tools are derived from the sanitized message evidence and return bounded read-only summaries; public JSON/SSE responses are still guarded by Aearn-side leak checks.

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

## Scenario: SDK Agent Ownership And Release Gates

### 1. Scope / Trigger

- Trigger: adding, changing, or releasing OpenAI Agents SDK-backed behavior for teaching messages, exercise coaching, note assist, review coaching, or onboarding plan drafts.
- Scope: `app/agents/*`, SDK-facing feature wrappers in `app/services/*`, API routes that expose JSON/SSE responses, and SDK release reports under `docs/qa/`.

### 2. Signatures

- SDK modules live under `app/agents/`.
- Feature services and repositories own public response normalization, `MODEL_UNAVAILABLE` mapping, idempotency, and durable writes.
- Release gate commands:
  - `uv --directory .\aearn\services\api run python -m pytest`
  - `uv --directory .\aearn\services\api run python -m mypy app`
  - `uv --directory .\aearn\services\api run ruff check app tests`
  - `uv --directory .\aearn\services\api lock --check`
  - `pnpm --dir .\aearn desktop:check`

### 3. Contracts

- SDK modules may build prompts, call SDK runners, attach tools or guardrails, validate candidate output, and return safe candidate text or structured data.
- SDK modules must not import database connection types or mutate `Attempt`, `ReviewState`, `ReviewLog`, `Note`, `LearningPlan`, `LearningSession`, or `idempotency_records`.
- Durable writes, retries, idempotency replay, transaction boundaries, and public response envelopes remain owned by Aearn services/repositories.
- SDK inputs must be safe summaries: bounded exercise metadata, visible test summaries, sanitized latest-attempt facts, bounded learner notes, and server-owned plan templates.
- SDK inputs and outputs must not expose hidden test ids, hidden test source, `solution_reference`, full submitted code, raw provider errors, SDK event names, API keys, raw prompts, or full private notes.
- `MODEL_UNAVAILABLE` is required when model config is disabled or incomplete, SDK execution fails, output validation fails, guardrails block input/output, or an SDK candidate claims unsupported runtime capabilities.
- Provider diagnostics are allowed only when they are secret-free and normalized; raw provider payloads, stack traces, prompts, submitted code, and API keys must never reach public JSON/SSE responses or logs.

### 4. Validation & Error Matrix

- Fake SDK success -> existing public JSON/SSE contract stays unchanged.
- SDK exception, invalid event stream, invalid JSON, missing required fields, unsupported enum, or empty output -> `MODEL_UNAVAILABLE`.
- Guardrail-blocked leakage -> `MODEL_UNAVAILABLE` or recoverable SSE error according to the owning route contract, without exposing block internals.
- Idempotency replay -> return the stored Aearn response and do not call the SDK again.
- Idempotency key reused with a different request hash -> existing `IDEMPOTENCY_CONFLICT` behavior.

### 5. Good/Base/Bad Cases

- Good: a configured SDK candidate improves coaching or draft wording while repositories still own `Attempt`, `ReviewState`, `ReviewLog`, `Note`, `LearningPlan`, and `idempotency_records` writes.
- Base: local development has no model key; every SDK-backed path returns `MODEL_UNAVAILABLE` and still passes model-key-free tests through fake clients.
- Bad: SDK code writes product rows, exposes SDK event names through SSE, logs raw prompts, returns provider error bodies, trusts model-provided knowledge point IDs, or promises Java/C++ execution for `compiled_sandbox_later`.

### 6. Tests Required

- Maintain model-key-free fake runner coverage for each SDK-backed path.
- Cover valid SDK output, SDK failure, invalid or malformed output, guardrail-blocked leakage, and `MODEL_UNAVAILABLE`.
- Keep route-level contract tests for learning JSON/SSE, exercise coach endpoints, note JSON/SSE draft updates, review start/rationale, onboarding plan generation, and dashboard/resume compatibility.
- Before release, create or update a cross-agent SDK matrix and record exact command results plus residual risks in `docs/qa/`.

## Scenario: Agent Architecture Tools, Memory, Retrieval, Handoffs, And Graph Skeleton

### 1. Scope / Trigger

- Trigger: adding or changing agent-owned tools, side-effect queues, real code execution, learner profile memory, teaching-material retrieval, SDK handoffs, or LangGraph graph skeletons.
- Scope: `app/agents/tools.py`, `app/agents/router.py`, `app/agents/sdk_runtime.py`, `app/agents/learning_graph.py`, `app/services/runtime_runner.py`, `app/services/sandbox*.py`, `app/services/learner_profile.py`, `app/services/teaching_chunks.py`, `app/core/config.py`, and `app/db/schema.sql`.

### 2. Signatures

- Tool context signature: `LearningToolContext(user_id, session_id, knowledge_point_id, exercise, latest_attempt, stage_state, run_code_fn, profile_summary)`.
- Side-effect signature: `AgentSideEffects(code_runs, stage_transitions, diagnosis_updates, profile_updates)`.
- Runtime feature flag: `REAL_EXECUTION_ENABLED`; when false, `runtime_runner` must preserve the deterministic path.
- Memory DB signature: `learner_profiles(user_id unique, weak_points jsonb, error_patterns jsonb, learning_preferences jsonb, pace_indicators jsonb, observations jsonb, session_count)`.
- Retrieval DB signature: `teaching_chunks(knowledge_point_id, chunk_type, title, content, source_url, search_vector, metadata_json)`.
- Handoff builder signature: `build_agent(..., handoffs=None)`.
- Graph entrypoint signature: `build_learning_graph()` returns a compiled/importable LangGraph graph using `AgentState`.

### 3. Contracts

- SDK tools may request product actions, but durable writes must be drained by Aearn services/repositories at transaction boundaries.
- Agent tools must return bounded JSON-compatible payloads and must not expose hidden tests, `solution_reference`, full submitted code, raw prompts, provider payloads, secrets, or cross-user data.
- Profile reads and writes are scoped by authenticated/current `user_id`; missing profile data is additive context absence, not a hard failure.
- Teaching-material search is scoped to current `knowledge_point_id`; no tool may search arbitrary users, plans, or unrelated knowledge points.
- Python execution sandbox must run out-of-process with timeout and restricted imports/builtins; never grant filesystem or network access.
- LangGraph skeletons must run behind `LANGGRAPH_ENABLED` until they replace the service orchestration path with equivalent API/SSE behavior.

### 4. Validation & Error Matrix

- Disabled `REAL_EXECUTION_ENABLED` -> use deterministic runtime fallback and keep existing response shape.
- Sandbox timeout or exception -> return bounded runtime error fields; do not leak stack traces or internal file paths.
- Missing learner profile -> return an empty/compact profile summary and continue the agent turn.
- Cross-user profile or chunk access attempt -> reject in service/repository review and cover with tests.
- Empty retrieval query or no FTS hits -> return bounded fallback chunks for the same knowledge point only.
- Handoff route has no match -> stay with the teaching/default agent, not a null agent.
- LangGraph compile failure or missing dependency -> fail tests before rollout; do not enable the feature flag.

### 5. Good/Base/Bad Cases

- Good: the agent calls `trigger_code_run`, Aearn records/drains the side effect, real execution returns visible test facts, and the public SSE/API envelope stays unchanged.
- Good: session 1 records a confirmed weak point, session 2 reads the learner profile summary for the same user only.
- Base: local dev has no model key; tool unit tests and graph tests still pass through fake clients and pure node functions.
- Bad: SDK tool writes `Attempt`, `LearningSession`, `ReviewState`, `learner_profiles`, or `teaching_chunks` directly, or returns raw sandbox/provider diagnostics to the frontend.

### 6. Tests Required

- Unit-test tool functions for side-effect accumulation without database writes.
- Unit-test sandbox success, runtime error, timeout, restricted imports, and disabled fallback behavior.
- Unit-test learner profile incremental merge, observation cap, confidence handling, and user scoping.
- Unit-test teaching chunk indexing/search, fallback search, and knowledge-point scoping.
- Unit-test handoff routing rules and `build_agent(..., handoffs=...)` plumbing.
- Unit-test LangGraph node transitions and graph compilation behind `LANGGRAPH_ENABLED`.
- Run backend `pytest`, `ruff check .`, `mypy app`, and `pnpm --dir .\aearn desktop:check` when the change touches cross-layer learning flow.

### 7. Wrong vs Correct

#### Wrong

```python
@function_tool
def update_learner_profile(user_id: str, observations: list[dict[str, object]]) -> dict[str, object]:
    merge_observations(connect(), user_id, observations)
    return {"ok": True}
```

This lets an SDK tool choose a user and write durable state outside Aearn's transaction/idempotency boundary.

#### Correct

```python
@function_tool
def update_learner_profile(observations: list[dict[str, object]], ctx: LearningToolContext) -> dict[str, object]:
    ctx.side_effects.profile_updates.extend(observations)
    return {"accepted": len(observations)}
```

The tool records intent against server-owned context; the feature service later drains the side effect for the authenticated user.

## Scenario: LangGraph Production Orchestration

### 1. Scope / Trigger

- Trigger: promoting a LangGraph skeleton into the production request path for learning, onboarding, review, or another main page flow.
- Scope: `app/agents/*_graph.py`, `app/agents/graph_runtime_contracts.py`, feature services under `app/services/`, route adapters under `app/routes/`, and route-level API/SSE tests.

### 2. Signatures

- Shared result signature: `GraphRunResult(next_stage, intents, diagnostics, safe_context)`.
- Shared intent signature: `GraphIntent(intent_type, target, payload)`.
- Human checkpoint signature: `GraphHumanCheckpoint(checkpoint_id, checkpoint_type, reason, prompt, scope, metadata)` built by `build_graph_human_checkpoint(...)`.
- Shared boundary contract signature: `graph_runtime_boundary_contract() -> GraphRuntimeBoundaryContract`.
- Boundary validation signature: `validate_run_result_for_boundary(result, allowed_intent_targets={...}) -> list[str]`.
- Checkpoint thread signature: `build_checkpoint_thread_state(session_id, user_id, session_type, checkpoint_ns, checkpoint_id=None, metadata=None) -> GraphCheckpointThreadState`.
- LangGraph invoke config shape: `{"configurable": {"thread_id": "aearn:<session_type>:<session_id>", "checkpoint_ns": "<graph_namespace>"}, "metadata": {...}}`.
- Graph stream event signature: `GraphStreamEvent(event_type="tool_status", payload={...})`.
- Learning entrypoint: `invoke_orchestration(...) -> {"next_stage", "tool_name", "tool_names", "learner_content", "next_state", "run_result"}`.
- Learning tool-loop adapter: `graph_result_to_run_result()` converts ordered `tool_names` into ordered `IntentType.TOOL_CALL` intents while keeping legacy `tool_name` fallback compatibility.
- Onboarding entrypoint: `invoke_onboarding_orchestration(...) -> {"next_action", "intent_type", "intent_payload"}`.
- Review entrypoint: `invoke_review_orchestration(...) -> {"next_action", "intent_type", "intent_payload"}`.
- Feature flag: `LANGGRAPH_ENABLED`; when false, the previous stable service path must remain available until the migration task explicitly removes it.

### 3. Contracts

- Graph modules own routing decisions, stage transitions, next-action selection, and intent production.
- Graph modules must return shared `GraphRunResult` or adapt raw graph output through a `*_result_to_run_result()` helper before service code consumes it.
- The shared boundary contract must document ownership for `graph`, `service`, `repository`, `api`, and `sse` layers in code, not only prose.
- Services must validate `GraphRunResult` against a service-scoped allowed intent-target map before applying intents. For the learning message path, allowed graph intents are `STAGE_UPDATE -> learning_session`, `TOOL_CALL -> show_code_exercise|show_concept_check_result|show_concept_intro|show_learning_history`, and `FEEDBACK_REQUEST -> human_checkpoint`.
- Human checkpoints are soft graph interrupts for learner approval, clarification, or teaching-safety boundaries. They must be bounded/redacted, converted to scoped `FEEDBACK_REQUEST` intents, and consumed or ignored by services without graph-owned durable writes.
- Graph thread ids must be service-derived and deterministic from durable Aearn session facts. The learning graph uses `checkpoint_ns=learning`; the single-step learning orchestration graph uses `checkpoint_ns=learning_orchestration`.
- LangGraph checkpoints are not product persistence. Checkpoint config may resume graph execution details, but durable learning state remains in Aearn services/repositories and idempotency records.
- Services and routes own durable writes, idempotency replay, transactions, public response envelopes, and SSE frame order.
- Graph runtime stream adapters must map graph progress only to existing SSE event types, currently `tool_status`, with bounded/redacted payloads and stable public node/tool names.
- Repository modules own SQL and persistence invariants; graph nodes must not open database connections or write product rows directly.
- Route handlers may pre-load service-owned facts for graph input, but they must consume graph intents rather than call the graph only for telemetry.
- Feature-flag fallback must be deterministic: disabled graph path or graph exception falls back to the last stable service logic without changing public response shape.
- Graph context, diagnostics, node names, checkpoints, and intent payloads must be bounded and redacted: no hidden tests, `solution_reference`, raw prompts, provider payloads, submitted code, stack traces, API keys, or secrets.
- Learning-page graphs may own ordered repeated tool-call decisions, but feature services must execute the tools, build public payloads, update `LearningSession`, load exercises, and persist idempotency records.

### 4. Validation & Error Matrix

- `LANGGRAPH_ENABLED=false` -> use the stable non-graph branch and keep existing status codes/SSE events.
- Graph compile or invoke exception -> catch at the service/route boundary, produce a safe fallback, and do not leak raw graph errors.
- Boundary validation error -> reject the graph output for that service scope and use the stable fallback or existing public error path; do not partially apply intents.
- Missing checkpointer or graph checkpoint storage -> continue with deterministic `configurable.thread_id`; do not create ad-hoc graph-owned database writes.
- Graph emits a persistence intent that does not match the route action -> reject or continue fallback; do not perform the write blindly.
- Graph emits route-generation/tool intent -> service builds/stashes the plan or tool args, then emits the existing public `tool_call` contract.
- Graph emits multiple learning tool intents -> service executes supported tools in graph intent order; unsupported targets are rejected by boundary validation before any partial application.
- Graph emits a human checkpoint -> service accepts only scoped `FEEDBACK_REQUEST -> human_checkpoint` intents; unknown checkpoint targets fall back before any stage/tool side effect is applied.
- Graph emits review not-due action -> route returns the same `REVIEW_NOT_DUE` envelope as repository validation.
- Graph-enabled learning message SSE -> may emit bounded `tool_status` frames before normal `agent_message` frames; flag-off and idempotency replay must not synthesize graph status frames.
- Idempotency replay -> return stored Aearn response and do not re-run graph side-effect decisions that could drift stored tool calls.

### 5. Good/Base/Bad Cases

- Good: onboarding confirm calls the graph, verifies a `confirm_plan` persistence intent, then the service confirms the stashed draft in the existing transaction.
- Good: review start/warmup/submit invoke the review graph from real route paths while repositories still own `ReviewState`, `ReviewLog`, and `Attempt` writes.
- Good: learning message graph output is validated with `validate_run_result_for_boundary()` before the service applies stage/tool intents.
- Good: learning graph invocations pass `configurable.thread_id=aearn:learning:<session_id>` and bounded metadata while `LearningSession` remains the service-owned durable state.
- Good: graph-owned early practice emits `show_concept_check_result` followed by `show_code_exercise`; the service builds both public tool payloads in that order and keeps all durable writes service/repository-owned.
- Base: local development keeps `LANGGRAPH_ENABLED=false`; all old-path route tests still pass with the same public contract.
- Bad: graph nodes write `LearningSession`, `Attempt`, `ReviewState`, or `LearningPlan` rows directly, routes call graphs but ignore their `GraphRunResult` intents, services execute unknown graph intent types without boundary validation, graph checkpointing becomes a second product-state store, or service code reorders graph-owned tool intents.

### 6. Tests Required

- Unit-test graph node routing and `*_result_to_run_result()` adapters for each migrated flow.
- Unit-test ordered graph tool-loop output so `tool_names` produces ordered `TOOL_CALL` intents.
- Unit-test `graph_runtime_boundary_contract()`, `GraphIntentBoundaryRule`, and `validate_run_result_for_boundary()` for layer ownership and scoped intent rejection.
- Unit-test `GraphCheckpointThreadState` for deterministic thread ids, session-type separation, bounded namespace/config serialization, and metadata redaction.
- Unit-test `GraphHumanCheckpoint` and graph adapters for checkpoint bounding, redaction, scoped `FEEDBACK_REQUEST` conversion, and invalid-target rejection.
- Unit-test graph stream adapters for existing SSE vocabulary, payload bounding, redaction, and disabled/empty graph context behavior.
- Route-level tests must set `LANGGRAPH_ENABLED=true`, monkeypatch the graph entrypoint, and assert the production path consumes graph intents.
- Route-level learning message SSE tests must assert graph `tool_status` ordering before `agent_message`, no raw graph diagnostics leakage, and flag-off compatibility.
- Route-level tests must cover ordered learning tool-call payloads, including graph-owned `show_concept_check_result` before `show_code_exercise`.
- Route-level tests must assert graph invocations receive the expected thread config when `LANGGRAPH_ENABLED=true`.
- Route-level tests must cover invalid/unscoped graph intents and assert the service does not blindly execute them.
- Route-level tests must keep flag-off fallback coverage for public response shape, idempotency replay, and SSE event ordering.
- Add regression tests for graph error/fallback behavior and redaction of sensitive graph payload fields.
- Run backend `pytest`, `ruff check .`, `mypy app`, and `pnpm --dir .\aearn desktop:check` before archiving a production graph migration.

### 7. Wrong vs Correct

#### Wrong

```python
result = invoke_review_orchestration(...)
submit_review_exercise_result(conn, ...)
```

This only observes the graph. The production route still ignores the graph's decision and can drift from the graph-owned orchestration contract.

#### Correct

```python
result = invoke_review_orchestration(...)
run_result = review_result_to_run_result(result)
errors = validate_run_result_for_boundary(run_result, allowed_intent_targets=REVIEW_ALLOWED_INTENTS)
if errors:
    return error_response(...)
if run_result.next_stage == "reject_not_due":
    return error_response(...)
submit_review_exercise_result(conn, ...)
```

The graph owns the route decision; the service validates the graph output against its allowed boundary, then executes or rejects through the existing Aearn service/repository and public response contracts.

## Scenario: Shared Agent Runtime Context Layer

### 1. Scope / Trigger

- Trigger: adding or changing shared context, summary, sanitization, JSON parsing, or runtime-context helpers used by multiple SDK-backed domains.
- Scope: `app/agents/agent_runtime_context.py`, `app/agents/agent_domain_contexts.py`, domain SDK clients under `app/agents/*_agent.py`, feature services that build prompt messages, and model-key-free LLM integration tests.

### 2. Signatures

- Shared safe-message conversion: `safe_messages_from_records(records) -> list[SafeMessage]`.
- Shared summary refresh decision: `should_refresh_summary(state, message_count, stage, threshold) -> ContextRefreshDecision`.
- Shared JSON extraction: `extract_json_object(text)` and `parse_fenced_json_object(content, invalid_message, object_message) -> dict[str, object]`.
- Shared bounded text helpers: `limit_text(value, max_length)`, `sanitize_summary_text(...)`, and `sanitize_summary_list(...)`.
- Runtime context block builder: `build_runtime_context_block(safe_summary, recent_safe_messages, current_diagnosis, response_policy)`.
- Domain runtime context builders: `build_onboarding_plan_runtime_context(...)` and `build_review_runtime_context(...)`.

### 3. Contracts

- Shared runtime-context helpers may transform domain facts into safe prompt context, produce bounded summaries, normalize JSON, and expose domain-specific `runtime_context` dictionaries.
- Shared runtime-context helpers must not import repository modules, open database connections, write `LearningPlan`, `LearningSession`, `LearningMessage`, `Attempt`, `ReviewState`, `ReviewLog`, `Note`, or `idempotency_records`.
- Domain services remain responsible for loading facts, persisting summaries, mapping model failures to public errors, idempotency replay, and public JSON/SSE framing.
- Domain adapters must keep domain-specific policy explicit. Learning, onboarding, and review contexts may share sanitization primitives, but must not collapse into one global summary schema.
- Runtime context must contain bounded and sanitized summaries only: no hidden test ids/source, `solution_reference`, full submitted code, full private notes, raw prompts, provider payloads, SDK event names, or API keys.
- Shared JSON helpers must raise `LLMInvalidResponseError` with domain-provided messages when output is invalid or not a JSON object.

### 4. Validation & Error Matrix

- Empty or fully redacted stored message -> skip it from recent safe messages.
- Hidden identifiers, provider errors, API-key-like tokens, or direct complete-answer text in context candidates -> redact before prompt construction or reject at the guardrail boundary.
- Missing or stale summary state -> refresh summary according to `message_count`, stage, and threshold.
- Invalid fenced JSON or non-object JSON from an SDK candidate -> `LLMInvalidResponseError`, then the owning service maps to `MODEL_UNAVAILABLE`.
- Shared helper accidentally starts owning durable writes or repository imports -> reject in review; move the write back to the feature service/repository.

### 5. Good/Base/Bad Cases

- Good: learning, onboarding, and review clients call shared sanitization/JSON/context helpers while their services still own persistence, idempotency, and public responses.
- Base: a domain has no durable summary storage yet; it can still build an ephemeral bounded `runtime_context` from safe current facts and recent messages.
- Bad: copying a learning-page summary schema into onboarding/review, injecting raw chat history into prompts, or letting the shared context layer mutate product rows.

### 6. Tests Required

- Unit-test shared helpers for bounded text, safe-message conversion, refresh decisions, JSON fence parsing, redaction, and confidence normalization.
- Unit-test domain runtime context builders for onboarding and review, including bounded fields and no hidden/reference/provider/API-key leakage.
- Keep fake SDK runner/client tests for learning, onboarding, and review paths; no live model credentials are required.
- Route-level tests must continue asserting unchanged public response shapes, SSE event ordering, idempotency replay, and `MODEL_UNAVAILABLE` behavior.

### 7. Wrong vs Correct

#### Wrong

```python
payload = {
    "history": [dict(row) for row in learning_messages],
    "summary": state_json,
}
```

This injects raw stored messages and state into the prompt, bypassing bounded sanitization and cross-domain leakage checks.

#### Correct

```python
safe_messages = safe_messages_from_records(rows)
runtime_context = build_runtime_context_block(
    safe_summary=safe_summary,
    recent_safe_messages=[message.as_dict() for message in safe_messages],
    current_diagnosis=current_diagnosis,
    response_policy=response_policy,
)
```

The feature service loads facts and owns persistence, while the shared layer only builds bounded safe context for SDK input.

## Scenario: Language Grounding Sources And Fetching

### 1. Scope / Trigger

- Trigger: adding or changing allowlisted documentation sources or documentation fetch behavior for language-aware grounding.
- Scope: `app/services/grounding_sources.py`, `app/services/grounding_fetcher.py`, `app/services/grounding_processing.py`, `app/services/grounding_retrieval.py`, `app/services/grounding_citations.py`, `app/services/grounding_fixtures.py`, `app/services/grounding_reindex.py`, `app/services/language_capabilities.py`, and grounding tests.

### 2. Signatures

- Source descriptor: `GroundingSource(source_id, language_id, display_name, provider, trust_tier, seed_policy, content_type, allowlisted_domains, seed_urls, topic_tags, notes)`.
- Helper signatures: `all_grounding_sources()`, `sources_for_language(language_id_or_alias)`, `get_grounding_source(source_id)`, `allowlisted_domains_for_source(source_id)`, `seed_urls_for_language(language_id_or_alias)`, and `validate_grounding_source_registry()`.
- Fetcher signatures: `GroundingDocsFetcher.fetch(source_id, url)`, `fetch_source_seed_documents(source_id)`, and `fetch_language_seed_documents(language_id_or_alias)`.
- Fetch result signature: `GroundingFetchResult(status='ok'|'blocked'|'failed', document?, error_code?, error_message?, cache_hit)`.
- Processing signature: `clean_and_chunk_document(document, max_chars=1200) -> tuple[GroundingChunk, ...]`.
- Chunk signature: `GroundingChunk(chunk_id, source_id, language_id, title, section_path, canonical_url, source_type, source_trust_tier, fetched_at, content_hash, text, topic_tags)`.
- Retrieval signature: `retrieve_grounding_chunks(chunks, GroundingRetrievalQuery(...)) -> tuple[GroundingRetrievalResult, ...]`.
- Retrieval query fields: `language_id_or_alias`, `query_text`, `topic_tags`, `preferred_trust_tiers`, optional `knowledge_point_id`, optional `knowledge_point_title`, and `top_k`.
- Agent citation signature: `grounding_results_for_agent(results, max_items=4, max_content_chars=800) -> tuple[AgentGroundingItem, ...]`.
- Agent grounding item fields: bounded content snippet, `GroundingCitation`, relevance score, and match reasons.
- Fixture signatures: `mainstream_grounding_fixture_documents(fetched_at=None)` and `fixture_documents_for_language(language_id_or_alias, fetched_at=None)`.
- Reindex signatures: `run_grounding_reindex(fetcher, source_ids=None) -> GroundingReindexReport` and `run_fixture_grounding_reindex() -> GroundingReindexReport`.
- Reindex report fields: status, total sources, total documents, total chunks, total failures, per-source reports, and chunks.

### 3. Contracts

- Use canonical ids from `LANGUAGE_CAPABILITIES`; do not introduce a parallel language taxonomy.
- Registry entries are static and side-effect free; importing the module must not fetch network content or expose runtime agent web search.
- Documentation grounding readiness is separate from runtime readiness: planned languages may have docs sources while still being unavailable for public selection or execution.
- C++ and SQL require explicit trust disclosure because they use trusted/de facto or vendor documentation rather than a single official beginner source.
- Seed URLs must stay under declared allowlisted domains and use `http` or `https`.
- Documentation fetchers must use the registry allowlist before HTTP and return typed blocked/failed results instead of raising for expected fetch failures.
- HTTP clients must be injectable for tests and future worker integration; tests must not call live documentation sites.
- Fetch cache is scoped to one fetcher/reindex run and must not become durable storage.
- Documentation cleaning must be deterministic and dependency-light; script/style/head/nav/footer/aside content must not enter chunks.
- Chunks must carry enough metadata for later retrieval and citation without rereading the source registry.
- Chunk ids and content hashes must be stable for the same source URL, section path, chunk index, and text.
- Retrieval must canonicalize language aliases through `LANGUAGE_CAPABILITIES` and filter by language before ranking.
- Retrieval ranking must remain deterministic and return bounded same-language fallback chunks for empty/no-hit queries.
- Retrieval results must retain chunk metadata plus match reasons so downstream agent citation formatting can stay transparent.
- Agent-facing grounding adapters must bound snippets and carry source metadata explicitly; do not rely on the model to infer citations from prose.
- Citation ids must be deterministic for the same canonical URL, section path, and content hash.
- Mainstream language fixtures must be offline, deterministic, and built from registered source ids and seed URLs.
- Fixtures must cover every `LANGUAGE_CAPABILITIES` id without implying runtime execution or public selection.
- Reindex service code must isolate per-source failures and return structured status instead of raising for expected source/fetch failures.
- Reindex observability may expose service-level reports, but must not add route, worker schedule, or startup hook until an explicit task owns that rollout.

### 4. Validation & Error Matrix

- Unknown language id in a source -> registry validation error.
- Duplicate `source_id` -> registry validation error.
- Missing seed URLs or domains -> registry validation error.
- Seed URL outside declared allowlist -> registry validation error.
- No source matching a language's `source_trust_policy` -> registry validation error.
- URL outside a source allowlist -> `GroundingFetchResult(status='blocked', error_code='URL_NOT_ALLOWLISTED')` before any HTTP call.
- Non-2xx HTTP response -> `GroundingFetchResult(status='failed', error_code='HTTP_STATUS')`.
- HTTP client exception -> `GroundingFetchResult(status='failed', error_code='FETCH_FAILED')` with bounded safe message.
- Unknown source for a fetched document -> no chunks.
- Empty or unreadable document body -> empty chunk tuple, not an exception.
- Unknown retrieval language -> empty result tuple.
- Empty/no-hit retrieval query -> same-language fallback results with `match_reasons=('fallback',)`.
- Empty citation input -> empty agent grounding tuple.
- Non-positive `max_items` or `max_content_chars` -> empty agent grounding tuple.
- Unknown fixture language -> empty fixture tuple.
- Unknown reindex source id -> per-source `failed` report with `SOURCE_NOT_REGISTERED`.
- Mixed reindex success and failures -> top-level `completed_with_failures` with successful chunks preserved.
- No successful documents or chunks -> top-level `failed`.

### 5. Good/Base/Bad Cases

- Good: TypeScript has official docs grounding but remains `enabled_for_public_selection=False` and `supports_execution=False`.
- Good: fetching a registered Python seed URL through an injected fake client returns a document with canonical URL, final URL, fetched timestamp, content type, and content hash.
- Good: cleaning fetched HTML returns section-aware chunks with canonical URL, trust tier, source type, fetched timestamp, topic tags, and stable hashes.
- Good: a Python retrieval query never returns JavaScript chunks, even when the text matches.
- Good: agent grounding context includes a bounded snippet plus citation id, URL, section path, trust tier, content hash, score, and match reasons.
- Good: every mainstream language fixture can chunk, retrieve, and convert to an agent citation without network access.
- Good: a reindex run with one failed source and one successful source returns `completed_with_failures` and keeps the successful chunks.
- Base: C++ uses `cppreference` with `trusted_de_facto` and a rationale note.
- Bad: adding a docs URL changes public course language ids, runtime runner status, or lets agents browse arbitrary domains.
- Bad: raw `<script>`, navigation, or footer text appears in grounded teaching context.
- Bad: retrieval ranks before language filtering and leaks another language's same-topic chunk.
- Bad: prompt code pastes a whole fetched page and asks the model to invent or summarize its own citations.
- Bad: source fetch failure raises out of reindex and blocks normal learning/session startup.

### 6. Tests Required

- Assert every `LANGUAGE_CAPABILITIES` id has at least one grounding source.
- Assert source ids are unique and registry validation returns no errors.
- Assert alias lookup works through `sources_for_language()`.
- Assert seed URLs remain under allowlisted domains.
- Assert planned languages gain docs without runtime/public-selection side effects.
- Assert fetcher success, blocked URL, HTTP status failure, client exception, cache hit, and language-level seed fetching through fake clients.
- Assert HTML cleaning, metadata propagation, deterministic chunk ids/hashes, empty-content behavior, and bounded chunk splitting.
- Assert retrieval language filtering, query/topic ranking, trust-tier preference, unknown language behavior, and same-language fallback behavior.
- Assert agent citation metadata, deterministic citation ids, bounded snippets, score/reason preservation, max item limits, and empty input behavior.
- Assert fixture coverage for every mainstream language id and smoke the offline chunk/retrieve/citation pipeline.
- Assert successful reindex, mixed failure reindex, unknown source handling, and fixture reindex smoke status/counts.

### 7. Wrong vs Correct

#### Wrong

```python
GROUNDING_SOURCES = {"typescript": ["https://example.com/typescript"]}
LANGUAGE_CAPABILITIES["typescript"].enabled_for_public_selection = True
```

This mixes documentation readiness with product/runtime availability.

#### Correct

```python
sources = sources_for_language("typescript")
assert sources
assert require_language_capability("typescript").supports_execution is False
```

Grounding can be prepared before the runtime runner or public course contract exists.
