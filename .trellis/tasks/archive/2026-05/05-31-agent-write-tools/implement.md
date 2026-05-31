# Implementation Plan: Agent Write Tools

## Ordered Steps

1. Add `AgentSideEffects` and `LearningToolContext` dataclasses to `app/agents/tools.py`.

2. Add write tool functions to `app/agents/tools.py`:
   - `trigger_code_run` — calls runtime runner, returns structured result
   - `update_learning_stage` — validates transition, appends to side_effects
   - `record_diagnosis` — appends diagnosis to side_effects
   - `record_attempt` — appends attempt record to side_effects

3. Extend `build_teaching_tools` signature to accept optional `side_effects` and `context` params. When provided, include write tools alongside existing read tools.

4. Update `AgentsSDKLearningConversationClient` in `learning_conversation_agent.py` to accept and forward `side_effects` and `context`.

5. Update `learning_conversation.py` to:
   - Create `AgentSideEffects` instance before agent call
   - Build `LearningToolContext` from session state
   - Pass both to the agent client
   - After agent turn: drain side_effects and apply (stage update, diagnosis merge, attempt creation)

6. Write unit tests in `tests/test_agent_write_tools.py`:
   - `update_learning_stage` with valid transition → accumulates
   - `update_learning_stage` with invalid transition → returns error
   - `record_diagnosis` → merges into accumulator
   - `trigger_code_run` → returns structured runner result
   - `AgentSideEffects.final_stage` logic

7. Write integration test demonstrating multi-turn tool loop (agent calls tool, observes, responds).

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_agent_write_tools.py -v
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py -v
uv --directory .\aearn\services\api run ruff check app/agents/tools.py app/agents/learning_conversation_agent.py app/services/learning_conversation.py tests/test_agent_write_tools.py
uv --directory .\aearn\services\api run python -m mypy --follow-imports=skip app/agents/tools.py app/agents/learning_conversation_agent.py
```

## Review Gates

- Write tools must not import DB/route modules
- Side effects accumulator must not commit transactions
- Existing read-only tool behavior unchanged when side_effects=None
- Transition map must match current valid stage transitions
- Existing M3 tests must pass without modification
