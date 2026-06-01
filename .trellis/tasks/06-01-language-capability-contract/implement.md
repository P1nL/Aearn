# Language Capability Contract Implementation Plan

## Ordered Checklist

- [ ] Read project specs before implementation: `.trellis/spec/backend/index.md`, `.trellis/spec/backend/quality-guidelines.md`, `.trellis/spec/frontend/type-safety.md`, and `.trellis/spec/frontend/quality-guidelines.md`.
- [ ] Add a backend capability model or registry module near the existing learning/runtime service boundary.
- [ ] Encode the current-state matrix for Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS.
- [ ] Map current public course languages to capabilities:
  - `python` -> Python executable stdout/test capability.
  - `javascript` -> JavaScript browser preview capability.
  - `html_css` -> combined HTML and CSS browser preview capability.
  - `java` -> Java static/compiled-later placeholder.
  - `cpp` -> C++ static/compiled-later placeholder.
- [ ] Add helper functions for normalized language lookup, public-course mapping, executable-runner support, grounding support, and UX disclosure.
- [ ] Add focused tests for matrix completeness, current public language compatibility, unsupported/planned execution disclosure, and enum/database/catalog alignment expectations.
- [ ] Update docs only where needed to point future runner/RAG/graph tasks to the capability contract as the source of truth.
- [ ] Do not start runner registry implementation inside this task.

## Validation Commands

Run the narrow backend tests added for the contract first. Then run:

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
```

If this task only changes backend contracts and docs, `desktop:check` still matters if shared frontend type unions or API metadata examples change.

## Risky Files And Rollback Points

- `aearn/services/api/app/models/onboarding.py`: changing `Language` too early can break existing request validation.
- `aearn/services/api/app/db/schema.sql`: changing checks without seeds and tests can break bootstrap.
- `aearn/services/api/app/db/seeds.py`: changing public catalog data affects onboarding and route generation tests.
- `aearn/services/api/app/services/plan_generator.py`: changing course templates can alter user-visible route cards.
- `aearn/apps/desktop/src/types.ts`: frontend unions must stay aligned with API response values.

Prefer adding a contract module and tests before widening public enums. Widen public language support only when downstream catalog/runtime/UI behavior is ready in the later child tasks.

## Review Gate Before Start

Before `task.py start`, confirm that:

- The user accepts tiered capability disclosure instead of public all-language execution.
- Child tasks depend on this contract explicitly in their artifacts rather than relying on tree position.
- The current `06-01-runner-registry-tests` pointer is ignored until prerequisites are started or completed.
