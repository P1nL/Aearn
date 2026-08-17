# 技术设计

## 设计目标

以现有服务端权威计划草案和确认 API 为基础，消除 plan-drafting 流程中由通用 typed approval 产生的第二个确认入口。保持通用 Tutor continuation/approval 体系完整，避免为了一个产品流程例外重写 thread/turn v2 协议。

## 当前数据流

```text
普通 planning input
  -> fresh TurnRun
  -> tutor.learning-plan-draft@1.0.1
  -> learning.plan.draft capability
  -> append-only current_draft
  -> provider 再次决策
  -> 可能错误选择 wait_for_input(approval)
  -> pending approval 完全替代 Composer

右侧计划窗口
  -> POST /api/learning-plan-sessions/{id}/confirm
  -> exact session/draft/version/hash 校验
  -> 原子创建 LearningTrack
```

问题在于 provider 的最后一步把“计划已经可供审阅”误解成 generic approval，而右侧 HTTP confirm 已经拥有真正的计划确认 authority。

## 目标数据流

```text
普通 planning input
  -> fresh TurnRun
  -> learning.plan.draft capability
  -> append-only current_draft
  -> provider 输出可见总结 + turn_completed
  -> Composer 继续可用

用户提出修改
  -> 普通 conversation input
  -> fresh TurnRun
  -> 新 current_draft version
  -> 右侧窗口自动展示最新版

用户确认
  -> 仅点击右侧“确认并创建学习主线”
  -> POST /api/learning-plan-sessions/{id}/confirm
  -> 原子创建 LearningTrack
```

## 边界设计

### 1. Learning-plan Skill 边界

修改 `aearn/services/api/app/agents/skills/tutor.learning-plan-draft/1.0.1/instructions.md`：

- capability 成功后只告知“计划已可审阅”；
- 最终 action 必须结束当前 turn；
- 明确禁止使用 `continuation_kind=approval` 确认当前 learning-plan draft；
- 修改请求只能来自后续普通 planning input，再生成完整替代版本。

保留 Skill 的 exact capability 输入、模块/node、字符限制和 server-owned source/runtime 约束。

### 2. 通用决策示例边界

修改 `aearn/services/api/app/services/tutor/decision_protocol.py` 的 canonical approval example：

- 不再以学习计划为示例；
- 使用真正需要 yes/no authorization 的受控操作示例；
- 不改变 JSON schema、枚举或 parser。

这样通用 provider 指令仍教授 approval 的合法用途，但不会与 plan session confirm 混淆。

为避免只依赖模型遵循指令，interactive provider boundary 增加窄的确定性安全网：当且仅当 exact run 能解析到 active `plan_drafting` session 且 provider 仍返回 `approval` 时，保留公开消息并清除 continuation，使 Turn 正常完成；无法解析到该 session 的 generic approval 原样保留。该规则不读取 prompt 文案，也不改变 approval DTO。

### 3. Desktop Composer 边界

`LearningPlanBuilderPage` 已拥有 `current_draft`。通过窄 props 将草案是否存在或计划态 placeholder 传给 `TutorConversationSurface` / `Composer`：

- 无草案：`描述你想学习什么`；
- 有草案：`对计划有修改意见？直接告诉我……`。

不把完整 draft 传入对话组件，不让 `TutorConversationSurface` 读取 learning session API，也不在 Composer 中渲染确认按钮。

通用 `TypedRequestSeat` 保持不变；当后端遵循新计划契约时，plan-drafting 不会产生用于计划确认的 approval，因此普通 Composer 自然保持可见。非计划场景的 pending approval 仍完全占用 Composer。

### 4. Think 验证屏障、稳定窗口与恢复边界

问题根因不在 timer 本身，而在跨层 completion 语义：旧 projector 在 provider transport EOF 时立即调用 `complete_attempt()`，但 gateway 随后仍可能因 action/schema/domain validation 失败而 discard。真实 rejected generation 从首个 append 到 discard 可超过数秒，因此单纯 `350ms` 只能遮住快速失败。

目标数据流：

```text
provider delta
  -> projector 解析 exact public_thinking_text
  -> append 安全候选前缀（provisional）
  -> provider EOF：只校验 JSON 闭合并 flush，不发 complete
  -> gateway 校验完整 schema/domain/safety + stream/final exact match
  -> complete（validated reveal authority）
  -> Desktop 在 complete + 350ms 同时满足后进入 DOM

任一完整决策失败
  -> append（可能持续数秒）
  -> discard
  -> replacement generation
  -> 从未进入 DOM
```

Desktop 继续把 live generation 分为 buffered 与 visible 两层：

- `receivedText` 接收 exact `turn_id + input_revision + generation + chunk_sequence`，但 append 不直接驱动 DOM；
- 新 generation 的首段同时启动固定 `350ms` 稳定窗口；timer 只依赖 generation identity 与是否已有文本，后续 append 不重启；
- `revealLiveThinking` 必须同时满足 `liveThinking.complete` 与稳定窗口；任一条件缺失都保持静态 `StateDot + Think`；
- snapshot 仅在 `active_thinking.complete=true` 时即时恢复；incomplete snapshot 继续缓冲；
- authoritative reset/discard 取消 generation；validated 文本的 recovery 路径继续保留当前可见内容直到 snapshot 裁决。

该方案不新增 event operation、数据库列或 state；只收紧现有 `complete` 的业务语义，并保留现有 accepted stream 与最终 message 的原子一致性检查。

### 5. 右侧确认边界

保留 `LearningPlanDraftCard` 的现有确认调用：

- `LearningPlanBuilderPage` 继续拥有 session、draft、confirming/cancelling/error 状态；
- `TutorConversationSurface` 不获得确认权限；
- `confirmLearningPlanSession()` 继续发送 exact session version、draft id/version/hash；
- 成功后调用 `onConfirmed(track_id)`。

本任务只校正文案与职责，不新增第二套 plan mutation。

## 状态矩阵

| 状态 | Composer | 右侧计划窗口 | 确认入口 |
|---|---|---|---|
| session collecting、无 draft | 收集目标与计划事实 | emoji 等待态 | 无 |
| draft ready | 提出修改或补充要求 | 展示 current draft | 右侧唯一按钮 |
| 新修改 turn 运行中 | 沿用现有 running/Queue 语义 | 继续展示当前服务端 draft | 不新增底部 approval；stale 由现有确认契约保护 |
| 新 draft 到达 | 恢复普通修改输入 | 自动展开最新版本 | 右侧最新版按钮 |
| confirming | 保持页面但不重复触发确认 | 按钮 busy/disabled | 右侧 |
| confirmed | 页面导航到正式 LearningTrack | planning view 退出 | 无 |
| 非计划 generic approval | typed request seat 接管 | 不涉及计划窗口 | typed approval seat |

## 兼容策略

- 不改变 public DTO 和 API schema，因此 Desktop/API 版本无需升级。
- 不迁移开发期已经持久化的 redundant approval item；避免自动批准、自动拒绝或根据文案猜测语义。
- 新生成的 plan draft 不再产生该 item。测试应创建全新 planning session，避免旧 fixture 掩盖结果。

## 测试设计

### 后端

- Skill catalog/指令测试：`1.0.1` 明确禁止 plan confirmation approval，并要求 capability 后结束 turn。
- decision protocol 测试：canonical approval example 仍能通过 exact schema，但文案不再指向学习计划。
- fake-provider 或 run-loop 回归：成功生成 draft 后最终 decision 为 completed，不持久化 pending approval item。
- 现有 `test_tutor_interaction_requests.py` 的 generic approval identity/CAS 测试保持通过。
- 现有 `test_learning_plan_sessions.py` 的 exact confirm、stale、idempotency 测试保持通过。

### 前端

- `LearningPlanBuilderPage` 测试或相邻组件测试：有 draft 时 Composer 显示修改提示，右侧仅有 `确认并创建学习主线`。
- `TutorConversationSurface` typed request 测试继续证明 generic approval/elicitation 仍可接管 Composer。
- 点击右侧确认断言 exact API 参数和 busy 状态。
- 新版本 draft 到达仍自动展开；同版刷新不重置手动收起。

### 文档与浏览器

- 1440px、900px、390px 验证 Composer 与右侧/底部浮动 inspector 均可达，无水平溢出或遮挡。
- 确认页面中只存在一个创建正式计划的主操作。
- console clean，键盘可聚焦 Composer、展开计划窗口并触发确认。

## 回滚

- Skill 与 canonical example 可独立回退，不影响存储 schema。
- Composer placeholder props 可回退到固定文案。
- 右侧 confirm API 未改变，因此本任务不需要数据库回滚。
