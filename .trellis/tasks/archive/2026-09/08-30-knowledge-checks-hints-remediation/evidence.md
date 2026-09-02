# Child07 implementation and check evidence

Date: 2026-09-02

## Delivered contracts

- Strict `knowledge_check_v1` presentation and closed response actions for
  single/multi select, prediction, ordering, code range, and short text.
- Immutable server-owned response/result projection with D1-D5 base difficulty.
- Exactly-once H1-H3 and direct-answer assistance receipts.
- Published, unused, semantic-distinct, capability-scoped remediation/transfer
  selection with one exact receipt-backed evaluation continuation candidate.
- Portal/fixed Hint overlay with manual paging, inert off-screen pages, Escape,
  focus return, narrow bottom-sheet layout, and reduced-motion behavior.
- Safe cutover/export/reset/delete classification and repeat-bootstrap support.

## Review fixes

- Split the shared receipt trigger before reading response-only fields.
- Prevented incorrect or assisted responses from claiming independent mastery.
- Required exact remediation/transfer successors before terminal receipt commit.
- Filtered required successor handles before the candidate query limit and
  excluded reserved purposes from ordinary teaching context.
- Applied active-plan capability scope before selecting a successor.
- Preserved one required successor through the 1,200-character context bound;
  optional recent teaching units are omitted for knowledge-check evaluation.
- Fixed newly unlocked Hint page selection and restored dialog/trigger focus
  across server projection rerenders.

## Verification

- Focused serial PostgreSQL/API matrix:
  `pytest test_knowledge_checks.py test_tutor_teaching_artifact_commit.py
  test_tutor_teaching_candidates.py test_tutor_learning_artifact_routes.py
  test_tutor_branch_continuation.py test_harness_cutover.py test_db_bootstrap.py
  test_schema_manifest.py -q` -> **65 passed in 42.28s**.
- Complete API with `LLM_TYPE=disabled` and `-m "not real_provider"` ->
  **845 passed, 2 deselected in 277.21s**.
- API Ruff -> **All checks passed**.
- API Mypy -> **243 source files, no issues**.
- API compileall and dependency lock check -> **pass**.
- Desktop final full Vitest -> **19 files / 137 tests passed**.
- Desktop `tsc && vite build` -> **pass, 134 modules transformed**.
- Trellis task validation -> **pass**.
- `git diff --check` -> **pass**; configured line-ending warnings only.
- Existing dedicated bootstrap regression persists a
  `tutor_conversation_event_v3` row, applies the schema again, and verifies the
  v1/v2/v3 projection constraint/default.

## Browser evidence

A temporary Vite harness outside the committed product surface mounted the real
`KnowledgeCheckArtifact` and project CSS in Chromium. It was deleted after use.

- 1440x900, 900x900, 390x844, and 390x844 reduced-motion.
- `document` and `body` horizontal overflow delta: **0** at every viewport.
- Hint layer parent: **BODY**; opening the overlay changed main height by **0**.
- Explicit actions: exactly H1, H2, H3 once each; no paging action receipt.
- ArrowLeft/Home/End selected H2/H1/H3.
- Non-current pages were `aria-hidden` and `inert`.
- Escape restored the exact `提示` button focus.
- Console warnings/errors: **0**.
- Temporary port 1421 and harness files were verified absent afterward.

## Non-claims

- No real provider smoke was run.
- No real executor/container or Docker conformance was run.
- No production image build/sign/publish, Tauri installer, push, deploy, or
  production data migration was run.
- The local Chromium fake-action harness proves component behavior and layout,
  not production teaching quality or a signed Desktop release.
