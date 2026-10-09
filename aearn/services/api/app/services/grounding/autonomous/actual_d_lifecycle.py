"""Conditional private lifecycle for actual-D v3; no IO, commits or new epochs."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.errors import CheckViolation
from psycopg.pq import TransactionStatus

ACTUAL_D_FORMAT = "aearn.rag.actual-d-finite-source.v3"
LIFECYCLE_FUNCTION = "public.rag_actual_d_private_epoch(uuid,bigint,boolean)"
EXPORT_LIMIT = 100


def _transaction(conn: Connection[dict[str, Any]]) -> None:
    if conn.autocommit or conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("actual D private lifecycle requires caller transaction")


def lifecycle_installed(conn: Connection[dict[str, Any]]) -> bool:
    _transaction(conn)
    row = conn.execute("SELECT to_regprocedure(%s) IS NOT NULL AS installed", (LIFECYCLE_FUNCTION,)).fetchone()
    return row is not None and row.get("installed") is True


def current_actual_d_epoch(conn: Connection[dict[str, Any]], *, user_id: UUID,
                           expected_epoch: int | None = None, nowait: bool = False) -> int:
    """Read and lock original active owner/epoch; missing 503 always denies."""
    if type(user_id) is not UUID or (expected_epoch is not None and
                                   (type(expected_epoch) is not int or expected_epoch < 1)):
        raise ValueError("actual D private owner/epoch invalid")
    if not lifecycle_installed(conn):
        raise ValueError("actual D private lifecycle not installed")
    try:
        row = conn.execute("SELECT public.rag_actual_d_private_epoch(%s,%s,%s) AS epoch",
                           (user_id, expected_epoch, nowait)).fetchone()
    except CheckViolation:
        raise ValueError("actual D private owner/epoch unavailable") from None
    if row is None or type(row.get("epoch")) is not int or row["epoch"] < 1:
        raise ValueError("actual D private owner/epoch unavailable")
    return int(row["epoch"])


def export_actual_d_private(conn: Connection[dict[str, Any]], user_id: UUID) -> dict[str, object]:
    """Only IDs/status/times/counts; no signed body, handles, source or hashes."""
    if not lifecycle_installed(conn):
        assert_actual_d_purged(conn, user_id)
        return {"status": "lifecycle_not_installed", "count": 0, "items": [], "has_more": False}
    rows = conn.execute(
        """SELECT id,issued_at,expires_at,revoked_at,count(*) OVER () AS total_count
           FROM rag_assessment_source_evidence
           WHERE private_user_id=%s AND signed_proof->'payload'->>'format'=%s
           ORDER BY issued_at,id LIMIT %s""", (user_id, ACTUAL_D_FORMAT, EXPORT_LIMIT),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        items.append({"id": str(row["id"]), "status": "revoked" if row["revoked_at"] else "issued",
                      "issued_at": row["issued_at"].isoformat(), "expires_at": row["expires_at"].isoformat(),
                      "revoked_at": row["revoked_at"].isoformat() if row["revoked_at"] else None})
    count = int(rows[0]["total_count"]) if rows else 0
    result: dict[str, object] = {"status": "private", "count": count, "items": items, "has_more": count > len(items)}
    bridge = conn.execute("SELECT to_regclass('public.rag_actual_d_private_provenance') IS NOT NULL AS present").fetchone()
    if bridge is not None and bridge.get("present") is True:
        records = conn.execute("""SELECT private_evidence_id AS id,created_at,count(*) OVER () AS total_count
            FROM rag_actual_d_private_provenance WHERE user_id=%s ORDER BY created_at,private_evidence_id LIMIT %s""",
            (user_id, EXPORT_LIMIT)).fetchall()
        result["provenance"] = {"count": int(records[0]["total_count"]) if records else 0,
            "items": [{"id": str(r["id"]), "status": "bound", "created_at": r["created_at"].isoformat()} for r in records],
            "has_more": bool(records and int(records[0]["total_count"]) > len(records))}
    return result


def assert_actual_d_purged(conn: Connection[dict[str, Any]], user_id: UUID) -> None:
    """Original reset advances epoch/finishes 503; never broad-purge here.

    Read signed owner even without 503: never omit unclassified v3 from export
    or leave it behind on a successful reset/delete.
    """
    _transaction(conn)
    table = conn.execute("SELECT to_regclass('public.rag_assessment_source_evidence') IS NOT NULL AS present").fetchone()
    if table is None or table.get("present") is not True:
        return
    row = conn.execute(
        """SELECT count(*) AS count FROM rag_assessment_source_evidence
           WHERE signed_proof->'payload'->>'format'=%s
             AND signed_proof->'payload'->'prepared'->'actual_d'->'draft'->>'user_id'=%s""",
        (ACTUAL_D_FORMAT, str(user_id)),
    ).fetchone()
    if row is None or row["count"] != 0:
        raise ValueError("actual D private lifecycle purge blocked")


def finish_actual_d_private_purge(conn: Connection[dict[str, Any]], user_id: UUID) -> None:
    """Original D owner calls AFTER bindings/reviews/selections, BEFORE drafts.

    503 tail requires the original protected reset permit and advanced epoch;
    it invokes no 501/502/496/495 purge owner and never mints a new permit.
    """
    if lifecycle_installed(conn):
        conn.execute("SELECT public.rag_actual_d_private_purge(%s)", (user_id,))
    assert_actual_d_purged(conn, user_id)


def actual_d_private_counts(conn: Connection[dict[str, Any]], user_id: UUID) -> dict[str, int]:
    """Conditional target inventory; never reclassify the four mixed tables."""
    _transaction(conn)
    if type(user_id) is not UUID:
        raise ValueError("actual D private inventory owner invalid")
    result = {name: 0 for name in ("rag_assessment_source_evidence", "rag_source_reviews", "rag_source_admissions",
                                  "rag_source_claim_receipts", "rag_actual_d_private_provenance")}
    present = conn.execute("SELECT to_regclass('public.rag_assessment_source_evidence') IS NOT NULL AS present").fetchone()
    if present is None or present.get("present") is not True:
        return result
    # Signed owner works even before503, so old unclassified v3 blocks cutover.
    owner = "e.signed_proof->'payload'->>'format'=%s AND e.signed_proof->'payload'->'prepared'->'actual_d'->'draft'->>'user_id'=%s"
    joins = {
        "rag_assessment_source_evidence": "rag_assessment_source_evidence e",
        "rag_source_reviews": "rag_source_reviews r JOIN rag_assessment_source_evidence e ON e.id=r.assessment_evidence_id",
        "rag_source_admissions": "rag_source_admissions a JOIN rag_source_reviews r ON r.id=a.review_id JOIN rag_assessment_source_evidence e ON e.id=r.assessment_evidence_id",
        "rag_source_claim_receipts": "rag_source_claim_receipts c JOIN rag_assessment_source_evidence e ON e.id=c.assessment_evidence_id",
    }
    for name, source in joins.items():
        row = conn.execute(f"SELECT count(*) AS count FROM {source} WHERE {owner}", (ACTUAL_D_FORMAT, str(user_id))).fetchone()
        if row is None:
            raise ValueError("actual D private inventory unavailable")
        result[name] = int(row["count"])
    bridge = conn.execute("SELECT to_regclass('public.rag_actual_d_private_provenance') IS NOT NULL AS present").fetchone()
    if bridge is not None and bridge.get("present") is True:
        row = conn.execute("SELECT count(*) AS count FROM rag_actual_d_private_provenance WHERE user_id=%s", (user_id,)).fetchone()
        if row is None:
            raise ValueError("actual D private inventory unavailable")
        result["rag_actual_d_private_provenance"] = int(row["count"])
    return result
