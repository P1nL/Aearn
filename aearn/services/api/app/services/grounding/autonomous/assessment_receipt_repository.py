"""Fresh-only same-connection signed source, execution and claim authority.

A signature authenticates the independent service's real sealed oracle run.
FKs/hashes alone do not authenticate a terminal. No caller verified flag is stored.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.errors import LockNotAvailable
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.grounding.corpus_repository import CorpusRepository
from app.services.grounding.material_contracts_v2 import DraftScope
from app.services.learning.item_supply.finite_targets.contracts import TargetId

from .access_policy import AccessRequest, AuthoritySnapshot
from .assessment_contracts import ClaimEvidenceReceipt, ExecutionReceipt
from .actual_d_finite_source import ACTUAL_D_PROFILE_TARGET, ActualDFiniteSourceScope, read_actual_d_finite_scope
from .actual_d_lifecycle import current_actual_d_epoch
from .capture_provenance_composition import PinnedCaptureProvenanceComposition
from .contracts import LearningMaterialDemand, RagBudgetDelegation, Usage, revalidate
from .material_lifetime import COURSE_MATERIAL_POLICY, LEGACY_MATERIAL_POLICY, MaterialLifetimePolicy, material_lifetime, new_material_expiry
from .registered_source_provenance import PostgresCurrentCaptureProvenanceResolver
from .source_assessment import CurrentReview, DocumentCoordinate, DocumentReviewFacts, StorageUseGrant
from .source_assessment_profiles import (
    PUBLIC_PYTHON_PROFILES, PreparedSourceAssessment, PreparedSQLiteSourceAssessment, SQLiteCompanionCapture,
    PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment,
    ProfileId, SignedSourceAssessment, SourceAssessmentDenied,
    SourceAssessmentPayload, analyze_source, source_proof_hash, source_request, storage_profile_id, verify_source_assessment,
)
from .source_review_repository import CompleteCapture, QualityFinding, SourceReviewRepository

OWNED_DATABASE = "aearn_b1d_sandbox_20261001"
if TYPE_CHECKING:
    from .actual_d_private_provenance import PrivatePublicProvenance
USAGES: tuple[Usage, ...] = ("assessment_evidence",)


class AssessmentReceiptRepository:
    def __init__(self, conn: Connection[dict[str, Any]], *, service_keys: dict[str, bytes],
                 provenance: PostgresCurrentCaptureProvenanceResolver | PinnedCaptureProvenanceComposition, enabled: bool = False,
                 actual_d_private_provenance_enabled: bool = False) -> None:
        self.conn = conn
        self.enabled = enabled
        self.actual_d_private_provenance_enabled = actual_d_private_provenance_enabled
        self.service_keys = dict(service_keys)
        self.provenance = provenance
        if (type(provenance) not in (PostgresCurrentCaptureProvenanceResolver, PinnedCaptureProvenanceComposition)
                or provenance.conn is not conn or not self.service_keys
                or any(type(k) is not str or type(v) is not bytes or len(v) != 32
                       for k, v in self.service_keys.items())):
            raise SourceAssessmentDenied("SOURCE_CONFIG_DENIED")

    def require_transaction(self) -> None:
        if (not self.enabled or self.conn.autocommit
                or self.conn.info.transaction_status != TransactionStatus.INTRANS):
            raise SourceAssessmentDenied("SOURCE_GATE_CLOSED")
        row = self.conn.execute("SELECT current_database() AS name").fetchone()
        if row is None or row["name"] != OWNED_DATABASE:
            raise SourceAssessmentDenied("SOURCE_DATABASE_DENIED")
        isolation = self.conn.execute("SHOW transaction_isolation").fetchone()
        readonly = self.conn.execute("SHOW transaction_read_only").fetchone()
        if (isolation is None or isolation["transaction_isolation"] != "read committed"
                or readonly is None or readonly["transaction_read_only"] != "off"):
            raise SourceAssessmentDenied("SOURCE_TRANSACTION_DENIED")

    def _clock(self) -> datetime:
        row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if row is None or not isinstance(row["now"], datetime) or row["now"].tzinfo is None:
            raise SourceAssessmentDenied("SOURCE_CLOCK_DENIED")
        # The DB is the clock authority; a connection's display timezone is not.
        # Normalize its instant, never change expiry or renew a signed receipt.
        return row["now"].astimezone(timezone.utc)

    def _current_capture(self, capture_id: UUID, demand: LearningMaterialDemand,
                         now: datetime, lifetime_policy: MaterialLifetimePolicy = LEGACY_MATERIAL_POLICY
                         ) -> tuple[CompleteCapture, dict[str, Any], dict[str, Any], str, datetime]:
        capture, policy = SourceReviewRepository(self.conn)._capture(capture_id, "registered", now)
        root = self.conn.execute(
            "SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR SHARE",
            (policy["root_id"],),
        ).fetchone()
        provenance_digest = self.provenance.resolve(capture)
        if (not provenance_digest or root is None or demand.scope != capture.scope
                or demand.purpose != "assessment_evidence"
                or "assessment_evidence" not in policy["allowed_usages"]
                or not policy["immutable_history_allowed"]):
            raise SourceAssessmentDenied("SOURCE_AUTHORITY_DENIED")
        expiry = new_material_expiry(now=now, policy=lifetime_policy,
            policy_expires_at=policy["expires_at"], policy_retention_until=policy["policy_retention"],
            capture_retention_until=policy["retention_until"], delegation_expires_at=root["delegation_expires_at"],
            period_end=root["period_end"])
        return capture, policy, root, provenance_digest, expiry

    def prepare(self, *, capture_id: UUID, document_handle: str,
                demand: LearningMaterialDemand, profile_id: ProfileId,
                companion_capture_ids: tuple[UUID, UUID] | None = None,
                lifetime_policy: MaterialLifetimePolicy | None = None) -> PreparedSourceAssessment:
        if profile_id in ACTUAL_D_PROFILE_TARGET:
            raise SourceAssessmentDenied("SOURCE_ACTUAL_D_REPOSITORY_REQUIRED")
        return self._prepare(capture_id=capture_id, document_handle=document_handle, demand=demand,
            profile_id=profile_id, companion_capture_ids=companion_capture_ids, lifetime_policy=lifetime_policy)

    def prepare_actual_d(self, *, capture_id: UUID, document_handle: str, draft: DraftScope,
                         base_selection_handle: str, node_id: str, target_id: TargetId,
                         companion_capture_ids: tuple[UUID, UUID] | None = None
                         ) -> PreparedActualDSourceAssessment | PreparedActualDSQLiteSourceAssessment:
        """New real D scope; no caller demand, ready flag, old proof or run nonce."""
        return self._prepare_actual_d(capture_id=capture_id, document_handle=document_handle, draft=draft,
            base_selection_handle=base_selection_handle, node_id=node_id, target_id=target_id,
            companion_capture_ids=companion_capture_ids, oracle_run_id=uuid4(), allow_confirmed=False)

    def _prepare_actual_d(self, *, capture_id: UUID, document_handle: str, draft: DraftScope,
                          base_selection_handle: str, node_id: str, target_id: TargetId,
                          companion_capture_ids: tuple[UUID, UUID] | None,
                          oracle_run_id: UUID, allow_confirmed: bool
                          ) -> PreparedActualDSourceAssessment | PreparedActualDSQLiteSourceAssessment:
        self.require_transaction()
        from .actual_d_private_provenance import require_private_provenance

        require_private_provenance(self)
        try:
            # A short nested savepoint contains NOWAIT denial on current reads;
            # no connection/commit/IO is introduced or caller work committed.
            with self.conn.transaction():
                scope, demand = read_actual_d_finite_scope(self.conn, draft=draft,
                    base_selection_handle=base_selection_handle, node_id=node_id, target_id=target_id,
                    oracle_run_id=oracle_run_id, allow_confirmed=allow_confirmed)
        except (ValueError, LockNotAvailable):
            raise SourceAssessmentDenied("SOURCE_ACTUAL_D_SCOPE_STALE") from None
        profile = cast(ProfileId, next(k for k, target in ACTUAL_D_PROFILE_TARGET.items() if target == target_id))
        prepared = self._prepare(capture_id=capture_id, document_handle=document_handle, demand=demand,
            profile_id=profile, companion_capture_ids=companion_capture_ids,
            lifetime_policy=COURSE_MATERIAL_POLICY, actual_d=scope)
        if not isinstance(prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)):
            raise SourceAssessmentDenied("SOURCE_ACTUAL_D_SCOPE_REQUIRED")
        return prepared

    def _prepare(self, *, capture_id: UUID, document_handle: str,
                 demand: LearningMaterialDemand, profile_id: ProfileId,
                 companion_capture_ids: tuple[UUID, UUID] | None = None,
                 lifetime_policy: MaterialLifetimePolicy | None = None,
                 actual_d: ActualDFiniteSourceScope | None = None) -> PreparedSourceAssessment:
        self.require_transaction()
        now = self._clock()
        demand = revalidate(demand, LearningMaterialDemand)
        native_sqlite = profile_id in ("sqlite-predicate-source-v1", "sqlite-predicate-actual-d-source-v1")
        native_course = native_sqlite or profile_id in (*PUBLIC_PYTHON_PROFILES, *ACTUAL_D_PROFILE_TARGET)
        if (profile_id in ACTUAL_D_PROFILE_TARGET) != (actual_d is not None):
            raise SourceAssessmentDenied("SOURCE_ACTUAL_D_SCOPE_REQUIRED")
        if actual_d is not None:
            try:
                with self.conn.transaction():
                    current_actual_d_epoch(self.conn, user_id=UUID(actual_d.draft.user_id),
                                           expected_epoch=actual_d.user_epoch, nowait=False)
            except (ValueError, LockNotAvailable):
                raise SourceAssessmentDenied("SOURCE_ACTUAL_D_SCOPE_STALE") from None
        lifetime_policy = lifetime_policy if lifetime_policy is not None else (COURSE_MATERIAL_POLICY if native_course else LEGACY_MATERIAL_POLICY)
        material_lifetime(lifetime_policy)
        if lifetime_policy == COURSE_MATERIAL_POLICY and not native_course:
            raise SourceAssessmentDenied("SOURCE_LIFETIME_SCOPE_DENIED")
        if (native_sqlite != (companion_capture_ids is not None)
                or (native_sqlite and type(self.provenance) is not PinnedCaptureProvenanceComposition)):
            raise SourceAssessmentDenied("SOURCE_COMPANIONS_REQUIRED")
        capture, policy, root, provenance_digest, expiry = self._current_capture(capture_id, demand, now, lifetime_policy)
        companions = []
        if companion_capture_ids is not None:
            from .sqlite_predicate_source_profile import analyze_sqlite_capture

            if len(companion_capture_ids) != 2 or len({capture_id, *companion_capture_ids}) != 3:
                raise SourceAssessmentDenied("SOURCE_COMPANIONS_REQUIRED")
            roles: tuple[Literal["expression", "corefunc"], ...] = ("expression", "corefunc")
            for role, companion_id in zip(roles, companion_capture_ids, strict=True):
                c, policy_c, root_c, provenance_c, expiry_c = self._current_capture(companion_id, demand, now, lifetime_policy)
                companions.append(SQLiteCompanionCapture(role=role, capture_id=c.capture_id,
                    source_handle=c.source_handle, document_hash=c.digest, license_id=c.license_id,
                    reading_level=cast(Literal["beginner", "intermediate", "advanced"], c.reading_level),
                    provenance_digest=provenance_c, policy_id=policy_c["policy_id"],
                    policy_generation=policy_c["policy_generation"],
                    budget=RagBudgetDelegation(root_id=root_c["root_id"], delegation_id=root_c["delegation_id"],
                        generation=root_c["delegation_generation"], expires_at=expiry_c),
                    storage_receipt_id=policy_c["storage_receipt_id"], spans=analyze_sqlite_capture(c, role),
                    authority_expires_at=expiry_c))
                expiry = min(expiry, expiry_c)
        values = dict(profile_id=profile_id, capture_id=capture_id,
            source_handle=capture.source_handle, document_handle=document_handle,
            document_hash=capture.digest, license_id=capture.license_id,
            reading_level=cast(Literal["beginner", "intermediate", "advanced"], capture.reading_level),
            provenance_digest=provenance_digest,
            policy_id=policy["policy_id"], policy_generation=policy["policy_generation"],
            budget=RagBudgetDelegation(root_id=root["root_id"], delegation_id=root["delegation_id"],
                generation=root["delegation_generation"], expires_at=expiry),
            storage_receipt_id=policy["storage_receipt_id"], demand=demand,
            spans=analyze_source(capture, profile_id), prepared_at=now, authority_expires_at=expiry)
        if actual_d is not None:
            if native_sqlite:
                return PreparedActualDSQLiteSourceAssessment.model_validate({**values, "actual_d": actual_d, "companions": tuple(companions)})
            return PreparedActualDSourceAssessment.model_validate({**values, "actual_d": actual_d})
        if native_sqlite:
            return PreparedSQLiteSourceAssessment.model_validate({**values, "companions": tuple(companions)})
        return PreparedSourceAssessment.model_validate(values)

    def _verify_current(self, signed: SignedSourceAssessment, *, for_issuance: bool = False) -> tuple[SourceAssessmentPayload, CompleteCapture]:
        self.require_transaction()
        now = self._clock()
        p = verify_source_assessment(signed, service_keys=self.service_keys, now=now)
        companion_ids = ((p.prepared.companions[0].capture_id, p.prepared.companions[1].capture_id)
                         if isinstance(p.prepared, PreparedSQLiteSourceAssessment) else None)
        fresh: PreparedSourceAssessment
        if isinstance(p.prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)):
            d = p.prepared.actual_d
            try:
                with self.conn.transaction():
                    current_actual_d_epoch(self.conn, user_id=UUID(d.draft.user_id),
                                           expected_epoch=d.user_epoch, nowait=not for_issuance)
            except (ValueError, LockNotAvailable):
                raise SourceAssessmentDenied("SOURCE_ACTUAL_D_SCOPE_STALE") from None
            fresh = self._prepare_actual_d(capture_id=p.prepared.capture_id, document_handle=p.prepared.document_handle,
                draft=d.draft, base_selection_handle=d.base_selection_handle, node_id=d.node_id, target_id=d.target_id,
                companion_capture_ids=companion_ids, oracle_run_id=d.oracle_run_id, allow_confirmed=not for_issuance)
        else:
            fresh = self.prepare(capture_id=p.prepared.capture_id,
                document_handle=p.prepared.document_handle, demand=p.prepared.demand,
                profile_id=p.prepared.profile_id,
                lifetime_policy=COURSE_MATERIAL_POLICY if p.format == "aearn.rag.fresh-assessment-source.v2" else LEGACY_MATERIAL_POLICY,
                companion_capture_ids=companion_ids)
        a, b = fresh.model_dump(), p.prepared.model_dump()
        # Preparation time is historical, not a mutable renewal. Current bounds may
        # only be narrower; never move the signed expiry to extend an old grant.
        for key in ("prepared_at", "authority_expires_at", "budget"):
            a.pop(key)
            b.pop(key)
        if isinstance(fresh, PreparedSQLiteSourceAssessment) and isinstance(p.prepared, PreparedSQLiteSourceAssessment):
            for current, original in zip(a["companions"], b["companions"], strict=True):
                for binding in (current, original):
                    binding.pop("authority_expires_at")
                    binding["budget"].pop("expires_at")
        if (a != b or fresh.budget.model_dump(exclude={"expires_at"})
                != p.prepared.budget.model_dump(exclude={"expires_at"})
                or p.expires_at > fresh.authority_expires_at):
            raise SourceAssessmentDenied("SOURCE_AUTHORITY_STALE")
        capture, _ = SourceReviewRepository(self.conn)._capture(p.prepared.capture_id, "registered", self._clock())
        # Actual-D scope/source locks may outlast the shorter signed proof (or
        # companion) deadline while the primary capture remains current. Never
        # reuse the pre-wait signature clock as the final consume/insert fence.
        if isinstance(p.prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)) and not (
                p.issued_at <= self._clock() < p.expires_at):
            raise SourceAssessmentDenied("SOURCE_AUTHORITY_STALE")
        return p, capture

    def persist(self, signed: SignedSourceAssessment) -> UUID:
        """Final short transaction fence, after the independent source run/signature."""
        signed = revalidate(signed, SignedSourceAssessment)
        p, _ = self._verify_current(signed, for_issuance=True)
        q, proof_hash = p.prepared, source_proof_hash(signed)
        old = self.conn.execute(
            "SELECT * FROM rag_assessment_source_evidence WHERE id=%s FOR SHARE", (p.evidence_id,),
        ).fetchone()
        if old is not None:
            if old["proof_hash"] != proof_hash or old["revoked_at"] is not None:
                raise SourceAssessmentDenied("SOURCE_REPLAY_CONFLICT")
            self._load(p.evidence_id)
            return p.admission_id
        with self.conn.transaction():
            private = isinstance(q, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment))
            private_columns = ",private_user_id,private_epoch" if private else ""
            private_placeholders = ",%s,%s" if private else ""
            private_values = ((UUID(q.actual_d.draft.user_id), q.actual_d.user_epoch)
                              if isinstance(q, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)) else ())
            self.conn.execute(
                f"""INSERT INTO rag_assessment_source_evidence
                   (id,capture_id,source_handle,document_handle,document_hash,policy_id,policy_generation,
                    root_id,profile_id,demand_hash,claim_hash,execution_handle,claim_handle,
                    service_key_id,signed_proof,proof_hash,terminal_hash,issued_at,expires_at{private_columns})
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s{private_placeholders})""",
                (p.evidence_id,q.capture_id,q.source_handle,q.document_handle,q.document_hash,q.policy_id,
                 q.policy_generation,q.budget.root_id,storage_profile_id(q),q.demand.demand_hash,q.claim_hash,
                 p.execution_handle,p.claim_handle,signed.service_key_id,Jsonb(signed.model_dump(mode="json")),
                 proof_hash,canonical_hash(p.terminal),p.issued_at,p.expires_at,*private_values),
            )
            family = "family.python" if q.profile_id.startswith("python-") else "family.sqlite"
            self.conn.execute(
                """INSERT INTO rag_source_reviews
                   (id,registered_capture_id,source_handle,document_handle,subject_id,subject_version,
                    facets,document_revision,document_hash,lineage_family,origin,reading_level,
                    status,quality_code,reading_fit,version_fit,technical_status,conflict_status,
                    known_error,covered_facets,quality_evidence_hash,storage_receipt_id,license_id,
                    allowed_usages,immutable_history_allowed,policy_id,policy_generation,root_id,
                    review_receipt_hash,reviewed_at,assessment_evidence_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'official',%s,'reviewed','QUALIFIED',
                    'suitable','current','correct','resolved','absent',%s,%s,%s,%s,%s,true,%s,%s,%s,%s,%s,%s)""",
                (p.review_id,q.capture_id,q.source_handle,q.document_handle,q.demand.scope.subject_id,
                 q.demand.scope.subject_version,list(q.demand.scope.facets),q.document_hash,q.document_hash,
                 family,q.reading_level,list(q.demand.scope.facets),proof_hash,q.storage_receipt_id,
                 q.license_id,list(USAGES),q.policy_id,q.policy_generation,q.budget.root_id,proof_hash,
                 p.issued_at,p.evidence_id),
            )
            self.conn.execute(
                """INSERT INTO rag_source_admissions
                   (id,review_id,receipt_handle,allowed_usages,policy_generation,receipt_hash)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (p.admission_id,p.review_id,p.admission_handle,list(USAGES),q.policy_generation,proof_hash),
            )
            _, _, applicability = source_request(q.profile_id)
            self.conn.execute(
                """INSERT INTO rag_source_claim_receipts
                   (id,admission_id,claim_hash,demand_hash,subject_id,subject_version,
                    source_document_hash,applicability_hash,method,execution_receipt_handle,
                    verification_receipt_hash,verified_at,assessment_evidence_id,receipt_handle,
                    applicability,scope_facets,execution_scope_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'isolated_execution',%s,%s,%s,%s,%s,%s,%s,%s)""",
                (p.claim_id,p.admission_id,q.claim_hash,q.demand.demand_hash,q.demand.scope.subject_id,
                 q.demand.scope.subject_version,q.document_hash,hashlib.sha256(applicability.encode()).hexdigest(),
                 p.execution_handle,proof_hash,p.issued_at,p.evidence_id,p.claim_handle,applicability,
                 list(q.demand.scope.facets),Jsonb(q.execution_scope.model_dump(mode="json"))),
            )
            self._load(p.evidence_id)
        return p.admission_id

    def _load(self, evidence_id: UUID) -> tuple[SourceAssessmentPayload, CompleteCapture, dict[str, Any]]:
        self.require_transaction()
        row = self.conn.execute(
            """SELECT e.*,r.id AS review_id,r.review_receipt_hash,r.quality_evidence_hash,
                r.storage_receipt_id,r.license_id,r.origin,r.reading_level,r.facets,r.covered_facets,
                r.subject_id,r.subject_version,r.document_revision,r.lineage_family,r.status,r.quality_code,
                r.reading_fit,r.version_fit,r.technical_status,r.conflict_status,r.known_error,
                r.allowed_usages AS review_usages,r.immutable_history_allowed,
                a.id AS admission_id,a.receipt_handle,a.allowed_usages AS admission_usages,
                a.policy_generation AS admission_generation,a.active,a.revoked_at AS admission_revoked,
                c.id AS claim_id,c.receipt_handle AS stored_claim_handle,c.claim_hash AS stored_claim_hash,
                c.demand_hash AS stored_demand_hash,c.applicability,c.applicability_hash,c.execution_scope_json,
                c.scope_facets,c.source_document_hash,c.execution_receipt_handle,c.verification_receipt_hash,
                c.method,c.revoked_at AS claim_revoked
              FROM rag_assessment_source_evidence e
              JOIN rag_source_reviews r ON r.assessment_evidence_id=e.id
              JOIN rag_source_admissions a ON a.review_id=r.id
              JOIN rag_source_claim_receipts c ON c.assessment_evidence_id=e.id AND c.admission_id=a.id
              WHERE e.id=%s FOR SHARE OF e,r,a,c""", (evidence_id,),
        ).fetchone()
        if row is None or row["revoked_at"] is not None:
            raise SourceAssessmentDenied("SOURCE_EVIDENCE_MISSING")
        signed = SignedSourceAssessment.model_validate_json(json.dumps(row["signed_proof"]))
        p, capture = self._verify_current(signed)
        q = p.prepared
        if isinstance(q, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)) and (
                row.get("private_user_id") != UUID(q.actual_d.draft.user_id) or row.get("private_epoch") != q.actual_d.user_epoch):
            raise SourceAssessmentDenied("SOURCE_BINDING_DENIED")
        _, _, applicability = source_request(q.profile_id)
        checks = {
            "id": p.evidence_id, "capture_id": q.capture_id, "source_handle": q.source_handle,
            "document_handle": q.document_handle, "document_hash": q.document_hash,
            "policy_id": q.policy_id, "policy_generation": q.policy_generation,
            "root_id": q.budget.root_id, "profile_id": storage_profile_id(q), "demand_hash": q.demand.demand_hash,
            "claim_hash": q.claim_hash, "execution_handle": p.execution_handle,
            "claim_handle": p.claim_handle, "service_key_id": signed.service_key_id,
            "proof_hash": source_proof_hash(signed), "terminal_hash": canonical_hash(p.terminal),
            "issued_at": p.issued_at, "expires_at": p.expires_at,
            "review_id": p.review_id, "admission_id": p.admission_id, "claim_id": p.claim_id,
            "review_receipt_hash": source_proof_hash(signed), "quality_evidence_hash": source_proof_hash(signed),
            "storage_receipt_id": q.storage_receipt_id, "license_id": q.license_id,
            "origin": "official", "reading_level": q.reading_level,
            "subject_id": q.demand.scope.subject_id, "subject_version": q.demand.scope.subject_version,
            "document_revision": q.document_hash, "status": "reviewed", "quality_code": "QUALIFIED",
            "reading_fit": "suitable", "version_fit": "current", "technical_status": "correct",
            "conflict_status": "resolved", "known_error": "absent", "immutable_history_allowed": True,
            "receipt_handle": p.admission_handle, "admission_generation": q.policy_generation, "active": True,
            "admission_revoked": None, "claim_revoked": None, "stored_claim_handle": p.claim_handle,
            "stored_claim_hash": q.claim_hash, "stored_demand_hash": q.demand.demand_hash,
            "applicability": applicability, "applicability_hash": hashlib.sha256(applicability.encode()).hexdigest(),
            "source_document_hash": q.document_hash, "execution_receipt_handle": p.execution_handle,
            "verification_receipt_hash": source_proof_hash(signed), "method": "isolated_execution",
            "execution_scope_json": q.execution_scope.model_dump(mode="json"),
        }
        if (any(row[key] != value for key,value in checks.items())
                or tuple(row["facets"]) != q.demand.scope.facets
                or tuple(row["covered_facets"]) != q.demand.scope.facets
                or tuple(row["scope_facets"]) != q.demand.scope.facets
                or tuple(row["review_usages"]) != USAGES or tuple(row["admission_usages"]) != USAGES):
            raise SourceAssessmentDenied("SOURCE_BINDING_DENIED")
        return p,capture,row

    def _find(self, handle: str, *, execution: bool = False) -> tuple[SourceAssessmentPayload, CompleteCapture, dict[str, Any]]:
        self.require_transaction()
        column = "execution_handle" if execution else "claim_handle"
        row = self.conn.execute(
            f"SELECT id FROM rag_assessment_source_evidence WHERE {column}=%s FOR SHARE", (handle,),
        ).fetchone()
        if row is None:
            raise SourceAssessmentDenied("SOURCE_EVIDENCE_MISSING")
        return self._load(row["id"])

    def _lock_active_corpus(self, handle: str, *, execution: bool = False, preparation_owner: object | None = None) -> None:
        """Established version -> proof/source/root -> active pointer lock order.

        The first handle lookup is identity-only, deliberately unlocked. Mutable
        active authority is reread under the final pointer fence in _active.
        """
        self.require_transaction()
        if self.is_actual_d_handle(handle, execution=execution):
            self.private_provenance(handle, execution=execution, preparation_owner=preparation_owner)
            return
        column = "execution_handle" if execution else "claim_handle"
        rows = self.conn.execute(
            f"""SELECT v.id FROM grounding_corpus_versions v
                JOIN rag_corpus_admission_links l ON l.corpus_id=v.id
                JOIN rag_source_admissions a ON a.id=l.admission_id
                JOIN rag_source_reviews r ON r.id=a.review_id
                JOIN rag_assessment_source_evidence e ON e.id=r.assessment_evidence_id
                WHERE e.{column}=%s AND v.state='published'
                ORDER BY v.created_at DESC LIMIT 3""", (handle,),
        ).fetchall()
        repo = CorpusRepository(self.conn)
        for row in rows:
            version = repo.version(row["id"],for_update=True)
            active = repo.active(version.subject_id)
            if active is not None and active.corpus_id == version.corpus_id and version.state == "published":
                return
        raise SourceAssessmentDenied("SOURCE_CORPUS_STALE")

    def _active(self, p: SourceAssessmentPayload, capture: CompleteCapture, *, preparation_owner: object | None = None) -> None:
        if isinstance(p.prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)):
            self.private_provenance(p.claim_handle,preparation_owner=preparation_owner)
            return
        rows = self.conn.execute(
            """SELECT c.content,c.chunk_hash,c.facets_json,v.subject_id,v.subject_version,
                      v.state,v.summary_hash,r.summary_hash AS receipt_summary,l.document_hash
               FROM grounding_corpus_versions v
               JOIN grounding_active_corpora active ON active.corpus_version_id=v.id
               JOIN rag_corpus_validation_receipts r ON r.corpus_id=v.id
               JOIN rag_corpus_admission_links l ON l.corpus_id=v.id
               JOIN grounding_corpus_chunks c ON c.corpus_version_id=v.id AND c.document_id=l.document_id
               WHERE l.admission_id=%s AND l.document_id=%s AND l.source_id=%s
               FOR SHARE OF v,active,r,l,c""",
            (p.admission_id,p.prepared.document_handle,p.prepared.source_handle),
        ).fetchall()
        excerpts = self.excerpts(p,capture)
        if (isinstance(p.prepared, PreparedSQLiteSourceAssessment)
                and {row["content"] for row in rows} != set(excerpts)):
            raise SourceAssessmentDenied("SOURCE_CORPUS_STALE")
        if (not rows or any(row["state"] != "published" or not row["summary_hash"]
                or row["summary_hash"] != row["receipt_summary"]
                or row["document_hash"] != p.prepared.document_hash
                or row["subject_id"] != p.prepared.demand.scope.subject_id
                or row["subject_version"] != p.prepared.demand.scope.subject_version
                or tuple(row["facets_json"]) != p.prepared.demand.scope.facets
                or row["content"] not in excerpts
                or row["chunk_hash"] != hashlib.sha256(row["content"].encode()).hexdigest()
                for row in rows)):
            raise SourceAssessmentDenied("SOURCE_CORPUS_STALE")

    @staticmethod
    def excerpts(p: SourceAssessmentPayload, capture: CompleteCapture) -> tuple[str, ...]:
        return tuple(capture.body[s.start_byte:s.end_byte].decode("utf-8") for s in p.prepared.spans)

    def is_actual_d_handle(self, handle: str, *, execution: bool = False) -> bool:
        from .actual_d_private_provenance import actual_handle

        return actual_handle(self, handle, execution=execution)

    def private_provenance(self, handle: str, *, execution: bool = False, draft: DraftScope | None = None,
                           node_id: str | None = None, goal_hash: str | None = None,
                           preparation_owner: object | None = None) -> PrivatePublicProvenance:
        from .actual_d_private_provenance import reconstruct_private_provenance

        return reconstruct_private_provenance(self, handle, execution=execution, draft=draft, node_id=node_id, goal_hash=goal_hash,preparation_owner=preparation_owner)

    def resolve_review(self, source_handle: str, document_handle: str) -> tuple[CurrentReview, tuple[str, ...]] | None:
        try:
            self.require_transaction()
            row = self.conn.execute(
                "SELECT id FROM rag_assessment_source_evidence WHERE source_handle=%s AND document_handle=%s FOR SHARE",
                (source_handle,document_handle),
            ).fetchone()
            if row is None:
                return None
            p,capture,r = self._load(row["id"])
            q = p.prepared
            coordinate = DocumentCoordinate(scope=q.demand.scope, source_handle=q.source_handle,
                document_handle=q.document_handle, document_revision=q.document_hash, document_hash=q.document_hash)
            facts = DocumentReviewFacts(coordinate=coordinate, review_id=p.review_id,
                registered_capture_id=q.capture_id, review_receipt_hash=r["review_receipt_hash"],
                quality_code="QUALIFIED", license_id=q.license_id, policy_id=q.policy_id,
                policy_generation=q.policy_generation, root_id=q.budget.root_id, immutable_history_allowed=True,
                allowed_usages=USAGES, lineage_family=r["lineage_family"], origin="official",
                reading_level=q.reading_level, reading_fit="suitable", version_fit="current",
                technical_status="correct", conflict_status="resolved", known_error="absent",
                covered_facets=q.demand.scope.facets, status="reviewed")
            grant = StorageUseGrant(coordinate=coordinate,review_id=p.review_id,active=True,revoked=False,
                storage_receipt_id=q.storage_receipt_id,admission_receipt_id=p.admission_handle,
                policy_generation=q.policy_generation,license_status="granted",retained_until=p.expires_at,
                allowed_usages=USAGES)
            return CurrentReview(facts=facts,grant=grant,revoked=False),self.excerpts(p,capture)
        except Exception:
            return None

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        # C legacy callers cannot use this interface to upgrade an unpersisted proof.
        try:
            self.require_transaction()
            rows = self.conn.execute(
                "SELECT id FROM rag_assessment_source_evidence WHERE capture_id=%s LIMIT 2 FOR SHARE", (capture.capture_id,),
            ).fetchall()
            # This legacy capture-only port cannot choose a frozen demand.
            # Exact document/claim ports resolve their signed evidence separately.
            if len(rows) != 1:
                raise SourceAssessmentDenied("SOURCE_EVIDENCE_MISSING")
            p,current,evidence = self._load(rows[0]["id"])
            if current != capture:
                raise SourceAssessmentDenied("SOURCE_BINDING_DENIED")
            family = "family.python" if p.prepared.profile_id.startswith("python-") else "family.sqlite"
            return QualityFinding("production","current","suitable","correct","resolved","absent",
                capture.scope.facets,family,evidence["proof_hash"])
        except Exception:
            return QualityFinding("offline_protocol_only","unknown","unknown","unknown","unknown",
                "unknown",(),"family.unverified","0"*64)

    def reviewed_usages(self, capture: CompleteCapture) -> tuple[Usage, ...]:
        return USAGES if self.verify(capture).mode == "production" else ()

    def approved_excerpts(self, capture: CompleteCapture) -> tuple[str, ...]:
        scoped = self.resolve_review(capture.source_handle, self._document_for(capture.capture_id))
        return scoped[1] if scoped is not None else ()

    def _capture_source(self, capture_id: UUID) -> str:
        self.require_transaction()
        # Source identity belongs to the unique capture/policy, not an arbitrary
        # one of its demand-specific assessment proofs.
        row = self.conn.execute(
            "SELECT p.source_handle FROM rag_registered_source_captures c "
            "JOIN rag_registered_source_policies p ON p.policy_id=c.policy_id AND p.generation=c.generation "
            "WHERE c.id=%s FOR SHARE OF c,p", (capture_id,),
        ).fetchone()
        return row["source_handle"] if row else ""

    def _document_for(self, capture_id: UUID) -> str:
        self.require_transaction()
        rows = self.conn.execute(
            "SELECT document_handle FROM rag_assessment_source_evidence WHERE capture_id=%s LIMIT 2 FOR SHARE", (capture_id,),
        ).fetchall()
        return rows[0]["document_handle"] if len(rows) == 1 else ""


class PostgresAssessmentClaimResolver:
    def __init__(self, repository: AssessmentReceiptRepository, *, preparation_owner: object | None = None) -> None:
        self.repository = repository
        self.conn = repository.conn
        self.preparation_owner = preparation_owner

    def resolve(self, receipt_id: str) -> ClaimEvidenceReceipt | None:
        try:
            if self.preparation_owner is None:
                self.repository._lock_active_corpus(receipt_id)
            else:
                self.repository._lock_active_corpus(receipt_id,preparation_owner=self.preparation_owner)
            p,capture,r = self.repository._find(receipt_id)
            if self.preparation_owner is None:
                self.repository._active(p,capture)
            else:
                self.repository._active(p,capture,preparation_owner=self.preparation_owner)
            q = p.prepared
            translation = self.repository.private_provenance(receipt_id,preparation_owner=self.preparation_owner) if self.repository.is_actual_d_handle(receipt_id) else None
            carrier = translation.public if translation is not None else p
            return ClaimEvidenceReceipt(receipt_id=p.claim_handle,demand_hash=q.demand.demand_hash,
                purpose="assessment_evidence",admission_receipt_id=carrier.admission_handle,claim_hash=q.claim_hash,
                scope=q.demand.scope,source_handle=q.source_handle,document_handle=carrier.prepared.document_handle,
                document_revision=q.document_hash,document_hash=q.document_hash,applicability=r["applicability"],
                method="isolated_execution",execution_receipt_id=p.execution_handle,
                execution_scope=q.execution_scope,verified=True,revoked=False)
        except Exception:
            return None


class PostgresAssessmentExecutionResolver:
    def __init__(self, repository: AssessmentReceiptRepository, *, preparation_owner: object | None = None) -> None:
        self.repository = repository
        self.conn = repository.conn
        self.preparation_owner = preparation_owner

    def resolve(self, receipt_id: str) -> ExecutionReceipt | None:
        try:
            if self.preparation_owner is None:
                self.repository._lock_active_corpus(receipt_id,execution=True)
            else:
                self.repository._lock_active_corpus(receipt_id,execution=True,preparation_owner=self.preparation_owner)
            p,capture,_ = self.repository._find(receipt_id,execution=True)
            if self.preparation_owner is None:
                self.repository._active(p,capture)
            else:
                self.repository._active(p,capture,preparation_owner=self.preparation_owner)
            q = p.prepared
            translation = self.repository.private_provenance(receipt_id,execution=True,preparation_owner=self.preparation_owner) if self.repository.is_actual_d_handle(receipt_id,execution=True) else None
            carrier = translation.public if translation is not None else p
            return ExecutionReceipt(receipt_id=p.execution_handle,claim_hash=q.claim_hash,
                demand_hash=q.demand.demand_hash,scope=q.demand.scope,source_handle=q.source_handle,
                document_handle=carrier.prepared.document_handle,document_revision=q.document_hash,document_hash=q.document_hash,
                execution_scope=q.execution_scope,verified=True,revoked=False)
        except Exception:
            return None


class PostgresAssessmentConsumeAuthority:
    """Actor/demand from independently signed fresh evidence, never request authority."""
    def __init__(self, repository: AssessmentReceiptRepository, *, preparation_owner: object | None = None) -> None:
        self.repository = repository
        self.conn = repository.conn
        self.preparation_owner = preparation_owner

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot | None:
        try:
            self.repository.require_transaction()
            rows = self.conn.execute(
                "SELECT id,claim_handle FROM rag_assessment_source_evidence "
                "WHERE demand_hash=%s AND policy_id=%s AND policy_generation=%s AND root_id=%s "
                "AND revoked_at IS NULL AND issued_at<=clock_timestamp() AND expires_at>clock_timestamp() "
                "ORDER BY id LIMIT 3",
                (request.demand_hash,request.policy_id,request.policy_generation,request.budget.root_id),
            ).fetchall()
            if len(rows) != 1:
                return None
            if self.preparation_owner is None:
                self.repository._lock_active_corpus(rows[0]["claim_handle"])
            else:
                self.repository._lock_active_corpus(rows[0]["claim_handle"],preparation_owner=self.preparation_owner)
            p,capture,_ = self.repository._load(rows[0]["id"])
            if self.preparation_owner is None:
                self.repository._active(p,capture)
            else:
                self.repository._active(p,capture,preparation_owner=self.preparation_owner)
            q = p.prepared
            expected = AccessRequest(demand_hash=q.demand.demand_hash,scope=q.demand.scope,
                purpose="assessment_evidence",actor_id=q.consume_actor,action="consume",policy_id=q.policy_id,
                policy_generation=q.policy_generation,budget=q.budget)
            if request != expected:
                return None
            return AuthoritySnapshot(demand=q.demand,demand_hash=q.demand.demand_hash,scope=q.demand.scope,
                purpose="assessment_evidence",actor_id=q.consume_actor,allowed_actions=("consume",),policy_id=q.policy_id,
                policy_generation=q.policy_generation,budget=q.budget,budget_active=True,authorized=True)
        except Exception:
            return None
