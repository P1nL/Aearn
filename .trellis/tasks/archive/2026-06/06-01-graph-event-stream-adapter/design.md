# Design

## Scope

This task adapts graph runtime progress into the existing SSE event contract used by the desktop learning page. It does not add frontend event types, new UI surfaces, or graph diagnostics to public payloads.

## Event Boundary

Existing frontend-supported SSE types are the allowed vocabulary:

- `agent_message`
- `tool_status`
- `tool_call`
- `runner_result`
- `evaluation_result`
- `done`
- `error`

Graph runtime progress maps only to `tool_status` in this task. Existing learning tool-call rendering still comes from stored `tool_calls` and the existing `_tool_call_events()` path.

## Adapter Shape

Add a small service adapter with:

- a typed `GraphStreamEvent`
- a builder that emits safe `tool_status` frames for graph-enabled learning contexts
- redaction/bounding helpers that reuse graph runtime redaction

The route layer remains responsible for `SSEWriter` event ids and final frame serialization.

## Data Flow

```text
learning message SSE request
  -> prepare_learning_message()
  -> prepare_learning_message_for_generation()
  -> if graph context exists: emit adapter tool_status frame(s)
  -> stream agent_message deltas
  -> persist final response
  -> emit stored tool_call frames
  -> emit done
```

## Compatibility

The adapter must be additive and safe:

- Non-streaming JSON requests are unchanged.
- Stored response replay uses the existing replay branch and does not synthesize graph status frames.
- `LANGGRAPH_ENABLED=false` contexts do not emit graph status frames.
- Raw graph node names and diagnostics remain internal.

## Rollback

Rollback is deleting the adapter module and removing the one SSE route hook. No database or frontend cleanup is required.
