# Desktop 前端模块化

## 目标

在不改变 Desktop 行为、视觉结果、公开 API 契约和当前用户修改的前提下，消除 `api.ts`、`types.ts`、`styles.css` 与 `TutorConversationSurface.tsx` 的单体维护风险。

## 需求

1. 将 HTTP 基础 client、错误处理和各业务域 API 分离。
2. 将 Tutor、Learning、Review、Lesson、Cutover 等 contract 类型按领域拆分。
3. 保持现有 `./api` 与 `./types` 导入兼容，或一次性完整迁移并证明无遗漏。
4. 将全局样式拆成基础、shell、响应式和 feature-local 样式；继续复用 `ui/dsh-derived` tokens 与 CSS Modules。
5. 将 Tutor Conversation Surface 的数据控制、消息时间线、composer/action shelf 和辅助面板拆成窄组件或 hooks。
6. 不改变交互文案、SSE 协议、焦点/键盘行为、响应式断点或视觉语义，除非修复拆分引入的问题。

## 验收标准

- [x] 根级 `api.ts` 和 `types.ts` 不再承载跨领域实现，只作为小型兼容入口或被完全移除。
- [x] `styles.css` 不再承载全部 feature 样式，只保留有明确职责的入口/基础层。
- [x] `TutorConversationSurface.tsx` 不再同时拥有所有数据控制与主要 UI 子树。
- [x] 所有现有 Desktop 测试继续通过，测试数量不减少。
- [x] `tsc` 与 Vite production build 通过。
- [x] 当前用户已有前端改动被完整保留。

## 验证结果

- 基线与重构后均为 `9` 个 Vitest 文件、`60` 个测试通过。
- `pnpm --dir ./aearn desktop:check`：通过；Vite 从 86 个模块增加到 101 个领域模块，CSS 产物大小保持 174.48 kB。
- `api.ts`、`types.ts` 分别收敛为 1 行兼容入口；`styles.css` 为 8 行有序入口。
- API 拆为 client/core/tutor/learning/reviews，contracts 拆为 core/tutor/learning/review/lesson/planning，样式按原 cascade 顺序拆为 8 个职责文件。
- `TutorConversationSurface.tsx` 从 1113 行降至 633 行；UI 子树与纯 reducer/request model 分别进入 `TutorConversationParts.tsx` 和 `tutorConversationModel.ts`。
- Browser 插件真实检查 `http://127.0.0.1:1420`：页面标题 `Aearn`、API 在线、学习工作区非空、console error/warn 为 0。
- 桌面交互：左右面板按钮均唯一，折叠后 `aria-expanded=false`，grid 同时带 `roadmap-collapsed secondary-collapsed`，body/workspace 水平溢出均为 0。
- 390x844：仅一个 Composer、Tutor Surface 和 Lesson Page；点击“课程”后 `aria-pressed=true`，课程面板激活、Tutor 面板退出，水平溢出为 0。
- Browser 原生截图调用超时；按项目完成门仅对截图使用独立 Playwright fallback，截图保存在被忽略的 `.playwright-mcp/`，DOM/交互/console 证据仍来自 Browser。
- `git diff --check` 与 `git diff --cached --check`：通过。
