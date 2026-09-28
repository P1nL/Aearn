"""Caller-transaction current provenance for an operator-registered capture.

The attestor signs pre-dial isolation only; TLS/body facts are attributed to
an authenticated, externally pinned reviewed worker image, not the attestor.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import psycopg

from .registered_source_bridge_host import SignedDispatchProofVerifier, _canonical
from .registered_source_policy import RegisteredSourceScope
from .registered_source_repository import _current
from .source_review_repository import CompleteCapture

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PostgresCurrentCaptureProvenanceResolver:
    """No network/commit; caller supplies transaction and external trust pins."""

    def __init__(
        self,
        conn: psycopg.Connection[dict[str, Any]],
        *,
        verifier: SignedDispatchProofVerifier,
        worker_image_sha256: str,
    ) -> None:
        if (
            conn is None
            or type(verifier) is not SignedDispatchProofVerifier
            or type(worker_image_sha256) is not str
            or _SHA256.fullmatch(worker_image_sha256) is None
        ):
            raise ValueError("PROVENANCE_CONFIG_DENIED")
        self.conn = conn
        self.verifier = verifier
        self.worker_image_sha256 = worker_image_sha256

    def resolve(self, capture: CompleteCapture) -> str | None:
        if (
            self.conn.autocommit
            or type(capture) is not CompleteCapture
            or capture.lane != "registered"
            or type(capture.capture_id) is not UUID
        ):
            return None
        try:
            row = self.conn.execute(
                "SELECT * FROM rag_registered_source_captures WHERE id=%s FOR SHARE",
                (capture.capture_id,),
            ).fetchone()
            if row is None:
                return None
            policy = self.conn.execute(
                "SELECT * FROM rag_registered_source_policies WHERE policy_id=%s FOR SHARE",
                (row["policy_id"],),
            ).fetchone()
            attempt = self.conn.execute(
                "SELECT * FROM rag_registered_fetch_attempts WHERE id=%s FOR SHARE",
                (row["fetch_attempt_id"],),
            ).fetchone()
            if policy is None or attempt is None:
                return None
            scope = RegisteredSourceScope(
                policy_id=policy["policy_id"], generation=policy["generation"],
                source_handle=policy["source_handle"], subject_id=policy["subject_id"],
                subject_version=policy["subject_version"], facets=tuple(policy["facets"]),
                url=policy["canonical_url"], host=policy["host"], path=policy["path"],
                root_id=policy["root_id"], dispatch_id=attempt["id"],
                max_bytes=policy["max_captured_bytes"],
            )
            clock = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
            if clock is None:
                return None
            now = clock["now"]
            # Existing policy/root checker re-reads current grants under locks.
            if _current(self.conn, scope, now, lock=True) is None:
                return None
            body = row["captured_body"]
            if type(body) is not bytes or not body:
                return None
            digest = hashlib.sha256(body).hexdigest()
            settled, dispatched = attempt["settled_at"], attempt["dispatched_at"]
            if (
                row["id"] != capture.capture_id
                or row["policy_id"] != scope.policy_id
                or row["generation"] != scope.generation
                or row["fetch_attempt_id"] != scope.dispatch_id
                or row["cleared_at"] is not None
                or row["retention_until"] <= now
                or row["retention_until"] > policy["retention_until"]
                or row["license_id"] != policy["license_id"]
                or row["evidence_level"] != "live_egress_attested"
                or row["final_url"] != scope.url
                or row["request_chain"] != [scope.url]
                or row["fetched_sha256"] != digest
                or row["captured_bytes"] != len(body)
                or not 0 < len(body) <= scope.max_bytes
                or attempt["policy_id"] != scope.policy_id
                or attempt["generation"] != scope.generation
                or attempt["canonical_url_sha256"] != policy["canonical_url_sha256"]
                or attempt["root_id"] != scope.root_id
                or attempt["state"] != "settled"
                or attempt["response_sha256"] != digest
                or attempt["response_bytes"] != len(body)
                or type(settled) is not datetime or settled.tzinfo is None
                or type(dispatched) is not datetime or dispatched.tzinfo is None
                or dispatched > settled or settled > now
                or capture.body != body or capture.digest != digest
                or capture.revision != digest
                or capture.scope.subject_id != scope.subject_id
                or capture.scope.subject_version != scope.subject_version
                or capture.scope.facets != scope.facets
                or capture.source_handle != scope.source_handle
                or capture.final_url != scope.url
                or capture.request_chain != (scope.url,)
                or capture.origin != policy["origin"]
                or capture.reading_level != policy["reading_level"]
                or capture.license_id != policy["license_id"]
            ):
                return None
            proof_bytes, proof_hash = row["transport_proof"], row["transport_proof_sha256"]
            if (
                type(proof_bytes) is not bytes or not 0 < len(proof_bytes) <= 4096
                or type(proof_hash) is not str or _SHA256.fullmatch(proof_hash) is None
                or hashlib.sha256(proof_bytes).hexdigest() != proof_hash
                or row["attestor_key_sha256"] != self.verifier._key_sha256
                or row["worker_image_sha256"] != self.worker_image_sha256
            ):
                return None
            proof = json.loads(proof_bytes)
            if _canonical(proof) != proof_bytes:
                return None
            # Historical signed proof is checked at trusted settlement, not now.
            # The bridge verifier accepts the exact wire scope (canonical UUID string).
            wire_scope = SimpleNamespace(**{**vars(scope), "dispatch_id": str(scope.dispatch_id)})
            verified = self.verifier.verify(wire_scope, proof, now=settled)
            if verified is None:
                return None
            report = verified.worker_fetch_report
            if (
                report["request_hash"] != attempt["request_hash"]
                or report["dispatch_id"] != str(scope.dispatch_id)
                or report["url"] != scope.url
                or report["content_type"] != row["content_type"]
                or report["body_sha256"] != digest
                or report["body_bytes"] != len(body)
                or dispatched.timestamp() * 1000 > cast(int, report["pre_dial_unix_ms"])
            ):
                return None
            return proof_hash
        except (psycopg.Error, KeyError, TypeError, ValueError, AttributeError, OverflowError):
            return None
