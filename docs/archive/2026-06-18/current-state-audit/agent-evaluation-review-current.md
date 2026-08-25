# Agent、评估与复习当前边界

> **历史快照，非当前 source of truth。** 本文生成于 2026-06-18，描述已经被 Tutor Harness 替代的旧运行时。当前事实请从 [`../../../README.md`](../../../README.md) 路由。

生成日期：2026-06-18

## Agent 层当前结构

| 领域 | 主要文件 | 当前职责 |
|---|---|---|
| Onboarding Agent | `app/agents/onboarding/*` | 槽位提取、路线生成、route card draft、authoritative docs coverage |
| Learning Agent | `app/agents/learning/*` | 学习对话、概念解释、练习教练、public output 约束 |
| Review Agent | `app/agents/review/*` | 复习教练、warmup judgement、review conversation |
| Notes Agent | `app/agents/notes/note_assist_agent.py` | 笔记草稿辅助 |
| Runtime | `app/agents/runtime/*` | SDK runtime、guardrails、structured judgement、domain context |
| Tools | `app/agents/tooling/*` | agent tool definitions、web tool adapters |
| Graphs | `app/agents/graphs/*` | LangGraph orchestration contracts and optional routing |

LLM 相关能力依赖 `aearn/.env`，不要在文档或 demo 中假设真实模型已配置。`.env.example` 只保留空 key 和本地默认值。

## LangGraph 当前状态

| 图 | 文件 | 当前用途 | 状态 |
|---|---|---|---|
| Onboarding orchestration | `graphs/onboarding_graph.py` | clarify / generate_route / revise_route / confirm_plan intent | Partially implemented |
| Learning state graph | `graphs/learning_graph.py` | context、concept intro/check/repair、practice offer、select exercise | Partially implemented |
| Learning orchestration graph | `graphs/learning_graph.py` | single-step message routing，替代部分 imperative transition | Partially implemented |
| Review orchestration | `graphs/review_graph.py` | not-due rejection、start/reuse、submit、warmup、coach feedback | Partially implemented |
| Runtime contract | `graphs/graph_runtime_contracts.py` | redaction、checkpoint thread state、intent validation、fallback | Implemented |

准确边界：

| 项 | 说明 |
|---|---|
| 默认开关 | `LANGGRAPH_ENABLED=false` |
| Graph owns | routing decision、safe intent、observability context、fallback signal |
| Graph does not own | DB writes、ReviewState/ReviewLog、public response rendering、FSRS、hidden tests、raw provider payload |
| Fallback | graph error 或 boundary validation 失败时回退服务层路径 |
| 测试 | `test_learning_graph.py`、`test_onboarding_graph.py`、`test_review_graph.py`、`test_graph_runtime_contracts.py`、`test_graph_event_stream.py` |

## SSE 事件边界

前端 `hooks/useSSE.ts` 支持的事件：

| Event | 用途 |
|---|---|
| `agent_message` | assistant bubble 增量和完整内容 |
| `tool_status` | backend tool/runner/graph 状态 |
| `tool_call` | generative UI cards 的 start/delta/done |
| `runner_result` | run/submit 的运行反馈 |
| `evaluation_result` | submit 后评分结果 |
| `session_created` | onboarding session 创建 |
| `done` | terminal success event |
| `error` | terminal recoverable/non-recoverable error |

当前 frontend 通过 fetch readable stream 处理 POST SSE。这样可以携带 JSON body、`X-Request-Id` 和 `client_message_id`，避免 `EventSource` 的 GET-only 限制。

## 语言与 runner 能力矩阵

| Language | Public route | Execution | Runner | 面试表述 |
|---|---:|---|---|---|
| JavaScript | Yes | `browser_preview` | browser | DOM/browser preview + visible/hidden style assertions |
| HTML/CSS | Yes | `browser_preview` | browser | combined `html_css` course boundary |
| Python | Yes | `python_stdout_test` | python | subprocess-restricted stdout/tests，不是容器级沙箱 |
| TypeScript | Yes | `node_typescript_test` | node | single-file function exercises，依赖本机 Node/TypeScript |
| SQL | Yes | `sql_query_test` | sql | per-run SQLite teaching dialect，不访问 Aearn PostgreSQL |
| Java | Yes | `managed_compiled_test` | compiled | local teaching-grade single exercise，不支持 Maven/Gradle |
| Go | Yes | `managed_compiled_test` | compiled | local teaching-grade single package |
| C# | Yes | `managed_compiled_test` | compiled | local teaching-grade single file / SDK |
| C++ | No | `compiled_later` | compiled planned | 非公开路线，不能宣称当前可编译运行 |
| Rust | No | `compiled_later` | compiled planned | 非公开路线，不能宣称当前可编译运行 |

关键文件：

| 文件 | 用途 |
|---|---|
| `app/services/runners/language_capabilities.py` | public language map 和 disclosure |
| `app/services/runners/runner_registry.py` | runtime profile -> runner selection |
| `app/services/runners/runtime_contracts.py` | public runtime result contract |
| `app/services/runners/*_runner.py` | concrete runner implementations |

## 评估与 Attempt

学习提交链路：

| Step | Owner | 结果 |
|---|---|---|
| Run | `run_learning_session_exercise()` | 写 `Attempt(run)`，包含 runtime status、stdout/stderr、test results |
| Submit | `submit_learning_session_exercise()` | 基于 run attempt 和当前 code hash 评分，写 `Attempt(submit)` |
| Evaluation | `build_code_completion_result()` | 生成 `score_breakdown`、hard gates、`fsrs_rating`、`next_action` |
| Schedule | `apply_attempt_review_update()` | 更新 KnowledgePoint / ReviewState，写 ReviewLog |

评分维度在 `app/services/exercises/evaluation.py` 中实现，核心思想：

| 维度 | 说明 |
|---|---|
| `completion_correctness` | 补全是否正确解决目标 |
| `runtime_and_tests` | runtime/test 通过率 |
| `error_diagnosis` | 错因理解和修复方向 |
| `explanation_check` | 学习者解释是否过关 |
| hard gates | runtime/test/core blank/explanation 等门槛 |
| FSRS mapping | `Again`、`Hard`、`Good`、`Easy` |

Hidden test 边界：public response 会隐藏 hidden expected values 和 solution references，只给安全提示，例如 hidden test passed/failed 风格信息。

## Review batch 当前实现

| 组件 | 文件 | 职责 |
|---|---|---|
| Due queue | `review_repository.get_today_reviews()` | 读取到期 review states |
| Session start | `review_repository.start_review_session()` | 校验 due、创建/复用 review session、选择 seed |
| Seed bank | `review_seed_bank.py`、`aearn_worker/review_seed_bank_core.py` | 生成/校验/持久化 review candidate pool |
| Warmup | `record_review_warmup_result()` | 记录 session-level warmup，不写 Attempt/ReviewState |
| Review submit | `submit_review_exercise_result()` | 写 review submit Attempt，推进 batch |
| Final schedule | `review_scheduler.apply_review_batch_update()` | batch final rating 后写 ReviewState 和 ReviewLog |
| Worker | `aearn_worker.worker_app.generate_seed_bank` | 异步/后台 seed bank 生成入口 |

重要规则：

| 规则 | 当前状态 |
|---|---|
| Warmup 不写长期调度 | Implemented |
| 中间 review submit 不直接更新 ReviewState | Implemented |
| final batch 聚合后才写 ReviewState/ReviewLog | Implemented |
| no valid baseline candidate 时返回 recoverable error | Implemented |
| `review_ai_patch` 是 first-class exercise type | Implemented |

## `review_ai_patch`

`review_ai_patch` 用于训练“审查 AI 生成补丁”的能力。它不是普通代码填空，提交时要求结构化回答。

| 字段/维度 | 当前实现 |
|---|---|
| verdict | pass / fail / uncertain |
| evidence | 证据是否具体和 grounded |
| knowledge point risk | 是否对齐当前知识点风险 |
| next action | accept / reject / request_change / run_more_tests |
| score breakdown | `verdict_correctness`、`evidence_grounding`、`knowledge_point_alignment`、`actionability` |

实现入口：`build_review_ai_patch_completion_result()` 和 `review_repository.submit_review_exercise_result()`。

## 当前限制

| 限制 | 影响 |
|---|---|
| `LANGGRAPH_ENABLED` 默认关闭 | Graph 是可选增强，不是默认所有请求路径 |
| 真实模型依赖配置 | 无 LLM provider 时，hint/explain/agent draft/dynamic generation 等会返回 model unavailable 或走 deterministic fallback |
| Java/Go/C# 本机工具链依赖 | 缺 toolchain 时应显示 missing/unsupported，不算产品能力失败 |
| C++/Rust 非公开 | 只能说 planned/static boundary |
| Shared package placeholder | 跨前后端契约仍主要靠 docs、Pydantic models、frontend type guards |
