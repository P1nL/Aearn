# Teaching Chunks Indexing Runtime

## Goal

Trigger `teaching_chunks` indexing from real lesson/exercise content creation so `search_teaching_materials` can return useful scoped results in production flows.

## Requirements

- Index teaching chunks when lesson outline, exercises, or knowledge point material are created or updated.
- Keep search scoped to the current `knowledge_point_id`.
- Make indexing idempotent and safe to rerun.
- Do not add async Celery requirements in this slice unless the current code already supports it cleanly.
- Preserve plan/session creation response contracts.

## Acceptance Criteria

- [x] Confirmed plan creation or exercise material creation indexes teaching chunks.
- [x] Search tool returns indexed content for the same knowledge point.
- [x] Search cannot return chunks from another knowledge point.
- [x] Re-indexing does not duplicate stale chunk rows.
- [x] Focused tests, lint, mypy, and task validation pass.
