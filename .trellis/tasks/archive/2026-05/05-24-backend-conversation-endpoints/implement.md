# Implementation Plan

## Phase 1: Database Schema

1. Add `onboarding_conversations` and `onboarding_messages` tables to `app/db/schema.sql`.
2. Add `review_messages` table to `app/db/schema.sql`.
3. Verify bootstrap runs cleanly: `uv --directory .\aearn\services\api run python -m app.db.bootstrap`

## Phase 2: Onboarding Conversation Service

1. Create `app/services/onboarding_conversation.py`:
   - `create_onboarding_session(user_id)` — creates a new conversation record.
   - `prepare_onboarding_message(conversation_id, user_content, client_message_id)` — idempotency check + history load.
   - `build_onboarding_message_response(conversation_id, agent_content, metadata)` — persist agent response.
   - `get_onboarding_history(conversation_id)` — load conversation for agent context.
2. Create `app/agents/onboarding_conversation_agent.py`:
   - Define system prompt for multi-turn onboarding dialogue.
   - Implement `start_onboarding_generation(context, user_content)` returning a streaming chunks iterator.
   - Include plan-draft detection logic (agent signals readiness via structured output or tool call).

## Phase 3: Onboarding Route

1. Create `app/routes/onboarding.py`:
   - `POST /api/onboarding/messages` — SSE streaming endpoint.
   - Request body: `{ user_id, content, client_message_id, onboarding_session_id? }`
   - If `onboarding_session_id` is null, create a new session and return its ID in the first event.
   - Stream agent response using existing `SSEWriter` + `stream_response()`.
   - Emit `plan_draft` event when agent proposes a plan.
2. Register router in `app/main.py`.

## Phase 4: Review Conversation Service

1. Create `app/services/review_conversation.py`:
   - `prepare_review_message(session_id, user_content, client_message_id)` — idempotency + history.
   - `build_review_message_response(session_id, agent_content)` — persist.
   - `get_review_context(session_id)` — load review session + knowledge point + conversation history.
2. Create `app/agents/review_conversation_agent.py`:
   - Define system prompt for Socratic review dialogue.
   - Implement `start_review_generation(context, user_content)` returning streaming chunks.

## Phase 5: Review Route

1. Add `POST /api/reviews/{session_id}/messages` to `app/routes/reviews.py`.
2. Same SSE streaming pattern as onboarding.

## Phase 6: Verification

```powershell
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Manual test with curl:
```powershell
curl -X POST http://127.0.0.1:8001/api/onboarding/messages -H "Content-Type: application/json" -H "Accept: text/event-stream" -d '{"user_id": "<test_user_id>", "content": "Python", "client_message_id": "test_1"}'
```

## Files In Scope

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/routes/onboarding.py` (new)
- `aearn/services/api/app/routes/reviews.py` (modify)
- `aearn/services/api/app/services/onboarding_conversation.py` (new)
- `aearn/services/api/app/services/review_conversation.py` (new)
- `aearn/services/api/app/agents/onboarding_conversation_agent.py` (new)
- `aearn/services/api/app/agents/review_conversation_agent.py` (new)
- `aearn/services/api/app/main.py` (register new router)

## Stop Conditions

- If the LLM provider API changes or is unavailable, stop and document.
- If schema changes break existing bootstrap, fix before proceeding.
- If existing learning session tests fail after changes, investigate before continuing.
