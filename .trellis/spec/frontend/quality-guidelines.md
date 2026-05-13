# Quality Guidelines

> Code quality standards for frontend development.

---

## Overview

Frontend work targets the Tauri desktop app under `aearn/apps/desktop/`. The current quality gate is the package build command, which runs `tsc && vite build`; the root workspace exposes it as `pnpm desktop:check` from `aearn/`.

Every UI task must be checked against `docs/product/frontend-interaction-spec.md` and the acceptance plan.

---

## Forbidden Patterns

- Do not implement product UI in `docs/design/`; that directory is reference/prototype material.
- Do not expose `Attempt(run)`, `Attempt(submit)`, `review_submit`, or FSRS internals as ordinary user labels.
- Do not calculate final score, result, `fsrs_rating`, `due_at`, or review scheduling in the frontend.
- Do not show unsupported Java/C++ sandbox capabilities as runnable.
- Do not add new UI libraries, routers, or state managers without task scope and verification.
- Do not rely on console output as the only user feedback.

---

## Required Patterns

- Run desktop commands from `aearn/` or `aearn/apps/desktop/`, not from the repository root.
- Keep loading, error, disabled, retry, and stale states visible for long operations.
- Keep generated exercise cards in the conversation flow, not as a separate fixed workbench unless the product spec changes.
- Use backend responses as source of truth for run/submit results.
- Preserve responsive behavior for narrow windows.
- Keep `src-tauri/icons/icon.ico` present for Windows Tauri checks.

---

## Testing Requirements

- Run `pnpm desktop:check` from `aearn/` after desktop code changes.
- Run `pnpm --dir apps/desktop build` from `aearn/` when only the desktop package is in scope.
- For Tauri shell changes, run `cargo check` from `aearn/apps/desktop/src-tauri` when practical.
- For visible UI changes, open the local Vite or Tauri target and verify loading/error/responsive behavior.
- For API-connected UI, cover happy path, API error, offline, retry, stale result, and disabled unsupported runtime states.

---

## Code Review Checklist

- The component names and page flow match `frontend-interaction-spec.md`.
- UI labels avoid backend-internal Attempt and FSRS implementation terms.
- Async operations have user-visible state and do not allow duplicate writes while pending.
- Old run output cannot masquerade as current output after code changes.
- API errors branch on stable `error.code`, not free-form messages.
- Build/type-check commands were run from the correct workspace.

## Scenario: M2 Desktop Onboarding Flow

### 1. Scope / Trigger

- Trigger: implementing or changing the M2 desktop onboarding flow.
- Scope: `aearn/apps/desktop/src/App.tsx`, `api.ts`, `types.ts`, and `styles.css`.

### 2. Signatures

- `fetchLanguageCourses()` loads `GET /api/language-courses`.
- `createUser(displayName)` calls `POST /api/users`.
- `generatePlanDraft(input)` calls `POST /api/plans/generate`.
- `confirmPlan(userId, planDraft)` calls `POST /api/plans`.

### 3. Contracts

- The frontend may own onboarding form state, loading/error/disabled state, and local draft preview state.
- The backend remains source of truth for user IDs, plan IDs, persisted modules, knowledge points, and review initialization.
- Draft preview must show runtime capability metadata, source attribution, and non-skippable core modules.
- Workspace after confirmation is only a route summary entry in M2; it must not show generated exercise cards, run/submit actions, Attempt types, score, FSRS rating, or due scheduling.
- Java/C++ courses must display `compiled_sandbox_later` as unsupported/postponed execution capability.

### 4. Validation & Error Matrix

- API offline -> visible top status and generation disabled.
- Missing goal/material input -> disabled generate button with visible reason.
- API error envelope -> show stable `error.code` and `error.message`.
- Unsupported runtime -> show a capability boundary notice, not a runnable claim.

### 5. Good/Base/Bad Cases

- Good: select JavaScript, generate draft, inspect source attribution and core module lock, confirm, and see workspace route panel.
- Base: select Java or C++ and see the compile sandbox later notice.
- Bad: exposing `Attempt(run)` / `Attempt(submit)` labels, showing a Java/C++ run button, or locally marking review scheduling as complete.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check`.
- Browser smoke: open `http://127.0.0.1:1420`, verify API online, generate a JS draft, confirm it, and see workspace summary.
- Browser console should have no current errors after the latest reload and flow.

### 7. Wrong vs Correct

#### Wrong

```tsx
<button>Run Java sandbox</button>
```

This implies Java execution exists in M2.

#### Correct

```tsx
<div>Java/C++ 第一版只展示静态阅读和补全边界，不提供完整编译运行沙箱。</div>
```

M2 keeps course visibility separate from real runtime availability.
