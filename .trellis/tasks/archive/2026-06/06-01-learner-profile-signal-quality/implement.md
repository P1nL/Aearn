# Learner Profile Signal Quality Implementation Plan

## Checklist

- Add pure signal derivation helpers to `app/services/learner_profile.py`.
- Call the helper from `submit_learning_session_exercise()` after evaluated submit attempts are inserted.
- Call the helper from `submit_review_exercise_result()` after evaluated review attempts are inserted.
- Add unit tests for derived weak point, error pattern, pace, and review rating observations.
- Add or extend request-path tests proving submit/review submit updates the profile.

## Validation

- `uv --directory .\aearn\services\api run python -m pytest tests/test_learner_profile.py tests/test_learning_sessions_m3.py tests/test_reviews_m4.py`
- `uv --directory .\aearn\services\api run ruff check .`
- `uv --directory .\aearn\services\api run python -m mypy app`

## Risk Notes

- Avoid deriving preferences from weak evidence.
- Do not store raw code, stderr, hidden tests, or provider payloads in learner profile observations.
