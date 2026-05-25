# Implementation Plan

Strategy: **vertical slices**. Slice 1 delivers a full end-to-end pipeline with one tool call (`show_learning_route`) on the onboarding flow; Slice 2 expands to learning + review with the remaining four tool calls. Slice 1 must pass smoke test before Slice 2 starts.

## Slice 1: End-to-End Pipeline (Onboarding + `show_learning_route`)

### S1.1 Install & Configure assistant-ui

- [ ] Install `@assistant-ui/react` in `aearn/apps/desktop/`, pin exact version
- [ ] Verify peer deps (React 19, react-dom 19) and that build still passes
- [ ] Confirm headless mode works without Tailwind (no default styles imported)

### S1.2 Type & SSE Extensions

- [ ] Extend `ConversationMessage` in `appTypes.ts` with optional `toolCalls?: Array<{ id, name, args: Partial<T> | T, argsBuffer: string, status: "pending" | "running" | "done" | "error" }>`
- [ ] Add `tool_call` to `SSEEventType` union in `useSSE.ts`
- [ ] Define three SSE payload variants (discriminated by `phase`):
  - `SSEToolCallStart { phase: "start", tool_call_id, name }`
  - `SSEToolCallDelta { phase: "delta", tool_call_id, arguments_delta }`
  - `SSEToolCallDone { phase: "done", tool_call_id, arguments }`
- [ ] Add `tool_call` case in `toTypedSSEEvent` / `isSSEEventType`

### S1.3 Partial JSON Parser

- [ ] Add `partial-json` dependency (or implement minimal in-house parser)
- [ ] Create `src/lib/partialJson.ts` with `parsePartial(buffer: string): unknown` that returns the longest valid prefix
- [ ] Unit-test edge cases: mid-string, mid-key, mid-number, escaped chars, nested arrays

### S1.4 Tool Call State Machine in Store

- [ ] Add store actions: `startToolCall`, `appendToolCallDelta`, `finalizeToolCall`
- [ ] `start` creates a tool call entry on the latest assistant message, `status: "pending"`, `args: null`, `argsBuffer: ""`
- [ ] `delta` appends to `argsBuffer`, runs `parsePartial`, updates `args` with partial object, sets `status: "running"`
- [ ] `done` replaces `args` with the authoritative full object, sets `status: "done"`
- [ ] Wire SSE `tool_call` events in onboarding page handler to dispatch the right store action

### S1.5 External Store Adapter

- [ ] Create `src/hooks/useAssistantRuntime.ts` using `useExternalStoreRuntime`
- [ ] Map `ConversationMessage[]` → `ThreadMessage[]`:
  - `speaker: "user"` / `speaker: "agent"` → text content
  - `toolCalls` → `tool-call` content parts (pass `args` and `status`)
- [ ] Wire `isRunning` from message status, `onNew` to existing SSE dispatch

### S1.6 Tool UI Registration

- [ ] Create `src/components/generative-ui/assistantToolUIs.tsx`
- [ ] Wrap `LearningRouteCard` via `makeAssistantToolUI` for `show_learning_route`
- [ ] Bridge assistant-ui `ToolCallContentPartProps` → existing `ToolUIProps<T>` shape, passing the partial args during `running` phase
- [ ] `LearningRouteCard` must tolerate missing fields: render skeleton placeholders when `status: "pending"` or fields absent

### S1.5 Thread Component

- [ ] Create `src/components/AssistantUIThread.tsx` (headless `<Thread>` + `<Composer>`)
- [ ] Apply existing CSS classes for visual continuity
- [ ] Register `show_learning_route` tool UI via `<AssistantRuntimeProvider>`
- [ ] Implement contextual composer placeholder (idle / interactive-card-pending / streaming) — derive from store flags
- [ ] Composer disabled only during `streaming`; stays enabled while interactive tool calls are pending

### S1.6 Onboarding Page Integration

- [ ] Replace `<AssistantThread>` + `<LearningComposer>` with `<AssistantUIThread>` in `OnboardingPage.tsx`
- [ ] Pass `onboardingMessages` from store, wire `onSend` to `/api/onboarding/messages` SSE
- [ ] Hook `LearningRouteCard` `onAction` → store actions (confirm plan, navigate)

### S1.7 Backend: Onboarding Agent Tool Call

- [ ] Add `emit_tool_call_start` / `emit_tool_call_delta` / `emit_tool_call_done` helpers in `aearn/services/api/app/utils/sse.py` (or equivalent)
- [ ] Add JSON chunking utility: serialize args object, split into ~50–200 byte deltas
- [ ] Modify onboarding agent to emit the three-phase `show_learning_route` tool call sequence when plan is ready
- [ ] Keep existing `plan_draft` event emission for backward compat (one release cycle)
- [ ] Arguments shape must match `LearningRouteArgs` exactly

### S1.8 Backend: Persistence

- [ ] Update `onboarding_messages` insert path to write `metadata = {"tool_calls": [...]}` on the agent message row when a tool call resolves
- [ ] Update onboarding GET endpoint (session resume) to return `tool_calls` from `metadata` alongside text content
- [ ] Frontend resume path: when receiving `tool_calls` from API, create fully-resolved entries with `status: "done"` (skip `pending`/`running`)

### S1.9 Slice 1 Verification (Review Gate)

- [ ] `pnpm --dir .\aearn desktop:check` passes
- [ ] Browser smoke test: onboarding chat → AI emits `show_learning_route` → card renders
- [ ] User clicks "confirm" on card → plan confirmed → navigates to learning
- [ ] Plain text messages still render normally
- [ ] Composer disabled during streaming
- [ ] **STOP**: confirm with user before proceeding to Slice 2

## Slice 2: Expand to Learning + Review (4 More Tool Calls)

### S2.1 Register Remaining Tool UIs

- [ ] Wrap `ExerciseCard`, `SubmitResultCard`, `ReviewRecallCard`, `ProgressSummaryCard` via `makeAssistantToolUI`
- [ ] Add to `<AssistantRuntimeProvider>` tools list

### S2.2 Learning Page Integration

- [ ] Replace thread in `LearningWorkspacePage.tsx` with `<AssistantUIThread>`
- [ ] Pass `homeConversation`, wire `onSend` to learning SSE endpoint
- [ ] Wire `ExerciseCard` actions (run / submit / hint) to existing API wrappers
- [ ] Wire `SubmitResultCard` actions (next / explain) to store

### S2.3 Review Page Integration

- [ ] Replace thread in `ReviewPage.tsx` with `<AssistantUIThread>`
- [ ] Pass `reviewConversation`, wire `onSend` to `/api/reviews/{session_id}/messages`
- [ ] Wire `ReviewRecallCard` confidence buttons to existing review API

### S2.4 Backend: Learning Agent Tool Calls

- [ ] Modify learning agent to emit `show_exercise` when presenting new exercise
- [ ] Modify learning agent to emit `show_submit_result` after grading
- [ ] Arguments shapes match `ExerciseCardArgs` / `SubmitResultArgs`

### S2.5 Backend: Review Agent Tool Call

- [ ] Modify review agent to emit `show_review_recall` at session start
- [ ] Modify review agent to emit `show_exercise` + `show_submit_result` during review

### S2.6 Backend: Tool Result Endpoints

- [ ] Add migration: extend `role` CHECK constraint on `onboarding_messages` and `review_messages` to allow `'tool'`
- [ ] Add `metadata jsonb NULL` column to `review_messages` (additive)
- [ ] Add `POST /api/onboarding/{conversation_id}/tool_result` route in `routes/onboarding.py`
- [ ] Add `POST /api/sessions/{session_id}/tool_result` route in `routes/learning_sessions.py`
- [ ] Add `POST /api/reviews/{session_id}/tool_result` route in `routes/reviews.py`
- [ ] Each endpoint: accepts `{ tool_call_id, name, result }`, persists tool message, resumes agent stream as SSE response
- [ ] `show_exercise` result delegates to existing submit pipeline; `show_review_recall` result feeds FSRS rating

### S2.7 Frontend: Tool Result Dispatch

- [ ] Wire `ExerciseCard` submit → `POST /api/sessions/{id}/tool_result`
- [ ] Wire `ReviewRecallCard` confidence buttons → `POST /api/reviews/{id}/tool_result`
- [ ] Display-only cards (`LearningRouteCard`, `SubmitResultCard`, `ProgressSummaryCard`) keep existing API calls (no tool_result endpoint)

### S2.6 Progress Summary Wiring

- [ ] Emit `show_progress_summary` from dashboard endpoint (or after module completion)
- [ ] Decide whether this surfaces in chat thread or as a side panel — defer to design.md if unclear

### S2.7 Slice 2 Verification

- [ ] `pnpm --dir .\aearn desktop:check` passes
- [ ] Browser smoke test: learning flow renders `ExerciseCard` + `SubmitResultCard`
- [ ] Browser smoke test: review flow renders `ReviewRecallCard` → exercise → result
- [ ] No regression: notes, settings, sidebar navigation
- [ ] Streaming works on all three pages

## Rollback Points

- After S1.1: revert package.json if assistant-ui breaks build
- After S1.6: keep old `AssistantThread` component as backup until Slice 2 finishes
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
