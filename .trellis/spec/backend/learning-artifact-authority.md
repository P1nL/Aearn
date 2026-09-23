# Learning Artifact Authority and Conversation Protocol

## 1. Scope / Trigger

Apply this contract whenever code adds or changes Tutor inline Learning Artifacts, their lifecycle tables, owner adapters, Artifact HTTP actions, Tutor public item unions, conversation snapshots/SSE, Attempt links, local export/reset, or cutover inventory.

The Artifact is an interaction facade and learner-safe projection. Lesson Gate, Review Item, TeachingSession/checkpoint, Learning Item publication, Attempt, execution result, mastery, progress, and scheduling remain their existing domain authorities.

## 2. Signatures

### HTTP

```text
GET  /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}?user_id={uuid}
POST /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/actions
GET  /api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/attempts/{attempt_id}?user_id={uuid}
```

Artifact actions carry exact `user_id`, `learning_track_id`, `teaching_session_id`, `client_action_id`, `expected_artifact_version`, and one closed action payload. `Idempotency-Key` may replace the request's client action identity at the HTTP boundary, but replay remains bound to the canonical body hash.

### Python

```python
LearningArtifactService.read_artifact(
    *, user_id: str, conversation_id: str, artifact_id: str
) -> TutorPublicArtifactItem

LearningArtifactService.act(
    *, artifact_id: str, conversation_id: str,
    request: TutorArtifactActionRequest,
) -> LearningArtifactWriteResult

PostgresLearningArtifactRepository.create_artifact(
    request: TutorArtifactCreate, *, creation_key: str, occurred_at: datetime
) -> LearningArtifactWriteResult

ArtifactOwnerAdapter.apply_action(
    *, conn, artifact: TutorPublicArtifactItem,
    request: TutorArtifactActionRequest,
) -> ArtifactMutation
```

### PostgreSQL and public versions

```text
tutor_learning_artifacts
tutor_learning_artifact_events
tutor_learning_artifact_references
tutor_learning_artifact_attempt_links

tutor_learning_artifact_v1
tutor_conversation_event_v3
tutor_conversation_snapshot_v4
```

Feature flag: `TUTOR_LEARNING_ARTIFACTS_ENABLED=false` by default.

## 3. Contracts

- `TutorPublicArtifactItem` is a strict `extra=forbid` member of `TutorPublicItem`. Artifact kind, presentation, actions, purpose, owner kind, state, and difficulty are closed unions.
- A conversation without persisted Artifact history continues to project snapshot v3. A conversation with Artifact history projects snapshot v4. Historical v3 serialization omits v4-only fields and must reject Artifact rows rather than silently drop them.
- Artifact and conversation events are committed on the same caller-owned PostgreSQL connection. Artifact lifecycle notifications reuse `item_added` and `item_updated`; SSE contains only stable item identity/version and never full presentation or private payloads.
- At most one blocking non-terminal Artifact exists per conversation and per TeachingSession. Lifecycle and version transitions are database-enforced; every mutation advances Artifact version exactly once.
- When TeachingSession authority is replaced, non-terminal Artifacts from proven blocked ancestors in the same user/conversation/track/node scope must be retired through the existing owner `SUPERSEDED` terminal transition, Artifact CAS/event and conversation `item_updated`. Preserve presentation, frozen owner/checkpoint identities and all historical receipts; do not delete or complete/score the old work. A matching-current-session open also reconciles previously leaked ancestor Artifacts. The conversation lock and caller transaction cover session/branch/Artifact changes; pending execution or an unfinished Attempt must fail closed rather than be silently cleared. Never supersede the current session's Artifact or an unrelated/active ancestor.
- Every write is fenced by exact user, conversation, track, knowledge, TeachingSession, checkpoint, owner identity/version, and expected Artifact version. A non-null `turn_id` must match the exact frozen teaching run scope.
- The Artifact repository is the only database-row-to-public-DTO projection boundary. Public reads validate protected keys/markers and canonical hashes before returning data.
- Full learner submission, private rubric/test, reference answer, provider body/reasoning, commands, paths, mounts, container/image identity, secrets, and raw validation input never enter public Artifact, snapshot, SSE, export, or error details.
- Attempt summaries and Attempt-detail reads are derived from authoritative `tutor_exercise_attempts` and result rows. Client/adapter-provided summaries must match the authoritative status, outcome, score, hashes, timestamps, and exact Gate/Review/Teaching owner scope.
- Artifact Attempt links are append-only and must link the current Artifact CAS version. `learning_item` ownership fails closed until the immutable Learning Item Bank authority exists; do not substitute a Teaching checkpoint.
- Owner adapters are a closed exact registry with no fallback or text inference. They use the supplied transaction and may admit bounded owner work, but they must not call a provider, runner, subprocess, or other unbounded dependency while the Artifact/conversation lock is held.
- The Learning Item SQL owner is the explicit post-commit exception pattern: its adapter only admits and links one pending Learning Item-owned Run Attempt under lock; the route commits, then an observer executes the bounded local SQLite query and finalizes the existing Attempt. The Attempt has no Gate binding, and the observer never creates score, mastery, or progress authority outside the existing scorer/repository path.
- With the feature flag off, historical Artifact reads remain available and all writes return `LEARNING_ARTIFACT_DISABLED`. Enabling the flag without a registered exact owner adapter fails closed with `LEARNING_ARTIFACT_OWNER_UNAVAILABLE`.
- All four Artifact tables are user-owned cutover targets. Local export returns bounded safe summaries only; reset/delete removes Artifact children before parent rows while preserving shared exercise/item versions.
- Keep `app.services.learning.artifacts.__init__` contracts-only or genuinely lazy. Eager repository/service/conversation-event exports cause a circular import through Tutor persistence.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Unknown/foreign user, conversation, Artifact, Attempt, track, session, or owner scope | `404 LEARNING_ARTIFACT_NOT_FOUND`; do not reveal foreign existence |
| Stale Artifact or owner version | `409 LEARNING_ARTIFACT_VERSION_CONFLICT`; no owner callback or partial write |
| Same idempotency identity with different canonical body | `409 IDEMPOTENCY_CONFLICT` |
| Invalid lifecycle or terminal mutation | `409 LEARNING_ARTIFACT_STATE_CONFLICT` or PostgreSQL `23514` |
| Feature disabled on mutation | `409 LEARNING_ARTIFACT_DISABLED`; reads still work |
| Missing owner adapter | `409 LEARNING_ARTIFACT_OWNER_UNAVAILABLE`; no fallback scoring |
| Artifact event cannot be atomically appended | `503 LEARNING_ARTIFACT_EVENT_UNAVAILABLE`; rollback Artifact mutation |
| Public projection contains protected key/marker or invalid SHA-256 | projection failure; never return the unsafe payload |
| Attempt summary differs from authoritative Attempt/result | reject atomically; no Artifact/link/event write |
| Snapshot requested before any Artifact history | snapshot v3 |
| Snapshot requested after Artifact history exists | snapshot v4 with exact timeline and optional active Artifact |
| Validation error contains private action input | sanitizer removes `input`, `ctx`, and raw payload values |
| Bootstrap runs again with persisted event v3 rows | fragment 110 and 120 preserve v1/v2/v3 and complete successfully |

## 5. Good / Base / Bad Cases

- **Good:** A verified Teaching owner creates an active Artifact and its `item_added` event in one transaction. Reconnect reads the same v4 snapshot, and a duplicate creation key replays the original Artifact without advancing conversation activity.
- **Good:** A Run owner commits an authoritative Attempt/result, then returns a matching safe mutation. The repository links the current Artifact version, appends one Artifact event and one `item_updated`, and projects only redacted Attempt details.
- **Base:** The feature is disabled. Existing Artifact history remains readable; new actions are rejected before any owner callback.
- **Base:** A legacy/no-Artifact conversation continues to serialize snapshot v3 for current Desktop compatibility.
- **Bad:** Trusting a client-provided `passed`, score, result hash, or Attempt summary without loading the exact owner authority.
- **Bad:** Emitting full Artifact presentation/submission through SSE, or allowing Pydantic validation errors to echo the rejected action body.
- **Bad:** Treating `learning_item` as a Teaching checkpoint because the Item Bank tables have not landed yet.
- **Bad:** Eagerly exporting repository/service modules from the Artifact package root and reintroducing the Tutor persistence circular import.

## 6. Tests Required

- Contract tests for every public presentation/action/response union, unknown/extra fields, duplicate references/actions, invalid hashes, terminal shape, and protected markers/keys.
- PostgreSQL bootstrap twice, including an already-committed `tutor_conversation_event_v3` Artifact row before the second bootstrap.
- Real PostgreSQL tests for cross-user/scope rejection, one-blocking indexes, lifecycle/CAS triggers, append-only evidence, current-version Attempt links, exact turn/owner scope, transaction rollback, and purge capability.
- Repository/service tests for deterministic create replay, conflicting idempotency, replay-before-owner-callback, one callback, owner unavailable, stale version, feature-off reads, safe projection, and exact Attempt detail.
- Snapshot/history/SSE tests for no-Artifact v3, Artifact v4, active Artifact projection, terminal recovery, duplicate event replay, cursor reconnect, artifact-only conversations, and reference-only SSE payloads.
- Route tests for stable error envelopes, strict action validation, `Idempotency-Key` override/replay/conflict, private validation-input redaction, cross-scope 404, and feature-off mutation rejection.
- Cutover/export/reset tests must classify all four Artifact tables exhaustively, omit private JSON/hashes, delete child-to-root, and retain shared immutable content.
- Complete the focused serial PostgreSQL matrix before the broad API suite; broad suite failures caused by an unrelated published Skill hash/EOL mismatch must be isolated rather than hidden by weakening Artifact tests.

## 7. Wrong vs Correct

### Wrong

```python
artifact = repository.read_artifact(artifact_id)
result = owner.run(request.action.submission)
artifact.active_attempt = request.action.attempt_summary
conn.commit()
publish_sse({"artifact": artifact.model_dump()})
```

This skips scope/CAS checks, performs unbounded owner work while authority is locked, trusts client summary data, separates conversation notification from the owner transaction, and leaks the full Artifact over SSE.

### Correct

```python
with transaction(conn):
    artifact = repository.read_artifact(
        user_id=request.user_id,
        conversation_id=conversation_id,
        artifact_id=artifact_id,
    )
    adapter = owner_registry.require(artifact.owner_kind)
    mutation = adapter.apply_action(conn=conn, artifact=artifact, request=request)
    result = repository.apply_action(
        artifact_id=artifact_id,
        conversation_id=conversation_id,
        request=request,
        owner_callback=lambda _artifact: mutation,
        occurred_at=now,
    )
```

The correct path validates exact authority and idempotency before the callback, derives Attempt facts from the existing owner, advances one Artifact version, and atomically appends safe Artifact/conversation events on the same connection.


## Tutor-driven source-inspector creation

- Source Artifacts are selected by Tutor, not by a learner-side save endpoint or an automatic write on citation open. The old manual creation route is removed.
- Use the existing teaching source_handles selection channel with server-provided exact frozen source bindings; do not confuse read-only citation support with learner-response Artifact interaction.
- Optional source candidates must fit the existing teaching character limit, required-facts item limit, and whole-request token budget. Drop optional sources rather than raising caps or evicting existing interaction candidates/required grounding; authorize only the source evidence/handle subset actually visible to the provider.
- Rank cited frozen teaching blocks against this run's persisted input (or frozen focus for no-input controls), with exact selections first and exact-block deduplication. Lexical ranking is a bounded shortlist, not semantic proof or a keyword-based create trigger. Never fall back to an unrelated first block for an unmatched learner question.
- Tutor may select one useful source proactively for misconception correction, subtle behavior contrasts or verifiable examples, without an explicit source request; skip low-value acknowledgements and repeated passages. The strict internal recently_displayed flag uses only same-scope teaching turns committed before this run began, never mutable future history. Public Artifact history remains unchanged.
- Provider-visible handles and the final Gate allowlist must agree. Unknown, forged, cross-scope, stale or flag-disabled source selections fail closed; no selection means no source Artifact.
- Recheck run/session/checkpoint/assignment/document/hash/block/citation during the existing atomic teaching terminal commit. Message, checkpoint/action receipt, source Artifact/event and run terminal must roll back together.
- Associate new sources with the real run and committed checkpoint; source_inspection remains readonly/nonblocking with no Attempt, score, progress or automatic continuation.
- Preserve old manual/null-turn sources and legacy remediation sources for reads without presenting them as evidence of Tutor-driven generation. Do not rewrite published Skill versions or relax budget/retry limits.
