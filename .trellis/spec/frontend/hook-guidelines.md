# Hook Guidelines

> How hooks are used in this project.

---

## Overview

The desktop defines focused lifecycle hooks under `aearn/apps/desktop/src/hooks/` when a feature owns real shared stateful logic in the Tauri/React runtime.

Add hooks only for an explicit lifecycle boundary such as snapshot bootstrap, conversation-global SSE, API health, or autosave; do not abstract UI-only derivations prematurely.

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


## Scenario: Tutor Conversation Snapshot and Opaque SSE

### 1. Scope / Trigger

Apply when changing `TutorConversationSurface`, `fetchTutorConversationSnapshot`,
`buildTutorConversationEventsUrl`, `useTutorConversationStream`, Queue/request
controls, or the public turn projection. The v2 Desktop surface is snapshot-first
and has no production caller for run-local SSE or `/runs/{run_id}/inputs`.

### 2. Signatures

```ts
fetchTutorConversationSnapshot({ userId, conversationId, limit, cursor, signal })
buildTutorConversationEventsUrl(conversationId, userId): string
useTutorConversationStream(endpoint, { initialCursor, onEvent, onResetRequired })
interruptTutorTurn({ expectedTurnId, expectedInputRevision, expectedControlVersion, ... })
respondToTutorInteractionRequest({ itemId, expectedRequestVersion, response, ... })
```

`TutorPublicTurn` includes `turn_id`, `conversation_id`, protocol/status,
non-negative `input_revision`, retry lineage, completion reason, and timestamps.

### 3. Contracts

- Hydrate timeline, active turn, pending request, Queue, control state/version,
  history cursor, and stream cursor from one exact snapshot.
- Treat conversation SSE IDs as opaque signed strings. Event `sequence` is the
  monotonic ordering field; do not parse the cursor as a number.
- An event only schedules a bounded snapshot refresh. Do not derive Queue,
  request, error, or turn state from event payloads in the component.
- Ignore duplicate/older sequence. Gap, invalid cursor, malformed JSON, unknown
  event, or invalid envelope closes the stream and requires a fresh snapshot.
- A pending typed request owns the composer seat. Learner clarification,
  planning, and approval use the exact request version; authority requests are
  read-only. Ordinary composer and conversation Queue controls are absent.
- Render public `message`, typed request, and safe `error`; parse but do not
  render standalone `process`. `Think` reads only `public_thinking_steps[]`.
- `effective_enabled=false` preserves reads and disables all v2 writes without
  falling back to legacy run-local input.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Snapshot contains unknown/extra field | reject the projection and show a visible contract error |
| SSE sequence is duplicate or older | ignore it without another render |
| SSE sequence has a gap | close stream, refetch snapshot, then resubscribe from returned cursor |
| Cursor is invalid/expired/ahead | refetch snapshot; never synthesize a cursor |
| Queue/request/control mutation returns stale conflict | preserve local draft, show safe error, refetch snapshot |
| Global capability is disabled | history remains readable; writes stay disabled; no legacy fallback |
| Legacy waiting error is public | show a fresh-turn migration card; do not prefill or submit an old answer |

### 5. Good / Base / Bad Cases

- Good: snapshot cursor is sent verbatim in `Last-Event-ID`; a valid event
  schedules one refresh and the next snapshot advances all visible state.
- Base: no conversation is selected; first non-empty send creates the first
  turn, selects the returned conversation, then hydrates its snapshot.
- Bad: `Number(streamCursor)`, optimistic local Queue mutation, rendering
  process steps as thinking, or retrying `/runs/{run_id}/inputs` after 410.

### 6. Tests Required

- Vitest parser tests for opaque cursor, exact envelope, cursor error, malformed
  event, and source guard against retired run-local callers.
- Desktop `pnpm test` and `desktop:check`.
- Real browser/Tauri fixture checks for running Send to Queue, Queue operations,
  Stop, Steer conflict refresh, Retry, typed requests, migration, reconnect,
  keyboard/focus, reduced motion, and 1440/900/390 layouts.
- Backend snapshot/Queue tests assert `active_turn.input_revision` is present and
  matches the CAS value used by Interrupt/Steer.

### 7. Wrong vs Correct

#### Wrong

```ts
const sequence = Number(snapshot.stream_cursor);
setQueue(applyEventLocally(queue, event));
await acceptTutorRunInput({ runId, content });
```

#### Correct

```ts
const stream = useTutorConversationStream(url, {
  initialCursor: snapshot.stream_cursor,
  onEvent: scheduleSnapshotRefresh,
  onResetRequired: refreshSnapshot,
});
await interruptTutorTurn({
  expectedTurnId: snapshot.active_turn.turn_id,
  expectedInputRevision: snapshot.active_turn.input_revision,
  expectedControlVersion: snapshot.conversation.control_version,
});
```
