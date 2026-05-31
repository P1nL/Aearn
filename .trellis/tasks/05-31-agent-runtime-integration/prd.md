# Agent Runtime Integration

## Goal

Connect the agent architecture modules that were implemented in `agent-architecture-upgrade` to Aearn's real request paths, one independently verifiable runtime slice at a time.

The previous parent task upgraded the codebase from prompt-only chat toward a full agent architecture. The remaining gap is runtime wiring: several modules exist and are tested, but they are not yet invoked by production routes or conversation services.

## Confirmed Current State

- `structured_judgement.py` is production-wired only through onboarding slot extraction and `onboarding_conversation.py`.
- `sandbox.py` and `sandbox_runner.py` are production-wired through `runtime_runner.py` when `REAL_EXECUTION_ENABLED=true`.
- Agent write-tool definitions exist in `tools.py`, but `learning_sessions.py` does not instantiate or pass `AgentSideEffects` / `LearningToolContext`, so runtime tool construction remains inactive.
- `learner_profile.py`, `teaching_chunks.py` indexing, `router.py`, `learning_graph.py`, and SDK handoffs are implemented and tested as modules, but still need glue code in the actual request chain.

## Child Workflow

Planned implementation order:

| Order | Child | Responsibility | Why First / Dependency |
|---|---|---|---|
| 1 | `cross-page-structured-judgement-integration` | Move non-onboarding LLM judgement points onto shared `StructuredJudgement` policies | Low-risk foundation for safer downstream agent decisions |
| 2 | `learning-agent-side-effects-wiring` | Instantiate `AgentSideEffects` and `LearningToolContext` in learning message routes | Required before write tools can mutate durable state |
| 3 | `learner-profile-runtime-integration` | Ensure, summarize, update, and merge learner profiles across real sessions | Depends on side-effect wiring and judgement observations |
| 4 | `teaching-chunks-indexing-runtime` | Trigger `teaching_chunks` indexing when lesson content is created or updated | Required before retrieval tools can return useful data |
| 5 | `agent-handoff-runtime-routing` | Use `router.py` and SDK handoffs in production conversation routing | Depends on reliable agent context and side-effect boundaries |
| 6 | `langgraph-runtime-rollout` | Introduce `learning_graph.py` behind `LANGGRAPH_ENABLED` for real learning orchestration | Last because it replaces the broadest control-flow surface |

Create future child task directories on demand as each preceding child reaches review/finish. This parent remains the map and integration-review anchor, not the implementation target.

## Requirements

- Each child must prove that the target module is invoked from a production route or service, not only from tests.
- Each child must preserve existing API/SSE event shapes unless its PRD explicitly calls out a contract migration.
- Each child must keep durable writes owned by route/service/repository layers; shared agent helpers may normalize decisions but must not become hidden persistence owners.
- Each child must add tests that fail if the module is disconnected from the real request chain again.
- Each child must keep model failures mapped to safe Aearn errors or deterministic fallbacks; raw provider errors must not leak to users.
- Cross-child changes must not break the first-version baseline contracts for `Attempt`, FSRS scheduling, hidden tests, source attribution, and model failure handling.

## Cross-Child Acceptance Criteria

- [ ] Non-onboarding judgement flows use page-specific `StructuredJudgement` policies, and ambiguous/missing/unsupported judgement outcomes do not advance durable state.
- [ ] Learning conversation write tools are built with real `AgentSideEffects` and `LearningToolContext` from the route layer.
- [ ] Learner profiles are ensured at session start, summarized into agent context, and updated from real observed learning events.
- [ ] Teaching materials are indexed from lesson outline/exercise content before retrieval tools are expected to search them.
- [ ] Router and handoff targets participate in production conversation routing without breaking current endpoint contracts.
- [ ] LangGraph can be enabled by feature flag for a real learning-session path and disabled for rollback.
- [ ] Relevant backend tests, lint, type-check, and Trellis validation pass for each child before archival.

## Out of Scope

- This parent task does not implement production code directly.
- This task does not add new public languages, new exercise types, pricing, auth, or deployment infrastructure.
- This task does not replace all existing deterministic fallbacks at once; children may preserve deterministic fallback paths when they are safer.
