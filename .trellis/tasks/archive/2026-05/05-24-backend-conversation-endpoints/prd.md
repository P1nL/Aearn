# Backend: Multi-turn Conversation Endpoints

## Goal

Add SSE streaming conversation endpoints for onboarding and review pages so that all three user-facing pages (onboarding, learning, review) support natural multi-turn AI dialogue.

## Background

Currently:
- Learning page has `POST /api/learning-sessions/{session_id}/messages` with full SSE streaming — this is the gold standard.
- Onboarding page uses `POST /api/plans/generate` which is a one-shot JSON call — no multi-turn conversation.
- Review page has no conversation endpoint at all.

The user wants all pages to feel like chatting with an AI that guides them through the task at hand.

## Requirements

### Onboarding Conversation Endpoint

- `POST /api/onboarding/messages` — SSE streaming endpoint for multi-turn onboarding dialogue.
- The agent should:
  - Accept a vague learning goal (e.g., "Python", "C++") and ask follow-up questions to clarify scope, level, time commitment, and focus areas.
  - Accumulate context across turns within the same onboarding session.
  - When enough context is gathered, generate a plan draft and present it in the conversation.
  - Support user confirmation or revision of the draft within the conversation flow.
- Request body: `{ user_id, content, client_message_id, onboarding_session_id? }`
- The endpoint should create an onboarding session on first message if `onboarding_session_id` is null.
- SSE events: same shape as learning messages (`agent_message` with delta/content, `done`, `error`).
- Add a new event type `plan_draft` that carries structured plan data when the agent decides to propose a plan.
- Persist conversation history per onboarding session for context continuity.

### Review Conversation Endpoint

- `POST /api/reviews/{session_id}/messages` — SSE streaming endpoint for review dialogue.
- The agent should:
  - Guide the user through recall before showing the exercise.
  - Provide contextual hints and explanations during review.
  - Give feedback after submission within the conversation flow.
- Request body: `{ content, client_message_id }`
- SSE events: same shape as learning messages.
- Persist conversation history per review session.

### Shared Infrastructure

- Reuse existing `SSEWriter`, `stream_response()`, and `wants_stream()` from `app/services/sse.py`.
- Reuse existing idempotency pattern via `client_message_id`.
- Each new endpoint needs its own agent prompt/persona but shares the streaming infrastructure.
- Add new agent definitions under `app/agents/` for onboarding and review conversation agents.

## Acceptance Criteria

- [ ] `POST /api/onboarding/messages` streams multi-turn responses with proper SSE format.
- [ ] Onboarding agent asks follow-up questions instead of generating a plan immediately.
- [ ] Onboarding conversation persists across multiple requests within the same session.
- [ ] `plan_draft` SSE event is emitted when the agent proposes a plan, carrying structured plan data.
- [ ] `POST /api/reviews/{session_id}/messages` streams multi-turn responses.
- [ ] Review agent provides contextual guidance during the review process.
- [ ] Both endpoints handle idempotency via `client_message_id`.
- [ ] Both endpoints emit `done` and `error` terminal events matching existing SSE contract.
- [ ] Existing learning session messages endpoint remains unchanged.
- [ ] Database schema supports onboarding and review conversation history storage.
- [ ] Both agents produce short conversational responses (1-3 sentences per turn).

## Out of Scope

- Frontend changes (separate task).
- Changing the existing learning session messages endpoint.
- Changing FSRS scheduling or evaluation logic.
- Changing the plan confirmation flow (still needs explicit user confirmation).
