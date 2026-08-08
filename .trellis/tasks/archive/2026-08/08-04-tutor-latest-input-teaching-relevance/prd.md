# 修复 Tutor 最新输入丢失与教学偏航

## 目标

恢复面向学习者的 Tutor 对话的核心可用性。每个交互式 TurnRun 都必须向配置的模型提供权威的当前学习者输入，只保留最相关且有界的历史，并要求 Tutor 在推进任何先前教学路径之前，先回答或确认学习者的最新意图。

本任务源于一次真实的多轮对话，学习者依次说道：

1. `我想做个网站`
2. `绘画作品，迪士尼风格，零基础`
3. `我已经有了`
4. `你不是应该教我编程语言吗`
5. `我应该学哪些语言`

当对话超过四条已存储消息后，Tutor 反复继续早先的图片/HTML 脚本，没有回应最新的纠正或问题。修复后的系统必须在上下文构造边界从机制上杜绝此类失败，并让该行为能够通过回归证据被观察和验证。

## 已确认的仓库事实

1. `PostgresTutorContextLoader` 以数据库降序读取最多八条对话消息，然后将其反转为时间顺序（`app/services/tutor/interactive.py`）。
2. `TutorContextBuilder` 对 `RECENT_MESSAGES` 应用默认四项上限，并从传入序列的开头选择（`app/agents/harness/context_builder.py`）。一旦对话超过四条消息，最早被选中的消息就可能挤掉当前学习者输入。
3. 权威学习者输入已由 `tutor_run_input_events(run_id, input_revision, message_id)` 精确映射到 `tutor_messages`；无需通过 `created_at` 推断当前输入身份。
4. 当前 provider system prompt 主要是严格的 JSON envelope contract。它没有明确要求最新输入优先、纠正处理、建议类问题先回答，或停止已被取代的教学路径（`app/services/tutor/provider_gateway.py`）。
5. 当前 provider 校验会检查 schema、continuation/terminal 组合和输出安全，但不会检查教学相关性。现有确定性 Tutor eval 覆盖运行时安全和生命周期行为，不覆盖本次多轮教学回归。
6. 当前工作树中已存在受保护且未提交的 Tutor provider、public API、配置、测试和运行时文档修改。本任务必须与这些修改合并共存，不得 reset、restore 或覆盖它们。

## 任务树位置与依赖

- 父任务：`08-04-tutor-context-governance-adaptive-budget`。
- 本任务是任务树的第一个实施子任务，不依赖后续 usage、预算或摘要任务。
- 本任务完成后，`08-04-tutor-provider-usage-cache-accounting` 才进入实施；后续预算、摘要和综合评估均依赖本任务冻结的 `current_input` 与 provider payload contract。
- 本任务只修复当前输入正确性、最新历史选择和教学相关性，不在本任务内引入自适应预算档位、provider usage 持久化或结构化长期摘要。

## 需求

### R1 — 权威当前输入是强制项

- 通过 `tutor_run_input_events.message_id`，使用精确的 `run_id + input_revision` 解析当前交互式学习者输入，并关联到规范的学习者消息。
- 不得仅根据对话顺序、时间戳、角色或宽泛历史查询返回的最后一行推断当前轮次。
- 在 Harness 上下文 contract 和 provider payload 中，将当前输入与可选的近期历史分开表示。
- 有效且非空的当前输入绝不能被 active-plan、review、history、memory、activity、capability-schema 或其他可选上下文挤出。
- 如果经过确定性的清理/截断规则后，仍无法在有界请求内表示当前输入，则必须在调用 provider 前以类型化安全结果失败；绝不能在缺少当前学习者意图的情况下调用 provider。
- 主动式运行可根据其现有独立策略继续不携带输入；本需求不得为主动式工作虚构学习者文本。

### R2 — 近期历史必须足够新且按时间顺序呈现

- 从可选历史切片中排除权威当前输入，避免重复。
- 选择有界范围内最新的既往消息，而不是从更大抓取窗口中选择最早的消息。
- 完成选择后，按对话时间顺序呈现所选既往消息。
- 保持用户范围、对话范围、脱敏、每来源字符边界、token 记账、checkpoint metadata 和不加载完整历史的保证。
- 单纯增加 token budget 或消息数量不是可接受的修复；在长对话和较小但有效的 budget 下也必须保证正确性。

### R3 — 最新意图与纠正策略

交互式 Tutor 的 instruction contract 必须要求以下全部行为，同时不得增加确定性的学科答案生成器：

- 将明确的当前输入视为当前 TurnRun 的权威请求。
- 在推进任何先前课程、练习、设置或计划之前，先回答当前问题或确认当前指令。
- 将学习者的纠正、拒绝、打断、目标变更，以及“已经完成 / 已经有了”等陈述视为对陈旧假设的覆盖。
- 除非学习者明确要求重做，否则不得重复已经完成或被拒绝的步骤。
- 对建议、比较、能力和“我应该学什么”类问题，先直接回答；只有在确实能改善下一步时，最多再问一个有用的后续问题。
- 不得仅因为网站/图片/HTML 路径曾在早先对话中出现，就强制继续该固定路径。
- 回复应简洁、面向学习者，在缺少事实时保持诚实，并兼容现有严格 JSON decision envelope。

### R4 — 保持 Provider 与安全边界

- 保持精确的 provider/model/protocol 选择、仅主 provider 行为、严格 JSON schema、同 provider 修复次数限制、输出安全检查、continuation 规则、标题规则和 `MODEL_UNAVAILABLE` 映射。
- repair prompt 必须保留相同的教学策略要求；schema 修复不得丢失最新输入优先级。
- 不得在公开响应、trace、event、checkpoint 或测试中暴露原始 prompt、原始 history、provider payload、reasoning、validation details、credential 或内部诊断。
- 不得为报告中的对话增加基于关键字的生产路由或硬编码中文答案。

### R5 — 确定性回归覆盖

添加聚焦测试，证明：

- 即使对话消息数超过历史项上限，也会选择当前学习者输入；
- 使用 run/input-revision 证据识别精确当前输入，并在可行情况下覆盖时间戳相同或存在干扰性后续行的情况；
- 既往历史选择保留最新的有界消息，并按时间顺序输出；
- budget 紧张时，先驱逐可选上下文，再处理当前输入；
- 无法表示的当前输入会在 provider 被调用前安全失败；
- provider request 会单独暴露当前输入，并包含最新意图/纠正策略；
- 严格 JSON、安全、脱敏、主动式运行、历史、首轮、普通新鲜 TurnRun 和 latest-input-wins 行为保持不变。

### R6 — 教学相关性评估

- 扩展现有受源码控制的 Tutor eval 机制，而不是创建无关的新框架。
- 为当前输入固定、近期历史选择、纠正策略 prompt 存在性，以及 provider 未被调用的失败行为添加确定性用例。
- 保持仅使用 fake、离线且确定性的 CI 行为。
- 基于报告中的对话定义一个受控、可选的真实 provider smoke 场景。它必须通过现有配置的环境凭据运行，不读取或打印凭据，并且只记录对学习者安全的输出和有界 rubric 结果。
- smoke rubric 必须检查最新轮次相关性、纠正确认、不重复已拒绝/已完成步骤、先回答行为，以及不存在强制陈旧教学路径。真实 provider smoke 结果只是模型行为证据，不能替代确定性 contract 测试或发布批准。

### R7 — 文档与可复用 Contract

- 在代码证明行为之后，更新 `docs/architecture/tutor-harness-runtime.md`，记录当前输入固定和最新意图教学 contract。
- 如果实现确认了“权威当前输入是强制项，且可选历史不得挤掉它”这一可复用规则，则更新 `.trellis/spec/backend/quality-guidelines.md`。
- 不得创建重复的产品规格，也不得恢复已归档的 Graph/onboarding 运行时代码。

### R8 — 工作树与交付安全

- 在实施前立即重新读取重叠的工作树 diff。
- 保留所有用户已有修改；只进行增量编辑或有意合并的编辑。
- 未获得单独明确批准前，不得 commit、push、deploy、修改生产数据或执行破坏性清理。

## 验收标准

- [ ] 基于报告中的对话构造的上下文包含精确的最新学习者输入 `我应该学哪些语言`，并将其作为权威当前输入；不得让早先的网站/图片指令取代它。
- [ ] 当当前输入为 `我已经有了` 时，Tutor 策略禁止要求学习者下载或重做同一资源步骤，除非学习者明确提出。
- [ ] 当当前输入为 `你不是应该教我编程语言吗` 时，Tutor 策略要求确认方向调整并停止陈旧的图片优先路径。
- [ ] 当当前输入为 `我应该学哪些语言` 时，Tutor 必须先回答该建议问题，再考虑任何可选的后续问题；不得只回复文件/文件夹/HTML 设置指令。
- [ ] 当前输入身份来自活动 run 和 revision 对应的 `tutor_run_input_events`，而不是时间戳猜测。
- [ ] 在有界历史上限内选择最新的既往消息，并按时间顺序呈现，同时从历史中排除当前输入以避免重复。
- [ ] budget 紧张时先删除可选上下文；如果当前输入仍无法表示，则必须在调用 provider 前安全终止。
- [ ] 现有 provider protocol、decision-envelope、安全、标题、continuation、生命周期、历史和主动式测试继续通过。
- [ ] 确定性 Tutor eval fixture 覆盖该回归，并且无需网络或真实模型即可通过。
- [ ] 存在有文档记录的可选真实 provider smoke 命令和 rubric；如执行，不记录凭据或原始 provider payload。
- [ ] 聚焦 Pytest、所有相关 API 测试、Ruff、Mypy、任务验证和 `git diff --check` 通过；如有环境阻塞，必须精确报告。

## 范围外

- 替换已配置模型，或增加 model/provider fallback。
- 重建整个 curriculum、语言目录、plan engine、Desktop layout 或对话历史 UI。
- 为每个教学主题增加确定性的关键字路由或硬编码答案。
- 将真实 provider smoke 测试设为普通离线 CI 的强制项。
- 修改生产配置、部署、提交或推送。

## 产品决策

- 当学习者明确纠正、打断、完成或拒绝当前教学路径时，Tutor 必须以可见但简洁的方式确认变化，明确停止陈旧路径，直接回答权威当前输入，并且最多询问一个必要的下一步问题。不得静默继续，也不得重复被拒绝或已完成的步骤。
