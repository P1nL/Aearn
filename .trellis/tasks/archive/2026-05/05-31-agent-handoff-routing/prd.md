# Agent Handoff Routing

## Goal

Replace the current architecture where each API endpoint is hardcoded to one agent with a meta-agent routing system. A single conversation entry point should route to the appropriate specialized agent (teaching, diagnosis, exercise coaching, review) based on context, and agents should be able to hand off to each other mid-conversation.

After this task, the user experiences seamless transitions between different "modes" of the agent without the frontend needing to call different endpoints.

## Context

- Current architecture: each route (`/learning-sessions/{id}/messages`, `/reviews/{id}/messages`, `/notes/{id}/agent-draft`) binds to exactly one agent. No routing, no handoffs.
- OpenAI Agents SDK supports `Agent.handoffs` — a list of agents that the current agent can transfer to. The SDK handles the handoff protocol natively.
- The LangGraph state machine doc describes a `route_entry` node that dispatches to subgraphs — this is the designed-but-not-built routing layer.
- Existing specialized agents: `learning_conversation_agent`, `learning_concept_agent`, `exercise_coach_agent`, `review_conversation_agent`, `review_coach_agent`, `note_assist_agent`.
- Dependency: `agent-transition-control` (per-agent transition control must work before cross-agent routing).

## Requirements

### Meta-Agent Router
- Implement a routing agent (or routing logic) that receives user messages and decides which specialized agent should handle them.
- Routing criteria:
  - Current session type and stage
  - User intent (asking a concept question vs requesting practice vs reviewing)
  - Conversation history context
- The router must be fast — it should not add perceptible latency to every message.

### Handoff Protocol
- Use the OpenAI Agents SDK `handoffs` mechanism for agent-to-agent transfers.
- When a specialized agent determines it should hand off (e.g., teaching agent realizes the user needs exercise coaching), it invokes the handoff.
- Handoff must preserve conversation context — the receiving agent gets relevant history.
- Handoff must be transparent to the user — no "please wait while I transfer you" unless the context switch is significant.

### Specialized Agent Boundaries
- Teaching agent: concept introduction, explanation, Socratic dialogue
- Diagnosis agent: identifying misconceptions, assessing understanding, structured judgement
- Exercise coach: hints, error explanation, code review, submission guidance
- Review coach: spaced repetition warmup, recall assessment, review feedback
- Note assistant: summarization, draft generation, content organization

### SSE Compatibility
- Handoffs must not break the SSE stream — the frontend sees a continuous `agent_message` stream regardless of which backend agent is active.
- A new SSE event type `agent_handoff` (optional) can notify the frontend of context switches for UI hints (e.g., changing avatar or tone indicator).
- Existing `tool_call` events continue to work across agent boundaries.

## Acceptance Criteria

- [ ] A routing mechanism exists that dispatches messages to appropriate specialized agents.
- [ ] At least one handoff scenario works end-to-end: teaching agent hands off to exercise coach when user requests practice.
- [ ] Handoff preserves relevant conversation context for the receiving agent.
- [ ] SSE stream is continuous across handoffs — no stream interruption or reconnection needed.
- [ ] Routing adds less than 200ms latency to message processing (measured in test).
- [ ] Each specialized agent can operate independently (no circular dependencies between agents).
- [ ] Existing single-agent flows still work — handoff is additive, not required for basic operation.
- [ ] At least one test demonstrates routing based on session context (not just keyword matching).
- [ ] Frontend requires no changes for basic handoff (optional `agent_handoff` event is additive).

## Out of Scope

- Creating new specialized agents beyond the existing ones (just wiring existing agents into the handoff system).
- Multi-agent concurrent execution (agents take turns, not parallel).
- User-visible agent selection UI.
- Cross-session handoff state (handoffs are within a single session).

## Dependencies

- Requires: `agent-transition-control` (per-agent routing must work before cross-agent routing).
- Enables: `langgraph-migration` (graph nodes map to specialized agents with handoff edges).
- Uses: OpenAI Agents SDK `handoffs` feature.

## Risks

- Routing latency: adding a routing step to every message. Mitigation: router can be a lightweight classifier, not a full LLM call, for obvious cases.
- Context loss during handoff: receiving agent may lack critical context. Mitigation: pass structured summary (from `safe_summary`) plus recent messages.
- Infinite handoff loops: agent A hands to B, B hands back to A. Mitigation: handoff depth limit (max 2 per turn).
