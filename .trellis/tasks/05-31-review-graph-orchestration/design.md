# Review Graph Orchestration Design

## Data Flow

1. Review route validates request and idempotency.
2. Service loads due review state, session facts, attempt facts, and safe learner context.
3. Review graph chooses start/reject/result/update/feedback path.
4. Service applies graph intents through existing review scheduler and repositories.
5. Public response remains compatible with current review API and UI.

## Rollback

Keep a feature flag until graph-enabled M4 parity and idempotency tests pass.
