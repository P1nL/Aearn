# Language runtime runner registry

## Goal

Extract runtime execution into a language runner registry, preserving Python sandbox support while defining runner contracts for Node, TypeScript, SQL, browser preview, and compiled languages.

## Requirements

- Depend on `06-01-language-capability-contract`; runner support must not define broader product promises than the capability matrix.
- Define a shared runner capability contract so learning flows, graph runtime, review logic, and tools do not hard-code language execution branches.
- Adapt the existing Python subprocess sandbox into the registry as the first real executable runner.
- Make sandbox limits explicit: subprocess isolation, timeout, restricted imports, output caps, and the fact that it is not container-grade isolation.
- Define browser preview, Node/TypeScript, SQL, and compiled-language runner contracts without claiming unsupported runtimes are already implemented.
- Return capability-aware unsupported responses for languages that can be taught or grounded but cannot yet be safely executed.
- Cover runner selection, sandbox adapter behavior, and unsupported fallbacks with tests.
- Preserve current public API response shapes for run/submit unless a documented contract update is required.
- Keep durable persistence in existing services/repositories; runners return results and metadata only.

## Acceptance Criteria

- [ ] Runtime execution has a language runner registry entry point.
- [ ] Python execution still uses the existing subprocess sandbox through the registry.
- [ ] Sandbox behavior and non-goals are documented and testable.
- [ ] Browser preview, Node/TypeScript, SQL, and compiled-language runner contracts exist or are explicitly represented as unsupported/later.
- [ ] The learning flow can ask one capability source whether a language supports execution, tests, static analysis, preview, or fallback-only behavior.
- [ ] Unsupported languages return clear product-safe responses instead of failing silently or pretending to run.
- [ ] Tests cover Python sandbox success/failure/timeout paths, runner selection, and unsupported runner fallback.
- [ ] Child task artifacts explicitly name dependencies instead of relying on task tree order.

## Task Tree

```text
language-runtime-runner-registry
├─ runner-capability-contract
├─ python-sandbox-adapter
├─ sandbox-security-boundary-hardening
├─ browser-preview-runner-contract
├─ node-typescript-runner-contract
├─ sql-runner-contract
├─ compiled-language-runner-contract
└─ runner-registry-tests
```

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
