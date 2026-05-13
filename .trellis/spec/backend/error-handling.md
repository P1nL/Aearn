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
