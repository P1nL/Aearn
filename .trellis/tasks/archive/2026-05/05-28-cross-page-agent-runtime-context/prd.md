# Design reusable Agent runtime context layer

## Goal

参考 `earendil-works/pi` / `pi-agent-core` 的 `transformContext`、LLM context conversion、stateful runtime 思路，为 Aearn 设计一个可复用的 Agent runtime/context layer。

目标不是把 TypeScript 的 `pi-agent-core` 直接引入 Python 后端，而是把它的架构模式移植成 Aearn-owned Python 层，让学习页、建档页和复习页可以共享安全上下文治理、SDK 调用、guardrail、fallback 和测试模式，同时保留各页面自己的产品契约。

## User Value

- 学习页不再是一次性 prompt 拼装，而是有连续上下文的导师对话。
- 建档页可以复用同一套安全摘要/近期上下文机制，让路线生成能承接用户前几轮目标澄清。
- 复习页可以复用同一套 context pipeline，让复习教练承接弱点、最近尝试和复习原因，而不复制学习页代码。
- 后续 Agent 页面不需要各自重新实现 SDK runner、message sanitization、summary refresh、guardrail fallback 和 fake runner tests。

## Confirmed Facts

- Aearn 当前采用 `application-on-SDK`，通过 `openai-agents==0.17.3` 构建 Aearn-owned Agent 模块，而不是 fork 或 vendor upstream SDK。
- 共享 SDK runtime 已在 `aearn/services/api/app/agents/sdk_runtime.py`，提供 `build_agent`、`stream_text_deltas`、`AgentsSDKRunner`、provider config 和 streaming error normalization。
- 学习页 SDK client 在 `aearn/services/api/app/agents/learning_conversation_agent.py`，由 `learning_conversation.py` 的 `TextCompletionClient` 边界调用。
- 建档页 SDK client 在 `aearn/services/api/app/agents/onboarding_plan_agent.py`，当前围绕 `PlanDraft` JSON candidate 和 server-owned course template 校验。
- 复习页 SDK client 在 `aearn/services/api/app/agents/review_coach_agent.py`，当前生成 `variant_reason` 与 `initial_agent_message`，但 FSRS、ReviewState 和 Attempt 写入仍由 Aearn repository 拥有。
- 学习页已经有页面专属的 `conversation_summary`、`safe_summary`、`recent_safe_messages`、threshold refresh 和 `learning_stage_state_json` persistence。
- `docs/architecture/api-contract.md` 明确 AI 驱动接口模型不可用或 guardrail 阻断时返回 `MODEL_UNAVAILABLE`，不得泄露 SDK event name、provider raw error、API key、hidden test、`solution_reference` 或完整提交代码。
- `docs/qa/sdk-agent-release-readiness.md` 已把 Teaching Agent、Exercise Coach、Note Assist、Review Coach、Onboarding Plan Agent 的 SDK 测试矩阵和 state ownership 边界列为 release gate。

## Requirements

- 设计一个 Aearn-owned reusable Agent runtime/context layer，而不是直接引入 `@earendil-works/pi-agent-core`。
- 参考 `pi-agent-core` 的核心思想：
  - app-specific messages 先转换为 safe context；
  - 旧上下文压缩为结构化 summary；
  - 最近消息保留少量原始语气；
  - 每个 domain 再转换为 LLM input；
  - runtime 统一处理 streaming、guardrails、fallback 和 state ownership。
- 第一阶段覆盖学习页、建档页和复习页。
- 第一阶段不纳入 Note Assist；Note Assist 作为共享 runtime 成熟后的第二阶段 follow-up。
- 学习页保留 learning-specific summary schema，例如学习目标、当前卡点、误解、已解释概念、上一轮诊断、下一步。
- 建档页需要自己的 onboarding summary schema，例如目标澄清、语言/水平/时间预算槽位、用户偏好、已拒绝方向、当前 plan draft 状态。
- 复习页需要自己的 review summary schema，例如 due reason、weak points、最近可见 attempt facts、variant rationale、推荐复习策略。
- 共享层必须允许 domain-specific policy 注入，不能把学习页的 concept-first 策略硬套到建档页或复习页。
- 共享层必须统一 sanitization/guardrail/fallback 行为，避免每个页面重复实现泄露防护。
- 共享层必须保持 public API/SSE contracts 不变。
- 共享层不得接管 Aearn durable writes：
  - `LearningPlan` / `PlanModule` / `KnowledgePoint` / `ReviewState` 创建仍由 plan repository/service 负责；
  - `LearningSession` / `LearningMessage` / `Attempt` 写入仍由 learning service/repository 负责；
  - `ReviewState` / `ReviewLog` / FSRS 更新仍由 review scheduler/repository 负责。
- 共享层可以产生候选输出、safe summaries、context blocks 和 normalized SDK results，但不能绕过现有 service/repository 校验。
- 测试必须保持 model-key-free，使用 fake SDK runner/client 覆盖成功、失败、非法输出、guardrail blocked 和 fallback。
- 第一版不要求新增数据库表；如果需要持久化跨页面 summary，优先复用现有 domain state JSON 或明确提出最小 migration。

## Acceptance Criteria

- [ ] `prd.md` 明确 reusable runtime/context layer 的目标、范围和不直接引入 TypeScript package 的边界。
- [ ] `design.md` 定义共享 runtime pipeline、domain adapter、summary strategy、guardrail/fallback、state ownership 和 API compatibility。
- [ ] `design.md` 覆盖学习页、建档页、复习页三个 domain 的 context shape 差异。
- [ ] `implement.md` 给出分阶段实施顺序，先抽共享基础，再迁移学习页，再接建档页和复习页。
- [ ] 设计证明 public JSON/SSE contracts 不变，模型不可用仍映射为 `MODEL_UNAVAILABLE`。
- [ ] 设计证明 shared layer 不写 `LearningPlan`、`ReviewState`、`Attempt`、`Note` 或幂等记录。
- [ ] 设计包含 no hidden tests、no `solution_reference`、no provider raw errors、no SDK event names、no API key 的统一安全验收。
- [ ] 设计包含 model-key-free 测试矩阵，至少覆盖 `tests/test_llm_integration.py`、`tests/test_learning_sessions_m3.py`、`tests/test_onboarding_m2.py`、`tests/test_reviews_m4.py` 的相关路径。
- [ ] 任务在用户审核规划前保持 `planning`，不启动 implementation。

## Out Of Scope

- 直接安装或运行 `@earendil-works/pi-agent-core`。
- fork、vendor 或修改 `openai/openai-agents-python`。
- 重写 FastAPI routes、Tauri frontend、PostgreSQL schema 或 FSRS scheduler。
- 把最终评分、runner execution、review scheduling、confirm-plan durable writes 移入 SDK Agent。
- 第一阶段不纳入 Note Assist；Note Assist 可作为同一 runtime 成熟后的 follow-up。
- 真实 provider quality benchmark 和生产部署。

## Decisions

- 第一阶段范围已确认：学习页、建档页、复习页。
- Note Assist 不纳入第一阶段，作为第二阶段 follow-up。
