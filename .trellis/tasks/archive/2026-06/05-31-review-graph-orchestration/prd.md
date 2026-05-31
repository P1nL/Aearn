# Review Graph Orchestration

## Goal

Make LangGraph the real orchestration layer for review page flows.

## Requirements

- Graph owns review flow decisions for review start, due-state validation routing, exercise result handling, FSRS update coordination, and review coach feedback.
- Review services/repositories still own session creation, `Attempt(review_submit)` writes, `ReviewState` updates, `ReviewLog` writes, idempotency, and public response envelopes.
- Graph must not double-apply FSRS updates or bypass scheduler idempotency.
- Existing review M4 contracts must remain stable.

## Acceptance Criteria

- [ ] Review routes invoke review graph as primary orchestration when enabled.
- [ ] Graph emits FSRS/update intents that existing services apply once.
- [ ] Review coach feedback is graph-routed without exposing model/provider internals.
- [ ] Existing review M4 tests pass with graph orchestration enabled.
- [ ] Flag-off rollback remains available during migration.
