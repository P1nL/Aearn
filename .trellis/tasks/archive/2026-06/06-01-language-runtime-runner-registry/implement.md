# Language Runtime Runner Registry Implementation Plan

## Ordered Checklist

- [ ] Start and complete `06-01-language-capability-contract` first.
- [ ] Complete `06-01-runner-capability-contract`.
- [ ] Implement a registry module and normalized runner result contract.
- [ ] Complete `06-01-python-sandbox-adapter` and wire Python through the registry.
- [ ] Complete `06-01-sandbox-security-boundary-hardening`.
- [ ] Add browser preview, Node/TypeScript, SQL, and compiled-language contracts as explicit runner entries or fallback descriptors.
- [ ] Complete `06-01-runner-registry-tests`.
- [ ] Update docs/API examples only where behavior or metadata changes.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
```

## Rollback Points

- Keep `runtime_runner.run_exercise()` callable until route/service tests prove the registry adapter preserves behavior.
- Avoid widening public language enums in the runner registry task unless the language capability contract and seed/catalog changes are already implemented.
- If a later runner contract is not executable, ship it as an unsupported descriptor rather than a partial runner.
