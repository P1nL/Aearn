"""Opt-in pinned service review for three exact third-party teaching groups.

The existing C repository owns review/admission rows. This signature is external
service evidence, never a supplied verified flag, page-wide claim or assessment.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import re
from typing import Any, Literal
from uuid import UUID

from aearn_shared.execution import SandboxResultV1
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from psycopg import Connection
from psycopg.pq import TransactionStatus
from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort, RunnerTerminalReceipt

from .contracts import FrozenContract, HANDLE, HASH, SubjectScope, revalidate
from .material_lifetime import COURSE_MATERIAL_POLICY, LEGACY_MATERIAL_POLICY, MaterialLifetimePolicy, material_lifetime, new_material_expiry
from .public_python_teaching_profile import GROUPS, PROBE, USAGES, TeachingAttribution, TeachingReviewDenied, analyze_teaching, teaching_request
from .registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from .source_assessment_profiles import SourceSpan
from .source_review_repository import CompleteCapture, QualityFinding, SourceReviewRepository

DOMAIN = b"AEARN-PUBLIC-PYTHON-TEACHING-EXCERPTS-V1\n"
COURSE_DOMAIN = b"AEARN-PUBLIC-PYTHON-TEACHING-EXCERPTS-V2\n"


class PreparedTeachingReview(FrozenContract):
    profile: Literal["learnx-python-exact-code-groups-v1", "learnx-python-exact-code-groups-v2"] = "learnx-python-exact-code-groups-v1"
    capture_id: UUID
    source_handle: str = Field(pattern=HANDLE)
    scope: SubjectScope
    document_hash: str = Field(pattern=HASH)
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    root_id: str = Field(pattern=HANDLE)
    provenance_digest: str = Field(pattern=HASH)
    excerpts: tuple[SourceSpan, ...] = Field(min_length=3,max_length=3)
    attribution: TeachingAttribution
    prepared_at: datetime
    authority_expires_at: datetime

    @model_validator(mode="after")
    def exact(self) -> PreparedTeachingReview:
        lifetime = material_lifetime(COURSE_MATERIAL_POLICY if self.profile == "learnx-python-exact-code-groups-v2" else LEGACY_MATERIAL_POLICY)
        if (self.scope.subject_id != "route.python" or self.scope.subject_version != "1.0"
                or self.scope.facets != ("fundamentals",) or {s.unit for s in self.excerpts} != set(GROUPS)
                or self.prepared_at.tzinfo is None or self.prepared_at.utcoffset() != timedelta(0)
                or self.authority_expires_at.tzinfo is None
                or not self.prepared_at < self.authority_expires_at <= self.prepared_at + lifetime):
            raise ValueError("teaching scope denied")
        return self


def _clock(conn: Connection[dict[str, Any]]) -> datetime:
    if conn.autocommit or conn.info.transaction_status != TransactionStatus.INTRANS:
        raise TeachingReviewDenied("TEACHING_TRANSACTION_REQUIRED")
    row = conn.execute("SELECT current_database() AS name,clock_timestamp() AS now").fetchone()
    if row is None or row["name"] != "aearn_b1d_sandbox_20261001":
        raise TeachingReviewDenied("TEACHING_DATABASE_DENIED")
    isolation = conn.execute("SHOW transaction_isolation").fetchone()
    if isolation is None or isolation["transaction_isolation"] != "read committed":
        raise TeachingReviewDenied("TEACHING_TRANSACTION_REQUIRED")
    return row["now"].astimezone(timezone.utc)


def prepare_teaching(conn: Connection[dict[str, Any]], *, capture_id: UUID,
                     provenance: PostgresCurrentCaptureProvenanceResolver, enabled: bool = False,
                     lifetime_policy: MaterialLifetimePolicy = COURSE_MATERIAL_POLICY) -> PreparedTeachingReview:
    if not enabled or type(provenance) is not PostgresCurrentCaptureProvenanceResolver or provenance.conn is not conn:
        raise TeachingReviewDenied("TEACHING_GATE_CLOSED")
    now = _clock(conn)
    capture, policy = SourceReviewRepository(conn)._capture(capture_id,"registered",now)
    proof = provenance.resolve(capture)
    root = conn.execute("SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR SHARE",(policy["root_id"],)).fetchone()
    if (root is None or not proof or tuple(policy["allowed_usages"]) != USAGES
            or policy["immutable_history_allowed"] is not True):
        raise TeachingReviewDenied("TEACHING_SOURCE_AUTHORITY_DENIED")
    expiry = new_material_expiry(now=now, policy=lifetime_policy,
        policy_expires_at=policy["expires_at"], policy_retention_until=policy["policy_retention"],
        capture_retention_until=policy["retention_until"], delegation_expires_at=root["delegation_expires_at"],
        period_end=root["period_end"])
    return PreparedTeachingReview(
        profile="learnx-python-exact-code-groups-v2" if lifetime_policy == COURSE_MATERIAL_POLICY else "learnx-python-exact-code-groups-v1",
        capture_id=capture_id,source_handle=capture.source_handle,scope=capture.scope,
        document_hash=capture.digest,policy_id=policy["policy_id"],policy_generation=policy["policy_generation"],
        root_id=policy["root_id"],provenance_digest=proof,excerpts=analyze_teaching(capture),attribution=TeachingAttribution(),
        prepared_at=now,authority_expires_at=expiry)


def _terminal(payload: dict[str, Any]) -> None:
    request, expected = teaching_request()
    try:
        result = SandboxResultV1.model_validate_json(json.dumps(payload["result"]))
        elapsed = payload["elapsed_seconds"]
        if (payload["schema_version"] != "item_supply_runner_terminal_v1" or payload["mode"] != "live"
                or payload["isolation"] != "approved_os_boundary" or payload["probe_name"] != PROBE
                or payload["request_hash"] != canonical_hash(request.model_dump(mode="json"))
                or re.fullmatch(HASH,payload["lock_fingerprint"]) is None or not payload["seal"]
                or type(elapsed) not in (int,float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 5
                or result.status.value != "success" or result.stderr or result.diagnostic_code != "item_supply_facts_v1"
                or result.test_feedback or result.passed_test_count or result.total_test_count
                or json.loads(result.stdout) != expected):
            raise ValueError
    except Exception:
        raise TeachingReviewDenied("TEACHING_EXECUTION_DENIED") from None


class TeachingReviewPayload(FrozenContract):
    format: Literal["aearn.public-python-teaching.v1", "aearn.public-python-teaching.v2"] = "aearn.public-python-teaching.v1"
    quality_scope: Literal["approved_code_groups_only"] = "approved_code_groups_only"
    prepared: PreparedTeachingReview
    terminal: dict[str, Any]
    usages: tuple[Literal["main_teaching"], ...] = USAGES
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def bounded(self) -> TeachingReviewPayload:
        expected_profile = "learnx-python-exact-code-groups-v2" if self.format == "aearn.public-python-teaching.v2" else "learnx-python-exact-code-groups-v1"
        if (self.usages != USAGES or self.issued_at.tzinfo is None or self.issued_at.utcoffset() != timedelta(0)
                or self.prepared.profile != expected_profile
                or self.expires_at.tzinfo is None or self.expires_at.utcoffset() != timedelta(0)
                or not self.prepared.prepared_at <= self.issued_at < self.expires_at <= self.prepared.authority_expires_at):
            raise ValueError("teaching expiry denied")
        _terminal(self.terminal)
        return self


class SignedTeachingReview(FrozenContract):
    service_key_id: str = Field(pattern=HANDLE)
    payload: TeachingReviewPayload
    signature_hex: str = Field(pattern=r"^[0-9a-f]{128}$")


def _canonical(payload: TeachingReviewPayload) -> bytes:
    payload = revalidate(payload,TeachingReviewPayload)
    domain = COURSE_DOMAIN if payload.format == "aearn.public-python-teaching.v2" else DOMAIN
    return domain + json.dumps(payload.model_dump(mode="json"),
                               sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()


def run_teaching(prepared: PreparedTeachingReview, *, runner: RunnerPort, run_id: UUID) -> RunnerTerminalReceipt:
    revalidate(prepared,PreparedTeachingReview)
    request, _ = teaching_request()
    terminal = runner.run(request=request,run_id=run_id,probe_name=PROBE)
    if not runner.verify(terminal,request=request):
        raise TeachingReviewDenied("TEACHING_SEAL_DENIED")
    _terminal(terminal.to_payload())
    return terminal


def sign_teaching(prepared: PreparedTeachingReview, terminal: RunnerTerminalReceipt, *, runner: RunnerPort,
                  private_key: Ed25519PrivateKey, service_key_id: str, now: datetime, expires_at: datetime | None = None) -> SignedTeachingReview:
    prepared = revalidate(prepared,PreparedTeachingReview)
    request, _ = teaching_request()
    if not isinstance(private_key,Ed25519PrivateKey) or not runner.verify(terminal,request=request):
        raise TeachingReviewDenied("TEACHING_SEAL_DENIED")
    payload = TeachingReviewPayload(
        format="aearn.public-python-teaching.v2" if prepared.profile == "learnx-python-exact-code-groups-v2" else "aearn.public-python-teaching.v1",
        prepared=prepared,terminal=terminal.to_payload(),
        issued_at=now,expires_at=expires_at if expires_at is not None else prepared.authority_expires_at)
    return SignedTeachingReview(service_key_id=service_key_id,payload=payload,signature_hex=private_key.sign(_canonical(payload)).hex())


class PublicPythonTeachingVerifier:
    """Same-connection pinned verifier, composed only in explicitly enabled C."""
    def __init__(self, conn: Connection[dict[str, Any]], *, review: SignedTeachingReview,
                 service_keys: dict[str, bytes], provenance: PostgresCurrentCaptureProvenanceResolver,
                 enabled: bool = False) -> None:
        if (type(provenance) is not PostgresCurrentCaptureProvenanceResolver or provenance.conn is not conn
                or not service_keys or any(type(k) is not str or type(v) is not bytes or len(v)!=32 for k,v in service_keys.items())):
            raise TeachingReviewDenied("TEACHING_CONFIG_DENIED")
        self.conn,self.review,self.provenance = conn,revalidate(review,SignedTeachingReview),provenance
        self.service_keys,self.enabled = dict(service_keys),enabled is True

    def _reviewed(self, capture: CompleteCapture) -> tuple[tuple[str, ...], str] | None:
        try:
            if not self.enabled:
                return None
            now = _clock(self.conn)
            signed = revalidate(self.review,SignedTeachingReview)
            p = signed.payload
            key = self.service_keys.get(signed.service_key_id)
            if key is None or p.issued_at > now or p.expires_at <= now or p.prepared.capture_id != capture.capture_id:
                return None
            Ed25519PublicKey.from_public_bytes(key).verify(bytes.fromhex(signed.signature_hex),_canonical(p))
            fresh = prepare_teaching(self.conn,capture_id=capture.capture_id,provenance=self.provenance,enabled=True,
                lifetime_policy=COURSE_MATERIAL_POLICY if p.format == "aearn.public-python-teaching.v2" else LEGACY_MATERIAL_POLICY)
            if (fresh.model_dump(exclude={"prepared_at","authority_expires_at"}) != p.prepared.model_dump(exclude={"prepared_at","authority_expires_at"})
                    or p.expires_at > fresh.authority_expires_at or capture.digest != fresh.document_hash
                    or analyze_teaching(capture) != fresh.excerpts):
                return None
            excerpts = tuple(capture.body[s.start_byte:s.end_byte].decode("utf8") for s in fresh.excerpts)
            return excerpts, canonical_hash(signed.model_dump(mode="json"))
        except Exception:
            return None

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        result = self._reviewed(capture)
        if result is None:
            return QualityFinding("offline_protocol_only","unknown","unknown","unknown","unknown","unknown",(),"family.unverified","0"*64)
        return QualityFinding("production","current","suitable","correct","resolved","absent",("fundamentals",),"family.learnxinyminutes.python",result[1])

    def reviewed_usages(self, capture: CompleteCapture) -> tuple[str, ...]:
        return USAGES if self._reviewed(capture) is not None else ()

    def approved_excerpts(self, capture: CompleteCapture) -> tuple[str, ...]:
        result = self._reviewed(capture)
        return result[0] if result is not None else ()
