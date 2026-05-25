# Technical Design: Concept-first learning workspace

## Status

Planning artifact. Implementation must not start until the user reviews this plan and approves `task.py start`.

## Scope And Boundaries

- This change applies only to `session_type = 'learn'` sessions in the learning workspace.
- Onboarding/profile setup and review sessions remain separate flows and must never be included in knowledge-point learning history.
- Existing exercise execution, submit, hint, explain-error, and post-attempt explanation-check endpoints remain authoritative after practice is unlocked.
- The desktop must continue to render the conversation through assistant-ui primitives and keep the existing POST-based SSE transport.

## Target Learning Flow

```text
start / resume learn session
  -> concept_intro
  -> concept_qna
  -> readiness_check
       -> passed: practice_support + generated exercise UI
       -> incomplete: remain in readiness_check + offer generated history-reference UI
  -> practice_support
```

- `concept_intro` introduces the knowledge point, source-attributed outline, and an initial interaction question. It does not request the final Feynman explanation.
- `concept_qna` covers curated sub-points in order while allowing learner questions.
- `readiness_check` requests one Feynman-style explanation only after all curated sub-points have been covered.
- A learner can request practice from a concept stage. This enters `practice_support` with an `early_request` unlock reason and incomplete-progress notice embedded in the exercise card.
- A failed Feynman explanation does not initiate mandatory re-teaching. It exposes a `查看相关学习对话` action that opens the history-reference tool UI.

## Persisted Data Design

### Curated Lesson Outline

Extend `knowledge_points` with MVP-local lesson content rather than runtime web retrieval:

- `lesson_outline_json jsonb NOT NULL DEFAULT '[]'::jsonb`: ordered sub-points with stable IDs, titles, and concise teaching notes.
- `lesson_sources_json jsonb NOT NULL DEFAULT '[]'::jsonb`: official-document source titles and URLs/section references used to curate the outline.

Bootstrap/seed data owns these values. The runtime reads and attributes them but does not fetch external documentation.

### Compact Session Stage

Extend `learning_sessions` for learn-session progression:

- `learning_stage text`: `concept_intro`, `concept_qna`, `readiness_check`, or `practice_support`.
- `learning_stage_state_json jsonb`: compact state containing `covered_subpoint_ids`, `feynman_status`, `practice_unlock_reason`, `learning_incomplete`, and the short concept summary required for early practice.

This state is restored by start/resume contracts. It is not reconstructed by replaying all learning messages.

### Learning Conversation History

Add a dedicated `learning_messages` table:

- `id uuid`, `session_id uuid`, `knowledge_point_id uuid`, `role text CHECK (role IN ('user', 'agent'))`, `content text`, `client_message_id text`, `metadata jsonb`, `created_at timestamptz`.
- Index by `(knowledge_point_id, session_id, created_at)` and enforce user-message idempotency where `client_message_id` is provided.
- Store the initial concept-introduction agent message as the first learning message so history is complete.
- Store optional generative UI tool call metadata in the same shape already used by onboarding message restoration.

Because this table is written only by learn-session paths, history retrieval cannot accidentally include onboarding or review messages.

## API Contracts

### Start Or Re-enter Learning Session

Update `POST /api/learning-sessions/start`:

- Return `learning_stage`, `learning_stage_state`, source-attributed `lesson_outline`, and `exercise: null | LearningExercise`.
- A new concept-stage session returns `exercise: null` and a persisted concept-first `initial_agent_message`.
- A resumed session returns an exercise only if its persisted stage already unlocked practice.
- Do not send starter code or exercise prompt into a concept-stage frontend response or concept-stage model context.

### Learning Message Stream

Keep `POST /api/learning-sessions/{session_id}/messages` as the conversation endpoint:

- Persist each user turn and completed agent turn in `learning_messages`.
- Build prompts from `learning_stage`, compact progress, and `lesson_outline`; include exercise context only in `practice_support`.
- When a stage transition unlocks practice, return a session patch and emit a `show_code_exercise` tool call whose arguments include the unlocked exercise and any early-practice notice.
- When the learner requests history after an incomplete Feynman check, emit or append a `show_learning_history` tool UI part backed by the history API result.
- Failed/incomplete generation must not persist a false stage transition or duplicate a message on retry.

### History Reference

Add a read API such as:

```text
GET /api/learning-sessions/history?user_id={user_id}&knowledge_point_id={knowledge_point_id}&cursor={cursor}
```

- Scope by authenticated/selected user, `session_type = 'learn'`, and `entry_point = knowledge_point_id`.
- Return learning sessions ordered with the active/current session first, then newest prior sessions.
- Group AI/learner message turns by session; support cursor-based loading so the UI can reach all prior sessions without dumping them into initial resume.
- Return no onboarding or review data and no exercise solution/internal prompt material.

## Desktop And Generative UI Design

- Generalize the existing assistant-ui tool event plumbing currently used for onboarding so learning messages can carry `toolCalls`.
- Add `show_code_exercise` tool UI that renders the existing exercise interactions inside the conversation timeline, with early-practice summary/notice when applicable.
- Add `show_learning_history` tool UI that renders a compact session-grouped dialogue reference card. Default presentation expands the active/current session and collapses earlier sessions; a load-more action reaches all prior learning sessions.
- `LearningWorkspacePage` must no longer derive a visible workbench from `session.exercise` at entry. It renders practice only from persisted unlock state and the generated tool UI message.
- Durable learning stage and history remain backend-owned; open/collapsed card state and in-progress display state remain frontend-owned.

## Compatibility And Migration

- Existing active learn sessions with no `learning_stage` are treated as legacy practice sessions or migrated explicitly to avoid hiding an already-created exercise mid-session. The implementation must choose and test one deterministic fallback.
- Existing onboarding tool cards remain unchanged; history uses a new learning-only tool name and data source.
- Review session messages and exercise flows remain untouched except for any shared type-safe tool rendering refactor.
- Product and architecture documents must be updated alongside implementation because current state-machine and API docs describe practice-first startup.

## Validation Strategy

- Backend contract tests cover concept-first start, compact stage resume, normal unlock, early practice unlock, persisted learning messages, all-session history filtering, and no onboarding/review leakage.
- Frontend checks cover nullable exercise/start contract, tool rendering, no workbench at concept entry, early-practice notice, and history-card session grouping.
- Browser smoke confirms a fresh knowledge point opens in dialogue-first concept mode and practice appears only after a readiness trigger.

## Risks And Rollback Points

- The current worktree already contains unrelated uncommitted frontend and SDK integration changes; implementation must avoid reverting or accidentally committing them.
- Storing all dialogue increases history volume; cursor retrieval and collapsed UI prevent automatic thread inflation.
- Hiding the existing immediate exercise can break legacy active sessions unless the compatibility rule is implemented before switching frontend rendering.
