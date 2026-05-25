# Design

## Boundary

This task spans both frontend and backend:

**Frontend** (`aearn/apps/desktop/src/`):
- Replace custom `AssistantThread` + `LearningComposer` with assistant-ui primitives
- Wire generative UI components via `makeAssistantToolUI`
- Add `useExternalStoreRuntime` adapter for Zustand
- Styling: either Tailwind adoption or headless mode with existing CSS

**Backend** (`aearn/services/api/app/`):
- Modify agent outputs to emit tool calls for structured content
- Keep plain text streaming for conversational responses

Must not change:
- FSRS scheduling logic
- Database tables (no new tables; one additive column on `review_messages`)
- Protected HTML prototype
- Existing API endpoint URLs (only response format changes)

## Persistence of Tool Calls

Tool calls completed during a conversation turn are persisted on the message row so session resume renders the same cards without replaying the stream.

- `onboarding_messages.metadata` (already `jsonb`): write `{"tool_calls": [{id, name, args, status}]}` on the agent message row when a tool call resolves.
- `review_messages`: add new column `metadata jsonb NULL` (additive, backward compatible). Same shape as onboarding.
- On session resume, the API returns `tool_calls` alongside text content; the frontend creates fully-resolved tool call entries (skipping `pending`/`running` phases).
- `homeConversation` (learning page) is currently in-memory only; tool call persistence for learning is out of scope for this task and tracked separately.

## Architecture

```text
┌─────────────────────────────────────────────────────┐
│  assistant-ui Runtime (useExternalStoreRuntime)      │
│                                                     │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │ Zustand Store │◄──►│ ExternalStoreAdapter     │   │
│  │ (source of   │    │ - messages → ThreadMessage│   │
│  │  truth)       │    │ - send → useSSE dispatch │   │
│  └──────────────┘    └──────────────────────────┘   │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ <Thread>                                      │   │
│  │   <ThreadMessages>                            │   │
│  │     <UserMessage />                           │   │
│  │     <AssistantMessage />                      │   │
│  │     <ToolUI name="show_exercise">             │   │
│  │       <ExerciseCard />  ← generative UI       │   │
│  │     </ToolUI>                                 │   │
│  │   </ThreadMessages>                           │   │
│  │   <Composer />                                │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Styling Decision

Two options:

### Option A: Adopt Tailwind (recommended)
- Install `tailwindcss` + `@tailwindcss/vite` + `autoprefixer`
- Use assistant-ui's default styled components
- Gradually migrate existing CSS to Tailwind utilities
- Risk: existing CSS may conflict; needs careful `@layer` ordering

### Option B: Headless mode
- Use `@assistant-ui/react` primitives only (no default styles)
- Keep all existing CSS, add new classes for assistant-ui slots
- More work upfront but zero conflict risk
- Risk: must manually style every assistant-ui primitive

Recommendation: Start with Option B (headless) to avoid CSS conflicts in MVP, then migrate to Tailwind in a follow-up task.

## External Store Adapter

The adapter bridges Zustand → assistant-ui runtime:

```ts
// Pseudocode
const runtime = useExternalStoreRuntime({
  messages: zustandMessages.map(toThreadMessage),
  isRunning: composerStreaming,
  onNew: (message) => {
    // Dispatch to useSSE via existing flow
    handleComposerSubmit(message.content[0].text);
  },
});
```

Key mapping:
- `ConversationMessage { speaker: "agent", text }` → `ThreadMessage { role: "assistant", content: [{ type: "text", text }] }`
- `ConversationMessage { speaker: "user", text }` → `ThreadMessage { role: "user", content: [{ type: "text", text }] }`
- Tool call messages → `ThreadMessage { role: "assistant", content: [{ type: "tool-call", toolName, args }] }`

## Backend Tool Call Format

Currently agents emit plain text via SSE `agent_message` events. For generative UI, structured content becomes a tool call:

```json
{
  "type": "agent_message",
  "data": {
    "delta": "",
    "content": "让我为你生成学习路线。",
    "tool_calls": [
      {
        "id": "tc_001",
        "name": "show_learning_route",
        "arguments": { "plan_id": "...", "modules": [...] }
      }
    ]
  }
}
```

The frontend parses `tool_calls` from the SSE event data and renders the corresponding component.

Alternative: emit tool calls as a separate SSE event type `tool_call` (cleaner separation). Decision: use separate event type to avoid breaking existing `agent_message` consumers.

New SSE event:
```
event: tool_call
data: {"tool_call_id": "tc_001", "name": "show_learning_route", "arguments": {...}, "status": "done"}
```

## Tool Call Streaming Protocol

Tool call arguments stream incrementally so cards show a loading skeleton while args arrive.

Three SSE event sub-types over the existing `tool_call` event channel, distinguished by a `phase` field:

```
event: tool_call
data: {"phase": "start", "tool_call_id": "tc_001", "name": "show_learning_route"}

event: tool_call
data: {"phase": "delta", "tool_call_id": "tc_001", "arguments_delta": "{\"plan_id\":\"p_"}

event: tool_call
data: {"phase": "delta", "tool_call_id": "tc_001", "arguments_delta": "abc\",\"modules\":["}

event: tool_call
data: {"phase": "done", "tool_call_id": "tc_001", "arguments": {"plan_id": "p_abc", "modules": [...]}}
```

Frontend state machine:
- `start` → create tool call entry with `status: "pending"`, args = `null` → card renders skeleton
- `delta` → append `arguments_delta` to a per-id buffer, attempt incremental parse with a tolerant JSON parser; if parse succeeds, set `status: "running"` with partial args → card renders progressive content
- `done` → replace partial args with the authoritative full `arguments`, set `status: "done"` → card finalizes

Tolerant parsing: use a partial-JSON parser (e.g., `partial-json` npm package, or a small in-house implementation) that returns the longest valid prefix. If a delta arrives mid-string, the buffer is held until the next delta closes the literal.

Backend emission:
- The agent's structured-output call (LM with JSON schema) returns the full args object at once today. To enable streaming, the backend serializes the object and chunks the resulting JSON string into ~50–200 byte deltas before SSE emission.
- This is not "true" token-level streaming from the LM, but it gives the frontend an honest progressive render and keeps the contract correct for a future LM that does stream tool args.
- Each card's component receives the partially-parsed object and must tolerate missing fields during the `running` phase.

## Backward Compatibility for `plan_draft`

The existing onboarding flow emits a custom `plan_draft` SSE event. Migration strategy:

- **Slice 1**: backend dual-emits both `plan_draft` AND `show_learning_route` tool call. Frontend consumes only the tool call going forward.
- **Slice 2 / follow-up task**: remove `plan_draft` emission once the new pipeline is verified.
- Rationale: MVP iteration is still active; keeping `plan_draft` for one release gives a quick rollback path if the assistant-ui pipeline regresses. Cost is one extra `emit` line in the onboarding agent.

## Tool Call → Component Mapping

| Tool Name | Component | When Emitted | Result Type |
|-----------|-----------|--------------|-------------|
| `show_learning_route` | `LearningRouteCard` | After plan confirmation or on session resume | display |
| `show_exercise` | `ExerciseCard` | When agent presents a new exercise | interactive |
| `show_submit_result` | `SubmitResultCard` | After exercise submission is graded | display |
| `show_review_recall` | `ReviewRecallCard` | At start of review session | interactive |
| `show_progress_summary` | `ProgressSummaryCard` | In learning thread after a module completes | display |

## Tool Call Result Handling

Two categories with different result-handling strategies:

**Display-only tools** (`show_learning_route`, `show_submit_result`, `show_progress_summary`):
- User actions (confirm plan, click "next", navigate) trigger frontend side effects only: existing API calls (`POST /api/plans`, `POST /api/sessions`), store mutations, route changes.
- No tool result is sent back to the agent. The next user message carries any needed context (e.g., "我确认这个计划").
- Existing endpoints (`/api/plans`, `/api/sessions/{id}/submit`) remain unchanged.

**Interactive tools** (`show_exercise`, `show_review_recall`):
- User produces a structured result (submitted code, recall confidence) that the agent must see to continue the conversation coherently.
- Frontend posts the result to a new endpoint per flow:
  - `POST /api/onboarding/{conversation_id}/tool_result`
  - `POST /api/sessions/{session_id}/tool_result`
  - `POST /api/reviews/{session_id}/tool_result`
- Request body: `{ tool_call_id, name, result }`. The endpoint writes a `tool` role message into the conversation history (extending the `role` CHECK constraint), then resumes the agent stream as a normal SSE response.
- Reuses existing scoring logic: `show_exercise` result delegates to current submit pipeline, `show_review_recall` result feeds into FSRS rating logic.

## Composer State During Interactive Cards

Composer stays enabled while interactive cards (`show_exercise`, `show_review_recall`) are pending so users can ask the AI questions mid-task without losing the chat-first feel.

- Placeholder switches contextually:
  - Idle: "向 AI 提问..."
  - Interactive card pending: "卡片操作中，可输入消息向 AI 提问..."
  - Streaming: composer disabled until `done`/`error` (existing behavior).
- Two parallel paths:
  - Card submit button → `POST /api/.../tool_result` (structured result feeds agent as tool message).
  - Composer send → `POST /api/.../messages` (free-form user turn).
- Concurrency: a pending tool call is not auto-cancelled when the user sends a free-form message. The agent receives the user message as a normal turn; the unresolved tool call remains in store with `status: "pending"` and the user can return to complete it. If the agent's reply emits a new tool call of the same name, the prior one is marked `status: "superseded"` and visually grayed.

## Risks

- assistant-ui version churn: pin to a specific version, test before upgrading.
- Headless mode may not support all features (e.g., branch switching, edit). Acceptable for MVP.
- Tool call streaming: assistant-ui expects OpenAI-format tool call deltas. Our SSE format differs — the adapter must translate.
- Performance: rendering Monaco editor inside a thread message could be heavy. Mitigation: lazy-load Monaco only for active exercise cards.
