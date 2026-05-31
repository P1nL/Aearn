# Technical Design: LangGraph Migration (MVP Skeleton)

## Scope

Full migration of 72KB orchestration code is multi-session work. This task delivers:
1. `AgentState` TypedDict matching the design doc
2. Learning graph skeleton with core nodes (concept_intro → concept_check → practice_offer → exercise)
3. Feature flag `LANGGRAPH_ENABLED` for gradual rollout
4. Graph definition is importable and testable (node connectivity, state transitions)

The graph does NOT replace `learning_conversation.py` yet — it runs alongside as an alternative path.

## Architecture

### `app/agents/learning_graph.py`

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict, total=False):
    request_id: str
    user_id: str
    session_id: str
    session_type: str
    learning_stage: str
    learning_stage_state: dict
    knowledge_point: dict
    exercise: dict | None
    runtime_result: dict | None
    side_effects: list
    messages: list
    next_action: str | None
    errors: list

def build_learning_graph() -> StateGraph:
    ...
```

### Node Functions

Each node is a pure function: `(state: AgentState) -> dict` returning state updates.

- `context_assembler` — loads KP context into state
- `concept_intro` — generates concept introduction
- `concept_check` — evaluates user understanding
- `practice_offer` — offers practice transition
- `select_exercise` — picks exercise
- `persist_side_effects` — drains side_effects queue

### Conditional Edges

```python
graph.add_conditional_edges("concept_check", route_after_check, {
    "correct": "practice_offer",
    "incorrect": "concept_repair",
    "practice": "select_exercise",
})
```

## Files to Create

- `app/agents/learning_graph.py` — graph definition + AgentState
- `tests/test_learning_graph.py` — graph structure tests

## Files to Modify

- `app/core/config.py` — add `LANGGRAPH_ENABLED` setting
