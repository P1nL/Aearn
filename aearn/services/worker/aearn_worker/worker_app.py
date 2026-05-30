import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

from aearn_worker.review_seed_bank_core import (
    GENERATOR_VERSION,
    ReviewSeedBankValidationError,
    build_review_seed_bank_payload,
    persist_failed_seed_bank,
    persist_ready_seed_bank,
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
              review_states.knowledge_point_id::text AS knowledge_point_id,
              review_states.last_fsrs_rating,
              review_states.lapses,
              knowledge_points.title,
              knowledge_points.description,
              knowledge_points.order_index,
              knowledge_points.weak_points_json,
              runtime_profiles.language,
              runtime_profiles.runtime_tier
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
            seeds, quality_report = build_review_seed_bank_payload(context)
        except (KeyError, ValueError, ReviewSeedBankValidationError) as exc:
            persist_failed_seed_bank(
                conn,
                user_id=str(context["user_id"]),
                plan_id=str(context["plan_id"]),
                knowledge_point_id=str(context["knowledge_point_id"]),
                failure_code="VALIDATION_FAILED",
                failure_message=str(exc),
            )
            conn.commit()
            return {"status": "failed", "failure_code": "VALIDATION_FAILED"}
        persist_ready_seed_bank(
            conn,
            user_id=str(context["user_id"]),
            plan_id=str(context["plan_id"]),
            knowledge_point_id=str(context["knowledge_point_id"]),
            seeds=seeds,
            quality_report=quality_report,
        )
        conn.commit()
    return {"status": "ready", "seed_count": len(seeds), "generator_version": GENERATOR_VERSION}
