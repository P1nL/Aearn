import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.core.errors import error_response, request_id_from
from app.routes.courses import router as courses_router
from app.routes.environment import router as environment_router
from app.routes.exercise_gates import router as exercise_gates_router
from app.routes.health import router as health_router
from app.routes.harness_cutover import router as harness_cutover_router
from app.routes.learning_plan_sessions import router as learning_plan_sessions_router
from app.routes.lesson_documents import router as lesson_documents_router
from app.routes.learning_tracks import router as learning_tracks_router
from app.routes.learning_track_reviews import router as reviews_router
from app.routes.tutor import router as tutor_router
from app.routes.users import router as users_router


logger = logging.getLogger(__name__)


app = FastAPI(title="Aearn API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "tauri://localhost",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(users_router)
app.include_router(courses_router)
app.include_router(environment_router)
app.include_router(harness_cutover_router)
app.include_router(learning_tracks_router)
app.include_router(lesson_documents_router)
app.include_router(exercise_gates_router)
app.include_router(reviews_router)
app.include_router(learning_plan_sessions_router)
app.include_router(tutor_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_response(
        request,
        code="VALIDATION_ERROR",
        message="请求字段不合法",
        status_code=status.HTTP_400_BAD_REQUEST,
        details={"errors": jsonable_encoder(exc.errors(), custom_encoder={Exception: str})},
        recoverable=True,
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled API exception request_id=%s method=%s path=%s category=%s",
        request_id_from(request),
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return error_response(
        request,
        code="INTERNAL_ERROR",
        message="服务暂时不可用，请稍后重试。",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        recoverable=True,
    )
