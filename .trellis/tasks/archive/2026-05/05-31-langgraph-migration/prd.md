# LangGraph Migration

## Goal

Replace the imperative service-layer orchestration (sequential function calls in `learning_conversation.py`, `review_conversation.py`, etc.) with a LangGraph-based state machine. The project already has LangGraph installed as a dependency and a detailed state machine design doc (`docs/architecture/langgraph-state-machine.md`), but none of it is implemented in code.

After this task, conversation flow is a declarative graph with explicit nodes, edges, and state — making it observable, testable, and extensible without modifying orchestration code.

## Context

- `langgraph` and `langgraph-checkpoint-postgres` are declared dependencies in `pyproject.toml` but never imported in application code.
- `docs/architecture/langgraph-state-machine.md` describes:
  - `AgentState` schema with fields for messages, stage, side_effects queue, user context, etc.
  - Named nodes: `context_assembler`, `concept_intro`, `concept_check`, `concept_repair`, `practice_offer`, `select_exercise`, `run_exercise`, `hint_or_explain_error`, `evaluate_attempt`, `update_learning_memory`, etc.
  - Subgraphs: `onboarding_graph`, `learning_graph`, `review_graph`, `resume_graph`, `note_assist_graph`
  - A `route_entry` dispatcher node
  - Checkpoint persistence via Postgres
- Current orchestration: `learning_conversation.py` is a ~72KB file with imperative if/else chains calling agent builders, repository functions, and SSE emitters in sequence.
- Dependency: `agent-handoff-routing` (graph nodes map to specialized agents; handoff edges connect them).

## Requirements

### Graph Definition
- Implement the learning conversation flow as a LangGraph `StateGraph` with:
  - Typed `AgentState` matching the design doc schema
  - Nodes for each logical step (concept intro, concept check, repair, practice, exercise, evaluation, etc.)
  - Conditional edges based on agent decisions and state
  - Entry/exit points matching the current `learning_stage` values
- The graph must be the single source of truth for flow control — no parallel if/else orchestration.

### State Persistence
- Use `langgraph-checkpoint-postgres` to persist graph state across requests within a session.
- State must survive server restarts (checkpoint in Postgres, not in-memory).
- Checkpoint must include: current node, accumulated messages, side effects queue, learning stage, conversation summary.
- Resume from checkpoint on subsequent messages in the same session.

### Side Effects Queue
- Nodes that need to write to the database (create attempt, update mastery, schedule review) must append to a `side_effects` queue in state.
- A dedicated `persist_side_effects` node at the end of each graph execution drains the queue and commits.
- This preserves the principle: agents don't write to DB directly; the graph orchestrator does.

### SSE Integration
- Graph execution must stream SSE events as nodes produce output.
- Each node that generates agent text must emit `agent_message` deltas.
- Tool calls within nodes must emit `tool_call` events.
- The `done` event fires when the graph reaches a terminal node or a wait-for-input node.

### Observability
- Graph execution must be traceable: which nodes executed, in what order, what state transitions occurred.
- Expose a debug endpoint or log format showing the graph execution path for a given session.

## Acceptance Criteria

- [ ] Learning conversation flow is implemented as a LangGraph `StateGraph`.
- [ ] `AgentState` is typed and matches the design doc schema (or a documented subset for MVP).
- [ ] Graph state persists across requests via `langgraph-checkpoint-postgres`.
- [ ] At least the core learning path (concept_intro → concept_check → practice_offer → exercise → evaluate) works as graph nodes.
- [ ] Side effects (DB writes) happen in a dedicated node, not scattered across the graph.
- [ ] SSE events stream correctly during graph execution — no regression in frontend behavior.
- [ ] `learning_conversation.py` imperative orchestration is replaced (not duplicated alongside the graph).
- [ ] At least one test demonstrates graph resumption: message 1 advances to node X, message 2 resumes from node X.
- [ ] Graph execution path is logged for observability.
- [ ] Existing learning flow tests pass with the graph-based implementation.

## Out of Scope

- Migrating review/onboarding/notes flows to LangGraph (follow-up work per subgraph).
- Implementing the full design doc (all subgraphs, all nodes) — start with learning graph only.
- LangGraph Studio or visual debugging tools.
- Changing the product flow or adding new learning stages.

## Dependencies

- Requires: `agent-handoff-routing` (graph nodes correspond to specialized agents; handoff edges are graph edges).
- Uses: `langgraph` and `langgraph-checkpoint-postgres` (already installed).
- Replaces: imperative orchestration in `learning_conversation.py`.

## Risks

- LangGraph adds abstraction overhead — debugging graph execution is harder than reading sequential code. Mitigation: comprehensive logging of node transitions.
- Checkpoint size may grow large for long sessions. Mitigation: prune old messages from state, keep only summary + recent N messages.
- Migration risk: replacing 72KB of working orchestration code. Mitigation: implement graph alongside existing code first, switch over with a feature flag, then remove old code.
- LangGraph version stability — the library is evolving rapidly. Mitigation: pin version, avoid experimental APIs.
