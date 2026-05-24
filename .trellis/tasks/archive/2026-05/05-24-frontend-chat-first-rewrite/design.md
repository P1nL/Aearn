# Design

## Boundary

This task modifies frontend code under `aearn/apps/desktop/src/`. It depends on backend endpoints from the `05-24-backend-conversation-endpoints` task.

It may change:
- `pages/OnboardingPage.tsx` — full rewrite to chat-first
- `pages/ReviewPage.tsx` — add composer + thread integration
- `pages/LearningWorkspacePage.tsx` — minor polish (AI greeting)
- `components/AssistantThread.tsx` — add inline card rendering for plan_draft events
- `components/LearningComposer.tsx` — add quick-reply chips slot
- `stores/useAppStore.ts` — add onboarding conversation state
- `hooks/useSSE.ts` — handle new `plan_draft` event type
- `styles.css` — new styles for inline cards and quick-reply chips

It must not change:
- Backend API code
- FSRS scheduling logic
- Protected HTML prototype
- Existing learning session SSE flow

## Architecture

```text
OnboardingPage (chat-first)
  AssistantThread
    InlinePlanCard (rendered when plan_draft event arrives)
  LearningComposer
    QuickReplyChips (optional suggestions)

LearningWorkspacePage (existing, minor polish)
  AssistantThread
  ExerciseWorkbench
  LearningComposer

ReviewPage (add conversation)
  AssistantThread
  ReviewExerciseCard (existing, becomes inline)
  LearningComposer
```

## Onboarding Page Rewrite

Current flow:
```
Form (course select + goal textarea) → "Generate" button → PlanDraftPanel
```

New flow:
```
AI welcome message → User types goal → AI asks questions (SSE) → ... → AI proposes plan (plan_draft event) → InlinePlanCard → User confirms in chat
```

Key changes:
- Remove `PlanDraftPanel` as a separate split-pane
- Remove mandatory form fields (course, mode become optional quick-actions)
- Add SSE streaming via `useSSE` hook connected to `POST /api/onboarding/messages`
- Render plan draft as an inline card component within the thread
- Confirmation happens via a button on the inline card or a chat message

## Review Page Enhancement

Current flow:
```
Due items list → Click "start" → Exercise form → Submit → Static result
```

New flow:
```
Due items list → Click "start" → AI greets + asks recall (SSE) → User responds → AI feedback → Exercise card appears → User works → Submit → AI conversational feedback
```

Key changes:
- Add `LearningComposer` to review page
- Connect to `POST /api/reviews/{session_id}/messages`
- Exercise form becomes an inline card in the thread
- AI messages appear before and after the exercise

## New SSE Event Handling

The `useSSE` hook needs to handle a new event type:

```ts
type SSEPlanDraft = {
  type: "plan_draft";
  data: {
    draft_id: string;
    modules: Array<{ title: string; knowledge_points: Array<{ title: string; id: string }> }>;
    summary: string;
  };
};
```

When this event arrives, the thread renders an `InlinePlanCard` component with confirm/revise actions.

## Quick-Reply Chips

Optional suggestion buttons below the last AI message:
- Onboarding: "就这样生成吧", "我想调整方向", "加入更多细节"
- Review: "我记得", "不太确定", "完全忘了"
- Learning: contextual based on exercise state

These are purely frontend — clicking a chip just fills and submits the composer.
