# M5 笔记页与笔记抽屉 Design

## Technical Design

### Boundaries

- Backend remains the only source of truth for persisted note identity, content, `agent_draft_content`, and save timestamps.
- Frontend may stage temporary unsaved edits, but all durable note state must come from the notes APIs.
- There is one shared note surface per `knowledge_point_id` regardless of whether the user opens it from learning, review, or the dedicated notes page.
- M5 does not introduce a separate note-draft entity, `publishDrawer`, or code-review draft workflow.

### Backend Data Flow

1. `GET /api/notes` resolves either a specific note for `(user_id, knowledge_point_id)` or a notes-page list for the same user, joined with knowledge-point and plan metadata needed for navigation labels.
2. `POST /api/notes` creates the initial note record for a knowledge point. If the user already has an active note for that knowledge point, the repository returns that record instead of creating a second visible note.
3. `PATCH /api/notes/{note_id}` updates title, markdown content, and `is_user_edited`, then returns the saved note snapshot.
4. `POST /api/notes/{note_id}/agent-draft` assembles minimal note/session context, generates a structured assist response, writes only `agent_draft_content`, and returns the updated note.

### Schema / Repository

- Add `notes` to `app/db/schema.sql` with:
  - `id`, `user_id`, `knowledge_point_id`, `title`, `content_markdown`, `agent_draft_content`, `is_user_edited`, `created_at`, `updated_at`, `deleted_at`
  - indexes on `(user_id, updated_at DESC)` and `(knowledge_point_id)` where `deleted_at IS NULL`
  - an `updated_at` trigger via the shared `set_updated_at()`
- Repository/service responsibilities:
  - fetch single note by knowledge point
  - fetch notes-page list grouped by language / plan / knowledge point labels
  - create-or-return existing note for a knowledge point
  - patch note content
  - update only `agent_draft_content`

### Agent Assist

- M5 can use a deterministic assist implementation first, as long as the endpoint shape and persistence behavior match the docs.
- Assist output is stored in `agent_draft_content` and surfaced in drawer/page context panels.
- The assist flow may use current session title, latest review or learning feedback, and current note text as prompt inputs, but the persisted user note body is changed only by explicit note save.

### Frontend

- Extend `src/types.ts` and `src/api.ts` with note DTOs and request helpers.
- Introduce note state in `App.tsx` that tracks:
  - current note context (`knowledgePointId`, source page/session, optional session metadata)
  - loaded or newly created note record
  - autosave status and retry state
  - local unsaved draft text
- Wire both learning and review flows to provide the active note context into the global drawer.
- Replace the local-only `NotesPage.tsx` with a browser/editor that loads note lists, selects a note, edits markdown, and can request note-assist suggestions.

### Compatibility / Rollback

- Existing onboarding, learning, and review APIs must remain compatible.
- If notes APIs regress, rollback can remove the notes router from `app/main.py` and revert the new `App.tsx` note state wiring while leaving M3/M4 behavior intact.
- Schema changes are additive; rollback requires exporting note content before dropping the table in a real data environment.
