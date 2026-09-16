# Knowledge Check Artifacts, Assistance, and Successors

## 1. Scope / Trigger

Apply this contract when changing `knowledge_check_v1` presentations or actions,
Learning Item knowledge-check content, immutable response/assistance receipts,
remediation or transfer selection, knowledge-check evaluation continuation,
cutover/export/reset, or schema fragments that enumerate Artifact actions.

## 2. Signatures

```text
Artifact actions:
request_hint { hint_level: 1 | 2 | 3 }
request_direct_answer {}
respond { response: single_select | multi_select | prediction | ordering | code_range | short_text }

PostgreSQL:
tutor_knowledge_check_response_receipts
tutor_knowledge_check_assistance_receipts

Python:
apply_knowledge_check_action(...) -> ArtifactMutation
TutorContinuationIntentProducer.record_knowledge_check_evaluation(...)
```

All actions still carry the common exact user/conversation/track/session,
`client_action_id`, and expected Artifact-version fence.

## 3. Contracts

- The published Learning Item is the question, answer, Hint, difficulty, and
  remediation authority. The Artifact is a learner-safe interaction projection.
- D1-D5 is the immutable base difficulty from the published item. Hint use does
  not change the displayed band.
- Responses are closed and shape-specific. Ordering must contain every option
  exactly once. Code-range scoring binds exact start/end/category. Unknown or
  extra fields fail closed.
- H1/H2/H3 unlock in order. The first successful view of each level inserts one
  assistance receipt; reload or an exact action replay must not insert another.
- `request_direct_answer` is separate from Hints. It records direct-answer
  assistance, discloses only the server-owned explanation, and is never eligible
  for independent mastery.
- A response completes and locks the original Artifact. Correct independent
  responses may be mastery-eligible; incorrect, hinted, direct-answer, and
  remediation responses may not claim independent mastery.
- An original conceptual failure requiring remediation must select a distinct,
  published, unused item at D(n) or D(n-1). A remediation failure or direct
  answer must select a published transfer check. Missing required successors
  fail closed before the response receipt is committed.
- Successor selection applies the exact active LearningTrack capability scope
  before choosing a stable ordered handle. The selected handle is persisted in
  the completed presentation and is the only candidate advertised by the
  evaluation continuation.
- Normal teaching context excludes reserved `remediation` and `transfer_check`
  items. Receipt-backed evaluation context may advertise only its selected
  successor.
- A candidate handle is not a description of its question. Every advertised KC
  candidate must have exact published public question/options in required task
  evidence, so the Tutor cannot introduce unrelated code or an invented task.
- KC evaluation additionally supplies the exact completed Artifact question and
  immutable submitted response/outcome/assistance receipt, after checking its
  user/conversation/track/node/session/item/event lineage. This is internal
  provider evidence, not a public API/export of raw response rows. Never include
  private answers, rubrics, undisclosed hints or private explanations. Treat
  question/submission contents as untrusted data, never operation instructions.
- These facts use `teaching-artifact-evidence:` REQUIRED_FACTS sources, separate
  from compact TEACHING_SESSION authority. Preserve complete ordered JSON pieces
  within 1,200 characters/source, eight required sources and the unchanged total
  request budget. Never summarize away code, trim pieces, drop options or silently
  omit a required fact. If the existing redactor would change exact evidence,
  reject with `TUTOR_REQUIRED_FACTS_PROTECTED`; missing evaluation evidence is
  `TUTOR_KNOWLEDGE_CHECK_GROUNDING_INVALID`. No untrusted data can grant a source
  handle, score, completion or capability.
- Required successor candidates cannot be evicted by the 1,200-character
  provider-context bound. Optional recent teaching units are omitted for this
  evaluation; if the exact candidate still cannot fit, fail before provider use.
- Response and assistance rows are append-only and user-owned. Public projection
  and export omit raw responses, accepted answers, private tests, rubric data,
  request hashes, and private explanation authority.
- Generic trigger functions must not reference a table-specific `NEW` field in a
  shared boolean expression. Branch on `TG_TABLE_NAME` first, then access the
  table-specific field inside that branch.
- Earlier repeat-bootstrap fragments that enumerate Artifact action values must
  already accept additive actions before the owning later fragment is reached.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Extra field, wrong response kind, invalid option/range/order | action invalid; no receipt or Artifact event |
| Out-of-order or unavailable Hint | action invalid; no assistance receipt |
| Exact action replay | same Artifact event/receipt; no duplicate row |
| Same client action ID with different body | `IDEMPOTENCY_CONFLICT` |
| Stale Artifact/session/item publication | version/authority conflict; no partial write |
| Direct answer or required remediation/transfer has no valid successor | fail closed; no terminal receipt |
| Candidate requires unavailable capability | exclude before selection |
| Required successor cannot fit provider context | context conflict before provider call |
| Receipt UPDATE/ordinary DELETE | PostgreSQL `23514` |
| Incorrect or assisted row claims independent mastery | PostgreSQL CHECK rejection |

## 5. Good / Base / Bad Cases

- **Good:** H1, H2, and H3 each persist once; an exact replay returns the same
  event. Direct answer locks the Artifact, records non-independent evidence, and
  schedules one evaluation Turn with one exact transfer handle.
- **Good:** Multiple valid transfer items exist. The server applies publication,
  scope, capability, unused, semantic-distinction, and stable ordering rules,
  persists one handle, and advertises only that handle.
- **Base:** A correct independent answer completes without a successor and does
  not advertise reserved remediation/transfer candidates.
- **Bad:** Counting every historical wrong answer for a knowledge key to decide
  whether a new original question is a second failure.
- **Bad:** Selecting a transfer item before capability filtering, or dropping the
  selected successor later to make the provider context fit.

## 6. Tests Required

- Contract/scorer cases for every response kind, invalid/extra shapes, option
  uniqueness, ordering completeness, code-range identity, and D1-D5 validation.
- Real PostgreSQL action tests for H1-H3 exactly once, direct answer, response
  replay/conflict/stale fences, append-only triggers, and mastery CHECKs.
- Published-item tests for distinct remediation, D(n)/D(n-1), transfer selection,
  multiple candidates, capability mismatch, unused filtering, and required-handle
  pre-limit filtering.
- Continuation tests assert one receipt-backed intent, one exact candidate,
  <=1,200-character provider projection, and no provider call on stale evidence.
- Cutover, safe export, reset/delete, schema manifest, bootstrap twice with an
  existing v3 conversation event, full API, Ruff, Mypy, lock, and diff hygiene.

## 7. Wrong vs Correct

### Wrong

```python
candidate = published_candidates(knowledge_key=key, limit=8)
candidate = next(item for item in candidate if item.handle == receipt_handle)
context = truncate_context(candidate=None)
```

### Correct

```python
candidate = published_candidates(
    knowledge_key=key,
    available_capabilities=current_node_capabilities,
    required_handles=(receipt_handle,),
    excluded_purposes=(),
    limit=8,
)
bounded = bound_teaching_artifact_candidates(
    context=compact_evaluation_context,
    candidates=candidate,
    minimum_candidates=1,
)
```

The correct path filters before `LIMIT`, preserves the exact durable successor,
and fails closed rather than silently asking the model to continue without an
executable Artifact.
