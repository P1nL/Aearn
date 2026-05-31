# Implementation Plan: Agent Transition Control

## Ordered Steps

1. Extract `_prepare_stage_state` helper from `_determine_transition` logic in `learning_conversation.py`.

2. Add side-effects draining logic to the learning message flow:
   - After agent turn completes, check `side_effects.has_stage_change()`
   - If yes: call `_prepare_stage_state` with the agent's chosen stage, update session
   - If no: fall back to existing `_determine_transition` behavior (backward compat)

3. Wire `AgentSideEffects` and `LearningToolContext` creation into `prepare_learning_message` / `start_learning_generation`:
   - Build context from session state
   - Pass to agent client

4. Add transition map and routing instructions to the learning agent's system prompt (in the messages builder that constructs the system message).

5. Add logging for agent transition decisions (stage_from, stage_to, reason).

6. Update tests:
   - Add test proving agent-driven transition works (agent calls update_learning_stage → stage changes)
   - Existing tests continue to pass via fallback path (agent doesn't call tool → old behavior)

7. Verify all validation commands pass.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_agent_write_tools.py tests/test_learning_sessions_m3.py -v
uv --directory .\aearn\services\api run ruff check app/agents/tools.py app/agents/learning_conversation_agent.py app/services/learning_conversation.py
uv --directory .\aearn\services\api run python -m mypy --follow-imports=skip app/agents/tools.py app/agents/learning_conversation_agent.py app/services/learning_conversation.py
```

## Review Gates

- `_determine_transition` remains as fallback — no existing test should break
- Side effects draining must happen within the existing transaction boundary
- Agent's transition decision must be logged
- SSE event shapes unchanged
- `next_action` field still correctly populated

## Rollback Points

- If agent-driven transitions cause test instability, disable by not passing side_effects to agent client (reverts to read-only tools + fallback transition)
