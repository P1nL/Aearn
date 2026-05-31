# Agent Transition Control

## Goal

Replace the hardcoded `_determine_transition` if/else logic in `learning_conversation.py` with LM-driven stage routing via tool calls. The agent should decide "what happens next" (continue teaching, offer practice, show history, transition to review) based on conversation context, not keyword matching.

After this task, the learning agent is truly autonomous in its pedagogical decisions within the bounds of allowed transitions.

## Context

- `learning_conversation.py` currently has `_determine_transition(stage, message, state)` which uses:
  - `_requests_practice(msg)` — keyword match for "练习/practice/试试/code"
  - `_requests_history(msg)` — keyword match for "历史/history/之前"
  - `_passes_feynman_check(msg)` — length + token heuristic
  - Hardcoded if/else over `learning_stage` values
- `learning_stage` values: `concept_intro`, `concept_check`, `concept_repair`, `practice_offer`, `exercise_active`, `exercise_feedback`, `hint_active`, `error_explain`, `explanation_check`, `session_complete`
- The LangGraph state machine doc (`docs/architecture/langgraph-state-machine.md`) describes the intended graph but is not implemented.
- Dependency: `agent-write-tools` must be complete (agent needs `update_learning_stage` tool to act on its decisions).

## Requirements

- Remove `_determine_transition`, `_requests_practice`, `_requests_history`, `_passes_feynman_check` from `learning_conversation.py`.
- Add a `transition_stage` tool (or extend `update_learning_stage` from `agent-write-tools`) that the agent calls to declare its routing decision.
- The agent's system prompt must include:
  - The current stage and allowed next stages (as a transition map)
  - Policy rules: when to offer practice, when to require concept check, when repair is needed
  - The learner's current state (from `safe_summary`)
- The agent must call the transition tool explicitly — implicit transitions (Python code deciding after the agent responds) are removed.
- Allowed transition map must be enforced server-side: if the agent requests an invalid transition, the tool returns an error and the agent must choose a valid one.
- Transition decisions must be logged (stage_from, stage_to, reason) for observability.
- The existing `next_action` field in SSE `agent_message` events must still be populated correctly for frontend state management.

## Acceptance Criteria

- [ ] `_determine_transition` and its helper functions are deleted from `learning_conversation.py`.
- [ ] The agent decides stage transitions via tool call, not Python control flow.
- [ ] Transition map is enforced: invalid transitions return tool errors, not exceptions.
- [ ] All valid learning stage transitions from the current flow are preserved (no regression in reachable states).
- [ ] `next_action` in SSE events is still correctly populated based on the new stage.
- [ ] At least one test demonstrates the agent choosing to transition based on conversation context (not keyword matching).
- [ ] At least one test demonstrates the agent being blocked from an invalid transition.
- [ ] Existing learning flow tests pass with updated assertions (keyword-based transition tests are replaced with tool-call-based tests).
- [ ] No changes to frontend code — SSE event shapes are preserved.

## Out of Scope

- Applying transition control to review/onboarding flows (follow-up).
- Implementing the full LangGraph state machine (that's `langgraph-migration`).
- Changing the set of learning stages or adding new ones.
- Modifying exercise/attempt creation flow.

## Dependencies

- Requires: `agent-write-tools` (provides the `update_learning_stage` tool mechanism).
- Enables: `agent-handoff-routing` (routing between agents builds on per-agent transition control).

## Risks

- LM may make worse transition decisions than the hardcoded heuristics initially. Mitigation: keep the transition map strict and log all decisions for tuning.
- Latency increase from tool-call round-trip. Mitigation: transition tool is fast (DB write + validation), and the existing `max_turns=4` bounds total round-trips.
