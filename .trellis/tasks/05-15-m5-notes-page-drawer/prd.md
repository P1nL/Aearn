# M5 笔记页与笔记抽屉

## Goal

Implement Milestone 5 so users can create, view, and update knowledge-point notes from both the in-session note drawer and the dedicated notes page, while keeping Agent assistance constrained to structured note augmentation rather than full note generation.

## Background / Known Context

- The live implementation lives under `aearn/`; historical tutorial directories are not runtime sources.
- `docs/plans/learning-agent-implementation-plan.md` defines M5 as the `notes` table, note CRUD APIs, `POST /api/notes/{note_id}/agent-draft`, a session note drawer, a dedicated notes page, and UF-07 / UF-08 acceptance coverage.
- `docs/architecture/database-schema.md` defines a single `notes` record per user-authored note with `knowledge_point_id`, `content_markdown`, `agent_draft_content`, `is_user_edited`, `deleted_at`, and updated-at indexing.
- `docs/product/frontend-interaction-spec.md` requires learning and review sessions to reference the same knowledge-point note and requires the note drawer to show `未保存` / `保存中` / `已保存` / `保存失败`.
- Current implementation gaps are large: backend has no `notes` table or routes, `NotesPage.tsx` is local-only, and `App.tsx` treats note drawer state as local scratch text instead of API-backed note state.

## Requirements

- Add the `notes` schema with the documented fields, soft-delete shape, indexes, and `updated_at` trigger behavior.
- Implement `GET /api/notes`, `POST /api/notes`, and `PATCH /api/notes/{note_id}` following the existing API error envelope and note payload contract.
- Support reading notes by `user_id`, `knowledge_point_id`, and list-oriented views for the notes page without introducing a separate draft object or `publishDrawer`.
- Implement `POST /api/notes/{note_id}/agent-draft` so it writes only `agent_draft_content` for the target note.
- Keep Agent assistance scoped to structured completion suggestions that use current note/session context; it must not auto-generate a full standalone note or create a separate code-draft workflow.
- Refactor the global note drawer so learning and review sessions both resolve the current `knowledge_point_id`, load or create the shared note, autosave through the backend, and preserve local edits on save failure.
- Replace the local-only `NotesPage` with an API-backed notes browser/editor that groups or filters notes by language and knowledge point while editing the same underlying note records used by the drawer.
- Preserve the current MVP boundary: no independent retrospective drafts, no `CodeDraftPage`, no `publishDrawer`, and no settings that let the frontend redefine note-assist generation rules.

## Acceptance Criteria

- [ ] `GET /api/notes` returns an existing note for a knowledge point, supports empty-state results, and supports notes-page list retrieval without returning soft-deleted records.
- [ ] `POST /api/notes` creates a note for the requested `knowledge_point_id`; repeated create attempts for the same knowledge point are handled deterministically without creating conflicting user-visible duplicates.
- [ ] `PATCH /api/notes/{note_id}` updates title and/or markdown content, preserves content on backend failure, and correctly marks `is_user_edited`.
- [ ] `POST /api/notes/{note_id}/agent-draft` writes only `agent_draft_content` and does not create a separate draft entity or overwrite the user-authored note body.
- [ ] Desktop `NoteDrawer` works from both learning and review flows, shows autosave state transitions, and does not silently close when save fails.
- [ ] Desktop `NotesPage` reads and edits the same note records as the drawer, with language / knowledge-point navigation and an empty state when the user has no notes yet.
- [ ] Learning-session and review-session entry points resolve to the same note for the same `knowledge_point_id`.
- [ ] Focused backend tests cover UF-07 / UF-08 note CRUD and agent-draft behavior, and desktop typecheck/build passes for the changed UI.

## Notes

- This is a complex Trellis task. `design.md` and `implement.md` are required before `task.py start`.
