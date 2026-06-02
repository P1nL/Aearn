from __future__ import annotations

from fastapi import APIRouter

from app.services.environment_doctor import EnvironmentDoctorReport, build_environment_doctor_report


router = APIRouter(prefix="/api/environment", tags=["environment"])


@router.get("/doctor")
def environment_doctor() -> EnvironmentDoctorReport:
    return build_environment_doctor_report()
