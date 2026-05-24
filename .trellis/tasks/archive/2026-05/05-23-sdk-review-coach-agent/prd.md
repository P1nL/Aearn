# Add SDK review coach agent

## Goal

Add SDK-backed review coaching for review session guidance and variant rationale while keeping due-review ordering, `ReviewState`, `ReviewLog`, `Attempt(review_submit)`, FSRS scheduling, idempotency, and review API contracts owned by Aearn.

This task improves the Agent-facing parts of the review experience without moving deterministic scheduling or final evaluation into the SDK.

## Requirements

- Add an Aearn-owned SDK Review Coach module under `aearn/services/api/app/agents/`, likely `review_coach_agent.py`.
- Preserve existing review API contracts:
  - `GET /api/reviews/today`;
  - `POST /api/reviews/start`;
  - `POST /api/reviews/{session_id}/exercise-result`.
- SDK can generate or improve:
  - `initial_agent_message` for review sessions;
  - `variant_reason` wording;
  - optional short coaching text grounded in current due review context.
- Aearn service/repository code must continue to own:
  - due-review filtering and ordering;
  - selecting or creating the review exercise;
  - validating `REVIEW_NOT_DUE`;
  - writing `Attempt(review_submit)`;
  - applying FSRS and `ReviewState` updates;
  - review idempotency records.
- SDK context must be read-only and safe:
  - due review summary;
  - knowledge point title/description/weak points;
  - bounded latest attempt facts;
  - no hidden tests, solutions, full submissions, or raw provider errors.
- Preserve deterministic fallback if SDK is unavailable, output is invalid, or guardrails block.

## Acceptance Criteria

- [ ] `app/agents/review_coach_agent.py` or equivalent exists and is used by review session guidance.
- [ ] `GET /api/reviews/today` ordering and fields remain deterministic and SDK-free.
- [ ] `POST /api/reviews/start` still creates/reuses review sessions according to existing idempotency and due-state rules.
- [ ] `POST /api/reviews/{session_id}/exercise-result` still writes `Attempt(review_submit)` and updates `ReviewState` outside SDK code.
- [ ] SDK-generated review text never changes FSRS rating, `due_at`, forget risk, or pass/fail results.
- [ ] SDK output cannot leak hidden test IDs, hidden test text, reference answers, or provider raw errors.
- [ ] Existing `tests/test_reviews_m4.py` still passes.
- [ ] Focused fake SDK tests cover review coach success, fallback, invalid output, and leakage blocking.

## Out Of Scope

- Replacing FSRS scheduling.
- Moving review exercise result evaluation into the SDK.
- Creating a new review chat endpoint.
- Frontend ReviewPage redesign.
- Note Assist or Teaching Agent changes.

## Dependencies

- `05-23-sdk-teaching-tools-guardrails` should finish first for shared guardrails and safe context tooling.
- `05-23-sdk-exercise-coach-endpoints` can provide shared coaching normalization patterns, but review scoring must remain separate.
