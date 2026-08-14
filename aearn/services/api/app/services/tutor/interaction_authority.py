"""Internal-only authority receipt service for typed Tutor requests."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from psycopg import Connection

from app.agents.harness.context_budget import build_tutor_context_budget_policy
from app.agents.harness.contracts import TutorPolicySnapshot
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings, get_settings
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.tutor.persistence import (
    PostgresTutorRepository,
    TutorInteractionResponseAcceptance,
)


class TutorInteractionAuthorityService:
    """Resolve authority-owned requests without exposing a learner route."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._repository = PostgresTutorRepository(conn)
        self._learning_tracks = PostgresLearningTrackRepository(conn)

    def accept_receipt(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_request_version: int,
        issuer: str,
        subject: str,
        scope: Mapping[str, object],
        request_hash: str,
        result_hash: str,
        verification_result: str,
        receipt_identity: str,
        received_at: datetime | None = None,
    ) -> TutorInteractionResponseAcceptance:
        now = received_at or datetime.now(UTC)
        catalog = compile_published_skill_catalog()
        self._repository.record_catalog_snapshot(catalog)
        accepted = self._repository.accept_authority_receipt(
            user_id=user_id,
            conversation_id=conversation_id,
            item_id=item_id,
            expected_version=expected_request_version,
            issuer=issuer,
            subject=subject,
            scope=scope,
            request_hash=request_hash,
            result_hash=result_hash,
            verification_result=verification_result,
            receipt_identity=receipt_identity,
            catalog_digest=catalog.digest,
            policy=_authority_policy(now, settings=self._settings),
            received_at=now,
        )
        if accepted.turn is not None:
            self._learning_tracks.inherit_run_scope(
                user_id=user_id,
                run_id=accepted.turn.run.run_id,
                source_run_id=accepted.request.source_turn_id,
            )
        return accepted


def _authority_policy(now: datetime, *, settings: Settings) -> TutorPolicySnapshot:
    return TutorPolicySnapshot(
        deadline=now + timedelta(minutes=5),
        max_iterations=4,
        max_model_calls=3,
        max_capability_calls=2,
        max_effects=2,
        context_token_budget=settings.tutor_context_token_budget,
        lease_duration_seconds=30,
        context_budget_policy=build_tutor_context_budget_policy(settings),
    )
