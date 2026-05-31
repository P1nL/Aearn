# Agent Persistent Memory

## Goal

Enable the learning agent to remember learner characteristics across sessions: weak points, recurring error patterns, learning preferences, pace, and mastery trajectory. Currently all memory is session-scoped (`safe_summary` in `learning_stage_state_json`), lost when a new session starts.

After this task, the agent can say "you struggled with recursion last week, let's revisit that" or "you learn faster with examples than explanations, so here's an example first."

## Context

- Current memory: `conversation_summary` JSON refreshed every ~4 messages within a session. Contains: `stuck_point`, `misconceptions`, `concepts_explained`, `avoid_repeating`, `last_diagnosis`, `last_agent_strategy`. Dies with the session.
- FSRS data (`review_states`: stability, difficulty, due_at, reps, lapses) persists across sessions but is scheduling metadata, not pedagogical memory.
- `attempts` table has historical code submissions, scores, and error patterns — but the agent never queries past sessions.
- `knowledge_points` has `mastery_score` and `status` — aggregate metrics, not detailed learner profile.
- No vector store or embedding infrastructure exists. Redis is available.
- Dependency: `shared-structured-judgement-module` (memory entries should use structured judgement format for consistency).

## Requirements

### Learner Profile Schema
- Define a persistent learner profile that accumulates across sessions:
  - `weak_points`: knowledge areas where the learner repeatedly struggles (with evidence: which KPs, how many attempts, what errors)
  - `error_patterns`: recurring code mistakes (e.g., off-by-one, scope confusion, type errors) with frequency
  - `learning_preferences`: observed preferences (examples vs theory, guided vs exploratory, verbose vs concise feedback)
  - `pace_indicators`: average time per concept, attempts per exercise, hint usage rate
  - `mastery_trajectory`: progression over time (improving, plateauing, regressing per area)

### Storage
- Store learner profile in Postgres (new table or JSONB column on `users`).
- Profile must be updatable incrementally — each session contributes observations, not a full rewrite.
- Profile must be queryable by the agent via a read tool (`get_learner_profile`).
- Profile updates happen at session end (or periodically during long sessions) via a write tool or service hook.

### Agent Integration
- Add a `get_learner_profile` tool that returns the current profile summary for the active user.
- Add an `update_learner_profile(observations)` tool that appends new observations from the current session.
- The agent's system prompt should include a condensed profile summary so it can adapt teaching style from the first message.
- Profile observations must use the structured judgement format (confirmed/ambiguous/missing) to distinguish strong signals from weak ones.

### Privacy and Boundaries
- Profile data is per-user and never exposed to other users.
- The agent cannot modify profile fields that contradict observed data (e.g., cannot mark a weak point as mastered without evidence from attempts).
- Users should eventually be able to view/reset their profile (frontend work deferred).

## Acceptance Criteria

- [ ] A learner profile schema exists and persists across sessions.
- [ ] The agent can read the learner profile via tool call at the start of a session.
- [ ] The agent can write observations to the profile via tool call.
- [ ] Profile accumulates across at least 3 sessions in a test scenario (not overwritten each time).
- [ ] The agent demonstrably adapts behavior based on profile data (e.g., different teaching approach for a known weak point).
- [ ] Profile observations use structured judgement format with confidence levels.
- [ ] No cross-user data leakage — profile queries are scoped to the authenticated user.
- [ ] Existing session flow is not disrupted — profile is additive context, not a required dependency.
- [ ] At least one integration test demonstrates cross-session memory: session 1 records a weak point, session 2's agent references it.

## Out of Scope

- Frontend UI for viewing/editing learner profile.
- Vector embeddings or semantic search over profile data.
- Automated profile-driven curriculum adjustment (that's `agent-autonomous-planning`).
- Sharing profiles across users or collaborative learning features.

## Dependencies

- Requires: `shared-structured-judgement-module` (profile observations use structured judgement format).
- Enables: `agent-autonomous-planning` (planning uses profile to adapt learning path).
- Complements: `agent-rag-retrieval` (retrieval can be personalized based on profile).
