# 学习计划语言语义解析与窄候选

## Goal

在保留服务器课程目录和学习事实 authority 的前提下，让 Aearn 能理解用户对框架、技术栈和应用目标的模糊描述；只有明确语言才自动确认，语义推断只生成需要用户确认的窄候选，无法判断时提出定向澄清，不再因 `no_intent_signal` 直接展示全部语言目录。

## User Value

- 用户描述“用 LangChain 做 Agent”等目标时，只看到与目标相关的语言，而不是无关的八项全目录。
- 模糊表达会得到可回答的定向追问，不会因为后端没有关键词映射而失去反馈。
- 模型负责语义匹配，但不能发明课程、越过发布状态或直接写入已确认语言事实。
- 用户始终确认模型推断结果，避免自动进入错误语言学习路径。

## Background and Confirmed Facts

- 2026-09-03 的实际请求持久化为 `selection_scope=full_catalog`、`selection_reason_code=no_intent_signal`、`recommended=null`，因此显示八门当前 active 课程。
- 对原始输入“我想做langchain架构的agent”，当前 `detect_explicit_course_languages()` 与 `detect_intent_tags()` 均返回空。
- 当前确定性解析只覆盖明确语言 aliases 和有限方向标签；`langchain`、`agent`、`AI agent`、`LLM 应用` 不在规则中。
- `PlanningIntentResolver` 已接受可选 `model_hint`，但生产持久化调用没有传入；v1 hint 也只能表达 closed intent tags，不能对 active course candidates 做语义排序。
- Desktop 只渲染持久化的 exact presentation，不自行推荐或过滤，历史/刷新必须重放相同 options。
- 当前分支基于已提交的 Skill raw-byte EOL 修复；新 Skill 版本必须继承该 checkout 约束，不能修改已发布的 1.0.1 bundle。

## Requirements

### R1：明确语言确定性优先

- 用户明确说出一个 active course language 或受支持 alias 时，保持现有 deterministic auto-confirm，并直接进入下一缺失事实。
- 多语言、显式冲突或显式 unsupported 输入不得自动确认。
- 只有明确语言证据可以自动写 confirmed `language_id`；任何模型语义推断都不得自动写事实。

### R2：服务器提供受限候选目录

- 当 `language_id` 仍缺失时，模型上下文获得 bounded、server-built active course candidate list，至少包含 canonical language value、课程标题、级别和安全 capability 摘要。
- 候选来自 PostgreSQL active published course/capability authority；模型不能增加、改名或提供课程 UUID、URL、命令及任意 option label。

### R3：模型语义匹配协议

- 发布 strict、versioned、extra-forbid 的 `planning-intent-hint-v2`，只允许从服务器候选中返回 1..3 个 canonical language candidates、closed confidence bucket 和 closed reason code。
- Hint 只允许绑定当前 run/input revision 的 `planning_input + language_id`；其他 question/continuation 必须省略。
- Provider 输出、Harness `TutorDecision`、decision gate 和持久化边界 exact 对齐；未知、重复、stale、inactive 或超量候选 fail closed。

### R4：窄候选必须人工确认

- 有有效语义匹配时生成 1..3 项 single-select，`recommended=null`，不得默认选中或自动创建语言事实。
- 可复用现有 `intent_shortlist` public scope，以 versioned reason code 区分 deterministic 与 semantic resolution，避免无必要扩大 Desktop DTO。
- 用户提交后继续使用持久 request presentation 验证并写入 exact planning fact。

### R5：低置信和无匹配走定向澄清

- 模型认为信息不足、候选接近或无法安全映射时，必须使用现有 `clarification` typed request，只问一个与实现语言/框架/运行环境相关的定向问题。
- Feature enabled 时，`no_intent_signal`、空/无效 model hint 和无 active semantic candidate 不得生成 full-catalog language request。
- 无效 hint 必须被结构/decision gate 拒绝，不能静默扩展为全目录。

### R6：模型与服务器 authority 边界

- 模型只做 bounded semantic ranking；active course membership、发布状态、candidate ordering、presentation labels、事实写入和 request persistence 仍由服务器决定。
- Public snapshot/SSE/Descriptor 不包含 raw model rationale、provider body/reasoning、内部 course UUID 或置信度细节；只允许 safe scope/reason/policy metadata。
- 默认测试使用 fake provider/offline fixtures，不调用真实 DeepSeek/OpenAI/provider。

### R7：兼容、回滚和当前请求

- `planning-intent-hint-v1` 和已持久化 v1/full-catalog request 继续可读取和按原 options 回放；不得改写历史 presentation。
- `TUTOR_PLANNING_INTENT_ENABLED=false` 可保留 legacy full-catalog 作为显式 rollback 行为，但 enabled 模式不允许该 ambiguity fallback。
- 新行为发布后，当前已经持久化的八项请求通过现有“取消计划”流程结束，再创建新计划会话以使用 v2；不得直接更新该 request JSON。
- 发布新的 immutable `tutor.learning-plan-draft` Skill 版本并更新选择策略，不修改 1.0.1。

### R8：文档、可观察性和防回归

- 同步 source-of-truth 中 planning intent、dynamic presentation、provider contract 和 QA 条目。
- Safe reason codes 必须区分 explicit、deterministic intent、semantic shortlist、clarification required、invalid hint 和 feature-off rollback。
- 加入 LangChain、LangChain4j、模糊 Agent、明确 Python、多候选、低置信、无效候选和 durable replay 回归测试。

## Acceptance Criteria

- [x] AC1：输入“我想做langchain架构的agent”不会显示八项全目录，只生成 Python 窄候选并要求用户确认；Java 不出现。
- [x] AC2：输入明确 `Python` 时仍 deterministic auto-confirm，不显示语言选择器。
- [x] AC3：输入明确 `LangChain4j` 但未写 `Java` 时，模型可生成仅含 Java 的语义窄候选，但不得自动确认。
- [x] AC4：输入“我想做一个 Agent”且无法可靠确定实现语言时，生成一个 clarification text request，不生成 full catalog。
- [x] AC5：语义 hint 只能引用 active server candidate values，最多 3 项；unknown、duplicate、inactive、stale、extra field 被拒绝且不扩大候选。
- [x] AC6：语义候选 `recommended=null`，Desktop 初始无选中、提交禁用；选择后只提交持久 presentation 中的 exact value。
- [x] AC7：刷新、SSE reconnect、history replay 保留同一请求的候选和顺序；已有 full-catalog request 仍按历史内容读取。
- [x] AC8：Feature enabled 下没有 `no_intent_signal -> full_catalog` 路径；feature-off rollback 明确标记且保持兼容。
- [x] AC9：模型输出、TutorDecision、decision gate、persistence 和 public DTO 对 hint/scope/reason exact 对齐，raw rationale/UUID 不公开。
- [x] AC10：新 Skill bundle 通过 raw-byte hash/catalog tests；旧 1.0.1 未修改。
- [x] AC11：相关 API/Tutor/learning-plan tests、Ruff、Mypy、Desktop tests/check、Trellis validate 和 `git diff --check` 通过。
- [x] AC12：默认验证无真实 provider 调用；实现完成后当前计划只通过 cancel/recreate 使用新策略，不篡改 pending request。

## Out of Scope

- 让模型创建课程、修改语言 capability、联网搜索框架或自动扩展课程目录。
- 在线自学习 framework alias、未经审核地把用户文本写入全局分类规则。
- 自动确认任何只由模型推断出的语言。
- 修改历史 pending request、历史 snapshot 或已发布 Skill 1.0.1。
- 新增独立推荐页面、重做语言选择 UI 或变更学习计划字段集合。
- 真实 provider smoke、部署、push 或生产数据迁移，除非另行批准。

## Verification Evidence — 2026-09-03

- 语义主路径已覆盖：LangChain 仅生成 Python 人工确认窄候选；LangChain4j 仅生成 Java 人工确认窄候选；模糊 Agent 生成定向 clarification；明确 Python 仍 deterministic auto-confirm。
- Provider hint v2、Harness `TutorDecision`、decision gate、Codex 两次工具调用协议与 persistence 重算使用同一 server-built active candidate authority；无效、重复、inactive、stale、extra 和超过 3 项的候选均 fail closed。
- Feature enabled 模式不存在 ambiguity 到 full catalog 的回退；feature-off 明确保留 `full_catalog` / `feature_off_rollback` 兼容路径。
- 聚焦 PostgreSQL 回归：`24 passed in 45.97s`。
- 隔离全量 API 回归：`891 passed, 2 skipped in 691.29s`。首次在开发 worker 运行时出现的漂移失败均可单独通过；停止共享 worker 后全量通过，确认是共享数据库并发干扰而非本任务回归。
- API 静态门禁：Ruff 通过；Mypy 对 248 个 source files 通过；`uv lock --check` 通过。
- Desktop：24 个测试文件、161 个测试通过；`pnpm --dir ./aearn desktop:check` 通过。
- Skill Catalog：9 个 Skill 编译通过，新 digest 为 `8714c4a01714005a78f6f00cf452e69b5ca91e7cbf7d7e262f83e6596e47a9b9`；1.0.2 三个文件均由 `.gitattributes` 强制 LF；1.0.1 未由本任务修改。
- Trellis validate 与 `git diff --check` 通过；本轮未调用真实 provider，也未修改、取消或重写当前已持久化的八项 pending request。
