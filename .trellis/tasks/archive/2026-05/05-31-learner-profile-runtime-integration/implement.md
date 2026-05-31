# Learner Profile Runtime Integration Implementation Plan

## Checklist

- [x] Inspect `learner_profile.py` API and current learning session lifecycle.
- [x] Add ensure call to real session start/resume path.
- [x] Add profile summary to learning conversation/tool context.
- [x] Drain accepted profile side effects after learning message generation.
- [x] Add tests for ensure, summary injection, merge, and user scoping.
- [x] Run focused backend tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_learner_profile.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-learner-profile-runtime-integration
```
