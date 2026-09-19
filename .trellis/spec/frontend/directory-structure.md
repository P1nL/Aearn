# Directory Structure

> How the current Aearn desktop is organized and how large root modules are decomposed.

---

## Overview

The runtime lives under `aearn/apps/desktop/` and uses Vite, React, TypeScript, and Tauri 2. The HTML prototype in `docs/design/` is reference material only and is never the production source tree.

---

## Desktop Layout

```text
aearn/apps/desktop/
  src/
    api/          # shared HTTP client plus domain endpoint modules
    contracts/    # frontend copies/projections of public API contracts by domain
    features/     # workflow-owned UI, hooks, tests, and feature-local styles
    hooks/        # cross-feature hooks only
    lib/          # pure helpers and labels
    pages/        # route/shell-level pages
    stores/       # application bootstrap and shared UI state
    styles/       # base, shell, utilities, and cross-feature responsive rules
    tests/        # cross-feature contract/integration tests
    ui/           # reusable primitives and design-system-derived foundation
    App.tsx
    main.tsx
  src-tauri/
    capabilities/
    icons/
    src/
```

During migration, root `api.ts`, `types.ts`, or `styles.css` may remain only as small compatibility/entry barrels. They must not regain cross-domain implementation ownership.

---

## Ownership Rules

### Application shell

- `main.tsx` installs global providers and imports the style entrypoint.
- `App.tsx` owns application-level route/shell composition only.
- Page-local editors, timelines, workbenches, result panels, and feature state belong under `features/` or `pages/`.

### Features

Each substantial workflow owns its components, hooks, tests, and feature-local styles. Current primary roots are `features/learning/` and `features/tutor/`. A feature must not duplicate HTTP decoding, shared design primitives, or server-authority logic already owned elsewhere.

### API and contracts

- `api/client.ts` owns base URL, request execution, common headers, JSON/error decoding, and cancellation behavior.
- Domain API modules own endpoint-specific request/response adaptation.
- `contracts/` groups public types by domain such as Tutor, Learning, Lesson/Practice, Review, and Cutover.
- Compatibility barrels may re-export stable names while imports migrate.
- Runtime payload validation stays at the API boundary; components consume validated projections.

### Styling

- `styles/` owns reset/base, application shell, utilities, and truly cross-feature responsive rules.
- Feature selectors stay next to their owning feature, preferably in CSS Modules where isolation is practical.
- `ui/dsh-derived/` owns its tokens and primitives; feature code reuses them rather than copying token values or primitive CSS.
- A single global stylesheet must not accumulate unrelated feature histories.

### Tauri

`src-tauri/` owns Rust shell code, capabilities, configuration, and native assets. `src-tauri/icons/icon.ico` remains required for Windows `cargo check` through `tauri-build`.

---

## Common Mistakes

- Building runtime UI in `docs/design/`.
- Keeping all endpoint functions, public types, or feature CSS in one root file after domain boundaries exist.
- Moving server-authority decisions into components or Zustand state.
- Creating feature-local copies of API decoders, SSE ordering, tokens, or shared primitives.
- Letting `App.tsx` or one surface component own data orchestration and every major visual subtree.
