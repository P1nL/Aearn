# Aearn 数据库 Schema 与持久化契约

**状态：** 当前 schema 说明，2026-09-02。
**权威来源：** `aearn/services/api/app/db/schema/__init__.py` 的显式 manifest、`aearn/services/api/app/db/schema/*.sql`、PostgreSQL bootstrap、
Tutor/LearningTrack repositories 与 schema/cutover tests。
**范围：** PostgreSQL 是 Tutor run、cutover receipt、背景队列和 learner-safe
projection 的唯一 durable authority；Desktop、Celery 和 provider 不拥有并行
状态机或迁移账本。

## 1. Bootstrap、迁移与范围原则

- `python -m app.db.bootstrap` 按 `SCHEMA_FRAGMENT_NAMES` 的显式顺序重复执行其中登记的 Schema fragment（数量以 manifest 为准）。数字前缀只帮助阅读，执行顺序不依赖目录自然排序。当前仓库没有另一个可与其竞争的 Alembic/Graph migration path。
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

`tutor_codex_runtime_health` 是无 learner ownership 的 shared infrastructure。server-side policy 只有在 feature enabled 且 latest heartbeat 对 exact allowlisted Runtime version、`deepseek-flash`、`aearn_deepseek`、`responses`、generation 和 freshness 全部通过时，才为全新 `plan_drafting` conversation 冻结 `codex_sidecar_v1`。既有 conversation 后续 fresh turn 与 Retry 继承原 Runtime；Queue item 只保存服务端冻结值，客户端字段不能影响。Harness/Codex worker 对同一 durable dispatch queue 按 `runtime_kind` 精确 claim，关闭 admission 不删除历史 binding/receipt，也不让 active run 跨 Runtime 续跑。

## 5. LearningTrack、计划路线、掌握度与教学 scope

### 2026-09-13：Frozen catalog scope

增量 fragment `220_plan_catalog_knowledge_scope.sql` 为 `tutor_track_plan_nodes`
增加可空 `catalog_knowledge_key`。INSERT guard 将非空映射与 immutable revision
`plan_json` 中的同节点映射/能力对照，并验证同语言、能力兼容的 published catalog；
旧 null 行与其 hash 不被回填改写。`tutor_plan_catalog_knowledge_key` 按
user/track/revision/node 精确解析，`tutor_artifact_catalog_knowledge_key` 经 Artifact
绑定的 TeachingSession frozen revision 解析。不存在或跨 scope 时 fail closed。
Artifact/Attempt owner guard 只用映射检查内容身份，根 `knowledge_key`、session/
assignment/version guard 和正式 Gate 的 progress owner 仍保持原路线节点身份。
修改映射必须发布新计划 revision；不得重标 published item、复用其他节点成绩或
改写旧 session/Attempt。仅内容映射并不构成学习完成、真实执行或独立内容覆盖证据。

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

### 2026-09-08：Lesson attempt 安全诊断

`tutor_lesson_authoring_attempt_receipts.diagnostic_json` 为 `jsonb NOT NULL DEFAULT '{}'`，数据库 CHECK 要求 object。fresh create 和 additive `ADD COLUMN IF NOT EXISTS` 同时维护；历史行保持空对象兼容，无新增 user-owned 表或删除顺序变更。

2026-09-08：应用侧私有诊断继续读取空对象和 `lesson_author_attempt_diagnostic_v1`；新响应元数据使用 `lesson_author_attempt_diagnostic_v2`，增加封闭的 `provider_response`（状态、截断原因枚举、请求输出额度/思考强度、可见输出字符数）与可空的 `reasoning_tokens`。未知用量保留 NULL；reasoning 是 output 的子集，不再次累加总用量。不得存入原始响应、思考正文或任意 provider 错误文本；公共 API/SSE/用户导出不投影这些诊断。复用现有 JSONB 列，不需要新增数据库迁移或回填历史记录。

新诊断只允许版本、standard/personalized document kind、文档内 attempt index、失败阶段、稳定 issue codes/locations 和 feedback hash。constraint 文本、prompt、provider body、reasoning、raw candidate、credential 不持久化。receipt 的 success 只在 parse/identity/quality 全部通过后记录；每次失败仍单独记录，`(run_id, attempt_index)` identity、append-only trigger 和 usage 缺失时 NULL 语义保留。

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
| `tutor_conversation_runtime_threads` | 一个 learner conversation 对应的持久 Codex App Server thread | owner/conversation scoped FK；每 conversation/runtime 最多一个 active row；固定 `deepseek-flash` + `aearn_deepseek`；external identity immutable/private；记录 native/adopted legacy/reseed lineage 与 resume/compaction 时间 |
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

`tutor_teaching_action_receipts` 每个 run 最多一条，复合引用 exact run/session/new checkpoint/stimulus。v2 row 在既有 closed action、objective/focus identity、focus resolution、pause kind、bounded source handles、public-message SHA-256 与 selected context IDs/hashes 上，新增 `teaching_moves_json`、`learner_response_mode`、`schema_version=teaching_action_receipt_v2` 与 `policy_version=lesson_teaching_policy_v2`；不保存 public message 正文、provider body、prompt 或 reasoning。DB CHECK 要求 v2 有 2--4 个 closed、互不重复的 moves，并约束 composer/action 兼容；v1 默认空 moves/none 以兼容历史行。receipt 与 message/checkpoint/session/run terminal 在同一事务提交，普通 UPDATE/DELETE 由 append-only trigger 拒绝。

五张 user-owned 表全部属于 cutover exhaustive target inventory，并进入 local summary/export/reset/delete。删除在 transaction-local purge capability 下按 `action receipt -> run teaching scope -> stimulus -> checkpoint -> session` 执行，再清 Lesson/track root；session current-checkpoint、checkpoint predecessor/source-stimulus 与 receipt lineage 使用 deferred `NO ACTION`，使同一事务 child-to-root 清理可验证且 bootstrap twice 幂等。早期本地 `RESTRICT` source-stimulus FK 必须在 bootstrap 时 drop/recreate 为 deferred `NO ACTION`，否则已有 action checkpoint 的 reset 会在中途失败。

## 2026-08-23：Domain event admission 与 checkpoint-backed teaching summary

Gate/Attempt terminal、Review finalization、progress completion 与 Lesson assignment migration 不新增第二套业务事实表。各 owner 先提交既有 result/evidence/schedule/progress/assignment authority，`TeachingDomainEventAdapter` 再以 durable source ID/version 生成 `domain_event` stimulus。`uq_tutor_run_stimuli_domain(teaching_session_id,domain_event_kind,source_id,source_version)` 与 admission 前 exact receipt lookup 共同保证重复事件返回同一 run，而不是依赖 unique violation 创建孤儿 run。

长期 teaching summary 复用 `tutor_teaching_session_checkpoints` 的 append-only predecessor chain，不新增 mutable summary table。`teaching_session_summary_v1` 是受控投影：objective、active/suspended focus、unresolved questions、covered concepts、evidence cursors、pause/completion 与 source checkpoint/authority hashes。loader 每次重新验证 current checkpoint/session version、authority snapshot 与 canonical source hash；任一失配都不进入 provider context。current summary 进入 optional working-summary section，required teaching context 使用 compact authority projection；最多选择一个 exact predecessor summary，默认不全量重放长期 conversation。

## 2026-08-27：Teaching action receipt v2

`080_lesson_teaching_practice.sql` 对既有 `tutor_teaching_action_receipts` 做 additive bootstrap：`teaching_moves_json JSONB NOT NULL DEFAULT '[]'::jsonb`、`learner_response_mode TEXT NOT NULL DEFAULT 'none'`、`schema_version TEXT NOT NULL DEFAULT 'teaching_action_receipt_v1'` 与 `policy_version TEXT NOT NULL DEFAULT 'lesson_teaching_policy_v1'`。历史 v1 row 因默认值继续可读；新提交只能写 v2 schema/policy。

repeatable bootstrap 先删除旧同名自动 CHECK，再建立稳定命名的 moves、response-mode 与 version-shape constraints。v2 moves 必须是长度 2--4 的 JSON string array，值属于 closed enum且位置不重复；composer 只与 `check_understanding | wait_for_input` 共存，none 禁止这两个 action。receipt 仍 append-only，local export 只增加 safe moves/mode，不增加 public message、prompt、provider body 或 reasoning。

## 2026-09-01：Teaching Artifact commit、branch lineage 与 continuation intent

`tutor_teaching_action_receipts` additive 支持 `teaching_action_receipt_v3 / lesson_teaching_policy_v3`。v3 仅在 learner response mode 为 Artifact 时保存 exact interaction intent、`li:<sha256>` handle、Artifact id、Artifact event id 与 sequence；none/composer 继续使用 v2 shape。receipt、Tutor message、next checkpoint/session CAS、Learning Artifact/event、conversation `item_added` 和 source Turn terminalization由同一 transaction 提交，任一 FK/CHECK/CAS/event failure 整体回滚。

Learning Item-backed Artifact owner 固定 immutable version id 与 latest published state version。materialization 必须匹配 public/content hash、Practice exercise/rubric receipt、capability set、runtime profile 和 current TeachingSession fences；表约束不允许把 Learning Item facade误绑定为 Gate/Review authority，也不产生 Attempt、score、mastery 或 progress row。

`tutor_conversation_branches` 保存一个 blocking Artifact 下的 durable depth-one branch root、predecessor branch、current event、version/round、latest disposition 与 resolved Turn。`tutor_conversation_branch_events` 是 predecessor-linked append-only CAS lineage；`tutor_conversation_branch_items` 显式记录 learner/Tutor message 与 process membership；`tutor_run_branch_scopes` 冻结 source input、branch round、Artifact、TeachingSession/checkpoint 与 closed classification/control。partial unique 与 scope FK 禁止同一 Artifact 多 active branch、nested branch、跨 conversation/user/track binding 和 item 重归属。

`tutor_continuation_intents` 保存 exact Artifact/session/checkpoint/track/progress/assignment fence、source kind/id/version、fixed priority、idempotency hash、not-before、state/version、claim owner/generation/expiry 与 consumed run；`tutor_continuation_intent_events` 保存 append-only transition evidence。一个 conversation 同时最多一条 claimed intent。claim 前必须确认没有 active foreground run、pending learner input 或 active branch，并重新验证 Artifact/session versions 与 checkpoint ancestry；stale intent转 cancelled，过期 claim按 generation release。producer 只写 intent，不创建 run或调用 provider。

branch/continuation 六张表属于 user-owned cutover target。local export 只能输出 bounded state/count/identity summary；reset/delete 按 event/item/run-scope/intent child-to-root 清理。conversation snapshot 仅在 branch history 存在时投影 v5。repeat bootstrap 必须保留早期 fragment 110 对 persisted `tutor_conversation_event_v3` row 的兼容，否则 schema 120 之前会因 projection-version CHECK 失败。

### 2026-09-13：Branch authority retirement

增量 fragment `210_tutor_branch_supersession.sql` 增加 branch `superseded` 终态、`superseded_by_session_id` 与 `superseded_at`；它不表示正常答疑完成，`resolved_turn_id/resolved_at` 必须为空。旧 `active/resolved` 行不被迁移改写。`authority_superseded` 是 append-only branch event，保存 `superseding_session_id`，不带 source input、provider response、disposition 或 assistance receipt；已有事件类型仍必须拥有完整 source input。

TeachingSession owner 在一个 caller-owned transaction/savepoint 内阻塞陈旧会话、建立真实 successor、调用 branch owner 追加事件并推进 branch CAS。数据库与 owner 都验证直接 predecessor、相同 user/conversation/track/knowledge、不同 authority snapshot、旧 session 已 blocked 且没有未终态 run；终态 root 不可再改。branch round、items、旧 disposition、Attempt 与学习进度均不重写。Python/SQL active-branch guard 不放宽；旧 Artifact 的内容保持不变，生命周期退役遵循下节独立合同。

历史修复必须使用明确范围、有限且无环的 predecessor 链，先只读 dry-run，再核对当前 authority 与预期版本，通过 owner 处理；不得直接 UPDATE 状态或顺便调度陈旧 intent。local export 保留新的 retirement identity/timestamp，不把空 source input 补成旧 learner/Turn 来源。

### 2026-09-15：Blocked TeachingSession Artifact retirement

增量 fragment `230_artifact_authority_supersession.sql` 不改写数据。正常 TeachingSession open 在 conversation lock 和同一事务内，仅沿同 user/conversation/track/node、最多 32 层且全部 blocked 的祖先链，通过 Artifact owner 将最多 64 个非终态旧工件置为 `superseded`。正在运行或有未终态 Attempt 的工件必须先完成或取消，不可退役绕过。重复 open 不增加事件或版本。

数据库的历史例外仅允许 `pending/ready/active → superseded`、version +1、清空 actions 并设置 terminal timestamp；其余冻结字段必须逐项保持不变。它要求真实且匹配当前 track/plan/progress/assignment 的 successor、同范围 checkpoint；教学 owner 的冻结 session version 对照原 checkpoint 而非已经 blocked 后的新 version。Gate/Review owner 保留身份和范围，退役不要求其可变版本仍为当前版本；Learning Item 仍校验原 published receipt、Practice materialization、kind 和 difficulty，Turn/Attempt scope 不豁免。

deferred constraint trigger 在 COMMIT 验证对应版本、scope、确定 event key、predecessor/successor 及 reason code 的 append-only terminal event。缺 receipt、篡改题面或冻结 owner 的直接 UPDATE 均失败。正常 owner 同时发布 conversation `item_updated`；退役不生成 Attempt、score、mastery、进度或模型调用。

## 2026-09-01：Terminal execution result projection

本增量不增加新的业务 authority 表。`tutor_execution_jobs.result_json` 对新完成 job 保存 strict `safe-execution-result-v2`；历史无版本 v1 row 继续由 reader adapter 转成 v2 `presentation=none`。`tutor_exercise_attempt_results.safe_feedback_json` 保存同一 learner-safe v2 JSON，Attempt result hash、outcome、score 与 policy 仍由 Gate/Review scorer authority 生成。

每个 terminal Artifact-linked Attempt 通过现有 `tutor_learning_artifacts / events / references / attempt_links` 投影：source Artifact 追加 exact `execution-result:<attempt_id>` owner event；result Artifact 使用 deterministic `execution-result:<attempt_id>` creation key，固定 `artifact_kind=test_result,purpose=result,state=completed,blocking=false`，并引用 source Artifact 的新 version 以及 exact Attempt result hash。该 durable result row 在评价 Turn 完成前不进入 conversation timeline；Turn terminal transaction 先追加 Tutor Markdown message item，再追加 exact result Artifact item，二者同事务提交或回滚。repository 在重放时同时验证 source event 与 result Artifact；只存在一侧视为 partial persistence 并 fail closed。多个 Attempt 保留独立 result Artifact，source Artifact 只投影最新 Attempt。

result-evaluation 复用 `tutor_continuation_intents`。intent 的 Artifact 是 result Artifact，source ID/version 是其 exact created event，idempotency key 为 `result-evaluation:<event-id>`；调度和 Teaching context 重新验证 user/conversation/track/knowledge/session、Artifact kind/state/presentation、Attempt identity 与 event sequence 后才消费。pending Attempt 不写 result Artifact 或 intent。以上写入由 caller-owned transaction 包含；provider failure 不修改或删除已提交的 Attempt/result。


### `tutor_demonstration_completion_receipts`

Append-only, user-scoped receipt for one completed `demonstration_v2` Artifact. It binds the Artifact version and descriptor hash to either exact isolated-Preview event evidence or bounded visible-clock evidence. The table is purge-aware, exported only as a redacted summary, and is not an Attempt/mastery/progress authority.

## 2026-09-02：Knowledge Check receipt authority

schema fragment `180_knowledge_checks.sql` 新增 user-owned append-only `tutor_knowledge_check_response_receipts` 与 `tutor_knowledge_check_assistance_receipts`。response 每 Artifact 最多一条，绑定 exact user/conversation/track/knowledge/TeachingSession/checkpoint/Learning Item/Artifact version、closed response kind、response/result hash、outcome、assistance kind 与 scorer policy。数据库 CHECK 只允许 `outcome=correct AND assistance_kind=independent` 标记 independent mastery eligible；direct-answer response 固定为安全 marker shape，不保存公开答案 authority。

assistance receipt 对每个 Artifact 的 H1/H2/H3 与 direct answer 分别 exactly-once。scope trigger 要求 Artifact 仍是 exact active/ready Learning Item knowledge check；普通 UPDATE/DELETE 以 `23514` 拒绝，transaction-local user purge 才允许删除。通用 trigger 必须先按 `TG_TABLE_NAME` 分支再读取 response 表专属字段，避免在 assistance trigger record 上解析不存在列。

两张表属于 cutover target，并进入 local summary、安全 export、reset/delete 的 child-to-root 顺序。fragment 170 提前兼容 additive `request_direct_answer` action，fragment 110 继续在 schema 120/180 前接受 persisted `tutor_conversation_event_v3`；显式 bootstrap-twice 回归验证既有 v3 row、default 与 v1/v2/v3 CHECK 均保留。


## 2026-09-02：对话内模型审查 Artifact receipt

`190_model_review_artifacts.sql` additive 扩展 Learning Artifact presentation kind，使
`model_code_review_v1 | model_code_review_v2` 同时可读，并把 presentation JSON 上限提高到
196,608 bytes 以容纳 server-built code/diff line map。早期 `120_learning_artifacts.sql` 与
`170_teaching_demonstrations.sql` 已提前接受 v2 kind，保证已有数据重复 bootstrap 在抵达 fragment
190 之前不会暂时违反 CHECK；`110_thread_turn_codex.sql` 继续接受持久化
`tutor_conversation_event_v3`。

`tutor_model_review_artifact_receipts` 是 user-owned append-only private authority，一条 Artifact 最多
一条 receipt。复合 FK 固定 artifact/user/conversation/TeachingSession/track，普通 FK 固定 exact
Learning Item version 与 Practice exercise version；trigger 在 insert 前锁定并复核 active/ready v2
Artifact、knowledge/checkpoint/owner/version/materialization。表保存完整 submission JSON/hash、verdict、
outcome/score、assistance、safe feedback、result/remediation/policy/receipt hash；CHECK 要求 failed 必有
`li:<sha256>` remediation、passed 必无 successor，submission schema/hash 必须匹配 presentation。
普通 UPDATE/DELETE 由既有 Artifact append-only guard 拒绝；只有 transaction-local user purge 可
child-first 删除。

该表进入 exhaustive cutover target inventory、本地 summary count、safe export 与 reset/delete。export
只列 scope、verdict、outcome、score、assistance、successor、policy 和时间；省略完整 submission、
safe-feedback body、presentation/submission/result/receipt hash、private rubric/test/proof。删除顺序在
Artifact event/root 之前清理 receipt，不能因新增 private child 破坏 confirmed reset。

## 2026-09-02：SQL Learning Workspace Attempt owner

`200_sql_learning_workspace.sql` additive 允许 `sql_workspace_v1 | sql_workspace_v2` presentation，
为 `tutor_exercise_attempts` 增加 nullable `learning_item_version_id`、FK 和 partial index，并扩展
owner-shape/`tutor_learning_artifact_attempt_owner_matches`。Learning Item SQL Run 必须是 `attempt_type=run`、
绑定当前 lesson assignment/document 与 materialized ExerciseVersion、没有 Gate/diagnostic/review binding，且 exact
Learning Item latest publication state 为 `published`。普通 Gate/Review/Teaching Attempt 必须保持
`learning_item_version_id IS NULL`。

repeat bootstrap 在抵达 fragment 200 前会重新应用早期约束，因此 fragment 100 已提前声明该列并接受后来
合法的 Learning Item-owned Run，fragment 160 允许 Learning Item source 的 `test_result/purpose=result`
投影，fragment 170/190 提前接受持久化 `sql_workspace_v2`。fragment 110 的
`tutor_conversation_event_v3` projection-version compatibility 保持不变。bootstrap twice 与 schema
manifest test 必须同时覆盖已有 SQL v2 Artifact/Attempt 和完整显式 fragment 顺序。


## 2026-09-02：Learning Artifact platform final schema reconciliation

The explicit manifest contains 21 fragments from 000_foundation.sql through 200_sql_learning_workspace.sql. Fragment 110 is the early owner of tutor_conversation_events and must accept tutor_conversation_event_v1/v2/v3 before every later Artifact fragment executes; repeat bootstrap over persisted v3 rows is a release gate. Fragments 120-200 add the shared Artifact, Learning Item/governance, branch/continuation, teaching commit, demonstration, knowledge-check, model-review, and SQL owner contracts without a second aggregate schema source.

User-owned Artifact/branch/continuation/completion/assistance/private-receipt rows are explicit cutover target state and are deleted child-first by confirmed reset/delete. Shared immutable Learning Item versions, source/publication/governance evidence, private evaluation templates, and catalog infrastructure remain in the shared allowlist. test_cutover_inventory_explicitly_classifies_every_tutor_table requires the real information_schema tutor_* set to equal the disjoint target/shared union; a new table missing either classification fails the final gate.

The source document drawer adds no table. It resolves immutable Lesson assignments/documents/source snapshots, persisted tutor_message_context_references, and current source-inspector Artifact provenance through a verified scoped read. Rollback keeps all additive rows/history and disables admission/presentation in reverse dependency order; there is no destructive down migration or invented Artifact backfill.


### 来源工件用途与兼容（2026-09-21）

Artifact purpose 闭合集合新增 `source_inspection`。Tutor 生成的正式来源工件关联真实 run/turn 与提交后的教学 checkpoint，并复用
`tutor_learning_artifacts`、`tutor_learning_artifact_events`、`tutor_learning_artifact_references`
与同事务 conversation item event，不新增独立分数、进度或发布表。
新 purpose 通过显式 manifest fragment 为既有数据库增量扩展约束；历史 remediation/source rows 不改写。
真实验收库只应用对应增量 DDL，不为验收运行完整 bootstrap/种子导入。

既有手动来源记录与创建事件保留为历史，不能修改为真实 Tutor turn；新来源与教学消息共用原子终态提交，不通过已移除的手动创建 API 落库。


## 2026-09-23：RAG 版本化语料权威（阶段 I）

`260_rag_subject_corpus.sql` 在 manifest 尾部增量加入独立语料表，不改变旧
`grounding_chunks` 的替换语义，不 backfill 既有 Lesson/Tutor 引用，也不为公开消费者切换读路径。

| 表 | 责任与边界 |
| --- | --- |
| `grounding_corpus_versions` | 固定 Subject/version、registry/policy 身份及语料哈希；维护 candidate、validated、published、failed、retired 生命周期 |
| `grounding_active_corpora` | 每个 Subject 一个 active 指针；用 expected generation CAS 更新，rollback 也推进 generation |
| `grounding_corpus_source_snapshots` | 保存语料内固定来源、trust、允许域名/版本/facet 元数据，不存凭据 |
| `grounding_corpus_documents` | 固定 corpus/source 文档身份、URL、文档哈希、解析状态与有界诊断，不存整页原始抓取正文 |
| `grounding_corpus_chunks` | 固定 corpus/document/source/Subject/version 及 document/chunk 哈希谱系；有界内容与 generated FTS/GIN |
| `grounding_corpus_events` | append-only 生命周期操作回执，绑定请求/摘要哈希与幂等身份；不存 provider 原文或任意运维路径 |

Repository 使用调用方提供的事务；不得在内部提交、另开一条业务事务或绕过状态/代际校验。
写操作拒绝 autocommit 连接，并在调用方事务内使用 savepoint；即使调用方捕获后续步骤的异常并继续提交，
失败操作的状态、事件和指针变更也必须整体撤销。空闲连接先开启调用方的隐式事务，不能让 savepoint 包装变成自动提交。
持久化 URL 元数据仅接受不含凭据、显式端口、query 或 fragment 的 HTTPS 文档位置；seed 主机须匹配声明域名。
validation/coverage summary 只允许有界标量事实和安全字段名，不接受嵌套对象、任意正文/URL/路径；JSON 数组必须满足元素类型与长度约束。
这些存储边界不代替后续抓取授权、重定向/DNS 检查或来源覆盖质量验证。
validated 及后续状态的内容快照不可原地替换；发布和回退只改变合法状态/active 指针，
不修改已发布内容。当前 active 语料不可退役；失败/退役状态不能回到 candidate。
同一 Subject 的两个并发激活必须只允许一个 expected-generation 胜者；失败操作不得遗留半条发布或回执。
相同幂等键与相同请求恢复原回执，键相同而请求不同必须冲突，不能以“当前指针已变化”重新执行旧请求。

这六表属于共享基础设施，不归某个用户所有。用户 reset/delete 和 clean-slate cutover
不能清除共享语料；用户 export 不额外导出原始来源、片段正文或内部审计回执。
`tutor_*` 域的 exhaustive target/shared 分类保持自己的命名空间，不把 `grounding_*` 硬塞入该集合。

此阶段不提供网络抓取、operator CLI、自动发布策略或公开 consumer；候选覆盖摘要也不等同
真实来源质量已验证。工程验收使用独立临时数据库进行 bootstrap twice、immutable/scope 约束、
CAS 竞争与旧读取兼容回归，不能记作真实语料准入、题目发布或完整小节通过。

## RAG 2.0 内部集成的数据库边界（阶段 I）

本轮shadow adapter、scenario manifest与demo不新增数据库表、迁移fragment或学习者状态。既有六张共享corpus表的不可变内容、append-only事件及generation CAS仍按上文执行。演示operator发布只允许显式隔离临时库；引用/预检探针使用调用方持有的只读快照，不修改active learning plan、progress、assignment、Lesson或Artifact。

v2引用兼容输出不是v1 `grounding_chunks` 外键或HTTP ingestion provenance。不得向既有Lesson/Artifact来源表写入伪造兼容行；公开来源冻结、权限与版本校验仍以原契约为准。表/manifest及共享corpus用户清理隔离回归纳入[验收计划](../qa/acceptance-test-plan.md)。

## 2026-09-24：RAG B1 受控发现持久账本（默认关闭）

`270_rag_discovery_jobs.sql` 是在 `260_rag_subject_corpus.sql` 之后的增量 fragment，不更改既有语料、fixture 哈希或公开读取路径。B1 只存发现作业与**未准入**候选：

| 表 | 责任与边界 |
| --- | --- |
| `rag_budget_authority_roots` | 默认禁用、bootstrap 不 seed 的服务端 root/delegation/policy/period/cap 配置；只读 resolver 逐字段核对 A 的当前 snapshot，缺审批/配置不得启用 |
| `rag_budget_periods` | canonical root + period 唯一行，记录可信服务端额度上限及周期截止；锁定此行后累计所有 job/profile 的预留、未知与已结算用量 |
| `rag_budget_reservations` | root/period/operation 幂等预留；尝试中及用量不明均占满预留容量，已结算按权威实际用量计费；跨 job 共享 root |
| `rag_budget_attempts` | 每一预留仅一次 attempt 身份；`started -> dispatched` 在当前权限/开关、完整服务端投影摘要、预留、lease owner+generation 下持久一次性 CAS；只有提交成功的首次 dispatch 可外呼，重启/重复调用不能再发送；不明用量标 unknown 且不因超时/失租释放 |
| `rag_discovery_jobs` | 无全局 beat 的显式作业；`owner_id + generation + expiry` 租约隔离失租写入，终态不重新领取 |
| `rag_discovery_job_refs` | actor 私有引用与共享 job 分离；**不属于 shared classification**，不能随共享 job/receipt 整体保留或导出。本人 unlink/用户 reset/delete 必须通过可信 `PrivateReferenceRemovalAuthority`，删除仅该 actor 的映射；无授权默认拒绝 |
| `rag_discovery_receipts` | 同一 job 内安全搜索结果码、响应摘要和已结算 attempt 身份，不存 query、provider 原文或密钥 |
| `rag_discovery_candidates` | 同一 receipt/job 范围的未准入 URL 元数据；只允许无凭据、query/fragment 的 HTTPS 位置；无 active corpus 外键、不得被正式检索或题库消费 |

Repository 使用调用方事务和内部 savepoint；不提交事务、不执行外呼。每次预留必须先由 A 的当前 `AuthorityResolver` 验证 actor/action/完整 demand/purpose/policy/delegation，再由可信 `BudgetPolicyResolver` 解析同一 root 的 period/cap；请求的 `RagBudgetDelegation` 只是匹配参考而非余额。operation/attempt/receipt 重放必须比对完整安全身份；冲突拒绝。作业 lease 过期后不可提交候选/终态；账本未知用量保持保守占用，后续权威对账不能由失败响应推测零消耗。四个自主开关仍默认关闭，本 schema 不启动 worker、provider 或外部抓取。

私有引用双用户反例：actor A/B 对同一公开 job 分别建立映射，A 的本人 unlink 或用户清理只删 A 的 `rag_discovery_job_refs` 行；B 的映射、共享 job、已结算预算/receipt/candidate 保留。清理入口不得因为 `grounding_*` / `rag_*` 表名前缀将这些映射盲目列入旧 Tutor cutover 的共享或全局删除集合。若用户导出引用，只能由产品层按已核验本人范围投影允许的个人关联，不得顺带导出另一 actor 映射、共享候选原文或内部审计。当前仅提供仓储清理端口，产品 reset/delete/export 接线尚未完成，不能宣称全链路通过。

本 fragment 属于 B1 代码合同，不代表真实 PostgreSQL、Tavily 费用、出口或用户清理/导出全链路已验收。B2 的暂存内容、许可及留存需要后续独立 fragment；B1 candidate URL 也绝非已抓取正文或正式教材来源。

## 2026-09-24：RAG B2 隔离候选暂存（不入正式语料）

`280_rag_candidate_staging.sql` 接在 B1 fragment 后，仅建未准入候选的捕获、片段和个人引用。它不更新六张 corpus 表、active pointer、旧 grounding 读取或公开消费者：

| 表 | 责任与边界 |
| --- | --- |
| `rag_candidate_captures` | 唯一 B1 candidate/job 的隔离捕获，真实请求链、最终 URL、原始捕获范围（none/prefix/full）、hash、保留期限及清理状态；原文仅获 exact StorageRetentionPolicy 后限量存放。`offline_protocol_only` 是离线协议证据；`live_egress_attested` 仅可由同一 concrete SafeFetcher 的一次性签名出口 receipt 在提交时消费，不代表正式准入。none 的 fetched hash 是空 HEAD 响应体，不是远端正文；prefix hash 仅覆盖精确 206 range。 |
| `rag_candidate_fragments` | 仅 full 捕获后保留结构化片段及 hash；过期/全局撤权清空片段文本并保留最小审计身份。不能供正式检索、规划或题库读取。 |
| `rag_candidate_private_refs` | 学习者/actor 对共享 candidate 的个人关联。本人删除仅 unlink 自己；共享来源事实和其他用户引用不随之删除。未经核验的私有导出不得暴露其他用户、共享原文或审计内部信息。 |
| `rag_candidate_intake_leases` | B1 结算并终结 discovery lease 后，按已结算 candidate 独立持久化 B2 摄入租约（owner + generation + expiry），不重开 Tavily dispatch。重试/失租只按候选和新代数 fencing；成功完成后不可再领取，失败保留已结算预算义务。表存在不构成抓取或保留授权。 |

`CandidateStagingRepository` 在调用方短事务内对同一候选的 intake lease owner+generation、已结算 B1 收据、完整 demand/purpose/root、当前 probe/store 权限和 exact storage grant 重新验证，捕获内容/hash/片段重新计算后才写入。网络 I/O 不在 DB 事务内，接口既不授教材用途也不验证评分 claim。过期/撤权清理原文及片段文本、保留获许可的非秘密摘要；临时文件、失败样本、队列与日志不得成为保留旁路。schema 可标记 concrete fetcher 的一次性 `live_egress_attested` receipt；离线测试及一次临时隔离出口 smoke 不能替代生产出口与保留许可审批。

共享候选/捕获不进旧 Tutor 用户删除集合；`rag_candidate_private_refs` 是私有映射，产品 reset/delete/export 需只处理当前 actor 的引用。B2 的阶段性抓取与暂存不等于正式语料准入；生产出口和 operator policy 未独立验收前保持默认关闭。

## RAG B 持久需求与默认关闭的候选政策

`290_rag_discovery_context.sql` 保存 job 的去身份化、经服务端审核的查询词与 hash；`rag_discovery_private_contexts` 保存按 `users.id`/actor 精确归属的 plan/node/revision、适读性和语言需求，`rag_discovery_actor_owners` 只能在可信身份绑定后创建，旧孤立引用不自动认领。重启按私有 context 重建完整 demand 后仍须再次核验 A 的当前 actor/action/policy/delegation；hash 和共享 job 不能单独授予外部发现。用户导出仅按本人投影 job/candidate 不含共享内容与其他用户引用；reset/delete 应同事务解绑自己的 context、refs 和 actor owner，保留共享用量事实。

`300_rag_candidate_policy.sql` 保存 operator 配置、bootstrap 不 seed/enable 的确切 policy generation、HTTPS host/path 探查与存储许可、内容捕获级别/字节和许可/保留截止。软来源偏好不是权限；公开可见也不推导全文保存许可。政策未知、过期、撤权或更改代际时默认拒绝。探查、暂存提交以及每一个 redirect 目标必须重新核对当前政策；代码已有逐跳政策与签名出口验证，但生产部署出口尚未独立验收，不能把离线规则或临时实验算作生产联网准入。`license_id` 必须来自 operator grant 并与候选暂存记录一致，而非依赖模型/网页自称。

这些增量 fragment 仅提供默认关闭的持久合同，不改变既有 corpus active、旧 Tutor Gate、公开 route 或来源正式用途审核。用户 reset/delete/export 已按本人私有引用接线；生产 live 执行与正式 C 准入仍有独立验收门槛。

## RAG B 基础 campaign 的服务 principal

`310_rag_campaign_authority.sql` 把 operator 配置的服务 actor、精确 Subject/version/facets/purpose/适读性/语言、预算 root 和周期/费用批准与用户私有 actor 所有权分开。bootstrap 只建表、不 seed 或启用服务 principal、campaign 或网络调用。签发的 campaign context 不属于 `users.id`，不可伪装用户计划；仅显式 operator 入口、当前 principal/policy/root/period/cost/开关与受支持 Subject 校验全部通过后才能共享 B1 broker/job/ledger。没有全局 beat、公开 route 或自动外部发现。持久 issuance 供重启重核，但并不等于来源正式准入或课程可授课。服务 principal 与审批撤销时，新操作必须拒绝，已发作业和不明费用仍按租约及账本处理。B2 probe/store 在此之外还要当前 `intake_approved`（默认 false）及精确候选存储政策、独立费用/网络/保留审批；撤回该位不重开 B1 已结算作业。

## RAG C 来源审核与正式语料准入（默认关闭的增量结构）

`320_rag_registered_source.sql` 和 `330_rag_source_admission.sql` 顺接 B 的 310 fragment。Bootstrap 只建表，不预置来源、准入、许可或生产开关。它们不重写既有 260 corpus 的六表、fixture-v1 内容/含义、旧公开检索或 Tutor Gate：

| 表 | 责任与边界 |
| --- | --- |
| `rag_registered_source_policies` | operator 预注册精确 Subject/version/facets/source、HTTPS URL/host/path、origin/适读性、许可/用途、保留期、最高 8 MiB 正文（来源策略可更低，历史 320 的 1 MiB 约束由 `340_rag_c_capture_capacity.sql` 幂等升级）、canonical root，默认 `enabled=false`；撤权不可复活，不能由模型 URL/公开域名推导许可 |
| `rag_registered_fetch_attempts` | 预注册 source 默认单 URL 一次性 `dispatched` CAS，独立于 Tavily/B1 attempt；350 仅允许绑定已终结原记录、精确新 dispatch/policy/root/request hash 与有效期的 operator 显式单次补充授权，旧记录不复活；同进程 dispatch owner 只提供 pre-DNS/pre-dial 两次 grant，重启丢失 permit。结果 settled 或 unknown，失去响应不得换 key 重抓、不能伪造 B candidate receipt |
| `rag_registered_source_captures` | 单次受控 fetch 的链/最终 URL/hash/许可/有界正文；真实 host 结算同时保存 canonical `transport_proof`、其 SHA-256、attestor 公钥指纹及 worker 镜像指纹（旧合成 fixture 可空，不等于生产证明）；只允许带签名出口的 live provenance，过期/撤权后清正文而保留允许的最小非秘密事实；记录本身不授教学用途 |
| `rag_registered_supplemental_authorizations` | 350 中显式 operator 单次追加请求凭据；绑定终态原派发、新派发 UUID、URL、策略/代次、root、request hash 和有效期，不复活或删除原记录，不链式追加 |
| `rag_candidate_use_grants` | 360 中 B full capture 的独立正式用途及历史保留授权，默认关闭；绑定 capture/hash、当前 B policy/generation/root、scope、许可和用途，允许单调撤权。B 暂存许可不能替代该授权 |
| `rag_source_reviews` / `rag_source_admissions` | 具体注册 capture 或 B full capture 的 exact 文档/revision/hash、lineage、适读性、质量与用途审核事实；review 与 admission 分离，失败/隔离不得准入。`immutable_history_allowed` 只有在 corpus 快照历史内容保留许可明确时才允许 link |
| `rag_source_claim_receipts` | 对 exact claim/需求/来源版本的独立来源验证事实；同 lineage 的另一篇不能假装独立。隔离执行路径没有可信 verifier adapter 时 DB 默认拒绝仅凭 handle 的 receipt；应用仍须独立验证语义和当前授权 |
| `rag_assessment_source_evidence` | 480 中新增的 private shared/operator source 签名证据，没有 learner `user_id`；绑定 capture/document、policy/generation/root、有限 profile、demand/claim/execution handle、独立 service signer、sealed terminal 与有效期。不是用户内容、公开来源列表或用户 export；per-user reset/delete 不删除共享 RAG 来源证据 |
| `rag_corpus_admission_links` / `rag_corpus_validation_receipts` | C admission 到现有 corpus source/document 的绑定及独立动态验证 receipt；现有 `CorpusRepository` 仍是唯一 candidate/validation event/单 active CAS 写者，旧 `CorpusService` 保持 fixture-only |

可信 control 通过 Unix peer UID/GID、固定镜像与当前 DB 授权验证 worker 报告，并在同一事务结算 attempt/capture；B 签名只证明拨号前的 namespace/出口规则，不独立证明 HTTPS 正文。`registered_source_retention` 在调用方事务内物理置空到期/撤权的 capture 正文；formal corpus 历史文本另须 policy 与 review 双重永久历史授权，不能把当前用途过期等同于历史许可撤销，也不能把读取拒绝冒充备份/WAL 擦除。

2026-09-25 隔离实测已完成真实 SQLite SELECT 全文抓取与留存（2,033,807 bytes）、provenance 再验、独立自动服务审核及签名回执、正式 supplementary admission 和 partial corpus 激活。自动审核仅批准 WHERE/LIMIT 两个精确片段；不是整页或主教材/评分证据资格。真实库现为 1 capture、1 review、1 admission、1 active pointer（generation=1），正式快照仅含 2 个获审片段。原 unknown 记录保留；后来明确批准的两次追加 GET 已耗尽（一次定位旧 1 MiB 大小拒绝、一次在 8 MiB 上限下完整结算）。这不授权自动重试或继续请求。实测仍限获准单页、无 Tavily、专用可丢弃数据库；该页最多支持 `route.sql` 的 `queries` facet，缺 `schema` 时完整基础资料仍 not_ready。任何生产网络、共享内容保留、用途/claim 或公开 consumer 要独立核对；真实来源已抓取也不能单独解除默认关闭门禁。


## 2026-09-28：隔离来源的单次到期刷新（420）

`420_rag_c_expired_source_refresh.sql` 复用现有 final-followup allowance 与 supplemental authorization，不新增 corpus authority、不自动授予权限。仅在同一 URL 已有前三次 unknown 和第四次真实 settled capture，且第四代 capture/policy/root/授权均到期但未撤销时，允许 operator 以 `standingpolicy.sourcefreshness.` 审批引用追加一次第五代全新 GET。新 policy/root/dispatch/request 必须独立、当前有效且最长 24 小时，来源、Subject/version/facets、URL、license、用途及历史许可不变，字节上限不扩大。原四次记录和到期时间不可改写；`dispatched_at <= fetched_at <= settled_at <= DB now`。旧 generation-3/4 检查保持原样，第六代及重复第五次派发拒绝；失败仍消耗本次额度，不能复用已过期正文或将 partial body 当作完整 capture。该结构已通过隔离测试，不代表新的真实抓取或 D 全链路验收已成功。

## Tavily 提取接入（430，用户显式授权切换）

`430_rag_tavily_extraction.sql` 增加 `rag_provider_extraction_attempts`，记录 Tavily 单 URL 的预派发、请求/返回内容 hash、格式/深度、provider request ID、可空 usage、时间及 settled/failed/unknown 终态；它复用当前 registered policy/root，派发先持久化、HTTP 在事务外、结果另开短事务结算。根资源上限不因失败重置。

`rag_registered_source_captures` 复用既有留存和准入体系：`fetch_attempt_id` 与 `provider_attempt_id` 必须且只能有一个。旧 direct capture 的 `live_egress_attested` 合同保留；新 provider capture 明确标记 `provider_extracted`、`text/markdown` 或 `text/plain`，不附加或伪造 TLS/worker transport proof。Tavily 返回的完整提取结果不等于原始完整 HTML。独立自动服务使用新的原生 Markdown 签名 profile 审核精确片段，后续仍进入唯一的 review/admission/corpus/selection/binding 权威。Schema 不开启公开消费者、不授予整页/主教材/评分资格，也不复活旧 direct dispatch。

## 2026-09-27：RAG D 草案材料选择与冻结（内部默认关闭）

`370_rag_plan_material_bindings.sql` 在现有manifest增量登记两张用户级表，不新增corpus/document/active pointer或题库publication authority：

| 表 | 当前职责 |
|---|---|
| `rag_material_selections` | 整稿scope、逐节点/用途需求与材料结果、canonical digest及幂等身份；snapshot不可变，只允许一次全空→全满的target run/input_revision关联，关联具有独立摘要和唯一target约束 |
| `rag_plan_material_bindings` | successor selection及exact draft/node/goal/purpose、文档/chunk/授权坐标；同自然键只能冻结一组canonical证据，更换retry key不能替代旧绑定 |

仓储在调用方同连接READ COMMITTED短事务核对当前草案和typed current授权receipt，重放不豁免当前授权；不接受None/boolean回调作成功。父selection只作反馈，新稿必须重新取证与选择。来源、claim与active权限仍归A/C及唯一corpus writer。

两表纳入用户数据统计与既有授权purge：binding→selection，再一致地解除目标用户session.current_draft_id引用后删除draft/session/scope/run。不能删除其他用户或共享corpus；普通业务无权改历史，reset/delete仍需既有用户授权。C已有表/记录和旧schema定义保留。

### D 追加：教材语义审查审计（2026-09-27）

`380_rag_material_semantic_reviews.sql` 增加用户私有 `rag_material_semantic_reviews`，关联精确run/user/conversation与selection handle/digest，保存parent/candidate/authority/request哈希、decision iteration/attempt、verdict/reason及可得模型usage；不保存原始提示、来源正文或密钥。

审查派发前记录 `dispatched`，完成后只允许一次结算为 `settled`；结算后不可变，未结算表示结果/用量未知而非免费。相同attempt重放不能再调用模型；usage结算与后续lease/current authorization是否仍有效分开，审计行不等于发布或append授权。append还需核对当前来源、父稿、候选哈希及匹配的已接受provider attempt。授权用户purge先删除语义审计，再删除其引用的selection；共享C来源不受影响。

本schema说明不是生产部署、真实来源资格或真实模型通过证据；实际隔离验收与非声明见D任务 `research/implementation-verification.md`。费用授权与执行核算另外遵循开发期外部资源政策。

## 2026-09-30：题库 P2 物理隔离持久化骨架（440，内部默认关闭）

新增显式fragment 440_learning_item_supply_sandbox.sql。完整DDL职责为14张shared表、22张private表及独立user epoch；权威清单位于item_supply/storage_tables.py。protected purge permit是内部维护权限，不是用户业务表。此结构只在专属一次性fixture验证，不代表已迁移默认业务库或上线供题。

| 表族 | 持久化责任与边界 |
| --- | --- |
| tutor_item_supply_shared_* | 公共matrix/policy/blueprint/slot、非私人job/evidence/proof/admission与预算账本；不存私人owner映射、原材料或内容hash |
| tutor_item_supply_private_* | 用户scope、材料/候选/版本payload、证据/proof/observation、发布引用/绑定/cache/staging、demand/result/subscription及job/预算；物理分表且复合owner/epoch/scope FK |
| tutor_item_supply_user_epochs | reset后保留的身份tombstone；不是公共catalog，也不是可重新进入学习的库存；deleting禁用epoch |

private repository绑定真实active track/revision/node并重验P1冻结scope/目标合同。私有handle使用独立opaque lip:v2 identity，hash由存储边界计算，不由调用方任意签发。来源坐标必须全空或全有，但只表示证据引用，不能代替RAG current authorization。不可变版本/事件及严格幂等冲突由DB和repository共同拒绝。

ObservationV2区分simulation/deterministic_probe/real_learner；真实观察须精确匹配session assignment document、Attempt、terminal result、plan revision、owner、track和knowledge node，不是只验证UUID非空；但P2不证明真实采集器、沙盘、scorer或用途许可已经ready。autonomous_evidence_policy_v2与旧v1审核/试点/人审隔离，旧行不回填；P2 admission仅blocked/evidence_pending，不能发布或物化。

现行export/reset/delete/cutover接入新private职责清单。reset先锁定并递增epoch、失效job/binding，再按child-to-root清payload；晚到请求或worker旧epoch不能复活，shared和另一用户保持。purge与既有owner使用同一caller事务，不自行COMMIT，rollback同时恢复epoch和payload。SECURITY DEFINER固定search_path、PUBLIC execute撤销、permit私有保护；普通session GUC不授予删除权。schema/maintenance owner是显式可信边界，生产角色grant仍需独立部署配置。

export只返回逐private表的有界安全摘要及truncated标识，不输出材料、答案/hidden tests/rubric、provider body、私人hash或lease信息。DB reset不撤回用户已导出文件或外部备份，本阶段不承诺备份清理。generation/network/v2 admission/supply四开关均default-off；P3作业运行、P4-P10消费者和RAG E验收仍独立。

P2工程验收包含49个聚焦DB/静态/竞态测试；epoch reset与active revision切换均以真实双连接双顺序验证bind/store/direct SQL，调用方rollback保持原子。该计数是2026-09-30 P2验收快照，不代替后续P3测试或完整API验收。

## 2026-10-01：题库 P3 内部运行时与累计账本（450）

在已验收440骨架之后显式增加450_learning_item_supply_runtime.sql，保存版本化参数profile、shared/private作业controls与checkpoint，以及逐资源预留/结算和system/provider/window/pool/private-user累计约束。身份envelope与append-only证据保持分离；所有新增业务表纳入storage_tables/cutover分类，私有表仍使用owner/epoch/scope复合边界，并由既有维护owner在同一事务内清理。

canonical obligation由服务端持久化blueprint或用户scope/demand重建，profile/client/job键不清预算。预留在统一锁序下检查全部维度；unknown占用保守预留，费用未知保留NULL，known reconciliation/真实超额如实记账且不能自动扩大cap。共享统计不得保存私人材料/用户hash映射；用户export只提供有界安全摘要。

450最终增加18张表（11 shared、7 private），包括tutor_item_supply_runtime_global_usage_facts匿名append-only资源事实；只保留opaque reservation/settlement UUID、sequence、资源种类和known/unknown actual，不存用户、epoch、scope、材料/hash/client key/provider body。private reset删除明细后，已发生实际用量仍计入global cap；latest unknown保持预留与已有known overage中的保守值，不把已知超额降为预留。该表纳入shared全分类且不阻止用户私有清理。

本节是内部代码合同，工程验收以B1b任务research下实际P3记录为准，不是默认业务库迁移或生产角色配置。完整P4-P10/E、真实provider与消费者仍独立。

## 2026-10-01：题库 P4/P5 私有流水线收据

新增显式 fragment `460_learning_item_supply_pipeline.sql`，不改440/450原DDL。`tutor_item_supply_private_generation_artifacts`保存严格生成request、内容source、provider/source receipt及source/content hash；`tutor_item_supply_private_pipeline_receipts`按白名单保存validation、blind_solve、review_bundle、admission_evaluation四类不可变typed报告。候选/版本仍复用P2专表，不能在只允许v1公开/私有内容的staging JSON夹带新元数据。

两表是private，不进入公共catalog；复合owner/epoch/scope/job/version FK、服务及DB current lease fence共同约束写入，`publication_enabled`恒为false。原export仅返回有界opaque摘要；原reset capability先清理新增子表，再清理440/450父表，保留epoch tombstone及匿名usage事实。B1c只bootstrap专属fixture，不代表默认业务库迁移或公开发布。

## P6 独立沙盘与执行-only资源门禁（B1d）

显式fragment `470_learning_item_supply_sandbox_execution.sql`增加private execution_intents、sandbox_runs、sandbox_observations三表。P6写入只允许精确独立`aearn_b1d_sandbox_20261001`及sandbox actor namespace，组合owner/epoch/scope/job/root/generation/profile/source身份与真实terminal JSON；Observation唯一键(source_run,scenario,attempt)，origin不可修改，模型不能输入sample/completed统计。

private reservation请求/token仅通过470改为nonnegative；零header必须有当前exact execution intent，七个非执行维度真0，execution_seconds严格正数。shared与原440/450/460文件未改，普通reserve默认仍拒execution-only；受信reserve_execution继续使用原450累计limit/账本及unknown保守结算。P4 synthetic库allowlist只加这一个精确P6库，不开放业务库或伪造live来源。

三表纳入原opaque export与cutover分类，原维护权限按observations→runs→intents→旧children删除，epoch/匿名usage仍保留，没有新PUBLIC purge授权。所有bootstrap与验收只作用于独立沙盘，不代表业务库迁移。阶段提交和结算分别commit，失败的真实执行/已知费用事实不可删改来使验收变绿。

450升级对仍存在的真实settlement与actual子行做幂等additive匿名事实迁移，不更新/删除旧账本，不把缺失维度或已丢失历史编成零。unknown中间行不能遮蔽上一known消费；降低资源/费用需显式reconciliation。profile/observation JSON键集与当前严格模型同步，数据库同时检查参数范围、timeout层级、floor/ceiling与初始化证据，不接受自算正确hash但内容非法的配置。

## 2026-10-02：独立服务的来源 assessment 签名证据（480）

`480_rag_assessment_execution_authority.sql` 已在现有有序 `SCHEMA_FRAGMENT_NAMES` 中增量登记，新增唯一表 `rag_assessment_source_evidence`，并给 `rag_source_reviews` / `rag_source_claim_receipts` 追加 assessment evidence 关联及精确 receipt/applicability/scope 字段。旧行保持 NULL，不把旧 supplementary、synthetic capture 或 candidate 执行结果回填为来源 assessment 权威。

新表属于 **private shared/operator RAG service evidence**：没有 learner `user_id`，保存由独立服务签名、当前 provenance 及实际 source oracle terminal 绑定的证据；普通证明字段不可变，仅有受控单调撤权。当前 SQL 写入仍限明确的 B1d 隔离库，expiry/revocation、用途、来源 current authority 和 service pin 必须分别核验；建表、FK/hash 或分类清单本身不能证明真实签名/来源/准入已通过。

分类沿用 `tests/grounding/test_rag_c_inventory.py::_C_SHARED` 及其既有 RAG exhaustive inventory，不新增另一份业务表 manifest。该集合与 `CUTOVER_SHARED_TUTOR_TABLES` / `CUTOVER_TARGET_TUTOR_TABLES` 均保持无交集；不能因为它是 shared 就加入 Tutor cutover shared、用户 purge 或全局来源删除列表。用户 export/public API 不输出该表、signed proof、source terminal 详情或 operator 审计；per-user reset/delete 只处理既有用户私有引用，不删除共享 RAG 来源和证据，也不产生公开读取授权。480 的首次 PG bootstrap/replay 与真实 reconciliation 由 main 独占执行，此文是结构/分类合同，不代表 PG 或 actual source/admission 验收结果。

## 2026-10-02：候选 admission 私有完整事实（481）

`481_learning_item_supply_admission_facts.sql` 新增 `tutor_item_supply_private_admission_facts`，由现有有序 manifest 增量执行。它是 user/epoch/scope/job/version/generation-artifact 精确绑定的 **private** 表，`payload_json` 保存 source、候选目标 coverage mapping、task ambiguity 等完整 typed receipt；可能包含 goal/draft opaque references、独立执行事实及内部上下文。`publication_enabled` 恒为 false，候选 mapping 不等于 published inventory，不创建第二个正式成绩或 Gate owner。

新表只在 `storage_tables.py::PRIVATE_TABLES` 登记一次；现有 private export 和 cutover target/count SQL 从该 tuple 自动派生，不复制 SQL、不加入 shared catalog。用户 export 仍是既有 bounded opaque ID/scope/time inventory（可据此计数），不读取 `payload_json`、goal/draft 细节、hidden datasets 或 terminal private stdout，不另加 raw 事实导出。历史 `P6_PRIVATE_TABLES` 仅表示470的三张执行表，后续481 facts仍由完整private集合覆盖。

reset/delete 沿用现有维护 owner 与 reset-permit：481 的复合 generation-artifact FK 使用 `ON DELETE CASCADE`，parent 被授权清理时级联删除其当前用户事实；epoch 与 immutable('private') trigger 仍生效。不添加新的PUBLIC purge权限或单独强制删除入口，不提前删除共享 `rag_assessment_source_evidence`、来源/corpus或其它用户数据，累计资源事实与 epoch tombstone 保留。首次481 PG bootstrap/replay及实际cascade/reconciliation由main独占；静态分类/manifest通过不能代替该真实验收。

## 2026-10-02：Python exact canonical assessment source（482）

`482_rag_python_canonical_assessment_source.sql` 保留480原片段，仅增量更新既有来源证据的profile约束及guard；不新增表，不改变shared/private分类、用户export/reset或PUBLIC权限。`python-sum-print-source-v1`仍绑定原exact URL `https://docs.python.org/3/library/functions.html`；新增`python-sum-print-source-v2`只接受canonical URL `https://docs.python.org/3/builtins/functions.html`上的**全新、当前有效registered capture**，Subject仍为`route.python`、facets仍为`fundamentals`。SQLite v1合同不变。

旧Python URL的301不能作为自动redirect许可、URL别名或旧capture转换；不改签旧proof、不续旧grant/policy/root、不复活failed/expired dispatch。有限sum/print source oracle units、独立service签名及pin、完整provenance、用途/expiry/revocation、owner/隔离库和current authority fences全部保留。482 bootstrap/replay成功只证明结构可重复部署，不代表新URL capture、source proof或assessment admission已产生；这些真实前置仍须独立记录。

## 2026-10-03：已结算来源的有限新捕获授权（484）

`484_rag_c_settled_second_fresh_capture.sql` 复用既有 `rag_registered_final_followup_allowances`、supplemental authorization 与 dispatch；只追加 nullable、不可变且互斥的两种精确 capture/failed-authorization 坐标及 FK，不新建 capture 或预算账本，bootstrap 不发授权。

- Python 分支：精确 canonical Python 官方 assessment 范围，第一次 attempt 为 unknown、第二次为 settled 且来源自然过期；两次历史 policy generation 实际均为1，不能把 attempt 顺序当 policy generation。允许一次独立新 generation=3 root/policy/allowance/auth/dispatch，保留原已消费和过期事实。合法 unused-grant correction 的前置撤销链仍须验证。
- SQLite 分支：精确 SQLite 官方 assessment 范围，原 settled capture 自然过期，随后 ordinary supplemental 为固定 PID namespace 部署错误的 terminal unknown且无 capture。新 generation=3 仅为一次明确批准的部署纠正；source_handle 继承失败 second policy，原 source 的语义范围不得扩大。零 wire 不能把旧 grant 变回 unused。
- 两分支均复用 original attempt 行锁及 allowance/auth/dispatch 三处 SQL guard；等待锁后重读数据库时间，核验 exact capture/hash、完整历史、license/usages/Subject/facets、scope 非扩大、新 root/current/expiry 及24小时上限。新 nullable 分支不能被当成旧400/410/420 unknown链继续续抓，旧分支保持原语义。
- 新字段仍是私有 shared/operator 来源治理证据，不加入 learner export，不形成 public consumer authority；旧 unknown、费用、期限、签名、capture 和 immutable history 不重写。新 GET 后仍须独立 source oracle、签名、用途准入、corpus/current binding，不因发 grant 或建表而宣称 E 通过。

## 2026-10-02：来源 assessment 的冻结需求坐标（483）

`483_rag_assessment_demand_coordinates.sql` 增量把来源签名证据唯一键改为 `(capture_id,demand_hash)`：同捕获、同冻结需求仍不得重复签发；新需求可在原捕获及政策仍有效时独立执行、签发。来源 review 保留无 assessment 关联的 legacy capture partial unique，assessment 路径使用 `(registered_capture_id,assessment_evidence_id)` 唯一关联。document/evidence 的其它唯一约束、原不可变与用途/expiry/revocation guards 保留。没有新表、预算根、公开授权或用户清理权限。

capture-only verifier 在多证据时必须 fail closed；明确 document/claim/evidence 的读取仍精确核验。不得使用任意第一条证据，也不得修改旧 proof/grant 的有效期。真实 bootstrap/replay 与新需求独立源事实证据保存在当前隔离任务，原两份 proof 未被改写；这不等于候选审核或公开供题通过。
## 2026-10-03：原生公开课程的有限 Python 来源证据（486）

`486_rag_public_python_course_source.sql` 不新增表、预算或发布许可，只在既有
`rag_assessment_source_evidence` 中增加 `python-state-source-v1` 与
`python-binding-source-v1` 两个闭集 profile。只接受 Python 官方 reference
`simple_stmts.html` 的当前真实 capture、`route.python` / `1.0` / `fundamentals`
以及原生 `course.*` / `target.*` demand；仍须应用层独立 service signature、实际
sealed execution、逐源码片段审核、C admission/current corpus 和消费 fence。
这不是把旧私有 DraftScope 改名为公开池，也不授予第三方教程 assessment 权威。

为允许包含后续 profile 行的完整 bootstrap 重放，482 的历史子集 CHECK 采用
`NOT VALID` 过渡态（新写仍受约束），486 在同一 bootstrap 中恢复并验证完整闭集。
真实新 profile 行存在时重复完整 bootstrap 已验证，已有证据/预算/当前指针未改写。
消费 actor 根据 profile 推导，不给旧签名 payload 添加默认字段；数据库 clock 的
时区表示统一到 UTC，不能据此延长旧签名或来源保留期。SQLite 的新课程闭集尚未接入。

## 2026-10-03：C corpus 按用途分区的联合快照（487）

`487_rag_corpus_usage_partitions.sql` 扩展既有 validation receipt，不另建 corpus
或发布系统。`dynamic-c-purpose-v2` 在同一快照内保留各文档独立的实际准入用途：
第三方 `main_teaching` 与官方 `assessment_evidence` 不能互相升级。每次审计仍检查
全部文档的当前来源、审核、policy/root、字节和精确片段；消费资格仅返回目标用途的
文档和覆盖范围，缺失用途不变成 ready。

新 receipt 的 `audit_policy_version` 明确区分合同；v2 的
`review_policy_generation` 为 NULL，因为各 policy generation 由身份绑定的摘要
逐项记录，而不是伪造一个 corpus-global 代数。旧合同继续非空正整数，旧记录补充的
默认审计标记是 `dynamic-c-v1`，不改写其用途或来源证明。INSERT guard 绑定已验证
corpus 的实际 policy/summary；既有 immutable guard 和唯一 active CAS 不变。
实际包含新 v2 receipt 后完整 bootstrap 两次、当前读取和禁用来源强制回滚已验证。
第三方片段 attribution 和域分离 service 签名是独立当前证据，不是公开发布许可。

## 2026-10-03：原生 SQLite companion 来源与 shared 生成暂存（488–489）

488 在既有来源证据中增加封闭 SQLite predicate/order profile：primary SELECT
加两个必需的 expr/corefunc typed companions，分别固定 capture、外部 provenance、
policy/root、完整断言和期限。新子类型参与签名；旧 prepared 不新增默认字段，不续旧
签名。486 历史子集 CHECK 采用过渡 NOT VALID，488 最终完整闭集 validated。真实三
来源 prepare/oracle/sign/persist/corpus/current material 与 companion 禁用回滚已执行。

489 新增 `tutor_item_supply_shared_generation_artifacts` 和
`tutor_item_supply_shared_pipeline_receipts`：原生 public P3 job/root/lease 下的
append-only confidential staging。没有 learner owner/private scope/demand locator，
不进入用户 export/reset；也没有提前写 item bank version、publication 或 ready。
已注册 manifest/SHARED_TABLES，历史 P3 table family 保持不变。实际 bootstrap 首次
IF/CASE 语法失败已保留，仅加表达式括号后重跑成功；真实 shared provider/admission/
publication 仍是独立的后续验收，不能由两个表已创建推定完成。随后真实生成暂存的
三条原生候选见下一节；这不等于 shared publication 已通过。

## 2026-10-03：原生 shared validation（490）

490 新增 `tutor_item_supply_shared_validation_preparations` 与
`tutor_item_supply_shared_validation_evidence`，均归 shared confidential staging，
不纳入用户私有 export/reset。不可变 preparation 固定原生 artifact/item/version、
实际 public job/root/lease/profile、完整 spec/input 及资源计划；evidence 保留真实
terminal audit、验证结果和已结算使用，不从 JSON 恢复 runner 权威。既有 P3 table
family 仍是原来的12表，新表单独追加到 `P7_SHARED_PIPELINE_TABLES`。

执行型候选通过原 P3 累计预算 owner 预留，仅精确 current preparation 能使用零
HTTP/token 的 execution-only header；实际容器运行前提交预留并结束事务，结算先
独立提交，最终来源/租约检查后再写 typed validation。静态 KC 无 execution
reservation、terminal 或虚构使用量。只有真实 `machine_verified` 推进 validating，
不产生 final admission facts、publication、coverage、ready、Attempt 或 Gate。

主代理已实际生成并暂存 Python state、SQLite predicate、KC 各一条，再分别完成
9/15/0 个真实 OS terminal 的验证路径，三条 typed validation 均已提交。三个 native
version ID 仍未插入 `tutor_learning_item_versions`。490首次安装成功；含新行的
一次完整 bootstrap 已提交且8表内容 hash 保持相等。随后只读 bank 查表名错误
`42P01` 已保留并纠正，仅补做只读 readback，没有再次运行 bootstrap 或候选测试。


## 2026-10-03：原生续行、V2导入与发布（491–494）

491 新增 shared candidate continuation：只采用原已提交 generation 的数据，保留其
原job/profile/author/source，不把旧runner或验证seal恢复为新授权。新操作使用同canonical
root下的新有界lease/profile。完成guard仅对真实adoption以其余六个真实stage替代原生成stage；
private/普通七stage路径不变，不写伪generating checkpoint。

492 为原题库validation新增显式V2 provenance。旧V1通过位及policy/hash唯一性由V1
partial indexes保留；V2以exact shared validation receipt区分操作（静态KC可相同payload
但不同current provenance）。恢复导入只可复用原合法machine_verified initial event，不能
重开quarantine/published。新版本继续使用原li命名空间与原import/event owner。

493 新增shared confidential `tutor_item_supply_shared_admission_facts`。签发必须由同连接、
同Settings且V2 flag启用的原validation/review owner与原runner/ambiguity实例验证，实际
stage先提交；保留review aggregate UNKNOWN，不把一题target proof升级为2/2/1或族独立性。

494 新增shared `tutor_learning_item_native_publication_proofs`，在原事件链增加明确native_v2
policy分支，不伪造V1真人pilot/review。proof、原Practice materialization及published事件在
同一caller事务原子生成；新增nullable无默认/无回填的materialization.native_publication_txid
绑定受guard保护的top-level transaction marker。savepoint xmin不能与顶层txid等同；旧V1行
保持NULL。其他stage committed-before的xmin比较仍不普遍覆盖同父事务savepoint，实际链
按独立commit运行；不声称已验证该更宽边界。

main已在显式B1d内部库应用491及492–494，492–494保留37表原列内容hash。KC首条实际
native发布/物化通过，Python首条真实review因material_review_failure隔离且无发布。SQL单独真实
链随后发布/物化通过，fresh连接核对两条原子发布与Python无发布；完整供题尚未通过。
全部结果以当前任务runtime证据为准。当前查询另行核对source/claim/corpus、
最终published事件及code/SQL真实runtime health，不能以历史producer lease/旧facts有效期
充当当前消费许可。裸旧selector排除native。没有公开release、Gate/Attempt或完整库存ready授权。

## 2026-10-06：原生曝光与预留（495）

495增加六张user-private曝光表：births、inbox、events、watermarks、reservations、deliveries，完整表名以 `NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER` 为准。真实users新增产生epoch1完整起点；既有用户、reset后的epoch或未映射origin不能以空记录宣称未曝光。原artifact、assistance、attempt、hint与Gate binding owner触发器记录不可变inbox，Gate binding本身不是展示事实。

原reset在受维护permit保护的epoch推进后通过 `native_exposure_epoch_purge` 按FK顺序清理六表，不另建purge权限，不生成新epoch完整性。assessment必须先预留两个未曝光族，practice展示须当前watermark、同顶层事务delivery及当前publication/source检查；声明family hash不等于语义独立性。

2026-10-06仅在显式B1d隔离库应用495。真实DDL/幂等、rollback-only新用户birth/watermark及原reset→epoch2通过；275张原public表行数/内容摘要安装前后与回滚后不变。真实native展示、assessment预留及完整供题包尚未因此验收，默认业务库/生产未迁移。证据见题库任务 `research/native-exposure-495-live-20261006.md`。

## 2026-10-06：新课程资料的版本化有效期（497）

### 496 真实D冻结课程映射前置

有序manifest在495后加入496的user-private `tutor_item_supply_finite_course_mappings`，引用真实confirmed session/draft、active revision/node、原D selection/assessment binding以及原P3三个scope/demand。映射receipt不可变；读取重核current claim/source/runtime，不从JSON恢复授权。三个scope共用一个receipt，safe export仅输出id、NULL scope_id与created_at，不导出source/mapping JSON。

496 reset hook仅在原permit/epoch推进后删除自身receipt，与495互不引用且均早于原父表删除。2026-10-06隔离B1d真实DDL/同片重放、空mapping表下495/496原reset共存及实际safe-export查询通过，281张既有表内容摘要不变。当时actual-D finite proof、mapped/resolve和含真实mapping FK的reset仍待验收；2026-10-07的实际有限目标提交与填充生命周期证据见下方506后续记录。PUBLIC proof或旧sum/filter语义不能替代新目标来源。

### 497 新资料有效期

用户要求延长课程资料有效期；本次工程默认选择7天。`course_material_7d_v1` 仅作用新课程proof，实际截止取7天、policy有效期/保留期、capture保留期、budget delegation与period结束的最短值；SQLite另取三个实际capture的最短截止。签发采用新的v2格式和签名域，旧v1字节、24小时合同和旧行保持。

497没有新增表或改写旧proof：先校验最终488 guard精确函数体，才替换其版本门禁及原24小时CHECK为版本化检查；缺488或函数漂移拒绝。它不修改旧policy/root/expiry、一次性dispatch、job lease或90秒运行时健康期限，也不扩大484的独立24小时授权。

主代理已在B1d应用497及同片重放，281张既有public表摘要不变，8条旧assessment proof仍通过版本合同且原行不变。新七天来源授权/fresh capture/新签名proof仍待独立真实验收，不能以迁移通过宣称旧过期材料重新可用。证据：`.runtime/e-resume-20261006/schema-497-23fb62f6a97d/result.json`。

### 498 后续真实新授权与资料刷新（2026-10-06更新）

上段497的迁移快照不包含来源验收；后续498已完成真实新授权/捕获/新proof/current消费，不能继续把它们误读为当前未执行。498增加operator共享 `rag_registered_course_refresh_authorizations` 和supplemental可空显式引用，只允许本轮五个精确来源各一次新dispatch。由真实历史推导7个既有借记（含1个unknown），本轮新增5，上限12；新source-access-only roots不可作为通用搜索/provider预算，未新增预算period/reservation或修改旧cap。

五次真实捕获均settled，四次新受限容器source oracle完成，三个assessment v2证明及一个第三方main_teaching证明的实际截止均为2026-10-13 16:09:16.360356+08:00。Python内部分用途混合C generation7、SQL内部C generation4及当前material核验通过；第三方仅exact fundamentals教学充分，不提升为assessment或全课程充分。旧generation材料拒绝且历史保留。

### 499 actual-D source分支：2026-10-06历史门禁检查点

499新增签名v3 actual-D finite profile，物理profile列沿用语义存储键兼容旧486/488重放，签名payload保留新身份而不是重贴PUBLIC。prepare/persist重建真实draft_ready节点/输入代次，consume验证正常confirmed冻结计划和active user；新oracle run/probe身份阻止旧PUBLIC terminal复用；锁等待后再次核验proof截止。

该历史检查点仅通过有限离线检查与隔离DDL/同片重放，当时用户关联payload的安全export/reset/delete或合法保留政策未闭环。它不是匿名shared审计；当时actual-D v3行数为0，未执行v3签发/落库。新的public v2来源已存在时全schema两次重放通过，不能替代含v3行的生命周期验收。后续KC私有链的实际证据见506恢复记录；E及公开消费者仍未放行。

### 500 显式V3题面展示接缝

`500_learning_item_flexible_public_spec.sql` 不新增表或改写历史行。新内部helper只对request blueprint精确 `finite-public-spec-v3` 和三种既有target放宽title/instruction；其他public JSON字段完全一致，规范任务block及其start/end marker必须各一次。旧版本仍全文一致，缺失/null/错误类型拒绝。它不替代typed任务重建、参考/等价/错误解验证、盲解或六角色审核。

迁移先核对有效489+491 trigger完整prosrc摘要及属性，只替换唯一模板比较子句，保留原lease/root/预算/settlement/source/provider/hash和continuation lookup；未知baseline拒绝。新helper无PUBLIC执行授权，不是第二发布authority。manifest显式注册500，既有489/491字节保持。

2026-10-06 19:20+08主会话在显式B1d隔离库实际应用500、同片重放及完整有序manifest重放；49项SQL helper正负例（含SQL NULL与JSON null区别）通过，283张既有public表行数/内容摘要不变。证据 `.runtime/e-type-evidence-20261006/schema-500-c1b6f22ab01c/result.json`。测试仅用历史public形状构造内存参数，没有生成新候选/来源授权/审核回执，不证明真实供题或E完成。

### 501–504 原生题型证据、曝光及actual-D私有关联（已注册；隔离安装状态见下方记录）

-501新增私有content facts、relation preparations、relation batches、eligibility四表；从原493/494和496重建事实。同一原始批次ID/hash/判断时间在新曝光下保持，不重签。新execution期限和最多7天且受source期限限制的evidence期限分别冻结。
-502新增私有type exposure snapshots/reservations/deliveries三表；当前快照来自原495 collector，SQL当前校验返回完整JSON而非布尔成功。实际预留/交付要求501 capability、同事务、当前scope/epoch/watermark与截止时刻。
-503按签名actual-D v3 owner/epoch对混合source evidence增加条件私有列、关联保护和原reset/delete尾部清理；504新增私有provenance表，精确关联已有PUBLIC载体，不将私有admission写进共享corpus。保留PUBLIC来源、其他用户、capture和共享预算历史。
-原epoch清理顺序为502 `a01_native_type_exposure_epoch_purge` →501 `a02_native_type_evidence_epoch_purge` →496/495；501不对后安装的502表建立前向FK。新七张Tutor私有表纳入原inventory和安全导出；条件私有actual-D表单独按owner统计，cutover只阻止不清理。

2026-10-06 21:21+08在显式B1d隔离库完成501–504、同片重放、完整有序manifest重放及新用户空表reset控制，283张旧表按原列投影的行数/摘要保持。**整个演练强制回滚，501–504未安装**；schema初始化器新增`--rehearse`，即使未来`--execute`也先在DDL事务内完成reset控制再提交，失败不留半验收安装。证据 `.runtime/e-native-type-20261006/schema-501-504-8eacad026a52/result.json`。不把编译、重放和空表reset当成填充私有proof/bridge或真实题包交付验收。

### 505 诊断式盲解准入（显式新policy，已注册）

新增共享不可变表`tutor_item_supply_shared_generation_policy_bindings`，在原author reservation前冻结新policy与candidate/root/job/request/profile/lease绑定。属于shared metadata，不进入用户私有清理/导出，不创建新预算钱包或覆盖义务。旧V2没有binding时仍走原策略；旧候选/已经预留或生成的候选不可追贴V3。

505以完整已知函数体和属性pin加法扩展有效489+491+500、493、494门禁，核对真实绑定、V2/V3 schema、原盲解与evaluation warning一致性；未知baseline拒绝。440–504文件不修改，旧行不升级，原provider/source/lease/budget/hash/发布owner不被warning代替。

主会话2026-10-07 00:19+08完成501–505真实PG回滚编译、同片与完整manifest截至505重放、283旧表原列摘要、空表reset及函数/OID完全恢复；00:24+08用旧失败KC候选测试追贴policy，被SQLSTATE23514拒绝，旧artifact摘要和预算root数量不变，新增binding为0。均为**强制回滚，未安装505，也不是新V3填充阳性**。分别记录于`.runtime/e-native-type-20261006/schema-501-505-6b23fc787ae2/result.json`与`.runtime/e-blind-diagnostic-20261006/historical-policy-denial-42cf0025e122/result.json`。后续若505变化须重验对应SHA；不得把仅编译通过当完整题包可交付。

**2026-10-07后续实际状态：** 独立检查补齐后，主会话在原明确隔离库`aearn_b1d_sandbox_20261001`正式安装501–505，`ddl_committed=true`，283张既有表原列摘要保持不变；证据`.runtime/e-native-type-20261006/schema-501-505-888ddcaaf280/result.json`。这不是生产安装、填充私有生命周期或完整题包通过。随后通过原thread/turn cutover的dry-run→prepare→enable启用该隔离库；5个无lease/未决effect的旧queued夹具由原owner取消并追加审计，草稿/source/candidate摘要保持，未直接修改开关状态。证据`.runtime/e-fast-continuation-20261007/thread-turn-v2-enable.json`。


### 506 actual-D私有claim触发器别名修复（独立通过，已正式隔离安装）

2026-10-07真实私有source持久化触发`42702 column reference e.id is ambiguous`：503的`rag_actual_d_private_insert()`同时使用record变量`e`和局部JOIN别名`e`。新增506仅把后者改为`private_evidence`，完整pin已知旧/新函数体及函数属性；不改440–505、不放宽owner/epoch/签名/独立引用检查，不更新历史行。

本日较早阶段，主会话2项纯契约测试和Ruff通过；真实PG编译、同片重放、完整manifest截至506重放、复用保留真实签名的私有proof/review/admission/claim插入均在强制回滚中通过，结束后数据与原函数完全还原。证据`.runtime/e-fast-continuation-20261007/schema506-rollback-3be3384227b04ef38120a1f4d3cc9397/result.json`。当时506独立复核受网关403阻塞、尚未正式安装；该失败/回滚记录保留，不倒写成正式提交。

**2026-10-07恢复后的实际状态：** `native-private-independent-check-20261007.md`已追加506独立passed，接受SQL SHA256=`5856416e9a2c81ce7b2c0d9c4356260ddace1d59ce7d23f9ebbb728c874642a9`。main在`aearn_b1d_sandbox_20261001`正式安装同一506，复用保留的正确私有signed，经原`AssessmentReceiptRepository.persist`正式提交且`current_readback=true`；未新增oracle/签名。证据`.runtime/e-actual-d-native-20261007/506-install-persist-4c62a0c556984e3b9cd86475533496c2/result.json`。403不再是当前阻塞。

随后原producer的私有bridge及assessment freeze提交、原confirm_session/CAS确认（session v4）、confirmed authority与496 finite mapping提交均通过。对应同前缀的`kc-assessment-freeze-c10b3fbdce744c55aab34cb6b5537a48/result.json`、`kc-confirm-5b452a3e34c14b399bf7a33f2ad1ea3c/result.json`及`response.json`、`kc-mapping-fcf13940d4bd4ce98e145e79df14db85/result.json`及`mapping.json`。这些是该KC目标的正式私有持久化事实，不是完整题包或公开发布。

原reset/delete又在真实填充数据上分别执行force_rollback：`rag_assessment_source_evidence`、`rag_source_reviews`、`rag_source_admissions`、`rag_source_claim_receipts`、`rag_actual_d_private_provenance`各1条→0；PUBLIC和其他用户的179张保护表摘要不变，回滚后292表全部恢复。证据`.runtime/e-actual-d-native-20261007/kc-populated-lifecycle-6692cbbd7bc140e2a72842d0dd01f112/result.json`，`committed=false`；没有永久删除原课程/私有链，也不把生命周期回滚测试称为新的数据提交。

上述来源至确认/映射/生命周期恢复窗口新增provider/GET/oracle/签名均0，规划累计77和unknown金额保留；随后新候选的1次author独立记在下方，不覆盖该窗口。P7b完整题包、P8–P10/E仍未完成，生产迁移、公开release与Git收尾未执行。

### 507：505运行时RECORD/composite声明修复（2026-10-07已正式隔离安装）

新immutable campaign `.runtime/e-native-type-20261006/kc-diagnostic-v3-20261007-actual-d-1`的`practice-1`已由原author一次HTTP生成staged，原validator本地结果为`machine_verified`；首次原`commit_validation`触发505运行时SQLSTATE42846：generic RECORD不能转换为`tutor_item_supply_shared_generation_artifacts` composite，当时没有成功提交validation，也未进入盲解/六角色/发布。失败attempt `e417d025a3714b71958849be85c4a339`保留，不能用计算阶段通过替代持久化门禁；507后的续跑另记，不覆盖该历史失败。

main在`.runtime/e-fast-continuation-20261007/schema507-record-diagnosis-c6da9b73d14f4d8da6885f04459427b0/result.json`记录真实隔离PG对照：generic record失败42846，仅generation表`%ROWTYPE`对照通过，全部未提交、0provider。该诊断本身不等于修复安装；后续append-only507已完成checker离线4 tests/Ruff及main审阅：仅3处声明变为`%ROWTYPE`，其余BEGIN之后body逐字不变，未修改旧505/历史事实。

接受507 SHA256=`5cc76ad7f096eb5944a46d269b478ef3b4ca3f29d78e218feac930bd837e71a8`。真实PG同片重放、完整manifest截至507重放、292表行不变及rehearsal回滚恢复原函数/行均通过，随后正式隔离安装`ddl_committed=true`；证据`.runtime/e-fast-continuation-20261007/schema507-acceptance-6c7a29a58d1a4e658638488514a034b8/result.json`。DDL验收provider=0、新author=0。原491一次续跑已结束：复用同一题目、0新增author，continued-validation-staged.json确认machine_verified及校验回执已提交。随后盲解请求URLError，review.json为blind_solve_pending且blind/bundle均null；六角色未调用，facts/publication未产生。一次无鉴权、无推理HEAD也出现SSLEOFError，当前阻塞为provider TLS/network，不是已完成答错；不能按V3诊断策略放行。已停止新增付费调用，不重审刷通过、不改UNKNOWN或旧lease。原author known12841/2137、total14978 tokens和金额null保留，规划累计仍77；盲解请求尝试1次、六角色0次，服务端usage unknown及7请求原review预留保留；传输诊断`.runtime/e-fast-continuation-20261007/provider-head-diagnostic-20261007.json`。
