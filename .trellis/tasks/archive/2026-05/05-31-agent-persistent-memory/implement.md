# Implementation Plan: Agent Persistent Memory

## Ordered Steps

1. Add `learner_profiles` table to `app/db/schema.sql`.

2. Create `app/services/learner_profile.py`:
   - `get_learner_profile(conn, user_id)` → dict or None
   - `ensure_learner_profile(conn, user_id)` → creates if not exists
   - `merge_observations(conn, user_id, observations)` → incremental update
   - `build_profile_summary(profile)` → condensed string for system prompt

3. Add agent tools to `app/agents/tools.py`:
   - `get_learner_profile` read tool (returns profile summary)
   - `update_learner_profile` write tool (appends observations via side_effects)
   - Add `profile_updates` field to `AgentSideEffects`

4. Inject profile summary into learning agent system prompt in `learning_conversation.py`.

5. Add profile draining at session message commit: after agent turn, if `side_effects.profile_updates` has entries, call `merge_observations`.

6. Create `tests/test_learner_profile.py`:
   - Test: profile created on first access
   - Test: observations merge correctly (increment, not overwrite)
   - Test: weak_points accumulate across multiple merges
   - Test: observations capped at 50
   - Test: profile summary is bounded string
   - Test: cross-session memory (session 1 records weak point, session 2 reads it)

7. Verify all tests pass.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learner_profile.py -v
uv --directory .\aearn\services\api run python -m pytest tests/ -v
uv --directory .\aearn\services\api run ruff check app/services/learner_profile.py app/agents/tools.py
uv --directory .\aearn\services\api run python -m mypy --follow-imports=skip app/services/learner_profile.py app/agents/tools.py
```

## Review Gates

- Existing tests pass without modification
- Profile is additive — no session flow changes
- Agent tools follow same pattern as existing write tools
- Profile data scoped to user_id (no cross-user leakage)

## Rollback Points

- Profile tools are only added when side_effects + context are provided (same pattern as write tools)
- If profile table doesn't exist, `get_learner_profile` returns empty dict gracefully
