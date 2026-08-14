# 技术设计

## 数据模型

新增 `tutor_run_pending_inputs`，包含 run/user/conversation scope、input revision、continuation kind、question key、schema version、presentation/validation JSON、pending/resolved/superseded/cancelled state 和时间戳。约束一个 run 最多一个 unresolved projection，并使用 composite FK 防止跨用户/会话引用。

## Public contract

`TutorForegroundRun` 和 run read 增加 nullable `pending_input`：

```ts
type TutorPendingInput = {
  pending_input_id: string;
  schema_version: "tutor_pending_input_v1";
  run_id: string;
  input_revision: number;
  continuation_kind: TutorContinuationKind;
  question_key: PlanningQuestionKey | null;
  required: true;
  presentation: TutorPendingInputPresentation;
};
```

presentation 是 text/single_select/multi_select discriminated union。public payload 只包含 learner-safe title/detail/options/limits，不含 provider trace、prompt、rubric 或内部 validation implementation。

## Catalog

新增 `services/learning/planning_questions.py`：

- exact `PlanningFactField` key -> immutable template/version。
- `language_id` 从发布课程 catalog 按 stable id 构造。
- `target_level`、`experience_level`、`weekly_minutes`、`teaching_preferences` 使用 allowlisted options。
- `goal_text`、`pace_constraints` 使用 bounded text。
- catalog 输出与 `normalize_planning_fact()` 使用同一服务端 value contract，避免 UI 与 persistence 各写一套规则。

## Run-loop 接缝

当 approved decision 包含 continuation：

1. decision gate 验证 kind/key 组合。
2. 对 planning scope，`planning_input` 必须是 missing/unconfirmed field；`clarification` 不携带 planning fact key。
3. 服务端构造 pending projection。
4. lifecycle 持久化 waiting result 与 pending item 后释放 lease。
5. history/run/SSE 读取 projection。

## Answer transaction

`POST /runs/{run_id}/inputs` 对 typed continuation 增加 `pending_input_id` 与 `expected_input_revision`：

- 锁 run + pending item。
- 验证 ownership/state/version/kind/key。
- 验证 `planning_facts` 只含当前 key 且值有效。
- 调用现有 input/planning fact persistence。
- 标记 resolved 并将 run 恢复 queued、清 continuation/pending。
- idempotency record 包含 pending identity 和结构化 body hash。

## Prompt migration

对原始工作树相关 prompts/skills 做 hunk 级迁移。contract tests 静态检查 examples 存在，并用 fake provider decisions 验证：

- 普通歧义 -> `clarification`。
- 缺 required planning fact -> `planning_input + exact question_key`。
- 有风险动作授权 -> `approval`。
- confirmed key 重问 -> decision gate denied。

## 兼容

旧 run/history 没有 pending row时 `pending_input=null`；旧 continuation kind 仍可解析。新增 request 字段只在 typed continuation required，普通旧客户端 path 不受影响。

## 回滚

代码回滚保留 additive table；旧 API 忽略 nullable projection。不得 drop 已有 pending rows，避免恢复时丢失用户等待状态。
