# Aearn API 契约文档

日期：2026-05-13  
状态：Draft V1.1  
适用范围：桌面端前端、后端 API、runner service、LangGraph 编排层与 mock/契约测试

## 目标

本文件是第一版可实施 API 契约，承接产品流程、评分规则、状态机和数据库 Schema。第一版已经作为稳定基线；post-MVP / v1.1 增强必须复用或显式扩展本契约，不能通过隐式字段、前端本地判断或 provider 原始响应绕开公共 API。

第一版 API 必须支撑核心闭环：

```text
读代码 -> 补全关键代码 -> 运行/实时预览 -> 测试/错误反馈 -> Agent 提示/错因解释 -> 记录笔记 -> 复习调度
```

## 全局约定

### Base URL

- 本地开发：`http://127.0.0.1:8001`
- API 前缀：`/api`
- 默认内容类型：`Content-Type: application/json; charset=utf-8`
- 流式响应：`Content-Type: text/event-stream; charset=utf-8`

### 认证

V1 使用本地单用户或轻量用户机制，不强制登录态。所有需要用户上下文的接口必须显式传入 `user_id`，后续版本再替换为 Token / Session。

### 请求头

| Header | 必填 | 说明 |
|---|---|---|
| `X-Request-Id` | 建议 | 前端生成的请求追踪 ID，写入 `AgentState.request_id` |
| `Idempotency-Key` | 写操作建议 | 幂等键。缺省时后端按业务字段生成保守幂等键 |
| `Accept: text/event-stream` | 流式接口必填 | 要求接口以 SSE 返回事件流 |

### 时间与 ID

- 时间字段统一使用 ISO 8601 UTC 字符串，如 `2026-05-11T08:30:00Z`。
- 所有 `id` 第一版使用字符串，不暴露数据库自增 ID。
- 示例 ID 前缀仅用于可读性：`user_`、`course_`、`plan_`、`mod_`、`kp_`、`ex_`、`att_`、`sess_`、`note_`。

### 核心枚举

| 字段 | 枚举 |
|---|---|
| `language` | `javascript` / `python` / `java` / `cpp` / `html_css` |
| `runtime_tier` | `browser_preview` / `python_stdout_test` / `compiled_sandbox_later` |
| `runner` | `browser` / `python` / `sandbox` |
| `LearningPlan.status` | `active` / `paused` / `completed` |
| `PlanModule.status` | `pending` / `in_progress` / `completed` / `skipped` |
| `KnowledgePoint.status` | `pending` / `learning` / `reviewing` / `mastered` |
| `LearningSession.learning_stage` | `concept_intro` / `concept_check` / `concept_repair` / `practice_offer` / `concept_qna` / `readiness_check` / `practice_support` |
| `Exercise.exercise_type` | `code_blank` / `fix_bug` / `implement_function` / `explain_code` / `review_ai_patch` |
| `Attempt.attempt_type` | `run` / `submit` / `review_submit` |
| `Attempt.runtime_status` | `success` / `runtime_error` / `timeout` / `unsupported` |
| `code_completion_result.result` | `failed` / `partial` / `passed` / `easy` |
| `next_action` | `retry_same` / `show_hint` / `explain_error` / `review_variant` / `schedule_review` / `advance_next` |
| `fsrs_rating` | `Again` / `Hard` / `Good` / `Easy` |
| `hint_level` | `nudge` / `concept` / `code_shape` |

补充约束：

- `Attempt.attempt_type=run` / `submit` / `review_submit` 是后端事实枚举，用于运行留痕、评分、FSRS 和追溯。
- 前端 UI 不把 `run` / `submit` 暴露为“Attempt 类型”，只展示“运行 / 预览 / 提交结果”等自然操作。
- 设置页只允许修改用户偏好和模型配置，不提供修改评分规则、Attempt 必填字段或 FSRS 固定规则的 API。
- `language` 仍是服务端拥有的公开枚举。动态路线生成可以裁剪已登记课程的模块内容，但新增 TypeScript、Rust、Go 等公开语言必须同步扩展 Pydantic `Language`、数据库 CHECK 约束、课程 catalog、runtime boundary、API 示例和验收用例。

## 统一错误结构

所有非 2xx 响应必须返回：

```json
{
  "error": {
    "code": "PLAN_NOT_FOUND",
    "message": "学习计划不存在",
    "details": {
      "plan_id": "plan_404"
    },
    "request_id": "req_001",
    "recoverable": true,
    "next_action": "retry_same"
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `error.code` | 是 | 稳定错误码，前端按该字段分支 |
| `error.message` | 是 | 面向用户或开发者的简短说明 |
| `error.details` | 否 | 字段级错误、冲突对象、runner 细节等 |
| `error.request_id` | 是 | 对齐 `X-Request-Id` 或后端生成值 |
| `error.recoverable` | 是 | 前端是否可以展示重试入口 |
| `error.next_action` | 否 | 与状态机 `next_action` 对齐 |

### 错误码枚举

| 错误码 | 建议 HTTP | 说明 |
|---|---:|---|
| `VALIDATION_ERROR` | 400 | 请求字段缺失、类型错误或枚举非法 |
| `UNAUTHORIZED` | 401 | 后续鉴权版本使用 |
| `FORBIDDEN` | 403 | 用户无权访问对象 |
| `USER_NOT_FOUND` | 404 | 用户不存在 |
| `COURSE_NOT_FOUND` | 404 | 课程不存在 |
| `PLAN_NOT_FOUND` | 404 | 学习计划不存在 |
| `PLAN_DRAFT_INVALID` | 422 | `plan_draft` 无法转为 `LearningPlan` |
| `MODULE_NOT_FOUND` | 404 | 模块不存在 |
| `MODULE_NOT_SKIPPABLE` | 409 | 模块不允许跳过 |
| `KNOWLEDGE_POINT_NOT_FOUND` | 404 | 知识点不存在 |
| `EXERCISE_NOT_FOUND` | 404 | 练习不存在 |
| `SESSION_NOT_FOUND` | 404 | 学习会话不存在 |
| `SESSION_CONFLICT` | 409 | 存在同一用户同一知识点的活动会话 |
| `ATTEMPT_NOT_FOUND` | 404 | Attempt 不存在 |
| `ATTEMPT_STATE_CONFLICT` | 409 | Attempt 状态不允许当前操作 |
| `RUNTIME_UNSUPPORTED` | 422 | `RuntimeProfile.runtime_tier` 第一版不支持真实运行 |
| `MODEL_UNAVAILABLE` | 503 | 模型 API 未配置、不可连接或返回不可用响应 |
| `RUNNER_UNAVAILABLE` | 503 | runner service 不可用 |
| `RUNNER_TIMEOUT` | 504 | 运行或测试超时 |
| `EVALUATION_INVALID_JSON` | 502 | Agent 评分输出无法解析为 JSON |
| `EVALUATION_CONFLICT` | 422 | 评分结果与硬门槛或 FSRS 映射冲突 |
| `REVIEW_NOT_DUE` | 409 | 知识点未到复习时间 |
| `REVIEW_SEED_BANK_GENERATION_FAILED` | 503 | 复习 seed bank 生成或校验失败，不能展示低质量 fallback 题 |
| `NOTE_NOT_FOUND` | 404 | 笔记不存在 |
| `IDEMPOTENCY_CONFLICT` | 409 | 同一幂等键对应不同请求体 |
| `RATE_LIMITED` | 429 | 过于频繁请求提示、运行或 Agent 生成 |
| `INTERNAL_ERROR` | 500 | 未分类服务端错误 |

### 模型必需契约

下列 AI 驱动接口必须依赖已配置且可用的模型 API：建档对话槽位提取、学习页对话、练习提示/错因解释/解释检查、复习页教练文案和复习对话、笔记辅助补全。模型未配置、不可连接、调用失败、流式输出为空、输出不符合 schema，或 guardrail 判定输出不可安全展示时，接口必须返回 `MODEL_UNAVAILABLE`，不得退回关键词解析或确定性文案。

动态路线生成是 post-MVP 增强，不改变上面的模型失败总则：槽位提取和普通对话仍不得关键词兜底。它允许在已验证用户、课程 catalog 和 runtime boundary 的前提下，从 agent-generated modules 回退到服务端拥有的 `COURSE_TEMPLATES` 或已校验 onboarding plan candidate；fallback 必须写入 `source_attribution` 或 `agent_notes`，且不得承诺未登记语言、未支持 runtime 或隐藏测试能力。已命中幂等记录的历史成功响应可直接回放；服务端课程模板和 runner/FSRS 等非 AI 判定逻辑仍可保持确定性，因为它们不是模型失败兜底。

## 分页、排序与过滤

### 分页

列表接口默认使用 cursor 分页。

请求参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `limit` | `20` | 范围 `1-100` |
| `cursor` | `null` | 上一页返回的 `next_cursor` |

响应格式：

```json
{
  "items": [],
  "page_info": {
    "limit": 20,
    "next_cursor": "cursor_next_001",
    "has_more": true
  }
}
```

### 排序

排序参数统一为 `sort`，降序使用 `-` 前缀。

示例：

- `sort=created_at`
- `sort=-updated_at`
- `sort=due_at`

不支持的排序字段返回 `VALIDATION_ERROR`。

### 过滤

过滤参数使用业务字段名，例如：

- `status=active`
- `language=javascript`
- `knowledge_point_id=kp_dom_event_state`
- `due_before=2026-05-11T23:59:59Z`

非法枚举、非法时间格式或跨用户查询返回 `VALIDATION_ERROR` 或 `FORBIDDEN`。

## 幂等与重试总则

| 操作 | 幂等键 |
|---|---|
| 开始会话 | `user_id + plan_id + knowledge_point_id + active_session` |
| 运行练习 | `session_id + exercise_id + code_hash + run_mode` |
| 提交练习 | `session_id + exercise_id + attempt_id + submit_version` |
| 更新 `ReviewState` | `knowledge_point_id + attempt_id + fsrs_rating` |

重试规则：

1. `RUNNER_UNAVAILABLE`、`RUNNER_TIMEOUT`、`INTERNAL_ERROR` 可由前端重试。
2. 已创建 `Attempt` 的请求重试时不得重复运行代码，应读取已有 `Attempt` 并继续。
3. `ReviewState` 写入失败时不得向前端返回“复习完成”。
4. 同一 `Idempotency-Key` 搭配不同请求体必须返回 `IDEMPOTENCY_CONFLICT`。

## SSE 流式契约

第一版流式接口统一使用 SSE。客户端通过 `Accept: text/event-stream` 请求流式响应；非流式请求仍返回普通 JSON。

适用接口：

- `POST /api/plans/generate`
- `POST /api/learning-sessions/{session_id}/messages`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit`
- `POST /api/notes/{note_id}/agent-draft`

### 事件帧格式

```text
id: evt_001
event: agent_message
data: {"request_id":"req_001","session_id":"sess_001","content":"先观察这段 DOM 事件代码。"}

```

每个 `data` 必须是单行 JSON。流结束前必须发送 `done` 或 `error`。

### 事件类型

#### `agent_message`

用途：Agent 教学、提示、解释或笔记辅助补全的自然语言增量。

```json
{
  "request_id": "req_001",
  "session_id": "sess_001",
  "message_id": "msg_001",
  "delta": "先看 count 变量的位置。",
  "content": "先看 count 变量的位置。",
  "next_action": "show_hint"
}
```

#### `tool_status`

用途：LangGraph 节点或工具调用状态。

```json
{
  "request_id": "req_001",
  "session_id": "sess_001",
  "node": "run_exercise",
  "tool": "runner_service",
  "status": "running",
  "message": "正在执行 visible tests"
}
```

#### `tool_call`

用途：对话流中的生成式 UI 工具调用。学习页当前使用 `show_concept_intro` 生成概念开场卡，使用 `show_concept_check_result` 展示概念判断结果，使用 `show_code_exercise` 生成练习卡片，使用 `show_learning_history` 引用当前知识点的学习页历史对话。

```json
{
  "phase": "start",
  "tool_call_id": "tc_001",
  "name": "show_concept_intro"
}
```

```json
{
  "phase": "delta",
  "tool_call_id": "tc_001",
  "arguments_delta": "{\"session_id\":\"sess_001\""
}
```

```json
{
  "phase": "done",
  "tool_call_id": "tc_001",
  "arguments": {
    "session_id": "sess_001",
    "exercise": {
      "id": "ex_dom_click_count"
    },
    "learning_incomplete": false
  }
}
```

#### `runner_result`

用途：runner service 返回预览、stdout、stderr、测试结果。

```json
{
  "request_id": "req_001",
  "session_id": "sess_001",
  "attempt_id": "att_001",
  "runtime_status": "success",
  "preview_url": "app://preview/sess_001/att_001",
  "stdout": "",
  "stderr": "",
  "test_pass_rate": 1.0,
  "test_results": [
    {
      "case_id": "visible_initial",
      "case_type": "visible",
      "passed": true,
      "weight": 1
    }
  ],
  "next_action": "advance_next"
}
```

#### `evaluation_result`

用途：`evaluate_attempt` 输出最终 `code_completion_result`。

```json
{
  "request_id": "req_001",
  "session_id": "sess_001",
  "attempt_id": "att_001",
  "code_completion_result": {
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
    "feedback": "能通过测试，并能解释状态变量的生命周期。",
    "next_action": "schedule_review",
    "fsrs_rating": "Good"
  }
}
```

#### `done`

用途：流正常结束。

```json
{
  "request_id": "req_001",
  "session_id": "sess_001",
  "result_ref": {
    "type": "Attempt",
    "id": "att_001"
  }
}
```

#### `error`

用途：流中断或节点失败。

```json
{
  "error": {
    "code": "RUNNER_TIMEOUT",
    "message": "代码运行超时",
    "details": {
      "timeout_ms": 3000
    },
    "request_id": "req_001",
    "recoverable": true,
    "next_action": "retry_same"
  }
}
```

### SSE 顺序要求

- 练习运行：`tool_status` -> `runner_result` -> `done`，失败时以 `error` 结束。
- 提交评分：`tool_status` -> `runner_result` 可选 -> `evaluation_result` -> `done`。
- Agent 讲解：可以多次发送 `agent_message`；若触发生成式 UI，发送 `tool_call start/delta/done`；最后必须发送 `done`。
- `id` 必须单调递增，断线重连时后端可根据 `Last-Event-ID` 尽力补发最近事件；V1 不承诺完整事件回放。

## 核心对象响应片段

### `RuntimeProfile`

```json
{
  "id": "rt_browser_js",
  "runtime_tier": "browser_preview",
  "language": "javascript",
  "runner": "browser",
  "supports_realtime_preview": true,
  "supports_stdout": true,
  "supports_tests": true,
  "compile_required": false,
  "timeout_ms": 3000,
  "memory_limit_mb": 128,
  "sandbox_policy": "dom_preview_only"
}
```

### `KnowledgePoint`

```json
{
  "id": "kp_dom_event_state",
  "module_id": "mod_dom",
  "language_course_id": "course_js_dom",
  "title": "事件监听与状态变量",
  "description": "理解事件回调和外层状态变量的关系",
  "skill_tags_json": ["dom", "event", "state"],
  "status": "learning",
  "mastery_score": 0.42,
  "weak_points_json": ["state_scope_error"],
  "effective_hint_strategy": "先提示变量生命周期，再提示事件绑定位置",
  "last_exercise_result": "partial",
  "last_exercise_score": 5,
  "last_exercise_breakdown_json": {
    "completion_correctness": 2,
    "runtime_and_tests": 1,
    "error_diagnosis": 1,
    "explanation_check": 1
  },
  "last_explanation_check_result": "partial",
  "last_session_id": "sess_001"
}
```

### `Exercise`

```json
{
  "id": "ex_dom_click_count",
  "knowledge_point_id": "kp_dom_event_state",
  "runtime_profile_id": "rt_browser_js",
  "title": "点击按钮后计数递增",
  "exercise_type": "code_blank",
  "prompt_markdown": "补全事件绑定代码，让按钮每点击一次数字加 1。",
  "starter_code": "let count = 0;\nbutton.__BLANK_1__('click', () => {\n  __BLANK_2__;\n  output.textContent = count;\n});",
  "visible_test_policy": "show_first_failure",
  "difficulty": 2,
  "estimated_minutes": 8,
  "runtime_profile": {
    "id": "rt_browser_js",
    "runtime_tier": "browser_preview",
    "language": "javascript",
    "supports_realtime_preview": true,
    "supports_tests": true
  },
  "code_blanks": [
    {
      "id": "blank_1",
      "blank_key": "blank_1",
      "placeholder": "事件绑定方法",
      "expected_concept": "DOM event listener",
      "order_index": 1
    }
  ],
  "visible_tests": [
    {
      "id": "tc_visible_initial",
      "case_type": "visible",
      "input_json": {
        "clicks": 1
      },
      "expected_output_json": {
        "text": "1"
      },
      "weight": 1,
      "timeout_ms": 1000,
      "order_index": 1
    }
  ]
}
```

## 接口契约

### 1. 用户与设置

#### `POST /api/users`

用途：创建本地用户画像，后续 `LearningPlan`、`LearningSession`、`ReviewState` 均通过 `user_id` 关联。

Request JSON 示例：

```json
{
  "display_name": "Pinking",
  "learning_style": "practice_first",
  "teaching_preference": "step_by_step",
  "encouragement_preference": "direct",
  "profession": "frontend_developer",
  "background_context": "有 Vue 经验，正在补 JavaScript 基础和 AI 辅助编程验证能力。",
  "preferred_time_slots": [
    {
      "weekday": "mon",
      "start": "20:00",
      "end": "21:00"
    }
  ],
  "reminder_preference": {
    "enabled": true,
    "channel": "desktop",
    "quiet_hours": {
      "start": "23:00",
      "end": "08:00"
    }
  }
}
```

Response JSON 示例：

```json
{
  "user": {
    "id": "user_001",
    "display_name": "Pinking",
    "learning_style": "practice_first",
    "teaching_preference": "step_by_step",
    "encouragement_preference": "direct",
    "profession": "frontend_developer",
    "background_context": "有 Vue 经验，正在补 JavaScript 基础和 AI 辅助编程验证能力。",
    "preferred_time_slots": [
      {
        "weekday": "mon",
        "start": "20:00",
        "end": "21:00"
      }
    ],
    "reminder_preference": {
      "enabled": true,
      "channel": "desktop",
      "quiet_hours": {
        "start": "23:00",
        "end": "08:00"
      }
    },
    "created_at": "2026-05-11T08:00:00Z",
    "updated_at": "2026-05-11T08:00:00Z"
  }
}
```

HTTP 状态码：

- `201`：创建成功
- `400`：请求字段不合法
- `409`：本地单用户模式下已存在用户

错误码：`VALIDATION_ERROR`、`IDEMPOTENCY_CONFLICT`、`INTERNAL_ERROR`

幂等/重试说明：建议使用 `Idempotency-Key=create-user-{client_uuid}`；重试时返回同一 `user`。

相关数据表/状态机节点：`User`；无 Agent 节点。

#### `GET /api/users/{user_id}`

用途：查询用户基础信息和设置。

Request JSON 示例：

```json
{
  "path_params": {
    "user_id": "user_001"
  },
  "query": {}
}
```

Response JSON 示例：

```json
{
  "user": {
    "id": "user_001",
    "display_name": "Pinking",
    "learning_style": "practice_first",
    "teaching_preference": "step_by_step",
    "encouragement_preference": "direct",
    "profession": "frontend_developer",
    "background_context": "有 Vue 经验。",
    "preferred_time_slots": [],
    "reminder_preference": {
      "enabled": true,
      "channel": "desktop"
    },
    "created_at": "2026-05-11T08:00:00Z",
    "updated_at": "2026-05-11T08:10:00Z"
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `404`：用户不存在

错误码：`USER_NOT_FOUND`、`FORBIDDEN`

幂等/重试说明：安全可重试；可使用 HTTP 缓存，但前端设置页进入时应重新拉取。

相关数据表/状态机节点：`User`；`context_assembler` 读取用户画像。

#### `PATCH /api/users/{user_id}/preferences`

用途：更新学习偏好、提醒偏好、职业与背景信息。该接口不接受评分规则、Attempt 写入策略或 FSRS 固定规则配置。

Request JSON 示例：

```json
{
  "teaching_preference": "example_then_practice",
  "encouragement_preference": "direct",
  "profession": "fullstack_developer",
  "background_context": "正在学习 Python 测试和 JavaScript DOM。",
  "preferred_time_slots": [
    {
      "weekday": "sat",
      "start": "09:30",
      "end": "10:30"
    }
  ],
  "reminder_preference": {
    "enabled": false,
    "channel": "desktop"
  }
}
```

Response JSON 示例：

```json
{
  "user": {
    "id": "user_001",
    "teaching_preference": "example_then_practice",
    "encouragement_preference": "direct",
    "profession": "fullstack_developer",
    "background_context": "正在学习 Python 测试和 JavaScript DOM。",
    "preferred_time_slots": [
      {
        "weekday": "sat",
        "start": "09:30",
        "end": "10:30"
      }
    ],
    "reminder_preference": {
      "enabled": false,
      "channel": "desktop"
    },
    "updated_at": "2026-05-11T08:15:00Z"
  }
}
```

HTTP 状态码：

- `200`：更新成功
- `400`：字段不合法
- `404`：用户不存在

错误码：`VALIDATION_ERROR`、`USER_NOT_FOUND`

幂等/重试说明：PATCH 使用字段覆盖语义，同一请求体可安全重试。

相关数据表/状态机节点：`User`；`context_assembler` 后续读取更新后的画像。

### 2. 语言课程与练习目录

#### `GET /api/language-courses`

用途：获取可学习的编程语言或技术栈课程列表。

Request JSON 示例：

```json
{
  "query": {
    "language": "javascript",
    "level": "beginner",
    "limit": 20,
    "cursor": null,
    "sort": "language"
  }
}
```

Response JSON 示例：

```json
{
  "items": [
    {
      "id": "course_js_dom",
      "language": "javascript",
      "title": "JavaScript DOM 基础",
      "description": "通过浏览器预览和 DOM 断言学习事件、状态和渲染。",
      "level": "beginner",
      "runtime_profile_id": "rt_browser_js",
      "runtime_profile": {
        "id": "rt_browser_js",
        "runtime_tier": "browser_preview",
        "language": "javascript",
        "supports_realtime_preview": true,
        "supports_tests": true
      },
      "supported_exercise_types_json": ["code_blank", "fix_bug", "implement_function"]
    }
  ],
  "page_info": {
    "limit": 20,
    "next_cursor": null,
    "has_more": false
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `400`：过滤或排序参数不合法

错误码：`VALIDATION_ERROR`

幂等/重试说明：只读接口，可安全重试；mock 与真实环境必须保持枚举一致。

相关数据表/状态机节点：`LanguageCourse`、`RuntimeProfile`；`select_language_course`。

#### `GET /api/language-courses/{course_id}/exercises`

用途：按课程和可选知识点获取练习列表，供计划生成、学习会话和复习变体选择。

Request JSON 示例：

```json
{
  "path_params": {
    "course_id": "course_js_dom"
  },
  "query": {
    "knowledge_point_id": "kp_dom_event_state",
    "exercise_type": "code_blank",
    "difficulty": 2,
    "limit": 20,
    "cursor": null,
    "sort": "difficulty"
  }
}
```

Response JSON 示例：

```json
{
  "items": [
    {
      "id": "ex_dom_click_count",
      "knowledge_point_id": "kp_dom_event_state",
      "runtime_profile_id": "rt_browser_js",
      "title": "点击按钮后计数递增",
      "exercise_type": "code_blank",
      "difficulty": 2,
      "estimated_minutes": 8,
      "runtime_profile": {
        "id": "rt_browser_js",
        "runtime_tier": "browser_preview",
        "language": "javascript",
        "supports_realtime_preview": true,
        "supports_tests": true
      }
    }
  ],
  "page_info": {
    "limit": 20,
    "next_cursor": null,
    "has_more": false
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `400`：过滤参数不合法
- `404`：课程或知识点不存在

错误码：`COURSE_NOT_FOUND`、`KNOWLEDGE_POINT_NOT_FOUND`、`VALIDATION_ERROR`

幂等/重试说明：只读接口，可安全重试。

相关数据表/状态机节点：`LanguageCourse`、`KnowledgePoint`、`Exercise`、`RuntimeProfile`；`select_exercise`、`select_review_variant`。

### 3. 学习计划

#### `POST /api/onboarding/messages`

用途：以多轮建档对话收集语言、目标和当前水平；当必需信息齐备时，通过 SSE `tool_call` 事件生成对话内学习路线卡片，并暂存最新 `plan_draft`。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "onboarding_session_id": "onboarding_001",
  "role": "user",
  "content": "我想用 Python 做自动化脚本，看过基础语法",
  "client_message_id": "desktop_onboarding_msg_001"
}
```

SSE 行为：

- 信息不足时发送简短 `agent_message`，每轮只追问一个关键缺口。
- `language`、`target_level`、`goal_text` 齐备时，先发送简短 `agent_message`，再发送 `tool_call(name="show_learning_route")`；完整路线内容只放在工具参数中。
- `time_budget` 为可选字段；用户之后补充时间、方向或难度时，服务重新暂存草稿并发送新的 `show_learning_route` 工具调用，工具参数会携带新的节奏信息。
- 同一建档会话只有最新暂存草稿可确认；前端必须将历史路线卡片的 `开始学习` 置为禁用。
- 建档对话不提供关键词或确定性兜底解析；槽位提取和普通回复依赖模型 API。模型未配置、不可连接、流式中断前无有效输出，或结构化槽位输出非法时，SSE 返回 `error.code=MODEL_UNAVAILABLE`，不更新槽位、不生成路线卡片。

`show_learning_route` arguments 示例：

```json
{
  "plan_id": "plan_draft_001",
  "goal_text": "学习 Python，聚焦自动化，从入门到进阶",
  "language": "python",
  "time_budget": {
    "minutes_per_day": 120,
    "days_per_week": 1
  },
  "modules": []
}
```

#### `POST /api/onboarding/{session_id}/confirm_plan`

用途：确认建档会话中最新暂存的 `plan_draft`，创建正式 `LearningPlan` 后进入学习流程。该接口不接受历史卡片指定旧草稿。

Request JSON 示例：

```json
{
  "user_id": "user_001"
}
```

错误码：`ONBOARDING_SESSION_NOT_FOUND`、`USER_MISMATCH`、`PLAN_DRAFT_NOT_READY`、`PLAN_DRAFT_INVALID`、`IDEMPOTENCY_CONFLICT`

#### `POST /api/plans/generate`

用途：根据目标、资料或澄清答案生成可确认的 `plan_draft`，不直接创建正式 `LearningPlan`。post-MVP 动态路线生成开启时，后端可先用 `plan_generation_agent` 参考权威文档目录和用户目标生成 modules；成功结果仍必须保持 `PlanDraft` 结构，失败则回退到服务端拥有的课程模板或已校验 SDK candidate。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "mode": "goal_based",
  "goal_text": "两周内掌握 JavaScript DOM 事件，并能验证 AI 生成代码。",
  "language": "javascript",
  "course_id": "course_js_dom",
  "target_level": "beginner_to_intermediate",
  "materials": [
    {
      "type": "text",
      "title": "已有学习笔记",
      "content": "事件绑定、状态变量、querySelector 基础。"
    }
  ],
  "time_budget": {
    "minutes_per_day": 30,
    "days_per_week": 5,
    "deadline": "2026-05-25"
  },
  "profession": "frontend_developer",
  "clarification_answers": [
    {
      "question_id": "q_runtime",
      "answer": "优先浏览器实时预览。"
    }
  ]
}
```

Response JSON 示例：

```json
{
  "plan_draft": {
    "draft_id": "plan_draft_001",
    "user_id": "user_001",
    "language_course_id": "course_js_dom",
    "goal_text": "两周内掌握 JavaScript DOM 事件，并能验证 AI 生成代码。",
    "language": "javascript",
    "target_level": "beginner_to_intermediate",
    "mode": "goal_based",
    "deadline": "2026-05-25",
    "modules": [
      {
        "temp_id": "mod_draft_dom",
        "title": "DOM 事件与状态",
        "description": "用按钮计数、输入框同步和事件委托练习状态更新。",
        "order_index": 1,
        "is_skippable": false,
        "is_adjustable": true,
        "estimated_sessions": 3,
        "knowledge_points": [
          {
            "temp_id": "kp_draft_dom_event_state",
            "title": "事件监听与状态变量",
            "exercise_refs": ["ex_dom_click_count"]
          }
        ]
      }
    ],
    "runtime_boundary": {
      "runtime_tier": "browser_preview",
      "unsupported_languages": ["java", "cpp"]
    }
  },
  "agent_notes": [
    "第一版会优先用浏览器预览和 DOM 断言验证。"
  ],
  "next_action": "advance_next"
}
```

HTTP 状态码：

- `200`：生成成功
- `400`：目标或课程参数不合法
- `404`：用户或课程不存在
- `422`：无法生成可练习计划

错误码：`USER_NOT_FOUND`、`COURSE_NOT_FOUND`、`PLAN_DRAFT_INVALID`、`VALIDATION_ERROR`、`EVALUATION_INVALID_JSON`

幂等/重试说明：建议幂等键为 `user_id + goal_text_hash + course_id + materials_hash`。流式模式可先发送 `agent_message` 澄清，再发送最终 `done`。动态路线生成失败但 fallback 成功时不暴露 provider 原始错误；如果课程不存在、语言未登记、fallback 草稿也无法通过校验，则返回 `COURSE_NOT_FOUND` 或 `PLAN_DRAFT_INVALID`。

相关数据表/状态机节点：读取 `User`、`LanguageCourse`、`RuntimeProfile`、`Exercise`；`collect_goal`、`clarify_profile`、`select_language_course`、`generate_plan_draft`、`validate_plan_draft`。动态增强额外使用 `plan_generation_agent`、`web_search`、`fetch_doc_toc`，但不拥有正式计划写入。

#### `POST /api/plans`

用途：用户确认 `plan_draft` 后创建正式 `LearningPlan`、`PlanModule`、`KnowledgePoint`，并初始化 `ReviewState`。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "plan_draft": {
    "draft_id": "plan_draft_001",
    "language_course_id": "course_js_dom",
    "goal_text": "两周内掌握 JavaScript DOM 事件，并能验证 AI 生成代码。",
    "language": "javascript",
    "target_level": "beginner_to_intermediate",
    "mode": "goal_based",
    "deadline": "2026-05-25",
    "modules": [
      {
        "temp_id": "mod_draft_dom",
        "title": "DOM 事件与状态",
        "description": "用按钮计数练习状态更新。",
        "order_index": 1,
        "is_skippable": false,
        "is_adjustable": true,
        "estimated_sessions": 3,
        "knowledge_points": [
          {
            "temp_id": "kp_draft_dom_event_state",
            "title": "事件监听与状态变量",
            "description": "理解事件回调和外层状态变量的关系。"
          }
        ]
      }
    ]
  }
}
```

Response JSON 示例：

```json
{
  "LearningPlan": {
    "id": "plan_001",
    "user_id": "user_001",
    "language_course_id": "course_js_dom",
    "goal_text": "两周内掌握 JavaScript DOM 事件，并能验证 AI 生成代码。",
    "language": "javascript",
    "target_level": "beginner_to_intermediate",
    "mode": "goal_based",
    "deadline": "2026-05-25",
    "status": "active",
    "overall_progress": 0,
    "current_module_id": "mod_dom"
  },
  "modules": [
    {
      "id": "mod_dom",
      "plan_id": "plan_001",
      "title": "DOM 事件与状态",
      "order_index": 1,
      "status": "pending",
      "is_skippable": false,
      "is_adjustable": true,
      "estimated_sessions": 3
    }
  ],
  "knowledge_points": [
    {
      "id": "kp_dom_event_state",
      "module_id": "mod_dom",
      "language_course_id": "course_js_dom",
      "title": "事件监听与状态变量",
      "status": "pending",
      "mastery_score": 0
    }
  ],
  "next_entry_point": {
    "type": "learning_session",
    "plan_id": "plan_001",
    "knowledge_point_id": "kp_dom_event_state"
  }
}
```

HTTP 状态码：

- `201`：创建成功
- `400`：请求结构不合法
- `404`：用户或课程不存在
- `422`：`plan_draft` 未通过校验
- `409`：同一用户已有冲突的活动计划

错误码：`USER_NOT_FOUND`、`COURSE_NOT_FOUND`、`PLAN_DRAFT_INVALID`、`IDEMPOTENCY_CONFLICT`

幂等/重试说明：幂等键建议为 `user_id + plan_draft.draft_id`。如果 `LearningPlan` 已创建，重试返回已有计划。

相关数据表/状态机节点：`LearningPlan`、`PlanModule`、`KnowledgePoint`、`ReviewState`；`confirm_plan`、`initialize_review_state`、`finish_onboarding`。

#### `GET /api/plans/{plan_id}`

用途：获取学习计划详情、模块、知识点和当前入口。

Request JSON 示例：

```json
{
  "path_params": {
    "plan_id": "plan_001"
  },
  "query": {
    "include": "modules,knowledge_points,review_state"
  }
}
```

Response JSON 示例：

```json
{
  "LearningPlan": {
    "id": "plan_001",
    "user_id": "user_001",
    "language_course_id": "course_js_dom",
    "goal_text": "两周内掌握 JavaScript DOM 事件，并能验证 AI 生成代码。",
    "language": "javascript",
    "target_level": "beginner_to_intermediate",
    "mode": "goal_based",
    "deadline": "2026-05-25",
    "status": "active",
    "overall_progress": 0.12,
    "current_module_id": "mod_dom"
  },
  "modules": [
    {
      "id": "mod_dom",
      "status": "in_progress",
      "knowledge_points": [
        {
          "id": "kp_dom_event_state",
          "title": "事件监听与状态变量",
          "status": "reviewing",
          "mastery_score": 0.62,
          "ReviewState": {
            "knowledge_point_id": "kp_dom_event_state",
            "due_at": "2026-05-12T08:00:00Z",
            "last_fsrs_rating": "Good"
          }
        }
      ]
    }
  ],
  "next_entry_point": {
    "type": "resume",
    "session_id": "sess_001",
    "next_action": "advance_next"
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `404`：计划不存在

错误码：`PLAN_NOT_FOUND`、`FORBIDDEN`

幂等/重试说明：只读接口，可安全重试。

相关数据表/状态机节点：`LearningPlan`、`PlanModule`、`KnowledgePoint`、`ReviewState`；`load_resume_context` 可读取该结构。

#### `PATCH /api/plans/{plan_id}/modules/{module_id}`

用途：调整模块状态、跳过模块或修改模块安排。只有 `is_skippable=true` 的模块可跳过。

Request JSON 示例：

```json
{
  "status": "skipped",
  "reason": "已有工作经验，跳过基础选择器模块。",
  "estimated_sessions": 1
}
```

Response JSON 示例：

```json
{
  "module": {
    "id": "mod_selector",
    "plan_id": "plan_001",
    "title": "DOM 选择器基础",
    "status": "skipped",
    "is_skippable": true,
    "is_adjustable": true,
    "estimated_sessions": 1
  },
  "risk_warning": null,
  "next_entry_point": {
    "type": "learning_session",
    "knowledge_point_id": "kp_dom_event_state"
  }
}
```

HTTP 状态码：

- `200`：更新成功
- `400`：字段不合法
- `404`：计划或模块不存在
- `409`：模块不可跳过或调整会破坏知识主干

错误码：`PLAN_NOT_FOUND`、`MODULE_NOT_FOUND`、`MODULE_NOT_SKIPPABLE`、`VALIDATION_ERROR`

幂等/重试说明：同一 PATCH 请求体可安全重试；如果调整触发 `risk_warning`，前端必须再次确认后再提交。

相关数据表/状态机节点：`LearningPlan`、`PlanModule`、`KnowledgePoint`；无 Agent 必经节点，可影响 `decide_resume_entry`。

### 4. 学习会话

#### `POST /api/learning-sessions/start`

用途：开始一次学习会话，创建或恢复活动 `LearningSession(session_type=learn)`。新会话先生成并持久化 `show_concept_intro`，进入 `concept_check`，默认不返回练习；只有已解锁练习的恢复会话才返回当前 `Exercise`。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "plan_id": "plan_001",
  "knowledge_point_id": "kp_dom_event_state"
}
```

Response JSON 示例：

```json
{
  "session_id": "sess_001",
  "session_type": "learn",
  "context_snapshot": {
    "current_stage": "DOM 事件",
    "LearningPlan": {
      "id": "plan_001",
      "current_module_id": "mod_dom"
    },
    "KnowledgePoint": {
      "id": "kp_dom_event_state",
      "title": "事件监听与状态变量",
      "status": "learning"
    },
    "RuntimeProfile": {
      "id": "rt_browser_js",
      "runtime_tier": "browser_preview",
      "language": "javascript",
      "supports_realtime_preview": true,
      "supports_tests": true
    }
  },
  "exercise": null,
  "lesson_outline": [
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
  ],
  "lesson_sources": [
    {
      "title": "MDN Web Docs: EventTarget.addEventListener()",
      "url": "https://developer.mozilla.org/docs/Web/API/EventTarget/addEventListener"
    }
  ],
  "learning_stage": "concept_check",
  "learning_stage_state": {
    "covered_subpoint_ids": [],
    "feynman_status": "pending",
    "practice_unlock_reason": null,
    "learning_incomplete": true,
    "concept_summary": "事件监听与状态变量：理解事件监听如何触发回调，以及状态变量为什么需要跨点击保存。",
    "active_concept_intro": {
      "summary": "事件监听会把回调登记到按钮上，状态变量要放在能跨点击保留的位置。",
      "example": {
        "title": "点击计数",
        "body": "按钮每次被点击都会执行同一个回调；如果 count 在回调外层，下一次点击能看到上一次的值。",
        "takeaway": "需要跨交互保留的状态不要放进每次都会重新执行的局部作用域。"
      },
      "check": {
        "question": "count 放在 click 回调内部时，第二次点击会看到什么？",
        "options": [
          {"id": "A", "text": "从上次的 count 继续累加"},
          {"id": "B", "text": "重新从 0 开始"}
        ],
        "expected_focus": "回调作用域与跨点击状态共享的关系"
      }
    },
    "active_concept_check": {
      "question": "count 放在 click 回调内部时，第二次点击会看到什么？",
      "options": [
        {"id": "A", "text": "从上次的 count 继续累加"},
        {"id": "B", "text": "重新从 0 开始"}
      ],
      "expected_focus": "回调作用域与跨点击状态共享的关系"
    },
    "concept_check_attempts": 0,
    "concept_check_result": null
  },
  "initial_agent_message": "今天先理解事件监听与状态变量，目标是能说明它如何影响程序行为，而不是立刻做题。",
  "initial_tool_calls": [
    {
      "id": "tc_001",
      "name": "show_concept_intro",
      "status": "done",
      "args": {
        "session_id": "sess_001",
        "knowledge_point_id": "kp_dom_event_state",
        "summary": "事件监听会把回调登记到按钮上，状态变量要放在能跨点击保留的位置。",
        "example": {
          "title": "点击计数",
          "body": "按钮每次被点击都会执行同一个回调；如果 count 在回调外层，下一次点击能看到上一次的值。",
          "takeaway": "需要跨交互保留的状态不要放进每次都会重新执行的局部作用域。"
        },
        "check": {
          "question": "count 放在 click 回调内部时，第二次点击会看到什么？",
          "options": [
            {"id": "A", "text": "从上次的 count 继续累加"},
            {"id": "B", "text": "重新从 0 开始"}
          ],
          "expected_focus": "回调作用域与跨点击状态共享的关系"
        }
      }
    }
  ],
  "session_state": "learning"
}
```

HTTP 状态码：

- `201`：新会话已创建
- `200`：复用已有活动会话
- `404`：用户、计划或知识点不存在
- `409`：会话冲突且无法复用
- `503`：概念开场生成失败或输出校验失败

错误码：`USER_NOT_FOUND`、`PLAN_NOT_FOUND`、`KNOWLEDGE_POINT_NOT_FOUND`、`SESSION_CONFLICT`、`CONCEPT_INTRO_GENERATION_FAILED`

幂等/重试说明：幂等键为 `user_id + plan_id + knowledge_point_id + active_session`。重试不得创建多个活动会话；已创建会话必须重放持久化的 `initial_tool_calls`，不得重新生成漂移的概念开场。

相关数据表/状态机节点：`LearningSession`、`LearningPlan`、`KnowledgePoint`、`RuntimeProfile`、`LearningMessage`；`start_learning_session`、`context_assembler`、`concept_intro`、`concept_check`。练习只在 `practice_support` 阶段进入 `select_exercise`、`present_exercise`。

#### `POST /api/learning-sessions/{session_id}/messages`

用途：发送学习对话消息，获取 Agent 讲解、追问或下一步建议。该接口不产生最终评分。

阶段规则：

- `concept_check`：围绕 `show_concept_intro` 的判断题接收自然语言回答，返回持久化 `show_concept_check_result`；不主动展示完整题面或 starter code。
- `concept_repair`：首次判断错误后只修正一个误解，返回更窄的 `repair_check`；两次失败后停止盘问，提供另一个例子或引导练习。
- `practice_offer`：概念判断正确后等待用户确认是否开始练习；确认后进入 `practice_support`，`practice_unlock_reason=concept_check_passed`。
- `practice_support`：允许围绕真实练习、运行事实、hint 和错因解释继续对话。
- 用户在 `concept_check` / `concept_repair` 中明确要求提前练习时可进入 `practice_support`，但必须先持久化 `show_concept_check_result(result=skipped)`，且 `show_code_exercise` 参数必须带 `practice_unlock_reason=concept_check_skipped`、`learning_incomplete=true` 和概念小结。

Request JSON 示例：

```json
{
  "role": "user",
  "content": "B，因为放在回调里面每次点击都会重新从 0 开始。",
  "client_message_id": "msg_client_001"
}
```

Response JSON 示例：

```json
{
  "agent_message": {
    "id": "msg_agent_001",
    "role": "assistant",
    "content": "你的判断是对的。关键关系是：事件回调会重复执行，跨点击状态必须放在回调外层。要开始做一个小练习吗？"
  },
  "session_state": {
    "session_id": "sess_001",
    "next_action": "retry_same",
    "current_stage": "DOM 事件",
    "learning_stage": "practice_offer",
    "learning_stage_state": {
      "covered_subpoint_ids": [],
      "feynman_status": "pending",
      "practice_unlock_reason": null,
      "learning_incomplete": false,
      "concept_check_result": "correct"
    }
  },
  "tool_calls": [
    {
      "name": "show_concept_check_result",
      "args": {
        "session_id": "sess_001",
        "knowledge_point_id": "kp_dom_event_state",
        "result": "correct",
        "confidence": "high",
        "explanation": "放在回调内部会导致每次点击重新初始化，不能跨点击保存状态。",
        "next_prompt": "要开始做一个小练习吗？",
        "actions": [{"id": "start_practice", "label": "开始练习"}],
        "repair_check": null
      }
    }
  ]
}
```

HTTP 状态码：

- `200`：响应成功
- `400`：消息为空或角色非法
- `404`：会话不存在
- `503`：模型 API 未配置、不可连接、输出为空或输出不安全
- `429`：对话过于频繁

错误码：`SESSION_NOT_FOUND`、`VALIDATION_ERROR`、`MODEL_UNAVAILABLE`、`RATE_LIMITED`

模型说明：学习页对话不提供确定性教学文案兜底。模型失败或输出被 guardrail 拦截时，JSON 模式返回 `MODEL_UNAVAILABLE`；SSE 模式发送一个 `error.code=MODEL_UNAVAILABLE` 事件并终止，不写入成功的 assistant 响应或幂等成功记录。

幂等/重试说明：使用 `client_message_id` 去重；SSE 模式可增量返回多个 `agent_message` 和 `tool_call` 事件。

相关数据表/状态机节点：`LearningSession`、`LearningMessage`；`context_assembler`、`concept_check`、`concept_repair`、`practice_offer`、`practice_support`、`teaching_prompt`。

#### `GET /api/learning-sessions/history`

用途：按知识点读取学习页对话历史，用于用户主动回看概念判断、修正或旧费曼检查相关对话。该接口只读取 `session_type=learn` 的 `learning_messages`，不包含建档页、复习页或笔记页对话。

Request JSON 示例：

```json
{
  "query": {
    "user_id": "user_001",
    "knowledge_point_id": "kp_dom_event_state",
    "active_session_id": "sess_001"
  }
}
```

Response JSON 示例：

```json
{
  "knowledge_point_id": "kp_dom_event_state",
  "knowledge_point_title": "事件监听与状态变量",
  "active_session_id": "sess_001",
  "sessions": [
    {
      "session_id": "sess_001",
      "is_active": true,
      "status": "active",
      "started_at": "2026-05-25T11:20:00Z",
      "messages": [
        {
          "id": "msg_001",
          "role": "agent",
          "content": "今天先理解事件监听与状态变量...",
          "created_at": "2026-05-25T11:20:01Z"
        },
        {
          "id": "msg_002",
          "role": "user",
          "content": "我认为状态需要保存在回调外层。",
          "created_at": "2026-05-25T11:21:02Z"
        }
      ]
    }
  ]
}
```

HTTP 状态码：

- `200`：查询成功
- `404`：用户或知识点不存在

错误码：`KNOWLEDGE_POINT_NOT_FOUND`

幂等/重试说明：只读接口，可安全重试；默认按当前会话优先，其后按会话开始时间倒序返回。

相关数据表/状态机节点：`LearningSession`、`LearningMessage`、`KnowledgePoint`；`show_learning_history`。

#### `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run`

用途：运行当前代码，返回浏览器预览、stdout、stderr 或测试执行结果，并创建 `Attempt(attempt_type=run)`。该内部类型只服务后端事实记录，不作为前端 UI 概念展示。

Request JSON 示例：

```json
{
  "code": "let count = 0;\nbutton.addEventListener('click', () => {\n  count += 1;\n  output.textContent = count;\n});",
  "filled_blanks": {
    "blank_1": "addEventListener",
    "blank_2": "count += 1"
  },
  "runtime_profile_id": "rt_browser_js",
  "run_mode": "visible_tests",
  "code_hash": "sha256:run001"
}
```

Response JSON 示例：

```json
{
  "attempt_id": "att_run_001",
  "attempt_type": "run",
  "runtime_status": "success",
  "preview_url": "app://preview/sess_001/att_run_001",
  "stdout": "",
  "stderr": "",
  "test_pass_rate": 1.0,
  "passed_test_count": 2,
  "total_test_count": 2,
  "test_results": [
    {
      "case_id": "visible_initial",
      "case_type": "visible",
      "passed": true,
      "weight": 1,
      "message": "点击一次后输出为 1"
    }
  ],
  "error_message": null,
  "next_action": "advance_next"
}
```

HTTP 状态码：

- `200`：命中相同代码的已有 Attempt
- `201`：运行完成并创建 Attempt；M3 最小切片下 `compiled_sandbox_later` 也写入 `Attempt(run)`，并返回 `runtime_status=unsupported`
- `400`：请求字段不合法
- `404`：会话或练习不存在
- `503`：runner 不可用
- `504`：runner 超时

错误码：`SESSION_NOT_FOUND`、`EXERCISE_NOT_FOUND`、`RUNNER_UNAVAILABLE`、`RUNNER_TIMEOUT`、`VALIDATION_ERROR`

幂等/重试说明：幂等键为 `session_id + exercise_id + code_hash + run_mode`。若已生成 `Attempt`，重试返回原 `attempt_id` 和运行结果。

相关数据表/状态机节点：`Exercise`、`RuntimeProfile`、`Attempt`；`run_exercise`、`route_runtime_result`、`hint_or_explain_error`。

#### `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit`

用途：提交练习结果并生成最终 `code_completion_result`，写回 `Attempt(attempt_type=submit)`、`KnowledgePoint` 和 `ReviewState`。前端只展示“提交结果”，不暴露内部 Attempt 类型。

Request JSON 示例：

```json
{
  "attempt_id": "att_run_001",
  "submit_version": 1,
  "code": "let count = 0;\nbutton.addEventListener('click', () => {\n  count += 1;\n  output.textContent = count;\n});",
  "explanation": "count 放在回调外层，这样多次点击会共享同一个状态。",
  "hint_usage_count": 1,
  "error_count": 0
}
```

Response JSON 示例：

```json
{
  "attempt_id": "att_submit_001",
  "code_completion_result": {
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
    "feedback": "代码通过测试，也能解释状态变量位置。",
    "next_action": "schedule_review",
    "fsrs_rating": "Good"
  },
  "KnowledgePoint": {
    "id": "kp_dom_event_state",
    "status": "reviewing",
    "mastery_score": 0.68,
    "last_exercise_result": "passed",
    "last_exercise_score": 7
  },
  "ReviewState": {
    "knowledge_point_id": "kp_dom_event_state",
    "due_at": "2026-05-12T08:00:00Z",
    "last_attempt_id": "att_submit_001",
    "last_fsrs_rating": "Good"
  },
  "next_action": "schedule_review"
}
```

HTTP 状态码：

- `200`：提交成功或幂等返回
- `400`：字段不合法
- `404`：会话、练习或 Attempt 不存在
- `409`：Attempt 状态不允许提交
- `422`：评分结果与硬门槛冲突
- `502`：Agent JSON 输出无效且无法修复

错误码：`ATTEMPT_NOT_FOUND`、`ATTEMPT_STATE_CONFLICT`、`EVALUATION_CONFLICT`、`EVALUATION_INVALID_JSON`、`VALIDATION_ERROR`

幂等/重试说明：幂等键为 `session_id + exercise_id + attempt_id + submit_version`。重试必须返回同一个 `code_completion_result`，不得重复推进 `ReviewState.due_at`。

相关数据表/状态机节点：`Attempt`、`SessionKnowledgePoint`、`KnowledgePoint`、`ReviewState`；`check_explanation`、`evaluate_attempt`、`route_evaluation_result`、`update_learning_memory`。

#### `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint`

用途：获取分层提示并增加当前 Attempt 或会话级 `hint_usage_count`。

Request JSON 示例：

```json
{
  "attempt_id": "att_run_001",
  "current_code": "let count = 0;\nbutton.addEventListener('click', () => {\n  output.textContent = count;\n});",
  "blank_id": "blank_2",
  "hint_level": "concept"
}
```

Response JSON 示例：

```json
{
  "hint": {
    "hint_level": "concept",
    "content": "这里需要在每次点击时更新状态变量，再把状态同步到页面。"
  },
  "hint_usage_count": 2,
  "affected_score": {
    "max_result": "passed",
    "score_penalty_hint": 1
  },
  "next_action": "retry_same",
  "generation_source": "llm",
  "generation_model": "third-party-model"
}
```

HTTP 状态码：

- `200`：提示生成成功
- `400`：提示层级或空缺 ID 不合法
- `404`：会话、练习或 Attempt 不存在
- `503`：模型 API 未配置、不可连接、输出为空或输出不安全
- `429`：提示请求过于频繁

错误码：`SESSION_NOT_FOUND`、`EXERCISE_NOT_FOUND`、`ATTEMPT_NOT_FOUND`、`VALIDATION_ERROR`、`MODEL_UNAVAILABLE`、`RATE_LIMITED`

幂等/重试说明：同一 `attempt_id + blank_id + hint_level` 在短时间重试应返回相同提示，不重复增加 `hint_usage_count`。

相关数据表/状态机节点：`Attempt`、`CodeBlank`；`hint_or_explain_error`、`hint_prompt`。

#### `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`

用途：解释运行错误、测试失败或编译错误，并记录 `error_cause`。

Request JSON 示例：

```json
{
  "error_message": "Expected textContent to be '3' after three clicks, got '1'.",
  "stderr": "",
  "failed_tests": [
    {
      "case_id": "hidden_three_clicks",
      "case_type": "hidden",
      "message": "连续点击三次后状态未累加"
    }
  ],
  "current_code": "button.addEventListener('click', () => {\n  let count = 0;\n  count += 1;\n  output.textContent = count;\n});"
}
```

Response JSON 示例：

```json
{
  "error_cause": "state_scope_error",
  "explanation": "count 写在回调内部，每次点击都会重新变成 0，所以页面始终显示 1。",
  "fix_suggestion": "把 count 移到事件回调外层，只在回调里执行 count += 1。",
  "related_knowledge_points": [
    {
      "id": "kp_dom_event_state",
      "title": "事件监听与状态变量"
    }
  ],
  "next_action": "retry_same"
}
```

HTTP 状态码：

- `200`：解释成功
- `400`：错误上下文缺失
- `404`：会话或 Attempt 不存在
- `503`：模型 API 未配置、不可连接、输出为空或输出不安全

错误码：`SESSION_NOT_FOUND`、`ATTEMPT_NOT_FOUND`、`VALIDATION_ERROR`、`MODEL_UNAVAILABLE`

模型说明：`generation_source` 为可选非敏感诊断字段，成功生成时取值为 `llm`；`generation_model` 为可选模型标识。真实 API key、provider 原始错误和隐藏测试源码不得返回给前端。模型未配置、请求失败、超时、返回非法 JSON 或不符合 schema 时，后端必须返回 `MODEL_UNAVAILABLE`，不回退到确定性错因解释。

幂等/重试说明：同一 Attempt 的相同错误上下文可安全重试；不重复增加 `error_count`，只更新 `Attempt.error_cause`。命中幂等记录时不得再次调用模型。

相关数据表/状态机节点：`Attempt`、`KnowledgePoint`；`hint_or_explain_error`、`explain_error_prompt`。

#### `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation`

用途：检查用户是否理解关键代码、边界条件或 AI 辅助改动，写回 `Attempt.explanation_check_result`。

Request JSON 示例：

```json
{
  "explanation": "状态变量在回调外层，所以多次点击会累加；如果写在回调里，每次点击都会重新初始化。",
  "focus": "core_logic",
  "round": 1
}
```

Response JSON 示例：

```json
{
  "result": "passed",
  "score": 2,
  "score_breakdown": {
    "explanation_check": 2
  },
  "follow_up_required": false,
  "feedback": "解释覆盖了状态生命周期和错误写法。",
  "next_action": "advance_next"
}
```

HTTP 状态码：

- `200`：检查完成
- `400`：解释为空或 focus 非法
- `404`：会话或 Attempt 不存在
- `422`：超过解释检查轮次
- `503`：模型 API 未配置、不可连接、输出为空或输出不安全

错误码：`SESSION_NOT_FOUND`、`ATTEMPT_NOT_FOUND`、`VALIDATION_ERROR`、`EVALUATION_CONFLICT`、`MODEL_UNAVAILABLE`

幂等/重试说明：同一 `attempt_id + round` 可安全重试；最多 2 轮，超过后必须进入 `evaluate_attempt`。

相关数据表/状态机节点：`Attempt`；`check_explanation`。

#### `POST /api/learning-sessions/{session_id}/finish`

用途：结束学习会话，生成摘要、阶段反馈并写回 `LearningSession.next_entry_point`。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "summary_hint": "今天完成 DOM 事件状态变量练习。",
  "client_duration_seconds": 1200
}
```

Response JSON 示例：

```json
{
  "session_summary": {
    "session_id": "sess_001",
    "summary_text": "完成按钮计数练习，主要薄弱点是状态变量作用域。",
    "duration_seconds": 1180
  },
  "stage_feedback": {
    "current_stage": "DOM 事件",
    "capability_message": "可以解释状态变量为什么需要跨事件回调保存。",
    "carry_forward_weak_points_json": ["state_scope_error"]
  },
  "next_entry_point": {
    "type": "review_or_next_lesson",
    "plan_id": "plan_001",
    "knowledge_point_id": "kp_dom_input_sync",
    "next_action": "advance_next"
  }
}
```

HTTP 状态码：

- `200`：结束成功
- `404`：会话不存在
- `409`：会话已经结束

错误码：`SESSION_NOT_FOUND`、`SESSION_CONFLICT`

幂等/重试说明：同一会话重复 finish 返回已写入的 `summary_text` 和 `next_entry_point`。

相关数据表/状态机节点：`LearningSession`、`StageSummary`；`finish_learning_session`。

#### `GET /api/learning-sessions/resume`

用途：恢复最近一次中断学习，返回最小上下文和下一入口，不重放完整历史对话。

规则补充：

- 如果最近一次学习会话缺少 `summary_text`，服务端会基于当前知识点和最近一次 Attempt 合成摘要。
- 如果不存在可恢复的有效学习会话，仍返回 `200`，但 `resume_available=false`，并给出回退到当前学习知识点的 `learning_session` 入口。
- 学习页恢复不自动重放 `learning_messages`。概念判断、修正、旧费曼检查兼容状态和练习解锁状态由 `learning_stage` 与 `learning_stage_state` 随 `POST /api/learning-sessions/start` 返回。
- 用户需要回看完整学习页历史时，前端显式调用 `GET /api/learning-sessions/history`。

Request JSON 示例：

```json
{
  "query": {
    "user_id": "user_001",
    "plan_id": "plan_001"
  }
}
```

Response JSON 示例：

```json
{
  "last_session_summary": "上次完成按钮计数练习，解释通过但使用过一次概念提示。",
  "next_entry_point": {
    "type": "learning_session",
    "plan_id": "plan_001",
    "knowledge_point_id": "kp_dom_input_sync",
    "next_action": "advance_next"
  },
  "current_module": {
    "id": "mod_dom",
    "title": "DOM 事件与状态"
  },
  "current_stage": "DOM 事件",
  "today_review_count": 2,
  "resume_available": true
}
```

HTTP 状态码：

- `200`：查询成功
- `404`：用户或计划不存在

错误码：`USER_NOT_FOUND`、`PLAN_NOT_FOUND`

幂等/重试说明：只读接口，可安全重试；返回值可能随 `ReviewState.due_at` 到期变化。

相关数据表/状态机节点：`LearningSession`、`StageSummary`、`ReviewState`、`Attempt`；`load_resume_context`、`decide_resume_entry`、`assemble_resume_message`。

### 5. 复习

#### `GET /api/reviews/today`

用途：获取今日待复习列表，按 `ReviewState.due_at` 排序。

Request JSON 示例：

```json
{
  "query": {
    "user_id": "user_001",
    "due_before": "2026-05-11T23:59:59Z",
    "limit": 20,
    "cursor": null,
    "sort": "due_at"
  }
}
```

Response JSON 示例：

```json
{
  "items": [
    {
      "ReviewState": {
        "knowledge_point_id": "kp_dom_event_state",
        "card_state": "review",
        "stability": 2.3,
        "difficulty": 5.1,
        "due_at": "2026-05-11T09:00:00Z",
        "last_review_at": "2026-05-10T09:00:00Z",
        "review_count": 2,
        "lapse_count": 0,
        "last_attempt_id": "att_submit_001",
        "last_fsrs_rating": "Good"
      },
      "KnowledgePoint": {
        "id": "kp_dom_event_state",
        "title": "事件监听与状态变量",
        "weak_points_json": ["state_scope_error"]
      }
    }
  ],
  "page_info": {
    "limit": 20,
    "next_cursor": null,
    "has_more": false
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `400`：时间或分页参数不合法
- `404`：用户不存在

错误码：`USER_NOT_FOUND`、`VALIDATION_ERROR`

幂等/重试说明：只读接口，可安全重试；列表会随时间和提交结果变化。

相关数据表/状态机节点：`ReviewState`、`KnowledgePoint`、`Attempt`；`load_due_review`。

#### `POST /api/reviews/start`

用途：开始一条复习任务，确保当前知识点有可用 `review_seed_bank`，创建或复用 `LearningSession(session_type=review)`，返回短热身、复习阶段状态和持久化变体练习。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "knowledge_point_id": "kp_dom_event_state"
}
```

Response JSON 示例：

```json
{
  "session_id": "sess_review_001",
  "session_type": "review",
  "knowledge_point": {
    "id": "kp_dom_event_state",
    "title": "事件监听与状态变量",
    "weak_points_json": ["state_scope_error"]
  },
  "review_exercise": {
    "id": "ex_dom_toggle_state_variant",
    "exercise_type": "review_ai_patch",
    "runtime_profile_id": "rt_browser_js",
    "title": "审核 AI 对事件状态代码的修改",
    "metadata_json": {
      "requirement": "连续点击时计数必须持续递增。",
      "original_code": "let count = 0;\nbutton.addEventListener('click', () => { count += 1; });",
      "ai_diff": "-let count = 0;\n button.addEventListener('click', () => {\n+  let count = 0;\n   count += 1;",
      "review_focus": "用需求、diff 与可见行为共同判断状态作用域风险",
      "expected_risk": "count 被移进回调后每次点击都会重新初始化",
      "rubric": {
        "verdict_correctness": "0-2",
        "evidence_grounding": "0-2",
        "knowledge_point_alignment": "0-2",
        "actionability": "0-2"
      }
    }
  },
  "warmup": {
    "question": "先用一句话回忆：事件监听与状态变量最容易错在哪里？",
    "expected_focus": "状态应位于能跨事件复用的作用域",
    "keywords": ["state", "count", "作用域", "事件"],
    "result": "pending",
    "repair_count": 0,
    "last_answer": null,
    "feedback": null
  },
  "review_stage": "warmup",
  "review_stage_state": {
    "review_stage": "warmup",
    "knowledge_point_id": "kp_dom_event_state",
    "seed_bank_id": "rsb_001",
    "seed_id": "seed_review_ai_patch_01",
    "warmup": {
      "result": "pending",
      "repair_count": 0
    },
    "variant": {
      "exercise_id": "ex_dom_toggle_state_variant",
      "exercise_type": "review_ai_patch",
      "guided": false
    }
  },
  "selected_seed_id": "seed_review_ai_patch_01",
  "seed_bank": {
    "id": "rsb_001",
    "status": "ready",
    "generator_version": "review_seed_bank_v1",
    "seed_count": 12,
    "generated_at": "2026-05-11T09:19:00Z",
    "quality_report": {
      "required_type_coverage": true,
      "contains_review_ai_patch": true
    }
  },
  "variant_reason": "上次错因是 state_scope_error，本次换成同构状态保存场景。",
  "initial_agent_message": "这次不重复原题，我们看一个开关按钮状态保存问题。"
}
```

HTTP 状态码：

- `201`：复习会话创建成功
- `200`：同一到期复习会话幂等返回
- `404`：用户或知识点不存在
- `409`：当前知识点未到复习时间
- `503`：模型 API 未配置、不可连接、输出为空、输出不安全，或 seed bank rescue 生成失败

错误码：`USER_NOT_FOUND`、`KNOWLEDGE_POINT_NOT_FOUND`、`REVIEW_NOT_DUE`、`SESSION_CONFLICT`、`MODEL_UNAVAILABLE`、`REVIEW_SEED_BANK_GENERATION_FAILED`

Seed bank 说明：正常路径由 worker 在计划或知识点创建后预生成完整 seed bank；如果复习开始时缺失或失效，`POST /api/reviews/start` 可以同步 rescue 生成同一份完整 seed bank，并先持久化再选择 seed。异步生成和同步 rescue 必须共用 generator、schema、校验、安全检查和持久化路径。rescue 失败时返回 `REVIEW_SEED_BANK_GENERATION_FAILED`，不得展示低质量 fallback 问题。

模型说明：复习页的 `variant_reason` 和 `initial_agent_message` 必须来自模型生成并通过安全校验。模型不可用或输出不安全时返回 `MODEL_UNAVAILABLE`，不得退回本地固定复习文案。Seed bank 中不得包含 hidden tests、`solution_reference`、raw prompt、provider 原始错误或 secrets。

幂等/重试说明：幂等键为 `user_id + knowledge_point_id + due_at`。同一到期项重试返回同一 `session_id`。

相关数据表/状态机节点：`LearningSession`、`ReviewState`、`KnowledgePoint`、`ReviewSeedBank`、`Exercise`；`start_review_session`、`load_due_review`、`ensure_review_seed_bank`、`select_review_seed`、`present_review_warmup`、`present_review_exercise`。

#### `POST /api/reviews/{session_id}/warmup-result`

用途：提交或跳过短热身，只更新复习会话阶段状态，不创建 `Attempt`，不写 `review_logs`，不更新 `ReviewState`。

Request JSON 示例：

```json
{
  "action": "answer",
  "answer": "count 要放在能跨多次点击复用的外层作用域，不能每次回调重新初始化。"
}
```

跳过热身：

```json
{
  "action": "skip"
}
```

Response JSON 示例：

```json
{
  "session_id": "sess_review_001",
  "review_stage": "variant_practice",
  "warmup": {
    "question": "先用一句话回忆：事件监听与状态变量最容易错在哪里？",
    "expected_focus": "状态应位于能跨事件复用的作用域",
    "result": "correct",
    "last_answer": "count 要放在能跨多次点击复用的外层作用域。",
    "repair_count": 0,
    "feedback": "热身通过，继续完成变体练习。"
  },
  "review_stage_state": {
    "review_stage": "variant_practice",
    "knowledge_point_id": "kp_dom_event_state",
    "seed_bank_id": "rsb_001",
    "seed_id": "seed_review_ai_patch_01"
  },
  "next_action": "start_variant"
}
```

HTTP 状态码：

- `200`：热身结果记录成功
- `400`：字段不合法
- `404`：复习会话不存在
- `409`：复习会话状态冲突

错误码：`SESSION_NOT_FOUND`、`SESSION_CONFLICT`、`VALIDATION_ERROR`

阶段规则：`correct`、`skipped` 直接进入 `variant_practice`；`incorrect` 或 `unclear` 最多进入一次 `warmup_repair`，第二次仍不通过时进入带引导的 `variant_practice`。任何 warmup 分支都不得触发 FSRS。

相关数据表/状态机节点：`LearningSession`；`record_review_warmup_result`、`present_review_exercise`。

#### `POST /api/reviews/{session_id}/exercise-result`

用途：提交复习变体练习结果，写入 `Attempt(attempt_type=review_submit)`，生成 `code_completion_result`，并更新 `ReviewState`。这是复习页唯一可以推进 FSRS 的写入。

Request JSON 示例：

```json
{
  "exercise_id": "ex_dom_toggle_state_variant",
  "attempt_id": "att_review_run_001",
  "code": "let enabled = false;\nbutton.addEventListener('click', () => {\n  enabled = !enabled;\n  output.textContent = enabled ? 'on' : 'off';\n});",
  "test_pass_rate": 1.0,
  "hint_usage_count": 0,
  "error_count": 0,
  "explanation_check": {
    "result": "passed",
    "score": 2,
    "feedback": "能解释状态为什么在回调外层。"
  }
}
```

`review_ai_patch` Request JSON 示例：

```json
{
  "exercise_id": "ex_dom_ai_patch_review",
  "review_ai_patch_answer": {
    "verdict": "fail",
    "evidence": "需求要求连续点击持续递增，但 diff 把 count 移进 click 回调；可见测试只覆盖一次点击，不能证明连续点击。",
    "knowledge_point_risk": "状态变量作用域错误会导致每次事件回调重新初始化 count。",
    "next_action": "request_change"
  }
}
```

Response JSON 示例：

```json
{
  "result": "easy",
  "score": 8,
  "score_breakdown": {
    "completion_correctness": 2,
    "runtime_and_tests": 2,
    "error_diagnosis": 2,
    "explanation_check": 2
  },
  "fsrs_rating": "Easy",
  "weak_points": [],
  "feedback": "复习变体完成稳定，可以延长下次复习间隔。",
  "due_at": "2026-05-16T09:00:00Z",
  "forget_risk": "low",
  "ReviewState": {
    "knowledge_point_id": "kp_dom_event_state",
    "card_state": "review",
    "stability": 5.8,
    "difficulty": 4.7,
    "due_at": "2026-05-16T09:00:00Z",
    "last_review_at": "2026-05-11T09:20:00Z",
    "review_count": 3,
    "lapse_count": 0,
    "last_attempt_id": "att_review_submit_001",
    "last_fsrs_rating": "Easy"
  },
  "next_action": "advance_next"
}
```

`review_ai_patch` 的 `score_breakdown` 使用 `verdict_correctness`、`evidence_grounding`、`knowledge_point_alignment`、`actionability` 四项，并在 `code_completion_result.review_ai_patch_result` 中保存 learner verdict、expected verdict、evidence quality、expected risk 和 learner next action。只说 `tests passed` 属于弱证据；即使结论方向正确，也不得映射为 `Easy`。

HTTP 状态码：

- `200`：提交成功或幂等返回
- `400`：字段不合法
- `404`：复习会话、练习或 Attempt 不存在
- `409`：复习会话状态冲突
- `422`：评分与 FSRS 映射冲突

错误码：`SESSION_NOT_FOUND`、`EXERCISE_NOT_FOUND`、`ATTEMPT_NOT_FOUND`、`EVALUATION_CONFLICT`、`VALIDATION_ERROR`

幂等/重试说明：幂等键为 `knowledge_point_id + attempt_id + fsrs_rating`。重试不得重复增加 `review_count` 或重复推进 `due_at`。

相关数据表/状态机节点：`Attempt`、`ReviewState`、`KnowledgePoint`、`LearningSession`；`run_review_exercise`、`check_explanation`、`evaluate_attempt`、`update_review_state`、`finish_review_session`。

### 6. 笔记

#### `GET /api/notes`

用途：查询知识点相关笔记。第一版基线的笔记入口只来自笔记页和笔记抽屉，不存在独立复盘草稿页。

Request JSON 示例：

```json
{
  "query": {
    "user_id": "user_001",
    "knowledge_point_id": "kp_dom_event_state",
    "limit": 20,
    "cursor": null,
    "sort": "-updated_at"
  }
}
```

Response JSON 示例：

```json
{
  "items": [
    {
      "id": "note_001",
      "user_id": "user_001",
      "knowledge_point_id": "kp_dom_event_state",
      "title": "状态变量位置",
      "content_markdown": "状态变量要放在事件回调外层，才能跨多次点击保存。",
      "agent_draft_content": "可以补充一个错误示例：把 count 写进回调内部。",
      "is_user_edited": true,
      "updated_at": "2026-05-11T09:30:00Z"
    }
  ],
  "page_info": {
    "limit": 20,
    "next_cursor": null,
    "has_more": false
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `404`：用户或知识点不存在

错误码：`USER_NOT_FOUND`、`KNOWLEDGE_POINT_NOT_FOUND`

幂等/重试说明：只读接口，可安全重试。

相关数据表/状态机节点：`Note`、`KnowledgePoint`；`context_assembler` 可读取摘要，不读取全部笔记正文。

#### `POST /api/notes`

用途：创建用户笔记。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "knowledge_point_id": "kp_dom_event_state",
  "title": "状态变量位置",
  "content_markdown": "count 不能写在 click 回调内部。",
  "source": {
    "session_id": "sess_001",
    "attempt_id": "att_submit_001"
  }
}
```

Response JSON 示例：

```json
{
  "note": {
    "id": "note_001",
    "user_id": "user_001",
    "knowledge_point_id": "kp_dom_event_state",
    "title": "状态变量位置",
    "content_markdown": "count 不能写在 click 回调内部。",
    "agent_draft_content": null,
    "is_user_edited": true,
    "updated_at": "2026-05-11T09:30:00Z"
  }
}
```

HTTP 状态码：

- `201`：创建成功
- `400`：内容为空或字段不合法
- `404`：用户或知识点不存在

错误码：`USER_NOT_FOUND`、`KNOWLEDGE_POINT_NOT_FOUND`、`VALIDATION_ERROR`

幂等/重试说明：建议幂等键为 `user_id + knowledge_point_id + content_hash`。

相关数据表/状态机节点：`Note`；无 Agent 必经节点。

#### `PATCH /api/notes/{note_id}`

用途：更新笔记标题或正文。

Request JSON 示例：

```json
{
  "title": "事件状态变量位置",
  "content_markdown": "状态变量放在回调外层，事件回调里只做更新。",
  "is_user_edited": true
}
```

Response JSON 示例：

```json
{
  "note": {
    "id": "note_001",
    "title": "事件状态变量位置",
    "content_markdown": "状态变量放在回调外层，事件回调里只做更新。",
    "agent_draft_content": "可以加入一个测试失败例子。",
    "is_user_edited": true,
    "updated_at": "2026-05-11T09:40:00Z"
  }
}
```

HTTP 状态码：

- `200`：更新成功
- `400`：字段不合法
- `404`：笔记不存在

错误码：`NOTE_NOT_FOUND`、`VALIDATION_ERROR`

幂等/重试说明：同一请求体可安全重试；后续可扩展 `If-Match` 乐观锁。

相关数据表/状态机节点：`Note`；无 Agent 必经节点。

#### `POST /api/notes/{note_id}/agent-draft`

用途：根据当前笔记生成结构化辅助草稿，写回 `Note.agent_draft_content`。它属于 Note 辅助补全能力，不创建独立复盘草稿流程，也不替用户自动生成完整笔记。

Request JSON 示例：

```json
{
  "user_id": "user_001",
  "style": "concise",
  "focus": "mistake_summary"
}
```

Response JSON 示例：

```json
{
  "note_id": "note_001",
  "agent_draft_content": "易错点：如果把 count 放在事件回调内部，每次点击都会重新初始化，导致状态无法累加。",
  "updated_at": "2026-05-11T09:45:00Z"
}
```

HTTP 状态码：

- `200`：生成成功
- `404`：笔记不存在
- `503`：模型 API 未配置、不可连接、输出为空或输出不安全

错误码：`NOTE_NOT_FOUND`、`MODEL_UNAVAILABLE`

模型说明：笔记辅助补全不提供确定性草稿兜底。模型不可用、输出为空或输出包含 `CodeDraft` / 完整笔记重写等禁止语义时，JSON 模式返回 `MODEL_UNAVAILABLE`；SSE 模式发送 `error.code=MODEL_UNAVAILABLE`，不写入 `Note.agent_draft_content`。

幂等/重试说明：幂等键为 `note_id + content_hash + style + focus`；SSE 模式可流式返回 `agent_message`。

相关数据表/状态机节点：`Note`；只进入笔记辅助补全链路，不进入独立复盘草稿持久化。

### 7. 后置能力：代码复盘草稿（非第一版基线）

`CodeDraft` 与 `/api/code-drafts/*` 不属于 Draft V1.1 的主流程。第一版基线已移除独立复盘草稿流程、`publishDrawer` 用户路径、`CodeDraftPage` 一级页面和面试讲述草稿；第一版不实现下列接口，也不将其纳入前端契约测试、SSE 白名单或 dashboard 入口。

以下契约仅作为后续版本的保留草案，若重新启用，必须先补产品流程、状态机和 schema migration，再进入实现。

#### `POST /api/code-drafts/generate`

用途：后续版本中，基于 `Attempt`、测试结果和笔记生成代码复盘、题解或 AI 协作提示草稿。

Request JSON 示例：

```json
{
  "note_id": "note_001",
  "attempt_id": "att_submit_001",
  "draft_type": "code_review",
  "requirements": {
    "include_failed_tests": true,
    "include_ai_collaboration_warning": true
  }
}
```

Response JSON 示例：

```json
{
  "drafts": [
    {
      "id": "draft_001",
      "note_id": "note_001",
      "attempt_id": "att_submit_001",
      "draft_type": "code_review",
      "title": "按钮计数练习复盘",
      "content": "本次练习的关键是把状态变量保存在事件回调外层，并用测试验证多次点击行为。",
      "status": "draft"
    }
  ]
}
```

HTTP 状态码：

- `201`：草稿创建成功
- `400`：草稿类型非法
- `404`：笔记或 Attempt 不存在
- `502`：Agent 输出无效

错误码：`NOTE_NOT_FOUND`、`ATTEMPT_NOT_FOUND`、`VALIDATION_ERROR`、`EVALUATION_INVALID_JSON`

幂等/重试说明：后置草案暂按 `draft_type + attempt_id + note_id` 设计；不进入第一版基线幂等总则。

相关数据表/状态机节点：`CodeDraft`、`Note`、`Attempt`、`LearningSession`；`load_retrospective_sources`、`choose_draft_type`、`generate_code_draft`、`validate_code_draft`、`persist_code_draft`。

#### `GET /api/code-drafts`

用途：后续版本中，获取某条笔记的所有代码复盘草稿版本。

Request JSON 示例：

```json
{
  "query": {
    "note_id": "note_001",
    "draft_type": "code_review",
    "status": "draft",
    "limit": 20,
    "cursor": null,
    "sort": "-created_at"
  }
}
```

Response JSON 示例：

```json
{
  "items": [
    {
      "id": "draft_001",
      "note_id": "note_001",
      "attempt_id": "att_submit_001",
      "draft_type": "code_review",
      "title": "按钮计数练习复盘",
      "content": "本次练习的关键是把状态变量保存在事件回调外层。",
      "status": "draft"
    }
  ],
  "page_info": {
    "limit": 20,
    "next_cursor": null,
    "has_more": false
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `400`：过滤参数非法
- `404`：笔记不存在

错误码：`NOTE_NOT_FOUND`、`VALIDATION_ERROR`

幂等/重试说明：只读接口，可安全重试。

相关数据表/状态机节点：`CodeDraft`、`Note`；无 Agent 必经节点。

### 8. Dashboard 与 Review Metrics

#### `GET /api/dashboard`

用途：获取桌面端顶部状态栏、总览面板、恢复入口和今日任务。

规则补充：

- 普通打开应用时，默认仍返回当前学习入口或恢复入口，并只提示今日复习数量。
- 只有当“最近一次学习活动距当前超过 72 小时”且“至少存在一条 `forget_risk=high` 的到期复习”同时满足时，`next_entry_point` 才会切到 `review`。

Request JSON 示例：

```json
{
  "query": {
    "user_id": "user_001"
  }
}
```

Response JSON 示例：

```json
{
  "active_goal": "两周内掌握 JavaScript DOM 事件，并能验证 AI 生成代码。",
  "current_stage": "DOM 事件",
  "current_language": "javascript",
  "current_course": {
    "id": "course_js_dom",
    "title": "JavaScript DOM 基础"
  },
  "today_learning_tasks": [
    {
      "type": "learning_session",
      "plan_id": "plan_001",
      "knowledge_point_id": "kp_dom_input_sync",
      "title": "输入框同步状态"
    }
  ],
  "today_review_count": 2,
  "overall_progress": 0.18,
  "resume_available": true,
  "next_entry_point": {
    "type": "resume",
    "plan_id": "plan_001",
    "next_action": "advance_next"
  }
}
```

HTTP 状态码：

- `200`：查询成功
- `404`：用户不存在

错误码：`USER_NOT_FOUND`

幂等/重试说明：只读接口，可安全重试；建议前端进入首页和完成 Attempt 后重新拉取。

相关数据表/状态机节点：`User`、`LearningPlan`、`PlanModule`、`KnowledgePoint`、`ReviewState`、`LearningSession`；`load_resume_context`。

#### `GET /api/knowledge-points/{id}/review-metrics`

用途：获取知识点复习指标、FSRS 曲线和历史 Attempt 表现。

Request JSON 示例：

```json
{
  "path_params": {
    "id": "kp_dom_event_state"
  },
  "query": {
    "user_id": "user_001",
    "from": "2026-05-01T00:00:00Z",
    "to": "2026-05-11T23:59:59Z"
  }
}
```

Response JSON 示例：

```json
{
  "KnowledgePoint": {
    "id": "kp_dom_event_state",
    "title": "事件监听与状态变量",
    "mastery_score": 0.72,
    "weak_points_json": ["state_scope_error"]
  },
  "ReviewState": {
    "knowledge_point_id": "kp_dom_event_state",
    "card_state": "review",
    "stability": 5.8,
    "difficulty": 4.7,
    "due_at": "2026-05-16T09:00:00Z",
    "last_review_at": "2026-05-11T09:20:00Z",
    "review_count": 3,
    "lapse_count": 0,
    "last_attempt_id": "att_review_submit_001",
    "last_fsrs_rating": "Easy"
  },
  "metrics": {
    "attempt_count": 4,
    "average_score": 6.5,
    "latest_result": "easy",
    "latest_fsrs_rating": "Easy",
    "forget_risk": "low"
  },
  "series": [
    {
      "attempt_id": "att_submit_001",
      "created_at": "2026-05-10T09:00:00Z",
      "result": "passed",
      "score": 7,
      "fsrs_rating": "Good",
      "due_at": "2026-05-11T09:00:00Z"
    }
  ]
}
```

HTTP 状态码：

- `200`：查询成功
- `400`：时间范围不合法
- `404`：用户或知识点不存在

错误码：`USER_NOT_FOUND`、`KNOWLEDGE_POINT_NOT_FOUND`、`VALIDATION_ERROR`

幂等/重试说明：只读接口，可安全重试；完成复习后前端必须重新拉取。

相关数据表/状态机节点：`KnowledgePoint`、`ReviewState`、`Attempt`、`SessionKnowledgePoint`；`update_learning_memory`、`update_review_state` 的结果展示。

## Mock 数据规则

### ID 与时间

- mock ID 必须稳定，使用 `mock_` 前缀或本文示例 ID，不允许每次启动随机变化。
- mock 时间以固定基准 `2026-05-11T08:00:00Z` 派生，避免前端快照测试漂移。
- `due_at` 可通过场景参数派生，但同一场景内必须稳定。

### 场景参数

前端可通过 `X-Mock-Scenario` 指定场景：

| 场景 | 说明 |
|---|---|
| `happy_path` | 运行成功、提交 `passed`、`fsrs_rating=Good` |
| `easy_no_hint` | 零提示零错误，提交 `easy`、`fsrs_rating=Easy` |
| `partial_with_hint` | 测试通过但提示依赖高，`next_action=review_variant` |
| `runtime_error` | runner 返回 `runtime_error`，可进入 `explain_error` |
| `unsupported_runtime` | `compiled_sandbox_later` 返回 `runtime_status=unsupported` |
| `due_review` | 今日有待复习项 |
| `empty_dashboard` | 无活动计划、无复习 |

### Mock 必须覆盖的字段

- `LearningPlan.status`
- `KnowledgePoint.status`
- `Exercise.exercise_type`
- `RuntimeProfile.runtime_tier`
- `Attempt.runtime_status`
- `code_completion_result.result`
- `fsrs_rating`
- `due_at`
- `next_action`

### Mock 禁止行为

- 不得返回不在枚举表中的值。
- 不得把 `RuntimeProfile.runtime_tier=compiled_sandbox_later` mock 成真实运行成功。
- 不得在同一幂等键下返回不同 `attempt_id`。
- 不得省略错误结构中的 `error.code`、`error.message`、`error.request_id`。

## 前端契约测试边界

前端契约测试必须覆盖：

- 每个核心接口的成功响应 JSON shape。
- 统一错误结构和关键错误码分支。
- 分页字段 `items`、`page_info.limit`、`page_info.next_cursor`、`page_info.has_more`。
- 枚举字段非法时前端显示兜底文案，不崩溃。
- SSE 事件顺序：`agent_message`、`tool_call`、`tool_status`、`runner_result`、`evaluation_result`、`done`、`error`。
- `run` 重试不重复创建 Attempt。
- `submit` 重试不重复推进 `ReviewState.due_at`。
- `compiled_sandbox_later` 展示能力边界，不展示“可实时运行”。
- `code_completion_result.next_action` 能驱动按钮状态和下一步入口。
- `ReviewState.due_at` 到期和未到期两种 dashboard 状态。
- `POST /api/notes/{note_id}/agent-draft` 只回写 Note 辅助内容，不触发独立复盘草稿对象。

前端契约测试不负责：

- LLM 讲解质量主观评估。
- FSRS 算法内部数值推导。
- runner service 沙箱安全性。
- LangGraph 节点内部 prompt 质量。
- 数据库事务隔离和索引性能。

## 与数据模型和状态机的同步要求

字段变更必须同步检查：

- `plan_draft` 结构变化必须同步 `POST /api/plans/generate`、`POST /api/plans`、`generate_plan_draft`、`validate_plan_draft`。
- `source_attribution` 语义变化必须同步 onboarding route card、动态路线生成、fallback 文案和验收计划。
- `LearningPlan`、`KnowledgePoint`、`Exercise`、`Attempt`、`ReviewState`、`RuntimeProfile` 字段变化必须同步响应示例。
- `code_completion_result` 变化必须同步 `submit`、`review exercise-result`、SSE `evaluation_result`。
- `fsrs_rating`、`due_at` 或 `next_action` 变化必须同步 dashboard、review metrics 和前端契约测试。
- `Note.agent_draft_content` 变化必须继续约束为 Note 辅助补全，不得重新隐式引入独立复盘草稿主流程。
- 状态机节点名变化必须同步每个接口的“相关数据表/状态机节点”。

## 第一版不做

- 账号注册、登录、权限组和外部分发 API。
- 代码仓库级导入、视频解析和大型多文件项目运行。
- 未同步扩展 `Language`、数据库约束、课程 catalog 和 runtime boundary 的任意语言公开支持。
- Java / C++ 真实编译沙箱。
- WebSocket 事件通道。V1 只使用 SSE。
- OpenAPI 自动生成文件。本文先作为人工契约，后续再转 OpenAPI。
- 独立 `CodeDraft` / `/api/code-drafts/*` 主流程、`publishDrawer` 用户路径、`CodeDraftPage` 一级页面和面试讲述草稿。
