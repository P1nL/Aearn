# Learner Profile Runtime Integration Design

## Boundaries

- `app/services/learner_profile.py` owns profile read/merge helpers.
- Learning routes/repositories own authenticated `user_id` and transaction boundaries.
- Agent tools may request profile updates only through `AgentSideEffects.profile_updates`.

## Data Flow

1. Session start calls profile ensure for `user_id`.
2. Learning message generation loads compact profile summary.
3. Agent/tool context receives the summary as prompt-safe context.
4. After durable learning events, service code builds observations and calls profile merge.
5. Side-effect profile updates are drained for the authenticated user only.

## Compatibility

- Missing profile data is treated as empty context.
- Profile writes do not affect scoring, review scheduling, or Attempt idempotency.

## Rollback

Stop calling profile ensure/summary/merge; existing learning APIs still work without profile context.
