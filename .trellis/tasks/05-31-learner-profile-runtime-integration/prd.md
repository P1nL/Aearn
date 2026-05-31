# Learner Profile Runtime Integration

## Goal

Wire `learner_profile.py` into real learning sessions so Aearn can ensure a per-user profile, summarize it into agent context, and merge safe observations from completed learning events.

## Requirements

- Ensure a learner profile exists when a learning session starts or resumes.
- Inject `build_profile_summary()` into the agent/tool context without exposing raw cross-session data.
- Merge profile observations only from service-owned, authenticated user/session facts.
- Drain profile-related `AgentSideEffects` after side-effect wiring exists.
- Preserve behavior when no profile observations are available.

## Acceptance Criteria

- [x] Real learning session start ensures a profile for the current user.
- [x] Learning conversation context includes a compact profile summary.
- [x] Profile updates are merged from real learning observations or accepted side effects.
- [x] Cross-user profile access is impossible from route/service tests.
- [x] Model-free tests cover empty profile and incremental merge behavior.
- [x] Focused backend tests, lint, mypy, and task validation pass.
