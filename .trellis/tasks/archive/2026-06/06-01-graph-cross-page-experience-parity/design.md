# Design

## Scope

This task preserves cross-page behavior while the learning page becomes the complete graph runtime slice. Onboarding and review remain graph-assisted service flows: graph outputs may guide decisions, but page services and repositories still own durable writes, idempotency, public responses, and SSE framing.

## Boundary Rules

Use the shared `validate_run_result_for_boundary()` contract for onboarding and review before consuming graph decisions.

Allowed onboarding intents:

- `TOOL_CALL -> build_plan_draft|rebuild_plan_draft`
- `PERSISTENCE -> confirm_plan`
- `FEEDBACK_REQUEST -> onboarding_clarification`

Allowed review intents:

- `PERSISTENCE -> review_session|attempt_and_fsrs`
- `TOOL_CALL -> review_coach|evaluate_warmup`

Invalid graph output returns `None` from the local decision helper, which makes the route continue through the existing deterministic service path.

## Public Contract

Onboarding keeps existing `session_created`, `agent_message`, `tool_call`, `done`, and `error` SSE frames. Review keeps existing JSON and message SSE frames. This task does not emit graph runtime status frames outside the learning message stream and does not add frontend event types.

## Rollback

Rollback is limited to removing the onboarding/review boundary-validation helper changes and their tests. No database, frontend, or migration cleanup is required.
