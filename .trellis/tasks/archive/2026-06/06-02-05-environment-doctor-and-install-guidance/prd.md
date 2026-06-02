# 05 Environment Doctor and Install Guidance

## Goal

Add a product-facing environment doctor that reports local setup facts, language runner readiness, and safe Windows-first install guidance for the local-only Aearn desktop product.

## User Value

- Learners can see why a local feature or language runner is unavailable without reading terminal output.
- Aearn can distinguish "toolchain missing" from "runner not implemented yet" and avoid overclaiming TypeScript, SQL, Java, Go, C#, Rust, or C++ execution.
- The Agent and UI can ground environment explanations in detected facts and allowlisted static guidance instead of inventing install commands.
- Local startup support becomes discoverable inside the product, not only in docs or terminal scripts.

## Dependencies

- Depends on completed local startup work, especially `aearn/scripts/start-dev.ps1` and `pnpm --dir .\aearn dev*` commands.
- Depends on `app/services/language_capabilities.py` as the canonical language capability matrix.
- Depends on `app/services/runner_registry.py` as the canonical runner contract source.
- May reference grounding/citation metadata from the parent scope, but must not depend on live arbitrary web search.

## Requirements

- Provide a backend environment doctor API that returns local facts for API health, startup script presence, Python, `uv`, Node, `pnpm`, Docker, JDK, Go, .NET, and SQL/database-related tooling.
- Return a stable capability matrix that joins language capability state, runner key, execution state, detected toolchain status, and learner-safe disclosure text.
- Return allowlisted static install guidance templates with Windows-first steps, verification commands, and safety notes.
- Expose environment doctor status in the desktop settings diagnostics page with refresh support.
- Keep planned runners honest: detected toolchains do not make planned TypeScript, SQL, Java, Go, C#, Rust, or C++ runners executable.
- Keep all checks read-only. The doctor may run version/status checks, but must not install packages, mutate PATH, start Docker, alter WSL, or change system settings.
- Keep failures non-blocking: missing commands or version-check failures should produce structured `missing` / `error` statuses, not crash the API.

## Acceptance Criteria

- [ ] `GET /api/environment/doctor` returns a stable JSON contract with summary, components, language runner matrix, and guidance templates.
- [ ] Backend tests cover ready, missing, error, planned-runner, and no-mutation behavior using fake command runners.
- [ ] The route is wired into FastAPI and returns `200` even when optional local tools are missing.
- [ ] Settings diagnostics shows environment doctor summary, detected components, runner matrix, and matching static guidance.
- [ ] The UI clearly separates executable current support from planned runner support.
- [ ] The doctor does not run install commands or modify global/system configuration.
- [ ] Existing focused backend and desktop checks continue to pass.

## Out of Scope

- Automatic runtime installation.
- Editing global PATH, Docker Desktop, WSL, registry, firewall, or OS settings.
- Adding new executable runner adapters.
- Enabling TypeScript, SQL, Java, Go, C#, Rust, or C++ execution.
- Live web search for install instructions.
- Production/cloud environment diagnostics.

## Open Questions

- None blocking. The user has approved continuing the ordered child tasks.
