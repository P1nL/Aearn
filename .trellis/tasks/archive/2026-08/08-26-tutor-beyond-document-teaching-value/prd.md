# 重塑 Tutor 的非文档型教学价值与交互粒度

## 目标

让 Tutor 不再充当 LessonDocument 的逐段复述器或摘要器，而是提供静态文档无法提供的动态、个性化和交互式教学价值。学习者应在更少的显式操作中获得有实质推进的教学互动，并能明显区分“阅读文档”和“与 Tutor 学习”两种体验。

## 背景与已确认事实

- 用户实际使用后发现当前教学分段过细，需要频繁点击“继续”。
- 截图中的连续 Tutor 回合围绕 HTML 基础骨架进行近义复述，信息增量很低，与 LessonDocument 没有形成明确分工。
- 当前 `tutor.lesson-teaching@1.0.0` 要求每个 stimulus 只处理一个中心教学目的、只返回一个 `teaching_step`，并在每一步选择 pause；canonical example 进一步使用“只解释一个核心概念并停顿”的措辞。
- 当前服务端 invariant 是 one stimulus -> one closed teaching action -> one pause。任务不能通过删除 TeachingSession、checkpoint、CAS、durable Turn 或显式用户控制来换取表面连续性。
- 已发布 Skill 内容不可原地改写；教学指令或输出契约改变时必须发布新的精确语义版本，并同步 policy、catalog、provider contract、测试和 source-of-truth。
- 用户明确否定“强化文档”的方向：Tutor 的价值不是把文档讲得更长，而是给出文档本身无法提供的其他部分。

## 产品职责边界

- LessonDocument 负责权威、稳定、可引用、可完整阅读的知识材料。
- Tutor 默认不主动重新讲解文档正文，也不按 LessonDocument 的结构顺序推进。
- Tutor 从学习者的回答、疑问、错误、练习结果、历史停顿点和当前 checkpoint 出发，优先执行“理解诊断 → 引导推演 → 即时反馈 → 知识迁移”。
- 只有学习者明确指出某处未理解或主动要求解释时，Tutor 才针对具体障碍重新解释；解释完成后必须回到诊断、互动或迁移路径，不能退化为连续复述文档。

## 需求

### R1：非文档型教学价值

- 每个教学单元必须使用当前学习者证据，不能只根据知识点标题或 LessonDocument 摘要生成通用内容。
- 每个教学单元必须完成一次可识别的教学推进，例如发现误区、建立推导方法、验证预测、纠正错误、解释练习反馈或迁移到新情境。
- 仅增加字数、重复文档事实、近义改写上一轮内容或提出与当前证据无关的通用问题，不算教学推进。

### R2：弹性教学单元价值门

- 一个教学单元至少组合两种情境合适的互补动作。
- 互补动作的闭合候选包括：针对性解释、动态例子、反例、误区对比、逐步推演、预测结果、找错、微型迁移任务和即时反馈。
- 不强制固定的“解释 + 例子 + 提问”结构、固定顺序或统一篇幅，避免形成机械教案。
- `teaching_step.action` 继续表示该单元的主要或终点教学意图；一个 closed action 不等于 public message 只能包含一句话或一种教学动作。

### R3：同一 Turn 内的完整推进

- 同一个 Turn 内可以连续完成诊断、针对性解释、例子或反例、对比、逐步推演和一个可作答任务的设置。
- 上述非交互部分不能再拆成多个必须分别点击“继续”的微型 Turn。
- 每个 Turn 仍只提交一个 closed teaching action，并在同一事务中写 checkpoint、action receipt、Tutor message 和 terminal run。
- 禁止自动无限连播、无界多 Turn admission 或客户端自动代替学习者触发 `continue`。

### R4：理解检查策略

- 理解检查按知识类型选择最低负担但具有诊断价值的形式：
  - 程序行为或执行流程优先预测结果；
  - 语法或结构优先找错、补缺或局部修改；
  - 概念边界优先比较案例并选择理由；
  - 基础理解完成后优先微型迁移任务；
  - 前述证据不足时才追问简短原因；
  - 只有需要完整思路时才要求较长自由回答。
- 禁止默认使用“请用自己的话复述”之类与当前证据无关的通用检查。
- 检查结果必须能够影响下一步教学策略，否则不应制造一次强制交互。

### R5：Composer 与停顿边界

- 当后续教学策略真正依赖学习者表现时，Tutor 必须以具体、可作答的任务结束，由普通 Composer 承担下一步。
- 此时 Action Shelf 不显示普通“继续”主按钮；学习者回答形成新的 learner-message stimulus 和 fresh bounded Turn。
- 练习证据、authority 更新、知识点边界和用户显式暂停仍必须形成可审计停顿。
- active runtime、blocking typed request、evidence pause、session pause 与 completion 继续使用现有服务端优先级和专用操作。

### R6：条件式“继续”

- “继续”不常驻，只在服务端判断当前不需要学习者证据、但仍存在高价值非重复推进时出现。
- “继续”的语义是授权 Tutor 基于 checkpoint、recent teaching units、covered concepts 和当前 stimulus 选择下一种教学策略，而不是延长上一轮讲法。
- 正常 `continue` 后，下一单元必须体现策略变化、证据深化或迁移推进；同一 focus 下的完全相同 action/move signature 或相同 public message 不得重放。
- `change_example` 保持独立显式语义：允许围绕当前教学目的更换例子或表示方式，不冒充普通 `continue`。
- 如果不存在有价值的下一步，Tutor 应总结并建议暂停，而不是生成填充内容。

### R7：服务端权威与前端投影

- Action Shelf 是否包含“继续”必须由服务端 checkpoint/action policy 投影，前端不得通过问号、文案、段落长度、action 名称猜测。
- 当服务端没有投影可执行 action 时，Desktop 不渲染空 Action Shelf，也不显示“继续阅读”等本地补写占位文案。
- Action Shelf 仍最多一个 primary、三个 visible secondary；runtime/request/shelf 三类槽位继续互斥。
- Action descriptor 的 label、target、enabled、expected versions 和幂等/CAS 仍由服务端生成。

### R8：版本、兼容与安全

- 保持 `tutor.lesson-teaching@1.0.0` 文件和 hashes 不变，发布新的精确版本承载新教学单元契约。
- 历史 Tutor message、checkpoint 和 `teaching_action_receipt_v1` 保持可读，不回填或改写原始内容。
- 新版本只新增安全闭合 enum、布尔值、IDs、hashes 和 bounded metadata；不持久化 prompt、reasoning、provider body、完整 LessonDocument、完整练习提交、hidden tests、rubric、命令、路径或 secrets。
- 默认验证使用 fake/offline provider；真实 provider smoke、部署、生产 cutover 或生产数据修改均需单独明确批准。

## 范围内

- 新 lesson-teaching Skill 版本、manifest、eval suite 和 catalog/policy selection。
- teaching-step provider schema、domain contract、decision gate、canonical example 和 repair instruction。
- teaching action receipt 的 additive 安全元数据、recent teaching unit context 和避免重复规则。
- checkpoint reducer、Action Shelf 条件投影和 Desktop 空 shelf/条件“继续”渲染。
- focused backend/Desktop tests、source-of-truth 文档和本地浏览器验收。

## 范围外

- 扩写、重写或强化 LessonDocument 正文。
- 取消 TeachingSession/checkpoint/CAS/closed action 等服务端 authority。
- 自动多 Turn 连播或前端自动点击教学控制。
- 新模型供应商、provider/model/protocol fallback、任意工具、Shell 或非教学 runtime。
- 新建第二条学习 conversation、第二套 Tutor surface 或第二套 SSE reducer。
- 真实 provider、部署、生产迁移或生产数据修改。

## 验收标准

- [ ] AC1：用户阅读 LessonDocument 后进入 Tutor，默认输出不复述文档中的定义、目录、段落顺序或相同示例，而是使用当前 learner/session evidence 提供动态教学价值。
- [ ] AC2：一次显式教学 Turn 可以在一条 Tutor message 中完成至少两种互补动作，并形成一次可识别的教学推进；不再把同一单元拆成多个近义短句 Turn。
- [ ] AC3：连续三次教学控制不会在同一 focus 上重复相同 action/move signature 或相同 public message；`continue` 推进策略，`change_example` 才保持目的并更换案例。
- [ ] AC4：需要学习者证据的 `check_understanding` / `wait_for_input` 单元结束后不显示“继续”主按钮，Composer 是主要下一步；普通 learner response 可创建下一 fresh bounded Turn。
- [ ] AC5：不需要学习者证据且存在高价值下一步时，服务端可以投影“继续”；没有有价值下一步时不显示填充性控制。
- [ ] AC6：理解检查根据知识类型选择预测、找错、比较、局部修改或微型迁移；长自由回答不是默认形式。
- [ ] AC7：active runtime、blocking request、evidence/session/completion pause 和显式 next-knowledge 行为保持原有 authority、CAS、幂等与互斥契约。
- [ ] AC8：新 Skill 使用新的 exact semantic version；旧 `1.0.0` 目录与 hashes 不变，历史 v1 receipt/read projection 继续有效。
- [ ] AC9：Action Shelf 完全由服务端投影；Desktop 不从文案推断，不渲染无 action 的空 shelf，也不本地补写“继续阅读”占位。
- [ ] AC10：focused PostgreSQL/provider/catalog/teaching loop/context/API/Desktop tests、Ruff、Mypy、`uv lock --check`、浏览器三视口检查、Trellis validate 和 `git diff --check` 通过；默认不调用真实 provider。
