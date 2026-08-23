# Teaching Session Authority

## 1. Scope / Trigger

Use this contract whenever a long-lived LearningTrack Tutor conversation is segmented into knowledge-scoped teaching sessions, or when code touches teaching checkpoints, Tutor Turn admission, Harness commit fences, public projection, cutover inventory, or local export/reset/delete.

The session is a durable authority segment inside one track conversation. It is not a second conversation and must never be reconstructed from chat text.

## 2. Signatures

### HTTP

```text
GET  /api/learning-tracks/{track_id}/teaching-sessions?user_id={uuid}
GET  /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}?user_id={uuid}
POST /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}/open
POST /api/learning-tracks/{track_id}/teaching-sessions/{session_id}/actions
```

Mutation inputs use `client_action_id` or `Idempotency-Key` plus expected session/track/progress/assignment versions.

### Python

```python
TeachingSessionRepository.bind_learner_message_run(
    user_id: str,
    run_id: str,
    conversation_id: str,
    track_id: str,
    knowledge_key: str,
    message_id: str,
    input_revision: int,
) -> dict[str, object] | None

TeachingSessionRepository.assert_run_scope_current(
    user_id: str,
    run_id: str,
) -> Mapping[str, object]
```

### PostgreSQL

User-owned tables are `tutor_teaching_sessions`, `tutor_teaching_session_checkpoints`, `tutor_run_stimulus_events`, and `tutor_run_teaching_scopes`.

## 3. Contracts

- A LearningTrack keeps one long-lived track-scoped learner conversation. A teaching session owns one knowledge-point segment within it.
- `tutor_teaching_sessions` freezes user, track, conversation, knowledge key, track/plan/progress, active Lesson assignment, and LessonDocument authority. At most one `active | paused | blocked` session exists for the exact scope.
- `tutor_teaching_session_checkpoints` is an append-only predecessor chain. The session's `current_checkpoint_id` and `version` advance by CAS; old checkpoints are never rewritten.
- Every teaching-scoped fresh run has exactly one immutable `TutorTurnStimulus`: `learner_message | teaching_control | domain_event`.
- `learner_message` references exact `tutor_run_input_events(run_id,message_id,input_revision)` evidence. Controls/events create an `interactive` run without a forged learner message and without proactive origin.
- `tutor_run_teaching_scopes` freezes session/checkpoint/stimulus plus track/plan/progress/assignment/document authority. Effect commit, waiting-result persistence, and terminal persistence revalidate it.
- Public projections expose only stable IDs, versions, status/mode, bounded objective/focus summaries, counts, and safe action keys. Omit prompt, reasoning, provider body, raw checkpoint/authority JSON and proof hashes, complete question/submission, hidden tests/rubric, command, path, and secrets.
- All four tables belong to exhaustive cutover target inventory and local summary/export/reset/delete. Delete run scopes -> stimuli -> checkpoints -> sessions under the transaction-local purge capability.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Cross-user, cross-track, or cross-conversation read/mutation | `404` scoped not-found or `409 TEACHING_AUTHORITY_CONFLICT`; do not reveal foreign existence |
| Expected session/track/progress/assignment version is stale | `409 TEACHING_AUTHORITY_CONFLICT`; no checkpoint, run, effect, or message write |
| Current checkpoint/session pointer changed after run admission | Harness commit raises stale terminal/effect conflict |
| Stimulus supplies zero or multiple union branches | PostgreSQL `23514` exact-one CHECK failure |
| Learner stimulus lacks exact run/message/input receipt | composite FK or repository conflict |
| Control/domain admission would create a competing foreground run | `409 TEACHING_AUTHORITY_CONFLICT` |
| Same idempotency key with a different immutable request | `409 IDEMPOTENCY_CONFLICT` |
| Ordinary UPDATE/DELETE of checkpoint, stimulus, or run teaching scope | append-only trigger rejection |
| Reset/delete outside exact user purge scope | trigger/FK rejection |

## 5. Good / Base / Bad Cases

- **Good:** an existing track conversation opens `python.variables`, appends checkpoint version 1, accepts a real learner message on a fresh run, and binds exact message/input evidence plus immutable teaching scope.
- **Good:** an explicit `continue` control creates an interactive run with `input_revision=0`, one `teaching_control` stimulus, and no learner message row.
- **Base:** an old track conversation has no teaching session. History remains readable; a normal run may remain on the legacy-compatible path until the user explicitly opens a session.
- **Bad:** infer the current knowledge key from message text or backfill a session from conversation history.
- **Bad:** store only `session_id` on the run and read mutable current progress/assignment later without freezing versions.
- **Bad:** use proactive origin for a user-owned teaching control or insert a fake learner message to satisfy an old input shape.

## 6. Tests Required

- Bootstrap the same empty PostgreSQL schema twice and assert all tables, scoped FKs, partial unique index, exact-one CHECK, and immutable triggers.
- Test open/resume idempotency, checkpoint CAS, mode/status mutation, and cross-owner/scope rejection.
- Test real learner-message binding, explicit control/domain admission without a learner message, and `origin='interactive'`.
- Change track/progress/assignment/document/session/checkpoint authority after admission and assert effect/waiting/terminal persistence fails before public output or effect commit.
- Assert export contains only teaching summaries, reset/delete clears all four user-owned tables child-to-root, and cutover exhaustive inventory includes every table.
- Run Child 1 focused tests, Ruff, Mypy, Trellis validation, and `git diff --check` without a real provider.

## 7. Wrong vs Correct

### Wrong

```python
# Guesses authority from mutable state and forges a learner input for a button click.
knowledge_key = infer_from_chat(conversation.messages)
message_id = repository.insert_message(role="learner", content="continue")
run = repository.create_run(origin="proactive")
```

### Correct

```python
# Uses the explicit session/checkpoint authority and a closed structured control.
control = TeachingControlStimulus(
    control_key="continue",
    client_action_id=client_action_id,
    expected_session_version=session_version,
    expected_track_version=track_version,
    expected_progress_version=progress_version,
    expected_assignment_version=assignment_version,
)
run_scope = teaching_sessions.admit_control_run(
    authority=authority,
    session=current_session,
    stimulus=control,
)
assert run_scope["origin"] == "interactive"
```

The correct path produces no learner message, freezes exact authority, and can be rejected safely if any fence becomes stale.
