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
```

Public entrypoint: `aearn/apps/desktop/src/ui/dsh-derived/index.ts`.
Public tokens: `--aearn-*`. The class `.aearn-dsh-derived` is the only scope in
which internal `--dsw-*` compatibility aliases may exist.

### 3. Contracts

- Components are controlled, presentational React 19 components. They accept typed props/callbacks and never read Tutor APIs, Zustand stores, session state, or upstream runtime context.
- `DshDerivedRoot` establishes the compatibility scope. Product code consumes public exports and `--aearn-*` tokens rather than importing implementation CSS directly.
- `Button`, `Input`, `DisclosureRow`, and `Tooltip` preserve native keyboard semantics, visible focus, disabled/busy behavior, and refs where the native element has one.
- `MessageText` renders literal text only. It does not parse Markdown or HTML.
- `AearnToast` and `showAearnToast` adapt the existing `sonner` runtime; do not add another toast store or provider implementation.
- Derived source remains pinned to `deepseek-ai/deepseek-harness@47f943859bef60e4160492346772ded9b24f765a`. Update `THIRD_PARTY_NOTICES.md`, `UPSTREAM.md`, and substantial-file revision comments together.
- Brand assets, product names, Cordis, plugin/session/runtime packages, and upstream state contracts are forbidden production dependencies.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Component needs Tutor/server state | create an Aearn feature adapter outside `ui/dsh-derived`; pass typed props/callbacks down |
| Upstream CSS references `--dsw-*` | map only the required aliases inside `.aearn-dsh-derived`; do not expose them as public tokens |
| Target control is disabled but still needs a tooltip | use `disabledTarget` so the wrapper provides focus/title fallback |
| Motion is decorative | disable or reduce it under `prefers-reduced-motion: reduce` |
| New copied/adapted source is substantial | record repository path, revision, reuse type, and differences in `UPSTREAM.md` |
| A candidate dependency imports Cordis or upstream runtime | reject the dependency and adapt the React/CSS source locally |

### 5. Good / Base / Bad Cases

- Good: a Tutor feature owns Queue state and passes item text plus callbacks into foundation controls inside `DshDerivedRoot`.
- Base: a static `Pill` renders as text; an interactive `Pill` renders as a native button.
- Bad: import a Tutor store or `api.ts` from `ui/dsh-derived`.
- Bad: use `--dsw-*` in product CSS, copy brand icons, or install an upstream UI/runtime package.

### 6. Tests Required

- `pnpm --dir .\aearn\apps\desktop test` covers keyboard focus, busy/disabled, refs, controlled disclosure, tooltip association/fallback, literal text, semantic tokens, reduced motion, narrow-container CSS, import boundaries, and brand/runtime exclusion.
- `pnpm --dir .\aearn desktop:check` proves strict TypeScript and Vite production build compatibility.
- When the foundation is integrated into a visible product surface, add real browser checks at the required wide, medium, and narrow viewports; this foundation task alone does not authorize Tutor behavior changes.

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
