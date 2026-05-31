# Agent Write Tools

## Goal

Give the learning agent tools that can mutate backend state, enabling a real ReAct loop where the LM observes results and decides next actions. Currently all 3 tools are read-only summarizers; the agent cannot trigger code execution, create attempts, update learning stages, or write diagnostic records.

After this task, the agent's `max_turns=4` loop becomes meaningful: the LM can call a tool, observe the result, and decide whether to call another tool or respond to the user.

## Context

- Current tools (`tools.py`): `get_current_learning_context`, `get_latest_visible_attempt_summary`, `get_current_note_summary` — all read-only.
- All state mutations currently happen in Python service code (`learning_conversation.py`, `learning_session_repository.py`) outside the agent boundary.
- The OpenAI Agents SDK supports `function_tool` with arbitrary Python callables. Tools can return structured data that the agent observes.
- Frontend already handles `tool_call` SSE events with start/delta/done lifecycle — no frontend changes needed for new backend tools.
- Dependency: `shared-structured-judgement-module` must be complete (provides the structured output format for tool results).

## Requirements

- Add write tools to the learning conversation agent:
  - `trigger_code_run(code, exercise_id)` — invoke the runtime runner and return execution results (stdout, stderr, test pass/fail). Must integrate with `real-code-execution` when available, but initially can use the existing heuristic runner.
  - `update_learning_stage(new_stage, reason)` — transition the session's `learning_stage` with an LM-provided reason. Must validate against allowed transitions.
  - `record_diagnosis(diagnosis)` — persist a structured diagnosis (stuck_point, misconceptions, recommended_action) to `learning_stage_state_json`.
  - `create_attempt(exercise_id, submitted_code, action)` — create an Attempt record for run/submit actions.
- Tools must receive a connection/context object but NOT import route-level or request-level dependencies.
- Tools must validate inputs (e.g., `new_stage` must be in the allowed transition set from current stage).
- Tools must return structured results that the agent can reason about (not just "success").
- Tool execution must be wrapped in the existing transaction boundary managed by the service layer.
- Tools must not bypass guardrails — the agent cannot force a stage transition that policy disallows.
- Existing read-only tools remain available alongside new write tools.

## Acceptance Criteria

- [ ] At least 3 write tools are registered on the learning conversation agent.
- [ ] Agent can call `trigger_code_run` and receive structured execution results within the same turn.
- [ ] Agent can call `update_learning_stage` and the session's stage actually changes in the database.
- [ ] Agent can call `record_diagnosis` and the diagnosis appears in `learning_stage_state_json.conversation_summary`.
- [ ] Write tools validate inputs and return error results (not exceptions) for invalid calls.
- [ ] Existing tests pass — write tools are opt-in and don't change behavior when the agent doesn't call them.
- [ ] At least one integration test demonstrates a multi-turn tool loop: agent calls tool → observes result → responds.
- [ ] No tool directly commits a transaction; the service layer retains commit authority.
- [ ] Frontend SSE event shape is unchanged — new tools emit standard `tool_call` events.

## Out of Scope

- Replacing the fake runtime runner (that's `real-code-execution`).
- Removing `_determine_transition` (that's `agent-transition-control`).
- Adding tools to review/notes/onboarding agents (follow-up work).
- Changing the frontend generative UI cards.

## Dependencies

- Requires: `shared-structured-judgement-module` (for structured tool output format).
- Enables: `agent-transition-control` (which removes the if/else and relies on `update_learning_stage` tool).
