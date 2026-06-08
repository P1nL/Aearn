# 数据库 Schema / Migration 实施规格

日期：2026-05-13  
状态：Draft V1.1  
适用范围：Aearn 的 PostgreSQL 持久化、API 字段映射、LangGraph 写库节点与 FSRS 调度

## 目标

本文件是第一版可实现的 PostgreSQL Schema，承接 API 契约、评分规则和 LangGraph 状态机。第一版以单体 FastAPI + PostgreSQL 为基线，不依赖 ORM 魔法字段；所有表、约束、索引、JSONB 结构和 migration 顺序必须能直接转为 Alembic 或 SQL migration。Draft V1.1 只覆盖“笔记页 + 笔记抽屉”的持久化，不把独立复盘草稿表纳入 MVP migration。

## 通用约定

### 命名与类型

- 表名使用 snake_case 复数形式，例如 `learning_plans`、`knowledge_points`。
- 主键统一使用 `uuid`，默认值为 `gen_random_uuid()`。
- 面向 demo、种子数据和文档示例的稳定标识使用 `slug text`，不替代主键。
- 枚举第一版使用 `text CHECK (...)`，不使用 PostgreSQL enum，避免频繁迁移枚举类型。
- 金额无关的百分比使用 `numeric(5,4)`，取值范围 `0.0000` 到 `1.0000`。
- 分数使用 `smallint`，例如 `Attempt.score` 范围为 `0` 到 `8`。
- 长文本使用 `text`，代码内容不使用 `varchar(n)` 截断。

### 时间与时区策略

- 所有时间字段使用 `timestamptz`。
- 数据库存储以 UTC 为准，不保存 naive datetime。
- API、Celery beat 和用户界面按 `Asia/Shanghai` 展示与计算“今日复习”窗口。
- `due_at` 表示可复习的绝对时间点，查询时使用 `now()` 比较，不使用本地日期字符串。
- `deadline` 表示用户目标日期，使用 `date`；如果后续需要精确截止时间，再新增 `deadline_at timestamptz`。

### 公共字段

除 append-only 日志表外，业务表默认包含：

| 字段 | 类型 | 必填/默认值 | 说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | 主键 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` | 创建时间 |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` | 更新时间，由 trigger 维护 |
| `deleted_at` | `timestamptz` | NULL | 用户内容软删除 |
| `archived_at` | `timestamptz` | NULL | 课程、计划或配置归档 |

append-only 表包括 `attempts`、`review_logs`。这些表不做普通软删除，纠错通过新增记录或状态字段完成。

### 推荐基础 SQL

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

## 表结构

### `users`

用户基础信息与长期画像。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `display_name` | `text` | NOT NULL | 展示名 |
| `learning_style` | `text` | NULL | 学习风格 |
| `teaching_preference` | `text` | NULL | 讲解偏好 |
| `encouragement_preference` | `text` | NULL | 鼓励偏好 |
| `profession` | `text` | NULL | 职业背景 |
| `background_context` | `text` | NULL | 编程背景描述 |
| `preferred_time_slots` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | JSONB schema 见下文 |
| `reminder_preference` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | JSONB schema 见下文 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `deleted_at` | `timestamptz` | NULL | 本地用户删除；reset 不写该字段 |

索引：

- `idx_users_deleted_at` on (`deleted_at`)

### `runtime_profiles`

描述练习运行能力、限制和执行方式。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `slug` | `text` | NOT NULL | UNIQUE，例如 `rt_browser_js` |
| `runtime_tier` | `text` | NOT NULL | CHECK in `browser_preview` / `python_stdout_test` / `node_typescript_test` / `sql_query_test` / `managed_compiled_test` / `compiled_sandbox_later` |
| `language` | `text` | NOT NULL | `javascript` / `python` / `typescript` / `sql` / `java` / `go` / `csharp` / `cpp` / `html_css` |
| `runner` | `text` | NOT NULL | CHECK in `browser` / `python` / `node` / `sql` / `compiled` / `sandbox` |
| `supports_realtime_preview` | `boolean` | NOT NULL DEFAULT `false` |  |
| `supports_stdout` | `boolean` | NOT NULL DEFAULT `false` |  |
| `supports_tests` | `boolean` | NOT NULL DEFAULT `false` |  |
| `compile_required` | `boolean` | NOT NULL DEFAULT `false` |  |
| `timeout_ms` | `integer` | NOT NULL DEFAULT `5000` | CHECK `timeout_ms BETWEEN 100 AND 60000` |
| `memory_limit_mb` | `integer` | NOT NULL DEFAULT `128` | CHECK `memory_limit_mb BETWEEN 16 AND 2048` |
| `sandbox_policy` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | 网络、文件、DOM 权限限制 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `archived_at` | `timestamptz` | NULL | 废弃 runtime 时保留历史引用 |

约束与索引：

- UNIQUE (`slug`)
- UNIQUE (`runtime_tier`, `language`, `runner`) WHERE `archived_at IS NULL`
- `idx_runtime_profiles_language` on (`language`)

### `language_courses`

面向某一编程语言或技术栈的课程定义。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `slug` | `text` | NOT NULL | UNIQUE，例如 `course_js_dom_beginner` |
| `language` | `text` | NOT NULL | 与 `runtime_profiles.language` 对齐 |
| `title` | `text` | NOT NULL | 课程名 |
| `description` | `text` | NULL | 课程说明 |
| `level` | `text` | NOT NULL | CHECK in `beginner` / `intermediate` / `advanced` |
| `runtime_profile_id` | `uuid` | NOT NULL | FK -> `runtime_profiles.id` |
| `supported_exercise_types_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | JSONB array |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `archived_at` | `timestamptz` | NULL | 课程归档 |

约束与索引：

- UNIQUE (`slug`)
- UNIQUE (`language`, `level`, `title`) WHERE `archived_at IS NULL`
- `idx_language_courses_language_level` on (`language`, `level`)
- `idx_language_courses_runtime_profile_id` on (`runtime_profile_id`)

### `learning_plans`

用户确认 `plan_draft` 后创建的正式学习计划。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `user_id` | `uuid` | NOT NULL | FK -> `users.id` |
| `language_course_id` | `uuid` | NOT NULL | FK -> `language_courses.id` |
| `goal_text` | `text` | NOT NULL | 用户目标 |
| `language` | `text` | NOT NULL | 冗余字段，便于查询与展示 |
| `target_level` | `text` | NOT NULL | CHECK in `beginner` / `intermediate` / `advanced` |
| `mode` | `text` | NOT NULL | CHECK in `goal_based` / `material_based` |
| `deadline` | `date` | NULL | 用户目标日期 |
| `status` | `text` | NOT NULL DEFAULT `'active'` | CHECK in `active` / `paused` / `completed` / `archived` |
| `overall_progress` | `numeric(5,4)` | NOT NULL DEFAULT `0` | CHECK `0 <= overall_progress <= 1` |
| `current_module_id` | `uuid` | NULL | FK -> `plan_modules.id`，在 `plan_modules` 建表后补 FK |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `completed_at` | `timestamptz` | NULL |  |
| `archived_at` | `timestamptz` | NULL |  |
| `deleted_at` | `timestamptz` | NULL |  |

约束与索引：

- `idx_learning_plans_user_status` on (`user_id`, `status`) WHERE `deleted_at IS NULL`
- `idx_learning_plans_course` on (`language_course_id`)
- UNIQUE (`user_id`, `language_course_id`) WHERE `status = 'active' AND deleted_at IS NULL`

### `plan_modules`

学习计划中的模块。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `plan_id` | `uuid` | NOT NULL | FK -> `learning_plans.id` |
| `title` | `text` | NOT NULL |  |
| `description` | `text` | NULL |  |
| `order_index` | `integer` | NOT NULL | CHECK `order_index >= 0` |
| `status` | `text` | NOT NULL DEFAULT `'pending'` | CHECK in `pending` / `in_progress` / `completed` / `skipped` |
| `is_skippable` | `boolean` | NOT NULL DEFAULT `true` |  |
| `is_adjustable` | `boolean` | NOT NULL DEFAULT `true` |  |
| `estimated_sessions` | `integer` | NOT NULL DEFAULT `1` | CHECK `estimated_sessions >= 1` |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `completed_at` | `timestamptz` | NULL |  |
| `archived_at` | `timestamptz` | NULL |  |
| `deleted_at` | `timestamptz` | NULL |  |

约束与索引：

- UNIQUE (`plan_id`, `order_index`) WHERE `deleted_at IS NULL`
- `idx_plan_modules_plan_status` on (`plan_id`, `status`)

### `knowledge_points`

学习与复习的最小业务单元。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `slug` | `text` | NULL | 种子数据稳定标识 |
| `module_id` | `uuid` | NOT NULL | FK -> `plan_modules.id` |
| `language_course_id` | `uuid` | NOT NULL | FK -> `language_courses.id` |
| `title` | `text` | NOT NULL |  |
| `description` | `text` | NULL |  |
| `order_index` | `integer` | NOT NULL DEFAULT `0` | 模块内排序 |
| `skill_tags_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 标签数组 |
| `lesson_outline_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 本地维护的概念子点提纲，来源于官方文档整理 |
| `lesson_sources_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 概念提纲的官方文档来源归因 |
| `status` | `text` | NOT NULL DEFAULT `'pending'` | CHECK in `pending` / `learning` / `reviewing` / `mastered` |
| `mastery_score` | `numeric(5,4)` | NOT NULL DEFAULT `0` | CHECK `0 <= mastery_score <= 1` |
| `weak_points_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 错因与薄弱点 |
| `effective_hint_strategy` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | 有效提示方式 |
| `last_exercise_result` | `text` | NULL | CHECK in `failed` / `partial` / `passed` / `easy` |
| `last_exercise_score` | `smallint` | NULL | CHECK `0 <= last_exercise_score <= 8` |
| `last_exercise_breakdown_json` | `jsonb` | NULL | `code_completion_result.score_breakdown` |
| `last_explanation_check_result` | `jsonb` | NULL | 解释检查结果 |
| `last_session_id` | `uuid` | NULL | FK -> `learning_sessions.id`，在后置 FK migration 添加 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `archived_at` | `timestamptz` | NULL |  |
| `deleted_at` | `timestamptz` | NULL |  |

约束与索引：

- UNIQUE (`module_id`, `order_index`) WHERE `deleted_at IS NULL`
- UNIQUE (`slug`) WHERE `slug IS NOT NULL`
- `idx_knowledge_points_module_status` on (`module_id`, `status`)
- `idx_knowledge_points_course` on (`language_course_id`)
- `idx_knowledge_points_skill_tags_gin` GIN on (`skill_tags_json`)
- `idx_knowledge_points_weak_points_gin` GIN on (`weak_points_json`)

### `exercises`

绑定知识点的代码练习。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `slug` | `text` | NULL | 稳定练习标识 |
| `knowledge_point_id` | `uuid` | NOT NULL | FK -> `knowledge_points.id` |
| `runtime_profile_id` | `uuid` | NOT NULL | FK -> `runtime_profiles.id` |
| `title` | `text` | NOT NULL |  |
| `exercise_type` | `text` | NOT NULL | CHECK in `code_blank` / `fix_bug` / `implement_function` / `explain_code` / `review_ai_patch` |
| `prompt_markdown` | `text` | NOT NULL | 题面 |
| `starter_code` | `text` | NOT NULL | 初始代码 |
| `solution_reference` | `text` | NULL | 参考实现，API 默认不返回 |
| `visible_test_policy` | `text` | NOT NULL DEFAULT `'visible_and_hidden_summary'` | CHECK in `visible_only` / `visible_and_hidden_summary` / `hidden_only` |
| `difficulty` | `smallint` | NOT NULL DEFAULT `1` | CHECK `difficulty BETWEEN 1 AND 5` |
| `estimated_minutes` | `integer` | NOT NULL DEFAULT `10` | CHECK `estimated_minutes BETWEEN 1 AND 240` |
| `requires_explanation` | `boolean` | NOT NULL DEFAULT `false` | 控制 `explanation_gate` |
| `metadata_json` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | 变体来源、生成策略 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `archived_at` | `timestamptz` | NULL |  |
| `deleted_at` | `timestamptz` | NULL |  |

约束与索引：

- UNIQUE (`slug`) WHERE `slug IS NOT NULL`
- `idx_exercises_knowledge_point` on (`knowledge_point_id`)
- `idx_exercises_runtime_type` on (`runtime_profile_id`, `exercise_type`)

### `code_blanks`

代码填空练习中的空缺定义。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `exercise_id` | `uuid` | NOT NULL | FK -> `exercises.id` |
| `blank_key` | `text` | NOT NULL | 前端和评分输入使用的 key |
| `placeholder` | `text` | NOT NULL | 展示占位 |
| `expected_concept` | `text` | NOT NULL | 目标概念 |
| `acceptable_patterns_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 可接受模式 |
| `is_core` | `boolean` | NOT NULL DEFAULT `true` | 控制 `core_blank_gate` |
| `order_index` | `integer` | NOT NULL | CHECK `order_index >= 0` |

约束与索引：

- UNIQUE (`exercise_id`, `blank_key`)
- UNIQUE (`exercise_id`, `order_index`)
- `idx_code_blanks_exercise` on (`exercise_id`)

### `test_cases`

练习测试用例，覆盖可见测试、隐藏测试和预览断言。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `exercise_id` | `uuid` | NOT NULL | FK -> `exercises.id` |
| `case_type` | `text` | NOT NULL | CHECK in `visible` / `hidden` / `preview_assertion` |
| `input_json` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | runner 输入 |
| `expected_output_json` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | 期望输出 |
| `assertion_code` | `text` | NULL | DOM 断言或 Python assertion |
| `weight` | `numeric(6,2)` | NOT NULL DEFAULT `1` | CHECK `weight > 0` |
| `is_critical` | `boolean` | NOT NULL DEFAULT `false` | 关键测试失败时 `test_gate=false` |
| `timeout_ms` | `integer` | NOT NULL DEFAULT `5000` | CHECK `timeout_ms BETWEEN 100 AND 60000` |
| `order_index` | `integer` | NOT NULL | CHECK `order_index >= 0` |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `archived_at` | `timestamptz` | NULL |  |

约束与索引：

- UNIQUE (`exercise_id`, `order_index`)
- `idx_test_cases_exercise_type` on (`exercise_id`, `case_type`)

### `learning_sessions`

一次具体的学习或复习会话。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `user_id` | `uuid` | NOT NULL | FK -> `users.id` |
| `plan_id` | `uuid` | NOT NULL | FK -> `learning_plans.id` |
| `session_type` | `text` | NOT NULL | CHECK in `learn` / `review` |
| `status` | `text` | NOT NULL DEFAULT `'active'` | CHECK in `active` / `finished` / `abandoned` |
| `started_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `ended_at` | `timestamptz` | NULL |  |
| `duration_seconds` | `integer` | NULL | CHECK `duration_seconds >= 0` |
| `entry_point` | `text` | NOT NULL | 例如 `start_learning` / `review` / `resume` |
| `summary_text` | `text` | NULL | 会话摘要 |
| `next_entry_point` | `text` | NULL | 恢复学习入口 |
| `request_id` | `text` | NULL | API 幂等键 |
| `learning_stage` | `text` | NULL | CHECK in `documentation_reading` / `concept_intro` / `concept_check` / `concept_repair` / `practice_offer` / `concept_qna` / `readiness_check` / `practice_support`；仅 `session_type=learn` 使用，`concept_qna` / `readiness_check` 为旧会话兼容 |
| `learning_stage_state_json` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | 精简概念判断、修正、练习解锁和旧费曼检查状态 |
| `review_stage` | `text` | NULL | CHECK in `warmup` / `warmup_repair` / `variant_practice` / `exercise` / `exercise_feedback` / `final_summary` / `submitted`；仅 `session_type=review` 使用，`variant_practice` 为旧会话兼容别名 |
| `review_stage_state_json` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | `review_batch_v1` 复习批次状态、热身诊断、候选池元数据、当前题和最终结算占位 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |

约束与索引：

- UNIQUE (`request_id`) WHERE `request_id IS NOT NULL`
- UNIQUE (`user_id`, `plan_id`) WHERE `status = 'active'`
- `idx_learning_sessions_user_started` on (`user_id`, `started_at DESC`)
- `idx_learning_sessions_plan_type` on (`plan_id`, `session_type`, `status`)

### `learning_messages`

学习页专用对话历史。该表只由 `session_type=learn` 的学习会话路径写入，用于生成式历史引用卡片；不得混入建档页、复习页或笔记页对话。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `session_id` | `uuid` | NOT NULL | FK -> `learning_sessions.id` |
| `knowledge_point_id` | `uuid` | NOT NULL | FK -> `knowledge_points.id` |
| `role` | `text` | NOT NULL | CHECK in `user` / `agent` |
| `content` | `text` | NOT NULL | 用户或 Agent 在学习页中的可见文本 |
| `client_message_id` | `text` | NULL | 用户消息幂等 ID |
| `metadata` | `jsonb` | NULL | 可保存生成式 UI 工具调用元数据 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |

约束与索引：

- UNIQUE (`client_message_id`) WHERE `client_message_id IS NOT NULL`
- `idx_learning_messages_kp_session_created` on (`knowledge_point_id`, `session_id`, `created_at`)

### `attempts`

用户一次运行或提交练习的事实记录。`code_completion_result` 的结构化结果必须能追溯到该表。`attempt_type=run` / `submit` / `review_submit` 是后端固定事实枚举，前端 UI 不暴露内部类型拆分。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `session_id` | `uuid` | NOT NULL | FK -> `learning_sessions.id` |
| `exercise_id` | `uuid` | NOT NULL | FK -> `exercises.id` |
| `user_id` | `uuid` | NOT NULL | FK -> `users.id` |
| `attempt_type` | `text` | NOT NULL | CHECK in `run` / `submit` / `review_submit` |
| `submit_version` | `integer` | NOT NULL DEFAULT `1` | 同一练习多次提交递增 |
| `submitted_code` | `text` | NOT NULL | 用户代码 |
| `code_hash` | `text` | NOT NULL | `sha256(submitted_code + filled_blanks_json)` |
| `filled_blanks_json` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | `blank_key -> value` |
| `runtime_status` | `text` | NOT NULL | CHECK in `success` / `runtime_error` / `timeout` / `unsupported` |
| `test_pass_rate` | `numeric(5,4)` | NOT NULL DEFAULT `0` | CHECK `0 <= test_pass_rate <= 1` |
| `passed_test_count` | `integer` | NOT NULL DEFAULT `0` | CHECK `passed_test_count >= 0` |
| `total_test_count` | `integer` | NOT NULL DEFAULT `0` | CHECK `total_test_count >= passed_test_count` |
| `test_results_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 测试明细 |
| `stdout` | `text` | NULL |  |
| `stderr` | `text` | NULL |  |
| `error_message` | `text` | NULL |  |
| `error_cause` | `text` | NULL | CHECK in 错因标签集合，可 NULL |
| `hint_usage_count` | `integer` | NOT NULL DEFAULT `0` | CHECK `hint_usage_count >= 0` |
| `error_count` | `integer` | NOT NULL DEFAULT `0` | CHECK `error_count >= 0` |
| `explanation_text` | `text` | NULL | 用户解释 |
| `explanation_check_result` | `jsonb` | NULL | 解释检查输出 |
| `score` | `smallint` | NULL | CHECK `score BETWEEN 0 AND 8` |
| `score_breakdown_json` | `jsonb` | NULL | 四维评分 |
| `code_completion_result` | `jsonb` | NULL | 评分规格完整 JSON |
| `fsrs_rating` | `text` | NULL | CHECK in `Again` / `Hard` / `Good` / `Easy` |
| `evaluation_status` | `text` | NOT NULL DEFAULT `'pending'` | CHECK in `pending` / `evaluated` / `needs_manual_review` |
| `request_id` | `text` | NULL | API 幂等键 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` | append-only |

约束与索引：

- UNIQUE (`request_id`) WHERE `request_id IS NOT NULL`
- UNIQUE (`session_id`, `exercise_id`, `attempt_type`, `submit_version`)
- `idx_attempts_session_created` on (`session_id`, `created_at DESC`)
- `idx_attempts_user_created` on (`user_id`, `created_at DESC`)
- `idx_attempts_exercise_created` on (`exercise_id`, `created_at DESC`)
- `idx_attempts_fsrs_rating` on (`fsrs_rating`) WHERE `fsrs_rating IS NOT NULL`
- `idx_attempts_code_completion_result_gin` GIN on (`code_completion_result`)

### `session_knowledge_points`

一次会话涉及多个知识点时的关联关系和最终学习结果。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `session_id` | `uuid` | NOT NULL | FK -> `learning_sessions.id` |
| `knowledge_point_id` | `uuid` | NOT NULL | FK -> `knowledge_points.id` |
| `exercise_id` | `uuid` | NULL | FK -> `exercises.id` |
| `attempt_id` | `uuid` | NULL | FK -> `attempts.id` |
| `exercise_result` | `text` | NULL | CHECK in `failed` / `partial` / `passed` / `easy` |
| `exercise_score` | `smallint` | NULL | CHECK `exercise_score BETWEEN 0 AND 8` |
| `score_breakdown_json` | `jsonb` | NULL |  |
| `mastery_delta` | `numeric(6,4)` | NOT NULL DEFAULT `0` | 可为负数 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |

约束与索引：

- UNIQUE (`session_id`, `knowledge_point_id`)
- `idx_session_kp_knowledge_point` on (`knowledge_point_id`)
- `idx_session_kp_attempt` on (`attempt_id`) WHERE `attempt_id IS NOT NULL`

### `review_seed_banks`

每个知识点的复习材料候选池。复习页不主要依赖短学习历史生成题目，而是先从官方 taxonomy、知识点目标、课程提纲、runtime 能力和常见误解生成完整 candidate pool，再从中选择本轮变体。当前持久化表名和字段名仍沿用 `review_seed_banks` / `seeds_json`，但 `generator_version=review_candidate_pool_v1` 的行按候选池合同解释。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `user_id` | `uuid` | NOT NULL | FK -> `users.id` |
| `plan_id` | `uuid` | NOT NULL | FK -> `learning_plans.id` |
| `knowledge_point_id` | `uuid` | NOT NULL | FK -> `knowledge_points.id` |
| `generator_version` | `text` | NOT NULL | 生成器版本，例如 `review_candidate_pool_v1` |
| `status` | `text` | NOT NULL DEFAULT `'generating'` | CHECK in `generating` / `ready` / `failed` |
| `seed_count` | `integer` | NOT NULL DEFAULT `0` | CHECK `seed_count >= 0` |
| `seeds_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 完整复习候选题列表，schema 见下文 |
| `quality_report_json` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | 数量、题型/能力覆盖、core 覆盖、去重和安全校验结果 |
| `failure_code` | `text` | NULL | 失败时记录稳定错误码 |
| `failure_message` | `text` | NULL | 失败摘要，不保存 raw provider error 或 secrets |
| `generated_at` | `timestamptz` | NULL | 成功生成时间 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |

约束与索引：

- UNIQUE (`user_id`, `knowledge_point_id`, `generator_version`)
- `idx_review_seed_banks_status` on (`status`, `updated_at`)

生成与安全规则：

- 普通知识点要求 10-12 个候选题；核心或高风险知识点要求 12-16 个候选题；候选池硬上限为 18。
- 必须覆盖当前 runtime 支持的核心复习题型，并在支持时包含至少一个 `review_ai_patch`。
- 候选题必须携带 `capability`、`focus_tags`、`recommended_for`、`avoid_if`、`metadata.selection_reason` 和 `metadata.is_core`，供后端 graph 后续无模型选题。
- `capability` 取值为 `basic_application`、`concept_explanation`、`debugging`、`transfer_or_review`。
- `review_ai_patch` 候选题必须包含 requirement、original code、AI diff、review focus、expected risk、expected verdict、expected next action 和 scoring rubric。
- 候选题不得包含 hidden tests、参考答案泄露、raw prompt、provider 原始错误、API key 或 secrets。
- 异步生成和同步 rescue 必须共用同一 generator、schema、validation、安全检查和持久化路径；同步 rescue 失败时标记 `failed` 并返回 `REVIEW_SEED_BANK_GENERATION_FAILED`。

### `review_states`

与 FSRS Card 一一对应的当前调度状态。第一版映射粒度为 `KnowledgePoint -> FSRS Card`。该调度规则属于后端固定契约，不由设置页修改。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `knowledge_point_id` | `uuid` | NOT NULL | PK, FK -> `knowledge_points.id` |
| `user_id` | `uuid` | NOT NULL | FK -> `users.id`，用于快速 due 查询 |
| `plan_id` | `uuid` | NOT NULL | FK -> `learning_plans.id` |
| `card_state` | `text` | NOT NULL DEFAULT `'new'` | CHECK in `new` / `learning` / `review` / `relearning` |
| `stability` | `numeric(10,4)` | NULL | FSRS 字段，首次有效评分后写入 |
| `difficulty` | `numeric(10,4)` | NULL | FSRS 字段，首次有效评分后写入 |
| `due_at` | `timestamptz` | NULL | 未完成首次 Attempt 前为 NULL |
| `last_review_at` | `timestamptz` | NULL |  |
| `review_count` | `integer` | NOT NULL DEFAULT `0` | CHECK `review_count >= 0` |
| `lapse_count` | `integer` | NOT NULL DEFAULT `0` | CHECK `lapse_count >= 0` |
| `last_attempt_id` | `uuid` | NULL | FK -> `attempts.id` |
| `last_fsrs_rating` | `text` | NULL | CHECK in `Again` / `Hard` / `Good` / `Easy` |
| `scheduler_version` | `text` | NOT NULL DEFAULT `'fsrs_v1_default'` | 调度参数版本 |
| `fsrs_parameters` | `jsonb` | NOT NULL DEFAULT `'{}'::jsonb` | 个性化参数快照 |
| `suspended_at` | `timestamptz` | NULL | 暂停复习 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |

约束与索引：

- `idx_review_states_due` on (`user_id`, `due_at`) WHERE `due_at IS NOT NULL AND suspended_at IS NULL`
- `idx_review_states_plan_due` on (`plan_id`, `due_at`) WHERE `due_at IS NOT NULL AND suspended_at IS NULL`
- `idx_review_states_last_attempt` on (`last_attempt_id`) WHERE `last_attempt_id IS NOT NULL`

### `review_logs`

FSRS 更新的 append-only 日志。每次学习提交或复习批次最终结算只要更新 `ReviewState`，就必须写入一条 `ReviewLog`。复习中间题只写 `Attempt(review_submit)` 和 `learning_sessions.review_stage_state_json`，不写 `review_logs`；由于 `attempt_id` 仍为 `NOT NULL`，批次最终结算使用最后一个已完成正式题 attempt 作为 representative attempt。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `knowledge_point_id` | `uuid` | NOT NULL | FK -> `knowledge_points.id` |
| `user_id` | `uuid` | NOT NULL | FK -> `users.id` |
| `plan_id` | `uuid` | NOT NULL | FK -> `learning_plans.id` |
| `attempt_id` | `uuid` | NOT NULL | FK -> `attempts.id`；复习批次最终结算时保存 representative `review_submit` attempt |
| `rating` | `text` | NOT NULL | CHECK in `Again` / `Hard` / `Good` / `Easy` |
| `previous_state_json` | `jsonb` | NOT NULL | 更新前 ReviewState 快照 |
| `next_state_json` | `jsonb` | NOT NULL | 更新后 ReviewState 快照 |
| `scheduled_due_at` | `timestamptz` | NOT NULL | 本次计算出的 due |
| `reviewed_at` | `timestamptz` | NOT NULL DEFAULT `now()` | 实际评分时间 |
| `source` | `text` | NOT NULL | CHECK in `learn_submit` / `review_submit` / `manual_adjust` |
| `request_id` | `text` | NOT NULL | 幂等键 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` | append-only |

约束与索引：

- UNIQUE (`attempt_id`, `rating`, `source`)
- UNIQUE (`request_id`)
- `idx_review_logs_kp_reviewed` on (`knowledge_point_id`, `reviewed_at DESC`)
- `idx_review_logs_user_reviewed` on (`user_id`, `reviewed_at DESC`)

### `notes`

用户笔记主体。MVP 只保留笔记页与笔记抽屉；Agent 可辅助补全当前 Note，但不得把该字段解释为独立复盘草稿流程。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `user_id` | `uuid` | NOT NULL | FK -> `users.id` |
| `knowledge_point_id` | `uuid` | NOT NULL | FK -> `knowledge_points.id` |
| `title` | `text` | NOT NULL |  |
| `content_markdown` | `text` | NOT NULL DEFAULT `''` | 用户正文 |
| `agent_draft_content` | `text` | NULL | Note 内的 Agent 辅助补全内容，不自动生成完整笔记 |
| `is_user_edited` | `boolean` | NOT NULL DEFAULT `false` |  |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `deleted_at` | `timestamptz` | NULL |  |

约束与索引：

- `idx_notes_user_updated` on (`user_id`, `updated_at DESC`) WHERE `deleted_at IS NULL`
- `idx_notes_knowledge_point` on (`knowledge_point_id`) WHERE `deleted_at IS NULL`
- UNIQUE (`user_id`, `knowledge_point_id`) WHERE `deleted_at IS NULL`

### `idempotency_records`

写接口幂等记录。reset/delete 必须使该用户相关记录失效或删除，防止旧响应回放已清空的 plan/session/note 数据。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `key` | `text` | NOT NULL | PK，客户端或后端生成的幂等键 |
| `operation` | `text` | NOT NULL | 业务操作名，例如 `confirm_plan`、`run_learning_session_exercise` |
| `request_hash` | `text` | NOT NULL | 请求体稳定 hash |
| `response_json` | `jsonb` | NOT NULL | 可回放的 learner-safe 响应 |
| `user_id` | `uuid` | NULL | FK -> `users.id` ON DELETE SET NULL；用户级 reset/delete 使用 |
| `invalidated_at` | `timestamptz` | NULL | 非 NULL 表示该记录不得再回放 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |

约束与索引：

- `idx_idempotency_records_operation` on (`operation`)
- `idx_idempotency_records_user_active` on (`user_id`) WHERE `invalidated_at IS NULL`

### `stage_summaries`

阶段总结，用于跨模块衔接。V1 中 `stage` 不单独建模，`StageSummary` 以 `PlanModule` 为基础生成。

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `plan_id` | `uuid` | NOT NULL | FK -> `learning_plans.id` |
| `module_id` | `uuid` | NOT NULL | FK -> `plan_modules.id` |
| `version` | `integer` | NOT NULL DEFAULT `1` | CHECK `version >= 1` |
| `summary_text` | `text` | NOT NULL |  |
| `capability_message` | `text` | NULL | 面向用户的能力反馈 |
| `carry_forward_weak_points_json` | `jsonb` | NOT NULL DEFAULT `'[]'::jsonb` | 跨阶段携带薄弱点 |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |

约束与索引：

- UNIQUE (`module_id`, `version`)
- `idx_stage_summaries_plan_created` on (`plan_id`, `created_at DESC`)
- `idx_stage_summaries_module_created` on (`module_id`, `created_at DESC`)

## JSONB Schema

### `users.preferred_time_slots`

```json
[
  {
    "weekday": 1,
    "start": "20:00",
    "end": "21:00",
    "timezone": "Asia/Shanghai"
  }
]
```

规则：`weekday` 为 1-7；`start` 与 `end` 使用 `HH:mm`；第一版只接受 `timezone=Asia/Shanghai`。

### `users.reminder_preference`

```json
{
  "enabled": true,
  "channels": ["desktop"],
  "quiet_hours": {
    "start": "23:00",
    "end": "08:00",
    "timezone": "Asia/Shanghai"
  }
}
```

### `language_courses.supported_exercise_types_json`

```json
["code_blank", "fix_bug", "implement_function", "explain_code", "review_ai_patch"]
```

数组值必须来自 `Exercise.exercise_type` 枚举。

### `runtime_profiles.sandbox_policy`

```json
{
  "network": "disabled",
  "filesystem": "readonly",
  "dom_access": true,
  "max_processes": 1
}
```

### `knowledge_points.skill_tags_json`

```json
["dom", "event", "state_scope"]
```

### `knowledge_points.lesson_outline_json`

```json
[
  {
    "id": "core_concept",
    "title": "事件监听与状态变量",
    "note": "理解事件监听如何触发回调，以及状态变量为什么需要跨点击保存。"
  },
  {
    "id": "runtime_behavior",
    "title": "事件与状态行为",
    "note": "事件回调会在交互发生时运行；需要跨交互保留的状态应位于可复用的作用域。"
  }
]
```

`id` 必须在同一知识点内稳定；`note` 是面向学习页概念讲解的短说明，不应包含练习答案或 hidden tests。

### `knowledge_points.lesson_sources_json`

```json
[
  {
    "title": "MDN Web Docs: EventTarget.addEventListener()",
    "url": "https://developer.mozilla.org/docs/Web/API/EventTarget/addEventListener"
  }
]
```

来源用于说明本地课程提纲的官方文档依据；运行时不实时抓取外部文档。

### `learning_sessions.learning_stage_state_json`

```json
{
  "covered_subpoint_ids": ["core_concept", "runtime_behavior"],
  "feynman_status": "pending",
  "practice_unlock_reason": null,
  "learning_incomplete": true,
  "concept_summary": "事件监听与状态变量：理解事件监听如何触发回调...",
  "active_concept_intro": {
    "summary": "事件监听会把回调登记到按钮上...",
    "example": {
      "title": "点击计数",
      "body": "按钮每次被点击都会执行同一个回调...",
      "takeaway": "需要跨交互保留的状态不要放进每次都会重新执行的局部作用域。"
    },
    "check": {
      "type": "single_choice",
      "question": "count 放在 click 回调内部时，第二次点击会看到什么？",
      "options": [
        {"id": "A", "text": "从上次的 count 继续累加"},
        {"id": "B", "text": "重新从 0 开始"}
      ],
      "expected_focus": "回调作用域与跨点击状态共享的关系"
    }
  },
  "active_concept_check": {
    "type": "single_choice",
    "question": "count 放在 click 回调内部时，第二次点击会看到什么？",
    "options": [
      {"id": "A", "text": "从上次的 count 继续累加"},
      {"id": "B", "text": "重新从 0 开始"}
    ],
    "expected_focus": "回调作用域与跨点击状态共享的关系"
  },
  "concept_check_attempts": 0,
  "concept_check_result": null,
  "previous_misconceptions": []
}
```

该 JSON 只保存可恢复的精简阶段状态；完整学习页对话历史和可重放工具调用保存在 `learning_messages.metadata.tool_calls`，并通过刷新、恢复、幂等重放或用户触发的历史引用 UI 读取。

### `learning_sessions.review_stage_state_json`

```json
{
  "schema_version": "review_batch_v1",
  "review_stage": "warmup",
  "knowledge_point_id": "uuid",
  "seed_bank_id": "uuid",
  "seed_id": "seed_review_ai_patch_01",
  "batch": {
    "status": "active",
    "min_exercise_count": 3,
    "target_exercise_count": 4,
    "max_exercise_count": 6,
    "completed_count": 0,
    "current_exercise_id": "uuid",
    "current_candidate_id": "seed_review_ai_patch_01",
    "can_finalize": false
  },
  "warmup": {
    "question": "先用一句话回忆：事件监听与状态变量最容易错在哪里？",
    "expected_focus": "状态应位于能跨事件复用的作用域",
    "keywords": ["state", "count", "作用域", "事件"],
    "result": "pending",
    "recall_level": null,
    "last_answer": null,
    "repair_count": 0,
    "feedback": null,
    "diagnosis": {
      "recall_level": null,
      "confidence": null,
      "evidence": [],
      "missing_points": [],
      "misconception": "",
      "suggested_focus": []
    }
  },
  "session_diagnosis": {
    "recall_level": null,
    "weak_points": [],
    "passed_focus_tags": [],
    "failed_focus_tags": [],
    "skip_count": 0,
    "core_failure_count": 0,
    "last_result": null
  },
  "pool": {
    "seed_bank_id": "uuid",
    "generator_version": "review_candidate_pool_v1",
    "candidate_count": 12,
    "adaptive_supplements": []
  },
  "exercise_plan": [
    {
      "position": 1,
      "candidate_id": "seed_review_ai_patch_01",
      "exercise_id": "uuid",
      "status": "active",
      "capability": "transfer_or_review",
      "exercise_type": "review_ai_patch",
      "focus_tags": ["state_scope_error"],
      "is_core": true
    }
  ],
  "variant": {
    "exercise_id": "uuid",
    "exercise_type": "review_ai_patch",
    "guided": false
  },
  "finalization": {
    "status": "pending",
    "representative_attempt_id": null,
    "final_fsrs_rating": null,
    "aggregate_result": null
  }
}
```

`review_stage` 允许 `warmup`、`warmup_repair`、`exercise`、`exercise_feedback`、`final_summary`、`submitted`，并保留 `variant_practice` 读取旧会话。热身的 `correct`、`incorrect`、`unclear`、`skipped` 结果会归一成 `clear`、`wrong`、`fuzzy`、`skipped` 诊断，只写入该 JSON，用于刷新重放和本轮内选题，不创建 `Attempt`，不写 `review_logs`，不更新 `ReviewState`。

### `review_seed_banks.seeds_json`

```json
[
  {
    "id": "candidate_review_ai_patch_01",
    "knowledge_point_id": "uuid",
    "exercise_type": "review_ai_patch",
    "difficulty": 3,
    "capability": "transfer_or_review",
    "target_misconception": "state_scope_error",
    "focus_tags": ["state_scope_error", "ai_patch", "evidence"],
    "recommended_for": {
      "recall_levels": ["fuzzy", "wrong", "skipped"],
      "weak_points": ["state_scope_error"],
      "after_result": ["failed", "partial"]
    },
    "avoid_if": {
      "already_passed_focus_tags": ["state_scope_error"],
      "recent_candidate_ids": [],
      "unsupported_runtime_tiers": []
    },
    "warmup_question": "先回忆：事件状态最容易错在哪里？",
    "warmup_expected_focus": "状态变量作用域与连续事件行为",
    "review_focus": "用需求、diff 与可见行为共同判断状态作用域风险",
    "prompt_markdown": "审核 AI 对当前知识点代码的修改。",
    "starter_code": "const button = document.querySelector('#counter-button');",
    "metadata": {
      "requirement": "连续点击时计数必须持续递增。",
      "original_code": "let count = 0;",
      "ai_diff": "-let count = 0;\n+  let count = 0;",
      "expected_risk": "每次点击都会重新初始化 count",
      "expected_verdict": "fail",
      "expected_next_action": "request_change",
      "selection_reason": "用 AI patch 审核确认用户能基于需求、diff 与行为证据识别状态作用域风险。",
      "is_core": true,
      "rubric": {
        "verdict_correctness": "0-2",
        "evidence_grounding": "0-2",
        "knowledge_point_alignment": "0-2",
        "actionability": "0-2"
      }
    }
  }
]
```

同一 candidate pool 内候选题 `id` 必须唯一，题面和 starter code 需要做重复检测。`code_blank`、`fix_bug`、`implement_function` 和 `explain_code` 候选题可以包含可见测试和 hidden summary，但不得泄露隐藏测试源码或标准答案。候选池不是最终展示顺序，后端 graph 后续根据当前 session-local 诊断、已完成题和覆盖缺口选择具体题目。

### `knowledge_points.weak_points_json`

```json
[
  {
    "tag": "state_scope_error",
    "source_attempt_id": "uuid",
    "severity": "medium",
    "evidence": "count 被声明在 click 回调内部",
    "updated_at": "2026-05-11T12:00:00+08:00"
  }
]
```

`tag` 必须来自评分规格的错因分类；`severity` 为 `low` / `medium` / `high`。

### `knowledge_points.effective_hint_strategy`

```json
{
  "preferred_hint_level": "concept",
  "avoid": ["full_solution"],
  "last_effective_error_explanation": "用状态生命周期解释更有效"
}
```

`review_ai_patch` 也写入同一字段，不新增专表：

```json
{
  "result": "partial",
  "score": 6,
  "score_breakdown": {
    "verdict_correctness": 2,
    "evidence_grounding": 1,
    "knowledge_point_alignment": 2,
    "actionability": 1
  },
  "hard_gates": {
    "runtime_gate": true,
    "test_gate": false,
    "core_blank_gate": true,
    "explanation_gate": true
  },
  "weak_points": ["insufficient_test_or_diff_evidence"],
  "feedback": "结论方向可以，但证据不足。需要引用需求、diff 或可见测试，而不是只说 tests passed。",
  "next_action": "review_variant",
  "fsrs_rating": "Hard",
  "review_ai_patch_result": {
    "verdict": "fail",
    "expected_verdict": "fail",
    "evidence_quality": "weak",
    "expected_risk": "每次点击都会重新初始化 count",
    "learner_next_action": "request_change"
  }
}
```

`review_ai_patch` 的 score breakdown 固定为 `verdict_correctness`、`evidence_grounding`、`knowledge_point_alignment`、`actionability`。只说 `tests passed` 属于弱证据，即使 verdict 正确也不得映射为 `Easy`。

### `code_blanks.acceptable_patterns_json`

```json
[
  {
    "type": "literal",
    "value": "addEventListener"
  },
  {
    "type": "regex",
    "value": "count\\s*\\+=\\s*1"
  },
  {
    "type": "ast_semantic",
    "rule": "increments_shared_counter"
  }
]
```

### `test_cases.input_json` / `test_cases.expected_output_json`

```json
{
  "args": [1, 2],
  "stdin": "",
  "dom_events": [
    {
      "selector": "#button",
      "event": "click",
      "times": 3
    }
  ]
}
```

```json
{
  "stdout": "3",
  "return_value": 3,
  "dom": {
    "#output": "3"
  }
}
```

### `attempts.filled_blanks_json`

```json
{
  "blank_1": "addEventListener",
  "blank_2": "count += 1"
}
```

### `attempts.test_results_json`

```json
[
  {
    "case_id": "uuid",
    "case_type": "hidden",
    "passed": true,
    "weight": 2,
    "is_critical": true,
    "duration_ms": 34,
    "message": null
  }
]
```

### `attempts.score_breakdown_json`

```json
{
  "completion_correctness": 2,
  "runtime_and_tests": 2,
  "error_diagnosis": 1,
  "explanation_check": 2
}
```

四个字段必须存在，值必须为 0、1 或 2；四项之和必须等于 `attempts.score`。

### `attempts.explanation_check_result`

```json
{
  "result": "passed",
  "score": 2,
  "focus": "core_logic",
  "follow_up_required": false,
  "round_count": 1,
  "feedback": "能解释状态变量为什么放在监听器外层"
}
```

### `attempts.code_completion_result`

必须完整保存评分规格中的 `code_completion_result`：

```json
{
  "result": "passed",
  "score": 7,
  "score_breakdown": {
    "completion_correctness": 2,
    "runtime_and_tests": 2,
    "error_diagnosis": 1,
    "explanation_check": 2
  },
  "hard_gates": {
    "runtime_gate": true,
    "test_gate": true,
    "core_blank_gate": true,
    "explanation_gate": true
  },
  "test_pass_rate": 1.0,
  "hint_usage_count": 1,
  "error_count": 0,
  "weak_points": [],
  "error_cause": null,
  "feedback": "代码能稳定通过测试，且能解释状态变量为什么放在监听器外层。",
  "next_action": "schedule_review",
  "fsrs_rating": "Good"
}
```

### `review_states.fsrs_parameters`

```json
{
  "source": "default",
  "optimizer_version": null,
  "weights": [],
  "retention": 0.9
}
```

第一版可为空对象；启用 `fsrs-optimizer` 后写入参数版本和权重快照。

### `review_logs.previous_state_json` / `review_logs.next_state_json`

```json
{
  "card_state": "review",
  "stability": 3.42,
  "difficulty": 5.81,
  "due_at": "2026-05-13T01:00:00Z",
  "review_count": 2,
  "lapse_count": 0
}
```

### `stage_summaries.carry_forward_weak_points_json`

```json
[
  {
    "knowledge_point_id": "uuid",
    "tag": "async_order_error",
    "recommended_review_action": "review_variant"
  }
]
```

## 关系与删除策略

### 外键策略

- `users -> learning_plans -> plan_modules -> knowledge_points` 使用 `ON DELETE RESTRICT`。用户数据删除通过 `deleted_at` 或专门隐私擦除流程完成。
- `language_courses`、`runtime_profiles` 被历史练习引用后不得硬删，只能 `archived_at`。
- `exercises`、`test_cases`、`code_blanks` 被 `attempts` 引用后不得硬删，只能归档或软删除。
- `attempts` 和 `review_logs` 是事实日志，外键使用 `ON DELETE RESTRICT`。
- `notes` 可软删除；如果知识点被归档，笔记仍保留。
- local reset/delete 是专门隐私擦除流程：reset 保留 `users` 与偏好字段，delete 最后写 `users.deleted_at`，两者都必须先清空用户 owned learning data 并使相关 `idempotency_records` 不可回放。

### 软删除与归档

- 用户生成内容：`learning_plans`、`plan_modules`、`knowledge_points`、`exercises`、`notes` 使用 `deleted_at`。
- 课程配置与运行配置：`language_courses`、`runtime_profiles`、`test_cases` 使用 `archived_at`。
- 计划暂停不等于归档，使用 `LearningPlan.status=paused`。
- 完成计划不写 `deleted_at`，使用 `LearningPlan.status=completed` 和 `completed_at`。
- `Attempt` 写错时不得更新旧记录掩盖事实，应新增 `Attempt` 或将 `evaluation_status` 标为 `needs_manual_review`。

### 本地用户 reset/delete 顺序

- reset：保留 `users` 行与偏好设置；删除或清空 `learner_profiles`、`learning_plans`、`plan_modules`、`knowledge_points`、`exercises`、`code_blanks`、`test_cases`、`teaching_chunks`、`learning_sessions`、`attempts`、`review_states`、`review_logs`、`review_seed_banks`、`notes`、onboarding/learning/review messages 和 conversations。
- delete：执行与 reset 相同的 owned learning data 清理，然后设置 `users.deleted_at=now()`。normal product API 必须过滤 `users.deleted_at IS NULL`。
- 两者都必须先处理依赖顺序，避免 `ON DELETE RESTRICT` 约束失败；`attempts`、`review_logs` 在该隐私擦除流程中可硬删，因为它们属于被删除本地用户的 owned learning data。
- 两者都必须删除或失效该用户相关 `idempotency_records`，包括 `user_id` 匹配、key 或 stored response 中引用该用户 owned ids 的旧记录。

## Migration 顺序

### `0001_extensions_and_helpers`

- 创建 `pgcrypto` extension。
- 创建 `set_updated_at()` trigger function。
- 创建通用 CHECK helper 不强制，优先内联 CHECK。

回滚：删除 trigger function；`pgcrypto` 只有确认无其他表依赖时才删除。

### `0002_users_runtime_courses`

- 创建 `users`。
- 创建 `runtime_profiles`。
- 创建 `language_courses`。
- 创建相关索引和 `updated_at` triggers。

回滚：先 drop `language_courses`，再 drop `runtime_profiles`，最后 drop `users`。

### `0003_plans_modules`

- 创建 `learning_plans`，暂不添加 `current_module_id` FK。
- 创建 `plan_modules`。
- 添加 `learning_plans.current_module_id -> plan_modules.id` FK。
- 创建计划与模块索引。

回滚：先 drop `current_module_id` FK，再 drop `plan_modules`，最后 drop `learning_plans`。

### `0004_knowledge_exercise_catalog`

- 创建 `knowledge_points`，包含本地课程提纲 `lesson_outline_json` 和来源归因 `lesson_sources_json`，暂不添加 `last_session_id` FK。
- 创建 `exercises`。
- 创建 `code_blanks`。
- 创建 `test_cases`。
- 创建 GIN 与查询索引。

回滚：按 `test_cases`、`code_blanks`、`exercises`、`knowledge_points` 逆序删除。

### `0005_sessions_attempts_learning_results`

- 创建 `learning_sessions`，包含学习页 `learning_stage*` 和复习页 `review_stage*` 阶段字段。
- 创建 `learning_messages`，用于学习页 AI/用户对话历史引用。
- 创建 `attempts`。
- 创建 `session_knowledge_points`。
- 添加 `knowledge_points.last_session_id -> learning_sessions.id` FK。
- 创建幂等和查询索引。

回滚：先 drop `knowledge_points.last_session_id` FK，再按 `session_knowledge_points`、`attempts`、`learning_messages`、`learning_sessions` 逆序删除。

### `0006_review_state_and_logs`

- 创建 `review_states`。
- 创建 `review_seed_banks`。
- 创建 `review_logs`。
- 创建 `due_at` 查询索引。

回滚：先 drop `review_logs`，再 drop `review_seed_banks`，最后 drop `review_states`。回滚前必须确认调度 worker 已停止，避免任务读取空表。

### `0007_notes_stage_summaries`

- 创建 `notes`。
- 创建 `stage_summaries`。
- 创建查询索引。

回滚：按 `notes`、`stage_summaries` 逆序删除；如果已有用户内容，回滚前导出 markdown 和 JSON。

### `0008_seed_catalog`

- 写入第一版 `runtime_profiles`。
- 写入第一版 `language_courses`。
- 可选写入 demo `KnowledgePoint`、`Exercise`、`CodeBlank`、`TestCase`，但只能用于 dev/test 环境。

回滚：按 `slug` 删除 seed catalog；不得删除用户已引用的 seed 行，已引用时改写 `archived_at`。

## 回滚策略

- 开发环境允许 drop 新表；生产或真实用户数据环境禁止直接 drop 含业务数据表。
- 对新增列的回滚：先停止写入该列的服务版本，再 drop 列。
- 对约束收紧的回滚：先 drop 新约束，再保留数据。
- 对索引回滚：可 `DROP INDEX CONCURRENTLY`，不影响数据。
- 对种子数据回滚：优先 `archived_at=now()`，只有确认无 FK 引用时才物理删除。
- `review_logs` 与 `attempts` 不做数据回滚；如调度计算错误，通过新 `review_logs(source='manual_adjust')` 和更新 `review_states` 修正。

## 种子数据范围

第一版必须提供以下种子数据：

- `runtime_profiles`：
  - `rt_browser_js`：`runtime_tier=browser_preview`，`language=javascript`，`runner=browser`，支持 preview 和 tests。
  - `rt_browser_html_css`：`runtime_tier=browser_preview`，`language=html_css`，`runner=browser`，支持 preview 和 DOM assertions。
  - `rt_python_stdout`：`runtime_tier=python_stdout_test`，`language=python`，`runner=python`，支持 stdout 和 tests。
  - `rt_sql_sqlite_query`：`runtime_tier=sql_query_test`，`language=sql`，`runner=sql`，使用每次运行独立的 SQLite 教学数据库。
  - `rt_managed_compiled_java`：`runtime_tier=managed_compiled_test`，`language=java`，`runner=compiled`，支持本机 JDK 单文件教学练习。
  - `rt_managed_compiled_go`：`runtime_tier=managed_compiled_test`，`language=go`，`runner=compiled`，支持本机 Go 单包教学练习。
  - `rt_managed_compiled_csharp`：`runtime_tier=managed_compiled_test`，`language=csharp`，`runner=compiled`，支持本机 .NET 单文件教学练习。
  - `rt_compiled_later_cpp`：`runtime_tier=compiled_sandbox_later`，`language=cpp`，`runner=sandbox`，`compile_required=true`，只表示 C++ 内部/计划态执行边界，不是公开课程。
- `language_courses`：
  - JavaScript DOM beginner。
  - Python basic beginner。
  - HTML/CSS interaction beginner。
  - TypeScript Node beginner。
  - SQL query beginner。
  - Java managed compiled beginner。
  - Go basic beginner。
  - C# basic beginner。
  - 历史 `course_cpp_basic_placeholder` 需要归档，不作为 active public course。
- dev/test 环境可额外提供：
  - 1 个 demo user。
  - 1 个 `LearningPlan`。
  - 1 个 `PlanModule`。
  - 2-3 个 `KnowledgePoint`。
  - 每个 MVP runtime 至少 1 个 `Exercise`、2 个 `CodeBlank`、2 个 `TestCase`。

生产初始化不得创建 `Attempt`、`ReviewState`、`ReviewLog`、`LearningSession` 的假用户历史；这些只能由真实学习流程生成。

## 与 Agent 写库时机的对应

| LangGraph 节点 | 写入表 | 规则 |
|---|---|---|
| `confirm_plan` | `learning_plans`、`plan_modules`、`knowledge_points`、可选 `exercises` | 只有用户确认后写正式计划 |
| `initialize_review_state` | `review_states` | 为每个 `KnowledgePoint` 创建 `card_state=new`，`due_at=NULL` |
| `start_learning_session` / `start_review_session` | `learning_sessions` | 使用 `request_id` 幂等；学习页新会话写入 `learning_stage=documentation_reading`，不自动持久化 `show_concept_intro`；复习页新会话写入 `review_stage=warmup` 和完整 `review_stage_state_json` |
| `concept_check` / `concept_repair` / `practice_offer` | `learning_sessions`、`learning_messages` | 更新精简阶段状态并保存学习页可见对话和 `show_concept_check_result` 工具调用 |
| `ensure_review_seed_bank` | `review_seed_banks`、可选 `exercises` | 异步或同步 rescue 生成完整 candidate pool，校验通过后持久化到 `seeds_json`；rescue 失败记录 failed，不展示 fallback 题 |
| `record_review_warmup_result` | `learning_sessions` | 只更新 `review_stage` / `review_stage_state_json`，不创建 `Attempt`，不更新 FSRS |
| `run_exercise` / `run_review_exercise` | `attempts` | 保存运行事实，不更新 `ReviewState` |
| `evaluate_attempt` | `attempts` | 写 `score`、`score_breakdown_json`、`code_completion_result`、单题 `fsrs_rating` |
| `update_learning_memory` | `session_knowledge_points`、`knowledge_points`、`review_states`、`review_logs` | 在同一事务内提交 |
| `update_review_batch_state` | `learning_sessions`、可选 `exercises` | 复习中间题只更新 `review_batch_v1`、选择下一题或标记 `adaptive_supplement_status=needed`，不更新 FSRS |
| `finalize_review_batch` | `review_states`、`review_logs`、`knowledge_points`、`learning_sessions` | 用整批聚合 `final_fsrs_rating` 一次性更新 FSRS；`review_logs.attempt_id` 使用 representative attempt |
| `finish_learning_session` / `finish_review_session` | `learning_sessions`、必要时 `stage_summaries` | 生成摘要和恢复入口 |
| `assist_note_draft` | `notes` | 只回写 `agent_draft_content`，属于 Note 辅助补全，不创建独立复盘草稿流程 |

## 验收检查

- 所有核心对象都有表结构、字段类型、必填/默认值、主键、外键、唯一约束和索引。
- `Attempt.code_completion_result` 能完整保存评分 JSON。
- `ReviewState.due_at` 有可执行的 due 查询索引。
- `ReviewLog` 能追溯每次 FSRS 更新。
- `runtime_tier` 与运行能力分层一致。
- migration 可按顺序前进，也能按逆序安全回滚。
- `notes.agent_draft_content` 只服务 Note 辅助补全，不隐式依赖独立 `code_drafts` 表。

## 后置 Schema：`code_drafts`（非 MVP）

独立代码复盘草稿属于后置能力。Draft V1.1 不创建 `code_drafts` 表，不提供对应 migration，也不把它纳入 Agent 写库主链路；若后续恢复该能力，必须同步产品流程、API 契约、状态机与迁移顺序。

保留的后置草案如下：

| 字段 | 类型 | 必填/默认值 | 约束与说明 |
|---|---|---|---|
| `id` | `uuid` | NOT NULL DEFAULT `gen_random_uuid()` | PK |
| `note_id` | `uuid` | NOT NULL | FK -> `notes.id` |
| `attempt_id` | `uuid` | NULL | FK -> `attempts.id` |
| `draft_type` | `text` | NOT NULL | CHECK in `code_review` / `solution_explanation` / `ai_collaboration_prompt` |
| `version` | `integer` | NOT NULL DEFAULT `1` | CHECK `version >= 1` |
| `title` | `text` | NOT NULL |  |
| `content` | `text` | NOT NULL |  |
| `status` | `text` | NOT NULL DEFAULT `'draft'` | CHECK in `draft` / `exported` |
| `created_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT `now()` |  |
| `exported_at` | `timestamptz` | NULL |  |
| `deleted_at` | `timestamptz` | NULL |  |

后置索引建议：

- UNIQUE (`note_id`, `draft_type`, `version`)
- `idx_code_drafts_note` on (`note_id`) WHERE `deleted_at IS NULL`
- `idx_code_drafts_attempt` on (`attempt_id`) WHERE `attempt_id IS NOT NULL`
