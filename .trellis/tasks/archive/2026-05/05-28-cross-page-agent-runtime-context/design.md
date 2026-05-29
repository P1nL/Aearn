# Reusable Agent Runtime Context Layer Design

## Decision

Aearn should reuse the design pattern of `pi-agent-core`, not the package implementation.

`pi-agent-core` is valuable here because it separates app messages from LLM-ready messages through a context transform layer. Aearn should implement the same architectural boundary in Python on top of the existing OpenAI Agents SDK integration:

```text
Aearn domain state/messages
  -> domain context loader
  -> safe context transform
  -> summary + recent context block
  -> domain response policy
  -> Agents SDK client
  -> guardrail + schema validation
  -> existing API/SSE contract
```

## Existing Architecture

Current reusable pieces:

- `aearn/services/api/app/agents/sdk_runtime.py`
  - `AgentsSDKRunner`
  - `build_agent`
  - `stream_text_deltas`
  - `iter_streamed_text`
  - provider normalization and tracing disabled by default
- `aearn/services/api/app/agents/guardrails.py`
  - hidden/reference/provider/API-key/direct-answer checks
  - SDK input/output guardrail builders
- Domain-specific SDK clients:
  - `learning_conversation_agent.py`
  - `onboarding_plan_agent.py`
  - `review_coach_agent.py`
  - existing note/exercise agents as adjacent consumers

First-phase target domains are learning, onboarding/build-plan, and review. Note Assist stays out of the first implementation and can be migrated after the shared runtime/context layer proves stable.

Current duplication/risk:

- Learning page owns its own safe summary pipeline in `learning_conversation.py`.
- Onboarding and review agents build their own prompt/context shapes directly.
- Guardrail and fallback conventions are mostly shared by tests/specs, but not expressed as a reusable context abstraction.
- Adding continuity to onboarding/review would likely duplicate learning-page helper logic if no shared layer is introduced.

## Proposed Modules

First-pass module shape under `aearn/services/api/app/agents/`:

```text
agent_runtime_context.py
agent_domain_contexts.py
agent_context_summaries.py
```

Possible responsibilities:

- `agent_runtime_context.py`
  - generic dataclasses/protocols:
    - `AgentRuntimeContext`
    - `AgentDomainPolicy`
    - `SafeMessage`
    - `SummaryState`
    - `ContextRefreshDecision`
  - shared recent-message selection interface
  - shared forbidden-token sanitization helpers
  - shared refresh decision helpers
- `agent_context_summaries.py`
  - LLM summary generation wrapper
  - deterministic fallback summary wrapper
  - summary output validation
  - JSON extraction / normalization helpers
- `agent_domain_contexts.py`
  - domain-specific adapters for:
    - learning conversation
    - onboarding route/plan generation
    - review coach

Exact file split can change during implementation if neighboring code suggests a smaller shape.

## Shared Pipeline

The shared layer should implement this lifecycle:

1. Load domain-owned facts from existing repositories/services.
2. Convert facts/messages into bounded safe context.
3. Decide whether summary refresh is needed.
4. Generate or fallback summary.
5. Persist summary only through domain-owned persistence hook.
6. Build a domain-specific `runtime_context` block.
7. Build the SDK input messages.
8. Run SDK client.
9. Validate/guard output.
10. Return normalized result to the existing service/route.

The shared layer must not own durable product writes. Persistence should be injected as domain callbacks or remain in current services.

## Domain Context Shapes

### Learning Page

Reuse and eventually extract the current learning summary:

```json
{
  "safe_summary": {
    "learning_goal": "",
    "current_stuck_point": "",
    "misconceptions": [],
    "concepts_explained": [],
    "examples_used": [],
    "last_diagnosis": "",
    "last_agent_strategy": "",
    "avoid_repeating": [],
    "recommended_next_step": "",
    "summary_confidence": "low|medium|high"
  },
  "recent_safe_messages": []
}
```

Learning policy remains concept-first and diagnosis-first. It must not leak complete exercise answers, starter code in concept stages, hidden tests, reference answers, raw prompts, provider errors, or API keys.

### Onboarding / Build-Plan Page

Introduce an onboarding-specific continuity block:

```json
{
  "safe_summary": {
    "goal_text": "",
    "language": "",
    "target_level": "",
    "time_budget": "",
    "known_preferences": [],
    "missing_slots": [],
    "rejected_directions": [],
    "current_plan_draft_status": "",
    "recommended_next_question": "",
    "summary_confidence": "low|medium|high"
  },
  "recent_safe_messages": []
}
```

Onboarding policy must keep server-owned course templates, runtime boundaries, and `PlanDraft` validation authoritative. The Agent may clarify, rank, or explain, but must not invent unsupported course/runtime promises.

### Review Page

Introduce a review-specific continuity block:

```json
{
  "safe_summary": {
    "review_goal": "",
    "due_reason": "",
    "weak_points": [],
    "latest_visible_attempt_facts": [],
    "variant_rationale": "",
    "recommended_review_strategy": "",
    "summary_confidence": "low|medium|high"
  },
  "recent_safe_messages": []
}
```

Review policy must keep FSRS, due ordering, `ReviewState`, `ReviewLog`, and `Attempt(review_submit)` writes outside SDK ownership. The Agent may explain why this review matters and how to approach it, but cannot change scheduling/scoring.

## Persistence Strategy

First version should avoid broad migrations.

- Learning page can keep using `learning_sessions.learning_stage_state_json.conversation_summary`.
- Onboarding continuity should prefer existing onboarding conversation/session metadata if present; if no suitable durable field exists, the first implementation can keep only bounded recent safe context and defer persistent onboarding summary.
- Review continuity should prefer per-review session state if present; if no suitable durable field exists, the first implementation can summarize from due review facts and latest visible attempt without persisting a new summary.

If implementation discovers that onboarding/review continuity needs durable summary to satisfy acceptance criteria, add a dedicated design update before creating a migration.

## API Compatibility

Must remain unchanged:

- `POST /api/learning-sessions/{session_id}/messages`
- `POST /api/plans/generate`
- `POST /api/reviews/start`
- `POST /api/reviews/{session_id}/exercise-result`
- Existing JSON fields, SSE event names, terminal `done`, and error shape
- `MODEL_UNAVAILABLE` behavior for model unavailable, invalid output, guardrail blocked, empty stream, or unsafe result

No public response may expose:

- SDK event names or run items
- raw prompt or system prompt
- provider raw errors
- API keys or key-like tokens
- hidden test IDs/source/assertions
- `solution_reference` / reference answer / full answer

## Trade-Offs

- Shared layer improves consistency, but can become too abstract if it hides domain policy. Mitigation: keep domain adapters explicit and require domain-specific tests.
- Persisting summaries improves continuity, but can create schema churn. Mitigation: reuse existing state JSON first and defer migrations.
- Refactoring learning page first is lower risk because it already has summary plumbing. Onboarding/review should migrate after the shared extraction proves no behavior regression.

## Rollback Shape

- Keep existing domain SDK clients callable without the shared layer until each migration passes.
- Refactor learning page in a small commit; if it regresses, revert extraction while preserving current prompt/context behavior.
- Onboarding and review migrations should be independent. A failure in one domain must not require rolling back the shared primitives or the other domain.
