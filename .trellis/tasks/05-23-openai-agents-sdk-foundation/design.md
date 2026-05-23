# Technical Design

## Decision Frame

OpenAI Agents SDK can be used as the Agent framework foundation for Aearn, but the safest version is to build an Aearn-owned application on top of the SDK rather than modifying SDK internals.

The earlier adapter-first design is no longer the full target. The user has selected the `application-on-SDK` foundation mode:

1. Aearn depends on `openai-agents` as an upstream framework.
2. Aearn-owned modules define the programming-language learning Agent application.
3. SDK primitives power model loops, tools, guardrails, handoffs, streaming, and optional tracing/sessions.
4. Aearn remains owner of product APIs, database state, deterministic runner, grading, review scheduling, and frontend contracts.

## Target Architecture

```text
Desktop UI
  -> Aearn FastAPI product API
  -> Aearn learning-agent application services
  -> OpenAI Agents SDK primitives
       - Agent
       - Runner
       - function tools
       - guardrails
       - optional sessions/tracing
  -> OpenAI or compatible provider
  -> Aearn repositories for durable product state
```

In the recommended direction, Aearn owns product APIs, data model, grading rules, review scheduling, and UI contracts. The SDK owns model loop execution, tool orchestration, guardrails, and optional handoffs.

## Foundation Modes

### Application-on-SDK

This is the selected path.

- Add `openai-agents` as a dependency.
- Create Aearn-specific Agent modules under `aearn/services/api/app/agents/` or `app/services/agent_runtime/`.
- Implement learning-specific agents such as `TeachingAgent`, `HintAgent`, `NoteAssistAgent`, and later `ReviewCoachAgent`.
- Wrap Aearn read-only context functions as SDK function tools.
- Keep durable writes in Aearn repositories.
- Keep upstream SDK unmodified.

### SDK-primary inside current repo

This path is deferred. It goes further than application-on-SDK by moving more Aearn flow orchestration directly into SDK runs.

- Gradually make SDK `Agent` / `Runner` the main orchestration layer for selected flows.
- Aearn tools can call repositories and runner services through well-defined wrappers.
- This needs stronger contract tests because SDK run items and Aearn API events must be mapped carefully.

### Upstream fork

This path is rejected for the current MVP.

- It would modify SDK internals directly.
- Every upstream SDK update becomes a merge task.
- Aearn product code risks being mixed with generic SDK code.
- This is only justified if Aearn needs framework capabilities that cannot be built through public SDK extension points.

## Candidate Integration Points

### First spike: learning conversation messages as an Aearn Agent

Best first slice:

- `POST /api/learning-sessions/{session_id}/messages`
- Existing worktree changes already define a streaming learning conversation route and `TextCompletionClient` protocol.
- This path is user-visible but lower risk than `submit` or FSRS updates because it does not own final scoring.
- This slice must be sequenced after, or deliberately layered on top of, `05-23-streaming-learning-conversation`, because that active task already touches the same route/service area.

The SDK can provide an Aearn-specific teaching Agent:

- a single teaching `Agent`;
- streaming text;
- optional guardrails;
- later tool calls for safe context loading;
- a path toward multi-agent learning flows without changing frontend contracts immediately.

Aearn should still own in the first framework slice:

- session lookup;
- prompt context assembly;
- idempotency;
- SSE event framing;
- deterministic fallback;
- storage of replay response in `idempotency_records`.

### Later candidate: note assist

`POST /api/notes/{note_id}/agent-draft` can use the same adapter once the first spike is stable.

### Not first: final evaluation and review state

Do not move `evaluate_attempt`, `ReviewState`, FSRS, or `Attempt` write timing into SDK-managed state in the first migration. These are core Aearn contracts and must remain testable without model calls.

## SDK Usage Shape

Create Aearn-owned modules such as:

```text
aearn/services/api/app/agents/learning_conversation_agent.py
aearn/services/api/app/agents/sdk_runtime.py
aearn/services/api/app/agents/tools.py
```

Recommended responsibilities:

- create configured SDK `Agent` instances for Aearn learning use cases;
- run `Runner.run_streamed()` or `Runner.run()` behind Aearn's local client protocol;
- normalize SDK exceptions into Aearn `LLMCallError` / `LLMInvalidResponseError`;
- disable tracing by default when no platform OpenAI key is configured for trace export;
- avoid SDK sessions at first unless a later requirement needs SDK-managed transcript memory.

Avoid:

- storing Aearn product state in SDK session storage;
- exposing SDK run items directly through API responses;
- letting SDK tools write `Attempt`, `ReviewState`, or `LearningSession` without Aearn repository validation;
- making frontend depend on SDK event names.

## Provider Compatibility

OpenAI-only path:

- Use the SDK default Responses model path.
- Prefer explicit model settings rather than relying on SDK defaults for production behavior.

OpenAI-compatible provider path:

- Validate whether the provider supports Responses API streaming.
- If not, use SDK Chat Completions model support or keep the current `OpenAICompatibleClient` for that provider.
- Disable SDK tracing or configure a dedicated trace processor when the provider key is not a platform OpenAI key.
- Do not assume structured outputs work across third-party providers.

This task should produce a provider matrix before implementation starts:

| Provider type | Expected SDK path | Risk |
|---|---|---|
| OpenAI platform | Default Responses model | Low |
| Responses-compatible proxy | Default or custom OpenAI client | Medium |
| Chat-Completions-only provider | `OpenAIChatCompletionsModel` or current client | Medium |
| Provider without structured output | Current client + validation/fallback or no SDK | High |

## Data Flow

Learning conversation spike:

1. API validates request and session.
2. Aearn service loads safe learning context.
3. Aearn service calls `TextCompletionClient.complete_text_stream()`.
4. SDK-backed client streams deltas.
5. API converts deltas to current Aearn SSE `agent_message` events.
6. API sends terminal `done`.
7. Aearn stores replay response using existing idempotency key.

The SDK never directly writes DB state in this slice.

## Contracts To Preserve

- API response shapes in `docs/architecture/api-contract.md`.
- SSE event names and `done` terminal behavior.
- No hidden test source, hidden case IDs, reference answers, provider raw errors, or API keys in output.
- Deterministic fallback when model config is disabled/incomplete/fails.
- Tests must pass without real model credentials.
- `run` and `submit` semantics remain unchanged.
- `ReviewState` changes happen only through existing learning/review submit flows.

## Trade-Offs

Application-on-SDK:

- Pros: treats the SDK as the foundation framework while preserving Aearn product ownership and upstream update path.
- Cons: still requires mapping SDK abstractions to Aearn contracts.
- Decision: selected.

Adapter-first:

- Pros: lowest risk, compatible with current tests, easy rollback.
- Cons: may feel too shallow if the product goal is to build around SDK primitives.
- Decision: still useful as the first implementation slice inside application-on-SDK, but not the full product architecture.

SDK-primary selected flows:

- Pros: clearer use of SDK tools/guardrails/handoffs for agentic flows.
- Cons: needs more contract mapping and more careful failure handling.
- Decision: viable later phase if application-on-SDK spike is successful.

Upstream fork / broad replacement:

- Pros: maximum alignment with SDK primitives.
- Cons: high migration risk, broad test churn, SDK maintenance burden.
- Decision: not recommended for the current MVP.

## Rollback Shape

- Keep the current `OpenAICompatibleClient` path intact until the SDK path is verified.
- Add config-gated or constructor-injected SDK clients so tests can choose deterministic/fake clients.
- If SDK streaming breaks provider compatibility, revert only the SDK adapter and keep the route/service API unchanged.
- Do not remove LangGraph or existing LLM client dependencies until after a dedicated removal task.

## Final Planning Decision

This task will implement Aearn as an application-on-SDK. The recommended first slice remains a learning conversation Agent, framed as the first Aearn-owned SDK-based learning-agent module rather than as a generic LLM adapter.
