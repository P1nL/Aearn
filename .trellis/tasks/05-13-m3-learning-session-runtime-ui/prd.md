# M3 learning sessions, runner, attempts, and generated exercise UI

## Goal

在现有 M1/M2 基线上完成 full M3：用户从已创建学习计划进入当前知识点，会话返回一题生成式代码练习，前端支持运行预览、运行可见测试、获取提示、解释错误、检查解释和提交评分，后端写入可追溯 `Attempt(run)` / `Attempt(submit)`，并返回符合规格的 `code_completion_result`。

## Background / Known Context

- 当前工作树已落地 M1/M2：
  - `aearn/services/api/app/main.py` 已注册 health、users、courses、plans 路由。
  - `aearn/services/api/app/db/schema.sql` 已包含 `learning_sessions`、`attempts`、`review_states`、`exercises` 等 M3 所需表及补充字段。
  - `aearn/services/api/tests/test_onboarding_m2.py` 已覆盖 M2 API 契约与幂等路径。
- 本次 full M3 的 source of truth：
  - `docs/plans/learning-agent-implementation-plan.md`
  - `docs/product/frontend-interaction-spec.md`
  - `docs/architecture/api-contract.md`
  - `docs/architecture/code-completion-evaluation-spec.md`
  - `docs/architecture/langgraph-state-machine.md`
  - `docs/qa/acceptance-test-plan.md`

## Requirements

- 在 `aearn/services/api/` 中实现学习会话相关模型、路由和服务，覆盖：
  - `POST /api/learning-sessions/start`
  - `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run`
  - `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint`
  - `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`
  - `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation`
  - `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit`
- `start` 必须创建或复用活动 `LearningSession(session_type=learn)`，并返回当前 `Exercise`、`RuntimeProfile`、知识点上下文和初始 Agent 文案。
- `run` 必须依据 `runtime_tier` 返回可区分的 `runtime_status`，并写入 `Attempt(attempt_type=run)`；`run` 不更新 `ReviewState`。
- `hint` 必须按 `nudge` / `concept` / `code_shape` 分层返回提示，并以幂等方式增加 `hint_usage_count`。
- `explain-error` 必须基于真实错误上下文或失败测试返回 `error_cause`、解释和修正建议，不得伪造成功路径。
- `check-explanation` 必须最多支持 2 轮，写回 `Attempt.explanation_text` 与 `Attempt.explanation_check_result`。
- `submit` 必须生成符合 `code-completion-evaluation-spec.md` 的 `code_completion_result`，并综合运行结果、提示次数、错误次数和 explanation-check 结果写入 `Attempt(submit)`，再回写 `KnowledgePoint` 与 `ReviewState`。
- 前端必须把当前 M2 workspace 升级为 full M3 工作台，展示：
  - 当前知识点入口
  - 生成式练习卡片
  - 代码编辑区
  - 运行预览与运行可见测试动作
  - 提示历史、错因解释、解释检查面板
  - 运行/提交结果摘要
  - stale / loading / error / retry / disabled 说明
- 前端不得暴露 `Attempt(run)` / `Attempt(submit)` 内部类型。
- Java/C++ 的 `compiled_sandbox_later` 路径必须体现能力边界，不能伪装成可运行。
- 必须新增或更新自动化测试，覆盖 full M3 的核心契约与关键失败路径。

## Acceptance Criteria

- [x] 已确认学习计划的用户可以从桌面端进入当前学习会话，并拿到 `session_id`、上下文和一题 `Exercise`。
- [x] JS/HTML/CSS 与 Python 的 M3 运行路径都可区分 `success` / `runtime_error` / `timeout` / `unsupported` 边界中的已实现部分。
- [x] `hint`、`explain-error`、`check-explanation` 三条 API 可调用，且幂等与轮次规则符合契约。
- [x] 成功提交后返回结构合法的 `code_completion_result`，并生成一条 `Attempt(submit)`。
- [x] `submit` 会更新 `KnowledgePoint.last_exercise_result`、`KnowledgePoint.last_exercise_score` 和 `ReviewState.last_attempt_id`。
- [x] 当解释检查失败、提示过多或核心空缺错误时，评分与 `next_action` 会按规则降级。
- [x] 前端能显示运行/提交结果、提示历史、错因解释和 explanation-check 结果，但不会显示内部 Attempt 类型名称。
- [x] 旧运行结果在代码修改后会被标记 stale，预览-only 结果不会冒充可直接提交的测试结果。
- [x] `compiled_sandbox_later` 路径不会给出误导性的“可运行”承诺。
- [x] 已通过 full M3 对应的后端契约测试、前端构建检查与浏览器 smoke。

## Definition of Done

- 与本次实现对应的 `prd.md`、`design.md`、`implement.md` 已补齐并可审查。
- 相关测试、构建和浏览器 smoke 已运行并记录结果。
- 如果实现对文档规格做了保守收缩或保留后续项，已在任务文档中说明。

## Out of Scope

- M4 FSRS 完整调度、review queue 和复习闭环。
- M5 笔记抽屉、笔记页和 note assist 的完整产品闭环。
- Settings、dashboard、resume 的完整 M6 行为。
- 与 M3 工作台契约无关的视觉 polish 或额外页面重构。

## Research References

- `docs/plans/learning-agent-implementation-plan.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/code-completion-evaluation-spec.md`
- `docs/architecture/langgraph-state-machine.md`
- `docs/qa/acceptance-test-plan.md`

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- 这次任务从 minimal slice 扩展为 full M3，因此 task 文档必须明确包含 `hint` / `explain-error` / `check-explanation` 与 FE-02 状态矩阵。
