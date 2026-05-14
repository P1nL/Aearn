# Technical Design

## Scope Boundary

This task refactors only the desktop runtime under `aearn/apps/desktop/src/`.

In scope:

- file/component boundary refactor
- page extraction
- M3 workbench subtree extraction
- helper/constant relocation needed to support the split

Out of scope:

- backend changes
- API contract changes
- router/library/store migration
- visual redesign

## Problem Statement

The current desktop runtime already implements the M3 flow, but `App.tsx` carries too many unrelated responsibilities at once:

- bootstrap and API health
- onboarding inputs and plan confirmation
- learning-session orchestration
- workbench editing / run / submit / hint / explain / explanation-check state
- review / notes / settings presentation
- shell/navigation widgets
- static content and label helpers

This does not match the page and component boundaries defined in `docs/product/frontend-interaction-spec.md`, and it increases the risk of prop drift, state drift, and accidental behavior regressions.

## Options Considered

### Option A: Presentational extraction only

Move JSX blocks to component files but keep nearly all state and handlers in `App.tsx`.

Pros:

- lowest migration risk
- minimal changes to handler wiring

Cons:

- `App.tsx` still remains the real feature owner
- spec alignment is only partial
- future growth will recreate the same bottleneck

### Option B: Shell / page / feature split with current routing model retained

Keep the existing state-driven route model and global CSS, but move page-local behavior into page/feature files and leave `App.tsx` as the host shell.

Pros:

- aligns with current spec and frontend Trellis guidance
- manageable change size
- preserves current runtime and API assumptions

Cons:

- still uses local state routing instead of a formal router
- may require careful prop ownership decisions

### Option C: Full front-end architecture rewrite

Introduce router/store/layout system and reorganize the whole desktop app in one pass.

Pros:

- maximal long-term structure

Cons:

- too large for this task
- high regression risk
- mixes structural refactor with product/platform redesign

## Decision (ADR-lite)

Choose **Option B**.

Reason:

- It directly addresses the user-visible problem: page/feature code should no longer live in one giant file.
- It respects repo conventions that `App.tsx` may remain the shell entry while the UI grows into feature files.
- It avoids turning a structure refactor into a router/store rewrite.

## Target File Shape

Recommended target structure for this task:

```text
aearn/apps/desktop/src/
  App.tsx
  main.tsx
  styles.css
  api.ts
  types.ts
  pages/
    OnboardingPage.tsx
    LearningWorkspacePage.tsx
    ReviewPage.tsx
    NotesPage.tsx
    SettingsPage.tsx
  components/
    SidebarNav.tsx
    NestedNotesGroup.tsx
    SideContext.tsx
    ThreadMessages.tsx
    SystemCard.tsx
    ApiHealthChip.tsx
    ReviewRecap.tsx
  features/
    onboarding/
      PlanDraftPanel.tsx
    learning/
      ExerciseWorkbench.tsx
      RuntimeFeedback.tsx
      HintHistoryCard.tsx
      ErrorFeedbackPane.tsx
      ExplanationCheckPanel.tsx
      SubmissionSummary.tsx
  lib/
    appContent.ts
    desktopLabels.ts
    learningHelpers.ts
```

Exact folder names may be adjusted during implementation if a simpler grouping is cleaner, but the page/feature separation must remain visible in the final tree.

## State Ownership Plan

### `App.tsx` / App shell ownership

`App.tsx` should keep only app-level state and orchestration:

- bootstrap / API health
- current user
- current active route
- shared shell chrome state (sidebar, drawers, settings panel)
- cross-page domain state that must survive route switches:
  - created plan
  - current session lifecycle

### `OnboardingPage` ownership

Move onboarding-local interaction state out of `App.tsx`:

- display name input
- learning mode
- goal/material draft input
- selected course
- plan draft
- onboarding action loading/error state

`OnboardingPage` may receive app-level callbacks such as `ensureUser`, `onPlanConfirmed`, or `onOpenLearningSession`, but it should own the transient draft-editing workflow.

### `LearningWorkspacePage` ownership

Move workbench-local interaction state out of `App.tsx`:

- editor text
- filled blanks
- stale state
- last run / last submit
- hint / explain / explanation-check state
- workbench action loading/error/retry state

This page becomes the owner of the generated exercise flow while still relying on backend APIs and the passed-in session/plan context.

### `ReviewPage`, `NotesPage`, `SettingsPage`

These pages remain lighter, but they should still move into dedicated files so route-level rendering is no longer embedded inside `App.tsx`.

## Shared Utilities and Constants

The following categories should move out of `App.tsx` into pure utility/content files:

- route metadata
- settings panel definitions
- retrospective draft templates
- seeded conversation messages
- display label helpers
- pure learning helpers such as blank initialization or code materialization

Rules:

- pure helpers only
- no hidden React state in utility modules
- reuse `types.ts` domain types instead of inventing parallel model types

## Component Boundaries

`ExerciseWorkbench` should remain the single composition point for the generated code exercise card, but its result subpanels should be separate files:

- `RuntimeFeedback`
- `HintHistoryCard`
- `ErrorFeedbackPane`
- `ExplanationCheckPanel`
- `SubmissionSummary`

This preserves the current runtime contract while matching the spec's nested workbench boundary more closely.

## Styling Strategy

Keep `styles.css` as the single stylesheet for this task.

Rationale:

- structure refactor is the main objective
- CSS system migration would add unnecessary risk
- existing class names can be preserved during extraction to keep rendering stable

## Validation Strategy

Required:

- `pnpm --dir .\aearn desktop:check`

Recommended when behavior risk is high:

- browser smoke of onboarding -> confirm plan -> learning workbench -> run visible tests -> submit

## Rollout / Rollback

Rollout order:

1. extract shared constants/helpers
2. extract shell/shared components
3. extract onboarding page
4. extract learning workspace + M3 workbench subtree
5. extract review/notes/settings pages
6. reduce `App.tsx` to shell orchestration
7. run validation

Rollback:

- if compile or behavior regressions appear, revert the refactor commit as a frontend-only rollback
- no backend or migration rollback is needed because task scope is limited to desktop source files

## Risks

- state reset regressions when session or plan changes
- stale closure bugs in run/hint/submit callbacks
- prop drilling becoming noisy during first extraction pass
- CSS regressions caused by moving markup while reusing global class names
