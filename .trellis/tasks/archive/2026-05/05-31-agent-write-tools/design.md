# Technical Design: Agent Write Tools

## Architecture

Add write-capable tools to the learning conversation agent using the same `function_tool` pattern as existing read tools in `tools.py`. Tools receive a mutable context object (not a DB connection directly) and return structured results the agent can reason about.

The key constraint: tools must not commit transactions. They accumulate side effects that the service layer commits after the agent turn completes. This preserves the existing pattern where `learning_conversation.py` owns the transaction boundary.

## Tool Definitions

### 1. `trigger_code_run(code: str, exercise_id: str) -> dict`

Invokes the runtime runner on user code and returns structured results.

- Input: raw code string + exercise ID for test case lookup
- Output: `{status, stdout, stderr, test_results: [{name, passed, actual, expected}], pass_rate}`
- Initially delegates to existing `runtime_runner.py` (heuristic); will transparently switch to real execution when `real-code-execution` task completes
- Does NOT create an Attempt record (that's `record_attempt`'s job)

### 2. `update_learning_stage(new_stage: str, reason: str) -> dict`

Transitions the session's learning stage.

- Input: target stage name + LM-provided reason
- Output: `{success: bool, previous_stage, new_stage, error?}`
- Validates against allowed transition map (see below)
- Returns error result (not exception) for invalid transitions
- Writes to the side-effects accumulator, not directly to DB

### 3. `record_diagnosis(diagnosis: dict) -> dict`

Persists a structured diagnosis to the session's state JSON.

- Input: `{stuck_point?, misconceptions?, recommended_action?, concepts_explained?}`
- Output: `{recorded: true, summary_updated: true}`
- Merges into `learning_stage_state_json.conversation_summary`
- Uses the structured judgement format from the shared module

### 4. `record_attempt(exercise_id: str, code: str, action: str) -> dict`

Creates an Attempt record for a run/submit action.

- Input: exercise ID, submitted code, action type ("run" | "submit")
- Output: `{attempt_id, created: true}`
- Appends to side-effects accumulator for DB write

## Transition Map

Valid transitions the agent can request via `update_learning_stage`:

```
concept_intro    -> concept_qna, readiness_check, concept_check
concept_qna      -> concept_intro, readiness_check, concept_check
readiness_check  -> concept_check, practice_support, concept_qna
concept_check    -> concept_repair, practice_support
concept_repair   -> concept_check, practice_support
practice_support -> (terminal within session)
```

## Side-Effects Accumulator Pattern

```python
@dataclass
class AgentSideEffects:
    stage_updates: list[dict]       # [{new_stage, reason}]
    diagnosis_updates: list[dict]   # [{stuck_point, ...}]
    attempt_records: list[dict]     # [{exercise_id, code, action}]

    def has_stage_change(self) -> bool: ...
    def final_stage(self, current: str) -> str: ...
```

Tools write to this accumulator. After the agent turn completes, `learning_conversation.py` drains it:
1. Apply stage updates to session
2. Merge diagnosis into state JSON
3. Create Attempt records
4. Commit transaction

This keeps the agent's tool calls non-destructive until the service layer validates and commits.

## Integration Point

`build_teaching_tools(messages)` in `tools.py` currently returns read-only tools. Extend it to:

```python
def build_teaching_tools(
    messages: Sequence[Mapping[str, str]],
    *,
    side_effects: AgentSideEffects | None = None,
    context: LearningToolContext | None = None,
) -> list[Tool]:
```

When `side_effects` and `context` are provided, write tools are included. When omitted (backward compat), only read tools are returned.

`LearningToolContext` is a frozen dataclass with:
- `session_id`, `exercise_id`, `current_stage`
- `allowed_transitions: dict[str, list[str]]`
- `runner` reference for code execution

## SSE Compatibility

Write tools emit standard `tool_call` SSE events (start/delta/done) via the existing `chunk_tool_call_arguments` mechanism. No new event types needed. The frontend sees tool calls like any other — it just doesn't render a card for them (falls back to the "正在调用..." placeholder, which is acceptable for write operations).

## Testing Strategy

- Unit tests: tool functions with mock context/side-effects, verify accumulator state
- Integration test: full agent turn where LM calls `trigger_code_run` → observes result → responds
- Use existing `FakeRunner`/monkeypatch pattern from `test_llm_integration.py`
- No API keys needed: monkeypatch `build_sdk_*` functions as in M3 tests

## Files to Create/Modify

- `app/agents/tools.py` — extend with write tools + `AgentSideEffects` + `LearningToolContext`
- `app/agents/learning_conversation_agent.py` — pass context/side_effects to `build_teaching_tools`
- `app/services/learning_conversation.py` — create side_effects, pass to agent, drain after turn
- `tests/test_agent_write_tools.py` — new test file for write tool unit tests
