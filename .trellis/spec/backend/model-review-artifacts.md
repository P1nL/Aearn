# Conversation-Native Model Review Artifacts

## 1. Scope / Trigger

Apply this contract when changing `model_code_review_v2` presentations or
submissions, server-built code/diff identity, model-review scoring, immutable
review receipts, remediation selection, evaluation continuation, Item Bank
model-review purposes, cutover/export/reset, or schema fragments that enumerate
Artifact presentation kinds.

## 2. Signatures

```text
Published Item content: LearningItemModelReviewContentV2 (`type=model_review_v2`)
Presentation: model_code_review_v2
Submission:   model_code_review_submission_v2
Rubric:       model_code_review_rubric_v2
Score policy: model_code_review_score_v2

Artifact action:
complete_review {
  review_submission: {
    presentation_hash,
    verdict,
    findings[{client_finding_id,hunk_id,side,start_line,end_line,category,severity,explanation}]
  }
}

PostgreSQL:
tutor_model_review_artifact_receipts

Python:
build_model_review_artifact_v2(...) -> ModelReviewArtifactV2
evaluate_model_code_review_v2(...) -> ExerciseAttemptResult
TutorContinuationIntentProducer.record_model_review_evaluation(...)
```

Every action also carries exact user/conversation/track/TeachingSession scope,
`client_action_id`, and expected Artifact-version fences.

## 3. Contracts

- Version 2 is additive. Historical `model_code_review_v1`, existing Lesson Gate
  review Attempts, authoring, validation, publication, and evidence remain
  readable and are not rewritten or migrated.
- `LearningItemModelReviewContentV2` is the immutable published source/modified
  authority for a real diff. Legacy v1 content materializes code-only; the
  existing Practice/Gate adapter receives the v2 item's modified-code v1
  compatibility view so old validation and history remain intact.
- The published Learning Item and its exact Practice materialization remain the
  exercise/rubric authority. The Learning Artifact is only the conversation
  facade and must not create a second Gate, Review, Attempt, mastery, progress,
  or scheduling state machine.
- Code and diff presentations are built by the server. Newlines, source and
  modified hashes, hunk IDs, line keys, side mappings, diff hash, and complete
  presentation hash are deterministic. The v2 contract reconstructs the
  canonical builder output from source/modified code and requires exact hunk
  equality, not merely a self-consistent caller-provided hash. A code-only
  presentation has no selectable source side.
- A finding must target the current presentation hash, one existing hunk, one
  enabled side, and a complete contiguous range represented by that hunk. A
  nonempty overlap is insufficient. Unknown or extra fields fail closed.
- The scored taxonomy is closed to `requirements_drift`, `fabricated_api`,
  `logic_boundary`, `contract_integration`, `async_lifecycle`,
  `security_trust`, `error_false_success`, and optional `weak_testing`.
  Readability, maintainability, and style are non-scoring unless an explicit
  project contract maps them into the closed taxonomy.
- Matching is deterministic and server-owned. Category, hunk/side/range
  overlap, required concepts, severity distance, omissions, unsupported
  findings, and duplicates determine the result. Provider/model output may
  author a later teaching message but may not change verdict, score, receipt,
  successor, Artifact state, mastery, or progress.
- The first accepted submission is immutable and stored only in the private
  receipt table. Public Artifact, API/SSE/Desktop, Tutor context, local export,
  logs, and evidence documents omit the full submission, expected findings,
  private rubric/tests/proofs, provider body/reasoning, command/path/container,
  and secrets.
- A failed review must atomically select a distinct published unused remediation
  item at D(n-1) or D(n), with smaller code/range or lower difficulty. Missing
  required remediation fails before receipt or Artifact mutation. Passed review
  has no successor.
- The completed presentation exposes only learner-safe evaluation, score,
  receipt/result identity, and optional remediation handle. Its lock state must
  exactly match a completed Artifact.
- One exact receipt-backed continuation may advertise only the persisted
  remediation handle. Normal teaching context continues to exclude reserved
  remediation items.
- `artifacts/__init__.py` remains contracts-only or lazy. Do not add eager
  imports of conversation events, repository, service, or persistence modules.
- Earlier repeat-bootstrap fragments must accept additive v2 presentation kinds
  before fragment 190 runs, and fragment 110 must continue accepting persisted
  `tutor_conversation_event_v3` rows.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Stale presentation hash, unknown hunk, invented code source side, partial/cross-hunk range | action invalid; no receipt/event |
| Category not enabled by the presentation | action invalid; do not score it as an ordinary false positive |
| Same client action and same body | replay the same Artifact event and receipt |
| Same client action with a different body | `IDEMPOTENCY_CONFLICT` |
| Stale session/item/publication/materialization scope | authority/version conflict; no partial write |
| Failed score without a valid distinct published remediation | fail closed; no terminal receipt |
| Receipt UPDATE/ordinary DELETE | PostgreSQL `23514` |
| Public payload contains submission/rubric/test/proof/protected marker | reject the complete projection |
| Evaluation intent lacks exact Artifact event + receipt identity | stale/cancelled continuation; no provider call |
| Repeat bootstrap with existing event v3 and review receipt | both bootstraps succeed |

## 5. Good / Base / Bad Cases

- **Good:** A diff selection maps to one current hunk/side/range, the server
  deterministically scores it, stores one private receipt, and publishes only a
  safe terminal projection.
- **Good:** A failed D3 review selects one semantically distinct D2 published
  remediation item and the next teaching context advertises only that handle.
- **Base:** Historical v1 Artifact and Lesson Gate review history remain readable
  while new Learning Item-backed conversation reviews materialize as v2.
- **Bad:** Accepting `L1-L4000` because one line overlaps a hunk, allowing source
  findings in code-only mode, or letting the model revise the saved score.
- **Bad:** Serializing `submission_json`, `expected_findings`, matcher concepts,
  validation proofs, or private tests into public feedback or export.

## 6. Tests Required

- Contract tests for stable code/diff hashes, hunk/line maps, stale hash, unknown
  hunk, invented side, exact-range validation, closed categories, and terminal
  remediation/lock shape.
- Deterministic scorer cases for pass, wrong verdict, omission, unsupported
  finding, duplicate finding, severity, suspicious-but-correct/false-positive,
  and wording-independent concept matching.
- Real PostgreSQL tests for materialization, immutable private receipt,
  idempotent replay/conflict, stale scope, success without successor, failure
  with distinct D(n-1)/D(n) remediation, no mastery double-write, and exact
  continuation candidate.
- Existing authoring/publication/validation/Gate v1 suites must remain green.
- Cutover exhaustive inventory, safe export, reset/delete, manifest, bootstrap
  twice with persisted conversation event v3, full API, Ruff, Mypy, lock,
  Desktop Vitest/build, protected-marker audit, and `git diff --check`.

## 7. Wrong vs Correct

### Wrong

```python
if any_line_overlaps(finding.range, hunk):
    score = provider_review(finding, private_rubric)
    artifact.presentation["score"] = score
```

### Correct

```python
submission.validate_presentation(server_built_target)
result = evaluate_model_code_review_v2(
    submission=submission,
    presentation=server_built_target,
    rubric=private_server_rubric,
)
receipt = persist_private_immutable_receipt(result, submission)
return project_safe_terminal_artifact(receipt)
```

The correct path validates exact identity before deterministic server scoring and
keeps private evidence behind the public Artifact facade.
