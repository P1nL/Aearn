# 间隔复习与 ReviewSession 实施计划

## 阶段 1：契约与纯调度

1. 新建 `app/services/learning/reviews/` 包。
2. 定义 schedule、risk、session、stage、rating 与聚合 contract。
3. 实现纯 `track_review_fsrs_v1` 调度函数和 property 测试。

## 阶段 2：数据库 authority

1. 增加 schedule、schedule event、session、warmup、item、finalization 表。
2. 为 `tutor_exercise_attempts` 增加 `review_submit` owner shape。
3. 增加 FK、唯一约束、索引、immutable/lifecycle trigger。
4. 更新 bootstrap assertion、cutover inventory、export/reset。

## 阶段 3：repository 与 service

1. 实现 track-scoped due queue 与 critical prerequisite Gate 投影。
2. 从 verified mastery evidence seed schedule，并处理 `diagnostic_skipped` 低频策略。
3. 在计划激活事务中显式 retained/suspended schedule migration。
4. 实现 session create/retry/resume、warmup、item Attempt、poll 和 finalization。
5. 复用静态评分、模型审核评分与现有 executor queue，不复制执行 authority。
6. 持久化有界 `AuthoritativeContextSnapshot`。

## 阶段 4：API 与首页投影

1. 增加 review Pydantic models 和 `/api/learning-tracks/{track_id}/reviews...` 路由。
2. 将 LearningTrack `review_due_count` 改为数据库 authority。
3. 保持 Desktop 三栏与 ReviewSession UI 在范围外。

## 阶段 5：验证与收尾

1. 运行 focused contracts/repository/API/export/cutover/schema tests。
2. 运行 API lock、Ruff、Mypy 和全量 pytest。
3. 运行 Trellis validate 与 `git diff --check`。
4. 分层提交 product code、任务归档和 journal；始终排除本地敏感 Obsidian Translate 数据。
