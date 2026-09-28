"""Transaction-scoped persistence for provider-native Tavily extractions.

No method opens a connection, commits, performs network I/O, or upgrades provider
text into origin transport evidence. The caller owns the transaction.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg

from .contracts import SubjectScope
from .source_review_repository import CompleteCapture
from .tavily_extract import TavilyExtractResult

_KEY = re.compile(r"[A-Za-z0-9._:-]{8,160}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ERROR = re.compile(r"[a-z][a-z0-9_]{2,79}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_MAX_CONTENT_BYTES = 8 * 1024 * 1024


class TavilyCaptureDenied(ValueError):
    """Bounded refusal code without provider text, content, or credentials."""


def _digest(*parts: object) -> str:
    value = json.dumps(parts, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode()).hexdigest()


class TavilyCaptureRepository:
    """Caller-owned PostgreSQL repository; all operations are transaction scoped."""

    def __init__(self, conn: psycopg.Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def dispatch(
        self,
        *,
        policy_id: str,
        generation: int,
        operation_key: str,
        request_sha256: str,
        attempt_id: UUID | None = None,
        content_format: str = "markdown",
        extract_depth: str = "advanced",
    ) -> UUID:
        if (
            self.conn.autocommit
            or not isinstance(policy_id, str)
            or not policy_id
            or type(generation) is not int
            or generation < 1
            or not isinstance(operation_key, str)
            or _KEY.fullmatch(operation_key) is None
            or not isinstance(request_sha256, str)
            or _HASH.fullmatch(request_sha256) is None
            or (attempt_id is not None and type(attempt_id) is not UUID)
            or content_format not in {"markdown", "text"}
            or extract_depth not in {"advanced", "basic"}
        ):
            raise TavilyCaptureDenied("DISPATCH_DENIED")
        resolved_attempt_id = attempt_id if attempt_id is not None else uuid4()
        try:
            policy = self.conn.execute(
                "SELECT * FROM rag_registered_source_policies "
                "WHERE policy_id=%s AND generation=%s FOR SHARE",
                (policy_id, generation),
            ).fetchone()
            if policy is None:
                raise TavilyCaptureDenied("POLICY_DENIED")
            root = self.conn.execute(
                "SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR UPDATE",
                (policy["root_id"],),
            ).fetchone()
            clock_row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
            if clock_row is None:
                raise TavilyCaptureDenied("CLOCK_DENIED")
            now = clock_row["now"]
            used_row = self.conn.execute(
                "SELECT count(*) AS count FROM rag_provider_extraction_attempts WHERE root_id=%s",
                (policy["root_id"],),
            ).fetchone()
            if (
                not policy["enabled"]
                or policy["revoked_at"] is not None
                or policy["expires_at"] <= now
                or policy["retention_until"] <= now
                or root is None
                or not root["enabled"]
                or root["delegation_expires_at"] <= now
                or not root["period_start"] <= now < root["period_end"]
                or root["policy_id"] != policy_id
                or root["policy_generation"] != generation
                or used_row is None
                or used_row["count"] >= root["cap_units"]
            ):
                raise TavilyCaptureDenied("POLICY_DENIED")
            row = self.conn.execute(
                "INSERT INTO rag_provider_extraction_attempts "
                "(id,policy_id,generation,root_id,operation_key,requested_url,request_sha256,"
                "content_format,extract_depth) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (
                    resolved_attempt_id,
                    policy_id,
                    generation,
                    policy["root_id"],
                    operation_key,
                    policy["canonical_url"],
                    request_sha256,
                    content_format,
                    extract_depth,
                ),
            ).fetchone()
            if row is None:
                raise TavilyCaptureDenied("ALREADY_DISPATCHED")
            return row["id"]
        except TavilyCaptureDenied:
            raise
        except psycopg.Error as exc:
            raise TavilyCaptureDenied("DISPATCH_PERSISTENCE_DENIED") from exc

    def settle(
        self,
        *,
        attempt_id: UUID,
        result: TavilyExtractResult,
        capture_id: UUID,
    ) -> UUID:
        if (
            self.conn.autocommit
            or type(attempt_id) is not UUID
            or type(capture_id) is not UUID
            or type(result) is not TavilyExtractResult
            or not isinstance(result.request_id, str)
            or _REQUEST_ID.fullmatch(result.request_id) is None
            or result.received_at.tzinfo is None
            or result.received_at.utcoffset() is None
            or result.content_format not in {"markdown", "text"}
            or result.extract_depth not in {"advanced", "basic"}
            or _HASH.fullmatch(result.content_sha256) is None
            or _HASH.fullmatch(result.response_sha256) is None
            or (
                result.usage_credits is not None
                and (
                    type(result.usage_credits) not in (int, float)
                    or not math.isfinite(result.usage_credits)
                    or result.usage_credits < 0
                )
            )
        ):
            raise TavilyCaptureDenied("SETTLEMENT_DENIED")
        body = result.content.encode("utf-8")
        if (
            not body
            or len(body) > _MAX_CONTENT_BYTES
            or hashlib.sha256(body).hexdigest() != result.content_sha256
        ):
            raise TavilyCaptureDenied("SETTLEMENT_DENIED")
        try:
            attempt = self.conn.execute(
                "SELECT * FROM rag_provider_extraction_attempts WHERE id=%s FOR UPDATE",
                (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["state"] != "dispatched":
                raise TavilyCaptureDenied("ATTEMPT_DENIED")
            policy = self.conn.execute(
                "SELECT * FROM rag_registered_source_policies "
                "WHERE policy_id=%s AND generation=%s FOR SHARE",
                (attempt["policy_id"], attempt["generation"]),
            ).fetchone()
            root = self.conn.execute(
                "SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR SHARE",
                (attempt["root_id"],),
            ).fetchone()
            clock_row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
            if clock_row is None:
                raise TavilyCaptureDenied("CLOCK_DENIED")
            now = clock_row["now"]
            if (
                policy is None
                or root is None
                or not policy["enabled"]
                or policy["revoked_at"] is not None
                or policy["expires_at"] <= now
                or policy["retention_until"] <= now
                or policy["root_id"] != attempt["root_id"]
                or policy["canonical_url"] != attempt["requested_url"]
                or policy["canonical_url"] != result.url
                or policy["max_captured_bytes"] < len(body)
                or not root["enabled"]
                or root["delegation_expires_at"] <= now
                or not root["period_start"] <= now < root["period_end"]
                or root["policy_id"] != attempt["policy_id"]
                or root["policy_generation"] != attempt["generation"]
                or attempt["content_format"] != result.content_format
                or attempt["extract_depth"] != result.extract_depth
                or result.received_at < attempt["dispatched_at"]
                or result.received_at > now
            ):
                raise TavilyCaptureDenied("CURRENT_AUTHORITY_DENIED")
            updated = self.conn.execute(
                "UPDATE rag_provider_extraction_attempts SET state='settled',"
                "provider_request_id=%s,response_sha256=%s,content_sha256=%s,content_bytes=%s,"
                "usage_credits=%s,received_at=%s WHERE id=%s AND state='dispatched' RETURNING id",
                (
                    result.request_id,
                    result.response_sha256,
                    result.content_sha256,
                    len(body),
                    result.usage_credits,
                    result.received_at,
                    attempt_id,
                ),
            ).fetchone()
            if updated is None:
                raise TavilyCaptureDenied("ATTEMPT_DENIED")
            content_type = "text/markdown" if result.content_format == "markdown" else "text/plain"
            captured = self.conn.execute(
                "INSERT INTO rag_registered_source_captures "
                "(id,provider_attempt_id,policy_id,generation,request_chain,final_url,content_type,"
                "fetched_sha256,captured_bytes,captured_body,license_id,retention_until,"
                "evidence_level,fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "'provider_extracted',%s) RETURNING id",
                (
                    capture_id,
                    attempt_id,
                    attempt["policy_id"],
                    attempt["generation"],
                    json.dumps([attempt["requested_url"]], separators=(",", ":")),
                    attempt["requested_url"],
                    content_type,
                    result.content_sha256,
                    len(body),
                    body,
                    policy["license_id"],
                    policy["retention_until"],
                    result.received_at,
                ),
            ).fetchone()
            if captured is None:
                raise TavilyCaptureDenied("CAPTURE_PERSISTENCE_DENIED")
            return captured["id"]
        except TavilyCaptureDenied:
            raise
        except psycopg.Error as exc:
            raise TavilyCaptureDenied("SETTLEMENT_PERSISTENCE_DENIED") from exc

    def fail(self, *, attempt_id: UUID, error_code: str, unknown: bool = False) -> None:
        if (
            self.conn.autocommit
            or type(attempt_id) is not UUID
            or not isinstance(error_code, str)
            or _ERROR.fullmatch(error_code) is None
            or type(unknown) is not bool
        ):
            raise TavilyCaptureDenied("FAILURE_DENIED")
        try:
            row = self.conn.execute(
                "UPDATE rag_provider_extraction_attempts SET state=%s,safe_error=%s,"
                "received_at=clock_timestamp() WHERE id=%s AND state='dispatched' RETURNING id",
                ("unknown" if unknown else "failed", error_code, attempt_id),
            ).fetchone()
            if row is None:
                raise TavilyCaptureDenied("ATTEMPT_DENIED")
        except TavilyCaptureDenied:
            raise
        except psycopg.Error as exc:
            raise TavilyCaptureDenied("FAILURE_PERSISTENCE_DENIED") from exc

    def resolve_capture(
        self,
        capture_id: UUID,
        now: datetime,
    ) -> tuple[CompleteCapture, dict[str, Any]] | None:
        if type(capture_id) is not UUID or now.tzinfo is None or now.utcoffset() is None:
            raise TavilyCaptureDenied("CAPTURE_DENIED")
        try:
            row = self.conn.execute(
                "SELECT c.*,p.source_handle,p.subject_id,p.subject_version,p.facets,p.origin,"
                "p.reading_level,p.allowed_usages,p.immutable_history_allowed,p.enabled,p.revoked_at,"
                "p.expires_at,p.retention_until AS policy_retention,p.root_id,"
                "p.license_id AS policy_license,p.generation AS policy_generation,"
                "a.state AS attempt_state,a.provider,a.provider_request_id,a.requested_url,"
                "a.request_sha256,a.response_sha256,a.content_sha256 AS attempt_content_sha256,"
                "a.content_bytes AS attempt_content_bytes,a.content_format,a.extract_depth,"
                "a.usage_credits,a.received_at,r.enabled AS root_enabled,"
                "r.delegation_expires_at,r.period_start,r.period_end,r.policy_id AS root_policy_id,"
                "r.policy_generation AS root_policy_generation "
                "FROM rag_registered_source_captures c "
                "JOIN rag_provider_extraction_attempts a ON a.id=c.provider_attempt_id "
                "JOIN rag_registered_source_policies p ON p.policy_id=c.policy_id "
                "AND p.generation=c.generation "
                "JOIN rag_budget_authority_roots r ON r.root_id=p.root_id "
                "WHERE c.id=%s AND c.provider_attempt_id IS NOT NULL FOR SHARE OF c,a,p,r",
                (capture_id,),
            ).fetchone()
            if row is None:
                return None
            body = bytes(row["captured_body"] or b"")
            chain = row["request_chain"]
            if (
                row["generation"] != row["policy_generation"]
                or not row["enabled"]
                or row["revoked_at"] is not None
                or row["expires_at"] <= now
                or row["policy_retention"] <= now
                or row["retention_until"] <= now
                or row["cleared_at"] is not None
                or row["attempt_state"] != "settled"
                or row["provider"] != "tavily"
                or not row["provider_request_id"]
                or row["requested_url"] != row["final_url"]
                or row["response_sha256"] is None
                or row["attempt_content_sha256"] != row["fetched_sha256"]
                or row["attempt_content_bytes"] != row["captured_bytes"]
                or row["license_id"] != row["policy_license"]
                or row["evidence_level"] != "provider_extracted"
                or row["content_type"]
                != ("text/markdown" if row["content_format"] == "markdown" else "text/plain")
                or row["transport_proof"] is not None
                or row["transport_proof_sha256"] is not None
                or row["attestor_key_sha256"] is not None
                or row["worker_image_sha256"] is not None
                or not body
                or len(body) != row["captured_bytes"]
                or len(body) > _MAX_CONTENT_BYTES
                or hashlib.sha256(body).hexdigest() != row["fetched_sha256"]
                or not row["root_enabled"]
                or row["delegation_expires_at"] <= now
                or not row["period_start"] <= now < row["period_end"]
                or row["root_policy_id"] != row["policy_id"]
                or row["root_policy_generation"] != row["policy_generation"]
                or not isinstance(chain, list)
                or chain != [row["requested_url"]]
            ):
                raise TavilyCaptureDenied("CAPTURE_DENIED")
            scope = SubjectScope(
                subject_id=row["subject_id"],
                subject_version=row["subject_version"],
                facets=tuple(row["facets"]),
            )
            capture = CompleteCapture(
                capture_id,
                "registered",
                body,
                row["fetched_sha256"],
                row["fetched_sha256"],
                scope,
                row["source_handle"],
                row["final_url"],
                tuple(chain),
                row["origin"],
                row["reading_level"],
                row["policy_license"],
            )
            provenance = _digest(
                "provider_extracted",
                str(capture_id),
                str(row["provider_attempt_id"]),
                row["provider"],
                row["provider_request_id"],
                row["request_sha256"],
                row["response_sha256"],
                row["fetched_sha256"],
                row["content_format"],
                row["extract_depth"],
                row["captured_bytes"],
                row["policy_id"],
                row["policy_generation"],
                row["root_id"],
                row["requested_url"],
            )
            policy = dict(
                row,
                storage_receipt_id="provider.store." + provenance[:32],
                provider_provenance_digest=provenance,
            )
            return capture, policy
        except TavilyCaptureDenied:
            raise
        except psycopg.Error as exc:
            raise TavilyCaptureDenied("CAPTURE_READ_DENIED") from exc

    def provenance_digest(
        self,
        capture: CompleteCapture,
        *,
        expected_format: str | None = None,
    ) -> str | None:
        if (
            type(capture) is not CompleteCapture
            or expected_format not in (None, "markdown", "text")
        ):
            return None
        try:
            clock_row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
            if clock_row is None:
                return None
            resolved = self.resolve_capture(capture.capture_id, clock_row["now"])
        except (TavilyCaptureDenied, psycopg.Error):
            return None
        if resolved is None or resolved[0] != capture:
            return None
        if expected_format is not None and resolved[1].get("content_format") != expected_format:
            return None
        value = resolved[1].get("provider_provenance_digest")
        return value if isinstance(value, str) and _HASH.fullmatch(value) else None
