from fastapi import APIRouter, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.onboarding import UserCreateRequest
from app.services.repositories.local_user_data_repository import (
    EntityNotFoundError as LocalUserDataNotFoundError,
    delete_user_data,
    export_user_data,
    get_user_data_summary,
    list_local_users,
    reset_user_data,
)
from app.services.repositories.user_repository import create_user, get_user, update_preferences


router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_local_user(payload: UserCreateRequest) -> dict[str, object]:
    with connect() as conn:
        user = create_user(conn, payload)
        conn.commit()
    return {"user": user}


@router.get("", response_model=None)
def list_users() -> JSONResponse:
    with connect() as conn:
        response = list_local_users(conn)
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.get("/{user_id}", response_model=None)
def read_user(user_id: str, request: Request) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        user = get_user(conn, user_id)
    if user is None:
        return error_response(
            request,
            code="USER_NOT_FOUND",
            message="用户不存在",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"user_id": user_id},
        )
    return {"user": user}


@router.get("/{user_id}/data-summary", response_model=None)
def read_user_data_summary(user_id: str, request: Request) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            summary = get_user_data_summary(conn, user_id)
        except LocalUserDataNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id},
            )
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder({"summary": summary}))


@router.get("/{user_id}/export", response_model=None)
def export_user(user_id: str, request: Request) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            payload = export_user_data(conn, user_id)
        except LocalUserDataNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id},
            )
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(payload))


@router.post("/{user_id}/reset-data", response_model=None)
async def reset_user_learning_data(user_id: str, request: Request) -> dict[str, object] | JSONResponse:
    body = await _json_body(request)
    if body.get("confirm") is not True:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="重置本地学习数据需要确认",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"field": "confirm"},
            recoverable=False,
        )
    with connect() as conn:
        try:
            response = reset_user_data(conn, user_id)
        except LocalUserDataNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id},
            )
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.delete("/{user_id}", response_model=None)
async def delete_user(user_id: str, request: Request) -> dict[str, object] | JSONResponse:
    body = await _json_body(request)
    if body.get("confirm") is not True:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="删除本地用户需要确认",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"field": "confirm"},
            recoverable=False,
        )
    with connect() as conn:
        try:
            response = delete_user_data(conn, user_id)
        except LocalUserDataNotFoundError as exc:
            conn.rollback()
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id},
            )
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.patch("/{user_id}/preferences", response_model=None)
async def patch_user_preferences(user_id: str, request: Request) -> dict[str, object] | JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="偏好设置请求必须是 JSON object",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"field": "body"},
        )

    with connect() as conn:
        user, forbidden, unknown = update_preferences(conn, user_id, payload)
        if forbidden or unknown:
            conn.rollback()
            return error_response(
                request,
                code="VALIDATION_ERROR",
                message="偏好设置包含不允许修改的字段",
                status_code=status.HTTP_400_BAD_REQUEST,
                details={
                    "forbidden_fields": sorted(forbidden),
                    "unknown_fields": sorted(unknown),
                },
                recoverable=False,
            )
        if user is None:
            conn.rollback()
            return error_response(
                request,
                code="USER_NOT_FOUND",
                message="用户不存在",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id},
            )
        conn.commit()
    return {"user": user}


async def _json_body(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
