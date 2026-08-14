# 集成 DSH Tutor 对话 UI

## 目标

在 Child 1-3 的 authority 和组件基础上，将 Aearn Tutor Desktop 会话近像素迁移为选定 DSH UI：白色浅色 Composer、QueueDock、QuestionComposer、Think disclosure 和 PlanReviewPanel 内部结构，替换品牌身份并完成正式文档、组件测试和真实浏览器验收。

## 依赖

- **必须完成并通过验证：**
  - `08-13-dsh-derived-ui-foundation`
  - `08-13-tutor-controlled-pending-inputs`
  - `08-13-tutor-persistent-queue-stop`
- 实施前必须再次检查 `E:\codee\Aearn` 原始工作树的 `api.ts`、`types.ts`、`TutorConversationSurface.tsx` 和 prompts diff，确认前三个 child 已保留重叠语义。
- 本 child 是父任务最后一个实现 child；完成后回到 parent 做全量集成复核。

## 范围内

- `TutorConversationSurface` orchestration 拆分和 controlled components 集成。
- DSH capsule Composer、QueueDock、QuestionComposer、ReasoningRow/Think 和 PlanReviewPanel 内部视觉/交互。
- 默认 Queue delivery、send/stop primary action、busy/error/reconnect state。
- required Typed Question 完全接管 Composer，无 skip/close。
- message-level Think only，process timeline renderer 移除但后端 authority 保留。
- 右侧浮动 plan inspector 继续存在，内部使用 DSH review card 结构。
- CSS modules 迁移、Aearn 品牌文案、1440/900/390 响应式和 reduced-motion。
- Desktop component tests、浏览器 smoke、六份正式 source-of-truth 文档最终 reconciliation。

## 范围外

- 修改 Child 1-3 已稳定的后端 authority，除非发现 contract bug 并先回到 owning child 处理。
- 全局 AppFrame/Sidebar/Settings 和非 Tutor 页面重做。
- dark/system theme、model/access/command controls、terminal/diff/coding cards。
- raw reasoning、raw trace、provider partial、hidden tests/rubric。
- optional question skip/close、Queue reorder/clear、message branch/retry。

## 需求

1. 普通空闲 Composer 使用 DSH 22px capsule、textarea + bottom toolbar、圆形 primary action 和 sticky geometry；Aearn 文案/Logo/绿色 token。
2. active cancellable run 时 primary action 从 send 切换为方形 stop；`awaiting_effect_commit` 与 Typed Question 不显示误导 stop。
3. active run 普通输入默认 Queue；QueueDock 由服务端 snapshot 渲染，支持单项直显、多项折叠、edit/delete/Steer 和 busy/error。
4. pending `clarification`/`planning_input` 由 QuestionComposer 完全接管 Composer seat；移除现有 continuation 提示卡和“改为普通消息”入口。
5. required questions 保留 radio/checkbox/custom/pager/recommendation/keyboard/IME/error，隐藏 skip/close。
6. `Think` 只在 Tutor message `public_thinking_steps[]` 非空时显示，标题固定英文 `Think`；legacy 空数组不合成。
7. process timeline item 在 renderer 中忽略，不显示“公开处理过程”、steps、duration 或 terminal card；type/parser 可为兼容继续保留。
8. 右侧计划草案窗口不挤压主列，支持收起/重开/new-draft auto-open；内部使用 DSH strip/body/footer/actions，正文渲染 typed plan，不用任意 Markdown authority。
9. 1440/900/390 无横向溢出；390 使用底部浮动 plan inspector，Queue/Question/stop target 可触达。
10. visible focus、aria、IME、Enter/Shift+Enter、Escape edit、reduced-motion 和 screen-reader status 完整。
11. 全局旧 CSS 只在确认无引用后窄范围删除；其他页面视觉不得意外改变。
12. 正式 docs 与实际 UI/API 保持一致，不再描述 Desktop process row 或普通输入始终 fresh run。

## 验收标准

- [ ] 首轮 Tutor 主背景/Composer/浮层为白色浅色，Aearn 绿色仅在 token 规定状态使用。
- [ ] DeepSeek 品牌名称、logo 和产品文案不出现在运行 UI；NOTICE/upstream 归属除外。
- [ ] ordinary send、enqueue、edit/delete/Steer、completed drain、stop pause、next-send wake 可从 UI 完成并恢复。
- [ ] stop 成功后 current run cancelled，Queue 数量/顺序不变，Composer 恢复；UI 不宣称 provider 硬中断。
- [ ] clarification/planning_input takeover 无双 Composer、无 skip/close、structured answer 正确提交。
- [ ] Think-only 与 process-hidden 行为对新旧 history 一致，无 raw reasoning/trace/partial 泄漏。
- [ ] plan inspector 的讨论/批准/取消规划行为保持 Aearn 原 flow。
- [ ] component tests 覆盖 Queue、Question、Think、Composer、Plan 和 keyboard/IME。
- [ ] 1440/900/390 + reduced motion 浏览器 smoke 无 overflow、console error/warning 或 error overlay。
- [ ] Desktop build、后端回归、docs acceptance、Trellis validate 和 diff hygiene 通过。

## 风险

- `TutorConversationSurface` 当前承担过多状态；必须先拆 controlled components，再替换视觉，避免一次性 JSX/CSS 重写。
- 原始 dirty worktree 与本 child 高度重叠，需逐文件核对。
- DSH 原实现含 Markdown/runtime assumptions；Aearn 只能复用视觉，不得引入任意 Markdown authority 或 DSH session state。
