# Chat-first conversation experience

## Goal

Make Aearn's conversational surfaces feel closer to Claude Code / Codex: the agent should act like a collaborative assistant that understands the user's current intent, answers or acts on that intent first, and only then advances the product workflow when it is helpful. The immediate visible defect is the Onboarding page repeatedly replacing advisory questions like "agent generally uses what language?" with a fixed language-slot question, but the product requirement is broader than those two strings.

## Confirmed Facts

- External source: Anthropic describes Claude Code as an agentic assistant that works through context gathering, action, and verification, while staying interruptible and steerable by the user.
- External source: Anthropic's best-practice workflow separates explore, plan, implement, and verify phases instead of jumping directly to execution.
- External source: Anthropic says Claude Code is conversational: users can start with an imperfect request, correct it, and the agent adjusts instead of forcing a restart.
- External source: Anthropic recommends asking Claude questions as one would ask a senior engineer, and for larger features recommends an interview/spec phase before execution.
- The current Onboarding visible response is normalized by `normalize_onboarding_agent_message()` in `aearn/services/api/app/services/conversations/onboarding_conversation.py`.
- `REQUIRED_SLOT_PRIORITY = ("language", "goal_text", "target_level")`, so an unconfirmed `language` slot is the first clarification target.
- `onboarding_slot_extractor.py` intentionally treats broad goals such as "AI" and multi-meaning directions as ambiguous instead of guessing a supported language.
- `POST /api/onboarding/messages` currently depends on model-backed slot extraction and normal conversation generation; `docs/architecture/api-contract.md` forbids keyword or deterministic slot fallback when the model is unavailable.
- Learning and Review pages also use structured judgement, but they do not currently have the same global visible-message replacement path as Onboarding.

## Requirements

- The conversation model must be chat-first, workflow-aware. Slot extraction and route readiness are background state, not the visible conversation itself.
- The agent must distinguish at least these user intents at the visible behavior level:
  - advisory question: user asks for recommendation, comparison, explanation, or "what should I choose?"
  - capability question: user asks what Aearn, agent, a language, or a workflow can do.
  - slot answer: user is directly answering a prior question about language, goal, level, time, or focus.
  - plan request: user asks to generate/start/confirm a learning route.
  - revision request: user asks to change an already suggested direction, level, or time budget.
  - unsupported choice: user explicitly chooses an unsupported public course language.
  - model/runtime failure: the model cannot produce required structured output or visible response.
- Onboarding must preserve chat-first replies for advisory, comparison, and product-choice questions. Examples: "agent 一般用什么", "agent 一般用什么语言", "AI Agent 学什么语言", "Python 和 JavaScript 哪个更适合做 agent".
- Onboarding may still ask for missing route-building information, but it must do so as a natural follow-up after answering the user's latest question, not by erasing the answer.
- The visible response pattern should normally be: answer/acknowledge the user's latest intent -> connect it to the current learning context -> ask at most one useful next question if needed.
- The agent must avoid survey-like repetition: it should not repeatedly ask the same slot question when the user is asking meta/advisory questions or trying to understand options.
- Route generation safety must remain intact: if required slots are ambiguous or a language is truly unsupported/unbridged, no `show_learning_route` tool call is emitted and no `plan_draft` is stashed.
- TypeScript / TS, SQL, Go, and C# must be treated as supported public route languages alongside Python, JavaScript, HTML/CSS, and Java.
- The supported-language boundary must stay explicit: public course selection, runtime capability, teaching-grade execution limits, and unsupported route choices are separate product states.
- C++ and Rust must keep returning the existing `LANGUAGE_NOT_SUPPORTED` error behavior when the user explicitly selects either language.
- Model unavailability must still return `MODEL_UNAVAILABLE`; this task must not add keyword slot parsing or deterministic conversation fallback.
- Learning, Review, and Notes flows must not regress their existing structured judgement safeguards.
- Learning page composer errors must explain the concrete stable error class instead of collapsing `MODEL_UNAVAILABLE`, incomplete streams, and connection failures into one generic "answer incomplete" message.

## Acceptance Criteria

- [ ] Onboarding has a documented response policy that treats slot extraction as background state and keeps visible replies chat-first.
- [ ] Advisory questions, including but not limited to "agent 一般用什么" and "agent 一般用什么语言", receive a direct recommendation or explanation before any route-building follow-up.
- [ ] Capability questions such as "你能做什么", "Aearn 能帮我什么", or "agent 是什么" are answered as product/concept questions, not converted into an immediate language-slot prompt.
- [ ] Comparison questions such as "Python 和 JavaScript 哪个更适合做 agent" receive a recommended first path and reasoning, then at most one follow-up question.
- [ ] Direct slot answers still advance the workflow. If the user says "Python", "零基础", or "每天 1 小时", the system may ask the next missing route-building question.
- [ ] Repeated advisory/meta questions do not produce the same fixed slot question on every turn.
- [ ] Onboarding no longer replaces a valid non-route-ready conversational answer with only "您想用哪种编程语言学习 agent？目前支持 ...".
- [ ] When the model incorrectly claims enough information or mentions route-card generation while required slots are ambiguous, the existing protective normalization still blocks route-ready copy.
- [ ] Ambiguous required slots and ambiguous optional slots still prevent route generation and keep persisted `extracted_context.plan_ready=false`.
- [ ] TypeScript / TS with confirmed required slots generates a TypeScript route, not `LANGUAGE_NOT_SUPPORTED` and not a JavaScript bridge route.
- [ ] TypeScript / TS with missing or ambiguous required slots still does not emit `show_learning_route` and does not stash `plan_draft`.
- [ ] Existing unsupported-language SSE error behavior remains unchanged for C++ and Rust.
- [ ] Support-language documentation states the public route languages as `python`, `javascript`, `typescript`, `sql`, `html_css`, `java`, `go`, and `csharp`, with C++ and Rust explicitly unsupported for public routes.
- [ ] Learning page SSE error bubbles branch on stable `error.code`; `MODEL_UNAVAILABLE` explains model service/config unavailability, `STREAM_INCOMPLETE` explains a stream that ended without a terminal event, and connection/SSE errors explain API/SSE availability.
- [ ] Focused backend tests cover the conversation-intent matrix: advisory question, capability question, comparison question, direct slot answer, route-ready blocking, ambiguous slot clarification, unsupported-language behavior, and model-unavailable behavior where practical.
- [ ] No frontend-only workaround is introduced; the backend remains the owner of conversation state and route-generation readiness.

## Out of Scope

- Rebuilding the desktop UI layout.
- Adding C++ or Rust public course support.
- Changing `PlanDraft`, `LearningPlan`, `Attempt`, `ReviewState`, or FSRS data contracts.
- Making Learning and Review pages fully open-ended general chat assistants in this task.

## Source Basis

- https://code.claude.com/docs/en/how-claude-code-works
- https://code.claude.com/docs/en/best-practices
- https://code.claude.com/docs/en/common-workflows
