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


def model_unavailable_response(
    request: Request,
    *,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    return error_response(
        request,
        code="MODEL_UNAVAILABLE",
        message=MODEL_UNAVAILABLE_MESSAGE,
        status_code=503,
        details=details,
        recoverable=True,
    )
