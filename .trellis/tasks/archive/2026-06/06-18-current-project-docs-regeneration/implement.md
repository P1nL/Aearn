# Regenerate Current Project Documentation Implementation Plan

## Preconditions

- Task status remains `planning` until the user approves this plan.
- Before editing `docs/current/`, load `trellis-before-dev` and read relevant project specs.
- Do not change product runtime behavior. Build configuration may be changed only for the approved Vite chunk warning fix.
- Do not delete or replace `docs/design/learning-agent-claude-desktop-framework.html`.

## Execution Checklist

1. Reconfirm clean working tree and active task.
   - `git status --short`
   - `python .\.trellis\scripts\task.py current`

2. Read source-of-truth docs and current handoff docs.
   - `docs/README.md`
   - `docs/setup/newcomer-onboarding-guide.md`
   - `docs/product/user-flows.md`
   - `docs/product/frontend-interaction-spec.md`
   - `docs/architecture/api-contract.md`
   - `docs/architecture/database-schema.md`
   - `docs/architecture/langgraph-state-machine.md`
   - `docs/architecture/code-completion-evaluation-spec.md`
   - `docs/architecture/fsrs-scheduling-spec.md`
   - `docs/qa/acceptance-test-plan.md`
   - `docs/qa/agent-capability-hardening-demo-story.md`
   - `docs/qa/learning-graph-runtime-demo-story.md`

3. Audit backend implementation.
   - Routes in `aearn/services/api/app/routes`.
   - Service/repository/runner/streaming modules in `aearn/services/api/app/services`.
   - Agent graphs/runtime/tooling in `aearn/services/api/app/agents`.
   - DB schema/bootstrap/seeds in `aearn/services/api/app/db`.
   - Tests in `aearn/services/api/tests`.

4. Audit frontend implementation.
   - Pages in `aearn/apps/desktop/src/pages`.
   - Feature components in `aearn/apps/desktop/src/features`.
   - Hooks, stores, `api.ts`, and type files.

5. Audit operations and configuration.
   - `aearn/package.json`
   - `aearn/services/api/pyproject.toml`
   - `aearn/scripts/start-dev.ps1`
   - `aearn/infra/docker-compose.yml`
   - `.env.example` only; do not read or print secrets from `.env`.

6. Create `docs/current/` and generate six docs:
   - `current-state-audit.md`
   - `project-overview-interview.md`
   - `architecture-current.md`
   - `core-flows-current.md`
   - `agent-evaluation-review-current.md`
   - `demo-qa-script.md`

7. Validate documentation quality.
   - Check that each generated doc exists and is non-empty.
   - Check that the package contains exactly the six planned markdown files.
   - Search generated docs for forbidden overclaim patterns such as saying C++/Rust are public runtime-supported unless current code proves it.
   - Search generated docs for accidental secret-like strings; do not include `.env` contents.
   - Run `git diff --check`.

8. Follow-up: classify and safely write back old docs.
   - Keep `docs/current/` at exactly the six planned markdown files.
   - Add archive/writeback decisions to `docs/current/current-state-audit.md`.
   - Low-risk writebacks may update stale setup/worker/index docs; do not delete protected design assets.

9. Follow-up: fix desktop Vite large chunk warning.
   - Inspect `aearn/apps/desktop/vite.config.ts` and current build chunks.
   - Prefer Rollup manual chunks over raising `chunkSizeWarningLimit`.
   - Re-run `pnpm --dir .\aearn desktop:check` and confirm no chunk-size warning remains.

10. Run task validation.
   - `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-18-current-project-docs-regeneration`

11. Optional validation if time and local environment allow.
   - `pnpm --dir .\aearn desktop:check`
   - `uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_db_bootstrap.py`

## Review Gate

Before `task.py start`, ask the user to confirm this planning package. Once approved, run:

```powershell
python .\.trellis\scripts\task.py start .\.trellis\tasks\06-18-current-project-docs-regeneration
```

## Risks

- Existing docs may contain stale claims that are still partially true. Mitigation: classify claims rather than deleting or rewriting old docs.
- Some behavior may depend on local services or model/provider configuration. Mitigation: separate code evidence from runtime verification and state unverified areas clearly.
- Generated docs could become another stale layer. Mitigation: keep them as a current-state package with explicit date/context and traceable paths.
