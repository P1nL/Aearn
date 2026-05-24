# Design

## Boundary

This task changes the formal desktop frontend under `aearn/apps/desktop/src/`.

It does not modify:

- `docs/design/learning-agent-claude-desktop-framework.html`
- backend scoring, review scheduling, FSRS, or runner behavior
- unrelated docs freshness cleanup files

## UI Direction

The new direction is a dialogue-first learning workspace:

- Main region: a single conversation thread with the generated exercise card embedded only after a real session starts.
- Bottom region: fixed composer that stays reachable while the thread scrolls.
- Left sidebar: generated route navigator based on `CreatedPlanResponse.knowledge_points`.
- Empty state: calm blank-state guidance instead of fake demo chat.

## Data Flow

```text

Onboarding -> CreatedPlanResponse -> Sidebar generated titles
Sidebar knowledge point click -> POST /api/learning-sessions/start
Learning session ready -> Exercise card + enabled composer
Composer submit -> POST /api/learning-sessions/{session_id}/messages as SSE
SSE agent_message -> update one assistant bubble
SSE done/error -> clear busy state or show recoverable error

```

## Implementation Notes

- Keep `App.tsx` as shell/orchestrator.
- Keep page-local exercise state inside `LearningWorkspacePage`.
- Keep the existing `useSSE` hook for POST streaming because `EventSource` cannot send request bodies.
- Use direct `scrollTop = scrollHeight` on the conversation container, not `scrollIntoView`.
- Avoid hard-coded sample lesson titles in sidebar helpers and navigation components.
- Keep global CSS but rework layout classes so `.conversation` is the scroll container, not the whole app.

## Risks

- The current worktree already contains unrelated docs changes; validation and final reporting must separate them from this frontend task.
- Browser smoke depends on the current backend and Vite processes serving this checkout. If they are not running, use `desktop:check` as the reliable local gate and report the smoke blocker.
