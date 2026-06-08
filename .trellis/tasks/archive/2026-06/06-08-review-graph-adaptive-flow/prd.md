# Review graph adaptive flow

## Goal

把复习页从“热身 + 单个变体题 + 立即 FSRS 结算”的线性流程，升级为后端主导的 graph 复习批次流程：先热身诊断，再按最低阈值生成/选择正式题，之后在每题完成后更新 session 内用户状态并动态调整剩余题型和数量，最后只在整轮复习结束时更新 `ReviewState` / FSRS。

用户价值：

- 复习不再像一次孤立测验，而是围绕同一知识点做一组足够覆盖的题。
- 题目由模型按用户状态动态生成，不使用写死题目或固定内容兜底。
- 用户每次跳过、模糊、错误或通过都会影响本轮后续题型，但不会失去后续复习机会。
- 复习体验在前端上像学习页一样由当前 graph node 驱动渲染，而不是前端自行拼流程。

## Confirmed Facts

- 当前后端已有 `aearn/services/api/app/agents/graphs/review_graph.py`，但它是单步路由/编排骨架，只返回 `start_session`、`submit_and_update`、`warmup`、`coach_feedback` 等意图，不持有完整复习批次状态。
- 当前 `POST /api/reviews/start` 会创建或复用一个 `LearningSession(session_type=review)`，确保 `review_seed_banks` ready，选择一个 seed，物化一个 `review_exercise`，并返回 `review_stage=warmup`。
- 当前 `POST /api/reviews/{session_id}/warmup-result` 只写 `LearningSession.review_stage_state_json`，不会创建 `Attempt`、不会写 `ReviewLog`、不会更新 FSRS。
- 当前 `POST /api/reviews/{session_id}/exercise-result` 在一次正式题提交后立即写 `Attempt(review_submit)`，调用 `apply_attempt_review_update(...)` 更新 `ReviewState` / FSRS，并把 session 标记为 `finished` / `submitted`。
- 当前 DB 只允许复习阶段 `warmup`、`warmup_repair`、`variant_practice`、`submitted`，还没有批次内多题阶段、候选池、当前题索引、完成题列表或 session 级诊断状态的结构化约束。
- 当前前端 `ReviewPage.tsx` 一次只持有一个 `review_exercise`，热身后渲染单个练习工作台，提交成功后展示 `due_at` / `forget_risk` / FSRS 结果。
- 当前复习消息历史已通过 `GET /api/reviews/{session_id}/messages` 回放，前端开始复习时会尝试恢复历史消息。
- `review_seed_bank.py` 已经支持模型生成 seed bank，并按 runtime 能力、用户弱点、最近 FSRS、最近 attempt 等上下文生成和选择复习 seed。
- 产品文档当前描述的是“短热身 + 单个变体题 + 提交后更新 FSRS”，需要随本任务更新为“批次复习 + 最终结算”。
- 现有边界要求仍然成立：前端不计算评分、FSRS、`due_at` 或遗忘风险；模型不直接决定持久化、最低题量、FSRS 或完成状态；后端负责 schema 校验、状态推进、裁剪和持久化。

## Requirements

- 复习流程必须由后端 graph/session state 驱动，前端只渲染当前 node 和后端返回的可操作状态。
- graph 必须覆盖至少这些阶段：`start_review_session`、`present_warmup`、`diagnose_warmup`、`build_baseline_pool`、`select_next_exercise`、`submit_exercise_attempt`、`diagnose_attempt`、`adapt_remaining_plan`、`finalize_review_batch`。
- 热身默认 1 题，最多 2 题；`clear` 直接进入正式复习；`fuzzy` / `wrong` 增加一次短修正后进入正式复习；`skipped` / “完全忘了” 不强制回学习页，只降低正式复习难度并保留后续复习机会。
- 热身诊断必须以结构化字段表达，例如 `recall_level=clear|fuzzy|wrong|skipped`、`confidence`、`evidence`、`missing_points`、`misconception`、`suggested_focus`；模型可填写诊断建议，后端必须规范化和兜底。
- 正式复习必须有最低题量阈值：默认至少 3 题，常规 3-4 题，高风险 4-5 题，单轮最多 6 题。
- 最低题型覆盖必须至少包含基础掌握题、概念表达题、迁移/审查题三类能力中的组合；具体题型可在 `code_blank`、`fix_bug`、`explain_code`、`implement_function`、`review_ai_patch` 中选择。
- 题目池和候选题池都必须由模型按 JSON schema 生成，且适配用户知识点、弱点、最近 attempt、warmup 诊断、runtime 能力和本轮已答情况；不得回退到硬编码固定题目。
- 候选池必须先于正式题执行完成预生成，默认在复习会话开始时由后端持久化或命中已有 ready pool；只有当当前 pool 不足以覆盖 session-local 弱点或类型配比时，才补生成 adaptive supplement。
- 候选池必须携带覆盖矩阵和选择元数据，例如 `capability`、`target_misconception`、`focus_tags`、`recommended_for`、`avoid_if`、`difficulty`、`exercise_type`、`metadata.selection_reason`，以便 graph 可以无模型地快速选题。
- 候选池的最小设计目标是“题量足够 + 覆盖足够 + 可裁剪”；它不是最终展示列表，也不是固定轮换顺序。
- 后端必须校验模型输出的 schema、知识点归属、题型、runtime 能力、数量上下限、安全字段和 hidden-answer 泄露风险；校验失败不能展示低质量 fallback 题。
- 每题提交后必须写入可追溯 attempt / 练习结果事实，并更新 session 内诊断状态；但最终 `ReviewState` / FSRS 只能在整轮复习结束时更新一次。
- 每题后的用户状态更新只写 session-local 诊断状态，例如 `LearningSession.review_stage_state_json` 中的当前能力、弱点、已完成题和剩余计划；不得逐题写入长期 `learner_profile` 或全局掌握状态。
- 每题完成后 graph 必须可以调整剩余题型和数量：从现有候选池选择，或请求模型生成 adaptive supplement。
- 多次跳过热身或低表现不得导致复习机会消失，也不得强制用户重新进入学习页；后端应通过更低难度、更多基础题、短间隔或高风险标记保证后续复习。
- 用户在复习中途主动退出时，必须保留为未完成 `review` session；已完成题目和诊断状态可恢复，但不更新 FSRS，也不把本轮标记为完整复习批次。
- `review_ai_patch` 仍使用结构化审核答案，必须保留 `verdict`、`evidence`、`knowledge_point_risk`、`next_action` 和证据质量评分边界。
- 整轮最终 `fsrs_rating` 必须由后端基于本轮表现灵活聚合：综合正式题通过率、题型难度、解释质量、warmup 诊断、跳过次数、核心题失败和历史弱点；不能简单取平均，也不能让模型直接决定最终 rating。核心概念明显失败时不得给 `Easy`，但允许整体稳定表现抵消单个非核心小错误。
- 复习历史对话回放必须覆盖本轮热身、每题反馈、用户追问和最终总结，且跨用户 session mismatch 继续返回 `SESSION_NOT_FOUND`。
- 前端复习页必须复用学习页练习卡片/工作台的视觉和交互模式；热身通过对话/模型提问呈现，不做独立练习卡片。
- 空白/图标加载策略保持简洁，不用额外复杂 loading 卡片。

## Acceptance Criteria

- [ ] 创建父任务下的子任务地图，至少覆盖后端 graph/session state、模型题池 schema 与校验、逐题自适应与最终 FSRS 结算、前端 graph node 渲染、测试与文档收口。
- [ ] 文档中的 Review Graph、复习页用户流程和前端交互规格都从单题复习更新为批次复习，并明确最终 FSRS 只结算一次。
- [ ] 后端支持一轮复习内多道正式题，且 session state 能恢复当前题、已完成题、候选池、warmup 诊断和剩余计划。
- [ ] warmup 的 `clear`、`fuzzy`、`wrong`、`skipped` 分支都有测试覆盖，并证明 warmup 不写 `Attempt`、不写 `ReviewLog`、不更新 `ReviewState`。
- [ ] 每题提交后可以返回下一题或结束决策；中间题提交不会更新 `ReviewState.review_count`、`due_at`、`last_attempt_id` 或 `ReviewLog`。
- [ ] 每题提交后的诊断更新只影响本轮 session-local 状态；长期 learner profile、KnowledgePoint 掌握摘要和 FSRS 只在完整复习批次 finalize 时更新。
- [ ] 整轮结束时只发生一次 FSRS 更新，并能基于整轮 attempts 聚合出最终 rating / weak points / next due。
- [ ] 最终 `fsrs_rating` 聚合测试覆盖灵活分支：单个非核心失误但整体稳定可得到 `Good`，核心能力失败不能得到 `Easy`，多次跳过或高风险弱点会压低到 `Hard`/`Again`。
- [ ] 用户中途退出后再次进入同一到期知识点，会恢复未完成 session、当前题、已完成题、候选池和历史消息；恢复过程不创建新的复习批次，也不更新 FSRS。
- [ ] 模型生成 baseline pool 和 adaptive supplement 都有 schema 校验测试；非法、越权、数量不足、题型不支持或泄题输出会失败且不展示 fallback 题。
- [ ] 候选池 JSON 具备覆盖矩阵和选择元数据，后端能在不重新调用模型的情况下完成大部分下一题选择。
- [ ] 前端能按后端返回的当前 node 渲染热身、正式练习、逐题反馈、下一题、最终总结和历史回放，不本地计算调度或完成态。
- [ ] `review_ai_patch`、普通代码题、解释题都能在批次流程里被提交、记录、反馈和进入下一题选择。
- [ ] 现有回归命令保持通过，至少包括 `tests/test_reviews_m4.py` 相关批次和 `pnpm --dir .\aearn desktop:check`。

## Proposed Child Tasks

- `review-graph-session-state`：扩展后端 graph、review session state、DB 约束/迁移和 API response contract。
- `review-candidate-pool-generation`：定义 baseline/adaptive 题池 JSON schema、模型 prompt、校验器和持久化策略。
- `review-rolling-adaptation-and-finalization`：实现逐题提交、诊断聚合、剩余题调整和整轮最终 FSRS 结算。
- `review-page-graph-node-ui`：前端按 graph node 渲染，复用学习页练习工作台，修复热身/输入栏/加载/历史回放体验。
- `review-flow-tests-and-docs`：集中更新文档、回归测试、端到端场景和收口检查。

## Out Of Scope

- 不改变学习页 graph 的教学主流程，除非为了复用组件或合同类型做小范围抽取。
- 不允许前端计算 `score`、`fsrs_rating`、`due_at`、`forget_risk` 或最终复习完成态。
- 不把模型作为 FSRS、最低题量、due-state 或持久化结果的最终决策者。
- 不引入硬编码固定复习题作为兜底。
- 不改变未到期复习项不能绕过 `REVIEW_NOT_DUE` 的规则。
- 不在父任务直接实现全部代码；父任务只维护需求、子任务地图和集成验收。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.

## Decisions

- 用户主动中途退出时，保留为未完成 session，不更新 FSRS；用户下次回到同一到期知识点时继续该 session。
- 每题后只更新 session-local 状态，不即时写入长期 learner profile；完整批次 finalize 后再统一合并长期画像、知识点状态和 FSRS。
- 最终 `fsrs_rating` 采用灵活后端聚合策略，不走绝对保守压分；整体稳定表现可抵消非核心小错，但核心失败、连续跳过或明显高风险仍会限制最终评级。
- 候选池优先预生成并命中已有 ready pool；只在覆盖不足时补生成 adaptive supplement。
