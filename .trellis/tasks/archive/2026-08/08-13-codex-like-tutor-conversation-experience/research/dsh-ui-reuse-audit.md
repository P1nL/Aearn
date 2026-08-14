# DeepSeek Harness UI 源码与可复用性审计

## 固定基线

- 上游仓库：`deepseek-ai/deepseek-harness`
- 固定 revision：`47f943859bef60e4160492346772ded9b24f765a`
- revision 时间：`2026-08-13T19:38:46+08:00`
- 本地只读 sparse checkout：`C:\Users\PINKING\AppData\Local\Temp\deepseek-harness-ui-reference`
- 审计目录：`apps/web`、`packages/client`、`packages/bundle/web-app`、`assets`
- 根仓库和 revision 中的 UI packages 标注 MIT；若复制 substantial source，必须保留版权与许可证声明。

## 总体架构事实

DSH Web UI 不是一个可独立嵌入的页面组件库，而是由大量 `@deepseek-ai/dsh-client-ui-*` package 组成的 Cordis/plugin/slot 应用：

- `ui-primitives`：纯 React 原语，源码注释与 README 明确声明 zero-Cordis；`src/index.ts:1-47` 导出按钮、输入、菜单、Modal、Tooltip、Toast、Disclosure、Markdown、图标和各类结果块。
- `ui-conversation`：完整会话壳、时间线、composer、Queue、状态和 slot 注册；peer dependency 涉及 Cordis、runtime、locale、settings、agent、tools 等大量 DSH package。
- `ui-user-questions`：Question Composer 与 Plan Review，但 package 仍依赖 DSH runtime/conversation/slots；内部 React 视图可拆出为 controlled component。
- `ui-layout`、`ui-sidebar`、`ui-theme`：页面壳和主题行为与 DSH runtime/slots 强耦合。

因此直接安装整个 DSH Web UI 会把 Aearn 的 REST/SSE/Zustand/Tauri 前端拉向另一套 plugin runtime，不符合“减少 UI 手搓但保留 Aearn 产品 authority”的目标。

## npm 直接依赖审计

截至本次审计，`next` dist-tag 指向 `0.1.0-rc.6`，而 `latest` 仍指向较早的 `0.0.1-rc.*`。三个重点包均为 RC。

最关键限制：`ui-primitives/tsdown.config.ts` 在发布 bundle 中把 CSS import stub 成空对象；`npm pack --dry-run @deepseek-ai/dsh-client-ui-primitives@0.1.0-rc.6` 只包含 `lib/*.js` 和类型/文档，没有 CSS modules 或 `src`。因此从 npm 直接 import 虽能得到 React 函数，却得不到其视觉样式；它不是 Aearn 可直接安装即用的 styled component library。

同时：

- DSH UI packages 声明 React 18；Aearn Desktop 使用 React 19。
- `ui-primitives` npm package 仍声明 Cordis/invariants peer，即使核心原语源码自身不导入 Cordis。
- `ui-conversation` / `ui-user-questions` 引入大量 DSH peer/dependency，直接安装会扩大 runtime、升级和安全维护面。

结论：**不推荐把 DSH UI packages 作为 Aearn 生产依赖直接接入。** 推荐从固定 MIT revision 选择性抽取源码/CSS，改成 Aearn-owned、React 19 验证过的薄组件层，并保留 NOTICE/来源映射。

## 复用矩阵

### A. 可直接抽取源码，改 token 名即可使用（低适配）

| DSH 对象 | 源码锚点 | Aearn 用途 | 结论 |
| --- | --- | --- | --- |
| `Button` | `ui-primitives/src/Button.tsx:18` | 统一当前 `tutor-primary/compact/text` 等按钮 | 直接抽取，改为 Aearn variants/tokens |
| `Pill` / `Input` | `ui-primitives/src/index.ts:10-11` | 状态标签、输入控件 | 直接抽取 |
| `StateDot` | `ui-primitives/src/StateDot.tsx:24` | run/process/queue 状态 | 直接抽取，增加 interrupted/idle 映射由 Aearn wrapper 完成 |
| `DisclosureRow` | `ui-primitives/src/DisclosureRow.tsx:33` | 替换 Tutor process/thinking 两套手写 disclosure | 高价值直接抽取 |
| Tooltip / Toast | `Tooltip.tsx:41`、`Toast.tsx:28` | 图标操作提示和短暂反馈 | 直接抽取 |
| 图标子集 | `ui-primitives/src/icons/index.tsx:11-872` | send/stop/queue/edit/delete/check/chevron/settings | 只复制实际使用的 SVG，排除 DeepSeek brand/fish |
| `MessageText` | `ui-primitives/src/index.ts:43` | learner 原文安全展示 | 直接抽取 |

### B. 抽取交互结构，改成 controlled Aearn component（中适配，最值得）

| DSH 对象 | 源码锚点 | 复用部分 | 不复用部分 |
| --- | --- | --- | --- |
| Queue Dock | `ui-conversation/.../QueueDock.tsx:31` | 单/多项折叠、编辑、删除、立即 steer、busy/action UX、composer 上方附着布局 | `useSession`、Cordis entry、DSH Queue contract |
| Question Composer | `ui-user-questions/.../QuestionComposer.tsx:60` | 分页问题、推荐标记、单/多选、自定义答案、skip、键盘/错误状态 | DSH pending/request types、remote call |
| Plan Review | `ui-user-questions/.../PlanReviewPanel.tsx:42` | 警告色带、滚动计划主体、讨论/拒绝/批准三操作 | DSH question answer/cancel contract |
| Reasoning Row | `ui-conversation/.../ReasoningRow.tsx:27` | 紧凑 disclosure 行、running summary 跟随 | **不复用 raw reasoning/Think 语义**；只用于 Aearn learner-safe process/public summary |
| Message Actions | `ui-conversation/.../MessageIconActions.tsx` | copy、时间、运行耗时、图标操作布局 | branch、TTFT/tps 等 Aearn 未授权产品语义 |
| Composer 外观 | `ui-conversation/.../InputBar.tsx:46`、`InputBar.module.css` | 22px 浮动 capsule、textarea + 底部 toolbar、send/stop 圆按钮、dock stack geometry | 808 行 draft/runtime/chip/command/model/access mode 逻辑 |

### C. 只复用视觉/布局原则，不复制组件实现（中高适配）

| DSH 对象 | 原因 | Aearn 映射 |
| --- | --- | --- |
| Theme tokens | token 表成熟，但带 `--dsw-*`/DeepSeek blue/深浅主题假设 | 机械映射成 `--aearn-*` semantic tokens，保留 Aearn 绿色品牌 |
| AppFrame | DSH runtime/slots/SessionProvider 强耦合 | 借用三栏 CSS、resize/concession、reduced-motion；Aearn 自有 React shell |
| Sidebar | DSH session/workspace/slot 强耦合 | 借用 56px rail、折叠动画、固定 settings、搜索行结构 |
| Chat shell | 数据和节点 registry 深耦合 | 借用 timeline 宽度、sticky composer、gutter/scroll contract、message/tail spacing |

### D. 不应复用

- `FishLogo`、`BrandWordmark`、DeepSeek 品牌色和产品文案。
- Terminal/Diff/Search/Web coding-specific cards，除非 Aearn 后续真的有对应 learner-safe authority；当前任务不是 coding workspace UI。
- raw `ReasoningRow` 内容来源；Aearn 保留 `Think` 标签与 UI 形态，但数据只能来自服务端安全校验的 `public_thinking_steps[]`。
- 整个 `ui-conversation`、`ui-layout`、`ui-sidebar` package 依赖链。
- DSH model selector、permission mode、command menu、workspace/session hierarchy 的业务语义。

## 可复用的测试资产

DSH 的 Web E2E/accessibility snapshots 比页面代码本身更容易复用为验收蓝图：

- `apps/web/tests/queue-actions.e2e.ts`：Queue 编辑/删除/Steer 和 collapsed layout。
- `question-composer.e2e.ts`：question composer 的 checkbox/radio/custom/skip/pager。
- `plan-review.e2e.ts`：讨论/拒绝/批准。
- `chat-scroll-contract.e2e.ts`、`composer-draft-scroll.e2e.ts`、`conversation-column-overflow.e2e.ts`：composer/scroll geometry。
- `live-interactions.e2e.ts`、`turn-tail-actions.e2e.ts`：running/stop/retry/tail actions。
- `sidebar-scrollbar.e2e.ts`、`lifecycle-chrome.e2e.ts`：sidebar rail 和空会话 hero。

Aearn 应重写数据 fixture 和断言文案，但沿用这些交互矩阵，减少自行遗漏边界。

## 初步推荐

采用“**Aearn-owned DSH-derived UI kit**”：

1. 在 Aearn 建立小型 UI foundation，不引入 Cordis。
2. 从固定 revision 抽取 8-12 个低耦合原语、所需图标和 semantic token 结构。
3. 对 Queue、Question Composer、Plan Review、Think disclosure 编写 Aearn controlled wrappers。
4. 只借鉴 Composer/AppFrame/Sidebar 的 CSS geometry，不搬 runtime。
5. 每个 derived 文件保留来源 revision 与 MIT NOTICE；建立 upstream mapping，后续升级按 diff 审核而非自动漂移。

该方案比继续在 187KB 单体 `styles.css` 中手写每个交互更省工，也比安装整个 DSH UI 依赖更稳定。


## 决策后补充：Stop、Queue 与 Aearn 取消能力

- DSH `InputBar.tsx:758-792` 在 `interruptible` 时显示方形 stop，或让 primary action 从 send 切换为 stop。
- DSH `apps/web/tests/live-interactions.e2e.ts:143-154` 证明 stop 产生 `aborted` turn end，并恢复 Composer。
- DSH `apps/web/tests/queue-actions.e2e.ts:153-178` 证明 stop 后 Queue 保留且不自动消费；下一次正常发送追加到队尾并按 FIFO 唤醒旧 Queue。
- Aearn `persistence.py:1522-1573` 已有事务化 `request_cancellation()`，会写 cancelled terminal event、释放 lease 并冻结 public process。
- Aearn `run_loop.py:493-500` 在安全边界检查 cancelled/superseded；当前公开 routes 只有 run input/read/events，没有 run cancel endpoint。
- Aearn 当前 public Tutor message 是完整受控 decision 的持久化结果，没有 learner-facing raw partial stream；因此只复用 stop UI/队列语义，不暴露未校验 provider partial。

## 决策后补充：最终复用边界

- 用户确认完整复用选定 Tutor UI，但替换品牌身份；不是把 DSH 整个 AppFrame/runtime 搬入 Aearn。
- 首轮主题为白色浅色，Aearn 绿色集中在 brand/focus/selection/primary action token。
- 计划审核继续位于 Aearn 右侧浮动检查器，内部复用 DSH `PlanReviewPanel`。
- required `clarification` / `planning_input` 完全接管 Composer，无 skip/close。
- Desktop 只显示 message-level `Think`，服务端 `TutorPublicProcess` authority 保留但不渲染。
- Queue 为服务端持久化 FIFO；stop 只取消当前 run，Queue 保留并暂停，下一次发送唤醒。
