from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.agents.graph_runtime_contracts import redact_value


MAX_GRAPH_STREAM_FIELD_LENGTH = 120
MAX_GRAPH_STREAM_MESSAGE_LENGTH = 160
GRAPH_STREAM_NODE = "learning_graph"
GRAPH_STREAM_TOOL = "graph_runtime"

GraphStreamEventType = Literal["tool_status"]
GraphStreamStatus = Literal["running", "completed", "failed"]


@dataclass(frozen=True)
class GraphStreamEvent:
    event_type: GraphStreamEventType
    payload: Mapping[str, object]


def build_learning_graph_stream_events(
    *,
    request_id: str,
    session_id: str,
    conversation_context: Mapping[str, object],
    graph_memory_snapshot: Mapping[str, object] | None = None,
    rag_context: Mapping[str, object] | None = None,
) -> tuple[GraphStreamEvent, ...]:
    runtime_context = _safe_mapping(conversation_context.get("langgraph_runtime"))
    if not _has_graph_context(
        runtime_context,
        graph_memory_snapshot=graph_memory_snapshot,
        rag_context=rag_context,
    ):
        return ()

    payload: dict[str, object] = {
        "request_id": _safe_text(request_id, max_length=MAX_GRAPH_STREAM_FIELD_LENGTH),
        "session_id": _safe_text(session_id, max_length=MAX_GRAPH_STREAM_FIELD_LENGTH),
        "node": GRAPH_STREAM_NODE,
        "tool": GRAPH_STREAM_TOOL,
        "status": "completed",
        "message": _graph_status_message(runtime_context),
    }
    return (GraphStreamEvent(event_type="tool_status", payload=payload),)


def _has_graph_context(
    runtime_context: Mapping[str, object],
    *,
    graph_memory_snapshot: Mapping[str, object] | None,
    rag_context: Mapping[str, object] | None,
) -> bool:
    return (
        bool(runtime_context)
        or bool(_safe_mapping(graph_memory_snapshot))
        or bool(_safe_mapping(rag_context))
    )


def _graph_status_message(runtime_context: Mapping[str, object]) -> str:
    if _safe_list(runtime_context.get("errors")):
        return "Learning graph context prepared with safe fallback."
    if _safe_text(runtime_context.get("next_action"), max_length=MAX_GRAPH_STREAM_FIELD_LENGTH):
        return "Learning graph selected the next teaching step."
    return "Learning graph context is ready."


def _safe_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_value(value)
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _safe_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    redacted = redact_value(value)
    return list(redacted) if isinstance(redacted, list) else []


def _safe_text(value: object, *, max_length: int) -> str:
    redacted = redact_value(value)
    text = redacted if isinstance(redacted, str) else str(redacted or "")
    text = text.strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."
