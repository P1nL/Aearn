"""Operator-owned, default-deny B2 discovery and retention policy resolver.

This is a second, independent authority after A's actor/demand/budget check.
The exact host/path rule is re-read for every probe and staging commit. Use the
same connection/transaction for the commit recheck; release the short read
transaction before network I/O. No policy row is seeded by bootstrap.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from psycopg import Connection

from .access_policy import (
    AccessRequest, AuthorityResolver, AutonomousGates, check_candidate_access,
)
from .budget import require_transaction
from .contracts import HANDLE, SourceCandidate, revalidate
from .retention import StorageGrant
from .safe_fetch import SafeFetchDenied, _validated_url

_SAFE_PATH = re.compile(r"/[A-Za-z0-9._~/-]*\Z")
_CAPTURE_RANK = {"none": 0, "prefix": 1, "full": 2}


@dataclass(frozen=True)
class DiscoveryAccessDecision:
    allowed: bool
    reason: str


def _target(url: str) -> tuple[str, str]:
    canonical, host = _validated_url(url)
    path = urlsplit(canonical).path
    # Encoded separators/dot segments and normalization ambiguity cannot borrow
    # an operator grant. No query, fragment, userinfo or non-443 port is allowed.
    if (not _SAFE_PATH.fullmatch(path) or "//" in path
            or any(segment in {".", ".."} for segment in path.split("/"))):
        raise SafeFetchDenied("POLICY_URL_DENIED")
    return host, path


def _path_matches(path: str, prefix: str) -> bool:
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")


class PostgresCandidatePolicyResolver:
    """Read-only policy port and shared-revocation port; operator writes SQL.

    Probe authority and storage permission are separate. A public URL or a
    SourcePreference never grants either. A narrower denied/revoked rule
    shadows a broader allowed one rather than falling back to it.
    """

    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def _db_now(self) -> datetime:
        row = self.conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
        if row is None:
            raise ValueError("POLICY_CLOCK_UNAVAILABLE")
        return row["db_now"]

    def _rule(self, *, policy_id: str, generation: int,
              url: str) -> tuple[dict[str, Any], datetime] | None:
        host, path = _target(url)
        require_transaction(self.conn)
        policy = self.conn.execute(
            "SELECT current_generation,enabled,expires_at,revoked_at,clock_timestamp() AS db_now "
            "FROM rag_candidate_access_policies WHERE policy_id=%s FOR SHARE",
            (policy_id,),
        ).fetchone()
        if (policy is None or policy["current_generation"] != generation
                or not policy["enabled"] or policy["revoked_at"] is not None
                or policy["expires_at"] <= policy["db_now"]):
            return None
        rows = self.conn.execute(
            "SELECT path_prefix,probe_allowed,store_allowed,allowed_capture,"
            "max_captured_bytes,license_id,valid_until,retention_until,revoked_at "
            "FROM rag_candidate_access_rules WHERE policy_id=%s AND generation=%s "
            "AND host=%s FOR SHARE",
            (policy_id, generation, host),
        ).fetchall()
        matching = [row for row in rows if _path_matches(path, row["path_prefix"])]
        if not matching:
            return None
        rule = max(matching, key=lambda row: len(row["path_prefix"]))
        # Both DB time and caller's explicit time are checked at the boundary.
        return rule, min(policy["expires_at"], rule["valid_until"])

    def _effective(self, *, policy_id: str, generation: int,
                   url: str, now: datetime) -> tuple[dict[str, Any], datetime] | None:
        if now.tzinfo is None:
            return None
        found = self._rule(policy_id=policy_id, generation=generation, url=url)
        if found is None:
            return None
        rule, expires = found
        # DB clock is authoritative for expiry even if a caller supplies old time.
        db_now = self._db_now()
        if rule["revoked_at"] is not None or expires <= max(now, db_now):
            return None
        return rule, expires

    def check_probe(self, candidate: SourceCandidate, request: AccessRequest, *,
                    gates: AutonomousGates | None, authority_resolver: AuthorityResolver | None,
                    now: datetime) -> DiscoveryAccessDecision:
        """Check before probe and each redirect target using a new URL candidate.

        SafeFetcher invokes this through CandidateHopPolicy when composed;
        an initial URL check alone never authorizes redirect targets.
        """
        access = check_candidate_access(candidate, request, gates=gates,
                                        resolver=authority_resolver, now=now)
        if not access.allowed:
            return DiscoveryAccessDecision(False, access.reason)
        try:
            item = revalidate(candidate, SourceCandidate)
            req = revalidate(request, AccessRequest)
            if req.action != "probe":
                return DiscoveryAccessDecision(False, "PROBE_ACTION_DENIED")
            found = self._effective(policy_id=req.policy_id,
                                    generation=req.policy_generation, url=item.url, now=now)
            if found is None or not found[0]["probe_allowed"]:
                return DiscoveryAccessDecision(False, "DISCOVERY_POLICY_DENIED")
            return DiscoveryAccessDecision(True, "PROBE_AUTHORIZED")
        except Exception:
            return DiscoveryAccessDecision(False, "DISCOVERY_POLICY_DENIED")

    def resolve(self, candidate: SourceCandidate, request: AccessRequest) -> StorageGrant | None:
        """StorageGrantResolver port; check_storage performs A authority first.

        This cannot be used alone as actor authority. Only explicit operator
        store permission plus a license produces a grant (including hash-only).
        """
        try:
            item = revalidate(candidate, SourceCandidate)
            req = revalidate(request, AccessRequest)
            if (req.action != "store" or req.scope != item.scope
                    or req.demand_hash != item.demand_hash):
                return None
            found = self._effective(policy_id=req.policy_id,
                                    generation=req.policy_generation, url=item.url,
                                    now=self._db_now())
            if found is None:
                return None
            rule, expires = found
            if (not rule["probe_allowed"] or not rule["store_allowed"]
                    or not rule["license_id"] or rule["retention_until"] <=
                    self._db_now()):
                return None
            return StorageGrant(
                demand_hash=item.demand_hash, scope=item.scope,
                discovery_receipt_id=item.discovery_receipt_id,
                candidate_url_sha256=hashlib.sha256(item.url.encode("utf-8")).hexdigest(),
                policy_id=req.policy_id, policy_generation=req.policy_generation,
                allowed_capture=rule["allowed_capture"],
                max_captured_bytes=rule["max_captured_bytes"],
                license_id=rule["license_id"],
                retention_until=min(expires, rule["retention_until"]), revoked=False,
            )
        except Exception:
            return None

    def globally_revoked(self, candidate_id: UUID, policy_id: str,
                         policy_generation: int) -> bool:
        """SharedRevocationResolver port for CandidateStagingRepository.clear_revoked.

        True also covers expired/narrowed permission or a missing policy, never
        a single actor's withdrawn private reference. Call inside the capture
        row's lock/transaction so a successful scrub cannot race a policy edit.
        """
        if (not isinstance(candidate_id, UUID) or not isinstance(policy_id, str)
                or re.fullmatch(HANDLE, policy_id) is None
                or type(policy_generation) is not int or policy_generation < 1):
            raise ValueError("REVOCATION_SCOPE_INVALID")
        require_transaction(self.conn)
        row = self.conn.execute(
            "SELECT c.canonical_url,x.capture_kind,x.captured_bytes,x.retention_until,x.license_id "
            "FROM rag_discovery_candidates c JOIN rag_candidate_captures x "
            "ON x.candidate_id=c.id WHERE c.id=%s AND x.policy_id=%s "
            "AND x.policy_generation=%s",
            (candidate_id, policy_id, policy_generation),
        ).fetchone()
        if row is None:
            raise ValueError("REVOCATION_SCOPE_MISSING")
        now = self._db_now()
        try:
            found = self._effective(policy_id=policy_id, generation=policy_generation,
                                    url=row["canonical_url"], now=now)
        except Exception as exc:
            raise ValueError("REVOCATION_UNVERIFIED") from exc
        if found is None:
            return True
        rule, expires = found
        return (not rule["probe_allowed"] or not rule["store_allowed"]
                or not rule["license_id"] or row["license_id"] != rule["license_id"]
                or row["retention_until"] <= now
                or min(expires, rule["retention_until"]) <= now
                or _CAPTURE_RANK[row["capture_kind"]] > _CAPTURE_RANK[rule["allowed_capture"]]
                or row["captured_bytes"] > rule["max_captured_bytes"])
