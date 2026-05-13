# State Management

> How state is managed in this project.

---

## Overview

The current desktop shell has no external state management library and no global store. Keep this unless a feature creates a real sharing or caching need.

State must respect the contract boundary: frontend owns interaction state, while backend owns scoring, Attempts, ReviewState, FSRS scheduling, and durable notes.

---

## State Categories

- Local UI state: editor content, dirty/pristine flags, open drawers, selected panel, disabled reasons, loading state.
- Server state: user, plan, modules, knowledge points, sessions, exercises, attempts, review queue, notes.
- Derived display state: progress labels, stale result badges, retry visibility, unsupported runtime notices.
- Tauri/window state: shell readiness, API base URL, native capability status.
- URL/router state: page selection when routing is introduced; do not encode sensitive content in route state.

---

## When to Use Global State

- Use component-local state by default.
- Promote to app-level state only when multiple pages need the same source: current user, active plan, API health, global toast, confirm dialog, and note drawer.
- Do not create a global store just to pass props through one or two levels.
- Do not keep backend-owned facts only in frontend memory; refetch or update from API responses after writes.

---

## Server State

- Server state must use the API contract as source of truth.
- After run/submit operations, update UI from the returned operation result, not from locally recomputed score.
- `Attempt(run)` creates a fact record but must not advance ReviewState in the UI.
- `Attempt(submit)` or `review_submit` may update ReviewState only after the backend confirms it.
- Stale run results must be invalidated or clearly marked when editor content changes.
- Idempotent retries should show the existing server result when the backend returns it.

---

## Examples

- `aearn/apps/desktop/src/App.tsx` currently renders static Milestone 0 readiness state and does not need global state.
- `docs/product/frontend-interaction-spec.md` defines future app-level state such as `bootstrap_status`, `user_state`, `api_status`, `active_plan_id`, and `resume_available`.
- Exercise editor text is local UI state; `Attempt`, `code_completion_result`, and `ReviewState` are server state.

---

## Common Mistakes

- Duplicating backend scheduling or scoring rules in the desktop app.
- Showing old stdout/preview/test output after the code changed without a stale marker.
- Treating "today review count > 0" as automatic navigation to review. Product flow says normal open defaults to current learning unless backend flags high-risk resume.
- Making settings toggles for fixed backend rules such as Attempt persistence, scoring dimensions, or FSRS mapping.
