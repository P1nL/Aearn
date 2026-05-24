# Implementation Plan

## Checklist

1. Reconfirm git status and current active task.
2. Create a docs inventory table covering every file under `docs/`.
3. Search for stale paths, old project identities, removed-doc references, and obsolete commands.
4. Inspect each suspicious document enough to decide whether to archive or update.
5. Write an audit result table in this task directory.
6. Move whole stale documents to `docs/archive/2026-05-24/` only when the whole document is obsolete.
7. Update stale sections in active documents instead of archiving them.
8. Update `docs/README.md` to reflect active docs, auxiliary docs, protected assets, and archive location.
9. Run validation:
   - `git diff --check`
   - stale-marker scan over active markdown docs
   - index/path existence check for docs links
   - `git status --short`
10. Report:
   - files archived
   - files updated
   - files intentionally kept
   - validation results
   - any residual risks

## Validation Commands

```powershell
git diff --check
```

```powershell
$patterns = @(
  'superpowers',
  'ReActAgentsTest',
  'NanGePlus',
  '01_ReAct',
  '02_ReAct',
  '03_ReAct',
  '04_ReAct',
  '05_ReAct',
  '06_ReAct',
  '07_Refund',
  'aearn/infra/docker/',
  'apps/api',
  'uv run alembic',
  'uv run celery -A app.tasks.celery_app'
) -join '|'
Select-String -Path .\docs\**\*.md,.\docs\*.md -Pattern $patterns
```

```powershell
git status --short
```

## Risky Files

- `docs/README.md`: source-of-truth index; mistakes here mislead every future reader.
- `docs/setup/development-environment.md`: contains necessary environment setup but likely has stale early-planning commands.
- `docs/design/learning-agent-claude-desktop-framework.html`: protected asset; do not move.
- `docs/setup/newcomer-onboarding-guide.md`: newly added guide; should not be archived during this cleanup unless it is clearly wrong.

## Stop Conditions

- If an archive candidate is also referenced as the only source-of-truth for a current feature, stop and update rather than archive.
- If a move would affect protected prototype assets, stop and ask the user.
- If a stale marker appears only inside an explicit "removed docs" or "archive" section, do not treat it as a failure.
