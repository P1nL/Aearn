# Technical Design

## Architecture

The MVP should reuse the existing Aearn boundaries instead of introducing a new chat subsystem:

- API route: extend `aearn/services/api/app/routes/learning_sessions.py` with `POST /api/learning-sessions/{session_id}/messages`.
- Request model: add a small Pydantic model near existing learning-session request models, with `role`, `content`, and `client_message_id`.
- Backend service: add a focused learning conversation service, for example `app/services/learning_conversation.py`, that builds the prompt, calls the LLM stream, and provides deterministic fallback.
- LLM boundary: reuse `OpenAICompatibleClient.complete_text_stream`; first verify and adjust its Responses API payload so LatteCode-style providers do not reject unsupported fields.
- SSE boundary: reuse `stream_response`, `sse_event`, and existing event format from `app/services/sse.py`.
- Frontend API boundary: add typed helpers in `aearn/apps/desktop/src/api.ts` for the message endpoint.
- Frontend stream state: reuse or wrap `useSSE.ts`; do not introduce a new data-fetching library.
- UI: wire the existing bottom composer in `App.tsx` to a real backend stream for `home` route active sessions, then pass updated messages into `LearningWorkspacePage`.

## Backend Contract

Endpoint:

```text
POST /api/learning-sessions/{session_id}/messages
Accept: application/json | text/event-stream
Content-Type: application/json
```

Request:

```json
{
  "role": "user",
  "content": "Why does count reset on every click?",
  "client_message_id": "desktop-..."
}
```

JSON response:

```json
{
  "agent_message": {
    "id": "msg_agent_...",
    "role": "assistant",
    "content": "..."
  },
  "session_state": {
    "session_id": "...",
    "next_action": "retry_same",
    "current_stage": "..."
  },
  "generation_source": "llm"
}
```

SSE response:

```text
event: agent_message
data: {"request_id":"...","session_id":"...","message_id":"...","delta":"...","content":"..."}

event: done
data: {"request_id":"...","session_id":"...","message_id":"...","generation_source":"llm"}
```

On validation/session errors in SSE mode, return an SSE `error` event rather than a partial assistant response. On provider failures after validation, return a deterministic assistant message and mark `generation_source=deterministic`.

## Prompt And Safety Boundary

The prompt should include only safe learning context:

- current knowledge point title and stage;
- current exercise title/prompt/starter code if available;
- latest visible run or submit summary if available;
- learner message content.

It must not include hidden test source, hidden case IDs, API keys, provider raw errors, or reference answers. If the user asks directly for a solution, the assistant should explain the concept and suggest the next debugging step without giving away hidden tests or final answers.

## Idempotency

Use `client_message_id` and `session_id` as the logical replay key. Recommended first implementation:

- Store completed JSON response in `idempotency_records` after the full assistant text is available.
- For SSE replay, it is acceptable in V1 to stream the stored completed text as one `agent_message` followed by `done`.
- If implementation finds existing helpers make this too risky, keep replay deterministic and document the limitation in the task before starting.

Do not add a durable `conversation_messages` table unless the new session decides durable history is required. The current schema does not have one.

## Frontend Flow

1. User types in the existing composer on `home`.
2. If there is no active learning session, show disabled guidance or a local agent message.
3. On send, append a user `ConversationMessage` immediately.
4. Append an assistant placeholder message with empty text and streaming status.
5. Start POST SSE to `/api/learning-sessions/{session_id}/messages`.
6. For each `agent_message.delta`, append to the same assistant bubble.
7. On `done`, mark the bubble complete and clear the busy state.
8. On `error` or incomplete stream, show a visible recoverable error message and let the user retry.

The current `ConversationMessage` type may need an optional status field such as `status?: "streaming" | "error" | "done"` so the UI can show a streaming cursor or error copy.

## Compatibility Notes

- V1 uses SSE only. Do not introduce WebSocket.
- Existing `useSSE` uses `fetch` + `ReadableStream`, which is correct for POST bodies.
- Keep local deterministic fallback so default tests and dev environments do not require a real API key.
- Keep secrets process-local or in ignored `.env`; never write the real key into docs or tracked files.

## Risks

- `complete_text_stream` currently includes `temperature`. LatteCode Responses API may reject it. Fix and test this before relying on the live stream.
- Streaming state can duplicate messages if request IDs are reused. Generate fresh IDs per send.
- If the stream ends without `done`, the frontend must not leave the assistant bubble looking successful.
- Adding durable message storage can expand the task. Avoid unless needed for acceptance.
