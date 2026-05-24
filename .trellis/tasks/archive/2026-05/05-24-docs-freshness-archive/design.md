# Design

## Boundary

This is a documentation governance task. The active runtime and code remain unchanged. The cleanup touches only:

- `docs/`
- `.trellis/tasks/05-24-docs-freshness-archive/`

No runtime source, config, or generated dependency directory should be edited.

## Freshness Criteria

A document is considered active when it satisfies at least one of:

- It is listed by `docs/README.md` as source-of-truth or auxiliary context.
- It matches current code paths and commands.
- It defines product/API/database/frontend/QA boundaries still used by implementation or acceptance.
- It is a protected design asset.

A document is considered stale enough to archive when:

- The whole document is superseded by another active document.
- It documents an old repository layout or old project identity as the primary path.
- It points to old implementation directories as the runtime source.
- It duplicates active source-of-truth content and creates conflicting guidance.
- It is a completed roadmap or release artifact no longer needed in active navigation.

A document should be updated rather than archived when:

- Its main role is still necessary.
- Only specific commands, paths, or status text are stale.
- It contains active source-of-truth material plus small outdated sections.

## Archive Shape

Recommended archive path:

```text
docs/archive/2026-05-24/
```

The archive should include:

- moved stale files, preserving original relative naming when practical.
- an archive `README.md` with date, reason, and replacement links.

`docs/README.md` should list the archive location separately from active docs so new readers do not start from stale material.

## Audit Method

1. Build the current docs inventory.
2. Compare it to `docs/README.md`.
3. Search for stale path and old-scope markers:
   - `superpowers`
   - `ReActAgentsTest`
   - `NanGePlus`
   - `01_ReAct` through `07_Refund`
   - `aearn/infra/docker`
   - `apps/api`
   - root `migrations/`
   - `Alembic` / `alembic`
   - removed docs such as `api-design`, `data-model`, `agent-memory-design`, `desktop-ia-and-layout`, `documentation-roadmap`
4. Compare suspicious docs against current code:
   - `aearn/package.json`
   - `aearn/infra/docker-compose.yml`
   - `aearn/services/api/pyproject.toml`
   - `aearn/services/api/app/db/bootstrap.py`
   - `aearn/services/api/app/db/schema.sql`
   - `aearn/apps/desktop/package.json`
   - `aearn/apps/desktop/src/api.ts`
5. Classify each doc in an audit table.

## Compatibility Notes

- Existing links to active source-of-truth documents should continue to work.
- If a file is moved to archive, active docs should not link to it as required reading.
- The protected prototype and design assets stay in place.
- Archive moves are reversible through Git because files are moved, not deleted.

## Rollback

If archival is too aggressive:

1. Move the archived file back to its original path.
2. Restore the corresponding `docs/README.md` row.
3. Re-run documentation grep checks.

No database or runtime rollback is involved.
