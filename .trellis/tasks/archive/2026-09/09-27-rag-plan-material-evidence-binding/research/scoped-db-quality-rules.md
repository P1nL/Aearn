# D 所需数据库与质量规则（有界上下文）

本文件是规划时从现行spec抽取的只读上下文，避免大文件原生注入截断遗漏末尾RAG规则。权威仍是标注的原始spec；实施若源文改变，子代理按所列范围用FastCtx补读，不加载整份历史场景。

## 来源 .trellis/spec/backend/database-guidelines.md:13-37

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
- 当前 bootstrap Schema 由 `app/db/schema/__init__.py` 的 `SCHEMA_FRAGMENT_NAMES` 显式排序；数字前缀只帮助阅读，loader 不得依赖目录自然排序或 `glob()` 顺序。
- 每个 `app/db/schema/*.sql` fragment 只拥有连续职责范围，所有 fragment 必须在同一 caller-owned connection 和最终提交事务中执行；fragment/loader 不得 `commit` 或维护第二份聚合 SQL。
- bootstrap 使用 transaction-scoped advisory lock 串行化多进程 schema owner，并对 deadlock/serialization failure 有界重试完整事务；不得在 fragment 之间提交以规避锁冲突。
- Migration order must follow `docs/plans/learning-agent-implementation-plan.md`: base tables first, then learning/exercise core tables, then review and notes tables.
- Use `CREATE EXTENSION IF NOT EXISTS pgcrypto;` before relying on `gen_random_uuid()`.
- Add `set_updated_at()` triggers for mutable business tables.
- Do not create PostgreSQL enum types for MVP enums. The schema currently specifies `text CHECK (...)` to keep enum changes migration-friendly.
- Append-only tables such as `attempts` and `review_logs` should be corrected by new records or explicit status fields, not by soft deletion.
- `tutor_provider_attempt_receipts` 是每个实际 provider attempt 的 append-only 事实表；使用 `(run_id,input_revision,decision_iteration,attempt_index)` 幂等 identity、run/user/conversation 复合外键和 UPDATE/DELETE 拒绝触发器。相同 identity 只允许完全相同的安全事实重放。
- provider `input_tokens` 已包含 `cached_input_tokens`；数据库持久化 `uncached_input_tokens = input_tokens - cached_input_tokens`，并把 provider reported total 与 calculated input-plus-output 分列。usage 缺失必须使用 `NULL` + `usage_available=false`，不得写零值占位。

## 来源 .trellis/spec/backend/database-guidelines.md:173-182

## Naming Conventions

- Table names are plural `snake_case`: `learning_plans`, `knowledge_points`, `review_states`.
- Columns are `snake_case` and should match API fields unless the API contract explicitly uses a derived field.
- JSONB columns use a `_json` suffix where the schema uses it, such as `skill_tags_json` and `supported_exercise_types_json`.
- Index names should be descriptive and stable: `idx_<table>_<columns>`.
- Unique constraints for active records should include `WHERE deleted_at IS NULL` or `WHERE archived_at IS NULL` when the schema requires soft-delete or archive semantics.
- Idempotency storage must preserve both `Idempotency-Key` and request body identity when implemented.
- For a new user-scoped mutation whose idempotency row may not exist yet, a prior `SELECT ... FOR UPDATE` does not serialize concurrent first writes. Acquire a transaction-scoped advisory lock (or an equivalent database-owned reservation) from the full `(user_id, operation, idempotency_key)` identity before the replay lookup and business write.
- Immutable LearningTrack revisions, route structure, mastery evidence, migration receipts, and run scope snapshots reject ordinary physical deletes as well as updates. Confirmed local reset/delete may use a transaction-local purge capability only after active runs are safely terminalized and only for the exact user-owned child-to-root deletion path.

## 来源 .trellis/spec/backend/database-guidelines.md:1074-1122

## Scenario: Versioned RAG corpus authority (2026-09-23)

### 1. Scope / Trigger
- Changes to schema fragment `260_rag_subject_corpus.sql`, grounding `corpus_contracts.py` / `corpus_repository.py`, or their future CLI/consumer adapters.
- Database source of truth: `docs/architecture/database-schema.md`, the ordered manifest and actual PostgreSQL constraints; legacy grounding remains unchanged.

### 2. Signatures
- `CorpusRepository(conn)` consumes a caller-owned connection; writes never commit it.
- `create_candidate`, `add_source`, `add_document`, `add_chunk` build candidate snapshots.
- `finalize_validation(..., passed, expected_generation, validation_summary, coverage_summary, idempotency_key)` seals the candidate or records failure.
- `activate(..., expected_generation, summary_hash, idempotency_key)` and `rollback(..., expected_generation, idempotency_key)` move the Subject pointer; `retire` cannot retire its current target.
- `version`, `active`, `history` read internal typed facts, not public DTOs.

### 3. Contracts
- Six `grounding_corpus_*` / `grounding_active_corpora` tables are shared infrastructure, not learner-owned tables. `CUTOVER_SHARED_GROUNDING_CORPUS_TABLES` is separate from the exhaustive `tutor_*` namespace lists.
- Candidate → validated → published/retired, candidate → failed/retired; terminal states do not reopen. Content is immutable once validated, including ordinary direct SQL writes/deletes.
- Source/document/chunk composite scope and hashes must agree with corpus identity. Snapshot hash syntax alone is not semantic source authorization or facet coverage.
- Active pointer references a published corpus of the same Subject. Compare expected generation even when no pointer exists; rollback advances generation instead of undoing history.
- Idempotency is exact request replay: same key/request returns the prior receipt, conflicting request is rejected. A later active pointer must not change an old replay result.
- Lifecycle events are append-only, bounded, and free of provider payloads/credentials. No user-purge capability makes shared corpus history deletable.
- Corpus writes reject autocommit connections and use savepoints inside the caller transaction. An idle non-autocommit connection first starts its implicit transaction; a caught operation failure cannot leave publication/events for the caller to commit.
- Snapshot rows cannot change their corpus parent to escape sealing. The first active pointer must cite an activation receipt, not a rollback receipt.
- Stored HTTPS URL metadata excludes credentials, explicit ports, query strings and fragments; seed hosts match declared domains. This is metadata hygiene, not a source authorization/fetcher gate.
- Summary JSON is a bounded object of safe named scalar facts; nested JSON, arbitrary prose/URL/path fields are rejected. Snapshot arrays have bounded typed elements; do not rely on JSON byte size alone.

### 4. Validation & Error Matrix
| Condition | Required outcome |
| --- | --- |
| Stale generation / wrong summary hash / conflicting replay | Reject without partial publication or pointer/event effects |
| Cross-corpus/source/document/Subject/version lineage | Reject at repository/DB boundary, including direct SQL bypass tests |
| Content mutation after validation/publication, event mutation | Database guard rejects ordinary UPDATE/DELETE |
| Two first activations with expected generation 0 | Exactly one winner; no second generation-1 pointer |
| Retire active target | Reject, retain usable pointer/history |
| User export/reset/delete/cutover | No shared corpus content export or shared-row deletion |

### 5. Good / Base / Bad Cases
- Good: publish two immutable versions, rollback to an earlier published version with a new active generation, and preserve all receipts.
- Base: repeat full bootstrap against the same disposable database without altering historical content or the old grounding read path.
- Bad: bootstrap the default learner database for acceptance, delete shared fixtures to clean a test, or treat a stored `passed` summary as independently verified real-source evidence.

### 6. Tests Required
- Use an explicitly named disposable PostgreSQL database. Run schema/bootstrap and mutation tests serially; only the dedicated CAS test opens concurrent business connections.
- Assert bootstrap twice, state/hash/scope/immutability constraints, exact replay/conflict, two-connection CAS, rollback/retirement and legacy compatibility.
- Inventory tests must exercise real export/reset/delete/cutover with six-table shared records as well as static classification. Roll back owned fixtures instead of deleting immutable published rows.
- Record Ruff/Mypy and focused counts separately from live fetch/provider/consumer acceptance; those later phases are not executed here.

### 7. Wrong vs Correct
- Wrong: add `grounding_corpus_versions` to `CUTOVER_SHARED_TUTOR_TABLES`, or reset a user's shared corpus to achieve test cleanup.
- Correct: keep a separate shared-infrastructure classification and verify user operations leave it intact; discard only the task-owned disposable database after verification.

## 来源 .trellis/spec/backend/quality-guidelines.md:9-94

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
