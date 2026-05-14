# Directory Structure

> How frontend code is organized in this project.

---

## Overview

The formal desktop frontend lives under `aearn/apps/desktop/` and uses Vite, React, TypeScript, and Tauri 2. The static HTML prototype in `docs/design/` is reference material, not the runtime source tree.

---

## Directory Layout

```text
aearn/apps/desktop/
  src/
  src-tauri/
    capabilities/
    icons/
    src/
```

---

## Module Organization

- `src/` owns React application code and styling.
- `src-tauri/` owns Tauri Rust shell code, capabilities, config, and native assets.
- `src-tauri/icons/icon.ico` is required for Windows `cargo check` because `tauri-build` generates a Windows resource file even when bundling is disabled.
- When the desktop UI grows beyond a single shell screen, split `src/` by responsibility instead of expanding one giant `App.tsx`:
  - `pages/` for route-level screens
  - `features/` for larger workflow-specific subtrees such as the M3 workbench
  - `components/` for shared presentational/shell pieces
  - `lib/` for pure labels, content seeds, and helper functions
  - `appTypes.ts` for app-local shared UI types that do not belong in backend contract files

---

## Naming Conventions

- Keep the formal desktop runtime under `aearn/apps/desktop/`.
- Use React component files with PascalCase when new components are introduced, such as `GeneratedCodeExerciseCard.tsx`.
- Keep bootstrap files as `main.tsx`, `App.tsx`, and `styles.css` until the UI grows enough to split by feature.
- After that split threshold is crossed, keep `App.tsx` as the app shell entry, not the home for page-local editors, workbench panels, or result cards.
- Keep Tauri Rust code under `src-tauri/src/` and Tauri configuration under `src-tauri/`.
- Do not treat `docs/design/learning-agent-claude-desktop-framework.html` as runtime source; it is a visual/reference prototype.

---

## Examples

- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/main.tsx`
- `aearn/apps/desktop/src/styles.css`
- `aearn/apps/desktop/src-tauri/tauri.conf.json`
- `aearn/apps/desktop/src-tauri/icons/icon.ico`

## Common Mistakes

- Building the product UI inside `docs/design/` instead of the Tauri/Vite app.
- Adding route or feature files before checking `docs/product/frontend-interaction-spec.md`.
- Letting `App.tsx` keep route JSX, page-local state, and M3 feature panels after the app already has clear page/feature boundaries.
- Removing `src-tauri/icons/icon.ico`; Windows `cargo check` needs it through `tauri-build`.
