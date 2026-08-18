"""Server-authoritative Tutor Runtime admission and Codex worker readiness."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from collections.abc import Callable
from typing import Final, Literal, cast

from psycopg import Connection

from app.core.config import DEEPSEEK_V4_FLASH_MODEL, Settings
from app.services.learning.contracts import LearningScopeKind

TutorRuntimeKindValue = Literal["harness_v1", "codex_sidecar_v1"]

_CODEX_RUNTIME_KIND: Final[TutorRuntimeKindValue] = "codex_sidecar_v1"
_HARNESS_RUNTIME_KIND: Final[TutorRuntimeKindValue] = "harness_v1"
_REQUIRED_PROVIDER: Final[str] = "aearn_deepseek"
_REQUIRED_PROTOCOL: Final[str] = "responses"
_SAFE_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")


class TutorCodexRuntimeUnavailable(ValueError):
    """Stable fail-closed admission error without provider diagnostics."""

    code = "TUTOR_CODEX_RUNTIME_UNAVAILABLE"

    def __init__(self, reason_code: str) -> None:
        if _SAFE_IDENTIFIER.fullmatch(reason_code) is None:
            reason_code = "runtime_readiness_invalid"
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class TutorCodexRuntimeReadiness:
    worker_id: str
    status: str
    generation: int
    runtime_version: str | None
    model: str | None
    model_provider: str | None
    protocol: str | None
    safe_error_code: str | None
    observed_at: datetime

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True, slots=True)
class TutorRuntimeSelection:
    runtime_kind: TutorRuntimeKindValue
    reason_code: str


class PostgresTutorCodexRuntimeReadinessRepository:
    """Persist only bounded worker health facts shared by API and Celery."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def record(
        self,
        *,
        worker_id: str,
        status: str,
        generation: int,
        runtime_version: str | None,
        model: str | None,
        model_provider: str | None,
        protocol: str | None,
        safe_error_code: str | None,
        observed_at: datetime,
    ) -> TutorCodexRuntimeReadiness:
        if _SAFE_IDENTIFIER.fullmatch(worker_id) is None:
            raise ValueError("Codex Runtime worker identity is invalid")
        if status not in {"stopped", "starting", "ready", "unavailable", "failed"}:
            raise ValueError("Codex Runtime readiness status is invalid")
        if generation < 0:
            raise ValueError("Codex Runtime readiness generation is invalid")
        for value, label, maximum in (
            (runtime_version, "version", 120),
            (model, "model", 120),
            (model_provider, "provider", 120),
            (protocol, "protocol", 40),
            (safe_error_code, "safe error code", 120),
        ):
            if value is not None and (not value or len(value) > maximum):
                raise ValueError(f"Codex Runtime readiness {label} is invalid")
        row = self._conn.execute(
            """
            INSERT INTO tutor_codex_runtime_health (
              worker_id, status, generation, runtime_version, model,
              model_provider, protocol, safe_error_code, observed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (worker_id) DO UPDATE SET
              status = EXCLUDED.status,
              generation = EXCLUDED.generation,
              runtime_version = EXCLUDED.runtime_version,
              model = EXCLUDED.model,
              model_provider = EXCLUDED.model_provider,
              protocol = EXCLUDED.protocol,
              safe_error_code = EXCLUDED.safe_error_code,
              observed_at = EXCLUDED.observed_at
            RETURNING *
            """,
            (
                worker_id,
                status,
                generation,
                runtime_version,
                model,
                model_provider,
                protocol,
                safe_error_code,
                observed_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Codex Runtime readiness write failed")
        return _readiness_from_row(row)

    def latest(self) -> TutorCodexRuntimeReadiness | None:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_codex_runtime_health
            ORDER BY observed_at DESC, updated_at DESC, worker_id
            LIMIT 1
            """
        ).fetchone()
        return _readiness_from_row(row) if row is not None else None

    def conversation_runtime_kind(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> TutorRuntimeKindValue | None:
        row = self._conn.execute(
            """
            SELECT runtime_kind
            FROM tutor_runs
            WHERE user_id = %s AND conversation_id = %s AND origin = 'interactive'
            ORDER BY created_at, id
            LIMIT 1
            """,
            (user_id, conversation_id),
        ).fetchone()
        if row is None:
            return None
        return _runtime_kind(row.get("runtime_kind"))


class TutorRuntimeSelectionPolicy:
    """Freeze one Runtime from server-owned scope, lineage, feature, and health."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._readiness = PostgresTutorCodexRuntimeReadinessRepository(conn)
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def select(
        self,
        *,
        scope_kind: LearningScopeKind,
        inherited_runtime_kind: TutorRuntimeKindValue | None = None,
        conversation_runtime_kind: TutorRuntimeKindValue | None = None,
    ) -> TutorRuntimeSelection:
        if inherited_runtime_kind is not None:
            return TutorRuntimeSelection(inherited_runtime_kind, "runtime_inherited")
        if conversation_runtime_kind is not None:
            return TutorRuntimeSelection(conversation_runtime_kind, "conversation_runtime_frozen")
        if scope_kind is not LearningScopeKind.PLAN_DRAFTING:
            return TutorRuntimeSelection(_HARNESS_RUNTIME_KIND, "scope_not_plan_drafting")
        if not self._settings.tutor_codex_plan_drafting_enabled:
            return TutorRuntimeSelection(_HARNESS_RUNTIME_KIND, "codex_admission_disabled")
        if not self._settings.codex_runtime_enabled:
            raise TutorCodexRuntimeUnavailable("runtime_disabled")
        readiness = self._readiness.latest()
        if readiness is None:
            raise TutorCodexRuntimeUnavailable("runtime_readiness_missing")
        now = self._now_provider()
        if readiness.observed_at < now - timedelta(
            seconds=self._settings.tutor_codex_runtime_health_max_age_seconds
        ):
            raise TutorCodexRuntimeUnavailable("runtime_readiness_stale")
        if not readiness.ready:
            raise TutorCodexRuntimeUnavailable(readiness.safe_error_code or "runtime_not_ready")
        if readiness.generation < 1:
            raise TutorCodexRuntimeUnavailable("runtime_generation_invalid")
        if readiness.runtime_version not in _allowed_versions(self._settings):
            raise TutorCodexRuntimeUnavailable("unsupported_codex_version")
        if readiness.model != DEEPSEEK_V4_FLASH_MODEL:
            raise TutorCodexRuntimeUnavailable("runtime_model_mismatch")
        if readiness.model_provider != _REQUIRED_PROVIDER:
            raise TutorCodexRuntimeUnavailable("runtime_provider_mismatch")
        if readiness.protocol != _REQUIRED_PROTOCOL:
            raise TutorCodexRuntimeUnavailable("runtime_protocol_mismatch")
        return TutorRuntimeSelection(_CODEX_RUNTIME_KIND, "codex_plan_drafting_admitted")

    def conversation_runtime_kind(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> TutorRuntimeKindValue | None:
        return self._readiness.conversation_runtime_kind(
            user_id=user_id,
            conversation_id=conversation_id,
        )


def _allowed_versions(settings: Settings) -> frozenset[str]:
    return frozenset(
        item.strip()
        for item in settings.codex_runtime_allowed_versions.split(",")
        if item.strip()
    )


def _runtime_kind(value: object) -> TutorRuntimeKindValue:
    normalized = str(value or _HARNESS_RUNTIME_KIND)
    if normalized not in {_HARNESS_RUNTIME_KIND, _CODEX_RUNTIME_KIND}:
        raise ValueError("stored Tutor Runtime kind is invalid")
    return cast(TutorRuntimeKindValue, normalized)


def _readiness_from_row(row: dict[str, object]) -> TutorCodexRuntimeReadiness:
    observed_at = row.get("observed_at")
    if not isinstance(observed_at, datetime):
        raise ValueError("stored Codex Runtime readiness timestamp is invalid")
    return TutorCodexRuntimeReadiness(
        worker_id=str(row["worker_id"]),
        status=str(row["status"]),
        generation=_as_int(row.get("generation")),
        runtime_version=str(row["runtime_version"]) if row.get("runtime_version") is not None else None,
        model=str(row["model"]) if row.get("model") is not None else None,
        model_provider=str(row["model_provider"]) if row.get("model_provider") is not None else None,
        protocol=str(row["protocol"]) if row.get("protocol") is not None else None,
        safe_error_code=str(row["safe_error_code"]) if row.get("safe_error_code") is not None else None,
        observed_at=observed_at,
    )


def _as_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
