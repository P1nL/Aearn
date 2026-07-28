from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.errors import error_response
from app.db.connection import connect
from app.services.repositories.dashboard_repository import EntityNotFoundError, get_dashboard
from app.services.tutor.cutover import require_legacy_runtime


router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(require_legacy_runtime)])


@router.get("/dashboard", response_model=None)
def read_dashboard(
    request: Request,
    user_id: str = Query(min_length=1),
) -> dict[str, object] | JSONResponse:
    with connect() as conn:
        try:
            response = get_dashboard(conn, user_id=user_id)
        except EntityNotFoundError as exc:
            return error_response(
                request,
                code=exc.code,
                message=exc.message,
                status_code=status.HTTP_404_NOT_FOUND,
                details={"user_id": user_id},
            )
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))
