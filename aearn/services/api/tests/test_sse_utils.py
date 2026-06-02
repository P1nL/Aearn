import json

from app.services.streaming.sse import SSEWriter, sse_event


def test_sse_event_uses_single_line_json_data() -> None:
    frame = sse_event("agent_message", {"content": "第一行\n第二行"}, event_id="evt_001")

    assert frame.startswith("id: evt_001\nevent: agent_message\n")
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload == {"content": "第一行\n第二行"}


def test_sse_writer_increments_event_ids() -> None:
    writer = SSEWriter()

    first = writer.event("tool_status", {"status": "running"})
    second = writer.done(request_id="req_001", session_id="sess_001", result_ref={"type": "Attempt", "id": "att_001"})

    assert first.startswith("id: evt_000001\n")
    assert second.startswith("id: evt_000002\n")
