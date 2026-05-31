# Technical Design: Agent Handoff Routing

## Problem Analysis

Each API endpoint is hardcoded to one agent. No routing, no handoffs. The user experience is fragmented across endpoints.

## Architecture Decision

**Rule-based routing + SDK handoffs**

Rationale:
- LLM-based routing adds 1-2s latency per message — unacceptable for MVP
- Session stage + user intent keywords provide sufficient routing signal
- OpenAI Agents SDK `handoffs` parameter enables native agent-to-agent transfer
- Keeps existing single-agent flows working (handoff is additive)

## Design

### Agent Registry

A central registry that maps agent names to their builder functions:

```python
AGENT_REGISTRY = {
    "teaching": build_teaching_agent,
    "exercise_coach": build_exercise_coach_agent,
    "diagnosis": build_diagnosis_agent,
    "review_coach": build_review_coach_agent,
}
```

### Routing Rules (no LLM call)

```python
def route_message(session_stage: str, user_message: str, session_type: str) -> str:
    # Stage-based routing (primary signal)
    if session_stage in ("practice_support",) and _wants_hint(user_message):
        return "exercise_coach"
    if session_stage in ("concept_intro", "concept_qna", "readiness_check"):
        return "teaching"
    if session_stage in ("concept_check", "concept_repair"):
        return "diagnosis"
    # Default
    return "teaching"
```

### Handoff Integration

Each agent declares which agents it can hand off to:
- Teaching → exercise_coach, diagnosis
- Exercise coach → teaching, diagnosis
- Diagnosis → teaching, exercise_coach

The SDK handles the handoff protocol natively via `Agent(handoffs=[...])`.

### SSE Compatibility

Handoffs happen within a single `run_streamed()` call — the SDK manages the transition internally. The text stream continues uninterrupted. An optional `agent_handoff` SSE event can be emitted when the active agent changes.

## Files to Create

- `app/agents/router.py` — routing logic + agent registry

## Files to Modify

- `app/agents/sdk_runtime.py` — add `handoffs` param to `build_agent`
- `tests/test_agent_router.py` — routing tests
