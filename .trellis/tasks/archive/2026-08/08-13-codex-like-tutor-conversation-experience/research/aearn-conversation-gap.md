# Aearn 当前对话链路与差距

## 当前事实

### Conversation 与 run

- `TutorConversation` 已是持久化会话范围。
- 普通 conversation input 调用 `create_interactive_turn`，会取代旧前台 run 并创建 fresh run。
- `/runs/{run_id}/inputs` 允许 `waiting_for_input` 且带 `continuation_kind` 的 run 接收下一 revision；它继续使用旧 run 的 deadline 和全部累计计数。

源码锚点：

- `aearn/services/api/app/services/tutor/public_api.py:169`：普通 conversation input。
- `aearn/services/api/app/services/tutor/public_api.py:207`：旧 run input。
- `aearn/services/api/app/services/tutor/public_api.py:627`：fresh interactive turn。
- `aearn/services/api/app/services/tutor/public_api.py:704`：显式 continuation 合并旧 run。
- `aearn/services/api/app/services/tutor/persistence.py:577`：`create_interactive_turn`。
- `aearn/services/api/app/services/tutor/persistence.py:1575`：`accept_input`。

### 预算故障证据

2026-08-13 的实际 run：

- `run_id=1a24887e-41b7-4a06-a38e-cc85e4865bd8`
- `terminal_outcome=budget_exhausted`
- `terminal_diagnostic_code=model_call_budget_exhausted`
- `model_call_count=3`，`max_model_calls=3`
- 第一次用户输入已经消耗两次模型调用，continuation 回复在同一个 run 中消耗第三次；Skill context rebuild 还需要下一次模型调用时触发预算终止。

根因不是 DeepSeek transport 或 schema 失败，而是阻塞式学习问答复用了旧 turn 的有限预算。

### Run loop

- run 在每次采样前检查累计 `iteration_count` 和 `model_call_count`。
- decision 返回 `continuation_kind` 时，run 进入 `waiting_for_input`，没有形成独立 turn/item 级 elicitation。
- public API 把所有 `budget_exhausted` 合并为 `TUTOR_RUN_UNAVAILABLE`。

源码锚点：

- `aearn/services/api/app/services/tutor/run_loop.py:122`。
- `aearn/services/api/app/services/tutor/run_loop.py:313`。
- `aearn/services/api/app/services/tutor/public_api.py:1331-1349`。

### SSE 与 Desktop

- SSE 是 run-local sequence；Desktop 只订阅一个 `active_run.run_id`。
- 公开事件只有 `input_accepted | tool_status | activity | run_state | done | error`。
- SSE 事件触发节流 history refresh；timeline source of truth 是 history endpoint。
- UI 只有 `ordinary | continuation` 两种 composer mode。
- running 时没有明确 steer/queue 选择，也没有用户可见 interrupt 控制。
- 错误可展示，但不存在关联原 turn 的 retry contract。

源码锚点：

- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx:136`。
- `aearn/apps/desktop/src/hooks/useTutorSSE.ts:437`。

## 与 Codex-like 体验的差距

| 维度 | 当前 Aearn | 目标方向 |
| --- | --- | --- |
| Conversation | 已持久化 | 保留并明确为 thread |
| Turn | run 可跨 continuation 多轮 | 每条普通请求独立 turn；阻塞项单独建模 |
| Timeline item | message + 聚合 process | typed user/assistant/progress/action/elicitation/error item |
| 运行中输入 | 普通输入 supersede；continuation 合并 | steer 与 queue 显式区分 |
| Agent 提问 | assistant message + waiting run | typed elicitation/request + 精确 response identity |
| 停止 | 内部 cancel/supersede | 用户显式 interrupt API 和 UI |
| Retry | transport retry，缺少 turn retry | 从失败 turn 创建关联新 turn，副作用去重 |
| Stream | run-local SSE | conversation/thread event stream 或可跨 turn 的统一 cursor |
| 错误 | 多种预算原因合并 | learner-safe 分类 + recoverability/action |
| 恢复 | history + active run | thread snapshot + turn/item projection + live cursor |

## 建议的产品映射

- `TutorConversation` → Codex `Thread`。
- `TutorRun` → Codex `Turn`，但保留 Aearn policy、Skill、capability、effect 和 learner scope。
- `TutorPublicTimelineItem` → Codex `ThreadItem` 的 learner-safe 子集。
- `clarification/planning_input` → typed elicitation item，而不是任意 run input merge。
- `approval` → typed approval item/response。
- `capability_result/external_result` → 服务端 authority receipt 唤醒，不通过普通 learner composer。
- 普通 composer：idle 时 start turn；running 时按产品设置 steer 或 queue；waiting elicitation 时只回答目标 item。

## 兼容风险

1. 当前数据库、API 和 Desktop 都把 `waiting_for_input` 视为 active foreground run；迁移必须处理已存在记录。
2. conversation history 当前混合 message/process 两类，新增 item contract 需要 versioned projection 或兼容 union。
3. run-local SSE cursor 无法自然跨新 turn，若要 Codex-like 单一流需要 conversation-level event sequence。
4. 当前部分文档已经声称“普通消息 fresh run”，但同时允许 continuation 复用旧 run；必须修正这种语义冲突。
5. 工作树中已有 continuation enum/prompt/Model Review 未提交修改，新任务不能覆盖或回退这些改动。
