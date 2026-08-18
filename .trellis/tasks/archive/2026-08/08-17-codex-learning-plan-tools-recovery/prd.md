# Codex 学习计划工具与恢复闭环

## 目标

把当前学习计划草案能力改造成 Codex 可调用、Aearn 服务端权威的 typed domain tools，并建立可修复错误回灌闭环。模型只提交结构化教学模块；用户、计划会话、profile、事实 revision、source 与写入 authority 均由宿主注入。

## 依赖

- 父任务：`08-17-codex-runtime-sidecar-integration`。
- 前置任务：`08-17-codex-runtime-adapter-supervisor` 已提供稳定 Runtime 与 tool callback contract。

## 需求

### R1：权威规划上下文工具

- `aearn_planning_context_read` 从当前 user/conversation/plan session 读取 bounded confirmed facts、missing facts、当前 draft 摘要和 facts revision/fingerprint。
- 工具不信任模型提供的 user id、session id、runtime kind 或数据库主键。
- 返回内容必须有长度、字段和隐私白名单，不能暴露内部备注或 secret。

### R2：结构化草案工具

- `aearn_learning_plan_draft` 接收 2-8 个 typed modules，每个 module 使用显式字段与节点数组，不再接收 `profile_json` 或 `module_N` JSON 字符串。
- 服务端从 PlanningFact/plan session 构造 profile、source 与 user scope，并复用现有 LearningPlan 校验和 append-only repository。
- 成功返回 draft id、version、hash 与安全摘要，不执行确认或 LearningTrack 创建。

### R3：错误分类与同 Turn 修复

- 统一结果：`completed | repairable_invalid | awaiting_user | conflict | policy_blocked | unavailable | fatal`。
- 结构、stable key、prerequisite、quality 等模型可修复错误返回 `repairable_invalid` 与安全 path/code。
- 缺少用户事实返回 `awaiting_user`；stale revision 返回 `conflict`；授权/安全失败返回 `policy_blocked`，不可伪装成 repair。
- Repair 最多执行有界次数；耗尽后形成明确 terminal error。

### R4：Fence、预算与幂等

- tool handler 在读取、写入前检查 run active、lease/generation、input revision、facts revision 与 runtime binding generation。
- 使用 idempotency key 或 action receipt 防止断连重放重复 append draft。
- 限制 tool calls、repair count、payload size、modules/nodes、wall clock 与输出大小。

## 范围外

- Runtime correlation DB 表和 public item 投影。
- 正式 plan-drafting feature cutover。
- LearningPlan confirm、LearningTrack 创建、Lesson/Exercise/Review 工具化。

## 验收标准

- [x] 模型不再提交 `profile_json`、`module_1..8`、user id、source 或 confirm action。
- [x] server-authoritative facts 可以确定性构造与现有领域校验兼容的 profile。
- [x] typed schema 拒绝未知字段、越界 modules/nodes、重复 stable key 和无效 prerequisite。
- [x] 第一次 `repairable_invalid` 后模型在同 Turn 内重新调用并成功，学习者无需重复输入。
- [x] `awaiting_user`、`conflict`、`policy_blocked`、`unavailable` 和 `fatal` 不被错误合并。
- [x] stale/duplicate tool call 不产生第二份 draft；成功重放返回原安全结果。
- [x] tool result 与日志不泄露 raw invalid value、profile 私有字段或内部异常。
