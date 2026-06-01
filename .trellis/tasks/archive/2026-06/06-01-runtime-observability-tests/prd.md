# Runtime observability tests

## Goal

Add observability, regression tests, and quality gates across graph orchestration, tools, RAG, memory, routing, and runtime execution.

## Confirmed Facts

- `app/services/graph_event_stream.py` already emits a graph runtime `tool_status` SSE adapter event when graph memory/RAG/runtime context exists.
- Tests already cover graph contracts, event stream basics, learner profile, router, and graph runtime paths.
- The latest hardening work added graph memory/RAG context but observability payloads are still minimal.

## Requirements

- Add bounded runtime observability metadata for graph memory, RAG, fallback, and next-action status.
- Add focused tests that prove observability metadata is present, redacted, and connected to production request helpers.
- Keep observability public-safe and avoid raw diagnostics/provider errors.
- Include tool intent, routing, memory, RAG, and runtime execution regression checks in the task validation set.

## Acceptance Criteria

- [ ] Graph SSE tool-status payload includes safe observability fields.
- [ ] Tests cover memory availability, RAG retrieval status, fallback detection, and redaction/bounding.
- [ ] Existing graph event stream behavior stays backward-compatible for current event name and core fields.
- [ ] Validation command includes the hardened graph/tool/profile/router/runtime tests.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
