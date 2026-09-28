"""C operator-provisioned B full-capture use grant; no default or inferred grant."""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psycopg

from .source_review_repository import CandidateUseGrant


class PostgresCandidateGrantResolver:
    """Transaction-scoped current grant; B's temporary store rule is insufficient."""

    def __init__(self, conn: psycopg.Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def resolve(self, capture_id: UUID) -> CandidateUseGrant | None:
        if self.conn.autocommit or type(capture_id) is not UUID:
            return None
        try:
            db = self.conn.execute("SELECT current_database() AS name").fetchone()
            if db is None or not db["name"].startswith("aearn_rag260_c_"):
                return None
            row = self.conn.execute(
                """SELECT g.*, c.policy_id AS capture_policy,
                          c.policy_generation AS capture_generation,
                          c.full_sha256,c.fetched_sha256,c.captured_bytes,c.captured_body,
                          c.capture_kind,c.evidence_level,c.cleared_at,
                          c.retention_until AS capture_retention,c.license_id AS capture_license,
                          c.final_url,d.subject_id AS candidate_subject,
                          d.subject_version AS candidate_version,
                          j.root_id AS job_root,j.state AS job_state,
                          j.policy_id AS job_budget_policy,
                          j.policy_generation AS job_budget_generation,
                          j.delegation_id AS job_delegation_id,
                          j.delegation_generation AS job_delegation_generation,
                          l.state AS lease_state,p.enabled AS policy_enabled,
                          p.revoked_at AS policy_revoked,p.current_generation,p.expires_at AS policy_expiry,
                          root.enabled AS root_enabled,root.period_start,root.period_end,
                          root.delegation_expires_at,
                          root.policy_id AS root_budget_policy,
                          root.policy_generation AS root_budget_generation,
                          root.delegation_id AS root_delegation_id,
                          root.delegation_generation AS root_delegation_generation
                   FROM rag_candidate_use_grants g
                   JOIN rag_candidate_captures c ON c.id=g.capture_id
                   JOIN rag_discovery_candidates d ON d.id=c.candidate_id AND d.job_id=c.job_id
                   JOIN rag_discovery_jobs j ON j.id=d.job_id
                   JOIN rag_candidate_intake_leases l ON l.candidate_id=d.id AND l.job_id=d.job_id
                   JOIN rag_candidate_access_policies p ON p.policy_id=g.policy_id
                   JOIN rag_budget_authority_roots root ON root.root_id=g.root_id
                   WHERE g.capture_id=%s FOR SHARE OF g,c,d,j,l,p,root""",
                (capture_id,),
            ).fetchone()
            now_row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
            if row is None or now_row is None:
                return None
            now = now_row["now"]
            body = row["captured_body"]
            if (row["active"] is not True or row["revoked_at"] is not None
                    or row["immutable_history_allowed"] is not True
                    or not body or len(body) != row["captured_bytes"]
                    or hashlib.sha256(bytes(body)).hexdigest() != row["capture_sha256"]
                    or row["capture_sha256"] != row["full_sha256"]
                    or row["capture_sha256"] != row["fetched_sha256"]
                    or row["capture_kind"] != "full"
                    or row["evidence_level"] != "live_egress_attested"
                    or row["cleared_at"] is not None
                    or row["retained_until"] <= now or row["capture_retention"] <= now
                    or row["retained_until"] > row["capture_retention"]
                    or row["license_id"] != row["capture_license"]
                    or row["policy_id"] != row["capture_policy"]
                    or row["policy_generation"] != row["capture_generation"]
                    or row["policy_generation"] != row["current_generation"]
                    or row["policy_enabled"] is not True or row["policy_revoked"] is not None
                    or row["policy_expiry"] <= now
                    or row["root_id"] != row["job_root"]
                    or row["root_budget_policy"] != row["job_budget_policy"]
                    or row["root_budget_generation"] != row["job_budget_generation"]
                    or row["root_delegation_id"] != row["job_delegation_id"]
                    or row["root_delegation_generation"] != row["job_delegation_generation"]
                    or row["root_enabled"] is not True
                    or not row["period_start"] <= now < row["period_end"]
                    or row["delegation_expires_at"] <= now
                    or row["job_state"] != "completed" or row["lease_state"] != "done"
                    or row["subject_id"] != row["candidate_subject"]
                    or row["subject_version"] != row["candidate_version"]
                    or not row["allowed_usages"]
                    or not set(row["allowed_usages"]) <= {"main_teaching", "supplementary_explanation"}):
                return None
            parsed = urlsplit(row["final_url"])
            path = parsed.path or "/"
            if (parsed.scheme != "https" or not parsed.hostname or parsed.port
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                return None
            rules = self.conn.execute(
                """SELECT * FROM rag_candidate_access_rules WHERE policy_id=%s
                   AND generation=%s AND host=%s AND store_allowed
                   AND allowed_capture='full' AND revoked_at IS NULL FOR SHARE""",
                (row["policy_id"], row["policy_generation"], parsed.hostname),
            ).fetchall()
            if not any(
                (rule["path_prefix"] == "/" or path == rule["path_prefix"]
                 or path.startswith(rule["path_prefix"] + "/"))
                and rule["license_id"] == row["license_id"]
                and rule["valid_until"] > now and rule["retention_until"] > now
                and rule["max_captured_bytes"] >= row["captured_bytes"]
                and row["retained_until"] <= rule["retention_until"]
                for rule in rules
            ):
                return None
            settled = self.conn.execute(
                """SELECT 1 FROM rag_candidate_captures c
                   JOIN rag_discovery_candidates d ON d.id=c.candidate_id AND d.job_id=c.job_id
                   JOIN rag_discovery_receipts receipt ON receipt.id=d.discovery_receipt_id AND receipt.job_id=d.job_id
                   JOIN rag_budget_attempts attempt ON attempt.id=receipt.attempt_id AND attempt.job_id=d.job_id
                   JOIN rag_budget_reservations reservation ON reservation.id=attempt.reservation_id AND reservation.job_id=d.job_id
                   WHERE c.id=%s AND receipt.result_code='SEARCH_COMPLETED'
                     AND attempt.state='settled' AND reservation.state='settled'
                     AND reservation.root_id=%s FOR SHARE OF c,d,receipt,attempt,reservation""",
                (capture_id, row["root_id"]),
            ).fetchone()
            if settled is None:
                return None
            return CandidateUseGrant(
                capture_id=capture_id, policy_id=row["policy_id"],
                generation=row["policy_generation"], root_id=row["root_id"],
                source_handle=row["source_handle"], license_id=row["license_id"],
                origin=row["origin"], reading_level=row["reading_level"],
                facets=tuple(row["facets"]), allowed_usages=tuple(row["allowed_usages"]),
                immutable_history_allowed=True, retained_until=row["retained_until"],
                storage_receipt_id=row["storage_receipt_id"], active=True,
            )
        except (psycopg.Error, KeyError, TypeError, ValueError, AttributeError):
            return None


def require_candidate_history_grant(
    conn: psycopg.Connection[dict[str, Any]], admission_id: UUID,
) -> None:
    """Pre-link explicit grant; the SQL link trigger independently repeats it."""
    row = conn.execute(
        """SELECT review.candidate_capture_id FROM rag_source_admissions admission
           JOIN rag_source_reviews review ON review.id=admission.review_id
           WHERE admission.id=%s AND admission.active AND review.immutable_history_allowed
             AND review.candidate_capture_id IS NOT NULL FOR SHARE OF admission,review""",
        (admission_id,),
    ).fetchone()
    if row is None or PostgresCandidateGrantResolver(conn).resolve(row["candidate_capture_id"]) is None:
        raise ValueError("HISTORY_GRANT_MISSING")