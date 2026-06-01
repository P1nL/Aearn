# Graph checkpoint thread state

## Goal

Add or validate checkpoint/thread state strategy so learning graph execution can resume safely without moving persistence ownership into graph nodes.

## Requirements

- Define a deterministic checkpoint/thread identity strategy for learning graph invocations.
- Ensure thread identity is derived from service-owned session facts, especially `session_id` and `session_type`.
- Pass thread configuration into learning graph and orchestration graph invocations so future checkpointers can resume the same graph thread.
- Keep durable learning state in existing Aearn services/repositories; graph checkpoints may cache graph execution state but must not replace `LearningSession`, `LearningMessage`, `Attempt`, `KnowledgePoint`, or `ReviewState` persistence.
- Keep `LANGGRAPH_ENABLED=false` behavior unchanged.
- Preserve graph failure fallback and public API response shapes.
- Bound and redact checkpoint metadata before it can enter graph config, diagnostics, or tests.

## Acceptance Criteria

- [ ] A reusable typed thread/checkpoint state contract exists in backend code.
- [ ] Thread ids are deterministic for the same session and distinct across session types.
- [ ] Graph invoke config uses `configurable.thread_id` and a bounded namespace without exposing secrets.
- [ ] Learning graph context assembly and orchestration graph invocation pass service-owned thread config.
- [ ] No graph node opens a database connection or writes durable product state as part of checkpointing.
- [ ] Tests cover config serialization, metadata redaction, deterministic identity, and graph invocation wiring.
- [ ] Existing flag-off and graph-fallback tests continue to pass.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
