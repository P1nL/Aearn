# Chat-first conversation experience design

## Architecture Boundary

This task changes backend conversation behavior, not frontend rendering. The Onboarding page already displays whatever `POST /api/onboarding/messages` streams as `agent_message`, plus route-card `tool_call` events. The backend must therefore own the chat-first fix.

Primary files:

- `aearn/services/api/app/services/conversations/onboarding_conversation.py`
- `aearn/services/api/app/routes/onboarding.py`
- `aearn/services/api/app/agents/onboarding/onboarding_slot_extractor.py`
- `aearn/services/api/tests/test_onboarding_m2.py`
- `aearn/services/api/tests/test_onboarding_graph.py`

Secondary regression surface:

- `aearn/services/api/app/services/conversations/learning_conversation.py`
- `aearn/services/api/app/services/repositories/review_repository.py`
- `aearn/services/api/app/agents/notes/note_assist_agent.py`

## Claude Code / Codex-Like Conversation Model

This section is based on Anthropic Claude Code documentation, especially:

- `https://code.claude.com/docs/en/how-claude-code-works`
- `https://code.claude.com/docs/en/best-practices`
- `https://code.claude.com/docs/en/common-workflows`

The target model is not "always answer freely" and not "always fill a form". It is a layered assistant behavior:

1. Gather context before acting.
2. Answer, acknowledge, or act on the user's latest intent.
3. Plan when the task is complex.
4. Take action only when the task is ready for execution.
5. Verify results with tests, builds, screenshots, or other readable evidence.
6. Stay interruptible and steerable; user corrections should update the approach, not restart the workflow.
7. Keep workflow state in the background.
8. Ask one high-value follow-up only when it moves the task forward.
9. Use tools or structured state when needed, but do not expose the internal checklist as the conversation.
10. Refuse or boundary unsafe/unsupported actions clearly, then offer the closest viable next step.

For Aearn, this means Onboarding can still collect `language`, `goal_text`, and `target_level`, but it should feel like a learning coach helping the user choose a path, not a form that overwrites every message with the next required field.

## Current Failure Mode

The Onboarding generator prompt already says to answer the user's latest question first. However, `normalize_onboarding_agent_message()` currently replaces visible text whenever there is a structured clarification question and the generated text does not contain that exact question. This makes the slot gate overtake normal conversation:

1. User asks an advisory question such as "agent 一般用什么语言".
2. Slot extraction keeps `language` ambiguous or missing.
3. The generated conversational answer is replaced by `_missing_slot_followup_message(slots)`.
4. The user sees only the same language-slot question.

## Proposed Behavior

Normalize should separate two responsibilities:

- Safety blocking: keep preventing visible text from claiming route readiness when `route_ready=false`.
- Chat continuity: preserve non-route-ready conversational text, and append or naturally include the missing-slot follow-up instead of erasing the answer.

The visible behavior should follow an intent matrix:

| User intent | Expected visible behavior | Workflow behavior |
|---|---|---|
| Advisory question | Give a recommendation or explanation first, then one natural follow-up | Continue background slot extraction; no route if required slots are missing |
| Capability question | Explain what Aearn / the agent / a language can do | Do not force a slot prompt unless the reply naturally transitions |
| Comparison question | Pick a recommended first path with reasoning | May ask the next route-building question after the recommendation |
| Direct slot answer | Acknowledge and ask the next missing slot | Update slots and route readiness normally |
| Plan request | Generate route only if required slots are ready; otherwise explain what is missing | Preserve existing `show_learning_route` gate |
| Revision request | Acknowledge the change and regenerate only when the revised slots are safe | Preserve latest-card-wins behavior |
| Supported mainstream language choice | For TypeScript / TS, SQL, Go, or C#, explain the public route and teaching-grade runtime boundary directly | Emit route only when required slots are ready; persist the selected public `language` |
| Unsupported choice | Return existing `LANGUAGE_NOT_SUPPORTED` SSE error for C++ or Rust | Do not emit route text or card |
| Model failure | Return existing `MODEL_UNAVAILABLE` | No keyword fallback |

An acceptable response shape for advisory inputs is:

```text
做 AI Agent 通常优先用 Python；如果偏网页产品，也可以用 JavaScript/TypeScript。你如果想先做可运行的 Agent，我建议先从 Python 入手。接下来你更想偏自动化脚本、网页助手，还是本地工具型 Agent？
```

The exact wording can vary, but the response must first answer the user's intent before collecting route-building details.

## Data Flow

1. `prepare_onboarding_message()` stores the user message and loads conversation context.
2. `extract_slots()` performs model-backed structured extraction.
3. `normalize_extracted_slots()` enforces readiness from structured slot statuses.
4. `_should_generate_onboarding_route()` decides whether to generate a route card.
5. `start_onboarding_generation()` streams normal text when route generation is not ready.
6. `normalize_onboarding_agent_message()` post-processes the visible text:
   - If `route_ready=true`, leave route-ready message unchanged.
   - If generated text claims route readiness while `route_ready=false`, replace it with the missing-slot follow-up.
   - If generated text is otherwise valid and a clarification is required, preserve the generated answer and append the missing-slot follow-up only when the follow-up is absent.
   - If generated text is empty, keep existing model-unavailable handling.
7. Persist the final visible text and any route-card metadata.

## Prompt / Policy Update

The Onboarding conversation prompt should explicitly state the response policy:

- Treat extracted slots as private workflow state, not as the whole visible conversation.
- For advisory and capability questions, answer first and transition second.
- For direct answers to prior follow-ups, move to the next missing route-building detail.
- Ask at most one follow-up question.
- Do not repeat the same slot question if the user is asking about options, concepts, or capabilities.

It should also explicitly recognize AI Agent / agent advisory questions:

- Recommend Python first for backend/tooling/automation agents.
- Mention JavaScript/TypeScript for web-product agents, and explain that TypeScript is an independent public route with a single-file Node/TypeScript teaching runner.
- Continue with one natural follow-up question that helps choose a supported first route.

This prompt update supports natural generation, while normalization ensures safety and continuity.

## Compatibility

- `LANGUAGE_NOT_SUPPORTED` remains the error path for C++ and Rust.
- The public course / route selection set is `python`, `javascript`, `typescript`, `sql`, `html_css`, `java`, `go`, and `csharp`.
- Runtime capability still has teaching-grade limits: TypeScript uses `node_typescript_test`, SQL uses `sql_query_test`, Java/Go/C# use `managed_compiled_test`, and none of these imply arbitrary project execution or dependency installation.
- C++ may remain as an internal/planned `compiled_sandbox_later` runtime profile for boundary disclosure, but it is not an active public course or onboarding route.
- `MODEL_UNAVAILABLE` remains the failure path for unavailable slot extraction or normal generation.
- `show_learning_route` is still emitted only when required slots are ready.
- Existing Learning, Review, and Notes judgement behavior remains unchanged unless tests reveal the same replacement defect.
- No deterministic keyword-based slot parser is introduced. Tests may use monkeypatched model outputs to assert server behavior, but production routing still depends on the existing model-backed extraction/generation contract.

## Learning Page Error Copy

The Learning page composer still uses the existing SSE contract and does not become a general fallback chatbot. The frontend may, however, translate stable error codes into clearer user-facing explanations:

- `MODEL_UNAVAILABLE`: explain that model service/configuration is unavailable, so no new Agent reply was generated.
- `STREAM_INCOMPLETE`: explain that the SSE stream ended without a terminal `done` or `error` event.
- `STREAM_ERROR`, `STREAM_UNAVAILABLE`, and `STREAM_HTTP_ERROR`: explain connection or SSE availability, while preserving the stable error code and backend message.

This is a display-layer clarification only. It must not synthesize assistant content, mark the stream `done`, or write a successful `LearningMessage`.

## Trade-offs

- Appending a follow-up can occasionally make the response a little longer, but it preserves user trust by not discarding answers.
- Not adding deterministic slot parsing keeps the model-dependency contract intact, but means model quality still matters for ideal wording.
- Fixing Onboarding first is lower risk than converting every page to fully open-ended chat in one task.

## Rollback

Revert the `normalize_onboarding_agent_message()` behavior and prompt additions if the change causes route-card generation, unsupported-language handling, or ambiguous-slot blocking regressions. Tests should make those regressions visible before shipping.
