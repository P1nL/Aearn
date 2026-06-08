# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

The formal MVP runtime lives under `aearn/`, not under the historical `01_` through `07_` tutorial directories. Local backend prerequisites use Docker Compose from `aearn/infra/docker-compose.yml`.

---

## Query Patterns

- First implement database behavior from `docs/architecture/database-schema.md`; do not infer table names or enums from historical tutorial code.
- Use PostgreSQL as the source of truth for persisted API state.
- Use explicit SQL or migration-defined schema contracts. Avoid ORM-only behavior that is not reflected in migration files.
- Use UUID primary keys and stable `slug` fields only where the schema document defines them.
- Use `timestamptz` for persisted timestamps and expose API timestamps as ISO 8601 UTC strings.
- When implementing resume / inactivity heuristics, do not treat trigger-managed `updated_at` columns as user activity. Use domain timestamps such as `learning_sessions.started_at`, `learning_sessions.ended_at`, and `attempts.created_at`.
- Use cursor pagination for list APIs where the API contract requires `page_info`.

---

## Migrations

- Milestone 1 must establish a repeatable migration baseline before features write business data.
- Migration order must follow `docs/plans/learning-agent-implementation-plan.md`: base tables first, then learning/exercise core tables, then review and notes tables.
- Use `CREATE EXTENSION IF NOT EXISTS pgcrypto;` before relying on `gen_random_uuid()`.
- Add `set_updated_at()` triggers for mutable business tables.
- Do not create PostgreSQL enum types for MVP enums. The schema currently specifies `text CHECK (...)` to keep enum changes migration-friendly.
- Append-only tables such as `attempts` and `review_logs` should be corrected by new records or explicit status fields, not by soft deletion.

---

## Naming Conventions

- Table names are plural `snake_case`: `learning_plans`, `knowledge_points`, `review_states`.
- Columns are `snake_case` and should match API fields unless the API contract explicitly uses a derived field.
- JSONB columns use a `_json` suffix where the schema uses it, such as `skill_tags_json` and `supported_exercise_types_json`.
- Index names should be descriptive and stable: `idx_<table>_<columns>`.
- Unique constraints for active records should include `WHERE deleted_at IS NULL` or `WHERE archived_at IS NULL` when the schema requires soft-delete or archive semantics.
- Idempotency storage must preserve both `Idempotency-Key` and request body identity when implemented.

---

## Scenario: Review Warmup, Candidate Pool, Batch, and Patch Review Contracts

### 1. Scope / Trigger

- Trigger: any review-page backend, worker, API, or migration change that touches warmup, review candidate pools, review batch state, rolling exercise selection, finalization, or `review_ai_patch`.
- Scope: `POST /api/reviews/start`, `POST /api/reviews/{session_id}/warmup-result`, `POST /api/reviews/{session_id}/exercise-result`, `review_seed_banks`, `learning_sessions.review_stage*`, materialized review `exercises`, `attempts`, `review_states`, `review_logs`, and long-term learner profile merges.

### 2. Signatures

- DB: `review_seed_banks(user_id, plan_id, knowledge_point_id, generator_version, status, seed_count, seeds_json, quality_report_json, failure_code, failure_message, generated_at)`.
- DB: `review_seed_banks.generator_version=review_candidate_pool_v1` stores a validated baseline candidate pool in `seeds_json`; table/column names remain `review_seed_banks` / `seeds_json` for compatibility.
- DB: `learning_sessions.review_stage` in `warmup | warmup_repair | variant_practice | exercise | exercise_feedback | final_summary | submitted`; `variant_practice` is legacy read compatibility.
- DB: `learning_sessions.review_stage_state_json.schema_version=review_batch_v1` stores `batch`, `warmup`, `session_diagnosis`, `pool`, `exercise_plan`, `variant`, and `finalization`.
- API: `POST /api/reviews/start` returns `warmup`, `review_stage`, `review_stage_state`, `current_node`, `selected_seed_id`, `review_exercise`, and optional `seed_bank`.
- API: `POST /api/reviews/{session_id}/warmup-result` accepts `{ action: "answer", answer: string }` or `{ action: "skip" }`.
- API: `POST /api/reviews/{session_id}/exercise-result` accepts normal code payloads or `review_ai_patch_answer`, and returns `current_node` for both intermediate exercise and final summary responses.

### 3. Contracts

- `reviews/start` must ensure a ready candidate pool before selecting a seed/candidate. Async generation and sync rescue must share generator, validation, safety checks, and persistence helpers.
- Sync rescue must persist the full ready candidate pool before selecting a seed/candidate. If rescue fails, persist a failed bank row and return `REVIEW_SEED_BANK_GENERATION_FAILED`.
- Candidate pool entries must carry `capability`, `focus_tags`, `recommended_for`, `avoid_if`, `selection_reason`, and `is_core`; backend graph selection consumes this metadata and must not depend on frontend scoring.
- Warmup outcomes are review-session state only. They never create `Attempt`, never write `review_logs`, and never update `ReviewState`.
- Formal review submit creates or replays exactly one `Attempt(review_submit)` and updates only `learning_sessions.review_stage_state_json` until the batch is finalized.
- Intermediate review submits must not update `ReviewState`, `review_logs`, `KnowledgePoint`, FSRS, or long-term learner profile.
- Final review submit computes one backend-owned aggregate `final_fsrs_rating` from the whole batch, then writes exactly one `ReviewState` update and one `ReviewLog`. Because `review_logs.attempt_id` is `NOT NULL`, use the final representative `review_submit` attempt.
- If baseline candidates cannot cover the remaining weakness or minimum coverage, keep the session `active`, mark `pool.adaptive_supplement_status=needed`, and return `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED`; do not synthesize a fallback question.
- `review_ai_patch` is a first-class `Exercise.exercise_type`. It must require `verdict`, `evidence`, `knowledge_point_risk`, and `next_action`.
- `review_ai_patch` scoring must write `verdict_correctness`, `evidence_grounding`, `knowledge_point_alignment`, and `actionability` into `Attempt.code_completion_result.score_breakdown`.

### 4. Validation & Error Matrix

- Missing user, knowledge point, session, or exercise -> map to documented 404 error codes.
- Not due -> `REVIEW_NOT_DUE` with 409.
- Candidate pool invalid, empty, missing required type/capability coverage, missing `review_ai_patch`, duplicate candidates, hidden tests, solution references, raw provider errors, or secrets -> `REVIEW_SEED_BANK_GENERATION_FAILED`.
- Warmup `action=answer` without non-empty `answer` -> `VALIDATION_ERROR`.
- `review_ai_patch` exercise without `review_ai_patch_answer` -> `VALIDATION_ERROR`.
- Submitted exercise not matching the active `current_node.exercise.id` -> `SESSION_CONFLICT`.
- Correct `review_ai_patch` verdict with weak evidence such as only `tests passed` -> single-exercise `fsrs_rating=Hard`, never `Easy`.
- Core capability failure -> final batch rating cannot be `Easy`.
- Repeated skips, repeated core failures, or unresolved high-risk weakness -> final batch rating should be `Hard` or `Again`.
- No valid baseline candidate and batch cannot finalize -> `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED`, recoverable.

### 5. Good/Base/Bad Cases

- Good: ready candidate pool exists, `reviews/start` replays the same session state, warmup answer moves to `exercise`, intermediate `exercise-result` writes one `Attempt(review_submit)` and next `current_node` but no scheduler state, and final submit writes exactly one `review_log`.
- Base: candidate pool missing, sync rescue generates and persists a full pool, then selects a candidate and returns warmup plus current exercise node.
- Bad: rescue or coverage miss fabricates a fallback question, warmup or intermediate exercise updates `ReviewState`, or frontend/model-provided final FSRS is trusted.

### 6. Tests Required

- API test: `reviews/start` returns warmup, selected seed/candidate, persisted exercise, `current_node`, `review_batch_v1`, and replay uses the same state.
- API test: rescue generation failure returns `REVIEW_SEED_BANK_GENERATION_FAILED` and persists `review_seed_banks.status=failed`.
- API test: warmup `skip`, wrong answer, and repair-limit paths write no `Attempt`, no `review_logs`, and no `ReviewState` changes.
- API test: intermediate review submit writes an `Attempt(review_submit)`, updates `exercise_plan`, returns next `current_node`, and leaves `ReviewState`, `review_logs`, `KnowledgePoint`, and long-term profile unchanged.
- API test: final review submit writes `ReviewState`, `review_logs`, `KnowledgePoint`, and long-term profile exactly once.
- API test: intermediate and final idempotency replay do not duplicate attempts, exercises, scheduler writes, or review logs.
- API test: no valid baseline candidate returns `REVIEW_ADAPTIVE_SUPPLEMENT_FAILED`, preserves the active session, and does not show fallback exercise.
- Unit/API tests: final rating aggregation covers stable `Easy`, non-core miss still `Good`, core failure not `Easy`, and repeated skip/high-risk `Hard`/`Again`.
- API test: `review_ai_patch` weak evidence maps to `Hard` and writes `review_ai_patch_result` under `Attempt.code_completion_result`.

### 7. Wrong vs Correct

#### Wrong

```python
# Fallback question violates the product contract and hides candidate-pool failure.
if seed_bank_failed or coverage_miss:
    exercise = build_simple_question_from_title(knowledge_point["title"])
    return {"review_exercise": exercise}
```

#### Correct

```python
if seed_bank_failed:
    persist_failed_seed_bank(...)
    raise ReviewSeedBankGenerationError(
        "REVIEW_SEED_BANK_GENERATION_FAILED",
        "review candidate pool validation failed",
    )
if coverage_miss:
    mark_adaptive_supplement_needed(session_state)
    raise ReviewAdaptiveSupplementRequired("baseline pool cannot cover remaining weakness")
```

---

## Scenario: Local PostgreSQL and Redis Prerequisite Services

### 1. Scope / Trigger

- Trigger: any backend, worker, checkpoint, store, session, queue, or cache work for Aearn.
- Scope: local development only; do not treat the historical tutorial project compose files as the formal runtime.

### 2. Signatures

- Compose command: `docker compose -f .\aearn\infra\docker-compose.yml up -d`
- PostgreSQL health command: `docker exec aearn_postgres pg_isready -U postgres -d postgres`
- Redis health command: `docker exec aearn_redis redis-cli ping`
- Python PostgreSQL smoke check: `psycopg.connect("postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable", connect_timeout=10)`
- Python Redis smoke check: `redis.from_url("redis://127.0.0.1:6379/0").ping()`

### 3. Contracts

- `DATABASE_URL`: `postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable`
- `REDIS_URL`: `redis://127.0.0.1:6379/0`
- `CELERY_BROKER_URL`: `redis://127.0.0.1:6379/0`
- `CELERY_RESULT_BACKEND`: `redis://127.0.0.1:6379/1`
- PostgreSQL image: `postgres:15`
- Redis image: `redis:latest`
- Container names: `aearn_postgres`, `aearn_redis`

### 4. Validation & Error Matrix

- Docker daemon not running -> start Docker Desktop before running Compose.
- `postgres:15` image missing or pull is slow -> run `docker pull postgres:15` separately, then retry Compose.
- Python PostgreSQL `localhost` connection hangs on Windows -> use `127.0.0.1` in env defaults and smoke checks.
- Port `5432` or `6379` already bound -> inspect `docker ps -a --format "table {{.Names}}\t{{.Ports}}"` before changing ports.

### 5. Good/Base/Bad Cases

- Good: both containers are `healthy`, `pg_isready` accepts connections, Redis returns `PONG`, and Python clients connect through `127.0.0.1`.
- Base: Compose starts but health is still `starting`; wait and rerun `docker compose ps`.
- Bad: reusing `06_` or `07_` compose files as the formal runtime, or committing a real `.env` with secrets.

### 6. Tests Required

- Run `docker compose -f .\aearn\infra\docker-compose.yml config --quiet`.
- Run container health commands for PostgreSQL and Redis.
- Run Python client smoke checks for PostgreSQL and Redis from `services/api` via `uv`.
- Verify `.env.example` contains only local defaults and no real LLM keys.

### 7. Wrong vs Correct

#### Wrong

```powershell
uv --directory .\aearn\services\api run python -c "import psycopg; psycopg.connect('postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable')"
```

#### Correct

```powershell
uv --directory .\aearn\services\api run python -c "import psycopg; conn = psycopg.connect('postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable', connect_timeout=10); print(conn.execute('select 1').fetchone()[0]); conn.close()"
```
