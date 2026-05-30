# 代码补全验证 Prompt 与评分规则实施规格

日期：2026-05-11  
状态：Draft V1.1  
适用范围：Aearn 的学习会话、复习变体、Attempt 评分与 FSRS Rating 映射

## 目标

本规格定义 Aearn 的核心判定闭环：

```text
读代码 -> 补全关键代码 -> 运行/实时预览 -> 测试/错误反馈 -> Agent 提示/错因解释 -> 评分 -> FSRS Rating
```

它用于替代旧的主观问答式理解检验。第一版必须以运行结果和测试结果为主，代码解释检查为辅，避免把产品重新做成纯聊天学习工具。

## 设计原则

1. 先看确定性证据，再看 Agent 判断。
2. 运行/测试失败时，不允许直接判定为 `passed`。
3. 代码解释检查只补足“是否理解关键代码”，不能替代测试结果。
4. 提示使用、错误次数、重试次数必须影响评分。
5. 评分结果必须能稳定映射到 `Again` / `Hard` / `Good` / `Easy`。
6. 不同语言按运行能力分层，不承诺第一版支持任意语言实时运行。

## 术语

- `Exercise`：绑定知识点的代码练习，包含题面、代码模板、空缺、测试用例和运行能力要求。
- `CodeBlank`：代码补全题中的空缺定义。
- `TestCase`：可见测试、隐藏测试或预览断言。
- `Attempt`：用户一次运行或提交练习的记录。
- `code_completion_result`：一次提交后的统一评分结果。
- `explanation_check`：用户对关键代码、边界条件或 AI 辅助改动的简短解释检查。
- `hint_usage_count`：本次 Attempt 使用提示的次数。
- `error_count`：本次 Attempt 产生运行错误、测试失败或编译错误的次数。
- `runtime_tier`：当前语言/练习可用的运行能力分层，如浏览器预览、stdout、单元测试或后置沙箱。

## 运行能力分层

| 层级 | 语言/技术 | 第一版能力 | 是否 MVP 必需 |
|---|---|---|---|
| `browser_preview` | JS / HTML / CSS | 浏览器内实时预览、DOM 断言、console 输出 | 是 |
| `python_stdout_test` | Python | stdout、函数测试、简单单元测试 | 是，可先 mock 判定 |
| `compiled_sandbox_later` | Java / C++ | 编译、运行、资源限制、沙箱隔离 | 否，保留扩展位 |

如果 `runtime_tier` 为 `compiled_sandbox_later`，第一版只能展示课程和静态练习，不得承诺完整实时运行。

## 验证流程

### 学习会话

1. 系统加载 `Exercise`、`CodeBlank`、`TestCase` 和 `RuntimeProfile`。
2. 用户补全代码并点击运行，生成 `Attempt(run)`。
3. 系统返回预览、stdout、stderr、测试结果或错误信息。
4. 用户提交最终答案，生成或更新 `Attempt(submit)`。
5. Agent 根据运行/测试结果、提示使用、错误次数和解释检查生成 `code_completion_result`。
6. 系统写回 `KnowledgePoint`、`SessionKnowledgePoint`、`Attempt` 和 `ReviewState`。

### 复习会话

1. 系统按 `due_at` 取出待复习知识点。
2. 系统生成或选择同构变体练习。
3. 用户完成变体代码补全、改错或解释检查。
4. 系统生成 `Attempt(review_submit)`。
5. `code_completion_result` 映射到 FSRS Rating，并更新 `ReviewState`。

## 输入数据

### `evaluation_input`

```json
{
  "attempt_id": "att_001",
  "exercise_id": "ex_dom_click_count",
  "knowledge_point_id": "kp_dom_event_state",
  "runtime_profile": {
    "runtime_tier": "browser_preview",
    "language": "javascript",
    "supports_realtime_preview": true,
    "supports_tests": true
  },
  "submitted_code": "let count = 0;\nbutton.addEventListener('click', () => { count += 1; output.textContent = count; });",
  "filled_blanks": {
    "blank_1": "addEventListener",
    "blank_2": "count += 1"
  },
  "runtime_status": "success",
  "test_results": [
    {
      "case_id": "visible_initial",
      "case_type": "visible",
      "passed": true,
      "weight": 1
    },
    {
      "case_id": "hidden_three_clicks",
      "case_type": "hidden",
      "passed": true,
      "weight": 2
    }
  ],
  "hint_usage_count": 1,
  "error_count": 0,
  "explanation_text": "count 放在事件函数外层，多次点击会共享同一个状态。"
}
```

## 输出数据

### `code_completion_result`

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

## 评分维度

每次提交默认 4 个维度，总分 8 分。

| 维度 | 字段 | 分值 | 是否硬门槛 | 说明 |
|---|---|---:|---|---|
| 关键代码补全正确性 | `completion_correctness` | 0-2 | 是 | 是否补对关键空缺，是否符合目标概念 |
| 运行/测试结果 | `runtime_and_tests` | 0-2 | 是 | 是否能运行，测试通过率是否达标 |
| 错因定位能力 | `error_diagnosis` | 0-2 | 否 | 用户或 Agent 是否能定位错误原因 |
| 代码解释检查 | `explanation_check` | 0-2 | 是 | 是否能解释关键代码、边界条件或 AI 辅助改动 |

## 0/1/2 分标准

### `completion_correctness`

| 分数 | 标准 |
|---:|---|
| 0 | 核心空缺错误，或补全代码与目标知识点无关 |
| 1 | 关键思路接近，但存在作用域、返回值、事件绑定、边界条件等问题 |
| 2 | 核心空缺正确，代码表达符合当前语言和练习意图 |

### `runtime_and_tests`

| 分数 | 标准 |
|---:|---|
| 0 | 无法运行、编译失败、预览不可用，或测试通过率低于 50% |
| 1 | 能运行但测试通过率未达门槛，或只通过可见测试 |
| 2 | 能运行，测试通过率达到门槛，关键隐藏测试或预览断言通过 |

### `error_diagnosis`

| 分数 | 标准 |
|---:|---|
| 0 | 无法说明错误原因，或将错误归因为无关概念 |
| 1 | 能描述表面错误，但不能定位到代码位置或概念边界 |
| 2 | 能定位错误代码、错误类型和修正方向 |

### `explanation_check`

| 分数 | 标准 |
|---:|---|
| 0 | 无法解释关键代码，或解释与代码行为矛盾 |
| 1 | 能解释主路径，但边界条件、状态生命周期或 AI 修改意图不稳定 |
| 2 | 能解释主路径、边界条件和为什么这样补全 |

## 硬门槛

### `runtime_gate`

通过条件：

- `runtime_status = success`
- 或当前 `runtime_tier` 不支持真实运行，但 mock 判定明确为可通过

失败后果：

- 不允许判定为 `passed` 或 `easy`
- 默认最高只能为 `partial`

### `test_gate`

通过条件：

- `test_pass_rate >= 0.8`
- 且关键测试用例通过

失败后果：

- 关键测试失败：结果为 `failed`
- 非关键测试失败：最高为 `partial`

### `core_blank_gate`

通过条件：

- 所有标记为核心的 `CodeBlank` 均满足 `acceptable_patterns_json`
- 或 AST / 断言结果证明语义等价

失败后果：

- 核心空缺错误时结果为 `failed`

### `explanation_gate`

通过条件：

- 必要解释检查达到 1 分以上
- 如果练习标记 `requires_explanation=true`，则必须达到 2 分才可判定 `easy`

失败后果：

- 测试全过但解释失败：结果为 `partial`
- 最多追问 2 轮，超过后不继续拉长当次验证

## 判定结果

| `result` | 条件 | 后续动作 |
|---|---|---|
| `easy` | 总分 ≥ 7，全部硬门槛通过，测试稳定，未使用关键提示或仅使用轻提示 | 进入复习，降低近期复习压力 |
| `passed` | 总分 ≥ 6，全部硬门槛通过，测试通过率达标 | 进入复习队列 |
| `partial` | 总分 4-5，或测试通过但提示依赖高 / 解释不稳定 | 记录薄弱点，短补讲，加入重点复习 |
| `failed` | 总分 ≤ 3，核心空缺错误，关键测试失败，或无法运行 | 降低粒度重讲，不推进新知识 |

## FSRS Rating 映射

| `result` | 附加条件 | FSRS Rating |
|---|---|---|
| `failed` | 任意失败 | `Again` |
| `partial` | 任意部分通过 | `Hard` |
| `passed` | `hint_usage_count <= 2` 且 `error_count <= 2` | `Good` |
| `passed` | 提示或错误次数较高 | `Hard` |
| `easy` | `hint_usage_count = 0` 且 `error_count = 0` | `Easy` |
| `easy` | 使用过轻提示 | `Good` |

## 提示策略

提示分三层，必须记录到 `hint_usage_count`。

| 层级 | `hint_level` | 内容边界 | 对评分影响 |
|---|---|---|---|
| 轻提示 | `nudge` | 指向概念或代码区域，不给代码形状 | 轻微影响 |
| 概念提示 | `concept` | 解释相关概念和常见错误 | 中等影响 |
| 代码形状提示 | `code_shape` | 给出局部结构，但不直接给完整答案 | 明显影响 |

如果用户明确请求答案，可以给完整答案，但本次 Attempt 默认不能高于 `partial`，除非用户随后完成新的变体练习。

## 错因分类

第一版内置错因标签：

- `syntax_error`：语法错误
- `selector_error`：选择器或节点定位错误
- `event_binding_error`：事件绑定错误
- `state_scope_error`：状态变量作用域错误
- `return_value_error`：返回值缺失或错误
- `edge_case_error`：边界条件错误
- `type_error`：类型理解错误
- `async_order_error`：异步执行顺序错误
- `test_misread`：读错题目或测试意图
- `ai_over_trust`：直接接受 AI 生成代码但未验证

每个 `failed` 或 `partial` Attempt 至少要记录一个错因标签。

## 代码解释检查

触发条件：

- 测试全过但 `hint_usage_count > 0`
- 用户代码与参考答案结构差异较大
- 练习涉及状态、闭包、异步、边界条件或 AI 生成代码修改
- 复习变体需要确认迁移理解

检查问题只问 1-2 个，不做长问答。示例：

- “为什么 `count` 不能写在 click 回调内部？”
- “这个函数遇到空数组时会返回什么？”
- “AI 改动的这行代码解决了哪个失败测试？”

## LLM 输出要求

Agent 评分必须输出可解析 JSON，禁止只输出自然语言。

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
  "weak_points": [],
  "error_cause": null,
  "feedback": "简短、具体、可执行的反馈",
  "next_action": "schedule_review",
  "fsrs_rating": "Good"
}
```

### 枚举限制

- `result`：`failed` / `partial` / `passed` / `easy`
- `next_action`：`retry_same` / `show_hint` / `explain_error` / `review_variant` / `schedule_review` / `advance_next`
- `fsrs_rating`：`Again` / `Hard` / `Good` / `Easy`

### `review_ai_patch` 专用评分

`review_ai_patch` 是复习页核心题型，不要求用户改写代码，而要求用户审核 AI diff。提交字段必须包含：

- `verdict`：`pass` / `fail` / `uncertain`
- `evidence`：来自需求、diff、可见测试或代码行为的证据
- `knowledge_point_risk`：当前知识点相关风险
- `next_action`：`accept` / `reject` / `request_change` / `run_more_tests`

该题型仍写入 `Attempt(attempt_type=review_submit).code_completion_result`，但 `score_breakdown` 使用四个专用维度：

```json
{
  "verdict_correctness": 2,
  "evidence_grounding": 1,
  "knowledge_point_alignment": 2,
  "actionability": 1
}
```

只说 `tests passed` 属于弱证据；如果 `evidence_grounding < 2`，即使 verdict 正确也必须映射为 `result=partial`、`fsrs_rating=Hard`、`next_action=review_variant`，不得给 `Easy`。

## JSON Schema

后端必须用 schema 校验 Agent 输出，并在写入 `attempts.code_completion_result` 前补齐服务端可验证字段。下列 schema 适用于代码补全/修复/解释类练习；`review_ai_patch` 使用上方专用维度，但仍遵守 `result`、`score`、`hard_gates`、`weak_points`、`feedback`、`next_action`、`fsrs_rating` 的公共约束。

```json
{
  "type": "object",
  "required": [
    "result",
    "score",
    "score_breakdown",
    "hard_gates",
    "test_pass_rate",
    "hint_usage_count",
    "error_count",
    "weak_points",
    "feedback",
    "next_action",
    "fsrs_rating"
  ],
  "additionalProperties": false,
  "properties": {
    "result": {
      "type": "string",
      "enum": ["failed", "partial", "passed", "easy"]
    },
    "score": {
      "type": "integer",
      "minimum": 0,
      "maximum": 8
    },
    "score_breakdown": {
      "type": "object",
      "required": [
        "completion_correctness",
        "runtime_and_tests",
        "error_diagnosis",
        "explanation_check"
      ],
      "additionalProperties": false,
      "properties": {
        "completion_correctness": { "type": "integer", "minimum": 0, "maximum": 2 },
        "runtime_and_tests": { "type": "integer", "minimum": 0, "maximum": 2 },
        "error_diagnosis": { "type": "integer", "minimum": 0, "maximum": 2 },
        "explanation_check": { "type": "integer", "minimum": 0, "maximum": 2 }
      }
    },
    "hard_gates": {
      "type": "object",
      "required": ["runtime_gate", "test_gate", "core_blank_gate", "explanation_gate"],
      "additionalProperties": false,
      "properties": {
        "runtime_gate": { "type": "boolean" },
        "test_gate": { "type": "boolean" },
        "core_blank_gate": { "type": "boolean" },
        "explanation_gate": { "type": "boolean" }
      }
    },
    "test_pass_rate": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "hint_usage_count": {
      "type": "integer",
      "minimum": 0
    },
    "error_count": {
      "type": "integer",
      "minimum": 0
    },
    "weak_points": {
      "type": "array",
      "items": { "type": "string" }
    },
    "error_cause": {
      "type": ["string", "null"]
    },
    "feedback": {
      "type": "string",
      "minLength": 1
    },
    "next_action": {
      "type": "string",
      "enum": ["retry_same", "show_hint", "explain_error", "review_variant", "schedule_review", "advance_next"]
    },
    "fsrs_rating": {
      "type": "string",
      "enum": ["Again", "Hard", "Good", "Easy"]
    }
  }
}
```

服务端补齐字段：

- `evaluation_status`：`evaluated` / `needs_manual_review` / `rule_fallback`
- `evaluated_at`：评分写入时间
- `evaluator_version`：例如 `code_completion_eval_v1`
- `evidence_hash`：由 `attempt_id + submitted_code + test_results + explanation_text` 生成，防止评分与证据错配

## 评分 Prompt 模板

`evaluate_attempt_prompt` 只能用于结构化评分，不承担重新运行代码、泄露隐藏测试或补全答案职责。

```text
你是 Aearn 的评分器。请只根据给定 evidence 评分，不要推测不存在的运行结果。

输入：
- exercise: {exercise}
- runtime_profile: {runtime_profile}
- code_blanks: {code_blanks}
- submitted_code: {submitted_code}
- runtime_status: {runtime_status}
- test_results: {test_results}
- hint_usage_count: {hint_usage_count}
- error_count: {error_count}
- explanation_text: {explanation_text}
- explanation_check_result: {explanation_check_result}

评分要求：
1. 按 completion_correctness、runtime_and_tests、error_diagnosis、explanation_check 四项各给 0/1/2 分。
2. 先判断 runtime_gate、test_gate、core_blank_gate、explanation_gate。
3. 任一硬门槛失败时，result 不得为 passed 或 easy。
4. 不得输出隐藏测试源码、参考答案或完整修复代码。
5. feedback 必须引用真实证据，例如失败测试名称、stderr 摘要、错因标签或解释检查结果。
6. 只输出符合 JSON Schema 的 JSON，不要输出 Markdown。
```

## 规则引擎兜底

当 LLM 评分输出连续校验失败时，后端必须用确定性规则生成保守结果，避免学习流程卡死。

### 输入

- `runtime_status`
- `test_pass_rate`
- 关键 `TestCase.passed`
- 核心 `CodeBlank` 是否通过
- `hint_usage_count`
- `error_count`
- `explanation_check_result`
- `requires_explanation`

### 兜底规则

| 条件 | `result` | `fsrs_rating` | `next_action` |
|---|---|---|---|
| `runtime_status != success` | `failed` | `Again` | `explain_error` |
| 核心空缺失败 | `failed` | `Again` | `retry_same` |
| 关键测试失败 | `failed` | `Again` | `explain_error` |
| `test_pass_rate < 0.8` | `partial` | `Hard` | `show_hint` |
| 测试通过但解释检查失败 | `partial` | `Hard` | `review_variant` |
| 测试通过、提示或错误次数过高 | `passed` | `Hard` | `review_variant` |
| 测试通过、低提示低错误 | `passed` | `Good` | `schedule_review` |
| 全部通过、无提示无错误、解释满分 | `easy` | `Easy` | `schedule_review` |
| `review_ai_patch` verdict 错误 | `failed` | `Again` | `review_variant` |
| `review_ai_patch` 证据不足 | `partial` | `Hard` | `review_variant` |
| `review_ai_patch` 四项满分 | `easy` | `Easy` | `schedule_review` |

兜底结果必须写入：

- `attempts.evaluation_status = rule_fallback`
- `attempts.code_completion_result.feedback` 说明“评分由规则引擎兜底生成”
- `review_logs.next_state_json.scheduler_fallback` 不由本规则直接写入，仍由 FSRS 调度层决定

## 输出校验与重试

后端必须做结构校验：

1. JSON 可解析。
2. 枚举值合法。
3. `score` 等于 4 个维度之和。
4. 分项分数均在 0-2。
5. 硬门槛失败时，`result` 不得为 `passed` 或 `easy`。
6. `result` 与 `fsrs_rating` 映射不冲突。

如果校验失败：

1. 第一次：带错误原因要求 LLM 只修 JSON。
2. 第二次：使用规则引擎按测试结果降级生成保守结果。
3. 仍失败：写入 `Attempt`，标记 `evaluation_status=needs_manual_review`。

## API 对齐

相关接口：

- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/run`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/submit`
- `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint`
- `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`
- `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation`
- `POST /api/reviews/{session_id}/exercise-result`

字段命名必须与 `docs/architecture/api-contract.md` 保持一致。

## 数据模型对齐

必须写回或更新：

- `Attempt.submitted_code`
- `Attempt.filled_blanks_json`
- `Attempt.runtime_status`
- `Attempt.test_pass_rate`
- `Attempt.test_results_json`
- `Attempt.stdout`
- `Attempt.stderr`
- `Attempt.error_message`
- `Attempt.error_cause`
- `Attempt.hint_usage_count`
- `Attempt.error_count`
- `Attempt.explanation_text`
- `Attempt.explanation_check_result`
- `Attempt.score`
- `Attempt.score_breakdown_json`
- `Attempt.fsrs_rating`
- `KnowledgePoint.last_exercise_result`
- `KnowledgePoint.last_exercise_score`
- `KnowledgePoint.last_exercise_breakdown_json`
- `ReviewState.last_attempt_id`
- `ReviewState.last_fsrs_rating`

## 示例

### 示例 1：一次通过

- 测试通过率：1.0
- 提示次数：0
- 错误次数：0
- 解释检查：2

结果：

```json
{
  "result": "easy",
  "score": 8,
  "fsrs_rating": "Easy",
  "next_action": "schedule_review"
}
```

### 示例 2：测试通过但依赖提示

- 测试通过率：1.0
- 提示次数：3
- 错误次数：1
- 解释检查：1

结果：

```json
{
  "result": "passed",
  "score": 6,
  "fsrs_rating": "Hard",
  "next_action": "review_variant"
}
```

### 示例 3：关键测试失败

- 测试通过率：0.66
- 关键隐藏测试失败
- 错因：`state_scope_error`

结果：

```json
{
  "result": "failed",
  "score": 3,
  "fsrs_rating": "Again",
  "next_action": "explain_error"
}
```

## 后续同步

修改本规格后必须同步检查：

- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/fsrs-scheduling-spec.md`
- `docs/architecture/langgraph-state-machine.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/qa/acceptance-test-plan.md`
- `docs/product/user-flows.md`
- `docs/plans/learning-agent-implementation-plan.md`

## 完成标准

本规格达到可实施状态需要满足：

- 每个评分维度都有 0/1/2 分标准。
- 每个硬门槛都有通过条件和失败后果。
- `code_completion_result` JSON 可直接被 API 和数据库引用。
- 评分 Prompt、JSON Schema 和规则引擎兜底足够直接落到后端实现。
- `result` 到 FSRS Rating 的映射无歧义。
- LLM 输出有校验和重试策略。
- JS/HTML/CSS、Python、Java/C++ 的运行能力边界清晰。
