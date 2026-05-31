# LangGraph Orchestration Migration Implementation Plan

## Execution Order

- [ ] Finish `graph-shared-runtime-contracts`.
- [ ] Finish `learning-graph-real-orchestration`.
- [ ] Finish `onboarding-graph-orchestration`.
- [ ] Finish `review-graph-orchestration`.
- [ ] Run final cross-flow integration verification.
- [ ] Remove or demote obsolete imperative orchestration only after all child parity tests pass.
- [ ] Archive parent only after all children are archived.

## Parent Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-langgraph-orchestration-migration
```
