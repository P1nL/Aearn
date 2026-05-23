# Technical Design

## Decision Frame

OpenAI Agents SDK should be treated as an Agent runtime library, not as the whole Aearn application framework.

The default design recommendation is adapter-first:

- Keep Aearn's FastAPI routes, database repositories, deterministic runner, FSRS scheduling, evaluation rules, and frontend API contracts as the source of truth.
- Add an SDK-backed client behind Aearn's existing LLM protocols.
- Use SDK features only where they reduce custom orchestration code without taking ownership of durable product state.

## Target Architecture

```text
Desktop UI
  -> FastAPI route
  -> Aearn service/repository
  -> Aearn Agent client protocol
  -> AgentsSdkClient
  -> openai-agents Agent / Runner
  -> OpenAI or compatible provider
```

The SDK layer should be replaceable. Aearn services should depend on local protocols such as `TextCompletionClient` or `JsonCompletionClient`, not directly on SDK global state.

## Candidate Integration Points

### First spike: learning conversation messages

Best first slice:

- `POST /api/learning-sessions/{session_id}/messages`
- Existing worktree changes already define a streaming learning conversation route and `TextCompletionClient` protocol.
- This path is user-visible but lower risk than `submit` or FSRS updates because it does not own final scoring.

The SDK can provide:

- a single teaching `Agent`;
- streaming text;
- optional guardrails;
- later tool calls for safe context loading.

Aearn should still own:

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

Create a new module such as:

```text
aearn/services/api/app/services/agents_sdk_client.py
```

Recommended responsibilities:

- create a configured SDK `Agent` for a specific Aearn use case;
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

Adapter-first:

- Pros: lowest risk, compatible with current tests, easy rollback.
- Cons: slower to adopt SDK handoffs/sessions broadly.

SDK-primary selected flows:

- Pros: clearer use of SDK tools/guardrails/handoffs for agentic flows.
- Cons: needs more contract mapping and more careful failure handling.

Broad replacement:

- Pros: maximum alignment with SDK primitives.
- Cons: high migration risk, broad test churn, unclear benefit for current MVP.

## Rollback Shape

- Keep the current `OpenAICompatibleClient` path intact until the SDK path is verified.
- Add config-gated or constructor-injected SDK clients so tests can choose deterministic/fake clients.
- If SDK streaming breaks provider compatibility, revert only the SDK adapter and keep the route/service API unchanged.
- Do not remove LangGraph or existing LLM client dependencies until after a dedicated removal task.

## Open Design Decision

The key remaining user decision is whether this task should stop at an adapter-first spike or prepare for SDK-primary orchestration in a later phase.
