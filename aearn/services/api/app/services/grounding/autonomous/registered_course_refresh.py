"""This run's five source-access renewals; not a wallet or general refresh service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb

from .registered_source_policy import RegisteredSourceScope

AUTHORIZATION = "aearn-development-20260927"
ACCESS_ROOT_PREFIX = "root.course-refresh.20261006."
DATABASE = "aearn_b1d_sandbox_20261001"
TARGETS = {
    "python_reference": ("https://docs.python.org/3/reference/simple_stmts.html", "route.python", "fundamentals", "psf-2.0", "course-python-reference-capture-v1"),
    "sqlite_select": ("https://www.sqlite.org/lang_select.html", "route.sql", "queries", "sqlite-public-domain", "sqlite-filter-order-source-v1"),
    "sqlite_expression": ("https://www.sqlite.org/lang_expr.html", "route.sql", "queries", "sqlite-public-domain", "course-sqlite-expr-capture-v1"),
    "sqlite_functions": ("https://www.sqlite.org/lang_corefunc.html", "route.sql", "queries", "sqlite-public-domain", "course-sqlite-functions-capture-v1"),
    "learnx_python": ("https://learnxinyminutes.com/python/", "route.python", "fundamentals", "cc-by-sa-3.0", "course-learnx-python-capture-v1"),
}


class CourseRefreshDenied(ValueError):
    """Stable non-secret operator refusal."""


def require(value: object, code: str = "COURSE_REFRESH_DENIED") -> None:
    if not value:
        raise CourseRefreshDenied(code)


def required_row(row: dict[str, Any] | None, code: str = "COURSE_REFRESH_ROW_REQUIRED") -> dict[str, Any]:
    if row is None:
        raise CourseRefreshDenied(code)
    return row


def deadline(now: datetime, access: datetime, retention: datetime) -> datetime:
    require(all(isinstance(t, datetime) and t.tzinfo is not None and t.utcoffset() is not None
                for t in (now, access, retention)), "COURSE_REFRESH_AWARE_PERMISSION_REQUIRED")
    result = min(now + timedelta(days=7), access, retention)
    require(result > now, "COURSE_REFRESH_PERMISSION_EXPIRED")
    return result


def resource_debits(snapshot: dict[str, Any], target: str) -> tuple[int, int]:
    """Convenience validation; SQL independently recomputes and enforces all facts."""
    require(target in TARGETS)
    attempts = snapshot["attempts"]
    states = [a["state"] for a in attempts]
    generations = [a["generation"] for a in attempts]
    if target == "sqlite_select":
        require(states == ["settled", "unknown", "settled"] and generations == [1, 1, 3],
                "COURSE_REFRESH_SELECT_LINEAGE_DENIED")
        require(attempts[1]["error_code"] == "EGRESS_UNVERIFIED_SIGNATURE_PID_NAMESPACE",
                "COURSE_REFRESH_SELECT_FAILURE_DENIED")
    else:
        require(states == ["settled"] and generations == [1] and
                attempts[0]["supplemental_authorization_id"] is None,
                "COURSE_REFRESH_COURSE_LINEAGE_DENIED")
    return len(attempts), states.count("unknown")


@dataclass(frozen=True)
class CourseRefreshResult:
    authorization_id: UUID
    supplemental_authorization_id: UUID
    scope: RegisteredSourceScope
    request_hash: str
    operation_key: str
    profile_id: str
    source_expires_at: datetime
    dispatch_expires_at: datetime
    carried_dispatch_units: int
    carried_unknown_units: int
    policy: dict[str, Any]

    def manifest_entry(self) -> dict[str, Any]:
        s = self.scope
        return {
            "scope": {**vars(s), "facets": list(s.facets), "dispatch_id": str(s.dispatch_id)},
            "profile_id": self.profile_id, "origin": self.policy["origin"],
            "license_id": self.policy["license_id"], "reading_level": self.policy["reading_level"],
            "allowed_usages": list(self.policy["allowed_usages"]), "deadline_seconds": 90,
            "expires_at": self.source_expires_at.isoformat(), "retention_until": self.source_expires_at.isoformat(),
            "supplemental_authorization_id": str(self.supplemental_authorization_id),
            "course_refresh_authorization_id": str(self.authorization_id),
            "request_hash": self.request_hash, "operation_key": self.operation_key,
        }


def issue(conn: Connection[dict[str, Any]], *, target_key: str,
          source_permission_expires_at: datetime, retention_permission_expires_at: datetime,
          enabled: bool = False) -> CourseRefreshResult:
    require(enabled is True and target_key in TARGETS, "COURSE_REFRESH_DEFAULT_OFF")
    require(required_row(conn.execute("SELECT current_database() AS name").fetchone())["name"] == DATABASE,
            "COURSE_REFRESH_OWNED_DATABASE_REQUIRED")
    url, _subject, _facet, _license, profile = TARGETS[target_key]
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    original = required_row(conn.execute("SELECT id,root_id FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=%s AND supplemental_authorization_id IS NULL FOR UPDATE", (url_hash,)).fetchone(), "COURSE_REFRESH_ORIGINAL_REQUIRED")
    # DB function sets UTC and reads actual attempts/captures/roots/periods/usage.
    row = required_row(conn.execute("SELECT s AS snapshot,encode(digest(s::text,'sha256'),'hex') AS hash FROM rag_registered_course_refresh_lineage(%s) AS s", (url_hash,)).fetchone())
    snapshot = row["snapshot"]
    carried, unknown = resource_debits(snapshot, target_key)
    latest = snapshot["attempts"][-1]
    policy = next(p for p in snapshot["policies"] if p["policy_id"] == latest["policy_id"])
    capture = next(c for c in snapshot["captures"] if c["fetch_attempt_id"] == latest["id"])
    now = required_row(conn.execute("SELECT clock_timestamp() AS now").fetchone())["now"]
    until = deadline(now, source_permission_expires_at, retention_permission_expires_at)
    dispatch_until = min(until, now + timedelta(minutes=30))
    aid = uuid5(NAMESPACE_URL, f"{AUTHORIZATION}:498:{original['id']}:{url}")
    sid, dispatch = uuid5(aid, "supplemental"), uuid5(aid, "dispatch")
    root_id = ACCESS_ROOT_PREFIX + target_key
    policy_id = "source.course-refresh.20261006." + target_key
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
