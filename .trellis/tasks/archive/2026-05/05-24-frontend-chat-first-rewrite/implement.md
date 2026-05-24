# Implementation Plan

## Prerequisites

Backend task `05-24-backend-conversation-endpoints` must be complete, providing:
- `POST /api/onboarding/messages` SSE endpoint
- `POST /api/reviews/{session_id}/messages` SSE endpoint
- `plan_draft` SSE event type

## Phase 1: Shared Components

1. Add `plan_draft` event type to `hooks/useSSE.ts` event parsing.
2. Create `components/InlinePlanCard.tsx` — renders a plan draft as a card within the thread.
3. Add `QuickReplyChips` slot to `LearningComposer.tsx` — optional array of suggestion strings.
4. Update `AssistantThread.tsx` to support rendering inline cards between messages.

## Phase 2: Onboarding Page Rewrite

1. Remove `PlanDraftPanel` import and split-pane layout.
2. Add onboarding conversation state to `useAppStore.ts`:
   - `onboardingSessionId: string | null`
   - `onboardingMessages: ConversationMessage[]`
   - `onboardingPlanDraft: PlanDraft | null`
3. Rewrite `OnboardingPage.tsx`:
   - Full-width thread + composer layout (no split pane).
   - On mount (if no existing session): show AI welcome message locally.
   - Composer sends to `POST /api/onboarding/messages` via `useSSE`.
   - Handle `plan_draft` event: store draft and render `InlinePlanCard` in thread.
   - Confirm button on card calls existing `POST /api/plans` to finalize.
   - Course/mode selection becomes optional chip buttons above composer.
4. Remove or archive `features/onboarding/PlanDraftPanel.tsx`.

## Phase 3: Review Page Enhancement

1. Add review conversation state to `useAppStore.ts`:
   - `reviewMessages: ConversationMessage[]`
2. Add `LearningComposer` to `ReviewPage.tsx`.
3. Connect composer to `POST /api/reviews/{session_id}/messages` via `useSSE`.
4. Restructure review page layout:
   - Thread at top with AI messages.
   - Exercise card rendered inline after AI presents it.
   - Composer at bottom.
5. After submit, AI feedback appears as a new message in the thread.

## Phase 4: Learning Page Polish

1. When session opens, if `initialAgentMessage` exists, render it as a proper `AssistantThread` message (not a separate article element).
2. Add quick-reply chips for common actions (e.g., "给我提示", "解释这个错误").

## Phase 5: Styling

1. Remove `.split-workspace` and `.split-pane` styles (onboarding no longer uses them).
2. Add `.inline-plan-card` styles.
3. Add `.quick-reply-chips` styles.
4. Ensure all three pages have consistent thread/composer spacing.

## Phase 6: Verification

```powershell
pnpm --dir .\aearn desktop:check
```

Browser smoke:
- Onboarding: cold start shows AI welcome → type "Python" → AI asks questions → plan card appears → confirm works.
- Review: start review → AI greets → can chat → exercise appears → submit → AI feedback.
- Learning: existing flow still works, initial message renders in thread.

## Files In Scope

- `aearn/apps/desktop/src/pages/OnboardingPage.tsx` (rewrite)
- `aearn/apps/desktop/src/pages/ReviewPage.tsx` (major changes)
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx` (minor)
- `aearn/apps/desktop/src/components/AssistantThread.tsx` (extend)
- `aearn/apps/desktop/src/components/LearningComposer.tsx` (extend)
- `aearn/apps/desktop/src/components/InlinePlanCard.tsx` (new)
- `aearn/apps/desktop/src/hooks/useSSE.ts` (extend)
- `aearn/apps/desktop/src/stores/useAppStore.ts` (extend)
- `aearn/apps/desktop/src/features/onboarding/PlanDraftPanel.tsx` (remove)
- `aearn/apps/desktop/src/styles.css` (modify)

## Stop Conditions

- If backend endpoints are not ready, stop and wait.
- If removing PlanDraftPanel breaks other flows, investigate before proceeding.
- If styling changes cause regressions in learning page, fix before continuing.
