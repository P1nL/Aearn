# Agent Handoff Runtime Routing Implementation Plan

## Checklist

- [ ] Inspect `router.py`, `sdk_runtime.py`, and learning conversation client construction.
- [ ] Add route call at the production learning message boundary.
- [ ] Build safe handoff target list for supported routes.
- [ ] Add tests that monkeypatch/spy route and handoff construction from real request handling.
- [ ] Run focused tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_agent_router.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-agent-handoff-runtime-routing
```

