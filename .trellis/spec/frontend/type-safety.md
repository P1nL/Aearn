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

## Scenario: LessonDocument Unknown Boundary

### 1. Scope / Trigger

Apply this contract to Lesson read, prepare, refresh, start, and migration API responses, plus every new Lesson block/source/assignment field.

### 2. Signatures

```ts
parseLessonState(payload: unknown): LessonState
fetchLessonDocument(...): Promise<LessonState>
prepareLessonDocument(...): Promise<LessonPreparingState | LessonReadyState>
startLessonAssignment(...): Promise<LessonMutationResponse>
activateLessonMigration(...): Promise<LessonMutationResponse>
```

### 3. Contracts

- Parse from `unknown`; construct the public TypeScript union only after exact validation.
- Validate exact top-level keys by state, exact fields for every registered block, unique continuous block order, unique citation IDs, and citation membership in the returned source set.
- URLs must be absolute credential-free HTTP(S). Validate trust tier, source type, source version kind, assignment status, authoring state, impact arrays, and nullable timestamps explicitly.
- Reject unknown fields/types rather than dropping them.
- Do not add `any`, direct response casts, `@ts-ignore`, HTML/Markdown fallback, or a permissive index signature.

### 4. Validation & Error Matrix

| Payload defect | Frontend result |
| --- | --- |
| Unknown top-level status | visible Lesson contract error |
| Unknown block type or extra block field | visible Lesson contract error |
| Duplicate/non-continuous `order_index` | visible Lesson contract error |
| Block citation absent from `sources` | visible Lesson contract error |
| Credentialed/non-HTTP source URL | visible Lesson contract error |
| Invalid assignment/authoring enum | visible Lesson contract error |
| Network/server learner-safe error | preserve safe code/message and recoverability; do not expose raw body |

### 5. Good / Base / Bad Cases

- Good: a `ready` payload with ten exact blocks and citations contained in one validated source set.
- Base: a `failed` payload with a safe authoring run and retryable learner message.
- Bad: `const lesson = await response.json() as LessonReadyState`.
- Bad: accept an unknown block and render its arbitrary `content` field.

### 6. Tests Required

- Runtime parser fixtures for every Lesson state and registered block.
- Rejection fixtures for extra keys, unknown type/status, bad order, duplicate IDs, invalid URL, bad citation membership, invalid enums, and unsafe error bodies.
- Real browser fixture must exercise both success and failed/retry states because no standalone frontend unit runner currently owns this parser.

### 7. Wrong vs Correct

#### Wrong

```ts
const payload = (await response.json()) as LessonState;
return payload;
```

#### Correct

```ts
const payload: unknown = await response.json();
return parseLessonState(payload);
```

The parser, not a cast, establishes the application type.

## 场景：Gate、Attempt 与诊断运行时解析（2026-08-11）

### 1. 适用范围与触发条件

- 触发条件：修改 Gate/Attempt/diagnostic API、execution tier、`allowed_actions`、Lesson Gate 页面或模块诊断弹窗。
- 目标：前端只渲染经过 exact runtime validation 的 learner-safe projection，不从本地状态扩权。

### 2. 接口签名

```ts
fetchLessonGates(...): Promise<LessonGateCollection>
prepareLessonGate(...): Promise<LessonGateMutationResponse>
requestLessonGateHint(...): Promise<LessonGateHint>
createLessonGateAttempt(...): Promise<ExerciseAttempt>
fetchExerciseAttempt(...): Promise<ExerciseAttempt>
createModuleDiagnostic(...): Promise<ModuleDiagnostic>
createModuleDiagnosticAttempt(...): Promise<ModuleDiagnostic>
confirmModuleDiagnosticSkip(...): Promise<ModuleDiagnostic>
```

### 3. 契约

- 从 `unknown` 精确验证 execution tier、exercise type、Gate status/action/requirement、Attempt type/status/result、diagnostic state/item/impact 和 nullable 时间。
- `allowed_actions` 是服务端授权 literal union；未知 action/tier/status/extra key 必须拒绝整个 projection。
- public Attempt 只接受 `submission_hash` 和 learner-safe result；完整 submission、private rubric/test/reference、container/image/command/path 字段均为 contract violation。
- editor/hint/poll/modal/stale 是页面临时状态；score/pass/mastery/route change/diagnostic impact 只来自 API。
- API wrapper 不使用 `any`、response cast、宽泛 index signature 或前端推导 score/pass/unlock。

### 4. 验证与错误矩阵

| Payload 或状态缺陷 | 前端结果 |
| --- | --- |
| 未知 `execution_tier`、Gate status、exercise type 或 diagnostic state | 显示 contract error，不局部渲染 |
| `allowed_actions` 含未知动作 | 拒绝整个 Gate projection |
| public result 含 submission/private/container 字段 | 拒绝 payload，不写入页面状态 |
| pending poll 返回另一个 `attempt_id` | 视为 contract/scope error，不覆盖当前 Attempt |
| editor 在 terminal result 后变化 | 旧结果标记 stale 或清除 |
| diagnostic pass 未确认 | 只展示 proposed impact，不本地更新路线 |

### 5. 正常、基础与错误案例

- 正常：`container_verified` 返回 `allowed_actions=[hint,run,submit]`，页面轮询同一 Attempt 并显示服务端终态。
- 基础：`static_only` 只返回 hint/submit，页面无 Run 并显示 `not_run` 语义。
- 错误：根据 tier 自行补出 Run，或用 `response.json() as LessonGate` 绕过 parser。

### 6. 必须测试

- exact parser 接受所有合法 Gate/Attempt/diagnostic 状态，并拒绝 extra key、未知 enum/action 和 protected field。
- 真实浏览器覆盖 prepare/hint/run/submit/poll/stale、四 tier、diagnostic fail/pass/confirm。
- 1440px、精确 900px、390px 检查无水平溢出、modal fit、visible focus、console clean 和无 overlay。
- DOM/network public projection 不得出现 private test、reference answer、rubric、container/image、Docker socket、command/path。

### 7. 错误与正确写法

#### 错误

```ts
const gate = (await response.json()) as LessonGate;
if (gate.execution_tier === "container_verified") actions.push("run");
```

这会绕过服务端 `allowed_actions`，并允许未知或敏感字段进入应用状态。

#### 正确

```ts
const payload: unknown = await response.json();
const gate = parseLessonGate(payload);
const canRun = gate.allowed_actions.includes("run");
```

parser 建立类型边界，`allowed_actions` 建立能力边界，两者缺一不可。
