"""Default-off concrete native investigation owner, original shared writer only.

Caller commits prepare, run is IDLE, caller separately commits UNKNOWN settle,
then persist in a fresh short transaction. No checkpoint, facts or publication.
Persisted rows are audit DATA and cannot rehydrate the in-process capabilities.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
from app.services.learning.item_bank.contracts import LearningItemReviewRole, canonical_hash
from app.services.learning.item_supply.diagnostic_policy import checked_bundle
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.native_review_investigation_contracts import (
    InvestigationProtocol, NativeReviewInvestigationInputV1, NativeReviewInvestigationReportV1,
    checked_investigation_protocol, investigation_prompt_version,
)
from app.services.learning.item_supply.native_review_investigation_provider import NativeReviewInvestigator
from app.services.learning.item_supply.persistent_pack_repair import (
    PROTOCOL as PERSISTENT_PROTOCOL, PROMPT_VERSION as PERSISTENT_PROMPT,
    PersistentCloneFindingV1, PersistentInvestigationInputV1,
    PersistentInvestigationReportV1, PersistentInvestigationSender,
)
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.private_investigation_diagnostics import (
    PrivateInvestigationAudit, PrivateInvestigationAuditSink,
)
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2, ReviewInputV2
from app.services.learning.item_supply.review_deliberation import review_disputes
from app.services.learning.item_supply.review_observability import ReviewFailureObservation, observe_review_failure
from app.services.learning.item_supply.review_protocol import make_review_request, report_protocol, verify_review_report
from app.services.learning.item_supply.review_provider import AutonomousReviewError
from app.services.learning.item_supply.shared_review import PreparedSharedReview, SharedReviewPipeline, SharedReviewResult
from app.services.learning.item_supply.storage_contracts import checked_model


@dataclass(frozen=True, repr=False)
class PreparedNativeReviewInvestigation:
    preparation_id: UUID
    root_id: UUID
    lease: JobLeaseV1
    original: PreparedSharedReview
    original_result: SharedReviewResult
    blind_receipt_id: UUID
    review_receipt_id: UUID
    continuation_binding_hash: str | None
    reservation_id: UUID
    request: NativeReviewInvestigationInputV1 | PersistentInvestigationInputV1
    identity: ProviderIdentityV2
    resources: ResourceAmounts
    source_deadlines: tuple[tuple[str, str, datetime], ...]
    deadline_at: datetime
    timeout_seconds: float
    persistent_phase: Any = field(default=None, repr=False)

    @property
    def reservation_key(self) -> str:
        return "investigate." + self.original.artifact_id.hex + "." + self.review_receipt_id.hex

    def payload(self) -> dict[str, Any]:
        payload = {"schema_version": "native_shared_review_investigation_preparation_v1",
            "preparation_id": str(self.preparation_id), "root_id": str(self.root_id),
            "lease": self.lease.model_dump(mode="json"), "generation_artifact_id": str(self.original.artifact_id),
            "artifact_hash": self.original.artifact_hash, "validation_receipt_id": str(self.original.validation_receipt_id),
            "blind_receipt_id": str(self.blind_receipt_id), "review_receipt_id": str(self.review_receipt_id),
            "review_receipt_hash": self.request.review_receipt_hash,
            "original_review_reservation_id": str(self.original.reservation_id),
            "continuation_binding_hash": self.continuation_binding_hash,
            "reservation_id": str(self.reservation_id), "reservation_key": self.reservation_key,
            "request_hash": self.request.input_hash, "request_payload": self.request.input_payload,
            "identity": self.identity.model_dump(mode="json"), "resources": self.resources.model_dump(mode="json"),
            "source_deadlines": [{"binding_digest": b, "claim_receipt_id": c, "retained_until": t.isoformat()}
                for b,c,t in self.source_deadlines], "deadline_at": self.deadline_at.isoformat(),
            "timeout_seconds": self.timeout_seconds, "publication_enabled": False, "admission_eligible": False}
        if self.persistent_phase is not None:
            payload["persistent_frame"]={"schema_version":"persistent_normal_investigation_frame_v1",
                "phase":self.persistent_phase.record.model_dump(mode="json"),
                "original_review_frame":self.original.persistent_committed_frame}
        return payload


@dataclass(frozen=True, repr=False)
class NativeReviewInvestigationRun:
    preparation_id: UUID
    reservation_id: UUID
    report: NativeReviewInvestigationReportV1 | PersistentInvestigationReportV1 | None
    safe_reason: str
    observation: ReviewFailureObservation | None = field(default=None, repr=False)

    def payload(self, p: PreparedNativeReviewInvestigation) -> dict[str, Any]:
        return {"schema_version": "native_shared_review_investigation_receipt_v1",
            "preparation_id": str(self.preparation_id), "reservation_id": str(self.reservation_id),
            "preparation_hash": canonical_hash(p.payload()), "request_hash": p.request.input_hash,
            "review_receipt_id": str(p.review_receipt_id), "review_receipt_hash": p.request.review_receipt_hash,
            "disputes": [d.model_dump(mode="json") for d in p.request.disputes],
            "report": None if self.report is None else self.report.model_dump(mode="json"),
            "observation": None if self.observation is None else self.observation.payload(),
            "safe_reason": self.safe_reason, "state": "investigation_pending_revision_owner",
            "usage_state": "unknown", "blockers_discharged": False,
            "publication_enabled": False, "admission_eligible": False}


class NativeReviewInvestigationOwner:
    def __init__(self, review: SharedReviewPipeline, *, enabled: bool = False,
                 protocol: InvestigationProtocol = "legacy-v1",
                 private_investigation_audit_sink: PrivateInvestigationAuditSink | None = None) -> None:
        if type(review) is not SharedReviewPipeline:
            raise PipelineRepositoryError("INVESTIGATION_ORIGINAL_SHARED_OWNER_REQUIRED")
        self.review, self.conn, self.enabled = review, review.conn, enabled
        self.protocol = checked_investigation_protocol(protocol)
        if private_investigation_audit_sink is not None and not callable(private_investigation_audit_sink):
            raise ValueError("private investigation sink must be callable")
        self._audit_sink = private_investigation_audit_sink
        self.budget = review.budget
        self._prepared: dict[UUID, tuple[PreparedNativeReviewInvestigation, str, Any, Any]] = {}
        self._runs: dict[UUID, tuple[NativeReviewInvestigationRun, str]] = {}
        self._started: set[UUID] = set()
        # Process-only protocol/full-envelope seals. No change to 508 payloads.
        self._sender_seals: dict[UUID, tuple[Any, str]] = {}
        self._audits: dict[UUID, PrivateInvestigationAudit] = {}
        self._persistent_pairs: dict[UUID, dict[UUID, Any]] = {}
        self._committed_revision_proofs: dict[UUID, tuple[Any, str]] = {}

    def private_audit_status(self, p: PreparedNativeReviewInvestigation) -> Mapping[str, object]:
        self._issued(p)
        audit = self._audits.get(p.preparation_id)
        return ({"enabled": False, "attempted": 0, "written": 0, "failed": 0,
                 "data_only": True, "acceptance_asserted": False} if audit is None else audit.status())

    def _guard(self) -> datetime:
        if not self.enabled or not self.review.review_enabled:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_DISABLED")
        self.review.artifacts.require_owner()
        row = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_review_investigation_preparations') AS p, "
            "to_regclass('public.tutor_item_supply_shared_review_investigation_receipts') AS r, "
            "to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()') AS guard").fetchone()
        if row is None or row["p"] is None or row["r"] is None or row["guard"] is None:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_SCHEMA_REQUIRED")
        if checked_investigation_protocol(self.protocol) == "scalar-evidence-v2":
            capability = self.conn.execute("SELECT pg_get_functiondef("
                "to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()')) AS definition").fetchone()
            predicate = "(report->'run'->>'prompt_version' IS NULL OR report->'run'->>'prompt_version' NOT IN " \
                "('native-shared-review-investigation-v1', 'native-shared-review-investigation-v2'))"
            if (capability is None or not isinstance(capability["definition"], str)
                    or predicate not in " ".join(capability["definition"].split())):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_V2_INSTALLED_GUARD_REQUIRED")
        return server_clock(self.conn, datetime.now(UTC))

    def _original(self, original: PreparedSharedReview, result: SharedReviewResult, lease: JobLeaseV1,
                  review_receipt_id: UUID) -> tuple[dict[str, Any], dict[str, Any], UUID, tuple[tuple[str, str, datetime], ...]]:
        if original.persistent_committed_frame is not None:
            return self._committed_original(original,result,lease,review_receipt_id)
        now = self._guard()
        authority, solver, reviewers, _ = self.review._issued(original)
        scorer = self.review._result(original, result)
        lease = checked_model(lease, JobLeaseV1)
        if (lease.visibility != "public" or lease.owner_id is not None or lease.owner_epoch is not None
                or (lease.job_id, lease.generation, lease.profile, lease.lease_owner) != (
                    original.lease.job_id, original.lease.generation, original.lease.profile, original.lease.lease_owner)
                or lease.state_version < original.lease.state_version
                or self.review.runtime.next_stage(lease) not in {"reviewing", "investigating"}
                or lease.profile.values.discussion_rounds < 2 or lease.profile.values.investigation_rounds < 1):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_CURRENT_STAGE_PROFILE_REQUIRED")
        # Original p has an older state_version after a legitimate checkpoint;
        # validate current operation via _load, NEVER manufacture a checkpoint.
        a, source, request, validation = self.review._load(lease=lease, artifact_id=original.artifact_id,
            validation_receipt_id=original.validation_receipt_id, spec=original.spec, authority=authority,
            allowed_stages=("reviewing", "investigating"))
        meta = self.review.artifacts.context(lease, now=now)
        if self.review._identities(lease, solver, reviewers) != original.provider_identities:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_REVIEW_BINDINGS_CHANGED")
        if ((source, request, validation, a["artifact_hash"]) != (
                original.source, original.request, original.validation, original.artifact_hash)
                or self.review.artifacts.generation_policy(lease, request, now=now).policy_hash != original.binding.policy_hash):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_SOURCE_CHANGED")
        if result.bundle is None or result.blind is None:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMPLETE_REVIEW_REQUIRED")
        bundle = checked_bundle(result.bundle)
        if (bundle.binding != original.binding or bundle.blind_solve != result.blind
                or bundle.author_identity != original.author_identity
                or tuple(r.run.provider_identity for r in bundle.reports) != original.provider_identities[1:]
                or result.blind.run.provider_identity != original.provider_identities[0]
                or not scorer.verify(result.blind.score, original.source)):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_REVIEW_ISSUER_REQUIRED")
        with finite_review_context(source, spec=original.spec, materials=request.materials):
            for report in bundle.reports:
                if report_protocol(report) != original.review_protocol:
                    raise PipelineRepositoryError("NATIVE_INVESTIGATION_REVIEW_PROTOCOL_CHANGED")
                verify_review_report(report, make_review_request(source, binding=original.binding,
                    validation_receipt=validation, role=report.role, protocol=original.review_protocol))
        row = self.conn.execute("SELECT r.*,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.id=%s FOR SHARE", (review_receipt_id,)).fetchone()
        if (row is None or row["same_transaction"] or row["artifact_kind"] != "review_bundle"
                or row["job_id"] != lease.job_id or row["lease_generation"] != lease.generation
                or row["lease_owner"] != lease.lease_owner or row["generation_artifact_id"] != original.artifact_id
                or row["artifact_key"] != "review_bundle."+original.reservation_id.hex
                or row["receipt_hash"] != bundle.bundle_hash or row["payload_json"] != bundle.model_dump(mode="json")):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_ORIGINAL_BUNDLE_REQUIRED")
        blind = self.conn.execute("SELECT r.id,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.job_id=%s AND r.lease_generation=%s "
            "AND r.generation_artifact_id=%s AND r.artifact_kind='blind_solve' AND r.receipt_hash=%s "
            "AND r.payload_json=%s AND r.artifact_key=%s", (lease.job_id, lease.generation, original.artifact_id,
                result.blind.receipt_hash, Jsonb(result.blind.model_dump(mode="json")), "blind_solve."+original.reservation_id.hex)).fetchall()
        if len(blind) != 1 or blind[0]["same_transaction"]:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_BLIND_REQUIRED")
        review_usage = self.conn.execute("SELECT s.*,s.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=%s AND s.settlement_key=%s",
            (original.reservation_id, "review."+original.artifact_id.hex)).fetchone()
        if review_usage is None or review_usage["same_transaction"] or review_usage["usage_state"] != "unknown":
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_REVIEW_SETTLEMENT_REQUIRED")
        review_reservation = self.budget._reservation_by_key(lease,"review."+original.artifact_id.hex)
        if (review_reservation is None or review_reservation["id"] != original.reservation_id
                or review_reservation["root_id"] != meta["root_id"] or review_reservation["lease_generation"] != lease.generation
                or self.budget._reservation_amounts(lease,original.reservation_id) != original.resources.as_dict()):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_REVIEW_RESERVATION_REQUIRED")
        terminal = self.conn.execute("SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts WHERE generation_artifact_id=%s) "
            "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts WHERE generation_artifact_id=%s "
            "AND artifact_kind='admission_evaluation') OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events WHERE version_id=%s) AS terminal",
            (original.artifact_id, original.artifact_id, a["version_id"])).fetchone()
        if terminal is None or terminal["terminal"]:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_FINAL_HISTORY_RETAINED")
        deadlines = []
        source_reviews = authority._current.governance.source_reviews
        for material in request.materials:
            coordinate = material.binding.evidence[0].binding
            review = None if source_reviews is None else source_reviews.resolve(coordinate.source_handle, coordinate.document_handle)
            if review is None or review.grant is None or review.grant.retained_until <= now:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_CURRENT_SOURCE_GRANT_REQUIRED")
            deadlines.append((material.binding.binding_digest, material.exact_claims[0].claim_receipt_id, review.grant.retained_until))
        return meta, row, UUID(str(blind[0]["id"])), tuple(deadlines)

    def _committed_original(self, original: PreparedSharedReview, result: SharedReviewResult,
            lease: JobLeaseV1, review_receipt_id: UUID) -> tuple[dict[str,Any],dict[str,Any],UUID,tuple[tuple[str,str,datetime],...]]:
        self._guard()
        frame=original.persistent_committed_frame
        entry=self.review._committed_frames.get(original.reservation_id)
        if frame is None or entry is None or entry[0] is not original or entry[1] is not result:
            raise PipelineRepositoryError("PERSISTENT_ORIGINAL_COMMITTED_REVIEW_ISSUER_REQUIRED")
        phase=entry[2]
        meta=self.review.require_committed_phase(original,result,phase=phase)
        if (lease!=phase.record.lease or review_receipt_id!=UUID(frame["review_receipt_id"])
                or phase.version is None or phase.version.artifact_id!=original.artifact_id
                or lease.profile.values.discussion_rounds<2 or lease.profile.values.investigation_rounds<1):
            raise PipelineRepositoryError("PERSISTENT_CURRENT_FINDING_EXECUTION_PHASE_REQUIRED")
        authority=self.review._prepared[original.reservation_id][2]
        row=self.conn.execute("SELECT * FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s FOR SHARE",
            (review_receipt_id,)).fetchone()
        if row is None or result.bundle is None or row["receipt_hash"]!=result.bundle.bundle_hash:
            raise PipelineRepositoryError("PERSISTENT_IMMUTABLE_ORIGINAL_REVIEW_REQUIRED")
        now=server_clock(self.conn,datetime.now(UTC))
        sources=[]
        source_reviews=authority._current.governance.source_reviews
        for material in original.request.materials:
            coordinate=material.binding.evidence[0].binding
            grant=None if source_reviews is None else source_reviews.resolve(coordinate.source_handle,coordinate.document_handle)
            if grant is None or grant.grant is None or grant.grant.retained_until<=now:
                raise PipelineRepositoryError("PERSISTENT_CURRENT_SOURCE_GRANT_REQUIRED")
            sources.append((material.binding.binding_digest,material.exact_claims[0].claim_receipt_id,grant.grant.retained_until))
        phase.owner.require_phase(phase,kind="candidate")
        return meta,row,UUID(frame["blind_receipt_id"]),tuple(sources)

    def issue_committed_revision(self, context: Any) -> Any:
        from app.services.learning.item_supply.persistent_pack_committed_revision import issue_evidence
        return issue_evidence(self, context)

    def require_committed_revision(self, proof: Any) -> dict[str, Any]:
        from app.services.learning.item_supply.persistent_pack_committed_revision import require_evidence
        return require_evidence(self, proof)

    def _require_finding_context(self, phase: Any) -> None:
        from app.services.learning.item_supply.persistent_pack_committed_revision import RevisionOnlyContext, require_context
        if type(phase) is RevisionOnlyContext:
            require_context(phase)
        else:
            phase.owner.require_phase(phase, kind="candidate")

    def _historical_revision_mapping(self, phase: Any) -> Any:
        from app.services.learning.item_supply.persistent_pack_committed_revision import RevisionOnlyContext, require_context
        if type(phase) is not RevisionOnlyContext or phase.source_successor is None:
            return None
        # Only this issued revision-only context may read expired publication DATA.
        # require_context rechecks the source successor, execution, epoch and holds.
        require_context(phase)
        if phase.owner.conn is not self.conn:
            raise PipelineRepositoryError("PERSISTENT_CONCRETE_PUBLISHED_REPAIR_PHASE_REQUIRED")
        return phase.owner.type_owner.mapping_owner.resolve_source_successor(
            receipt_id=phase.task.mapping_receipt_id, user_id=phase.task.user_id,
            epoch=phase.task.epoch, materials=phase.source_successor.course_materials)

    def _historical_revision_content(self, phase: Any, version: Any, mapping: Any) -> Any:
        from app.services.learning.item_supply.native_type_evidence import require_content_mapping_identity
        actual = phase.owner.type_owner.resolve_content(version.published_version_id, current=False)
        if (actual.spec != version.specification
                or actual.publication.generation_artifact_id != version.artifact_id
                or actual.facts.root_id != version.root_id
                or version.public_task_id != phase.record.public_task_id):
            raise PipelineRepositoryError("PERSISTENT_IMMUTABLE_BOUND_PARENT_PAIR_REQUIRED")
        require_content_mapping_identity(actual, mapping)
        return actual

    def _clone_finding(self, phase: Any, pair: tuple[UUID,UUID]) -> PersistentCloneFindingV1:
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        from app.services.learning.item_supply.persistent_pack_contracts import IssuedPackPhase, SLOTS
        from app.services.learning.item_supply.persistent_pack_committed_revision import RevisionOnlyContext
        from app.services.learning.item_supply.type_evidence import assessment_clone
        if (type(phase) not in (IssuedPackPhase, RevisionOnlyContext) or type(phase.owner) is not PersistentPackTaskOwner
                or phase.owner.conn is not self.conn or phase.version is None or phase.version.published_version_id is None):
            raise PipelineRepositoryError("PERSISTENT_CONCRETE_PUBLISHED_REPAIR_PHASE_REQUIRED")
        by_id=self._persistent_pairs.get(phase.record.phase_id)
        if by_id is None:
            versions=phase.owner._versions(phase.task)
            by_id={v.published_version_id:v for v in versions.values() if v.published_version_id is not None}
            if phase.version!=versions.get(phase.version.slot):
                raise PipelineRepositoryError("PERSISTENT_INITIAL_CURRENT_PARENT_REVISION_REQUIRED")
            self._persistent_pairs[phase.record.phase_id]=by_id
        if len(pair)!=2 or len(set(pair))!=2 or any(i not in by_id for i in pair):
            raise PipelineRepositoryError("PERSISTENT_EXACT_FIXED_SLOT_PAIR_REQUIRED")
        # A child journal version may already be appended during recheck. That does
        # not erase the immutable SAME-parent justification issued for this phase.
        for version in (by_id[i] for i in pair):
            committed=self.conn.execute("SELECT payload_json FROM tutor_item_supply_shared_persistent_pack_journal "
                "WHERE public_task_id=%s AND record_kind='qualified' AND payload_json->>'revision_id'=%s",
                (phase.record.public_task_id,str(version.revision_id))).fetchall()
            if not committed or any(r["payload_json"]!=version.model_dump(mode="json") for r in committed):
                raise PipelineRepositoryError("PERSISTENT_IMMUTABLE_BOUND_PARENT_PAIR_REQUIRED")
        # A DATA pair cannot choose another parent or give a controlled ancestor permission.
        for version in (by_id[i] for i in pair):
            held=self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(job_id) AS held "
                "FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s",(version.artifact_id,)).fetchone()
            if held is None or held["held"] is not False:
                raise PipelineRepositoryError("PERSISTENT_CONTROLLED_ANCESTRY_DENIED")
        self._require_finding_context(phase)
        mapping=self._historical_revision_mapping(phase)
        if mapping is None:
            mapping=phase.owner.type_owner.resolve_mapping(phase.task.mapping_receipt_id)
            contents=tuple(phase.owner.type_owner.resolve_content(i,current=True) for i in pair)
            for content in contents:
                phase.owner.type_owner._candidate(content,mapping,phase.owner._guard())
        else:
            contents=tuple(self._historical_revision_content(phase,by_id[i],mapping) for i in pair)
        assessments=[by_id[i] for i in pair if by_id[i].specification.allocation.slot=="assessment"]
        parent=max(assessments,key=lambda v:SLOTS.index(v.slot)) if assessments else None
        if (parent is None or parent!=phase.version or parent.root_id!=phase.record.root_id
                or any(c.spec.target_id!=parent.specification.target_id for c in contents)
                or not assessment_clone(contents[0].content,contents[1].content)):
            raise PipelineRepositoryError("PERSISTENT_ACTUAL_CLONE_AND_EXACT_AFFECTED_SLOT_REQUIRED")
        fields=tuple(n for n in ("item_handle","content_hash","actual_public_task_hash","decision_signature","answer_leakage_signature")
            if getattr(contents[0].content,n)==getattr(contents[1].content,n))
        data=dict(schema_version="persistent_deterministic_clone_finding_v1",role="deterministic",safe_code="assessment_clone",
            rule="original_assessment_clone_v2",pair=[c.content.model_dump(mode="json") for c in contents],
            equal_fields=list(fields),references=[],model_finding_asserted=False,historical_finding_resolved=False)
        return PersistentCloneFindingV1.model_validate_json(json.dumps(dict(data,dispute_key=canonical_hash(data))))

    def _persistent_finding(self, phase: Any, request: Any) -> None:
        if type(request) is not PersistentInvestigationInputV1 or request.execution_profile_hash!=phase.record.lease.profile.profile_hash:
            raise PipelineRepositoryError("PERSISTENT_CURRENT_EXECUTION_PROFILE_REQUIRED")
        clones=[d for d in request.disputes if type(d) is PersistentCloneFindingV1]
        if phase.version is None:
            raise PipelineRepositoryError("PERSISTENT_FIXED_PARENT_REQUIRED")
        if phase.version.published_version_id is not None and not clones:
            raise PipelineRepositoryError("PERSISTENT_PUBLISHED_PARENT_ACTUAL_RELATION_FINDING_REQUIRED")
        for finding in clones:
            if self._clone_finding(phase,(finding.pair[0].version_id,finding.pair[1].version_id))!=finding:
                raise PipelineRepositoryError("PERSISTENT_ORIGINAL_CLONE_FACT_CHANGED")
        self._require_finding_context(phase)

    def prepare_persistent(self, *, phase: Any, original: PreparedSharedReview, result: SharedReviewResult,
            review_receipt_id: UUID, clone_pair: tuple[UUID,UUID] | None=None) -> PreparedNativeReviewInvestigation | None:
        # Explicit new issuer path: no fake peer report, boolean grant, old lease, or restored cap.
        meta,row,blind_id,sources=self._committed_original(original,result,phase.record.lease,review_receipt_id)
        if self.review._committed_frames[original.reservation_id][2] is not phase or result.bundle is None:
            raise PipelineRepositoryError("PERSISTENT_EXACT_ORIGINAL_FRAME_REQUIRED")
        schema=self.conn.execute("SELECT to_regprocedure('item_supply_internal.assert_persistent_normal_repair(jsonb)') AS guard").fetchone()
        if schema is None or schema["guard"] is None:
            raise PipelineRepositoryError("PERSISTENT_NORMAL_525_RECEIVER_REQUIRED")
        disputes=(*review_disputes(result.bundle),*(() if clone_pair is None else (self._clone_finding(phase,clone_pair),)))
        if not disputes:
            return None
        lease=phase.record.lease
        now=server_clock(self.conn,datetime.now(UTC))
        deadline=min(phase.record.valid_until,lease.expires_at,lease.parent_deadline,*(t for _,_,t in sources))
        timeout=min(100.0,lease.profile.values.request_timeout_ms/1000,(deadline-now).total_seconds())
        if timeout<=0:
            raise PipelineRepositoryError("PERSISTENT_NORMAL_PHASE_EXPIRED")
        with finite_review_context(original.source,spec=original.spec,materials=original.request.materials):
            request=PersistentInvestigationInputV1(review_receipt_id=review_receipt_id,review_receipt_hash=row["receipt_hash"],
                bundle=checked_bundle(result.bundle),review_input=ReviewInputV2(binding=original.binding,
                role=LearningItemReviewRole.TECHNICAL,source=original.source,validation_receipt=original.validation),
                execution_profile_hash=lease.profile.profile_hash,disputes=disputes,
                revision_allocation=None if clone_pair is None else self._select_registered_child_allocation(phase,original.spec))
            self._persistent_finding(phase,request)
            key=meta["key"]
            model=self.review.settings.llm_model
            if model is None:
                raise PipelineRepositoryError("PERSISTENT_CURRENT_CONFIGURED_MODEL_REQUIRED")
            identity=ProviderIdentityV2(identity="deepseek.native.shared.investigator",provider=key.provider,
                model=model,model_version=key.model_version)
            if (self.review._models.get((key.provider,key.model_version))!=identity.model
                    or identity.identity in {original.author_identity,*(i.identity for i in original.provider_identities)}):
                raise PipelineRepositoryError("PERSISTENT_CURRENT_INDEPENDENT_INVESTIGATOR_REQUIRED")
            adapter=PersistentInvestigationSender(self.review.settings,profile=lease.profile,identity=identity,timeout_seconds=timeout)
            resources=adapter.resource_plan(request)
            reserve_key="investigate."+original.artifact_id.hex+"."+review_receipt_id.hex
            reserved=self.budget.reserve(lease=lease,reservation_key=reserve_key,amounts=resources,now=now)
            if not reserved.allowed or reserved.reservation_id is None or reserved.reason=="REPLAY":
                return None
            assert original.persistent_committed_frame is not None
            p=PreparedNativeReviewInvestigation(uuid4(),UUID(str(meta["root_id"])),lease,original,result,blind_id,
                review_receipt_id,original.persistent_committed_frame["continuation_binding_hash"],
                reserved.reservation_id,request,identity,resources,sources,deadline,timeout,persistent_phase=phase)
            payload=p.payload()
            self.conn.execute("SELECT item_supply_internal.assert_persistent_normal_repair(%s::jsonb)",(Jsonb(payload),)).fetchone()
        self.conn.execute("INSERT INTO tutor_item_supply_shared_review_investigation_preparations "
            "(id,root_id,job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,review_receipt_id,reservation_id,payload_json,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(p.preparation_id,p.root_id,lease.job_id,lease.lease_owner,
                lease.generation,lease.state_version,original.artifact_id,review_receipt_id,p.reservation_id,Jsonb(payload),deadline))
        self._prepared[p.preparation_id]=(p,canonical_hash(payload),adapter,self.review.settings.model_copy(deep=True))
        with finite_review_context(original.source,spec=original.spec,materials=original.request.materials):
            self._sender_seals[p.preparation_id]=(PERSISTENT_PROTOCOL,adapter.envelope_hash(request))
        return p


    def child_allocation(self, p: PreparedNativeReviewInvestigation) -> Any:
        """Original-issuer deterministic registered-family change for an actual clone.

        The old variant/seed/goal/root are untouched. This is a child version plan,
        never a replacement slot or a content reroll. No available structure => STOP.
        """
        self._issued(p)
        self._fence(p)
        if p.persistent_phase is None or type(p.request) is not PersistentInvestigationInputV1:
            return p.original.spec.allocation
        clones=[d for d in p.request.disputes if type(d) is PersistentCloneFindingV1]
        if not clones:
            return p.original.spec.allocation
        allocation=self._select_registered_child_allocation(p.persistent_phase,p.original.spec)
        if allocation!=p.request.revision_allocation:
            raise PipelineRepositoryError("PERSISTENT_FROZEN_FAMILY_PLAN_CHANGED_STOP")
        return allocation

    def _select_registered_child_allocation(self, phase: Any, parent: Any) -> Any:
        from app.services.learning.item_supply.finite_candidate_factory import build_finite_slot_allocation
        from app.services.learning.item_supply.finite_task_families import families_for_course
        from app.services.learning.item_supply.native_type_fingerprints import FINGERPRINT_VERSION
        if parent.target_id!="python-kc-binding-v1" or parent.allocation.slot!="assessment":
            raise PipelineRepositoryError("PERSISTENT_REGISTERED_KC_ASSESSMENT_FAMILY_REVISION_REQUIRED")
        mapping=self._historical_revision_mapping(phase)
        versions=phase.owner._versions(phase.task)
        occupied=[]
        for v in versions.values():
            if v.published_version_id is None or v.public_slot_id==phase.version.public_slot_id:
                continue
            actual=(phase.owner.type_owner.resolve_content(v.published_version_id,current=True) if mapping is None
                else self._historical_revision_content(phase,v,mapping))
            occupied.append(actual.content)
        observed=phase.owner.exposure_owner.snapshot_v2()
        if observed.exposure is None or observed.snapshot_id is None:
            raise PipelineRepositoryError("PERSISTENT_COMPLETE_CURRENT_EXPOSURE_REQUIRED")
        occupied.extend(e.content for e in observed.exposure.records)
        parent_family=next(f for f in families_for_course(parent.target_id) if f.family_id==parent.allocation.family_id)
        family=None
        for candidate in families_for_course(parent.target_id):
            semantics={"version":FINGERPRINT_VERSION,"profile":"kc","decision":candidate.task_kind}
            decision=canonical_hash({"domain":"decision","semantics":semantics})
            leakage=canonical_hash({"domain":"contextual-solution","semantics":semantics})
            if candidate.task_kind!=parent_family.task_kind and not any(
                    c.decision_signature==decision or c.answer_leakage_signature==leakage for c in occupied):
                family=candidate
                break
        if family is None:
            raise PipelineRepositoryError("PERSISTENT_FINITE_REASONING_STRUCTURES_EXHAUSTED_NO_REROLL")
        role=parent.allocation.variant_id.rsplit(":",1)[1]
        allocation=build_finite_slot_allocation(target_id=parent.target_id,family_id=family.family_id,
            slot="assessment",slot_index=int(role[-1]))
        if allocation.variant_id!=parent.allocation.variant_id:
            raise PipelineRepositoryError("PERSISTENT_ORIGINAL_VARIANT_MUST_REMAIN")
        self._require_finding_context(phase)
        return allocation


    def _adapter(self, lease: JobLeaseV1, meta: dict[str, Any], *, timeout: float) -> NativeReviewInvestigator:
        key = meta["key"]
        settings = self.review.settings
        model=settings.llm_model
        if model is None:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_FROZEN_MODEL_BINDING_REQUIRED")
        identity = ProviderIdentityV2(identity="deepseek.native.shared.investigator", provider=key.provider,
            model=model, model_version=key.model_version)
        adapter = NativeReviewInvestigator(settings, profile=lease.profile, identity=identity, timeout_seconds=timeout,
            protocol=self.protocol)
        if (meta["provider_key"] != identity.provider or self.review._models.get((key.provider, key.model_version)) != identity.model):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_FROZEN_MODEL_BINDING_REQUIRED")
        return adapter

    def _issued(self, p: PreparedNativeReviewInvestigation) -> Any:
        if type(p) is not PreparedNativeReviewInvestigation:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_PREPARED_REQUIRED")
        entry = self._prepared.get(p.preparation_id)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            if entry is None or entry[0] is not p or entry[1] != canonical_hash(p.payload()):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_PREPARED_REQUIRED")
            sender = self._sender_seals.get(p.preparation_id)
            adapter = entry[2]
            if p.persistent_phase is not None:
                if (type(adapter) is not PersistentInvestigationSender or sender is None
                        or sender[0]!=PERSISTENT_PROTOCOL or type(p.request) is not PersistentInvestigationInputV1
                        or adapter.envelope_hash(p.request)!=sender[1]):
                    raise PipelineRepositoryError("PERSISTENT_INVESTIGATION_ORIGINAL_ENVELOPE_REQUIRED")
                return adapter
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            if not isinstance(p.request,NativeReviewInvestigationInputV1):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_INPUT_REQUIRED")
            if (sender is None or type(adapter) is not NativeReviewInvestigator
                    or checked_investigation_protocol(self.protocol) != sender[0]
                    or checked_investigation_protocol(adapter.protocol) != sender[0]
                    or adapter.envelope_hash(p.request) != sender[1]):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_ENVELOPE_CHANGED")
        return adapter

    def prepare(self, *, original: PreparedSharedReview, result: SharedReviewResult,
                lease: JobLeaseV1, review_receipt_id: UUID) -> PreparedNativeReviewInvestigation | None:
        meta, row, blind_id, sources = self._original(original, result, lease, review_receipt_id)
        if result.bundle is None:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMPLETE_REVIEW_REQUIRED")
        disputes = review_disputes(result.bundle)
        if not disputes:
            return None
        now = server_clock(self.conn, datetime.now(UTC))
        deadline = min(lease.expires_at, lease.parent_deadline, lease.profile.parent_deadline_at,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms), *(t for _,_,t in sources))
        timeout = min(3600.0, lease.profile.values.request_timeout_ms/1000, (deadline-now).total_seconds())
        if timeout <= 0:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_DEADLINE_REACHED")
        with finite_review_context(original.source, spec=original.spec, materials=original.request.materials):
            request = NativeReviewInvestigationInputV1(review_receipt_id=review_receipt_id,
                review_receipt_hash=row["receipt_hash"], bundle=checked_bundle(result.bundle),
                review_input=ReviewInputV2(binding=original.binding, role=LearningItemReviewRole.TECHNICAL,
                    source=original.source, validation_receipt=original.validation), disputes=disputes)
            adapter = self._adapter(lease, meta, timeout=timeout)
            if adapter.identity.identity in {original.author_identity, *(i.identity for i in original.provider_identities)}:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_AUTHOR_REVIEW_SEPARATION_REQUIRED")
            resources = adapter.resource_plan(request)
            sender = (checked_investigation_protocol(self.protocol), adapter.envelope_hash(request))
            key = "investigate."+original.artifact_id.hex+"."+review_receipt_id.hex
            reserved = self.budget.reserve(lease=lease, reservation_key=key, amounts=resources, now=now)
            if not reserved.allowed or reserved.reservation_id is None or reserved.reason == "REPLAY":
                return None
            p = PreparedNativeReviewInvestigation(uuid4(), UUID(str(meta["root_id"])), lease, original, result,
                blind_id, review_receipt_id, row["continuation_binding_hash"], reserved.reservation_id,
                request, adapter.identity, resources, sources, deadline, timeout)
            payload = p.payload()
        self.conn.execute("INSERT INTO tutor_item_supply_shared_review_investigation_preparations "
            "(id,root_id,job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,review_receipt_id,reservation_id,payload_json,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (p.preparation_id,p.root_id,lease.job_id,lease.lease_owner,
                lease.generation,lease.state_version,original.artifact_id,review_receipt_id,p.reservation_id,Jsonb(payload),deadline))
        self._prepared[p.preparation_id] = (p, canonical_hash(payload), adapter, self.review.settings.model_copy(deep=True))
        self._sender_seals[p.preparation_id] = sender
        if self._audit_sink is not None:
            with finite_review_context(original.source, spec=original.spec, materials=original.request.materials):
                context = {"preparation_id": str(p.preparation_id), "reservation_id": str(p.reservation_id),
                    "root_id": str(p.root_id), "job_id": str(p.lease.job_id),
                    "review_receipt_id": str(p.review_receipt_id), "review_receipt_hash": request.review_receipt_hash,
                    "binding": request.binding.model_dump(mode="json"), "source_hash": original.source.source_hash,
                    "request_input_hash": request.input_hash, "envelope_hash": sender[1],
                    "protocol": sender[0], "prompt_version": investigation_prompt_version(sender[0]),
                    "provider_identity": p.identity.model_dump(mode="json"), "run_id": None}
                self._audits[p.preparation_id] = PrivateInvestigationAudit(self._audit_sink, context=context)
        return p

    def _fence(self, p: PreparedNativeReviewInvestigation, *, committed: bool = True) -> datetime:
        adapter = self._issued(p)
        meta, _, _, sources = self._original(p.original, p.original_result, p.lease, p.review_receipt_id)
        now = server_clock(self.conn, datetime.now(UTC))
        if (meta["root_id"] != p.root_id or now >= p.deadline_at or sources != p.source_deadlines
                or self.review.settings != self._prepared[p.preparation_id][3]
                or adapter.identity != p.identity or adapter.timeout_seconds != p.timeout_seconds
                or adapter.client.frozen_profile != p.lease.profile
                or adapter.client._settings != self._prepared[p.preparation_id][3]
                or (p.persistent_phase is None and self._adapter(p.lease, meta, timeout=p.timeout_seconds).identity != p.identity)):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_CURRENT_FENCE_CHANGED")
        if p.persistent_phase is not None:
            with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
                self._persistent_finding(p.persistent_phase,p.request)
                self.conn.execute("SELECT item_supply_internal.assert_persistent_normal_repair(%s::jsonb)",(Jsonb(p.payload()),)).fetchone()
        row = self.conn.execute("SELECT p.*,p.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_review_investigation_preparations p WHERE p.id=%s", (p.preparation_id,)).fetchone()
        reservation = self.budget._reservation_by_key(p.lease, p.reservation_key)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            payload = p.payload()
            resources = adapter.resource_plan(p.request)
        if (row is None or (committed and row["same_transaction"]) or row["snapshot_hash"] != canonical_hash(payload)
                or row["payload_json"] != payload or reservation is None or reservation["id"] != p.reservation_id
                or reservation["root_id"] != p.root_id or reservation["lease_generation"] != p.lease.generation
                or self.budget._reservation_amounts(p.lease,p.reservation_id) != p.resources.as_dict() or resources != p.resources):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_RESERVATION_REQUIRED")
        return now

    def run(self, p: PreparedNativeReviewInvestigation) -> NativeReviewInvestigationRun:
        adapter = self._issued(p)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_IDLE_REQUIRED")
        if p.preparation_id in self._started:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ALREADY_DISPATCHED")
        self._started.add(p.preparation_id)
        report: NativeReviewInvestigationReportV1 | PersistentInvestigationReportV1 | None = None
        observation = None
        reason = "investigation_analysis_pending_revision_owner"
        try:
            with self.conn.transaction():
                now = self._fence(p)
            # Price/hash remain frozen; invocation timeout can ONLY decrease.
            remaining = (p.deadline_at-max(now, datetime.now(UTC))).total_seconds()
            if remaining <= 0:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_DEADLINE_REACHED")
            if self.conn.info.transaction_status != TransactionStatus.IDLE:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_IDLE_REQUIRED")
            with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
                report = adapter.investigate(p.request, deadline_at=p.deadline_at, remaining_seconds=remaining,
                    expected_envelope_hash=self._sender_seals[p.preparation_id][1],
                    private_audit=self._audits.get(p.preparation_id))
            with self.conn.transaction():
                self._fence(p)
        except Exception as exc:
            # A returned analysis is not a valid result after an owner fence fails.
            # The separately settled reservation remains UNKNOWN either way.
            report = None
            reason = "investigation_provider_or_fence_pending"
            observation = exc.observation if isinstance(exc, AutonomousReviewError) else None
            if observation is None:
                observation = observe_review_failure(exc, phase="evidence_verification")
            audit = self._audits.get(p.preparation_id)
            if audit is not None:
                audit.failure(phase=observation.phase, safe_code=observation.safe_code)
        result = NativeReviewInvestigationRun(p.preparation_id,p.reservation_id,report,reason,observation)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            self._runs[p.preparation_id] = (result,canonical_hash(result.payload(p)))
        return result

    def _result(self, p: PreparedNativeReviewInvestigation, result: NativeReviewInvestigationRun) -> None:
        self._issued(p)
        entry = self._runs.get(p.preparation_id)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            if (type(result) is not NativeReviewInvestigationRun or entry is None or entry[0] is not result
                    or result.preparation_id != p.preparation_id or result.reservation_id != p.reservation_id
                    or entry[1] != canonical_hash(result.payload(p))):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_RESULT_REQUIRED")
            if result.report is not None:
                if isinstance(result.report,NativeReviewInvestigationReportV1):
                    if not isinstance(p.request,NativeReviewInvestigationInputV1):
                        raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_INPUT_REQUIRED")
                    result.report.verify_input(p.request,expected_protocol=self._sender_seals[p.preparation_id][0])
                else:
                    result.report.verify_input(p.request,expected_protocol=self._sender_seals[p.preparation_id][0])
                if (result.report.run.provider_identity != p.identity
                        or result.report.run.prompt_version != (PERSISTENT_PROMPT if p.persistent_phase is not None
                            else investigation_prompt_version(self._sender_seals[p.preparation_id][0]))
                        or result.report.run.max_output_tokens != DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
                        or result.report.run.timeout_seconds > p.timeout_seconds):
                    raise PipelineRepositoryError("NATIVE_INVESTIGATION_ACTUAL_RUN_BINDING_REQUIRED")

    def settle(self, p: PreparedNativeReviewInvestigation, result: NativeReviewInvestigationRun) -> None:
        self._result(p,result)
        self.budget.settle(lease=p.lease,reservation_id=p.reservation_id,settlement_key=p.reservation_key,
            usage_state="unknown",actual=None,cost_amount=None,receipt_hash=None)

    def persist(self, p: PreparedNativeReviewInvestigation, result: NativeReviewInvestigationRun) -> UUID:
        self._result(p,result)
        self._fence(p)
        usage = self.conn.execute("SELECT s.*,s.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=%s AND s.settlement_key=%s",
            (p.reservation_id,p.reservation_key)).fetchone()
        if usage is None or usage["same_transaction"] or usage["usage_state"] != "unknown":
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_UNKNOWN_SETTLEMENT_REQUIRED")
        with finite_review_context(p.original.source,spec=p.original.spec,materials=p.original.request.materials):
            payload = result.payload(p)
        receipt_id = p.preparation_id  # One immutable result per preparation, including failures.
        row = self.conn.execute("INSERT INTO tutor_item_supply_shared_review_investigation_receipts "
            "(id,preparation_id,root_id,job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,review_receipt_id,reservation_id,settlement_id,payload_json,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(preparation_id) DO NOTHING RETURNING id",
            (receipt_id,p.preparation_id,p.root_id,p.lease.job_id,p.lease.lease_owner,p.lease.generation,p.lease.state_version,
                p.original.artifact_id,p.review_receipt_id,p.reservation_id,usage["id"],Jsonb(payload),p.deadline_at)).fetchone()
        if row is None:
            prior = self.conn.execute("SELECT id,snapshot_hash,payload_json FROM tutor_item_supply_shared_review_investigation_receipts WHERE preparation_id=%s",
                (p.preparation_id,)).fetchone()
            if prior is None or prior["snapshot_hash"] != canonical_hash(payload) or prior["payload_json"] != payload:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_IMMUTABLE_RESULT_CONFLICT")
            return UUID(str(prior["id"]))
        return UUID(str(row["id"]))
