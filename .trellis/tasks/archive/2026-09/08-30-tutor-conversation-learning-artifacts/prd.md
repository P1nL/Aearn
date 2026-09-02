# Tutor 对话式学习工件平台

## Goal

在现有 Aearn Tutor Harness、TeachingSession、Lesson/Gate/Review、Conversation Snapshot/SSE 和 Desktop 工作区之上，建立一套服务器权威、可恢复、安全且全部呈现在 Tutor 对话流中的学习工件平台，使模型只有在 UI 确实提供可操作工件时才能要求用户编辑、运行、回答、审查、查询或交互。

## User Value

- Tutor 不再给出“修改代码、运行页面、执行 SQL”等用户无法在当前界面完成的指令。
- 用户在同一对话流内完成学习任务，不需要离开会话或寻找外部工具。
- 实时预览、权威运行、结构化检查、提示、审查、SQL 和来源文档形成可恢复的完整教学闭环。
- 题目、评分、答案、提示和发布经过确定性验证及风险分级审核，避免在线模型临时生成不可评分或不安全内容。

## Background and Confirmed Facts

- 当前公共 item union 没有 artifact，snapshot 版本为 v3；证据见 `research/repository-evidence.md`。
- 当前 Teaching response mode 只有 none/composer，artifact target 仅为未实现的预留值。
- 当前 Lesson Gate、Review、Attempt、Runner、TeachingSession 和 context reference 已有业务 authority；新工件必须复用而非复制。
- 当前 Desktop 已具备 Monaco 依赖，但没有 Tutor inline artifact renderer；Tauri 主窗口 CSP 仍为空。
- 当前 public execution 不能声称 container-verified；实时 Browser Preview 必须明确为本地非权威体验。

## Requirements

### R1：统一 Learning Artifact 公共协议

- 新增严格、版本化、extra-forbid 的 `TutorPublicArtifactItem`，并加入 TutorPublicItem 与 item reference union。
- Artifact 必须包含稳定 identity、owner、purpose、kind、version、state、presentation、allowed actions、safe source refs、active attempt summary 和时间字段。
- Presentation 使用封闭 discriminated union，前端不得根据模型给出的组件名、URL、HTML 或脚本动态装载 UI。
- 公共投影不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器、密钥或隐藏 SQL 数据。

### R2：Artifact 生命周期和业务归属

- 支持 pending、ready、active、running、completed、failed、cancelled、superseded 等受控状态；非法逆向转换被服务和数据库拒绝。
- Artifact 只作为交互和投影 facade；Lesson Gate、Review、Attempt、TeachingSession、mastery/progress 仍是原业务 authority。
- 每个 conversation/TeachingSession 至多一个前台阻塞交互工件；历史结果和演示可以只读保留。
- 所有 action 携带 client action ID、expected artifact version 和用户/track/conversation/session scope。

### R3：对话流 UI

- Artifact 直接作为 Tutor 时间线 item 渲染，不创建另一个中央工作区，不占用右侧文档区。
- 普通聊天与 Artifact 视觉明显区分；Artifact 只保留标题、一句任务、必要状态、内容和主动作。
- 新工件自动展开并滚动到自身位置，键盘焦点保持原控件。
- 完成工件保持展开直到用户发送下一条消息；程序关闭前保留 UI state，重新打开会话时按需从服务器重新加载。
- 宽屏/窄屏和 reduced-motion 行为满足已确认决策。

### R4：安全 Markdown

- Tutor message、任务说明、评价、Hint、错误和引用摘录支持安全 Markdown 与流式增量渲染。
- 支持代码块、表格、列表、引用、链接、复制、语法高亮，以及受控字号/颜色扩展。
- 禁止 raw HTML/script/style 执行；字号、颜色、URL 和对比度必须校验。
- Markdown 不能成为动态 Artifact 组件或任意 HTML 的加载机制。

### R5：代码编辑与实时 Browser Preview

- 单文件 Monaco 编辑器，宽屏与 Preview 固定 50:50，窄屏上下排列，不允许拖动比例。
- 编辑后经过短防抖实时更新隔离 Preview；Preview 不创建 Attempt、不推进 Gate/mastery。
- Preview 运行在无 Tauri IPC/网络/导航/下载/弹窗/表单权限的隔离 host 中；卡死可销毁重建且不影响主应用。
- 只有用户点击 Run 才创建权威 Attempt；全部通过直接完成，无第二次 Submit。

### R6：Tutor 评价和测试结果工件

- 每次 Run 终态后创建新的 Tutor 主线 Turn：Markdown 评价 + 服务端权威 test-result artifact。
- 测试结果显示总结果、通过计数、失败项、必要错误位置、按需 stdout/stderr、SQL grid 和返回修改。
- 失败时原编辑工件继续 active；通过时原工件 completed 并保持展开到下一条用户消息。
- 模型不能更改权威通过/失败、测试数量或 SQL 数据结果。

### R7：演示工件

- 演示代码只读；交互演示允许操作受控 Preview，但不能修改源码。
- Interactive demonstration 仅由 exact expected event 完成。
- Static demonstration 仅累计有效可见时间，底部显示细进度动画，结束后触发低优先级 continuation intent。
- 用户消息优先于计时继续；模型不能跳过步骤、设置时间或将演示当作 mastery evidence。

### R8：结构化理解检查、难度和补救

- 支持单选、多选、预测、排序、代码范围和短文本等封闭题型。
- 回答后原工件不可修改；服务端评分，Tutor 新 Turn 输出评价与结果。
- D1-D5 基础难度由课程或服务端规则确定，UI 角落显示低存在感 `D(n)`。
- 答错后生成 immutable successor remediation；同知识点最多原题 + 一次补救，之后明确讲解并做不同上下文迁移检查。
- Assistance/disclosure 规则按已确认策略执行。

### R9：Overlay 多级提示

- H1/H2/H3 提示在提示按钮锚定的 overlay popover 中，不改变 Artifact 布局或对话高度。
- 提示在同一小窗中手动横向分页，不自动轮播；第一次查看新页才记录 receipt。
- 关闭后可重开已解锁提示；完成工件不再解锁新提示。
- Direct answer 不作为普通提示页，必须由披露策略授权。

### R10：AI 代码审查

- Review v2 支持 code/diff、稳定 hash/hunk/line mapping 和结构化 finding。
- 第一版评分只覆盖可验证的 AI 常见错误；主观可读性/风格仅作非评分 Tutor 建议。
- 用户 finding 至少含代码范围、错误类别和简短说明；完成后锁定并由新 Tutor Turn 反馈。
- 复用现有 model review authoring/publication/private rubric authority，保留 v1 历史读取。

### R11：SQL Workspace

- 宽屏 Editor/Schema 固定左右分屏，窄屏上下；公开 query result 放在原工件底部。
- SQL 只由显式 Run 执行；公开结果与隐藏评分数据严格分离。
- Schema 显示表、列、类型、PK/FK 和关系；名称可复制但不自动插入编辑器。
- 只允许受控只读查询；表格有列/行/单元格/总 payload 上限。

### R12：来源与文档抽屉

- 引用绑定 exact document/version/block/hash；点击后打开右侧文档栏、滚动到目标并播放无 reflow 的虚线框动画。
- 窄屏文档抽屉从右覆盖对话区大部分，只由收起按钮或 Escape 关闭；点击外部不关闭。
- 文档滚动与对话滚动隔离；关闭后恢复来源触发点焦点和原对话位置。

### R13：答疑支线与 Turn 优先级

- 等待交互时 Composer 始终可用；普通消息进入锚定工件的单层临时支线。
- 用户消息保持右对齐，Tutor 保持左对齐，分支线统一包裹；不嵌套，不创建第二交互工件。
- 主线动作恢复后支线折叠为“答疑 · N 轮”；可重新展开。
- 无关问题也先回答再引导返回主线；明确取消/跳过/切换主题走教学控制。
- 优先级固定为用户消息 > 显式工件动作 > 交互完成 > 静态计时 > 后台推进；同 conversation 同时只有一个可发布 Tutor Turn。

### R14：Learning Item Bank 与代理审核

- 建立 immutable、versioned Learning Item Bank，公私内容分离，包含知识点、目的、难度、题型、runtime、rubric/test、Hint、remediation、source 和发布状态。
- 生产流程为 blueprint -> draft -> machine verified -> agent reviewed -> pilot -> published/retired。
- 生成代理不能审核自己的题；教学、难度、技术、歧义、安全、对抗角色独立输出结构化报告。
- 确定性失败、答案不唯一、安全/泄漏和 rubric 错配一票阻断。
- 低/中/高风险按已确认策略自动晋级或人工批准；在线 Tutor 只能从已发布候选中选择 handle。

### R15：Snapshot/SSE、兼容和恢复

- 发布新 snapshot version，保留旧客户端读取兼容；Artifact/Branch 使用 item_added/item_updated 与 snapshot recovery，不扩散临时事件种类。
- SSE event 只传稳定 item reference 和安全小 payload；完整代码、结果表和私有内容通过 scoped API/snapshot detail 获取。
- duplicate、gap、cursor invalid、stale version、reconnect 和程序重开均可恢复。
- Skill 发布新 immutable version；旧 teaching Skill、snapshot 和 model-review v1 保留历史兼容。

### R16：安全、回滚和文档

- 功能开关关闭时，模型不能选择 artifact response mode，也不能输出不可执行指令。
- Browser Preview、Markdown、SQL、item bank、public result 和 source drawer 必须有专门的滥用/泄漏测试。
- 新表纳入 bootstrap manifest、cutover exhaustive inventory、export/reset/delete 分类和 append-only/CAS 约束。
- 同步更新 `docs/README.md` 指定的 source-of-truth；不恢复历史 Generative UI runtime，不删除受保护原型。

## Acceptance Criteria

- [x] AC1：截图所示 HTML 教学可在单一对话流中完成任务、编辑、实时预览、显式运行、结果评价和继续教学。
- [x] AC2：任何 edit/run/query/review 指令没有合法 published Artifact handle 时被 decision gate 拒绝，用户看不到不可执行消息。
- [x] AC3：TutorPublicItem、snapshot、SSE、API、Desktop parser 对 artifact/branch union exact 对齐并拒绝未知/extra 字段。
- [x] AC4：断线、重复事件、gap、cursor invalid、重新打开会话均恢复同一 Artifact/Branch/Attempt 权威状态。
- [x] AC5：模型消息安全渲染 Markdown 与受控字号/颜色，raw HTML/script/style/不安全 URL 不进入 DOM。
- [x] AC6：Monaco 与隔离 Preview 实时联动；Preview 卡死、导航、网络、popup、下载、表单和 Tauri IPC 攻击不影响主应用。
- [x] AC7：Run 仅由用户触发；通过直接完成，失败保持可编辑；模型不能伪造结果。
- [x] AC8：运行终态产生新的 Tutor 评价和 test-result artifact，失败项优先且隐藏测试不泄漏。
- [x] AC9：完成工件保持展开至下一条用户消息，程序关闭后重新进入会话按需加载权威内容。
- [x] AC10：静态/交互演示按 exact 时间或事件完成，用户消息抢占自动继续且无重复 Turn。
- [x] AC11：结构化回答 immutable；错误补救、答案披露、迁移检查和 D(n) 规则按策略执行。
- [x] AC12：Hint overlay 不改变 Artifact 布局，手动横向分页且 assistance receipt exactly-once。
- [x] AC13：AI code review v2 可定位 diff finding，并只以可验证问题决定结果。
- [x] AC14：SQL Schema/Editor/Result 布局、复制、只读执行、公开/隐藏数据隔离和 table bounds 通过。
- [x] AC15：来源抽屉 exact 定位并播放虚线框动画；窄屏覆盖、收起、焦点与滚动恢复正确。
- [x] AC16：等待工件期间普通/无关消息进入单层支线；主线恢复后折叠，结果 Turn 回到主线。
- [x] AC17：Learning Item draft 未通过机器/代理/风险门不得进入在线候选；审核报告绑定 exact content hash。
- [x] AC18：新 user-owned/shared 表全部进入 cutover inventory 与 reset/export 分类，bootstrap 连续两次成功。
- [x] AC19：1440x900、900x900、390x844 无页面级水平溢出，键盘可操作，reduced motion 和屏幕阅读器语义正确。
- [x] AC20：API 串行测试、Ruff、Mypy、lock、executor tests、Desktop tests/check、Tauri cargo check、安全 smoke、Trellis validate 与 diff hygiene 全部通过。

## Out of Scope

- 多文件项目树、完整 IDE、终端、shell、包管理器、用户本机文件访问。
- 服务器草稿历史、跨设备未运行草稿恢复、Artifact 历史版本浏览。
- 任意模型生成 React/HTML host、任意网页 URL、开放网络 Preview。
- A3a 确定性伪预览、独立大型成绩/证据 dashboard、进度卡和复杂模拟器。
- 生产容器镜像构建/签名/发布、真实 provider smoke、部署、push 或生产数据迁移，除非另行批准。

## Child Task Map

1. `08-30-artifact-authority-conversation-protocol`：Artifact DB/API/public item/snapshot/SSE authority。
2. `08-30-teaching-orchestration-branch-scheduling`：Teaching v3、impossible-instruction gate、branch/priority arbiter。
3. `08-30-inline-artifact-shell-markdown`：对话内 Artifact shell、安全 Markdown、支线 UI。
4. `08-30-code-editor-browser-preview`：Monaco 与隔离实时 Preview。
5. `08-30-execution-results-runtime-presentation`：Safe result v2、Tutor 评价和 test-result artifact。
6. `08-30-teaching-demonstration-artifacts`：静态/交互演示。
7. `08-30-knowledge-checks-hints-remediation`：检查、难度、Hint、补救和迁移。
8. `08-30-ai-code-review-artifact`：AI 代码审查 v2。
9. `08-30-sql-learning-workspace`：SQL workspace/table result。
10. `08-30-source-references-document-drawer`：来源引用和右侧文档抽屉。
11. `08-30-learning-item-bank-agent-review`：题库、验证、代理审核和发布。
12. `08-30-artifact-integration-qa-rollout`：最终集成、QA、迁移、文档和回滚。

## Open Questions

无阻塞产品问题。任何后续物质性范围变更必须更新本 PRD、相关 child artifact，并重新进行最终规划审阅。
