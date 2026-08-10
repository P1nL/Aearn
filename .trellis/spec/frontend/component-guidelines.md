# Component Guidelines

> How components are built in this project.

---

## Overview

The formal frontend is a Vite + React + TypeScript + Tauri 2 desktop app under `aearn/apps/desktop/`. The current implementation is a Milestone 0 shell with `App.tsx`, `main.tsx`, and `styles.css`.

Future components must follow `docs/product/frontend-interaction-spec.md`, especially the generated exercise UI, loading/error states, note drawer, and settings boundaries.

---

## Component Structure

- Keep small presentational components as plain function components.
- Define static arrays or constants outside the component when they do not depend on props or state. Current example: `readinessItems` in `aearn/apps/desktop/src/App.tsx`.
- Use semantic containers with explicit labels where needed. Current example: `<main className="shell">`, `<section className="hero" aria-labelledby="app-title">`, and `<section className="panel" aria-label="前置能力">`.
- Split feature components only when a page grows beyond the current shell shape. Do not introduce a component hierarchy before the feature exists.

---

## Props Conventions

- Use TypeScript props types or interfaces for components with props.
- Keep prop names aligned with API contract fields unless converting for display.
- Do not pass backend-internal Attempt terms into user-facing component labels.
- Use discriminated unions for future UI state such as `loading`, `error`, `dirty`, `running`, and `submitted`.

---

## Styling Patterns

- Current styling uses global CSS in `aearn/apps/desktop/src/styles.css`.
- Keep design tokens in `:root` until a larger design system exists.
- Use class names that describe layout roles (`shell`, `hero`, `panel`) rather than implementation details.
- Maintain responsive rules for desktop and small screens. The current shell uses a `max-width: 640px` media query.
- Do not add Tailwind, CSS-in-JS, or a component library without a specific task requirement.

---

## Accessibility

- Use semantic landmarks and headings.
- Give unlabeled sections an accessible label when the visible heading is not enough.
- Disable controls while API operations are pending and show the reason when possible.
- Long-running run/submit/generation states must expose visible feedback, not only console logs.
- Generated code exercise UI must distinguish current vs stale results so old output is not announced as the latest result.

---

## Server-Authoritative Generated Side Panels

A conversational planning inspector may be present before the validated backend
artifact exists, but generated plan content must remain server-authoritative.
Render the toggle and a visually minimal shell immediately; while the artifact
pointer is null, the open shell may show only a neutral emoji plus hidden
accessible status text. It must not synthesize titles, modules, progress,
sources, readiness, or any other plan fact.

```tsx
const draft = session.current_draft;
const draftId = draft?.draft_id ?? null;
const [draftOpen, setDraftOpen] = useState(true);

useEffect(() => {
  if (draftId) setDraftOpen(true);
}, [draftId]);

return (
  <DraftDock open={draftOpen} onOpenChange={setDraftOpen}>
    {draftOpen
      ? draft
        ? <PlanRouteInspector draft={draft} />
        : <DraftPendingEmoji aria-label="计划尚未生成" />
      : null}
  </DraftDock>
);
```

The backend artifact pointer is still the generated-content reveal contract.
A newly generated draft may open the inspector automatically, while collapsing
the same draft must survive ordinary session refreshes; key the auto-open effect
to the primitive draft ID, not the whole session object. Keep the desktop
inspector compact with a bounded width and height, inset it visibly from the
viewport edge, and preserve visible rounding on all four corners so it reads as
an independent floating window instead of an attached sidebar. On narrow
screens, use a bounded floating sheet rather than inserting the draft below the
conversation. Respect `prefers-reduced-motion`, expose `aria-expanded` and
`aria-controls`, and keep the conversation/composer usable before and after the
inspector appears.

## Conversation Activation Layout

Planning conversations distinguish an unactivated shell from an active thread.
The idle layout is derived from loaded server history, not from whether the
composer currently contains text:

```tsx
const planningIdle = mode === "plan_drafting"
  && historyStatus === "ready"
  && timeline.length === 0
  && activeRun === null
  && historyError === null;
```

When `planningIdle` is true, hide the empty timeline, suggestion controls, and
secondary composer hints; center the single composer in the available workspace.
As soon as the first input is accepted and an active run or durable timeline
item exists, switch to the normal message stream with the composer at the
bottom. Loading and error states are not idle states and must remain visible.
This prevents an empty conversation from looking like an already-active thread
while preserving immediate transition from accepted input to run feedback.

## Common Mistakes

- Showing backend fact enums such as `Attempt(run)` or `Attempt(submit)` directly to users.
- Letting the frontend calculate final `result`, `score`, or `fsrs_rating`; these must come from backend APIs.
- Treating compiled-language course or runner availability as full sandbox availability. Java/Go/C# are only `managed_compiled_test` teaching-grade single-exercise execution; C++ and Rust remain unsupported for public routes.
