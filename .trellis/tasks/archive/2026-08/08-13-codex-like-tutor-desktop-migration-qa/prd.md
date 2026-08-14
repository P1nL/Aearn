# 类 Codex Tutor Desktop 与集成迁移验收

## 目标

消费已冻结的 v2 thread/turn/item/event/control contract，构建接近 Codex 的 Tutor 对话体验：稳定 message timeline、message-level `Think`、running 默认 Queue、显式 Steer、Stop、Retry、typed request response、刷新/断线恢复，并完成 DSH-derived UI、旧 Desktop contract 的有界迁移、浏览器/集成 QA 和 source-of-truth 文档收口。

## 依赖与范围

- 依赖 `08-13-tutor-thread-turn-item-event-foundation`、`08-14-dsh-derived-ui-foundation`、`08-14-tutor-typed-request-authority-turns`、`08-13-tutor-queue-steer-interrupt-control` 与 `08-14-tutor-thread-turn-v2-global-cutover` 完成并归档。
- 本 child 不重新定义后端状态机；发现 contract 缺口时回到 owning child/父任务。
- 受保护原型 `docs/design/learning-agent-claude-desktop-framework.html` 不删除、不替换。

## 需求

### R1：快照与会话事件流

- 新 hook 先加载 snapshot，再按 cursor 订阅 conversation SSE；切换 conversation 时取消旧 fetch/EventSource。
- reducer 按 sequence/stable item ID 去重，cursor invalid/version mismatch 时重新 snapshot。
- UI 不再依赖 run-local SSE 推断 Queue、pending request 或 active turn。

### R2：时间线与公开 Think

- timeline 主体只渲染 learner/tutor message、typed request 与 learner-safe error；新 Desktop 不渲染独立 process row。
- Tutor message 仅在 `public_thinking_steps[]` 非空时显示 DSH-derived、可折叠 `Think`；内容不得来自 raw reasoning、trace 或 run-level process steps。
- 服务端 `TutorPublicProcess` authority、parser 和兼容 history projection 继续保留；Desktop 遇到 process item 时忽略显示但保持 cursor/item 处理稳定。
- 历史恢复后 message/request 顺序、Think 展开状态和滚动锚点稳定；legacy message 缺少 `public_thinking_steps[]` 时不合成内容。

### R3：输入区与 Queue

- idle Send 创建 fresh turn；running Send 默认 Queue，并明确提示。
- Queue 显示在 composer 上方并展示服务端投影的 `n/10` 容量，支持编辑、键盘上移/下移、删除、Steer 和立即执行；不能拖拽-only，也不能由前端自行扩大容量。Steer 明确提示共享当前预算，立即执行明确提示会中断当前 turn并启动 fresh turn。
- Steer 为显式次级动作，提交前显示“将影响当前处理”；后端拒绝时不自动 Queue。
- pending typed request 时 Required Typed Question 完全接管 Composer seat，不显示普通 Composer、QueueDock、skip 或 close；现有 Queue 保留但不可在该状态下执行控制 mutation。

### R4：停止、重试与错误

- running 有明确 Stop；点击后 optimistic 状态仅显示“正在停止”，最终以 server event 为准。
- recoverable failed turn 显示 Retry；Retry 返回新 turn 并保留原错误/lineage。
- learner-safe error card 按 code 提供对应 action，不统一显示 `TUTOR_RUN_UNAVAILABLE`。

### R5：DSH-derived 视觉与计划检查器

- 选定 Tutor surfaces 近像素派生固定 DSH MIT revision 的 React/CSS 结构，但全部可见品牌、文案和 semantic tokens 归属 Aearn。
- 首轮只交付白色浅色主题；Aearn 绿色用于品牌、focus、selection、primary action 与 positive state，不引入 dark/system theme。
- 计划草案保持右侧浮动 inspector，不挤压对话主列；内部派生 DSH PlanReviewPanel，窄屏使用受限高度底部浮层。
- Required Question、Queue、Composer、Think 和 Plan components 只能接受 Aearn typed props/actions，不读取 DSH runtime/session。

### R6：迁移与验收

- 新 Desktop 不调用 `/runs/{run_id}/inputs`；v2 cutover 后旧 continuation write 对所有 run 已禁用，前端不得保留可触达 caller、继续按钮或自动重试。
- 后端 gate 不可用时显示明确 unavailable/read-only，不静默回退到旧预算 merge。
- legacy waiting run 被 cutover 终结后，timeline 保留旧问题/消息并显示 `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN` 迁移卡；卡片不提交目标回答、approval 或 authority action，只引导用户在普通 Composer 中开启 fresh v2 turn。
- cutover 取消的 active legacy run 与用户 Stop 一样渲染普通 `interrupted`，不显示专用迁移卡或系统升级错误，不自动 Retry或创建turn；内部 `legacy_protocol_cutover` 不进入公开UI。
- Desktop 只支持单一全局 v2 capability 状态；gate-off 显示 unavailable/read-only，不按 user 或 conversation 选择 v1/v2 renderer、mutation 或 SSE 路径。
- 完成 desktop build、类型、browser/Tauri flow、窄屏、键盘、reduced-motion、SSE reconnect 和离线 Queue 自动执行验收。
- 同步 frontend/API/database/runtime/acceptance source-of-truth。

## 验收标准

- [ ] running 主 Send 明确进入 Queue；三条 Queue 可编辑、键盘重排、删除、Steer、立即执行，刷新后一致；Steer 保持当前 turn，立即执行产生 fresh turn。
- [ ] Steer、Stop、Retry、request answer 均使用独立 API，stale conflict 不导致 UI 假成功或隐式 Queue。
- [ ] Desktop 关闭后 Queue 仍由服务端自动执行；重新打开能恢复 active turn/Queue/timeline。
- [ ] typed clarification/planning/approval UI 精确绑定 item，回答后看到 fresh turn。
- [ ] SSE 断线、重复事件、cursor reset、conversation switch 不重复 item、不串流。
- [ ] `Think` disclosure 键盘可达、`aria-expanded` 正确、reduced-motion 生效；独立 process item 不渲染但不破坏 cursor/history，composer 在窄屏仍可见。
- [ ] 没有 raw hidden reasoning/provider/prompt/diagnostic/secret 出现在 UI 或前端日志。
- [ ] 旧 continuation write caller 不再可触达；对旧 endpoint 的 `410 Gone` 响应不会被 UI 解释为可重试 continuation，legacy history/run/SSE 仍可只读展示。
- [ ] cutover 终结的 legacy waiting run 显示可恢复迁移卡且不提供旧回答/批准入口；用户后续普通 Send 创建 fresh v2 turn，不与旧 run 共享预算或 request identity。
- [ ] cutover 取消的 active legacy run 与用户 Stop 使用同一 `interrupted` timeline/control UI，无专用卡片、无自动Retry/turn创建；waiting migration card仍保持独立。
- [ ] Desktop 不包含 per-user/per-conversation protocol selector；全局 gate-off 时所有写操作不可用，gate-on 后统一使用 snapshot + conversation SSE + v2 mutations。
- [ ] `pnpm desktop:check`、相关后端集成测试、browser smoke、docs link/contract 检查通过。

## 范围外

- 复制 Codex 品牌或像素 UI。
- 删除受保护原型或大规模重做非 Tutor 页面。
- 物理移除 legacy API/SSE/data。

