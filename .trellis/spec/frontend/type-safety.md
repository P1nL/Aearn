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

## Scenario: Legacy Tutor Run Cursor SSE (retired from v2 Desktop)

### 1. Scope / Trigger

- Trigger: maintaining backend/legacy compatibility for `GET /api/tutor/runs/{run_id}/events`. The v2 Desktop deletes `buildTutorRunEventsUrl()` and `useTutorSSE`; no production Tutor surface may reintroduce them.
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


## 场景：模型代码审核 exact contract 与结构化编辑器

### 1. 适用范围与触发条件
- 触发条件：修改 `model_code_review` Gate、authoring 状态、finding editor、evidence 或 result parser/UI。

### 2. 接口签名
```ts
prepareLessonGate(...): Promise<LessonGateMutationResponse>
createLessonGateAttempt({ reviewSubmission, submission: null, ... }): Promise<ExerciseAttempt>
requestModelReviewEvidence(...): Promise<ModelReviewEvidenceResponse>
```

### 3. 契约
- API 从 `unknown` exact-validate prompt/artifact/submission/result/evidence；未知字段、enum、score key 或 protected marker 整体拒绝。
- `model_code_review` 只能 submit `review_submission`，不能发送普通 `submission` 或 Run。
- 页面可保存草稿、字段错误和 pending 状态；score/pass/mastery/unlock、finding classification 与 assistance 只来自服务端。
- result 只按 `client_finding_id` 映射用户卡片，不显示 expected finding、隐藏位置/测试、matcher、rubric 或 provider payload。

### 4. 验证与错误矩阵
| 条件 | 前端结果 |
| --- | --- |
| `preparing` | 显示服务端状态/重试，不生成 fallback |
| verdict/finding shape 或行范围非法 | 字段级错误，阻止提交 |
| evidence 成功 | 显示 `validation_evidence_viewed` assisted badge |
| unknown/extra/protected field | contract error，拒绝局部渲染 |
| terminal result 后编辑 | 清除或标记旧结果 stale |

### 5. 正常、基础与错误案例
- 正常：增加两个 finding、删除一个、提交后按保留的 client id 显示 classification。
- 基础：`no_correctness_issue` 允许零 finding；代码区只读且可横向滚动。
- 错误：`response.json() as ModelReviewResult`，或前端根据 finding 数量计算 pass。

### 6. 必须测试
- `pnpm --dir .\\aearn desktop:check`。
- 真实浏览器覆盖 preparing/retry、结构化编辑、evidence、result、390/900/1440、键盘/focus、console 与 protected marker。
- 后端 contract/scorer/API 测试必须同行通过。

### 7. 错误与正确写法
#### 错误
```ts
const result = await response.json() as ModelReviewResult;
const passed = findings.length > 0;
```
#### 正确
```ts
const payload: unknown = await response.json();
const result = parseModelReviewResult(payload);
```
只有 exact parser 与服务端结果建立类型和评分权威。


## 场景：Tutor typed request API seam

- `TutorInteractionRequestItem` 必须按 `kind=elicitation|approval` exact-parse；request kind、actor、state、version、presentation、allowed actions 与 nullable answer lineage 均为 closed union。
- `TutorRequestPresentation` 只接受 `text | integer | single_select | multi_select | approval` 的 exact server-owned shape；未知 type、extra key、非法 option/risk/state 整体拒绝。
- response mutation 只发送 clarification text、planning exact key/catalog/value 或 approval exact proposal identity/decision；不得发送 capability/external receipt。
- response 成功必须解析 fresh run 的 `response_to_request_id`、`completion_reason`、`dispatch_job_id` 和 returned request；客户端不得根据 prompt 文案推断 kind、approval 或 authority success。
- 在最终 QuestionComposer child 前，Desktop 可以只读显示 request placeholder，但 history/snapshot parser 不得丢弃或宽松 cast request。


## 场景：Tutor Queue 与 control mutation exact DTO（2026-08-14）

- `TutorConversationInputResponse` 必须是 `TutorInputAcceptedResponse | TutorQueuedInputAcceptedResponse` closed union；用 `"queued" in response` 缩窄，不能读取不存在的 `run`。
- `TutorQueuedInput` exact-parse `item_id/state/position/version/content/created_at/updated_at`；未知 state、extra key、非正 position/version 整体拒绝。
- snapshot conversation exact-parse `control_version/control_state/queue_paused/queue_pause_reason/pending_count/max_pending`，Queue 不得保留为 `Record<string, unknown>[]`。
- Queue read/edit/delete/reorder/Interrupt 响应按 `TutorQueueStateResponse` exact-parse；Steer/execute/Retry fresh-turn 响应必须先剥离并验证 additive `control_version`/`queue_item`，再复用 exact turn parser。
- `control_state` 只允许 `idle|running|waiting|queue_paused`，pause reason 只允许 `pending_request|interrupted|failed|null`。
- 在最终 Queue UI child 前，现有 composer 收到 queued response 必须安全清空/刷新，不得把它当成 accepted turn 崩溃或本地伪造 active run。

必须运行 Desktop Vitest 与 `desktop:check`；parser 应覆盖合法 accepted/queued/control payload 及 extra/unknown/missing 字段拒绝。


## 场景：Tutor thread/turn v2 capability exact DTO（2026-08-14）

- `GET /api/tutor/capabilities/thread-turn-v2` 必须 exact-parse `tutor_thread_turn_v2_capability_v1`，包括 cutover/desktop contract version、env、state、generation、summary/block、effective gate、安全 counts 与时间。
- state 只允许 `idle|preparing|blocked|ready|enabled`；未知字段、负 generation、未知 nested count 值整体拒绝。
- Desktop 不从 localStorage、本地 env 或旧 harness cutover receipt 猜测 v2 已启用。


## Tutor v2 exact turn and timeline additions (2026-08-14)

- `TutorPublicTurn.input_revision` is a required non-negative Desktop field even though backend validation supplies `0` for replaying older stored event payloads. Snapshot producers must project the current persisted revision.
- `TutorHistoryItem` includes exact learner-safe `error { id, turn_id, code, message, recoverable, created_at }`; unknown/extra error fields reject the item.
- The v2 renderer exhaustively handles message/request/error and intentionally returns `null` for standalone process. This is a display rule, not permission to skip process validation at the API boundary.
- Conversation SSE cursors are opaque strings; only event `sequence` participates in duplicate/gap checks.

## 场景：Tutor public process step 跨层 allowlist 同步（2026-08-19）

### 1. 适用范围与触发条件

- 触发：后端新增或移除 Tutor public process step key，或修改 snapshot/history/process parser。
- 目的：防止服务端已发布的安全步骤被 Desktop 误判为 invalid payload，同时继续拒绝未知或受保护阶段。

### 2. 类型签名

```ts
type TutorPublicProcessStep = {
  key: "input_received" | "context_prepared" | "authorized_resource_checked"
    | "runtime_started" | "domain_tool_running" | "domain_tool_completed"
    | "learning_reply_generated" | "replaced_by_newer_input";
  state: "completed" | "current";
  label: string;
};
```

服务端权威是 `persistence.py` 的 `_PUBLIC_PROCESS_STEP_KEYS` 与 `schema.sql` 的 process step check constraint；Desktop 的 literal union 和 `isTutorProcessStepKey` 必须同步。

### 3. 契约

- snapshot/history 的 `process.steps[]` 从 `unknown` 逐项验证 key、state 与 label，不得直接 cast。
- Codex sidecar 的 `runtime_started | domain_tool_running | domain_tool_completed` 是 learner-safe Aearn projection，不代表可以公开 raw tool、provider 或 reasoning payload。
- 新增后端 key 时必须在同一变更链中审计 Desktop type、runtime guard 和 API boundary fixture；不得只更新数据库或后端 repository allowlist。
- standalone process 即使不在 v2 timeline 中渲染，也必须先通过 API boundary validation。

### 4. 验证与错误矩阵

| 条件 | Desktop 结果 |
| --- | --- |
| key 属于完整 allowlist，state/label 合法 | 接受 snapshot/process DTO |
| key 未知，例如 `provider_reasoning` | 拒绝整个 payload，显示稳定 contract error |
| state 未知或 label 非字符串 | 拒绝整个 payload |
| step 带 raw arguments/result/reasoning 等受保护结构 | exact parser 或 public API 审计拒绝，不进入应用状态 |

### 5. 正常、基础与错误案例

- 正常：Codex turn 返回 `input_received -> runtime_started -> domain_tool_running -> domain_tool_completed -> learning_reply_generated`，Desktop 恢复完整消息时间线。
- 基础：Harness turn 继续只返回旧 `context_prepared` / `authorized_resource_checked` 步骤，仍可解析。
- 错误：后端扩展 `_PUBLIC_PROCESS_STEP_KEYS` 后只更新 backend test，导致 Desktop 在 `toTutorPublicProcess` 返回 `null`。

### 6. 必须测试

- `fetchTutorConversationSnapshot` API boundary fixture 接受 Codex runtime step 序列。
- 同一 fixture 将 key 替换为未知值后必须抛出 `Tutor snapshot API returned an invalid payload`。
- 运行 Desktop Vitest 与 `pnpm --dir .\aearn desktop:check`。
- 真实浏览器恢复至少一个包含 Codex process steps 的 conversation，并断言错误横幅不存在、learner/Tutor message 可见、console clean。

### 7. 错误与正确写法

#### 错误

```ts
return value === "input_received" || value === "learning_reply_generated";
```

后端新增正式 allowlisted key 后，陈旧 guard 会把整个合法 snapshot 误判为无效。

#### 正确

```ts
return value === "input_received"
  || value === "runtime_started"
  || value === "domain_tool_running"
  || value === "domain_tool_completed"
  || value === "learning_reply_generated";
```

实际实现必须覆盖服务端完整 allowlist，而不是只复制示例子集；未知值仍然 fail closed。

## 场景：Tutor public-thinking v2 exact DTO（2026-08-15）

### 1. 适用范围与触发条件

- 触发：修改 Tutor snapshot/message/request/event/parser 中的公开思考字段。

### 2. 类型签名

```ts
type TutorConversationSnapshotResponse = { snapshot_version: "tutor_conversation_snapshot_v2"; active_thinking: TutorActiveThinking | null; ... };
type TutorTurnOutputPayload = AppendPayload | ResetCompleteDiscardPayload;
```

### 3. 契约

- `active_thinking` exact keys：`turn_id,input_revision,generation,state,text,complete,last_event_sequence`；必须匹配 active turn identity/revision。
- `turn_output` exact closed union；append 唯一允许 `text`，长度 1..160；总 message/request `public_thinking_text` 最多 1280。
- snapshot/message/request 从 `unknown` 构造，extra/unknown/missing/protected field 整体拒绝。
- legacy steps 只在 API compatibility boundary 转为文本；组件内部统一只消费 `public_thinking_text`。

### 4. 验证与错误矩阵

| 缺陷 | 前端结果 |
| --- | --- |
| snapshot/event version 非 v2 | contract error / reset |
| active thinking 与 active turn 不匹配 | 拒绝 snapshot |
| append 空文本、超 160 或多字段 | 拒绝 event并 fresh snapshot |
| state/complete 不一致或 text 超 1280 | 拒绝 payload |
| payload 含 reasoning/prompt/body | extra/protected field 拒绝 |

### 5. 正常、基础与错误案例

- 正常：v2 snapshot + exact active thinking +连续 append。
- 基础：`active_thinking=null`，running UI 保持静态 `Think`。
- 错误：`response.json() as TutorConversationSnapshotResponse`、宽泛 `Record<string, unknown>` 直传组件。

### 6. 必须测试

- 合法 v2 snapshot/message/request/event；所有 missing/extra/unknown/越界/identity mismatch 拒绝。
- protected marker fixture：reasoning、reasoning_content、prompt、provider_body、diagnostic。
- `pnpm --dir .\aearn\apps\desktop test` 与 `pnpm --dir .\aearn desktop:check`。

### 7. 错误与正确写法

#### 错误

```ts
const snapshot = await response.json() as TutorConversationSnapshotResponse;
```

#### 正确

```ts
const payload: unknown = await response.json();
return requireTutorConversationSnapshotV2(payload);
```

## 场景：Tutor Codex Runtime output exact DTO（2026-08-20）

### 1. 适用范围与触发条件

- 触发：修改 snapshot v3、history message `runtime_output`、Runtime `turn_output` SSE 或 Desktop parser/types。

### 2. 类型签名

```ts
type TutorRuntimeOutput = {
  output_version: "tutor_runtime_output_v1";
  input_revision: number;
  generation: number;
  reasoning_items: TutorRuntimeOutputItem[];
  final_answer_item: TutorRuntimeOutputItem | null;
};
type TutorRuntimeOutputItem = { item_id: string; text: string; state: "streaming" | "completed"; last_sequence: number };
```

### 3. 契约

- snapshot v3 exact 包含 `active_runtime_output`；历史 Tutor message 可选 exact `runtime_output`。item ID 是 Aearn projection ID，不是 Codex external item ID。
- Runtime SSE closed union 仅允许 `output_version,input_revision,generation,operation,chunk_sequence,item_id,channel`，append/complete 才允许 `text`；channel 仅 `reasoning|final_answer`。
- parser 从 `unknown` 构造，reasoning 最多 64 项、单项 text 最多 1,000,000、generation 正数、sequence 非负；model/provider/protocol/commentary/external thread/turn ID 等 extra key 整体拒绝。
- 旧 `active_thinking/public_thinking_text` contract 继续服务 Harness；不得把两种 payload 宽松合并为 `Record<string, unknown>`。

### 4. 验证与错误矩阵

| 缺陷 | 前端结果 |
| --- | --- |
| snapshot v3 缺 `active_runtime_output` key | 拒绝 snapshot |
| runtime output revision 与 active turn 不一致 | 拒绝 snapshot |
| item state/channel/operation 未知 | 拒绝 payload并 fresh snapshot |
| extra provider/commentary/external ID | 拒绝 payload |
| complete text 为空且 reducer 已有同 item 文本 | 类型接受；reducer 保留累计文本并完成 |

### 5. 正常、基础与错误案例

- 正常：v3 snapshot 恢复两个 reasoning item 与一个 streaming final answer，后续 exact complete 接管。
- 基础：`reasoning_items=[]` 且 final answer completed。
- 错误：`response.json() as TutorRuntimeOutput`、接受 `model_provider` extra key、把 external item ID 当公开 identity。

### 6. 必须测试

- `tutorApiV2.test.ts` 覆盖 snapshot/history 合法 runtime output、extra provider metadata 拒绝、identity mismatch。
- `useTutorConversationStream.test.ts` 覆盖 append/complete/reset/discard exact union、unknown/extra/gap recovery。
- `TutorConversationSurface.test.tsx` 覆盖 reducer 单调合并与 transient null snapshot。

### 7. 错误与正确写法

#### 错误

```ts
const runtime = payload.active_runtime_output as TutorRuntimeOutput;
```

#### 正确

```ts
const runtime = payload.active_runtime_output === null
  ? null
  : toTutorRuntimeOutput(payload.active_runtime_output);
if (payload.active_runtime_output !== null && runtime === null) return null;
```

## Planning language presentation exact DTO (2026-08-21)

- `single_select` accepts optional compatibility fields `selection_scope`, `selection_reason_code`, and `intent_policy_version`; current language requests provide the closed scope union `explicit_shortlist | intent_shortlist | conflict_shortlist | full_catalog`.
- Parse from `unknown`, validate option values/labels and nullable recommendation, and reject unknown extra keys. Internal course UUIDs, learner evidence, regex matches, and model rationale are not public fields.
- The response continues to send the exact public option value under `planning_input.value`; the client never submits candidate course IDs.
