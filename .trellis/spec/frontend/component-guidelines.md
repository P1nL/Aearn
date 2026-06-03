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

## Common Mistakes

- Showing backend fact enums such as `Attempt(run)` or `Attempt(submit)` directly to users.
- Letting the frontend calculate final `result`, `score`, or `fsrs_rating`; these must come from backend APIs.
- Treating compiled-language course or runner availability as full sandbox availability. Java/Go/C# are only `managed_compiled_test` teaching-grade single-exercise execution; C++ and Rust remain unsupported for public routes.
