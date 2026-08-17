# Tutor 公开思考文本实时流式输出

## 目标与用户价值

让学习者在 Tutor 处理当前 Turn 时，不再长时间只看到静态“正在思考”占位，而是从用户消息进入时间线后立即看到 `● Think`。模型专门为学习者生成的公开思考文本按真实 provider 进度进入 provisional buffer；只有 validated `complete` 与首文本 `350ms` 稳定窗口同时满足后才逐字出现。正式回答输出完成后，`Think` 自动折叠一次，用户仍可重新展开查看。

该能力只展示 learner-safe 公开文本，不读取、转发或持久化 provider-native `reasoning`、`reasoning_content`、hidden chain-of-thought、prompt、原始事件或诊断内容。

## 背景与已确认事实

- 当前 Responses 调用已使用 `stream=true`，但 `OpenAICompatibleClient` 只在服务端累积 `response.output_text.delta`，等完整响应完成后才返回严格 JSON。
- 当前 Tutor provider contract 将回答 `text` 与 `public_thinking_steps[]` 放在同一个 `agent_message` 中；gateway 等完整 JSON 解析、schema 校验和教学安全校验完成后，run loop 才原子持久化消息。
- 当前 conversation SSE 只发送已持久化的 learner-safe conversation event；Desktop 收到事件后重新读取权威 snapshot，不消费 provider 文本 delta。
- 当前 Desktop 未渲染 process item；成功 Tutor message 上的 `public_thinking_steps[]` 使用编号列表式 `Think` disclosure。工作树中已有未提交的运行占位、布局修复、测试和文档修改，实施时必须逐文件保留并融合，不能覆盖或撤销。
- 旧 Tutor history 可能只有 `public_thinking_steps[]`，新契约必须给出只读兼容投影，不能删除历史消息。

## 已确认产品决策

1. 用户消息进入时间线后立即显示 `● Think`，不显示“Tutor 正在思考”或其他说明文案。
2. 后端尚未产生可展示文本时，`Think` 不可展开，隐藏展开按钮，整行不表现为可点击控件。
3. `turn_output append` 与 incomplete snapshot 只进入前端 provisional buffer；仅在同 generation 的 validated `complete` 与首文本 `350ms` 稳定窗口同时满足后，显示展开按钮、默认展开并开始逐字揭示。
4. 思考内容是模型自行排版的一段公开纯文本；前端不编号、不排序、不拆分步骤，保留换行、段落、标点和空白。
5. 前端按真实 provider 流接收并缓冲内容；通过完整性门后，字符队列稳定地逐字显示真实累计文本，不能从最终回答反推或伪造公开思考。
6. 正式回答以成功持久化 message 为权威并由前端逐字揭示；揭示期间 `Think` 保持展开，字符队列完成后自动折叠一次，之后允许用户手动重新展开或折叠。
7. `Think` 区域除状态圆点、固定标题 `Think`、有文本后出现的展开按钮和模型输出文本外，不显示任何说明性文字、数量、时长或状态标签。
8. Turn 停止、失败、被取代、进入 repair 或流重置时，临时文本不得与后续尝试混合；未形成正式成功结果的临时内容不进入持久化历史。
9. 成功后临时内容必须与最终持久化 `Think + 回答` 原位衔接，snapshot 刷新不得重复、回退或闪烁。
10. 不公开 provider 原始 reasoning；实时内容必须来自明确的公开输出字段并经过 learner-safe 边界处理。

## 范围内

- 将新 Tutor provider 输出中的公开思考从固定步骤数组升级为保留模型排版的文本字段，并定义旧 history 兼容投影。
- 在 provider stream 解析、Tutor gateway、run lifecycle 与 conversation event/snapshot 之间建立有界的公开思考临时流；正式回答保持 authority-first。
- 定义流式 attempt、Turn、revision、sequence、repair、interrupt、supersede 和 reconnect 边界，避免 stale delta 泄漏到新尝试。
- Desktop `Think` 的空态禁用、provisional 文本离 DOM、validated `complete` + `350ms` 后自动展开、逐字队列、回答完成自动折叠、手动重开、reduced-motion 和无辅助文案交互。
- 更新数据库/API/SSE/Desktop 类型、自动化测试和 source-of-truth 文档。
- 融合当前工作树已有的运行占位和高度修复，不覆盖用户修改。

## 范围外

- 展示或存储 raw chain-of-thought、provider `reasoning`、`reasoning_content`、prompt、raw SSE、trace 或内部诊断。
- 将任意 HTML 作为模型排版执行，或新增通用 Markdown/HTML authority。
- 改变 Queue、Steer、Interrupt、Retry、typed request、global cutover 或 capability/effect 权威语义。
- 更换 provider、模型或 Tutor 预算策略。
- 生产部署、生产迁移、Git 提交或推送。

## 功能需求

### R1：运行中 `Think` 状态

- accepted learner message 出现在时间线后，同一 active Turn 立即追加一个非持久化 `Think` 行。
- 无文本时只显示运行状态圆点和 `Think`；没有 chevron、button、helper copy 或空正文。
- active Turn 消失但没有成功 Tutor message 时，空 `Think` 必须移除，由已有 learner-safe error/interrupted UI 接管。

### R2：公开思考文本流

- provider contract 提供单一公开思考文本语义，不要求列表、固定句式或编号。
- 后端只把公开字段中的完整、安全片段发布到 conversation scope；raw reasoning 永不进入该路径。
- 每个 delta 必须关联 conversation、Turn、input revision、provider attempt 和单调流序列；stale、repair 前一 attempt、interrupt 或 superseded delta fail closed。
- Desktop 按序去重并把 append/incomplete snapshot 仅存入 provisional buffer；只有同 generation 的 validated `complete` 与 `350ms` 稳定窗口同时满足后，字符队列才开始逐字揭示，模型换行和空白保持原样。

### R3：权威回答揭示与完成边界

- 正式回答不能在 decision gate、capability/effect、stale revision 与 terminal persistence 之前公开；它只来自成功持久化 message 的权威 snapshot。
- 对刚从 active Turn 转为成功 message 的回答，Desktop 使用独立字符队列逐字揭示；历史消息和刷新后恢复的已完成消息不重放动画。
- 回答揭示期间 `Think` 保持默认展开；只有回答字符队列完成后才自动折叠一次。
- 最终成功 snapshot 必须包含可持久化的公开思考文本和回答，Desktop 将临时节点升级为正式消息而非重复追加。

### R4：交互与可访问性

- 未满足 validated `complete` 与 `350ms` 稳定窗口时，即使已收到 provisional 文本，`Think` 也不是 button，不能聚焦或通过键盘展开。
- validated `complete` 与 `350ms` 稳定窗口同时满足后，`Think` 变为原生可操作 disclosure，默认展开并支持键盘与可见 focus。
- 回答完成后的自动折叠只执行一次；用户随后手动展开不会被普通 snapshot refresh 再次强制折叠。
- `prefers-reduced-motion: reduce` 下不使用逐字动画，直接追加已经批准的文本，同时保持状态和折叠语义。
- screen reader 获得有界 live update，不能每个字符都造成独立冗长播报。

### R5：失败、恢复与兼容

- repair、失败、Interrupt、Retry、supersede、conversation 切换和 cursor reset 都必须清理错误 attempt 的临时缓冲和字符队列。
- 重连必须从权威流状态恢复，不能依赖浏览器内存猜测；重复事件幂等，cursor 过旧时回到 snapshot。
- 旧 `public_thinking_steps[]` 历史以稳定分隔符合并为只读文本展示；不改写旧行。
- 新增公共字段和事件必须有长度、事件数量、重放窗口和 payload allowlist 上限。

## 验收标准

- [x] 用户消息进入时间线后立即显示且只显示运行圆点与 `Think`，无文本时没有展开按钮、可点击语义或辅助文案。
- [x] 第一段公开思考文本只进入 provisional buffer；同 generation 的 validated `complete` 与 `350ms` 稳定窗口同时满足后 `Think` 才自动展开，真实累计内容进入字符队列并逐字出现，保留模型换行且没有前端编号。
- [x] `Think` 区域不显示“正在思考”“完成后显示”、步骤数、时长、说明 页脚说明 或其他非模型文案。
- [x] 刚完成 Turn 的权威回答逐字揭示期间 `Think` 保持展开；回答字符队列完成后自动折叠一次，用户可重新展开且 snapshot refresh 不再次抢占用户选择。
- [x] 成功终态只渲染一份持久化 `Think + 回答`，临时流与 snapshot 无重复、倒退或闪烁。
- [x] repair、失败、停止、Retry、supersede、断线重连和 conversation 切换不会混合不同 attempt/Turn 的文本。
- [x] raw reasoning、prompt、provider body/event、trace、诊断、secret 不进入数据库公共列、conversation event、SSE、Desktop state、日志或测试快照。
- [x] legacy `public_thinking_steps[]` 历史仍可读取并以纯文本展示，不新增编号 UI。
- [x] 键盘、focus、screen reader、390/900/1440 viewport 与 reduced-motion 行为通过自动化和浏览器验证。
- [x] 后端 聚焦测试、Desktop tests、`desktop:check`、相关 lint/typecheck、Trellis validate 和 `git diff --check` 通过。

## 风险与约束

- 当前 provider 输出是一个严格 JSON 对象，partial JSON 在完整校验前不具备最终权威；设计必须避免把任意 JSON 片段或后来被 repair 拒绝的文本直接升级为持久消息。
- conversation event 当前是 durable snapshot invalidation authority；临时流若不可恢复，会在重连时造成体验回退，因此必须明确持久化短期流状态或可重放事件的边界。
- 当前工作树已有相关未提交修改；实施只能在 scoped diff 上演进，不能 reset、restore 或覆盖这些修改。

## 已冻结技术边界

- 新 provider contract 使用单一 `public_thinking_text`；旧 `public_thinking_steps_json` 只保留只读兼容。
- Responses visible output delta 是实时公开思考的首要完成路径；不支持兼容 structured stream 的 provider 保持空禁用 `Think` 直到最终消息，禁止伪造思考动画。
- conversation snapshot/event/cursor 使用新版本，`turn_output` 是唯一允许 Desktop 局部消费 payload 的 event；其他事件继续触发权威 snapshot refresh。
- 正式回答不提前消费 provider JSON delta，避免展示后来被 action/gate/repair/stale 屏障拒绝的回答。
