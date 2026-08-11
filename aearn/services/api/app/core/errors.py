from fastapi import Request
from fastapi.responses import JSONResponse


MODEL_UNAVAILABLE_MESSAGE = "模型服务暂时不可用，请检查模型配置或稍后重试。"


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
    next_action: str | None = None,
) -> JSONResponse:
    request_id = request_id_from(request)
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "details": details or {},
        "request_id": request_id,
        "recoverable": recoverable,
    }
    if next_action is not None:
        error["next_action"] = next_action
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers={"X-Request-Id": request_id},
    )


def model_unavailable_response(
    request: Request,
    *,
    details: dict[str, object] | None = None,
    next_action: str | None = None,
) -> JSONResponse:
    return error_response(
        request,
        code="MODEL_UNAVAILABLE",
        message=MODEL_UNAVAILABLE_MESSAGE,
        status_code=503,
        details=details,
        recoverable=True,
        next_action=next_action,
    )
