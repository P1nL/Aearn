from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.core.errors import error_response
from app.routes.dashboard import router as dashboard_router
from app.routes.courses import router as courses_router
from app.routes.health import router as health_router
from app.routes.learning_sessions import router as learning_sessions_router
from app.routes.notes import router as notes_router
from app.routes.plans import router as plans_router
from app.routes.reviews import router as reviews_router
from app.routes.users import router as users_router


app = FastAPI(title="Aearn API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "tauri://localhost",
    ],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(users_router)
app.include_router(courses_router)
app.include_router(dashboard_router)
app.include_router(plans_router)
app.include_router(learning_sessions_router)
app.include_router(reviews_router)
app.include_router(notes_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_response(
        request,
        code="VALIDATION_ERROR",
        message="请求字段不合法",
        status_code=status.HTTP_400_BAD_REQUEST,
        details={"errors": exc.errors()},
        recoverable=True,
    )
