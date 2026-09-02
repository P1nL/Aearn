# Authoritative Execution Result Artifacts

## 1. Scope / Trigger

Apply this contract when changing executor result serialization, Gate/Review Attempt observation, `test_result` Artifact projection, result-evaluation continuation scheduling, learner-safe teaching context, or model-unavailable handling for an explicit Artifact Run.

The execution job, Attempt scorer, Gate/Review owner, Learning Artifact repository, TeachingSession, and Tutor continuation/run loop remain separate authorities. This flow coordinates them; it must not create a second score, pass, mastery, progress, or scheduling implementation.

## 2. Signatures

```python
parse_safe_execution_result(value: object) -> SafeExecutionResultV2

ExecutionResultArtifactProjector.project(
    *, user_id: str, conversation_id: str,
    source_artifact_id: str, attempt_id: str,
) -> ExecutionResultArtifactProjection

TutorContinuationIntentProducer.record_result_evaluation(
    *, user_id: str, conversation_id: str,
    result_artifact_id: str, result_artifact_event_id: str,
    result_artifact_event_sequence: int, attempt_id: str,
) -> ContinuationIntentRecord
```

```text
GET /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/attempts/{attempt_id}?user_id={uuid}

safe-execution-result-v2
tutor_learning_artifact_attempt_v2
test_result_v1
```

`SafeExecutionResultV2.presentation` is a closed union of `{kind:"none"}` and `table_result_v1`. Table bounds are 32 columns, 200 rows, 120 Unicode code points per column, 500 Unicode code points per text cell, JSON-safe finite numbers within +/-9,007,199,254,740,991, and 65,536 UTF-8 bytes for the complete presentation.

## 3. Contracts

- New executor writes use `safe-execution-result-v2`; persisted unversioned v1 rows remain readable only through the explicit v1 adapter and reproject as v2 with `presentation={kind:"none"}`.
- Public output contains only bounded stdout/stderr, learner-safe feedback, numeric source coordinates, aggregate counts, duration, a stable diagnostic code, and the closed presentation. Paths, commands, stack/container/image identity, secrets, hidden IDs/input/expected values, and private payloads are rejected or redacted before storage.
- SQL workspace execution preserves the exact bounded public query columns/rows as `table_result_v1`. Hidden datasets contribute only sequential `non-visible-N` pass/fail feedback and never replace, merge into, or leak through the public grid.
- A hidden feedback item uses the exact sequential ID `non-visible-N`, a fixed safe message, and no location. A visible location contains only line/column/end-line/end-column.
- An Artifact Run that is still pending/running returns the current Attempt and creates no result Artifact, continuation intent, or Tutor Turn.
- A Learning Item-owned SQL Run admits one exact private pending `tutor_exercise_attempts` row while the Artifact transaction is locked, with no counterfeit Gate binding. The caller commits admission before local in-memory SQLite execution, then finalizes that same Attempt through the existing scorer/result authority, projects the source/result Artifacts, and schedules the standard result-evaluation continuation. Replay or GET recovery observes the committed Attempt; this path writes no mastery or progress evidence.
- A terminal Attempt is loaded through its exact Gate/Review owner, then one caller-owned transaction updates the source Artifact, creates one immutable nonblocking completed `test_result` Artifact without publishing its timeline item, records one exact result-evaluation intent, and consumes it into at most one teaching Turn. The Turn terminal transaction writes the evaluation message first and then publishes the exact result Artifact item; both timeline items commit or roll back together. Replays return the same projection and do not execute again.
- Passed results complete the source Artifact and clear actions. Failed/timed-out/cancelled/unavailable/invalid results keep the source Artifact active with its safe edit/run actions.
- The result Artifact references the exact source Artifact version and the exact Attempt result hash. Multiple Runs create distinct result Artifacts keyed by Attempt while the source Artifact projects the newest authoritative Attempt.
- A terminal Run action response returns the latest source Artifact write and the matching event ID/sequence. Returning a newer Artifact with the earlier action event sequence is an invalid cross-layer response.
- Result-evaluation context admits only `reason_code=result_evaluation`, `artifact:<result-artifact-id>`, and a revalidated learner-safe summary of at most 320 characters. It advertises no new Artifact candidates and never injects the complete execution payload or submission.
- The model may author only the evaluation message. If the exact result-evaluation Turn ends `MODEL_UNAVAILABLE`, the run loop persists a deterministic Markdown fallback containing the already-saved authoritative summary. Ordinary model-unavailable Turns retain their existing no-fallback behavior.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Unknown result version, enum, extra field, non-finite cell, mismatched row width, or exceeded bound | reject the complete result |
| Hidden case exposes its original ID/message/location or dataset value | reject before durable/public projection |
| SQL query reads an unpublished table, mutates state, accesses file/extension APIs, exceeds resource/table bounds, or carries multiple statements | fail closed with a learner-safe runtime result and no table presentation |
| Attempt is not terminal | return pending; no projection or scheduling |
| Artifact/Attempt/user/conversation/owner scope mismatch | stable not-found/conflict; no partial write |
| Projection is replayed | return one source/result pair with replay evidence; no new rows or execution |
| Only source update or only result Artifact exists | fail closed as partial projection |
| Result-evaluation intent lacks exact result Artifact creation evidence | cancel/reject; never downgrade to an ordinary continuation |
| Provider unavailable on exact result evaluation | terminal outcome remains `MODEL_UNAVAILABLE`; publish one fixed safe evaluation message |
| Provider unavailable on an ordinary Turn | preserve the ordinary existing behavior; do not synthesize a result fallback |
| Action response Artifact version differs from event sequence | fail the contract; return the projected source write instead |

## 5. Good / Base / Bad Cases

- **Good:** A failed Run is observed once. The source stays active, one result Artifact is appended, the safe summary enters one evaluation Turn, and “return to edit” targets the source Artifact.
- **Good:** A passed Run completes the source directly; there is no second Submit action. A repeated GET returns the same result and continuation lineage.
- **Base:** A historical v1 execution row is adapted to strict v2 with no rich presentation and remains readable without exposing legacy arbitrary feedback to the Desktop result renderer.
- **Bad:** Scheduling an Artifact continuation immediately when Run only created a pending Attempt.
- **Bad:** Letting the model provide score, outcome, test counts, result Artifact fields, or a replacement result when the provider fails.
- **Bad:** Returning source Artifact version 3 with the earlier action event sequence 2.

## 6. Tests Required

- Shared contract tests: v1 adapter, strict v2 round trip, hidden redaction, location validation, table scalar/shape/byte bounds, and protected output rejection.
- Executor tests: all newly completed jobs serialize v2; historical v1 rows read as v2; terminal state mapping remains unchanged.
- PostgreSQL projector tests: pass/failure state, exact source/result references, multiple Run history, replay, partial persistence rejection, and bootstrap after persisted conversation event v3.
- Route/owner tests: pending no-op, terminal projection, exactly-one continuation/Turn, source response event identity, cross-scope rejection, and no duplicate Attempt/execution. SQL coverage additionally proves admission commit precedes execution, exact Learning Item/materialization scope, no Gate binding, public/hidden dataset separation, and no mastery write.
- Tutor loop tests: exact safe context, bounded source handle, message-before-result atomic timeline publication, model-unavailable fallback, and ordinary model-unavailable non-regression.
- Run focused serial PostgreSQL tests before the broad API suite, plus Ruff, Mypy, executor tests, and `git diff --check`.

## 7. Wrong vs Correct

### Wrong

```python
artifact = service.act(run_request)
continuation.record_artifact_action(artifact.event_id)
if provider_failed:
    artifact.result = model_fallback_result
```

This schedules before terminal authority and lets provider availability alter the saved result.

### Correct

```python
action_write = service.act(run_request)
observation = observe_exact_attempt(action_write.artifact.active_attempt)
if observation.terminal:
    projection = projector.project(...)
    intent = continuations.record_result_evaluation(
        result_artifact_id=projection.result_artifact.artifact.id,
        result_artifact_event_id=projection.result_artifact.artifact_event_id,
        result_artifact_event_sequence=projection.result_artifact.artifact_event_sequence,
        attempt_id=observation.attempt_id,
    )
    action_write = projection.source_artifact
```

The correct path waits for owner-terminal evidence, returns one matching Artifact/event projection, and treats model evaluation as an optional message over an immutable server result.
