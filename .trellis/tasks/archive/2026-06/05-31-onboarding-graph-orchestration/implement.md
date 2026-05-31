# Onboarding Graph Orchestration Implementation Plan

## Checklist

- [ ] Map current onboarding service branches and StructuredJudgement use.
- [ ] Add onboarding graph state and nodes.
- [ ] Add graph result adapter for route-card and confirmation intents.
- [ ] Enable graph path behind a flag.
- [ ] Add graph-enabled onboarding parity tests.
- [ ] Run focused tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_structured_judgement.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-onboarding-graph-orchestration
```
