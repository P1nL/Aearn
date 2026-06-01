# Learner profile signal quality

## Goal

Improve learner profile updates from stable learning signals such as submissions, errors, review performance, and preferences.

## Confirmed Facts

- `app/services/learner_profile.py` already owns durable learner profile reads, creation, profile summary generation, and observation merging.
- Learning conversation agent tool side effects can already append profile observations, and `store_learning_message_response()` drains those observations into `merge_observations()`.
- Exercise run, exercise submit, and review submit paths persist attempts with runtime status, pass rate, error counts, score, FSRS rating, and code completion details, but profile updates are not yet derived from those stable attempt signals.

## Requirements

- Derive learner profile observations from stable attempt outcomes instead of relying only on conversational guesses.
- Use only service-owned attempt/review data that is already persisted or about to be persisted; do not let graph nodes or tool functions write profile rows directly.
- Capture at least these signal classes: failing weak point, repeated/runtime error pattern, hint/error load, successful mastery/review recovery, and review failure risk.
- Keep profile observations bounded, deterministic, and safe for prompt injection.
- Preserve existing profile merge semantics and existing learning conversation profile tool behavior.
- Cover the new derivation logic and at least one production request path with tests.

## Acceptance Criteria

- [ ] Learner profile can derive deterministic observations from submit/review attempt metadata.
- [ ] Learning submit path merges stable attempt observations into the current user's profile.
- [ ] Review submit path merges stable review observations into the current user's profile.
- [ ] Existing profile tool side-effect updates still merge as before.
- [ ] Focused tests prove weak point, error pattern, pace/performance, and review rating signals are produced without raw code or hidden test leakage.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
