# Integrate assistant-ui Generative UI

## Goal

Replace the current custom thread/composer implementation with `@assistant-ui/react`, using its generative UI pattern so that AI tool calls render as interactive React components (learning route, exercise card, submit result, review recall, progress summary) directly within the conversation thread.

## Background

The desktop app currently has a hand-rolled `AssistantThread` + `LearningComposer` that renders `ConversationMessage[]`. Generative UI components already exist as prototypes in `components/generative-ui/` with a `toolUIRegistry`. The backend already emits structured SSE events (`agent_message`, `plan_draft`, `done`, `error`) and the onboarding/review/learning agents are in place.

The missing piece: the thread doesn't render tool-call results as interactive cards. Messages are plain text bubbles. assistant-ui's `makeAssistantToolUI` + `useExternalStoreRuntime` would let us keep Zustand as state owner while rendering tool calls as rich components.

## Requirements

### Frontend Integration

- Install `@assistant-ui/react` and required peer dependencies.
- Decide on styling strategy: either adopt Tailwind (assistant-ui's default) or use the unstyled/headless mode with existing CSS.
- Implement `useExternalStoreRuntime` adapter that bridges the existing Zustand store (`useAppStore`) to assistant-ui's runtime interface.
- Register generative UI tool components via `makeAssistantToolUI` for each tool name in the registry.
- Replace `AssistantThread` and `LearningComposer` with assistant-ui's `<Thread>` and `<Composer>` primitives (or wrap them).
- All three pages (onboarding, learning, review) must use the new thread.

### Backend Changes

- Add new `tool_call` SSE event type with three phases (`start` / `delta` / `done`) for incremental streaming of tool call arguments.
- Tool call names must match the frontend registry: `show_learning_route`, `show_exercise`, `show_submit_result`, `show_review_recall`, `show_progress_summary`.
- Plain text responses remain as `agent_message` events (no tool call needed for conversational text).
- During Slice 1, dual-emit `plan_draft` and `show_learning_route` for backward compatibility; remove `plan_draft` in a follow-up task.
- Persist resolved tool calls in `onboarding_messages.metadata` and `review_messages.metadata` (additive `jsonb` column on `review_messages`) so session resume re-renders cards.
- Add tool result endpoints (`POST /api/onboarding/{id}/tool_result`, `POST /api/sessions/{id}/tool_result`, `POST /api/reviews/{id}/tool_result`) for interactive cards. Extend `role` CHECK constraint to allow `'tool'`.

### Generative UI Components

These prototypes already exist and need to be wired up:
- `LearningRouteCard` — interactive learning route tree with module/KP navigation
- `ExerciseCard` — code editor + blanks + run/test/hint actions
- `SubmitResultCard` — score ring + breakdown + weak points + next action
- `ReviewRecallCard` — recall prompt with confidence buttons
- `ProgressSummaryCard` — progress ring + stats

### Constraints

- Keep Zustand as the single source of truth for session state, messages, and app routing.
- Keep the existing SSE transport (`useSSE` hook with fetch + ReadableStream). Do not switch to WebSocket or EventSource.
- Do not delete the protected HTML prototype.
- The app must remain functional at desktop and narrow widths.
- If Tailwind is adopted, it must coexist with existing CSS without breaking current styles.

## Acceptance Criteria

### Slice 1 (Onboarding + `show_learning_route`)

- [ ] `@assistant-ui/react` installed (pinned version), app builds cleanly in headless mode.
- [ ] `useExternalStoreRuntime` adapter connects Zustand store to assistant-ui runtime.
- [ ] `tool_call` SSE event with `start`/`delta`/`done` phases is parsed correctly; partial JSON renders progressively.
- [ ] `LearningRouteCard` shows skeleton on `pending`, partial content on `running`, full content on `done`.
- [ ] Onboarding flow: AI asks questions → dual-emits `plan_draft` + `show_learning_route` → card renders → user confirms → plan saved.
- [ ] Plain text messages still render as normal assistant/user bubbles.
- [ ] Composer disabled during streaming, enabled otherwise (including while interactive cards are pending).
- [ ] Tool calls persist in `onboarding_messages.metadata`; session resume re-renders the card without replay.
- [ ] `pnpm --dir .\aearn desktop:check` passes.
- [ ] Browser smoke test passes for onboarding flow.

### Slice 2 (Learning + Review + remaining 4 cards)

- [ ] Remaining 4 components (`ExerciseCard`, `SubmitResultCard`, `ReviewRecallCard`, `ProgressSummaryCard`) render in respective threads.
- [ ] Learning flow: AI emits `show_exercise` → user submits → `tool_result` posted → AI emits `show_submit_result`.
- [ ] Review flow: AI emits `show_review_recall` → user responds → `tool_result` posted → exercise card → submit → result card.
- [ ] `show_progress_summary` emits in learning thread after a module completes.
- [ ] Display-only cards (`LearningRouteCard`, `SubmitResultCard`, `ProgressSummaryCard`) trigger frontend side effects only (no `tool_result`).
- [ ] Interactive cards (`ExerciseCard`, `ReviewRecallCard`) post structured results via `POST /api/.../tool_result` and agent stream resumes.
- [ ] Composer placeholder switches contextually (idle / interactive-card-pending / streaming).
- [ ] Tool calls persist in `review_messages.metadata` (after additive column added); session resume re-renders cards.
- [ ] No regression: notes, settings, sidebar navigation, dashboard.
- [ ] `pnpm --dir .\aearn desktop:check` passes.
- [ ] Browser smoke test passes for learning and review flows.

## Out of Scope

- Migrating to a different state management library.
- Changing the backend LLM provider or model.
- Adding new learning features beyond what exists.
- Mobile/responsive redesign (maintain current narrow-width support only).
