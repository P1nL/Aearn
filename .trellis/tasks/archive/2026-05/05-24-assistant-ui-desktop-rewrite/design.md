# Design

## Boundary

This task is a frontend runtime rewrite under `aearn/apps/desktop/src/`.

It may change:

- `App.tsx`
- `components/`
- `pages/`
- `features/learning/`
- `features/onboarding/`
- `stores/`
- `lib/`
- `styles.css`
- `aearn/package.json` / `aearn/apps/desktop/package.json` only if a new UI dependency is intentionally added

It must not change:

- backend API contracts
- database/schema/FSRS behavior
- runner/evaluation semantics
- protected docs prototype location

## Architecture Direction

```text
AppShell
  SidebarRouteTree
  AssistantLearningPage
    AssistantThread
      AssistantMessage
      ExerciseWorkbenchMessage
    LearningComposer
  NoteDrawer
  ReviewPage
  NotesPage
  SettingsPage
```

## assistant-ui Integration Strategy

Preferred path:

1. Use `assistant-ui` only for the thread/composer interaction layer.
2. Use an external-store/runtime adapter so Aearn keeps ownership of session state and messages.
3. Keep Aearn exercise, notes, review, dashboard, and settings components as product-specific UI.

Fallback path:

- If `assistant-ui` requires Tailwind/shadcn migration that is too disruptive for this MVP, implement an assistant-ui-compatible internal thread/composer shape first, then migrate the visual components later.

## Data Contracts

Message send:

```json
{
  "role": "user",
  "content": "string",
  "client_message_id": "fresh client id"
}
```

Endpoint:

```text
POST /api/learning-sessions/{session_id}/messages
Accept: text/event-stream
```

Consumed events:

- `agent_message`
- `done`
- `error`

## UI Contracts

- The main thread is scrollable independently from app chrome.
- The composer is visible at the bottom of the learning page.
- Exercise workbench appears inside or adjacent to the thread as the current session's generated learning card.
- Assistant messages are real runtime state only.
- Empty states are explicit and honest.

## Risks

- Adding assistant-ui may pull in Tailwind/shadcn conventions that conflict with the current global CSS setup.
- Rewriting too broadly can regress onboarding, notes, review, and settings.
- Existing docs-freshness task changes are present in the worktree and must not be mixed into this implementation commit.
