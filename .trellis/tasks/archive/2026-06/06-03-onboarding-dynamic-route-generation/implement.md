# Implement: Onboarding dynamic route generation

## Preconditions

- Task is reviewed and started with `python ./.trellis/scripts/task.py start .trellis/tasks/06-03-onboarding-dynamic-route-generation`.
- Before editing code, load `trellis-before-dev` and the relevant backend spec guides.

## Implementation Checklist

- [x] Add or extract a shared dynamic plan generation service used by both `POST /api/plans/generate` and onboarding.
- [x] Ensure the shared service treats missing config, missing `EXA_API_KEY`, disabled `PLAN_GENERATION_ENABLED`, missing docs mapping, and invalid model output as failures, not fallback triggers.
- [x] Wire `POST /api/onboarding/messages` route-card generation to the shared dynamic service.
- [x] Prevent `build_plan_draft_from_slots(...)` or its replacement path from using `COURSE_TEMPLATES` for public supported languages.
- [x] Add `sql` and `csharp` authoritative docs mappings.
- [x] Add a supported-language coverage assertion so missing docs mappings fail tests.
- [x] Tighten dynamic output validation to require user-need coverage and authoritative-source coverage without enforcing a fixed module count as the product quality bar.
- [x] Update `/api/plans/generate` fallback semantics to match no-fallback requirements.
- [x] Update `docs/architecture/api-contract.md` for onboarding and plans generation.
- [x] Keep C++ and Rust unsupported-language behavior unchanged.

## Test Checklist

- [x] Onboarding route generation uses dynamic modules and emits `show_learning_route`.
- [x] Onboarding dynamic failure returns error/no-route and does not stash a draft.
- [x] Supported-language docs mapping is complete.
- [x] Dynamic output that ignores user needs or lacks authoritative sources fails the quality gate.
- [x] `/api/plans/generate` does not fallback to templates when dynamic generation is unavailable or invalid.
- [x] Existing unsupported language tests still pass for C++ and Rust.

## Suggested Verification Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests\test_onboarding_m2.py tests\test_plan_generation_agent.py -q
uv --directory .\aearn\services\api run python -m pytest tests\test_plan_generator.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

If frontend contracts change, also run:

```powershell
pnpm --dir .\aearn desktop:check
```

## Risk Areas

- Existing tests may assume `build_sdk_plan_generation_response(...) is None` means deterministic fallback.
- Dynamic failures must not leak provider errors or secrets in SSE payloads.
- Removing fallback can make local tests depend on monkeypatched dynamic output; focused tests should use fakes rather than live model calls.
- The docs contract currently says `/api/plans/generate` may fallback to templates and must be updated in the same task.

## Review Gate

Do not start implementation until the user reviews this coverage-based quality gate and approves proceeding.
