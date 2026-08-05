# Aearn 数据库 Schema 与持久化契约

**状态：** 当前 schema 说明，2026-08-05。
**权威来源：** `aearn/services/api/app/db/schema.sql`、PostgreSQL bootstrap、
Tutor/LearningTrack repositories 与 schema/cutover tests。
**范围：** PostgreSQL 是 Tutor run、cutover receipt、背景队列和 learner-safe
projection 的唯一 durable authority；Desktop、Celery 和 provider 不拥有并行
状态机或迁移账本。

## 1. Bootstrap、迁移与范围原则

- `python -m app.db.bootstrap` 重复执行 `schema.sql`。当前仓库没有另一个可与其
  竞争的 Alembic/Graph migration path。
- `tutor_*` 与 `harness_cutovers` 是当前 runtime 的核心表族。所有可公开读取的
  内容必须从 repository 的安全投影产生，不能直接把 JSONB、trace 或 provider
  数据返回到 API/SSE。
- 旧 `learning_*`、`review_*`、`notes`、`attempts`、`learning_plans` 等表仍在
  schema 中，以便服务器能够对已有本地用户做精确 inventory/delete、数据摘要、
  导出和已归档证据。它们不是当前 Desktop/Tutor runtime 的写入目标。
- 服务器不把旧记录迁移到 `tutor_*`。confirmed clean-slate cutover 删除精确
  legacy scope；rollback 只可能恢复代码，不会重建已删除历史。

## 2. 基础身份与课程表

| 表 | 当前作用 | 关键边界 |
| --- | --- | --- |
| `users` | 本地学习者 identity、显示名称、时间段、通知偏好 | `id` 是所有 user-scoped Tutor 数据的根；身份和允许的通知偏好在 cutover 中保留 |
| `language_courses`、`runtime_profiles` | 目录/环境安全 read model | 只通过课程/环境接口读取，不成为旧计划恢复入口 |
| `idempotency_records` | 历史业务的本地数据记录 | cutover 按精确 `user_id` 删除；不与 Tutor API idempotency 混用 |

## 3. Server-authoritative cutover

### `harness_cutovers`

主键是 `(user_id, cutover_version)`，当前版本为 `harness_clean_slate_v1`。

| 字段/状态 | 含义 |
| --- | --- |
| `state` | `required`、`summary_ready`、`verified`、`verification_failed`、`blocked_target_state` 或 `blocked_checkpoint_scope` |
| `summary_hash`、`summary_version`、`preview_nonce` | 服务器生成的可验证预览事实，不包含旧学习正文 |
| `confirmation_idempotency_key`、`confirmation_request_hash` | one-time confirmation 的安全重放/冲突检查 |
| `confirmed_at`、`verified_at` | 删除确认与可进入 Tutor 的时间事实 |
| `failure_code`、`failure_at` | 失败/阻塞的稳定安全码，非 raw exception |

`verified` 才允许 `/api/tutor/*` 与 verified-only 背景工作。任何预切换
`tutor_*` user-scoped row 都构成 target contamination：服务器写
`blocked_target_state`，而不是删除或迁移新数据。

### 历史 scope 与 checkpoint

服务器只删除能证明归属当前用户的 legacy 行，并对
`aearn:learning:<learning_session_id>` thread ID 逐表检查
`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`。未知表/namespace、
`NULL` thread ID、未知 learning thread 或无法证明映射的记录都 fail closed。

## 4. Tutor 对话、TurnRun、公开过程与可重放事件

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_conversations` | user-scoped learner-visible/internal conversation 根 | `visibility` 与 `kind` 区分公开交互和内部 proactive conversation；learner conversation 的 `title` 只能保存安全模型简述，`NULL` 对外投影为“新对话”；`last_public_activity_at` 是列表排序的唯一 authority |
| `tutor_messages` | canonical learner/Tutor public message body | 唯一允许存放原始 learner 文本的 Tutor 表；不可作为 trace/export dump；旧 message-only conversation 继续可读 |
| `tutor_catalog_snapshots` | reviewed Skill catalog digest snapshot | run 只能引用已持久化的 digest |
| `tutor_runs` | 有限 loop 的 durable snapshot | `origin` 为 `interactive/proactive`；lease、budget counter、`input_revision`、terminal outcome 和 `next_event_sequence` 都由 DB 保护；`superseded_by_run_id` 是内部 audit link；`continuation_kind` 只允许 explicit continuation enum |
| `tutor_run_public_processes` | 一条新 interactive run 对应一条 server-safe public-process projection | 只允许 `thinking/completed/superseded/unavailable`，只保留 timestamps、关联 public Tutor message 和固定 step key；不存 reasoning、provider payload、prompt、trace 或工具参数 |
| `tutor_run_public_process_steps` | append-only public-process step order | `(run_id, ordinal)` 唯一；step key/state 均有 DB + repository allowlist；公开 label 在 read projection 映射而非存自由文本 |
| `tutor_run_skill_selections` | exact Skill evidence | `(run_id, input_revision)` 唯一；保存 id/version 与 manifest/instruction/evaluation hash |
| `tutor_run_input_events` | 已接受输入的 revision/event receipt | revision 在同一 run 内单调；普通消息一条一个 fresh run，只有 explicit continuation 才在同 run 增加 revision；用于 replay 与 stale-effect gate |
| `tutor_run_checkpoints` | metadata-only checkpoint | 不保存 assembled prompt、raw history 或 provider payload |
| `tutor_run_events` | run-local ordered event log | `event_sequence` 在 locked run row 上分配；SSE 只读取其安全后缀 |
| `tutor_capability_invocations`、`tutor_effects` | capability/effect receipt | 当前 revision、lease、Skill evidence 与 policy 必须同时通过；stale/superseded effect 不调用 handler |
| `tutor_run_traces` | redacted diagnostic trace | trace 写入和导出都再次走 allowlist projection |
| `tutor_api_idempotency_records` | public Tutor / LearningTrack mutation replay | `(user_id, operation, idempotency_key)` 唯一；Tutor 输入与 `learning_track.*` mutation 都绑定 request hash 与安全 response JSON |

`POST /conversations/first-turn` 的 repository mutation 在一个 transaction 内创建 learner
conversation、fresh run、首条 learner message/input event 和 `input_received` process；任何
中间失败都会回滚，不留下空 conversation。普通 conversation-input 在 conversation lock
下先结束旧 foreground run、冻结其 process，再创建新 run。partial unique index
`uq_tutor_runs_interactive_foreground` 只允许同一 conversation 存在一条尚未 terminal、
cancelled 或 superseded 的 interactive foreground run。

终态约束：`tutor_runs.terminal_outcome` 与 `terminal_at` 必须同时为 `NULL` 或同时
存在。terminal transition、safe event、trace 与 curation outbox 由同一事务维护，
避免暴露半完成状态。provider 返回后的 lifecycle write 再次检查 cancellation/supersede；
stale run 只能收敛到安全 cancelled/superseded projection，不能写 Tutor message、title、
capability receipt 或 effect commit。

## 5. LearningTrack、计划路线、掌握度与教学 scope

LearningTrack 是新增的 track-scoped 教学权威状态，与旧 `learning_*` 表以及
user-level `tutor_plan_revisions` 明确隔离：

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_learning_tracks` | user + language + goal 的长期主线根 | `(id,user_id)` 复合 scope；`version` 用于 CAS；当前节点 FK 只能指向同 track progress |
| `tutor_track_plan_revisions` | predecessor-linked 完整计划版本 | predecessor 不得自指；canonical `plan_json` / SHA-256 不可普通 UPDATE/DELETE；状态 transition 与 activation timestamp 由 trigger 收口；每 track partial unique active revision，deferred constraint 保证 pointer/revision 一致 |
| `tutor_track_active_plans` | track 唯一 active pointer | revision、track、user 必须为同一复合作用域 |
| `tutor_track_plan_modules`、`tutor_track_plan_nodes` | revision 内不可变路线结构 | stable key/order 唯一；module/node 普通 UPDATE/DELETE 被 trigger 拒绝；prerequisite DAG 在应用 contract 验证 |
| `tutor_track_node_progress` | `(track_id,knowledge_key)` 长期进度 | stable key 跨 revision 保留；source revision 必须在同 track/user scope 内真实包含该 knowledge key；status 与 started/completed timestamps 双向一致 |
| `tutor_track_plan_migrations` | proposal/activation 影响与 CAS receipt | from/to revision 同 track/user；impact、expected version、idempotency/request hash 不可原地改写；lifecycle trigger 约束 proposed/confirmed/rejected/applied 与 timestamps |
| `tutor_mastery_evidence` | append-only trusted evidence | receipt 在 track + kind 内唯一；普通 UPDATE/DELETE 均被 trigger 拒绝；不能由模型正文直接生成 |
| `tutor_mastery_states` | projector 可重算的 bounded 状态 | 只引用同 progress/evidence scope；零 evidence 与 `last_evidence_id=NULL` 一致 |
| `tutor_conversation_learning_scopes` | conversation 的 general/planning/track binding | learning-track scope 必须引用同 user track；无 row 的旧 conversation 投影为 general |
| `tutor_run_learning_scopes` | fresh TurnRun 创建时的 immutable task/scope snapshot | run/user/conversation/track/progress 复合 FK；continuation 不得 UPDATE snapshot |

计划激活先锁 track 并校验 `expected_track_version`、direct predecessor 与 migration
状态，再切换 revision/pointer。相同 `knowledge_key` 的 progress/mastery 保留；新 key
依据其 prerequisite 的已完成状态初始化为 available 或 locked。移出 active plan 的旧
progress/evidence 不在 activation 时删除，roadmap/progress 汇总只读取 active revision
节点。

`MasteryProjector` 只消费 persisted trusted evidence summary，按 independence 权重产生
`confidence`、`mastery_level`、strength/weakness 与 projector version。它不依赖 provider，
同一有序 evidence 集可确定性重算。

本地 data summary/export 包含 LearningTrack、revision、node/progress 与 bounded mastery
state，但不导出 raw `plan_json` 或 evidence body/hash。confirmed reset/delete 先将该
用户仍 active 的 interactive runs 安全 terminalize，再在 transaction-local purge capability
下按 run/conversation scope -> mastery -> progress/migration -> node/module -> active pointer ->
child-first revision -> track 的外键顺序清理，并删除该用户 API idempotency；cutover
inventory 将任一新 track/scope/evidence 行视为 target contamination，绝不在切换中删除。

## 6. Skills、capability、effects 与执行器

- Skills 以 Git-owned catalog 的 exact `id@semantic-version` 选择，永久保存
  evidence hash。别名、范围、`current` 与未知 Skill 不能成为 durable proof。
- capability/effect descriptor 只允许声明字段；模型正文不能成为 URL、文件路径、
  shell/SQL、用户 ID、镜像、命令或数据库 target。
- `tutor_execution_intents`、`tutor_execution_jobs`、
  `tutor_execution_attempts`、`tutor_executor_health` 是 explicit-only
  container executor 的 durable queue/health 事实。API、普通 worker 和
  Desktop 不导入 runtime client，也没有 host subprocess fallback。
- Proactive origin 永远不允许 `runner.execute` 或 learner-code execution。

## 7. Proactive scheduler 与 curation 队列

| 表 | 责任 | 默认/安全边界 |
| --- | --- | --- |
| `tutor_proactive_preferences` | 每用户 `enabled` 与 `hard_paused` | 默认 `enabled=true`、`hard_paused=false`；bootstrap 将旧的未暂停 disabled preference 恢复为 enabled |
| `tutor_proactive_signals` | safe signal、source hash、dedupe/disposition | interactive terminal metadata 仅含 run ID/outcome/time hash；不保存 message/prompt/code/trace/provider diagnostic |
| `tutor_proactive_candidates` | durable candidate、lease、retry、no-action | `(user_id, dedupe_key, dedupe_bucket_at)` 唯一；verified gate/pause/budget/cooldown/concurrency/circuit 必须通过 |
| `tutor_scheduler_audit` | scheduler decision evidence | 仅保存安全 code/details，支持审计不泄露内容 |
| `tutor_memory_curation_outbox`、`tutor_curation_proposals` | redacted compaction/proposal envelope | 非 raw provider payload store |
| `tutor_curation_jobs` | curation lease/retry lifecycle | 默认 budget/output tokens 为 0，inferred memory 默认关闭 |
| `tutor_curation_projection_receipts` | 正常 policy/service validation 后的 projection 结果 | 只能记录 committed/no-action/stale/failed 的安全事实 |

生产 `scan_due_signals` 的 `user_id=None` 语义是全局队列扫描。repository 支持
显式 user scope 仅供 fixture/maintenance isolation；它不能改变正常 worker 的
全局行为。

## 8. Learner-state projections

| 表 | 当前业务事实 | 不变量 |
| --- | --- | --- |
| `tutor_plan_revisions` | 不可变 plan revision | revision 含 evidence、diff 与 predecessor；不会写旧 `learning_plans` |
| `tutor_active_plans` | 唯一可变 active pointer | 只能指向当前用户 revision |
| `tutor_plan_revision_actions` | append-only activation/rollback action | 用户 rollback 只可回到直接 predecessor |
| `tutor_memory_preferences` | inferred-memory setting/version | setting version 使 stale queued work 失效 |
| `tutor_memory_entries` | objective fact 或 inference | correction 追加 replacement；delete 是受控 state transition |
| `tutor_context_summaries` | safe compacted context projection | bounded source/evidence，非 prompt/history dump |
| `tutor_activity_records` | append-only learner-safe activity | 可从 effect/run 追溯，但不含 internal payload |
| `tutor_inbox_items` | 一条 activity 对应的可读/dismiss 投影 | `unread/read/dismissed` 生命周期与时间戳约束 |

## 9. 公开投影与删除规则

- repository 是唯一可将表行转成 API/SSE payload 的层；SQL/JSONB 不得被 route
  直接串行化为用户输出。
- `tutor_messages` 的 raw learner content 不复制到 event、trace、outbox、
  inbox、activity、capability/effect receipt 或 idempotency response。
- 所有 user-scoped query/mutation 都显式带 user ID；复合外键、unique constraint、
  lease generation、CAS 和 `FOR UPDATE SKIP LOCKED` 防止跨用户和重复 worker 写入。
- 删除本地用户是显式 confirmed 用户数据操作。cutover 不是“reset”捷径，且
  pre-cutover target state 不能用普通 reset 清空。

## 10. 历史表与当前读取规则

旧表仍可能包含 `learning_plans`、`plan_modules`、`knowledge_points`、
`exercises`、`attempts`、`review_states`、`review_logs`、`notes`、
`onboarding_*`、`learning_messages` 和 `review_messages`。在当前代码中：

- 它们不构成 `/api/tutor` 的输入、上下文、effect 或 UI state。
- `harness_cutovers` 只能把它们作为 server-side inventory/delete target，
  并在成功后验证同一 scope 已清空。
- 历史概念如 Attempt、FSRS、hidden tests 与 source attribution 不会被 Tutor
  API 重建、展示或静默写入；历史归档不会被当作 current runtime source。

## 11. Schema 验证

执行顺序必须串行，避免共享 PostgreSQL bootstrap fixture 并发导致 deadlock 或
`tuple concurrently updated`：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py tests/test_learning_track_repository.py tests/test_harness_cutover.py
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_repository.py tests/test_tutor_proactive_default_delivery.py
```

完整命令、结果和 residual risk 以
[Release Readiness Ledger](../qa/tutor-harness-release-readiness.md) 为准。
