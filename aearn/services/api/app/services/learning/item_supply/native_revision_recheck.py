"""Default-off ORIGINAL revision -> validation -> independent blind/six-peer owner.

Short caller transactions prepare/settle/commit; original run methods require
IDLE. Historical opinions stay in this server-side owner, never provider inputs.
510 records partial clause DATA; 509 unconditional admission hold remains intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from psycopg.pq import TransactionStatus

from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.generation_contracts import GenerationResultV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.native_revision import NativeRevisionOwner, PreparedNativeRevision
from app.services.learning.item_supply.native_revision_recheck_contracts import NativeRevisionDisputeEvidenceV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
from app.services.learning.item_supply.review_deliberation import review_disputes
from app.services.learning.item_supply.review_provider import BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort
from app.services.learning.item_supply.shared_pipeline_contracts import PreparedSharedGeneration
from app.services.learning.item_supply.shared_review import PreparedSharedReview, SharedReviewPipeline, SharedReviewResult
from app.services.learning.item_supply.shared_validation import PreparedSharedValidation, SharedValidationPipeline, SharedValidationResult
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.diagnostic_policy import ReviewBundleV3, checked_bundle
from app.services.learning.item_supply.review_contracts_v2 import ReviewBundleV2


class _RecheckClient(BoundedOpenAIReviewClient):
    """Original client/schema/one-HTTP path; only narrow the live deadline.

    complete_json rechecks bounded_timeout AFTER envelope construction, so a
    timeout computed before serialization cannot outlive the ancestor/source.
    """
    def __init__(self, settings: Any, *, profile: Any, operation_deadline_at: datetime) -> None:
        super().__init__(settings, profile=profile)
        self.operation_deadline_at = operation_deadline_at

    def bounded_timeout(self, requested: float) -> float:
        timeout = min(super().bounded_timeout(requested),
                      (self.operation_deadline_at-datetime.now(UTC)).total_seconds())
        if timeout<=0:
            raise PipelineRepositoryError("RECHECK_ORIGINAL_DEADLINE_REACHED")
        return timeout


@dataclass(frozen=True, repr=False)
class PreparedNativeRevisionRecheck:
    preparation_id: UUID
    revision: PreparedNativeRevision
    author: PreparedSharedGeneration
    author_result: GenerationResultV2
    lease: JobLeaseV1
    artifact_id: UUID
    artifact_hash: str
    lineage_hash: str
    ancestors: tuple[tuple[UUID,str], ...]
    forbidden_run_ids: frozenset[UUID]
    bundle_version: int

    def payload(self) -> dict[str, Any]:
        return {"schema_version": "native_shared_revision_recheck_preparation_v1",
            "preparation_id": str(self.preparation_id), "lineage_id": str(self.revision.preparation_id),
            "lineage_hash": self.lineage_hash, "root_id": str(self.revision.investigation.root_id),
            "lease": self.lease.model_dump(mode="json"), "artifact_id": str(self.artifact_id), "artifact_hash": self.artifact_hash,
            "context_hash": self.revision.context.context_hash,
            "original_disputes": [d.model_dump(mode="json") for d in self.revision.investigation.request.disputes],
            "ancestor_reviews": [{"receipt_id": str(i), "receipt_hash": h} for i,h in self.ancestors],
            "forbidden_run_ids": sorted(str(i) for i in self.forbidden_run_ids), "bundle_version": self.bundle_version,
            "deadline_at": self.revision.deadline_at.isoformat(), "publication_enabled": False, "blockers_discharged": False}


class NativeRevisionRecheckOwner:
    def __init__(self, revision_owner: NativeRevisionOwner, validation: SharedValidationPipeline,
                 review: SharedReviewPipeline, *, enabled: bool = False) -> None:
        if (type(revision_owner) is not NativeRevisionOwner or type(validation) is not SharedValidationPipeline
                or type(review) is not SharedReviewPipeline or revision_owner.conn is not validation.conn or review.conn is not validation.conn):
            raise PipelineRepositoryError("RECHECK_SAME_CONCRETE_ORIGINAL_OWNERS_REQUIRED")
        self.revision_owner,self.validation,self.review,self.conn,self.enabled = revision_owner,validation,review,review.conn,enabled
        self._prepared: dict[UUID,tuple[PreparedNativeRevisionRecheck,str]] = {}
        self._validations: dict[UUID,PreparedSharedValidation] = {}
        self._validation_results: dict[UUID,SharedValidationResult] = {}
        self._validation_ids: dict[UUID,UUID] = {}
        self._reviews: dict[UUID,PreparedSharedReview] = {}
        self._review_results: dict[UUID,SharedReviewResult] = {}
        self._review_ids: dict[UUID,tuple[UUID,UUID]] = {}
        self._runners: dict[UUID,RunnerPort | None] = {}

    def _guard(self) -> None:
        if not self.enabled or not self.validation.validation_enabled or not self.review.review_enabled:
            raise PipelineRepositoryError("NATIVE_REVISION_RECHECK_DISABLED")
        self.validation.artifacts.require_owner()
        row = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_revision_recheck_preparations') AS p, "
            "to_regclass('public.tutor_item_supply_shared_revision_recheck_receipts') AS r").fetchone()
        if row is None or row["p"] is None or row["r"] is None:
            raise PipelineRepositoryError("NATIVE_REVISION_RECHECK_SCHEMA_REQUIRED")

    def _ancestry(self, revision: PreparedNativeRevision) -> tuple[tuple[tuple[UUID,str], ...],frozenset[UUID],int]:
        # Immutable DB history is used ONLY to reject reused identities, not to
        # restore any provider/executor/author capability. Include every reachable
        # committed bundle, including 491-origin artifacts via lineage parent IDs.
        rows = self.conn.execute("WITH RECURSIVE history AS (SELECT parent_artifact_id AS id FROM "
            "tutor_item_supply_shared_revision_lineage WHERE id=%s UNION SELECT l.parent_artifact_id "
            "FROM tutor_item_supply_shared_revision_lineage l JOIN history h ON l.child_artifact_id=h.id) "
            "SELECT r.id,r.receipt_hash,r.payload_json,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r JOIN history h ON h.id=r.generation_artifact_id "
            "WHERE r.artifact_kind='review_bundle' ORDER BY r.id",(revision.preparation_id,)).fetchall()
        if not rows or len(rows)>64:
            raise PipelineRepositoryError("RECHECK_COMPLETE_ANCESTRAL_HISTORY_REQUIRED")
        receipts,ids,version = [],set(),1
        for row in rows:
            schema = row["payload_json"].get("schema_version")
            kind = ReviewBundleV3 if schema=="item_supply_review_bundle_v3" else ReviewBundleV2
            try:
                bundle = checked_bundle(kind.model_validate_json(json.dumps(row["payload_json"])))
            except Exception:
                raise PipelineRepositoryError("RECHECK_COMPLETE_ANCESTRAL_HISTORY_REQUIRED") from None
            if row["same_transaction"] or row["receipt_hash"] != bundle.bundle_hash:
                raise PipelineRepositoryError("RECHECK_COMMITTED_ANCESTRAL_HISTORY_REQUIRED")
            receipts.append((UUID(str(row["id"])),bundle.bundle_hash))
            ids.update((bundle.blind_solve.run.run_id,*(r.run.run_id for r in bundle.reports)))
            version = max(version,bundle.bundle_version)
        return tuple(receipts),frozenset(ids),version+1

    def _parent_solver(self, revision: PreparedNativeRevision) -> JsonBlindSolverV2:
        parent = revision.investigation.original
        owner = self.revision_owner.investigation_owner.review
        if type(owner) is not SharedReviewPipeline or owner.conn is not self.conn:
            raise PipelineRepositoryError("RECHECK_ORIGINAL_REVIEW_OWNER_REQUIRED")
        with finite_review_context(parent.source, spec=parent.spec, materials=parent.request.materials):
            _, solver, _, _ = owner._issued(parent)
        if (solver.blind_protocol != parent.blind_protocol
                or (self.review.blind_protocol is not None and self.review.blind_protocol != parent.blind_protocol)):
            raise PipelineRepositoryError("RECHECK_ORIGINAL_BLIND_PROTOCOL_REQUIRED")
        return solver

    def _issued(self, p: PreparedNativeRevisionRecheck) -> None:
        if type(p) is not PreparedNativeRevisionRecheck:
            raise PipelineRepositoryError("RECHECK_ORIGINAL_PREPARED_REQUIRED")
        entry = self._prepared.get(p.preparation_id)
        self._parent_solver(p.revision)
        parent = p.revision.investigation.original
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            if entry is None or entry[0] is not p or entry[1] != canonical_hash(p.payload()):
                raise PipelineRepositoryError("RECHECK_ORIGINAL_PREPARED_REQUIRED")

    def _current(self, p: PreparedNativeRevisionRecheck, lease: JobLeaseV1, *, committed: bool = True) -> dict[str,Any]:
        self._guard()
        self._issued(p)
        current = self.revision_owner.verified_committed_lineage(p.revision,p.author,p.author_result,lease=lease)
        row = self.conn.execute("SELECT rr.*,rr.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_revision_recheck_preparations rr WHERE rr.id=%s FOR SHARE",(p.preparation_id,)).fetchone()
        parent = p.revision.investigation.original
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            payload = p.payload()
        if (row is None or (committed and row["same_transaction"]) or row["payload_json"]!=payload
                or row["snapshot_hash"]!=canonical_hash(payload)):
            raise PipelineRepositoryError("RECHECK_COMMITTED_ORIGINAL_PREPARATION_REQUIRED")
        ancestry = self._ancestry(p.revision)
        if (current["artifact"]["id"] != p.artifact_id or current["artifact"]["artifact_hash"] != p.artifact_hash
                or current["lineage"]["snapshot_hash"] != p.lineage_hash
                or ancestry != (p.ancestors,p.forbidden_run_ids,p.bundle_version)):
            raise PipelineRepositoryError("RECHECK_CURRENT_LINEAGE_OR_HISTORY_CHANGED")
        return current

    def prepare(self, *, revision: PreparedNativeRevision, author: PreparedSharedGeneration,
                author_result: GenerationResultV2, lease: JobLeaseV1) -> PreparedNativeRevisionRecheck | None:
        self._guard()
        self._parent_solver(revision)
        current = self.revision_owner.verified_committed_lineage(revision,author,author_result,lease=lease)
        if self.validation.runtime.next_stage(lease) != "validating":
            raise PipelineRepositoryError("RECHECK_NEW_VALIDATION_STAGE_REQUIRED")
        ancestors,ids,version = self._ancestry(revision)
        p = PreparedNativeRevisionRecheck(uuid4(),revision,author,author_result,checked_model(lease,JobLeaseV1),
            current["artifact"]["id"],current["artifact"]["artifact_hash"],current["lineage"]["snapshot_hash"],ancestors,ids,version)
        parent = revision.investigation.original
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            payload = p.payload()
        row = self.conn.execute("INSERT INTO tutor_item_supply_shared_revision_recheck_preparations "
            "(id,lineage_id,root_id,job_id,generation_artifact_id,payload_json,valid_until) VALUES(%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(lineage_id) DO NOTHING RETURNING id",(p.preparation_id,revision.preparation_id,revision.investigation.root_id,
                lease.job_id,p.artifact_id,Jsonb(payload),revision.deadline_at)).fetchone()
        if row is None:
            return None
        self._prepared[p.preparation_id] = (p,canonical_hash(payload))
        return p

    def prepare_validation(self, p: PreparedNativeRevisionRecheck, *, lease: JobLeaseV1,
                           runner: RunnerPort | None = None) -> PreparedSharedValidation | None:
        current = self._current(p,lease,committed=False)
        if p.preparation_id in self._validations:
            raise PipelineRepositoryError("RECHECK_VALIDATION_ALREADY_PREPARED")
        v = self.validation.prepare_validation(lease=lease,artifact_id=p.artifact_id,spec=p.revision.spec,
            source_authority=current["authority"],runner=runner,operation_deadline_at=p.revision.deadline_at)
        if v is not None:
            self._validations[p.preparation_id],self._runners[p.preparation_id] = v,runner
        return v

    def run_validation(self, p: PreparedNativeRevisionRecheck) -> SharedValidationResult:
        self._issued(p)
        v = self._validations.get(p.preparation_id)
        if v is None or p.preparation_id in self._validation_results:
            raise PipelineRepositoryError("RECHECK_ORIGINAL_VALIDATION_PREPARED_REQUIRED")
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("RECHECK_VALIDATION_IDLE_REQUIRED")
        with self.conn.transaction():
            self._current(p,v.lease)
        result = self.validation.run_validation(v)
        self._validation_results[p.preparation_id] = result
        return result

    def settle_validation(self, p: PreparedNativeRevisionRecheck) -> None:
        self._issued(p)
        self.validation.settle_validation(self._validations[p.preparation_id],self._validation_results[p.preparation_id])

    def commit_validation(self, p: PreparedNativeRevisionRecheck) -> Any:
        v = self._validations[p.preparation_id]
        self._current(p,v.lease)
        stage = self.validation.commit_validation(v,self._validation_results[p.preparation_id])
        if stage.state=="machine_verified" and stage.validation_receipt_id is not None:
            self._validation_ids[p.preparation_id] = stage.validation_receipt_id
        return stage

    def prepare_review(self, p: PreparedNativeRevisionRecheck, *, lease: JobLeaseV1) -> PreparedSharedReview | None:
        current = self._current(p,lease)
        if p.preparation_id in self._reviews or p.preparation_id not in self._validation_ids:
            raise PipelineRepositoryError("RECHECK_ORIGINAL_COMMITTED_VALIDATION_REQUIRED")
        self.validation.verified_committed_validation(self._validations[p.preparation_id],self._validation_results[p.preparation_id],
            lease=lease,receipt_id=self._validation_ids[p.preparation_id])
        original_solver = self._parent_solver(p.revision)
        settings = self.review.settings
        if (not settings.uses_deepseek_v4_flash_responses or settings.tutor_max_output_tokens != DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
                or self.review._models != self.revision_owner.generation._models):
            raise PipelineRepositoryError("RECHECK_FORMAL_FROZEN_OUTPUT_MODEL_REQUIRED")
        timeout = min(3600.0,lease.profile.values.request_timeout_ms/1000,
            (min(lease.expires_at,lease.parent_deadline,p.revision.deadline_at)-server_clock(self.conn,datetime.now(UTC))).total_seconds())
        if timeout<=0:
            raise PipelineRepositoryError("RECHECK_ORIGINAL_DEADLINE_REACHED")
        def identity(role: str) -> ProviderIdentityV2:
            return ProviderIdentityV2(identity="deepseek.recheck."+p.preparation_id.hex+"."+role,
                provider="deepseek",model=settings.llm_model)
        kwargs = dict(profile_hash=lease.profile.profile_hash,timeout_seconds=timeout,max_output_tokens=DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS)
        operation_deadline = min(p.revision.deadline_at,self.review._review_deadline(lease))
        if original_solver._max_output_tokens != DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS:
            raise PipelineRepositoryError("RECHECK_FORMAL_FROZEN_BLIND_OUTPUT_REQUIRED")
        solver = JsonBlindSolverV2(_RecheckClient(settings,profile=lease.profile,operation_deadline_at=operation_deadline),
            identity=identity("blind"), profile_hash=lease.profile.profile_hash,
            timeout_seconds=min(timeout, original_solver._timeout_seconds),
            max_output_tokens=original_solver._max_output_tokens,
            max_input_bytes=original_solver._max_input_bytes, blind_protocol=original_solver.blind_protocol)
        reviewers = tuple(JsonReviewerV2(_RecheckClient(settings,profile=lease.profile,operation_deadline_at=operation_deadline),
            role=r,identity=identity(r.value),review_protocol="evidenced-v1",**kwargs) for r in REQUIRED_REVIEW_ROLES)
        review = self.review.prepare_independent_review(bundle_version=p.bundle_version,forbidden_run_ids=p.forbidden_run_ids,
            lease=lease,artifact_id=p.artifact_id,validation_receipt_id=self._validation_ids[p.preparation_id],spec=p.revision.spec,
            source_authority=current["authority"],solver=solver,reviewers=reviewers,runner=self._runners[p.preparation_id],
            operation_deadline_at=operation_deadline)
        if review is not None:
            self._reviews[p.preparation_id] = review
        return review

    def run_review(self, p: PreparedNativeRevisionRecheck) -> SharedReviewResult:
        self._issued(p)
        r = self._reviews.get(p.preparation_id)
        if r is None or p.preparation_id in self._review_results:
            raise PipelineRepositoryError("RECHECK_ORIGINAL_REVIEW_PREPARED_REQUIRED")
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("RECHECK_REVIEW_IDLE_REQUIRED")
        with self.conn.transaction():
            self._current(p,r.lease)
        result = self.review.run_review(r)
        self._review_results[p.preparation_id] = result
        return result

    def settle_review(self, p: PreparedNativeRevisionRecheck) -> None:
        self._issued(p)
        self.review.settle_review(self._reviews[p.preparation_id],self._review_results[p.preparation_id])

    def commit_review(self, p: PreparedNativeRevisionRecheck) -> Any:
        r = self._reviews[p.preparation_id]
        self._current(p,r.lease)
        stage = self.review.commit_review(r,self._review_results[p.preparation_id])
        if stage.blind_receipt_id is not None and stage.review_receipt_id is not None:
            self._review_ids[p.preparation_id] = (stage.blind_receipt_id,stage.review_receipt_id)
        return stage

    def persist_dispute_evidence(self, p: PreparedNativeRevisionRecheck, *, lease: JobLeaseV1) -> UUID:
        current = self._current(p,lease)
        r,result = self._reviews[p.preparation_id],self._review_results[p.preparation_id]
        if r.lease != lease or p.preparation_id not in self._review_ids:
            raise PipelineRepositoryError("RECHECK_COMPLETE_COMMITTED_NEW_REVIEW_REQUIRED")
        verified = self.review.verified_review_evidence(r,result,runner=self._runners[p.preparation_id])
        validation = self.validation.verified_committed_validation(self._validations[p.preparation_id],self._validation_results[p.preparation_id],
            lease=lease,receipt_id=self._validation_ids[p.preparation_id])
        if (verified.bundle.bundle_version != p.bundle_version or p.forbidden_run_ids &
                {verified.blind.run.run_id,*(x.run.run_id for x in verified.bundle.reports)}):
            raise PipelineRepositoryError("RECHECK_ANCESTRAL_REVIEW_IDENTITY_REUSED")
        blind_id,review_id = self._review_ids[p.preparation_id]
        for receipt_id,payload,kind in ((blind_id,verified.blind,"blind_solve"),(review_id,verified.bundle,"review_bundle")):
            row = self.conn.execute("SELECT rr.*,rr.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
                "FROM tutor_item_supply_shared_pipeline_receipts rr WHERE rr.id=%s FOR SHARE",(receipt_id,)).fetchone()
            if (row is None or row["same_transaction"] or row["artifact_kind"] != kind or row["generation_artifact_id"] != p.artifact_id
                    or row["payload_json"] != payload.model_dump(mode="json")):
                raise PipelineRepositoryError("RECHECK_COMMITTED_ORIGINAL_NEW_REVIEW_REQUIRED")
        entries = []
        scorer = self.review._result(r,result)
        static = r.inputs.static_facts
        proof = None
        if (type(scorer) is FiniteStaticBlindScorer and static is not None and validation==static.validation
                and scorer.verify(verified.blind.score,r.source) and scorer._facts(r.source)==static
                and sum(o.accepted for o in static.options)==1
                and tuple(r.source.private.content.accepted_answers)==(static.correct_option_id,)):
            proof = canonical_hash({"check":"finite_kc_unique_truth_v1","source_hash":r.source.source_hash,
                "static_facts_hash":canonical_hash(static.model_dump(mode="json")),"scorer_version":static.scorer_version,
                "validation_hash":validation.evidence_hash})
        fresh_codes = {d.safe_code for d in review_disputes(verified.bundle)}
        for d in p.revision.investigation.request.disputes:
            state,check,evidence,reason = "unsupported",None,None,"no_clause_specific_adapter"
            pointers = tuple(x.pointer for x in d.references)
            if d.safe_code in fresh_codes:
                state,reason = "unresolved","new_material_dispute_retained"
            elif (d.safe_code=="unique_answer" and proof is not None
                    and any(x.startswith("/source/public/content/options") for x in pointers)
                    and any(x.startswith("/source/private/content/accepted_answers") for x in pointers)):
                state,check,evidence,reason = "check_supported","finite_kc_unique_truth_v1",proof,"finite_property_only_not_claim_resolution"
            entries.append(NativeRevisionDisputeEvidenceV1.model_validate_json(json.dumps({"original_dispute":d.model_dump(mode="json"),
                "new_binding":r.binding.model_dump(mode="json"),"validation_receipt_id":str(self._validation_ids[p.preparation_id]),
                "validation_hash":validation.evidence_hash,"review_receipt_id":str(review_id),"review_hash":verified.bundle.bundle_hash,
                "state":state,"supported_check":check,"issuer_evidence_hash":evidence,"safe_reason":reason})))
        parent = p.revision.investigation.original
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            prep_hash = canonical_hash(p.payload())
        payload = {"schema_version":"native_shared_revision_recheck_receipt_v1","preparation_id":str(p.preparation_id),
            "preparation_hash":prep_hash,"lease":lease.model_dump(mode="json"),"artifact_id":str(p.artifact_id),
            "lineage_hash":p.lineage_hash,"validation_receipt_id":str(self._validation_ids[p.preparation_id]),
            "blind_receipt_id":str(blind_id),"review_receipt_id":str(review_id),"review_hash":verified.bundle.bundle_hash,
            "entries":[e.model_dump(mode="json") for e in entries],"new_material_disputes":[d.model_dump(mode="json") for d in review_disputes(verified.bundle)],
            "finite_unique_property_hash":proof,"publication_enabled":False,"admission_eligible":False,"blockers_discharged":False}
        row = self.conn.execute("INSERT INTO tutor_item_supply_shared_revision_recheck_receipts "
            "(id,preparation_id,root_id,job_id,generation_artifact_id,validation_receipt_id,blind_receipt_id,review_receipt_id,payload_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(preparation_id) DO NOTHING RETURNING id",
            (p.preparation_id,p.preparation_id,p.revision.investigation.root_id,lease.job_id,p.artifact_id,
                self._validation_ids[p.preparation_id],blind_id,review_id,Jsonb(payload))).fetchone()
        if row is None:
            prior = self.conn.execute("SELECT id,snapshot_hash,payload_json FROM tutor_item_supply_shared_revision_recheck_receipts WHERE preparation_id=%s",
                (p.preparation_id,)).fetchone()
            if prior is None or prior["payload_json"]!=payload or prior["snapshot_hash"]!=canonical_hash(payload):
                raise PipelineRepositoryError("RECHECK_IMMUTABLE_EVIDENCE_CONFLICT")
        return p.preparation_id
