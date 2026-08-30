# 当前行为与根因证据

## 结论

当前体验不是偶发模型文风，而是契约、Skill、canonical example、服务端 Action Shelf 和测试共同塑造的稳定结果。修复重点应是重新定义 Tutor 与 LessonDocument 的互补职责和“一个 teaching step”的内容完整度，而不是简单隐藏“继续”按钮或延长同类文档式说明。

## 关键证据

- `.trellis/spec/backend/teaching-session-authority.md:73-81`：每个 stimulus 只提交一个主要 teaching action，并在 terminal 后等待新 stimulus。
- `aearn/services/api/app/agents/skills/tutor.lesson-teaching/1.0.0/instructions.md:5-11`：一个中心教学目的、一个 teaching step、每步 pause、禁止自动下一 Turn。
- `aearn/services/api/app/services/tutor/decision_protocol.py:307-318`：canonical teaching example 使用“只解释一个核心概念并在完成后停顿”。
- `aearn/services/api/app/services/learning/teaching_loop.py:155-163`：普通 guided shelf 固定提供“换个例子 / 暂停 / 继续”。
- `aearn/services/api/tests/tutor/test_tutor_teaching_action_loop.py:96-116`：回归测试显式冻结 one stimulus -> one step -> soft pause -> continue。
- `.trellis/spec/backend/quality-guidelines.md:3704-3708`：已发布 Skill 指令改变必须新建语义版本，不得原地修改。

## 不应采用的表面修复

- 自动点击或前端自动触发多个 `continue`：会绕过显式控制并制造无界 Turn admission 风险。
- 单纯增加字数下限：可能把短复述变成长复述，仍不产生非文档价值。
- 把 LessonDocument 内容更多地塞进 prompt：会进一步强化重复问题。
- 只修改按钮文案：不会改变 provider 的教学策略与输出信息增量。
