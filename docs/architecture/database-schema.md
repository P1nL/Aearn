# Aearn 数据库 Schema 与持久化契约

**状态：** 当前 schema 说明，2026-08-14。
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
| `tutor_conversations` | user-scoped learner-visible/internal conversation 根 | `visibility` 与 `kind` 区分公开交互和内部 proactive conversation；learner conversation 的 `title` 只能保存安全模型简述，`NULL` 对外投影为“新对话”；`last_public_activity_at` 是列表排序 authority；`next_public_event_sequence` 与 `control_version` 均从 1 开始 |
| `tutor_messages` | canonical learner/Tutor public message body + bounded public thinking narration | 唯一允许存放原始 learner 文本的 Tutor 表；Tutor 回复可保存最多 4 条 learner-visible `public_thinking_steps_json`，它不是 provider-native reasoning；不可作为 trace/export dump；旧 message-only conversation 继续可读并投影空数组 |
| `tutor_message_context_references` | learner message/run revision 的 append-only learner-safe artifact snapshot | 复合 FK 固定 user/conversation/run/message/input revision；只保存 bounded safe projection/hash，不复制 learner content、submission、hidden/private artifact 或 raw execution/provider 数据 |
| `tutor_catalog_snapshots` | reviewed Skill catalog digest snapshot | run 只能引用已持久化的 digest |
| `tutor_runs` | 有限 loop / public turn 的 durable snapshot | `origin` 为 `interactive/proactive`；`interaction_protocol_version` 区分 `legacy_v1/thread_turn_v2`；retry predecessor/root 通过 user+conversation scoped FK；lease、budget counter、`input_revision`、terminal outcome 和 `next_event_sequence` 都由 DB 保护；`continuation_kind` 只允许 `clarification/planning_input/approval/capability_result/external_result` |
| `tutor_provider_attempt_receipts` | 每个实际 provider HTTP attempt 的 append-only usage 事实 | identity 为 `(run_id,input_revision,decision_iteration,attempt_index)`；复合 FK 固定 user/run/conversation scope；只保存受限 provider/model/protocol、outcome/diagnostic 和非负 token 数，不保存 prompt、response body、reasoning 文本、URL/header 或 credential |
| `tutor_run_public_processes` | 一条新 interactive run 对应一条 server-safe public-process projection | 只允许 `thinking/waiting_input/waiting_approval/waiting_authority/completed/interrupted/superseded/unavailable/failed`，只保留 timestamps、关联 public Tutor message 和固定 step key；不存 reasoning、provider payload、prompt、trace 或工具参数 |
| `tutor_run_public_process_steps` | append-only public-process step order | `(run_id, ordinal)` 唯一；step key/state 均有 DB + repository allowlist；公开 label 在 read projection 映射而非存自由文本 |
| `tutor_run_skill_selections` | exact Skill evidence | `(run_id, input_revision)` 唯一；保存 id/version 与 manifest/instruction/evaluation hash |
| `tutor_run_input_events` | 已接受输入的 revision/event receipt | revision 在同一 run 内单调；普通消息一条一个 fresh run，只有 explicit continuation 才在同 run 增加 revision；用于 replay 与 stale-effect gate |
| `tutor_run_checkpoints` | metadata-only checkpoint | 不保存 assembled prompt、raw history 或 provider payload |
| `tutor_run_events` | run-local ordered event log | `event_sequence` 在 locked run row 上分配；SSE 只读取其安全后缀 |
| `tutor_conversation_events` | learner-safe conversation-global append-only event log | conversation row lock 分配严格递增 sequence；`event_key` 幂等；kind/payload version 闭合；turn/item reference 与 payload identity 必须一致；普通 UPDATE/DELETE 被 trigger 拒绝 |
| `tutor_interactive_dispatch_jobs` | one-row-per-run durable interactive dispatch authority | PostgreSQL state 为 `pending/leased/retry_wait/completed/dead`；claim 使用 `FOR UPDATE SKIP LOCKED`、owner/generation/expiry CAS、bounded retry/backoff；Celery 仅是 wakeup |
| `tutor_capability_invocations`、`tutor_effects` | capability/effect receipt | 当前 revision、lease、Skill evidence 与 policy 必须同时通过；stale/superseded effect 不调用 handler |
| `tutor_run_traces` | redacted diagnostic trace | trace 写入和导出都再次走 allowlist projection |
| `tutor_api_idempotency_records` | public Tutor / LearningTrack mutation replay | `(user_id, operation, idempotency_key)` 唯一；Tutor 输入与 `learning_track.*` mutation 都绑定 request hash 与安全 response JSON |

`POST /conversations/first-turn` 的 repository mutation 在一个 transaction 内创建 learner
conversation、fresh run、首条 learner message/input event 和 `input_received` process；任何
中间失败都会回滚，不留下空 conversation。普通 conversation-input 在 conversation lock
下先结束旧 foreground run、冻结其 process，再创建新 run。partial unique index
`uq_tutor_runs_interactive_foreground` 只允许同一 conversation 存在一条尚未 terminal、
cancelled 或 superseded 的 interactive foreground run。

历史与内部 run 明确保持 `legacy_v1`；新 learner-visible fresh turn 显式写
`thread_turn_v2`。同一输入事务还会插入/重新武装 dispatch job，并按 turn-created、message-added、
process-added 等 owning mutation 追加 conversation event；任何一步失败都会连同 message/run/job/event
整体回滚。continuation 重用同一 job row，但重置本次 dispatch 的 attempt budget，并递增 lease
generation 以 fence 仍在完成旧 revision 的 worker。

conversation event payload 只保存 turn 或 item reference、control version、safe dispatch code 和
attempt，不复制 learner content、Tutor message、prompt、reasoning、trace、provider body 或 capability
args。snapshot 在 learner conversation 上持有 share lock，再读取 active turn、typed timeline 与
当前 sequence；历史 conversation 无 event backfill 时仍从 message/process 表投影，stream cursor
指向 sequence 0。dispatch job 最终 `dead` 时同事务终结 run、冻结 failed process、追加 safe error
item projection 与 `dispatch_dead` event。

终态约束：`tutor_runs.terminal_outcome` 与 `terminal_at` 必须同时为 `NULL` 或同时
存在。terminal transition、safe event、trace 与 curation outbox 由同一事务维护，
避免暴露半完成状态。provider 返回后的 lifecycle write 再次检查 cancellation/supersede；
stale run 只能收敛到安全 cancelled/superseded projection，不能写 Tutor message、title、
capability receipt 或 effect commit。
已经真实发生的 provider attempt 是独立执行/成本事实：run loop 在 provider 返回后、业务结果门禁前持久化其安全 receipt，因此 superseded/cancelled run 可以保留 usage，但仍不能获得 message、title、capability 或 effect 写权限。`input_tokens` 已包含缓存读取；`uncached_input_tokens = input_tokens - cached_input_tokens`，不得把 cached 再加回总输入。provider reported `total_tokens` 与 calculated `input_tokens + output_tokens` 分列保存；usage 缺失用 `usage_available=false` 与 `NULL` 表示，不能伪装成零。

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
| `tutor_learning_plan_sessions`、`tutor_learning_plan_drafts` | planning lifecycle 与 immutable typed draft | session 保存 facts policy version；draft 保存生成时的 facts fingerprint/revision，确认时必须仍匹配 current projection |
| `tutor_planning_intake_facts` | append-only typed intake fact authority | field/value/revision/source evidence 都受 user/session/conversation/run/input 复合 scope；correction 追加 successor，current fact 是没有 `supersedes_fact_id` successor 的 confirmed leaf |
| `tutor_planning_question_events` | append-only stable question-state lineage | `question_key=field_key`；`previous_event_id` 每个 predecessor 最多一个 successor；current state 从 leaf 沿 predecessor 链解析，不能使用 `created_at` 或 UUID 猜测事务内顺序 |

PostgreSQL `now()` 在同一事务内稳定，因此同次 input 写入的 reopen、supersede 和
confirmed event 可以拥有相同 `created_at`。planning question current projection 必须先找
`previous_event_id` 没有 successor 的真实 leaf，再沿显式 lineage 回溯；
`uq_tutor_planning_question_events_previous` 阻止链分叉。`reasked_blocked` 是审计事件，
读取对外 question state 时跳过该节点并继续使用其 predecessor 状态。

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
| `tutor_context_summaries` | safe compacted context projection | v2 绑定 conversation、schema/policy、结构化 JSON、coverage、source hash 与 prior lineage；UPDATE 被 append-only trigger 拒绝，legacy 短摘要可保留但不进入 v2 loader |
| `tutor_activity_records` | append-only learner-safe activity | 可从 effect/run 追溯，但不含 internal payload |
| `tutor_inbox_items` | 一条 activity 对应的可读/dismiss 投影 | `unread/read/dismissed` 生命周期与时间戳约束 |

### 8.1 长对话结构化摘要

`tutor_memory_curation_outbox.projection_kind` 区分旧的 `memory_or_summary` 与
`context_summary`。v2 outbox 必须同时具备 exact schema/policy version、连续退休消息
ID/hash、conversation coverage cursor、source hash，以及成对的 prior summary
identity/hash；相同语义 evidence 在 high-water 与 terminal lifecycle 之间共用一个
curation idempotency key。`tutor_curation_jobs.projection_kind` 必须与 outbox 一致。

`tutor_context_summaries` 的 v2 row 通过 composite FK 证明 user/run/conversation、
outbox、covered message 与 prior summary 均在同一 scope。结构化列必须整组存在，
`source_hash`/`prior_summary_hash` 为 SHA-256，并使用
`(user_id, conversation_id, covered_through_created_at DESC,
covered_through_message_id DESC)` 检索最新 coverage。summary 内容不可原地 UPDATE；
纠正通过追加新 row。用户级 reset/delete 可按既有依赖顺序物理删除 summary
projection，但不能因此删除或改写 `tutor_messages`。公开 export 默认不暴露内部
`summary_json`。

## 9. 公开投影与删除规则

- repository 是唯一可将表行转成 API/SSE payload 的层；SQL/JSONB 不得被 route
  直接串行化为用户输出。
- `tutor_messages` 的 raw learner content 不复制到 event、trace、outbox、
  inbox、activity、capability/effect/provider-attempt receipt 或 idempotency response。
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

## 2026-08-10：计划制定持久化

`tutor_learning_plan_sessions` 是 user/conversation-scoped planning root，同一用户最多一条 `collecting | draft_ready` session；它保存 current draft pointer、确认 track、版本、facts policy version 与 allowlisted safe error，不保存 raw prompt/history/provider body/reasoning。`tutor_learning_plan_drafts` 保存确认所需的 profile、canonical plan、registry-owned source summary、content hash、source run/revision，以及生成时的 facts fingerprint/revision；草案 append-only，`(session_id,draft_version)` 与 `(source_run_id,source_input_revision)` 唯一。current pointer 使用 deferrable composite FK 保证 draft 属于同一 user/session。

`tutor_planning_intake_facts` 与 `tutor_planning_question_events` additive 地补足 draft 前的
规划 authority。事实 correction 和 question transition 都追加 row，不原地改写；复合 FK
把 source message/run/input revision 锁定到同一 user/session/conversation。local export 仅
输出 normalized value、lineage/source identity 与安全状态，显式省略 value/event hash 和
gate reason；reset/delete 按 question leaf-to-root、fact high-revision-to-low-revision、draft、
session 的顺序清理。cutover target inventory 已将四张 planning 表全部视为 target state。

## 2026-08-11：LessonDocument authority

`tutor_lesson_documents` 保存共享 immutable standard document 与 user/track-scoped
personalized document。standard 行没有 user/track owner；personalized 行必须引用匹配语言和 `knowledge_key` 的 standard document、active plan revision、profile hash 和可选 predecessor。canonical blocks、coverage、Gate slot 和引用集合进入 content hash。

`tutor_lesson_source_snapshots` 在发布事务中复制 registry/version/URL/section、grounding chunk ID、raw document hash、chunk hash、抓取/冻结时间和 bounded excerpt；它不对可替换的 `grounding_chunks` 建立删除阻塞 FK。`tutor_lesson_block_citations` 和 `tutor_lesson_gate_slots` 冻结 block-to-source 与公开 Gate contract。

`tutor_lesson_assignments` 保证每个 `track_id + knowledge_key` 最多一个 active assignment。开始后 `started_at`、document identity 与 activation lineage 不可改写；更新先创建 direct proposed successor。`tutor_lesson_authoring_runs` 保存 pending/claimed/running/terminal、lease、expected versions、source set、safe failure 和结果 identity；`tutor_lesson_authoring_attempt_receipts` 只保存 append-only provider/model/protocol/outcome/usage/hash metadata。

local export 包含 personalized blocks、assignment 与 citation metadata，但省略 evidence excerpt 全文、prompt/body/reasoning 和内部 quality details。reset/delete 在 transaction-local purge capability 下 child-to-root 删除 user-owned Lesson rows；共享 standard documents 与其 source snapshots 保留。cutover target inventory 只统计 personalized document、assignment 和 authoring run，不把共享 standard 内容归给某个用户。

## 2026-08-11：练习 Gate、Attempt 与模块诊断 authority

新练习 authority 由十二张 additive 表组成：`tutor_exercise_versions`、`tutor_exercise_private_rubrics`、`tutor_lesson_gate_bindings`、`tutor_lesson_gate_states`、`tutor_module_diagnostic_versions`、`tutor_module_diagnostic_sessions`、`tutor_module_diagnostic_items`、`tutor_exercise_attempts`、`tutor_exercise_attempt_submissions`、`tutor_exercise_attempt_results`、`tutor_exercise_hint_receipts` 和 `tutor_exercise_execution_links`。共享 exercise/diagnostic version 与 private rubric 不属于单个用户；binding/state、Attempt、submission/result/hint、diagnostic session/item 和 execution link 通过复合 FK 固定 exact user/track/plan/Lesson/diagnostic scope。

`gate_kind=knowledge_check | guided_practice | independent_practice` 继续描述 Lesson 教学形态；`requirement_kind=required | recommended | diagnostic` 单独控制路线阻塞。binding 和 exercise/rubric 由 canonical hash/version 冻结。Gate state 只允许 `available | in_progress | passed | remediation_required` 的受控生命周期；Attempt、submission、result、hint 与 execution link 为 append-only/immutable，普通 UPDATE/DELETE 被 trigger 拒绝。

`tutor_exercise_attempts` 使用 owner shape CHECK 分离 Lesson `run | submit` 与模块 `diagnostic_submit`。完整提交只保存在 `tutor_exercise_attempt_submissions.content_text`，公共读取和 export 只投影 hash/摘要。terminal `tutor_exercise_attempt_results` 每个 Attempt 最多一条；required submit 的 result、mastery evidence、Gate CAS、progress completion 和 unlock 在同一数据库事务内 exactly-once 投影。`run` 结果不进入 Gate/mastery/progress。

现有 `tutor_execution_intents` 通过 `source_kind=tutor_message | exercise_submission` 扩展，`tutor_execution_jobs` 通过 `owner_kind=tutor_effect | exercise_attempt` 扩展；两者使用 exact one-of CHECK 和复合 FK 保留旧 Tutor scope，同时允许 Gate 复用同一 claim/lease/launch-token/terminal 队列。Gate 路径不创建 Tutor conversation/message/effect。`tutor_exercise_execution_links` 固定 Attempt 到 existing intent/job 的一对一关系。

`tutor_mastery_evidence.evidence_effect` 区分 `reinforcing` 与 `observational_non_degrading`。失败或部分通过的模块诊断只追加 observation/weakness，不降低既有 confidence；全部核心能力独立达到版本化阈值后，session 才可引用 predecessor-linked proposed plan revision。只有 confirm transaction 可把 session 置为 `confirmed`、激活 successor、写 `diagnostic_skipped` 并重算下游 availability。

local export 省略完整 submission、hidden/private rubric/reference answer 和内部 execution 信息；reset/delete/cutover 在 transaction-local purge capability 下按 execution link/result/hint/submission/Attempt/Gate/diagnostic child-to-root 清理 user-owned rows。共享 curated exercise/diagnostic versions 与 private rubric 保留。Bootstrap twice 必须重复成功，并断言 owner/source one-of、scope FK、唯一性、immutability/lifecycle trigger 和索引存在。


## 2026-08-12：受控 Action Runtime 持久化

`tutor_action_invocations` 保存统一 action orchestration identity、exact descriptor/adapter、
run/input revision、lease owner/generation、action generation、idempotency/stable key、catalog/policy
证据与 resource fingerprint；不保存 raw arguments。其生命周期由数据库 trigger 与应用同一
迁移表约束，终态不可更新或普通删除。`tutor_action_attempts`、
`tutor_action_verifications`、`tutor_action_receipts` 都是 append-only evidence；只保存安全状态、
authority reference/hash、结果/验证 hash、稳定 diagnostic/recovery code 与有界 safe JSON。

Action 表不复制领域事实：`capability_invocation` 指向现有 capability receipt，`plan_draft`
指向 immutable plan draft，`execution_job` 指向现有 execution job/result，未来 effect 仍指向
原 effect receipt。`(run_id,idempotency_key)` 防止同 key 重复执行；current verified partial
unique index `(run_id,input_revision,stable_action_key)` 防止同 revision 的语义重复 action。
复合外键固定 invocation/receipt 的 run、user、conversation scope，parent/retry lineage 只能
留在同一 run。

Action reserve 必须匹配当前 `tutor_runs` 的 input revision、exact active lease owner/generation、
未过期 lease、catalog digest、policy fingerprint 与非 terminal/cancelled/superseded 状态。
本地 export 只返回 bounded action summary，不返回 raw result/hash；confirmed reset 使用既有
transaction-local purge capability 按 receipt -> verification -> attempt -> invocation 顺序删除。
cutover inventory 将四张 action 表视为 target state，不会在切换中静默清除。


## 2026-08-12：模型代码审核 authoring 与发布 authority

`tutor_model_review_authoring_runs`、`tutor_model_review_authoring_attempt_receipts`、
`tutor_model_review_candidates`、`tutor_model_review_validation_runs`、
`tutor_model_review_validation_checks`、`tutor_model_review_publications` 与
`tutor_model_review_evidence_receipts` 保存 user/track/Gate scoped 的生成、受控验证、发布和
learner assistance 事实。candidate 公共题面与 private rubric/test payload 分列并各自 hash；
provider candidate 只保存教学标题、学习者说明和候选代码，server-owned private payload 保存
受控 test DSL、expected outcome、finding/rubric/proof、score policy 以及完整
`template_id + template_version + template_contract_hash`。只有
`model-code-review.validate@1.0.0` 的 verified authority 才能原子发布
`tutor_exercise_versions` / `tutor_exercise_private_rubrics` 与 exact Gate binding。

共享执行队列新增 `source_kind=model_review_candidate` 与
`owner_kind=model_review_validation`，仍复用既有 intent/job/attempt、reviewed runtime lock、
lease、retry、cancel 与 terminal contract。trusted-input resolver 只在 exact claimed scope 读取
private DSL，并在 sandbox wire payload 中剥离 template test id、`candidate_expected_pass` 和
`proof_ids`；这些 metadata 只用于 API 侧验证结果与服务端模板预期是否一致。学习者 submit 为
`structured_answer`，完整 JSON 只
保存在 private submission 表；export 只投影 verdict 与用户 finding 的 id/kind/line/category/
severity 摘要。private candidate、rubric、test、matcher、proof 与 submission 自由文本均省略。

Authoring 对 candidate/validation/publication 的环形引用使用 `ON DELETE NO ACTION
DEFERRABLE INITIALLY IMMEDIATE`。`RESTRICT` 即使标记 `DEFERRABLE` 仍会立即检查，不能用于
transaction-local child-to-root purge。confirmed reset 先 terminalize 内部 proactive run，
删除 evidence/action/execution/check/publication/validation/candidate/author receipt/authoring，
再删除该 authoring 独占的 internal run/conversation；去个性化的 immutable published
exercise/rubric 保留。cutover inventory 将上述七张 user-owned 表显式计为 target state。

## 2026-08-12：Track-scoped ReviewSession 与调度 authority

正式复习由七张 additive user-owned 表组成：`tutor_review_schedule_states`、
`tutor_review_schedule_events`、`tutor_review_sessions`、
`tutor_review_warmup_receipts`、`tutor_review_items`、
`tutor_review_hint_receipts` 和 `tutor_review_finalizations`。schedule state 对
`track_id + knowledge_key` 唯一，并用复合 FK 固定 user/track/plan revision；event、warmup、
hint 和 finalization 是 append-only receipt。session 生命周期为
`blocked | active | ready_to_finalize | finalized | cancelled`，blocked 保持可恢复且不会占用
第二个 active session identity。

`tutor_exercise_attempts` 的 owner shape 增加 `review_submit`：必须同时绑定 exact
`review_session_id + review_item_id + track_id + plan_revision_id + knowledge_key`，并保存 expected
review session/item version。每个 review item 最多一个 Attempt；submission/result 继续使用既有
private artifact 和 immutable terminal result。执行依赖题复用 `tutor_execution_intents`、
`tutor_execution_jobs` 与 `tutor_exercise_execution_links`，不新增 queue 或 Tutor conversation。

warmup/hint/中间 Attempt 不更新长期 mastery/schedule。唯一 finalization 在一个事务中锁定
session、track、schedule 和 terminal Attempts，写一条 `tutor_review_finalizations`、一条
`tutor_review_schedule_events`、一条 `tutor_mastery_evidence(evidence_kind='review')` 并 CAS 更新
`tutor_review_schedule_states`。计划 revision 激活按稳定 `knowledge_key` 写 retained/suspended
migration event；确认的模块诊断 skip 建立低频 schedule。actionable due count 查询包括普通
`due_at <= now()` 和 `risk_level='critical'`，后者仅在其为当前节点前置知识时投影短 Gate。

local export 只包含 schedule/session/finalization 的有界摘要和 Attempt owner ID，不导出
context snapshot/hash、selection reason、完整 submission、private rubric/test 或 event state JSON。
reset/delete 使用既有 transaction-local purge capability，按 finalization/event/hint/result/
submission/Attempt/item/warmup/session/schedule 的 FK 逆序清理。cutover inventory 显式统计七张
review 表；bootstrap twice 必须断言 owner CHECK、复合 FK、唯一索引、lifecycle/immutable trigger
和 repeatable additive migration。


## 2026-08-12：Tutor message context reference authority

`tutor_message_context_references` 是 user-owned append-only 表。每行保存 exact
`user_id + conversation_id + run_id + message_id + input_revision + reference_index`，并用复合 FK 确保 learner
message、run 和 input event 属于同一作用域。`(run_id,input_revision,reference_index)` 与
`(message_id,reference_index)` 唯一；`reference_kind` 只允许 `lesson_selection | exercise_feedback |
execution_result | review_feedback`。普通 UPDATE/DELETE 由 immutable trigger 拒绝，用户级 confirmed purge 才能按
child-to-root 路径删除。

表中的 `safe_payload_json` 必须符合 `tutor_context_reference_v1`，`safe_payload_hash` 是 canonical JSON SHA-256。
artifact identity 列只保存必要的 track/knowledge/document/attempt/review session/exercise version/source version/hash；
公开读取会重新校验 safe payload hash。Lesson safe snapshot 保存服务端重建的 bounded excerpt；Attempt/Review snapshot
只保存 terminal outcome、score、assistance、safe feedback、capability scores 和公开时间；execution snapshot 只增加安全
job identity/state。不得存 learner message 的副本、完整 submission、private rubric/test/reference answer、raw stdout/stderr、
command/path/container、provider body、reasoning、credential 或 secret。

Tutor input 在外层事务中先创建/锁定 message、run input event 与 immutable run scope，再验证 source artifact 并插入全部
reference rows；任何 source/scope/version/hash/terminal 校验失败都回滚整条 input。History 按 message + reference index
重放，context loader 按 run + input revision 读取，因此后续 Lesson migration、Review schedule 更新或 artifact pointer 变化
不会改写既有快照语义。

local export 仅输出 safe reference projection 与 hash；reset/delete 在删除 Tutor message/run 前先删除引用。cutover target
inventory 把该表视为 pre-verification target state。bootstrap twice 必须断言复合 FK、唯一索引、kind CHECK、immutable trigger
和 repeatable additive schema 均存在。

## 2026-08-12：最终 schema 与迁移清单审计

`HarnessCutoverService` 的 target inventory 现在逐表列出每个 user-owned `tutor_*` 表，包括 run/message/run-event/conversation-event/interactive-dispatch job/trace/checkpoint、Action、execution attempt、Lesson source/citation/Gate slot/authoring receipt、Review 与 context reference descendants。只有无 learner ownership 的 `tutor_catalog_snapshots`、`tutor_executor_health`、去个性化 `tutor_exercise_versions` / `tutor_exercise_private_rubrics` 与 `tutor_module_diagnostic_versions` 被显式归类为 shared。

`test_cutover_inventory_explicitly_classifies_every_tutor_table` 读取真实 PostgreSQL `information_schema.tables`，要求 schema 中所有 `tutor_*` 表恰好等于 target inventory 与 shared allowlist 的并集；新增表若未分类会直接失败。target 任一行存在都会阻断 clean-slate cutover，防止把当前 Tutor/LearningTrack 状态与旧数据混合删除。

迁移策略保持非转换：旧 `learning_*`、user-level Tutor plan、旧 review/notes、旧 checkpoint 只参与 exact inventory/deletion，不会生成 LearningTrack、Lesson、Attempt、mastery 或 ReviewSession。普通 reset/delete 清理当前用户拥有的学习状态和私有提交，但保留共享 immutable exercise/catalog；feature rollback 不执行数据删除，也不把 verified receipt 回退为旧 runtime 入口。
