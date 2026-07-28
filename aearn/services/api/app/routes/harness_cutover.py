from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import error_response
from app.db.connection import connect
from app.models.tutor import HarnessCutoverConfirmRequest
from app.services.tutor.cutover import CutoverError, HarnessCutoverService


router = APIRouter(prefix="/api/harness", tags=["harness-cutover"])


@router.get("/cutover", response_model=None)
def read_harness_cutover(request: Request, user_id: str = Query(min_length=1)) -> JSONResponse:
    with connect() as conn:
        try:
            response = HarnessCutoverService(conn).get_decision(
                user_id=user_id,
                rollout_enabled=get_settings().tutor_harness_enabled,
            )
        except CutoverError as exc:
            conn.rollback()
            return _cutover_error(request, exc)
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


@router.post("/cutover/confirm", response_model=None)
def confirm_harness_cutover(payload: HarnessCutoverConfirmRequest, request: Request) -> JSONResponse:
    with connect() as conn:
        try:
            response = HarnessCutoverService(conn).confirm(
                user_id=payload.user_id,
                cutover_version=payload.cutover_version,
                summary_version=payload.summary_version,
                preview_nonce=payload.preview_nonce,
                summary_hash=payload.summary_hash,
                client_action_id=payload.client_action_id,
                confirm=payload.confirm,
                rollout_enabled=get_settings().tutor_harness_enabled,
            )
        except CutoverError as exc:
            conn.rollback()
            return _cutover_error(request, exc)
        conn.commit()
    return JSONResponse(status_code=status.HTTP_200_OK, content=jsonable_encoder(response))


def _cutover_error(request: Request, error: CutoverError) -> JSONResponse:
    return error_response(
        request,
        code=error.code,
        message=error.message,
        status_code=error.status_code,
        details=error.details,
        recoverable=error.recoverable,
    )
