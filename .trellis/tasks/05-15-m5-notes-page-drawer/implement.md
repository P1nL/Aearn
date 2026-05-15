# M5 笔记页与笔记抽屉 Implementation Plan

## Implementation Checklist

- [x] Add backend tests for note lookup, note creation, note update, shared knowledge-point reuse, and agent-draft persistence.
- [x] Add `notes` schema support and any repository helpers required by the new tests.
- [x] Add note request/response models, repository/service code, and `/api/notes*` routes.
- [x] Refactor desktop types and API client for notes.
- [x] Refactor `App.tsx` note drawer state to load, create, autosave, retry, and assist notes through the backend.
- [x] Replace `NotesPage.tsx` local storage/editor logic with API-backed list/select/edit behavior.
- [x] Run focused backend tests, desktop checks, Trellis validation, and a final diff sanity check.

## Validation Snapshot

- `uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py tests/test_notes_m5.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_worker_import.py`
- `pnpm --dir .\aearn desktop:check`
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-15-m5-notes-page-drawer`
- `git diff --check`

## Validation Notes

- API test batches use the shared bootstrap database and should be run sequentially to avoid schema reset conflicts.
- If the desktop build surfaces legacy accessibility or lint issues outside M5 scope, fix only the ones introduced or directly exposed by the new notes implementation.

## Review Gates

- Planning gate: `prd.md`, `design.md`, and `implement.md` exist before `task.py start`.
- Data gate: no duplicate visible note records for the same user + knowledge point.
- Boundary gate: no `CodeDraftPage`, `publishDrawer`, or independent draft entities are introduced.
- UX gate: save failures keep local note edits visible and retryable.
