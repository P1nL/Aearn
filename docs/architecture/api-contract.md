# Aearn Tutor HTTP 与 SSE API 契约

**状态：** 当前公共 API 契约，2026-08-12。
**权威来源：** `aearn/services/api/app/main.py` 中注册的路由、Pydantic model、
`services/tutor/public_api.py`、`services/learning/`、`services/tutor/cutover.py` 与 API 测试。
**不适用：** 已移除的 Graph、Dashboard、Onboarding、Learning Session、Review、
Notes 和旧 streaming endpoint。历史文档不构成当前可调用 API。

## 1. 通用约定

### Base URL 与编码

- 本地 API 默认 `http://127.0.0.1:8001`。
- 请求和响应使用 UTF-8 JSON，SSE endpoint 使用 `text/event-stream`。
- 用户、conversation、run、memory、inbox 与 plan revision 公开 ID 都按 UUID
  处理；服务端会校验范围，客户端不能用另一个用户 ID 读取/修改数据。
- 时间使用 ISO-8601 UTC 字符串。`event_sequence` 是单个 run 内单调递增的整数，
  不是跨 run 的 cursor 或客户端 acknowledgement store。

### 统一错误信封

```json
{
  "error": {
    "code": "CUTOVER_REQUIRED",
    "message": "需要先完成受控切换，当前学习入口暂不可用。",
    "details": { "cutover_version": "harness_clean_slate_v1" },
    "request_id": "req_unset",
    "recoverable": false
  }
}
```

`X-Request-Id` 会原样作为 `request_id` 反映；它不是认证或幂等键。公开错误
不会包含 provider error body、prompt、reasoning、hidden test、reference answer、
learner code、checkpoint、path、command 或 secret。

### Tutor mutation 幂等性

所有 `/api/tutor` 写操作都要求 body 中的 `client_action_id`；客户端也可以用
同格式的 `Idempotency-Key` header 覆盖它。合法格式为：

```text
[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}
```

服务端按 `(user_id, operation, idempotency_key, request_body_hash)` 存储安全响应
投影；mutation 在 lookup/write 前按 `(user_id, operation, idempotency_key)` 获取 transaction
advisory lock，因此 concurrent first write 也只执行一次。同 body 重放返回原响应并标记
`idempotent_replayed=true`；相同 key 配不同不可变 body 返回 `409 IDEMPOTENCY_CONFLICT`，
绝不重复写入或重新调用 provider。
`/api/learning-tracks` mutation 复用同一存储与 key 格式，但使用独立
`learning_track.*` operation namespace。

## 2. Runtime gate

`/api/tutor/*` 的每一个 endpoint 都先检查当前 cutover 版本的
`harness_cutovers` receipt：只有 `state=verified` 可访问。`summary_ready`、
`required`、`verification_failed`、`blocked_target_state` 和
`blocked_checkpoint_scope` 统一拒绝。客户端/本地缓存不能替代这个 gate。

| 常见 gate 错误 | HTTP | 含义 |
| --- | ---: | --- |
| `CUTOVER_REQUIRED` | 409 | 需要先获得或确认服务器摘要 |
| `CUTOVER_TARGET_STATE_PRESENT` | 409 | 预切换 Tutor 数据存在，系统不删除它 |
| `CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED` | 409 | 不能证明旧 checkpoint 的删除范围 |
| `CUTOVER_VERIFICATION_FAILED` | 409 | 删除事务已回滚或不能验证，两个运行时继续锁定 |

## 3. 基础与本地身份接口

| Method | Path | 成功 | 说明 |
| --- | --- | ---: | --- |
| `GET` | `/health` | 200 | `{"status":"ok","service":"aearn-api"}` |
| `GET` | `/api/language-courses` | 200 | `language`、`level`、`limit=1..100` 过滤后的目录；不创建计划 |
| `GET` | `/api/environment/doctor` | 200 | 本地环境诊断的公开 report |
| `POST` | `/api/users` | 201 | 创建本地用户，body 至少有 `display_name` |
| `GET` | `/api/users` | 200 | 本地用户列表 |
| `GET` | `/api/users/{user_id}` | 200 | 当前用户 profile；不存在返回 `USER_NOT_FOUND` |
| `GET` | `/api/users/{user_id}/data-summary` | 200 | 本地历史数据摘要，仅用于用户数据操作 |
| `GET` | `/api/users/{user_id}/export` | 200 | 本地用户导出，不是 Tutor trace/export API |
| `POST` | `/api/users/{user_id}/reset-data` | 200 | 必须 JSON `{"confirm":true}`；未 verified 用户不能借此完成切换 |
| `DELETE` | `/api/users/{user_id}` | 200 | 必须 JSON `{"confirm":true}` |
| `PATCH` | `/api/users/{user_id}/preferences` | 200 | 只更新允许的本地用户偏好 |

创建用户的历史画像字段可以被接收以支持切换清点，但它们不代表当前 Tutor
计划/FSRS/Graph 运行时。Desktop 正常入口只要求显示名称，然后立即读取
cutover decision。

## 4. 受控切换接口

### `GET /api/harness/cutover?user_id={uuid}`

返回当前服务器判断。所有成功响应都带：

```json
{
  "cutover_version": "harness_clean_slate_v1",
  "rollout_active": true,
  "state": "verified | summary_ready | blocked_target_state | blocked_checkpoint_scope",
  "next_action": "enter_tutor | confirm_cutover | resolve_cutover_block"
}
```

- `verified` 包含 `verified_at`，可以进入 Tutor。
- `summary_ready` 还包含 `summary_version`、`preview_nonce`、`summary_hash` 和
  `summary`。`summary` 仅列出 legacy category count、待清空 profile field、
  checkpoint state/count、保留类别和是否存在 target state。
- 两类 blocked 响应包含 stable `code` 和安全 `summary`；服务器不会执行删除。
- 没有 legacy 数据且没有 target contamination 的用户会由此调用直接变为
  `verified`。

### `POST /api/harness/cutover/confirm`

```json
{
  "user_id": "uuid",
  "cutover_version": "harness_clean_slate_v1",
  "summary_version": 1,
  "preview_nonce": "server-value",
  "summary_hash": "64-lowercase-hex",
  "client_action_id": "cutover:uuid:unique",
  "confirm": true
}
```

服务器锁定用户、重算 canonical summary、检查 exact version/nonce/hash、删除
已证明归属的旧范围、验证相同范围并保留 identity/notification fields。成功返回
`state=verified`；相同确认的安全重放会返回 `idempotent_replayed=true`。

`CUTOVER_SUMMARY_STALE`、`CUTOVER_CONFIRMATION_CONFLICT`、target state、未知
checkpoint scope 或验证失败都不产生半完成删除。代码回滚之后也不会恢复已经
确认删除的历史。

## 5. Tutor 会话、TurnRun 与历史接口

所有本节接口均要求 verified user；所有 UUID、idempotency replay、cursor 和读取范围都
同时受当前 `user_id` 约束。

### 首发、普通输入与显式 continuation

| Method | Path | 请求/查询 | 成功响应 |
| --- | --- | --- | --- |
| `POST` | `/api/tutor/conversations/first-turn` | `user_id`、`client_action_id`、`content`、可选 `learning_scope` | 202（新首发）或 200（同 key 重放）；原子返回新 `conversation_id`、新 `run_id` 与初始公开 process |
| `POST` | `/api/tutor/conversations/{conversation_id}/inputs` | `user_id`、`client_action_id`、`content`、可选 `learning_scope` | 202（新普通 TurnRun）或 200（同 key 重放）；见下方 turn response |
| `POST` | `/api/tutor/runs/{run_id}/inputs` | 同上 | 只接受服务端持久化授权的 explicit continuation；202（新接受）或 200（重放） |
| `POST` | `/api/tutor/conversations` | `user_id`、`client_action_id`、可选 `conversation_id` / `learning_scope` | 兼容 create/resume 入口；Desktop draft 不调用它创建空 conversation |
| `GET` | `/api/tutor/runs/{run_id}?user_id={uuid}` | — | 当前 `TutorRun` 安全状态 |

`content` 必须是 trim 后非空且最多 16,000 字符。点击 Desktop “新对话”只建立本地
 draft；首个非空输入调用 `first-turn`，在同一 idempotent transaction 中创建
conversation、fresh interactive `TurnRun`、learner message/input event 和
`input_received` public-process。中间失败会整体回滚，不能留下空 conversation；同
idempotency key/body 重放返回相同 conversation/run ID，且不重复 dispatch；同 key
不同 body 返回 `409 IDEMPOTENCY_CONFLICT`。

每条普通 learner 消息都调用 conversation-input 并创建独立、有限的 `TurnRun`，不会
复用旧 run 的 deadline、budget、lease 或 counter。事务在 conversation lock 下将旧的
foreground interactive run 标记为 `cancelled` + `superseded_by_run_id`，冻结旧公开
process 为 `superseded`，再创建并只 dispatch 新 run。因此每个 conversation 同时至多
一条 foreground run；旧 run 的公开卡片只显示“已根据你的新消息更新本轮处理”。

`learning_scope` 是 additive 结构化输入：`scope_kind` 为 `general | plan_drafting |
learning_track`；first-turn/ordinary-turn 的 track scope 还可固定 run-only
`task_kind` 与 `knowledge_key`。单独 `/conversations` binding 只持久化 broad
scope/track，若携带 run-only 字段则返回 `409 LEARNING_SCOPE_CONFLICT`，不会静默丢弃。
未提供时新 run 快照为 `general/general_tutor`。旧 conversation 没有
scope row 时也只投影为 general，不从聊天正文推断归属。

当 `learning_scope.scope_kind=plan_drafting` 时，三个 Tutor 输入入口还可携带可选
`planning_facts` 与 `reopen_fact_fields`。`planning_facts` 只接受
`language_id`、`goal_text`、`target_level`、`weekly_minutes`、
`experience_level`、`teaching_preferences`、`pace_constraints`；值由服务端
normalize/validate，并绑定已接受的 learner message、run 和 input revision。
`reopen_fact_fields` 使用同一稳定 field key，表示 learner 主动重新开启收集；普通
conversation 不会因为请求里出现这些字段而获得 planning authority。同一个
idempotency key 的 request hash 包含这两个字段，因此变更事实或 reopen 集合不会被
误判为同请求重放。

`/runs/{run_id}/inputs` 不是普通聊天快捷方式：仅当 run 仍属于当前用户、尚未
terminal/cancelled/superseded、状态为 `waiting_for_input`，且已持久化
`continuation_kind` 时允许继续。ordinary input 创建 fresh run 并重新快照 conversation
scope；explicit continuation 复用同一 immutable run scope，若请求携带新的
`learning_scope` 则返回 `409 LEARNING_SCOPE_CONFLICT`。普通 completed、normal-chat 或
被替代 run 一律返回 `409 RUN_NOT_ACTIVE`。

安全 title 只能在同次成功 Tutor decision 写入 learner-visible reply 时尝试写入，使用
NFKC 单行且最多 48 字符的 `conversation_title`，并以 `WHERE title IS NULL` 固定一次。
无 title 时对外显示“新对话”；不得从 learner 原文回退命名，也没有 rename API。

普通 turn response 示例：

```json
{
  "conversation_id": "uuid",
  "run_id": "uuid",
  "input_revision": 1,
  "message_id": "uuid",
  "event_cursor": 1,
  "merged": false,
  "input_replayed": false,
  "idempotent_replayed": false,
  "replaced_run_id": "uuid-or-null",
  "process": {
    "kind": "process",
    "run_id": "uuid",
    "display_state": "thinking",
    "steps": [{"key": "input_received", "state": "completed", "label": "已接收你的问题"}],
    "elapsed_seconds": 0
  },
  "replaced_process": {"kind": "process", "display_state": "superseded"},
  "run": {
    "run_id": "uuid",
    "conversation_id": "uuid",
    "origin": "interactive",
    "status": "queued",
    "input_revision": 1,
    "terminal_outcome": null,
    "continuation_kind": null
  }
}
```

接受输入的事务完成后，路由才安排 post-commit interactive dispatch。接受响应不泄露
dispatcher/provider 异常；run read、SSE 和 history 只反映服务端安全投影。

### Conversation list、history 与 public process

| Method | Path | 查询 | 响应 |
| --- | --- | --- | --- |
| `GET` | `/api/tutor/conversations` | `user_id`、`limit=1..40`、可选 opaque `cursor` | learner-visible conversation summaries，按 `(last_public_activity_at DESC, id DESC)` 排序 |
| `GET` | `/api/tutor/conversations/{conversation_id}/history` | `user_id`、`limit=1..40`、可选 opaque `cursor` | 服务端权威的倒序 public timeline、`next_cursor`、`has_more`、可选 active foreground run |

list item 只含 `conversation_id`、服务端投影 title、`last_public_activity_at` 与可选
`active_run={run_id,status,continuation_kind}`；不返回 learner 原文 preview、provider/model
信息、trace 或诊断。history item 是 `message`（含 public learner/Tutor `content`，
并为 Tutor message 返回 bounded `public_thinking_steps[]`；learner/legacy message 返回空数组）
或 `process`（只含 `display_state`、固定 allowlisted `steps[].label`、server-calculated
`elapsed_seconds` 与时间字段）。`public_thinking_steps` 是 provider 明确写入最终可见
JSON 契约、经 safety validation 后与成功 Tutor message 原子持久化的公开说明；它不是
Responses/DeepSeek 的原生 reasoning item。旧 `tutor_messages` 没有 process row 或公开思路
字段时仍以 message-only history 返回，服务器不会伪造思路、步骤、duration 或 title。

cursor 由服务端签名并绑定 cursor kind、user 和（history 时）conversation scope。篡改、
跨用户、跨 conversation、错误版本或不合法 token 一律返回 `400 CURSOR_INVALID`，不返回
SQL/签名细节。公开 process 的状态仅可为 `thinking`、`completed`、`superseded` 或
`unavailable`；步骤文本来自服务端固定 allowlist，时长为非负且 bounded 的服务器计算值。

### Run 状态

`status` 可为 `queued`、`leased`、`running`、`waiting_for_input`、
`waiting_for_capability`、`awaiting_effect_commit`、`completed`、
`model_unavailable`、`blocked_policy`、`budget_exhausted`、`cancelled` 或
`failed`。`terminal_outcome` 仅在终态出现，值为 `completed`、
`model_unavailable`、`blocked_policy`、`budget_exhausted`、`cancelled` 或
`failed`。

`MODEL_UNAVAILABLE` 表示主 provider 没有产生可安全使用的结果；Aearn 不尝试
跨 provider/model fallback。run read 和 SSE 都不会返回内部 provider diagnostics；
数据库中的受控诊断仅用于本地运维排查，且不会包含 provider response body、prompt、
reasoning、transport detail 或 credential。

## 6. Tutor SSE cursor 契约

### `GET /api/tutor/runs/{run_id}/events?user_id={uuid}`

- 可选 `Last-Event-ID` 必须是非负十进制 run-local cursor；空值等价于 `0`。
  非法值返回 `400 SSE_CURSOR_INVALID`。
- 首先 preflight 读取 run；随后轮询 durable ordered suffix。读取流永远不会
  调用 provider。
- 非 error event 带 `id: <event_sequence>`；event data 同时携带
  `run_id`、`input_revision`、`event_sequence` 与 `request_id`。
- 服务器发送 terminal `done`/`error` 后关闭流。路由级 error 可以没有 SSE ID；
  客户端必须保留上一数字 cursor。

| SSE `event` | 公开 data | 终态 |
| --- | --- | --- |
| `input_accepted` | `message_id`、`status="accepted"` | 否 |
| `tool_status` | 安全 `status`、`tool`、固定 learner-safe message | 否 |
| `activity` | effect `category`、安全 `status` | 否 |
| `run_state` | `status`、`terminal_outcome`、可选 learner-safe `public_message` | 可能 |
| `done` | `result_ref={type:"TutorRun",id}`、可选 `public_message` | 是 |
| `error` | 统一公开 error、可选 `public_message` | 是 |

SSE 不提供 raw learner messages、traces、selected Skill instructions、capability
arguments、effect payload、curation envelope、provider diagnostics 或 checkpoint
payload。

## 7. LearningTrack 路线与计划接口

所有 `/api/learning-tracks*` 路由都要求 verified user，并以 `user_id + track_id`
校验对象范围。一个用户可以创建多条 LearningTrack，同一语言的不同目标不会互相
覆盖；跨用户对象与不存在对象都返回 `404 LEARNING_TRACK_NOT_FOUND`。

| Method | Path | 请求/查询 | 响应与限制 |
| --- | --- | --- | --- |
| `GET` | `/api/learning-tracks` | `user_id` | track 列表、进度摘要、active revision、当前节点、`execution_tier` |
| `POST` | `/api/learning-tracks` | `user_id`、`client_action_id`、language/goal/target、完整 `plan`、可选 `conversation_id` | 原子创建 track、active revision、modules/nodes、初始 progress/mastery；201 或幂等重放 200 |
| `GET` | `/api/learning-tracks/{track_id}` | `user_id` | track detail 安全投影 |
| `GET` | `/api/learning-tracks/{track_id}/roadmap` | `user_id` | active revision 的 module/node、progress 与 bounded mastery state |
| `GET` | `/api/learning-tracks/{track_id}/plan-revisions` | `user_id` | predecessor-linked revision 摘要与 impact |
| `POST` | `/api/learning-tracks/{track_id}/plan-revisions` | `user_id`、`client_action_id`、`expected_track_version`、完整候选 `plan` | 创建 proposed revision，不改变 active pointer；201 或幂等重放 200 |
| `POST` | `/api/learning-tracks/{track_id}/plan-revisions/{revision_id}/activate` | `user_id`、`client_action_id`、`expected_track_version` | 只激活当前 active revision 的 proposed 直接后继；200 |

计划必须有 canonical SHA-256、稳定 lowercase `module_key` / `knowledge_key`、唯一
order 和无环 prerequisite DAG。proposal/activation 使用 track row lock + expected
version；冲突返回 `409 LEARNING_PLAN_VERSION_CONFLICT` 或
`LEARNING_PLAN_ACTIVATION_INVALID`。计划结构的输入错误返回统一 validation envelope；
track root 的 language/goal/target 不一致返回 `LEARNING_PLAN_INVALID`。

Track public projection 不返回 `plan_json`、mastery evidence body、source receipt hash、
provider、image lock fingerprint 或 executor health detail。`execution_tier` 只能是
`teaching_local | container_verified | static_only | unavailable`：development 可声明
teaching-local；public 必须同时拥有 reviewed immutable image lock 和 compatible health
才可声明 container-verified，否则 fail closed。

## 8. 学习控制接口

| Method | Path | 请求/查询 | 响应与限制 |
| --- | --- | --- | --- |
| `GET` | `/api/tutor/activity` | `user_id`、可选 `limit=1..100` | 安全 activity items |
| `GET` | `/api/tutor/inbox` | `user_id`、`include_dismissed`、`limit` | `unread/read/dismissed` inbox items |
| `POST` | `/api/tutor/inbox/{id}/read` | `user_id`、`client_action_id` | 幂等 read；无效 state 为 409 |
| `POST` | `/api/tutor/inbox/{id}/dismiss` | 同上 | 幂等 dismiss；无效 state 为 409 |
| `GET` | `/api/tutor/memory` | `user_id`、`include_inactive`、`limit` | 安全 memory items |
| `PATCH` | `/api/tutor/memory/{id}` | `user_id`、`client_action_id`、`statement<=180` | 追加 replacement memory |
| `DELETE` | `/api/tutor/memory/{id}` | `user_id`、`client_action_id` | guarded delete state |
| `GET` | `/api/tutor/plans/revisions` | `user_id`、`limit` | active revision 与 immutable history |
| `POST` | `/api/tutor/plans/rollback` | `user_id`、`client_action_id` | 只回退直接 predecessor；无前驱为 409 |
| `GET` | `/api/tutor/preferences` | `user_id` | `inferred_memory_enabled`、version、`proactive_paused`、`proactive_enabled` |
| `PATCH` | `/api/tutor/preferences` | `user_id`、`client_action_id`，至少一个 preference | 更新 memory / proactive 用户控制 |

`PATCH /preferences` 的 `inferred_memory_enabled` 若随附
`expected_memory_setting_version`，会在版本冲突时返回
`409 MEMORY_SETTING_VERSION_CONFLICT`。`proactive_paused=false` 会恢复用户
`enabled=true`，但不放宽服务器 verified、global pause、budget、cooldown、
concurrency 或 circuit gate。

### 受控 Action Runtime 的公开边界（2026-08-12）

Action Runtime 是 Harness 内部 orchestration/receipt 层，不新增 learner-facing 任意工具
endpoint。客户端不能提交 URL、路径、命令、镜像、环境变量、动态 MCP server、retry 次数或
resource escalation。公开 conversation/history/SSE 仍只消费既有 learner-safe message/process
投影；action receipt 仅通过服务端构建的 authoritative context 元数据影响后续 provider turn。

公开或本地导出最多包含 action id/version、terminal status、safe summary、authority kind/handle、
verification status 与 bounded recovery hint。raw arguments/result、provider body、private test/rubric、
learner code、command/path、内部异常和 secret 不属于 HTTP/SSE/export contract。

## 9. Background / executor 非 API 边界

- Celery 中只有 `tutor.proactive.scan_due_signals`、
  `tutor.proactive.drain_candidates` 和 `tutor.curation.drain` target task；它们
  不是公共 HTTP endpoint，也不接受用户任意 run/effect 参数。
- 默认主动建议仅从 safe interactive-terminal metadata 生成候选，结果只能进入
  activity/inbox。它不会发出 SSE chat、桌面通知、`runner.execute`、learner-code
  执行、subprocess 或直接 memory effect。
- Container executor 没有 HTTP endpoint。`TUTOR_EXECUTOR_ENABLED=false` 且
  reviewed immutable image lock 缺失时保持 safe unavailable；见
  [Executor Operations](../setup/container-sandbox-executor.md)。

## 10. 已移除的接口

当前 `main.py` 不注册旧 `/api/dashboard`、`/api/plans`、
`/api/learning-sessions`、`/api/reviews`、`/api/notes`、Graph event stream 或
SDK specialist route。调用方必须迁移到本文件中的 cutover/Tutor 接口；不得
通过兼容 adapter 重建旧业务状态。

## 11. 契约验证

最小自动验证覆盖：cutover gate/confirmation、LearningTrack contract/repository/API、
PostgreSQL scoped constraints、Tutor scope snapshot、Tutor public routes、SSE cursor 与
terminal ordering、run loop/persistence、activity/inbox/memory/plan、默认
proactive delivery、worker import、schema bootstrap 和 Desktop typed build。完整
可复现命令与结果记录在
[Release Readiness Ledger](../qa/tutor-harness-release-readiness.md)。

## 2026-08-10：Learning Home 与 planning session API

- `GET /api/learning-tracks/catalog?user_id={uuid}`：返回语言 `selection_tier`、`selectable`、lesson generation、server-resolved `execution_tier`/disclosure 与 source trust policy。
- `POST /api/learning-plan-sessions`：创建或恢复同一用户唯一未完成 session，并创建专用 Tutor conversation、绑定 `plan_drafting` scope。
- `GET /api/learning-plan-sessions/current` 与 `GET /api/learning-plan-sessions/{id}`：返回 user-scoped session 和当前 typed draft 安全投影。
- `POST /api/learning-plan-sessions/{id}/cancel`：按 expected session version 取消。
- `POST /api/learning-plan-sessions/{id}/confirm`：校验 session version、current draft id/version/hash 后，在同一事务创建 track/revision/route/progress 并改绑 conversation。

session 公开投影包含 learner-safe `planning_context={schema_version,facts[],questions[],fact_revision}`。
`facts[]` 只暴露稳定 field、normalized value、状态、revision、source kind 与 source
message/run/revision identity；`questions[]` 只暴露 `question_key`、`field_key` 和状态。
内部 value/event hash、question gate reason、prompt 与 provider body 不进入该投影。
草案保存其生成时的 facts fingerprint/revision；确认时如果 current facts 已变化，即使
调用方使用最新 session version，也返回 `409 LEARNING_PLAN_DRAFT_STALE`。

稳定错误包括 `LEARNING_PLAN_SESSION_NOT_FOUND`、`LEARNING_PLAN_SESSION_CONFLICT`、`LEARNING_PLAN_SESSION_ALREADY_CONFIRMED`、`LEARNING_PLAN_DRAFT_NOT_READY`、`LEARNING_PLAN_DRAFT_INVALID`、`LEARNING_PLAN_DRAFT_QUALITY_BLOCKED`、`LEARNING_PLAN_DRAFT_STALE` 和 `LEARNING_LANGUAGE_NOT_SELECTABLE`。

## 2026-08-11：LessonDocument API

所有 Lesson 路由都要求 verified user，并按 `user_id + track_id + knowledge_key`
校验 active plan node；跨用户对象与不存在对象统一返回 `404 LESSON_DOCUMENT_NOT_FOUND`。

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}?user_id=...` | 返回 `missing / preparing / ready / failed`；ready 仅包含 learner-safe document、active assignment、source snapshots 和可选 update proposal |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/prepare` | 使用 expected track/progress version 和幂等键创建/replay durable authoring run；新 run 返回 `202`，post-commit dispatch 不持有长事务 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/refresh` | 生成候选新版本；started assignment 只得到 proposal，不静默替换 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/start` | CAS 冻结 assignment，并只推进 `available -> in_progress` |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/migrations/{assignment_id}/activate` | 只激活 active assignment 的 direct proposed successor |

稳定错误包括 `LESSON_DOCUMENT_NOT_FOUND`、`LESSON_DOCUMENT_NOT_READY`、
`LESSON_DOCUMENT_VERSION_CONFLICT`、`LESSON_ASSIGNMENT_CONFLICT`、
`LESSON_SOURCE_EVIDENCE_INSUFFICIENT`、`LESSON_DOCUMENT_GENERATION_UNAVAILABLE`、
`LESSON_DOCUMENT_INVALID` 和 `LESSON_DOCUMENT_QUALITY_BLOCKED`。公共投影不包含 prompt、provider body、reasoning、内部 quality report、完整抓取原文、hidden test、reference answer、命令、路径或 credential。

## 2026-08-11：练习 Gate 与模块诊断 API

所有 Gate 和模块诊断路由都位于 `/api/learning-tracks`、要求 verified user，并按 exact `user_id + track_id + active plan revision + knowledge/module scope` 校验。跨用户、跨 track、locked Lesson、失效 assignment/binding 和不存在对象不泄漏存在性。mutation 使用 `client_action_id`/`Idempotency-Key`、request hash 与 expected version；同 key 同请求重放原响应，同 key 不同请求返回冲突。

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates?user_id=...` | 返回 active/frozen assignment 的 learner-safe Gate、exercise、tier、`allowed_actions` 与最新安全结果 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/prepare` | 使用 expected track/progress version 创建或重放 exact immutable binding/state |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/hints` | 使用 expected Gate version 追加有界 safe hint receipt；不返回 private rubric/reference answer |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/attempts` | `attempt_type=run | submit`；保存私有 submission，pending execution 返回 `202`，同步 static/local 结果可直接终态 |
| `GET` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/attempts/{attempt_id}?user_id=...` | 读取同一 Attempt 的 pending/terminal learner-safe projection，并可幂等触发 terminal projection |
| `POST` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics` | 只在服务端模块入口规则允许时冻结诊断版本/items；direct API 绕过同样被拒绝 |
| `GET` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics/{session_id}?user_id=...` | 返回 session、冻结能力/items、safe results、薄弱项、cooldown 和 proposed impact |
| `POST` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics/{session_id}/items/{item_id}/attempts` | 创建 `diagnostic_submit` Attempt；要求 independent-only，不提供提示/补救 |
| `POST` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics/{session_id}/confirm-skip` | 只确认当前 active predecessor 的 `passed_pending_confirmation` session，并原子激活 proposed revision |

公共 Gate/Attempt/diagnostic 投影不包含完整 submission、private tests、reference answer、private rubric、container/image、command/path、raw executor/provider response 或内部异常。稳定错误包括 `LESSON_GATE_NOT_FOUND`、`LESSON_GATE_NOT_READY`、`LESSON_GATE_VERSION_CONFLICT`、`EXERCISE_ATTEMPT_CONFLICT`、`EXECUTION_UNAVAILABLE`、`MODULE_DIAGNOSTIC_NOT_ALLOWED`、`MODULE_DIAGNOSTIC_COOLDOWN` 和 `MODULE_DIAGNOSTIC_VERSION_CONFLICT`；validation error 使用 learner-safe `422`。


## 2026-08-12：模型代码审核练习 API

`model_code_review` 是现有 Lesson Gate/Attempt contract 的正式 exercise type，不是旧
`review_ai_patch` 的别名。Gate prepare/read 可投影 `preparing | ready | failed` 的
`review_authoring_run`；客户端不得生成 fallback 题。模型审核 submit 必须且只能发送
`review_submission={schema_version,verdict,findings[],supplemental_note?}`，不能同时发送普通
`submission`，也不提供 learner Run。finding 包含稳定 client id、行范围、kind/category、
severity、trigger、principle、impact、validation method 与 suggested fix；服务端再次校验
verdict/finding shape、行范围和重复 ID。

`POST /api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/evidence`
只返回 verified prepublication checks 的 learner-safe projection，并写入 assistance receipt；
它不执行代码。Attempt/result 只返回 `submission_hash`、`assistance_kind`、确定性分数维度、
按 client finding id 的 `supported | partial | unsupported | duplicate`、omission band 与 next
 action，不返回 expected finding、隐藏测试、matcher token、private rubric 或 candidate body。
稳定错误包括 `MODEL_REVIEW_GENERATION_UNAVAILABLE`、`MODEL_REVIEW_CANDIDATE_INVALID`、
`MODEL_REVIEW_VALIDATION_UNAVAILABLE`、`MODEL_REVIEW_VALIDATION_FAILED`、
`MODEL_REVIEW_VALIDATION_STALE`、`MODEL_REVIEW_PUBLICATION_CONFLICT`、
`MODEL_REVIEW_SUBMISSION_INVALID` 与 `MODEL_REVIEW_EVIDENCE_UNAVAILABLE`。

## 2026-08-12：Track-scoped ReviewSession API

旧 top-level `/api/reviews` 仍属于已移除接口；正式复习只通过 verified-only 的
`/api/learning-tracks/{track_id}/reviews...` 路由访问，并按 exact
`user_id + track_id + active plan revision + knowledge_key` 校验。所有 mutation 使用
`client_action_id` 或 `Idempotency-Key`、request hash 与 expected version；同 key 同请求重放，
同 key 不同请求返回 `409 IDEMPOTENCY_CONFLICT`。

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/reviews?user_id=...` | 返回 actionable `due_count`、today queue、risk 与可选 `critical_prerequisite_gate`；普通 due 不构成课程 Gate，关键前置 `critical` 项立即投影 |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions` | 输入 `knowledge_key`、expected track/schedule version 与 `max_items=1..3`；冻结 plan/schedule/context/candidates；候选不足返回可恢复 `blocked` session |
| `GET` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}?user_id=...` | 恢复同一有限 session、冻结 item、Attempt 与 finalization 的 learner-safe 投影 |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/warmup` | `answered + confidence` 或 `skipped`；只写 warmup receipt 和 session stage，不写长期状态 |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/items/{item_id}/hints` | 追加有界 safe hint receipt，并把后续 Attempt 标为 hinted；不返回答案/private rubric |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/items/{item_id}/attempts` | 普通题发送 `submission`，模型审核题发送 `review_submission`，二者严格 one-of；静态结果同步 `200`，existing executor pending 为 `202` |
| `GET` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/attempts/{attempt_id}?user_id=...` | 读取 exact pending/terminal `review_submit` Attempt |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/finalize` | 仅在全部 item terminal 后执行唯一聚合；原子写 mastery evidence、schedule event/projection 和 finalization |

稳定错误包括 `REVIEW_NOT_FOUND`、`REVIEW_NOT_READY`、
`REVIEW_VERSION_CONFLICT`、`REVIEW_CANDIDATE_UNAVAILABLE`、
`REVIEW_CANDIDATE_INVALID`、`MODEL_REVIEW_SUBMISSION_INVALID`、
`EXECUTION_UNAVAILABLE` 和 `IDEMPOTENCY_CONFLICT`。候选不足是 session 内的
`failure_code=REVIEW_CANDIDATE_UNAVAILABLE`、`recoverable=true`，客户端可使用原幂等请求重试。
公共投影不包含完整 submission、private rubric/tests/reference answer、raw provider/executor
response、command/path/image/credential、内部 context hash 或 schedule event payload。
