# Implementation Plan

## Checklist

- [x] Add `docs/qa/learning-graph-runtime-demo-story.md`.
- [x] Link it from `docs/README.md` auxiliary docs.
- [x] Include local demo commands and expected evidence.
- [x] Include cross-page boundary explanation for onboarding/review.
- [x] Include fallback/redaction/idempotency evidence.
- [x] Run docs-oriented checks plus targeted backend tests that back the demo evidence.
- [ ] Validate and archive the Trellis task after checks pass.

## Validation Commands

```powershell
Select-String -Path docs\README.md,docs\qa\learning-graph-runtime-demo-story.md -Pattern 'learning graph runtime|LANGGRAPH_ENABLED|onboarding|review|tool_status'
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_graph.py tests/test_graph_event_stream.py tests/test_learning_sessions_m3.py tests/test_onboarding_m2.py tests/test_reviews_m4.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Risk Notes

- This task is documentation-only. If implementation changes seem necessary, stop and split them into a separate task.
- Keep `.codex/config.toml` and `.claude/skills/grill-me/` out of staging.
