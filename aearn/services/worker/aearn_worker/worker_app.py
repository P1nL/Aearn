import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row


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
