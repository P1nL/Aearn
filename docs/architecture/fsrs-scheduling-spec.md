# FSRS 调度实现规格

日期：2026-05-11  
状态：Draft V1  
适用范围：Aearn 的 `KnowledgePoint` 复习调度、`ReviewState` 更新、`ReviewLog` 追溯、Celery 定时任务与 `fsrs-optimizer` 启用策略

## 目标

本文件定义代码练习闭环如何进入复习系统：

```text
Attempt -> code_completion_result -> Attempt.fsrs_rating -> ReviewState -> due_at -> Review Graph
```

第一版的调度事实来源是 `Attempt` 和 `ReviewLog`，不是主观聊天轮次。`ReviewState` 只保存当前 FSRS Card 状态，`ReviewLog` 保存每次状态变化，保证调度可追溯、可重试、可恢复。

## 核心原则

1. 一个 `KnowledgePoint` 对应一张 FSRS Card。
2. `Attempt.fsrs_rating` 是调度输入，取值只能是 `Again` / `Hard` / `Good` / `Easy`。
3. 只有 `Attempt(attempt_type=submit)` 和 `Attempt(attempt_type=review_submit)` 可以更新 `ReviewState`。
4. `Attempt(attempt_type=run)` 只保存运行事实，不进入 FSRS。
5. 复习页 warmup 的 `correct`、`incorrect`、`unclear`、`skipped` 只写入 `learning_sessions.review_stage_state_json`，不创建 `Attempt`，不写 `ReviewLog`，不更新 FSRS。
6. `due_at` 使用 `timestamptz` 存储绝对时间点，数据库比较统一使用 `now()`。
7. “今日复习”窗口按 `Asia/Shanghai` 计算，但不改变数据库 UTC 存储策略。
8. 任何失败重试都不得重新运行用户代码，只能基于已保存的 `Attempt` 重放调度更新。

## 术语映射

| 业务术语 | FSRS 术语 | 存储位置 | 说明 |
|---|---|---|---|
| `KnowledgePoint` | Card identity | `review_states.knowledge_point_id` | V1 最小复习单元 |
| `ReviewState` | Card current state | `review_states` | 保存 `card_state`、`stability`、`difficulty`、`due_at` |
| `ReviewLog` | Review history | `review_logs` | append-only，保存每次 rating 和状态快照 |
| `Attempt.fsrs_rating` | Rating | `attempts.fsrs_rating` | 由评分规格写入 |
| `due_at` | Scheduled review datetime | `review_states.due_at` | 到期可复习时间 |
| `code_completion_result` | Rating evidence | `attempts.code_completion_result` | 保存评分证据与 `next_action` |

## KnowledgePoint 与 FSRS Card 映射

### 当前映射

V1 中 `KnowledgePoint` 属于用户确认后的 `LearningPlan`，因此可直接映射为：

```text
review_states.knowledge_point_id = knowledge_points.id
```

`review_states` 同时冗余保存：

- `user_id`
- `plan_id`

这样 `GET /api/reviews/today?user_id={user_id}` 和 Celery due 查询不需要从 `knowledge_points -> plan_modules -> learning_plans` 每次深 join 才能过滤用户。

### 创建时机

`initialize_review_state` 在 `confirm_plan` 后执行：

```text
KnowledgePoint.status = pending
ReviewState.card_state = new
ReviewState.stability = NULL
ReviewState.difficulty = NULL
ReviewState.due_at = NULL
ReviewState.review_count = 0
ReviewState.lapse_count = 0
```

初始 `ReviewState` 不进入今日复习。只有第一次有效提交完成并写入 `Attempt.fsrs_rating` 后，才计算第一版 `due_at`。

### 状态转换

| 当前状态 | Rating | 下一状态 | 说明 |
|---|---|---|---|
| `new` | `Again` | `learning` | 第一次失败，短间隔重练 |
| `new` | `Hard` | `learning` | 部分通过，短间隔巩固 |
| `new` | `Good` | `review` | 正常进入复习 |
| `new` | `Easy` | `review` | 首次掌握较稳，间隔更长 |
| `learning` | `Again` | `learning` | 继续短间隔 |
| `learning` | `Hard` | `learning` | 保持短间隔 |
| `learning` | `Good` | `review` | 进入正常复习 |
| `learning` | `Easy` | `review` | 进入正常复习 |
| `review` | `Again` | `relearning` | 复习失败，计入 lapse |
| `review` | `Hard` | `review` | 小幅拉长或保持 |
| `review` | `Good` | `review` | 正常拉长 |
| `review` | `Easy` | `review` | 明显拉长 |
| `relearning` | `Again` | `relearning` | 继续短间隔 |
| `relearning` | `Hard` | `relearning` | 保持短间隔 |
| `relearning` | `Good` | `review` | 回到正常复习 |
| `relearning` | `Easy` | `review` | 回到正常复习 |

## ReviewState 存储结构

`review_states` 是当前状态表，主键为 `knowledge_point_id`。

| 字段 | 类型 | 更新规则 |
|---|---|---|
| `knowledge_point_id` | `uuid` | 创建后不变 |
| `user_id` | `uuid` | 创建后不变 |
| `plan_id` | `uuid` | 创建后不变 |
| `card_state` | `text` | 每次有效 rating 后更新 |
| `stability` | `numeric(10,4)` | 由 FSRS scheduler 计算；fallback scheduler 可写估算值 |
| `difficulty` | `numeric(10,4)` | 由 FSRS scheduler 计算；fallback scheduler 可写估算值 |
| `due_at` | `timestamptz` | 每次有效 rating 后更新 |
| `last_review_at` | `timestamptz` | 等于本次 `reviewed_at` |
| `review_count` | `integer` | 每次有效 rating 后 `+1` |
| `lapse_count` | `integer` | `review` 或 `relearning` 状态下收到 `Again` 时 `+1` |
| `last_attempt_id` | `uuid` | 本次调度使用的 `Attempt.id` |
| `last_fsrs_rating` | `text` | 本次 `Attempt.fsrs_rating` |
| `scheduler_version` | `text` | 默认 `fsrs_v1_default`，optimizer 启用后写参数版本 |
| `fsrs_parameters` | `jsonb` | 本次计算使用的参数快照 |
| `suspended_at` | `timestamptz` | 计划暂停或知识点归档时写入 |

更新 `ReviewState` 必须与插入 `ReviewLog` 在同一数据库事务内完成。

## ReviewLog 存储结构

`review_logs` 是 append-only 表，用于训练 `fsrs-optimizer`、调试 due 变化和恢复失败任务。

| 字段 | 类型 | 规则 |
|---|---|---|
| `id` | `uuid` | PK |
| `knowledge_point_id` | `uuid` | FK -> `knowledge_points.id` |
| `user_id` | `uuid` | FK -> `users.id` |
| `plan_id` | `uuid` | FK -> `learning_plans.id` |
| `attempt_id` | `uuid` | FK -> `attempts.id` |
| `rating` | `text` | `Again` / `Hard` / `Good` / `Easy` |
| `previous_state_json` | `jsonb` | 调度前 `ReviewState` 快照 |
| `next_state_json` | `jsonb` | 调度后 `ReviewState` 快照 |
| `scheduled_due_at` | `timestamptz` | 本次计算出的 `due_at` |
| `reviewed_at` | `timestamptz` | 使用 `Attempt.created_at` 或服务端 `now()`，优先 Attempt 时间 |
| `source` | `text` | `learn_submit` / `review_submit` / `manual_adjust` |
| `request_id` | `text` | 幂等键 |
| `created_at` | `timestamptz` | 插入时间 |

幂等约束：

```text
UNIQUE(attempt_id, rating, source)
UNIQUE(request_id)
```

如果同一个 `Attempt` 重试更新 FSRS，必须返回已存在的 `ReviewLog.next_state_json`，不得重复增加 `review_count` 或 `lapse_count`。

## Attempt.fsrs_rating 到 FSRS Rating 的映射

`evaluate_attempt` 必须先根据 `code-completion-evaluation-spec.md` 写入 `Attempt.fsrs_rating`。调度层只做校验和转换，不重新评分。

| `code_completion_result.result` | 附加条件 | `Attempt.fsrs_rating` | FSRS Rating Code |
|---|---|---|---|
| `failed` | 任意失败 | `Again` | `1` |
| `partial` | 任意部分通过 | `Hard` | `2` |
| `passed` | `hint_usage_count <= 2` 且 `error_count <= 2` | `Good` | `3` |
| `passed` | 提示或错误次数较高 | `Hard` | `2` |
| `easy` | `hint_usage_count = 0` 且 `error_count = 0` | `Easy` | `4` |
| `easy` | 使用过轻提示 | `Good` | `3` |

`review_ai_patch` 仍使用同一 `Attempt(attempt_type=review_submit)` 和 `code_completion_result` 证据字段，但 score breakdown 固定为 `verdict_correctness`、`evidence_grounding`、`knowledge_point_alignment`、`actionability`。其中 `evidence_grounding < 2` 必须降级为 `Hard`，即使 learner verdict 正确，也不得映射为 `Easy`。

调度层校验规则：

1. `Attempt.fsrs_rating` 必须非空。
2. `Attempt.evaluation_status` 必须为 `evaluated`。
3. `Attempt.attempt_type` 必须为 `submit` 或 `review_submit`。
4. `Attempt.code_completion_result.fsrs_rating` 必须等于 `Attempt.fsrs_rating`。
5. `Attempt.user_id` 必须等于 `ReviewState.user_id`。
6. `Attempt.exercise_id` 必须能追溯到同一个 `KnowledgePoint`。

校验失败时不更新 `ReviewState`，将 `Attempt.evaluation_status` 保持或改为 `needs_manual_review`，并返回可恢复错误。

## 调度计算

### 输入

```json
{
  "knowledge_point_id": "uuid",
  "attempt_id": "uuid",
  "rating": "Good",
  "reviewed_at": "2026-05-11T12:00:00+08:00",
  "previous_state": {
    "card_state": "review",
    "stability": 3.42,
    "difficulty": 5.81,
    "due_at": "2026-05-11T00:00:00Z",
    "review_count": 2,
    "lapse_count": 0
  }
}
```

### 主路径

1. 读取并锁定 `review_states` 行：`FOR UPDATE`。
2. 校验 `Attempt.fsrs_rating`。
3. 根据 `scheduler_version` 选择 FSRS 参数。
4. 调用 FSRS scheduler 计算下一状态。
5. 将下一状态写入 `review_states`。
6. 插入 `review_logs`。
7. 根据 `code_completion_result.result` 更新 `KnowledgePoint.status` 和 `mastery_score`。
8. 提交事务。

### fallback scheduler

当 FSRS library 不可用、参数损坏或计算异常时，使用 deterministic fallback，保证学习流程不中断。

| Rating | fallback `due_at` | `card_state` | `stability` 估算 | `difficulty` 估算 |
|---|---|---|---|---|
| `Again` | `reviewed_at + 10 minutes` | `learning` 或 `relearning` | `0.1` | `max(previous + 0.8, 7.0)` |
| `Hard` | `next_review_slot(reviewed_at, 1 day)` | `learning` 或 `review` | `max(previous, 1.0)` | `min(previous + 0.3, 10.0)` |
| `Good` | `next_review_slot(reviewed_at, 3 days)` | `review` | `max(previous * 1.8, 3.0)` | `previous` |
| `Easy` | `next_review_slot(reviewed_at, 7 days)` | `review` | `max(previous * 2.5, 7.0)` | `max(previous - 0.3, 1.0)` |

`next_review_slot(base, days)`：

1. 先把 `base` 转为 `Asia/Shanghai`。
2. 加上 `days` 个自然日。
3. 默认落到本地 `20:00`。
4. 如果用户 `preferred_time_slots` 有可用时间，则选择目标日第一个不在 quiet hours 内的 slot。
5. 转回 UTC 后写入 `due_at`。

fallback 必须在 `review_logs.next_state_json.scheduler_fallback=true` 中标记，并将 `review_states.scheduler_version` 写为 `fsrs_v1_fallback`。

## Asia/Shanghai 时区策略

### 存储

- `review_states.due_at`、`review_states.last_review_at`、`review_logs.reviewed_at` 全部为 `timestamptz`。
- 应用层使用 timezone-aware datetime。
- 写库前不允许丢失时区信息。

### 展示

- UI 展示 `due_at` 时转换为 `Asia/Shanghai`。
- 今日待复习列表以 `Asia/Shanghai` 的自然日为边界。

### 今日窗口

```text
local_start = YYYY-MM-DD 00:00:00 Asia/Shanghai
local_end = local_start + 1 day
utc_start = local_start converted to UTC
utc_end = local_end converted to UTC
```

- “已到期可做”：`due_at <= now()`
- “今日稍后到期”：`now() < due_at < utc_end`
- “今日列表默认展示”：优先展示已到期；如果 UI 需要预告，再展示今日稍后到期并标记不可开始或可提前复习。

## due_at 查询策略

### API 查询今日到期

```sql
SELECT
  rs.knowledge_point_id,
  rs.due_at,
  rs.card_state,
  rs.review_count,
  rs.lapse_count,
  rs.last_fsrs_rating,
  kp.title,
  kp.status,
  kp.weak_points_json
FROM review_states rs
JOIN knowledge_points kp ON kp.id = rs.knowledge_point_id
JOIN learning_plans lp ON lp.id = rs.plan_id
WHERE rs.user_id = :user_id
  AND rs.due_at IS NOT NULL
  AND rs.due_at <= now()
  AND rs.suspended_at IS NULL
  AND lp.status = 'active'
  AND lp.deleted_at IS NULL
  AND kp.deleted_at IS NULL
  AND kp.status IN ('reviewing', 'mastered')
ORDER BY rs.due_at ASC, rs.lapse_count DESC, kp.mastery_score ASC
LIMIT :limit;
```

依赖索引：

```text
idx_review_states_due(user_id, due_at)
idx_review_states_plan_due(plan_id, due_at)
```

### Worker 批量领取

Celery worker 需要避免多 worker 重复处理同一条 due 记录：

```sql
SELECT rs.knowledge_point_id
FROM review_states rs
WHERE rs.due_at IS NOT NULL
  AND rs.due_at <= now()
  AND rs.suspended_at IS NULL
ORDER BY rs.due_at ASC
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```

领取查询只用于刷新提醒、预热复习变体或统计 due count；真正更新 `ReviewState` 仍必须由有效 `Attempt` 触发。

## Celery 调度时间

Celery 配置：

```python
timezone = "Asia/Shanghai"
enable_utc = True
```

推荐 beat 任务：

| 任务 | 时间 | 作用 | 幂等键 |
|---|---|---|---|
| `review.refresh_due_counts` | 每 5 分钟 | 刷新用户今日 due 计数和 dashboard cache | `refresh_due_counts:{yyyyMMddHHmm}` |
| `review.prepare_due_variants` | 每 15 分钟 | 为已到期 `KnowledgePoint` 预生成或选择复习变体 | `prepare_due:{knowledge_point_id}:{due_at}` |
| `review.send_reminders` | 每天 `08:00`、`12:30`、`20:00` | 按用户偏好发送本地提醒 | `reminder:{user_id}:{yyyyMMdd}:{slot}` |
| `review.repair_stuck_jobs` | 每 15 分钟 | 重试卡在中间状态的调度任务 | `repair_stuck:{yyyyMMddHHmm}` |
| `review.optimize_fsrs_parameters` | 每天 `03:30` | 满足条件时运行 `fsrs-optimizer` | `fsrs_optimizer:{scope}:{yyyyMMdd}` |

执行规则：

- `send_reminders` 只提醒 `due_at <= now()` 的内容。
- `prepare_due_variants` 可以提前准备 `due_at <= now() + interval '30 minutes'` 的内容，但不得把未到期内容标记为已到期。
- 用户开始复习时仍以数据库实时 due 查询为准，不信任缓存。
- 计划暂停时写 `review_states.suspended_at`，Celery 必须跳过。

## update_review_state 事务流程

伪代码：

```text
update_review_state(attempt_id, knowledge_point_id, request_id):
  begin transaction
    attempt = SELECT * FROM attempts WHERE id = attempt_id FOR UPDATE
    state = SELECT * FROM review_states WHERE knowledge_point_id = knowledge_point_id FOR UPDATE

    if existing review_logs by request_id:
      return existing.next_state_json

    validate attempt and rating
    previous_state = snapshot(state)
    next_state = fsrs_schedule(previous_state, attempt.fsrs_rating, attempt.created_at)

    UPDATE review_states SET ...
    INSERT review_logs(previous_state_json, next_state_json, request_id, ...)
    UPDATE knowledge_points SET status/mastery/last fields
  commit
```

事务内必须先锁 `attempts`，再锁 `review_states`，所有调用保持同一锁顺序，降低死锁概率。

## 幂等策略

| 操作 | 幂等键 | 重复请求行为 |
|---|---|---|
| 学习提交后调度 | `review:update:{knowledge_point_id}:{attempt_id}:{fsrs_rating}` | 返回已有 `ReviewLog` |
| 复习提交后调度 | `review:update:{knowledge_point_id}:{attempt_id}:{fsrs_rating}` | 返回已有 `ReviewLog` |
| 预生成复习变体 | `review:variant:{knowledge_point_id}:{due_at}` | 返回已有 variant |
| 发送提醒 | `review:reminder:{user_id}:{local_date}:{slot}` | 跳过重复提醒 |
| optimizer 训练 | `fsrs:optimize:{scope}:{local_date}` | 返回当日已有参数集 |

数据库层必须至少保证：

```text
review_logs.request_id UNIQUE
review_logs(attempt_id, rating, source) UNIQUE
```

应用层可以再用 Redis lock 降低重复任务，但不能只依赖 Redis。

## 失败重试

### Attempt 已保存但 ReviewState 更新失败

处理：

1. 不重新运行代码。
2. 以 `attempt_id` 重新调用 `update_review_state`。
3. 如果已存在 `ReviewLog`，直接返回其 `next_state_json`。
4. 如果不存在，按同一 `Attempt.fsrs_rating` 重新计算。

### FSRS 计算失败

处理：

1. 记录 error log。
2. 使用 fallback scheduler。
3. `ReviewLog.next_state_json.scheduler_fallback=true`。
4. 不把前端成功提交变成失败，除非数据库写入也失败。

### 数据库死锁或连接超时

Celery retry 策略：

```text
max_retries = 5
countdown = min(2 ** retry_count * 5 seconds, 5 minutes)
jitter = true
```

API 同步提交策略：

- 首次失败返回 `202 Accepted` 和 `review_update_status=pending`。
- 后台任务继续用同一 `request_id` 重试。
- 前端查询 Attempt 或 session summary 时读取最终 `ReviewState`。

### 无效 rating

条件：

- `Attempt.fsrs_rating IS NULL`
- `Attempt.fsrs_rating` 不在枚举内
- `Attempt.code_completion_result.fsrs_rating` 与 `Attempt.fsrs_rating` 不一致

处理：

1. 不更新 `ReviewState`。
2. 将 `Attempt.evaluation_status` 设为 `needs_manual_review`。
3. 写入结构化错误 `INVALID_FSRS_RATING`。
4. 前端显示“评分需要重新生成”，允许重新执行 `evaluate_attempt`，但不重新运行代码。

## fsrs-optimizer 启用条件

默认配置：

```text
FSRS_OPTIMIZER_ENABLED=false
FSRS_OPTIMIZER_SCOPE=global
FSRS_TARGET_RETENTION=0.90
FSRS_MIN_REVIEW_LOGS=200
FSRS_MIN_DISTINCT_CARDS=50
FSRS_MIN_LAPSES=10
```

启用条件必须全部满足：

1. `FSRS_OPTIMIZER_ENABLED=true`。
2. `review_logs` 有至少 `FSRS_MIN_REVIEW_LOGS` 条有效日志。
3. 至少覆盖 `FSRS_MIN_DISTINCT_CARDS` 个不同 `KnowledgePoint`。
4. 至少有 `FSRS_MIN_LAPSES` 条 `rating=Again`，否则难以校准遗忘。
5. 最近 7 天没有正在生效的同 scope 参数训练任务。
6. 训练集中的 `rating` 全部能映射到 FSRS Rating Code。
7. 评估集相对默认参数的 loss 改善至少 `2%`，且未来 7 天 due 数量增长不超过 `20%`。

### 参数生效策略

- MVP 默认使用全局参数：`scheduler_version=fsrs_v1_default`。
- optimizer 产物以 `scheduler_version=fsrs_opt_{yyyyMMdd}_{hash}` 标识。
- 新参数只影响后续调度计算，不批量重写所有旧 `due_at`。
- 每次更新 `ReviewState` 时把本次参数快照写入 `review_states.fsrs_parameters` 和 `review_logs.next_state_json.fsrs_parameters`。
- 如果新参数导致异常 due 激增，切回上一个 `scheduler_version`；已写入的 due 不批量回滚，只通过后续 review 自然修正，必要时用 `manual_adjust` 写 `ReviewLog`。

### optimizer 输入

训练数据来自 `review_logs`，最小字段：

```json
{
  "card_id": "knowledge_point_id",
  "reviewed_at": "2026-05-11T04:00:00Z",
  "rating": 3,
  "elapsed_days": 3,
  "previous_stability": 2.1,
  "previous_difficulty": 5.4
}
```

排除数据：

- `source=manual_adjust`
- `next_state_json.scheduler_fallback=true`
- `Attempt.evaluation_status != evaluated`
- `reviewed_at` 缺失或时区不合法
- 同一 `attempt_id` 的重复日志

## 与 LearningSession 的衔接

### 学习提交

当 `Learning Graph` 中 `update_learning_memory` 执行时：

1. 读取 `Attempt.fsrs_rating`。
2. 更新 `KnowledgePoint.last_exercise_result`、`last_exercise_score`、`last_exercise_breakdown_json`。
3. 更新 `ReviewState` 和插入 `ReviewLog(source=learn_submit)`。
4. `easy` / `passed` / `partial`：`KnowledgePoint.status=reviewing`。
5. `failed`：`KnowledgePoint.status=learning`，但仍可写短间隔 `due_at` 用于补练提醒。

### 复习提交

当 `Review Graph` 中 `update_review_state` 执行时：

1. `Attempt.attempt_type=review_submit`。
2. 更新 `ReviewState` 和插入 `ReviewLog(source=review_submit)`。
3. 根据结果更新 `KnowledgePoint.mastery_score`：
   - `Again`：降低 `0.10`，最低 `0`。
   - `Hard`：降低或小幅增加 `0.00` 到 `0.03`。
   - `Good`：增加 `0.05`。
   - `Easy`：增加 `0.08`，最高 `1`。
4. `review_count >= 3` 且最近两次 `Good` / `Easy` 时，可将 `KnowledgePoint.status` 设为 `mastered`。

### 复习热身

当 `Review Graph` 记录 warmup 时：

1. 写入 `LearningSession.review_stage` 和 `LearningSession.review_stage_state_json`。
2. `correct`、`skipped` 进入 `variant_practice`；`incorrect` 或 `unclear` 最多进入一次 `warmup_repair`。
3. 不创建 `Attempt`，不写 `ReviewLog`，不改变 `ReviewState.review_count`、`last_review_at`、`last_attempt_id`、`last_fsrs_rating` 或 `due_at`。
4. 后续必须通过变体练习提交生成 `Attempt(review_submit)`，才能进入 `update_review_state`。

## API 输出规则

### `GET /api/reviews/today`

必须返回：

```json
{
  "due_reviews": [
    {
      "knowledge_point_id": "uuid",
      "title": "事件监听与状态变量",
      "due_at": "2026-05-11T20:00:00+08:00",
      "card_state": "review",
      "last_fsrs_rating": "Good",
      "weak_points": ["state_scope_error"]
    }
  ],
  "timezone": "Asia/Shanghai",
  "generated_at": "2026-05-11T12:00:00+08:00"
}
```

### `POST /api/reviews/{session_id}/exercise-result`

响应中的 `due_at` 必须来自更新后的 `ReviewState.due_at`，不得由前端自行计算。

```json
{
  "result": "passed",
  "score": 7,
  "fsrs_rating": "Good",
  "due_at": "2026-05-14T20:00:00+08:00",
  "forget_risk": "normal"
}
```

## 验收检查

- 每个 `KnowledgePoint` 在确认计划后都有一条 `ReviewState`。
- 未完成首次有效 `Attempt` 前，`due_at` 为 NULL 且不会进入 due 查询。
- 每次 `submit` 或 `review_submit` 更新 `ReviewState` 时都有且只有一条 `ReviewLog`。
- 重复提交同一 `request_id` 不会重复增加 `review_count`。
- Celery 任务使用 `Asia/Shanghai` 调度，但数据库 `due_at` 仍为 `timestamptz`。
- `fsrs-optimizer` 未满足启用条件时不会改变默认参数。
- FSRS library 失败时 fallback scheduler 能给出明确 `due_at`，且日志可追溯。
