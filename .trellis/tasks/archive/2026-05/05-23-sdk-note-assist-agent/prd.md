# Add SDK note assist agent

## Goal

Move `POST /api/notes/{note_id}/agent-draft` generation to an Aearn-owned OpenAI Agents SDK Note Assist Agent while preserving Note CRUD ownership, SSE shape, deterministic fallback, and the MVP rule that the Agent only assists user notes instead of generating full notes or reviving CodeDraft flows.

## Requirements

- Add an SDK Note Assist module under `aearn/services/api/app/agents/`, likely `note_assist_agent.py`.
- Keep `note_repository.py` responsible for:
  - loading notes and verifying user ownership;
  - selecting bounded note/session/attempt context;
  - writing `Note.agent_draft_content`;
  - keeping `content_markdown` user-owned.
- Preserve existing API behavior:
  - `GET /api/notes`;
  - `POST /api/notes`;
  - `PATCH /api/notes/{note_id}`;
  - `POST /api/notes/{note_id}/agent-draft`;
  - JSON and SSE variants of agent draft generation.
- SDK output must be an insertable supplement or patch-style suggestion, not a complete replacement note.
- SDK context must be bounded and safe:
  - current knowledge point;
  - current note summary or bounded note excerpt;
  - latest visible attempt facts;
  - optional session summary;
  - no hidden tests, reference answers, full submissions, or provider raw errors.
- Preserve deterministic fallback when model config is absent, SDK fails, guardrails block, or output validation fails.
- Do not create or reintroduce `CodeDraft`, `publishDrawer`, independent retrospective drafts, or interview narration flows.

## Acceptance Criteria

- [ ] `app/agents/note_assist_agent.py` or equivalent exists and is used by note agent-draft generation.
- [ ] `Note.agent_draft_content` is still the only Agent-written note field.
- [ ] User-authored `Note.content_markdown` is never overwritten by the SDK Agent.
- [ ] The SSE stream still emits the current public event names and does not leak SDK event names or tool payloads.
- [ ] SDK output is rejected or falls back if it attempts a full-note rewrite, hidden-test leakage, provider-error leakage, or unsupported CodeDraft flow.
- [ ] Existing `tests/test_notes_m5.py` still passes.
- [ ] Focused fake SDK tests cover success, fallback, blocked leakage, and streaming storage behavior.

## Out Of Scope

- Full note editor redesign.
- CodeDraft or retrospective draft implementation.
- Automatic conversion of all Attempts into notes.
- Review Coach Agent behavior.
- Changing Note table schema unless a separately approved migration task requires it.

## Dependencies

- `05-23-sdk-teaching-tools-guardrails` should finish first so Note Assist can reuse safe tool and guardrail helpers.
- `05-23-sdk-exercise-coach-endpoints` can improve the Attempt/explanation context available to Note Assist, but Note Assist should still work with current deterministic Attempt facts.
