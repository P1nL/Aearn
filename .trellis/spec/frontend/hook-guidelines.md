# Hook Guidelines

> How hooks are used in this project.

---

## Overview

The current desktop shell does not define custom hooks. Add hooks only when there is real shared stateful logic in the Tauri/React runtime.

Future hooks should support the frontend interaction spec rather than abstracting prematurely.

---

## Custom Hook Patterns

- Name custom hooks with the `use*` prefix.
- Keep hooks focused on one responsibility: bootstrap, API health, SSE stream, learning session, exercise run/submit, note autosave, or settings form state.
- Return explicit state objects instead of positional tuples when the state has more than two values.
- Keep side effects inside hooks only when they own the lifecycle. UI-only derived values can stay inside components.

---

## Data Fetching

- No data-fetching library is currently installed. Do not introduce React Query, SWR, or another cache layer without a task.
- First API integration should use small typed fetch wrappers aligned to `docs/architecture/api-contract.md`.
- Include `X-Request-Id` for traceable requests when practical.
- Handle JSON and SSE paths separately. SSE hooks must parse single-line JSON `data` frames and surface `done` / `error`.
- Use `fetch` + `ReadableStream` for POST SSE endpoints. Browser `EventSource` is GET-only and cannot carry the existing run/submit/agent-draft request bodies.
- Treat the SSE stream as incomplete if it closes without a terminal `done` or `error` event, and surface a visible recoverable error state.
- API offline state must disable run/submit/generation actions and show a visible warning.

---

## Naming Conventions

- `useBootstrap` for app startup and user/API readiness.
- `useApiHealth` for `/health`.
- `useLearningSession` for current session start/resume state.
- `useExerciseRun` and `useExerciseSubmit` for exercise operations.
- `useNoteAutosave` for note drawer/page save state.
- `useSseStream` only if multiple endpoints share streaming behavior.

---

## Examples

- `aearn/apps/desktop/src/App.tsx` currently needs no hook because readiness copy is static.
- The first API hook should be introduced only when `GET /health` or bootstrap state is wired into the desktop shell.
- SSE hook behavior must follow the event format in `docs/architecture/api-contract.md`.

---

## Common Mistakes

- Creating global hooks before the app has the corresponding feature.
- Hiding request errors in hooks without exposing `error.code`, `recoverable`, and retry options to the component.
- Letting hooks mutate final scoring or FSRS state locally instead of using backend responses.
- Reusing stale run results after the editor content changes.
- Reusing one hard-coded `X-Request-Id` across streamed write tests. Backend write paths can persist request IDs under unique indexes, so tests and hooks should generate a fresh request ID per request unless intentionally testing replay behavior.
