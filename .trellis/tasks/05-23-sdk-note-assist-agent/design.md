# Technical Design

## Selected Slice

Only the note agent-draft path moves to the SDK. CRUD, ownership checks, autosave semantics, and final database writes remain in `note_repository.py` and `routes/notes.py`.

## Target Module Shape

```text
aearn/services/api/app/agents/
  sdk_runtime.py
  tools.py
  guardrails.py
  note_assist_agent.py
```

`note_assist_agent.py` should expose a Note Assist client that accepts a safe `NoteAssistContext` and returns a stream or full text compatible with the existing route/repository behavior.

## Data Flow

1. `routes/notes.py` parses JSON or SSE request and keeps current public framing.
2. `note_repository.py` loads note ownership and builds a safe context.
3. SDK Note Assist generates a bounded draft supplement.
4. Guardrails validate that the output is a supplement, not a full replacement or CodeDraft.
5. Repository code writes `agent_draft_content`.

## Context Boundary

Allowed context:

- note id, title, knowledge point title, module title, language;
- bounded current note excerpt or summary;
- style and focus request;
- latest attempt runtime status, pass rate, error cause, and bounded explanation;
- session id as trace context only.

Disallowed context:

- full hidden tests;
- full submitted code;
- reference solutions;
- full note history when a summary is enough;
- raw provider or SDK events.

## Streaming Compatibility

The SDK layer should expose text deltas that the existing SSE route can map to `agent_message`. The route should not forward SDK event types, tool call names, or raw run items.

If SDK fails before a useful delta, deterministic draft chunks should be used. If failure happens after partial useful output, preserve the route's existing recoverable error behavior and avoid writing a misleading complete draft.

## State Ownership

SDK code must not update `notes` directly. It returns text only. `update_agent_draft_content(...)` remains the write boundary.
