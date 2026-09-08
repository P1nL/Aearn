# 技术设计：用户聊天方向偏移后的主线恢复

## 1. 设计目标

为 Tutor 建立跨模式、跨 Runtime 的通用方向恢复语义。修复目标不是识别某个主题词，而是让模型根据最新消息与当前讨论主线的关系选择继续、回答后回归、澄清方向或确认切换，同时保留现有服务端权威。

## 2. 共享行为模型

以下分类只用于指令、设计和测试，不新增公开 API/数据库枚举：

1. **continue_mainline**：最新消息是当前目标、objective 或问题的正常延伸，继续当前流程。
2. **answer_and_refocus**：消息是临时岔题且可以安全简短回答；先回答，再明确连接回当前主线及下一步。
3. **clarify_direction**：无法判断消息是相关素材、临时岔题还是希望切换；只问一个方向澄清问题。
4. **confirmed_switch**：用户明确否定旧方向并给出新方向；停止旧路径，进入当前产品支持的新方向。

共享优先级为：最新 learner input / 显式控制 / 当前服务端事实与 TeachingSession authority > recent messages > summary > persistent thread 联想。旧上下文只能帮助解释，不能覆盖最新输入。

## 3. 覆盖面

### 3.1 普通 Harness provider

更新 `TUTOR_TEACHING_POLICY`，加入完整方向恢复闭环：

- 不能忽略当前岔题，也不能回答后永久丢失主线；
- 方向不明时只澄清一次；
- 明确切换后不再强拉回已拒绝路径；
- 相关延伸直接继续，禁止关键词式误判。

replacement prompt 继续复用该 policy，保证首次输出和修复重试一致。

### 3.2 LearningPlan Skill

发布 `tutor.learning-plan-draft@1.0.3`：

- 保留 `1.0.2` 的 planning facts、semantic language、typed request 和 draft 合同；
- 增加四类方向行为及正反例；
- 对疑似偏移不静默沿用旧目标继续问实现细节；
- 当前输入和 server facts 高于旧对话语境；
- evals 使用多种方向偏移场景，“厨师”只是其中一个样例。

`plan_policy.py` 将当前计划 Skill 切换到 `1.0.3`，旧版本不可变。

### 3.3 LessonTeaching Skill

发布 `tutor.lesson-teaching@1.2.1`：

- 保留 v3 teaching-step、objective/focus、Artifact candidate 与 interaction pairing 合同；
- 临时岔题使用当前 objective/focus 生成一个 bounded teaching step：先回答或承认，再通过合适 teaching move 回到当前 focus；
- 方向不明时使用一个 composer 问题；
- 明确切换只在现有 server objective/focus/control 允许时执行，不由模型伪造新 authority；
- blocking Artifact branch 继续使用已有 server disposition，不在 Skill 中创建第二套状态。

`plan_policy.py` 的 teaching Skill 当前选择切换到 `1.2.1`，旧版本不可变。

### 3.4 Codex plan-drafting

Codex 路径不消费 Harness LearningPlan Skill，因此同步修改 `_BASE_INSTRUCTIONS`：

- latest input 和 `aearn_planning_context_read` facts 高于 persistent thread；
- 使用 continue / answer-and-refocus / clarify / confirmed-switch 的相同语义；
- 不得从旧线程无确认地补全网站、图片、HTML 或任何其他旧方向；
- 继续复用现有 language hint、`clarification_required`、server exact question 和 typed request authority。

### 3.5 Codex plan-drafting 的有界方向决策

当前 `clarification_required=true` 与 `confirmed_switch=true` 只覆盖两类显式分支；`continue_mainline` 和 `answer_and_refocus` 由“没有设置布尔值”隐式表示。模型因此可以在 reasoning 中反复权衡，最后不调用第二次工具，dispatcher 仍把该 Turn 当作普通 `next_missing_fact` 继续，缺少可验证的纠偏完成点。

修复采用现有 `aearn_planning_context_read` typed boundary，不新增前端分类或数据库状态机：

1. **Closed action：** 在工具输入中使用一个互斥的 `direction_action`，值为 `continue_mainline / answer_and_refocus / clarify_direction / confirmed_switch`。模型先读取 context，再在下一次工具调用中提交恰好一个 action；语义语言 hint 可按现有规则与允许的主线 action 组合。
2. **Accepted marker：** Registry 仅在服务端工具返回合法结果后记录 `planning_direction_action`，并保留稳定 result code。这个值是当前 Turn 的 validated control marker，不是 planning fact，也不提供任何事实值。
3. **有界执行：** 基础指令要求读取 context 后立即选择 closed action，不继续自由讨论，也不在 action 被接受后重新分类。draft 调用和 Turn finalization 都必须检查 action marker。
4. **缺失标志 fail closed：** completed Turn 如果没有 accepted action，不使用模型 final answer，也不继续旧 `next_missing_fact`；Aearn 创建一个 server-owned `clarify_direction` typed request。
5. **确定性纠偏提示：** `clarify_direction` 不接受“只要有一个问号就算合法”的任意模型问题。服务端使用明确提示：指出最新输入可能与当前计划方向不一致，并让学习者在补充当前目标、临时岔题和切换方向之间选择。
6. **其余动作：** `continue_mainline` 使用现有 exact question；`answer_and_refocus` 只有在模型回答以 exact question 结束且只有一个问题时才保留前置回答；`confirmed_switch` 继续复用 append-only fact reopen 和 server-owned next question。
7. **保留 Think：** reasoning started/delta/completed、snapshot/SSE、历史回放和 Desktop `think` 保持修改前合同。本任务的“变短”来自 action 路径和终态 gate，而不是隐藏 reasoning。

## 4. 数据流

```text
latest learner input
  + current server authority
  + supporting conversation context
        ↓
aearn_planning_context_read (read current facts once)
        ↓
closed direction_action tool call
        ↓
validated registry marker
  ├─ continue_mainline    -> existing exact next question/draft flow
  ├─ answer_and_refocus   -> bounded answer + exact next question
  ├─ clarify_direction    -> deterministic server-owned direction question
  └─ confirmed_switch     -> append-only reopen + server-owned new question
        ↓
missing/invalid marker -> deterministic clarify_direction fallback
        ↓
existing Decision Gate / typed request / TeachingSession / branch authority
        ↓
formal Tutor message and unchanged reasoning/answer Desktop projection
```

## 5. 回归测试设计

回归测试按语义类别参数化，不以“厨师”文本作为唯一判断：

| 当前主线 | 最新消息类型 | 预期 |
| --- | --- | --- |
| 网站学习 | 非编程职业/兴趣陈述 | 澄清方向或回答后回归；不直接补全网站技术细节 |
| SQL JOIN | CSS 动画问题 | 简短处理岔题并明确回到 JOIN，或询问是否切换 |
| Python 变量 | 暂时询问网络概念 | 回答/界定后恢复当前变量任务 |
| 网站学习 | “厨师作品展示网站” | 视为相关延伸，继续主线 |
| 旧编程方向 | “停止旧方向，改学 Python 自动化” | 确认切换，停止旧路径 |
| 任意主线 | 模糊的短句或主题词 | 只问一个方向澄清问题 |

测试层次：

- provider-policy 和 replacement-policy 文本合同；
- LearningPlan/Teaching Skill eval 与 Catalog 不可变/hash/LF；
- fake Harness action loop / teaching loop 的方向偏移输出；
- fake Codex plan-drafting cutover 的 persistent-thread 优先级、四类 closed `direction_action`、accepted marker、缺标志 fail-closed 与 deterministic typed clarification；
- blocking Artifact branch 的既有 answer/refocus/switch 非回归；
- 正常计划、语义语言和教学 Artifact 行为非回归。

## 6. 兼容和安全边界

- reasoning 的 API、SSE、snapshot、Desktop contracts 和数据库 schema 保持修改前行为；只调整 planning tool 的私有 typed input/result 与 dispatcher gate。
- 不在前端做语义分类，不维护关键词表。
- 模型不能创建 objective/focus、修改 planning facts、选择未授权 Skill/Artifact 或写数据库。
- 已有 blocking Artifact branch 是唯一 branch authority；普通方向恢复只改变模型可见消息和现有合法 action。
- 所有新 Skill 资源保持 LF，manifest 使用 exact raw-byte SHA-256。

## 7. 回滚与升级条件

- 正常相关消息被频繁误判时，回退新 Skill 选择、共享指令和 closed direction action gate，保留旧 Skill 版本及原 reasoning 展示。
- 新 Skill hash 不匹配时 Catalog 必须 fail closed，不能放宽校验。
- 如果测试证明现有 planning fact、TeachingSession focus 或 checkpoint 无法在明确切换后保持正确权威，停止实现并回到规划，单独设计状态扩展。
- 不运行真实 provider；实施结论只覆盖静态合同、fake-provider 和本地回归。
