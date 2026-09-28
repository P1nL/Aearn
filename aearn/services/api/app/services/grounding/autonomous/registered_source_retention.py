"""Caller-owned C capture cleanup; formal corpus history has separate authority.

Only schema 320's captured body is mutable. A reviewed indefinite-history grant
is independent of temporary capture retention and current-use permission.
This module is not a scheduler, public reader, or grant issuer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection, Error
from psycopg.pq import TransactionStatus


class RegisteredRetentionDenied(ValueError):
    """Safe code only; never include database errors or captured material."""


@dataclass(frozen=True)
class RegisteredRetentionReport:
    capture_bodies_cleared: int
    historical_chunks_preserved: int
    blocked_formal_documents: int
    more_pending: bool
    status: Literal["no_due_capture", "cleared", "partial", "blocked_formal_history"]


def _require_transaction(conn: Connection[dict[str, Any]]) -> None:
    if conn.autocommit or conn.info.transaction_status != TransactionStatus.INTRANS:
        raise RegisteredRetentionDenied("TRANSACTION_REQUIRED")


def require_indefinite_history_grant(
    conn: Connection[dict[str, Any]], *, admission_id: UUID
) -> None:
    """Pre-link registered-source guard; current-use admission remains separate.

    Both exact policy and immutable review must grant formal history. Call this
    in the link writer's transaction, alongside its current-use checks. Schema
    330 currently checks only the review flag; this guard must be wired there
    before its pre-link protection can be claimed for all writers.
    """
    _require_transaction(conn)
    if type(admission_id) is not UUID:
        raise RegisteredRetentionDenied("HISTORY_GRANT_MISSING")
    row = conn.execute(
        """SELECT review.immutable_history_allowed AS reviewed_history,
                  policy.immutable_history_allowed AS policy_history,
                  review.policy_generation AS review_generation,
                  policy.generation AS policy_generation
           FROM rag_source_admissions admission
           JOIN rag_source_reviews review ON review.id=admission.review_id
           JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id
           WHERE admission.id=%s AND admission.active
             AND review.registered_capture_id IS NOT NULL
           FOR SHARE OF admission,review,policy""",
        (admission_id,),
    ).fetchone()
    if (row is None or row["reviewed_history"] is not True
            or row["policy_history"] is not True
            or row["review_generation"] != row["policy_generation"]):
        raise RegisteredRetentionDenied("HISTORY_GRANT_MISSING")


def clear_registered_captures(
    conn: Connection[dict[str, Any]], *, limit: int = 100,
    operator_approved: bool = False,
) -> RegisteredRetentionReport:
    """Operator-gated cleanup with bounded database-failure reporting."""
    try:
        return _clear_registered_captures(
            conn, limit=limit, operator_approved=operator_approved,
        )
    except Error:
        raise RegisteredRetentionDenied("RETENTION_STORAGE_FAILED") from None


def _clear_registered_captures(
    conn: Connection[dict[str, Any]], *, limit: int,
    operator_approved: bool,
) -> RegisteredRetentionReport:
    """Clear expired/revoked captures, retaining hash and citation audit facts.

    Requires a caller-owned transaction and trusted operator approval. The
    caller commits. A blocked-formal-history result does not undo capture
    clearing: linked corpus bytes without an indefinite grant remain in 260
    and need a reviewed schema migration/recovery, not a silent success.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise RegisteredRetentionDenied("INVALID_CLEANUP_LIMIT")
    if operator_approved is not True:
        raise RegisteredRetentionDenied("OPERATOR_APPROVAL_REQUIRED")
    _require_transaction(conn)
    with conn.transaction():
        rows = conn.execute(
            """SELECT capture.id FROM rag_registered_source_captures capture
               JOIN rag_registered_source_policies policy
                 ON policy.policy_id=capture.policy_id
                AND policy.generation=capture.generation
               WHERE capture.cleared_at IS NULL
                 AND (capture.retention_until<=clock_timestamp()
                      OR policy.revoked_at IS NOT NULL OR NOT policy.enabled)
               ORDER BY capture.retention_until,capture.id LIMIT %s
               FOR UPDATE OF capture,policy SKIP LOCKED""",
            (limit,),
        ).fetchall()
        ids = [row["id"] for row in rows]
        if not ids:
            pending = conn.execute(
                """SELECT EXISTS (
                     SELECT 1 FROM rag_registered_source_captures capture
                     JOIN rag_registered_source_policies policy
                       ON policy.policy_id=capture.policy_id
                      AND policy.generation=capture.generation
                     WHERE capture.cleared_at IS NULL AND
                       (capture.retention_until<=clock_timestamp()
                        OR policy.revoked_at IS NOT NULL OR NOT policy.enabled)
                   ) AS pending"""
            ).fetchone()
            more = pending is None or pending["pending"] is True
            return RegisteredRetentionReport(0, 0, 0, more, "partial" if more else "no_due_capture")

        # Sealed 260 content is immutable and constrained by NOT NULL, hash and
        # stored FTS. Do not mutate chunks, disable triggers, or erase citations.
        history = conn.execute(
            """SELECT count(chunk.chunk_id) FILTER (
                     WHERE review.immutable_history_allowed
                       AND policy.immutable_history_allowed
                       AND review.policy_generation=policy.generation) AS preserved,
                      count(DISTINCT (link.corpus_id,link.document_id)) FILTER (
                     WHERE NOT review.immutable_history_allowed
                        OR NOT policy.immutable_history_allowed
                        OR review.policy_generation<>policy.generation) AS blocked
               FROM rag_source_reviews review
               JOIN rag_registered_source_policies policy
                 ON policy.policy_id=review.policy_id
               JOIN rag_source_admissions admission ON admission.review_id=review.id
               JOIN rag_corpus_admission_links link ON link.admission_id=admission.id
               LEFT JOIN grounding_corpus_chunks chunk
                 ON chunk.corpus_version_id=link.corpus_id
                AND chunk.document_id=link.document_id
               WHERE review.registered_capture_id=ANY(%s)""",
            (ids,),
        ).fetchone()
        if history is None:
            raise RegisteredRetentionDenied("HISTORY_AUDIT_UNAVAILABLE")
        updated = conn.execute(
            """UPDATE rag_registered_source_captures
               SET captured_body=NULL,cleared_at=clock_timestamp()
               WHERE id=ANY(%s) AND cleared_at IS NULL RETURNING id""",
            (ids,),
        ).fetchall()
        if len(updated) != len(ids):
            raise RegisteredRetentionDenied("CAPTURE_CLEAR_INCOMPLETE")
        pending = conn.execute(
            """SELECT EXISTS (
                 SELECT 1 FROM rag_registered_source_captures capture
                 JOIN rag_registered_source_policies policy
                   ON policy.policy_id=capture.policy_id
                  AND policy.generation=capture.generation
                 WHERE capture.cleared_at IS NULL AND
                   (capture.retention_until<=clock_timestamp()
                    OR policy.revoked_at IS NOT NULL OR NOT policy.enabled)
               ) AS pending"""
        ).fetchone()
        more = pending is None or pending["pending"] is True
        blocked = int(history["blocked"])
        status: Literal["no_due_capture", "cleared", "partial", "blocked_formal_history"] = (
            "blocked_formal_history" if blocked else "partial" if more else "cleared"
        )
        return RegisteredRetentionReport(
            len(updated), int(history["preserved"]), blocked, more, status,
        )
