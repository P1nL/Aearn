# Frontend: Chat-first UI Rewrite

## Goal

Rewrite onboarding, learning, and review pages so that the primary interaction on every page is a natural AI conversation. Forms and controls become secondary — the user talks to the AI, and the AI guides them through each task.

## Background

Current state:
- **Onboarding page**: Form-driven (select course → fill goal → click "generate"). No multi-turn conversation.
- **Learning page**: Has composer + SSE streaming, but only activates after session open. Empty state is passive text.
- **Review page**: No composer at all. Pure mechanical flow (see exercise → fill blanks → submit).

Target state: Every page has a chat thread + composer as the primary UI. The AI initiates, asks questions, and guides the user. Forms/controls appear inline or as secondary panels when needed.

## Requirements

### Onboarding Page

- Replace the form-first flow with a chat-first flow.
- On first load, show an empty thread with a welcome message from the AI asking what the user wants to learn.
- User types a vague goal (e.g., "Python") into the composer.
- AI responds with follow-up questions (streamed via SSE from `POST /api/onboarding/messages`).
- Multi-turn conversation continues until the AI proposes a plan.
- When a `plan_draft` SSE event arrives, render the plan as a structured card in the thread (not a separate panel).
- User can confirm or ask for changes within the conversation.
- Course selection and mode selection become optional quick-action buttons above the composer, not mandatory form fields.
- Remove the split-pane layout; the plan draft panel becomes an inline card in the thread.

### Learning Page

- AI should send an initial greeting message when a session opens (not just a static `initialAgentMessage` string).
- Composer should feel responsive: instant local echo of user message, streaming indicator on assistant bubble.
- Exercise workbench remains but is visually integrated as a card within or adjacent to the thread.
- No changes to SSE endpoint (already works).

### Review Page

- Add a composer + thread to the review page.
- On review start, AI greets the user and asks them to recall the concept before showing the exercise.
- User can ask questions during the review via the composer (streamed via `POST /api/reviews/{session_id}/messages`).
- After submission, AI provides conversational feedback in the thread.
- Exercise form remains but is secondary to the conversation.

### Shared UX Patterns

- All pages use the same `AssistantThread` + `LearningComposer` components (already exist).
- Streaming indicator: typing dots or cursor animation while AI is generating.
- Quick-reply suggestions: optional chip buttons below the last AI message for common responses.
- Composer disabled state: clear guidance text when the user can't send (e.g., "等待 AI 回复中…").
- Auto-scroll to latest message on new content.

## Acceptance Criteria

- [ ] Onboarding page starts with an AI welcome message and composer, not a form.
- [ ] User can complete onboarding entirely through conversation (no mandatory form fields).
- [ ] Plan draft renders as an inline card in the onboarding thread when `plan_draft` event arrives.
- [ ] User can confirm or revise the plan within the conversation.
- [ ] Review page has a working composer connected to `POST /api/reviews/{session_id}/messages`.
- [ ] Review AI greets user and guides recall before showing exercise.
- [ ] All three pages use consistent thread/composer UX.
- [ ] Streaming works on all pages: deltas update one bubble, no duplicate sends.
- [ ] Quick-reply suggestion chips appear below AI messages where appropriate.
- [ ] `pnpm --dir .\aearn desktop:check` passes.
- [ ] No prototype fallback content or hard-coded messages remain.

## Dependencies

- Backend task `05-24-backend-conversation-endpoints` must provide:
  - `POST /api/onboarding/messages` endpoint
  - `POST /api/reviews/{session_id}/messages` endpoint
  - `plan_draft` SSE event type

## Out of Scope

- Backend endpoint implementation (separate task).
- Changing FSRS scheduling or evaluation logic.
- Changing the protected HTML prototype.
- Adding new npm dependencies (use existing component patterns).
