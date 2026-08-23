# Journal - PINKING (Part 3)

> Continuation from `journal-2.md` (archived at ~2000 lines)
> Started: 2026-08-23

---



## Session 119: 完成教学会话 authority 与结构化 Turn 触发

**Date**: 2026-08-23
**Task**: 完成教学会话 authority 与结构化 Turn 触发
**Branch**: `main`

### Summary

完成 Child 1：新增 durable TeachingSession/checkpoint、exact TutorTurnStimulus、immutable run teaching scope、stale commit fence、verified-only API、cutover/export/reset/delete 治理与 PostgreSQL/focused 测试；未调用真实 provider，未启动 Child 2。

### Git Commits

| Hash | Message |
|------|---------|
| `f88cea72` | (see git log) |

### Status

[OK] **Completed**


## Session 120: 完成 Harness closed teaching action Loop

**Date**: 2026-08-23
**Task**: 完成 Harness closed teaching action Loop
**Branch**: `main`

### Summary

完成 Child 2：发布 tutor.lesson-teaching@1.0.0，接入 required TEACHING_SESSION 与 strict teaching_step，原子提交 checkpoint/action receipt/message/run terminal，实现 bounded focus reducer、服务端 Action Shelf、Free Reading 显式 escalation、authority refresh successor、completion pause 与显式 next-node transition。focused 187 passed，完整 API 711 passed/2 skipped，bootstrap twice、Ruff、Mypy、Trellis validate 与 diff check 通过；未调用真实 provider，未启动 Desktop child。

### Git Commits

| Hash | Message |
|------|---------|
| `5e3b05bc` | (see git log) |

### Status

[OK] **Completed**


## Session 121: 完成 Guided/自由阅读工作区与 Composer Action Shelf

**Date**: 2026-08-23
**Task**: 完成 Guided/自由阅读工作区与 Composer Action Shelf
**Branch**: `main`

### Summary

完成 Child 3：以单一 Tutor/Lesson/SSE authority 实现 Guided/Free Reading 主次换位、教学 session 分组、文档跟随、closed Action Shelf 与 exact 历史消息引用，并通过自动化和三视口 browser gate。

### Main Changes

- 新增 useTeachingWorkspaceController、server-authoritative mode/action/conflict 处理与稳定 Tutor/Lesson CSS role swap。
- 增加 teaching session/group/shelf/follow exact DTO 与 strict parser；conversation projection 使用 durable turn_ids 分组。
- 增加 teaching_session_message exact reference：公开投影仅含中性元数据，完整历史消息只在内部模型上下文按 authority 解析。
- 补齐 Guided follow pause/resume、Free Reading 不抢滚动、completion 显式导航与 responsive/accessibility 样式。

### Git Commits

| Hash | Message |
|------|---------|
| `57be45fc` | (see git log) |
| `eb55a21b` | (see git log) |

### Testing

- [OK] Desktop Vitest：58 passed；desktop:check 通过。
- [OK] API 全量：712 passed, 2 skipped；教学/引用 focused PostgreSQL：24 passed；bootstrap twice：2 passed。
- [OK] Ruff、Mypy、Trellis validate、git diff --check 均通过；browser smoke 覆盖 1440x900、900x900、390x844、reduced motion、conflict/no replay、single mount/SSE 与 console clean。

### Status

[OK] **Completed**

### Next Steps

- 仅在下一次明确执行指令后启动 08-22-adaptive-learning-integration-evals；不要自动启动父任务或其他 child。


## Session 122: 完成长期自适应教学集成 Child 4

**Date**: 2026-08-23
**Task**: 完成长期自适应教学集成 Child 4
**Branch**: `main`

### Summary

完成 domain event admission、checkpoint-backed teaching summary、deterministic eval、隐私治理与最终质量门，并归档 Child 4。

### Main Changes

- Gate/Attempt、Review、progress 与 assignment owner 接入统一 durable domain-event adapter，重复/陈旧 source fail closed。
- Teaching checkpoint 生成结构化 summary，扩展 current-session context precedence 与 correction/unresolved compaction protection。
- 新增 deterministic adaptive teaching eval，并同步 backend specs 与 source-of-truth docs。

### Git Commits

| Hash | Message |
|------|---------|
| `ad1cd13e` | (see git log) |
| `e1b9d2c3` | (see git log) |

### Testing

- [OK] Focused Child 4 50 passed；teaching/Gate/Review/Lesson regression 33 passed；adaptive eval 4 passed。
- [OK] 完整 API 716 passed, 2 skipped；Ruff、Mypy 200 files、Desktop 58 tests/build、bootstrap twice 通过。
- [OK] Browser Guided↔Free Reading、reload/reconnect、1440/900/390 无溢出、overlay、console error/warning 或 protected marker。

### Status

[OK] **Completed**

### Next Steps

- 复核父任务 08-22-harness-led-adaptive-learning-workspace 的四个 child archive 与 PRD 验收映射；不自动归档父任务，等待用户收尾决定。


## Session 123: 归档 Harness 主导的长期自适应学习工作区父任务

**Date**: 2026-08-23
**Task**: 归档 Harness 主导的长期自适应学习工作区父任务
**Branch**: `main`

### Summary

四个 child 已按依赖顺序完成、提交、归档；父任务验收映射、质量门、source-of-truth docs 与工作树边界复核通过，现已完成父任务 closeout。

### Main Changes

- 确认 teaching authority、closed teaching loop、Guided/Free Reading Desktop 与 adaptive integration 四个 child 均为 completed archive。
- 确认父任务 4/4 done、validate 通过，并归档 08-22-harness-led-adaptive-learning-workspace。
- 保留另一个 LearningPlan 五分钟窗口任务及其六个用户修改，不暂存、不提交、不覆盖。

### Git Commits

| Hash | Message |
|------|---------|
| `f88cea72` | (see git log) |
| `5e3b05bc` | (see git log) |
| `57be45fc` | (see git log) |
| `ad1cd13e` | (see git log) |

### Testing

- [OK] 最终证据：完整 API 716 passed, 2 skipped；Ruff、Mypy、Desktop 58 tests/build、bootstrap twice 与 browser smoke 通过。
- [OK] 父任务 Trellis validate 与归档后 task tree/status 复核通过。

### Status

[OK] **Completed**

### Next Steps

- 该父任务树已完成；后续如继续 LearningPlan 五分钟窗口任务，应在其独立会话和既有修改基础上执行。


## Session 124: LearningPlan 工具五分钟窗口收尾

**Date**: 2026-08-23
**Task**: LearningPlan 工具五分钟窗口收尾
**Branch**: `main`

### Summary

将 Codex plan_drafting LearningPlan Runtime 工具默认 wall-time 从 30 秒调整为 300 秒，补充窗口内与超时回归，完成全量离线质量门并归档任务。

### Main Changes

- 默认 LearningPlanToolBudget.max_wall_seconds 调整为 300.0，保留既有范围校验和 fail-closed 超时语义。
- 同步 Codex Runtime sidecar 规格，并更新 LearningPlan 工具与 Runtime adapter 回归测试。

### Git Commits

| Hash | Message |
|------|---------|
| `9e8d5511` | (see git log) |

### Testing

- [OK] focused pytest: 46 passed
- [OK] full API pytest: 716 passed, 2 skipped
- [OK] Ruff、Mypy、lock check、compileall、bootstrap twice、Trellis validate、git diff --check 均通过

### Status

[OK] **Completed**

### Next Steps

- 保留 .trellis/tasks/.obsidian 下两项用户修改，不纳入本任务提交。
