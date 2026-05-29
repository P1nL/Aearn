# 动态学习路线生成 — 模型实时参考权威文档

## Goal

将学习路线生成从静态 `COURSE_TEMPLATES` 查表改为 LLM agent 实时参考权威文档动态生成，支持任意编程主题、个性化裁剪，并保持输出结构与现有 `PlanDraft` 模型完全兼容。

## Scope Clarification — 2026-05-29

当前可交付范围是 post-MVP / v1.1 的动态路线生成增强，不是取消第一版基线契约。实现必须保留现有 `Language`、数据库约束、课程 catalog、runtime boundary 和 `PlanDraft` validation。TypeScript、Rust、Go 等新语言可以作为后续扩展目标和测试样例设计，但在公开 API 可确认计划前，必须先补 `Language` 枚举、schema CHECK、catalog seed、runtime boundary、前端展示和验收用例。

## 现状问题

1. **覆盖面有限**：`COURSE_TEMPLATES` 只有 5 种语言的固定模板，无法覆盖 TypeScript、Rust、Go 等用户可能选择的主题。
2. **千人一面**：同一语言的所有用户拿到完全相同的模块和知识点，无法根据用户目标、水平做裁剪。
3. **内容滞后**：模板内容是手写快照，无法跟随官方文档更新（如 Python 3.13 新特性）。
4. **扩展成本高**：每新增一种语言需要手动编写完整模板，维护负担大。

## Requirements

### R1 — Agent 架构

- 新建 `plan_generation_agent`，接收用户目标、语言、水平、时间预算作为输入
- Agent 可调用 web search tool 查询权威文档目录结构
- Agent 输出必须严格符合 `PlanDraft` 的 modules + knowledge_points 结构（structured output）
- 单次生成延迟目标 ≤ 15s（含网络请求）

### R2 — 权威文档参考策略

- 维护一份语言 → 权威文档 URL 的映射表（如 python → docs.python.org/tutorial, javascript → developer.mozilla.org/Guide）
- Agent 优先从映射表中的 URL 获取目录结构
- 对于映射表中没有的语言，Agent 通过 web search 自行发现权威文档
- 生成的模块顺序应参考官方文档的教学顺序

### R3 — 个性化裁剪

- 根据 `target_level` 调整深度：beginner 侧重基础语法和可见输出，intermediate 加入设计模式和工具链
- 根据 `goal_text` 调整侧重：如用户目标是"做网页"则 JS 路线侧重 DOM，目标是"数据分析"则 Python 路线侧重 pandas
- 根据 `time_budget` 控制模块数量：时间紧则精简为核心模块，时间充裕则展开可选模块

### R4 — 输出结构约束

- 每个 module 必须包含：temp_id、title、description、order_index、is_skippable、estimated_sessions、knowledge_points
- 每个 knowledge_point 必须包含：temp_id、title、description、skill_tags、exercise_refs（可为空）
- temp_id 格式：`mod_draft_{language}_{slug}` / `kp_draft_{language}_{slug}`
- title 和 description 必须为中文

### R5 — Fallback 机制

- 如果 web search 失败或超时，回退到静态模板（保留现有 `COURSE_TEMPLATES` 作为 fallback）
- 如果 LLM 输出不符合结构约束，重试一次；仍失败则回退到静态模板
- 记录 fallback 事件到日志，便于监控动态生成的可靠性

### R6 — 来源归因

- `source_attribution` 字段记录实际参考的文档 URL
- 如果使用了 web search，记录搜索查询和命中的文档标题
- 如果回退到静态模板，标注 "Fallback: static template"

## Constraints

- 不改变 `PlanDraft` 模型定义和下游消费方的接口
- 不删除 `COURSE_TEMPLATES`，保留作为 fallback 和测试基准
- 不绕过现有 `Language` 枚举、数据库约束、课程 catalog 和 runtime boundary；未登记语言不得被公开承诺为可确认计划
- Agent 使用项目已有的 LLM 调用基础设施（`litellm` / 现有 agent 框架）
- Web search 当前使用 Exa 工具配置（`EXA_API_KEY`）；替换为其他 provider 需要同步实现和文档

## Acceptance Criteria

- [ ] 对已有语言（JS/Python/HTML_CSS），动态生成的路线质量不低于静态模板（模块覆盖度、顺序合理性）
- [ ] 对新语言（如 Rust、Go），能生成合理的 6 模块学习路线
- [ ] 用户目标不同时，同一语言生成的路线有明显差异
- [ ] Web search 失败时自动回退到静态模板，不影响用户体验
- [ ] 未登记语言在 schema/catalog/runtime 扩展前不会被误报为可运行或可确认计划
- [ ] 生成延迟 P95 ≤ 15s
- [ ] 输出结构 100% 符合 PlanDraft schema，下游无需任何适配
- [ ] source_attribution 正确记录参考来源
