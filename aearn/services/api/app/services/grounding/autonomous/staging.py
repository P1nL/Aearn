"""Caller-transaction-owned, pre-admission B2 quarantine; no corpus or public reader."""
from __future__ import annotations

import json
from hashlib import sha256
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from psycopg import Connection

from .access_policy import AccessRequest, AuthorityResolver, AutonomousGates
from .budget import BudgetDenied, PostgresBudgetPolicyResolver, current_authority, require_transaction
from .candidate_repository import _public_url
from .candidate_policy_repository import PostgresCandidatePolicyResolver
from .contracts import LearningMaterialDemand, SourceCandidate, revalidate
from .jobs import DiscoveryJobRepository
from .intake_leases import IntakeLease, require_live_intake_lease
from .provenance import PreparedCapture
from .retention import StorageGrantResolver, check_storage
from .safe_fetch import SafeFetcher


class SharedRevocationResolver(Protocol):
    """Trusted shared-policy authority, not an actor-specific denial or caller flag."""

    def globally_revoked(self, candidate_id: UUID, policy_id: str, generation: int) -> bool: ...


class CandidateStagingRepository:
    """Requires an authenticated resolver and active lease on every content commit.

    The caller owns the outer transaction. No network call or body logging occurs here.
    """

    def __init__(self, conn: Connection[dict[str, Any]], *, offline_protocol_test: bool = False,
                 live_fetcher: SafeFetcher | None = None) -> None:
        self.conn = conn
        self.offline_protocol_test = offline_protocol_test
        self.live_fetcher = live_fetcher

    def stage(
        self, *, candidate_id: UUID, candidate: SourceCandidate, prepared: PreparedCapture,
        lease: IntakeLease, request: AccessRequest, demand: LearningMaterialDemand,
        gates: AutonomousGates, authority_resolver: AuthorityResolver,
        storage_resolver: StorageGrantResolver, now: datetime,
    ) -> UUID:
        if self.offline_protocol_test:
            expected_evidence = "offline_protocol_only"
        elif (type(self.live_fetcher) is SafeFetcher
              and not self.live_fetcher.offline_protocol_test
              and self.live_fetcher.live_ready):
            expected_evidence = "live_egress_attested"
        else:
            raise BudgetDenied("LIVE_EGRESS_UNVERIFIED")
        item = revalidate(candidate, SourceCandidate)
        need = revalidate(demand, LearningMaterialDemand)
        if (type(prepared) is not PreparedCapture or request.action != "store"
                or type(candidate_id) is not UUID or type(lease) is not IntakeLease
                or lease.candidate_id != candidate_id):
            raise BudgetDenied("STAGING_INPUT_INVALID")
        if (prepared.evidence_level != expected_evidence or item.demand_hash != need.demand_hash
                or item.scope != need.scope or item.capture.kind != "none"):
            raise BudgetDenied("CANDIDATE_SCOPE_STALE")
        # Recompute captured hashes and parsed fragments; never trust caller DTOs.
        from .provenance import validate_prepared_capture
        validate_prepared_capture(prepared, candidate=item)
        if _public_url(item.url) != item.url or prepared.request_chain[0] != item.url:
            raise BudgetDenied("CANDIDATE_LOCATION_STALE")
        # Never trust externally constructed StorageDecision or parsed fragment text.
        planned = len(prepared.captured_body or b"")
        before = check_storage(item, request, intended_capture=prepared.capture_kind,
                               planned_bytes=planned, gates=gates,
                               authority_resolver=authority_resolver,
                               storage_resolver=storage_resolver, now=now)
        if not before.allowed:
            raise BudgetDenied(before.reason)
        require_transaction(self.conn)
        with self.conn.transaction():
            # Match claim's candidate -> intake lease lock order; refresh DB time
            # after each lock wait, never rely on the caller's pre-fetch clock.
            row = self.conn.execute(
                "SELECT * FROM rag_discovery_candidates WHERE id=%s AND job_id=%s FOR UPDATE",
                (candidate_id, lease.job_id),
            ).fetchone()
            if row is None or (row["canonical_url"], row["canonical_url_hash"], row["demand_hash"],
                               row["subject_id"], row["subject_version"], row["kind"],
                               row["repo_commit"], row["repo_path"]) != (
                item.url, sha256(item.url.encode()).hexdigest(), need.demand_hash,
                need.scope.subject_id, need.scope.subject_version, item.kind,
                item.repo_commit, item.repo_path,
            ):
                raise BudgetDenied("CANDIDATE_SCOPE_STALE")
            clock_row = self.conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
            if clock_row is None:
                raise BudgetDenied("CLOCK_UNAVAILABLE")
            db_now = clock_row["db_now"]
            require_live_intake_lease(self.conn, lease, db_now)
            clock_row = self.conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
            if clock_row is None:
                raise BudgetDenied("CLOCK_UNAVAILABLE")
            db_now = clock_row["db_now"]
            require_live_intake_lease(self.conn, lease, db_now)
            job = self.conn.execute("SELECT * FROM rag_discovery_jobs WHERE id=%s", (lease.job_id,)).fetchone()
            if job is None or job["state"] != "completed":
                raise BudgetDenied("JOB_SCOPE_STALE")
            current = current_authority(request=request, demand=need, gates=gates,
                                        resolver=authority_resolver, now=db_now)
            DiscoveryJobRepository._scope(job, current, need)
            root = PostgresBudgetPolicyResolver(self.conn).resolve(current)
            if (root is None or root.root_id != job["root_id"]
                    or not root.period_start <= db_now < root.period_end):
                raise BudgetDenied("JOB_SCOPE_STALE")
            if item.kind == "landing" and prepared.capture_kind == "full":
                probe = request.model_copy(update={"action": "probe"})
                probe_authority = current_authority(request=probe, demand=need,
                                                    gates=gates, resolver=authority_resolver, now=db_now)
                if probe_authority.budget.root_id != job["root_id"]:
                    raise BudgetDenied("JOB_SCOPE_STALE")
            receipt = self.conn.execute(
                "SELECT r.receipt_handle,a.state AS attempt_state,b.state AS reservation_state,"
                "b.job_id AS reserved_job,b.root_id AS reserved_root,b.period_key AS reserved_period "
                "FROM rag_discovery_receipts r "
                "JOIN rag_budget_attempts a ON a.id=r.attempt_id AND a.job_id=r.job_id "
                "JOIN rag_budget_reservations b ON b.id=a.reservation_id AND b.job_id=r.job_id "
                "WHERE r.id=%s AND r.job_id=%s",
                (row["discovery_receipt_id"], lease.job_id),
            ).fetchone()
            if (receipt is None or receipt["receipt_handle"] != item.discovery_receipt_id
                    or receipt["attempt_state"] != "settled"
                    or receipt["reservation_state"] != "settled"
                    or receipt["reserved_job"] != lease.job_id
                    or receipt["reserved_root"] != root.root_id
                    or receipt["reserved_period"] != root.period_key):
                raise BudgetDenied("RECEIPT_STALE")
            # Live storage grant is read from the policy table on this same
            # commit transaction; a caller-provided resolver cannot grant it.
            commit_storage_resolver = (storage_resolver if self.offline_protocol_test
                                       else PostgresCandidatePolicyResolver(self.conn))
            decision = check_storage(item, request, intended_capture=prepared.capture_kind,
                                     planned_bytes=planned, gates=gates,
                                     authority_resolver=authority_resolver,
                                     storage_resolver=commit_storage_resolver, now=db_now)
            if not decision.allowed or decision.retention_until is None:
                raise BudgetDenied(decision.reason)
            if decision.license_id != prepared.license_id:
                raise BudgetDenied("STORAGE_LICENSE_MISMATCH")
            if decision.retention_until <= db_now:
                raise BudgetDenied("STORAGE_POLICY_STALE")
            live = self.live_fetcher
            if (not self.offline_protocol_test and
                    (live is None or not live.consume_live_receipt(
                        prepared.live_receipt, url=item.url, digest=prepared.fetched_sha256
                    ))):
                raise BudgetDenied("LIVE_RECEIPT_UNVERIFIED")
            # B1 discovery kind remains the immutable lead ('landing' included).
            # A full, reparsed B2 capture is a document-body observation on the
            # SAME candidate_id, not a second (job_id, URL), source admission,
            # or model-supplied promotion. Transport evidence is kept distinct.
            # Reuse only an identical receipt. A scrubbed row cannot be rehydrated.
            clock_row = self.conn.execute("SELECT clock_timestamp() AS db_now").fetchone()
            if clock_row is None:
                raise BudgetDenied("CLOCK_UNAVAILABLE")
            db_now = clock_row["db_now"]
            require_live_intake_lease(self.conn, lease, db_now)
            if not root.period_start <= db_now < root.period_end or decision.retention_until <= db_now:
                raise BudgetDenied("STORAGE_POLICY_STALE")
            self.conn.execute(
                "INSERT INTO rag_candidate_captures(candidate_id,job_id,evidence_level,final_url,request_chain,"
                "chain_sha256,media_type,fetched_sha256,capture_kind,captured_bytes,prefix_sha256,"
                "full_sha256,captured_body,policy_id,policy_generation,retention_until,license_id,"
                "author_name,origin_sha256,repo_commit,repo_path) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (candidate_id) DO NOTHING",
                (candidate_id, lease.job_id, prepared.evidence_level, prepared.final_url,
                 json.dumps(prepared.request_chain), prepared.chain_sha256, prepared.media_type,
                 prepared.fetched_sha256, prepared.capture_kind, planned, prepared.prefix_sha256,
                 prepared.full_sha256, prepared.captured_body, request.policy_id,
                 request.policy_generation, decision.retention_until, prepared.license_id,
                 prepared.author_name, prepared.origin_sha256, item.repo_commit, item.repo_path),
            )
            saved = self.conn.execute(
                "SELECT * FROM rag_candidate_captures WHERE candidate_id=%s", (candidate_id,),
            ).fetchone()
            assert saved is not None
            if (saved["job_id"], saved["evidence_level"], saved["final_url"],
                    tuple(saved["request_chain"]), saved["chain_sha256"], saved["media_type"],
                    saved["fetched_sha256"], saved["capture_kind"], saved["captured_bytes"],
                    saved["prefix_sha256"], saved["full_sha256"], saved["policy_id"],
                    saved["policy_generation"], saved["retention_until"], saved["license_id"],
                    saved["author_name"], saved["origin_sha256"], saved["repo_commit"],
                    saved["repo_path"]) != (
                lease.job_id, prepared.evidence_level, prepared.final_url, prepared.request_chain,
                prepared.chain_sha256, prepared.media_type, prepared.fetched_sha256,
                prepared.capture_kind, planned, prepared.prefix_sha256, prepared.full_sha256,
                request.policy_id, request.policy_generation, decision.retention_until,
                prepared.license_id, prepared.author_name, prepared.origin_sha256,
                item.repo_commit, item.repo_path
            ) or saved["cleared_at"] is not None:
                raise BudgetDenied("CAPTURE_CONFLICT")
            for fragment in prepared.fragments:
                self.conn.execute(
                    "INSERT INTO rag_candidate_fragments(capture_id,ordinal,kind,depth,sha256,text_content) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (capture_id,ordinal) DO NOTHING",
                    (saved["id"], fragment.ordinal, fragment.kind, fragment.depth,
                     fragment.sha256, fragment.text),
                )
            persisted = self.conn.execute(
                "SELECT ordinal,kind,depth,sha256,text_content FROM rag_candidate_fragments "
                "WHERE capture_id=%s ORDER BY ordinal", (saved["id"],),
            ).fetchall()
            if tuple((part["ordinal"], part["kind"], part["depth"], part["sha256"],
                      part["text_content"]) for part in persisted) != tuple(
                (part.ordinal, part.kind, part.depth, part.sha256, part.text)
                for part in prepared.fragments
            ):
                raise BudgetDenied("FRAGMENT_CONFLICT")
            self.conn.execute(
                "INSERT INTO rag_candidate_private_refs(actor_id,candidate_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (request.actor_id, candidate_id),
            )
            return saved["id"]

    def clear_expired(self, *, limit: int = 100) -> int:
        """DB-clock expiration, preserving hash/location audit but no body/fragment text."""
        if not 1 <= limit <= 1000:
            raise BudgetDenied("INVALID_CLEANUP_LIMIT")
        require_transaction(self.conn)
        with self.conn.transaction():
            ids = self.conn.execute(
                "SELECT id FROM rag_candidate_captures WHERE retention_until<=CURRENT_TIMESTAMP "
                "AND cleared_at IS NULL ORDER BY retention_until,id LIMIT %s FOR UPDATE SKIP LOCKED",
                (limit,),
            ).fetchall()
            for row in ids:
                self.conn.execute("UPDATE rag_candidate_fragments SET text_content=NULL "
                                  "WHERE capture_id=%s AND text_content IS NOT NULL", (row["id"],))
                self.conn.execute("UPDATE rag_candidate_captures SET captured_body=NULL,cleared_at=CURRENT_TIMESTAMP "
                                  "WHERE id=%s", (row["id"],))
            return len(ids)

    def unlink_actor(self, *, actor_id: str) -> int:
        """Owner-verified caller only; shared audit/capture is not deleted."""
        require_transaction(self.conn)
        with self.conn.transaction():
            return self.conn.execute(
                "DELETE FROM rag_candidate_private_refs WHERE actor_id=%s", (actor_id,),
            ).rowcount

    def clear_revoked(self, *, candidate_id: UUID,
                      resolver: SharedRevocationResolver) -> bool:
        """Globally revoked shared capture only; one actor's withdrawal just unlinks.

        The resolver must be the trusted shared-policy authority. No untrusted
        StorageDecision, actor denial, or arbitrary caller bool can erase a
        still-authorized shared candidate.
        """
        require_transaction(self.conn)
        with self.conn.transaction():
            row = self.conn.execute(
                "SELECT id,policy_id,policy_generation,cleared_at FROM rag_candidate_captures "
                "WHERE candidate_id=%s FOR UPDATE", (candidate_id,),
            ).fetchone()
            if row is None or row["cleared_at"] is not None:
                return False
            try:
                revoked = resolver.globally_revoked(candidate_id, row["policy_id"],
                                                    row["policy_generation"])
            except Exception as exc:
                raise BudgetDenied("REVOCATION_UNVERIFIED") from exc
            if revoked is not True:
                return False
            self.conn.execute("UPDATE rag_candidate_fragments SET text_content=NULL "
                              "WHERE capture_id=%s AND text_content IS NOT NULL", (row["id"],))
            self.conn.execute("UPDATE rag_candidate_captures SET captured_body=NULL,cleared_at=CURRENT_TIMESTAMP "
                              "WHERE id=%s", (row["id"],))
            return True
