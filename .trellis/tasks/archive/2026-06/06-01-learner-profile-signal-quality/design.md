# Learner Profile Signal Quality Design

## Boundaries

- `app/services/learner_profile.py` remains the profile repository and signal normalization layer.
- Learning and review repositories may call learner profile helpers after they persist an evaluated attempt.
- Agent tools can still emit profile observations, but stable attempt-derived observations are service-derived and deterministic.
- No graph node, router, API route, or frontend component writes profile rows directly.

## Data Flow

1. A run/submit/review submit path persists an `attempts` row.
2. The owning service builds a bounded attempt signal payload from the attempt row, exercise/knowledge point context, and review source.
3. `derive_stable_profile_observations()` converts the payload into observation records accepted by `merge_observations()`.
4. The repository merges observations inside the same service transaction.
5. The existing `build_profile_summary()` prompt input benefits from the merged stable signals on later turns.

## Observation Contract

- `weak_point`: stable failures on a knowledge point, especially low score, low pass rate, or negative review rating.
- `error_pattern`: normalized runtime/error cause categories, never raw code, stderr, stack traces, or hidden tests.
- `pace_indicator`: bounded signal metadata such as `last_attempt_outcome`, `hint_load`, `review_rating`, and `mastery_signal`.
- `learning_preference`: remains explicit/profile-tool driven only; attempt-derived logic does not infer preferences from one-off behavior.

## Compatibility

- Existing JSONB profile schema is reused.
- Existing `merge_observations()` caps still apply.
- Existing tests that assert `session_count` increments per merge remain valid.

## Rollback

- Remove the repository calls to the derivation helper to stop profile updates from attempt signals.
- The helper is pure and covered by unit tests, so rollback does not require schema changes.
