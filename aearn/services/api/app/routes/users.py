from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.models.onboarding import UserCreateRequest
from app.services.user_repository import create_user, get_user, update_preferences


router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_local_user(payload: UserCreateRequest) -> dict[str, object]:
    with connect() as conn:
        user = create_user(conn, payload)
        conn.commit()
    return {"user": user}


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
