# Graph runtime tests

## Goal

Add focused tests for graph runtime branches, fallbacks, event mapping, memory/RAG context, and service intent execution.

## Requirements

- Cover the learning graph runtime vertical slice with focused tests that are easier to diagnose than broad milestone smoke tests.
- Lock the service/graph boundary for graph-produced `GraphRunResult` objects:
  - ordered `STAGE_UPDATE` and `TOOL_CALL` intents are consumed by the learning service in graph order
  - scoped human checkpoint intents are accepted without becoming public payloads
  - unscoped persistence/profile/side-effect intents fall back to the stable service path
- Cover memory/RAG context injection into graph invocation without leaking `solution_reference`, hidden tests, raw provider payloads, or internal graph diagnostics.
- Cover SSE event mapping from graph runtime context into the existing public `tool_status` vocabulary.
- Keep onboarding and review tests focused on graph decision validation and fallback; do not migrate durable writes into graph nodes.
- Do not add live model, live web, or external service dependencies.

## Acceptance Criteria

- [x] Focused graph runtime tests cover ordered learning intents, fallback on invalid graph output, memory/RAG argument passing, and safe SSE event mapping.
- [x] Existing route-level graph tests for learning, onboarding, and review continue to pass with `LANGGRAPH_ENABLED=true` and flag-off compatibility.
- [x] Tests assert public responses and SSE frames do not expose raw graph diagnostics, `langgraph_runtime`, memory snapshots, RAG internals, provider payloads, API keys, hidden tests, or `solution_reference`.
- [x] The task runs the relevant backend focused tests plus `ruff` and `mypy`.
- [x] No production behavior is changed unless a test exposes a real boundary bug.

## Notes

- This is a test hardening task. The target is regression coverage for the graph runtime slice implemented by earlier `02` subtasks.
