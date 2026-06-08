# Review candidate pool generation

## Goal

把当前 `review_seed_bank_model_v2` 单题 seed bank 升级为批次复习可用的 `review_candidate_pool_v1` 候选池合同：模型按 JSON schema 生成足量候选题，后端做 schema、覆盖、runtime、安全和泄题校验，并把 graph 后续选题所需的 capability / focus / recommended / avoid / selection metadata 持久化到 `review_seed_banks.seeds_json`。

用户价值：

- 复习批次开始前已有一组可裁剪的候选题，而不是每次只选一个变体题。
- 后续 graph 可以优先从 ready pool 快速选题，减少模型调用和等待。
- 候选题能明确说明覆盖能力、目标误解、适用场景和避用条件，支持逐题自适应。
- 无效模型输出不会退回硬编码题目，也不会把泄题或不支持的题展示给用户。

## Parent Dependency

父任务：`.trellis/tasks/06-08-review-graph-adaptive-flow`

必须继承的父任务决策：

- 题目池和候选题池都由模型按 JSON schema 生成，后端校验和选择；不得回退到硬编码 fallback 题。
- baseline pool 优先预生成并复用 ready pool；只有覆盖不了当前 session-local 弱点时，后续子任务才生成 adaptive supplement。
- baseline pool 继续优先复用 `review_seed_banks.seeds_json`；adaptive supplement 由后续 graph/session state 子任务存入 `LearningSession.review_stage_state_json`，避免污染长期候选池。
- 候选池必须携带覆盖矩阵和选择元数据，以便 graph 大部分情况下无需重新调用模型即可选题。
- 本子任务不启动父任务实现，不修改前端 graph node 渲染，也不实现最终 FSRS 结算。

## Confirmed Facts

- 当前共享 worker core 在 `aearn/services/worker/aearn_worker/review_seed_bank_core.py`，`GENERATOR_VERSION` 是 `review_seed_bank_model_v2`，校验要求普通 8-12 个 seed，高风险 12-16 个 seed，并检查数量、题型、知识点归属、difficulty、重复、`review_ai_patch` metadata/rubric 和泄露风险。
- 当前 API repository 在 `aearn/services/api/app/services/repositories/review_seed_bank.py`，负责生成上下文、prompt、模型 JSON 调用、`_seeds_from_generated(...)` 规范化、`select_review_seed(...)` 和 `materialize_review_seed_exercise(...)`。
- 当前 `review_seed_banks` 表已存在，`seeds_json` 保存完整 seed 列表，唯一索引是 `(user_id, knowledge_point_id, generator_version)`。
- 当前 `POST /api/reviews/start` 会确保 ready seed bank，选择一个 seed，物化一个 `review_exercise`，并返回 `seed_bank`、`selected_seed_id`、`review_exercise` 和 `review_stage=warmup`。
- 当前测试 `aearn/services/api/tests/test_reviews_m4.py` 已覆盖模型生成上下文、seed bank ready、生成失败不展示 fallback、warmup 分支不写 FSRS。
- 当前 docs 仍描述 seed bank 和单题 `variant_practice`，本子任务只更新与 candidate pool schema/seed bank 直接相关的文档；批次 review flow 文档收口由后续 `review-flow-tests-and-docs` 子任务完成。

## Requirements

- 引入新的生成器合同版本，建议为 `review_candidate_pool_v1`，使新候选池与旧 `review_seed_bank_model_v2` ready rows 能通过 `generator_version` 清晰区分。
- baseline pool 仍持久化在 `review_seed_banks.seeds_json`，本子任务不新增全局候选池表。
- 普通知识点 baseline pool 目标为 10-12 个候选题；高风险知识点目标为 12-16 个候选题；硬上限 18 个候选题，除非后续验证证明更高数量必要。
- 候选题必须保留现有可物化字段：`id`、`knowledge_point_id`、`exercise_type`、`difficulty`、`title`、`prompt_markdown`、`starter_code`、`code_blanks`、`test_cases`、`metadata`。
- 候选题必须新增或规范化选择字段：`capability`、`target_misconception`、`focus_tags`、`recommended_for`、`avoid_if`、`metadata.selection_reason`、`metadata.is_core`。
- `capability` 至少支持 `basic_application`、`concept_explanation`、`debugging`、`transfer_or_review`，并能映射到 `code_blank`、`fix_bug`、`explain_code`、`implement_function`、`review_ai_patch`。
- `recommended_for` 必须能表达适用的 recall level、weak points 和 previous result；`avoid_if` 必须能表达已掌握 focus tags、近期候选题或不适用 runtime/题型条件。
- 模型 prompt 必须说明候选池是“可裁剪 pool”，不是展示顺序；模型不得决定最终题量、FSRS、due state 或 session 完成态。
- 生成上下文必须继续包含 runtime profile、supported exercise types、knowledge point、weak points、mastery、latest attempt、last FSRS 和高风险信号；允许为后续 adaptive supplement 预留 `session_diagnosis` / `warmup_diagnosis` 输入字段，但本子任务不负责接入 graph。
- 后端必须校验数量、schema required fields、枚举、知识点归属、runtime 支持题型、capability 覆盖、focus tag 基本质量、重复内容、difficulty 范围、`review_ai_patch` rubric、hidden-answer / raw prompt / provider error / secret 泄露。
- 校验失败必须保持现有 no-fallback 行为：持久化 failed seed bank，返回稳定错误，不返回 `review_exercise`。
- `quality_report_json` 必须记录候选数量、exercise type 覆盖、capability 覆盖、core/non-core 数量、安全校验、generator/prompt version 和 adaptation inputs。
- `materialize_review_seed_exercise(...)` 必须把选择元数据带入 `exercises.metadata_json.review_seed` 或相邻 metadata，供后续 graph/session state 子任务追踪已选候选题。
- `select_review_seed(...)` 可以保持兼容旧单题 API 的临时选择，但必须优先利用新 metadata，并为后续 graph 的多题 selector 留出明确 helper/contract。
- 现有 `/api/reviews/start` 兼容字段在本子任务中保持可用：`seed_bank`、`selected_seed_id`、`review_exercise`、`warmup` 不因 schema 升级被破坏。

## Acceptance Criteria

- [ ] `review_candidate_pool_v1` 的 generator version、prompt version、response shape 和 required fields 在代码中有单一 source of truth。
- [ ] `review_seed_banks.seeds_json` 能保存包含 `capability`、`focus_tags`、`recommended_for`、`avoid_if`、`metadata.selection_reason`、`metadata.is_core` 的候选题。
- [ ] 普通 baseline pool 生成 10-12 个候选题，高风险 baseline pool 生成 12-16 个候选题，超过硬上限或低于下限都会被拒绝。
- [ ] 校验覆盖 unsupported exercise type、wrong `knowledge_point_id`、invalid difficulty、missing capability、missing selection metadata、duplicate prompt/code、hidden-answer leakage、invalid `review_ai_patch` metadata/rubric。
- [ ] `quality_report_json` 至少包含 `candidate_count`、`exercise_types`、`capabilities`、`core_candidate_count`、`focus_tag_count`、`generation_source`、`generation_model`、`prompt_version`、`adaptation_inputs` 和 `safety=validated`。
- [ ] `POST /api/reviews/start` 命中或生成 ready candidate pool 后仍能返回兼容的 `review_exercise`，并且该 exercise metadata 能追溯 `seed_bank_id`、`candidate_id`、`capability`、`focus_tags`、`selection_reason`。
- [ ] 模型不可用、返回非法 JSON、数量不足、覆盖不足或泄露风险时返回 `REVIEW_SEED_BANK_GENERATION_FAILED` / 现有稳定错误，不返回 fallback `review_exercise`。
- [ ] 现有 warmup 不写 `Attempt` / `ReviewLog` / `ReviewState` 的回归测试继续通过。
- [ ] 为新 schema 增加 focused unit/API tests，并保持 `tests/test_reviews_m4.py -k "seed_bank or candidate or review_start"` 相关批次通过。

## Notes

- 本子任务是复杂任务，需要 `design.md` 和 `implement.md` 后才能 `task.py start`。
- 子任务之间的依赖必须写在各自 artifacts 中，不能只依赖父子目录关系。

## Out Of Scope

- 不实现 `LearningSession.review_stage_state_json` 的 batch state、当前题索引、已完成题列表或 session-local diagnosis。
- 不实现 adaptive supplement 的运行时生成和 session-state 存储；本子任务只定义兼容 schema 和 validation helper。
- 不拆分每题提交与最终 FSRS 结算；该逻辑属于 `review-rolling-adaptation-and-finalization`。
- 不重构 `ReviewPage.tsx` 为 backend `current_node` 渲染；该逻辑属于 `review-page-graph-node-ui`。
- 不新增硬编码 fallback 题。
