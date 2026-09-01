# Child 05 implementation evidence

Date: 2026-09-01

## Implemented boundary

- New executor writes use strict `safe-execution-result-v2`; historical v1 rows use an explicit adapter.
- Public result presentation is the closed `none | table_result_v1` union with hard row/column/cell/byte bounds and learner-safe redaction.
- Exact Gate/Review Attempt observation waits for terminal owner authority before projecting one source update, one immutable result Artifact, and one result-evaluation continuation/Turn; the result Artifact remains off-timeline until the terminal Turn atomically publishes its Tutor evaluation message first and the exact result Artifact second.
- Passed Run completes the source Artifact without Submit. Non-passed results keep it active and return to edit.
- Result-evaluation provider context contains only an exact result Artifact handle and a bounded safe summary. `MODEL_UNAVAILABLE` preserves the result and publishes a deterministic safe evaluation message; ordinary Tutor Turns retain their existing behavior.
- Desktop exact-parses Attempt v1/v2, renders concise failure-first details, omits diagnostic/hidden identities, bounds output/table presentation, avoids duplicate result summary, and returns focus to the exact source Artifact version.

## Automated gates

| Gate | Result |
| --- | --- |
| Shared execution result tests | 34 passed |
| Executor full tests | 13 passed |
| Executor Ruff | passed |
| Executor Mypy | passed, 9 source files |
| Focused serial API matrix (projector/routes/continuation/context/run-loop/Gate/Review) | 60 passed |
| Full API suite excluding explicit real-provider marker | 827 passed, 2 deselected |
| API changed-file Ruff | passed |
| API changed-file Mypy (`--no-incremental --follow-imports=skip`) | passed, 13 source files |
| API changed-file compileall | passed |
| Desktop full Vitest | 13 files / 110 tests passed |
| `pnpm --dir .\aearn desktop:check` | passed, Vite transformed 109 modules |
| `git diff --check` | passed; only configured LF-to-CRLF informational warnings |
| PostgreSQL bootstrap after persisted Artifact conversation event v3 | passed |

The full API run used local PostgreSQL 16 and did not call a real provider or executor.

## Real browser fixture

Target: `http://127.0.0.1:1420/artifact-result-smoke.html`, served by Vite from this checkout. The fixture was temporary, used only learner-safe static DTOs/fake fetch responses, and was removed after verification.

| Viewport | Page overflow | Result/detail | Table | Return to source | Reduced motion |
| --- | --- | --- | --- | --- | --- |
| 1440x900 | document/body/workspace `1440 == 1440` | one source, one result, failure-first, stdout/stderr visible, no hidden ID/diagnostic/Submit, summary once | `1362 / 1362` client/scroll | one Artifact scroll; source toggle focused | smooth |
| 900x900 | document/body/workspace `900 == 900` | same | `822 / 822` | same | smooth |
| 390x844 | document/body/workspace `390 == 390`; Artifact width 348 | same | internal horizontal scroll `318 / 532` | same; 44px return button | smooth |
| 390x844 reduced | same | same | internal horizontal scroll `318 / 532` | same | auto |

All viewports had exactly one Tutor surface, one Composer, one source Artifact, and one result Artifact. The DOM contained no protected marker or executable script node; there was no framework overlay or alert; relevant browser console warning/error count was zero.

## Non-claims

- No real provider smoke.
- No real executor/container execution or Docker conformance.
- No production image build/sign/publish, push, deploy, or production data migration.
- Browser evidence validates the public Desktop contract only; PostgreSQL tests validate durable authority.
