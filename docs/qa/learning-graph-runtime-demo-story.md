# Learning Graph Runtime Demo Story

日期：2026-06-01  
状态：Post-MVP graph hardening demo evidence  
范围：`02-learning-graph-runtime-hardening` 的学习页 LangGraph runtime vertical slice，以及 onboarding / review 为什么保持 graph-assisted service flow。

## 结论

学习页现在是完整的 graph runtime 垂直切片：服务层加载安全上下文，注入 memory / RAG，上交给 LangGraph 做阶段和工具意图决策，再由服务层做 boundary validation、执行可允许的 stage/tool intents、写入持久化状态，并把 graph 运行进度映射到现有 SSE vocabulary。

Onboarding 和 review 没有被迁移成“graph 直接拥有持久化”的全量 runtime。它们只消费 graph 的 route decision，并继续由现有 service / repository 拥有 `LearningPlan`、`ReviewState`、`ReviewLog`、`Attempt` 和 idempotency 写入。这是刻意边界，不是缺口。

## Runtime Slice

```text
learning message request
  -> prepare_learning_message()
  -> load LearningConversationContext
  -> build GraphMemorySnapshot + GraphRagContext
  -> invoke_orchestration(..., thread_config)
  -> validate_run_result_for_boundary()
  -> consume scoped STAGE_UPDATE / TOOL_CALL intents
  -> service/repository persist LearningSession + LearningMessage
  -> SSE maps safe graph status to tool_status
  -> normal agent_message / tool_call / done frames continue
```

Layer ownership:

| Layer | Owns | Does not own |
|---|---|---|
| Graph | routing decisions, stage transitions, typed intents, ordered tool selection | database connections, idempotency records, public API/SSE envelopes |
| Service | graph invocation, boundary validation, intent execution, durable write orchestration, fallback | SQL invariants, raw SSE frame serialization |
| Repository | SQL, transactions, persistence invariants | graph routing and public response rendering |
| API | request validation, response mode, error envelopes | graph internals and repository writes |
| SSE | public event names, frame order, bounded payloads | raw graph diagnostics or provider errors |

## Demo Script

Run from `E:\codee\Aearn` in PowerShell.

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_graph_runtime_contracts.py tests/test_graph_event_stream.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_onboarding_m2.py tests/test_reviews_m4.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
```

Expected evidence:

| Evidence | Where to look |
|---|---|
| Graph node and adapter contracts | `tests/test_learning_graph.py`, `tests/test_graph_runtime_contracts.py` |
| Service consumes ordered learning intents | `tests/test_learning_graph.py::TestLearningServiceGraphBoundary` |
| Graph status maps to existing SSE `tool_status` before `agent_message` | `tests/test_graph_event_stream.py`, `tests/test_learning_sessions_m3.py::test_learning_message_sse_emits_graph_tool_status_before_agent_message` |
| Flag-off compatibility and graph failure fallback | `tests/test_learning_sessions_m3.py` graph flag/fallback tests |
| Onboarding graph decision remains service-owned persistence | `tests/test_onboarding_m2.py::test_onboarding_message_langgraph_flag_on_invokes_graph_route_decision` |
| Review graph decision remains review service/repository persistence | `tests/test_reviews_m4.py::test_review_routes_langgraph_flag_on_invokes_start_and_submit_graph` |

## Fallback And Safety Story

- `LANGGRAPH_ENABLED=false` keeps the previous service path and must not compile or invoke the graph.
- Graph compile/invoke failure falls back to the stable service transition and does not expose raw errors.
- Invalid or unscoped graph intents are rejected by `validate_run_result_for_boundary()` before any service side effect is applied.
- Idempotency replay returns the stored Aearn response and must not re-run graph side-effect decisions.
- Public JSON/SSE must not expose `langgraph_runtime`, memory snapshots, RAG internals, raw graph node names, provider payloads, API keys, hidden tests, `solution_reference`, stack traces, or complete submitted code.

## Cross-Page Boundary

Onboarding consumes graph decisions such as `build_plan_draft`, `rebuild_plan_draft`, `confirm_plan`, and `onboarding_clarification`. The graph can decide that a draft is ready or not ready, but `POST /api/plans` and the onboarding route still own `LearningPlan`, modules, knowledge points, review states, latest-card-wins, and idempotency behavior.

Review consumes graph decisions such as `review_session`, `attempt_and_fsrs`, `evaluate_warmup`, and `review_coach`. The graph can reject a not-due start or guide a review action, but scheduler/repository code still owns `ReviewState`, `ReviewLog`, `Attempt(review_submit)`, FSRS updates, and replay protection.

This separation keeps the learning page as the graph runtime proof while preventing graph nodes from becoming a second persistence layer.

## Runtime Capability Boundary

This demo story does not add language runtime support.

- Python execution is available through the runner registry path.
- JavaScript / HTML / CSS remain browser-preview style learning runtimes.
- Java uses the teaching-grade `managed_compiled_test` path when a generated exercise has the matching runtime profile, but it must not be described as Maven/Gradle or arbitrary project execution.
- TypeScript, SQL, Go, and C# are independent public course selections with teaching-grade runner/runtime limits.
- C++ and Rust are not public course selections and must not be described as currently compile-run executable.

## Short Interview Story

The honest demo sentence is:

> The learning page is now the full LangGraph runtime slice for teaching decisions and ordered UI tools, while Aearn services still own writes, idempotency, public API/SSE contracts, and cross-page persistence. Onboarding and review intentionally stay graph-assisted service flows until a future task proves a safe full-runtime migration.
