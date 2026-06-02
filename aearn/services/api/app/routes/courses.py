from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.services.curriculum.catalog import list_courses


router = APIRouter(prefix="/api/language-courses", tags=["language-courses"])


@router.get("", response_model=None)
def read_language_courses(
    request: Request,
    language: str | None = None,
    level: str | None = None,
    limit: int = 20,
) -> dict[str, object] | JSONResponse:
    if limit < 1 or limit > 100:
        return error_response(
            request,
            code="VALIDATION_ERROR",
            message="limit 必须在 1 到 100 之间",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"limit": limit},
        )
    with connect() as conn:
        items = list_courses(conn, language=language, level=level)
    return {
        "items": items[:limit],
        "page_info": {
            "limit": limit,
            "next_cursor": None,
            "has_more": len(items) > limit,
        },
    }
