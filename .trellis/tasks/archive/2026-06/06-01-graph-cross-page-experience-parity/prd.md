# Graph cross page experience parity

## Goal

Keep onboarding and review experiences consistent with learning runtime while avoiding unnecessary full graph runtime migration for those pages.

## Requirements

- Keep onboarding and review graph usage as decision/orchestration helpers, not full learning runtime migrations.
- Validate onboarding and review graph `GraphRunResult` outputs against page-specific allowed intent targets before route/service code consumes them.
- If onboarding or review graph output is invalid, unscoped, or throws, fall back to the existing service-owned behavior without changing public JSON/SSE response shapes.
- Onboarding may use graph decisions only for route draft generation/revision and confirm gating; services still own draft building, stash, plan confirmation, idempotency, and route-card SSE.
- Review may use graph decisions only for due-state routing and coach/warmup/submit orchestration hints; services/repositories still own sessions, attempts, FSRS updates, review logs, and idempotency.
- Do not add graph runtime `tool_status` frames, graph diagnostics, raw graph node names, checkpoints, provider payloads, raw prompts, stack traces, API keys, or secrets to onboarding/review public responses.
- Keep `LANGGRAPH_ENABLED=false` behavior unchanged for onboarding and review.

## Acceptance Criteria

- [x] Onboarding graph decisions are boundary-validated before route generation or confirm gating.
- [x] Review graph decisions are boundary-validated before due-state or review action routing.
- [x] Invalid graph outputs fall back to service-owned behavior instead of changing public outcomes.
- [x] Onboarding and review public JSON/SSE responses do not expose graph runtime internals or new event types.
- [x] Focused tests cover onboarding confirm fallback, review start fallback, flag-on graph invocation, and existing page behavior.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
