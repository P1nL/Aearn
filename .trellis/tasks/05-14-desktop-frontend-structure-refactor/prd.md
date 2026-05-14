# Refactor desktop frontend structure to match interaction spec

## Goal

在不改变当前 M3 用户行为和 API 契约的前提下，把 `aearn/apps/desktop/src/App.tsx` 从单个大文件拆成符合 `docs/product/frontend-interaction-spec.md` 组件边界的前端结构，让 `App.tsx` 回到 app shell / bootstrap / route orchestration 职责，页面与工作台逻辑进入独立文件。

## Background / Known Context

- 正式前端 runtime 位于 `aearn/apps/desktop/src/`，当前入口只有 `main.tsx`、`App.tsx`、`styles.css`、`api.ts`、`types.ts`。
- `docs/product/frontend-interaction-spec.md` 已明确定义顶层组件树和页面组件树，包含 `AppShell`、`OnboardingPage`、`LearningWorkspacePage`、`ReviewPage`、`NotesPage`、`SettingsPage` 以及 M3 工作台子树。
- 当前实现中，`App.tsx` 约 2279 行，除了 `App()` 自身，还内联了 `SidebarNav`、`PlanDraftPanel`、`ExerciseWorkbench`、`RuntimeFeedback`、`HintHistoryCard`、`ErrorFeedbackPane`、`ExplanationCheckPanel`、`SubmissionSummary` 等多个页面级/功能级组件。
- `.trellis/spec/frontend/directory-structure.md` 与 `component-guidelines.md` 允许在 UI “grow beyond the current shell shape” 后按 feature / page 拆分文件；当前桌面端已经超过这个阈值。
- 上一个 M3 任务已经打通后端、前端 build 和浏览器 smoke；本次重构不能牺牲现有 M3 行为闭环。

## Requirements

- 把 `App.tsx` 收敛到 app shell 级职责：bootstrap、全局导航、当前 route 切换、全局 drawer / settings orchestration、跨页共享状态。
- 按 `frontend-interaction-spec.md` 的页面边界抽出独立页面文件，至少覆盖：
  - `OnboardingPage`
  - `LearningWorkspacePage`
  - `ReviewPage`
  - `NotesPage`
  - `SettingsPage`
- 把 M3 学习工作台子树从 `App.tsx` 中抽出独立 feature 组件，至少覆盖：
  - `ExerciseWorkbench`
  - `RuntimeFeedback`
  - `HintHistoryCard`
  - `ErrorFeedbackPane`
  - `ExplanationCheckPanel`
  - `SubmissionSummary`
- 保持当前 API 使用方式和现有 M3 用户行为不变；这次任务不新增后端接口，不修改评分、FSRS、Attempt 语义。
- 保持当前技术约束不变：不引入 React Router、全局状态库、Tailwind、组件库或 CSS-in-JS。
- 保持 stale / loading / error / disabled / retry 等状态反馈行为不回退。
- 前端继续不暴露 `Attempt(run)` / `Attempt(submit)` 等后端内部类型名。

## Acceptance Criteria

- [ ] `aearn/apps/desktop/src/App.tsx` 不再定义页面级 JSX 或工作台结果面板组件；它主要负责 app shell、路由切换和跨页编排。
- [ ] `OnboardingPage`、`LearningWorkspacePage`、`ReviewPage`、`NotesPage`、`SettingsPage` 具备独立文件边界并接入当前运行时。
- [ ] `ExerciseWorkbench` 及其 M3 反馈/解释/提交子组件具备独立文件边界，不再全部内联在 `App.tsx`。
- [ ] 运行预览、可见测试、提示、解释错误、检查解释、提交、stale 标记和重试提示等 M3 行为与当前实现保持一致。
- [ ] 本次任务不修改 backend 文件和 API contract 文档。
- [ ] `pnpm --dir .\aearn desktop:check` 通过。
- [ ] 如果重构过程中发现必须调整行为边界，变更会先写回任务文档再进入实现。

## Definition of Done

- 结构拆分后的文件职责与 `frontend-interaction-spec.md` 页面/组件边界基本一致。
- 关键 props / state ownership 明确，不靠 `App.tsx` 承载全部页面细节。
- 编译检查通过，必要时补充桌面端 smoke。
- 若沉淀出新的前端结构规则，再在 Phase 3 评估是否更新 Trellis spec。

## Out of Scope

- 新增或重写 M4/M5/M6 产品能力。
- 视觉重设计、整体 CSS 体系重写、设计 token 体系重构。
- 引入 React Router、全局 store、组件库或新的样式方案。
- 后端接口、数据库、评分逻辑、FSRS 逻辑改造。
- 把所有现有 helper / 常量都彻底重建为新架构；本次只做支撑当前桌面端的必要拆分。

## Research References

- `docs/product/frontend-interaction-spec.md`
- `.trellis/spec/frontend/directory-structure.md`
- `.trellis/spec/frontend/component-guidelines.md`
- `.trellis/spec/frontend/state-management.md`
- `.trellis/tasks/archive/2026-05/05-13-m3-learning-session-runtime-ui/design.md`

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
