"""Pre-admission B1 search receipts/candidates only; never writes active corpus."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from psycopg import Connection

from .access_policy import AccessRequest, AuthorityResolver, AuthoritySnapshot, AutonomousGates
from .budget import BudgetDenied, _valid_hash, current_authority, require_transaction
from .contracts import LearningMaterialDemand, SourceCandidate, revalidate
from .jobs import DiscoveryJobRepository, JobLease, require_live_lease


def _public_url(value: str) -> str:
    """Persist only a location without query/credentials; this is NOT a fetch security check."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != "https" or host is None or not host.isascii()
                or parsed.port is not None or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "@" in value or "\\" in value
                or any(ord(c) < 33 for c in value)
                or len(value) > 2048 or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                or host.startswith(".") or host.endswith(".")):
            raise ValueError("invalid location")
        return urlunsplit(("https", host.lower(), parsed.path or "/", "", ""))
    except ValueError as exc:
        raise BudgetDenied("UNSAFE_CANDIDATE_LOCATION") from exc


class CandidateRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def record_receipt(
        self, *, lease: JobLease, request: AccessRequest, demand: LearningMaterialDemand,
        gates: AutonomousGates, resolver: AuthorityResolver, attempt_id: UUID,
        receipt_handle: str, result_code: str, response_hash: str, now: datetime,
    ) -> UUID:
        if not re.fullmatch(r"^[a-z][a-z0-9._:-]{2,159}$", receipt_handle):
            raise BudgetDenied("INVALID_RECEIPT")
        if not re.fullmatch(r"^[A-Z][A-Z0-9_]{0,79}$", result_code):
            raise BudgetDenied("INVALID_RECEIPT")
        _valid_hash(response_hash)
        snapshot = self._authority(request, demand, gates, resolver, now)
        require_transaction(self.conn)
        with self.conn.transaction():
            require_live_lease(self.conn, lease, now)
            job = self.conn.execute("SELECT * FROM rag_discovery_jobs WHERE id=%s", (lease.job_id,)).fetchone()
            if job is None:
                raise BudgetDenied("JOB_NOT_FOUND")
            DiscoveryJobRepository._scope(job, snapshot, demand)
            if self._authority(request, demand, gates, resolver, now) != snapshot:
                raise BudgetDenied("AUTHORITY_CHANGED")
            attempt = self.conn.execute(
                "SELECT r.job_id,a.state FROM rag_budget_attempts a "
                "JOIN rag_budget_reservations r ON r.id=a.reservation_id WHERE a.id=%s", (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["job_id"] != lease.job_id or attempt["state"] != "settled":
                raise BudgetDenied("ATTEMPT_NOT_SETTLED")
            self.conn.execute(
                "INSERT INTO rag_discovery_receipts(job_id,attempt_id,receipt_handle,result_code,response_hash) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (lease.job_id, attempt_id, receipt_handle, result_code, response_hash),
            )
            row = self.conn.execute("SELECT * FROM rag_discovery_receipts WHERE attempt_id=%s", (attempt_id,)).fetchone()
            if row is None or (row["job_id"], row["receipt_handle"], row["result_code"], row["response_hash"]) != (
                lease.job_id, receipt_handle, result_code, response_hash
            ):
                raise BudgetDenied("RECEIPT_CONFLICT")
            return row["id"]

    def record_candidate(
        self, *, lease: JobLease, request: AccessRequest, demand: LearningMaterialDemand,
        gates: AutonomousGates, resolver: AuthorityResolver,
        candidate: SourceCandidate, now: datetime,
    ) -> UUID:
        valid = revalidate(candidate, SourceCandidate)
        snapshot = self._authority(request, demand, gates, resolver, now)
        if (valid.demand_hash != demand.demand_hash or valid.scope != demand.scope
                or valid.capture.kind != "none"):
            raise BudgetDenied("CANDIDATE_SCOPE_STALE")
        url = _public_url(valid.url)
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        require_transaction(self.conn)
        with self.conn.transaction():
            require_live_lease(self.conn, lease, now)
            job = self.conn.execute("SELECT * FROM rag_discovery_jobs WHERE id=%s", (lease.job_id,)).fetchone()
            if job is None:
                raise BudgetDenied("JOB_NOT_FOUND")
            DiscoveryJobRepository._scope(job, snapshot, demand)
            if self._authority(request, demand, gates, resolver, now) != snapshot:
                raise BudgetDenied("AUTHORITY_CHANGED")
            receipt = self.conn.execute(
                "SELECT id FROM rag_discovery_receipts WHERE receipt_handle=%s AND job_id=%s",
                (valid.discovery_receipt_id, lease.job_id),
            ).fetchone()
            if receipt is None:
                raise BudgetDenied("RECEIPT_NOT_FOUND")
            self.conn.execute(
                "INSERT INTO rag_discovery_candidates(job_id,discovery_receipt_id,canonical_url,canonical_url_hash,"
                "kind,demand_hash,subject_id,subject_version,repo_commit,repo_path) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (job_id,canonical_url_hash) DO NOTHING",
                (lease.job_id, receipt["id"], url, url_hash, valid.kind, demand.demand_hash,
                 demand.scope.subject_id, demand.scope.subject_version, valid.repo_commit, valid.repo_path),
            )
            row = self.conn.execute(
                "SELECT * FROM rag_discovery_candidates WHERE job_id=%s AND canonical_url_hash=%s",
                (lease.job_id, url_hash),
            ).fetchone()
            if row is None or (
                row["discovery_receipt_id"], row["canonical_url"], row["kind"], row["repo_commit"], row["repo_path"]
            ) != (receipt["id"], url, valid.kind, valid.repo_commit, valid.repo_path):
                raise BudgetDenied("CANDIDATE_CONFLICT")
            return row["id"]

    @staticmethod
    def _authority(request: AccessRequest, demand: LearningMaterialDemand, gates: AutonomousGates,
                   resolver: AuthorityResolver, now: datetime) -> AuthoritySnapshot:
        if request.action != "discover":
            raise BudgetDenied("ACTION_DENIED")
        return current_authority(request=request, demand=demand, gates=gates, resolver=resolver, now=now)
