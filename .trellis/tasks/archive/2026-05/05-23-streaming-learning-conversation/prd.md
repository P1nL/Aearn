# Implement streaming learning conversation

## Goal

Add the missing end-to-end model-backed streaming conversation path for the Aearn desktop learning workspace. The current MVP can start, run exercises, submit, and call `explain-error`, but the bottom composer still appends local canned messages instead of streaming an assistant response from the configured model.

The first useful user value is narrow: while an active learning session is open, the learner can type a follow-up question in the existing composer and see the assistant answer arrive incrementally in the conversation timeline.

## Confirmed Facts

- `docs/architecture/api-contract.md` already defines `POST /api/learning-sessions/{session_id}/messages` for learning conversation messages, with SSE support through `Accept: text/event-stream`.
- V1 transport must remain SSE, not WebSocket.
- Backend already has SSE helpers in `aearn/services/api/app/services/sse.py`.
- Frontend already has a POST-capable SSE hook in `aearn/apps/desktop/src/hooks/useSSE.ts`.
- Frontend `App.tsx` currently handles composer submit by appending a user message and a canned local agent message.
- `LearningWorkspacePage` renders a local `messages` array through `ThreadMessages`; it does not currently stream or mutate an in-flight assistant bubble.
- `OpenAICompatibleClient.complete_text_stream` exists, but it currently sends `temperature`; LatteCode-style Responses API providers may reject unsupported parameters, so this path needs a compatibility check.
- No durable conversation-message table exists in the current schema. Existing idempotency support is in `idempotency_records`.

## Requirements

- Implement `POST /api/learning-sessions/{session_id}/messages`.
- Support both normal JSON response and SSE response selected by `Accept: text/event-stream`.
- In SSE mode, emit one or more `agent_message` events and finish with exactly one terminal `done` event, or an `error` event on recoverable failure.
- Use the configured OpenAI-compatible model when LLM settings are complete.
- Fall back to a deterministic assistant response when LLM settings are disabled, incomplete, timeout, or return an invalid stream.
- Do not return provider raw errors, API keys, hidden test source, hidden case IDs, or reference answers to the frontend.
- Keep the feature scoped to the active learning session; do not add a global chatbot or account-wide memory in this task.
- Preserve existing run, submit, hint, explain-error, check-explanation, notes, and review flows.
- Frontend must use the existing composer for learning-session messages when `visibleRoute === "home"` and a session is active.
- Frontend must render the assistant response incrementally in the existing conversation timeline instead of waiting for the final text.
- Frontend must show a visible streaming/loading/error state and prevent duplicate sends while one response is in flight.
- Frontend must generate a fresh `client_message_id` / `X-Request-Id` per send.
- If no active session exists, the composer should keep a clear disabled or local guidance state rather than calling the message API.
- Tests must not require a real third-party API key by default; mock streaming and fallback paths.

## Acceptance Criteria

- [ ] Backend test covers JSON success for `POST /api/learning-sessions/{session_id}/messages`.
- [ ] Backend test covers SSE success with ordered `agent_message` delta events and terminal `done`.
- [ ] Backend test covers missing session / invalid request behavior for JSON and SSE modes.
- [ ] Backend test covers LLM-disabled or LLM-failure fallback without leaking provider details.
- [ ] Backend test or unit test covers Responses API streaming payload compatibility, including avoiding provider-unsupported `temperature` where needed.
- [ ] Frontend build passes with `pnpm --dir .\aearn desktop:check`.
- [ ] Frontend learning composer sends to the real backend when an active learning session exists.
- [ ] Frontend appends the user message immediately, then progressively updates one assistant bubble as deltas arrive.
- [ ] Frontend shows an error bubble or card if the stream closes without `done` / `error`.
- [ ] Existing manual smoke path still works: onboarding -> start learning session -> run visible tests -> explain-error -> submit.
- [ ] No secrets are written to tracked files, logs, task docs, or UI diagnostics.

## Out of Scope

- WebSocket transport.
- Persistent full chat history / memory beyond the minimal request and replay behavior needed for MVP.
- General chatbot outside an active learning session.
- Review-page streaming conversation, unless it falls out as a safe reuse with no added backend scope.
- Streaming final scoring or changing `run` / `submit` semantics.
- OpenAPI generation.

## Open Questions For Next Session

- Default recommendation: implement only the active learning workspace first. If the user explicitly wants review-page chat too, split it into a follow-up task.
- Decide during implementation whether `idempotency_records` is enough for `client_message_id` replay. Do not add a new messages table unless a real acceptance criterion requires durable history.
