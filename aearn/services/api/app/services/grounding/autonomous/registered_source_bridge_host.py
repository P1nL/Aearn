"""Trusted control callbacks for the default-off registered-source Unix bridge.

The B attestor signs pre-dial isolation only. The reviewed worker image and
peer-authenticated Unix transport are the separate response-report trust boundary.
No network or worker-side database access occurs in this module.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, cast
from uuid import UUID

import psycopg
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .registered_source_policy import RegisteredSourceHopGrant, RegisteredSourceScope
from .registered_source_repository import PostgresRegisteredSourceRepository, _clock, _current

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SIG = re.compile(r"[0-9a-f]{128}\Z")
_SCOPE_FIELDS = frozenset(
    {
        "policy_id",
        "generation",
        "source_handle",
        "subject_id",
        "subject_version",
        "facets",
        "url",
        "host",
        "path",
        "root_id",
        "dispatch_id",
        "max_bytes",
    }
)
_REPORT_FIELDS = frozenset(
    {
        "v",
        "policy_id",
        "generation",
        "root_id",
        "dispatch_id",
        "request_hash",
        "url",
        "host",
        "ip",
        "nonce",
        "status",
        "redirects",
        "tls_verified",
        "peer_verified",
        "capture_kind",
        "content_type",
        "body_sha256",
        "body_bytes",
        "wire_bytes",
        "pre_dial_unix_ms",
        "reported_unix_ms",
    }
)
_EGRESS_FIELDS = frozenset(
    {
        "deployment_id",
        "host",
        "ip",
        "namespace_inode",
        "nonce",
        "policy_sha256",
        "expires_unix",
        "isolation_verified",
    }
)
_CONTENT_TYPES = frozenset(("text/html", "text/plain", "text/markdown"))

OWNED_B1D_DATABASE = "aearn_b1d_sandbox_20261001"
OWNED_B1D_TARGETS = frozenset({
    ("https://docs.python.org/3/library/functions.html", "docs.python.org", "/3/library/functions.html", "route.python", ("fundamentals",)),
    ("https://docs.python.org/3/builtins/functions.html", "docs.python.org", "/3/builtins/functions.html", "route.python", ("fundamentals",)),
    ("https://www.sqlite.org/lang_select.html", "www.sqlite.org", "/lang_select.html", "route.sql", ("queries",)),
})
OWNED_COURSE_TARGETS = frozenset({
    ("https://docs.python.org/3/reference/simple_stmts.html", "docs.python.org", "/3/reference/simple_stmts.html", "route.python", ("fundamentals",)),
    ("https://www.sqlite.org/lang_expr.html", "www.sqlite.org", "/lang_expr.html", "route.sql", ("queries",)),
    ("https://www.sqlite.org/lang_corefunc.html", "www.sqlite.org", "/lang_corefunc.html", "route.sql", ("queries",)),
    ("https://en.wikibooks.org/wiki/Python_Programming/Variables_and_Strings", "en.wikibooks.org", "/wiki/Python_Programming/Variables_and_Strings", "route.python", ("fundamentals",)),
    ("https://learnxinyminutes.com/python/", "learnxinyminutes.com", "/python/", "route.python", ("fundamentals",)),
})


def transport_database_allowed(database: object, *, owned_b1d_assessment: bool = False,
                               owned_b1d_course_sources: bool = False) -> bool:
    """An explicit owned assessment lane never broadens the legacy C DB fence."""
    if (type(owned_b1d_assessment) is not bool or type(owned_b1d_course_sources) is not bool
            or owned_b1d_assessment and owned_b1d_course_sources or type(database) is not str):
        return False
    if owned_b1d_assessment or owned_b1d_course_sources:
        return database == OWNED_B1D_DATABASE
    return re.fullmatch(r"aearn_rag260_c_[a-zA-Z0-9_]+", database) is not None


def owned_b1d_scope_allowed(scope: RegisteredSourceScope) -> bool:
    return (type(scope) is RegisteredSourceScope
            and (scope.url, scope.host, scope.path, scope.subject_id, scope.facets) in OWNED_B1D_TARGETS
            and 0 < scope.max_bytes <= 8 * 1024 * 1024)


def owned_course_scope_allowed(scope: RegisteredSourceScope) -> bool:
    """Finite course capture lane, never an assessment/main-teaching grant."""
    return (type(scope) is RegisteredSourceScope
            and (scope.url, scope.host, scope.path, scope.subject_id, scope.facets) in OWNED_COURSE_TARGETS
            and 0 < scope.max_bytes <= 8 * 1024 * 1024)


def owned_course_policy_allowed(policy: dict[str, Any]) -> bool:
    url = policy.get("canonical_url")
    if url not in {target[0] for target in OWNED_COURSE_TARGETS}:
        return False
    usages = policy.get("allowed_usages")
    if (type(usages) not in (list, tuple) or not usages or any(type(value) is not str for value in usages)
            or len(set(usages)) != len(usages)):
        return False
    if url == "https://en.wikibooks.org/wiki/Python_Programming/Variables_and_Strings":
        return policy.get("origin") == "community" and tuple(usages) == ("main_teaching",)
    if url == "https://learnxinyminutes.com/python/":
        return policy.get("origin") == "tutorial" and tuple(usages) == ("main_teaching",)
    return policy.get("origin") == "official" and set(usages) <= {"assessment_evidence", "main_teaching"}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _registered_scope(scope: object) -> RegisteredSourceScope | None:
    """Exact wire-to-domain value mapping; a wire scope is never a grant."""
    try:
        values = vars(scope)
        if type(values) is not dict or values.keys() != _SCOPE_FIELDS:
            return None
        dispatch = values["dispatch_id"]
        if type(dispatch) is not str or str(UUID(dispatch)) != dispatch:
            return None
        if type(values["facets"]) is not tuple:
            return None
        return RegisteredSourceScope(**{**values, "dispatch_id": UUID(dispatch)})
    except (TypeError, ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class VerifiedProof:
    """Signed pre-dial fact plus a separate, explicitly worker-reported result."""

    egress_receipt: dict[str, object]
    worker_fetch_report: dict[str, object]


class SignedDispatchProofVerifier:
    """Verify B's signer independently, then constrain the worker's report.

    Only the pre-dial namespace/firewall fact is cryptographically attested.
    The reviewed, pinned worker image and concrete SafeFetcher are trusted for
    TLS/peer/body reporting through SO_PEERCRED Unix transport. The report is
    NOT a signed or independent HTTPS attestation. The store additionally needs
    an authenticated server-side peer socket; this method alone grants nothing.
    """

    def __init__(
        self,
        *,
        public_key: bytes,
        deployment_id: str,
        policy_sha256: str,
        namespace_inode: int,
        allowed_ips: frozenset[str],
    ) -> None:
        if (
            type(public_key) is not bytes
            or len(public_key) != 32
            or type(deployment_id) is not str
            or re.fullmatch(r"[a-z][a-z0-9._:-]{2,159}", deployment_id) is None
            or type(policy_sha256) is not str
            or _HASH.fullmatch(policy_sha256) is None
            or type(namespace_inode) is not int
            or namespace_inode <= 0
            or type(allowed_ips) is not frozenset
            or not 1 <= len(allowed_ips) <= 16
        ):
            raise ValueError("ATTESTOR_CONFIG_DENIED")
        try:
            if any(
                type(ip) is not str
                or str(ipaddress.IPv4Address(ip)) != ip
                or not ipaddress.IPv4Address(ip).is_global
                for ip in allowed_ips
            ):
                raise ValueError("ATTESTOR_CONFIG_DENIED")
        except ipaddress.AddressValueError as exc:
            raise ValueError("ATTESTOR_CONFIG_DENIED") from exc
        self._namespace_inode = namespace_inode
        self._allowed_ips = allowed_ips
        self._key = Ed25519PublicKey.from_public_bytes(public_key)
        self._key_sha256 = hashlib.sha256(public_key).hexdigest()
        self._deployment_id = deployment_id
        self._policy_sha256 = policy_sha256

    def verify(
        self, scope: object, proof: object, *, now: datetime | None = None
    ) -> VerifiedProof | None:
        expected = _registered_scope(scope)
        if expected is None:
            return None
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            return None
        try:
            if (
                type(proof) is not dict
                or set(proof) != {"egress", "worker_fetch_report"}
                or len(_canonical(proof)) > 2048
            ):
                return None
            envelope = proof["egress"]
            report = proof["worker_fetch_report"]
            if (
                type(envelope) is not dict
                or set(envelope) != {"receipt", "signature"}
                or type(report) is not dict
                or report.keys() != _REPORT_FIELDS
            ):
                return None
            receipt, signature = envelope["receipt"], envelope["signature"]
            if (
                type(receipt) is not dict
                or receipt.keys() != _EGRESS_FIELDS
                or type(signature) is not str
                or _SIG.fullmatch(signature) is None
            ):
                return None
            self._key.verify(bytes.fromhex(signature), _canonical(receipt))
            ip = receipt["ip"]
            nonce = receipt["nonce"]
            expiry = receipt["expires_unix"]
            if (
                receipt["deployment_id"] != self._deployment_id
                or receipt["host"] != expected.host
                or type(ip) is not str
                or ip not in self._allowed_ips
                or type(receipt["namespace_inode"]) is not int
                or receipt["namespace_inode"] != self._namespace_inode
                or receipt["policy_sha256"] != self._policy_sha256
                or type(nonce) is not str
                or re.fullmatch(r"[0-9a-f]{48}", nonce) is None
                or type(expiry) is not int
                or receipt["isolation_verified"] is not True
            ):
                return None
            # Everything below is an attributed worker report, not attestor fact.
            pre_dial = report["pre_dial_unix_ms"]
            reported = report["reported_unix_ms"]
            now_ms = current.timestamp() * 1000
            if (
                type(report["v"]) is not int
                or report["v"] != 1
                or report["policy_id"] != expected.policy_id
                or type(report["generation"]) is not int
                or report["generation"] != expected.generation
                or report["root_id"] != expected.root_id
                or report["dispatch_id"] != str(expected.dispatch_id)
                or type(report["request_hash"]) is not str
                or _HASH.fullmatch(report["request_hash"]) is None
                or report["url"] != expected.url
                or report["host"] != expected.host
                or report["ip"] != ip
                or report["nonce"] != nonce
                or type(report["status"]) is not int
                or report["status"] != 200
                or type(report["redirects"]) is not int
                or report["redirects"] != 0
                or report["tls_verified"] is not True
                or report["peer_verified"] is not True
                or report["capture_kind"] != "full"
                or type(report["content_type"]) is not str
                or report["content_type"] not in _CONTENT_TYPES
                or type(report["body_sha256"]) is not str
                or _HASH.fullmatch(report["body_sha256"]) is None
                or type(report["body_bytes"]) is not int
                or not 0 < report["body_bytes"] <= expected.max_bytes
                or type(report["wire_bytes"]) is not int
                or not 0 < report["wire_bytes"] <= expected.max_bytes
                or type(pre_dial) is not int
                or type(reported) is not int
                or not (cast(int, expiry) - 4) * 1000 <= pre_dial
                or not pre_dial < cast(int, expiry) * 1000
                or not pre_dial <= reported
                or not now_ms - 60_000 <= reported <= now_ms + 5_000
            ):
                return None
            return VerifiedProof(receipt, report)
        except (KeyError, ValueError, TypeError, OverflowError, InvalidSignature):
            return None


@dataclass(frozen=True)
class HostCallbacks:
    resolver: Callable[[object, datetime], object | None]
    proof_verifier: Callable[[object, object], bool]
    capture_store: Callable[..., object | None]


def make_host_callbacks(
    *,
    dsn: str,
    verifier: SignedDispatchProofVerifier,
    decision_type: type[Any],
    capture_record_type: type[Any],
    worker_uid: int,
    worker_gid: int,
    dispatch_owner: PostgresRegisteredSourceRepository,
    worker_image_sha256: str,
    owned_b1d_assessment: bool = False,
    owned_b1d_course_sources: bool = False,
) -> HostCallbacks:
    """Pass infra server.Decision/CaptureRecord; only an explicit C DB is accepted.

    No default key, DB or signer. The bridge supplies its authenticated Unix
    peer socket as the seventh store argument. The mandatory dispatch owner is
    the *same process instance* that committed the one-shot attempt; its two
    permits cover pre-DNS/pre-dial grants and cannot be recreated on restart.
    The grant_nonce guard is separate from the durable dispatch fence.
    """
    try:
        database = psycopg.conninfo.conninfo_to_dict(dsn).get("dbname")
    except (TypeError, ValueError, psycopg.Error) as exc:
        raise ValueError("BRIDGE_CONFIG_DENIED") from exc
    if (
        not transport_database_allowed(database, owned_b1d_assessment=owned_b1d_assessment,
                                       owned_b1d_course_sources=owned_b1d_course_sources)
        or type(verifier) is not SignedDispatchProofVerifier
        or not callable(decision_type)
        or not callable(capture_record_type)
        or type(worker_uid) is not int
        or worker_uid <= 0
        or type(worker_gid) is not int
        or worker_gid <= 0
        or type(dispatch_owner) is not PostgresRegisteredSourceRepository
        or dispatch_owner._dsn != dsn
        or type(worker_image_sha256) is not str
        or _HASH.fullmatch(worker_image_sha256) is None
    ):
        raise ValueError("BRIDGE_CONFIG_DENIED")

    def authenticated_peer(conn: socket.socket | None) -> bool:
        """Only a live Unix peer credential can authorize a worker report.

        The bridge must pass the accepted connection into capture_store; its
        six-argument legacy callback fails closed. No boolean or report field
        can stand in for SO_PEERCRED and the pinned worker image review.
        """
        if (
            type(conn) is not socket.socket
            or conn.family != getattr(socket, "AF_UNIX", None)
            or not hasattr(socket, "SO_PEERCRED")
        ):
            return False
        try:
            pid, uid, gid = struct.unpack(
                "3i",
                conn.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                ),
            )
            return pid >= 0 and uid == worker_uid and gid == worker_gid
        except (OSError, struct.error):
            return False

    def db_matches(conn: psycopg.Connection[dict[str, Any]]) -> bool:
        row = conn.execute("SELECT current_database() AS name").fetchone()
        return row is not None and row["name"] == database

    def assessment_policy_allowed(policy: dict[str, Any] | None) -> bool:
        if policy is None:
            return False
        if owned_b1d_course_sources:
            return owned_course_policy_allowed(policy)
        if not owned_b1d_assessment:
            return True
        return (policy.get("origin") == "official"
                and type(policy.get("allowed_usages")) in (list, tuple)
                and tuple(policy["allowed_usages"]) == ("assessment_evidence",))

    def resolver(scope: object, now: datetime) -> object | None:
        checked = _registered_scope(scope)
        if (
            checked is None
            or (owned_b1d_assessment and not owned_b1d_scope_allowed(checked))
            or (owned_b1d_course_sources and not owned_course_scope_allowed(checked))
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            return None
        try:
            # Only the process that committed the first dispatch retains these
            # two pre-DNS/pre-dial permits. A restart cannot re-arm a GET.
            permit = dispatch_owner.resolve(checked, now=now)
            if (type(permit) is not RegisteredSourceHopGrant
                    or permit.scope != checked or permit.allowed is not True):
                return None
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                if not db_matches(conn):
                    return None
                policy = _current(conn, checked, now, lock=True)
                if policy is None or not assessment_policy_allowed(policy):
                    return None
                attempt = conn.execute(
                    "SELECT id,state,root_id,request_hash FROM rag_registered_fetch_attempts "
                    "WHERE id=%s AND policy_id=%s AND generation=%s AND canonical_url_sha256=%s FOR SHARE",
                    (
                        checked.dispatch_id,
                        checked.policy_id,
                        checked.generation,
                        policy["canonical_url_sha256"],
                    ),
                ).fetchone()
                if (
                    attempt is None
                    or attempt["id"] != checked.dispatch_id
                    or attempt["root_id"] != checked.root_id
                    or attempt["state"] != "dispatched"
                    or not attempt["request_hash"]
                ):
                    return None
                # Recheck expiry/root after waiting on the attempt lock.
                if not assessment_policy_allowed(_current(conn, checked, now, lock=True)):
                    return None
                return decision_type(
                    checked.max_bytes,
                    min(policy["retention_until"], policy["expires_at"]),
                )
        except (psycopg.Error, ValueError, TypeError, KeyError):
            return None

    def proof_verifier(scope: object, proof: object) -> bool:
        if owned_b1d_assessment or owned_b1d_course_sources:
            checked = _registered_scope(scope)
            if (checked is None or owned_b1d_assessment and not owned_b1d_scope_allowed(checked)
                    or owned_b1d_course_sources and not owned_course_scope_allowed(checked)):
                return False
        return verifier.verify(scope, proof) is not None

    def capture_store(
        scope: object,
        body: bytes,
        content_type: str,
        sha256: str,
        proof: object,
        now: datetime,
        peer_socket: socket.socket | None = None,
    ) -> object | None:
        if not authenticated_peer(peer_socket):
            return None
        checked = _registered_scope(scope)
        if (
            checked is None
            or (owned_b1d_assessment and not owned_b1d_scope_allowed(checked))
            or (owned_b1d_course_sources and not owned_course_scope_allowed(checked))
            or type(body) is not bytes
            or not 0 < len(body) <= checked.max_bytes
            or type(content_type) is not str
            or content_type not in _CONTENT_TYPES
            or type(sha256) is not str
            or _HASH.fullmatch(sha256) is None
            or hashlib.sha256(body).hexdigest() != sha256
        ):
            return None
        verified = verifier.verify(scope, proof, now=now)
        if verified is None:
            return None
        receipt = verified.worker_fetch_report
        if (
            receipt["body_sha256"] != sha256
            or receipt["body_bytes"] != len(body)
            or receipt["content_type"] != content_type
        ):
            return None
        try:
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                if not db_matches(conn):
                    return None
                policy = _current(conn, checked, now, lock=True)
                if policy is None or not assessment_policy_allowed(policy):
                    return None
                attempt = conn.execute(
                    "SELECT id,state,root_id,request_hash,dispatched_at "
                    "FROM rag_registered_fetch_attempts WHERE id=%s AND policy_id=%s "
                    "AND generation=%s AND canonical_url_sha256=%s FOR UPDATE",
                    (
                        checked.dispatch_id,
                        checked.policy_id,
                        checked.generation,
                        policy["canonical_url_sha256"],
                    ),
                ).fetchone()
                db_now = _clock(conn, now)
                # Re-read current policy/root against the post-lock DB clock.
                if not assessment_policy_allowed(_current(conn, checked, now, lock=True)):
                    return None
                if (
                    attempt is None
                    or attempt["id"] != checked.dispatch_id
                    or attempt["state"] != "dispatched"
                    or attempt["root_id"] != checked.root_id
                    or attempt["request_hash"] != receipt["request_hash"]
                    or attempt["dispatched_at"].timestamp() * 1000
                    > cast(int, receipt["pre_dial_unix_ms"])
                    or verifier.verify(scope, proof, now=db_now) is None
                ):
                    return None
                settled = conn.execute(
                    "UPDATE rag_registered_fetch_attempts SET state='settled', "
                    "response_sha256=%s,response_bytes=%s,settled_at=%s "
                    "WHERE id=%s AND state='dispatched' RETURNING id",
                    (sha256, len(body), db_now, checked.dispatch_id),
                ).fetchone()
                if settled is None:
                    return None
                capture = conn.execute(
                    "INSERT INTO rag_registered_source_captures "
                    "(fetch_attempt_id,policy_id,generation,request_chain,final_url,"
                    "content_type,fetched_sha256,captured_bytes,captured_body,license_id,"
                    "retention_until,transport_proof,transport_proof_sha256,attestor_key_sha256,"
                    "worker_image_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (
                        checked.dispatch_id,
                        checked.policy_id,
                        checked.generation,
                        Jsonb([checked.url]),
                        checked.url,
                        content_type,
                        sha256,
                        len(body),
                        body,
                        policy["license_id"],
                        policy["retention_until"],
                        _canonical(proof),
                        hashlib.sha256(_canonical(proof)).hexdigest(),
                        verifier._key_sha256,
                        worker_image_sha256,
                    ),
                ).fetchone()
                if capture is None:
                    raise ValueError("CAPTURE_DENIED")  # roll back settlement
                capture_id = capture["id"]
            return capture_record_type(str(capture_id))
        except (psycopg.Error, ValueError, TypeError, KeyError, AttributeError):
            return None

    return HostCallbacks(resolver, proof_verifier, capture_store)
