# Type Safety

> Type safety patterns in this project.

---

## Overview

The desktop app uses TypeScript. Current strictness comes from `tsc` in `aearn/apps/desktop/package.json` and `aearn/apps/desktop/tsconfig.json`.

Runtime API types must follow `docs/architecture/api-contract.md`; do not invent frontend-only enum names for backend fields.

---

## Type Organization

- Keep component-local types near the component until a type is shared.
- Move shared API/domain types into a dedicated module when multiple features need them.
- Future cross-runtime shared contracts may live under `aearn/packages/shared/` only after both desktop and service code need them.
- Keep enum literal unions aligned with API contract values: `language`, `runtime_tier`, `attempt_type`, `runtime_status`, `next_action`, and `fsrs_rating`.

---

## Validation

- No runtime validation library is currently installed.
- Validate unknown API responses at the fetch boundary when the first API integration lands. If a validation library is added, document it in this file and keep it service-wide.
- Do not rely on TypeScript types alone for SSE event parsing; events arrive as strings and must be parsed defensively.
- Surface invalid response shapes as API/contract errors with visible UI feedback.

---

## Common Patterns

- Use literal union types for API enums.
- Use discriminated unions for async UI states, for example `{ status: "loading" }`, `{ status: "error"; code: string }`, and `{ status: "success"; data: T }`.
- Use explicit return types for reusable hooks and API wrappers.
- Prefer `unknown` plus validation for external data over direct `as` casting.

---

## Forbidden Patterns

- Avoid `any` in application code.
- Avoid type assertions for API responses unless immediately preceded by runtime validation.
- Do not duplicate enum strings with different casing or labels.
- Do not model backend-internal Attempt types as visible user labels.

## Scenario: Tutor Cursor SSE and Non-Durable Error Frames

### 1. Scope / Trigger

- Trigger: adding or changing `GET /api/tutor/runs/{run_id}/events`,
  `buildTutorRunEventsUrl()`, `useTutorSSE`, `TutorSseEvent`, or a Tutor
  workspace timeline.
- Scope: `aearn/apps/desktop/src/{api,types}.ts`,
  `hooks/useTutorSSE.ts`, and pre-cutover Tutor components only. It does not
  change the existing learning/onboarding/review SSE hooks or the default app
  route.

### 2. Signatures

- Endpoint: `GET /api/tutor/runs/{run_id}/events?user_id={user_id}`.
- Resume header: `Last-Event-ID: <non-negative decimal durable sequence>`.
- Allowed public events: `input_accepted`, `tool_status`, `activity`,
  `run_state`, `done`, and `error`.
- Type boundary: durable events have `id: number`; a route/replay `error` frame
  that is not tied to a durable event has `id: null` and only an `ApiError`
  plus optional learner-safe public message.

### 3. Contracts

- Parse SSE strings at the hook boundary as `unknown`, then construct only the
  fields declared by `TutorSseEvent`; never cast an arbitrary frame into the
  union or pass through unrecognized fields.
- Only a non-negative numeric durable `id` advances the retained cursor and is
  sent on reconnect. Duplicate or older ids are ignored without re-rendering
  the learner timeline.
- A `done` or `error` event is terminal for the stream transport. The hook may
  expose that terminal fact but must not invent a run outcome, effect, plan
  revision, score, or ordering; `GET /api/tutor/runs/{run_id}` remains the
  source for full run state.
- An id-less `error` is terminal UI feedback, not a cursor reset. Keep the last
  valid numeric cursor and never send `Last-Event-ID: null`, an error code, or
  a synthetic sequence.
- Non-terminal transport closure is `STREAM_INCOMPLETE` and can reconnect only
  a bounded number of times. A manual retry resets the retry budget but not
  the durable cursor for the same run.

### 4. Validation & Error Matrix

- Missing/non-decimal/unsafe `id` on a non-error event ->
  `TUTOR_SSE_PROTOCOL_ERROR` or `SSE_CURSOR_INVALID`; do not render it.
- Unknown event name, invalid JSON, or payload failing the public union ->
  `TUTOR_SSE_PROTOCOL_ERROR`; do not expose raw frame text.
- Duplicate durable id after reconnect -> ignore it and preserve one timeline.
- `done` -> stop the stream and refresh the learner-safe run state.
- `error` with a numeric id -> record that cursor, surface the stable error,
  and stop. `error` with no id -> surface the stable error and stop without
  changing the cursor.
- Closed non-terminal stream -> bounded reconnect; after the limit, show a
  recoverable `STREAM_INCOMPLETE` state with a user retry action.

### 5. Good / Base / Bad Cases

- Good: reconnect after id `17` sends `Last-Event-ID: 17`, receives only id
  `18`, and appends exactly one new learner-safe timeline entry.
- Good: an in-stream `error` has no `id`; the UI shows its stable code/message,
  retains cursor `17`, and never treats the error as a run-local sequence.
- Base: the endpoint returns `CUTOVER_REQUIRED` before streaming during the
  pre-cutover period; the isolated Tutor surface displays the envelope and does
  not switch the legacy app route.
- Bad: using `EventSource`, parsing `id: undefined` as zero, using a terminal
  error code as `Last-Event-ID`, silently dropping malformed payloads, or
  creating a local terminal plan/effect state from a transport close.

### 6. Tests Required

- Run `pnpm --dir .\aearn desktop:check` after changing Tutor event types,
  parser logic, or workspace rendering.
- Backend contract tests must prove numeric cursor replay, duplicate-free
  ordering, terminal `done`/`error` mapping, invalid `Last-Event-ID`, and no
  protected fields in Tutor SSE output.
- When a desktop test runner is introduced, add parser coverage for a numeric
  durable `error`, an id-less route/replay `error`, malformed ids, duplicate
  replay frames, and bounded incomplete-stream reconnects.

### 7. Wrong vs Correct

#### Wrong

```ts
const event = JSON.parse(data) as TutorSseEvent;
cursorRef.current = Number(frame.id ?? 0);
```

This treats arbitrary JSON and an id-less error as durable replay state.

#### Correct

```ts
const event = parseTutorSseFrame(frame); // validates only the public union
if (event.id !== null && event.id > cursorRef.current) {
  cursorRef.current = event.id;
}
if (event.type === "error") {
  showStableError(event.data.error);
}
```

Only a validated numeric durable id advances the replay cursor; an id-less
public error remains terminal feedback rather than persisted ordering state.
