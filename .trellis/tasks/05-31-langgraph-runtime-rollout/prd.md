# LangGraph Runtime Rollout

## Goal

Introduce `learning_graph.py` as an opt-in runtime orchestration path behind `LANGGRAPH_ENABLED` without replacing the stable learning conversation flow by default.

## Requirements

- Add a real service entrypoint that can invoke the compiled learning graph when `LANGGRAPH_ENABLED=true`.
- Keep `LANGGRAPH_ENABLED=false` as the default rollback path.
- Preserve existing API/SSE behavior in the default path.
- Ensure graph invocation receives sanitized current-session state only.
- Do not let graph nodes bypass service/repository persistence boundaries.

## Acceptance Criteria

- [ ] Feature flag off preserves current learning message behavior.
- [ ] Feature flag on invokes the compiled graph from a real request/service path.
- [ ] Graph failures map to safe fallback or model-unavailable behavior without leaking internals.
- [ ] Tests cover flag-off and flag-on routing.
- [ ] Focused backend tests, lint, mypy, and task validation pass.
