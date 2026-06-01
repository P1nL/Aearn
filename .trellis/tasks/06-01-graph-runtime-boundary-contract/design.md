# Design

## Boundary Model

The learning LangGraph runtime is a decision layer. It may inspect bounded state, choose the next stage, select tool/UI actions, and emit typed intents. It must not directly execute durable writes, construct public API envelopes, or emit SSE frames.

Layer ownership:

| Layer | Owns | Does Not Own |
|---|---|---|
| Graph | routing decisions, stage transitions, next-action selection, `GraphRunResult` / `GraphIntent` production | database connections, idempotency records, public response envelopes, SSE frame ordering |
| Service | graph invocation, boundary validation, durable write orchestration through repositories, idempotency replay, fallback to stable imperative path | SQL invariants, direct graph-internal routing logic |
| Repository | SQL, transaction-scoped persistence invariants, database constraints | graph decisions, public response rendering |
| API | request validation, response envelope selection, HTTP/SSE mode selection | graph internals, repository writes |
| SSE | event names, frame order, bounded public payloads | graph diagnostics, raw model/provider/internal errors |

## Contract Shape

Extend the existing graph runtime contract module with:

- A typed owner enum for `graph`, `service`, `repository`, `api`, and `sse`.
- A serializable boundary contract describing layer responsibilities.
- Intent boundary rules describing which owner produces an intent, which owner consumes it, whether it may request durable writes, and whether it is public API/SSE visible.
- A validation helper that combines existing `GraphRunResult` validation with boundary checks.

The validation helper should reject graph output that cannot be safely consumed by the current service path. For the learning message path in this task, the service consumes only stage updates and supported tool calls. Persistence/profile/side-effect intents can remain contractually modeled for later tasks, but the current learning message adapter must not execute them blindly.

## Compatibility

- `LANGGRAPH_ENABLED=false` must continue to use `_determine_transition()` without compiling or invoking graph code.
- Graph compile/invoke failures must continue to fall back to `_determine_transition()` and must not leak raw errors to API responses.
- Existing `invoke_orchestration()` return shape remains compatible: raw fields plus `run_result`.
- Existing tests for learning stages and tool calls should continue to pass.

## Rollback

The change is additive around boundary validation. Rollback is removing the validation call and the new boundary helpers while leaving the older `GraphRunResult`/`GraphIntent` dataclasses intact.
