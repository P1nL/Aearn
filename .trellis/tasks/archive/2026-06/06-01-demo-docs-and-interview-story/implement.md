# Demo Docs and Interview Story Implementation Plan

## Checklist

- Create `docs/qa/agent-capability-hardening-demo-story.md`.
- Update `docs/README.md` with the new QA/demo entry.
- Include explicit supported/scaffolded capability boundaries.
- Include validation commands used in this closeout.

## Validation

- `Select-String -Path .\docs\README.md -Pattern 'agent-capability-hardening-demo-story'`
- `uv --directory .\aearn\services\api run ruff check .`
- `pnpm --dir .\aearn desktop:check`
