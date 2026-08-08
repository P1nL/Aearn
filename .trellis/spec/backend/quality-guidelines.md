# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Backend work targets the active **Tutor Harness** runtime under
`aearn/services/api/app`. Current behavior is defined by
`docs/architecture/tutor-harness-runtime.md`, `api-contract.md`,
`database-schema.md`, `setup/development-environment.md`, and the current
route/schema/tests—not by the retired Graph/SDK implementation.

> **Historical-scenario note (2026-07-29):** The older Milestone/Graph/SDK
> scenarios below are retained as implementation history. They may use
> historical present tense, `LANGGRAPH_ENABLED`, old routes, FSRS/Attempt, or
> legacy data models. Do not implement or restore those paths unless a future
> task explicitly reopens them. Active work must preserve the verified-only
> Tutor entry, current API composition, and dated archive boundary.

The API dependency source is `aearn/services/api/pyproject.toml`; it contains
FastAPI, psycopg, Redis, Celery, Pydantic, dotenv and local worker/shared
packages. It intentionally has no LangChain, LangGraph, LangGraph checkpoint,
or OpenAI Agents SDK direct runtime dependency.

---

## Forbidden Patterns

- Do not write current backend code in historical tutorial directories or
  reintroduce `app.agents.graphs`, Graph/router/tool/legacy conversation
  surfaces, `LANGGRAPH_ENABLED`, or Agents SDK imports into active code.
- Do not use a feature flag, client cache, ordinary reset, or a docs claim as a
  substitute for the server-authoritative `harness_cutovers` receipt.
- Do not expose raw learner text outside `tutor_messages`, or provider payloads,
  prompts/reasoning, hidden tests, reference answers, checkpoint data, paths,
  commands or secrets through public projections.
- Do not make proactive work learner-visible chat/desktop notification or allow
  it to execute learner code, `runner.execute`, subprocesses, or direct memory
  effects.
- Do not duplicate/replay Tutor input/effect/plan/memory/activity writes without
  repository idempotency, current revision and lease/CAS checks.
- Do not commit real `.env` files or LLM secrets.

---

## Required Patterns

- Run backend commands from `aearn/services/api` through
  `uv --directory .\aearn\services\api ...`.
- Check public changes against `docs/architecture/api-contract.md`, persistence
  against `docs/architecture/database-schema.md`, and runtime/scheduler/cutover
  changes against `docs/architecture/tutor-harness-runtime.md`.
- Require exact reviewed `Skill id@semantic-version` evidence before a
  capability/effect; default-deny all descriptor fields/targets not explicitly
  allowed.
- Keep the production scheduler scan global (`user_id=None`); test/maintenance
  user scope must be explicit and propagate through every changed queue phase.
- Treat the initial proactive posture as controlled default delivery:
  verified receipt + policy/pause/budget/cooldown/concurrency/lease/circuit gates
  still apply, while curation/inferred memory remain default-off.
- Preserve clean-slate semantics: target-state contamination and unresolved
  checkpoint scope block before deletion; code rollback after confirmation never
  restores deleted history.

---

## Testing Requirements

- Run `ruff check .`, `python -m mypy app`, `lock --check`, and the serial
  `python -m pytest` suite from the API directory for cross-layer changes.
- API tests must assert public status/envelope/error/idempotency and absence of
  protected fields, not just internal helper return values.
- PostgreSQL/bootstrap-sensitive tests must run sequentially. A fixture that
  commits for independent-connection coverage must clean exact child rows,
  verified receipts and test singleton state in foreign-key order.
- Default proactive coverage must prove verified activity/inbox delivery and
  unverified no-provider/no-run denial with deterministic seams.
- After retirement, run the scoped source/dependency audit; historical docs are
  permitted only when visibly labelled and not indexed as active runtime.

---

## Code Review Checklist

- The change runs from the correct subproject directory and does not rely on a
  repository-root Python environment.
- Routing, worker composition and public projections consult the same current
  `verified` cutover receipt; no legacy fallback route survives.
- Durable writes use user/run/conversation scope, idempotency and repository
  transactions; stale effects cannot invoke handlers.
- Provider/executor/runtime imports remain at their designated boundaries.
- Any fixture commit has a tested scoped cleanup path and does not leak rows to
  the following test.

---

## Scenario: Local User Data Boundary APIs

### 1. Scope / Trigger

- Trigger: adding or changing local-only profile switching, user data summary/export/reset/delete, or user-scoped plan/note/session/review mutation behavior.
- Scope: `routes/users.py`, `routes/plans.py`, `routes/notes.py`, `routes/learning_sessions.py`, `routes/reviews.py`, `local_user_data_repository.py`, owned-data repositories, `idempotency_records`, and user-boundary tests.

### 2. Signatures

- API: `GET /api/users`
- API: `GET /api/users/{user_id}/data-summary`
- API: `GET /api/users/{user_id}/export`
- API: `POST /api/users/{user_id}/reset-data` with `{ "confirm": true }`
- API: `DELETE /api/users/{user_id}` with `{ "confirm": true }`
- User-scoped read: `GET /api/plans/{plan_id}?user_id=...`
- User-scoped mutations: learning message/run/hint/explain/check/submit and review warmup/exercise-result/message payloads include optional compatibility `user_id`.
- DB: `idempotency_records(user_id uuid, invalidated_at timestamptz)` for user-owned write replay boundaries.

### 3. Contracts

- This is a local product isolation boundary, not public auth, RBAC, or a hostile-local-attacker model.
- When a request supplies `user_id`, every plan, note, learning session, review session, attempt, and idempotency replay must match that user before reading or mutating data.
- Cross-user mismatches return the same not-found family used for missing objects: `PLAN_NOT_FOUND`, `NOTE_NOT_FOUND`, `SESSION_NOT_FOUND`, or `USER_NOT_FOUND`.
- New user-owned idempotency records must store `user_id`; replay lookups with explicit `user_id` must filter by `idempotency_records.user_id` and `invalidated_at IS NULL`.
- Export is learner-safe: include visible learner data and summaries only; omit hidden test bodies/expected values, solution references, raw prompts, provider payloads, API keys, runner temp paths, and internal secrets.
- Reset preserves the user row and preferences, deletes owned learning data, invalidates/deletes user-owned idempotency records, and returns a zeroed post-reset summary.
- Delete removes or soft-deletes the user after clearing owned data and must make normal product APIs treat the user as not found.

### 4. Validation & Error Matrix

- Unknown or deleted user -> `USER_NOT_FOUND`.
- Plan id belongs to another user when `user_id` is supplied -> `PLAN_NOT_FOUND`.
- Note id belongs to another user -> `NOTE_NOT_FOUND`.
- Learning or review session belongs to another user -> `SESSION_NOT_FOUND`, including SSE message endpoints.
- Destructive request missing `{ "confirm": true }` -> `VALIDATION_ERROR` with `recoverable=false`.
- Same idempotency key with different request body -> `IDEMPOTENCY_CONFLICT`.
- Reset/delete followed by old confirm-plan or session idempotency replay -> no stale replay; return a fresh result or the correct not-found error.

### 5. Good/Base/Bad Cases

- Good: two local users can hold separate plans, notes, sessions, reviews, and settings; switching `user_id` cannot read or mutate the other user's rows.
- Good: reset keeps `users.profession` and preferences but clears plans, sessions, attempts, review state/logs/seed banks, notes, conversations, and user-owned idempotency records.
- Base: legacy internal tests may omit `user_id` for compatibility, but desktop-facing calls must pass the active user.
- Bad: loading an idempotency record by key only before checking the session owner lets a wrong user replay another user's prior response.
- Bad: exporting `test_cases`, `solution_reference`, raw graph/provider payloads, or hidden expected values directly.

### 6. Tests Required

- Assert `GET /api/users` lists only non-deleted users with switchable summary fields.
- Assert data summary counts plans, sessions, attempts, review states/logs/seed banks, notes, and conversations for the target user only.
- Assert export contains learner-visible notes/attempt summaries and excludes hidden tests, solution references, raw prompts, provider payloads, and secrets.
- Assert cross-user plan detail, note update, learning message/run, review warmup/exercise-result/message return stable not-found errors.
- Assert reset preserves user preferences, clears owned learning data, clears stale plan visibility, and prevents stale idempotency replay.
- Assert delete hides the user from read/list APIs, hides old owned data, and prevents stale idempotency replay.
- Run M3/M4 DB tests sequentially with other bootstrap-heavy batches; parallel runs can deadlock on schema bootstrap.

### 7. Wrong vs Correct

#### Wrong

```python
stored = conn.execute(
    "SELECT request_hash, response_json FROM idempotency_records WHERE key = %s",
    (key,),
).fetchone()
session = _load_session(conn, session_id)
```

This can replay another local user's response before the session owner is checked.

#### Correct

```python
session = _load_session(conn, session_id, user_id=payload.user_id)
stored = _load_idempotency_record(conn, key, user_id=payload.user_id)
```

The object owner and idempotency owner are both checked before replay or mutation.

## Scenario: Local Dev Startup Lifecycle

### 1. Scope / Trigger

- Trigger: changing the repo-local Aearn startup/status/restart/stop workflow, especially `aearn/scripts/start-dev.ps1`, `aearn/package.json` `dev*` scripts, or `docs/setup/development-environment.md`.
- Scope: local development lifecycle for Docker PostgreSQL/Redis, schema bootstrap, FastAPI, Celery worker, Tauri desktop dev server, and `aearn/.logs/dev-processes.json`.

### 2. Signatures

- `pnpm --dir .\aearn dev`
- `pnpm --dir .\aearn dev:status`
- `pnpm --dir .\aearn dev:restart`
- `pnpm --dir .\aearn dev:stop`
- API readiness endpoint: `GET http://127.0.0.1:8001/health`
- Desktop readiness URL: `http://127.0.0.1:1420`
- Tracked state file: `aearn/.logs/dev-processes.json`

### 3. Contracts

- Startup order remains Docker PostgreSQL/Redis -> schema bootstrap -> API -> Celery worker -> Tauri desktop dev server.
- Backend processes must use `python -m uvicorn` and `python -m celery` through `uv --directory .\aearn\services\api`; do not call bare `uvicorn` or `celery` executables on Windows.
- `dev:status` must report Docker service state, API readiness, desktop readiness, and tracked process state.
- Tracked process state must distinguish `alive`, `stale`, and `untrusted`.
- `dev:stop` and `dev:restart` may stop only tracked Aearn processes whose command line matches the expected startup command.
- Stale or untrusted tracked PIDs must be skipped and then cleared from the state file; never kill a process only because its PID appears in old state.
- Runtime logs and `dev-processes.json` live under `aearn/.logs/` and must not be committed.

### 4. Validation & Error Matrix

- Missing `uv`, `pnpm`, or `docker` -> fail with the missing command name.
- Docker compose failure -> `docker compose startup failed`.
- Database bootstrap failure -> `database bootstrap failed`.
- API readiness timeout -> component-specific API readiness failure.
- Worker readiness timeout -> component-specific worker log readiness failure.
- Desktop readiness timeout -> component-specific desktop readiness failure.
- Tracked PID missing -> `stale`, skip stop.
- Tracked PID exists but command line mismatch -> `untrusted`, skip stop.

### 5. Good/Base/Bad Cases

- Good: old `dev-processes.json` contains stale PIDs; `dev:status` reports them as `stale`, and `dev:stop` skips them without killing unrelated processes.
- Good: `dev` starts API, worker, and desktop, then `dev:status` reports tracked PIDs as `alive, command verified`.
- Base: Docker dependencies are healthy but API/desktop are stopped; `dev:status` reports Docker healthy, API not ready, desktop not ready, and no tracked PIDs.
- Bad: `dev:stop` calls `Stop-Process` on a PID from old state without checking the command line.
- Bad: status prints raw JSON only, forcing users to infer whether a tracked PID is live or stale.

### 6. Tests Required

- Run `pnpm --dir .\aearn dev:status`.
- Run `pnpm --dir .\aearn dev`, then confirm `dev:status` shows API and desktop ready with verified tracked PIDs.
- Run `pnpm --dir .\aearn dev:restart`, then confirm the same readiness and tracked PID behavior.
- Run `pnpm --dir .\aearn dev:stop`, then confirm API and desktop are not ready and tracked PIDs are `none`.
- Run focused backend smoke tests: `uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_db_bootstrap.py tests/test_worker_import.py -q`.
- Run `pnpm --dir .\aearn desktop:check`.

### 7. Wrong vs Correct

#### Wrong

```powershell
Stop-Process -Id $state.apiPid -Force
```

This trusts stale state and can kill an unrelated process if Windows has reused the PID.

#### Correct

```powershell
$tracked = Get-TrackedProcessStatus -Key "apiPid" -ProcessId $state.apiPid
if ($tracked.status -eq "alive") {
  Stop-ProcessTree -ProcessId $state.apiPid
}
```

Stop only script-managed Aearn processes whose current command line still matches the expected startup command.

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
- Public drafts for JS/HTML/CSS/Python/TypeScript/SQL/Java/Go/C# must expose the matching teaching-grade runtime tier; C++ and Rust are not public route languages.
- Onboarding slot normalization must map supported aliases before emitting unsupported-language errors: `MySQL`, `PostgreSQL`/`Postgres`, `SQLite`, `SQL Server`/`MSSQL`, and `MariaDB` are SQL dialect/product aliases and must persist as `language="sql"`, not `unsupported_language`.
- JS/HTML/CSS/Python draft templates must be multi-module routes organized by official learning taxonomies, then adapted to Aearn's executable verification loop:
  - Python follows Python Tutorial-style categories such as basics/value flow, control flow/functions, data structures, modules/I/O, errors/tests, and classes/code review.
  - JavaScript follows MDN JavaScript Guide-style categories such as language basics, control flow/functions, objects/state, DOM events, async/modules, and generated-code verification.
  - HTML/CSS follows MDN learning module-style categories such as HTML structure, forms/accessibility, selectors/cascade/box model, text styling, layout, and responsive review.
- Confirmed plans normalize `target_level=beginner_to_intermediate` to the DB-supported `beginner` value.
- Confirm plan default idempotency key is `confirm-plan:{user_id}:{plan_draft.draft_id}` unless `Idempotency-Key` is provided.
- Onboarding conversation route-ready turns must emit a short `agent_message` plus a persisted `show_learning_route` tool call, not a long plain-text route body.
- Onboarding message idempotency replay must re-emit stored `metadata.tool_calls` so desktop resume/retry rehydrates the same route card.
- Time-budget-only onboarding revisions must update the route tool args and draft identity; missing time budget must not block initial route-card generation.
- Dynamic route generation for public onboarding languages must use the shared dynamic plan service; `COURSE_TEMPLATES` must not be used as a hidden fallback after route-ready onboarding or `/api/plans/generate` dynamic failure.
- Dynamic generation must first establish user, course, runtime boundary, draft identity, and authoritative docs coverage, then merge only validated `agent_generated` modules into the `PlanDraft`.
- `PLAN_GENERATION_ENABLED=false`, missing OpenAI-compatible model configuration, missing dynamic client, missing `EXA_API_KEY`, missing authoritative docs mapping, invalid dynamic output, guardrail rejection, or provider failure must surface as `PLAN_GENERATION_UNAVAILABLE` or `PLAN_DRAFT_INVALID` without exposing raw provider/tool errors.
- `EXA_API_KEY` is required by the dynamic-generation gate and real keys must stay in local `.env`, never in docs, tests, logs, or fixtures.
- DeepSeek / Chat Completions route generation must not use the OpenAI Agents SDK tool-call flow. Prefetch authoritative doc TOCs in backend code, inject them as ordinary `authoritative_doc_tocs` prompt evidence, and call the OpenAI-compatible JSON client with normal `system`/`user` messages and `temperature=None` unless provider support for sampling parameters is explicitly tested.
- Adding a new public language such as C++ or Rust requires updating the Pydantic `Language` literal, database CHECK constraints, catalog seed, runtime boundary, API examples, and acceptance tests. Adding an `AUTHORITATIVE_DOCS` URL alone is not sufficient.

### 4. Validation & Error Matrix

- Unknown user -> `USER_NOT_FOUND` with 404.
- Unknown course -> `COURSE_NOT_FOUND` with 404.
- Missing goal/material input -> `VALIDATION_ERROR` with 400.
- Invalid `plan_draft` shape, user mismatch, no modules, or no non-skippable core module -> `PLAN_DRAFT_INVALID` with 422.
- Invalid dynamic modules -> `PLAN_DRAFT_INVALID` with 422; dynamic unavailability or missing generation config -> `PLAN_GENERATION_UNAVAILABLE` with 503/no-route SSE.
- SQL dialect aliases such as `MySQL` returned by the extractor as `unsupported_language` -> normalize to `language="sql"` and continue route generation; do not emit `LANGUAGE_NOT_SUPPORTED`.
- Unsupported or unregistered language -> `COURSE_NOT_FOUND` / validation failure; do not synthesize a confirmable plan from web search alone.
- Same idempotency key with a different request hash -> `IDEMPOTENCY_CONFLICT` with 409.
- FastAPI/Pydantic validation errors must be normalized to the documented error envelope.

### 5. Good/Base/Bad Cases

- Good: generate draft, confirm once, replay same request, and receive the existing plan without duplicate modules or review states.
- Good: route-ready onboarding with valid dynamic output emits `show_learning_route`, stashes the same dynamic draft, and includes authoritative `source_attribution`.
- Good: DeepSeek route generation receives only normal chat messages plus backend-prefetched doc TOCs, so no assistant `tool_calls` message needs a matching tool response.
- Base: Java/Go/C# courses are visible with `managed_compiled_test` teaching-grade boundaries, TypeScript is visible with `node_typescript_test`, SQL is visible with `sql_query_test`, and C++/Rust are absent from public course selection.
- Bad: a settings request modifies `fsrs_parameters`, a plan draft creates `Attempt` rows, or `POST /api/plans/generate` writes formal plan rows.
- Bad: dynamic generation failure silently produces template modules, or DeepSeek receives an Agents SDK tool-call conversation and returns `invalid_request_error`.

### 6. Tests Required

- Assert user create/get/preference update success.
- Assert forbidden preference fields return `VALIDATION_ERROR`.
- Assert catalog includes TypeScript `node_typescript_test`, SQL `sql_query_test`, Java/Go/C# `managed_compiled_test`, and no active C++/Rust course entries.
- Assert goal and material generation success, insufficient input, unknown user, and unknown course.
- Assert supported public route languages have `AUTHORITATIVE_DOCS` coverage.
- Assert `PLAN_GENERATION_ENABLED=false`, missing model config, missing `EXA_API_KEY`, invalid dynamic output, and provider failures return no-fallback dynamic errors without stashing a route card.
- Assert fake dynamic plan success swaps modules to `agent_generated` while preserving `PlanDraft` identity, runtime boundary, and source attribution.
- Assert malformed dynamic output, unsafe output, missing authoritative source coverage, and thrown provider errors do not leak provider/tool details.
- Assert DeepSeek-compatible dynamic generation prefetches authoritative doc TOCs and calls the direct JSON client with only normal `system`/`user` messages.
- Tests that indirectly call `/api/plans/generate` through `_confirmed_plan()` must monkeypatch dynamic and onboarding plan clients to fake/offline responses; local `.env` may contain real `OPENAI_*` and `EXA_API_KEY`, but routine DB test batches must never call live providers.
- Assert unregistered languages cannot become confirmable plans until language enum, DB constraints, catalog, runtime boundary, API docs, and acceptance tests are updated together.
- Assert confirm plan creates plan/module/knowledge point rows and one `review_states` row per knowledge point.
- Assert idempotent replay returns the original plan and conflicting request body returns `IDEMPOTENCY_CONFLICT`.
- Assert route-ready onboarding SSE stores and replays `show_learning_route` metadata, including time-budget-only revisions.
- Assert route-ready onboarding maps `MySQL`/database product aliases to the SQL route and still returns `LANGUAGE_NOT_SUPPORTED` for truly unsupported languages such as C++ and Rust.

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

#### Wrong

```python
agent = build_agent(tools=build_web_tools(settings), model=settings.llm_model)
streamed = Runner.run_streamed(agent, input_text, run_config=deepseek_run_config)
```

DeepSeek Chat Completions can reject an Agents SDK tool-call transcript when an assistant `tool_calls` message is not followed by matching tool messages.

#### Correct

```python
doc_tocs = prefetch_authoritative_doc_tocs(context.doc_urls)
messages = build_plan_messages(context, authoritative_doc_tocs=doc_tocs)
result = OpenAICompatibleClient(settings).complete_json(messages, temperature=None)
```

Route generation keeps documentation grounding in backend code and sends the model a normal JSON request, so provider incompatibility surfaces as a stable dynamic-generation error rather than a broken route card.

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
- `POST /api/reviews/{session_id}/exercise-result` with `exercise_id`, optional `attempt_id`, `code`, `filled_blanks`, `submit_version`, optional `explanation_check`, hint/error counts, optional `code_hash`, or `review_ai_patch_answer` writes or replays one `Attempt(review_submit)` and returns the next `current_node`.
- Learning scheduler signature: `apply_attempt_review_update(conn, knowledge_point_id, attempt_id, source, request_id)` updates `ReviewState` from persisted learning `Attempt(submit)`.
- Review batch scheduler signature: `apply_review_batch_update(conn, knowledge_point_id, representative_attempt_id, final_rating, aggregate_result, source, request_id)` updates `ReviewState` once from the finalized review batch.
- Worker task signature: `review.refresh_due_counts` reads due `review_states` and returns `{"total_due": int, "counts_by_user": {user_id: count}}`.

### 3. Contracts

- `Attempt(run)` must never update `ReviewState` or write `ReviewLog`.
- Learning submit calls the attempt scheduler; review intermediate submits must not call a scheduler; review finalization calls the batch scheduler.
- Scheduler idempotency key defaults to `review:update:{knowledge_point_id}:{attempt_id}:{rating}` for attempt scheduling and `review:batch:{session_id}:{representative_attempt_id}:{final_rating}` or caller-provided request id for review batch finalization.
- Replay by request id or `(attempt_id, rating, source)` returns the existing next state and must not increment counters twice.
- `review_states` storage still uses legacy `reps` / `lapses`, but API payloads must expose `review_count` / `lapse_count` while preserving `reps` / `lapses` compatibility.
- `review_logs.request_id` and `(attempt_id, rating, source)` must be unique to prevent double counter increments.
- Worker due-count queries are read-only; they must not update `ReviewState`, create `ReviewLog`, or prepare variants.

### 4. Validation & Error Matrix

- Unknown user in due list or start -> `USER_NOT_FOUND` with 404.
- Unknown knowledge point for review start -> `KNOWLEDGE_POINT_NOT_FOUND` with 404.
- No due state, future `due_at`, suspended state, or inactive plan -> `REVIEW_NOT_DUE` with 409.
- Review session/exercise mismatch -> `SESSION_CONFLICT` with 409.
- Baseline candidate pool cannot cover remaining review weakness and batch cannot finalize -> `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED` with recoverable 409.
- Missing review session, exercise, or run attempt -> documented 404 error code.
- Same review result idempotency key with different payload -> `IDEMPOTENCY_CONFLICT` with 409.
- Invalid scheduling attempt type, rating, user mismatch, or unevaluated attempt -> `ReviewSchedulingError` and no `ReviewState` mutation.

### 5. Good/Base/Bad Cases

- Good: complete a learning submit, force due, start review, submit intermediate review exercises and see only `Attempt(review_submit)` plus session-local batch state; final submit writes one `ReviewLog(source='review_submit')`, increments `review_count`, and returns backend `due_at` / `forget_risk`.
- Base: call due-count worker with existing due rows and verify the returned counts while the row snapshot and log count stay unchanged.
- Bad: computing `due_at` from the request body, updating `review_states` from `Attempt(run)` or intermediate review submit, or inserting a second `ReviewLog` on final retry.

### 6. Tests Required

- Assert `GET /api/reviews/today` returns empty state and due items sorted by `due_at`.
- Assert `POST /api/reviews/start` rejects early items and reuses the active due review session.
- Assert intermediate review exercise results write `Attempt(review_submit)` and do not update `ReviewState`, `ReviewLog`, `KnowledgePoint`, or long-term learner profile.
- Assert final review exercise result updates `ReviewState` and `ReviewLog` exactly once.
- Assert replaying the same intermediate or final review result returns `idempotency_replayed=true` without duplicating attempts, exercises, logs, or `reps`.
- Assert `Attempt(run)` leaves review state unchanged.
- Assert `review.refresh_due_counts` is registered, uses `Asia/Shanghai`, and is read-only.

### 7. Wrong vs Correct

#### Wrong

```python
if attempt_type in {"run", "review_submit"}:
    update_review_state(...)
```

This makes exploratory runs and intermediate review questions change the spaced-repetition schedule.

#### Correct

```python
if source == "learn_submit":
    apply_attempt_review_update(
        conn,
        knowledge_point_id=knowledge_point_id,
        attempt_id=submit_attempt_id,
        source=source,
        request_id=request_id,
    )
elif source == "review_submit" and batch_can_finalize:
    apply_review_batch_update(
        conn,
        knowledge_point_id=knowledge_point_id,
        representative_attempt_id=submit_attempt_id,
        final_rating=final_rating,
        aggregate_result=aggregate_result,
        source=source,
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

## Scenario: Learning Documentation Reading Flow

### 1. Scope / Trigger

- Trigger: implementing or changing the pre-concept-check documentation reading stage, knowledge-point documentation endpoint, concept-check trigger endpoint, or plan-detail review preview fields.
- Scope: `routes/learning_sessions.py`, `models/learning_sessions.py`, `learning_session_repository.py`, `plan_repository.py`, `learning_concept_agent.py`, learning graph/router/tool transitions, `schema.sql`, and M2/M3/M4 API tests.

### 2. Signatures

- API: `GET /api/learning-sessions/knowledge-points/{knowledge_point_id}/documentation?user_id=...`.
- API: `POST /api/learning-sessions/{session_id}/trigger-concept-check` with `{ "user_id": string }`.
- API extension: `GET /api/plans/{plan_id}` knowledge points may include `review_state: { due_at, is_due, label }`.
- DB: `learning_sessions.learning_stage` includes `documentation_reading` when new sessions start in document-reading mode.
- Cache: Redis documentation cache keys must include both `user_id` and `knowledge_point_id`, with a 24 hour TTL.

### 3. Contracts

- Starting a new learning session in `documentation_reading` must not persist or return an initial `show_concept_intro` tool call.
- Documentation payloads are structured JSON with stable section ids, titles, markdown content, code blocks, references, `generated_at`, and `cache_hit`.
- Documentation generation may use persisted outline/source/chunk data and may best-effort cache the result, but Redis unavailability must not block the learning flow.
- `trigger-concept-check` must validate session ownership, accept first trigger from `documentation_reading` or `concept_qna`, and move the session to `concept_check`.
- Trigger replay is idempotent only when the session is already in `concept_check` with an active concept intro; later stages must return `SESSION_CONFLICT` instead of resetting progress.
- Concept intro generation may include recent learner questions from the same session, bounded and sanitized, as `learner_questions`.
- `review_state.is_due` is computed by the backend. The frontend must not infer due status from `knowledge_points.status`.

### 4. Validation & Error Matrix

- Unknown user or knowledge point -> documented not-found family without leaking other users' data.
- Session belongs to another user -> `SESSION_NOT_FOUND`.
- Trigger from `practice_support`, submitted, or another later stage -> `SESSION_CONFLICT` with 409.
- Redis get/set failure -> continue without cache and return a fresh payload with `cache_hit=false`.
- Missing `due_at` for a reviewing/mastered point -> return no `review_state` or a non-due preview; never mark it due optimistically.

### 5. Good/Base/Bad Cases

- Good: start session returns a documentation-reading guide message, documentation endpoint returns five learner-safe sections, and trigger returns one `show_concept_intro`.
- Good: a previously triggered concept check can replay the same active concept intro without duplicate stage reset.
- Base: Redis is down; documentation still returns from persisted lesson content and tests remain offline.
- Bad: starting a learning session still auto-sends `show_concept_intro`, trigger resets a practice-stage session, or cache keys omit `user_id`.

### 6. Tests Required

- API-test new session start with `learning_stage=documentation_reading` and no initial concept tool call.
- API-test documentation success, ownership failure, learner-safe payload shape, and Redis cache hit/miss behavior with fake cache clients.
- API-test `trigger-concept-check` first trigger, concept-check replay, later-stage conflict, and learner-question input to concept generation.
- API-test plan detail review preview for due, future due, and missing review state.
- Run bootstrap-heavy M2/M3/M4 pytest batches sequentially, not in parallel.

### 7. Wrong vs Correct

#### Wrong

```python
cache_key = f"kp-doc:{knowledge_point_id}"
session["learning_stage"] = "concept_check"
```

This can leak user-specific documentation cache content and skips the required reading stage.

#### Correct

```python
cache_key = f"kp-doc:{user_id}:{knowledge_point_id}"
session["learning_stage"] = "documentation_reading"
```

The cache boundary is user-scoped and concept checks are created only after the explicit trigger.

## Scenario: Learning Session Message Streaming Conversation

### 1. Scope / Trigger

- Trigger: implementing or changing model-backed learning conversation messages, structured public output, practice unlock copy, or generated learning tool calls for the active learning workspace.
- Scope: `POST /api/learning-sessions/{session_id}/messages`, `LearningMessageRequest`, `app/services/conversations/learning_conversation.py`, `app/agents/learning/learning_public_output.py`, `app/agents/learning/learning_conversation_agent.py`, `app/agents/learning/learning_concept_agent.py`, `app/services/llm/llm_client.py`, `idempotency_records`, and API tests for JSON and SSE modes.
- SDK-backed Agent modules for this flow belong under `app/agents/`, for example `app/agents/learning_conversation_agent.py` and `app/agents/sdk_runtime.py`.

### 2. Signatures

- `POST /api/learning-sessions/{session_id}/messages`
- Request body: `{ "role": "user", "content": string, "client_message_id": string }`
- Streaming selector: `Accept: text/event-stream`
- Request tracing: optional `X-Request-Id`
- Idempotency key: `learning-message:{session_id}:{client_message_id}`
- Practice unlock tool args: `show_code_exercise.args.notice` defaults to an empty string; it must not copy the model-generated agent message.
- Local protocol boundary: `TextCompletionClient.complete_structured_text_stream(messages, *, output_type=LearningPublicOutput, temperature=None)`.
- Learning structured output schema: `LearningPublicOutput(schema_version, public_message, internal_review)`.
- Learning stream decoder: `LearningOutputStreamDecoder.feed(chunk) -> list[str]` and `LearningOutputStreamDecoder.finish() -> LearningPublicOutput`.
- Default configured model path: `AgentsSDKLearningConversationClient.complete_structured_text_stream(...)`, backed by `openai-agents` with `Agent(output_type=LearningPublicOutput)`.
- DeepSeek learning text path: `DirectLearningConversationClient.complete_structured_text_stream(...)`, backed by `OpenAICompatibleClient.complete_structured_text_stream(...)`, Chat Completions `stream=true`, and `response_format={"type":"json_object"}`.
- DeepSeek concept JSON path: `DirectConceptClient.complete_json(...)`, backed by `OpenAICompatibleClient.complete_json(...)` and Chat Completions `response_format={"type":"json_object"}`.
- Dependency signature: `openai-agents==0.17.3` in `aearn/services/api/pyproject.toml`.
- SDK tool factory signature: `app/agents/tools.py::build_teaching_tools(messages) -> list[Tool]`.
- SDK guardrail factory signature: `app/agents/guardrails.py::build_teaching_guardrails() -> tuple[list[InputGuardrail], list[OutputGuardrail]]`.

### 3. Contracts

- JSON mode returns `agent_message`, `session_state`, `generation_source`, and optional `generation_model`; `agent_message.content` is the validated `public_message`.
- SSE mode emits one or more `agent_message` events and exactly one terminal `done` event on success.
- `agent_message` data must include `request_id`, `session_id`, `message_id`, `delta`, and accumulated `content`.
- SSE learning-message `agent_message` deltas must be decoded only from the structured envelope's `public_message`; never stream JSON braces, `schema_version`, `internal_review`, or extra diagnostic text as message content.
- `done` data must include `request_id`, `session_id`, `message_id`, `generation_source`, `generation_model`, and a `result_ref`.
- Provider configuration, raw provider errors, API keys, hidden test source, hidden case IDs, and reference answers must never be returned or logged.
- The prompt context may include current knowledge point, lesson outline, sanitized current-stage state, safe exercise prompt/starter code, visible run summary, learner message, and safe conversation continuity only.
- The learning prompt user JSON must not contain `response_policy`, `stage_strategy`, `forbidden_outputs`, `allowed_outputs`, or renamed equivalents of those internal policy objects.
- Safe conversation continuity is `conversation_context.safe_summary` plus the most recent bounded `recent_safe_messages`; it must be generated or reused after sanitizing stored `learning_messages`, not by injecting full raw chat history.
- `conversation_summary` belongs under `learning_sessions.learning_stage_state_json` as versioned session state. It must include refresh metadata such as message count and stage so the service can avoid every-turn summary refresh.
- Direct-answer requests from learners are not input-guardrail failures by default. Detect them separately, compile the decision into `LearningReplyDirective`, and render only concise public-facing reply instructions; do not serialize the directive object or internal field names into user JSON.
- Aearn-owned SDK modules may use SDK `Agent`, `Runner.run_streamed`, `ModelSettings`, and `OpenAIProvider`, but product API shapes and durable state remain in Aearn services/repositories.
- Teaching-agent SDK tools may read only the already-sanitized learning evidence prepared by `learning_conversation.py`; they must return bounded summaries and must not read or write repositories directly.
- Teaching-agent SDK tools must not return hidden case IDs, hidden test source, `solution_reference`, full submitted code, provider payloads, raw prompts, API keys, or full note bodies.
- Teaching-agent guardrails must exist at the SDK-agent boundary and at the public response boundary so fake clients and SDK clients both pass through the same leak checks before JSON or SSE output reaches the frontend; guardrails are defense-in-depth, not the primary channel separator.
- Teaching-agent output guardrails must block internal policy self-references when they appear in `public_message`, including `response_policy`, `_policy`, `policy要求`, and "according to policy" style wording, while allowing normal course terminology such as browser same-origin policy.
- `internal_review` contains only fixed boolean self-review fields. Any false value, missing field, duplicate key, extra free-text reasoning, or non-boolean value invalidates the candidate.
- `internal_review` must never be returned to JSON clients, emitted over SSE, stored in `learning_messages.content`, stored in normal metadata, or written to ordinary logs.
- Provider-native reasoning fields such as DeepSeek `reasoning_content` remain ignored by transport parsing and must not be mapped into the structured public envelope.
- SDK tracing must be disabled by default for this path unless a dedicated tracing configuration is explicitly designed.
- SDK provider base URL handling must preserve existing `OPENAI_BASE_URL` behavior: both `https://provider.example` and `https://provider.example/v1` must resolve to the OpenAI client base URL ending in `/v1`.
- `llm_provider_type="deepseek"` must use the direct OpenAI-compatible Chat Completions path for learning text and concept JSON. Do not instantiate OpenAI Agents SDK clients, tools, or handoffs for DeepSeek learning-session generation unless a task explicitly implements the official Chat Completions `tools` / `tool_calls` / `role:"tool"` loop.
- `show_code_exercise` remains a backend-owned tool event: the service/repository owns exercise selection, unlock reason, `learning_incomplete`, and durable stage writes.
- Practice unlock visible copy is model-backed: when `practice_unlock_reason` is set, the prompt must require a current knowledge-point summary based on `concept_progress.concept_summary` and `lesson_outline`.
- Practice unlock model copy must not repeat the exercise card payload. The prompt must forbid printing the exercise title, prompt, starter code, code blanks, code blocks, or blank answers; the generated exercise card owns those details.
- `show_code_exercise.args.notice` must not duplicate `agent_message.content`; use an empty notice unless a future model contract adds a separate, non-duplicative notice field.
- Do not add deterministic or keyword fallback copy for practice unlock. If the model is disabled, unavailable, returns empty output, or fails guardrails before success, return `MODEL_UNAVAILABLE` and do not emit/store `show_code_exercise`.
- When model configuration is disabled, incomplete, failing, or produces an invalid/empty stream, return `MODEL_UNAVAILABLE`.

### 4. Validation & Error Matrix

- Blank `content` or `client_message_id` -> `VALIDATION_ERROR` with 400 in JSON mode or one SSE `error` event in streaming mode.
- Missing or inactive learning session -> `SESSION_NOT_FOUND` with 404 in JSON mode or one SSE `error` event in streaming mode.
- Same idempotency key with a different request body -> `IDEMPOTENCY_CONFLICT`, `recoverable=false`.
- Same idempotency key with the same request body -> replay the stored completed assistant message; SSE replay may send it as one `agent_message` plus `done`.
- Model failure before useful validated public output -> `MODEL_UNAVAILABLE`.
- Model failure during `practice_offer -> practice_support` unlock -> `MODEL_UNAVAILABLE`; no agent success message, no `show_code_exercise`, no idempotency success record.
- DeepSeek direct Chat Completions failure, invalid structured JSON, missing JSON response-format support, or empty direct stream before useful output -> `MODEL_UNAVAILABLE`.
- SDK runner exception, invalid SDK event stream, missing final structured output, or empty SDK output before useful output -> `MODEL_UNAVAILABLE`.
- Structured envelope schema failure, duplicate JSON key, missing or blank `public_message`, false `internal_review`, public guardrail failure, or decoder/final-output mismatch -> `MODEL_UNAVAILABLE`.
- Guardrail-blocked learner request or model public output before useful output -> `MODEL_UNAVAILABLE`.
- Model stream interruption after partial output -> SSE `error` event with recoverable retry guidance and no stored successful response.
- Guardrail-blocked model output after at least one public SSE `agent_message` chunk -> SSE `error` event with recoverable retry guidance and no stored successful idempotency response.
- Unexpected server failure -> `INTERNAL_ERROR` without raw provider details, prompt text, code submissions, or secrets.

### 5. Good/Base/Bad Cases

- Good: configured OpenAI-compatible provider streams a structured envelope, the decoder emits only `public_message` deltas, the service stores the final public response once, and replay returns the same `client_message_id` result without calling the model again.
- Good: learner clicks `开始练习`, the configured model returns a concise current knowledge-point summary in `public_message`, and `show_code_exercise.args.notice` is empty so the card does not repeat the agent message.
- Good: DeepSeek learning messages use direct Chat Completions structured JSON while concept checks use their own direct JSON path; OpenAI can continue using the Agents SDK path with `output_type=LearningPublicOutput`.
- Good: SDK tools summarize current stage, knowledge point, exercise metadata, and visible latest-attempt facts without exposing raw code submissions or hidden identifiers.
- Base: local development has no model key; the endpoint returns `MODEL_UNAVAILABLE` and all tests pass without live provider access via fake clients.
- Bad: adding a durable chat-history table for this MVP, exposing hidden test data in prompt/response, using WebSocket/global chatbot behavior for active learning composer messages, exposing SDK event names directly through the public API, sending DeepSeek through Agents SDK handoff/tool orchestration, letting an SDK tool mutate `Attempt`, `ReviewState`, `ReviewLog`, `Note`, `LearningSession`, or `idempotency_records`, showing hard-coded practice unlock copy when the model is unavailable, streaming raw JSON envelope keys to the frontend, rendering `internal_review` or provider reasoning, printing the exercise prompt/starter code in the agent message before the card, or copying the full agent message into `show_code_exercise.args.notice`.

### 6. Tests Required

- API-test JSON success and idempotent replay for a real active learning session.
- API-test SSE success with ordered `agent_message` chunks followed by terminal `done`.
- Unit-test structured learning output schema, duplicate-key rejection, false `internal_review`, public-message guardrails, and the incremental decoder for chunk splits, escapes, Unicode escapes, field-order changes, truncation, and oversized output.
- API-test missing session and validation errors in both JSON and SSE modes.
- API-test LLM-disabled or LLM-failure `MODEL_UNAVAILABLE` and assert provider raw details do not leak.
- API-test practice unlock in JSON and SSE modes with LLM disabled; assert `MODEL_UNAVAILABLE`, no terminal success, and no `show_code_exercise`.
- API-test JSON success and replay expose only validated `agent_message.content`, never `internal_review` or diagnostic text.
- API-test SSE success emits only decoded `public_message` deltas followed by terminal `done`.
- API-test successful practice unlock with fake structured model output; assert `generation_source="llm"`, the prompt forbids repeating exercise-card details, the model text includes the current knowledge-point summary, and `show_code_exercise.args.notice == ""`.
- API-test guardrail-blocked JSON model output and assert `MODEL_UNAVAILABLE` without leaked hidden IDs, key-like tokens, or complete-answer wording.
- API-test internal policy leakage in normal model content, such as `_policy` or `policy要求`, and assert `MODEL_UNAVAILABLE` with no leaked content persisted.
- API-test guardrail-blocked SSE output after a partial safe chunk and assert a recoverable `error` event with no stored successful idempotency response.
- API-test safe summary generation, persisted summary reuse below refresh threshold, direct-answer request redirection, and prompt context redaction for hidden IDs, internal reference fields, provider errors, API-key-like tokens, and complete-answer wording.
- Unit-test OpenAI-compatible streaming payload compatibility so unsupported `temperature` is omitted by default.
- Unit-test DeepSeek direct learning structured streaming and direct concept JSON clients with fake transports; assert learning messages request Chat Completions `response_format={"type":"json_object"}` and do not instantiate Agents SDK clients.
- API-test DeepSeek concept repair and practice-unlock flows with fake direct clients; assert there is no `MODEL_UNAVAILABLE` caused by Agents SDK handoff/tool orchestration.
- Unit-test the SDK-backed client with a fake SDK runner; tests must assert no live model call is required, tracing is disabled, structured public output is serialized, `output_type=LearningPublicOutput` is attached, base URLs are normalized, SDK tools are attached, and guardrails are attached.
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
chunks = AgentsSDKLearningConversationClient(settings).complete_structured_text_stream(
    messages,
    output_type=LearningPublicOutput,
    temperature=None,
)
```

The feature owns safe prompt construction, structured-output decoding, model-error mapping, idempotency, and SSE framing while the SDK client remains behind the local structured text boundary.

#### Wrong

```python
client = AgentsSDKLearningConversationClient(settings, side_effects=side_effects)
```

This sends DeepSeek learning sessions through SDK tools/handoffs even though the provider contract is Chat Completions-compatible, not Agents SDK orchestration-compatible.

#### Correct

```python
if settings.llm_provider_type == "deepseek":
    client = DirectLearningConversationClient(settings)
else:
    client = AgentsSDKLearningConversationClient(settings, side_effects=side_effects)
```

DeepSeek uses the documented Chat Completions surface while the service keeps stage transitions and `show_code_exercise` tool payloads under Aearn ownership.

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
- Bad: SDK code writes product rows, exposes SDK event names through SSE, logs raw prompts, returns provider error bodies, trusts model-provided knowledge point IDs, presents Java `managed_compiled_test` as full project execution, or promises C++ execution for `compiled_sandbox_later`.

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
- For the onboarding route path, allowed graph intents are `TOOL_CALL -> build_plan_draft|rebuild_plan_draft`, `PERSISTENCE -> confirm_plan`, and `FEEDBACK_REQUEST -> onboarding_clarification`; invalid graph output falls back to existing slot/proposal and confirm service behavior.
- For the review route path, allowed graph intents are `PERSISTENCE -> review_session|attempt_and_fsrs` and `TOOL_CALL -> review_coach|evaluate_warmup`; invalid graph output falls back to repository-owned due-state/session/attempt behavior.
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
- Unit-test the learning service graph transition adapter so scoped `STAGE_UPDATE` / ordered `TOOL_CALL` intents are consumed, scoped human checkpoints stay internal, and unscoped persistence/profile/side-effect intents fall back before service execution.
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
- Demo or interview docs for this graph slice must state that the learning page is the full graph runtime proof, while onboarding and review remain graph-assisted service flows with service/repository-owned persistence.
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
- Runtime context block builder: `build_runtime_context_block(*, safe_summary, recent_messages, current_focus_key, fallback_focus_key=None, strategy_key=None, avoid_key=None)`.
- Domain runtime context builders: `build_onboarding_plan_runtime_context(...)` and `build_review_runtime_context(...)`.

### 3. Contracts

- Shared runtime-context helpers may transform domain facts into safe prompt context, produce bounded summaries, normalize JSON, and expose domain-specific `runtime_context` dictionaries.
- Shared runtime-context helpers must not import repository modules, open database connections, write `LearningPlan`, `LearningSession`, `LearningMessage`, `Attempt`, `ReviewState`, `ReviewLog`, `Note`, or `idempotency_records`.
- Domain services remain responsible for loading facts, persisting summaries, mapping model failures to public errors, idempotency replay, and public JSON/SSE framing.
- Domain adapters must keep domain-specific policy explicit. Learning, onboarding, and review contexts may share sanitization primitives, but must not collapse into one global summary schema.
- Runtime context must contain bounded and sanitized summaries only: no hidden test ids/source, `solution_reference`, full submitted code, full private notes, raw prompts, provider payloads, SDK event names, or API keys.
- Shared runtime context blocks must not carry learning-specific internal policy objects such as `response_policy`; learning reply behavior belongs in the owning service as `LearningReplyDirective` plus compiled public-facing instructions.
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
    recent_messages=[message.as_dict() for message in safe_messages],
    current_focus_key="current_stuck_point",
    fallback_focus_key="last_diagnosis",
    strategy_key="last_agent_strategy",
    avoid_key="avoid_repeating",
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

- Good: TypeScript may have official docs grounding, a validated Node/TypeScript runner, and `enabled_for_public_selection=True` because the route/content/UI contract explicitly enables public selection.
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
assert require_language_capability("typescript").enabled_for_public_selection is False
```

Grounding can be prepared before the public course contract exists, but it must not silently change language selection or runner availability.

## Scenario: Browser Preview Runner Boundary

### 1. Scope / Trigger

- Trigger: adding or changing `browser_preview` runner behavior for JavaScript, HTML, or CSS exercises.
- Scope: `app/services/browser_preview_runner.py`, `app/services/runner_registry.py`, `app/services/runtime_runner.py`, `app/services/language_capabilities.py`, exercise/review seed metadata, and browser runner tests.

### 2. Signatures

- Service signature: `execute_browser_preview_with_tests(exercise, code, filled_blanks) -> BrowserPreviewExecutionResult`.
- Runtime dispatch signature: `RunnerRegistry.run_browser_preview(exercise, code, filled_blanks) -> RuntimeExecutionResult`.
- Runtime profile signature: `runtime_profile.runtime_tier="browser_preview"` with `language` in `javascript`, `html_css`, `html`, or `css`.
- Metadata fields: `metadata_json.required_patterns`, optional `metadata_json.preview_html.success`, optional `metadata_json.preview_html.failure`, optional `metadata_json.browser_rule_family`.
- Test case fields: `case_type` may be `visible`, `hidden`, or `preview_assertion`.

### 3. Contracts

- Browser preview is a deterministic teaching runner, not a real headless browser or arbitrary JS project runner.
- The runner must not install npm packages, execute arbitrary `assertion_code`, fetch network resources, or write project files.
- JavaScript event-flow exercises use the `js_event_flow` rule family: event binding, output sync, blank gates, and shared state before the event listener.
- HTML/CSS static preview exercises use the `static_preview` rule family: blank gates and required patterns without requiring `addEventListener` or `output.textContent`.
- `BROWSER_PREVIEW_RUNNER` must disclose `supports_execution=True`, `supports_tests=True`, `supports_stdout=True`, and `supports_preview=True`.
- Public `RuntimeExecutionResult.test_results` must redact hidden case ids, hidden expected values, and hidden failure messages.

### 4. Validation & Error Matrix

- `while (true)` or `for (;;)` in browser-preview code -> `runtime_status=timeout`, failed public test cases, retry same.
- Browser runtime-error signature such as `throw new Error` or `undefinedVariable` -> `runtime_status=runtime_error`, failed public test cases, explain error.
- JavaScript event-flow code missing event binding or output sync -> `runtime_status=success` with failing tests, not a runner crash.
- HTML/CSS static preview missing required patterns -> `runtime_status=success` with failing tests and failure preview HTML when available.
- Hidden test failure -> public hidden case id such as `hidden_case_3` and generic hidden failure message.

### 5. Good/Base/Bad Cases

- Good: a JavaScript counter exercise with shared `count` state before `addEventListener` passes visible and preview assertion tests.
- Good: an HTML/CSS static exercise with `.pill.active` and required CSS patterns passes without any JavaScript event code.
- Base: preview assertions remain deterministic server-owned checks; `assertion_code` is stored but not executed.
- Bad: applying JavaScript event-flow requirements to HTML/CSS static preview exercises.
- Bad: exposing hidden ids such as `hidden_secret_case` or expected values such as `999` in public test output.

### 6. Tests Required

- Assert browser runner capability selects `runner_key="browser"` and discloses execution/tests/stdout/preview support.
- Assert JavaScript event-flow success covers event binding, output sync, shared state, stdout, and preview HTML.
- Assert HTML/CSS static preview can pass without `addEventListener` or `output.textContent`.
- Assert runtime error and timeout return stable public categories.
- Assert hidden browser failures redact case ids and expected values.
- Run M3/M4 regression tests after dispatch changes because learning and review write `Attempt(run)` records from `RuntimeExecutionResult`.

### 7. Wrong vs Correct

#### Wrong

```python
if runtime_tier == "browser_preview":
    logic_pass = logic_pass and "addEventListener" in code and "output.textContent" in code
```

This forces HTML/CSS static preview exercises to satisfy JavaScript counter-exercise rules.

#### Correct

```python
if language in {"html_css", "html", "css"}:
    rule_family = "static_preview"
else:
    rule_family = "js_event_flow"
```

Browser preview exercises share the same runtime tier, but JavaScript event-flow and HTML/CSS static preview have different deterministic validation rules.

## Scenario: Exercise Template Runtime Alignment

### 1. Scope / Trigger

- Trigger: adding or changing internal exercise seed/harness templates, adaptive exercise generation, semantic validators, language-course runtime profiles, or practice unlock behavior.
- Scope: `app/services/exercises/exercise_repository.py`, `app/services/exercises/exercise_templates.py`, `app/services/exercises/adaptive_exercise_service.py`, `app/services/runners/runtime_runner.py`, `app/services/runners/runner_registry.py`, `app/services/curriculum/plan_generator.py`, and M3 exercise/session tests.

### 2. Signatures

- Internal seed/harness signature: `_exercise_template(knowledge_point, runtime_profile) -> dict[str, object]`.
- Canonical template signature: `select_canonical_exercise_template(knowledge_point=..., runtime_profile=..., fallback_template=...) -> CanonicalExerciseTemplate`.
- Adaptive generation signature: `build_adaptive_exercise_template(conn, knowledge_point=..., runtime_profile=..., fallback_template=..., candidate_generator=...) -> dict[str, object]`.
- Runtime profile fields: `language`, `runtime_tier`, `runner`, `supports_tests`.
- SQL metadata fields: `metadata_json.sql.dialect`, `metadata_json.sql.setup_sql`, `metadata_json.sql.comparison`, and `metadata_json.sql.max_rows`.
- Public executable language/runtime pairs include `python`/`python_stdout_test`, `javascript`/`browser_preview`, `html_css`/`browser_preview`, `typescript`/`node_typescript_test`, `sql`/`sql_query_test`, and `java`/`go`/`csharp` with `managed_compiled_test`.

### 3. Contracts

- An internal seed/harness template must match the current `runtime_profile.language`, `runtime_tier`, and runner capability before adaptive generation begins.
- Adaptive model generation may rewrite learner-facing fields, but the canonical seed must not point to a different language or runtime tier.
- SQL exercises must use SQL starter/solution code, SQLite teaching metadata, and `sql_query_test`; they must not fall through to browser/JavaScript event templates.
- Browser seed templates are valid only for browser-preview languages and must not be used as the generic seed for every unhandled public language.
- `cpp` and Rust must not be promoted to executable templates unless the public language enum, DB constraints, catalog, runtime profile, docs, and tests are updated together.
- Model candidate validation must run semantic alignment checks and the selected runner before caching.
- Provider, schema, semantic, runner, or unsupported-runner failure must retry with safe feedback up to the configured cap, then surface `MODEL_UNAVAILABLE` or the documented unavailable family without presenting the internal seed as a user-visible adaptive exercise.
- Public exercise payloads must not expose hidden test bodies, hidden expected values, `solution_reference` except where the API contract explicitly returns it for local teaching flows, provider payloads, or raw prompts.

### 4. Validation & Error Matrix

- `language=sql` and `runtime_tier=sql_query_test` -> SQL `SELECT` starter code, SQLite metadata, and SQL runner validation.
- `language=html_css` and `runtime_tier=browser_preview` -> static preview/browser metadata, not JavaScript event-flow-only requirements.
- `language=javascript` and `runtime_tier=browser_preview` -> JavaScript/browser event-flow-compatible template.
- Public language with missing internal seed branch -> add an explicit seed/harness template or prove the selected seed matches the language/runtime through tests before exposing the course.
- Unsupported runner capability -> return an unavailable generation error; do not show the internal seed as a learner-visible adaptive exercise.
- Model candidate schema, semantic, or runner failure -> retry with safe feedback; retry-cap exhaustion returns an honest unavailable error.

### 5. Good/Base/Bad Cases

- Good: SQL practice unlock materializes an exercise whose `starter_code` starts with `SELECT`, has `metadata_json.sql.dialect="sqlite"`, and passes `sql_query_test`.
- Good: browser-preview HTML/CSS exercises can pass static preview checks without requiring `document.querySelector` or `addEventListener`.
- Base: model generation is unavailable; the API returns a recoverable unavailable error instead of presenting a deterministic seed as adaptive practice.
- Bad: a SQL route unlocks a practice card containing `document.querySelector`, `addEventListener`, or `count += 1`.
- Bad: adding a public language route without a matching runtime profile, seed/harness template, runner validation, and regression test.

### 6. Tests Required

- Unit-test `_exercise_template()` seed/harness selection and adaptive generation behavior for each public language/runtime pair touched by the task.
- API-test learning-session practice unlock for changed languages, including `runtime_profile.language`, `runtime_profile.runtime_tier`, starter code shape, and metadata.
- Runner-test the generated solution for SQL, Python, browser preview, Node/TypeScript, or managed compiled paths as appropriate.
- Regression-test that SQL does not fall through to browser/JavaScript seed strings.
- Regression-test that provider, schema, semantic, or runner failure does not present an internal deterministic seed as adaptive practice.
- Keep routine DB tests offline/fake for adaptive model generation unless the test explicitly opts into a live provider.

### 7. Wrong vs Correct

#### Wrong

```python
return {
    "slug": f"m3-browser-{knowledge_point_id}",
    "starter_code": "const button = document.querySelector('#run')",
}
```

Using a browser seed as the final catch-all makes non-browser public routes show the wrong language syntax.

#### Correct

```python
if language == "sql":
    return {
        "starter_code": "SELECT name\nFROM learners\nWHERE __BLANK_1__\nORDER BY id;\n",
        "metadata_json": {"sql": {"dialect": "sqlite", "setup_sql": [...]}},
    }
```

The internal seed/harness is language/runtime-correct before adaptive generation. If model generation fails validation, retry and then return an honest unavailable error instead of showing this seed as adaptive practice.

## Scenario: Onboarding Chat-First Message Normalization

### 1. Scope / Trigger

- Trigger: adding or changing Onboarding conversation generation, visible message normalization, slot extraction readiness, or route-card generation.
- Scope: `app/services/conversations/onboarding_conversation.py`, `app/routes/onboarding.py`, `app/agents/onboarding/onboarding_slot_extractor.py`, and Onboarding tests.

### 2. Signatures

- Visible message normalizer: `normalize_onboarding_agent_message(content, *, slots, route_ready) -> str`.
- Route tool event: `show_learning_route` may be emitted only after required slots are confirmed.
- Public SSE errors: `MODEL_UNAVAILABLE` and `LANGUAGE_NOT_SUPPORTED`.

### 3. Contracts

- Onboarding is chat-first and workflow-aware: answer or acknowledge the user's latest intent before asking for route-building details.
- Slot extraction, `missing_slot_question`, and `plan_ready` are private workflow state, not a reason to erase valid advisory, comparison, or capability answers.
- If `route_ready=false`, visible text must not claim "information is enough", route-card generation, or route readiness.
- If required slots are missing or ambiguous, do not emit `show_learning_route` and do not persist `extracted_context.plan_draft`.
- Explicit C++ or Rust route choices keep the `LANGUAGE_NOT_SUPPORTED` path.
- Model failure keeps the `MODEL_UNAVAILABLE` path; do not add keyword slot parsing or deterministic conversation fallback.
- Language support has separate layers:
  - Public course / route selection: `python`, `javascript`, `typescript`, `sql`, `html_css`, `java`, `go`, and `csharp`.
  - Teaching-grade executable runners: TypeScript / TS, SQL, Go, and C# may be public routes while still being limited to single-file, query, or harness-based execution.
  - Unsupported route languages: C++ and Rust remain `LANGUAGE_NOT_SUPPORTED` until a task updates catalog, content, UI, API examples, and tests together.
- TypeScript / TS is executable through the Node/TypeScript runner and is an independent public route.
- Agent language advice may mention Python first for tooling, automation, backend, and local scripts, and JavaScript/TypeScript for web-product agents; TypeScript must not be bridged to JavaScript.

### 4. Validation & Error Matrix

- Valid advisory/comparison/capability answer with missing required slot -> preserve answer and append or keep at most one natural follow-up.
- Model text claims route readiness while `route_ready=false` -> replace with the missing-slot follow-up.
- Empty generated model text -> keep empty so the route can return `MODEL_UNAVAILABLE`.
- Required slot status is `missing`, `ambiguous`, or `unsupported` -> `plan_ready=false`; no route tool and no stashed draft.
- TypeScript / TS selected with all required slots confirmed -> generate `language=typescript`; no `LANGUAGE_NOT_SUPPORTED`.
- TypeScript / TS selected with missing or ambiguous required slots -> no `show_learning_route` and no stashed `plan_draft`.
- Explicit C++ or Rust as the selected route -> `LANGUAGE_NOT_SUPPORTED`.

### 5. Good/Base/Bad Cases

- Good: "agent 一般用什么语言" receives a recommendation such as Python for tooling/automation and JavaScript/TypeScript for web products before any route-building follow-up.
- Good: "我想用 TypeScript 做网页端科研助手，零基础" can create a TypeScript public route instead of reporting `LANGUAGE_NOT_SUPPORTED` or bridging to JavaScript.
- Good: "Python 和 JavaScript 哪个更适合做 agent" receives a recommended first path with reasoning, then one follow-up at most.
- Base: a direct slot answer such as "Python" can advance to the next missing route-building question.
- Bad: replacing a valid answer with only "你想主学哪门语言？目前支持 ..." when the user asked an advisory or capability question.
- Bad: synthesizing a route card or stashing `plan_draft` while required slots remain ambiguous.

### 6. Tests Required

- Unit-test normalization for advisory, capability, comparison, duplicate-follow-up avoidance, route-ready claim blocking, and empty model text.
- Route/SSE tests must cover direct slot progression, independent TypeScript route generation, ambiguous required and optional slots, C++/Rust unsupported-language behavior, `MODEL_UNAVAILABLE`, and route-card generation/replay.
- Assert ambiguous required slots leave persisted `extracted_context.plan_ready=false` and omit `plan_draft`.

### 7. Wrong vs Correct

#### Wrong

```python
if question and not _text_contains_phrase(text, question):
    return _missing_slot_followup_message(slots)
```

This erases useful chat-first answers and makes Onboarding feel like a form.

#### Correct

```python
if _claims_route_ready(text):
    return _missing_slot_followup_message(slots)
if question and _has_structured_clarification(slots):
    return _append_missing_slot_followup_message(text, slots)
```

Safety blocking remains strict, while valid conversational answers stay visible.

## Scenario: Feature-Disabled Tutor Harness Runtime Seam

### 1. Scope / Trigger

- Trigger: adding or extending the internal Tutor Harness under
  `app/agents/harness/` and `app/services/tutor/`, including the finite run
  loop, context construction, provider gateway, feature flag, typed effects, or
  compaction requests.
- Scope: `TUTOR_HARNESS_ENABLED`, `TutorRunLoop`, `TutorHarnessService`,
  `TutorRunStore`, context/provider/capability/effect/compaction ports, and
  the focused Harness unit tests.
- This is a migration seam. It is not permission to add a learner-facing route,
  SSE frame, Desktop consumer, database migration, repository, worker, or
  outbox before the owning follow-up task is approved.

### 2. Signatures

- Environment: `TUTOR_HARNESS_ENABLED=false` by default; it is independent of
  `LANGGRAPH_ENABLED`.
- Internal entry point:
  `TutorHarnessService.run(run_id=..., lease_owner_id=...) -> TutorRunResult`.
- Finite orchestration:
  `TutorRunLoop.run(run_id=..., lease_owner_id=...) -> TutorRunResult`.
- Revision authority:
  `TutorRunStore.current_input_revision(run_id) -> int`.
- Provider boundary:
  `TutorProviderGateway.decide(run=..., context=...) -> TutorProviderResult`.
- Compaction boundary:
  `TutorCompactionPublisher.publish(TutorCompactionRequest)`; the request must
  carry a deterministic idempotency key and must not call a Curator directly.

### 3. Contracts

- Keep `TUTOR_HARNESS_ENABLED` feature-off unless an explicit integration task
  wires it. Legacy routes, Graph routing/checkpoints, SSE producers, learning
  conversation services, and Desktop source must not read the flag during the
  isolated runtime-seam phase.
- Harness modules may use `app.agents.runtime` helpers and the selected
  `OpenAICompatibleClient`. They must not import legacy Graph/router modules,
  LangGraph APIs, route handlers, database connections/repositories, or worker
  implementations.
- Acquire a valid lease before writing any terminal checkpoint or durable-like
  result. A lease conflict returns a non-persistent `lease_unavailable` result;
  it must not allow a competing worker to terminalize the run.
- Reload the authoritative input revision before a model call, capability
  dispatch, after a capability result, and immediately before effect commit. An
  effect whose expected revision is stale becomes `stale_rejected` and its
  committer is never called.
- Every interactive TurnRun context must resolve one authoritative learner input
  from exact run/revision evidence and carry it separately from optional history.
  Reserve its bounded token cost before optional sections; optional context may be
  evicted, but must never evict the current input. If no safe non-empty
  representation fits, fail with a typed safe code before provider invocation.
  Proactive contexts must explicitly declare that current input is not required.
- Context construction is deterministic and bounded in this order:
  system/selected-Skill/policy, active plan, review/FSRS, sanitized recent
  messages, working summary, learner-visible memory, activity/execution facts,
  and allowed capability schemas. Checkpoint metadata contains only source
  identifiers, hashes, counts, and token-budget data; it never stores a raw
  prompt, full history, provider payload, hidden test, reference answer, or
  secret.
- The provider gateway uses only the currently configured primary model/provider
  and its existing retry behavior. Configuration, transport, strict-envelope,
  malformed nested payload, or guardrail failures map to the redacted internal
  terminal code `MODEL_UNAVAILABLE`; do not add cross-provider/model fallback.
- A compaction request may be published only for terminal, safe-checkpoint, or
  configured context-high-water conditions. It is not a per-token trigger and
  does not create a worker, outbox row, or model call in this phase.

### 4. Validation & Error Matrix

- `TUTOR_HARNESS_ENABLED=false` -> internal service returns `blocked_policy`
  / `feature_disabled` without lease acquisition or provider invocation.
- Lease unavailable -> `blocked_policy` / `lease_unavailable`, with no
  checkpoint or result persisted by the losing worker.
- Deadline, cancellation, or an exhausted fixed budget after a lease -> typed
  terminal outcome plus a terminal checkpoint/compaction request.
- Newer input revision before effect commit -> `stale_rejected`; the effect
  committer receives no call.
- Primary provider configuration/call/invalid response/strict-envelope or
  guardrail failure -> `model_unavailable` with safe code `MODEL_UNAVAILABLE`
  and no raw provider detail.
- Capability/effect port denies or is unavailable -> `blocked_policy`; no
  default capability executes and no product-domain mutation occurs.
- Forbidden import or a legacy product consumer of the Harness flag -> test
  failure before integration.

### 5. Good/Base/Bad Cases

- Good: a fake primary provider produces a bounded decision, a fake store owns
  the lease, and the run waits for input or reaches a typed terminal result
  without changing existing public traffic.
- Good: a second learner input increments the revision; the old effect is
  rejected, context is rebuilt from the new revision, and the stale committer
  is never invoked.
- Base: a local developer has no model key. The isolated gateway returns
  `MODEL_UNAVAILABLE` through fakes/tests; no live provider call is required.
- Bad: a terminal checkpoint is written before acquiring a lease, allowing a
  losing worker to race the owning worker.
- Bad: a gateway silently redacts and accepts `reasoning`, provider diagnostics,
  hidden-test, or raw-history data inside a nested capability/effect payload.
- Bad: setting the internal flag changes legacy API/SSE/Desktop behavior or
  introduces a migration/outbox/worker before the designated child owns it.

### 6. Tests Required

- Unit-test default-false feature gating, with no lease or provider call while
  disabled; statically assert legacy API, Graph, streaming, conversation, and
  Desktop sources do not consume `TUTOR_HARNESS_ENABLED`.
- Unit-test zero, one, and multiple bounded iterations; cover lease conflict,
  cancellation, deadline, iteration/model/capability/effect budgets, and the
  no-persist behavior for a losing lease contender.
- Unit-test revision reloads at every unsafe boundary and assert a stale effect
  is recorded as `stale_rejected` before the committer can run.
- Unit-test fixed-order context selection, token/item limits, runtime and
  Harness-specific redaction, metadata-only checkpoints, and deterministic
  high-water/terminal/safe-checkpoint compaction idempotency keys.
- Unit-test both DeepSeek Chat Completions and OpenAI-compatible Responses
  through fake transports; assert no fallback, strict nested envelope rejection,
  guardrail rejection, and redacted `MODEL_UNAVAILABLE` results.
- Keep the legacy Graph redaction regression test: legacy import must re-export
  the runtime-owned helper without changing its bounded redaction behavior.

### 7. Wrong vs Correct

#### Wrong

```python
# A losing worker persists a terminal result before it owns the run.
if stop_outcome is not None:
    return self._terminal(snapshot, outcome=stop_outcome)
lease = store.acquire_lease(run_id, owner_id=owner_id, now=clock.now(), duration_seconds=30)
```

This lets cancellation, deadline, or a zero budget terminalize a run even when
another worker already owns the lease.

#### Correct

```python
lease = store.acquire_lease(run_id, owner_id=owner_id, now=clock.now(), duration_seconds=30)
if lease is None:
    return nonpersistent_lease_unavailable(run_id)
if stop_outcome is not None:
    return persist_terminal_after_owned_lease(snapshot, lease, stop_outcome)
```

Lease ownership precedes terminal persistence. The finite loop then reloads the
input revision before every unsafe boundary and keeps all resulting state inside
its typed ports until later persistence and API integration tasks own the
adapter work.


## Scenario: Authoritative Tutor Current Input and Newest History

### 1. Scope / Trigger

- Trigger: changing interactive Tutor input evidence, `TutorContextInput`,
  `TutorContextBuilder`, PostgreSQL context loading, provider prompt assembly,
  context-failure mapping, or latest-input regression evaluation.
- Scope: `tutor_run_input_events`, `tutor_messages`,
  `app/agents/harness/{contracts,context_builder}.py`,
  `app/services/tutor/{interactive,provider_gateway,run_loop,evals}.py`, and
  their focused unit/PostgreSQL tests.
- This contract does not authorize schema changes, keyword-based production
  routing, provider fallback, live-provider CI, or proactive learner chat.

### 2. Signatures

- Evidence: `tutor_run_input_events(run_id, input_revision, message_id)` joins
  the canonical `tutor_messages(id, conversation_id, role, content)` row.
- Loader: `PostgresTutorContextLoader.load_context(snapshot, *, input_revision)
  -> TutorContextInput`.
- Input contract: `TutorContextInput.current_input_required: bool` plus
  `current_input: TutorContextSource | None`.
- Builder: `TutorContextBuilder.build(context_input, *, token_budget)
  -> TutorContextSelection`.
- Provider payload: `{input_revision, current_input, context,
  context_metadata}`, where `current_input` is separate from optional context.
- Optional smoke: set `AEARN_RUN_TUTOR_LATEST_INPUT_SMOKE=1`, then run
  `python -m app.services.tutor.latest_input_smoke` through the API `uv`
  environment.

### 3. Contracts

- Interactive runs explicitly set `current_input_required=true` and resolve
  exactly one nonblank learner message from the active run, exact revision, user,
  and conversation. Never infer current input from timestamp, role alone, or the
  last conversation row.
- Proactive runs explicitly set `current_input_required=false`, carry no
  `current_input`, and expose no recent learner chat. Origin and loader mode
  must agree; a caller cannot use proactive composition to bypass an interactive
  input requirement.
- The builder sanitizes and bounds current input first, reserves its token estimate
  before every optional section, and stores only source id/hash, token estimate,
  and truncation state in checkpoint metadata. Selection content and metadata must
  agree exactly.
- Optional recent history excludes the exact current message. Apply the item cap
  to the newest suffix, attempt token-budget selection newest-first, skip an
  oversized optional item without blocking smaller next-newest items, then present
  selected messages in chronological order.
- If a safe nonempty current-input representation cannot fit, terminate before
  the provider with a typed safe diagnostic. Never call the provider with missing
  learner intent.
- Initial and repair requests share the same teaching policy: acknowledge/answer
  the authoritative input first, treat corrections/refusals/completion as stale
  path overrides, do not repeat rejected steps, answer advice/comparison questions
  directly, and ask at most one necessary follow-up.

### 4. Validation & Error Matrix

- Required input missing -> `TUTOR_CURRENT_INPUT_MISSING`; no provider call.
- Input supplied when not required -> `TUTOR_CURRENT_INPUT_UNEXPECTED`.
- Loader origin/composition mismatch -> `TUTOR_CONTEXT_ORIGIN_INVALID`.
- Requested revision differs from the snapshot or is below one ->
  `TUTOR_CURRENT_INPUT_REVISION_INVALID`.
- Exact scoped event/message evidence is missing or ambiguous ->
  `TUTOR_CURRENT_INPUT_EVIDENCE_INVALID`.
- Evidence points to a non-learner role -> `TUTOR_CURRENT_INPUT_ROLE_INVALID`.
- Canonical or sanitized input is blank -> `TUTOR_CURRENT_INPUT_EMPTY`.
- Minimum safe representation exceeds the token budget ->
  `TUTOR_CURRENT_INPUT_UNREPRESENTABLE`; run terminalizes as `failed` with
  zero model calls and public projection remains the generic safe failure family.

### 5. Good / Base / Bad Cases

- Good: a long conversation resolves `我应该学哪些语言` from exact run/revision
  evidence, excludes it from history, keeps the newest prior messages, and sends it
  as the provider payload's separate `current_input`.
- Good: an explicit continuation advances the same run revision; the new event is
  current input and the prior revision becomes optional history. Equal timestamps
  and later unrelated rows do not change current-input identity.
- Base: a proactive candidate carries learner-state/activity context with
  `current_input_required=false` and no learner chat.
- Bad: read eight newest rows, reverse them, then take the first four; this selects
  an older prefix and can discard the learner's latest correction.
- Bad: silently omit an oversized required input, route on Chinese keywords, or let
  a schema-repair reminder replace the teaching policy.

### 6. Tests Required

- Unit-test required-input reservation, sanitization, deterministic truncation,
  unrepresentable failure, selection/metadata consistency, and proactive invented
  input rejection.
- Unit-test latest-history item cap and tight-budget behavior: select newest-first,
  skip oversized optional items, and emit the selected subset chronologically.
- PostgreSQL-test exact event/message resolution, long history, equal timestamp,
  later interfering rows, explicit continuation revision, role/missing evidence,
  scope mismatch, and interactive/proactive origin agreement.
- Provider-test separate payload shape, current-input content, teaching-policy
  markers, and repair inheritance without echoing rejected output.
- Run-loop/eval tests assert typed failure and zero provider calls. Default tests
  must not read live settings or construct a live provider; the smoke command is
  explicit opt-in only.

### 7. Wrong vs Correct

#### Wrong

```python
rows = load_latest_messages(limit=8)
context = TutorContextInput(
    current_input_required=True,
    current_input=None,
    recent_messages=tuple(reversed(rows)),
)
```

This guesses that history contains the current request and lets item/token limits
discard it.

#### Correct

```python
current = load_exact_input_event(run_id=run.run_id, input_revision=run.input_revision)
history = load_bounded_history_excluding(current.message_id)
context = TutorContextInput(
    current_input_required=True,
    current_input=TutorContextSource(f"message:{current.message_id}", current.content),
    recent_messages=history,
)
selection = builder.build(context, token_budget=run.policy.context_token_budget)
```

The exact event owns identity, required input consumes budget first, and optional
history can be reduced without erasing the learner's current intent.


## Scenario: Tutor Primary JSON Decision Provider Boundary

### 1. Scope / Trigger

- Trigger: changing `OpenAICompatibleClient.complete_json()`, DeepSeek model
  routing, Responses SSE decoding, `PrimaryTutorProviderGateway`, strict
  `TutorDecision` parsing, or provider diagnostic logging.
- Scope: `app/services/llm/{llm_client,llm_urls}.py`,
  `app/services/tutor/provider_gateway.py`,
  `app/agents/harness/contracts.py`, and focused fake-transport tests.
- This scope owns a primary-provider JSON decision boundary only. It does not
  authorize a provider/model fallback, public diagnostics, conversation-title
  persistence, history APIs, or Desktop behavior.

### 2. Signatures

- `select_llm_protocol(settings) -> LLMProtocol`.
- `deepseek_responses_url(base_url) -> str`.
- `OpenAICompatibleClient.complete_json(messages, *, temperature, max_tokens,
  timeout_seconds) -> LLMJsonResponse`.
- `PrimaryTutorProviderGateway.decide(run, context) -> TutorProviderResult`.
- `parse_tutor_decision(payload) -> TutorDecision`.
- Strict decision fields: `public_message`, `conversation_title`,
  `skill_references`, `capability_requests`, `effect_proposals`,
  `checkpoint_reason`, `continuation_kind`, and `terminal_intent`.

### 3. Contracts

- Select exactly one protocol before the request: non-DeepSeek uses Responses;
  DeepSeek uses `/responses` only for the exact case-sensitive model
  `deepseek-v4-flash`; every other DeepSeek model uses
  `/chat/completions`. Never use a prefix, alias, casing normalization, failed
  request, or retry to infer a different protocol.
- The DeepSeek Responses request uses `input`, optional `instructions`,
  `stream=true`, `text.format=json_object`, and bounded
  `max_output_tokens`. Its final learner-visible content may come only from
  `output_text`; reasoning, analysis, provider error bodies, and arbitrary output
  items are never a fallback source.
- Use one canonical complete JSON example in both the initial prompt and the
  one permitted same-primary repair. The decision envelope is `extra=forbid`.
  `conversation_title` is NFKC-normalized, single-line, learner-safe, and at
  most 48 characters. `continuation_kind` is closed and is valid only with
  `checkpoint_reason=capability_result` and no terminal intent.
- A repair is allowed at most once and only for a repairable visible-content,
  JSON, Tutor-decision, or output-safety rejection. `response.incomplete`,
  `response.failed`, malformed envelopes, HTTP/transport failures, and selected
  provider request rejection terminate without repair.
- HTTP 400 maps to the bounded internal category
  `TUTOR_PROVIDER_REQUEST_REJECTED`; public run reads/SSE remain
  `MODEL_UNAVAILABLE`. Provider bodies, prompts, reasoning, headers,
  credentials, URL details, and exception messages must not enter public
  projections, durable safe diagnostics, or normal logs. Transport logs may use
  only a stable exception category.

### 4. Validation & Error Matrix

- Exact `deepseek-v4-flash` -> one `/responses` request; no Chat Completions
  fallback.
- Other DeepSeek model or different casing -> one `/chat/completions` request.
- Completed response with only reasoning/no `output_text` ->
  `TUTOR_PROVIDER_RESPONSE_CONTENT_MISSING`; one same-primary repair may be
  attempted.
- `response.incomplete` -> `TUTOR_PROVIDER_RESPONSE_INCOMPLETE`; one request,
  no repair.
- `response.failed` -> `TUTOR_PROVIDER_RESPONSE_FAILED`; one request, no repair.
- Unsupported/malformed Responses envelope ->
  `TUTOR_PROVIDER_RESPONSE_ENVELOPE_INVALID`; one request, no repair.
- Visible non-object JSON -> `TUTOR_PROVIDER_RESPONSE_CONTENT_NOT_JSON`; at most
  one same-primary repair.
- HTTP 400 -> `TUTOR_PROVIDER_REQUEST_REJECTED`; one request, no repair/fallback.
- Unknown decision key, unsafe title, invalid continuation, or internal nested
  field -> `TUTOR_PROVIDER_DECISION_INVALID`; at most one same-primary repair.

### 5. Good / Base / Bad Cases

- Good: fake `deepseek-v4-flash` Responses SSE emits deltas and a completed
  response; only the assembled `output_text` becomes the strict decision.
- Good: an upstream request rejection returns a bounded internal category while
  public API/SSE reveal only `MODEL_UNAVAILABLE` and the provider response is not
  retained.
- Base: a non-V4-Flash DeepSeek model remains on the existing Chat Completions
  JSON contract.
- Bad: falling through from `/responses` to `/chat/completions`, treating a
  reasoning item as answer content, retrying `response.failed`, or logging an
  exception string that contains provider URL, headers, or credentials.

### 6. Tests Required

- Fake-transport tests assert exact-model protocol selection, URL normalization,
  request shape, selected-protocol failure call count, and no fallback.
- Test raw SSE lines for `response.output_text.delta`, completed,
  incomplete, failed, malformed, reasoning-only, and non-JSON visible content.
- Test canonical prompt/repair shape, title/continuation validation, at-most-once
  repair, and that rejected JSON/provider body is absent from repair text and
  results.
- Test HTTP 400, authentication/quota/rate/timeout/transport categories and
  assert no provider detail appears in `repr`, public SSE, or log-safe transport
  categories.
- Run `tests/test_tutor_provider_gateway.py`, `tests/test_tutor_run_loop.py`,
  `tests/test_tutor_sse.py`, `ruff check`, `python -m mypy app`, and
  `git diff --check` through `uv` from `aearn/services/api`.

### 7. Wrong vs Correct

#### Wrong

```python
if responses_request_failed:
    return call_chat_completions(messages)
```

A cross-protocol fallback duplicates a primary decision attempt and hides a
provider-contract failure. It can also turn a rejected prompt into a second
unreviewed request.

#### Correct

```python
protocol = select_llm_protocol(settings)
response = complete_with_selected_protocol(protocol, messages)
if response_error_is_repairable(response):
    return repair_once_with_same_primary(messages)
return safe_selected_protocol_failure(response)
```

The configured model determines the one protocol before the call. Only bounded,
repairable candidate errors receive one same-primary repair; all other failures
remain safe terminal outcomes without provider detail.


## Scenario: Tutor Interactive TurnRun, Post-Provider Supersede, and Clock-Consistent CAS

### 1. Scope / Trigger

- Trigger: changing ordinary Tutor conversation input, first-turn creation, interactive dispatch, terminal persistence, public-process history, run-loop cancellation/supersede guards, or a proactive effect path that accepts an injected `Clock`.
- Scope: `app/routes/tutor.py`, `app/services/tutor/{public_api,interactive,run_loop,persistence,proactive_worker}.py`, additive `tutor_*` schema, and focused PostgreSQL/fake-provider/Desktop contract tests.
- This scenario owns the durable interactive TurnRun boundary. It does not authorize manual title rename, raw reasoning/provider projection, provider/model/protocol fallback, or a background run inheriting interactive authority.

### 2. Signatures

- First turn: `POST /api/tutor/conversations/first-turn` -> `PostgresTutorRepository.create_first_interactive_turn(...)`.
- Ordinary turn: `POST /api/tutor/conversations/{conversation_id}/inputs` -> `PostgresTutorRepository.create_interactive_turn(...)`.
- Explicit continuation only: `POST /api/tutor/runs/{run_id}/inputs`.
- Interactive dispatcher: `TutorInteractiveRunDispatcher.dispatch(user_id, run_id) -> TutorRunResult`.
- Unsafe-boundary guard: `TutorRunLoop._refresh_before_unsafe_boundary(snapshot, lease, metadata, effect_results)`.
- Terminal persistence: `PostgresTutorLifecycle.persist_terminal(...)` / repository terminal write under the scoped run/conversation lock.
- Clock-bound effect adapter: `PostgresProactiveEffectCommitter(repository, clock).commit(run, proposal)` -> `repository.commit_effect_if_current(..., now=clock.now())`.

### 3. Contracts

- A learner-visible `TutorConversation` is long-lived context/history scope. Every ordinary message creates a fresh finite interactive `TurnRun` with fresh policy deadline, counters, lease, and SSE lifecycle. Only a persisted explicit continuation can reuse its waiting run.
- First nonblank draft submit is one idempotent atomic mutation: conversation, run, learner message, input event, and initial allowlisted public-process projection either all commit or all roll back. Selecting a draft alone never persists a conversation.
- Under the conversation lock, a normal turn supersedes/cancels the current foreground run before inserting the replacement. The partial unique foreground predicate is the database authority; application-level selection alone is insufficient.
- Interactive provider calls must not inherit an implicit PostgreSQL transaction or hold a foreground/conversation lock. `TutorInteractiveRunDispatcher` uses an autocommit connection; repository lifecycle methods own short atomic transactions at durable boundaries.
- Immediately after every provider return, and again before decision gate, capability dispatch, effect commit, and terminal public persistence, the loop refreshes cancellation/supersede, lease, and input revision. If the run was superseded, it converges to a safe cancelled/superseded process result and must not invoke the decision gate, capability gateway, effect committer, or stale learner-visible terminal write.
- Terminal persistence repeats the foreground/cancel/supersede check while locked. A stale run may finalize only its safe cancellation/process projection; it cannot insert a Tutor message, write a conversation title, append a capability receipt, commit an effect, or advance public activity as a successful response.
- Any composition that accepts an injected `Clock` must propagate `clock.now()` into every repository mutation whose lease/CAS eligibility compares time. Do not mix a test/scheduler `FixedClock` with `datetime.now()` or an omitted repository `now` default, because an otherwise valid lease can be incorrectly rejected as expired.
- Conversation list/history/cursors and public-process labels are server projections. They remain user/conversation scoped and never reconstruct reasoning, traces, prompts, provider payloads, capability arguments, diagnostics, or secrets.

### 4. Validation & Error Matrix

- New ordinary input while an old provider call is pending -> old run is safely superseded after provider return; no Tutor message/title/capability/effect success from the old run.
- Terminal persistence observes cancellation/supersede/foreground loss under lock -> safe superseded/cancelled result only; no learner-visible success write.
- Normal completed/cancelled/superseded run passed to `POST /runs/{run_id}/inputs` -> `RUN_NOT_ACTIVE`; only a persisted authorized continuation is accepted.
- Same first-turn or ordinary-turn idempotency key/body -> replay the original safe IDs/result; same key with a different body -> `IDEMPOTENCY_CONFLICT`.
- Invalid, malformed, cross-user, or cross-conversation history/list cursor -> stable `CURSOR_INVALID`; no SQL/provider detail.
- A lease/CAS mutation evaluated with the composition clock before expiry -> normal current/committed path when other predicates pass; stale revision, cancelled/superseded state, or an actually expired lease -> safe stale/no-action path without a domain handler.

### 5. Good / Base / Bad Cases

- Good: ten ordinary messages retain one conversation id but create ten distinct run ids; each later run starts with fresh counters/deadline and the old foreground process becomes a safe superseded record.
- Good: a fake provider supersedes its run during `decide`; the post-provider guard returns cancellation before decision/capability/effect/public-terminal work, and the replacement run remains the only foreground run.
- Good: a proactive test injects `FixedClock`; the committer passes that same clock value into the repository CAS so the claimed lease is judged against the test timeline.
- Base: legacy message-only history remains readable without a fabricated process card or duration; title absence projects as `新对话`.
- Bad: calling a provider inside an open transaction, treating a revision check before the provider call as sufficient, writing a Tutor reply before the locked foreground recheck, or letting one repository call fall back to wall-clock time in a deterministic scheduler/test composition.

### 6. Tests Required

- `tests/test_tutor_input_merge.py`: first-turn atomic rollback/replay, distinct normal turns, foreground uniqueness, normal run-input denial, and provider-return supersede suppression.
- `tests/test_tutor_run_loop.py`: post-provider terminal/supersede refresh before decision, capability, effect, and terminal persistence.
- `tests/test_tutor_conversation_history.py`, `tests/test_tutor_sse.py`, and route/public API tests: user/conversation cursor scope, legacy history, allowlisted process projection, and selected-run-only transport behavior.
- `tests/test_tutor_proactive_default_delivery.py`, `tests/test_tutor_evals.py`, and provider/persistence tests: injected-clock effect/CAS behavior, stable safe diagnostics, and no live provider call.
- Run `uv --directory .\aearn\services\api lock --check && uv --directory .\aearn\services\api run python -m pytest -q`, then `ruff check app tests`, `python -m mypy app`, `pnpm --dir .\aearn desktop:check`, and `git diff --check`.

### 7. Wrong vs Correct

#### Wrong

```python
with connect() as conn:
    repository = PostgresTutorRepository(conn)
    provider_result = provider.decide(run=snapshot, context=context)
    repository.persist_terminal(...)
```

The provider call can inherit an implicit transaction and keep the foreground/conversation lock while a newer ordinary message needs to replace the run. A later terminal write can then publish stale work.

```python
receipt = repository.commit_effect_if_current(..., now=datetime.now(UTC))
```

This evaluates a deterministic scheduler/test lease against wall-clock time instead of the injected timeline.

#### Correct

```python
with connect() as conn:
    conn.autocommit = True
    result = loop.run(run_id=run_id, lease_owner_id=owner_id)

# `run_loop` refreshes supersede/cancellation after `provider.decide()`;
# lifecycle persistence opens the short locked transaction for the final write.
```

```python
receipt = repository.commit_effect_if_current(
    ...,
    now=self._clock.now(),
)
```

The external provider call no longer blocks replacement, the stale run fails closed at both loop and persistence boundaries, and all time-sensitive CAS predicates use the same composed clock.


## Scenario: Tutor Skill Catalog and Registry-Only Capability Gateway

### 1. Scope / Trigger

- Trigger: adding or changing published Tutor Skills, catalog compilation, catalog
  context decoration, decision gating, capability policy, or registry-only
  grounding under `app/agents/harness/` and `app/services/tutor/`.
- Scope: `app/agents/skills/`, `SkillCatalogCompiler`, immutable catalog and
  descriptor contracts, `CatalogContextLoader`, `TutorDecisionGate`,
  `CapabilityPolicyResolver`, `CatalogCapabilityGateway`, `GroundingLookup`,
  and focused catalog/gateway/grounding tests.
- This is still an internal feature-disabled Harness seam. It is not permission
  to expose a route, SSE event, Desktop consumer, database repository/migration,
  worker/outbox, arbitrary fetcher, runner, or legacy Graph/tool adapter.

### 2. Signatures

- Published bundle root:
  `app/agents/skills/<skill_id>/<semantic_version>/` containing
  `manifest.json`, a UTF-8 instruction file, and a non-empty JSON evaluation
  suite.
- Catalog compile:
  `SkillCatalogCompiler.compile(source_root: Path) -> SkillCatalogSnapshot`.
- Context decoration:
  `CatalogContextLoader.load_context(run, input_revision) -> TutorContextInput`.
- Decision gate:
  `TutorDecisionGate.validate(run, decision) -> TutorDecisionGateResult`.
- Capability dispatch:
  `CatalogCapabilityGateway.dispatch(run, request) -> TutorCapabilityResult`.
- Grounding adapter:
  `GroundingLookup.lookup(query, source_ids) -> tuple[GroundingLookupItem, ...]`.
- The first and only executable descriptor is
  `grounding.retrieve@1.0.0`; it accepts `language_id_or_alias`, `query_text`,
  optional `topic_tags`, and `top_k` in `1..4`.

### 3. Contracts

- A published Skill id and runtime reference must use stable identifiers plus
  exact SemVer. `current`, empty versions, ranges, wildcards, and unknown
  id/version pairs are denials, never resolution fallbacks.
- Catalog compilation is whole-snapshot and fail-closed: reject unsafe/symlinked
  source roots or resources, traversal, malformed/empty resources, hash
  mismatches, duplicate id/version pairs, untrusted resource refs, and unknown
  descriptor/effect declarations. The ordered immutable snapshot has a canonical
  SHA-256 digest.
- A policy context binds run/user scope, origin, input revision, catalog digest,
  consent, runtime availability, budget, eligible exact Skill refs, and allowed
  source ids. The uncomposed resolver is default-deny and must not infer any of
  those facts from model output.
- Before selection, context may expose only policy-eligible Skill summaries and
  MCP-compatible descriptor schemas. After a validated selection, it may expose
  only that reviewed instruction with exact id/version/hash facts. The normal
  bounded `TutorContextBuilder` remains the sole prompt-construction path.
- Store a new Skill selection only in the injected run-local store keyed by
  `(run_id, input_revision)`. Return a context-rebuild result and forbid a
  capability request, effect proposal, or terminal intent in that same
  selection decision. Durable selection/replay evidence belongs to the owning
  persistence child.
- The gate validates catalog membership and policy before every capability or
  effect boundary. The gateway decodes only descriptor-declared argument keys,
  validates the typed input/output schemas, and never turns a model value into
  a function, URL, path, SQL fragment, image, user id, shell command, or DB
  target.
- Registry grounding derives source scope from `grounding_sources.py` and uses
  an injected lookup over pre-indexed facts. Filter lookup output to registered
  source id/language/trust/allowlisted URL facts, reject credential-bearing
  citation URLs, bound snippets/citations, and convert malformed lookup output
  to a typed unavailable result. Harness/catalog/gateway code must not import a
  DB connection, persisted grounding index, HTTP client/fetcher, crawler,
  shell, runner, legacy Graph/router, or legacy teaching tools.
- Effects remain `TutorEffectProposal` values carrying
  `expected_input_revision`; they are default-denied unless both the selected
  Skill and catalog/policy explicitly authorize them. The initial published
  catalog authorizes no effect type.

### 4. Validation & Error Matrix

- Invalid or unpinned Skill ref, policy/catalog mismatch, or an unknown
  capability/effect -> typed `DENIED`; do not call the gateway or committer.
- New Skill selection mixed with a capability/effect/terminal action ->
  `DENIED / mixed_skill_selection_action`; record no partial action.
- No selected exact Skill before a capability request ->
  `DENIED / skill_selection_required`; do not call the lookup.
- Extra/duplicate/non-JSON argument fields or a URL/path/image/SQL/command
  input -> `DENIED / capability_arguments_invalid` or
  `DENIED / grounding_input_invalid`; do not call the lookup.
- Unsupported language -> `UNAVAILABLE / unsupported_grounding_language`.
  Empty policy/registry-source intersection ->
  `DENIED / grounding_source_scope_denied`.
- Lookup failure -> `UNAVAILABLE / grounding_lookup_unavailable`; malformed
  injected lookup output -> `UNAVAILABLE / grounding_lookup_invalid_result`.
  Out-of-scope or credential-bearing citation URLs are filtered before output
  and can produce a completed empty grounding result without leaking a value.
- Effect proposals not declared by the selected Skill/catalog/policy -> typed
  denial before `TutorEffectCommitter.commit()`; no product-domain mutation.

### 5. Good/Base/Bad Cases

- Good: policy exposes `tutor.registry-grounding@1.0.0` and
  `grounding.retrieve`; the first decision selects that exact Skill, the next
  bounded turn receives its reviewed instruction, and a declared request returns
  at most four cited registry snippets.
- Good: a malformed lookup record, invalid SHA-256 content hash, or credentialed
  canonical URL fails closed without exposing an unsafe citation.
- Base: default composition has no eligible Skill, capability, effect, source,
  or runtime permission, so model-shaped actions are denied without a network,
  DB, or product write.
- Bad: treating `current` as a latest-version lookup, loading an arbitrary Skill
  file from a provider field, resolving a URL/source id supplied by the model,
  or accepting a selected Skill and dispatching a capability in the same turn.
- Bad: allowing a manifest alone to enable plan/note/review/memory/runner
  effects before its owning durable transaction, sandbox, or user-control task
  exists.

### 6. Tests Required

- Assert deterministic snapshot digest and exact id/version resolution; reject
  invalid SemVer, `current`/wildcards, unsafe paths/symlinks, malformed or
  missing resources/evaluations, hash mismatch, duplicate bundles, unknown
  capabilities/effects, and untrusted registry refs.
- Assert context exposes only policy-eligible summaries/schemas before
  selection and exact reviewed instruction/hash facts after selection.
- Assert selection rebuilds context, cannot mix with a capability/effect, and
  does not persist beyond the injected run-local store contract.
- Assert unknown/non-policy capability/effect requests and undeclared/unsafe
  argument fields deny without gateway/lookup/committer calls.
- Assert `grounding.retrieve` language isolation, registry scope intersection,
  bounded snippets/citations, URL credential filtering, malformed lookup output
  failure, unsupported/empty results, and no lookup call for rejected input.
- Keep Child 00 Harness context/provider/run-loop tests and the static forbidden
  import/feature-off regression green. Use offline deterministic fakes only;
  no live model, documentation fetch, or database is required.

### 7. Wrong vs Correct

#### Wrong

```python
# A provider-selected version and URL become executable targets.
skill = catalog.resolve_latest(provider_skill_id)
return fetch(provider_arguments["url"])
```

This bypasses exact reviewed-version resolution, policy scope, schema
validation, and registry ownership.

#### Correct

```python
# Gate first; descriptor and registry scope own all executable facts.
gate = decision_gate.validate(run=run, decision=decision)
if gate.status is TutorDecisionGateStatus.REBUILD_CONTEXT:
    return rebuild_context()
if gate.status is TutorDecisionGateStatus.DENIED:
    return typed_denial(gate.diagnostic_code)

request = decode_only_descriptor_fields(decision.capability_requests[0])
return grounding_gateway.dispatch(run=run, request=request)
```

The model supplies only bounded intent. Catalog, policy, descriptor schemas,
and the registry determine whether anything is executable and what source scope
it can use.

## Scenario: Tutor Durable Persistence, Redacted Replay, and Curation Envelope

### 1. Scope / Trigger

- Trigger: changing Child 02 target-only Tutor SQL, `PostgresTutorRepository`,
  `PostgresTutorLifecycle`, safe trace/export projection, curation envelope, or
  deterministic Tutor evaluation fixtures.
- Scope: `app/db/schema.sql`, `app/services/tutor/{persistence,safe_projection,evals}.py`,
  the lifecycle adapter, and focused PostgreSQL/fake-only tests.
- This owner may persist feature-off `tutor_*` state. It does not add a route,
  SSE/`Last-Event-ID` adapter, Desktop consumer, worker, Curator model call, or
  plan/memory/review/FSRS/activity mutation.

### 2. Signatures

- Bootstrap: `bootstrap_database()` applies the additive idempotent `tutor_*`
  SQL delta through the existing schema applier.
- Input: `PostgresTutorRepository.accept_input(...) -> TutorInputAcceptance`.
- Replay: `events_after(user_id, run_id, after_sequence, limit) -> tuple[TutorDurableEvent, ...]`.
- Lifecycle: `PostgresTutorLifecycle.persist_safe_checkpoint(...)`,
  `persist_context_high_water(...)`, `persist_terminal(...)`, and
  `persist_waiting_result(...)` are the composed transaction boundary.
- Effects: `commit_effect_if_current(...) -> TutorEffectCommitReceipt`.
- Diagnostics: `TutorSafeProjection.project(...)` before persistence and
  `export(...)` again for every read/export path.

### 3. Contracts

- All new state is additive `tutor_*`, uses UUID/timestamptz/explicit JSONB
  contracts, and keeps user/run/conversation scope in both repository predicates
  and composite foreign keys. Bootstrap must be safe to rerun, including when
  the named scoped constraints already exist.
- Canonical learner text is written only to `tutor_messages`. Events,
  checkpoints, capability/effect receipts, traces, outbox rows, proposal rows,
  and exports contain only allowlisted IDs, hashes, counters, codes, and bounded
  metadata.
- Input acceptance locks the scoped run, replays the same key/body hash,
  rejects a different hash or cancelled/terminal run, increments exactly one
  revision, and appends one ordered `input_accepted` event in the same
  transaction.
- `next_event_sequence` is allocated under the locked run row. Reads return only
  `event_sequence > after_sequence` in ascending order; request-local SSE IDs
  are never stored as this cursor.
- Checkpoint/high-water/terminal writes atomically include their safe event,
  redacted trace, and idempotent outbox envelope. Retrying the same lifecycle
  identity reuses the trace/outbox rather than adding a second diagnostic row.
- Capability receipts require an exact selected Skill/catalog evidence and
  replay only an identical request/result receipt. Effects remain default-deny:
  a registered in-transaction handler is insufficient unless the exact selected
  catalog evidence also declares the effect; stale lease/revision/cancellation
  records only `stale_rejected` evidence and never invokes a handler.
- Curation source IDs/hashes and idempotency keys must pass the same safe
  projection before storage. Proposal creation marks an outbox stale when its
  input revision, policy/memory version, or retention boundary is stale.

### 4. Validation & Error Matrix

- Missing/wrong-user run or outbox -> `TutorRunNotFound`.
- Same input/event/capability/effect/outbox/proposal identity with different
  immutable evidence -> `TutorIdempotencyConflict`.
- Cancelled or terminal run -> reject new input/non-terminal state with
  `TutorTerminalStateConflict`.
- Stale lease, expired lease, or stale revision -> `TutorLeaseConflict` at the
  repository; the lifecycle adapter maps it to `TutorLifecycleConflict`, and
  the loop returns non-persistent `blocked_policy / lease_unavailable`.
- Unpinned/mismatched Skill, undeclared capability, or undeclared effect ->
  `TutorCatalogEvidenceError` or a durable typed `denied` effect; no callback.
- Unsafe diagnostic key/value, source evidence, or export header -> omit it;
  never substitute raw provider, prompt, code, path, command, SQL, or secret.

### 5. Good/Base/Bad Cases

- Good: a retry of the same input, event, safe checkpoint, terminal result,
  outbox, or proposal returns its original durable identity and preserves one
  ordered event/trace/outbox/proposal record.
- Good: a learner cancellation races an old effect; the repository records a
  safe `stale_rejected` event and does not call the handler.
- Base: the initial reviewed catalog declares no effect type, so even an
  explicitly registered future handler remains denied.
- Bad: writing learner content to `payload_json`, `trace_json`, or an outbox
  JSON column; exporting an unprojected event/trace `kind`; treating a local
  `evt_*` writer counter as a durable replay cursor.

### 6. Tests Required

- Run bootstrap twice and assert every `tutor_*` table/trigger/scoped constraint
  exists; assert a run cannot combine one user's `user_id` with another user's
  conversation.
- Assert input replay/hash conflict/cancellation, exact Skill evidence,
  capability receipt identity, event suffix ordering, terminal uniqueness, and
  lifecycle rollback/idempotent trace/outbox behavior.
- Assert stale lease/revision/cancellation effects never invoke the registered
  handler; initial catalog effects remain denied.
- Assert nested/key/value-based redaction at write and export time, including a
  malformed historical event/trace header and unsafe curation source evidence.
- Keep fake-only eval fixtures pinned to catalog/Skill hashes and cover denial,
  strict provider rejection, bounded loop, CAS, primary-only model failure,
  replay/outbox/proposal/terminal identity, and leakage.

### 7. Wrong vs Correct

#### Wrong

```python
# Each retry creates a fresh trace and trusts raw outbox source metadata.
append_event(run_id, event_key="checkpoint:1")
insert_trace(raw_checkpoint)
insert_outbox(source_ids=request.source_ids)
```

This duplicates diagnostic state and can turn the outbox into a raw
conversation/diagnostic store.

#### Correct

```python
# Under the scoped run lock, reuse the event/trace identity and project twice.
event = append_safe_event_locked(...)
trace = insert_or_replay_safe_trace(event, projector.project(metadata))
upsert_outbox(projector.export(source_ids_and_hashes), trace)
```

The lifecycle transaction either commits the whole safe receipt once or rolls
it back without a visible partial event, trace, or outbox row.

## Scenario: Feature-Disabled Tutor Proactive Scheduler and Curation Queue

### 1. Scope / Trigger

- Trigger: adding or changing target-only proactive signals/candidates, scheduler
  policy, PostgreSQL queue leases, curation-job mechanics, internal proactive
  conversations, `origin` propagation, or the three Tutor Celery wrappers.
- Scope: `app/services/tutor/{proactive,proactive_repository,proactive_worker}.py`,
  `TutorRunSnapshot`, `CapabilityPolicyContext`, `app/db/schema.sql`,
  `aearn_worker/worker_app.py`, and focused scheduler/database/worker tests.
- This is a Child 04 background seam. It must not expose an API route, SSE frame,
  desktop state, normal-success chat message/notification, legacy review-worker
  behavior, direct memory/plan/activity/inbox/review/FSRS/attempt write, or a
  live model dependency.

### 2. Signatures

- Signal ingress:
  `TutorProactiveScheduler.ingest_committed_signal(signal, now) -> TutorProactiveCandidate`.
- Candidate drain:
  `TutorProactiveScheduler.drain_candidates(worker_id, now, limit) -> SchedulerDrainResult`.
- Curation seed/drain:
  `seed_curation_jobs(now, limit)` and `drain_curation(worker_id, now, limit)`.
- DB: `tutor_proactive_preferences`, `tutor_proactive_signals`,
  `tutor_proactive_candidates`, `tutor_curation_jobs`, and
  `tutor_scheduler_audit`; all must use scoped foreign keys, lease generations,
  terminal-state checks, and repeatable bootstrap DDL.
- Background run reservation: one internal `tutor_conversations` row
  (`visibility=internal`, `kind=proactive`) plus one `tutor_runs` row with
  `origin=proactive` before a finite `TutorRunLoop` receives the run id.
- Worker tasks: `tutor.proactive.scan_due_signals`,
  `tutor.proactive.drain_candidates`, and `tutor.curation.drain`.

### 3. Contracts

- Defaults are fail-closed: `TUTOR_PROACTIVE_SCHEDULER_ENABLED=false`,
  `TUTOR_BACKGROUND_HARD_PAUSED=true`, no cutover eligibility, zero budgets,
  and no inferred-memory processing. Settings may enable mechanics only after a
  later approved cutover owns public activation.
- A signal carries only stable identifiers, a SHA-256 source hash, bounded
  dedupe facts, and allowlisted reference fields. Raw learner text, prompts,
  provider payloads, code, paths, commands, secrets, and reasoning are not
  scheduler/audit data.
- Scheduler policy checks global enable/hard pause/cutover, user preference and
  pause, independent proactive or curation budget/concurrency/cooldown/circuit
  limits before an executor or Curator processor call. Every denied candidate or
  leased job records a safe `no_action`/`stale` audit result.
- `TutorRunSnapshot.origin` is required and validated. Persistence must reject a
  missing/unknown origin, policy resolution must copy `run.origin`, and policy
  matching must compare origin so a background run cannot inherit interactive
  authority.
- The proactive composition forbids `runner.execute` and domain effects. It
  reserves the durable run before invoking only the existing finite loop; it
  never produces direct chat/desktop delivery.
- Curation jobs may be seeded only from Child 02 `pending` outbox records. They
  retain that outbox as the semantic redacted envelope, recheck policy/memory
  versions, source revision, and staleness, then call only an injected proposal
  processor. Child 04 supplies a default-deny processor, not a Curator model.

### 4. Validation & Error Matrix

- Scheduler disabled, hard paused, cutover-ineligible, preference-disabled,
  budget/concurrency/cooldown/circuit denial -> durable `no_action`; no provider,
  capability, or Curator processor call.
- Duplicate signal in the same user/dedupe bucket -> one existing candidate,
  signal `suppressed/dedupe_window`, and safe audit evidence.
- Expired lease below retry cap -> pending with bounded backoff; at/over cap ->
  terminal `failed`. A terminal row cannot return to a working state.
- Unknown/missing persisted run origin -> persistence error; never silently
  default to `interactive`.
- Non-pending/stale outbox, stale source revision, policy-version mismatch, or
  memory-setting mismatch -> curation `stale`/`no_action`; no processor call.
- Missing scheduler composition in the worker -> typed no-action fallback; no
  implicit provider or legacy review-task fallback.

### 5. Good/Base/Bad Cases

- Good: two committed signals with different producer ids but one dedupe bucket
  create one candidate, preserve both signal dispositions, and make the duplicate
  auditable without calling a model.
- Good: a proactive reservation creates an internal empty conversation and a
  `proactive` run, then an injected finite-loop factory can run that exact id.
- Base: scheduler remains disabled in a normal local checkout, so all target
  worker wrappers return a bounded blocked/no-action result and leave product
  traffic unchanged.
- Bad: treating a worker name as proof of origin, reusing a learner-visible
  conversation for a background run, putting raw outbox/learner content in an
  audit row, calling a Curator after inferred memory is disabled, or reusing a
  legacy review task as a hidden Tutor wake-up path.

### 6. Tests Required

- PostgreSQL tests: bootstrap twice; assert all scheduler tables, indexes,
  triggers, scoped foreign keys, terminal/lease checks, dedupe replay, lease
  recovery/backoff, and one internal proactive conversation/run reservation.
- Policy tests: explicit/unknown origin behavior, resolver origin match,
  proactive `runner.execute`/effect denial, fail-closed settings, and static
  absence of proactive composition in Graph/route/streaming/Desktop sources.
- Scheduler tests: hard pause, user pause, budget, concurrency, cooldown,
  circuit, and duplicate-window paths produce no executor call.
- Curation tests: outbox job idempotency, hard pause, inferred-memory disable,
  independent curation budget, stale outbox/revision/version handling, retry,
  and proof that no processor call happens after denial.
- Worker import tests: target task names/routes are registered while existing
  `review.refresh_due_counts` and `review.generate_seed_bank` remain unchanged.

### 7. Wrong vs Correct

#### Wrong

```python
# A broker retry creates a second learner-visible conversation and immediately calls a model.
conversation_id = create_existing_chat_conversation(user_id)
provider.decide(prompt_from_signal(signal))
```

#### Correct

```python
# PostgreSQL owns candidate claim and durable run reservation before the finite loop.
candidate = repository.claim_next_candidate(...)
if not policy.allows(candidate):
    repository.mark_candidate_terminal(candidate=candidate, state="no_action", ...)
else:
    reservation = repository.reserve_proactive_run(candidate=candidate, ...)
    result = finite_loop.run(run_id=reservation.run_id, lease_owner_id=worker_id)
```

The correct path is idempotent, origin-aware, feature-off by default, and has no
unbounded provider, direct domain-write, chat, or desktop side effect.

## Scenario: Feature-Disabled Tutor Learner State, Curator, and Safe Activity Projections

### 1. Scope / Trigger

- Trigger: changing reviewed Tutor learner-state effects, `tutor.learner-state@1.0.0`,
  `tutor_*` plan/memory/activity/inbox tables, `TutorLearnerStateRepository`,
  `PrimaryCurationGateway`, `TutorMemoryCurator`, or the Child 04 curation
  worker composition.
- Scope: `app/agents/harness/capabilities.py`, `app/agents/skills/`,
  `app/services/tutor/{persistence,learner_state,curation,proactive,proactive_worker}.py`,
  `app/core/config.py`, `app/db/schema.sql`, and focused PostgreSQL/fake-only tests.
- This is a target-only domain layer. It must not add a public route, SSE frame,
  Desktop rendering, legacy Graph composition, legacy plan/profile write, review,
  FSRS, attempt, executor, provider/model fallback, cutover, or legacy retirement.

### 2. Signatures

- Catalog effect types: `tutor.plan.activate`, `tutor.plan.rollback`,
  `tutor.memory.record`, and `tutor.activity.record`, each at exact version
  `1.0.0` and declared only by `tutor.learner-state@1.0.0`.
- Effect boundary:
  `PostgresTutorRepository.commit_effect_if_current(user_id, run_id, lease, proposal, idempotency_key, now)`
  validates the descriptor payload, exact selected Skill evidence, current input
  revision, lease, cancellation, and idempotency before invoking a domain handler.
- Plan domain: `TutorLearnerStateRepository.activate_plan_from_effect(...)` and
  `rollback_plan_from_effect(...)`; rollback accepts no caller-selected target.
- Learner controls: `set_inferred_memory_preference(...)`, `correct_memory_entry(...)`,
  `delete_memory_entry(...)`, `mark_inbox_read(...)`, and `dismiss_inbox_item(...)`.
- Curator: `PrimaryCurationGateway.propose(source) -> CurationGatewayResult` and
  `TutorMemoryCurator.process(job, lease_owner_id, now) -> CurationProcessOutcome`.
- Environment: `TUTOR_CURATION_MAX_OUTPUT_TOKENS=0` is the default. A positive
  value is necessary but not sufficient for a provider call; the Child 04
  scheduler, hard-pause, cutover, preference, source-revision, version,
  retention, budget, concurrency, cooldown, circuit, and job-lease gates still apply.
- DB: `tutor_plan_revisions`, `tutor_active_plans`,
  `tutor_plan_revision_actions`, `tutor_memory_preferences`,
  `tutor_memory_entries`, `tutor_context_summaries`,
  `tutor_curation_projection_receipts`, `tutor_activity_records`, and
  `tutor_inbox_items` are additive target-only tables.

### 3. Contracts

- Plan revisions are immutable and append-only. `tutor_active_plans` is the
  only mutable pointer. Activation creates an evidence-backed revision/action;
  rollback moves only to its stored predecessor and never edits revision bodies.
- Plan effects, actions, or read models never write `learning_plans`,
  `learner_profiles`, `review_states`, `review_logs`, FSRS state, attempts, or
  legacy product tables.
- `tutor.memory.record` accepts only `memory_kind="objective_fact"` with equal
  bounded `evidence_ids`/SHA-256 `evidence_hashes`. Inference is Curator-only
  and requires `confidence`, Curator/outbox/proposal provenance, policy and
  memory-setting versions, plus retention and staleness timestamps.
- Corrections append a new objective entry linked by `replaced_entry_id`; a
  delete changes only the guarded target state. No correction or delete rewrites
  historic evidence fields.
- A Curator receives only the Child 02 redacted outbox envelope, source ids and
  hashes, policy/memory versions, and retention facts. It stores neither raw
  prompt/message/provider payload/reasoning nor an arbitrary model response.
- A Curator chooses only one typed `context_summary`, `memory_entry`, or
  `no_action` result. Generic proposal evidence stores only a safe content hash;
  the target projection and exactly-one receipt carry the final domain result.
- `PrimaryCurationGateway` calls only the configured `OpenAICompatibleClient`
  primary provider/model. It must not instantiate or retry against a fallback
  provider/model. Existing transport retries inside that one configured client
  do not authorize a provider change.
- Proactive compositions permanently deny `runner.execute` and
  `tutor.memory.record`. They may receive only explicitly configured plan or
  activity effects with a positive effect budget; all default composition lists
  remain empty.
- Activity/inbox text is learner-safe and bounded. These tables never retain
  trace, provider reasoning, prompt, code, URL, path, command, SQL, hidden-test,
  solution, or secret data.

### 4. Validation & Error Matrix

- Missing descriptor, malformed/extra payload fields, unselected Skill, or
  effect absent from the selected Skill -> durable `DENIED`; handler not invoked.
- Stale input revision, cancelled/terminal run, expired/mismatched lease ->
  durable `STALE_REJECTED`; handler not invoked.
- No active plan predecessor -> `plan_rollback_unavailable`; no pointer/revision
  mutation occurs.
- Invalid learner memory statement/evidence hash/count -> validation failure;
  no memory entry is inserted.
- Correcting/deleting a missing or non-active memory entry ->
  `memory_entry_not_found` or `memory_entry_not_active`.
- Memory preference/version mismatch, disabled inferred memory, non-pending
  outbox, stale source revision, expired retention/staleness, or stale job lease
  -> curation `no_action`/`stale`; no gateway call after the pre-call denial.
- `TUTOR_CURATION_MAX_OUTPUT_TOKENS=0` -> `curation_output_disabled`; no
  `OpenAICompatibleClient` construction or provider call.
- Invalid/unavailable primary model output -> retryable `curation_model_*`; no
  partial proposal, context summary, memory entry, or receipt is committed.
- A mismatched replay proposal/receipt/target hash -> idempotency conflict;
  never silently replace a learner-state projection.

### 5. Good/Base/Bad Cases

- Good: a selected `tutor.learner-state@1.0.0` plan activation writes one
  immutable revision, one active pointer, and one action; a second activation
  records the predecessor; rollback returns only to that predecessor.
- Good: an objective memory effect stores evidence without confidence; a
  Curator inference stores confidence, outbox/proposal scope, setting/policy
  versions, and retention facts; correction appends a linked replacement.
- Good: a queued, current, enabled curation job sends only its redacted envelope
  to one fake primary gateway, then commits one inference/context target and one
  `committed` receipt in the same transaction as generic proposal persistence.
- Base: normal settings keep `TUTOR_CURATION_MAX_OUTPUT_TOKENS=0`, so a worker
  can reach the composed processor but receives bounded no-action with zero
  provider calls and no public product behavior change.
- Bad: putting a plan body, memory statement, raw provider response, prompt, or
  learner message into `tutor_curation_proposals.payload_json`; directly writing
  activity/inbox from a Curator; accepting an inference through
  `tutor.memory.record`; or selecting a provider/model from model output.

### 6. Tests Required

- `tests/test_learning_plan_revisions.py`: activate/replay/second revision/
  predecessor-only rollback, immutable revision trigger, and proof legacy plan,
  review, and attempt counts are unchanged.
- `tests/test_tutor_memory.py`: objective-only effect evidence, setting-version
  control, correction/delete lineage, unsafe raw payload rejection, and no
  direct inference row.
- `tests/test_tutor_memory_curator.py`: redacted source shape, one fake-primary
  call for an eligible job, one target projection plus receipt, preference-disable
  no-call, and zero-output-token no-call.
- `tests/test_tutor_activity.py`: user scope, optional inbox lifecycle,
  safe activity fields, and descriptor denial before a handler write.
- `tests/test_tutor_skill_catalog.py`, `tests/test_tutor_capability_gateway.py`,
  and `tests/fixtures/tutor_evals/tutor_harness_foundation_v1.json`: exact Skill
  catalog order, effect descriptors, digest/hash identity, and no relaxation of
  the catalog gate.
- `tests/test_db_bootstrap.py`: bootstrap twice, all new target tables, indexes,
  trigger names, scoped foreign keys, and immutable/lifecycle checks.
- Run PostgreSQL/bootstrap-heavy Tutor tests sequentially, then `ruff check app tests`
  and `python -m mypy app` from `aearn/services/api` through `uv`.

### 7. Wrong vs Correct

#### Wrong

```python
# This bypasses the selected-Skill/descriptor/CAS boundary and leaves a raw
# provider response in a generic curation record.
outbox = load_outbox(job.outbox_id)
proposal = fallback_provider.complete_json({"prompt": raw_messages})
conn.execute("INSERT INTO tutor_memory_entries (...) VALUES (...)")
```

#### Correct

```python
source, code = learner_state.curation_source_for_job(...)
if source is None:
    return CurationProcessOutcome(state="no_action", code=code)

result = primary_only_gateway.propose(source=source)
if result.state == "proposal":
    with conn.transaction():
        proposal = tutor_repository.record_curation_proposal(
            payload={"safe_hash": projection_hash},
            ...,
        )
        learner_state.commit_inference_memory_projection(
            source=source,
            proposal_id=proposal.proposal_id,
            ...,
        )
```

The correct path validates before the model boundary, preserves one primary-only
call, stores only safe evidence in the generic proposal, and commits the target
projection through scoped repository contracts.

## Scenario: Verified Tutor Harness Cutover and Legacy Runtime Denial

### 1. Scope / Trigger

- Trigger: adding or changing `harness_cutovers`, `/api/harness/cutover`,
  destructive legacy cleanup, Tutor/legacy runtime gates, legacy review-worker
  writes, or an ordinary local-user reset during a Tutor rollout.
- Scope: `app/db/schema.sql`, `app/services/tutor/cutover.py`,
  `app/routes/{harness_cutover,tutor,users}.py`, audited legacy routers,
  `aearn_worker/worker_app.py`, and focused PostgreSQL/API tests.
- This is a one-way clean-slate transition. It is not history migration,
  provider/executor activation, Graph deletion, or recovery of confirmed data.

### 2. Signatures

- DB receipt: `harness_cutovers(user_id, cutover_version)` with the durable
  states `required`, `summary_ready`, `verified`, `verification_failed`,
  `blocked_target_state`, and `blocked_checkpoint_scope`.
- Status: `GET /api/harness/cutover?user_id={uuid}`.
- Confirm: `POST /api/harness/cutover/confirm` with
  `{ user_id, cutover_version, summary_version, preview_nonce, summary_hash,
  client_action_id, confirm: true }`.
- Tutor gate: `HarnessCutoverService.assert_runtime_allowed(user_id=...)`.
- Legacy gate: `HarnessCutoverService.assert_legacy_runtime_denied(user_id=...)`.

### 3. Contracts

- `TUTOR_HARNESS_ENABLED=false` leaves legacy routes unchanged and keeps Tutor
  routes feature-off before opening a target connection. The flag alone never
  authorizes a learner.
- When the rollout is active, only `verified` authorizes Tutor routes. Every
  legacy router is denied, including a verified user; a missing or malformed
  user scope also fails closed instead of allowing a session/path-only read.
- The server alone derives canonical legacy counts, target-state facts,
  checkpoint threads, summary hash, and preview nonce. Clients never submit a
  deletion table, count, target id, or checkpoint scope.
- Confirmation locks the user, recomputes the exact summary, deletes only
  proven legacy ownership, verifies the same scope, and commits `verified` in
  one transaction. A failure rolls back deletion and writes only a safe
  `CUTOVER_VERIFICATION_FAILED` receipt in a separate transaction.
- The cutover path deletes exact `idempotency_records.user_id` rows; it must not
  reuse reset's key/JSON/text `LIKE` ownership heuristic. It clears only the
  five legacy learner fields and preserves local identity plus notification/UI
  preferences.
- `tutor_*` user state is target-state contamination and blocks without any
  target or legacy deletion. Checkpointer cleanup recognizes only
  `aearn:learning:<learning_session_id>` in the supported public tables; a
  missing table is safe zero, while an unknown schema/namespace/`NULL` thread
  id/unmatched thread blocks.
- Once rollout is active, ordinary `POST /api/users/{user_id}/reset-data` first
  requires the Tutor authorization gate. It cannot delete a pending summary and
  turn that user into an implicit empty-state cutover.

### 4. Validation & Error Matrix

- Missing/false `confirm` -> `CUTOVER_CONFIRMATION_REQUIRED`; no deletion.
- Changed legacy inventory, stale version/nonce/hash, or cross-user preview ->
  `CUTOVER_SUMMARY_STALE`; refresh the server summary.
- Same `client_action_id` with a changed confirmation body ->
  `CUTOVER_CONFIRMATION_CONFLICT`.
- Pre-cutover target rows -> `CUTOVER_TARGET_STATE_PRESENT`; delete nothing.
- Unknown or unprovable checkpointer scope ->
  `CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED`; delete nothing.
- Destructive SQL/verification failure -> `CUTOVER_VERIFICATION_FAILED`; both
  runtime families remain blocked.
- Active-rollout legacy request, including `verified` user -> `CUTOVER_REQUIRED`
  unless a more specific blocked/failure code applies.

### 5. Good / Base / Bad Cases

- Good: a legacy user receives a server summary, explicitly confirms its exact
  nonce/hash, loses all legacy rows and owned checkpoint rows, retains identity
  preferences, and reaches only Tutor.
- Good: an already empty user receives a durable verified receipt without a
  destructive prompt, while a target-contaminated user remains blocked.
- Base: checkpoint tables are absent; inventory reports safe zero and creates
  no LangGraph table.
- Bad: treating `TUTOR_HARNESS_ENABLED` as cutover proof, allowing a verified
  user into dashboard/resume/onboarding, or using ordinary reset to erase a
  pending legacy profile before confirmation.

### 6. Tests Required

- `tests/test_harness_cutover.py`: exact confirmation/replay/stale/cross-user
  behavior, full legacy hierarchy deletion, retained fields, target blocking,
  injected rollback receipt, malformed/unscoped legacy denial, verified legacy
  denial, public checkpoint ownership, unrelated checkpoint survival, and
  unresolved namespace/`NULL` thread denial.
- `tests/test_local_user_data_boundary.py`: ordinary reset still preserves its
  legacy preference contract while the rollout-off baseline remains intact.
- `tests/test_worker_import.py`: every active-rollout receipt state blocks the
  legacy review worker; a disabled rollout performs no gate query.
- Run `bootstrap_database()` after schema edits, then focused pytest, `ruff
  check app tests`, and `python -m mypy app` through `uv`.

### 7. Wrong vs Correct

#### Wrong

```python
if settings.tutor_harness_enabled:
    return  # Treats the global rollout flag as user authorization.
reset_user_data(conn, user_id)  # Can erase a pending summary before confirmation.
```

This lets a flag or legacy reset bypass a server-authoritative clean-slate
confirmation and can reopen the wrong runtime.

#### Correct

```python
if get_settings().tutor_harness_enabled:
    gate_error = runtime_gate_error(user_id=user_id)
    if gate_error is not None:
        return stable_error_response(gate_error)

HarnessCutoverService(conn).assert_legacy_runtime_denied(user_id=user_id)
```

Tutor authorization and legacy denial are separate decisions. The destructive
scope remains owned by the confirmation service, never by a generic reset.

## Scenario: Tutor Integration Adapter Boundaries and Scoped Curation Verification

### 1. Scope / Trigger

- Trigger: extending the published Tutor Skill catalog, adding a target
  integration adapter, or testing curation against the shared PostgreSQL
  outbox/job queue.
- Scope: catalog-consuming Tutor tests, target adapters under
  `app/services/tutor/`, `TutorProactiveScheduler`,
  `PostgresTutorProactiveRepository`, and their PostgreSQL integration tests.
- This scenario prevents integration tests from encoding catalog order,
  misclassifying approved target adapters as core Harness code, or accidentally
  claiming/recovering another fixture user's curation work.

### 2. Signatures

- Exact Skill identity: `skill.reference.key`, for example
  `tutor.registry-grounding@1.0.0`; a list position is not an identity.
- Test/maintenance seed:
  `TutorProactiveScheduler.seed_curation_jobs(now=..., limit=..., user_id: str | None = None)`.
- Test/maintenance drain:
  `TutorProactiveScheduler.drain_curation(worker_id=..., now=..., limit=..., user_id: str | None = None)`.
- Store methods carry the same optional `user_id` through curation-job seed,
  pending-job claim, and expired-lease recovery.
- Approved database-backed target adapters are
  `interactive.py`, `public_api.py`, and `cutover.py`. Their explicit target
  database access does not authorize Graph, legacy router/tool/runner, legacy
  conversation, or subprocess imports.

### 3. Contracts

- Tests that need a particular Skill resolve it by the exact reviewed
  `reference.key`; they must not use `catalog.skills[0]` or any other positional
  selection. Adding an unrelated published Skill must not redirect a grounding
  or learner-state test to another capability policy.
- Core Harness/catalog code remains storage- and legacy-runtime-independent.
  The named target adapters may open target persistence only because their
  owning child integrates the verified Harness boundary; static checks still
  deny Graph/router/tool/runner dependency paths.
- `user_id=None` preserves the production worker's global queue behavior. An
  explicit `user_id` is only for deterministic fixture isolation or controlled
  maintenance and must scope every state-changing queue phase: seed, claim,
  and expired-lease recovery.
- A scoped operation must neither seed, claim, recover, retry, fail, nor append
  audit effects for another user's curation job. SQL scoping belongs in the
  repository query/update, not only in a caller-side assertion.
- Capability/public-selection tests read the current capability registry as the
  source of truth. Do not preserve an old product matrix merely because a
  grounding fixture happens to exist for that language.

### 4. Validation & Error Matrix

- Missing or unknown exact Skill key in a test fixture -> fail the fixture
  setup; do not silently bind the first catalog entry.
- A core Harness/catalog module imports target DB or a legacy Graph/router/tool/
  runner surface -> static boundary regression.
- A named target adapter imports a Graph/router/tool/runner or subprocess
  surface -> static boundary regression even when its DB import is allowed.
- Empty/invalid explicit `user_id` -> identifier validation failure before any
  queue query.
- Scoped seed/claim/recovery sees only another user's row -> safe no-work; the
  foreign row's state, lease, retry count, and audit history remain unchanged.
- Global worker call omits `user_id` -> normal global queue drain remains
  available; do not accidentally convert production curation into per-test
  routing.

### 5. Good / Base / Bad Cases

- Good: a grounding test locates
  `tutor.registry-grounding@1.0.0` by key, an approved public adapter uses its
  target repository without importing legacy runtime code, and a fixture drain
  handles only that fixture user's outbox/job rows.
- Base: the live worker calls the scheduler without `user_id`, so committed
  curation work from all eligible users remains globally claimable.
- Bad: using `catalog.skills[0]`, changing a static test to allow DB imports in
  every Harness module, or calling an unscoped drain in a shared-bootstrap test
  and asserting the first database row represents the test fixture.

### 6. Tests Required

- Catalog/policy/repository tests: add or reorder a non-target Skill and prove
  grounding/learner-state fixtures still select their exact `reference.key`.
- Static boundary tests: separately assert the core Harness deny-list and the
  explicit target-adapter allow-list; both classes must continue to reject
  Graph/router/tool/runner/subprocess dependencies.
- PostgreSQL curation tests: with two users, prove scoped seed does not create
  a foreign job, scoped drain does not claim a foreign pending job, and scoped
  expired-lease recovery does not mutate a foreign leased job.
- Worker test: retain one unscoped composition test so `user_id=None` continues
  to mean global production processing rather than fixture-only behavior.
- Run bootstrap-sensitive Tutor tests sequentially, then run `ruff check .`
  and `python -m mypy app` from `aearn/services/api` through `uv`.

### 7. Wrong vs Correct

#### Wrong

```python
# Catalog order changes when a new Skill is published; this can bind a
# grounding policy to an unrelated learner-state Skill.
skill = catalog.skills[0]
scheduler.drain_curation(worker_id="test-worker", now=now)
```

#### Correct

```python
skill = next(
    item
    for item in catalog.skills
    if item.reference.key == "tutor.registry-grounding@1.0.0"
)

# Test-only scope traverses seed, claim, and expired-lease recovery. The
# production worker intentionally omits user_id and remains global.
scheduler.seed_curation_jobs(now=now, user_id=fixture.user_id)
scheduler.drain_curation(worker_id="test-worker", now=now, user_id=fixture.user_id)
```

Exact semantic identity and repository-owned queue scope keep independent
integration tests from changing one another's behavior while retaining the
global production worker contract.

---

## Scenario: Committed Verified Tutor Fixture Cleanup

### 1. Scope / Trigger

- Trigger: a PostgreSQL Tutor fixture gains a new user-root receipt or other
  non-cascading foreign-key row, and a test deliberately commits the fixture so
  independent connections can observe it.
- Scope: `tests/conftest.py::tutor_persistence`, cross-connection execution/
  scheduler tests, test-only cleanup helpers, `harness_cutovers`,
  `tutor_execution_*`, and singleton test health rows.
- This scenario prevents a new verified-cutover receipt from turning a normally
  rollback-scoped test into leaked state after a cross-connection assertion.

### 2. Signatures

- Verified fixture receipt:
  `harness_cutovers(user_id, cutover_version, state='verified')`.
- Cross-connection test pattern:
  `fixture.connection.commit()` followed by independent `connect()` calls.
- Exact cleanup helper:
  `_cleanup_committed_fixture(user_id, conversation_id, run_id, exercise_id)`.
- Root deletion boundary: `DELETE FROM users WHERE id = %s` is valid only after
  every test-owned child row and the matching `harness_cutovers` receipt are
  gone.

### 3. Contracts

- `tutor_persistence` models a user that already completed clean-slate cutover
  before any Tutor row exists. The verified receipt is part of the fixture
  contract, not optional test decoration.
- Normal fixture teardown may use rollback. A test that commits for a real
  `FOR UPDATE SKIP LOCKED` or independent-connection assertion owns exact
  cleanup in a separate transaction.
- Cleanup order is child-to-root: execution attempts/jobs/intents/effects,
  run-scoped Tutor rows, conversation rows, test-only executor health, legacy
  exercise hierarchy, learner profile/idempotency rows, `harness_cutovers`, then
  the fixture user. Do not use broad `TRUNCATE`, another user's rows, or a
  global queue reset.
- A cleanup helper that removes a user must delete the receipt for that exact
  `(user_id, CUTOVER_VERSION)` first. The helper must leave the shared
  `test-executor` health identity absent, otherwise the next fixture can collide
  on its primary key.

### 4. Validation & Error Matrix

- Deleting the fixture user while its `harness_cutovers` row exists ->
  PostgreSQL `ForeignKeyViolation`; the cleanup transaction rolls back and all
  rows remain leaked.
- A rolled-back cleanup leaves `tutor_executor_health(executor_id='test-executor')`
  -> the next fixture's health seed fails with `UniqueViolation`; fix cleanup
  order rather than weakening the health primary key or swallowing the error.
- A cross-connection test commits but has no exact cleanup helper -> full-suite
  order dependence; add the helper and rerun the complete serial API suite.
- Cleanup query missing its fixture user/run/conversation predicate -> test
  safety failure; it must not delete a foreign fixture's rows.

### 5. Good / Base / Bad Cases

- Good: a `SKIP LOCKED` test commits its verified fixture, contender assertions
  finish, cleanup deletes its receipt before the user, and the next executor
  test seeds `test-executor` without a collision.
- Base: a normal fixture never commits and `finally: conn.rollback()` removes
  the receipt with the rest of its transaction.
- Bad: adding a verified receipt in `conftest.py` but leaving a user-delete
  cleanup unchanged, calling `TRUNCATE tutor_executor_health`, or catching the
  foreign-key error and continuing to the next test.

### 6. Tests Required

- Run `tests/test_tutor_executor_job_store.py` serially; its independent
  `FOR UPDATE SKIP LOCKED` test must complete cleanup and the following
  reserved-launch recovery test must seed health successfully.
- Run the full API suite serially after fixture schema/root changes. A focused
  green test alone is insufficient because leaked committed rows appear in the
  next test, not necessarily the current one.
- Add/retain a fixture test that inserts the verified receipt before Tutor rows
  so routes/scheduler tests retain the real admission topology.

### 7. Wrong vs Correct

#### Wrong

```python
# Fails after tutor_persistence starts inserting harness_cutovers.
conn.execute("DELETE FROM idempotency_records WHERE user_id = %s", (user_id,))
conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
```

#### Correct

```python
# Child rows are already removed above. Delete the exact verified receipt before
# removing the root user, then clear only the test-owned singleton health row.
conn.execute("DELETE FROM tutor_executor_health WHERE executor_id = 'test-executor'")
conn.execute("DELETE FROM harness_cutovers WHERE user_id = %s", (user_id,))
conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
```

A committed fixture must be cleaned in the same foreign-key topology that
bootstrap created; keeping the receipt is correct for runtime admission and
incorrect only after the fixture's test-owned user is being destroyed.

---

## Scenario: Tutor Provider Attempt Usage 与缓存计量

### 1. Scope / Trigger

- Trigger：修改 `OpenAICompatibleClient` usage 解析、Tutor primary provider retry、
  `TutorProviderResult`、run-loop provider lifecycle 或 provider attempt 数据库表。
- Scope：`services/llm/contracts.py`、`llm_client.py`、
  `services/tutor/{provider_gateway,run_loop,persistence,ports}.py`、Harness contracts、
  `tutor_provider_attempt_receipts` 以及 focused provider/PostgreSQL tests。
- 该 contract 只记录安全计量事实；不选择预算、价格、provider、model 或 protocol，
  也不增加 learner-visible API/SSE 字段。

### 2. Signatures

- LLM contract：`LLMUsage(input_tokens, cached_input_tokens, output_tokens, total_tokens, reasoning_tokens)`。
- LLM response：`LLMJsonResponse(content, model, usage: LLMUsage | None = None)`。
- Gateway receipt：`TutorProviderAttemptReceipt(attempt_index, outcome, provider_type, protocol, usage, model, diagnostic_code)`。
- Run result：`TutorProviderResult(..., attempts: tuple[TutorProviderAttemptReceipt, ...])`。
- Lifecycle write：`persist_provider_attempts(snapshot, decision_iteration, attempts, created_at)`。
- DB identity：`UNIQUE (run_id, input_revision, decision_iteration, attempt_index)`。

### 3. Contracts

- Responses 使用 `input_tokens/output_tokens/total_tokens` 与 details 中的 cached/reasoning；
  Chat Completions 使用 `prompt_tokens/completion_tokens/total_tokens` 与 prompt/completion details。
- 所有 provider reported 数值可缺失但不得为负；`cached_input_tokens` 存在时必须有
  `input_tokens` 且不大于它。
- `input_tokens` 已包含缓存读取，规范化值固定为
  `uncached_input_tokens = input_tokens - cached_input_tokens`；不得再把 cached 加回 input。
- provider reported total 和 calculated `input_tokens + output_tokens` 是两个独立事实，
  不因不一致而改写 provider 数字。
- 一个 run-loop decision 可能产生首次请求和一次 same-provider repair 两条 receipt；
  `model_call_count` 仍只增加一次 decision boundary。
- envelope 已返回但 visible content/JSON/decision/safety 校验失败时保留 usage；
  transport 在 envelope 前失败时只记录安全 outcome/diagnostic，不伪造 token。
- receipt 在 provider 返回后、cancellation/supersede 的业务写门禁前持久化；stale run
  可保留已发生的 usage，但不能写 message、title、capability 或 effect。
- receipt 只含 scope、受限标识、outcome/diagnostic、token 和 timestamp；不含 prompt、
  history、raw response、reasoning 文本、URL/header/body 或 credential，也不进入 public history/SSE/export。

### 4. Validation & Error Matrix

- token 为负、布尔值，或 cached 大于 input -> `LLMUsage` 拒绝；provider envelope
  解析器将 malformed usage 降级为 unavailable，不使 Tutor 主流程失败。
- usage 字段缺失 -> `usage=None` / SQL `NULL` + `usage_available=false`，不是零值。
- accepted attempt 带 diagnostic，或 rejected/transport attempt 缺 diagnostic -> contract 拒绝。
- transport attempt 带 usage -> contract/DB CHECK 拒绝。
- exact identity + 完全相同安全事实 -> 幂等重放；exact identity + 不同事实 ->
  `TutorIdempotencyConflict`，lifecycle 映射为内部 `TutorLifecycleConflict`。
- user/run/conversation 不一致 -> repository not-found/conflict 或 PostgreSQL composite FK violation。
- receipt UPDATE/DELETE -> PostgreSQL `23514` append-only violation。
- persistence 冲突 -> 不公开半完成 token 计量，不绕过既有 terminal/safety gate。

### 5. Good/Base/Bad Cases

- Good：`175420 input / 170368 cached / 2223 output` 得到 `5052 uncached`，
  calculated total 为 `177643`，且 repair 的两次实际请求分别可审计。
- Good：首次响应有 usage 但 JSON 无效，receipt 记为 `repairable_rejected`；第二次
  accepted receipt 独立保存，run `model_call_count` 仍只增加一次。
- Base：compatible provider 不返回 usage；Tutor decision 正常继续，receipt 明确 unavailable。
- Bad：计算 `input + cached` 得到 `345788`，把缺失字段写成 0，只保留 repair 的最终
  success，或把 raw provider body/validation detail 塞进 receipt/trace。

### 6. Tests Required

- `tests/test_tutor_provider_gateway.py`：Responses stream、Chat Completions、cached/no-cache、
  reasoning、partial/malformed/missing usage、invalid JSON repair、transport 与 primary-only 回归。
- `tests/test_tutor_run_loop.py`：attempt receipts 在 stale-result 抑制前持久化，同时
  public message/title/capability/effect 仍被 cancellation/supersede gate 阻止。
- `tests/test_tutor_run_repository.py`：两个 attempt、missing usage、exact replay、冲突重放、
  跨 user/conversation、derived token CHECK、transport CHECK 和 UPDATE/DELETE trigger。
- `tests/test_db_bootstrap.py`：bootstrap 两次并断言表、索引、约束与 immutable trigger。
- 最终串行运行 focused pytest、完整 pytest、`ruff check app tests`、
  `python -m mypy app --no-incremental`、`uv lock --check`、Trellis validate 和 `git diff --check`。

### 7. Wrong vs Correct

#### Wrong

```python
# input_tokens 已含 cached；这里会重复计算物理输入。
physical_input = usage.input_tokens + usage.cached_input_tokens
persist(input_tokens=usage.input_tokens or 0, cached_input_tokens=usage.cached_input_tokens or 0)
```

#### Correct

```python
uncached_input = (
    usage.input_tokens - (usage.cached_input_tokens or 0)
    if usage.input_tokens is not None
    else None
)
persist(
    input_tokens=usage.input_tokens,
    cached_input_tokens=usage.cached_input_tokens,
    uncached_input_tokens=uncached_input,
    usage_available=usage.usage_available,
)
```

正确实现保留 missing 与 zero 的区别，并让数据库约束重新验证所有派生计量事实。
