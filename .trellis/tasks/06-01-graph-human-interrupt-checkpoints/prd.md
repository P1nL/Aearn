# Graph human interrupt checkpoints

## Goal

Model human approval/clarification checkpoints for stage transitions, route revisions, and unsafe or ambiguous actions.

## Requirements

- Add a typed graph-owned human checkpoint contract for approval, clarification, and safety boundary interrupts.
- Express checkpoints as bounded `feedback_request` intents consumed by the service layer; graph nodes must not write durable approval state directly.
- Cover learning-stage transitions where a learner asks to skip concept checks, asks an ambiguous readiness answer, or requests unsafe complete answers.
- Preserve existing learning API response shape and deterministic fallbacks; checkpoint metadata must stay internal unless an existing public tool/message path already exposes the same learner-facing prompt.
- Keep `LANGGRAPH_ENABLED=false` behavior unchanged.
- Do not introduce real-time human review queues, new database tables, or new frontend surfaces in this task.
- Do not expose hidden tests, reference solutions, raw prompts, provider payloads, secrets, graph diagnostics, or raw checkpoint internals in public responses.

## Acceptance Criteria

- [x] Typed contract exists for graph human checkpoints with bounding/redaction.
- [x] Learning orchestration can emit checkpoint metadata for early practice approval, readiness clarification, and direct-answer safety cases.
- [x] Checkpoints convert to scoped `feedback_request` intents and pass learning graph boundary validation.
- [x] Service fallback remains stable when a graph emits an invalid or unscoped checkpoint intent.
- [x] Public learning message responses do not expose raw `human_checkpoint` or graph diagnostics.
- [x] Focused tests cover contract construction, orchestration intent conversion, service boundary acceptance, and fallback behavior.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
