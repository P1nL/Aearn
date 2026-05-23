# Add SDK teaching-agent tools and guardrails

## Goal

Extend the first OpenAI Agents SDK foundation slice by giving the Aearn Teaching Agent safe SDK tools and guardrails while preserving the current learning message API, SSE contract, idempotency behavior, deterministic fallback, and Aearn-owned product state.

This is the next step after `05-23-openai-agents-sdk-foundation`: the SDK should start adding agent-framework value through tools and guardrails, not by taking over Aearn repositories, scoring, review scheduling, or frontend contracts.

## Requirements

- Add Aearn-owned SDK tool definitions under `aearn/services/api/app/agents/`, likely in `tools.py`.
- Tools must be read-only in this task.
- Tools must not write `Attempt`, `LearningSession`, `ReviewState`, `ReviewLog`, `Note`, or `idempotency_records`.
- Tools must not expose hidden test source, hidden case IDs, reference answers, API keys, provider raw errors, raw prompts, or full code submissions.
- The first tool set should focus on the active learning conversation:
  - load/summarize current learning context;
  - load/summarize latest visible attempt facts;
  - optionally load a note summary only if it can be done without broad DB writes or full note leakage.
- Add SDK guardrails or Aearn-side guardrail adapters around the teaching Agent path.
- Guardrails should catch direct-answer leakage, hidden-test leakage, provider-error leakage, and unsafe prompt/request content before data reaches the public API.
- Preserve existing endpoint contracts:
  - `POST /api/learning-sessions/{session_id}/messages`;
  - JSON response fields;
  - SSE `agent_message` and terminal `done`;
  - error event shape;
  - idempotency replay semantics.
- Preserve deterministic fallback when model settings are disabled, incomplete, failing, guardrail-blocked before useful output, or SDK tools/guardrails fail.
- Keep all tests model-key-free using fake SDK runners/tool calls.
- Do not fork, vendor, or modify upstream `openai-agents`.

## Acceptance Criteria

- [ ] `app/agents/tools.py` or equivalent defines read-only Aearn SDK tool wrappers with explicit safe inputs and safe outputs.
- [ ] Teaching Agent wiring can use the tool set without changing public API/SSE response shapes.
- [ ] Guardrail behavior is explicit and tested for hidden test IDs, reference answers, provider raw errors, and direct full-answer leakage.
- [ ] SDK tool or guardrail failures before useful output fall back to deterministic teaching guidance.
- [ ] SDK stream interruption after partial useful output still produces the current recoverable SSE error and does not store a successful idempotency response.
- [ ] No SDK tool writes durable product state.
- [ ] No SDK event names, run items, tool call payloads, or provider error bodies leak to frontend responses.
- [ ] Tests cover fake SDK tool/guardrail behavior without real model credentials.
- [ ] Existing `tests/test_learning_sessions_m3.py` still passes.
- [ ] Full backend pytest still passes before finishing implementation.

## Out Of Scope

- Note Assist Agent implementation.
- Review Coach Agent implementation.
- SDK-managed sessions or durable transcript storage.
- Moving final `evaluate_attempt`, FSRS scheduling, or `ReviewState` writes into SDK tools.
- Frontend UI redesign.
- Real model quality evaluation or live provider smoke.

## Dependencies

- Current task `05-23-openai-agents-sdk-foundation` must remain the foundation: `openai-agents==0.17.3`, `app/agents/sdk_runtime.py`, and `AgentsSDKLearningConversationClient`.
- Backend spec updates in `.trellis/spec/backend/quality-guidelines.md` define the local `TextCompletionClient` boundary and SDK ownership rules.
