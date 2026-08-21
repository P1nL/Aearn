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
- `tutor_provider_attempt_receipts` 是每个实际 provider attempt 的 append-only 事实表；使用 `(run_id,input_revision,decision_iteration,attempt_index)` 幂等 identity、run/user/conversation 复合外键和 UPDATE/DELETE 拒绝触发器。相同 identity 只允许完全相同的安全事实重放。
- provider `input_tokens` 已包含 `cached_input_tokens`；数据库持久化 `uncached_input_tokens = input_tokens - cached_input_tokens`，并把 provider reported total 与 calculated input-plus-output 分列。usage 缺失必须使用 `NULL` + `usage_available=false`，不得写零值占位。

---

## Scenario: Tutor 权威规划事实与 question lineage

### 1. Scope / Trigger

- Trigger: 修改 planning session 输入、`tutor_planning_intake_facts`、`tutor_planning_question_events`、计划草案 facts fingerprint、Tutor required-facts context、planning decision gate、local export/reset 或 cutover inventory。
- 该场景是 API、PostgreSQL、Harness、eval 和治理投影的跨层契约；实现时以 `docs/architecture/api-contract.md`、`docs/architecture/database-schema.md` 与 `docs/architecture/tutor-harness-runtime.md` 为 source of truth。

### 2. Signatures

- Tutor input additive fields: `planning_facts: dict[str, object] | None`、`reopen_fact_fields: list[str]`。
- Stable fields: `language_id | goal_text | target_level | weekly_minutes | experience_level | teaching_preferences | pace_constraints`。
- Fact identity: `(session_id, field_key, revision)`；source evidence: `(source_run_id, source_message_id, source_input_revision)`。
- Question lineage: `question_key=field_key`、`previous_event_id -> tutor_planning_question_events.id`。
- Projector: `build_authoritative_context_snapshot(run, input_revision, planning_session_id, facts, question_states, confirmed_question_reasked_count)`。

### 3. Contracts

- 只有服务端 deterministic normalization 或显式 typed input/confirmation 能写 planning fact；模型推断不能直接成为 confirmed authority。
- correction 追加一条带 `supersedes_fact_id` 的 successor。current confirmed fact 是没有 successor 的 confirmed leaf；不得 UPDATE 旧事实。
- question transition 追加 event。current question state 从没有 successor 的 leaf 沿 `previous_event_id` lineage 解析；`reasked_blocked` 只保留审计，公开 current state 回退到其 predecessor。
- PostgreSQL `now()` 在一个事务内稳定，不能用 `created_at`、UUID 大小或二者组合作为同事务事件先后 authority。`previous_event_id` 必须有唯一 successor 约束，防止 lineage 分叉。
- confirmed facts 进入 `required_facts`，在 optional history/summary/memory 前完整选中；无法完整表示时 fail closed。
- unresolved/reopened answer 的 source message 在没有 replacement fact/summary 时必须进入 compaction protection；export 省略 value/event hash 和 gate reason。
- plan draft 保存生成时 facts fingerprint/revision；confirm 必须与 current facts 相同。

### 4. Validation & Error Matrix

| 条件 | 结果 |
| --- | --- |
| `planning_facts` 含未知 field、重复/未知 reopen field 或 request shape 非法 | FastAPI/Pydantic `422` |
| field value 不能 normalize 或超出范围 | `400 VALIDATION_ERROR`，事务不留下半完成 fact |
| planning `wait_for_input` 缺少/使用未知 `question_key` | decision gate deny：`planning_question_key_required` / `planning_question_key_invalid` |
| provider 再问已 confirmed 且未 reopen 的 field | decision gate deny：`confirmed_question_reasked`，追加 `reasked_blocked` event |
| draft facts fingerprint/revision 与 current projection 不同 | `409 LEARNING_PLAN_DRAFT_STALE` |
| cross-user/session/conversation/run/message/input evidence 不匹配 | PostgreSQL composite FK violation |
| UPDATE/普通 DELETE planning fact 或 question event | PostgreSQL append-only trigger 拒绝 |
| required facts 超 item/token 表示边界 | `TUTOR_REQUIRED_FACTS_UNREPRESENTABLE`，provider 不得被调用 |

### 5. Good/Base/Bad Cases

- Good: learner 提交“每周 30 小时”并附 typed profile；系统保存 `weekly_minutes=1800`，超过四条后续消息后仍从 facts projector 注入 provider context。
- Base: 旧 collecting session 没有 facts 时返回空 required section；从后续有证据的新输入开始懒建立，不扫描历史自动回填。
- Good correction: learner 显式 reopen 并提交 `weekly_minutes=600`；新 row 指向 1800 row，question current state 回到 confirmed，旧 draft 变 stale。
- Bad: `ORDER BY created_at DESC, id DESC LIMIT 1` 猜 question current state；同一事务中的 reopen/supersede/confirmed 时间相同，会产生非确定结果。
- Bad: 仅扩大 recent-message limit，或让 summary/模型正文覆盖 typed fact。

### 6. Tests Required

- PostgreSQL bootstrap twice，并断言两张表、复合 FK、status CHECK、append-only trigger 与 `uq_tutor_planning_question_events_previous` 存在。
- fact idempotent replay、correction lineage、same-transaction question state、cross-user evidence、UPDATE rejection、child-first reset/delete。
- 超过四条后续消息的 `weekly_minutes=1800` fixture：required facts 完整、source semantic pinning、snapshot hash replay 稳定。
- unresolved answer fixture：source message 位于 `protected_message_ids`，`summary_blocked_by_unprojected_fact=1`。
- confirmed reask fixture：run 终止为 safe policy denial，checkpoint 保存 reask counter，公共投影不含 diagnostic/hash。
- draft correction fixture：即使 expected session version 最新，旧 facts fingerprint 仍返回 `LEARNING_PLAN_DRAFT_STALE`。

### 7. Wrong vs Correct

#### Wrong

```sql
SELECT field_key, status
FROM tutor_planning_question_events
WHERE session_id = $1
ORDER BY created_at DESC, id DESC
LIMIT 1;
```

#### Correct

```sql
WITH RECURSIVE question_chain AS (
  SELECT events.id, events.field_key, events.status, events.previous_event_id, 0 AS ancestor_depth
  FROM tutor_planning_question_events AS events
  WHERE events.session_id = $1
    AND NOT EXISTS (
      SELECT 1 FROM tutor_planning_question_events AS successor
      WHERE successor.previous_event_id = events.id
    )
  UNION ALL
  SELECT predecessor.id, predecessor.field_key, predecessor.status,
         predecessor.previous_event_id, chain.ancestor_depth + 1
  FROM tutor_planning_question_events AS predecessor
  JOIN question_chain AS chain ON chain.previous_event_id = predecessor.id
)
SELECT DISTINCT ON (field_key) field_key, status
FROM question_chain
WHERE status <> 'reasked_blocked'
ORDER BY field_key, ancestor_depth;
```

---

## Naming Conventions

- Table names are plural `snake_case`: `learning_plans`, `knowledge_points`, `review_states`.
- Columns are `snake_case` and should match API fields unless the API contract explicitly uses a derived field.
- JSONB columns use a `_json` suffix where the schema uses it, such as `skill_tags_json` and `supported_exercise_types_json`.
- Index names should be descriptive and stable: `idx_<table>_<columns>`.
- Unique constraints for active records should include `WHERE deleted_at IS NULL` or `WHERE archived_at IS NULL` when the schema requires soft-delete or archive semantics.
- Idempotency storage must preserve both `Idempotency-Key` and request body identity when implemented.
- For a new user-scoped mutation whose idempotency row may not exist yet, a prior `SELECT ... FOR UPDATE` does not serialize concurrent first writes. Acquire a transaction-scoped advisory lock (or an equivalent database-owned reservation) from the full `(user_id, operation, idempotency_key)` identity before the replay lookup and business write.
- Immutable LearningTrack revisions, route structure, mastery evidence, migration receipts, and run scope snapshots reject ordinary physical deletes as well as updates. Confirmed local reset/delete may use a transaction-local purge capability only after active runs are safely terminalized and only for the exact user-owned child-to-root deletion path.

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

---

## Scenario: Tutor Container Executor Scope and Lifecycle Integrity

### 1. Scope / Trigger

- Trigger: changing `tutor_execution_*` schema, `ExecutionIntentRepository`, `PostgresExecutionJobStore`, executor health/claim logic, or the in-transaction `runner.execute` submission seam.
- Scope: feature-disabled Tutor execution only. The API/Harness transaction persists an intent/job; only `aearn/services/executor/` may claim it after commit. No public route, SSE, Desktop, legacy runner, host subprocess fallback, or generic worker queue is authorized by this scenario.

### 2. Signatures

- DB parent evidence: `tutor_run_input_events(run_id, message_id, input_revision)`, `tutor_effects(id, run_id, effect_id)`, and `tutor_execution_intents(id, run_id, user_id, conversation_id)`.
- Intent contract: `tutor_execution_intents(run_id, source_message_id, input_revision, consumed_by_effect_id)`.
- Job contract: `tutor_execution_jobs(intent_id, effect_record_id, effect_key, run_id, user_id, conversation_id, state, lease_*, launch_*, result_*, terminal_at)`.
- Lifecycle: `pending -> claimed -> launch_reserved -> running -> terminal`, where terminal is `completed | timed_out | cancelled | unavailable | launch_uncertain | failed`. The only terminal-to-terminal convergence is `* -> failed` when cleanup fails.
- Claim command: `PostgresExecutionJobStore.claim_next(executor_id, now, lease_seconds)` uses `FOR UPDATE SKIP LOCKED`; `claim_reserved_for_recovery(...)` may adopt a reserved launch but may never allocate a new launch token.

### 3. Contracts

- Bootstrap remains repeatable and additive. Composite parent keys and child foreign keys must keep an intent, accepted source input, effect, job, run, user, and conversation in the same scope. Add new legacy-safe FK/CHECK constraints with guarded DDL; `NOT VALID` is permitted only to preserve existing rows, never to disable enforcement for new writes.
- An execution intent's `(run_id, source_message_id, input_revision)` must reference an actually accepted Tutor input. Its consumed effect must belong to the same run.
- A job's `(intent_id, run_id, user_id, conversation_id)` must match its intent, and `(effect_record_id, run_id, effect_key)` must match its effect. Scalar UUID foreign keys alone are not sufficient scope protection.
- A terminal job must have `terminal_at`, `result_json`, and `result_hash`; a non-terminal job must have none of them. `claimed` requires a non-empty owner, positive generation, and expiry. `launch_reserved` and `running` require one positive launch generation, token, reservation timestamp, and lease facts.
- `launch_token`, `launch_generation`, and `launch_reserved_at` become immutable once allocated. A terminal job may never return to a non-terminal state. These cross-row rules belong in a narrow `BEFORE INSERT OR UPDATE` trigger, not only in Python code.
- Raw source, hidden tests, image references, container identifiers, commands, mounts, paths, and Docker errors never enter these tables' learner-safe result/projection fields. Jobs persist opaque references, hashes, safe codes, counters, and bounded results only.

### 4. Validation & Error Matrix

- An intent whose source revision/message was not accepted for its run -> PostgreSQL foreign-key violation; no job is created.
- A consumed effect from another run, or a job whose effect/intent scope differs from its run/user/conversation -> PostgreSQL foreign-key violation.
- Terminal state without result/timestamp, a claimed row without a lease shape, or reserved/running state without launch facts -> PostgreSQL check violation.
- Replacing/clearing a reserved launch token or changing terminal back to pending/claimed/running -> lifecycle-trigger check violation.
- Cleanup after a terminal launch result -> may converge to `failed` with a new safe failure result and `cleanup_state=failed`; it must not resurrect work.
- Missing immutable lock, stale/incompatible health, disabled `TUTOR_EXECUTOR_ENABLED`, cancellation, or expired old lease -> safe unavailable/cancelled/stale behavior; never Docker launch or legacy runner fallback.

### 5. Good/Base/Bad Cases

- Good: one effect transaction commits one scoped `pending` job; two executor connections contend, the second skips the held row, and an expired **unreserved** claim can be reclaimed by the next generation.
- Good: a recovery executor adopts the same `launch_reserved` token and generation; it searches/adopts the matching container or records `launch_uncertain`, never reserves another token.
- Base: no reviewed digest lock exists, so the executor writes only unavailable health and no job reaches Docker.
- Bad: referencing a message from a different input revision, updating only a job UUID while changing its run, storing a terminal result on a non-terminal job, clearing the launch token for retry, or returning a terminal job to `pending`.

### 6. Tests Required

- Run `bootstrap_database()` twice and assert the composite keys, scoped foreign keys, lifecycle checks, and lifecycle trigger exist.
- Use real PostgreSQL mutation tests to prove cross-run input/effect/job updates are rejected, terminal result shape is enforced, launch token replacement is rejected, terminal-to-non-terminal is rejected, and terminal-to-`failed` cleanup convergence is allowed.
- Use two independent `psycopg` connections: lock a pending job in connection A, assert connection B's `claim_next()` skips it, then release A and assert B claims exactly once.
- Cover expired pre-launch lease reclaim, old-lease reserve rejection, reserved-launch recovery with the original token, and cancellation before reservation producing terminal `cancelled` without a token.
- Keep contract/redaction tests proving that API/Harness/worker/legacy runners have no Docker client or fallback and that safe results omit raw source, hidden tests, image/container/path/command details.

### 7. Wrong vs Correct

#### Wrong

```sql
-- A scalar UUID link can point at an effect from another Tutor run.
UPDATE tutor_execution_jobs
SET effect_record_id = :other_effect_id
WHERE id = :job_id;
```

#### Correct

```sql
-- The composite FK makes the effect record, run, and effect key one scope.
ALTER TABLE tutor_execution_jobs
  ADD CONSTRAINT fk_tutor_execution_job_effect_scope
  FOREIGN KEY (effect_record_id, run_id, effect_key)
  REFERENCES tutor_effects(id, run_id, effect_id)
  ON DELETE RESTRICT NOT VALID;

-- A trigger then preserves the one-time external-effect reservation.
IF OLD.launch_token IS NOT NULL
   AND NEW.launch_token IS DISTINCT FROM OLD.launch_token THEN
  RAISE EXCEPTION USING ERRCODE = '23514';
END IF;
```

## Scenario: Immutable LessonDocument Authority

### 1. Scope / Trigger

Apply this contract whenever a change touches `tutor_lesson_*`, grounding source version/hash fields, Lesson assignment migration, authoring lifecycle persistence, local export/reset/delete, or cutover inventory.

### 2. Signatures

The authority consists of these additive PostgreSQL roots and children:

```text
tutor_lesson_documents
  -> tutor_lesson_source_snapshots
  -> tutor_lesson_block_citations
  -> tutor_lesson_gate_slots

tutor_lesson_assignments -> tutor_lesson_documents
tutor_lesson_authoring_runs -> tutor_lesson_authoring_attempt_receipts
```

Repository mutations use exact scope and expected versions:

```python
start_assignment(
    *, user_id: str, track_id: str, knowledge_key: str,
    assignment_id: str, expected_assignment_version: int,
    expected_progress_version: int, now: datetime,
) -> Mapping[str, object]

activate_proposed_assignment(
    *, user_id: str, track_id: str, knowledge_key: str,
    assignment_id: str, expected_assignment_version: int,
    now: datetime,
) -> Mapping[str, object]
```

### 3. Contracts

- A standard document is shared and must have `user_id`, `track_id`, `active_plan_revision_id`, and `standard_document_id` all null.
- A personalized document is scoped to exact `user_id + track_id + knowledge_key`, references a standard document, and records active plan revision, profile hash, source-set hash, predecessor lineage, and immutable content hash.
- Publication copies source version, raw document hash, chunk hash, canonical URL, section path, timestamps, and bounded excerpt into immutable snapshots. `grounding_chunks` remains a replaceable search index and is not a replay dependency.
- One active assignment exists per track/key. Start may set `started_at` once and move only `available -> in_progress`. A started assignment is never silently replaced.
- Refresh creates a direct proposed successor with an impact payload. Only explicit activation may supersede the active assignment.
- Provider calls happen outside long transactions. A durable authoring run owns lease generation, expected track/progress/source versions, terminal safe failure, and append-only attempt usage facts.
- Confirmed local purge deletes user-owned Lesson children before personalized documents and LearningTrack roots. Shared standard documents and their snapshots remain.

### 4. Validation & Error Matrix

| Condition | Database/application result |
| --- | --- |
| Standard row contains user/track ownership | `chk_tutor_lesson_document_scope_shape` rejects the row |
| Personalized row omits standard/revision ownership | `chk_tutor_lesson_document_scope_shape` rejects the row |
| Assignment document belongs to another user/track/key | composite FK rejects the row; public service maps scope misses to 404 |
| Two active assignments exist for one track/key | `uq_tutor_lesson_assignments_one_active` rejects the loser |
| Started assignment is silently replaced or rewound | assignment lifecycle trigger rejects the update |
| Published document/snapshot/citation/Gate row is updated or deleted | immutable trigger rejects the mutation outside confirmed purge |
| Authoring lease or terminal fields contradict state | authoring run CHECK/lifecycle trigger rejects the mutation |
| Attempt usage is partially fabricated | `chk_tutor_lesson_authoring_attempt_usage` rejects the receipt |
| Expected track/progress/assignment version is stale | repository returns `LESSON_DOCUMENT_VERSION_CONFLICT` or `LESSON_ASSIGNMENT_CONFLICT` |

### 5. Good / Base / Bad Cases

- Good: publish a shared standard document and a track-scoped personalized successor in one final transaction, then create the active assignment.
- Base: reindex deletes the original grounding chunk; the already-published Lesson still renders from immutable snapshots.
- Bad: update a started assignment to a new document without a proposed successor and explicit activation.
- Bad: user purge deletes a shared standard document or another user's personalized document.

### 6. Tests Required

- Bootstrap twice and assert all seven Lesson tables, owning constraints, indexes, and triggers exist.
- Round-trip standard and personalized documents, snapshots, citations, and Gate slots through PostgreSQL.
- Assert standard/personalized shape checks and composite scope FKs reject bad inserts.
- Assert reindex independence, authoring lease reclaim/stale finalization, idempotent publication, start CAS, proposal creation, explicit migration, cross-user rejection, export/reset/delete, and cutover target counts.
- Run PostgreSQL/bootstrap-heavy tests serially because they share the bootstrap schema.

### 7. Wrong vs Correct

#### Wrong

```sql
UPDATE tutor_lesson_assignments
SET document_id = :new_document_id
WHERE id = :started_assignment_id;
```

This silently rewrites the authority referenced by future attempts and mastery evidence.

#### Correct

```sql
INSERT INTO tutor_lesson_assignments (
  user_id, track_id, knowledge_key, document_id,
  assignment_version, status, predecessor_assignment_id, impact_json
)
VALUES (
  :user_id, :track_id, :knowledge_key, :new_document_id,
  :next_version, 'proposed', :active_assignment_id, :impact_json
);
```

The active assignment remains stable until an explicit version-checked activation supersedes it.

## 场景：练习 Gate、Attempt 与 execution owner（2026-08-11）

### 1. 适用范围与触发条件

- 触发条件：新增或修改 exercise version、Gate binding/state、Attempt、模块诊断、执行队列 owner，或这些事实的 export/reset/cutover。
- 目标：让 PostgreSQL 固定 exact user/track/plan/Lesson/diagnostic scope，并在复用现有执行队列时不弱化旧 Tutor 路径。

### 2. 接口与数据库签名

```text
tutor_exercise_attempts.attempt_type = run | submit | diagnostic_submit
tutor_execution_intents.source_kind = tutor_message | exercise_submission
tutor_execution_jobs.owner_kind = tutor_effect | exercise_attempt
tutor_mastery_evidence.evidence_effect = reinforcing | observational_non_degrading
```

```sql
CHECK (
  (source_kind = 'tutor_message' AND conversation_id IS NOT NULL AND exercise_attempt_id IS NULL)
  OR
  (source_kind = 'exercise_submission' AND conversation_id IS NULL AND exercise_attempt_id IS NOT NULL)
)
```

### 3. 契约

- 共享 exercise/diagnostic version 与 user-owned Gate/Attempt/session 必须分表；私有 rubric/reference/test 不进入公共表、export 或普通模型上下文。
- Lesson `run | submit` 与模块 `diagnostic_submit` 使用 owner-shape CHECK 和复合 FK 固定 exact scope。
- `gate_kind` 是教学形态，`requirement_kind` 是路线阻塞语义，不得复用同一字段。
- Attempt、submission、result、hint、execution link 为 append-only/immutable；Gate/session 只允许受控生命周期更新。
- Gate intent/job 不得填 Tutor conversation/run/message/effect 字段；Tutor intent/job 不得填 exercise owner 字段。
- user purge 按 link/result/hint/submission/Attempt/Gate/diagnostic child-to-root 清理，保留共享 version/rubric。

### 4. 验证与错误矩阵

| 条件 | 必须结果 |
| --- | --- |
| Tutor 与 exercise owner 字段同时存在 | owner/source one-of CHECK 拒绝 |
| Attempt 引用其他用户、track、assignment、binding、session 或 item | 复合 FK 拒绝；公共服务映射为不泄漏 scope 的 404 |
| 同一 Attempt 写第二条 terminal result 或 execution link | 唯一约束拒绝，读取 winner 并重放 |
| 普通 UPDATE/DELETE 修改 append-only Practice 事实 | immutable trigger 拒绝 |
| 未授权 purge 删除 user-owned Practice 行 | purge capability trigger 拒绝 |
| failed/partial diagnostic 尝试写降低掌握度的 evidence | projector 只消费 reinforcing evidence，观察事实不降低 confidence |

### 5. 正常、基础与错误案例

- 正常：`submit` terminal result、mastery evidence、Gate CAS、progress completion 和下游 unlock 在一个事务中 exactly-once 提交。
- 基础：`run` 保存结果但不更新 Gate、mastery、progress 或路线。
- 错误：为 Gate 创建虚假 Tutor conversation/message/effect，或仅把旧 owner 字段改 nullable 而没有 one-of CHECK。

### 6. 必须测试

- bootstrap twice，断言十二张 Practice 表、owner/source CHECK、复合 FK、唯一约束、trigger 和索引存在。
- bad owner shape、跨 scope reference、重复 terminal result、普通 UPDATE/DELETE 与非授权 purge 均由真实 PostgreSQL 拒绝。
- 同一 Attempt 的 queue link、poll/recovery、result/evidence/unlock winner-replay。
- export 不含完整 submission/private rubric/reference answer；reset/cutover child-to-root 且共享版本保留。
- 旧 Tutor claim/lease/launch token/terminal/recovery 测试必须继续通过。

### 7. 错误与正确写法

#### 错误

```sql
ALTER TABLE tutor_execution_jobs ALTER COLUMN conversation_id DROP NOT NULL;
-- 没有 owner discriminator、CHECK 或复合 FK。
```

这会让半 Tutor、半 exercise 的 job 进入队列，应用层检查无法替代数据库 authority。

#### 正确

```sql
ALTER TABLE tutor_execution_jobs ADD COLUMN owner_kind text NOT NULL DEFAULT 'tutor_effect';
ALTER TABLE tutor_execution_jobs ADD COLUMN exercise_attempt_id uuid;
ALTER TABLE tutor_execution_jobs ADD CONSTRAINT chk_owner_shape CHECK (
  (owner_kind = 'tutor_effect' AND conversation_id IS NOT NULL AND exercise_attempt_id IS NULL)
  OR
  (owner_kind = 'exercise_attempt' AND conversation_id IS NULL AND exercise_attempt_id IS NOT NULL)
);
```

discriminator、one-of CHECK、owning复合 FK 和旧路径回归共同建立可执行边界。


## Scenario: Controlled Tutor Action Runtime

### 1. Scope / Trigger

- Trigger: add or change an `ActionDescriptor`, lifecycle transition, resource policy, action adapter/verifier, context receipt projection, or any `tutor_action_*` table.
- Scope: Harness contracts, Tutor services, PostgreSQL, authoritative context, local export/reset, cutover inventory, and tests.

### 2. Signatures

```python
ControlledActionRuntime.execute(invocation: ActionInvocation) -> ActionRuntimeOutcome
ActionReceiptStore.usage(*, run_id: str) -> ActionRuntimeUsage
ActionAdapter.execute(invocation: ActionInvocation) -> ActionExecutionResult
ActionVerifier.verify(*, descriptor, invocation, execution) -> ActionVerificationResult
```

DB identities are `tutor_action_invocations(run_id,idempotency_key)` and the current verified
projection `(run_id,input_revision,stable_action_key) WHERE status='verified'`.

### 3. Contracts

- An action descriptor owns schema, adapter, origin/task scope, resource profile, timeout, retry, verifier, recovery, and public projection policy.
- The Action Runtime owns orchestration only. Capability, plan draft, effect, and execution tables remain the sole domain authorities; an action receipt stores exactly one authority reference.
- Reserve and every terminal decision are fenced by exact run/input revision, lease owner/generation, action generation, catalog digest, and policy fingerprint.
- Success is `succeeded_unverified` until an independent verifier checks the referenced authority.
- Provider arguments cannot grant URL/path/command/image/environment/network/source/artifact/MCP access. Server-owned per-run action, retry, verification, and recovery budgets are mandatory.
- Context/API/SSE/export projections contain only bounded action metadata; raw arguments/results, private tests/rubrics, learner code, provider bodies, paths, commands, exceptions, and secrets are forbidden.

### 4. Validation & Error Matrix

| Condition | Stable result |
| --- | --- |
| Unknown descriptor/adapter/verifier or scope mismatch | `denied` with a stable action code |
| Resource request exceeds descriptor/server allowlist | `denied/action_admission_denied` before adapter execution |
| Stale revision, lease, cancellation, or supersede before/after execution/verification | `cancelled` or `superseded`; never current evidence |
| Adapter retryable failure within policy/budget | `retryable_failed` plus bounded `retry` directive |
| Retry/recovery/verification budget exhausted | `permanent_failed` or `denied` plus `safe_stop` |
| Handler output invalid or authority mismatch | verification failure; never `verified` |
| Same idempotency key with different request hash | conflict; no second owner call |

### 5. Good/Base/Bad Cases

- Good: grounding writes one existing capability receipt, the action verifier proves allowlisted citations, and one verified action receipt references that capability invocation.
- Base: a terminal execution job is read and verified by `runner.execute`; the API adapter never launches a process.
- Bad: storing raw action arguments/results in `tutor_action_receipts`, allowing a model-selected URL/path/command, or treating adapter success as verified.

### 6. Tests Required

- Descriptor/hash serialization and extension registration without changing the core state machine.
- Timeout, cancellation request/terminal separation, retry classification, budget exhaustion, stale fence before/after adapter and verification, idempotent replay, and current verified dedupe.
- PostgreSQL bootstrap twice; assert action tables, composite constraints, lifecycle/append-only triggers, indexes, replay, cross-user isolation, export redaction, and child-first reset.
- Integration tests for `grounding.retrieve`, `learning.plan.draft`, and `runner.execute` authority references; assert no duplicate domain owner and no process launch from the API adapter.

### 7. Wrong vs Correct

#### Wrong

```python
result = handler(arguments)
return {"status": "verified", "raw_result": result}
```

#### Correct

```python
execution = adapter.execute(invocation)
store.record_attempt(invocation, execution, attempt_index=1, created_at=now)
verification = verifier.verify(descriptor=descriptor, invocation=invocation, execution=execution)
receipt = runtime.finish_only_if_current(execution=execution, verification=verification)
```

The correct flow separates execution from verification, retains one domain authority, applies
stale/budget/resource gates, and publishes only the bounded receipt projection.


## Scenario: Model Code-Review Authoring, Export, and Purge

### 1. Scope / Trigger
- Trigger: changing `model_code_review` authoring/candidate/validation/publication tables, shared execution owner/source, local export/reset, or cutover inventory.

### 2. Signatures
- DB roots: `tutor_model_review_authoring_runs`, `tutor_model_review_candidates`, `tutor_model_review_validation_runs`, `tutor_model_review_publications`.
- Action authority: `model_review_validation`; execution source/owner: `model_review_candidate` / `model_review_validation`.
- Export keys: `model_review_*_summaries`; private payload/proof keys are omitted.

### 3. Contracts
- Candidate public/private JSON and hashes are immutable; publication requires exact verified validation authority and scope.
- Action/execution rows contain opaque IDs and safe hashes, never candidate code, tests, matcher tokens, provider bodies, commands, paths, images, or secrets.
- The authoring-to-candidate/validation/publication cycle uses `ON DELETE NO ACTION DEFERRABLE INITIALLY IMMEDIATE`. PostgreSQL `RESTRICT` is immediate even when declared deferrable.
- Confirmed reset terminalizes owned internal proactive runs, deletes user-owned child facts in dependency order, then deletes only those internal runs/conversations. Published immutable exercise/rubric rows remain.

### 4. Validation & Error Matrix
| Condition | Required result |
| --- | --- |
| Missing/failed/stale validation check or Action receipt | candidate remains unpublished |
| Cross-user candidate/validation/publication reference | composite FK or repository scope rejection |
| Ordinary UPDATE/DELETE of append-only evidence | `23514` trigger rejection |
| `RESTRICT` used on an intended deferred cycle | bootstrap/reset regression failure |
| Export contains private payload, proof, test, matcher, or finding prose | privacy test failure |

### 5. Good/Base/Bad Cases
- Good: verified nine-check validation publishes once, export returns IDs/status/hash/counts, reset removes user-owned chain and internal run.
- Base: failed authoring remains safely retryable and export contains only safe failure code/summary.
- Bad: clearing terminal pointers with a broad purge UPDATE, deleting shared exercise versions, or relying on `SET CONSTRAINTS` with `RESTRICT`.

### 6. Tests Required
- Bootstrap twice; assert all three circular FKs are deferrable, initially immediate, and `confdeltype='a'` (`NO ACTION`).
- Full PostgreSQL authoring→publication→evidence→Attempt→export→reset test.
- Assert private payload, tests, matcher/proof and learner finding prose are absent from export.
- Cutover inventory must count all seven model-review user-owned tables.

### 7. Wrong vs Correct
#### Wrong
```sql
FOREIGN KEY (publication_id, user_id)
REFERENCES tutor_model_review_publications(id, user_id)
ON DELETE RESTRICT DEFERRABLE;
```
#### Correct
```sql
FOREIGN KEY (publication_id, user_id)
REFERENCES tutor_model_review_publications(id, user_id)
ON DELETE NO ACTION DEFERRABLE INITIALLY IMMEDIATE;
```
Only `NO ACTION` permits the transaction to delete both sides before the deferred check.

## Scenario: Track-Scoped Review Schedule and Finite ReviewSession (2026-08-12)

### 1. Scope / Trigger

- Trigger: changes to `services/learning/reviews/`, track review counts, module-diagnostic skip scheduling, plan activation, `review_submit` Attempt ownership, review API routes, export/reset, or cutover inventory.
- The pre-cutover `ReviewState`/`ReviewLog` scenario above is historical compatibility evidence only. New work must not register top-level `/api/reviews` or use `review_states`, `review_logs`, or `review_seed_banks` as active authority.

### 2. Signatures

- Queue: `PostgresReviewScheduleRepository.read_queue(user_id, track_id, now) -> {due_count, items, critical_prerequisite_gate}`.
- Session: `ReviewService.create_session(..., expected_track_version, expected_schedule_version, max_items, idempotency_key)` where `1 <= max_items <= 3`.
- Mutations: `warmup`, `hint`, `attempt_item`, and `finalize_session` always carry exact user/track/session scope and expected versions.
- Route module: `app/routes/learning_track_reviews.py`; API root: `/api/learning-tracks/{track_id}/reviews...` only. The retired basename `app/routes/reviews.py` must remain absent.
- DB authority: `tutor_review_schedule_states`, `tutor_review_schedule_events`, `tutor_review_sessions`, `tutor_review_warmup_receipts`, `tutor_review_items`, `tutor_review_hint_receipts`, and `tutor_review_finalizations`; `tutor_exercise_attempts.attempt_type='review_submit'` owns exact review session/item IDs.

### 3. Contracts

- A schedule is unique by `track_id + knowledge_key` and must carry the matching user and source plan revision. Stable knowledge keys survive plan revision changes; removed keys are explicitly suspended with a migration event.
- The actionable queue contains active schedules with `due_at <= now` plus persisted `risk_level='critical'` schedules. Only an actionable critical item that is a direct or transitive prerequisite of the current node projects `critical_prerequisite_gate=true`. Track `review_due_count` uses the same actionable definition.
- A critical recovery Gate may start before its ordinary future `due_at`; ordinary future schedules may not. Candidate shortage leaves a recoverable blocked session and never synthesizes a fallback.
- Session creation freezes plan/schedule versions, immutable exercise versions, and `review_authoritative_context_v1`. Resume reads the frozen snapshot; it does not infer goal, time, preferences, or correction lineage from conversation history or summary.
- Warmup and hint receipts are append-only and do not update mastery or schedule. Each item has at most one append-only `review_submit` Attempt. Only one finalization after every item is terminal may append review mastery evidence and a schedule event and CAS-update the schedule in the same transaction.
- Static/model-review scoring and execution-required work reuse existing exercise contracts and the existing execution queue. Public projections and export omit full submissions, private rubrics/tests, context hashes, event state payloads, provider bodies, commands, paths, images, and credentials.

### 4. Validation & Error Matrix

| Condition | Stable result |
| --- | --- |
| Retired basename `app/routes/reviews.py` exists | Cutover regression; rename the track-scoped module instead of weakening the retirement guard |
| Cross-user/track/session/item/attempt scope | `404 REVIEW_NOT_FOUND` without existence leakage |
| Stale track, schedule, session, or item version | `409 REVIEW_VERSION_CONFLICT` |
| Same idempotency identity with different request hash | `409 IDEMPOTENCY_CONFLICT` |
| Ordinary schedule is not due | `409 REVIEW_NOT_READY`; no session row or Attempt |
| Critical schedule is a current prerequisite but `due_at` is future | Queue immediately includes it and session creation is allowed |
| No quality-approved compatible candidate | blocked session with `REVIEW_CANDIDATE_UNAVAILABLE`, `recoverable=true`, no fallback |
| Warmup writes long-term state or finalization is attempted before all items terminal | reject/rollback; no mastery or schedule mutation |
| Execution tier is unavailable or reviewed public lock is absent | `503 EXECUTION_UNAVAILABLE`; no host/legacy fallback |
| Plan revision removes a scheduled knowledge key | preserve audit history and mark schedule `suspended` via explicit migration event |

### 5. Good/Base/Bad Cases

- Good: a due two-item batch freezes both versions, warmup writes no long-term state, the first terminal Attempt leaves the session active, the second makes it ready, and one finalization writes one mastery evidence and one schedule event.
- Good: a critical forgotten prerequisite with a ten-minute future due date appears immediately as the sole short Gate and can start a recovery session.
- Base: no eligible candidate exists; the blocked session is returned and the same idempotency request recovers after a verified candidate is published.
- Bad: count only `due_at <= now`, hiding a persisted critical prerequisite for ten minutes; or include every future critical item as a course Gate without checking current-plan prerequisites.
- Bad: name the new track-scoped router `app/routes/reviews.py`; static cutover guards intentionally reserve that path for the removed runtime.
- Bad: update schedule/mastery after each item, regenerate context from recent chat on resume, or create a low-quality local fallback exercise.

### 6. Tests Required

- Pure scheduler tests across supported stability/difficulty ranges: rating/due monotonicity, finite 3650-day bounds, independence/hint difference, critical failure, overdue escalation, and diagnostic-skip seed.
- PostgreSQL tests for critical future Gate/actionable count, multi-item batch, warmup no-op, exactly-once finalization, cross-user scope, candidate recovery, retained/suspended plan migration, export/reset/cutover, and repeatable bootstrap constraints/triggers.
- API tests for verified-only lifecycle, idempotent replay, safe pending/terminal Attempt projection, cross-user 404, and track-card count consistency.
- Full API lock/Ruff/Mypy/pytest, including retired-path guards, executor regression, Desktop typed build, Trellis validation, and `git diff --check` before commit.

### 7. Wrong vs Correct

#### Wrong

```sql
SELECT count(*)
FROM tutor_review_schedule_states
WHERE track_id = $1
  AND status = 'active'
  AND due_at <= now();
```

This hides a persisted critical prerequisite until its ordinary relearning interval expires and lets the UI become a second Gate authority.

#### Correct

```sql
SELECT schedules.*
FROM tutor_review_schedule_states AS schedules
WHERE schedules.user_id = $1
  AND schedules.track_id = $2
  AND schedules.status = 'active'
  AND (schedules.due_at <= $3 OR schedules.risk_level = 'critical');
```

Then compute `critical_prerequisite_gate` only from the active plan's direct/transitive prerequisite graph. The repository and track-card projection must share this actionable rule, while session creation separately allows only due or critical schedules.

## Scenario: Tutor Conversation Events and Durable Interactive Dispatch

### 1. Scope / Trigger

- Trigger: changing Tutor conversation/thread snapshots, fresh turn creation, learner-safe timeline items, conversation SSE, public event replay, interactive dispatch jobs, worker wakeups, or retry/dead recovery.
- Scope: `tutor_conversations`, `tutor_runs`, `tutor_conversation_events`, `tutor_interactive_dispatch_jobs`, the Tutor persistence/public service boundary, API routes, and thin Celery adapters.
- PostgreSQL is the durable authority. Celery and FastAPI background tasks are wakeup mechanisms only and must never become the only copy of accepted work.

### 2. Signatures

- Conversation authority: `tutor_conversations(next_public_event_sequence bigint, control_version bigint)`.
- Run protocol: `tutor_runs.interaction_protocol_version in (legacy_v1, thread_turn_v2)` with scoped retry lineage foreign keys.
- Event identity: `(conversation_id, event_sequence)` plus idempotent `(conversation_id, event_key)`; payloads use `tutor_conversation_event_v1`.
- Dispatch identity: one `tutor_interactive_dispatch_jobs` row per run with `state`, `attempt_count`, `available_at`, `lease_owner`, `lease_generation`, and `lease_expires_at`.
- Public reads: `GET /api/tutor/conversations/{conversation_id}/snapshot` and `GET /api/tutor/conversations/{conversation_id}/events` with a signed, conversation-scoped cursor.
- Worker operations: `dispatch(job_id?)` claims at most one job; `reconcile(limit)` repeatedly claims bounded eligible work.

### 3. Contracts

- A fresh `thread_turn_v2` mutation must create the run, learner input/process projection, initial public events, and dispatch job in one database transaction.
- Allocate `event_sequence` by locking the owning conversation row, incrementing `next_public_event_sequence`, and inserting the event before commit. Do not derive sequence from timestamps, UUIDs, or run-local input revisions.
- Validate every event payload against a closed learner-safe schema before persistence. Public events contain IDs, enums, versions, attempts, and safe codes; they never contain raw reasoning, prompts, provider bodies, capability arguments, hidden tests, credentials, paths, or commands.
- A repeated event key is an idempotent replay only when kind, scoped identity, and canonical payload match. Conflicting reuse fails closed.
- The signed stream cursor binds version, conversation ID, and sequence. Cross-conversation, malformed, future, or unsupported cursors produce a stable recoverable API error; heartbeats do not write events or advance the cursor.
- Claiming a dispatch job requires a lease owner and generation. Completion or retry must compare both values so a stale worker cannot finalize work after lease recovery.
- Retry exhaustion moves the job to `dead`, terminalizes the owning run/process with a safe public error projection, and appends dispatch/turn/item events in the same transaction.
- Historical `legacy_v1` conversations do not require event backfill. Snapshot may project their existing message/process history, while conversation SSE remains event-table-only.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Initial event or dispatch-job insert fails | Roll back the complete fresh-turn mutation; no orphan run or accepted input |
| Duplicate event key with identical canonical identity/payload | Return the existing event without advancing sequence |
| Duplicate event key with different kind, identity, or payload | Fail closed; do not overwrite the existing event |
| Cursor belongs to another conversation, has an unknown version, or is malformed | Stable recoverable cursor error; client rebuilds from snapshot |
| Cursor sequence is ahead of committed conversation authority | Reject as invalid/future; do not silently clamp |
| Celery publish or local background wakeup fails | Keep job pending/retryable; periodic reconciler remains able to claim it |
| Worker crashes after lease claim | Lease expiry permits a later generation to reclaim; stale generation cannot complete |
| Retry budget is exhausted | Job `dead`, run/process terminal, learner-safe error item/event, no raw exception text |
| Legacy conversation has no public events | Snapshot projects bounded legacy history; no synthetic event backfill |

### 5. Good / Base / Bad Cases

- Good: one transaction creates a fresh v2 turn, input/process items, ordered events, and one pending job; either the API fast path or Celery claims it, and duplicate wakeups lose the same lease/CAS authority.
- Good: two concurrent event writers serialize on the conversation row and commit distinct contiguous sequences; replaying one event key returns its original event.
- Base: the broker is unavailable. The HTTP mutation still commits durable work, logs only job/run IDs and a safe diagnostic code, and the reconciler dispatches it later.
- Base: a legacy conversation has no event rows. Snapshot returns its existing message/process timeline and an empty event cursor without changing historical data.
- Bad: create a run and use only `BackgroundTasks.add_task(...)`; process loss after the response silently drops accepted learner work.
- Bad: use `MAX(event_sequence) + 1`, `created_at`, UUID order, or a run-local revision as conversation-global ordering authority.
- Bad: put raw `tutor_run_events` payloads, provider errors, prompts, reasoning, or learner content into the public event log or worker logs.

### 6. Tests Required

- Bootstrap twice and assert conversation authority columns, protocol checks, event/job tables, indexes, scoped foreign keys, append-only trigger, and cleanup/cutover inventory.
- Transaction rollback test: force an event/job failure and assert no run, input, item, event, or job residue remains.
- Event tests: concurrent contiguous allocation, idempotent replay, conflicting-key rejection, append-only enforcement, identity scoping, and canonical payload validation.
- Snapshot/SSE tests: scoped signed cursor, reconnect replay, duplicate-item prevention, heartbeat behavior, future/version/cross-conversation errors, and legacy projection without event backfill.
- Dispatch tests: duplicate wakeup, single claimant, lease expiry, stale-generation rejection, retry/backoff, continuation retry-budget reset, dead terminalization, and safe error projection.
- Worker tests: Celery task names/routes/priorities, periodic reconciler schedule, thin adapter imports, and broker-loss recovery without real network/provider calls.
- Run the complete API pytest suite, Ruff, Mypy, `uv lock --check`, compileall, Trellis validation, and `git diff --check` before commit.

### 7. Wrong vs Correct

#### Wrong

```python
run = repository.create_run(input_payload)
background_tasks.add_task(dispatcher.dispatch, run.id)
return {"run_id": run.id}
```

The accepted work has no durable dispatch authority, and process loss can leave an orphan in-progress turn.

#### Correct

```python
with transaction(conn):
    run = repository.create_fresh_v2_turn(input_payload)
    event = repository.append_conversation_event(
        conversation_id=run.conversation_id,
        event_key=f"turn:{run.id}:created",
        payload=learner_safe_turn_reference(run),
    )
    job = repository.create_interactive_dispatch_job(run_id=run.id)

best_effort_enqueue(job.id)  # PostgreSQL reconciler remains authoritative.
```

The owning mutation, public ordering authority, and recoverable dispatch job commit together; wakeup loss does not lose accepted work.


## 场景：Tutor 类型化请求与 fresh response turn

- v2 continuation 必须创建 `tutor_interaction_requests` 并 terminalize source turn；禁止把新 v2 run 写成 `waiting_for_input` 后恢复同一 budget。
- request kind/actor、planning key/catalog、approval identity、authority scope/hash 使用 closed CHECK + typed serializer；每 conversation 只允许一个 partial-unique pending request。
- learner response 和 authority receipt 都锁 conversation/request，比较 exact scope、state、version 与 canonical body hash，再创建 fresh `thread_turn_v2`、revision 1 input、process/event/job 和 `response_to_request_id`。
- 相同 body/receipt identity 重放同一 answer turn；不同 body/hash、stale version、跨 user/conversation、ambiguous authority verification 必须 fail closed，ambiguous 不得伪造 solved。
- public item 只能从 allowlisted descriptor/presentation 投影；不得保存或公开 provider schema、raw reasoning、capability args、raw authority result 或 secret。
- 必测：bootstrap twice、partial unique/FK/CHECK、request CAS、fresh deadline/counters、planning catalog、approval identity、authority receipt、pending normal-input block、snapshot/event allowlist、cutover inventory。


## 场景：Tutor conversation Queue 与 retry logical effect authority（2026-08-14）

### 1. 适用范围与触发条件
- 修改 `tutor_conversations.queue_*`、`tutor_queued_inputs`、conversation control mutation、completed-only drain、Retry lineage 或 `tutor_effects.logical_action_key` 时适用。

### 2. 数据库契约
- 所有 Queue mutation 固定锁序为 conversation -> pending request/queue -> run -> dependent rows；`control_version` 是公开 CAS authority。
- pending item 最多 10 项，`(conversation_id, position) WHERE state='pending'` 唯一；reorder 必须提交完整 pending ID 集合，并通过临时 offset 后重写连续 position。
- item lifecycle 仅为 `pending -> claimed|cancelled`。claim 必须同时写 claimed turn/input revision/mode/time；cancelled 必须写 cancelled time；两者都不能回到 pending。
- enqueue idempotency 绑定 conversation + enqueue key + canonical content/metadata hash。原始 learner 文本只在 pending Queue row 暂存，claim 后 canonical message 仍写 `tutor_messages`；event/idempotency payload 不复制正文。
- claim transaction 原子创建 fresh run、learner message/input event、scope/context/planning metadata、public process、dispatch job，并标记 item claimed。duplicate drain 遇到 active run 或非 pending item必须 no-op。
- `queue_paused=true` 只允许 `pending_request|interrupted|failed`；普通 Send 不能清除 pause。
- retry logical action key 绑定 user、conversation、stable retry root、effect type 与 payload hash。相同 run/effect identity 先返回原 receipt；跨 retry turn 的 committed key 复用 commit ID 且不调用 handler；proposed/ambiguous key fail closed。

### 3. 验证矩阵
- bootstrap twice，检查 table/columns/check/FK/index/trigger 与 cutover inventory。
- 并发 enqueue 不超过 10；duplicate enqueue/reorder/drain 不重复；stale control/item/revision 拒绝。
- Steer 保持同一 run/scope 并递增 revision；Interrupt/execute 不能留下两个 foreground run。
- completed 自动 drain；failed/interrupted/pending request pause；普通 Send 只排队。
- Retry predecessor/root 正确；同 logical effect 只产生一次领域写，ambiguous receipt 不重试。

### 4. 错误与正确写法
#### 错误
```sql
SELECT max(position) + 1 FROM tutor_queued_inputs WHERE conversation_id = $1;
```
这没有锁 conversation，也不能同时保护容量、完整 reorder 与 claim。

#### 正确
```sql
SELECT * FROM tutor_conversations WHERE id = $1 AND user_id = $2 FOR UPDATE;
SELECT count(*) FROM tutor_queued_inputs WHERE conversation_id = $1 AND state = 'pending';
```
先取得 conversation authority，再执行 Queue/item/run CAS。


## 场景：Tutor thread/turn v2 全局 cutover authority（2026-08-14）

- `tutor_thread_turn_cutovers` 是全局 singleton，状态仅为 `idle|preparing|blocked|ready|enabled`；所有 operator mutation 使用固定 PostgreSQL advisory lock、generation CAS 与 idempotency body hash。
- 有效 mutation gate 为 `TUTOR_THREAD_TURN_V2_ENABLED=true` 且 DB state=`enabled`。环境变量只是 kill switch，DB row 是跨进程原子 authority。
- preparing 后 legacy active run 只按闭合分类收口：`waiting_for_input` -> failed + `legacy_continuation_requires_new_turn`；`queued|leased|running|waiting_for_capability` -> cancelled + `legacy_protocol_cutover`，并清 lease/job。
- `awaiting_effect_commit`、`tutor_effects.status=proposed` 或未终态 Action receipt 必须 blocked；不得猜测成功/失败。
- `tutor_thread_turn_cutover_events` append-only，只保存 generation、state、safe counts/code/timestamp，不保存 learner/provider 内容。两张全局表属于 shared cutover infrastructure，不是 user-owned target state。

## 场景：Tutor 公开思考文本的 durable stream authority（2026-08-15）

### 1. 适用范围与触发条件

- 触发：修改 `public_thinking_text`、`tutor_turn_public_thinking_streams`、`turn_output`、terminal message/request、reset/delete/cutover。
- 该能力跨 Provider、Harness、PostgreSQL、SSE 与 Desktop，必须保持 learner-safe preview 与最终回答 authority 分离。

### 2. 接口与数据库签名

- `tutor_messages.public_thinking_text text NOT NULL DEFAULT '' CHECK (char_length(...) <= 1280)`。
- `tutor_turn_public_thinking_streams(run_id PK,user_id,conversation_id,input_revision,decision_iteration,generation,provider_attempt,state,thinking_text,next_chunk_sequence,last_public_event_sequence,...)`。
- lifecycle：`begin_attempt/append_text/complete_attempt/reset_attempt/discard_attempt/discard_current`。
- event：`turn_output` + `tutor_public_thinking_stream_v1`，`append.text` 最多 160 字符。

### 3. 契约

- stream row 只保存已通过累计 safety 的公开纯文本；禁止 raw JSON/reasoning/prompt/body/trace/diagnostic。
- 每次 mutation 与 conversation event 同一短事务，校验 foreground、lease、input revision、decision iteration、generation 与 provider attempt。
- terminal message 或 typed request 只有在 final decision 文本与 complete stream 完全一致时才能原子标记 `accepted`。
- legacy steps 只读，以双换行合并；新行禁止同时写 text 与非空 steps。

### 4. 验证与错误矩阵

| 条件 | 结果 |
| --- | --- |
| stale revision/generation/lease/foreground | `TutorLifecycleConflict`，不追加文本 |
| append 超 160、累计超 1280、sequence 非单调 | fail closed，事务无半写 |
| repair/restart/context rebuild | reset 新 generation；旧回调拒绝 |
| interrupt/supersede/failure | stream `discarded`，snapshot 不再投影 |
| final decision 与 stream 不一致 | 拒绝 terminal public item，不接受 stream |
| text 与 legacy steps 同时非空 | PostgreSQL CHECK 拒绝 |

### 5. 正常、基础与错误案例

- 正常：三次 append 后 complete，terminal transaction 写同文本 message 并将 row 置 `accepted`。
- 基础：provider 不支持 visible stream，active row 为空；最终 message 直接保存完整 text。
- 错误：repair 后继续向旧 generation 追加，或先写 message 再单独接受 stream。

### 6. 必须测试

- bootstrap twice：表、列、CHECK、复合 FK、index、updated trigger、event kind 与 cutover inventory。
- active snapshot 恢复安全前缀；reset 后 stale attempt 拒绝；discard 清除 projection。
- terminal message 与 typed request 原子接受 exact stream；失败路径不留半完成 public item。
- DB 测试串行执行，不能并发运行多个 schema bootstrap 组。

### 7. 错误与正确写法

#### 错误

```python
insert_message(public_thinking_text=provider_partial_text)
mark_stream_accepted(run_id)
```

#### 正确

```python
repository.complete_turn_with_message_if_current(
    run=run,
    public_thinking_text=validated_decision.public_thinking_text,
    expected_stream_generation=generation,
)
```

同一事务同时建立最终消息 authority 与 stream acceptance，任何 fence 失败都整体回滚。

## Scenario: Published course intent taxonomy and coverage gate (2026-08-21)

- `tutor_learning_intents` is a closed shared taxonomy; `language_course_intent_tags` owns the many-to-many course relation, relevance rank, primary marker, and policy version.
- Every active course must have at least one active intent tag, and every active intent must have at least one active course. Deferred constraint triggers enforce the final transaction state so course publication and tag writes can commit atomically.
- Bootstrap seeds intents and performs the only slug-based backfill, then runs `language_course_intent_coverage()` and `assert_language_course_intent_coverage()`. Runtime queries never branch on slug, title, or description.
- `tutor_learning_intents` is shared cutover metadata, not user-owned target state. Neither taxonomy table belongs in user export/reset/delete.
- PostgreSQL tests must run bootstrap twice, inspect tables/indexes/triggers, prove an untagged active course fails at the transaction boundary, and keep the exhaustive Tutor table classification green.
