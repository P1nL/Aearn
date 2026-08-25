# Aearn 数据库 Schema 与持久化契约

**状态：** 当前 schema 说明，2026-08-25。
**权威来源：** `aearn/services/api/app/db/schema/__init__.py` 的显式 manifest、`aearn/services/api/app/db/schema/*.sql`、PostgreSQL bootstrap、
Tutor/LearningTrack repositories 与 schema/cutover tests。
**范围：** PostgreSQL 是 Tutor run、cutover receipt、背景队列和 learner-safe
projection 的唯一 durable authority；Desktop、Celery 和 provider 不拥有并行
状态机或迁移账本。

## 1. Bootstrap、迁移与范围原则

- `python -m app.db.bootstrap` 按 `SCHEMA_FRAGMENT_NAMES` 的显式顺序重复执行 12 个 Schema fragment。数字前缀只帮助阅读，执行顺序不依赖目录自然排序。当前仓库没有另一个可与其竞争的 Alembic/Graph migration path。
- 所有 fragment 在同一 caller-owned PostgreSQL connection 和最终提交事务中执行；loader 不 `commit`。bootstrap 使用 transaction advisory lock，并对 deadlock/serialization failure 做有界整事务重试，避免多进程启动或测试重复 bootstrap 留下部分 Schema。
- `load_schema_text()` 只提供 manifest 组合的只读视图；仓库不维护第二份聚合 `schema.sql`。
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
| `tutor_messages` | canonical learner/Tutor public message body + bounded public thinking narration | 唯一允许存放原始 learner 文本的 Tutor 表；新 Tutor 回复保存最多 1280 字符 `public_thinking_text`，legacy `public_thinking_steps_json` 只读兼容，CHECK 禁止双表示同时非空；二者都不是 provider-native reasoning |
| `tutor_message_context_references` | learner message/run revision 的 append-only learner-safe artifact snapshot | 复合 FK 固定 user/conversation/run/message/input revision；只保存 bounded safe projection/hash，不复制 learner content、submission、hidden/private artifact 或 raw execution/provider 数据 |
| `tutor_catalog_snapshots` | reviewed Skill catalog digest snapshot | run 只能引用已持久化的 digest |
| `tutor_codex_runtime_health` | dedicated `tutor-codex` worker 的共享 readiness authority | 仅保存 bounded status/generation/version/model/provider/protocol/safe code 与 heartbeat；新 Codex admission 必须读取 fresh exact row |
| `tutor_runs` | 有限 loop / public turn 的 durable snapshot | `origin` 为 `interactive/proactive`；`runtime_kind` 在创建时冻结为 `harness_v1/codex_sidecar_v1` 且不可更新；`interaction_protocol_version` 区分 `legacy_v1/thread_turn_v2`；retry predecessor/root 与 `response_to_request_id` 通过 user+conversation scoped FK；lease、budget counter、`input_revision`、terminal outcome、`completion_reason` 和 `next_event_sequence` 都由 DB 保护；新 v2 request 来源 turn 不持久化 waiting continuation |
| `tutor_interaction_requests` | typed learner/authority blocking request 与 resolution lineage | kind/actor closed union；每 conversation partial unique pending；source/answer turn 与 answer message 复合 scope；server-owned descriptor/presentation、planning catalog、approval identity、authority scope/hash、state/version/response-or-receipt hash 受 CHECK/FK/CAS 约束 |
| `tutor_provider_attempt_receipts` | 每个实际 provider HTTP attempt 的 append-only usage 事实 | identity 为 `(run_id,input_revision,decision_iteration,attempt_index)`；复合 FK 固定 user/run/conversation scope；只保存受限 provider/model/protocol、outcome/diagnostic 和非负 token 数，不保存 prompt、response body、reasoning 文本、URL/header 或 credential |
| `tutor_conversation_runtime_threads` | conversation-scoped Codex App Server thread authority | 一个 learner conversation/runtime 至多一个 active thread；external identity immutable/private；resume/compaction 只更新时间事实 |
| `tutor_run_runtime_bindings`、`tutor_runtime_item_receipts`、`tutor_runtime_public_errors` | fresh run/turn private correlation、append-only safe receipt 与 Aearn public error | external thread/turn/item identity 不进入公共 DTO；binding/receipt 受 input/lease/Runtime generation fence；receipt 不复制 raw text |
| `tutor_runtime_text_items` | owner-scoped raw reasoning/final-answer projection | reasoning 与 final answer 分 channel；sequence/hash/state/owner/FK 受约束；commentary/summary 不写入 text projection，只有安全 final answer 关联正式 Tutor message |
| `tutor_run_public_processes` | 一条新 interactive run 对应一条 server-safe public-process projection | 只允许 `thinking/waiting_input/waiting_approval/waiting_authority/completed/interrupted/superseded/unavailable/failed`，只保留 timestamps、关联 public Tutor message 和固定 step key；不存 reasoning、provider payload、prompt、trace 或工具参数 |
| `tutor_run_public_process_steps` | append-only public-process step order | `(run_id, ordinal)` 唯一；step key/state 均有 DB + repository allowlist；公开 label 在 read projection 映射而非存自由文本 |
| `tutor_run_skill_selections` | exact Skill evidence | `(run_id, input_revision)` 唯一；保存 id/version 与 manifest/instruction/evaluation hash |
| `tutor_run_input_events` | 已接受输入的 revision/event receipt | 普通消息与 typed response/verified authority receipt 都在 fresh run 上从 revision 1 开始；legacy continuation 才可能在旧 run 增加 revision；用于 replay 与 stale-effect gate |
| `tutor_run_checkpoints` | metadata-only checkpoint | 不保存 assembled prompt、raw history 或 provider payload |
| `tutor_run_events` | run-local ordered event log | `event_sequence` 在 locked run row 上分配；SSE 只读取其安全后缀 |
| `tutor_conversation_events` | learner-safe conversation-global append-only event log | conversation row lock 分配严格递增 sequence；v2 kind 包含 bounded `turn_output`；`event_key` 幂等；turn/item reference 与 payload identity 必须一致；普通 UPDATE/DELETE 被 trigger 拒绝 |
| `tutor_turn_public_thinking_streams` | 当前 foreground Turn 的可恢复公开思考前缀 | one-row-per-run；exact user/conversation/run/revision/decision/generation/provider-attempt fence；state=`active|complete|discarded|accepted`；`active` 文本仅通过累计安全检查、仍是 provisional，`complete` 表示完整 provider decision 已验证并与 stream exact match；不保存 raw provider 数据 |
| `tutor_interactive_dispatch_jobs` | one-row-per-run durable interactive dispatch authority | PostgreSQL state 为 `pending/leased/retry_wait/completed/dead`；claim 使用 `FOR UPDATE SKIP LOCKED`、owner/generation/expiry CAS、bounded retry/backoff；Celery 仅是 wakeup |
| `tutor_queued_inputs` | conversation-scoped pending input authority | `pending/claimed/cancelled` closed lifecycle；pending position partial unique；最多 10 项由 conversation lock 保护；enqueue key、item version、claimed turn/revision/mode 与原始结构化 input metadata 可重放 |
| `tutor_capability_invocations`、`tutor_effects` | capability/effect receipt | 当前 revision、lease、Skill evidence 与 policy 必须同时通过；stale/interrupted effect 不调用 handler；effect 可保存 retry-root logical action key，committed 语义动作全局唯一复用 |
| `tutor_run_traces` | redacted diagnostic trace | trace 写入和导出都再次走 allowlist projection |
| `tutor_api_idempotency_records` | public Tutor / LearningTrack mutation replay | `(user_id, operation, idempotency_key)` 唯一；Tutor 输入与 `learning_track.*` mutation 都绑定 request hash 与安全 response JSON |

`POST /conversations/first-turn` 的 repository mutation 在一个 transaction 内创建 learner
conversation、fresh run、首条 learner message/input event 和 `input_received` process；任何
中间失败都会回滚，不留下空 conversation。普通 conversation-input 在 conversation lock
下仅在 idle 时创建 fresh run；active、pending request 或 paused 状态写入 `tutor_queued_inputs`。
partial unique index `uq_tutor_runs_interactive_foreground` 继续保证每 conversation 至多一个 active
interactive foreground run，`uq_tutor_queued_inputs_pending_position` 保证 pending FIFO position 不重复。

历史与内部 run 明确保持 `legacy_v1`；新 learner-visible fresh turn 显式写
`thread_turn_v2`。同一输入事务还会插入 dispatch job，并按 turn-created、message-added、
process-added 等 owning mutation 追加 conversation event；任何一步失败都会连同 message/run/job/event
整体回滚。v2 continuation intent 创建 typed request 并终结来源 run；response/receipt 解决 exact
request 后创建另一条 fresh run/job。旧 `/runs/{run_id}/inputs` 的 same-run revision/job rearm 仅属
legacy compatibility，不得被新 v2 mutation 调用。

Queue edit/delete/reorder/claim 与 `queue_paused/queue_pause_reason` 都在 conversation lock 下执行。
claim transaction 才创建 message/run/input/process/job，并把 item 写为 claimed；重复 drain 因 active run
或 item state CAS 返回 no-op。`logical_action_key` 由 user、conversation、stable retry root、effect type 与
payload hash 计算；同 run/effect 先走原 receipt replay，不同 retry turn 遇到 committed key 复用 commit ID，
遇到 proposed/ambiguous key fail closed。

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


## 2026-08-18：Codex plan-drafting 受控切换

`tutor_codex_runtime_health` 是无 learner ownership 的 shared infrastructure。server-side policy 只有在 feature enabled 且 latest heartbeat 对 exact allowlisted Runtime version、`deepseek-v4-flash`、`aearn_deepseek`、`responses`、generation 和 freshness 全部通过时，才为全新 `plan_drafting` conversation 冻结 `codex_sidecar_v1`。既有 conversation 后续 fresh turn 与 Retry 继承原 Runtime；Queue item 只保存服务端冻结值，客户端字段不能影响。Harness/Codex worker 对同一 durable dispatch queue 按 `runtime_kind` 精确 claim，关闭 admission 不删除历史 binding/receipt，也不让 active run 跨 Runtime 续跑。

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
uv --directory .\aearn\services\api run python -m pytest tests/database/test_db_bootstrap.py tests/learning/test_learning_track_repository.py tests/integration/test_harness_cutover.py
uv --directory .\aearn\services\api run python -m pytest tests/tutor/test_tutor_run_repository.py tests/tutor/test_tutor_proactive_default_delivery.py
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


## 2026-08-14：类型化请求与权威续轮

`tutor_interaction_requests` 使用 `(id,user_id,conversation_id)` 与 `(item_id,user_id,conversation_id)`
复合 identity，`source_turn_id`、`answer_turn_id`、`answer_message_id` 和
`tutor_runs.response_to_request_id` 不能跨 user/conversation。`state=pending` 时 response/receipt hash、
answer lineage 与 `resolved_at` 必须为空；resolved state 必须有 `resolved_at`。partial unique index
`uq_tutor_interaction_requests_pending_conversation` 保证同一 conversation 最多一个 blocking request。

`planning_input` 只能保存七个 allowlisted key 与 `tutor_planning_questions_v1`；approval 必须保存
server-owned proposal identity/authority key/risk；authority request 必须保存 exact request hash，receipt
则绑定 issuer/subject/scope/request/result hash 与 verification result。公开 projection 从 typed columns 和
allowlisted JSON serializer 构造，不直接回放 provider JSON。cutover target inventory 已显式包含该表。


## 2026-08-14：thread/turn v2 全局 cutover authority

`tutor_thread_turn_cutovers` 保存单例 state/generation/summary hash/safe counts/block code/operator idempotency/timestamps；`tutor_thread_turn_cutover_events` 是 append-only 安全审计。两表是 shared infrastructure。preparing 下 legacy waiting run 失败并要求 fresh v2 turn，其他可取消 active run 立即 cancelled/清 lease；ambiguous effect/action receipt 保持原状并使 singleton blocked。enable 只允许 ready 的 exact generation+summary，rollback 只回到 ready/read-only，不恢复 legacy mutation 或数据。

## 2026-08-15：Tutor 公开思考文本流 authority

`tutor_messages` additive 新增 `public_thinking_text text NOT NULL DEFAULT ''` 与
`char_length <= 1280` CHECK；`chk_tutor_messages_public_thinking_single_representation` 要求
新文本非空时 `public_thinking_steps_json` 必为空。旧 steps 不回填、不改写，读取层以
`"\n\n"` 连接为统一纯文本；新消息只写文本列。

`tutor_turn_public_thinking_streams` 以 `run_id` 为主键，并通过
`(run_id,user_id,conversation_id)` 复合 FK 固定作用域。`input_revision`、
`decision_iteration`、`generation`、`provider_attempt` 建立 stale fence；state 仅为
`active | complete | discarded | accepted`，时间戳 CHECK 保证状态与
`completed_at/discarded_at/accepted_at` 一致。`thinking_text` 最多 1280 字符，
`next_chunk_sequence >= 1`，可选 `last_public_event_sequence` 复合 FK 指向同 conversation event。

begin/append/reset/complete/discard 每次都锁定当前 run/stream，验证 foreground、lease、revision、
generation 后，在同一短事务更新文本并追加 `turn_output`。`append` 只写累计安全的 provisional
前缀；provider transport EOF 只结束 projector 解析，不得把 stream 置为 `complete`。只有完整 decision
通过 schema/domain/安全校验并与 streamed text exact match 后，gateway 才调用 complete。成功终态消息
或 typed request 必须在同一事务比较最终 decision 文本、写 canonical public item、把 stream 置为
`accepted` 并追加 owning conversation events；任一步失败全部回滚。repair、context rebuild、Interrupt、
supersede、stale revision、lease loss 或失败路径只能 reset/discard，不得接受旧 generation。

该表纳入 cutover target inventory、local export/reset/delete child-first 清单与 bootstrap-twice
验证。公共表只保存 learner-safe 文本；raw JSON、provider reasoning/body/event、prompt、trace、
diagnostic、credential 和 secret 禁止落入该表、message 列或 conversation event。

## 2026-08-20：Conversation Runtime thread 与 raw text projection

| 表 | 责任 | 关键不变量 |
| --- | --- | --- |
| `tutor_conversation_runtime_threads` | 一个 learner conversation 对应的持久 Codex App Server thread | owner/conversation scoped FK；每 conversation/runtime 最多一个 active row；固定 `deepseek-v4-flash` + `aearn_deepseek`；external identity immutable/private；记录 native/adopted legacy/reseed lineage 与 resume/compaction 时间 |
| `tutor_run_runtime_bindings` | fresh TutorRun 到同 conversation thread 内一个新 Codex turn 的绑定 | 增加 conversation thread FK；run 仍唯一，external turn 唯一；不再要求 external thread 在 run binding 中唯一；input/lease/connection generation fence 仍控制投影 |
| `tutor_runtime_text_items` | owner-scoped raw reasoning 与 final-answer current/history projection | `(binding, external item hash, channel)` 唯一；channel/state/sequence/hash/connection generation 闭合；streaming 可追加，completed/discarded/blocked terminal immutable；completed item 仅允许一次关联同 conversation 正式 message |

`reasoning` 和 `final_answer` raw text 只存在 `tutor_runtime_text_items`，不得复制进 runtime receipt。phase 校正为 commentary 或任意 turn terminal 遇到未完成 item 时，必须把 row 转为 `discarded`，同时将 `text=''`、`content_hash=NULL` 并写入 terminal 时间，禁止留下可恢复的 commentary 或永久 `streaming` row。`tutor_runtime_item_receipts` 仍只保存 event/item kind、sequence、hash、safe code、projection status 和 Aearn public reference；commentary/summary 只能形成 nonpublic receipt。新表纳入 bootstrap twice、cutover inventory、owner-scope FK 和 transaction-local purge guard。删除顺序必须先 text item/receipt/error，再 run binding，再 conversation thread，最后才允许删除 owning run/conversation。

## 2026-08-21: Course intent taxonomy

| Table | Purpose | Boundary |
| --- | --- | --- |
| `tutor_learning_intents` | Shared closed planning-direction taxonomy | `intent_key`, state, display name, and policy version; classified as shared Tutor metadata |
| `language_course_intent_tags` | Course UUID to intent-key relation | composite primary key, rank `0..100`, primary marker, policy version, and restrictive foreign keys |

`assert_language_course_intent_coverage()` requires every active course to have an active tag and every active intent to have an active course. Deferred constraint triggers check the final transaction state for course publication, intent activation, and tag mutation. Bootstrap performs the only slug-based backfill, validates coverage, and is repeatable. Runtime shortlist queries join active course UUIDs and active tags and never inspect course slug, title, or description.

## 2026-08-21：Runtime source/projection sequence 与合并审计

`tutor_runtime_item_receipts.event_sequence` 保留为兼容列并与新增 `projection_sequence` 严格相等；所有 PostgreSQL reducer、`tutor_runtime_text_items.last_event_sequence`、conversation `turn_output.chunk_sequence` 与 Desktop reducer 都以 projection sequence 为顺序 authority。provider-normalized source sequence 不进入公共 DTO。

每个有 source evidence 的 receipt 必须同时保存 `source_sequence_start`、`source_sequence_end`、`source_delta_count` 与 `source_content_hash`。四者要么全部为空（仅允许本地 synthetic control/recovery event），要么形成闭合连续范围且 count 精确等于范围长度。字段只保存数字与 SHA-256；raw delta、reasoning/final text、provider body、external identity 和工具参数仍禁止进入 receipt。`tutor_runtime_text_items` 是 owner-scoped text authority，completed item 继续校准全文。

## 2026-08-23：TeachingSession durable authority 与 action receipt

一条 LearningTrack 继续只绑定一条长期 learner-visible Tutor conversation；知识点教学分段由 `tutor_teaching_sessions` 持久化，不创建并行聊天根。session 冻结 exact `user_id + track_id + conversation_id + knowledge_key`，以及 track version、active plan revision、progress version、active Lesson assignment/version、LessonDocument/content hash。partial unique 只约束 `active | paused` current session；authority 变化时旧 session 追加 `authority_pause` checkpoint 并置为 `blocked`，新 session 通过 `predecessor_session_id` 形成 immutable successor lineage。旧 conversation/history 不从聊天正文猜测或回填 session。

`tutor_teaching_session_checkpoints` 是 predecessor-linked append-only CAS 链。`session_version=1` 必须没有 predecessor，后继版本必须引用唯一 predecessor；session 的 `current_checkpoint_id` 与 `version` 一起推进。checkpoint 的 bounded typed state 只包含 objective、active/suspended focus、unresolved-question 摘要、covered concept、evidence cursor、pause reason 与 recommended action；raw prompt、provider reasoning/body、完整题目/提交、private test/rubric、command/path/secret 不进入公共投影或 export。

`tutor_run_stimulus_events` 对每个 teaching-scoped fresh run 保存且只保存一个 exact stimulus：`learner_message | teaching_control | domain_event`。learner stimulus 必须复合引用 exact `tutor_run_input_events(run_id,message_id,input_revision)`；control/domain stimulus 不创建伪 learner message，run origin 仍为 `interactive`，不能滥用 proactive。`tutor_run_teaching_scopes` immutable 冻结 session/checkpoint/stimulus 与 track/plan/progress/assignment/document fence。effect commit、waiting-result 和 terminal-result 持久化前重新读取 current authority；任一 scope/version/pointer 已变化都 fail closed，不能写 effect 或 learner-visible terminal output。

`tutor_teaching_action_receipts` 每个 run 最多一条，复合引用 exact run/session/new checkpoint/stimulus。row 只保存 closed action、objective/focus identity、focus resolution、pause kind、bounded source handles、public-message SHA-256 与 selected context IDs/hashes；不保存 public message 正文、provider body、prompt 或 reasoning。receipt 与 message/checkpoint/session/run terminal 在同一事务提交，普通 UPDATE/DELETE 由 append-only trigger 拒绝。

五张 user-owned 表全部属于 cutover exhaustive target inventory，并进入 local summary/export/reset/delete。删除在 transaction-local purge capability 下按 `action receipt -> run teaching scope -> stimulus -> checkpoint -> session` 执行，再清 Lesson/track root；session current-checkpoint、checkpoint predecessor/source-stimulus 与 receipt lineage 使用 deferred `NO ACTION`，使同一事务 child-to-root 清理可验证且 bootstrap twice 幂等。早期本地 `RESTRICT` source-stimulus FK 必须在 bootstrap 时 drop/recreate 为 deferred `NO ACTION`，否则已有 action checkpoint 的 reset 会在中途失败。

## 2026-08-23：Domain event admission 与 checkpoint-backed teaching summary

Gate/Attempt terminal、Review finalization、progress completion 与 Lesson assignment migration 不新增第二套业务事实表。各 owner 先提交既有 result/evidence/schedule/progress/assignment authority，`TeachingDomainEventAdapter` 再以 durable source ID/version 生成 `domain_event` stimulus。`uq_tutor_run_stimuli_domain(teaching_session_id,domain_event_kind,source_id,source_version)` 与 admission 前 exact receipt lookup 共同保证重复事件返回同一 run，而不是依赖 unique violation 创建孤儿 run。

长期 teaching summary 复用 `tutor_teaching_session_checkpoints` 的 append-only predecessor chain，不新增 mutable summary table。`teaching_session_summary_v1` 是受控投影：objective、active/suspended focus、unresolved questions、covered concepts、evidence cursors、pause/completion 与 source checkpoint/authority hashes。loader 每次重新验证 current checkpoint/session version、authority snapshot 与 canonical source hash；任一失配都不进入 provider context。current summary 进入 optional working-summary section，required teaching context 使用 compact authority projection；最多选择一个 exact predecessor summary，默认不全量重放长期 conversation。
