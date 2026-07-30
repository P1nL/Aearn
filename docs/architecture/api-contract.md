# Aearn Tutor HTTP 与 SSE API 契约

**状态：** 当前公共 API 契约，2026-07-29。
**权威来源：** `aearn/services/api/app/main.py` 中注册的路由、Pydantic model、
`services/tutor/public_api.py`、`services/tutor/cutover.py` 与 API 测试。
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
投影：同 body 重放返回原响应并标记 `idempotent_replayed=true`；相同 key 配不同
不可变 body 返回 `409 IDEMPOTENCY_CONFLICT`，绝不重复写入或重新调用 provider。

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

## 5. Tutor 会话与 run 接口

所有本节接口均要求 verified user。

### Conversation 与输入

| Method | Path | 请求 body | 成功响应 |
| --- | --- | --- | --- |
| `POST` | `/api/tutor/conversations` | `user_id`、`client_action_id`、可选 `conversation_id` | `conversation_id`、`created`、`idempotent_replayed` |
| `POST` | `/api/tutor/conversations/{conversation_id}/inputs` | `user_id`、`client_action_id`、`content` | 202（新接受）或 200（重放）；见下方 input response |
| `POST` | `/api/tutor/runs/{run_id}/inputs` | 同上 | 202（新接受）或 200（重放/merge） |
| `GET` | `/api/tutor/runs/{run_id}?user_id={uuid}` | — | 当前 `TutorRun` 安全状态 |

`content` 必须是 trim 后非空且最多 16,000 字符。Conversation input 会创建新的
interactive run，或将输入合并进同 conversation 的兼容非终态 run；明确 run
input 只接受未取消且尚未 terminal 的 interactive run。终态/不兼容 run 返回
`409 RUN_NOT_ACTIVE`。

输入响应示例：

```json
{
  "conversation_id": "uuid",
  "run_id": "uuid",
  "input_revision": 2,
  "message_id": "uuid",
  "event_cursor": 8,
  "merged": true,
  "input_replayed": false,
  "idempotent_replayed": false,
  "run": {
    "run_id": "uuid",
    "conversation_id": "uuid",
    "origin": "interactive",
    "status": "queued",
    "input_revision": 2,
    "cancelled": false,
    "iteration_count": 0,
    "model_call_count": 0,
    "capability_call_count": 0,
    "effect_count": 0,
    "terminal_outcome": null,
    "diagnostic_code": null,
    "created_at": "...",
    "updated_at": "..."
  }
}
```

接受输入的事务完成后，路由安排 post-commit interactive dispatch。接受响应本身
不泄露 dispatcher/provider 异常，SSE/run read 才反映公开的 terminal outcome。

### Run 状态

`status` 可为 `queued`、`leased`、`running`、`waiting_for_input`、
`waiting_for_capability`、`awaiting_effect_commit`、`completed`、
`model_unavailable`、`blocked_policy`、`budget_exhausted`、`cancelled` 或
`failed`。`terminal_outcome` 仅在终态出现，值为 `completed`、
`model_unavailable`、`blocked_policy`、`budget_exhausted`、`cancelled` 或
`failed`。

`MODEL_UNAVAILABLE` 表示主 provider 没有产生可安全使用的结果；Aearn 不尝试
跨 provider/model fallback。

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
| `run_state` | `status`、`terminal_outcome` | 可能 |
| `done` | `result_ref={type:"TutorRun",id}`、可选 `public_message` | 是 |
| `error` | 统一公开 error、可选 `public_message` | 是 |

SSE 不提供 raw learner messages、traces、selected Skill instructions、capability
arguments、effect payload、curation envelope、provider diagnostics 或 checkpoint
payload。

## 7. 学习控制接口

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

## 8. Background / executor 非 API 边界

- Celery 中只有 `tutor.proactive.scan_due_signals`、
  `tutor.proactive.drain_candidates` 和 `tutor.curation.drain` target task；它们
  不是公共 HTTP endpoint，也不接受用户任意 run/effect 参数。
- 默认主动建议仅从 safe interactive-terminal metadata 生成候选，结果只能进入
  activity/inbox。它不会发出 SSE chat、桌面通知、`runner.execute`、learner-code
  执行、subprocess 或直接 memory effect。
- Container executor 没有 HTTP endpoint。`TUTOR_EXECUTOR_ENABLED=false` 且
  reviewed immutable image lock 缺失时保持 safe unavailable；见
  [Executor Operations](../setup/container-sandbox-executor.md)。

## 9. 已移除的接口

当前 `main.py` 不注册旧 `/api/dashboard`、`/api/plans`、
`/api/learning-sessions`、`/api/reviews`、`/api/notes`、Graph event stream 或
SDK specialist route。调用方必须迁移到本文件中的 cutover/Tutor 接口；不得
通过兼容 adapter 重建旧业务状态。

## 10. 契约验证

最小自动验证覆盖：cutover gate/confirmation、Tutor public routes、SSE cursor
与 terminal ordering、run loop/persistence、activity/inbox/memory/plan、默认
proactive delivery、worker import、schema bootstrap 和 Desktop typed build。完整
可复现命令与结果记录在
[Release Readiness Ledger](../qa/tutor-harness-release-readiness.md)。
