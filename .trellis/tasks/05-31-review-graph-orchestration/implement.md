# Review Graph Orchestration Implementation Plan

## Checklist

- [ ] Map review route/service branches and FSRS scheduler write timing.
- [ ] Add review graph state and nodes.
- [ ] Add graph result adapter for review start, result, scheduler, and feedback intents.
- [ ] Enable graph path behind a flag.
- [ ] Add graph-enabled review parity and idempotency tests.
- [ ] Run focused tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-review-graph-orchestration
```
