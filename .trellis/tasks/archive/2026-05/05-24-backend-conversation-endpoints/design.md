# Design

## Boundary

This task adds new route files and agent definitions under `aearn/services/api/app/`. It also adds a database table for onboarding conversation history.

It may change:
- `app/routes/` — new route files
- `app/agents/` — new agent definitions
- `app/services/` — new conversation service modules
- `app/db/schema.sql` — new table for onboarding conversations
- `app/main.py` — register new routers

It must not change:
- Existing learning session messages endpoint behavior
- FSRS scheduling logic
- Plan confirmation semantics (still requires explicit confirm)
- Frontend code

## Architecture

```text
Routes Layer
  POST /api/onboarding/messages  →  OnboardingConversationService  →  OnboardingAgent (LLM)
  POST /api/reviews/{id}/messages  →  ReviewConversationService  →  ReviewAgent (LLM)

Shared Infrastructure (existing)
  SSEWriter / stream_response / wants_stream
  llm_client (streaming HTTP to LLM provider)
  idempotency check via client_message_id
```

## New Database Tables

### `onboarding_conversations`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK to users |
| created_at | TIMESTAMPTZ | |
| status | TEXT | 'active', 'plan_proposed', 'confirmed', 'abandoned' |
| extracted_context | JSONB | Accumulated user preferences extracted by agent |

### `onboarding_messages`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| conversation_id | UUID | FK to onboarding_conversations |
| role | TEXT | 'user' or 'agent' |
| content | TEXT | Message text |
| client_message_id | TEXT | For idempotency |
| created_at | TIMESTAMPTZ | |
| metadata | JSONB | Optional structured data (e.g., plan_draft payload) |

### `review_messages`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| review_session_id | UUID | FK to review_sessions (existing) |
| role | TEXT | 'user' or 'agent' |
| content | TEXT | |
| client_message_id | TEXT | |
| created_at | TIMESTAMPTZ | |

## Agent Design

### Onboarding Agent

System prompt instructs the agent to:
1. Greet the user and ask what they want to learn.
2. Ask 2-4 follow-up questions (one per turn) about: level, time budget, focus areas, prior experience.
3. When sufficient context is gathered, emit a `plan_draft` event with structured data AND a conversational summary.
4. If the user wants changes, iterate on the draft.

The agent receives the full conversation history as context on each turn.

### Review Agent

System prompt instructs the agent to:
1. Present the knowledge point title and ask the user to recall the concept.
2. After user responds, provide feedback on their recall accuracy.
3. Present the exercise with contextual guidance.
4. During the exercise, answer questions and provide Socratic hints.
5. After submission, give conversational feedback on the result.

The agent receives: conversation history + review session context (knowledge point, exercise, attempt results).

## SSE Event Types

Both new endpoints emit the same event types as learning messages:
- `agent_message` — `{ delta, content, message_id, request_id, session_id }`
- `done` — `{ request_id, session_id, result_ref }`
- `error` — `{ code, message, recoverable, next_action }`

Additionally, the onboarding endpoint can emit:
- `plan_draft` — `{ draft_id, modules: [...], summary }` — structured plan data for the frontend to render.

## Risks

- Onboarding agent might ask too many questions and feel tedious. Mitigation: cap at 4 questions, allow user to say "just generate it" to skip.
- Review agent context window could grow large with exercise code + conversation. Mitigation: summarize prior turns after 10 messages.
- Adding new tables requires running bootstrap again. Document in implementation plan.
