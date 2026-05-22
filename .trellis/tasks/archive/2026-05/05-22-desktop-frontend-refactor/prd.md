# Desktop 前端架构重构与体验优化

日期：2026-05-22  
状态：Draft V1.0

## 背景

桌面端（`aearn/apps/desktop`）已完成从 HTML 原型到 React + Tauri 的迁移，核心闭环（建档 → 学习 → 练习 → 复习 → 笔记）功能已可用。但在以下方面存在明确的改进空间：

1. **代码编辑器体验**：当前使用 `<textarea>`，无语法高亮、自动缩进、括号匹配
2. **App.tsx 臃肿**：1326 行，集中了所有状态管理、业务逻辑、笔记管理
3. **错误处理粗糙**：所有错误转为字符串，丢失错误码，无差异化提示
4. **笔记自动保存**：800ms setTimeout 防抖不够健壮，缺少并发保护
5. **用户反馈不足**：缺少 Toast 通知系统，操作结果不够明显

## 目标

在不破坏现有功能的前提下，分阶段完成前端架构优化，提升代码质量和用户体验。

## Requirements

### R1：集成专业代码编辑器（P0）

- 用 Monaco Editor 替换 ExerciseWorkbench 中的 `<textarea>`
- 支持 JavaScript、Python、HTML/CSS 语法高亮
- 支持自动缩进、括号匹配、行号显示
- `compiled_sandbox_later` 语言（Java/C++）编辑器为只读态
- 编辑器状态（pristine → dirty → running → submitted）保持不变
- 代码修改后旧测试结果标记为 stale（现有逻辑保留）

### R2：优化笔记自动保存（P0）

- 防抖保存增加并发锁，避免多次保存请求同时发出
- 关闭抽屉前确保保存完成或明确提示失败
- 保存失败后允许重试，不丢失本地编辑内容
- 切换知识点时先尝试保存当前未保存内容

### R3：细化错误处理（P0）

- 创建错误码到友好中文提示的映射表
- 区分可恢复（显示重试按钮）和不可恢复错误
- 关键错误码覆盖：RUNNER_TIMEOUT, RUNNER_UNAVAILABLE, RUNTIME_UNSUPPORTED, SESSION_NOT_FOUND, ATTEMPT_STATE_CONFLICT, IDEMPOTENCY_CONFLICT, EVALUATION_CONFLICT
- 不改变后端 API 错误结构，仅优化前端展示层

### R4：引入轻量状态管理（P1）

- 用 Zustand 替代 App.tsx 中的 30+ 个 useState
- 按职责拆分为独立 store：app store、notes store、settings store
- 将业务逻辑抽取为自定义 hook：useLearningSession、useNotes、useSettings
- App.tsx 只保留布局和路由组合逻辑

### R5：添加 Toast 通知系统（P1）

- 集成 sonner 库作为全局通知
- 覆盖场景：笔记保存成功/失败、设置保存成功/失败、运行超时、API 离线恢复
- 不替换现有的内联错误展示，Toast 作为补充

### R6：SSE Hook 架构预设（P2）

- 创建 useSSE hook 框架代码和类型定义
- 定义 SSE 事件类型：agent_message、tool_status、runner_result、evaluation_result、done、error
- 当前不接入真实 SSE（后端未实现），但 hook 可用于后续无缝切换
- 在 api.ts 中预留 SSE 请求路径

## 约束

- 不改变后端 API 接口或数据结构
- 不改变现有页面路由和导航逻辑
- 不引入路由库（当前使用自定义 activeRoute 状态）
- 保持 React 19 + Vite 6 + TypeScript 5 技术栈
- 所有改动必须通过 `tsc --noEmit` 和 `vite build` 验证
- Monaco Editor 使用 `@monaco-editor/react`，不直接引入 monaco-editor 以减少 bundle

## 不做

- 不做 SSE 后端实现（后端独立任务）
- 不做多文件编辑器 / 项目级代码管理
- 不做 React Router 迁移
- 不做 UI 视觉大改（保持现有 Claude Desktop 风格）
- 不做测试框架搭建（后续独立任务）

## Acceptance Criteria

- [ ] ExerciseWorkbench 使用 Monaco Editor，支持 JS/Python/HTML 语法高亮
- [ ] 笔记抽屉关闭时不丢失未保存内容
- [ ] RUNNER_TIMEOUT 等关键错误显示友好中文提示和重试按钮
- [ ] App.tsx 行数降至 400 行以内
- [ ] Toast 通知在笔记保存、设置保存等场景正常展示
- [ ] `tsc --noEmit` 和 `vite build` 通过
- [ ] 现有功能（建档、学习、练习、复习、笔记、设置）不回归
