# Codex 学习计划工具与恢复实施结果

## 当前结论

- 日期：2026-08-18。
- Child 2 前置条件：已满足。
- Child 3 实施结论：通过。
- 正式 Tutor admission、Runtime correlation DB、公开投影与 Desktop：未接入，继续由后续 Child 负责。
- 真实 provider 调用：未执行，也不需要执行；本任务全部验证为 fake App Server、确定性单元测试和本地 PostgreSQL 集成测试。
- 用户全局 `C:\Users\PINKING\.codex`：未读取、未修改。

## 实施范围

新增服务端权威的 Codex LearningPlan typed tool facade：

- `aearn_planning_context_read`：读取 bounded confirmed facts、missing facts、facts revision/fingerprint、当前 draft 摘要和计划约束；
- `aearn_learning_plan_draft`：只接收 2-8 个 typed modules，每个 module/node 使用显式 `stable_key`、教学字段和 prerequisite/capability 数组；
- 模型输入不再包含 `profile_json`、`module_1..8`、user/session/run/database ID、source、runtime kind 或 confirm action；
- profile 仅从 confirmed `PlanningFact` 构造，`pace_constraints` 服务端映射为 `pace_summary`，title 由服务端确定性派生；
- 旧 Harness capability 与新 typed facade 共用 LearningPlan artifact builder、语言/source policy、图校验、quality gate 和 append-only repository。

## 结果分类与恢复

统一 tool result 状态为：

- `completed`；
- `repairable_invalid`；
- `awaiting_user`；
- `conflict`；
- `policy_blocked`；
- `unavailable`；
- `fatal`。

`repairable_invalid`、`awaiting_user` 和首个 bounded `conflict` 作为正常 tool output 返回模型；policy、unavailable、fatal 与预算耗尽返回失败 tool call，使 App Server 结束当前 turn。

默认预算：

- tool calls：6；
- repair：2；
- conflict rebuild：1；
- input payload：32,000 bytes；
- wall clock：30 秒；
- output：8,000 bytes。

安全 issue 只包含 allowlisted `path/code/hint`，不会回显 raw invalid value、Pydantic input、内部 exception、profile、prompt、reasoning、credential 或完整路径。

## Fence 与幂等

Registry 创建时冻结并在每次调用、draft mutation 前刷新：

- Aearn run/user/conversation；
- input revision；
- Tutor lease owner/generation/expiry；
- Codex Runtime connection generation；
- planning facts fingerprint/revision；
- policy allow/deny。

相同 `(source_run_id, source_input_revision)` 成功重放复用现有 draft row 和安全 receipt，不追加第二份 draft。实现同时修复了一个非显然 replay 陷阱：第一次 commit 后 session 已有 current draft，若按当前 session 重新生成 `change_reason`，相同输入会产生不同 content hash；现在 replay candidate 复用已存储的 `change_reason`，因此相同请求稳定返回原结果，不同请求仍返回 conflict。

## Fake App Server 自动化

正式 Runtime fake loop 已覆盖：

- `repairable_invalid -> completed` 同一 Turn 修复；
- `awaiting_user`；
- `conflict`；
- `policy_blocked`；
- `unavailable`；
- `fatal`；
- wall-clock timeout；
- duplicate replay；
- tool result 不进入普通 Runtime event arguments。

## PostgreSQL 集成证据

真实本地 PostgreSQL 测试证明：

1. confirmed facts 可以构造与现有 LearningPlan domain 兼容的 profile；
2. typed draft 成功 append；
3. 相同工具调用只产生 1 条 draft；
4. replay 返回相同 draft id/version/hash/receipt 并标记 `replayed=true`；
5. Runtime generation stale 与 facts fingerprint/revision stale 返回不同 conflict code；
6. policy callback deny 返回 `policy_blocked`；
7. facts 不完整返回 `awaiting_user` 和缺失 stable fact keys；
8. tool result 不暴露 user/conversation/run ID。

## 回归修复

完整测试首次运行得到 `643 passed, 2 skipped, 2 failed`。两个失败均为旧静态边界测试仍要求 `app/agents/runtime/__init__.py` 不存在，与 Child 2 已批准恢复正式 Runtime package 的架构事实冲突。

最终最小修复：

- `runtime` 不再属于“目录必须不存在”的 retired package；
- Harness/Tutor source 仍继续禁止导入 `app.agents.runtime`，因此 Child 3 未提前接业务 admission。

修复后完整 suite 通过。

## 最终验证结果

- focused pytest：`43 passed`。
- 完整 API pytest：`645 passed, 2 skipped`。
- Ruff：`ruff check app tests` 通过。
- Mypy：`188 source files` 无问题。
- `uv lock --check`：通过。
- `compileall -q app`：通过。
- PostgreSQL bootstrap 连续两次：通过。
- Child 3 与父任务 Trellis validate：通过。
- `git diff --check`：通过；仅报告既有 `.trellis/tasks/.obsidian/workspace.json` 行尾提示，未覆盖或回滚该文件。

## 剩余边界

1. 本任务没有把任何 Tutor run 路由到 Codex；正式 admission 仍不存在。
2. 没有新增 Runtime correlation/binding/item receipt 表；由 Child 4 负责。
3. 没有写 public Tutor message/process/error/SSE projection；由 Child 4 负责。
4. 没有执行 plan-drafting cutover；由 Child 5 负责。
5. 没有调用真实 provider、push 或部署。
