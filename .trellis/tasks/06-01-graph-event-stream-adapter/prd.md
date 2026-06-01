# Graph event stream adapter

## Goal

Adapt graph node events to the existing learning page streaming/API contract without breaking frontend behavior.

## Requirements

- Add a backend adapter that maps graph runtime progress to the existing learning-page SSE/API event vocabulary.
- Reuse existing frontend-supported event types; do not add a new frontend event type in this task.
- When `LANGGRAPH_ENABLED=true`, learning message SSE may emit bounded graph runtime `tool_status` frames before normal agent text/tool-call frames.
- Keep JSON response shape unchanged and keep non-streaming requests unchanged.
- Preserve existing `agent_message`, `tool_call`, `runner_result`, `evaluation_result`, `done`, and `error` semantics.
- Do not expose raw graph node names, graph diagnostics, checkpoints, hidden tests, reference solutions, raw prompts, provider payloads, secrets, or stack traces in SSE payloads.
- Keep `LANGGRAPH_ENABLED=false` behavior unchanged.

## Acceptance Criteria

- [x] Typed adapter exists for graph runtime stream events.
- [x] Adapter outputs only existing SSE event types and bounded/redacted payloads.
- [x] Learning message SSE emits graph `tool_status` frames only for graph-enabled prepared contexts.
- [x] Existing JSON response shape and replay behavior remain unchanged.
- [x] Focused tests cover adapter redaction/bounding, stream frame ordering, and flag-off compatibility.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
