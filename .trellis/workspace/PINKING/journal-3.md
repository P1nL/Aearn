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
