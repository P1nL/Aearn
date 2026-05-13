from fastapi import Request
from fastapi.responses import JSONResponse


def request_id_from(request: Request) -> str:
    return request.headers.get("X-Request-Id", "req_unset")


def error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, object] | None = None,
    recoverable: bool = True,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id_from(request),
                "recoverable": recoverable,
            },
        },
    )
