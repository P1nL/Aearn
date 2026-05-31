# Agent Architecture Upgrade

## Goal

Transform Aearn from a "prompt-engineered chat with deterministic control flow" into a real AI agent system where the LM makes decisions, uses tools to act, and adapts to the learner over time.

Current state: LM generates text, Python if/else controls decisions, tools are read-only, code never executes, no cross-session memory, no retrieval, no multi-agent coordination.

Target state: LM decides what to do next, tools execute real actions (run code, update state, retrieve docs), agent remembers the learner across sessions, and specialized agents collaborate via handoffs.

## Layers and Children

### Layer 1: Let the agent act

| Child | Responsibility | Dependency |
|-------|---------------|------------|
| `shared-structured-judgement-module` | Generic structured judgement schema + normalization policy | None |
| `agent-write-tools` | Give agent tools that mutate state: trigger code execution, create Attempt, update learning_stage, write diagnostic records | `shared-structured-judgement-module` |
| `agent-transition-control` | Replace `_determine_transition` if/else with LM tool-call-based stage routing | `agent-write-tools` |

### Layer 2: Give the agent real capabilities

| Child | Responsibility | Dependency |
|-------|---------------|------------|
| `real-code-execution` | Replace regex-based fake runner with real execution (Pyodide for Python, sandboxed JS eval for browser tier) | Can start in parallel with Layer 1 |
| `agent-persistent-memory` | Cross-session learner profile: weak points, error patterns, preferences, learning pace | `shared-structured-judgement-module` |
| `agent-rag-retrieval` | Vector-indexed teaching materials + retrieval tool, citation grounding | `agent-write-tools` |

### Layer 3: Multi-agent collaboration

| Child | Responsibility | Dependency |
|-------|---------------|------------|
| `agent-handoff-routing` | Meta-agent routes to specialized agents (teaching, diagnosis, exercise design, review coaching) via SDK handoffs | `agent-transition-control` |
| `langgraph-migration` | Implement the designed state machine using the already-installed LangGraph framework | `agent-handoff-routing` |

## Cross-Child Acceptance Criteria

- [ ] After Layer 1: agent autonomously decides stage transitions in at least the learning conversation flow; existing tests pass with updated assertions.
- [ ] After Layer 2: user code actually executes in a sandbox; agent references real execution results in feedback; learner profile persists across sessions.
- [ ] After Layer 3: a single user message can be routed to the appropriate specialized agent without hardcoded endpoint binding.
- [ ] At every layer boundary: existing frontend SSE event contracts are preserved; no breaking changes to `tool_call` / `agent_message` / `runner_result` event shapes.
- [ ] No child introduces database migrations that break other children's work.

## Constraints

- Frontend already handles streaming tool calls, partial JSON, and generative UI cards. Backend changes must emit the same SSE event types and payload shapes.
- OpenAI Agents SDK is already integrated. Prefer extending its capabilities (tools, handoffs, hooks) over replacing it with a different framework until Layer 3.
- Celery + Redis infrastructure exists but is underused. Prefer it for async work (code execution, seed bank generation) over adding new queue systems.
- No auth system exists. Agent capabilities must not expose cross-user data access.
- Code execution sandbox must be secure: no filesystem access, no network, resource-limited.

## Ordering Guidance

- `shared-structured-judgement-module` is ready to start immediately (planning artifacts complete).
- `real-code-execution` can start in parallel with Layer 1 since it's infrastructure, not agent logic.
- All other children should have their own PRD written before starting, informed by the completion state of their dependencies.
- Each child is independently verifiable and committable.

## Out of Scope for Parent

- This parent task does not implement anything directly.
- Individual child PRDs define their own acceptance criteria, design, and implementation plans.
- Product-level decisions (new exercise types, new languages, pricing) are not part of this upgrade.
