"""One authorized gen3 python_reference fetch; reuses original498 transport, not a wallet."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from .registered_course_refresh import (
    ACCESS_ROOT_PREFIX, AUTHORIZATION, DATABASE, TARGETS, CourseRefreshResult,
    deadline, require, required_row,
)
from .registered_source_policy import RegisteredSourceScope

TARGET = "python_reference"
ORIGINAL_ID = UUID("6b01e22b-856e-413b-b8d8-05a7f1dfc61f")
ORIGINAL_ROOT = "root.course.python_reference.20261003"
LATEST_ID = UUID("ee050b7c-a7ec-583f-8b01-d2b0259f3510")
PREVIOUS_AUTHORIZATION_ID = UUID("46207149-ab55-5054-9821-da9059c0a77a")
SUCCESSOR_ID = UUID("fbfabcf0-f336-5b12-9824-8b0b2782b69c")
ROOT_ID = ACCESS_ROOT_PREFIX + "python_reference.successor.20261013"
POLICY_ID = "source.course-refresh.20261013.python_reference"


def resource_debits(snapshot: dict[str, Any]) -> tuple[int, int]:
    """Exact known lineage; SQL recomputes before issue AND actual dispatch."""
    attempts = snapshot.get("attempts", [])
    require(len(attempts) == 2 and
            [str(a["id"]) for a in attempts] == [str(ORIGINAL_ID), str(LATEST_ID)] and
            [a["state"] for a in attempts] == ["settled", "settled"] and
            [a["generation"] for a in attempts] == [1, 2] and
            attempts[0]["supplemental_authorization_id"] is None and
            str(attempts[1]["supplemental_authorization_id"]) == "26b2b080-1aa2-5fdd-a530-6fcbc5cb89e8",
            "COURSE_REFRESH_SUCCESSOR_LINEAGE_DENIED")
    # Do not drop historical debits or treat an unexpected UNKNOWN as zero.
    return len(attempts), sum(a["state"] == "unknown" for a in attempts)


def issue(conn: Connection[dict[str, Any]], *, target_key: str,
          source_permission_expires_at: datetime, retention_permission_expires_at: datetime,
          enabled: bool = False) -> CourseRefreshResult:
    require(enabled is True and target_key == TARGET, "COURSE_REFRESH_DEFAULT_OFF")
    require(conn.info.transaction_status == TransactionStatus.INTRANS, "COURSE_REFRESH_CALLER_TRANSACTION_REQUIRED")
    require(required_row(conn.execute("SELECT current_database() AS name").fetchone())["name"] == DATABASE,
            "COURSE_REFRESH_OWNED_DATABASE_REQUIRED")
    url, _subject, _facet, _license, profile = TARGETS[target_key]
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    original = required_row(conn.execute("SELECT id,root_id FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=%s AND supplemental_authorization_id IS NULL FOR UPDATE", (url_hash,)).fetchone(), "COURSE_REFRESH_ORIGINAL_REQUIRED")
    require(original["id"] == ORIGINAL_ID and original["root_id"] == ORIGINAL_ROOT,
            "COURSE_REFRESH_SUCCESSOR_ORIGINAL_DENIED")
    require(conn.execute("SELECT 1 FROM rag_registered_course_refresh_authorizations WHERE id=%s",
                         (SUCCESSOR_ID,)).fetchone() is None, "COURSE_REFRESH_SUCCESSOR_ONCE_CONSUMED")
    # DB function sets UTC and reads actual attempts/captures/roots/periods/usage.
    row = required_row(conn.execute("SELECT s AS snapshot,encode(digest(s::text,'sha256'),'hex') AS hash FROM rag_registered_course_refresh_lineage(%s) AS s", (url_hash,)).fetchone())
    snapshot = row["snapshot"]
    carried, unknown = resource_debits(snapshot)
    latest = snapshot["attempts"][-1]
    policy = next(p for p in snapshot["policies"] if p["policy_id"] == latest["policy_id"])
    capture = next(c for c in snapshot["captures"] if c["fetch_attempt_id"] == latest["id"])
    now = required_row(conn.execute("SELECT clock_timestamp() AS now").fetchone())["now"]
    until = deadline(now, source_permission_expires_at, retention_permission_expires_at)
    dispatch_until = min(until, now + timedelta(minutes=30))
    aid = SUCCESSOR_ID
    sid, dispatch = uuid5(aid, "supplemental"), uuid5(aid, "dispatch")
    root_id = ROOT_ID
    policy_id = POLICY_ID
    scope = RegisteredSourceScope(policy_id=policy_id, generation=latest["generation"] + 1,
        source_handle=policy["source_handle"], subject_id=policy["subject_id"], subject_version=policy["subject_version"],
        facets=tuple(policy["facets"]), url=url, host=policy["host"], path=policy["path"],
        root_id=root_id, dispatch_id=dispatch, max_bytes=policy["max_captured_bytes"])
    wire = {**vars(scope), "dispatch_id": str(dispatch), "facets": list(scope.facets)}
    request_hash = hashlib.sha256(json.dumps({"scope": wire, "profile_id": profile, "method": "GET", "capture_kind": "full", "redirects": 0, "deadline_seconds": 90}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    operation = "course.refresh.20261006." + aid.hex
    conn.execute("""INSERT INTO rag_budget_authority_roots
        (root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,policy_generation,
         period_key,period_start,period_end,cap_units,enabled)
        VALUES (%s,%s,1,%s,%s,%s,'source-access-only.20261006',%s,%s,%s,true)""",
        (root_id, "delegation.course-refresh." + aid.hex, until, policy_id, scope.generation, now, until, carried + 1))
    conn.execute("""INSERT INTO rag_registered_source_policies
        (policy_id,generation,source_handle,subject_id,subject_version,facets,origin,reading_level,canonical_url,
         canonical_url_sha256,host,path,license_id,allowed_usages,immutable_history_allowed,max_captured_bytes,
         retention_until,expires_at,root_id,enabled)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,true)""",
        (policy_id, scope.generation, scope.source_handle, scope.subject_id, scope.subject_version, list(scope.facets),
         policy["origin"], policy["reading_level"], url, url_hash, scope.host, scope.path, policy["license_id"],
         policy["allowed_usages"], scope.max_bytes, until, until, root_id))
    conn.execute("""INSERT INTO rag_registered_course_refresh_authorizations
        (id,authorization_id,target_key,canonical_original_attempt_id,canonical_accounting_root_id,
         latest_attempt_id,latest_capture_id,latest_capture_sha256,canonical_url_sha256,lineage_snapshot,lineage_sha256,
         supplemental_authorization_id,dispatch_id,policy_id,generation,root_id,request_hash,operation_key,
         carried_dispatch_units,carried_unknown_units,cumulative_dispatch_ceiling,issued_at,
         source_permission_expires_at,retention_permission_expires_at,source_expires_at,dispatch_expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (aid, AUTHORIZATION, target_key, original["id"], original["root_id"], UUID(latest["id"]), UUID(capture["id"]),
         capture["fetched_sha256"], url_hash, Jsonb(snapshot), row["hash"], sid, dispatch, policy_id, scope.generation,
         root_id, request_hash, operation, carried, unknown, carried + 1, now, source_permission_expires_at,
         retention_permission_expires_at, until, dispatch_until))
    conn.execute("""INSERT INTO rag_registered_supplemental_authorizations
        (id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,prior_attempt_id,
         expires_at,approval_ref,course_refresh_authorization_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'standingpolicy.course-refresh.20261006',%s)""",
        (sid, dispatch, policy_id, scope.generation, url_hash, root_id, request_hash, UUID(latest["id"]), dispatch_until, aid))
    conn.execute("SELECT rag_registered_course_refresh_check(r,true) FROM rag_registered_course_refresh_authorizations r WHERE id=%s", (aid,))
    return CourseRefreshResult(aid, sid, scope, request_hash, operation, profile, until, dispatch_until, carried, unknown, policy)
