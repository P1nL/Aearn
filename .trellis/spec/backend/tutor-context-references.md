# Tutor Structured Context References

## Scenario: Learner-Safe Artifact References on Tutor Inputs

### 1. Scope / Trigger

- Trigger: changing Tutor input requests, LearningTrack run scope, Lesson selection, terminal exercise/execution/review feedback, public conversation history, context assembly, local export/reset, or `tutor_message_context_references`.
- This is a cross-layer API, PostgreSQL, Harness-context, and Desktop parser contract. Use `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md`, and `docs/product/frontend-interaction-spec.md` as the product sources of truth.

### 2. Signatures

```text
Tutor input: context_references?: TutorContextReferenceDraft[0..6]
Kinds: lesson_selection | exercise_feedback | execution_result | review_feedback | teaching_session_message
DB identity: (user_id, conversation_id, run_id, message_id, input_revision, reference_index)
History: learner message.context_references: TutorContextReference[]
Context source: tutor-context-references:{message_id}
```

```python
PostgresTutorContextReferenceRepository.record_for_input(
    *, user_id, scope, message_id, input_revision, references
) -> tuple[dict[str, object], ...]
```

### 3. Contracts

- References are allowed only on an immutable `learning_track` run scope and must match the exact task kind, track, and optional knowledge key.
- `lesson_selection` must match the active frozen assignment, exact document/hash/block, normalized range, and candidate excerpt. The server reconstructs the safe excerpt; the client excerpt is locator input, not authority.
- Exercise, execution, and review references must resolve to a real terminal Attempt in the same user/track/knowledge scope. `execution_result` additionally requires a real execution job.
- The input transaction atomically binds learner message, run/input revision, run scope, and every reference. One invalid reference rolls back the entire input.
- Persist only bounded learner-safe snapshots and canonical hashes. Never concatenate a reference into learner `content` and never store or expose full submissions, private rubrics/tests/reference answers, raw stdout/stderr, commands, paths, containers, provider bodies, reasoning, credentials, or secrets.
- Desktop API parsers start from `unknown`, require exact keys for every union member, accept only the public `teaching_session_message` metadata shape, reject internal `message_content`/extra fields, and clear draft chips only after the acceptance response confirms the saved references.
- Switching user, track, mode, knowledge key, or review session aborts old requests/SSE and clears drafts, editors, results, and composer scope.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| More than 6 references, duplicate identity, unknown kind, invalid key/hash/range | `422 CONTEXT_REFERENCE_INVALID`; no message/run/reference rows remain |
| General or plan-drafting scope, wrong task kind, cross-track or cross-knowledge reference | `409 CONTEXT_REFERENCE_SCOPE_CONFLICT` |
| Active Lesson document/hash/block/range changed | `409 CONTEXT_REFERENCE_STALE`; learner must select again |
| Attempt/Review is missing, non-terminal, or outside user scope | `404 CONTEXT_REFERENCE_NOT_FOUND` without existence leakage |
| Execution reference has no execution job | `409 CONTEXT_REFERENCE_NOT_READY` |
| Persisted safe payload hash mismatch | fail closed; do not inject or return the corrupted projection |
| Unknown/extra API response field | Desktop contract error; do not partially render |

### 5. Good / Base / Bad Cases

- Good: a learner selects text from one frozen Lesson block, sends it with `lesson_teaching`, and history replays the server-derived safe excerpt without changing the learner message body.
- Good: a terminal Review Attempt is attached to `review_coaching`; the snapshot survives later schedule finalization and plan changes.
- Base: a normal track-scoped Tutor message has `context_references=[]`; existing conversation and fresh finite TurnRun behavior is unchanged.
- Bad: append the selected excerpt to `content`, trust client-provided feedback, accept a cross-track Attempt ID, or query the current artifact later instead of persisting a frozen safe snapshot.

### 6. Tests Required

- PostgreSQL bootstrap twice; assert table, composite FKs, kind CHECK, unique indexes, immutable trigger, and target-state inventory.
- Input tests for first-turn, ordinary turn, and explicit continuation; assert atomic rollback, idempotent replay, duplicate rejection, task/scope mismatch, cross-user/track isolation, stale Lesson range, terminal Attempt rules, execution job requirement, and safe redaction.
- History and context-loader tests; assert reference ordering, exact run/input revision, separate required structured source, unchanged learner content, and frozen replay after artifact mutation.
- Desktop build plus real browser smoke for wide three-column, medium drawer keyboard boundary, narrow tabs, Review lifecycle, Lesson selection draft, feedback chips, scope cleanup, overflow, and console errors.

### 7. Wrong vs Correct

#### Wrong

```ts
const content = `${learnerText}

Selected lesson text: ${excerpt}`;
await acceptTutorConversationInput({ content });
```

The model cannot distinguish learner-authored content from a source artifact, and the server cannot verify scope, version, or provenance.

#### Correct

```ts
await acceptTutorConversationInput({
  content: learnerText,
  learningScope: {
    scope_kind: "learning_track",
    learning_track_id: trackId,
    task_kind: "lesson_teaching",
    knowledge_key: knowledgeKey,
  },
  contextReferences: [{
    kind: "lesson_selection",
    learning_track_id: trackId,
    knowledge_key: knowledgeKey,
    document_id: documentId,
    document_content_hash: documentHash,
    block_id: blockId,
    start_offset: start,
    end_offset: end,
    excerpt,
  }],
});
```

The server validates the artifact and stores a separate immutable learner-safe snapshot bound to the accepted message and run revision.


## Scenario: Exact LessonDocument Reference Resolver

### 1. Scope / Trigger

- Trigger: adding a public source-document opener for a Lesson block, saved Tutor context reference, or source_inspector_v1 Artifact.
- This resolver is read-only and additive. It reuses immutable Lesson assignments/documents/snapshots, persisted safe context references, and current Artifact projection; it does not create a second Lesson, Artifact, Gate, Review, or Attempt authority.

### 2. Signatures

~~~text
POST /api/learning-tracks/{track_id}/lesson-references/{conversation_id}/resolve
body = { user_id, knowledge_key, source }
source = lesson_block | context_reference | artifact
response.schema_version = lesson_document_reference_v1
~~~

### 3. Contracts

- Require a verified user and an exact tutor_conversation_learning_scopes row for the same user/conversation/track.
- lesson_block resolves only the supplied document/hash/assignment version/block/citation. context_reference reads the exact persisted lesson_selection safe payload and verifies its safe-payload hash. artifact requires the exact Artifact version, same track/knowledge, source_inspector_v1, and exactly one matching lesson_document source reference with the assignment version.
- Load the immutable assignment, document, and source snapshots by exact identity. Validate document hash/knowledge, block, normalized excerpt/range, citation membership, and selected citation before projection.
- Return the exact assignment/document/sources/target plus the current active assignment pointer. Mark current only when document/hash/version match the active assignment; otherwise mark historical without substituting current content.
- The projection may contain the full learner-visible Lesson and bounded source snapshots because it is a scoped drawer read. It must not contain submissions, private rubric/tests/reference answers, provider body/reasoning, commands, paths, container identity, credentials, or secrets.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Invalid UUID/stable key/hash/source shape | validation or 422 DOCUMENT_REFERENCE_INVALID |
| Missing or cross-scope conversation/reference/assignment/document/Artifact | 404 DOCUMENT_REFERENCE_NOT_FOUND |
| Saved hash, Artifact version/presentation/source ref, document hash, block, excerpt/range, or citation mismatch | 409 DOCUMENT_REFERENCE_STALE |
| Requested immutable assignment exists but a newer assignment is active | 200, reference_status=historical, exact old document plus current pointer |

### 5. Good / Base / Bad Cases

- Good: a saved lesson selection survives assignment migration and resolves its old document/hash/block/range.
- Good: a source-inspector Artifact resolves only when its exact version and lesson_document provenance agree with the presentation.
- Base: a direct current Lesson citation resolves as current with one selected source.
- Bad: query the active assignment first, accept any Artifact with the same excerpt, or return not-found details that reveal another user’s object.

### 6. Tests Required

- PostgreSQL/API tests for direct/context/Artifact source unions, current and historical assignments, extra fields, stale hash/version, citation/range validation, cross-user/track isolation, and learner-safe projection.
- Existing bootstrap-twice and tutor_conversation_event_v3 compatibility tests remain mandatory; this read path must not change schema fragment ordering.
- Import smoke must keep artifacts/__init__.py contracts-only/lazy so Lesson resolver imports cannot reintroduce the persistence circular dependency.

### 7. Wrong vs Correct

#### Wrong

~~~python
assignment = repository.read_active_assignment(track_id, knowledge_key)
block = find_similar_text(assignment.document, excerpt)
~~~

#### Correct

~~~python
identity = resolve_exact_source(source)
assignment = read_assignment(document_id=identity.document_id, assignment_version=identity.assignment_version)
require_hash_block_excerpt_and_citations(assignment, identity)
~~~

The request identity selects immutable evidence first; active state is returned only as a comparison pointer.
