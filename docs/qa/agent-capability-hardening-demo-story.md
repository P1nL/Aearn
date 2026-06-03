# Agent Capability Hardening Demo Story

日期：2026-06-01

状态：Post-MVP agent capability hardening review / interview story

范围：`06-01-agent-capability-hardening` 下的语言能力边界、学习页 graph runtime、工具 intent、learner profile 信号、RAG grounding、routing / handoff、observability 和 demo 验证。

## 一句话结论

Aearn 现在可以演示一个边界清晰的 AI 编程学习 Agent：学习页是完整 LangGraph runtime vertical slice，graph 负责学习阶段与有序工具 intent 决策；service / repository 继续拥有持久化、idempotency、API/SSE 公共契约和评分/复习写入；语言能力通过 registry 明确区分“可执行”“浏览器预览”“静态/计划中”，避免把未来 runner 误说成当前能力。

这份文档是面试或评审用叙事，不替代 `architecture/langgraph-state-machine.md`、`architecture/api-contract.md`、`architecture/database-schema.md` 或 `qa/learning-graph-runtime-demo-story.md`。

## Demo Path

从 `E:\codee\Aearn` 开始讲 demo：

1. 创建或恢复学习路线：onboarding 可以被 graph-assisted 决策影响，但 `LearningPlan`、modules、knowledge points、review states 和 latest-card-wins 仍由 service / repository 写入。
2. 进入学习页：learning session 加载当前 `LearningConversationContext`，包含 stage、knowledge point、lesson outline、最近 attempt、安全 conversation summary、learner profile summary、memory snapshot 和 RAG context。
3. 发送困惑消息：router 不只看关键词，还使用 stage、recent runtime error、learner profile weak signals、exercise/tool availability，选择 `teaching`、`exercise_coach` 或 `diagnosis`，并只暴露 bounded handoff targets。
4. Graph 决策学习动作：LangGraph 返回 scoped `STAGE_UPDATE` / `TOOL_CALL` intents；service 先做 boundary validation，再执行允许的 stage/tool side effects。
5. 展示有序 UI 工具：graph-owned tool loop 可以保持 `show_concept_check_result` 在 `show_code_exercise` 之前，旧的 public `tool_call` / `tool_status` / `agent_message` / `done` SSE vocabulary 不变。
6. 运行或提交练习：Python 使用真实 stdout/test runner 路径；JavaScript / HTML / CSS 使用 browser-preview course boundary；TypeScript 使用 Node/TypeScript 单文件 runner；SQL 使用 SQLite 教学方言 runner；Java / Go / C# 使用本机 teaching-grade `managed_compiled_test` 单练习 runner；C++ / Rust 暂不支持公开路线，不能宣称完整项目级执行。
7. 进入 review：review graph 可以决定 not-due / warmup / submit 路径，但 `Attempt(review_submit)`、`ReviewState`、`ReviewLog`、FSRS update 和 replay protection 仍由 review service / repository 拥有。

## Responsibility Boundaries

| Boundary | 当前拥有者 | Demo 里要强调的点 |
|---|---|---|
| Learning route / plan persistence | Service / repository | Graph 可以辅助判断，不直接写 `LearningPlan` 或 route card 持久化 |
| Learning stage and tool decisions | Graph + service boundary adapter | Graph 产出 typed intents，service 验证后执行 |
| Attempts and scoring | Service / repository | `Attempt(run)`、`Attempt(submit)`、hidden tests、FSRS rating 不暴露成前端决策 |
| Learner profile memory | Service-owned profile helpers | submit/review submit 合并稳定 signals，router 只读安全 summary |
| RAG grounding | Allowlisted docs grounding + service injection | 不开放 live agent web search；只注入 bounded trusted context |
| Handoff | Rule-based router + bounded SDK handoff targets | 最小可用，不引入未验证的 learned router |
| Observability | Existing SSE `tool_status` payload | 只暴露 safe additive `observability`，不泄露 raw graph diagnostics、provider payload、API key、hidden tests 或 `solution_reference` |

## Capability Boundary Matrix

| Capability | Current status | How to say it in review |
|---|---|---|
| Python execution | Real `python_stdout_test` runner path, visible/hidden tests, subprocess-restricted not container-grade sandbox | “Python exercises are actually runnable, with explicit sandbox limits.” |
| JavaScript / HTML / CSS | Browser-preview learning/runtime boundary with visible/hidden style checks | “Browser-side learning flows are supported through preview/assertion style checks, not a Node runner.” |
| Java | Public course language with teaching-grade `managed_compiled_test` | “Java exercises can run as single-file local JDK-backed teaching tasks, not Maven/Gradle projects or a container sandbox.” |
| TypeScript / SQL / Go / C# | Public teaching-grade runner layer | “These are independent public course selections, but they are still limited to single-file, query, or harness-based teaching execution.” |
| C++ / Rust | Unsupported public route / planned internal boundary | “C++ and Rust are not public course selections yet, and neither has current compile-run execution.” |
| Graph runtime | Full vertical slice on learning page | “Learning page proves graph orchestration end-to-end while service still owns writes.” |
| Onboarding / review graphs | Graph-assisted service flows | “They consume decisions but intentionally keep persistence and replay protection outside graph nodes.” |

## Interview Tradeoffs

- Why not let graph write the database? Because idempotency, FSRS, hidden-test scoring, `ReviewState`, `ReviewLog`, and route-card persistence are product invariants; keeping them service/repository-owned prevents graph checkpoint state from becoming a second source of truth.
- Why a rule-based router? The current need is bounded handoff selection using stable signals, not an opaque learned router. Stage, latest attempt, profile weak signals, and tool availability are enough for the current product slice and are testable.
- Why allow docs grounding before execution support? Documentation readiness and runtime readiness are different contracts. A language can have official/trusted docs grounding while still being unavailable for public execution.
- Why additive observability instead of raw graph traces? The desktop UI already consumes `tool_status`; safe additive fields give review/debug signals without leaking node internals, provider messages, stack traces, hidden tests, secrets, or raw prompts.
- Why keep onboarding/review graph-assisted? The learning page is the runtime proof. Onboarding and review can adopt more graph ownership later only after the same boundary validation, replay, and persistence tests exist for those flows.

## Regression Proof Points

Focused proof used during this hardening closeout:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learner_profile.py tests/test_learning_sessions_m3.py tests/test_reviews_m4.py
uv --directory .\aearn\services\api run python -m pytest tests/test_agent_write_tools.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run python -m pytest tests/test_graph_event_stream.py tests/test_graph_runtime_contracts.py tests/test_learning_graph.py tests/test_agent_write_tools.py tests/test_agent_router.py tests/test_learner_profile.py
uv --directory .\aearn\services\api run python -m pytest tests/test_agent_router.py tests/test_learning_sessions_m3.py tests/test_llm_integration.py
```

Final review gates for this slice:

```powershell
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
git diff --check
```

Bootstrap DB route tests share the same local database, so run those pytest batches sequentially rather than in parallel.

## Related Docs

- `qa/learning-graph-runtime-demo-story.md` explains the learning page graph runtime vertical slice in more detail.
- `architecture/langgraph-state-machine.md` remains the source of truth for graph nodes, conditions, and write timing.
- `architecture/api-contract.md` remains the source of truth for public API/SSE response shapes.
- `architecture/database-schema.md` remains the source of truth for persistence and idempotency invariants.
