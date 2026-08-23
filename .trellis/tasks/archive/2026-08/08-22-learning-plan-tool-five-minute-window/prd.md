# LearningPlan 工具时间窗口调整为五分钟

## 目标

将 Codex `plan_drafting` 的 `LearningPlanRuntimeToolRegistry` wall-time 预算从 30 秒扩大为 300 秒，避免模型在首次调用 `aearn_learning_plan_draft` 前进行较长 reasoning 时，计划工具立即返回 `tool_deadline_exhausted`。

## 背景

- 2026-08-22 最新计划对话的末轮总耗时约 34.716 秒，整体 `CODEX_RUNTIME_TURN_TIMEOUT_SECONDS=300` 并未耗尽。
- `aearn_learning_plan_draft` 在该轮开始约 30.45 秒后首次调用并立即失败；随后 `aearn_planning_context_read` 也失败。
- 根因是 `LearningPlanToolBudget.max_wall_seconds=30.0` 从 registry 创建时开始计时，模型 reasoning 时间也包含在该窗口内。

## 范围内

- 将默认 `LearningPlanToolBudget.max_wall_seconds` 调整为 `300.0`。
- 保留现有 `0.1..600` 校验范围与 `tool_deadline_exhausted` 失败语义。
- 更新单元测试，使 300 秒以内仍允许调用，超过 300 秒继续失败。
- 同步 Codex Runtime sidecar 规格中记录的默认工具 wall-time。

## 范围外

- 不修改 `CODEX_RUNTIME_TURN_TIMEOUT_SECONDS`、Tutor run deadline、模型、provider 或 protocol。
- 不调用真实 provider，不重放或修改现有计划对话数据。
- 不改变工具调用次数、repair、conflict、payload 或 output bytes 预算。

## 验收标准

- [x] 默认 `LearningPlanToolBudget.max_wall_seconds == 300.0`。
- [x] registry 创建后 299 秒的首次工具调用可以正常执行。
- [x] registry 创建后超过 300 秒的工具调用返回 `tool_deadline_exhausted`。
- [x] 相关 focused pytest、Ruff、Mypy 与 `git diff --check` 通过。
- [x] 两项受保护 Obsidian 用户修改不被覆盖或提交。
