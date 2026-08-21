# Component Guidelines

> How components are built in this project.

---

## Overview

The formal frontend is a Vite + React + TypeScript + Tauri 2 desktop app under `aearn/apps/desktop/`. The current implementation is a Milestone 0 shell with `App.tsx`, `main.tsx`, and `styles.css`.

Future components must follow `docs/product/frontend-interaction-spec.md`, especially the generated exercise UI, loading/error states, note drawer, and settings boundaries.

---

## Component Structure

- Keep small presentational components as plain function components.
- Define static arrays or constants outside the component when they do not depend on props or state. Current example: `readinessItems` in `aearn/apps/desktop/src/App.tsx`.
- Use semantic containers with explicit labels where needed. Current example: `<main className="shell">`, `<section className="hero" aria-labelledby="app-title">`, and `<section className="panel" aria-label="前置能力">`.
- Split feature components only when a page grows beyond the current shell shape. Do not introduce a component hierarchy before the feature exists.

---

## Props Conventions

- Use TypeScript props types or interfaces for components with props.
- Keep prop names aligned with API contract fields unless converting for display.
- Do not pass backend-internal Attempt terms into user-facing component labels.
- Use discriminated unions for future UI state such as `loading`, `error`, `dirty`, `running`, and `submitted`.

---

## Styling Patterns

- Current styling uses global CSS in `aearn/apps/desktop/src/styles.css`.
- Keep design tokens in `:root` until a larger design system exists.
- Use class names that describe layout roles (`shell`, `hero`, `panel`) rather than implementation details.
- Maintain responsive rules for desktop and small screens. The current shell uses a `max-width: 640px` media query.
- Do not add Tailwind, CSS-in-JS, or a component library without a specific task requirement.

---

## Accessibility

- Use semantic landmarks and headings.
- Give unlabeled sections an accessible label when the visible heading is not enough.
- Disable controls while API operations are pending and show the reason when possible.
- Long-running run/submit/generation states must expose visible feedback, not only console logs.
- Generated code exercise UI must distinguish current vs stale results so old output is not announced as the latest result.

---

## Server-Authoritative Generated Side Panels

A conversational planning inspector may be present before the validated backend
artifact exists, but generated plan content must remain server-authoritative.
Render the toggle and a visually minimal shell immediately; while the artifact
pointer is null, the open shell may show only a neutral emoji plus hidden
accessible status text. It must not synthesize titles, modules, progress,
sources, readiness, or any other plan fact.

```tsx
const draft = session.current_draft;
const draftId = draft?.draft_id ?? null;
const [draftOpen, setDraftOpen] = useState(true);

useEffect(() => {
  if (draftId) setDraftOpen(true);
}, [draftId]);

return (
  <DraftDock open={draftOpen} onOpenChange={setDraftOpen}>
    {draftOpen
      ? draft
        ? <PlanRouteInspector draft={draft} />
        : <DraftPendingEmoji aria-label="计划尚未生成" />
      : null}
  </DraftDock>
);
```

The backend artifact pointer is still the generated-content reveal contract.
A newly generated draft may open the inspector automatically, while collapsing
the same draft must survive ordinary session refreshes; key the auto-open effect
to the primitive draft ID, not the whole session object. Keep the desktop
inspector compact with a bounded width and height, inset it visibly from the
viewport edge, and preserve visible rounding on all four corners so it reads as
an independent floating window instead of an attached sidebar. On narrow
screens, use a bounded floating sheet rather than inserting the draft below the
conversation. Respect `prefers-reduced-motion`, expose `aria-expanded` and
`aria-controls`, and keep the conversation/composer usable before and after the
inspector appears.

## Conversation Activation Layout

Planning conversations distinguish an unactivated shell from an active thread.
The idle layout is derived from loaded server history, not from whether the
composer currently contains text:

```tsx
const planningIdle = mode === "plan_drafting"
  && historyStatus === "ready"
  && timeline.length === 0
  && activeRun === null
  && historyError === null;
```

When `planningIdle` is true, hide the empty timeline, suggestion controls, and
secondary composer hints; center the single composer in the available workspace.
As soon as the first input is accepted and an active run or durable timeline
item exists, switch to the normal message stream with the composer at the
bottom. Loading and error states are not idle states and must remain visible.
This prevents an empty conversation from looking like an already-active thread
while preserving immediate transition from accepted input to run feedback.

## Common Mistakes

- Showing backend fact enums such as `Attempt(run)` or `Attempt(submit)` directly to users.
- Letting the frontend calculate final `result`, `score`, or `fsrs_rating`; these must come from backend APIs.
- Treating compiled-language course or runner availability as full sandbox availability. Java/Go/C# are only `managed_compiled_test` teaching-grade single-exercise execution; C++ and Rust remain unsupported for public routes.

## Scenario: LessonDocument Registered Renderer

### 1. Scope / Trigger

Apply this contract when rendering Lesson documents, composing the later learning workspace, changing citation interaction, or adding a new registered Lesson block type.

### 2. Signatures

```tsx
<LessonDocumentPage userId={userId} trackId={trackId} knowledgeKey={knowledgeKey} onBack={onBack} />
<LessonDocumentView document={document} assignment={assignment} sources={sources} />
<LessonBlockRenderer block={block} onCitation={selectCitation} />
<LessonSourcesPanel sources={sources} selectedCitationId={selectedCitationId} onSelect={selectCitation} />
```

### 3. Contracts

- `LessonDocumentPage` owns loading, prepare/retry polling, start, refresh proposal, explicit migration, and learner-safe errors.
- `LessonDocumentView` is the reusable document boundary for both the single-page reader and the later three-column workspace.
- `LessonBlockRenderer` exhaustively renders only the registered discriminated union. A new block type requires backend contract, frontend type/parser, renderer, tests, and browser fixture updates together.
- Facts expose inline citation buttons that target `LessonSourcesPanel`; the source panel renders only validated frozen snapshot metadata.
- No component renders arbitrary HTML or Markdown.
- `exercise_gate` preserves its frozen public contract and receives capability UI only through a typed render seam. `LessonGatePanel` consumes server `allowed_actions`; no component computes score, pass, mastery, diagnostic outcome, or unlock.

### 4. Validation & Error Matrix

| UI condition | Required behavior |
| --- | --- |
| API returns unknown block or extra field | show visible contract error; do not partially render |
| Lesson is missing | show explicit prepare action |
| Authoring is pending/running | show preparing state and bounded polling |
| Authoring failed | show safe failure code/message and retry action |
| Assignment is started | show frozen-version disclosure |
| Proposed successor exists | show impact without replacing current document |
| Citation is selected | focus/highlight the matching source snapshot |
| Current knowledge key is absent | show route/not-ready error; never guess the first node |

### 5. Good / Base / Bad Cases

- Good: Learning Home passes the server-owned `current_knowledge_key`; all ten blocks and one frozen source set render.
- Base: an unprepared Gate shows only the server-authorized prepare action; static/unavailable tiers hide actions that the server did not authorize.
- Bad: use index position to infer the current node or source.
- Bad: use `dangerouslySetInnerHTML`, a Markdown fallback, or an `unknown as LessonDocument` cast.

### 6. Tests Required

- Browser flow from Learning Home through missing/preparing/ready and failed/retry.
- Render every registered block and assert inline citations map to returned sources.
- Start freeze, refresh proposal, and explicit migration behavior.
- Gate controls match `allowed_actions`; editor changes stale prior results; diagnostic pass still requires explicit confirm.
- Normal, 900px, and 390px checks for no overlay, clean console, no horizontal overflow, visible focus, keyboard source interaction, and reduced-motion compatibility.

### 7. Wrong vs Correct

#### Wrong

```tsx
<div dangerouslySetInnerHTML={{ __html: lesson.body }} />
```

#### Correct

```tsx
switch (block.type) {
  case "concept":
    return <ConceptBlockView block={block} onCitation={onCitation} />;
  case "exercise_gate":
    return renderExerciseGate(block);
  // every registered type is explicit; no default content fallback
}
```

## Lesson Gate 与模块诊断组件接缝（2026-08-11）

- `LessonDocumentPage` 拥有 Gate/editor/hint/Attempt/poll/stale/error/modal 状态；renderer 和 document view 只接 typed props/callback。
- `LessonGatePanel` 必须逐项检查 server `allowed_actions`，不能从 tier、score 或本地状态自行扩权。
- pending 必须轮询原 `attempt_id`；editor 修改后旧结果显示 stale 或清除，不能继续作为当前提交结果。
- `ModuleDiagnosticModal` 独立于知识点 Gate；失败明确不跳过，pass 只展示 impact，confirm 后才刷新 Lesson/路线。
- textarea、modal、关闭/确认按钮必须有 label、visible focus、busy/disabled 和 live status；390px 不得横向溢出。

## Scenario: Aearn-Owned DSH-Derived UI Foundation

### 1. Scope / Trigger

Apply this contract when adding or consuming reusable controls under
`aearn/apps/desktop/src/ui/dsh-derived/`, updating the pinned upstream-derived
source, or styling Tutor Composer, Queue, typed questions, `Think`, or plan
surfaces with this foundation.

### 2. Signatures

```tsx
<DshDerivedRoot>
  <Button variant="primary" busy={saving}>Save</Button>
  <Input ref={inputRef} aria-label="Name" invalid={hasError} />
  <DisclosureRow
    title="Think"
    expanded={expanded}
    onExpandedChange={setExpanded}
  >
    {publicSteps}
  </DisclosureRow>
</DshDerivedRoot>

<DshDerivedRoot className="tutor-surface-root">
  <main className="tutor-workspace tutor-conversation-only">
    {activeTurn?.status === "in_progress" && controlState === "running"
      ? <TutorRunningPlaceholder turn={activeTurn} />
      : null}
  </main>
</DshDerivedRoot>
```

Public entrypoint: `aearn/apps/desktop/src/ui/dsh-derived/index.ts`.
Public tokens: `--aearn-*`. The class `.aearn-dsh-derived` is the only scope in
which internal `--dsw-*` compatibility aliases may exist.

### 3. Contracts

- Components are controlled, presentational React 19 components. They accept typed props/callbacks and never read Tutor APIs, Zustand stores, session state, or upstream runtime context.
- `DshDerivedRoot` establishes the compatibility scope. Product code consumes public exports and `--aearn-*` tokens rather than importing implementation CSS directly.
- `DshDerivedRoot` renders a real `div`; it does not transparently forward a parent flex/grid height contract. A height-constrained product surface must add a product-owned layout class that carries `width: 100%`, `height: 100%`, `min-width: 0`, `min-height: 0`, and the required flex behavior to the root before relying on a descendant `height: 100%`. Keep this layout adapter outside `ui/dsh-derived`.
- A Tutor feature may derive an ephemeral `think` row from authoritative `active_turn.status === "in_progress"` plus `control_state === "running"`. Harness/public-thinking uses exact `active_thinking`; Codex sidecar uses only the exact owner-scoped `active_runtime_output` / `tutor_runtime_item_stream_v1` projection. It never consumes `process`, arbitrary provider objects, raw trace, prompt, commentary, reasoning summary, or arbitrary SSE payload. The successful snapshot reconciles by turn identity with persisted `public_thinking_text + answer` or `runtime_output` instead of rendering a duplicate.
- A typed-request learner response reuses the ordinary learner message bubble and renders only the server-projected natural-language result. Never expose `question_key`, `field_key`, internal option values, serialized JSON, or quoted raw values such as `experience_level: "new"`.
- `Button`, `Input`, `DisclosureRow`, and `Tooltip` preserve native keyboard semantics, visible focus, disabled/busy behavior, and refs where the native element has one.
- `MessageText` renders literal text only. It does not parse Markdown or HTML.
- `AearnToast` and `showAearnToast` adapt the existing `sonner` runtime; do not add another toast store or provider implementation.
- Derived source remains pinned to `deepseek-ai/deepseek-harness@47f943859bef60e4160492346772ded9b24f765a`. Update `THIRD_PARTY_NOTICES.md`, `UPSTREAM.md`, and substantial-file revision comments together.
- Brand assets, product names, Cordis, plugin/session/runtime packages, and upstream state contracts are forbidden production dependencies.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Component needs Tutor/server state | create an Aearn feature adapter outside `ui/dsh-derived`; pass typed props/callbacks down |
| A full-height surface becomes content-height after adding `DshDerivedRoot` | add a product-owned root layout class and verify the root/workspace heights match the available parent area; do not patch the generic foundation root with product layout |
| Snapshot reports an in-progress active turn with running control state but no text | append one static `StateDot + Think`; no button, chevron, focus target, body, or helper copy |
| First exact public-thinking text arrives without validated complete | keep the native row static and buffer text off-DOM |
| Validated complete and the stability window are both satisfied | enable the native disclosure in place, default expanded, preserve literal line breaks, and begin grapheme reveal |
| Snapshot terminalizes the turn and returns the Tutor message/request | reconcile by turn identity, finish queues, reveal authority text, then auto-collapse `Think` once without duplicating the row |
| Upstream CSS references `--dsw-*` | map only the required aliases inside `.aearn-dsh-derived`; do not expose them as public tokens |
| Target control is disabled but still needs a tooltip | use `disabledTarget` so the wrapper provides focus/title fallback |
| Motion is decorative | disable or reduce it under `prefers-reduced-motion: reduce` |
| New copied/adapted source is substantial | record repository path, revision, reuse type, and differences in `UPSTREAM.md` |
| A candidate dependency imports Cordis or upstream runtime | reject the dependency and adapt the React/CSS source locally |

### 5. Good / Base / Bad Cases

- Good: a Tutor feature owns Queue state and passes item text plus callbacks into foundation controls inside `DshDerivedRoot`.
- Good: `TutorConversationSurface` uses `tutor-surface-root` to propagate the parent height through the DSH scope into `.tutor-workspace`.
- Good: a running active turn renders only `StateDot + Think`; the first approved text enables an expanded disclosure, and the persisted item reuses the same visual row.
- Base: a static `Pill` renders as text; an interactive `Pill` renders as a native button.
- Bad: import a Tutor store or `api.ts` from `ui/dsh-derived`.
- Bad: insert the root wrapper into a full-height flex/grid chain without a layout adapter, leaving the Composer positioned against an approximately content-height root.
- Bad: render “Tutor 正在思考”/helper copy, make the empty row a disabled button, consume arbitrary provider reasoning instead of the exact Aearn Runtime projection, number model text, or retain live and persisted copies together.
- Bad: use `--dsw-*` in product CSS, copy brand icons, or install an upstream UI/runtime package.

### 6. Tests Required

- `pnpm --dir .\aearn\apps\desktop test` covers keyboard focus, busy/disabled, refs, controlled disclosure, tooltip association/fallback, literal text, semantic tokens, reduced motion, narrow-container CSS, import boundaries, and brand/runtime exclusion.
- `pnpm --dir .\aearn desktop:check` proves strict TypeScript and Vite production build compatibility.
- When the foundation is integrated into a visible product surface, add real browser checks at the required wide, medium, and narrow viewports; this foundation task alone does not authorize Tutor behavior changes.
- For full-height integrations, browser assertions must compare the DSH root and product workspace rectangles with the available parent height, hit-test the Composer center, focus the input without a position change, and assert `scrollWidth <= clientWidth`.
- Running-turn regression tests must assert `data-turn-id`, static `Think` without button before text, first-text default expansion, literal multiline content, unique persisted replacement, answer-complete one-time collapse, and manual reopen surviving snapshot refresh.

### 7. Wrong vs Correct

#### Wrong

```tsx
import { useAppStore } from "../../../stores/useAppStore";

export function QueueButton() {
  const queue = useAppStore((state) => state.queue);
  return <button style={{ color: "var(--dsw-alias-brand-primary)" }}>{queue.length}</button>;
}
```

#### Correct

```tsx
export interface QueueButtonProps {
  count: number;
  onOpen: () => void;
}

export function QueueButton({ count, onOpen }: QueueButtonProps) {
  return <Button variant="ghost" onClick={onOpen}>Queue {count}</Button>;
}
```

## 场景：Tutor `Think` 行与最终回答接替（2026-08-15）

### 1. 适用范围与触发条件

- 触发：修改 `TutorConversationSurface` 的 active turn、Tutor message/request、`DisclosureRow`、typewriter 或相关样式。

### 2. 组件签名

```tsx
<TutorRunningPlaceholder turn={turn} hasText={hasText} text={displayedText} complete={complete} />
<TutorThinking messageId={id} text={text} expanded={expanded} complete={complete} onExpandedChange={setExpanded} />
```

### 3. 契约

- 无文本时只渲染 `StateDot + Think`，不是 button，不含 chevron/helper/body。
- 首个 live chunk 先进入仅内存的 `350ms` 稳定窗口，并始终保持 provisional；只有同 generation 的 validated `complete` 到达后才允许进入 DOM。`complete` 与稳定窗口必须同时满足：先 complete 则等待窗口，先结束窗口则等待 complete。reset/discard 在 complete 前到达时正文永不出现。snapshot 仅在 `active_thinking.complete=true` 时直接恢复；incomplete snapshot 继续显示静态 Think。解禁后使用 controlled native disclosure，默认展开；正文 literal + `pre-wrap`，不解析 Markdown/HTML、不编号。
- SSE gap/mismatch recovery 在请求 snapshot 前不得清空已显示文本；snapshot 对同 Turn/Revision 的有效 generation 做单调合并，只有 recovery snapshot 明确缺少 active thinking、或 authoritative reset/discard/terminal 状态时才清除。
- learner 普通输入或 typed request 响应的 accepted mutation 返回 fresh run 后，组件必须立即把该 authoritative run 投影为新的静态 `● Think`，并更新 turn identity；不能丢弃 mutation response 后只等待下一次 snapshot。
- live 与 persisted item 通过 turn identity 原位接替；回答队列完成后只自动折叠一次，随后尊重用户选择。
- 历史项完整显示、默认折叠、不重放动画；reduced motion 直接同步。

### 4. 验证与错误矩阵

| 状态 | 组件行为 |
| --- | --- |
| accepted input/request response 返回 fresh run | 立即在最新 learner 输入后挂载该 run 的静态 `● Think` |
| active + empty text | 静态状态，不可聚焦/点击 |
| first live text、稳定窗口未结束 | 继续显示静态 Think；文本不进入 DOM |
| 稳定窗口已结束、尚无 complete | 继续静态 Think；provisional 文本仍不进入 DOM |
| validated complete + 稳定窗口结束 | disclosure 出现并展开 |
| complete 前 reset/discard | 取消待显示 generation，正文无论已等待多久都不闪现 |
| complete 后 append | contract mismatch，fresh snapshot；不能继续猜测 |
| gap/mismatch recovery pending | 保留当前可见文本，等待 snapshot 裁决 |
| recovery snapshot 无 active thinking | 清除 live 文本并恢复静态 Think/安全终态 |
| final item matched | 不重复节点，先完成 thinking 再揭示 answer |
| answer complete | 折叠一次；用户重开后 refresh 不再折叠 |
| fail/interrupt/discard | 移除 live row，由现有安全终态接管 |

### 5. 正常、基础与错误案例

- 正常：首段先稳定、完整 decision 验证后收到 complete，`Think` 文本两段逐字出现；回答完成后折叠，用户重新展开保持。
- 基础：无 structured stream，final snapshot 直接显示完整、默认折叠的 `Think`。
- 错误：只凭 `350ms` timer 展示 provisional chunk；把 transport EOF 当作 validated complete；recovery 请求前清空已显示文本；disabled disclosure 占位、显示步骤数/时长、同时渲染 live 和 final、用 `dangerouslySetInnerHTML`。

### 6. 必须测试

- Testing Library 断言 role/button/tab stop、普通输入与 typed request accepted response 的立即新 Turn 挂载、首个 `turn_output` 的 `350ms` 稳定窗口、超过窗口仍未 complete 不进入 DOM、慢速无效 generation discard 永不闪现、incomplete snapshot 保持静态、validated complete 后默认展开、gap recovery 保留文本直到 snapshot 裁决、换行、唯一节点、折叠一次、refresh 与历史行为。
- fake timers 断言每 tick 一个 grapheme、emoji/组合字符完整、timer cleanup。
- 真实浏览器验证 1440/900/390、focus、reduced motion、无溢出/overlay/console warning。

### 7. 错误与正确写法

#### 错误

```tsx
<DisclosureRow disabled title="Tutor 正在思考" summary="完成后显示" />
```

#### 正确

```tsx
return hasText
  ? <TutorThinking title="Think" text={text} expanded={expanded} />
  : <div role="status"><StateDot state="running" /><strong>Think</strong></div>;
```

## 场景：Tutor Codex raw Runtime reasoning 与 answer 同项接替（2026-08-20）

### 1. 适用范围与触发条件

- 触发：修改 `TutorConversationSurface` 的 `active_runtime_output`、`tutor_runtime_item_stream_v1` reducer、Codex 历史消息或恢复快照。

### 2. 组件签名

```tsx
<TutorRunningPlaceholder turn={turn} runtimeOutput={liveRuntimeOutput} ... />
<TutorRuntimeMessage item={message} output={message.runtime_output} />
```

### 3. 契约

- 当前 Codex Tutor entry 内先显示小写 `think`，reasoning 使用左边框 disclosure，`final_answer_item` 在其下直接流式显示；commentary 与 reasoning summary 没有渲染入口。
- identity 为 `turnId + input_revision + generation + item_id + channel`；append 连续累加，complete 使用后端返回的完整文本。若 complete 文本为空但本地已有非空前缀，保留前缀并只切换 `state=completed`。
- 同 Turn/Revision 的 recovery snapshot 暂时没有 `active_runtime_output` 时保留当前已验证内容；只有 Turn 改变/终态 handoff、显式 discard/reset 或不同 revision 才清理。
- 多个 reasoning item 按创建顺序以双换行拼接。当前 reasoning 默认展开；历史 reasoning 默认折叠；终态无 reasoning 时不渲染空 `think`。
- fresh typed-response run 立即接管当前 entry；后端可以创建新 Turn，但 UI 必须连续显示下一项 generated UI，不要求学习者再发普通消息。

### 4. 验证与错误矩阵

| 状态 | 组件行为 |
| --- | --- |
| reasoning append | 同 item 原位追加，不清空其他 reasoning item |
| reasoning complete 文本为空且已有前缀 | 保留前缀，标记 completed |
| recovery snapshot 同 Turn 但 runtime output 暂缺 | 保留当前内容，等待后续 SSE/snapshot |
| incoming generation 较旧 | 忽略 |
| explicit discard | 仅删除对应 item |
| 历史 runtime_output 有 reasoning | 默认折叠显示 `think` 与下方 answer |
| 历史 runtime_output 无 reasoning | 仅显示 answer，无空 disclosure |

### 5. 正常、基础与错误案例

- 正常：两个 reasoning item 连续流式出现，首项 text-less complete 后文本不变，answer 在下方继续流式，刷新后历史仍可展开完整 reasoning。
- 基础：只有 final answer，终态不出现空 `think`。
- 错误：snapshot 的瞬时 null 清空当前 reasoning；complete 空字符串覆盖累计 delta；把 commentary 拼进 `think`；为每个 fresh backend Turn 重置整个可见对话。

### 6. 必须测试

- Testing Library：raw reasoning/answer 同项流式、空 complete 保留文本、同 Turn snapshot gap 保留、历史默认折叠、无 reasoning 无空行、fresh typed response 立即挂载。
- API parser：v3 snapshot 与历史 `runtime_output` exact keys/limits/identity；provider metadata、commentary、external IDs 和 extra key 拒绝。
- 真实浏览器 fake/offline smoke：当前展开、历史折叠、刷新/重连、下一项 generated UI 连续出现、console clean，禁止调用真实 provider。

### 7. 错误与正确写法

#### 错误

```ts
if (!snapshot.active_runtime_output) setRuntimeOutput(null);
```

#### 正确

```ts
if (!snapshot.active_turn) clearRuntimeOutput();
else if (snapshot.active_runtime_output) mergeByTurnRevisionGeneration(snapshot.active_runtime_output);
else preserveValidatedCurrentRuntimeOutput();
```

## Scenario: Dynamic planning language selector (2026-08-21)

- The language `single_select` renders only the durable request's exact options and order. It never refetches or reconstructs the course catalog while the request is pending.
- Language requests have `recommended=null`; no radio is initially selected and Submit remains disabled until the learner selects one option. Non-language recommendation behavior remains unchanged.
- Safe select drafts may be retained in `sessionStorage` by exact request ID/version so reload/reconnect restores only a value still present in the durable options. Free text is not stored by this mechanism.
- Required browser states are explicit-language skip, frontend/backend/multi-language/conflict/full catalog, refresh recovery, keyboard focus, and no horizontal overflow at 1440x900, 900x900, and 390x844.
