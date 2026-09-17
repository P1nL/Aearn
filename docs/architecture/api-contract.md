# Aearn Tutor HTTP 与 SSE API 契约

**状态：** 当前公共 API 契约，2026-09-17。
**阅读说明：** 本次为 2026-09-17 本地源码静态核对；带日期的小节保留当时的契约演进与证据边界，较新修订优先，不代表本次执行了数据库、浏览器或真实提供方验收。
**权威来源：** `aearn/services/api/app/main.py` 中注册的路由、Pydantic 模型、
`services/tutor/public_api.py`、`services/learning/`、`services/tutor/cutover.py` 与 API 测试。
**不适用：** 已移除的 Graph、Dashboard、Onboarding、Learning Session、旧版 Review、
Notes 和旧流式端点。旧版 Review 不包括当前注册的路线复习接口；历史文档不构成当前可调用 API。

## 1. 通用约定

<a id="base-url-与编码"></a>
### 基础 URL 与编码

- 本地 API 默认 `http://127.0.0.1:8001`。
- 请求和响应使用 UTF-8 JSON，SSE 端点使用 `text/event-stream`。
- 用户、对话、运行、记忆、收件箱与计划修订公开 ID 都按 UUID
  处理；服务端会校验范围，客户端不能用另一个用户 ID 读取/修改数据。
- 时间使用 ISO-8601 UTC 字符串。旧运行 SSE 的 `event_sequence` 仍是单个运行内的
  单调整数；新对话 SSE 使用服务端签名的不透明游标，内部绑定用户、
  对话、游标版本与对话全局序号，二者不能互换。

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
不会包含提供方错误正文、提示词、推理、隐藏测试、参考答案、
学习者代码、检查点、路径、命令或密钥。

<a id="tutor-mutation-幂等性"></a>
### Tutor 写操作幂等性

所有 `/api/tutor` 写操作都要求请求体中的 `client_action_id`；客户端也可以用
同格式的 `Idempotency-Key` 请求头覆盖它。合法格式为：

```text
[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}
```

服务端按 `(user_id, operation, idempotency_key, request_body_hash)` 存储安全响应
投影；写操作在查找/写入前按 `(user_id, operation, idempotency_key)` 获取事务级咨询锁，因此并发的首次写入也只执行一次。同请求体重放返回原响应并标记
`idempotent_replayed=true`；相同键配不同不可变请求体返回 `409 IDEMPOTENCY_CONFLICT`，
绝不重复写入或重新调用提供方。
`/api/learning-tracks` 写操作复用同一存储与键格式，但使用独立
`learning_track.*` 操作命名空间。

<a id="2-runtime-gate"></a>
## 2. 运行时准入门禁

`/api/tutor/*` 的每一个端点都先检查当前受控切换版本的
`harness_cutovers` 回执：只有 `state=verified` 可访问。`summary_ready`、
`required`、`verification_failed`、`blocked_target_state` 和
`blocked_checkpoint_scope` 统一拒绝。客户端/本地缓存不能替代这个门禁。

| 常见门禁错误 | HTTP | 含义 |
| --- | ---: | --- |
| `CUTOVER_REQUIRED` | 409 | 需要先获得或确认服务器摘要 |
| `CUTOVER_TARGET_STATE_PRESENT` | 409 | 预切换 Tutor 数据存在，系统不删除它 |
| `CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED` | 409 | 不能证明旧检查点的删除范围 |
| `CUTOVER_VERIFICATION_FAILED` | 409 | 删除事务已回滚或不能验证，两个运行时继续锁定 |

## 3. 基础与本地身份接口

| 方法 | 路径 | 成功 | 说明 |
| --- | --- | ---: | --- |
| `GET` | `/health` | 200 | `{"status":"ok","service":"aearn-api"}` |
| `GET` | `/api/language-courses` | 200 | `language`、`level`、`limit=1..100` 过滤后的目录；不创建计划 |
| `GET` | `/api/environment/doctor` | 200 | 本地环境诊断的公开报告 |
| `POST` | `/api/users` | 201 | 创建本地用户，请求体至少有 `display_name` |
| `GET` | `/api/users` | 200 | 本地用户列表 |
| `GET` | `/api/users/{user_id}` | 200 | 当前用户资料；不存在返回 `USER_NOT_FOUND` |
| `GET` | `/api/users/{user_id}/data-summary` | 200 | 本地历史数据摘要，仅用于用户数据操作 |
| `GET` | `/api/users/{user_id}/export` | 200 | 本地用户导出，不是 Tutor 诊断轨迹/导出 API |
| `POST` | `/api/users/{user_id}/reset-data` | 200 | 必须 JSON `{"confirm":true}`；未已验证用户不能借此完成切换 |
| `DELETE` | `/api/users/{user_id}` | 200 | 必须 JSON `{"confirm":true}` |
| `PATCH` | `/api/users/{user_id}/preferences` | 200 | 只更新允许的本地用户偏好 |

创建用户的历史画像字段可以被接收以支持切换清点，但它们不代表当前 Tutor
计划/FSRS/Graph 运行时。桌面端正常入口只要求显示名称，然后立即读取
受控切换决策。

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
  `summary`。`summary` 仅列出旧版类别数量、待清空资料字段、
  检查点状态/数量、保留类别和是否存在目标状态。
- 两类被阻塞响应包含稳定 `code` 和安全 `summary`；服务器不会执行删除。
- 没有旧版数据且没有目标状态污染的用户会由此调用直接变为
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

服务器锁定用户、重算规范摘要、检查精确版本/一次性随机值/哈希、删除
已证明归属的旧范围、验证相同范围并保留身份/通知字段。成功返回
`state=verified`；相同确认的安全重放会返回 `idempotent_replayed=true`。

`CUTOVER_SUMMARY_STALE`、`CUTOVER_CONFIRMATION_CONFLICT`、目标状态、未知
检查点作用域或验证失败都不产生半完成删除。代码回滚之后也不会恢复已经
确认删除的历史。

## 5. Tutor 会话、TurnRun 与历史接口

所有本节接口均要求已验证用户；所有 UUID、幂等性重放、游标和读取范围都
同时受当前 `user_id` 约束。

<a id="首发普通输入与类型化-request-response"></a>
### 首发、普通输入与类型化请求响应

| 方法 | 路径 | 请求/查询 | 成功响应 |
| --- | --- | --- | --- |
| `POST` | `/api/tutor/conversations/first-turn` | `user_id`、`client_action_id`、`content`、可选 `learning_scope` / `context_references` | 202（新首发）或 200（同键重放）；原子返回新 `conversation_id`、新 `run_id` 与初始公开过程 |
| `POST` | `/api/tutor/conversations/{conversation_id}/inputs` | `user_id`、`client_action_id`、`content`、可选 `learning_scope` / `planning_facts` / `reopen_fact_fields` / `context_references` | 空闲时 202 创建新建 TurnRun；已有活跃回合、待处理请求或队列暂停时 202 进入队列；同键重放为 200 |
| `POST` | `/api/tutor/conversations/{conversation_id}/requests/{item_id}/responses` | `user_id`、`client_action_id`、`expected_request_version` 与澄清/规划/批准闭合联合类型响应 | 202（创建新建答案回合）或 200（API 幂等重放）；同请求/请求体的跨键重放返回同一答案回合 |
| `POST` | `/api/tutor/runs/{run_id}/inputs` | 旧版请求结构 | 永久 `410 Gone` 退役标记；无论协议都不写消息/事件/任务，不恢复旧版续接 |
| `POST` | `/api/tutor/conversations` | `user_id`、`client_action_id`、可选 `conversation_id` / `learning_scope` | 兼容创建/恢复入口；桌面端草案不调用它创建空对话 |
| `GET` | `/api/tutor/runs/{run_id}?user_id={uuid}` | — | 当前 `TutorRun` 安全状态 |

`content` 必须是去除首尾空白后非空且最多 16,000 字符。点击桌面端 “新对话”只建立本地
 草案；首个非空输入调用 `first-turn`，在同一幂等事务中创建
对话、新建交互式 `TurnRun`、学习者消息/输入事件和
`input_received` 公开过程。中间失败会整体回滚，不能留下空对话；同
幂等键/正文重放返回相同对话/运行 ID，且不重复分发；同键
不同请求体返回 `409 IDEMPOTENCY_CONFLICT`。

每条普通学习者消息都调用对话输入。对话空闲时创建独立、有限的
`thread_turn_v2`；已有活跃前台回合、待处理类型化请求或队列暂停时，消息不会
取代当前回合，而是在对话行锁下进入最多 10 项的先进先出队列。队列条目保存
原始输入的结构化作用域/上下文/规划元数据，领取后才创建新回合、学习者消息/输入
事件、过程和分发任务。显式 `Steer` 是唯一允许把指定待处理条目合并到当前活跃
回合的控制操作，并通过预期控制版本、回合 id、输入修订与条目版本执行 CAS。

`learning_scope` 是增量结构化输入：`scope_kind` 为 `general | plan_drafting |
learning_track`；首回合/普通回合的学习路线作用域还可固定仅属于单次运行的
`task_kind` 与 `knowledge_key`。单独 `/conversations` 绑定只持久化宽泛
作用域/学习路线，若携带仅属于单次运行的字段则返回 `409 LEARNING_SCOPE_CONFLICT`，不会静默丢弃。
未提供时新运行快照为 `general/general_tutor`。旧对话没有
作用域行时也只投影为通用，不从聊天正文推断归属。

当 `learning_scope.scope_kind=plan_drafting` 时，三个 Tutor 输入入口还可携带可选
`planning_facts` 与 `reopen_fact_fields`。`planning_facts` 只接受
`language_id`、`goal_text`、`target_level`、`weekly_minutes`、
`experience_level`、`teaching_preferences`、`pace_constraints`；值由服务端
规范化/校验，并绑定已接受的学习者消息、运行和输入修订。
`reopen_fact_fields` 使用同一稳定字段键，表示学习者主动重新开启收集；普通
对话不会因为请求里出现这些字段而获得规划权威来源。同一个
幂等键的请求哈希包含这两个字段，因此变更事实或重新开启集合不会被
误判为同请求重放。

五种阻塞意图固定为 `clarification | planning_input | approval | capability_result |
external_result`。`thread_turn_v2` provider 只能选择 kind、`planning_input` 的在允许清单中的
`question_key` 与有界面向学习者的安全问题文本；呈现/选项/上限、提案身份
和权威来源作用域/哈希全部由服务端构造。来源回合在同一事务创建
`tutor_interaction_requests` 条目，并以 `completed` + `completion_reason=awaiting_user |
awaiting_approval | awaiting_authority` 终结，不保留可继续消耗旧截止时间/计数器/租约的
`waiting_for_input`。

学习者响应路由只接受：`clarification.answer_text`、`planning_input` 的精确
`question_key + tutor_planning_questions_v1 + typed value`，或 `approval` 的精确
`proposal_identity + approve|deny + optional reason`。`expected_request_version`、请求状态、
用户/对话/条目作用域与规范响应哈希共同执行 CAS；成功后创建新的
`thread_turn_v2`、新的策略截止时间/计数器/租约、学习者消息/输入事件、过程、
分发任务，并写 `response_to_request_id` 与消息 `in_reply_to_item_id`。同请求体重放返回
同一答案回合，不同请求体、过期版本或普通文本冒充批准返回
`409 TUTOR_REQUEST_CONFLICT`。待处理请求下的普通发送只进入队列，不解决请求、
不隐式恢复，也不把自由文本解释为批准/权威来源响应。

`capability_result | external_result` 没有学习者写操作路由。内部权威来源服务必须提交
签发方、主体、精确作用域、请求/结果 SHA-256、验证结果与回执身份；
只有 `verified` 才解决请求并创建新建权威来源回合，`ambiguous | rejected` 保持待处理。

<a id="queuesteerinterruptresumeexecute-与-retry"></a>
### 队列、转向、打断、恢复、执行与重试

| 方法 | 路径 | 请求/查询 | 成功响应 |
| --- | --- | --- | --- |
| `GET` | `/api/tutor/conversations/{conversation_id}/queue` | `user_id` | `control_state`、`control_version`、暂停原因、待处理数量/上限、类型化条目、活跃轮次、待响应请求 |
| `PATCH` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}` | `expected_control_version`、`expected_item_version`、`content` | 编辑待处理条目并递增条目/控制版本 |
| `DELETE` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}` | `expected_control_version`、`expected_item_version` | 取消待处理条目并连续重排位置 |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/reorder` | 完整待处理 `item_ids[]`、`expected_control_version` | 原子重排完整待处理集合 |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}/steer` | 预期控制/回合/输入修订 | 同一活跃回合增加输入修订；不创建新运行 |
| `POST` | `/api/tutor/conversations/{conversation_id}/interrupt` | 预期控制/回合/输入修订 | 公开回合进入 `interrupted`；有队列时暂停原因=`interrupted` |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/resume` | `expected_control_version` | 显式解除暂停并先进先出领取；空队列幂等返回空闲 |
| `POST` | `/api/tutor/conversations/{conversation_id}/queue/{item_id}/execute` | `expected_control_version` | 原子中断当前回合（如有）并新建领取指定条目 |
| `POST` | `/api/tutor/conversations/{conversation_id}/turns/{turn_id}/retry` | `expected_control_version` | 可恢复失败/模型不可用回合创建新建重试沿袭关系 |

队列写操作都使用 API 幂等性与对话 `control_version` CAS。待处理请求阻塞
转向/恢复/执行/重试，但不阻塞普通发送进入队列。只有正常 `completed` 的工作进程完成
会自动领取先进先出队首；`interrupted`、`failed` 与待处理请求都暂停，必须由显式恢复/执行
或请求所属新回合的后续正常完成推进。`Retry` 固定 `retry_of_turn_id` 与稳定
`retry_root_turn_id`；副作用逻辑动作键绑定用户/对话/重试根/副作用类型/载荷哈希，
已已提交回执安全复用，已提议/含糊不明权威来源拒绝继续处理。

队列接受响应示例：

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

安全标题只能在同次成功 Tutor 决策写入学习者可见的回复时尝试写入，使用
NFKC 单行且最多 48 字符的 `conversation_title`，并以 `WHERE title IS NULL` 固定一次。
无标题时对外显示“新对话”；不得从学习者原文回退命名，也没有重命名 API。

普通回合响应示例：

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

新建的公开回合使用 `interaction_protocol_version=thread_turn_v2`；历史与内部
运行保持 `legacy_v1`。同一输入事务为新运行创建一条
`tutor_interactive_dispatch_jobs`，并返回不透明 `dispatch_job_id`。事务提交后路由只做
尽力而为的 Celery 唤醒信号和本地低延迟领取；PostgreSQL 任务/租约/世代才是分发
权威来源。唤醒信号丢失、进程崩溃或租约过期由周期核对器恢复。接受响应不泄露
分发器/提供方异常；运行读取、SSE、快照和历史只反映服务端安全投影。

<a id="conversation-listhistory-与-public-process"></a>
### 会话列表、历史与公开过程

| 方法 | 路径 | 查询 | 响应 |
| --- | --- | --- | --- |
| `GET` | `/api/tutor/conversations` | `user_id`、`limit=1..40`、可选不透明 `cursor` | 学习者可见的对话摘要，按 `(last_public_activity_at DESC, id DESC)` 排序 |
| `GET` | `/api/tutor/conversations/{conversation_id}/history` | `user_id`、`limit=1..40`、可选不透明 `cursor` | 旧客户端兼容的倒序消息/过程时间线、`next_cursor`、`has_more`、可选活跃前台运行 |
| `GET` | `/api/tutor/conversations/{conversation_id}/snapshot` | `user_id`、`limit=1..40`、可选历史游标 | 无 Artifact/分支历史时为 `tutor_conversation_snapshot_v3`，存在 Artifact 时为 v4、存在分支历史时为 v5：保留对话/控制版本、公开活跃回合、可选精确 `active_thinking`、待处理类型化请求、类型化时间线、队列与不透明 v2 `stream_cursor`，并返回可选 `active_runtime_output`；v4/v5 另含 Artifact/分支状态，桌面端保持 v2-v5 读取兼容 |
| `GET` | `/api/tutor/conversations/{conversation_id}/events` | `user_id`；可选不透明 `Last-Event-ID` | 对话全局仅追加 SSE；只读取公开事件表，不调用提供方 |

列表条目只含 `conversation_id`、服务端投影标题、`last_public_activity_at` 与可选
`active_run={run_id,status,continuation_kind}`；不返回学习者原文预览、提供方/模型
信息、诊断轨迹或诊断。快照 v2 的历史条目是 `message`（含公开学习者/Tutor
`content`、必需的 `context_references[]`，并为 Tutor 消息返回有界
`public_thinking_text`；Tutor 消息和无引用学习者/旧版消息的引用数组为空）或
`process`（只含 `display_state`、固定在允许清单中的 `steps[].label`、服务端计算得到的
`elapsed_seconds` 与时间字段）。`public_thinking_text` 是当前提供方 v5（兼容 v4）明确写入最终可见 JSON
契约、经累计安全性校验后与成功 Tutor 消息或类型化请求原子持久化的纯文本；
它不是 Responses/DeepSeek 的原生推理条目。旧 `public_thinking_steps_json` 读取时以双换行
稳定连接；旧 `/history` 为兼容客户端继续把新文本投影为单元素 `public_thinking_steps[]`。
服务器不会伪造思路、步骤、时长或标题。

历史游标由服务端签名并绑定游标种类、用户和对话作用域。篡改、跨用户、
跨对话、错误版本或不合法令牌一律返回 `400 CURSOR_INVALID`，不返回 SQL/签名
细节。基础快照时间线使用严格 `TutorPublicItem` 联合类型；以下为基础分支，当前还包含 `artifact` 分支：`message | process | elicitation |
approval | error`。`elicitation | approval` 来自类型化请求行，只公开稳定 ID、来源回合、
种类/参与方/状态/版本、有界提示词、服务端呈现、允许的动作与答案沿袭关系；
签发方密钥、原始结果、能力参数、提供方结构契约和校验内部细节不进入公开
载荷。`pending_requests` 是当前未解决请求权威来源；`queue` 是按位置排序的待处理 `TutorQueuedInput` 精确投影。对话同时返回 `control_state=idle|running|waiting|queue_paused`、暂停原因、待处理数量与上限=10。公开过程的
状态仅可为 `thinking | waiting_input | waiting_approval | waiting_authority | completed |
interrupted | superseded | unavailable | failed`；步骤文本来自服务端固定允许清单，时长为
非负且有界的服务器计算值。旧 `/history` 继续兼容消息/过程，并增量返回
请求条目；响应学习者/权威来源消息可带 `in_reply_to_item_id`，不从文案猜测关联。

<a id="run-状态"></a>
### 运行状态

`status` 可为 `queued`、`leased`、`running`、`waiting_for_input`、
`waiting_for_capability`、`awaiting_effect_commit`、`completed`、
`model_unavailable`、`blocked_policy`、`budget_exhausted`、`cancelled` 或
`failed`。`terminal_outcome` 仅在终态出现，值为 `completed`、
`model_unavailable`、`blocked_policy`、`budget_exhausted`、`cancelled` 或
`failed`。

`MODEL_UNAVAILABLE` 表示主提供方没有产生可安全使用的结果；Aearn 不尝试
跨提供方/模型降级。运行读取和 SSE 都不会返回内部提供方诊断；
数据库中的受控诊断仅用于本地运维排查，且不会包含提供方响应体、提示词、
推理、传输详情或凭据。

<a id="6-tutor-sse-cursor-契约"></a>
## 6. Tutor SSE 游标契约

### `GET /api/tutor/runs/{run_id}/events?user_id={uuid}`

- 可选 `Last-Event-ID` 必须是非负十进制运行本地游标；空值等价于 `0`。
  非法值返回 `400 SSE_CURSOR_INVALID`。
- 首先预检读取运行；随后轮询持久化有序后缀。读取流永远不会
  调用提供方。
- 非错误事件带 `id: <event_sequence>`；事件数据同时携带
  `run_id`、`input_revision`、`event_sequence` 与 `request_id`。
- 服务器发送终态 `done`/`error` 后关闭流。路由级错误可以没有 SSE ID；
  客户端必须保留上一数字游标。

| SSE `event` | 公开数据 | 终态 |
| --- | --- | --- |
| `input_accepted` | `message_id`、`status="accepted"` | 否 |
| `tool_status` | 安全 `status`、`tool`、固定面向学习者的安全消息 | 否 |
| `activity` | 副作用 `category`、安全 `status` | 否 |
| `run_state` | `status`、`terminal_outcome`、可选面向学习者的安全 `public_message` | 可能 |
| `done` | `result_ref={type:"TutorRun",id}`、可选 `public_message` | 是 |
| `error` | 统一公开错误、可选 `public_message` | 是 |

SSE 不提供原始学习者消息、诊断轨迹、已选 Skill 指令、能力
参数、副作用载荷、整理信封、提供方诊断或检查点
载荷。

### `GET /api/tutor/conversations/{conversation_id}/events?user_id={uuid}`

- `Last-Event-ID` 是不透明对话游标，不接受运行本地数字游标。游标
  篡改、版本不匹配、跨用户/对话、超前或早于保留窗口返回
  `400 CONVERSATION_CURSOR_INVALID`；客户端应重新读取快照。
- 事件 `id` 为下一次重连应保存的不透明游标；数据只含 `event_id`、对话全局
  `sequence`、闭合 `kind`、可选回合/条目引用、严格安全载荷与时间。
- 种类固定为 `turn_created | turn_updated | item_added | item_updated | turn_output |
  control_updated | dispatch_delayed | dispatch_dead`。心跳是 SSE 注释，不写数据库、不推进游标。
- `turn_output` 允许两个闭合版本：Harness 兼容使用
  `tutor_public_thinking_stream_v1`；Codex 原始运行时使用
  `tutor_runtime_item_stream_v1`，并额外携带 Aearn `item_id` 与
  `channel=reasoning|final_answer`。两者都绑定精确回合身份、`input_revision`、
  `generation`、单调 `chunk_sequence` 与闭合操作；桌面端可局部消费，
  身份/顺序/世代/结构不匹配时必须新建快照。
- 事件写入与所属写操作同事务；相同 `(conversation_id,event_key)` 只允许完全
  相同的公开事实幂等重放。SSE 不读取或转换原始 `tutor_run_events` 载荷。

## 7. LearningTrack 路线与计划接口

所有 `/api/learning-tracks*` 路由都要求已验证用户，并以 `user_id + track_id`
校验对象范围。一个用户可以创建多条 LearningTrack，同一语言的不同目标不会互相
覆盖；跨用户对象与不存在对象都返回 `404 LEARNING_TRACK_NOT_FOUND`。

| 方法 | 路径 | 请求/查询 | 响应与限制 |
| --- | --- | --- | --- |
| `GET` | `/api/learning-tracks` | `user_id` | 学习路线列表、进度摘要、活跃修订、当前节点、`execution_tier` |
| `POST` | `/api/learning-tracks` | `user_id`、`client_action_id`、语言/目标/目标、完整 `plan`、可选 `conversation_id` | 原子创建学习路线、活跃修订、模块/节点、初始进度/掌握度；201 或幂等重放 200 |
| `GET` | `/api/learning-tracks/{track_id}` | `user_id` | 学习路线详情安全投影 |
| `GET` | `/api/learning-tracks/{track_id}/roadmap` | `user_id` | 活跃修订的模块/节点、进度与有界掌握度状态 |
| `GET` | `/api/learning-tracks/{track_id}/plan-revisions` | `user_id` | 前任已关联修订摘要与影响 |
| `POST` | `/api/learning-tracks/{track_id}/plan-revisions` | `user_id`、`client_action_id`、`expected_track_version`、完整候选 `plan` | 创建已提议修订，不改变活跃指针；201 或幂等重放 200 |
| `POST` | `/api/learning-tracks/{track_id}/plan-revisions/{revision_id}/activate` | `user_id`、`client_action_id`、`expected_track_version` | 只激活当前活跃修订的已提议直接后继；200 |

计划必须有规范 SHA-256、稳定小写 `module_key` / `knowledge_key`、唯一
顺序和无环前置条件 DAG。提案/激活使用学习路线行锁 + 预期
版本；冲突返回 `409 LEARNING_PLAN_VERSION_CONFLICT` 或
`LEARNING_PLAN_ACTIVATION_INVALID`。计划结构的输入错误返回统一校验信封；
学习路线根的语言/目标/目标不一致返回 `LEARNING_PLAN_INVALID`。

### 2026-09-13：路线节点与内容目录的显式映射

节点可携带 `catalog_knowledge_key: string | null`：`knowledge_key` 仍是路线、
前置条件、进度、Gate 绑定、Artifact 与 Attempt 的节点身份；新字段只用于
Lesson 检索及已发布 Learning Item 的内容查找。省略或 null 保留旧的直接匹配行为，
不加入旧版规范载荷，因此不改变旧计划哈希。显式映射必须是稳定键，
携带非空 `required_capabilities`，并命中同语言、能力兼容的最新发布状态为
已发布的目录内容；目录不可用时不得放行显式映射。计划生成时省略的能力默认取
规范语言 ID，不得凭空生成 `python.core` 一类能力。既有计划需正常提案/激活，
不得原地改写冻结计划/会话；只有映射或能力变化时影响也必须报告
`teaching_scope_changed`，但不抹除同节点的历史进度。此字段不保证每个节点已有独立题库覆盖。

Track 公开投影不返回 `plan_json`、掌握度证据正文、来源回执哈希、
提供方、镜像锁指纹或执行器健康状态详情。`execution_tier` 只能是
`teaching_local | container_verified | static_only | unavailable`：开发可声明
教学本地；公开必须同时拥有已审查不可变镜像锁和兼容健康状态
才可声明容器已验证，否则拒绝继续处理。

## 8. 学习控制接口

| 方法 | 路径 | 请求/查询 | 响应与限制 |
| --- | --- | --- | --- |
| `GET` | `/api/tutor/activity` | `user_id`、可选 `limit=1..100` | 安全活动条目 |
| `GET` | `/api/tutor/inbox` | `user_id`、`include_dismissed`、`limit` | `unread/read/dismissed` 收件箱条目 |
| `POST` | `/api/tutor/inbox/{id}/read` | `user_id`、`client_action_id` | 幂等读取；无效状态为 409 |
| `POST` | `/api/tutor/inbox/{id}/dismiss` | 同上 | 幂等隐藏；无效状态为 409 |
| `GET` | `/api/tutor/memory` | `user_id`、`include_inactive`、`limit` | 安全记忆条目 |
| `PATCH` | `/api/tutor/memory/{id}` | `user_id`、`client_action_id`、`statement<=180` | 追加替代记忆 |
| `DELETE` | `/api/tutor/memory/{id}` | `user_id`、`client_action_id` | 受保护的删除状态 |
| `GET` | `/api/tutor/plans/revisions` | `user_id`、`limit` | 活跃修订与不可变历史 |
| `POST` | `/api/tutor/plans/rollback` | `user_id`、`client_action_id` | 只回退直接前任；无前驱为 409 |
| `GET` | `/api/tutor/preferences` | `user_id` | `inferred_memory_enabled`、版本、`proactive_paused`、`proactive_enabled` |
| `PATCH` | `/api/tutor/preferences` | `user_id`、`client_action_id`，至少一个偏好 | 更新记忆 / 主动发起的用户控制 |

`PATCH /preferences` 的 `inferred_memory_enabled` 若随附
`expected_memory_setting_version`，会在版本冲突时返回
`409 MEMORY_SETTING_VERSION_CONFLICT`。`proactive_paused=false` 会恢复用户
`enabled=true`，但不放宽服务器已验证、全局暂停、预算、冷却期、
并发或熔断门禁。

<a id="受控-action-runtime-的公开边界2026-08-12"></a>
### 受控操作运行时的公开边界（2026-08-12）

Action 运行时是 Harness 内部编排/回执层，不新增学习者面向任意工具
端点。客户端不能提交 URL、路径、命令、镜像、环境变量、动态 MCP 服务端、重试次数或
资源升级。公开对话/历史/SSE 仍只消费既有面向学习者的安全消息/过程
投影；动作回执仅通过服务端构建的权威上下文元数据影响后续提供方回合。

公开或本地导出最多包含动作 id/版本、终态状态、安全摘要、权威来源种类/句柄、
验证状态与有界恢复提示。原始参数/结果、提供方响应正文、私有测试/量规、
学习者代码、命令/路径、内部异常和密钥不属于 HTTP/SSE/导出契约。

<a id="9-background--executor-非-api-边界"></a>
## 9. 后台工作与执行器的非 API 边界

- Celery 中只有 `tutor.proactive.scan_due_signals`、
  `tutor.proactive.drain_candidates` 和 `tutor.curation.drain` 目标任务；它们
  不是公共 HTTP 端点，也不接受用户任意运行/副作用参数。
- 默认主动建议仅从安全交互式终态元数据生成候选，结果只能进入
  活动/收件箱。它不会发出 SSE 聊天、桌面通知、`runner.execute`、学习者代码
  执行、子进程或直接记忆副作用。
- Container 执行器没有 HTTP 端点。`TUTOR_EXECUTOR_ENABLED=false` 且
  已审查不可变镜像锁缺失时保持安全不可用；见
  [Executor Operations](../setup/container-sandbox-executor.md)。

## 10. 已移除的接口

当前 `main.py` 不注册旧 `/api/dashboard`、`/api/plans`、
`/api/learning-sessions`、`/api/reviews`、`/api/notes`、Graph 事件流或
SDK 专项处理器路由。调用方必须迁移到本文件中的受控切换/Tutor 接口；不得
通过兼容适配器重建旧业务状态。

## 11. 契约验证

最小自动验证覆盖：受控切换门禁/确认、LearningTrack 契约/数据仓储/API、
PostgreSQL 限定作用域的约束、Tutor 作用域快照、Tutor 公开路由、SSE 游标与
终态排序、运行循环/持久化、活动/收件箱/记忆/计划、默认
主动发起的交付、工作进程导入、数据库结构初始化和桌面端类型化构建。完整
可复现命令与结果记录在
[发布就绪记录](../qa/tutor-harness-release-readiness.md)。

<a id="2026-08-10learning-home-与-planning-session-api"></a>
## 2026-08-10：学习首页与规划会话 API

- `GET /api/learning-tracks/catalog?user_id={uuid}`：返回语言 `selection_tier`、`selectable`、课程世代、服务端解析的 `execution_tier`/披露与来源可信策略。
- `POST /api/learning-plan-sessions`：创建或恢复同一用户唯一未完成会话，并创建专用 Tutor 对话、绑定 `plan_drafting` 作用域。
- `GET /api/learning-plan-sessions/current` 与 `GET /api/learning-plan-sessions/{id}`：返回按用户隔离的会话和当前类型化草案安全投影。
- `POST /api/learning-plan-sessions/{id}/cancel`：按预期会话版本取消。
- `POST /api/learning-plan-sessions/{id}/confirm`：校验会话版本、当前草案 id/版本/哈希后，在同一事务创建学习路线/修订/路由/进度并改绑对话。

会话公开投影包含面向学习者的安全 `planning_context={schema_version,facts[],questions[],fact_revision}`。
`facts[]` 只暴露稳定字段、规范化值、状态、修订、来源种类与来源
消息/运行/修订身份；`questions[]` 只暴露 `question_key`、`field_key` 和状态。
内部值/事件哈希、问题门禁原因、提示词与提供方响应正文不进入该投影。
草案保存其生成时的事实指纹/修订；确认时如果当前事实已变化，即使
调用方使用最新会话版本，也返回 `409 LEARNING_PLAN_DRAFT_STALE`。

稳定错误包括 `LEARNING_PLAN_SESSION_NOT_FOUND`、`LEARNING_PLAN_SESSION_CONFLICT`、`LEARNING_PLAN_SESSION_ALREADY_CONFIRMED`、`LEARNING_PLAN_DRAFT_NOT_READY`、`LEARNING_PLAN_DRAFT_INVALID`、`LEARNING_PLAN_DRAFT_QUALITY_BLOCKED`、`LEARNING_PLAN_DRAFT_STALE` 和 `LEARNING_LANGUAGE_NOT_SELECTABLE`。

<a id="2026-08-18codex-plan-drafting-runtime-admission"></a>
## 2026-08-18：Codex 计划起草运行时准入

Tutor 公开输入 DTO 不新增运行时字段。服务端仅对没有既有运行时沿袭关系的全新 `plan_drafting` 对话执行精确就绪状态准入；通过后在运行插入时冻结 `runtime_kind=codex_sidecar_v1`。功能 off 时新计划起草仍走 `harness_v1`；功能 on 但工作进程就绪状态缺失、过期、不健康或版本/模型/提供方/协议不匹配时，输入返回 `503 TUTOR_RUNTIME_UNAVAILABLE`，且首回合不留下空对话。通用、学习路线、主动发起的与既有 Harness 对话不依赖 Codex 健康状态。

队列/转向/Interrupt/重试的公共路径和响应结构不变：队列接受时保存服务端冻结运行时；活跃 Codex 回合的新修订映射为 `turn/steer`，取消/取代/租约丢失映射为 `turn/interrupt`；重试创建新运行但复制重试根运行时，禁止跨运行时降级。Codex 只可通过类型化工具追加计划草案；`POST /api/learning-plan-sessions/{id}/confirm` 及 LearningTrack 创建仍由现有 Aearn 事务执行。

## 2026-08-11：LessonDocument API

所有 Lesson 路由都要求已验证用户，并按 `user_id + track_id + knowledge_key`
校验活跃计划节点；跨用户对象与不存在对象统一返回 `404 LESSON_DOCUMENT_NOT_FOUND`。

| 方法 | 路径 | 契约 |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}?user_id=...` | 返回 `missing / preparing / ready / failed`；就绪仅包含面向学习者的安全文档、活跃分配、来源快照和可选更新提案 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/prepare` | 使用预期学习路线/进度版本和幂等键创建/重放持久化编写运行；新运行返回 `202`，提交后的分发不持有长事务 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/refresh` | 生成候选新版本；started 分配只得到提案，不静默替换 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/start` | CAS 冻结分配，并只推进 `available -> in_progress` |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/migrations/{assignment_id}/activate` | 只激活活跃分配的直接已提议后继 |

稳定错误包括 `LESSON_DOCUMENT_NOT_FOUND`、`LESSON_DOCUMENT_NOT_READY`、
`LESSON_DOCUMENT_VERSION_CONFLICT`、`LESSON_ASSIGNMENT_CONFLICT`、
`LESSON_SOURCE_EVIDENCE_INSUFFICIENT`、`LESSON_DOCUMENT_GENERATION_UNAVAILABLE`、
`LESSON_DOCUMENT_INVALID` 和 `LESSON_DOCUMENT_QUALITY_BLOCKED`。公共投影不包含提示词、提供方响应正文、推理、内部质量报告、完整抓取原文、隐藏测试、参考答案、命令、路径或凭据。

<a id="2026-09-08有界生成修复与-replay-shape"></a>
### 2026-09-08：有界生成修复与重放结构

- 一个编写运行内标准/个性化共享最多一次额外生成预算；只对服务端允许清单的结构、候选或可重写质量错误发送内部 `lesson_author_feedback_v1`。同提供方/模型/协议修复，传输重试保持原有边界。
- 无来源、来源 integrity/过期、租约丢失、配置/传输失败和未知错误不进入该修复。标准与个性化全部校验通过后才原子发布；预算耗尽继续返回原稳定失败码。
- 准备的新建、既有分配和幂等重放统一返回 `status, track_id, knowledge_key, authoring_run, idempotent_replayed`；就绪重放使用 `authoring_run=null`。内部 `should_dispatch` 由路由消费，不进入公共响应。
- Lesson GET 仅 `preparing | failed` 携带 `authoring_run`；已取消运行投影为 `missing` 时省略该字段。内部反馈、诊断 JSON、问题和哈希不进入学习者 DTO。

## 2026-08-11：练习 Gate 与模块诊断 API

所有 Gate 和模块诊断路由都位于 `/api/learning-tracks`、要求已验证用户，并按精确 `user_id + track_id + active plan revision + knowledge/module scope` 校验。跨用户、跨学习路线、已锁定 Lesson、失效分配/绑定和不存在对象不泄漏存在性。写操作使用 `client_action_id`/`Idempotency-Key`、请求哈希与预期版本；同键同请求重放原响应，同键不同请求返回冲突。

| 方法 | 路径 | 契约 |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates?user_id=...` | 返回活跃/冻结分配的面向学习者的安全 Gate、练习、tier、`allowed_actions` 与最新安全结果 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/prepare` | 使用预期学习路线/进度版本创建或重放精确不可变绑定/状态 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/hints` | 使用预期 Gate 版本追加有界安全提示回执；不返回私有量规/参考答案 |
| `POST` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/attempts` | `attempt_type=run | submit`；保存私有提交内容，待处理执行返回 `202`，同步 static/本地结果可直接终态 |
| `GET` | `/api/learning-tracks/{track_id}/lessons/{knowledge_key}/attempts/{attempt_id}?user_id=...` | 读取同一 Attempt 的待处理/终态面向学习者的安全投影，并可幂等触发终态投影 |
| `POST` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics` | 只在服务端模块入口规则允许时冻结诊断版本/条目；直接 API 绕过同样被拒绝 |
| `GET` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics/{session_id}?user_id=...` | 返回会话、冻结能力/条目、安全结果、薄弱项、冷却期和已提议影响 |
| `POST` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics/{session_id}/items/{item_id}/attempts` | 创建 `diagnostic_submit` Attempt；要求 仅允许独立完成，不提供提示/补救 |
| `POST` | `/api/learning-tracks/{track_id}/modules/{module_key}/diagnostics/{session_id}/confirm-skip` | 只确认当前活跃前任的 `passed_pending_confirmation` 会话，并原子激活已提议修订 |

公共 Gate/Attempt/诊断投影不包含完整提交内容、私有测试、参考答案、私有量规、容器/镜像、命令/路径、原始执行器/提供方响应或内部异常。稳定错误包括 `LESSON_GATE_NOT_FOUND`、`LESSON_GATE_NOT_READY`、`LESSON_GATE_VERSION_CONFLICT`、`EXERCISE_ATTEMPT_CONFLICT`、`EXECUTION_UNAVAILABLE`、`MODULE_DIAGNOSTIC_NOT_ALLOWED`、`MODULE_DIAGNOSTIC_COOLDOWN` 和 `MODULE_DIAGNOSTIC_VERSION_CONFLICT`；校验错误使用面向学习者的安全 `422`。


### 2026-09-08：Gate 选题与持久化补充

- 准备只准备路径指定的 Gate，不同时绑定其他槽位。`knowledge_check_v1` 必须匹配当前语言、知识点和服务端能力范围内的已发布静态知识检查及其不可变 Practice 实体化，不能退回代码执行测试夹具；不兼容的历史绑定保留只读，不改写冻结版本。
- `execution_requirement` 来自精确练习。静态知识检查没有容器执行证据，结果仍为 `not_run`；已经通过的静态 Gate 不再暴露提交动作。单选题发送真实 `option_id`，客户端不自行判分，不把静态通过展示为代码运行成功。
- Gate 写操作成功响应前必须提交请求事务；服务 savepoint 成功不等于 HTTP 请求持久化。验收需用另一个数据库连接和刷新后的 GET 检查回执、Attempt 与 Gate 状态，不仅检查当前页面的成功提示。

## 2026-08-12：模型代码审核练习 API

`model_code_review` 是现有 Lesson Gate/Attempt 契约的正式练习类型，不是旧
`review_ai_patch` 的别名。编写提供方只返回
`model_review_author_candidate_v2={schema_version,title,learner_instruction,candidate_code}`；
`template_id`、requirements、可见/隐藏测试、预期 outcomes、私有量规、findings、
覆盖证明与分数策略全由服务端受控模板/DSL 构造，提供方多出的任何字段都使
候选拒绝继续处理。Gate 准备/读取可投影 `preparing | ready | failed` 的
`review_authoring_run`；客户端不得生成降级题。模型审核提交必须且只能发送
`review_submission={schema_version,verdict,findings[],supplemental_note?}`，不能同时发送普通
`submission`，也不提供学习者 Run。发现项包含稳定客户端 id、行范围、种类/类别、
严重程度、触发器、principle、影响、校验 method 与 suggested fix；服务端再次校验
判定/发现项结构、行范围和重复 ID。

`POST /api/learning-tracks/{track_id}/lessons/{knowledge_key}/gates/{gate_key}/evidence`
只返回已验证发布前 checks 的面向学习者的安全投影，并写入辅助回执；
它不执行代码。Attempt/结果只返回 `submission_hash`、`assistance_kind`、确定性分数维度、
按客户端发现项 id 的 `supported | partial | unsupported | duplicate`、omission band 与下一步
 动作，不返回预期发现项、隐藏测试、匹配器令牌、私有量规或候选正文。
发布前校验必须匹配服务端模板身份/哈希、精确运行时、测试顺序/数量、
可见/隐藏 visibility 与预期通过/失败结局；执行器不把私有模板 id、证明 id
或预期通过元数据传给沙箱。稳定错误包括 `MODEL_REVIEW_GENERATION_UNAVAILABLE`、`MODEL_REVIEW_CANDIDATE_INVALID`、
`MODEL_REVIEW_VALIDATION_UNAVAILABLE`、`MODEL_REVIEW_VALIDATION_FAILED`、
`MODEL_REVIEW_VALIDATION_STALE`、`MODEL_REVIEW_PUBLICATION_CONFLICT`、
`MODEL_REVIEW_SUBMISSION_INVALID` 与 `MODEL_REVIEW_EVIDENCE_UNAVAILABLE`。

<a id="2026-08-12track-scoped-reviewsession-api"></a>
## 2026-08-12：路线作用域的 ReviewSession API

旧顶层 `/api/reviews` 仍属于已移除接口；正式复习只通过仅限已验证状态的的
`/api/learning-tracks/{track_id}/reviews...` 路由访问，并按精确
`user_id + track_id + active plan revision + knowledge_key` 校验。所有写操作使用
`client_action_id` 或 `Idempotency-Key`、请求哈希与预期版本；同键同请求重放，
同键不同请求返回 `409 IDEMPOTENCY_CONFLICT`。

| 方法 | 路径 | 契约 |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/reviews?user_id=...` | 返回 actionable `due_count`、today 队列、风险与可选 `critical_prerequisite_gate`；普通到期不构成课程 Gate，关键前置 `critical` 项立即投影 |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions` | 输入 `knowledge_key`、预期学习路线/调度版本与 `max_items=1..3`；冻结计划/调度/上下文/候选；候选不足返回可恢复 `blocked` 会话 |
| `GET` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}?user_id=...` | 恢复同一有限会话、冻结条目、Attempt 与终结的面向学习者的安全投影 |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/warmup` | `answered + confidence` 或 `skipped`；只写热身回执和会话 stage，不写长期状态 |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/items/{item_id}/hints` | 追加有界安全提示回执，并把后续 Attempt 标为 hinted；不返回答案/私有量规 |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/items/{item_id}/attempts` | 普通题发送 `submission`，模型审核题发送 `review_submission`，二者严格多选一；静态结果同步 `200`，既有执行器待处理为 `202` |
| `GET` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/attempts/{attempt_id}?user_id=...` | 读取精确待处理/终态 `review_submit` Attempt |
| `POST` | `/api/learning-tracks/{track_id}/reviews/sessions/{session_id}/finalize` | 仅在全部条目终态后执行唯一聚合；原子写掌握度证据、调度事件/投影和终结 |

稳定错误包括 `REVIEW_NOT_FOUND`、`REVIEW_NOT_READY`、
`REVIEW_VERSION_CONFLICT`、`REVIEW_CANDIDATE_UNAVAILABLE`、
`REVIEW_CANDIDATE_INVALID`、`MODEL_REVIEW_SUBMISSION_INVALID`、
`EXECUTION_UNAVAILABLE` 和 `IDEMPOTENCY_CONFLICT`。候选不足是会话内的
`failure_code=REVIEW_CANDIDATE_UNAVAILABLE`、`recoverable=true`，客户端可使用原幂等请求重试。
公共投影不包含完整提交内容、私有量规/测试/参考答案、原始提供方/执行器
响应、命令/路径/镜像/凭据、内部上下文哈希或调度事件载荷。


## 2026-08-12：Tutor 结构化上下文引用

三个 Tutor 输入入口支持可选 `context_references`，最多 6 项，且仅允许
`learning_scope.scope_kind=learning_track`。引用是严格 discriminated 联合类型：

- `lesson_selection`：`learning_track_id`、`knowledge_key`、`document_id`、
  `document_content_hash`、`block_id`、`start_offset`、`end_offset`、`excerpt`；摘录最多 800 字符。
- `exercise_feedback`：`learning_track_id`、`knowledge_key`、终态 Lesson `attempt_id`。
- `execution_result`：同上，但 Attempt 必须存在真实 `execution_job_id`。
- `review_feedback`：`learning_track_id`、`knowledge_key`、`review_session_id`、终态 Review `attempt_id`。

服务端先固定对话/运行的不可变 LearningTrack 任务作用域，再逐项读取来源 of truth 并构造
`tutor_context_reference_v1` 安全快照。Lesson 必须匹配同用户同学习路线/知识的活跃冻结
分配、文档/哈希/块/范围；Exercise/Execution/Review 必须匹配同作用域的真实终态 Attempt。
客户端提交的摘录、反馈或结果不直接进入快照。引用类型必须与 `lesson_teaching | exercise_feedback |
model_code_review | review_coaching | remediation` 任务作用域一致；引用不能用于通用/计划起草输入。

输入接受事务把学习者消息、运行/输入修订、运行作用域与全部引用原子绑定；任一引用失败都会回滚整条输入。
acceptance 响应与学习者历史消息返回有序安全引用，模型上下文加载器通过独立必需来源
`tutor-context-references:{message_id}` 注入，不修改学习者 `content`。快照只含有界安全摘录、结局、分数、
安全反馈、能力 scores、辅助、公开时间和必要产物身份；不得返回完整提交内容、隐藏测试、
私有量规/参考答案、原始 stdout/stderr、命令、容器、路径、提供方响应正文或密钥。

稳定错误包括：非法联合类型/数量/重复为 `422 CONTEXT_REFERENCE_INVALID`；作用域/任务/学习路线/知识冲突为
`409 CONTEXT_REFERENCE_SCOPE_CONFLICT`；活跃文档/哈希/范围变化为 `409 CONTEXT_REFERENCE_STALE`；终态
Attempt 不存在为 `404 CONTEXT_REFERENCE_NOT_FOUND`；缺少真实执行结果为
`409 CONTEXT_REFERENCE_NOT_READY`。同一个 Tutor 幂等键的请求哈希包含引用数组；相同键不同引用不能
被误判为同请求重放。

## 2026-08-12：最终集成审计

最终集成没有新增第二套学习 API。LearningTrack、Lesson、Gate、ReviewSession 与 Tutor 输入继续使用本文件已列出的仅限已验证状态的路由；旧 `/api/dashboard`、`/api/plans`、`/api/learning-sessions`、顶层 `/api/reviews`、Graph/SDK 专项处理器路由仍未注册。

`tests/integration/test_learning_agent_integration_matrix.py` 对 Python、JavaScript、TypeScript、SQL 逐一验证学习路线/计划、来源支持 Lesson、活跃分配、Gate、终态反馈、私有提交内容持久化、掌握度/进度、到期复习、ReviewSession 终结与面向学习者的安全投影。相同测试夹具同时断言：空 `image-locks.json` 下公开执行必需 Gate 没有 `allowed_actions`，开发测试夹具只能返回 `teaching_local`。

公开响应的敏感字段审计按字段名递归执行，覆盖 Gate/Attempt/Review 投影；既有专项测试继续覆盖 SSE/历史/公开过程/诊断轨迹/检查点/活动/收件箱/导出。任何完整提交内容、私有测试/量规/参考答案、原始提供方/执行器正文、命令/路径/容器/密钥都只能留在私有存储或被完全省略。


<a id="2026-08-14tutor-threadturn-v2-全局-cutover-api"></a>
## 2026-08-14：Tutor 线程/轮次 v2 全局切换 API

- `GET /api/tutor/capabilities/thread-turn-v2?user_id=...` 返回 `tutor_thread_turn_v2_capability_v1`：`cutover_version=tutor_thread_turn_v2_global_v1`、`desktop_contract_version=tutor_thread_turn_v2_desktop_v1`、env/状态/世代/摘要/块/effective 门禁、安全数量与时间。
- 所有 Tutor 写操作仅在 `TUTOR_THREAD_TURN_V2_ENABLED=true` 且 DB 状态=`enabled` 时开放；否则返回 `503 TUTOR_THREAD_TURN_V2_UNAVAILABLE|PREPARING|BLOCKED`。历史/快照/运行详情/SSE 继续只读。
- `POST /api/tutor/runs/{run_id}/inputs` 对任意运行固定返回无副作用 `410 TUTOR_LEGACY_CONTINUATION_DISABLED`，`next_action=start_new_turn`。
- 旧版等待迁移的运行 SSE 公开 `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN`；其他受控切换取消仍投影普通已中断/RUN_NOT_ACTIVE，不新增专用卡片。

## 2026-08-15：Tutor 公开思考文本流契约

**历史版本说明：** 本节 v4 提供方、v2 快照/事件记录的是当时契约。当前生成 `tutor_provider_items_v5`、解析兼容 `tutor_provider_items_v4`；快照按内容选择 v3/v4/v5，Artifact 事件使用 v3。下文原始推理禁出规则针对 Harness 公开思考路径；Codex 的仅所有者可见原始运行时条目另见后续受控路径。

- 提供方决策结构契约为 `tutor_provider_items_v4`，新 `agent_message` 使用
  `public_thinking_text`（0..1280 字符纯文本）与最终 `text`；公共接口不暴露原始推理。
- 快照为 `tutor_conversation_snapshot_v2`，可返回
  `active_thinking={turn_id,input_revision,generation,state,text,complete,last_event_sequence}`；
  它必须与 `active_turn` 身份/修订完全一致，否则省略或拒绝投影。
- 对话事件投影为 `tutor_conversation_event_v2`，不透明游标版本为 2。
  `turn_output` 是唯一允许桌面端局部应用的事件；重复忽略、序号/世代/分块缺口、
  额外字段、错误回合/修订或旧游标均回到新建快照。
- `append` 只表示通过累计文本安全检查的候选前缀，不构成展示权威来源。`complete` 只能在完整
  提供方对象已通过结构/领域校验、公开文本安全检查以及流/最终结果 精确匹配后发出；
  被 修复/拒绝 的尝试必须从暂定内容 `append` 直接进入 `discard`，不得先发 `complete`。
- 成功 `message` 与 `elicitation|approval` 请求条目都可携带精确
  `public_thinking_text`。正式回答/问题文本只来自已持久化快照；部分提供方 JSON 不构成回答权威来源。
- 旧版 `/history` 继续返回旧形状：新文本投影为单元素 `public_thinking_steps[]`，旧 步骤 原样读取；
  快照 v2 只返回统一后的 `public_thinking_text`，不产生编号、说明或补写历史。
- API、SSE 与快照禁止包含 `reasoning`、`reasoning_content`、提示词、提供方响应正文/原始事件、
  诊断轨迹、诊断、凭据、密钥或内部安全拒绝原因。

<a id="2026-08-20tutor-snapshot-v3-与-codex-raw-runtime-item-stream"></a>
## 2026-08-20：Tutor 快照 v3 与 Codex 原始运行时条目流

`GET /api/tutor/conversations/{conversation_id}/snapshot` 当前返回 `tutor_conversation_snapshot_v3`。v3 保留 v2 的对话/控制、`active_turn`、`active_thinking`、类型化请求、队列、时间线、不透明游标，并新增可选 `active_runtime_output`：

- `output_version="tutor_runtime_output_v1"`；
- `input_revision` 与活跃回合完全一致，`generation` 为当前运行时连接世代；
- `reasoning_items[]` 与可选 `final_answer_item` 只包含 Aearn 条目 ID、文本、`streaming|completed` 和最后公开序号；
- 已完成 Tutor 消息的时间线条目可携带同形 `runtime_output`，用于刷新和历史恢复；无非空推理时不返回可见 Think 内容。

桌面端必须继续兼容读取 v2；v2 没有 `active_runtime_output`。v3 公开 serializer 不返回外部线程/回合/条目 ID、提供方/模型元数据、提示词、工具参数/结果、推理摘要、过程说明、诊断轨迹、诊断或凭据。

对话 SSE 的 `turn_output` 现在接受两种闭合版本：

1. `tutor_public_thinking_stream_v1`：保留 Harness 兼容；
2. `tutor_runtime_item_stream_v1`：包含 `input_revision`、`generation`、`item_id`、`channel=reasoning|final_answer`、`operation=reset|append|complete|discard` 与单调 `chunk_sequence`。`append` 携带增量文本，`complete` 携带权威 full 文本，`reset|discard` 不携带文本。

过程说明、推理摘要和未知阶段/通道不得进入公开文本流。若已完成条目将暂定内容 `final_answer` 校正为 `commentary`，或回合终态时仍有流式条目，服务端发送不带文本的 `discard` 并从快照/历史排除该条目。重复或旧序号可忽略；对话全局缺口、身份/修订/世代 mismatch、闭合结构失败或超限文本必须停止局部归约器并新建快照恢复。

<a id="2026-09-03-semantic-planning-language-resolution-and-dynamic-presentation"></a>
## 2026-09-03: 规划语言的语义解析与动态呈现

对于 `plan_drafting`，Aearn 根据已确认的规划事实及 PostgreSQL 中生效的课程/能力权威数据，解析当前这一次学习者输入。只有明确指定一种已启用语言，才会追加已确认的 `language_id` 事实，使用 `source_kind=deterministic_input` 和 `policy_version=planning-language-intent-v2`。多语言输入、仅描述方向、不支持的输入、事实冲突以及所有模型语义结果，都不能直接成为已确认事实。

缺少 `language_id` 时，模型上下文最多接收 24 个服务端构造的候选，包含规范语言值、课程标题、级别、能力状态和执行类别。提供方只可输出严格的 `planning-intent-hint-v2`：1..3 个互不重复的当前规范语言值、`confidence=high|medium` 及一个闭合的语义原因码。不得提供标签、选项、课程 UUID、URL、命令、路径、运行时配置、推荐项或自由文本理由。Harness 在 `TutorDecision` 中携带提示；Codex 必须先读取候选，再通过第二次经过校验的 `aearn_planning_context_read` 调用提交相同载荷。未知、重复、未启用、过期、多余或超限的候选一律拒绝。

有效语义结果仅创建供学习者确认的 `intent_shortlist`，不会写入事实或选择默认项。证据不足时，复用一个现有 `clarification` 请求，询问实现语言、框架变体或运行环境。启用意图解析后，不存在 `no_intent_signal -> full_catalog` 路径。`TUTOR_PLANNING_INTENT_ENABLED=false` 是显式的旧行为回退开关，允许构造完整的已启用目录，并标记 `feature_off_rollback`。

持久化的语言 `planning_input` 保存精确的 `options`、`recommended=null`、`selection_scope`、`selection_reason_code` 和 `intent_policy_version`。公开选项值仍为规范课程语言值，不公开模型置信度、内部课程 UUID、候选证据或理由。即使目录后来变化，刷新、SSE 重连、历史读取和响应校验也都使用已保存的呈现数据。历史 v1/完整目录请求原样重放。

<a id="2026-08-21runtime-projection-sequence-兼容说明"></a>
## 2026-08-21：运行时投影序列兼容说明

`tutor_runtime_item_stream_v1.chunk_sequence` 是 Aearn 投影序号，不是提供方/来源通知序号。服务端可以把多个连续同条目/种类/通道/索引/阶段增量合并成一个追加；客户端只需按现有闭合联合类型、身份和连续投影序号处理。来源范围/数量/哈希仅存在于私有 PostgreSQL 回执，不加入快照、历史、SSE 或桌面端 DTO。缺口仍要求停止局部归约器并读取新建快照；不得把缺口解释为模型不可用。

<a id="2026-08-23teachingsession-authorityaction-shelf-与-control-api"></a>
## 2026-08-23：TeachingSession 权威、操作区与控制 API

所有 TeachingSession 路由均位于仅限已验证状态的 `/api/learning-tracks` 边界，并按精确 `user_id + track_id + conversation_id + knowledge_key` 校验。写操作复用 `client_action_id` / `Idempotency-Key`、请求哈希、PostgreSQL 咨询锁与预期会话/学习路线/进度/分配版本；同键同请求返回原响应，同键不同请求返回 `409 IDEMPOTENCY_CONFLICT`。

| 方法 | 路径 | 契约 |
| --- | --- | --- |
| `GET` | `/api/learning-tracks/{track_id}/teaching-sessions?user_id=...` | 返回该学习路线的有界会话摘要，不返回检查点原始 JSON、提示词、推理或提供方响应正文 |
| `GET` | `/api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}?user_id=...` | 返回优先级为 `active/paused -> latest completed -> blocked` 的当前投影、有界检查点与服务端管理的 `TeachingActionShelfV1` |
| `POST` | `/api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}/open` | 输入对话、预期学习路线/进度/分配版本与 `guided | free_reading`；创建/恢复精确当前会话；权威来源变化时阻断旧会话并创建后继；Guided 新建时准入一个 `open_session` 运行；201 或幂等 200 |
| `POST` | `/api/learning-tracks/{track_id}/teaching-sessions/{session_id}/actions` | 输入闭合 `control_key`、预期会话/学习路线/进度/分配版本、可选目标模式/知识/原因；服务端忽略客户端 `admit_run` 偏好并按控制/模式策略决定是否准入运行 |

闭合控制包括 `continue`、`return_focus`、`change_example`、`pause`、`resume`、`escalate_guided`、`switch_mode` 与 `enter_next_knowledge`。Free Reading 中 `continue/return_focus/change_example` 返回 `400 TEACHING_ACTION_INVALID`，只有显式 `escalate_guided` 才切 Guided 并准入一个运行；Free Reading 恢复只恢复会话，不调用提供方。完成操作区只在已完成权威来源上投影显式下一步/navigation；`enter_next_knowledge` 必须携带候选键与最新预期版本，服务端重新验证活跃计划/可用性后才推进学习路线指针，并在同一长期对话开放/恢复下一会话。

`TeachingActionShelfV1` 最多一个主要、三个可见次要；活跃运行时与阻塞类型化请求时普通操作区为空。普通操作区的标签、强调样式、目标、预期版本均由服务端生成，提供方/客户端不能定义。`continue` 只在检查点推荐继续时出现；`learner_response_mode=composer` 投影 `respond_in_composer`，不存在任何真实描述符时返回空操作区，桌面端不生成 占位项。开放/动作返回 `pending_run.dispatch_job_id` 时，HTTP 层 只做尽力而为的工作进程唤醒信号；持久化分发任务才是执行权威来源，幂等重放或重复唤醒信号不产生第二个运行。

`TutorTurnStimulus` 是严格多选一：普通学习者输入绑定精确学习者消息/输入修订；显式教学控制或领域事件可创建没有学习者消息的新建交互式 TurnRun。公共响应/快照只增量返回安全教学会话/运行作用域/Action Shelf 元数据。稳定错误包括 `TEACHING_SESSION_NOT_FOUND`、`TEACHING_AUTHORITY_CONFLICT`、`TEACHING_ACTION_INVALID`、`TEACHING_STIMULUS_INVALID` 与既有 `IDEMPOTENCY_CONFLICT`；跨用户、跨学习路线/对话、过期检查点/会话/进度/分配/文档/触发输入一律拒绝继续处理。

### 2026-09-08：教学准入与失败投影补充

绑定知识点的 `learning_track/lesson_teaching` 输入在新建运行/消息/任务前验证当前 TeachingSession、检查点与 Lesson 权威来源；未就绪返回 `409 TEACHING_NOT_READY`，`recoverable=true` 表示应先完成准备，不表示自动重试模型。已接受的同一幂等输入先重放原有回执/作用域，不受之后会话关闭影响。无知识绑定教学目标的普通学习路线问答不自动推断或取得教学权限。

快照/历史为未产生既有最终失败分发/运行时错误的失败 Harness 回合返回稳定的 `kind=error`；不重写历史运行，不重复报错，不将正常已取消/已取代状态伪装成失败。`recoverable` 与队列重试的统一终态判定一致：未知能力/副作用拒绝不可自动重试。错误代码/消息均为服务端安全投影，不包含内部拒绝标识、原始模型输出或异常文本。

新课程作者只准入来源/URL/正文哈希匹配的 `http_fetch` 片段；测试夹具和未知来源链不因 official 标签而放行。无有效片段仍使用 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`，且不得调用提供方。此检查不修改历史冻结课程读取协议。

<a id="2026-08-23内部-teaching-domain-event-与-summary-context"></a>
## 2026-08-23：内部教学领域事件与摘要上下文

<a id="2026-09-15knowledge-check-的精确任务上下文"></a>
### 2026-09-15：知识检查的精确任务上下文

出题阶段为已授权、当前已发布的 KC 候选提供精确公开题干和选项；
`knowledge_check_evaluation` 还必须提供同 Artifact/条目/会话/学习路线/节点的不可变
提交与评分回执。它们进入内部 `teaching-artifact-evidence:` REQUIRED_FACTS，
不进入公开 Artifact 响应/导出，不包含私有答案、量规、未展示 Hint 或私有解释。
题干/提交文本是 untrusted 任务数据，不是执行指令或课程完成授权。模型介绍必须与
所选候选的实际题目一致；反馈必须依据实际问题、作答、结局/辅助，
不能依据 Lesson 标题或旧总结猜测错误。长 JSON 只可完整分片，所有分片均为必需；
保留每来源 1,200 字符、最多八个必需 sources 与既有总令牌预算。
现有脱敏若会改变证据内容，则 `TUTOR_REQUIRED_FACTS_PROTECTED` 拒绝发送；
缺失评价证据为 `TUTOR_KNOWLEDGE_CHECK_GROUNDING_INVALID`，不得静默退回泛化摘要。

本轮不新增公开 HTTP 路由。Gate、Review 与 Lesson 迁移的现有写操作在所属者事务内完成业务权威来源后，调用统一适配器尝试准入一个面向学习者的安全 `domain_event` 回合。没有开放教学会话、来源版本过期、重复来源或竞争前台运行时，所属者写操作仍按自身契约完成；适配器返回内部 ignored/已重放回执，不把完整提交、量规、提供方响应正文或内部原因加入公开响应。

`domain_event` 仍是精确一个触发输入，不创建学习者消息、不使用主动发起的来源。Gate 完成 合并为一个 `progress_changed` 回合并保留门禁安全句柄；非完成 Gate、Review 终结与分配迁移分别使用 `gate_terminal | review_terminal | assignment_changed`。Free Reading 对普通学习者输入仍是 仅响应学习者输入；类型化领域事件可以执行有界证据/完成动作，但不会隐式改变会话模式。

<a id="2026-08-27teaching-step-v2-与条件式-action-shelf"></a>
## 2026-08-27：教学步骤 v2 与条件式操作区

本增量不新增公开路由，也不允许客户端提交 `teaching_moves` 或 `learner_response_mode`。两者属于精确 `tutor.lesson-teaching@1.1.0` 的提供方决策与服务端回执权威来源；旧 `tutor.lesson-teaching@1.0.0` 保持不可变但不再用于新教学运行。

对话快照与 TeachingSession API 继续返回 `TeachingActionShelfV1`。当检查点需要学习者回答时，服务端投影 `respond_in_composer`；只有推荐动作确实是 `continue` 时才返回 Continue。若没有主要或次要描述符，`primary=null`、`secondary=[]` 是完整有效响应，桌面端必须完全省略操作区 DOM。权威来源暂停的恢复导航使用 `refresh_session`，客户端只能重新读取当前投影，不能本地恢复或准入运行。

<a id="2026-09-01teaching-artifact-candidatebranch-snapshot-与-continuation-contract"></a>
## 2026-09-01：教学 Artifact 候选、分支快照与续接契约

本增量不增加客户端可写的题目或调度字段。`tutor.lesson-teaching@1.2.0` 的提供方上下文增量接收服务端构造的 `artifact_candidates`，每项只含精确 `li:<sha256>` 句柄、闭合种类/purpose/difficulty 与允许的交互 intents；候选作用域固定当前 TeachingSession/检查点和学习路线/进度/分配版本。两个 Artifact flags 未同时开启、没有兼容已发布候选、上下文超出既有必需章节绑定或任何候选权威来源过期时，提供方前拒绝继续处理或返回空候选，不能截断成歧义允许清单。

决策 v3 的学习者交互是严格闭合联合类型：`none + none + null`、`composer + text_answer + null`、`artifact + one Artifact intent + exact advertised handle`。编辑/运行/复习/查询/演示/respond 意图没有精确候选时整条公开决策被拒绝，且不会写 Tutor 消息。合法 Artifact 决策的消息、检查点、回执、Artifact/事件、时间线条目与回合终态在同一事务完成；公开错误只返回稳定权威来源诊断，不包含条目私有内容、提交内容、量规/测试、提供方响应正文、命令/路径/运行时身份或密钥。

普通学习者输入在阻塞 Artifact 下由服务端绑定 深度为一的分支；客户端不提交分支 id，也不能把本地折叠状态当权威来源。存在分支历史时对话快照升级为 `tutor_conversation_snapshot_v5`，增量 `branches[]` 只返回 锚定 Artifact ID、TeachingSession/检查点 id、状态、处置结果、轮次/条目数量、显式消息/过程引用与时间；v3/v4 客户端 在无分支历史时继续得到原版本。主题切换 只能通过闭合控制确认，提示/直接答案分支完成需要精确服务端回执。

Artifact 动作、预期演示事件、计时器与后台 生产者 只持久化续接意图。调度器按学习者消息 > 显式 Artifact 动作 > 预期事件 > 计时器 > 后台选择一条 符合条件的 意图；活跃前台、待处理学习者输入、活跃分支、Free Reading 自动 意图或过期领取/权威来源都不会创建提供方回合。没有新增计时器触发的 HTTP 提供方路由，SSE 仍只投影已提交的对话事件。


<a id="2026-09-13superseded-branch-history"></a>
### 2026-09-13：已被取代的分支历史

正常 `active/resolved` 分支继续返回严格的 `tutor_conversation_branch_v1`；仅权威退役返回 `tutor_conversation_branch_v2`：保留 V1 全部字段，`state=superseded`、`collapsed=true`、`resolved_at=null`，新增必填非空 `superseded_at`。退役不要求处置结果，已有处置结果仅保留为历史；轮次与显式条目不变。Artifact 的对应摘要使用 `schema_version=tutor_artifact_branch_summary_v2` 加原摘要字段，`state=superseded,collapsed=true`；活跃/已解决摘要的未携带结构版本字段的 V1 摘要不变。

升级桌面端同时接受这两个封闭结构；V1 不可携带已取代，V2 不可冒充活跃/已解决。所有范围、数量、引用、摘要/group 一致性与额外字段拒绝规则保持。退役分支默认折叠，可只读展开历史，明确显示“教学会话已更新，此答疑分支已退役”，不能显示“已解决”或继续此分支的操作。旧严格客户端不兼容新增终态，需与 API 一起升级；不能靠未知状态降级伪造兼容。快照外层仍为 v5；未新增客户端关闭分支的写操作 API。

<a id="2026-09-01desktop-artifact-detailaction-与-snapshot-v4v5-consumer-contract"></a>
## 2026-09-01：桌面端 Artifact 详情/操作与快照 v4/v5 消费端契约

| 方法 | 路径 | 面向学习者的安全契约 |
| --- | --- | --- |
| `GET` | `/api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}?user_id=...` | 精确当前 `TutorPublicArtifactItem`; 不公开用户/会话/工件作用域不匹配的细节 |
| `POST` | `/api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/actions` | 正文 carries 用户/路线/会话作用域, `client_action_id`, `expected_artifact_version`, 与一个闭合操作载荷; 响应 returns 全新 Artifact 投影, 事件 ID/序号, 与重放 flag |
| `GET` | `/api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/attempts/{attempt_id}?user_id=...` | 作用域内的对学习者安全 Attempt 详情仅; 私有提交内容/评分规则/测试/运行时身份 remain 非公开 |

桌面端接受快照的增量版本，但不放宽类型边界：v2/v3 将缺少的 Artifact/分支字段规范化为 `null`/`[]`；v4 要求精确的 `active_artifact`；v5 还要求精确的分支组。Artifact 时间线身份为 `kind + id`；`active_artifact` 可以补足有界快照省略的条目，但不能与时间线副本冲突。分支引用必须保持连续序号、精确角色/类型/轮次身份、深度为一，并符合服务端数量/状态/处置/时间戳以及锚定对象/作用域。重复、多余、受保护、未知字段，或哈希/数量、终态、操作、引用、呈现类型、跨作用域不匹配，均拒绝整个响应。

桌面端操作入口只发送服务端明确公布的操作以及版本、范围和幂等字段，不自行推导分数、通过状态、掌握度、Attempt 结果、续接优先级或分支归属。操作响应必须推进 Artifact 版本、保持请求的作用域身份，并返回正事件序号；重放只能接受完全相同的安全响应。

<a id="2026-09-01execution-result-artifact-与-attempt-v2"></a>
## 2026-09-01：执行结果 Artifact 与 Attempt v2

`GET /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/attempts/{attempt_id}` 继续是限定作用域的读取端点，但允许在同一短事务中幂等观察既有执行器任务：Attempt 未终态时只返回待处理/运行中；所属者已保存终态结果时，服务端更新原 Artifact、追加唯一 `test_result_v1` Artifact、记录并消费唯一结果评估续接。重复 GET 返回同一 Attempt/结果/回合沿袭关系，不重新执行代码。跨用户/对话/学习路线/TeachingSession/Artifact/Attempt/所属者身份仍按 not-found/conflict 拒绝继续处理。

新响应默认是严格 `tutor_learning_artifact_attempt_v2`。终态 `result` 只含 `outcome,score,execution_result,capability_scores,policy_version,result_hash,terminal_at`；`execution_result` 为 可空的 严格 `safe-execution-result-v2`，含有界 stdout/stderr、类型化可见/不可见反馈、数值位置、数量/时长/诊断代码和闭合 `none | table_result_v1` 呈现。历史 v1 Attempt 仍可读取，但桌面端不解析任意 `safe_feedback` 为运行时 UI。完整提交内容、隐藏测试身份/输入/预期/私有载荷、量规/参考答案、路径/调用栈/命令/容器/镜像/提供方/密钥不进入 v2。

Artifact `run` 动作只在终态投影完成后产生结果评估续接；待处理 Run 不再提前创建普通 Artifact 续接。终态投影会先保存结果 Artifact 权威来源，但在评价回合完成前不把该 Artifact 加入公开时间线。回合终态事务先发布 Tutor Markdown 消息，再发布绑定该回合的精确结果 Artifact 条目；任一步失败两项都不公开。若动作内同步得到终态结果，动作响应返回最新来源 Artifact 写入及与其 `version` 相同的事件序号，而不是返回旧动作事件身份。已通过直接完成来源 Artifact，不存在第二 Submit；非已通过来源保持活跃以便返回修改。

结果评估回合的提供方上下文只含 `reason_code=result_evaluation`、精确 `artifact:<result-artifact-id>` 句柄和最多 320 字符的 revalidated 摘要，不广告新 Artifact 候选。模型只生成评价正文；`MODEL_UNAVAILABLE` 时仍保留 Attempt/结果 Artifact，并由服务端写入固定面向学习者的安全 Markdown 评价。普通回合的模型不可用语义不变。


<a id="published-teaching-demonstration-completion-child06"></a>
## 已发布教学演示完成 (Child06)

`demonstration_v2` 只能从已发布 Learning Item 句柄物化。提供方不能编写或改动来源、步骤、预期事件或时长。`complete_demo` 接受精确的 `interactive_event` 证据（事件键、规范化载荷、有界预览一次性随机值/代次/连续序号），或 `visible_clock` 证据。已发布载荷和公开请求都拒绝隔离桥无法编码的 JSON 结构。每个 Artifact 只保存一份仅追加完成回执；完成不创建 Attempt、掌握度证据或路线进度。交互式完成采用预期事件续接优先级，静态完成采用静态计时器优先级；学习者输入始终优先。

<a id="2026-09-02knowledge-checkhint-与-evaluation-continuation"></a>
## 2026-09-02：知识检查、提示与评价续接

`knowledge_check_v1` 动作为闭合联合类型：`request_hint`、`request_direct_answer`、`respond` 与通用 `cancel`。`respond` 只接受 single/multi select、prediction、排序、代码范围或 short 文本的精确结构；所有写操作继续携带用户/学习路线/TeachingSession、`client_action_id` 与预期 Artifact 版本。回答后原 Artifact 终态/读取仅；重复精确请求返回同一事件/回执，同键不同请求体返回 `IDEMPOTENCY_CONFLICT`，过期版本不调用评分器。

H1-H3 必须按序解锁并各写一条辅助回执；回看和动作重放不重复。`request_direct_answer` 不属于 Hint 页，写直接答案辅助 + 响应回执，公开内容只使用服务端管理的解释，且不能成为 independent 掌握度。原题需要补救、补救失败或直接答案均由服务端从已发布、当前能力兼容、未使用且语义不同的条目中选择精确后继；普通教学不广告 `remediation/transfer_check`，知识检查评估续接只广告已写入终态呈现的一个精确句柄。

评价续接的必需提供方投影保持既有 1,200 字符预算：省略可选 recent 教学 units，不重复序列化后继句柄，并禁止 bounder 驱逐唯一必需候选；仍无法表示时在提供方前拒绝继续处理。API/SSE/导出不返回原始响应、accepted 答案、私有测试/量规、请求哈希或提供方载荷。


## 2026-09-02：对话内 AI 代码审查 Artifact

历史 `model_code_review_v1` Artifact 与既有 Lesson Gate 复习 API 继续可读；新的 Learning
由 Learning Item 支撑的对话内审查使用增量 `model_code_review_v2`，不迁移旧提交内容或改写既有
Gate/Review/Attempt。`GET /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}`、
对话快照 v4/v5 与动作响应只返回面向学习者的安全呈现：精确
`exercise_version_id`、服务端构造的 `review_target`、闭合 `review_categories`、锁/结局/分数、
安全评估、回执/结果身份和可选补救句柄。

`review_target` 固定 `presentation_mode=code|diff`、规范化来源/modified 代码、各自 SHA-256、
服务端构造的差异块/行 map、`diff_hash` 与完整 `presentation_hash`。代码仅目标没有可提交的
来源侧；每条发现项必须在同一当前差异块/侧中完整覆盖连续行，不能以一个重叠行接受
跨差异块或越界范围。类别只允许需求偏离、虚构 API、逻辑边界、契约集成、异步生命周期、
安全信任、错误处理虚假成功与可选弱测试。

`POST .../artifacts/{artifact_id}/actions` 的 `complete_review` 必须携带精确
`model_code_review_submission_v2={presentation_hash,verdict,findings[]}`；发现项只含有界
客户端 ID、差异块、侧、start/end、闭合类别、严重程度和简短解释。服务端重新验证
用户/对话/学习路线/TeachingSession、Artifact 版本、已发布 Learning Item/实体化、
当前哈希/差异块/范围与类别，再以私有量规做确定性评分。相同动作键/正文重放
同一 Artifact 事件；同键不同请求体返回 `409 IDEMPOTENCY_CONFLICT`。

完整提交内容、预期发现项、匹配器 concept、私有量规/测试/证明、提供方响应正文/推理
不进入 Artifact、快照/历史/SSE、桌面端、Tutor 上下文、公开错误或本地导出。失败结果
必须在同一事务绑定语义不同且已发布、未使用、D(n-1) 或 D(n) 且范围更小/难度更低的
补救句柄；缺失时整个写操作拒绝继续处理。已通过结果没有后继。终态事件只产生
一个精确回执支持 `model_review_evaluation` 续接；模型可写后续教学消息，但不能修改
结局、分数、回执、后继、掌握度或进度。

<a id="2026-09-02对话内-sql-learning-workspace"></a>
## 2026-09-02：对话内 SQL 学习工作区

历史 `sql_workspace_v1` 继续可读；新的已发布 SQL Learning Item 使用增量
`sql_workspace_v2`。公开呈现只含精确 `exercise_version_id`、SQLite/
`teaching_local` 标识、starter 查询/哈希、最多 8 张已发布表的有界 column/类型/PK/FK
数据库结构、`max_rows`，以及可选且绑定精确查询哈希/Attempt ID 的 `table_result_v1`。公开契约
不含 setup SQL、私有数据集、预期行、标准查询、application database 身份或任意连接目标。

`POST /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/actions` 的 SQL `run`
只在第一段由调用方管理的事务中创建并链接精确 Learning Item-owned 待处理 Attempt；该 Attempt
绑定当前用户/对话/学习路线/TeachingSession/分配、已发布条目版本和 materialized
ExerciseVersion，`gate_binding_id IS NULL`。路由提交准入后才在第二段连接上运行每次独立的
内存 SQLite 公开/私有 数据集，再通过既有评分器/Attempt 结果权威来源终结、来源/结果
Artifact 投影和结果评估续接。GET Attempt 可幂等恢复已提交待处理 Run；重放不重新创建
Attempt 或结果。

服务端只接受单条 SELECT/WITH，令牌门禁、SQLite 查询仅/authorizer/资源上限同时拒绝
DDL/DML/ATTACH/PRAGMA、unpublished 表、extension/file functions、超时、超过 32 列、200 行硬上限、
500 字符 cell 或 65,536-byte 表呈现。公开数据集的结果列/行原样进入有界 grid；隐藏
数据集只投影顺序化 `non-visible-N` 通过/失败摘要。本路径不新建 Gate/Review 权威来源，也不写
掌握度/进度。


<a id="2026-09-02lessondocument-exact-reference-resolver"></a>
## 2026-09-02：LessonDocument 精确引用解析器

新增仅限切换已验证用户的读取端点 `POST /api/learning-tracks/{track_id}/lesson-references/{conversation_id}/resolve`。请求体包含 `user_id`、`knowledge_key`、`source`；`source` 是严格判别联合类型：当前 Lesson 引用提交 `document_id`、内容哈希、分配版本、块及可选引用；历史消息提交已持久化上下文引用 ID；来源工件提交精确 Artifact ID/版本。未知或额外字段不会被忽略。

服务端先校验对话的精确用户/学习路线作用域，再解析不可变来源身份。上下文引用必须是同对话/学习路线/知识的 lesson_selection 且安全载荷哈希有效；Artifact 必须是同作用域、同版本的 source_inspector_v1，并且呈现与唯一 lesson_document 来源引用的文档/哈希/版本一致。随后按精确分配/文档/版本/哈希/块/摘录/范围/引用读取冻结 Lesson 与来源快照，不做文本、DOM 顺序或活跃文档降级。

公开 lesson_document_reference_v1 返回来源身份、当前/历史、精确分配、当前活跃分配指针、完整学习者可见的冻结 Lesson、有界来源快照和目标块/哈希/安全摘录/引用。跨作用域或不存在对象返回 404 DOCUMENT_REFERENCE_NOT_FOUND；格式非法返回校验/422 DOCUMENT_REFERENCE_INVALID；版本/哈希/块/范围/引用/来源链不一致返回 409 DOCUMENT_REFERENCE_STALE。历史分配存在时返回旧文档并标记历史，而不是误框当前相似段落。响应不含提交内容、私有量规/测试/参考答案、提供方响应正文/推理、命令、路径、容器或密钥。


<a id="2026-09-02learning-artifact-platform-contract-reconciliation"></a>
## 2026-09-02：Learning Artifact 平台契约核对

公开 Learning Artifact 边界为 `tutor_learning_artifact_v1`，呈现与操作均采用闭合联合类型。`TutorPublicItem` 和会话条目引用包含 `artifact`；会话事件投影为 `tutor_conversation_event_v3`；后端读取快照 v3/v4/v5，桌面端保留 v2-v5 兼容。Artifact 详情、操作、Attempt 路由及精确 Lesson 来源解析器均要求切换已验证；返回或修改投影前，必须匹配用户、会话、路线、知识点、TeachingSession、Artifact/版本、所属权威对象和来源身份。

写入准入由默认关闭的 `TUTOR_LEARNING_ARTIFACTS_ENABLED` 与 `TUTOR_ARTIFACT_TEACHING_MODE_ENABLED` 控制。提供方只能看到服务端构造的已发布句柄；缺少兼容句柄或任一开关未放行时，编辑、运行、审查、查询、演示类 Artifact 意图必须在公开 Tutor 消息前被拒绝。已有安全历史仍可读取。每个类型复用现有 Gate/Review/Attempt/Teaching/Result 权威；Artifact 接口层不另建分数、掌握度、进度、调度或发布状态机。

公共 API、快照、SSE、桌面端载荷、本地导出、错误和就绪证据均不包含完整提交、私有评分规则/测试/参考答案、隐藏 SQL 数据、提供方响应正文/推理、命令、路径、容器身份、凭据及密钥。默认本地验证不包括真实提供方、Docker 一致性、生产镜像构建/签名/发布、推送、部署或生产迁移；这些操作需要单独批准，本地验证不构成发布批准。

<a id="2026-09-16learning-artifact-current-contract-reconciliation"></a>
## 2026-09-16：Learning Artifact 当前契约核对

本次核对不新增路由或客户端可写字段。既有 `tutor_learning_artifact_v1`、Artifact 操作、事件投影 v3、可读快照 v3/v4/v5（桌面端兼容 v2/v3/v4/v5）及精确的 `lesson_document_reference_v1` 仍为公共边界。当前教学使用 `tutor.lesson-teaching@1.2.1` 与 `tutor.teaching-step-decision.v3`；带日期的 1.2.0 记录属于历史，不是当前准入依据。

Artifact 操作继续携带精确的用户/路线/TeachingSession 作用域、客户端操作身份和预期 Artifact 版本。同请求重放返回已有证据；权威失效退役不能产生分数/掌握度，也不能改写冻结的呈现内容。精确引用的版本/哈希/范围检查及公开/私有数据脱敏边界保持不变。

提交落库前的模型代码审查语义评估，与后续 Tutor 评价消息是不同阶段；后者不能编辑已有结果回执。可恢复的语义证据不可用或不确定状态，不能被描述成成功评估。本次文档更新不改变 API 或评分策略。

源码契约矩阵以当前清单、已注册路由和类型化联合为核查依据。历史浏览器、测试夹具和提供方回执仍保留各自日期，不能因增加文字标记就成为当前端到端验收。

### 2026-09-17：源码核查边界

`app/main.py` 当前显式注册 13 组路由，包含 Learning Artifact、LessonDocument、TeachingSession、路线复习和 Tutor；不能将旧接口移除列表理解为这些现有路由被移除。请求模型的 `RequestValidationError` 统一映射为 HTTP 400 和 `VALIDATION_ERROR`；Lesson 引用解析器另有 HTTP 422 的 `DOCUMENT_REFERENCE_INVALID` 业务错误，二者不是同一校验层。当前 Artifact 开关默认值、教学 Skill/决策版本和数据库片段清单已按本地源码核对；本次未启动 API 或执行任何写入。
