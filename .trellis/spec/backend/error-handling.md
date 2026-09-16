# Error Handling

> How errors are handled in this project.

---

## Overview

Aearn's backend error contract is defined in `docs/architecture/api-contract.md`. The current API service is still Milestone 0 dependency scaffolding, so new FastAPI code must implement that contract instead of inventing ad-hoc response shapes.

All non-2xx API responses must return a stable JSON error envelope with `error.code`, `error.message`, `error.request_id`, and `error.recoverable`.

---

## Error Types

- Use stable API error codes from `docs/architecture/api-contract.md`, such as `VALIDATION_ERROR`, `PLAN_NOT_FOUND`, `RUNNER_TIMEOUT`, and `IDEMPOTENCY_CONFLICT`.
- Domain errors should map to explicit HTTP status codes and API error codes.
- Validation errors should be normalized to `VALIDATION_ERROR`; do not leak framework-native validation payloads directly if they break the documented envelope.
- Runner and evaluation errors must distinguish `runtime_error`, `timeout`, `unsupported`, invalid JSON, and service unavailability.

---

## Error Handling Patterns

- Preserve or generate a `request_id` for every API error. Prefer `X-Request-Id` when provided by the client.
- Return recoverability explicitly so the desktop UI can decide whether to show retry actions.
- Idempotent write retries must return existing business results when possible, not create duplicate `Attempt`, `ReviewState`, or `ReviewLog` records.
- Do not mark a review, submit, or note operation as complete if the required database write failed.
- Let unexpected exceptions become `INTERNAL_ERROR` responses while logging enough context to debug without exposing secrets.

---

## API Error Responses

Use this shape for all non-2xx responses:

```json
{
  "error": {
    "code": "PLAN_NOT_FOUND",
    "message": "学习计划不存在",
    "details": {
      "plan_id": "plan_404"
    },
    "request_id": "req_001",
    "recoverable": true,
    "next_action": "retry_same"
  }
}
```

For SSE endpoints, stream an `error` event and then terminate the stream with a clear final event. Each `data` frame must be single-line JSON.

---

## Common Mistakes

- Returning raw FastAPI/Pydantic errors that do not match the API contract.
- Treating `Attempt(run)` failure as a submitted exercise result. `run` can fail without updating `ReviewState`.
- Returning success before durable writes to `attempts`, `review_states`, `review_logs`, or `notes` complete.
- Using user-facing messages as branch conditions in the frontend instead of stable `error.code`.

## Scenario: Prepared teaching admission and durable terminal errors

### 1. Scope / Trigger

Managed `lesson_teaching` admission, Harness terminal snapshot/history projection, Queue retry, and diagnostic logging.

This also covers provenance admission before a new managed LessonDocument is authored.

### 2. Signatures

- Knowledge-bound input without prepared authority: `409 TEACHING_NOT_READY`, recoverable preparation error, before new run/message/job admission.
- `terminal_is_recoverable(outcome, diagnostic_code)` is shared by Queue retry and terminal error projection.
- `log_safe_event(logger, event, *, exception=None, **fields)` renders an allowlisted JSON **message**, not arbitrary LogRecord extras.
- Grounding metadata stores `provenance` with `schema_version=grounding_provenance_v1`, `kind=http_fetch|fixture|unknown`, source ID, requested/final URL and document hash.

### 3. Contracts

- Check current TeachingSession/checkpoint/lesson identity for new managed inputs; replay accepted idempotent input against its original stimulus rather than mutable current session state.
- General track Q&A remains distinct from knowledge-bound managed teaching; missing authority never grants generic capabilities or artifact ownership.
- Historical/new unsuccessful Harness turns project stable server-owned `kind=error` items. Do not duplicate an existing dead-dispatch/runtime error or turn normal cancellation/supersession into a failure.
- Public codes/copy contain no rejected identifiers, provider content, internal diagnostics or exception details. Desktop may continue hiding process items because the server supplies actual error items.
- Unknown capability/effect rejection is not automatically retryable. Retry UI must agree with Queue admission.
- Safe diagnostics record stage, IDs, frozen catalog/Skill, bounded counters and exception/cause class only. Unknown action identifiers are hashed. Never serialize payloads, exception text or raw reasoning.
- Lesson receipt persistence failure must log its own stage and preserve the preceding safe failure code/stage; it must not erase evidence of the original operation.
- Gate write routes explicitly commit successful owner-service results before returning HTTP success. A preflight SELECT can start an implicit outer psycopg transaction; inner service `transaction()` blocks may only release savepoints, while the shared connection helper closes without committing. HTTP tests must inspect results from a second connection, not only the request connection or response JSON. Error paths roll back and read routes do not acquire a blanket commit policy.
- New live lesson sources require verified `http_fetch` provenance, allowlisted redirects/URLs and matching document/chunk hashes. Filter before top-k; never promote unknown historical metadata to HTTP provenance based on an official label.
- Fixture admission is an explicit internal test-only seam. Existing frozen document reads are unchanged; replacing a live index does not rewrite history.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Unprepared managed teaching input | 409; no new message/run/job/provider call |
| Accepted input replay after checkpoint/session closes | Original receipt/scope replay, no duplicate admission |
| Unknown capability/effect terminal | One safe non-retryable error in snapshot/history |
| Dead dispatch/runtime already has public error | No second derived Harness error |
| Formatter contains only `%(message)s` | Safe diagnostic fields remain present in JSON message |
| Arbitrary exception/payload contains secret markers | No text, arguments or payload in emitted diagnostic |
| Only fixture/unknown source candidates exist | `LESSON_SOURCE_EVIDENCE_INSUFFICIENT` before provider construction |
| HTTP redirect exits registered domains | Reject before following the redirect |

### 5. Good / Base / Bad Cases

- Good: reload an old unavailable run and show its server-projected error without rewriting the run.
- Base: completed, cancelled and superseded histories retain their existing non-failure behavior.
- Bad: show a Retry button for every failure or infer authority from the text of a learner request.

### 6. Tests Required

Prepared/missing/closed-session admission, idempotency replay, snapshot/history cursor and cross-user fencing, error deduplication, retry parity, default-formatter visibility and protected-content absence. Database tests use a verified disposable database, never a retained real-model-test database.

### 7. Wrong vs Correct

- Wrong: drop every process from the UI while the backend publishes no terminal error; log only `extra={...}` and discard the actual dispatch exception class.
- Correct: derive a stable safe terminal error on the server and emit explicit, bounded JSON diagnostic events at the failure boundary.

## Tutor domain-assembly validation diagnostics

Catch Pydantic `ValidationError` before the generic `ValueError` fallback during provider-to-domain decision assembly. Preserve sanitized field paths/categories in same-primary-model replacement feedback; do not serialize input values, validator exception text or provider bodies. `tutor_provider_validation_issue` logs bounded run/revision/attempt, diagnostic code and issue category; only a fixed set of server schema paths is readable, other locations are hashed. Existing durable attempt `diagnostic_code` remains schema-compatible. Maximum provider decision attempts remains two. Historical INVALID_ACTION receipts cannot be reconstructed into exact field failures.
