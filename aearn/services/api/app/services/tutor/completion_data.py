"""User inventory for the three explicitly approved completion tables.

These tables are private target state, never shared corpus. Old installations
without the additive migrations remain readable while the feature is disabled.
Raw model requests, results and source units are deliberately not exported here.
"""
from __future__ import annotations

from psycopg import Connection


COMPLETION_PRIVATE_TABLES = (
    "tutor_run_execution_batches",
    "tutor_run_step_attempts",
    "tutor_lesson_authoring_stage_attempts",
)


def installed_completion_tables(conn: Connection[dict[str, object]]) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT name, to_regclass('public.' || name) IS NOT NULL AS present "
        "FROM unnest(%s::text[]) AS names(name)",
        (list(COMPLETION_PRIVATE_TABLES),),
    ).fetchall()
    present = {str(row["name"]) for row in rows if row.get("present") is True}
    return tuple(name for name in COMPLETION_PRIVATE_TABLES if name in present)


def completion_execution_counts(
    conn: Connection[dict[str, object]], user_id: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in installed_completion_tables(conn):
        # name comes only from the closed constant tuple above, never a request.
        row = conn.execute(
            f"SELECT count(*)::int AS count FROM {name} WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        value = row.get("count") if row is not None else None
        if type(value) is not int:
            raise ValueError("Completion inventory count is unavailable")
        counts[name] = value
    return counts


def export_completion_summary(
    conn: Connection[dict[str, object]], user_id: str,
) -> dict[str, object]:
    return {
        "schema_version": "completion_execution_summary_v1",
        "counts": completion_execution_counts(conn, user_id),
        "private_requests_results_and_source_units": "omitted",
    }


def purge_lesson_completion_stages(
    conn: Connection[dict[str, object]], user_id: str,
) -> None:
    """Called only inside the existing user-authorized learning-track purge.

The stage table's DELETE guard requires the same transaction-local user purge
capability as its authoring parent. Tutor run audit remains with the existing
retained conversation history; this helper never deletes it implicitly.
"""
    if "tutor_lesson_authoring_stage_attempts" in installed_completion_tables(conn):
        conn.execute(
            "DELETE FROM tutor_lesson_authoring_stage_attempts WHERE user_id = %s",
            (user_id,),
        )
