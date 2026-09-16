"""Resolve content identity from a frozen plan, never from learner/model prose."""
from psycopg import Connection


class LearningCatalogScopeError(ValueError):
    pass


def resolve_catalog_knowledge_key(
    conn: Connection[dict[str, object]], *, user_id: str, track_id: str,
    plan_revision_id: str, knowledge_key: str,
) -> str:
    row = conn.execute(
        "SELECT tutor_plan_catalog_knowledge_key(%s,%s,%s,%s) AS knowledge_key",
        (user_id, track_id, plan_revision_id, knowledge_key),
    ).fetchone()
    if row is None or not isinstance(row["knowledge_key"], str) or not row["knowledge_key"]:
        raise LearningCatalogScopeError("plan catalog scope was not found")
    return row["knowledge_key"]


def resolve_session_catalog_knowledge_key(
    conn: Connection[dict[str, object]], *, user_id: str, track_id: str,
    teaching_session_id: str, knowledge_key: str,
) -> str:
    row = conn.execute(
        """SELECT active_plan_revision_id FROM tutor_teaching_sessions WHERE id=%s
           AND user_id=%s AND track_id=%s AND knowledge_key=%s""",
        (teaching_session_id, user_id, track_id, knowledge_key),
    ).fetchone()
    if row is None:
        raise LearningCatalogScopeError("teaching catalog scope was not found")
    return resolve_catalog_knowledge_key(
        conn, user_id=user_id, track_id=track_id,
        plan_revision_id=str(row["active_plan_revision_id"]), knowledge_key=knowledge_key,
    )
