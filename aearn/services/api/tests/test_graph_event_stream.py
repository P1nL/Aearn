import json

from app.services.graph_event_stream import (
    GRAPH_STREAM_NODE,
    GRAPH_STREAM_TOOL,
    MAX_GRAPH_STREAM_FIELD_LENGTH,
    build_learning_graph_stream_events,
)


def test_learning_graph_stream_event_uses_existing_tool_status_payload() -> None:
    events = build_learning_graph_stream_events(
        request_id="req_001",
        session_id="session_001",
        conversation_context={
            "langgraph_runtime": {
                "current_node": "internal_graph_node",
                "next_action": "graph_checked",
            },
        },
    )

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "tool_status"
    assert event.payload == {
        "request_id": "req_001",
        "session_id": "session_001",
        "node": GRAPH_STREAM_NODE,
        "tool": GRAPH_STREAM_TOOL,
        "status": "completed",
        "message": "Learning graph selected the next teaching step.",
        "observability": {
            "memory_available": False,
            "rag_retrieval_status": "empty",
            "rag_chunk_count": 0,
            "fallback_used": False,
            "next_action": "graph_checked",
        },
    }
    assert "internal_graph_node" not in json.dumps(event.payload)


def test_learning_graph_stream_event_redacts_and_bounds_public_fields() -> None:
    secret_text = "provider payload sk-secret " + ("x" * 240)
    events = build_learning_graph_stream_events(
        request_id=secret_text,
        session_id="session_" + ("s" * 240),
        conversation_context={
            "langgraph_runtime": {
                "next_action": secret_text,
                "errors": [secret_text],
                "stack_trace": secret_text,
            },
        },
    )

    assert len(events) == 1
    payload = events[0].payload
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-secret" not in serialized
    assert "provider payload" not in serialized
    assert "stack_trace" not in serialized
    assert len(str(payload["request_id"])) <= MAX_GRAPH_STREAM_FIELD_LENGTH
    assert len(str(payload["session_id"])) <= MAX_GRAPH_STREAM_FIELD_LENGTH
    assert payload["message"] == "Learning graph context prepared with safe fallback."
    assert payload["observability"]["fallback_used"] is True
    assert payload["observability"]["next_action"] == ""


def test_learning_graph_stream_event_skips_non_graph_context() -> None:
    assert (
        build_learning_graph_stream_events(
            request_id="req_001",
            session_id="session_001",
            conversation_context={},
        )
        == ()
    )


def test_learning_graph_stream_event_accepts_graph_prepared_context_without_runtime() -> None:
    events = build_learning_graph_stream_events(
        request_id="req_001",
        session_id="session_001",
        conversation_context={},
        graph_memory_snapshot={"available": True, "profile_summary": "prefers examples"},
        rag_context={"retrieval_status": "available", "chunks": [{"chunk_id": "c1"}, {"chunk_id": "c2"}]},
    )

    assert len(events) == 1
    assert events[0].payload["message"] == "Learning graph context is ready."
    assert events[0].payload["observability"] == {
        "memory_available": True,
        "rag_retrieval_status": "available",
        "rag_chunk_count": 2,
        "fallback_used": False,
        "next_action": "",
    }
