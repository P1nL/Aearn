# Technical Design: Agent Transition Control

## Problem Analysis

`_determine_transition` does three things that must be separated:

1. **Routing decision**: which stage to go to next (currently keyword-based if/else)
2. **State preparation**: computing `covered_subpoint_ids`, `feynman_status`, `practice_unlock_reason`, `concept_summary`, `learning_incomplete` for the target stage
3. **Tool selection**: deciding which tool_name to emit (`show_code_exercise`, `show_concept_check_result`, `show_learning_history`)

The agent should own #1 (routing) and #3 (tool selection). The service layer should own #2 (state preparation) because it requires DB context the agent shouldn't have.

## Architecture

### Phase A: Agent-driven routing (this task)

Replace the routing decision with agent tool calls while keeping state preparation in the service layer.

```
Before:
  prepare_learning_message → _determine_transition (keyword match) → transition object
  → agent generates text within that transition's context

After:
  prepare_learning_message → initial context (no transition yet)
  → agent runs with write tools → calls update_learning_stage(new_stage, reason)
  → service layer observes side_effects.stage_updates
  → service layer applies state preparation for the chosen stage
  → agent's text response is the final output
```

### Key Insight

The current flow computes the transition BEFORE the agent runs. The new flow lets the agent decide DURING its run. This means:

1. The agent's system prompt must include the transition map and current stage
2. The agent calls `update_learning_stage` as its first action
3. After the agent turn, the service layer reads `side_effects.final_stage()` and applies state preparation
4. The `tool_name` (show_code_exercise, etc.) becomes a separate tool call the agent makes explicitly

### Transition State Preparation (stays in service layer)

When the agent transitions to a new stage, the service layer applies:

```python
def _prepare_stage_state(current_state: dict, new_stage: str, context: LearningConversationContext) -> dict:
    state = dict(current_state)
    state["covered_subpoint_ids"] = _lesson_subpoint_ids(context)
    state["concept_summary"] = _concept_summary(context)

    if new_stage == "practice_support":
        state["feynman_status"] = state.get("feynman_status", "pending")
        state["practice_unlock_reason"] = state.get("practice_unlock_reason", "agent_decision")
        state["learning_incomplete"] = state.get("learning_incomplete", True)

    if new_stage in ("concept_check", "concept_repair"):
        state["practice_unlock_reason"] = None
        state["learning_incomplete"] = True

    if new_stage in ("concept_intro", "concept_qna", "readiness_check"):
        state["feynman_status"] = "pending"
        state["practice_unlock_reason"] = None
        state["learning_incomplete"] = True

    return state
```

### Migration Strategy

To avoid breaking 40+ tests at once:

1. **Step 1**: Add `_prepare_stage_state` helper (extracted from `_determine_transition`)
2. **Step 2**: Wire side_effects draining into `learning_conversation.py` — after agent turn, if `side_effects.has_stage_change()`, apply `_prepare_stage_state` and update session
3. **Step 3**: Add transition map to agent system prompt (in the messages builder)
4. **Step 4**: Keep `_determine_transition` as fallback for when agent doesn't call the tool (backward compat during migration)
5. **Step 5**: Once tests confirm agent-driven transitions work, remove `_determine_transition` and its helpers

### System Prompt Addition

Add to the learning agent's instructions:

```
你可以通过调用 update_learning_stage 工具来决定教学流程的下一步。
当前阶段: {current_stage}
允许的转换: {allowed_transitions}
转换规则:
- concept_intro/concept_qna: 学员提问时留在 concept_qna，准备检查时转 readiness_check
- readiness_check: 学员解释清楚转 practice_support，需要修正转 concept_check
- concept_check: 回答正确转 practice_support，需要修正转 concept_repair
- concept_repair: 修正后重新检查转 concept_check
- practice_support: 终态，不可转出
```

## SSE Compatibility

- `next_action` field: currently derived from the transition's tool_name. After migration, derived from `side_effects.final_stage()` mapping.
- Tool call events: `update_learning_stage` emits standard `tool_call` SSE events. Frontend shows "正在调用..." fallback (acceptable).
- `show_code_exercise` / `show_concept_check_result`: these remain as separate tool calls the agent can make, not routing decisions.

## Files to Modify

- `app/services/learning_conversation.py` — add `_prepare_stage_state`, wire side_effects draining, add transition info to prompt
- `app/agents/learning_conversation_agent.py` — already updated to accept side_effects/tool_context
- `app/agents/tools.py` — already has `update_learning_stage` tool
- Tests: update assertions that depend on keyword-based transition behavior

## Risk Mitigation

- Keep `_determine_transition` as fallback during migration (if agent doesn't call the tool, fall back to old behavior)
- Feature flag: `AGENT_DRIVEN_TRANSITIONS=true` env var to enable/disable
- Log all agent transition decisions for comparison with what `_determine_transition` would have chosen
