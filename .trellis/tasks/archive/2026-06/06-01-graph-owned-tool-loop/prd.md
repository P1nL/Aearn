# Graph owned tool loop

## Goal

Move learning-page tool selection and repeated tool-call decisions into the graph runtime while keeping service persistence explicit.

## Requirements

- Move learning message tool selection into graph-produced `TOOL_CALL` intent order where `LANGGRAPH_ENABLED=true`.
- Support a graph-owned ordered tool loop for cases that need more than one generated UI tool in one learner turn, such as skipped concept check plus exercise card.
- Keep feature services responsible for executing tool calls, loading exercise data, updating `LearningSession`, writing `LearningMessage`, and storing idempotency records.
- Preserve existing non-graph fallback behavior and public response shape.
- Preserve current tool payload safety rules: no hidden tests, reference solutions, raw prompts, provider payloads, or secrets.
- Do not move concept judgement LLM execution, exercise lookup, or persistence into graph nodes.

## Acceptance Criteria

- [x] Graph orchestration can emit ordered tool-call decisions, not only one `tool_name`.
- [x] Learning service consumes the ordered graph `TOOL_CALL` intents and executes supported tools in order.
- [x] Early practice from concept check can emit `show_concept_check_result` followed by `show_code_exercise` from graph intent order.
- [x] Service-owned fallback still works for non-graph paths and graph failures.
- [x] Boundary validation still rejects unsupported tool targets.
- [x] Tests cover graph-owned multi-tool order and unchanged public tool-call payloads.
- [x] Durable writes remain in services/repositories.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
