# Research: persistence-and-schema-baseline

- Query: Investigate the current API database schema, migration/bootstrap conventions, repository transaction/idempotency/locking patterns, and completed Child 00/01 Harness seams to plan additive durable Tutor run/input/checkpoint/event/capability/effect/catalog persistence.
- Scope: internal
- Date: 2026-07-27

## Findings

### Scope boundary and fact/proposal labels

- **Confirmed current facts** below are based on checked-in code, tests, specifications, and archived Child 00/01 evidence.
- **Proposed Child 02 planning constraints** are not implemented behavior. They describe the minimum design decisions needed to satisfy the existing Child 02 PRD without extending public routes, Desktop behavior, worker scheduling, Curator model execution, or legacy-data deletion.
- The active Child 02 PRD explicitly depends on Child 00 and Child 01, requires additive persistence plus redaction/CAS/evals, and excludes learner UI, proactive scheduling, Curator behavior, and destructive legacy work: `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:5-32,47-50`.

### Files found

| File | Current role / relevance |
| --- | --- |
| `aearn/services/api/app/db/schema.sql` | The only checked-in API schema application source; creates legacy product tables, indexes, triggers, and repeatable `ALTER ... IF NOT EXISTS` upgrades. |
| `aearn/services/api/app/db/bootstrap.py` | Applies the whole schema and catalog seeds, then commits once. |
| `aearn/services/api/app/db/connection.py` | Opens a plain psycopg connection with `dict_row`; callers own commit/rollback. |
| `aearn/services/api/tests/test_db_bootstrap.py` | Proves bootstrap repeatability and basic relational inserts when PostgreSQL is available. |
| `aearn/services/api/app/services/repositories/plan_repository.py` | Representative caller-owned-connection repository and request-hash idempotency pattern. |
| `aearn/services/api/app/services/repositories/learning_session_repository.py` | Existing user-scoped idempotency replay pattern for run/submit writes. |
| `aearn/services/api/app/services/repositories/review_scheduler.py` | Existing `FOR UPDATE` transaction pattern for a multi-row state update plus append-only log. |
| `aearn/services/api/app/services/repositories/learner_profile.py` | Existing `ON CONFLICT ... DO NOTHING` followed by `FOR UPDATE` pattern. |
| `aearn/services/api/app/agents/harness/contracts.py` | Immutable Child 00 run/input/checkpoint/capability/effect/policy contracts and compaction idempotency key construction. |
| `aearn/services/api/app/services/tutor/ports.py` | `TutorRunStore` port and intentionally non-durable fakes. |
| `aearn/services/api/app/services/tutor/run_loop.py` | Current finite-loop ordering, lease checks, revision reloads, safe checkpoint/result calls, and typed compaction publication. |
| `aearn/services/api/app/agents/harness/skill_catalog.py` | Child 01 immutable reviewed catalog compilation and canonical digest/hash behavior. |
| `aearn/services/api/app/services/tutor/skill_selection.py` | Explicitly run-local/non-durable selected Skill evidence keyed by `(run_id, input_revision)`. |
| `docs/architecture/tutor-harness-transition.md` | Approved Child 00/01 seam ownership and no-public-traffic/no-persistence boundary. |
| `.trellis/tasks/07-22-agent-harness-rearchitecture/implement.md` | Parent dependency order and Child 02 validation/rollback requirements. |

### 1. Current API schema and bootstrap convention — confirmed facts

1. **There is no application migration runner or migration-version table in the checked-in API tree.** A repository scan found no non-virtualenv Alembic/migration files and no `schema_migrations`/`alembic_version` references. The effective convention is a repeatable, monolithic schema bootstrap:
   - `bootstrap_database()` opens one connection, executes the entire `schema.sql`, applies seed upserts/archives, and calls `conn.commit()` once: `aearn/services/api/app/db/bootstrap.py:13-23,26-100`.
   - The schema uses `CREATE ... IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, guarded `DO $$` blocks, and trigger recreation to tolerate repeated application: `aearn/services/api/app/db/schema.sql:1-9,216-226,333-373,479-619`.
   - `test_bootstrap_is_repeatable_and_seeds_catalog()` invokes bootstrap twice: `aearn/services/api/tests/test_db_bootstrap.py:26-37`.

2. **Current persistence is legacy learning-product persistence, not Tutor persistence.** The schema has `learning_sessions`, `attempts`, legacy conversation/message tables, grounding tables, and `idempotency_records`, but no `tutor_*` run/input/checkpoint/event/effect/catalog/outbox table declaration in the complete current table list.
   - `learning_sessions` holds legacy `learn`/`review` session type and `learning_stage` / `review_stage` JSON state: `aearn/services/api/app/db/schema.sql:196-214`.
   - `attempts` is a legacy learner-code fact table and contains submitted code, runtime outcomes, test data, and scores: `aearn/services/api/app/db/schema.sql:228-247`.
   - Legacy onboarding, review, and learning message tables persist `content` and optional metadata/client IDs: `aearn/services/api/app/db/schema.sql:622-667`.
   - Existing `idempotency_records` uses a globally primary-keyed `key`, `operation`, `request_hash`, `response_json`, optional `user_id`, invalidation timestamp, and creation timestamp: `aearn/services/api/app/db/schema.sql:333-345`.

3. **PostgreSQL conventions are explicit SQL, UUID keys, `timestamptz`, JSONB where named, and trigger-managed `updated_at`.** `pgcrypto` and `set_updated_at()` are bootstrap-level primitives: `aearn/services/api/app/db/schema.sql:1-9`. The backend database guidelines require PostgreSQL as source of truth, explicit SQL/migration-defined contracts, UUIDs, `timestamptz`, `_json` JSONB naming, and request-body identity for idempotency: `.trellis/spec/backend/database-guidelines.md:15-21,25-43`.

4. **The checked-in bootstrap test is integration-style and conditional on PostgreSQL.** It skips when PostgreSQL is unavailable, rather than replacing the schema with a fake database: `aearn/services/api/tests/test_db_bootstrap.py:11-23`. It creates connected legacy rows inside one connection then rolls them back for the relation smoke: `aearn/services/api/tests/test_db_bootstrap.py:74-184`.

5. **Documentation describes migration ordering, but current runtime implementation is bootstrap-driven.** `docs/architecture/database-schema.md` describes a conceptual ordered migration sequence, while actual runtime application is `schema.sql` through `bootstrap_database()`: `docs/architecture/database-schema.md:1098-1179`; `aearn/services/api/app/db/bootstrap.py:13-23`. Child 02 must not assume Alembic or a versioned migration executor already exists.

### 2. Current repository, transaction, idempotency, and locking patterns — confirmed facts

1. **Repositories receive an already-open connection; route/service callers commit or roll back.** `confirm_plan(conn, ...)` receives `Connection` and performs all domain writes through it: `aearn/services/api/app/services/repositories/plan_repository.py:34-175`. The route wraps that call in `with connect()`, maps domain/idempotency errors, then explicitly commits: `aearn/services/api/app/routes/plans.py:82-141`. `connect()` itself only opens/yields/closes; it does not commit or roll back: `aearn/services/api/app/db/connection.py:11-21`.

2. **Existing idempotency is request-hash replay inside the caller-owned transaction.** `confirm_plan()` first loads a record by key, rejects a different request hash, otherwise replays its response; on a first execution it writes the plan graph and then inserts an idempotency row before the caller commits: `aearn/services/api/app/services/repositories/plan_repository.py:44-58,67-175`. The run-exercise repository follows the same shape: load user-scoped replay record, insert `attempts`, serialize response, insert idempotency row: `aearn/services/api/app/services/repositories/learning_session_repository.py:532-599,1123-1148`.

3. **This legacy replay shape is not a ready-made multi-worker CAS primitive.** The representative plan path performs an unlocked `SELECT` followed by normal inserts, with neither `FOR UPDATE` nor `ON CONFLICT` around its idempotency insert: `aearn/services/api/app/services/repositories/plan_repository.py:44-58,167-174`. It is sufficient evidence of the current API replay convention, but Child 02 must design a stronger single-transaction concurrent-worker protocol rather than copy this pattern blindly.

4. **The codebase does have reusable row-locking and conflict-tolerant insert patterns.**
   - Review scheduling locks the attempt and `review_states` rows before computing/updating state and appending `review_logs`: `aearn/services/api/app/services/repositories/review_scheduler.py:32-84,91-180`.
   - Learner-profile creation uses `ON CONFLICT (user_id) DO NOTHING`, then locks the row with `FOR UPDATE` before merge/update: `aearn/services/api/app/services/repositories/learner_profile.py:41-69,116-138`.
   - Review seed-bank placeholder creation relies on a natural-scope unique constraint plus `ON CONFLICT ... DO NOTHING`: `aearn/services/api/app/services/repositories/review_seed_bank.py:58-81`; the backing unique index is `uq_review_seed_banks_scope`: `aearn/services/api/app/db/schema.sql:498-500`.

5. **There is no current SQL implementation of Tutor revision CAS or queue claiming.** A focused source scan found `input_revision`/`expected_input_revision` only in Harness contracts/fakes/loop code, plus no `SKIP LOCKED`, advisory lock, or Tutor SQL update predicate. Current SQL locks occur only in legacy learner profile/review code. This is a real Child 02 gap, not an existing reusable implementation.

### 3. Child 00 Harness seam — confirmed facts

1. **Child 00 is deliberately feature-disabled and persistence-free.** The transition contract says it adds no learner-facing route, SSE, Desktop entry point, database table/migration, worker, or outbox; existing persistence remains the legacy boundary: `docs/architecture/tutor-harness-transition.md:5-17,19-30`. `TUTOR_HARNESS_ENABLED` defaults to false: `aearn/services/api/app/core/config.py:61-66`.

2. **The run state to persist later is already strongly typed.** `TutorRunSnapshot` contains opaque run/conversation/user IDs, input revision, policy, status, lease, counters, and cancellation state: `aearn/services/api/app/agents/harness/contracts.py:483-506`. `TutorInputEvent` requires a positive monotonic revision, learner-only role, opaque message ID, and sanitized bounded content: `aearn/services/api/app/agents/harness/contracts.py:140-160`.

3. **Checkpoint and compaction contracts are metadata-only by design.** `TutorCheckpointMetadata` stores token budget, consumed tokens, section counts, source IDs, and source hashes: `aearn/services/api/app/agents/harness/contracts.py:254-288`. `TutorCheckpoint` stores only run/revision/reason/status/metadata/timestamp: `aearn/services/api/app/agents/harness/contracts.py:328-340`. `TutorCompactionRequest` includes only idempotency/run/conversation/revision/trigger/source IDs+hashes/budget facts: `aearn/services/api/app/agents/harness/contracts.py:291-313`; its deterministic key is built from those facts: `aearn/services/api/app/agents/harness/contracts.py:545-574`.

4. **The current `TutorRunStore` is a port with non-durable test fakes.** The formal protocol covers snapshot load, lease acquire/heartbeat, revision read, cancellation, checkpoint save, and result recording: `aearn/services/api/app/services/tutor/ports.py:32-59`. `InMemoryTutorRunStore` explicitly says it is non-durable; it keeps snapshots, revisions, leases, checkpoints, and results in process memory: `aearn/services/api/app/services/tutor/ports.py:122-150,196-221`.

5. **Important seam gap: `accept_input()` exists only on the in-memory fake, not on the declared `TutorRunStore` protocol.** The fake enforces `event.revision == current_revision + 1`: `aearn/services/api/app/services/tutor/ports.py:199-209`, while the protocol has no acceptance method at `:32-59`. Child 02 needs an explicit durable input-acceptance repository/service contract; it should not rely on a fake-only method surface.

6. **The loop enforces revision freshness in memory but not atomically in SQL.** It reloads revision before model invocation: `aearn/services/api/app/services/tutor/run_loop.py:143-166`; before/after capability dispatch: `:281-317`; and immediately before effect commit, rejecting a mismatched expected revision before invoking the committer: `:319-364`. This is the behavioral contract Child 02 must preserve with a transaction/CAS rather than only a pre-read.

7. **Checkpoint, compaction, and result calls are currently separate port calls.** Safe checkpoint does `save_checkpoint()` then `publish()` separately: `aearn/services/api/app/services/tutor/run_loop.py:410-434`. Terminal handling does `save_checkpoint()`, then `publish()`, then `record_result()`: `:436-500`. An SQL adapter that commits each port call independently would violate Child 02's transactional-outbox requirement under a crash; atomic grouping is therefore a required design concern.

### 4. Child 01 catalog/capability seam — confirmed facts

1. **Catalog compilation is immutable and digest-backed, but not durable.** The compiler validates a reviewed Git-owned Skill bundle, instruction/eval hashes, and produces an ordered snapshot with canonical SHA-256 digest: `aearn/services/api/app/agents/harness/skill_catalog.py:264-343`. A `PublishedSkill` carries exact manifest/instruction/evaluation hashes: `:180-197`.

2. **Persist resolved exact catalog facts, not an unresolved generic reference.** The generic `TutorSkillReference` still defaults to `"current"`: `aearn/services/api/app/agents/harness/contracts.py:344-350`. In contrast, `CatalogSkillReference` requires exact SemVer: `aearn/services/api/app/agents/harness/skill_catalog.py:164-177`; `TutorSkillSelection` captures exact reference plus manifest/instruction hashes: `aearn/services/api/app/services/tutor/skill_selection.py:10-19`.

3. **Selected-Skill evidence is currently run-local and non-durable.** `InMemoryTutorSkillSelectionStore` keys selections by `(run_id, input_revision)` and comments that later work replaces it with replay storage: `aearn/services/api/app/services/tutor/skill_selection.py:22-53`. The transition contract explicitly assigns durable selected version/hash evidence for replay/restart to Child 02: `docs/architecture/tutor-harness-transition.md:117-130`.

4. **Current capability execution has no durable invocation/effect evidence.** The read-only gateway returns bounded `TutorCapabilityResult` values after catalog/policy/selection checks and injected lookup: `aearn/services/api/app/services/tutor/capability_gateway.py:47-133`. `TutorEffectProposal`/`TutorEffectResult` are typed and revision-bound, but the initial catalog has no effect descriptor/allowed effect and the default committer denies effects: `aearn/services/api/app/agents/harness/contracts.py:391-414`; `docs/architecture/tutor-harness-transition.md:132-145`.

5. **Skill evaluation files are validated but not executed by a Tutor eval runner.** The only current application references validate non-empty JSON evaluation suites and hashes during compilation: `aearn/services/api/app/agents/harness/skill_catalog.py:319-341,421-429`. No `TutorEval`/`test_tutor_evals.py` implementation exists yet.

### 5. Proposed Child 02 planning constraints — not current behavior

| Durable concern | Confirmed gap / seam | Proposed Child 02 planning constraint |
| --- | --- | --- |
| Run snapshot + lease | Only `InMemoryTutorRunStore` persists state; lease has owner, expiry, and generation in the contract: `ports.py:122-194`; `contracts.py:126-137`. | Add a Tutor-only additive run repository that makes `load_snapshot`, acquire, and heartbeat authoritative in PostgreSQL. Lease acquire/heartbeat and any terminal write must require the same active owner + generation and unexpired lease. A loser returns the existing non-persistent `lease_unavailable` result, matching the runtime contract. |
| Input acceptance | Fake-only `accept_input()` enforces `current + 1`: `ports.py:199-209`; no SQL CAS exists. | Define a repository-owned atomic input operation: user/run scope check, idempotency replay/hash check, monotonic revision allocation/validation, input insert, and an ordered input-accepted event in one transaction. Use a row lock or conditional update on the authoritative run revision; do not derive order from timestamps. |
| Checkpoint + terminal + compaction | The loop currently invokes checkpoint/publisher/result ports separately: `run_loop.py:410-500`. | Make a transaction-level persistence method (or a unit-of-work adapter) atomically write the redacted checkpoint, relevant terminal/result/event state, and a deduplicated outbox request. Do not directly reuse `InMemoryTutorCompactionPublisher` semantics as a database implementation. |
| Ordered events / replay cursor | No `TutorEvent` contract or event repository/port exists; public SSE is expressly deferred to Child 06: `docs/architecture/tutor-harness-transition.md:175-180`. | Establish internal per-run ordered events with a durable monotonic cursor/sequence allocated in the same transaction as the state change; enforce uniqueness per run/sequence and replay strictly after a supplied cursor in sequence order. Do not add a public route, SSE frame, or Desktop consumer in this child. |
| Capability invocation evidence | Gateway returns bounded results only; no durable record: `capability_gateway.py:47-133`. | Persist only descriptor ID, request ID, resolved catalog facts, bounded/redacted argument/result summary, status/code, sequence, and timestamps. Never store arbitrary target values, raw lookup payloads, provider payloads, prompts, or full snippets unless separately approved as learner-visible content. |
| Effect proposal/commit CAS | Loop pre-checks revision before the committer: `run_loop.py:328-364`, but the check is in-memory. | Atomically claim/insert the effect identity and condition it on the expected current input revision plus valid lease. A stale revision must durably record `stale_rejected` (when the trace policy requires it), must not call a domain committer, and cannot be retried as a second commit. Initial actual domain-effect execution remains out of scope because Child 01 leaves effects default-denied. |
| Catalog snapshot and selection replay | Compiler creates canonical digest; selection is in-memory: `skill_catalog.py:291-301`; `skill_selection.py:34-53`. | Store a compact catalog snapshot record/digest and exact selected Skill ref + manifest/instruction/evaluation hash per input revision. Do not store mutable `current` aliases or copy full instruction bodies as trace evidence. |
| Trace/export redaction | Checkpoints are metadata-only and context code redacts provider/raw-history/hidden-test/secret fields: `contracts.py:254-340`; `context_builder.py:38-58,207-241`. | Separate canonical learner input from diagnostic trace data. Export/trace projections must omit raw prompts, provider payload/error bodies, hidden tests, solution references, secrets, executor paths, stack traces, and full raw history. Catalog/effect/capability trace fields should be allowlisted/structured, not arbitrary JSON dumps. |
| Curation outbox + proposals | Child 00 emits an idempotent typed request but never creates an outbox; Child 05 owns Curator model behavior: `docs/architecture/tutor-harness-transition.md:70-72,170-180`; parent plan `implement.md:297-304`. | Persist only redacted source IDs/hashes and bounded request metadata; enforce outbox idempotency on the existing deterministic request key. Persist typed proposal/no-action/retry state with closed source ranges, policy/memory-setting versions, retention/staleness fields, and export-redacted payload. Do not run a model, enqueue a worker, mutate learner memory, plans, FSRS, attempts, or activity in Child 02. |
| Evaluation fixtures | Skill `evals.json` is compile-time validation only; no Tutor eval runner/test module exists. | Add deterministic fake-provider/fake-capability evaluation fixtures/results with stable fixture IDs and no live model/network dependency. Cover policy denial, strict/schema rejection, bounded loop, stale revision/CAS, and primary-model failure as required by Child 02 PRD. |

### 6. Additive-migration and legacy-data constraints

- **Do not repurpose or migrate legacy `learning_sessions`, `learning_messages`, `attempts`, or legacy Graph checkpoint semantics into Tutor records.** They encode legacy stages and potentially sensitive learner-code/history content: `aearn/services/api/app/db/schema.sql:196-247,622-667`; the parent clean-slate rule says legacy history is not copied as a migration: `.trellis/tasks/07-22-agent-harness-rearchitecture/implement.md:67-74`.
- **Prefer an additive Tutor-specific schema family and a repeatable bootstrap-compatible SQL delta.** This is a planning recommendation, not a current table design. It fits the actual `schema.sql`/bootstrap runtime and avoids pretending an uninstalled Alembic system exists. Any future migration runner would require an explicit operational decision, schema-version mechanism, and repeatability proof.
- **Do not modify public API/SSE/Desktop in Child 02.** The transition contract leaves durable events/checkpoints/outbox to Child 02 but reserves API/SSE replay/feature exposure/Desktop adaptation for Child 06: `docs/architecture/tutor-harness-transition.md:175-182`.
- **Do not create a Curator worker or outbox consumer.** Child 02 owns persisted redacted outbox/proposal state; Child 04 owns generic queue/retry scheduling and Child 05 owns Curator behavior/commit semantics: `.trellis/tasks/07-22-agent-harness-rearchitecture/implement.md:253-259,292-304`.

### 7. Validation plan for the Child 02 design/implementation

The parent already names the focused Child 02 test command, but all five expected test files are currently absent (`test_tutor_run_repository.py`, `test_tutor_event_replay.py`, `test_tutor_effect_commit.py`, `test_tutor_memory_curation_outbox.py`, `test_tutor_evals.py`). The implementation plan should create them and run the following **sequentially** because bootstrap-heavy database tests share a local database:

```powershell
# Validate local configuration before DB-backed persistence tests.
docker compose -f .\aearn\infra\docker-compose.yml config --quiet

# New Child 02 database + deterministic-eval proof. Do not run this in parallel
# with the legacy M2/M3/M4/bootstrap-heavy batches.
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_repository.py tests/test_tutor_event_replay.py tests/test_tutor_effect_commit.py tests/test_tutor_memory_curation_outbox.py tests/test_tutor_evals.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py -q

# Keep Child 00/01 seam regressions green after replacing fakes with adapters.
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_loop.py tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_skill_catalog.py tests/test_tutor_capability_gateway.py tests/test_tutor_grounding_policy.py -q

uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

- Parent-required Child 02 command and sequential bootstrap warning: `.trellis/tasks/07-22-agent-harness-rearchitecture/implement.md:172-211`.
- Existing regression anchors include loop stale-effect/compaction/feature-off tests: `aearn/services/api/tests/test_tutor_run_loop.py:203-330`; context metadata-redaction/high-water tests: `aearn/services/api/tests/test_tutor_context_builder.py:49-117`; catalog/capability boundary tests: `aearn/services/api/tests/test_tutor_capability_gateway.py:120-296`.
- The backend quality guide independently requires sequential bootstrap-heavy API test batches: `.trellis/spec/backend/quality-guidelines.md:35-46`.

### 8. Related specs and documentation authority

- `.trellis/spec/backend/database-guidelines.md:15-43` — explicit SQL/PostgreSQL, UUID/timestamp/JSON naming, repeatable migration baseline, and idempotency requirements.
- `.trellis/spec/backend/quality-guidelines.md:1598-1742` — Child 00 finite-loop, lease-before-terminal, revision reload, redaction, and feature-off constraints; Child 02 must preserve these when adding durable adapters.
- `.trellis/spec/backend/quality-guidelines.md:1745-1778` — Child 01 catalog/gateway remains internal and forbids route/SSE/Desktop/database/worker/outbox additions in that child; Child 02 is the designated persistence owner.
- `docs/architecture/tutor-harness-transition.md:5-182` — current legacy/target/adapter authority and explicit Child 02 ownership of SQL repos, durable events/checkpoints, transaction commit, and compaction outbox.
- `docs/architecture/database-schema.md:7-43,1072-1238` — legacy/current data model, append-only convention, reset/delete boundary, and conceptual migration order; it is baseline evidence rather than an already-applied Tutor schema.
- `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:9-50` — child-specific required contract freeze, acceptance, and out-of-scope boundary.

### 9. Documentation and local version references

- No external network source was required for these repository-current conclusions; checked-in code is the authority for actual behavior.
- API package constraints are Python `>=3.11,<3.13`, psycopg with binary/pool extras, FastAPI `0.128.0`, LangGraph `1.0.5`, and LangGraph PostgreSQL checkpoint package `3.0.2`: `aearn/services/api/pyproject.toml:5-19`.
- Local development documentation and database guidelines specify PostgreSQL `15` and the bootstrap command `uv --directory .\aearn\services\api run python -m app.db.bootstrap`: `.trellis/spec/backend/database-guidelines.md:145-157`; `docs/setup/development-environment.md:291-322`.

## Caveats / Not Found

- No live PostgreSQL inspection or test execution was performed for this research. The report describes the checked-in expected schema/bootstrap behavior, not the current contents or migration history of a running local database.
- No actual application migration framework, migration version table, Tutor persistence table, persistent run-event cursor implementation, SQL Tutor CAS, or queue-claim mechanism was found in the current API source.
- Child 02 has only `prd.md` plus seed context manifests at present; it still requires its own `design.md`, `implement.md`, and real manifests before any `task.py start`, as stated in `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:11-18`.
- Retention durations, exact export projection shape, durable event taxonomy, cursor encoding, and proposal status vocabulary are intentionally not frozen by current code. The Child 02 transition-delta/design must resolve them before migrations or consumers, per the Child 02 PRD: `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:11-16`.
