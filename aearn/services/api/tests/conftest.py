from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest


from app.agents.harness.contracts import TutorPolicySnapshot, TutorRunSnapshot
from app.agents.harness.skill_catalog import SkillCatalogSnapshot, compile_published_skill_catalog
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.exercises import adaptive_exercise_service
from app.services.exercises.adaptive_exercise_service import GeneratedAdaptiveCandidate
from app.services.tutor.cutover import CUTOVER_VERSION
from app.services.tutor.persistence import PostgresTutorRepository

pytest_plugins = ("tests.support.tutor_public_api_support",)


@pytest.fixture(autouse=True)
def disable_external_tutor_dispatch_wakeup(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试只执行 API 的本地 fast path，禁止向真实 Celery broker 发送任务。"""

    from app.routes import teaching_sessions as teaching_session_routes
    from app.routes import tutor as tutor_routes
    from app.services.tutor import interactive_worker

    def _disabled_wakeup(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(interactive_worker, "enqueue_tutor_interactive_dispatch", _disabled_wakeup)
    monkeypatch.setattr(tutor_routes, "enqueue_tutor_interactive_dispatch", _disabled_wakeup)
    monkeypatch.setattr(teaching_session_routes, "enqueue_tutor_interactive_dispatch", _disabled_wakeup)


@pytest.fixture(autouse=True)
def disable_live_adaptive_model_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adaptive_exercise_service, "build_model_candidate", _fake_adaptive_model_candidate)


def _fake_adaptive_model_candidate(
    model_context: Mapping[str, object],
    template: object,
) -> GeneratedAdaptiveCandidate:
    fallback = getattr(template, "fallback_payload")
    assert isinstance(fallback, Mapping)
    required_skill_tags = model_context.get("required_skill_tags")
    target_skill_tags = list(required_skill_tags) if isinstance(required_skill_tags, list) else []
    return GeneratedAdaptiveCandidate(
        content={
            "candidate": {
                "title": f"{fallback['title']}：模型生成练习",
                "prompt_markdown": fallback["prompt_markdown"],
                "starter_code": fallback["starter_code"],
                "solution_reference": fallback["solution_reference"],
                "metadata_json": fallback["metadata_json"],
                "exercise_intent": "Align the exercise with the current route knowledge point.",
                "target_skill_tags": target_skill_tags,
                "alignment_claims": target_skill_tags,
            }
        },
        model="fake-adaptive-exercise-model",
    )


# Target-only Tutor persistence fixtures use real PostgreSQL when available and
# roll all test-owned rows back at fixture teardown.
@dataclass(frozen=True)
class TutorPersistenceFixture:
    connection: psycopg.Connection[dict[str, object]]
    repository: PostgresTutorRepository
    user_id: str
    conversation_id: str
    run: TutorRunSnapshot
    catalog: SkillCatalogSnapshot


def _tutor_database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def tutor_persistence() -> TutorPersistenceFixture:
    if not _tutor_database_available():
        pytest.skip("PostgreSQL is not available; run aearn infra compose for Tutor persistence tests.")
    bootstrap_database()
    with connect() as conn:
        suffix = uuid4().hex[:12]
        user = conn.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
            (f"Tutor Persistence {suffix}",),
        ).fetchone()
        assert user is not None
        user_id = str(user["id"])
        # Target-only persistence fixtures model a user that already completed
        # the one-way cutover before any Tutor rows are created.
        conn.execute(
            """
            INSERT INTO harness_cutovers (user_id, cutover_version, state, verified_at)
            VALUES (%s, %s, 'verified', now())
            """,
            (user_id, CUTOVER_VERSION),
        )
        catalog = compile_published_skill_catalog()
        repository = PostgresTutorRepository(conn)
        repository.record_catalog_snapshot(catalog)
        conversation_id = repository.create_conversation(user_id=user_id)
        run = repository.create_run(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog.digest,
            policy=TutorPolicySnapshot(
                deadline=datetime(2030, 1, 1, tzinfo=UTC),
                max_iterations=3,
                max_model_calls=3,
                max_capability_calls=2,
                max_effects=2,
                context_token_budget=64,
            ),
            origin="interactive",
        )
        try:
            yield TutorPersistenceFixture(
                connection=conn,
                repository=repository,
                user_id=user_id,
                conversation_id=conversation_id,
                run=run,
                catalog=catalog,
            )
        finally:
            conn.rollback()
