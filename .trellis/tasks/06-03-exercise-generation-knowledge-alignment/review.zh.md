# 中文 Review: 练习生成与知识点对齐

## 目标

让练习真正对齐学习路线里的知识点，而不是路线写着 `列表推导式`、`JOIN`、`DOM event`，练习却仍然是每种语言一套通用题。

这次规划明确采用用户想要的方向：`model-first bounded freeform generation`。也就是模型可以更自由地重新设计题目、`starter_code`、`solution_reference` 和 `code_blanks`；deterministic template 只作为内部 seed、边界和 runner harness，不再作为模型失败后的用户可见兜底题。

## 范围

- 后端练习生成链路。
- `skill_tags` / lesson context 进入模型上下文。
- 模型优先的受控自由生成。
- 生成后执行 runner validation。
- 增加语法/语义验证，确认题目真的练到了目标知识点。
- 失败后走模型多轮重试，重试仍不合格就诚实返回不可用/请重试，不展示硬编码假练习。
- 8 种可执行公开语言：`python`、`javascript`、`html_css`、`typescript`、`sql`、`java`、`go`、`csharp`。
- `cpp` 只作为静态占位，不进入可执行练习。

## 不在范围

- 不改任意项目执行、包管理器执行、自动安装依赖或容器沙箱。
- 不把 `cpp` 或 Rust 变成公开可执行语言。
- 不重做 onboarding、学习路线生成或前端 UI。
- 不改 DeepSeek/OpenAI provider 兼容逻辑。
- 不在未确认前 start 这个任务或进入实现。

## 核心设计

当前链路里，`adaptive_exercise_service.py::_model_context()` 只给模型 `knowledge_point_title`、500 字符 `knowledge_point_description`、`weak_points` 和 runtime 信息，没有把完整 `skill_tags` 或 lesson context 传进去。模型即使想对齐知识点，也缺少足够上下文。

新设计分成四层：

- 模型负责创造题目：可以改题面、代码结构、答案代码和 blanks。
- 系统负责边界：`language`、`runtime_tier`、`runner` 不能由模型修改。
- 系统负责验证：先做 schema/safety，再做 semantic validation，再做 runner validation。
- 系统负责重试和诚实失败：任何一步失败，都把安全的失败原因反馈给模型重新生成；达到重试上限仍失败，就返回不可用/请重试，不展示 deterministic template 冒充生成结果。

## 执行阶段

1. Phase 0：覆盖审计。列出 8 种公开语言、所有路线知识点、`skill_tags`、当前 internal seed/harness、runner 和 validator 覆盖情况。
2. Phase 1：增强模型上下文。把 `skill_tags`、lesson/module context、source/taxonomy hints、weak points 结构化传给模型。
3. Phase 2：模型优先的受控自由生成。模型可以自由重构练习形态，但不能改 runtime 边界，也不能自己当裁判。
4. Phase 3：语法/语义验证。先做 Python AST，再做 SQL 和 JavaScript/TypeScript 的轻量验证，其他语言后续分批补。

## 关键取舍

- 选择模型自由度，而不是只补 deterministic template family。
- 接受模型自由度带来的风险，但用 semantic validation 和 runner validation 控制风险。
- 不让模型拥有 `test_cases` 或最终判定权，避免模型自己出题、自己放行。
- `skill_tags` 命中不能只靠 prompt，要有 validator 验证。
- 不用硬编码题冒充智能生成；宁可让用户多等几轮或看到诚实失败。
- 长 lesson 内容不能无限塞进 prompt，需要 bounded structured context，避免 prompt injection 和噪声。

## 验收标准

- 有覆盖矩阵说明每种语言、每个知识点、每类 `skill_tags` 当前练习覆盖状态。
- 模型上下文里包含 `required_skill_tags` 和 lesson/module context。
- prompt 明确要求生成练习对齐 `required_skill_tags`，不能泛化成普通语言题。
- 模型可以生成和 deterministic seed 完全不同代码形态的候选题。
- 模型不能修改 `language`、`runtime_tier`、`runner`。
- 如果候选题能跑通但没有命中目标语法/语义，必须被拒绝并触发下一轮模型重试。
- 如果多轮重试后仍不合格，必须返回诚实的 unavailable/error 结果，不能展示 deterministic template 当作生成题。
- Python 至少有一个严格 AST validator，例如 `list_comprehension` 检查 `ast.ListComp`。
- SQL、JavaScript/TypeScript 至少有初始轻量 validator。
- 现有 runner validation、hidden-output redaction、cache/export/reset 行为不回归。

## 风险

- 模型生成题目看起来合理，但没有练到目标知识点。
- 每种语言 validator 工作量不同，Java/Go/C# 较复杂。
- lesson context 太长会带来 prompt injection 或噪声。
- cache 可能复用旧 prompt 生成的变体，需要版本化失效。
- managed compiled runner 依赖本机 toolchain，测试要保留 missing toolchain 边界。

## 回滚点

- 如果模型上下文增强导致生成质量下降，回滚 `_model_context()` 和 prompt 变更。
- 如果 semantic validators 过严，可以先通过 feature/config guard 禁用。
- 如果 model-first freeform 破坏 runner validation，先禁用该生成路径或返回诚实不可用，不把 deterministic template 作为正常用户可见替代。
- deterministic template 可以保留为内部 seed/harness 和测试工具，但不能作为默认产品兜底体验。

## 推荐首批实现

- Python：`list_comprehension`，用标准库 `ast` 检查 `ast.ListComp`。
- SQL：`filtering`、`joins`、`aggregation`，先用轻量 token/regex。
- JavaScript/TypeScript：`functions`、`dom_events`、`types`，先用轻量规则。

## 当前状态

已创建 Trellis planning task，但还没有 start，也没有进入实现。下一步应先 review 本规划；如果确认，再 start task 并按 Phase 0 开始做覆盖矩阵。
