# 当前行为与根因研究

## 问题定义

截图中的“我想做厨师”不是要被单独识别的业务词汇。问题的通用形式是：对话已经存在一个当前讨论方向，学习者的新消息与该方向不一致，但 Tutor 没有判断它是临时岔题、相关延伸、疑似切换还是明确切换，因而可能忽略最新输入、沿用旧语境或彻底丢失主线。

## 当前实现证据

### 普通 Harness 对话

- `aearn/services/api/app/agents/harness/provider_request.py` 的 `TUTOR_TEACHING_POLICY` 已规定 `current_input` 优先，纠正、拒绝和目标变化应停止旧路径。
- 当前策略还缺少临时岔题的完整闭环：先回应当前消息，再明确回到原主线；也没有定义“相关延伸 / 方向不明 / 明确切换”的正反边界。
- replacement prompt 会复用同一 teaching policy，因此共享策略是普通回答和修复重试的共同入口。

### 计划草拟

- `tutor.learning-plan-draft@1.0.2` 只覆盖 planning facts、语义语言候选、澄清和 plan draft 合同，没有通用方向偏移规则。
- `plan_policy.py` 固定选择该版本。修复需要发布新版本，不能修改已发布资源。
- Codex `codex_dispatcher.py` 复用 conversation-level thread，并在缺失语言且证据不足时允许模型提供 clarification 文本；现有基础指令没有充分约束旧线程方向对最新输入的影响。

### Lesson teaching 与 Artifact branch

- `tutor.lesson-teaching@1.2.0` 规定当前 learner message 优先，但 eval 主要覆盖教学动作、Artifact interaction 和 continue 去重，没有覆盖用户聊天方向偏移。
- `.trellis/spec/backend/teaching-artifact-orchestration.md` 已为 blocking Artifact branch 定义 `answer_and_refocus`、`offer_switch` 和 `confirmed_switch`。该状态机已有权威和测试，不应被复制。
- 非 blocking lesson-teaching 与普通 Tutor 消息仍需要共享的对话行为合同，确保岔题回答后回到当前 objective/focus。

## 根因结论

1. **共享语义缺口：** 当前输入优先已经存在，但“如何处理方向偏移并回归”没有形成所有模式共享的闭环。
2. **Skill 覆盖缺口：** LearningPlan 与 LessonTeaching 当前版本均没有通用方向偏移 eval。
3. **双 Runtime 漂移：** Harness provider/Skill 与 Codex plan-drafting 使用不同指令入口，必须同时对齐。
4. **测试抽象错误风险：** 如果只增加“厨师”用例，很容易得到关键词式修补，无法证明一般聊天方向偏移行为。

## 通用行为分类

- **continue_mainline：** 最新消息是当前方向的正常补充，直接继续。
- **answer_and_refocus：** 临时岔题可以回答；简短回答后连接回当前主线和下一步。
- **clarify_direction：** 无法判断相关延伸、临时岔题或切换，只问一个方向问题。
- **confirmed_switch：** 用户明确放弃旧方向并提出新方向，停止旧路径并进入新方向。

这些名称用于设计和测试，不新增公开协议枚举。blocking Artifact branch 继续使用它已有的服务端 disposition。

## 回归场景矩阵

至少使用以下语义类别，而不是只测一个文本：

1. 非编程岔题：网站学习中突然谈职业或生活兴趣。
2. 编程内跨主题岔题：SQL JOIN 教学中突然询问 CSS 动画。
3. 局部概念岔题：Python 变量教学中询问另一个尚未相关的网络概念。
4. 疑似主题素材：网站目标中出现“厨师”，但没有说明是职业目标还是网站主题。
5. 同主题延伸：明确提出“厨师作品展示网站”。
6. 明确切换：明确说停止旧主题，改学新的编程方向。
7. 临时问答后返回：明确表示“先问一个问题”，回答后应恢复原 objective/focus。

## 推荐方案

- 在 Harness 共享 provider policy 中定义通用方向偏移闭环。
- 发布新的 LearningPlan Skill 和 LessonTeaching Skill 语义版本，加入相同规则与场景化 eval；旧版本不变。
- Codex plan-drafting 基础指令同步 current input/facts 高于 persistent thread，以及 answer/refocus / clarify / switch 行为。
- 复用已有 typed clarification、TeachingSession focus 和 Artifact branch authority；不新增前端分类或关键词检测。
- 使用参数化 fake-provider、Skill catalog/eval、教学 action loop、plan-drafting cutover 与 branch 非回归测试验证。

## 2026-09-04 实机补充：方向纠偏缺少 accepted marker

启动计划制定页面后，Desktop 的 `think` 展示了 Codex 对方向关系的完整 reasoning。展示本身属于当前 Runtime 行为；真正失败链路是：

```text
Codex reads planning context
  -> reasoning 反复比较 clarify / continue / goal answer
  -> 没有提交 clarification_required 或 confirmed_switch
  -> registry 仍只有 next_missing_fact
  -> dispatcher 将“没有显式信号”解释为普通主线
  -> 最终继续询问编程经验或旧网站实现问题
```

当前实现只有 `clarification_required` 与 `confirmed_switch` 两个显式布尔信号，`continue_mainline` 和 `answer_and_refocus` 都是隐式缺省。更关键的是，model 完全不调用第二次工具时也没有 fail-closed gate；因此 instruction 中的四类名称不是可执行状态机，reasoning 再长也不等于纠偏成功。

修复应把四类语义收敛为一个 closed typed `direction_action`，并要求 context read 后立即提交一次。Registry 只有在工具成功返回后才记录 accepted marker；dispatcher 在 marker 缺失时必须丢弃模型问题并使用 server-owned direction clarification。`clarify_direction` 不能继续接受任意“只有一个问号”的 final answer，否则旧 `next_missing_fact` 仍可能伪装成纠偏问题。

reasoning started/delta/completed 的 Runtime projection、snapshot/SSE、历史回放和 Desktop `think` 应恢复并保持修改前行为。本任务不通过隐藏链式推理解决“思考过长”，而通过更短的 closed-action 路径、禁止 accepted 后重复分类和缺 marker 终态 gate 减少无效讨论。

## 升级条件

若实施证明现有权威无法在方向切换后恢复正确 planning fact、TeachingSession focus 或 checkpoint，应停止实现并回到规划阶段设计状态扩展；不得在本任务中临时加入未评审的数据库字段或隐式状态。
