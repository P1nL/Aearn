# Aearn Tutor HTTP 与 SSE API 契约

**状态：** 当前公共 API 契约，2026-08-20。
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
- 时间使用 ISO-8601 UTC 字符串。旧 run SSE 的 `event_sequence` 仍是单个 run 内的
  单调整数；新 conversation SSE 使用服务端签名的 opaque cursor，内部绑定 user、
  conversation、cursor version 与 conversation-global sequence，二者不能互换。

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

### 首发、普通输入与类型化 request response

| Method | Path | 请求/查询 | 成功响应 |
| --- | --- | --- | --- |
| `POST` | `/api/tutor/conversations/first-turn` | `user_id`、`client_action_id`、`content`、可选 `learning_scope` / `context_references` | 202（新首发）或 200（同 key 重放）；原子返回新 `conversation_id`、新 `run_id` 与初始公开 process |
| `POST` | `/api/tutor/conversations/{conversation_id}/inputs` | `user_id`、`client_action_id`、`content`、可选 `learning_scope` / `planning_facts` / `reopen_fact_fields` / `context_references` | idle 时 202 创建 fresh TurnRun；已有 active turn、pending request 或 Queue pause 时 202 进入 Queue；同 key 重放为 200 |
| `POST` | `/api/tutor/conversations/{conversation_id}/requests/{item_id}/responses` | `user_id`、`client_action_id`、`expected_request_version` 与 clarification/planning/approval closed-union response | 202（创建 fresh answer turn）或 200（API 幂等重放）；同 request/body 的跨 key 重放返回同一 answer turn |
| `POST` | `/api/tutor/runs/{run_id}/inputs` | legacy request shape | 永久 `410 Gone` tombstone；无论 protocol 都不写 message/event/job，不恢复 legacy continuation |
| `POST` | `/api/tutor/conversations` | `user_id`、`client_action_id`、可选 `conversation_id` / `learning_scope` | 兼容 create/resume 入口；Desktop draft 不调用它创建空 conversation |
| `GET` | `/api/tutor/runs/{run_id}?user_id={uuid}` | — | 当前 `TutorRun` 安全状态 |

`content` 必须是 trim 后非空且最多 16,000 字符。点击 Desktop “新对话”只建立本地
 draft；首个非空输入调用 `first-turn`，在同一 idempotent transaction 中创建
conversation、fresh interactive `TurnRun`、learner message/input event 和
`input_received` public-process。中间失败会整体回滚，不能留下空 conversation；同
idempotency key/body 重放返回相同 conversation/run ID，且不重复 dispatch；同 key
不同 body 返回 `409 IDEMPOTENCY_CONFLICT`。

每条普通 learner 消息都调用 conversation-input。conversation idle 时创建独立、有限的
`thread_turn_v2`；已有 active foreground turn、pending typed request 或 Queue pause 时，消息不会
supersede 当前 turn，而是在 conversation row lock 下进入最多 10 项的 FIFO Queue。Queue item 保存
原始输入的结构化 scope/context/planning metadata，claim 后才创建 fresh turn、learner message/input
event、process 和 dispatch job。显式 `Steer` 是唯一允许把指定 pending item 合并到当前 active
turn 的控制操作，并通过 expected control version、turn id、input revision 与 item version 执行 CAS。

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

五种阻塞意图固定为 `clarification | planning_input | approval | capability_result |
external_result`。`thread_turn_v2` provider 只能选择 kind、`planning_input` 的 allowlisted
`question_key` 与 bounded learner-safe 问题文本；presentation/options/limits、proposal identity
和 authority scope/hash 全部由服务端构造。来源 turn 在同一 transaction 创建
`tutor_interaction_requests` item，并以 `completed` + `completion_reason=awaiting_user |
awaiting_approval | awaiting_authority` 终结，不保留可继续消耗旧 deadline/counter/lease 的
`waiting_for_input`。

learner response route 只接受：`clarification.answer_text`、`planning_input` 的 exact
`question_key + tutor_planning_questions_v1 + typed value`，或 `approval` 的 exact
`proposal_identity + approve|deny + optional reason`。`expected_request_version`、request state、
user/conversation/item scope 与 canonical response hash 共同执行 CAS；成功后创建新的
`thread_turn_v2`、新的 policy deadline/counters/lease、learner message/input event、process、
dispatch job，并写 `response_to_request_id` 与 message `in_reply_to_item_id`。同 body 重放返回
同一 answer turn，不同 body、stale version 或普通文本冒充 approval 返回
`409 TUTOR_REQUEST_CONFLICT`。pending request 下的普通 Send 只进入 Queue，不解决 request、
不隐式 resume，也不把自由文本解释为 approval/authority response。

`capability_result | external_result` 没有 learner mutation route。内部 authority service 必须提交
issuer、subject、exact scope、request/result SHA-256、verification result 与 receipt identity；
只有 `verified` 才解决 request 并创建 fresh authority turn，`ambiguous | rejected` 保持 pending。

### Queue、Steer、Interrupt、resume、execute 与 Retry

| Method | Path | 请求/查询 | 成功响应 |
| --- | --- | --- | --- |
| `GET` | `/api/tutor/conversations/{conversation_id}/queue` | `user_id` | `control_state`、`control_version`、pause reason、pending count/max、typed items、active turn、pending request |
| `PATCH` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}` | `expected_control_version`、`expected_item_version`、`content` | 编辑 pending item 并递增 item/control version |
| `DELETE` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}` | `expected_control_version`、`expected_item_version` | 取消 pending item 并连续重排 position |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/reorder` | 完整 pending `item_ids[]`、`expected_control_version` | 原子重排完整 pending 集合 |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}/steer` | expected control/turn/input revision | 同一 active turn 增加 input revision；不创建新 run |
| `POST` | `/api/tutor/conversations/{conversation_id}/interrupt` | expected control/turn/input revision | public turn 进入 `interrupted`；有 Queue 时 pause reason=`interrupted` |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/resume` | `expected_control_version` | 显式解除 pause 并 FIFO claim；空 Queue 幂等返回 idle |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}/execute` | `expected_control_version` | 原子 interrupt 当前 turn（如有）并 fresh-claim 指定 item |
| `POST` | `/api/tutor/conversations/{conversation_id}/turns/{turn_id}/retry` | `expected_control_version` | recoverable failed/model-unavailable turn 创建 fresh retry lineage |

Queue mutation 都使用 API idempotency 与 conversation `control_version` CAS。pending request 阻塞
Steer/resume/execute/Retry，但不阻塞普通 Send 进入 Queue。只有正常 `completed` 的 worker completion
会自动 claim FIFO 队首；`interrupted`、`failed` 与 pending request 都 pause，必须由显式 resume/execute
或 request-owning fresh turn 的后续正常完成推进。`Retry` 固定 `retry_of_turn_id` 与稳定
`retry_root_turn_id`；effect logical action key 绑定 user/conversation/retry root/effect type/payload hash，
已 committed receipt 安全复用，proposed/ambiguous authority fail closed。

Queue 接受响应示例：

```json
{
  "conversation_id": "uuid",
  "queued": true,
  "queue_item": {
    "item_id": "uuid",
    "state": "pending",
    "position": 1,
    "version": 1,
    "content": "继续解释这个例子",
    "created_at": "timestamp",
    "updated_at": "timestamp"
  },
  "control_version": 3,
  "pending_count": 1,
  "max_pending": 10,
  "idempotent_replayed": false
}
```

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
  "dispatch_job_id": "uuid",
  "merged": false,
  "input_replayed": false,
  "idempotent_replayed": false,
  "replaced_run_id": null,
  "process": {
    "kind": "process",
    "id": "uuid",
    "turn_id": "uuid",
    "run_id": "uuid",
    "display_state": "thinking",
    "steps": [{"key": "input_received", "state": "completed", "label": "已接收你的问题"}],
    "elapsed_seconds": 0
  },
  "replaced_process": null,
  "context_references": [],
  "run": {
    "run_id": "uuid",
    "conversation_id": "uuid",
    "origin": "interactive",
    "status": "queued",
    "input_revision": 1,
    "terminal_outcome": null,
    "continuation_kind": null,
    "interaction_protocol_version": "thread_turn_v2",
    "retry_of_turn_id": null,
    "retry_root_turn_id": null,
    "response_to_request_id": null,
    "completion_reason": null
  }
}
```

新 public fresh turn 使用 `interaction_protocol_version=thread_turn_v2`；历史与内部
run 保持 `legacy_v1`。同一输入事务会同时创建或重新武装一条 one-row-per-run
`tutor_interactive_dispatch_jobs`，并返回 opaque `dispatch_job_id`。事务提交后路由只做
best-effort Celery wakeup 和本地低延迟 claim；PostgreSQL job/lease/generation 才是 dispatch
authority。wakeup 丢失、进程崩溃或 lease 过期由周期 reconciler 恢复。接受响应不泄露
dispatcher/provider 异常；run read、SSE、snapshot 和 history 只反映服务端安全投影。

### Conversation list、history 与 public process

| Method | Path | 查询 | 响应 |
| --- | --- | --- | --- |
| `GET` | `/api/tutor/conversations` | `user_id`、`limit=1..40`、可选 opaque `cursor` | learner-visible conversation summaries，按 `(last_public_activity_at DESC, id DESC)` 排序 |
| `GET` | `/api/tutor/conversations/{conversation_id}/history` | `user_id`、`limit=1..40`、可选 opaque `cursor` | 旧客户端兼容的倒序 message/process timeline、`next_cursor`、`has_more`、可选 active foreground run |
| `GET` | `/api/tutor/conversations/{conversation_id}/snapshot` | `user_id`、`limit=1..40`、可选 history cursor | `tutor_conversation_snapshot_v3`：保留 conversation/control version、public active turn、可选 exact `active_thinking`、pending typed request、typed timeline、Queue 与 opaque v2 `stream_cursor`，并新增可选 `active_runtime_output`；Desktop 保持 v2 read compatibility |
| `GET` | `/api/tutor/conversations/{conversation_id}/events` | `user_id`；可选 opaque `Last-Event-ID` | conversation-global append-only SSE；只读取 public event 表，不调用 provider |

list item 只含 `conversation_id`、服务端投影 title、`last_public_activity_at` 与可选
`active_run={run_id,status,continuation_kind}`；不返回 learner 原文 preview、provider/model
信息、trace 或诊断。snapshot v2 的 history item 是 `message`（含 public learner/Tutor
`content`、必需的 `context_references[]`，并为 Tutor message 返回 bounded
`public_thinking_text`；Tutor message 和无引用 learner/legacy message 的引用数组为空）或
`process`（只含 `display_state`、固定 allowlisted `steps[].label`、server-calculated
`elapsed_seconds` 与时间字段）。`public_thinking_text` 是 provider v4 明确写入最终可见 JSON
契约、经累计 safety validation 后与成功 Tutor message 或 typed request 原子持久化的纯文本；
它不是 Responses/DeepSeek 的原生 reasoning item。旧 `public_thinking_steps_json` 读取时以双换行
稳定连接；旧 `/history` 为兼容客户端继续把新文本投影为单元素 `public_thinking_steps[]`。
服务器不会伪造思路、步骤、duration 或 title。

history cursor 由服务端签名并绑定 cursor kind、user 和 conversation scope。篡改、跨用户、
跨 conversation、错误版本或不合法 token 一律返回 `400 CURSOR_INVALID`，不返回 SQL/签名
细节。snapshot timeline 使用严格 `TutorPublicItem` union：`message | process | elicitation |
approval | error`。`elicitation | approval` 来自 typed request row，只公开 stable ID、来源 turn、
kind/actor/state/version、bounded prompt、服务端 presentation、allowed actions 与 answer lineage；
issuer secret、raw result、capability args、provider schema 和 validation internals 不进入 public
payload。`pending_requests` 是当前 unresolved request authority；`queue` 是按 position 排序的 pending `TutorQueuedInput` exact projection。conversation 同时返回 `control_state=idle|running|waiting|queue_paused`、pause reason、pending count 与 max=10。公开 process 的
状态仅可为 `thinking | waiting_input | waiting_approval | waiting_authority | completed |
interrupted | superseded | unavailable | failed`；步骤文本来自服务端固定 allowlist，时长为
非负且 bounded 的服务器计算值。旧 `/history` 继续兼容 message/process，并 additive 返回
request item；response learner/authority message 可带 `in_reply_to_item_id`，不从文案猜测关联。

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

### `GET /api/tutor/conversations/{conversation_id}/events?user_id={uuid}`

- `Last-Event-ID` 是 opaque conversation cursor，不接受 run-local 数字 cursor。cursor
  tamper、版本不匹配、跨 user/conversation、超前或早于保留窗口返回
  `400 CONVERSATION_CURSOR_INVALID`；客户端应重新读取 snapshot。
- event `id` 为下一次重连应保存的 opaque cursor；data 只含 `event_id`、conversation-global
  `sequence`、闭合 `kind`、可选 turn/item reference、strict safe payload 与时间。
- kind 固定为 `turn_created | turn_updated | item_added | item_updated | turn_output |
  control_updated | dispatch_delayed | dispatch_dead`。heartbeat 是 SSE comment，不写数据库、不推进 cursor。
- `turn_output` 允许两个闭合版本：Harness compatibility 使用
  `tutor_public_thinking_stream_v1`；Codex raw Runtime 使用
  `tutor_runtime_item_stream_v1`，并额外携带 Aearn `item_id` 与
  `channel=reasoning|final_answer`。两者都绑定 exact turn identity、`input_revision`、
  `generation`、单调 `chunk_sequence` 与 closed operation；Desktop 可局部消费，
  identity/order/generation/shape 不匹配时必须 fresh snapshot。
- 事件写入与 owning mutation 同 transaction；相同 `(conversation_id,event_key)` 只允许完全
  相同的 public facts 幂等重放。SSE 不读取或转换 raw `tutor_run_events` payload。

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

## 2026-08-18：Codex plan-drafting Runtime admission

Tutor public input DTO 不新增 Runtime 字段。服务端仅对没有既有 Runtime lineage 的全新 `plan_drafting` conversation 执行 exact readiness admission；通过后在 run insert 时冻结 `runtime_kind=codex_sidecar_v1`。feature off 时新 plan-drafting 仍走 `harness_v1`；feature on 但 worker readiness 缺失、过期、不健康或 version/model/provider/protocol 不匹配时，输入返回 `503 TUTOR_RUNTIME_UNAVAILABLE`，且 first-turn 不留下空 conversation。general、learning-track、proactive 与既有 Harness conversation 不依赖 Codex health。

Queue/Steer/Interrupt/Retry 的公共路径和响应结构不变：Queue 接受时保存服务端冻结 Runtime；active Codex turn 的新 revision 映射为 `turn/steer`，cancel/supersede/lease loss 映射为 `turn/interrupt`；Retry 创建 fresh run 但复制 retry root Runtime，禁止跨 Runtime fallback。Codex 只可通过 typed tool 追加计划草案；`POST /api/learning-plan-sessions/{id}/confirm` 及 LearningTrack 创建仍由现有 Aearn transaction 执行。

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
`review_ai_patch` 的别名。authoring provider 只返回
`model_review_author_candidate_v2={schema_version,title,learner_instruction,candidate_code}`；
`template_id`、requirements、visible/hidden tests、expected outcomes、private rubric、findings、
coverage proof 与 score policy 全由服务端受控 template/DSL 构造，provider 多出的任何字段都使
candidate fail closed。Gate prepare/read 可投影 `preparing | ready | failed` 的
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
prepublication validation 必须匹配服务端 template identity/hash、exact runtime、test order/count、
visible/hidden visibility 与 expected pass/fail outcome；executor 不把 private template id、proof id
或 expected-pass metadata 传给 sandbox。稳定错误包括 `MODEL_REVIEW_GENERATION_UNAVAILABLE`、`MODEL_REVIEW_CANDIDATE_INVALID`、
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


## 2026-08-12：Tutor 结构化上下文引用

三个 Tutor 输入入口支持可选 `context_references`，最多 6 项，且仅允许
`learning_scope.scope_kind=learning_track`。引用是严格 discriminated union：

- `lesson_selection`：`learning_track_id`、`knowledge_key`、`document_id`、
  `document_content_hash`、`block_id`、`start_offset`、`end_offset`、`excerpt`；excerpt 最多 800 字符。
- `exercise_feedback`：`learning_track_id`、`knowledge_key`、terminal Lesson `attempt_id`。
- `execution_result`：同上，但 Attempt 必须存在真实 `execution_job_id`。
- `review_feedback`：`learning_track_id`、`knowledge_key`、`review_session_id`、terminal Review `attempt_id`。

服务端先固定 conversation/run 的 immutable LearningTrack task scope，再逐项读取 source of truth 并构造
`tutor_context_reference_v1` safe snapshot。Lesson 必须匹配同用户同 track/knowledge 的 active frozen
assignment、document/hash/block/range；Exercise/Execution/Review 必须匹配同 scope 的真实 terminal Attempt。
客户端提交的 excerpt、feedback 或 result 不直接进入快照。引用类型必须与 `lesson_teaching | exercise_feedback |
model_code_review | review_coaching | remediation` task scope 一致；引用不能用于 general/plan-drafting 输入。

输入接受事务把 learner message、run/input revision、run scope 与全部引用原子绑定；任一引用失败都会回滚整条输入。
acceptance response 与 learner history message 返回有序 safe references，模型 context loader 通过独立 required source
`tutor-context-references:{message_id}` 注入，不修改 learner `content`。快照只含 bounded safe excerpt、outcome、score、
safe feedback、capability scores、assistance、公开时间和必要 artifact identity；不得返回完整 submission、hidden test、
private rubric/reference answer、raw stdout/stderr、command、container、path、provider body 或 secret。

稳定错误包括：非法 union/数量/重复为 `422 CONTEXT_REFERENCE_INVALID`；scope/task/track/knowledge 冲突为
`409 CONTEXT_REFERENCE_SCOPE_CONFLICT`；active document/hash/range 变化为 `409 CONTEXT_REFERENCE_STALE`；terminal
Attempt 不存在为 `404 CONTEXT_REFERENCE_NOT_FOUND`；缺少真实 execution result 为
`409 CONTEXT_REFERENCE_NOT_READY`。同一个 Tutor idempotency key 的 request hash 包含引用数组；相同 key 不同引用不能
被误判为同请求重放。

## 2026-08-12：最终集成审计

最终集成没有新增第二套学习 API。LearningTrack、Lesson、Gate、ReviewSession 与 Tutor 输入继续使用本文件已列出的 verified-only 路由；旧 `/api/dashboard`、`/api/plans`、`/api/learning-sessions`、top-level `/api/reviews`、Graph/SDK specialist 路由仍未注册。

`tests/test_learning_agent_integration_matrix.py` 对 Python、JavaScript、TypeScript、SQL 逐一验证 track/plan、source-backed Lesson、active assignment、Gate、terminal feedback、private submission persistence、mastery/progress、due review、ReviewSession finalization 与 learner-safe projection。相同 fixture 同时断言：空 `image-locks.json` 下 public execution-required Gate 没有 `allowed_actions`，development fixture 只能返回 `teaching_local`。

公开响应的敏感字段审计按字段名递归执行，覆盖 Gate/Attempt/Review projections；既有专项测试继续覆盖 SSE/history/public process/trace/checkpoint/activity/inbox/export。任何完整 submission、private test/rubric/reference answer、raw provider/executor body、command/path/container/secret 都只能留在私有存储或被完全省略。


## 2026-08-14：Tutor thread/turn v2 全局 cutover API

- `GET /api/tutor/capabilities/thread-turn-v2?user_id=...` 返回 `tutor_thread_turn_v2_capability_v1`：`cutover_version=tutor_thread_turn_v2_global_v1`、`desktop_contract_version=tutor_thread_turn_v2_desktop_v1`、env/state/generation/summary/block/effective gate、安全 counts 与时间。
- 所有 Tutor mutation 仅在 `TUTOR_THREAD_TURN_V2_ENABLED=true` 且 DB state=`enabled` 时开放；否则返回 `503 TUTOR_THREAD_TURN_V2_UNAVAILABLE|PREPARING|BLOCKED`。history/snapshot/run detail/SSE 继续只读。
- `POST /api/tutor/runs/{run_id}/inputs` 对任意 run 固定返回无副作用 `410 TUTOR_LEGACY_CONTINUATION_DISABLED`，`next_action=start_new_turn`。
- legacy waiting migration 的 run SSE 公开 `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN`；其他 cutover cancellation 仍投影普通 interrupted/RUN_NOT_ACTIVE，不新增专用卡片。

## 2026-08-15：Tutor 公开思考文本流契约

- provider decision schema 为 `tutor_provider_items_v4`，新 `agent_message` 使用
  `public_thinking_text`（0..1280 字符纯文本）与最终 `text`；公共接口不暴露 raw reasoning。
- snapshot 为 `tutor_conversation_snapshot_v2`，可返回
  `active_thinking={turn_id,input_revision,generation,state,text,complete,last_event_sequence}`；
  它必须与 `active_turn` identity/revision 完全一致，否则省略或拒绝投影。
- conversation event projection 为 `tutor_conversation_event_v2`，opaque cursor version 为 2。
  `turn_output` 是唯一允许 Desktop 局部应用的事件；重复忽略、sequence/generation/chunk gap、
  extra field、错误 turn/revision 或旧 cursor 均回到 fresh snapshot。
- `append` 只表示通过累计文本安全检查的候选前缀，不构成展示 authority。`complete` 只能在完整
  provider object 已通过 schema/domain validation、公开文本安全检查以及 stream/final exact match 后发出；
  被 repair/reject 的 attempt 必须从 provisional `append` 直接进入 `discard`，不得先发 `complete`。
- 成功 `message` 与 `elicitation|approval` request item 都可携带 exact
  `public_thinking_text`。正式回答/问题文本只来自已持久化 snapshot；partial provider JSON 不构成回答 authority。
- legacy `/history` 继续返回旧形状：新文本投影为单元素 `public_thinking_steps[]`，旧 steps 原样读取；
  snapshot v2 只返回统一后的 `public_thinking_text`，不产生编号、说明或补写历史。
- API、SSE 与 snapshot 禁止包含 `reasoning`、`reasoning_content`、prompt、provider body/raw event、
  trace、diagnostic、credential、secret 或内部安全拒绝原因。

## 2026-08-20：Tutor snapshot v3 与 Codex raw Runtime item stream

`GET /api/tutor/conversations/{conversation_id}/snapshot` 当前返回 `tutor_conversation_snapshot_v3`。v3 保留 v2 的 conversation/control、`active_turn`、`active_thinking`、typed requests、Queue、timeline、opaque cursor，并新增可选 `active_runtime_output`：

- `output_version="tutor_runtime_output_v1"`；
- `input_revision` 与 active turn 完全一致，`generation` 为当前 Runtime connection generation；
- `reasoning_items[]` 与可选 `final_answer_item` 只包含 Aearn item ID、text、`streaming|completed` 和最后 public sequence；
- completed Tutor message 的 timeline item 可携带同形 `runtime_output`，用于刷新和历史恢复；无非空 reasoning 时不返回可见 Think 内容。

Desktop 必须继续兼容读取 v2；v2 没有 `active_runtime_output`。v3 public serializer 不返回 external thread/turn/item ID、provider/model metadata、prompt、tool arguments/results、reasoning summary、commentary、trace、diagnostic 或 credential。

conversation SSE 的 `turn_output` 现在接受两种闭合版本：

1. `tutor_public_thinking_stream_v1`：保留 Harness compatibility；
2. `tutor_runtime_item_stream_v1`：包含 `input_revision`、`generation`、`item_id`、`channel=reasoning|final_answer`、`operation=reset|append|complete|discard` 与单调 `chunk_sequence`。`append` 携带 delta text，`complete` 携带 authoritative full text，`reset|discard` 不携带 text。

commentary、reasoning summary 和未知 phase/channel 不得进入 public text stream。若 completed item 将 provisional `final_answer` 校正为 `commentary`，或 turn terminal 时仍有 streaming item，服务端发送不带 text 的 `discard` 并从 snapshot/history 排除该 item。重复或旧 sequence 可忽略；conversation-global gap、identity/revision/generation mismatch、closed-shape failure 或超限 text 必须停止局部 reducer 并 fresh snapshot recovery。

## 2026-08-21: Planning language intent and dynamic presentation

For `plan_drafting`, Aearn deterministically resolves an exact learner input before provider execution. A single explicit language with an active published course appends a confirmed `language_id` fact with `source_kind=deterministic_input` and `policy_version=planning-language-intent-v1`; the next request therefore targets the next missing fact. Multiple languages, direction-only input, unsupported input, or language/direction conflict never create a language fact.

A language `planning_input` presentation persists exact `options`, `recommended=null`, `selection_scope`, `selection_reason_code`, and `intent_policy_version`. Public option values remain canonical course-language values; internal course UUIDs and classification evidence are omitted. Refresh, reconnect, history, and response validation use the stored presentation as authority even if the catalog later changes. The optional model contract is exact `planning-intent-hint-v1` and may contain only closed intent tags; it cannot provide facts, course IDs, options, or recommendations.

## 2026-08-21：Runtime projection sequence 兼容说明

`tutor_runtime_item_stream_v1.chunk_sequence` 是 Aearn projection sequence，不是 provider/source notification sequence。服务端可以把多个连续同 item/kind/channel/index/phase delta 合并成一个 append；客户端只需按现有 closed union、identity 和连续 projection sequence 处理。source range/count/hash 仅存在于私有 PostgreSQL receipt，不加入 snapshot、history、SSE 或 Desktop DTO。gap 仍要求停止局部 reducer并读取 fresh snapshot；不得把缺口解释为模型 unavailable。

## 2026-08-23：TeachingSession authority API

所有 TeachingSession 路由均位于 verified-only `/api/learning-tracks` 边界，并按 exact `user_id + track_id + conversation_id + knowledge_key` 校验。mutation 复用 `client_action_id` / `Idempotency-Key`、request hash、PostgreSQL advisory lock 与 expected session/track/progress/assignment version；同 key 同请求返回原响应，同 key 不同请求返回 `409 IDEMPOTENCY_CONFLICT`。

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/teaching-sessions?user_id=...` | 返回该 track 的 bounded session summaries，不返回 checkpoint raw JSON、prompt、reasoning 或 provider body |
| `GET` | `/api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}?user_id=...` | 返回当前 nonterminal session、current checkpoint 的 learner-safe typed projection 与空/受控 `allowed_actions` |
| `POST` | `/api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}/open` | 输入 conversation、expected track/progress/assignment version 与 `guided | free_reading`；创建或恢复 exact current session，201 或幂等 200 |
| `POST` | `/api/learning-tracks/{track_id}/teaching-sessions/{session_id}/actions` | 输入 closed `control_key`、expected session/track/progress/assignment version、可选 target mode/knowledge/reason 与显式 `admit_run`；追加 checkpoint 并 CAS 推进 session |

`TutorTurnStimulus` 是 strict one-of：普通 learner input 绑定 exact learner message/input revision；explicit teaching control 或 domain event 可创建没有 learner message 的 fresh interactive TurnRun。公共 response/snapshot 只 additive 返回 safe teaching session/run-scope metadata。稳定错误包括 `TEACHING_SESSION_NOT_FOUND`、`TEACHING_AUTHORITY_CONFLICT`、`TEACHING_ACTION_INVALID`、`TEACHING_STIMULUS_INVALID` 与既有 `IDEMPOTENCY_CONFLICT`；跨用户、跨 track/conversation、stale checkpoint/session/progress/assignment/document/stimulus 一律 fail closed。
