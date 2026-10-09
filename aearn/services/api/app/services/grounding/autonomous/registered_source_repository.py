"""Durable one-shot authority for operator-registered HTTPS sources.

Dispatch commits before network I/O. A crash/unknown response is never retried;
this operator lane does not manufacture a B discovery/provider receipt.
"""

from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .registered_source_policy import (
    RegisteredSourceGrantResolver,
    RegisteredSourceHopGrant,
    RegisteredSourceScope,
)
from .safe_fetch import FetchResult, SafeFetcher
from .registered_course_refresh import (
    ACCESS_ROOT_PREFIX, CourseRefreshDenied, CourseRefreshResult,
    issue as issue_course_refresh,
)

_KEY = re.compile(r"[A-Za-z0-9._:-]{8,160}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ERROR = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
_APPROVAL = re.compile(r"[A-Za-z0-9 ._:/+-]{16,256}\Z")
_CLOCK_SKEW = timedelta(seconds=30)


class RegisteredSourceDenied(ValueError):
    """Bounded, non-secret refusal code."""


def _clock(conn: psycopg.Connection[dict[str, Any]], now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise RegisteredSourceDenied("CLOCK_DENIED")
    row = conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
    if row is None or abs(row["db_now"] - now) > _CLOCK_SKEW:
        raise RegisteredSourceDenied("CLOCK_DENIED")
    return row["db_now"]


def _current(
    conn: psycopg.Connection[dict[str, Any]],
    scope: RegisteredSourceScope,
    now: datetime,
    *,
    lock: bool = False,
) -> dict[str, Any] | None:
    suffix = " FOR SHARE" if lock else ""
    policy = conn.execute(
        "SELECT * FROM rag_registered_source_policies WHERE policy_id=%s" + suffix,
        (scope.policy_id,),
    ).fetchone()
    if policy is None:
        return None
    root = conn.execute(
        "SELECT * FROM rag_budget_authority_roots WHERE root_id=%s" + suffix,
        (scope.root_id,),
    ).fetchone()
    db_now = _clock(conn, now)  # refresh after lock waits
    if (
        policy["generation"] != scope.generation
        or policy["source_handle"] != scope.source_handle
        or policy["subject_id"] != scope.subject_id
        or policy["subject_version"] != scope.subject_version
        or tuple(policy["facets"]) != scope.facets
        or policy["canonical_url"] != scope.url
        or policy["canonical_url_sha256"]
        != hashlib.sha256(scope.url.encode()).hexdigest()
        or policy["host"] != scope.host
        or policy["path"] != scope.path
        or policy["root_id"] != scope.root_id
        or policy["enabled"] is not True
        or policy["revoked_at"] is not None
        or not policy["license_id"]
        or not policy["allowed_usages"]
        or policy["immutable_history_allowed"] is not True
        or policy["max_captured_bytes"] < scope.max_bytes
        or policy["retention_until"] <= db_now
        or policy["expires_at"] <= db_now
        or root is None
        or root["enabled"] is not True
        or root["delegation_expires_at"] <= db_now
        or root["period_start"] > db_now
        or root["period_end"] <= db_now
        or root["policy_id"] != scope.policy_id
        or root["policy_generation"] != scope.generation
    ):
        return None
    return policy


class PostgresRegisteredSourceRepository(RegisteredSourceGrantResolver):
    """Each operation opens a short connection; none spans a remote request.

    Root delegation/period expiry is the current operator lifetime. Schema 320
    has no fetch-owner lease. A process-local two-check permit is an extra brake:
    only the instance that committed dispatch can permit the two SafeFetcher
    policy checks. A process crash loses the permit and cannot resume a GET.
    This host-side resolver cannot run inside the isolated egress namespace
    until a trusted local policy bridge is implemented.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._permit_lock = threading.Lock()
        self._permits: dict[UUID, tuple[RegisteredSourceScope, int]] = {}

    def issue_course_refresh_once(
        self, *, target_key: str, source_permission_expires_at: datetime,
        retention_permission_expires_at: datetime, now: datetime,
        enabled: bool = False,
    ) -> CourseRefreshResult:
        """Trusted main-only498 issuer; one short atomic transaction, no IO grant.

        This creates bounded source access, not a generic budget or new period.
        All lineage identities/counters come from actual DB rows and SQL checks.
        """
        if enabled is not True:
            raise RegisteredSourceDenied("COURSE_REFRESH_DEFAULT_OFF")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                conn.execute("SET LOCAL statement_timeout='10s'")
                conn.execute("SET LOCAL lock_timeout='5s'")
                _clock(conn, now)
                return issue_course_refresh(conn, target_key=target_key,
                    source_permission_expires_at=source_permission_expires_at,
                    retention_permission_expires_at=retention_permission_expires_at,
                    enabled=True)
        except CourseRefreshDenied as exc:
            raise RegisteredSourceDenied(str(exc)) from exc
        except psycopg.Error as exc:
            raise RegisteredSourceDenied("COURSE_REFRESH_ISSUE_DENIED") from exc

    def resolve(
        self, scope: RegisteredSourceScope, *, now: datetime
    ) -> RegisteredSourceHopGrant | None:
        if (
            type(scope) is not RegisteredSourceScope
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            return None
        # A DB-dispatched row alone is NOT a replayable network grant. The
        # two checks belong to one concrete zero-redirect SafeFetcher call.
        with self._permit_lock:
            permit = self._permits.get(scope.dispatch_id)
            if permit is None or permit[0] != scope or permit[1] <= 0:
                return None
            try:
                with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                    policy = _current(conn, scope, now)
                    if policy is None:
                        return None
                    attempt = conn.execute(
                        "SELECT a.id,a.state,a.root_id,s.expires_at AS supplemental_expires_at, "
                        "r.authorization_id AS revoked_authorization_id "
                        "FROM rag_registered_fetch_attempts a LEFT JOIN "
                        "rag_registered_supplemental_authorizations s "
                        "ON s.id=a.supplemental_authorization_id LEFT JOIN "
                        "rag_registered_supplemental_revocations r "
                        "ON r.authorization_id=s.id "
                        "WHERE a.id=%s AND a.policy_id=%s AND a.generation=%s "
                        "AND a.canonical_url_sha256=%s",
                        (
                            scope.dispatch_id,
                            scope.policy_id,
                            scope.generation,
                            policy["canonical_url_sha256"],
                        ),
                    ).fetchone()
                    if (
                        attempt is None
                        or attempt["id"] != scope.dispatch_id
                        or attempt["root_id"] != scope.root_id
                        or attempt["state"] != "dispatched"
                        or attempt.get("revoked_authorization_id") is not None
                        or (attempt["supplemental_expires_at"] is not None
                            and attempt["supplemental_expires_at"] <= _clock(conn, now))
                    ):
                        return None
                    self._permits[scope.dispatch_id] = (scope, permit[1] - 1)
                    return RegisteredSourceHopGrant(
                        scope,
                        True,
                        policy["max_captured_bytes"],
                        min(policy["retention_until"], policy["expires_at"]),
                    )
            except (psycopg.Error, RegisteredSourceDenied, ValueError, TypeError):
                return None

    def take_dispatch(
        self,
        scope: RegisteredSourceScope,
        *,
        operation_key: str,
        request_hash: str,
        now: datetime,
        supplemental_authorization_id: UUID | None = None,
    ) -> UUID:
        """Atomic first insert, committed before DNS. No replay returns a GET grant."""
        if (
            type(scope) is not RegisteredSourceScope
            or not isinstance(operation_key, str)
            or _KEY.fullmatch(operation_key) is None
            or not isinstance(request_hash, str)
            or _HASH.fullmatch(request_hash) is None
            or (supplemental_authorization_id is not None
                and type(supplemental_authorization_id) is not UUID)
        ):
            raise RegisteredSourceDenied("DISPATCH_DENIED")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                policy = _current(conn, scope, now, lock=True)
                if policy is None:
                    raise RegisteredSourceDenied("POLICY_DENIED")
                if supplemental_authorization_id is not None:
                    auth = conn.execute(
                        "SELECT * FROM rag_registered_supplemental_authorizations "
                        "WHERE id=%s",
                        (supplemental_authorization_id,),
                    ).fetchone()
                    if (
                        auth is None
                        or auth["dispatch_id"] != scope.dispatch_id
                        or auth["policy_id"] != scope.policy_id
                        or auth["generation"] != scope.generation
                        or auth["canonical_url_sha256"] != policy["canonical_url_sha256"]
                        or auth["root_id"] != scope.root_id
                        or auth["request_hash"] != request_hash
                        or auth["expires_at"] <= _clock(conn, now)
                    ):
                        raise RegisteredSourceDenied("SUPPLEMENTAL_DENIED")
                    prior_id = auth["prior_attempt_id"]
                    if auth.get("course_refresh_authorization_id") is not None:
                        bound = conn.execute(
                            "SELECT canonical_original_attempt_id,latest_attempt_id "
                            "FROM rag_registered_course_refresh_authorizations WHERE id=%s",
                            (auth["course_refresh_authorization_id"],),
                        ).fetchone()
                        if bound is None or bound["latest_attempt_id"] != prior_id:
                            raise RegisteredSourceDenied("COURSE_REFRESH_DISPATCH_DENIED")
                        #498 serializes on canonical original, not its terminal
                        #successor used as the physical350 supplemental predecessor.
                        prior_id = bound["canonical_original_attempt_id"]
                    prior = conn.execute(
                        "SELECT state,supplemental_authorization_id,canonical_url_sha256 "
                        "FROM rag_registered_fetch_attempts WHERE id=%s FOR UPDATE",
                        (prior_id,),
                    ).fetchone()
                    auth = conn.execute(
                        "SELECT * FROM rag_registered_supplemental_authorizations "
                        "WHERE id=%s FOR SHARE",
                        (supplemental_authorization_id,),
                    ).fetchone()
                    revoked = conn.execute(
                        "SELECT 1 FROM rag_registered_supplemental_revocations "
                        "WHERE authorization_id=%s",
                        (supplemental_authorization_id,),
                    ).fetchone()
                    if (
                        prior is None
                        or auth is None
                        or revoked is not None
                        or auth["expires_at"] <= _clock(conn, now)
                        or _current(conn, scope, now) is None
                        or prior["state"] not in ("settled", "unknown")
                        or prior["supplemental_authorization_id"] is not None
                        or prior["canonical_url_sha256"] != policy["canonical_url_sha256"]
                    ):
                        raise RegisteredSourceDenied("SUPPLEMENTAL_DENIED")
                if scope.root_id.startswith(ACCESS_ROOT_PREFIX):
                    refresh = conn.execute(
                        "SELECT * FROM rag_registered_course_refresh_authorizations "
                        "WHERE root_id=%s FOR SHARE", (scope.root_id,),
                    ).fetchone()
                    if (refresh is None or refresh["dispatch_id"] != scope.dispatch_id
                            or refresh["supplemental_authorization_id"] != supplemental_authorization_id
                            or refresh["request_hash"] != request_hash
                            or refresh["operation_key"] != operation_key):
                        raise RegisteredSourceDenied("COURSE_REFRESH_DISPATCH_DENIED")
                    conn.execute(
                        "SELECT rag_registered_course_refresh_check(r,true) "
                        "FROM rag_registered_course_refresh_authorizations r WHERE id=%s",
                        (refresh["id"],),
                    )
                row = conn.execute(
                    "INSERT INTO rag_registered_fetch_attempts "
                    "(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,"
                    "supplemental_authorization_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
                    (
                        scope.dispatch_id,
                        scope.policy_id,
                        scope.generation,
                        policy["canonical_url_sha256"],
                        scope.root_id,
                        operation_key,
                        request_hash,
                        supplemental_authorization_id,
                    ),
                ).fetchone()
                if row is None:
                    raise RegisteredSourceDenied("ALREADY_DISPATCHED")
            with self._permit_lock:
                self._permits[scope.dispatch_id] = (scope, 2)
            return scope.dispatch_id
        except psycopg.Error as exc:
            raise RegisteredSourceDenied("DISPATCH_DENIED") from exc

    def correct_unused_supplemental(
        self,
        *,
        original_authorization_id: UUID,
        prior_attempt_id: UUID,
        replacement_authorization_id: UUID,
        scope: RegisteredSourceScope,
        request_hash: str,
        expires_at: datetime,
        approval_ref: str,
        now: datetime,
    ) -> UUID:
        """Operator-only, atomic unused-authority correction; never creates a policy/root.

        The caller must separately register and review an exact, current policy and
        root. Both revocation and replacement commit together. No network dispatch
        or permission is issued by this method.
        """
        if (
            type(original_authorization_id) is not UUID
            or type(prior_attempt_id) is not UUID
            or type(replacement_authorization_id) is not UUID
            or type(scope) is not RegisteredSourceScope
            or not isinstance(request_hash, str)
            or _HASH.fullmatch(request_hash) is None
            or not isinstance(approval_ref, str)
            or _APPROVAL.fullmatch(approval_ref) is None
            or not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None
            or expires_at.utcoffset() is None
        ):
            raise RegisteredSourceDenied("CORRECTION_DENIED")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                policy = _current(conn, scope, now, lock=True)
                if policy is None or expires_at <= _clock(conn, now):
                    raise RegisteredSourceDenied("CORRECTION_DENIED")
                prior = conn.execute(
                    "SELECT state,supplemental_authorization_id,canonical_url_sha256 "
                    "FROM rag_registered_fetch_attempts WHERE id=%s FOR UPDATE",
                    (prior_attempt_id,),
                ).fetchone()
                original = conn.execute(
                    "SELECT * FROM rag_registered_supplemental_authorizations "
                    "WHERE id=%s FOR SHARE", (original_authorization_id,),
                ).fetchone()
                if (
                    prior is None or prior["state"] not in ("unknown", "settled")
                    or _current(conn, scope, now) is None
                    or expires_at <= _clock(conn, now)
                    or prior["supplemental_authorization_id"] is not None
                    or prior["canonical_url_sha256"] != policy["canonical_url_sha256"]
                    or original is None
                    or original["prior_attempt_id"] != prior_attempt_id
                    or original["canonical_url_sha256"] != policy["canonical_url_sha256"]
                    or original["replaces_authorization_id"] is not None
                    or original.get("explicit_followup_id") is not None
                    or (original["policy_id"], original["generation"])
                        == (scope.policy_id, scope.generation)
                ):
                    raise RegisteredSourceDenied("CORRECTION_DENIED")
                target_attempt = conn.execute(
                    "SELECT 1 FROM rag_registered_fetch_attempts "
                    "WHERE policy_id=%s AND generation=%s AND canonical_url_sha256=%s",
                    (scope.policy_id, scope.generation, policy["canonical_url_sha256"]),
                ).fetchone()
                if target_attempt is not None:
                    raise RegisteredSourceDenied("CORRECTION_TARGET_SPENT")
                conn.execute(
                    "INSERT INTO rag_registered_supplemental_revocations "
                    "(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)",
                    (original_authorization_id, prior_attempt_id, approval_ref),
                )
                conn.execute(
                    "INSERT INTO rag_registered_supplemental_authorizations "
                    "(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,"
                    "request_hash,prior_attempt_id,expires_at,approval_ref,replaces_authorization_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        replacement_authorization_id, scope.dispatch_id,
                        scope.policy_id, scope.generation, policy["canonical_url_sha256"],
                        scope.root_id, request_hash, prior_attempt_id, expires_at,
                        approval_ref, original_authorization_id,
                    ),
                )
            return replacement_authorization_id
        except psycopg.Error as exc:
            raise RegisteredSourceDenied("CORRECTION_DENIED") from exc

    def authorize_final_followup(
        self,
        *,
        allowance_id: UUID,
        authorization_id: UUID,
        original_attempt_id: UUID,
        latest_attempt_id: UUID,
        scope: RegisteredSourceScope,
        request_hash: str,
        expires_at: datetime,
        approval_ref: str,
        now: datetime,
    ) -> UUID:
        """Explicit operator credit, never recovery of a spent dispatch.

        Generation 3 follows two terminal unknowns; a separately approved
        deployment correction at generation 4 requires all three terminal
        unknowns. Each needs a fresh policy/root and exact allowance. This
        method only records authority atomically; it never performs network I/O.
        """
        if (
            any(type(value) is not UUID for value in (
                allowance_id, authorization_id, original_attempt_id, latest_attempt_id,
            ))
            or type(scope) is not RegisteredSourceScope
            or scope.generation not in (3, 4)
            or not isinstance(request_hash, str)
            or _HASH.fullmatch(request_hash) is None
            or not isinstance(approval_ref, str)
            or _APPROVAL.fullmatch(approval_ref) is None
            or not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None or expires_at.utcoffset() is None
        ):
            raise RegisteredSourceDenied("FINAL_FOLLOWUP_DENIED")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                policy = _current(conn, scope, now, lock=True)
                if policy is None:
                    raise RegisteredSourceDenied("FINAL_FOLLOWUP_DENIED")
                conn.execute(
                    "SELECT id FROM rag_registered_fetch_attempts WHERE id=%s FOR UPDATE",
                    (original_attempt_id,),
                ).fetchone()
                if expires_at <= _clock(conn, now) or _current(conn, scope, now) is None:
                    raise RegisteredSourceDenied("FINAL_FOLLOWUP_DENIED")
                if conn.execute(
                    "SELECT 1 FROM rag_registered_fetch_attempts WHERE policy_id=%s "
                    "AND generation=%s AND canonical_url_sha256=%s",
                    (scope.policy_id, scope.generation, policy["canonical_url_sha256"]),
                ).fetchone() is not None:
                    raise RegisteredSourceDenied("FINAL_FOLLOWUP_TARGET_SPENT")
                conn.execute(
                    "INSERT INTO rag_registered_final_followup_allowances "
                    "(id,original_attempt_id,latest_attempt_id,authorization_id,dispatch_id,"
                    "policy_id,generation,canonical_url_sha256,root_id,request_hash,expires_at,approval_ref) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (allowance_id, original_attempt_id, latest_attempt_id, authorization_id,
                     scope.dispatch_id, scope.policy_id, scope.generation,
                     policy["canonical_url_sha256"], scope.root_id, request_hash, expires_at,
                     approval_ref),
                )
                conn.execute(
                    "INSERT INTO rag_registered_supplemental_authorizations "
                    "(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,"
                    "prior_attempt_id,expires_at,approval_ref,explicit_followup_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (authorization_id, scope.dispatch_id, scope.policy_id, scope.generation,
                     policy["canonical_url_sha256"], scope.root_id, request_hash,
                     original_attempt_id, expires_at, approval_ref, allowance_id),
                )
            return authorization_id
        except psycopg.Error as exc:
            raise RegisteredSourceDenied("FINAL_FOLLOWUP_DENIED") from exc

    def authorize_settled_second_fresh_once(
        self,
        *,
        allowance_id: UUID,
        authorization_id: UUID,
        original_attempt_id: UUID,
        latest_attempt_id: UUID,
        latest_capture_id: UUID,
        latest_capture_sha256: str,
        scope: RegisteredSourceScope,
        request_hash: str,
        expires_at: datetime,
        approval_ref: str,
        now: datetime,
    ) -> UUID:
        """One gen3 fresh GET authority after the second gen1 capture has expired.

        Both historical policies are gen1; second attempt does not mean gen2.

        Schema 484 checks the complete immutable history at allowance, auth and
        dispatch insertion. This is not the unknown-chain final-followup issuer.
        The caller supplies independently registered fresh policy/root identities;
        this short transaction creates neither a network permit nor a dispatch.
        """
        if (
            any(type(value) is not UUID for value in (
                allowance_id, authorization_id, original_attempt_id,
                latest_attempt_id, latest_capture_id,
            ))
            or type(scope) is not RegisteredSourceScope
            or scope.generation != 3
            or scope.url != "https://docs.python.org/3/builtins/functions.html"
            or scope.subject_id != "route.python"
            or scope.subject_version != "1.0"
            or scope.facets != ("fundamentals",)
            or len({allowance_id, authorization_id, original_attempt_id,
                    latest_attempt_id, latest_capture_id, scope.dispatch_id}) != 6
            or not isinstance(latest_capture_sha256, str)
            or _HASH.fullmatch(latest_capture_sha256) is None
            or not isinstance(request_hash, str)
            or _HASH.fullmatch(request_hash) is None
            or not isinstance(approval_ref, str)
            or _APPROVAL.fullmatch(approval_ref) is None
            or not approval_ref.startswith("standingpolicy.settledsecondfreshness.")
            or not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None or expires_at.utcoffset() is None
            or not isinstance(now, datetime)
            or now.tzinfo is None or now.utcoffset() is None
        ):
            raise RegisteredSourceDenied("SETTLED_SECOND_FRESH_DENIED")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                # Same original-row serialization point as all three SQL guards.
                original = conn.execute(
                    "SELECT id FROM rag_registered_fetch_attempts WHERE id=%s FOR UPDATE",
                    (original_attempt_id,),
                ).fetchone()
                policy = _current(conn, scope, now, lock=True)
                db_now = _clock(conn, now)
                if (original is None or policy is None or expires_at <= db_now
                        or expires_at > db_now + timedelta(hours=24)):
                    raise RegisteredSourceDenied("SETTLED_SECOND_FRESH_DENIED")
                conn.execute(
                    "INSERT INTO rag_registered_final_followup_allowances "
                    "(id,original_attempt_id,latest_attempt_id,authorization_id,dispatch_id,"
                    "policy_id,generation,canonical_url_sha256,root_id,request_hash,expires_at,"
                    "approval_ref,settled_second_capture_id,settled_second_capture_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s,3,%s,%s,%s,%s,%s,%s,%s)",
                    (allowance_id, original_attempt_id, latest_attempt_id, authorization_id,
                     scope.dispatch_id, scope.policy_id, policy["canonical_url_sha256"],
                     scope.root_id, request_hash, expires_at, approval_ref,
                     latest_capture_id, latest_capture_sha256),
                )
                conn.execute(
                    "INSERT INTO rag_registered_supplemental_authorizations "
                    "(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,"
                    "prior_attempt_id,expires_at,approval_ref,explicit_followup_id) "
                    "VALUES (%s,%s,%s,3,%s,%s,%s,%s,%s,%s,%s)",
                    (authorization_id, scope.dispatch_id, scope.policy_id,
                     policy["canonical_url_sha256"], scope.root_id, request_hash,
                     original_attempt_id, expires_at, approval_ref, allowance_id),
                )
            return authorization_id
        except psycopg.Error as exc:
            raise RegisteredSourceDenied("SETTLED_SECOND_FRESH_DENIED") from exc

    def authorize_settled_source_correction_once(
        self,
        *,
        allowance_id: UUID,
        authorization_id: UUID,
        original_attempt_id: UUID,
        original_capture_id: UUID,
        original_capture_sha256: str,
        latest_attempt_id: UUID,
        latest_authorization_id: UUID,
        scope: RegisteredSourceScope,
        request_hash: str,
        expires_at: datetime,
        approval_ref: str,
        now: datetime,
    ) -> UUID:
        """One SQL gen3 correction after the ordinary supplemental's PID failure.

        The second actual attempt used a separate generation-one policy. Its
        source_handle, not the expired original's handle, is the target identity.
        No diagnostic hash/Boolean is accepted as authority; schema 484 checks
        the exact persisted original capture and terminal failed authorization.
        This issuer commits only allowance/auth, never a network permit or GET.
        """
        if (
            any(type(value) is not UUID for value in (
                allowance_id, authorization_id, original_attempt_id,
                original_capture_id, latest_attempt_id, latest_authorization_id,
            ))
            or type(scope) is not RegisteredSourceScope
            or scope.generation != 3
            or scope.url != "https://www.sqlite.org/lang_select.html"
            or scope.subject_id != "route.sql"
            or scope.subject_version != "1.0"
            or scope.facets != ("queries",)
            or len({allowance_id, authorization_id, original_attempt_id,
                    original_capture_id, latest_attempt_id, latest_authorization_id,
                    scope.dispatch_id}) != 7
            or not isinstance(original_capture_sha256, str)
            or _HASH.fullmatch(original_capture_sha256) is None
            or not isinstance(request_hash, str)
            or _HASH.fullmatch(request_hash) is None
            or not isinstance(approval_ref, str)
            or _APPROVAL.fullmatch(approval_ref) is None
            or not approval_ref.startswith("standingpolicy.settledsourcecorrection.")
            or not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None or expires_at.utcoffset() is None
            or not isinstance(now, datetime)
            or now.tzinfo is None or now.utcoffset() is None
        ):
            raise RegisteredSourceDenied("SETTLED_SOURCE_CORRECTION_DENIED")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                original = conn.execute(
                    "SELECT id FROM rag_registered_fetch_attempts WHERE id=%s FOR UPDATE",
                    (original_attempt_id,),
                ).fetchone()
                policy = _current(conn, scope, now, lock=True)
                db_now = _clock(conn, now)
                if (original is None or policy is None or expires_at <= db_now
                        or expires_at > db_now + timedelta(hours=24)):
                    raise RegisteredSourceDenied("SETTLED_SOURCE_CORRECTION_DENIED")
                conn.execute(
                    "INSERT INTO rag_registered_final_followup_allowances "
                    "(id,original_attempt_id,latest_attempt_id,authorization_id,dispatch_id,"
                    "policy_id,generation,canonical_url_sha256,root_id,request_hash,expires_at,"
                    "approval_ref,settled_source_capture_id,settled_source_capture_sha256,"
                    "settled_source_failed_authorization_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,3,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (allowance_id, original_attempt_id, latest_attempt_id, authorization_id,
                     scope.dispatch_id, scope.policy_id, policy["canonical_url_sha256"],
                     scope.root_id, request_hash, expires_at, approval_ref,
                     original_capture_id, original_capture_sha256, latest_authorization_id),
                )
                conn.execute(
                    "INSERT INTO rag_registered_supplemental_authorizations "
                    "(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,"
                    "prior_attempt_id,expires_at,approval_ref,explicit_followup_id) "
                    "VALUES (%s,%s,%s,3,%s,%s,%s,%s,%s,%s,%s)",
                    (authorization_id, scope.dispatch_id, scope.policy_id,
                     policy["canonical_url_sha256"], scope.root_id, request_hash,
                     original_attempt_id, expires_at, approval_ref, allowance_id),
                )
            return authorization_id
        except psycopg.Error as exc:
            raise RegisteredSourceDenied("SETTLED_SOURCE_CORRECTION_DENIED") from exc

    def settle_capture(
        self,
        scope: RegisteredSourceScope,
        *,
        fetcher: SafeFetcher,
        result: FetchResult,
        now: datetime,
    ) -> UUID:
        """Fail closed until the cross-process signed-fetch receipt is defined.

        SafeFetcher's in-process object token cannot cross the approved isolated
        egress namespace. A test double, matching body hash, or a structural
        live_ready check cannot establish dispatch-bound transport provenance.
        No attempt/capture row is mutated by this method.
        """
        raise RegisteredSourceDenied("LIVE_BRIDGE_REQUIRED")

    def mark_unknown(
        self, scope: RegisteredSourceScope, *, error_code: str, now: datetime
    ) -> bool:
        """Terminal reconciliation; never reopens a dispatched/unknown attempt."""
        if (
            type(scope) is not RegisteredSourceScope
            or not isinstance(error_code, str)
            or _ERROR.fullmatch(error_code) is None
        ):
            raise RegisteredSourceDenied("UNKNOWN_DENIED")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                _clock(conn, now)
                row = conn.execute(
                    "UPDATE rag_registered_fetch_attempts SET state='unknown',error_code=%s "
                    "WHERE id=%s AND policy_id=%s AND generation=%s AND root_id=%s "
                    "AND state='dispatched' RETURNING id",
                    (
                        error_code,
                        scope.dispatch_id,
                        scope.policy_id,
                        scope.generation,
                        scope.root_id,
                    ),
                ).fetchone()
            if row is not None:
                with self._permit_lock:
                    self._permits.pop(scope.dispatch_id, None)
            return row is not None
        except psycopg.Error as exc:
            raise RegisteredSourceDenied("UNKNOWN_DENIED") from exc
