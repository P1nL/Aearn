import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

from aearn_worker.review_seed_bank_core import (
    GENERATOR_VERSION,
)


ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

celery_app = Celery(
    "aearn-worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1"),
)
celery_app.conf.update(timezone="Asia/Shanghai", enable_utc=True)


@celery_app.task(name="health.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="review.refresh_due_counts")
def refresh_due_counts() -> dict[str, object]:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable",
    )
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT review_states.user_id::text AS user_id, count(*)::int AS due_count
            FROM review_states
            JOIN learning_plans ON learning_plans.id = review_states.plan_id
            JOIN knowledge_points ON knowledge_points.id = review_states.knowledge_point_id
            WHERE review_states.due_at IS NOT NULL
              AND review_states.due_at <= now()
              AND review_states.suspended_at IS NULL
              AND learning_plans.status = 'active'
              AND learning_plans.deleted_at IS NULL
              AND knowledge_points.deleted_at IS NULL
              AND knowledge_points.status IN ('reviewing', 'mastered')
            GROUP BY review_states.user_id
            ORDER BY review_states.user_id
            """
        ).fetchall()
    counts_by_user = {str(row["user_id"]): int(row["due_count"]) for row in rows}
    return {
        "total_due": sum(counts_by_user.values()),
        "counts_by_user": counts_by_user,
    }


@celery_app.task(name="review.generate_seed_bank")
def generate_seed_bank(user_id: str, knowledge_point_id: str) -> dict[str, object]:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable",
    )
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        context = conn.execute(
            """
            SELECT
              review_states.user_id::text AS user_id,
              review_states.plan_id::text AS plan_id,
              review_states.knowledge_point_id::text AS id,
              review_states.last_fsrs_rating,
              review_states.reps,
              review_states.lapses,
              review_states.last_attempt_id::text AS last_attempt_id,
              knowledge_points.title,
              knowledge_points.description,
              knowledge_points.order_index,
              knowledge_points.skill_tags_json,
              knowledge_points.lesson_outline_json,
              knowledge_points.mastery_score,
              knowledge_points.weak_points_json,
              knowledge_points.last_exercise_result,
              knowledge_points.last_exercise_score,
              runtime_profiles.id::text AS runtime_profile_id,
              runtime_profiles.language,
              runtime_profiles.runtime_tier,
              runtime_profiles.runner,
              runtime_profiles.supports_tests,
              runtime_profiles.supports_stdout
            FROM review_states
            JOIN knowledge_points ON knowledge_points.id = review_states.knowledge_point_id
            JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
            JOIN runtime_profiles ON runtime_profiles.id = language_courses.runtime_profile_id
            WHERE review_states.user_id = %s
              AND review_states.knowledge_point_id = %s
            LIMIT 1
            """,
            (user_id, knowledge_point_id),
        ).fetchone()
        if context is None:
            return {"status": "failed", "failure_code": "KNOWLEDGE_POINT_NOT_FOUND"}
        try:
            from app.services.repositories.review_seed_bank import (
                ReviewSeedBankGenerationError,
                generate_review_seed_bank_for_knowledge_point,
            )
        except ImportError as exc:
            return {
                "status": "failed",
                "failure_code": "API_REPOSITORY_UNAVAILABLE",
                "failure_message": exc.__class__.__name__,
                "generator_version": GENERATOR_VERSION,
            }

        runtime_profile = {
            "id": str(context["runtime_profile_id"]),
            "language": context["language"],
            "runtime_tier": context["runtime_tier"],
            "runner": context["runner"],
            "supports_tests": context["supports_tests"],
            "supports_stdout": context["supports_stdout"],
        }
        try:
            seed_bank = generate_review_seed_bank_for_knowledge_point(
                conn,
                user_id=str(context["user_id"]),
                plan_id=str(context["plan_id"]),
                knowledge_point=context,
                runtime_profile=runtime_profile,
            )
        except ReviewSeedBankGenerationError as exc:
            conn.commit()
            return {
                "status": "failed",
                "failure_code": exc.code,
                "generator_version": GENERATOR_VERSION,
            }
        conn.commit()
    return {
        "status": "ready",
        "seed_count": int(seed_bank["seed_count"]),
        "generator_version": GENERATOR_VERSION,
    }
