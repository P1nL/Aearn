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
  render standalone `process`. Harness `Think` reads exact `public_thinking_text` plus fenced
  `active_thinking`; Codex `think` reads only exact owner-scoped `active_runtime_output` / runtime `turn_output`. Legacy steps normalize at the API boundary; arbitrary provider/reasoning payloads remain forbidden.
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

## 场景：Tutor `turn_output` reducer 与 grapheme 队列（2026-08-15）

### 1. 适用范围与触发条件

- 触发：修改 conversation SSE、`active_thinking` hydration、live-thinking reducer 或 `useGraphemeTypewriter`。

### 2. Hook 签名

```ts
useTutorConversationStream(endpoint, { initialCursor, onEvent, onResetRequired })
useGraphemeTypewriter(targetText, { animate, initialText, resetKey, intervalMs })
```

### 3. 契约

- 只有 exact `turn_output` payload 可局部消费；其他 event 仍只触发节流 snapshot refresh。
- reducer identity 为 `turnId + inputRevision + generation`，append 还要求连续 `chunkSequence`。
- `append` 只更新 off-DOM received buffer；`complete` 是 validated reveal fence。组件必须同时满足 complete 与首文本稳定窗口才把 buffer 交给 grapheme 队列；snapshot hydrate 也只有 `complete=true` 可直接显示。
- duplicate/older event 幂等忽略；gap、extra/unknown field、wrong identity 立即请求 fresh snapshot；recovery 返回前保留已经 validated 且可见的文本，但不得显示 incomplete buffer。
- typewriter 使用 `Intl.Segmenter(grapheme)`，fallback `Array.from`；Tutor 思考、回答与请求 prompt 显式共享 `18ms` 的 `intervalMs`，每 tick 仅追加一个 grapheme，并在 reset/unmount 清 timer。
- active Turn 已结束但同 Turn 的持久化 message/request 尚未出现在 snapshot 时，保留 live-thinking 节点与 turn identity；只有 final item 接管后才清理临时节点。
- 自动折叠必须同时满足思考队列 complete、回答/request prompt 队列 complete，并在最后一个 grapheme 已渲染后等待 `240ms`；不得以服务端 complete 或 active Turn 消失直接折叠。

### 4. 验证与错误矩阵

| 输入 | 结果 |
| --- | --- |
| `reset` sequence 0 | 新 generation 清空队列 |
| 连续 `append`、尚无 complete | 只追加 received buffer，不进入 DOM |
| validated `complete` | 若稳定窗口已结束则启动 grapheme 队列，否则等待剩余窗口 |
| duplicate append | 不重复文本 |
| gap/wrong turn/revision/generation | `onResetRequired` + fresh snapshot |
| `discard` | 清除 live state/queue |
| Turn 先消失、final item 后到达 | 保留 live-thinking，下一份含 final item 的 snapshot 完成交接 |
| 回答完成但折叠延迟未结束 | `Think` 仍保持展开 |
| reduced motion | 直接同步 target，无悬挂 timer，仍遵守一次性折叠延迟 |

### 5. 正常、基础与错误案例

- 正常：incomplete snapshot/append 只累计候选前缀，validated complete 后才进入 grapheme 队列且不回退。
- 基础：conversation 切换改变 reset key，旧 timer 与文本被清理。
- 错误：把所有 SSE payload merge 到 timeline、用 code unit 切 emoji、gap 后继续猜测。

### 6. 必须测试

- stream parser：exact append/reset/complete/discard、extra field、protected field、wrong identity、gap reset。
- typewriter：一 grapheme/tick、emoji/组合字符、换行、initial prefix、reset、reduced motion、unmount cleanup。
- component integration：稳定窗口结束但尚无 complete 仍不可见、慢速 rejected attempt 直接 discard、incomplete snapshot、repair reset、conversation switch、Turn 消失早于 final item 的 snapshot handoff、完整思考与回答显示后再折叠，以及 final reconciliation。

### 7. 错误与正确写法

#### 错误

```ts
setText((value) => value + payload.text);
setDisplayed(target.slice(0, displayed.length + 1));
```

#### 正确

```ts
if (!matchesFence(event, live) || !isNextChunk(event, live)) requireSnapshot();
const graphemes = segmentGraphemes(target);
setDisplayed(graphemes.slice(0, visibleCount + 1).join(""));
```

## Dynamic typed-request recovery (2026-08-21)

- Snapshot and conversation SSE remain the authority for request identity/version and exact options. Reconnect must replace the request projection, not merge a newly fetched catalog into it.
- A local select draft is valid only for the same request ID/version and only while every stored value remains in the server option set and within `maximum_selections`.
- Resolving the request clears its stored draft. Text and integer answers are not persisted as select-draft recovery state.

## Runtime coalesced projection recovery (2026-08-21)

- `tutor_runtime_item_stream_v1.chunk_sequence` is a projection sequence. A single append may represent many private source deltas; Desktop never expects one event per provider delta.
- Source range/count/hash are private receipt fields and must be rejected if they appear in public SSE/snapshot payloads.
- Duplicate/older projection events remain idempotent; projection gaps still trigger `onResetRequired` and fresh snapshot without changing the model turn outcome.

## Teaching authority open failure

Latch the attempted authority identity across failed open requests. Do not clear the identity on failure: parent/child authority callbacks run again after error-state renders and otherwise cause an unbounded POST/409 loop. Permit a different authoritative version to open, and keep the explicit user refresh action available for the same version. A conflict must not force server state or automatic model retries.
