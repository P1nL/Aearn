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


## 2026-10-11 native practice per-run terminal接线（代码已静态核验，真实catalog消费者未闭合）

### 1. Scope / trigger
正常P7完整native包的selected practice进入原Tutor terminal Artifact writer；不是新的writer/评分系统，不涉及历史finding解除或正式Gate成绩写权。代码静态核验与真实交付必须分层。

### 2. Signatures
- `NativeTeachingPracticeDeliveryContext(exposure_owner, mapping_receipt_id, reservation_key, selected_version_id)`：具体原NativeExposureOwnerV2/type owner，同connection/current namespace。
- `PostgresTeachingArtifactMaterializer(conn, settings=..., native_practice_delivery=context|None)`：defaultNone保留legacy。
- `PostgresTutorRepository.register_native_teaching_practice_delivery(run_id=actual_run, context=context)`：仅该repository实例内、该canonical run，供原complete_run的atomic prepare/create使用；无HTTP/JSON注入入口。
- 原prepared对象可交新materializer.create，但connection/settings/transaction及原对象身份必须一致。

### 3. Contracts
Native先无锁discovery，原current source→bank锁顺序，bank锁后fresh row/clock/refence；default无context时不增加nativeSQL。既有mapping、完整pack、exposure、selected practice、public/source/content/materialization及user/epoch/track/revision/node/turn/session/checkpoint严格闭合。原prepare_practice_delivery在同一事务先于原writer，后续capture不由helper伪造。nativecreate在入口与最终writer前重验两个Artifact flags，settings对象身份相等不替代flag值。
原curated来源及catalog equality未放宽；任意registered_author不能只凭标签进入。无private假handle、无publication/grade/progress新权限。

### 4. Validation / errors
| 条件 | 必须结果 |
| --- | --- |
| foreign/cloned/prepared marker-erased、错connection/settings/run/txid | 拒绝，不恢复JSON能力 |
| wrong selected practice/mapping/user/epoch/goal/content/current source/exposure | 拒绝 |
| 任一Artifact开关关闭或source锁等待后失效 | writer前拒绝 |
| 仅reservation/delivery DATA，没有原writer成功 | 不声明Artifact交付 |
| actual catalog python.bind与native finite.python-kc-binding-v1不等 | 现行Python及230 SQL接收端仍拒绝；ScopedV2 DTO不是越权豁免 |

### 5. Good/base/bad
Good：具体原owner/current capability→原terminal同事务prepare/create/capture。Base：defaultNone的curated路径保持。Bad：只去掉source_kind/catalog谓词，先提交delivery许可再写Artifact，settingsidentity当开关开启证据。

### 6. Focused verification / remaining gates
三文件scoped Ruff/Mypy、AST及独立静态P1锁顺序/P2flags修复复核通过；未运行旧suite。实际fresh5成员/真实关系/完整包/原terminal delivery及必要rollback未通过；native catalog original receiver与KC后续action读取尚未接通，见任务research/p7-native-catalog-bridge-gap-20261011.md。未宣称P7/P8/E完成。

### 7. Wrong vs correct
Wrong：FCO mapping和complete exposure通过即说明所有Artifact/KC/Run接收端支持native。Correct：496/501/502可以分离public内容与private目标身份，但230/220/原KC owner的独立catalog predicate仍须用明确新版原consumer bridge闭合；禁止强贴别名或改写旧confirmed plan。


## 2026-10-11 explicit native catalog bridge / original ongoing KC consumer

### 1. Scope / Trigger
For the explicitly allowlisted finite Python KC native practice in a genuine confirmed private course, bridge different catalog domains at original consumers; do not alias or rewrite frozen D. SQL521 is now selected-installed in B1d, not global/public rollout or live P7 completion.

### 2. Signatures
Original repository per-run `register_native_teaching_practice_delivery(run_id,context)`; `NativeTeachingArtifactCandidateBuilder(repository,conn=...,settings=...).register_delivery(...)`; inject builder in original learning loader AND `TeachingSessionRepository(...,artifact_candidate_builder=builder.for_run(run_id))` used by the decision gate. Original `LearningItemArtifactOwnerAdapter(native_consumer_owner=NativeArtifactConsumerOwner(conn,settings,type_owner=original_type_owner,enabled=True))` consumes via original `LearningArtifactService.act`. Defaults remain absent/off. SQL521 adds private consumer receipts and artifact bindings and narrowly replaces effective230 original owner receiver.

### 3. Contracts
Private catalog `python.bind` and public finite catalog `finite.python-kc-binding-v1` each retain identity; concrete current FCO/501/502 owner proves mapping, source, full pack, selected version/materialization and same-TX delivery. Original curated equality is unchanged. Creation authority and later actions are separate: ongoing owner freshly checks current mapping/source/published content/epoch/artifact, never restores old30sec snapshot/JSON capability. Issued consume/cancel permits bind both mode AND exact action; cancel cannot grant hints/answers/respond. Mandatory native remediation/transfer is unsupported before receipt/CAS, including direct-answer; ordinary correct and direct-explanation wrong responses use original scorer. No new Run/Gate/mastery authority.

### 4. Validation & Error Matrix
No concrete context/current pack/wrong scope/version/owner/epoch => reject; missing native receiver receipts => reject; disabled feature flags => reject at prepare/create/current use; unsupported successor => reject before assistance/response/CAS; native source retired/revoked => deny content without silently swapping active item; cancel remains distinct original ownership action. Same connection must be autocommitFalse for native owner; production interactive dispatcher uses autocommitTrue, so Main's allowlisted composition uses original loop/loader/repo/gate/lifecycle with explicit boundaries and commits before real provider IO, never relaxes native guard.

### 5. Good / Base / Bad Cases
Good: current exact native mapping + current complete pack + genuine model-selected advertised native handle + original terminal writer + new ongoing native owner reply. Base: curated calls remain original strict equality. Bad: string alias, registered-author blanket admission, reserve=delivery, old receipt JSON restoration, or a cancel token used for respond.

### 6. Tests Required
Independent final static A PASS, scoped lint/types, Main exact521 compile/replay/rollback/old6707rows-preservation/install, ten installed helper pins and intended isolated-role EXECUTE, missing receipt negative and original safe export passed. Fresh complete five-member pack, original genuine terminal/Artifact/KC action and populated private reset/export acceptance still pending; do not mark P7/E complete from these checks. No new test files/full old suite replay.

### 7. Wrong vs Correct
Wrong: only loader advertises native but the original decision gate rebuilds curated candidates and rejects the handle; or access `source.private.accepted_answers`. Correct: same per-run concrete builder reaches both original consumers, and post-terminal private-only synthetic QA reads `source.private.content.accepted_answers`, never puts gold into provider/blind inputs or claims learner efficacy.
