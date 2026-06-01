# Graph runtime boundary contract

## Goal

Define the exact boundary between LangGraph orchestration, services, repositories, SSE, and API contracts for the learning page runtime.

## Requirements

- Define a shared runtime boundary contract for the learning page LangGraph path.
- Make ownership explicit for LangGraph orchestration, feature services, repositories, API response envelopes, and SSE frames.
- Keep graph nodes responsible for routing decisions, stage transitions, next-action selection, and typed intent production only.
- Keep services responsible for consuming graph intents, executing durable writes through existing repositories, enforcing idempotency, and mapping results into public API/SSE contracts.
- Keep repositories responsible for SQL and persistence invariants; graph modules must not open database connections or write product rows directly.
- Preserve the existing `LANGGRAPH_ENABLED=false` stable service path and graph-exception fallback behavior.
- Preserve current learning page public response shape, tool-call metadata, and user-facing stage behavior.
- Ensure graph diagnostics, safe context, and intent payloads stay bounded and redacted before service/API consumption.

## Acceptance Criteria

- [ ] The boundary is represented in code as a reusable contract, not only prose.
- [ ] The contract documents ownership for graph, service, repository, API, and SSE layers.
- [ ] Learning graph results are validated against the boundary before service consumption.
- [ ] Unsupported or unsafe graph intents do not trigger blind service writes.
- [ ] Existing flag-off behavior still avoids graph execution.
- [ ] Existing graph failure fallback stays deterministic and does not leak raw graph errors.
- [ ] Focused tests cover ownership metadata, intent validation, safe payload redaction, service-owned write boundaries, and learning message compatibility.
- [ ] No repository writes are moved into graph nodes as part of this task.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
