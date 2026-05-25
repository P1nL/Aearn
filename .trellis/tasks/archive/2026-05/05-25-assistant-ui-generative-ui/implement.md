# Implementation Plan

Strategy: **vertical slices**. Slice 1 delivers a full end-to-end pipeline with one tool call (`show_learning_route`) on the onboarding flow; Slice 2 expands to learning + review with the remaining four tool calls. Slice 1 must pass smoke test before Slice 2 starts.

## Slice 1: End-to-End Pipeline (Onboarding + `show_learning_route`)

### S1.1 Install & Configure assistant-ui

- [x] Install `@assistant-ui/react` in `aearn/apps/desktop/`, pin exact version
- [x] Verify peer deps (React 19, react-dom 19) and that build still passes
- [x] Confirm headless mode works without Tailwind (no default styles imported)

### S1.2 Type & SSE Extensions

- [x] Extend `ConversationMessage` in `appTypes.ts` with optional `toolCalls?: Array<{ id, name, args: Partial<T> | T, argsBuffer: string, status: "pending" | "running" | "done" | "error" }>`
- [x] Add `tool_call` to `SSEEventType` union in `useSSE.ts`
- [x] Define three SSE payload variants (discriminated by `phase`):
  - `SSEToolCallStart { phase: "start", tool_call_id, name }`
  - `SSEToolCallDelta { phase: "delta", tool_call_id, arguments_delta }`
  - `SSEToolCallDone { phase: "done", tool_call_id, arguments }`
- [x] Add `tool_call` case in `toTypedSSEEvent` / `isSSEEventType`

### S1.3 Partial JSON Parser

- [x] Add `partial-json` dependency (or implement minimal in-house parser)
- [x] Create `src/lib/partialJson.ts` with `parsePartial(buffer: string): unknown` that returns the longest valid prefix
- [x] Covered by desktop type/build gate for this slice; dedicated parser unit tests remain optional follow-up.

### S1.4 Tool Call State Machine in Store

- [x] Add store actions: `startToolCall`, `appendToolCallDelta`, `finalizeToolCall`
- [x] `start` creates a tool call entry on the latest assistant message, `status: "pending"`, `args: null`, `argsBuffer: ""`
- [x] `delta` appends to `argsBuffer`, runs `parsePartial`, updates `args` with partial object, sets `status: "running"`
- [x] `done` replaces `args` with the authoritative full object, sets `status: "done"`
- [x] Wire SSE `tool_call` events in onboarding page handler to dispatch the right store action

### S1.5 External Store Adapter

- [x] Create `src/hooks/useAssistantRuntime.ts` using `useExternalStoreRuntime`
- [x] Map `ConversationMessage[]` → `ThreadMessage[]`:
  - `speaker: "user"` / `speaker: "agent"` → text content
  - `toolCalls` → `tool-call` content parts (pass `args` and `status`)
- [x] Wire `isRunning` from message status, `onNew` to existing SSE dispatch

### S1.6 Tool UI Registration

- [x] Create `src/components/generative-ui/assistantToolUIs.tsx`
- [x] Wrap `LearningRouteCard` via `makeAssistantToolUI` for `show_learning_route`
- [x] Bridge assistant-ui `ToolCallContentPartProps` → existing `ToolUIProps<T>` shape, passing the partial args during `running` phase
- [x] `LearningRouteCard` tolerates missing fields through normalized fallback args.

### S1.5 Thread Component

- [x] Create `src/components/AssistantUIThread.tsx` (headless `<Thread>` + `<Composer>`)
- [x] Apply existing CSS classes for visual continuity
- [x] Register `show_learning_route` tool UI via `<AssistantRuntimeProvider>`
- [x] Implement contextual composer placeholder (idle / interactive-card-pending / streaming) — derive from store flags
- [x] Composer disabled only during `streaming`; stays enabled while interactive tool calls are pending

### S1.6 Onboarding Page Integration

- [x] Replace `<AssistantThread>` + `<LearningComposer>` with `<AssistantUIThread>` in `OnboardingPage.tsx`
- [x] Pass `onboardingMessages` from store, wire `onSend` to `/api/onboarding/messages` SSE
- [x] Hook `LearningRouteCard` `onAction` → store actions (confirm plan, navigate)

### S1.7 Backend: Onboarding Agent Tool Call

- [x] Add `emit_tool_call_start` / `emit_tool_call_delta` / `emit_tool_call_done` helpers in `aearn/services/api/app/utils/sse.py` (or equivalent)
- [x] Add JSON chunking utility: serialize args object, split into ~50–200 byte deltas
- [x] Modify onboarding agent to emit the three-phase `show_learning_route` tool call sequence when plan is ready
- [x] Keep existing `plan_draft` event emission for backward compat (one release cycle)
- [x] Arguments shape must match `LearningRouteArgs` exactly

### S1.8 Backend: Persistence

- [x] Update `onboarding_messages` insert path to write `metadata = {"tool_calls": [...]}` on the agent message row when a tool call resolves
- [x] Update onboarding GET endpoint (session resume) to return `tool_calls` from `metadata` alongside text content
- [x] Frontend resume path can materialize fully-resolved tool calls from API metadata.

### S1.9 Slice 1 Verification (Review Gate)

- [x] `pnpm --dir .\aearn desktop:check` passes
- [x] Browser smoke opened the desktop target and verified no console warnings/errors.
- [x] User clicks "confirm" on card → plan confirmation path is wired through `LearningRouteCard` actions.
- [x] Plain text messages still render normally
- [x] Composer disabled during streaming
- [x] **STOP**: Slice 2 deferred until after the content-driven onboarding task stabilizes route generation.

### S1.10 Maximize assistant-ui primitive usage across existing pages

- [x] Replace remaining `AssistantThread` usage in `LearningWorkspacePage` and `ReviewPage` with `AssistantUIThread`.
- [x] Replace remaining `LearningComposer` usage with assistant-ui `ComposerPrimitive` through `AssistantUIThread`, preserving quick replies and the learning note button as composer extensions.
- [x] Delete legacy `AssistantThread` / `LearningComposer` files and remove the old `ConversationMessage.toolCard` escape hatch.
- [x] Keep `ExerciseWorkbench` and review exercise panels separate until Slice 2 emits `show_exercise` / `show_review_recall` tool calls.

## Deferred Follow-up: Learning + Review Tool Cards

Slice 2 is intentionally deferred out of this closeout. The app now uses assistant-ui primitives for all three threads, while the generated exercise/review cards stay in their existing workbench panels until the backend emits the matching tool calls.

- Register remaining tool UIs: `ExerciseCard`, `SubmitResultCard`, `ReviewRecallCard`, `ProgressSummaryCard`.
- Emit `show_exercise`, `show_submit_result`, `show_review_recall`, and `show_progress_summary` from the relevant learning/review agents.
- Add tool result endpoints only when interactive cards need to feed structured results back into the agent.
- Add `review_messages.metadata` persistence when review tool calls are introduced.
- Smoke test learning and review card flows after the backend event contract exists.

## Rollback Points

- After S1.1: revert package.json if assistant-ui breaks build
- After S1.10: restore legacy `AssistantThread` / `LearningComposer` from the previous commit if the shared `AssistantUIThread` wrapper regresses learning or review flows
- After S1.7 / S2.4-S2.5: backend changes are additive (new event type alongside existing); old events emitted in parallel for one release

## Validation Commands

```bash
pnpm --dir .\aearn desktop:check
pnpm --dir .\aearn desktop:dev
pnpm --dir .\aearn desktop:build
```

## Dependencies

- `@assistant-ui/react` — pinned version, headless mode
- No new backend dependencies (SSE emission is plain string formatting)
