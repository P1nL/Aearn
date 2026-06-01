# Design

## Tool Loop Contract

The graph owns tool selection, but the service owns tool execution.

Graph output:

- Single-tool turns may continue to expose `tool_name` for backwards compatibility.
- Multi-tool turns expose ordered `tool_names`.
- `graph_result_to_run_result()` converts ordered `tool_names` into ordered `IntentType.TOOL_CALL` intents.

Service consumption:

- `_determine_transition_via_graph()` reads ordered `TOOL_CALL` intents and stores them on `LearningConversationTransition`.
- `_apply_transition_and_build_tool_calls()` executes supported tool names in order while keeping existing service/repository ownership.
- Unsupported tool targets remain blocked by `validate_run_result_for_boundary()`.

## Initial Multi-Tool Case

The first graph-owned repeated tool-call case is direct practice from a concept-check or repair stage:

```text
TOOL_CALL show_concept_check_result
TOOL_CALL show_code_exercise
```

The graph decides that both UI tools are needed. The service still builds the skipped/repair-limit concept result payload, unlocks practice through `unlock_learning_session_practice()`, loads exercise data, persists state, and writes the final `LearningMessage`.

## Compatibility

- `tool_name` remains in raw graph output to avoid breaking existing callers.
- Non-graph `_determine_transition()` keeps the prior service-owned compatibility path.
- Public response remains `tool_calls: [...]` with the same payload shapes and ordering.
- SSE adaptation remains deferred to `graph-event-stream-adapter`; this task only prepares ordered tool calls in the JSON/service path.

## Rollback

Rollback is removing `tool_names` support and reverting to the previous single `tool_name` flow. No database rollback is needed.
