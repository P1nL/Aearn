from __future__ import annotations

import json
from typing import Any

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def wants_stream(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return any(part.split(";", 1)[0].strip().lower() == "text/event-stream" for part in accept.split(","))


def stream_response(events: Any) -> StreamingResponse:
    return StreamingResponse(
        events,
        status_code=status.HTTP_200_OK,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


class SSEWriter:
    def __init__(self) -> None:
        self._next_id = 1

    def event(self, event_type: str, data: dict[str, Any]) -> str:
        event_id = f"evt_{self._next_id:06d}"
        self._next_id += 1
        return sse_event(event_type, data, event_id=event_id)

    def done(self, *, request_id: str, session_id: str, result_ref: dict[str, Any]) -> str:
        return self.event(
            "done",
            {
                "request_id": request_id,
                "session_id": session_id,
                "result_ref": result_ref,
            },
        )

    def error(
        self,
        *,
        code: str,
        message: str,
        request_id: str,
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
        next_action: str | None = None,
    ) -> str:
        error_payload: dict[str, Any] = {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
            "recoverable": recoverable,
        }
        if next_action is not None:
            error_payload["next_action"] = next_action
        return self.event("error", {"error": error_payload})


def sse_event(event_type: str, data: dict[str, Any], *, event_id: str | None = None) -> str:
    payload = json.dumps(jsonable_encoder(data), ensure_ascii=False, separators=(",", ":"))
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"
