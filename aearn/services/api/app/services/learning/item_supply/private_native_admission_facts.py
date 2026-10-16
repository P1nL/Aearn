"""Concrete PRIVATE finite issuer. Original author/scorer/reviewer ports; no shared receipts.

Preparation/storage are caller transactions. IO requires IDLE. A committed DATA row
cannot reconstruct the in-process issuer. Publication and ongoing consumption are separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.admission import evaluate_admission
from app.services.learning.item_supply.contracts import require_aware
from app.services.learning.item_supply.diagnostic_policy import EvidencePolicy, ReviewBundle, checked_policy
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_course_mapping import FiniteCourseMappingOwner
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.finite_task_ambiguity import FiniteAmbiguityReceiptV1, FiniteTaskAmbiguityOwner, build_finite_ambiguity_plan
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationReceiptV2
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.pipeline import ItemSupplyPipeline, PreparedReview
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateNativeQualityV1, PrivateSlotRef
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvidenceV2, CandidateBindingV2, ProbeOutcomeV2, checked_validation_receipt
from app.services.learning.item_supply.review_provider import JsonBlindSolverV2, JsonReviewerV2, blind_solve_candidate, review_candidate_for_policy
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

QUALITY_TABLE = 'tutor_item_supply_private_native_quality_evidence'

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
    from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner


@dataclass(frozen=True)
class PreparedPrivateReview:
    ref: PrivateSlotRef
    original: PreparedReview
    spec: FiniteCandidateSpecV1
    request: GenerationRequestV2
    policy: EvidencePolicy
    preparation_id: UUID


@dataclass(frozen=True)
class CompletedPrivateReview:
    bundle: ReviewBundle
    ambiguity: FiniteAmbiguityReceiptV1


class PrivateNativeAdmissionFactsOwner:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 pipeline: ItemSupplyPipeline, mapping_owner: FiniteCourseMappingOwner,
                 source_authority: RagSourceAuthority, enabled: bool = False) -> None:
        if (type(pipeline) is not ItemSupplyPipeline or pipeline.conn is not conn
                or type(mapping_owner) is not FiniteCourseMappingOwner or mapping_owner.conn is not conn
                or type(source_authority) is not RagSourceAuthority or source_authority.connection is not conn):
            raise PrivateNativePending('private_native_concrete_owners_required')
        self.conn, self.settings, self.enabled = conn, settings, enabled
        self.pipeline, self.mapping_owner, self.source_authority = pipeline, mapping_owner, source_authority
        self.type_owner: PrivateNativeTypeEvidenceOwner | None = None
        self._prepared: dict[UUID, tuple[PreparedPrivateReview, str, FiniteStaticBlindScorer, JsonBlindSolverV2, tuple[JsonReviewerV2, ...]]] = {}
        self._results: dict[UUID, tuple[CompletedPrivateReview, FiniteTaskAmbiguityOwner]] = {}
        self._issued: dict[UUID, tuple[PrivateNativeQualityV1, PreparedPrivateReview, CompletedPrivateReview]] = {}
        self._started: set[UUID] = set()
        self._normal: dict[UUID, UUID] = {}
        self._committed_reviews: dict[UUID, Any] = {}

    def bind_type_owner(self, owner: PrivateNativeTypeEvidenceOwner) -> None:
        """Bind once after query/type composition; this is only a mapping DATA port."""
        from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner
        if (type(owner) is not PrivateNativeTypeEvidenceOwner or owner.conn is not self.conn
                or owner.settings is not self.settings or owner.mapping_owner is not self.mapping_owner
                or owner.query.source_authority is not self.source_authority
                or (self.type_owner is not None and self.type_owner is not owner)):
            raise PrivateNativePending('private_native_same_type_mapping_owner_required')
        self.type_owner = owner

    def resolve_mapping(self, ref: PrivateSlotRef) -> FiniteCourseMappingReceiptV1:
        ref = checked_model(ref, PrivateSlotRef)
        owner = self.type_owner
        if owner is not None:
            self.bind_type_owner(owner)
            if (owner.user_id, owner.epoch) != (ref.user_id, ref.epoch):
                raise PrivateNativePending('private_native_epoch_required')
            return owner.resolve_mapping(ref.mapping_receipt_id)
        result = self.mapping_owner.resolve(receipt_id=ref.mapping_receipt_id, user_id=ref.user_id, epoch=ref.epoch)
        if result.receipt is None:
            raise PrivateNativePending('private_native_mapping_scope_required')
        return result.receipt

    @contextmanager
    def current_source_front(self, ref: PrivateSlotRef) -> Iterator[IssuedCurrentPackSourceBinding | None]:
        """Fresh original SOURCE in the caller's TOP; never across provider IO."""
        from app.services.learning.item_bank.private_native_publication import PrivateNativePublicationQuery
        from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding, SOURCE_DATA, _seal
        private = self.type_owner
        if private is None:
            yield None
            return
        self.bind_type_owner(private)
        public = private.public_owner
        if public is None:
            yield None
            return
        if (type(self) is not PrivateNativeAdmissionFactsOwner
                or type(public) is not NativeTypeEvidenceOwner or public.conn is not self.conn
                or public.settings is not self.settings or public.mapping_owner is not self.mapping_owner
                or (public.user_id,public.epoch)!=(private.user_id,private.epoch)
                or type(private.query) is not PrivateNativePublicationQuery or private.query.conn is not self.conn
                or private.query.settings is not self.settings
                or (private.query.user_id,private.query.epoch)!=(private.user_id,private.epoch)
                or self.mapping_owner.conn is not self.conn
                or type(self.source_authority) is not RagSourceAuthority or self.source_authority.connection is not self.conn
                or public.source_authority is not self.source_authority):
            raise PrivateNativePending('private_native_original_source_graph_required')
        attached = NativeTypeEvidenceOwner._source_binding(public)
        if attached is None:
            yield None
            return
        ref = checked_model(ref, PrivateSlotRef)
        core, task = attached.owner, attached.task
        saved = core._current_source_bindings.get(attached.binding_id)
        if (type(core) is not PersistentPackTaskOwner or core.conn is not self.conn
                or core.settings is not self.settings or core.type_owner is not public
                or (core.user_id,core.epoch)!=(ref.user_id,ref.epoch)
                or saved is None or saved[0] is not attached or saved[1] != _seal(attached)
                or (task.pack_task_id,task.user_id,task.epoch,task.scope_id,task.mapping_receipt_id)
                != (ref.pack_task_id,ref.user_id,ref.epoch,ref.scope_id,ref.mapping_receipt_id)):
            raise PrivateNativePending('private_service_original_task_source_binding_required')
        # Attached cap is only an explicit mode/task selector. Its old origin
        # is not restored; every TOP issues a NEW original capability/origin.
        try:
            actual = core.issue_current_source_binding(task, source_data_id=SOURCE_DATA)
            if type(actual) is not IssuedCurrentPackSourceBinding or actual.owner is not core or actual.task != task:
                raise PrivateNativePending('private_service_original_task_source_binding_required')
            public.attach_current_source_binding(actual)
            with actual.current_scope():
                record = core._task(task)
                if record.enhancement != 'prefer_private':
                    raise PrivateNativePending('private_service_same_prefer_private_task_required')
                yield actual
        finally:
            public.current_source_binding = None

    def _guard(self, ref: PrivateSlotRef, lease: JobLeaseV1) -> datetime:
        if (not self.enabled or not self.settings.learning_item_supply_enabled
                or not self.settings.learning_item_v2_admission_enabled
                or self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS):
            raise PrivateNativePending('private_native_current_transaction_required')
        ref = checked_model(ref, PrivateSlotRef)
        if (lease.visibility != 'private' or (lease.owner_id, lease.owner_epoch) != (ref.user_id, ref.epoch)):
            raise PrivateNativePending('private_native_epoch_required')
        now = server_clock(self.conn, datetime.now(UTC))
        self.pipeline.artifacts._context(lease, ref.scope_id, now, 'live')
        meta = self.pipeline.budget._job_meta(lease, now=now)
        if UUID(str(meta['root_id'])) != ref.root_id:
            raise PrivateNativePending('private_native_original_root_required')
        mapping = self.resolve_mapping(ref)
        if not any(e.slot == ref.slot and e.storage_scope_id == ref.goal_scope_id for e in mapping.pack_request.demands):
            raise PrivateNativePending('private_native_mapping_scope_required')
        # 523 owns the persistent task/slot/phase registry. This receiver is a hard
        # dependency, not an optional flag or a callback authorizing readiness.
        row = self.conn.execute('SELECT item_supply_internal.private_pack_slot_current(%s,%s,%s,%s,%s,%s,%s,%s) AS ok',
            (ref.pack_task_id, ref.slot_id, ref.business_item_id, ref.root_id, ref.user_id, ref.epoch, ref.scope_id, lease.job_id)).fetchone()
        if row is None or row['ok'] is not True:
            raise PrivateNativePending('private_native_persistent_slot_required')
        # Recheck original live controls after mapping and every slot lock wait.
        self.pipeline.artifacts._context(lease, ref.scope_id, server_clock(self.conn, now), 'live')
        now = server_clock(self.conn, now)
        if now >= min(lease.expires_at, lease.parent_deadline):
            raise PrivateNativePending('private_native_current_lease_required')
        if self.type_owner is not None and self.type_owner.public_owner is not None:
            from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
            cap = NativeTypeEvidenceOwner._source_binding(self.type_owner.public_owner)
            if cap is not None and now >= cap.source_deadline:
                raise PrivateNativePending('private_native_current_mapping_required')
        return now

    def _artifact(self, ref: PrivateSlotRef, lease: JobLeaseV1, artifact_id: UUID) -> dict[str, Any]:
        self._guard(ref, lease)
        a = self.conn.execute("SELECT a.* FROM tutor_item_supply_private_generation_artifacts a JOIN tutor_item_supply_private_jobs j ON j.id=a.job_id AND j.user_id=a.user_id AND j.epoch=a.epoch WHERE a.id=%s AND a.user_id=%s AND a.epoch=%s AND a.scope_id=%s AND j.root_id=%s AND a.mode='live'", (artifact_id, ref.user_id, ref.epoch, ref.scope_id, ref.root_id)).fetchone()
        if a is None:
            raise PrivateNativePending('private_native_original_generation_required')
        # Historical generation is DATA. NEW 523 phase/root authorization was
        # checked above; never restore the old producer lease/capability.
        self.pipeline._fence_source(a, 'live', self.source_authority)
        return a

    def validate(self, *, ref: PrivateSlotRef, lease: JobLeaseV1, artifact_id: UUID,
                 spec: FiniteCandidateSpecV1) -> tuple[UUID, CandidateValidationV2]:
        a = self._artifact(ref, lease, artifact_id)
        source = LearningItemSourceV1.model_validate_json(json.dumps(a['source_json']))
        request = GenerationRequestV2.model_validate_json(json.dumps(a['request_json']))
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
        if spec.allocation.slot != ref.slot:
            raise PrivateNativePending('private_native_slot_spec_required')
        if inputs.static_facts is None:
            # Execution remains original P6-owned, never static-success for OS.
            raise PrivateNativePending('private_native_execution_validation_owner_required')
        validation = inputs.static_facts.validation
        rid = uuid4()
        row = self.conn.execute('INSERT INTO ' + QUALITY_TABLE + ' (id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,version_id,kind,job_id,payload_json,checked_at,valid_until) '
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'validation',%s,%s,%s,%s) RETURNING id",
            (rid, ref.user_id, ref.epoch, ref.scope_id, ref.pack_task_id, ref.slot_id, ref.root_id, a['version_id'], lease.job_id,
             Jsonb(validation.model_dump(mode='json')), self._guard(ref,lease), min(lease.expires_at,lease.parent_deadline))).fetchone()
        if row is None:
            raise PrivateNativePending('private_native_validation_storage_required')
        self.pipeline.runtime.checkpoint(lease, CheckpointV1(stage='validating', attempt=1, status='completed',
            receipt_hash=validation.evidence_hash, safe_reason='private_native_static_verified'), now=datetime.now(UTC))
        return UUID(str(row['id'])), validation

    def _seal(self, p: PreparedPrivateReview) -> str:
        return canonical_hash({'ref': p.ref.model_dump(mode='json'), 'lease': p.original.lease.model_dump(mode='json'),
            'source': p.original.source.source_hash, 'binding': p.original.binding.model_dump(mode='json'),
            'validation': p.original.validation.evidence_hash, 'reservation': str(p.original.reservation_id),
            'spec': p.spec.specification_hash, 'request': p.request.model_dump(mode='json'), 'policy': p.policy.policy_hash})

    def adopt_committed_review(self, cap: Any) -> tuple[PreparedPrivateReview, CompletedPrivateReview]:
        from app.services.learning.item_supply.private_native_committed_progress import (
            IssuedPrivateCommittedReview, PrivateNativeCommittedProgressOwner,
        )
        if (type(cap) is not IssuedPrivateCommittedReview or type(cap.owner) is not PrivateNativeCommittedProgressOwner
                or cap.owner.facts_owner is not self):
            raise PrivateNativePending('private_facts_fresh_committed_issuer_required')
        cap.owner.require(cap)
        self._committed_reviews[cap.prepared.preparation_id]=cap
        return cap.prepared,cap.result

    def _require(self, p: PreparedPrivateReview) -> tuple[FiniteStaticBlindScorer, JsonBlindSolverV2, tuple[JsonReviewerV2, ...]] | None:
        resumed=self._committed_reviews.get(p.preparation_id)
        if resumed is not None:
            resumed.owner.require(resumed)
            if resumed.prepared is not p:
                raise PrivateNativePending('private_facts_committed_prepared_identity_required')
            return None  # no paid/settlement/writer authority can be restored.
        row = self._prepared.get(p.preparation_id)
        if row is None or row[0] is not p or row[1] != self._seal(p):
            raise PrivateNativePending('private_native_prepared_identity_required')
        return row[2], row[3], row[4]

    def prepare_review(self, *, ref: PrivateSlotRef, lease: JobLeaseV1, artifact_id: UUID,
                       spec: FiniteCandidateSpecV1, policy: EvidencePolicy,
                       solver: JsonBlindSolverV2, reviewers: tuple[JsonReviewerV2, ...],
                       resources: ResourceAmounts) -> PreparedPrivateReview:
        a = self._artifact(ref, lease, artifact_id)
        policy = checked_policy(policy)
        from app.services.learning.item_supply.review_provider import review_resource_plan
        from app.services.learning.item_supply.review_protocol import configured_review_protocol
        source = LearningItemSourceV1.model_validate_json(json.dumps(a['source_json']))
        request = GenerationRequestV2.model_validate_json(json.dumps(a['request_json']))
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
        if inputs.static_facts is None:
            raise PrivateNativePending('private_native_original_execution_review_required')
        validation = inputs.static_facts.validation
        stored = self.conn.execute("SELECT payload_json FROM " + QUALITY_TABLE + " WHERE version_id=%s AND user_id=%s AND epoch=%s AND kind='validation' ORDER BY created_at DESC LIMIT 1", (a['version_id'],ref.user_id,ref.epoch)).fetchone()
        if stored is None or stored['payload_json'] != validation.model_dump(mode='json'):
            raise PrivateNativePending('private_native_original_validation_required')
        binding = CandidateBindingV2(candidate_key=str(a['candidate_id']),version_key=str(a['version_id']),
            source_hash=source.source_hash,content_hash=source.content_hash,policy_hash=policy.policy_hash,
            profile_hash=lease.profile.profile_hash,runtime_key=source.blueprint.runtime_profile_id or 'static-exact-v1',
            risk_tier=source.blueprint.publication_policy.risk_tier)
        ports = (solver,*reviewers)
        if any(getattr(port,'frozen_profile',None) != lease.profile for port in ports):
            raise PrivateNativePending('private_native_original_profile_ports_required')
        bindings = tuple(self.pipeline._provider_binding(lease,port.provider_identity.provider,port.provider_identity.model) for port in ports)
        bounds = self.pipeline._review_attempt_bounds(solver,reviewers)
        with finite_review_context(source,spec=spec,materials=request.materials):
            plan = review_resource_plan(source,binding=binding,validation_receipt=validation,solver=solver,reviewers=reviewers)
        if resources.requests < sum(bounds) or resources.input_tokens < plan.input_tokens or resources.output_tokens < plan.output_tokens:
            raise PrivateNativePending('private_native_complete_original_review_budget_required')
        reserved = self.pipeline.budget.reserve(lease=lease,reservation_key='private.native.review.'+uuid4().hex,
            amounts=resources,now=self._guard(ref,lease))
        if not reserved.allowed or reserved.reservation_id is None:
            raise PrivateNativePending('private_native_review_budget_pending')
        generation = GenerationReceiptV2.model_validate_json(json.dumps(a['receipt_json']))
        original = PreparedReview(lease,ref.scope_id,artifact_id,source,validation,binding,
            generation.provider.provider+'.item_author',reserved.reservation_id,'live',bounds,bindings,plan,configured_review_protocol(reviewers))
        if inputs.static_facts is None or type(solver) is not JsonBlindSolverV2 or any(type(r) is not JsonReviewerV2 for r in reviewers):
            raise PrivateNativePending('private_native_finite_concrete_ports_required')
        scorer = FiniteStaticBlindScorer(binding=binding, spec=spec, materials=request.materials)
        prepared = PreparedPrivateReview(ref, original, spec, request, policy, uuid4())
        self.conn.execute('SELECT item_supply_internal.private_pack_prepare_auxiliary(%s,%s,%s,%s,%s,%s)',
            (ref.pack_task_id,prepared.preparation_id,lease.job_id,reserved.reservation_id,
             Jsonb({'schema_version':'private_native_review_phase_v1','ref':ref.model_dump(mode='json'),
                 'lease':lease.model_dump(mode='json'),'artifact_id':str(artifact_id),'spec':spec.model_dump(mode='json'),
                 'policy':policy.model_dump(mode='json'),'binding':binding.model_dump(mode='json'),
                 'validation':validation.model_dump(mode='json')}),min(lease.expires_at,lease.parent_deadline)))
        self._prepared[prepared.preparation_id] = (prepared, self._seal(prepared), scorer, solver, reviewers)
        return prepared

    def run_review(self, p: PreparedPrivateReview) -> CompletedPrivateReview:
        ports = self._require(p)
        if ports is None:
            raise PrivateNativePending('private_committed_review_cannot_repeat_paid_call')
        scorer, solver, reviewers = ports
        if self.conn.info.transaction_status != TransactionStatus.IDLE or p.preparation_id in self._started:
            raise PrivateNativePending('private_native_review_idle_once_required')
        with self.conn.transaction():
            with self.current_source_front(p.ref) as actual:
                artifact = self._artifact(p.ref, p.original.lease, p.original.artifact_id)
                committed=self.conn.execute('SELECT item_supply_internal.private_pack_auxiliary_committed(%s,%s) AS ok',
                    (p.ref.pack_task_id,p.preparation_id)).fetchone()
                if committed is None or committed['ok'] is not True:
                    raise PrivateNativePending('private_review_committed_original_preparation_required')
                request = GenerationRequestV2.model_validate_json(json.dumps(artifact['request_json']))
                generation = GenerationReceiptV2.model_validate_json(json.dumps(artifact['receipt_json']))
                if request != p.request or len(p.request.materials) != len(generation.sources):
                    raise PrivateNativePending('private_review_exact_prepared_sources_required')
                for material, expected in zip(p.request.materials, generation.sources, strict=True):
                    self.source_authority.assert_current(material, expected)
                if actual is not None:
                    actual.require()
                now = self._guard(p.ref, p.original.lease)
                now = server_clock(self.conn, now)
                if actual is not None and now >= actual.source_deadline:
                    raise PrivateNativePending('private_review_current_source_required')
                from app.services.learning.item_supply.private_native_committed_progress import COMMITTED_WRITER_ID
                if p.original.lease.job_id == COMMITTED_WRITER_ID:
                    # Denial only for this C19 writer; prepared/current/once
                    # authority above remains mandatory. Accounting can wait.
                    from app.services.learning.item_supply.private_development_model_accounting import accounting_batch_for_lease
                    lease = p.original.lease
                    batch = accounting_batch_for_lease(self.conn,lease,now=now)
                    now = server_clock(self.conn,now)
                    if actual is None:
                        raise PrivateNativePending('private_review_current_source_required')
                    if batch is None:
                        raise PrivateNativePending('private_committed_quality_current_accounting_required')
                    deadline = min(lease.expires_at,lease.parent_deadline,lease.profile.parent_deadline_at,
                        lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms),
                        actual.source_deadline,batch['valid_until'])
                    if (deadline-now).total_seconds() <= 7*lease.profile.values.request_timeout_ms/1000+15:
                        raise PrivateNativePending('private_committed_quality_remaining_window_required')
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PrivateNativePending('private_native_review_idle_once_required')
        self._started.add(p.preparation_id)
        source, binding = p.original.source, p.original.binding
        ambiguity_owner = FiniteTaskAmbiguityOwner(None, parent_deadline_at=min(p.original.lease.expires_at, p.original.lease.parent_deadline))
        inputs = prepare_finite_candidate_validation(source, spec=p.spec, materials=p.request.materials)
        with finite_review_context(source, spec=p.spec, materials=p.request.materials):
            blind = blind_solve_candidate(source, binding=binding, author_identity=p.original.author_identity,
                solver=solver, scorer=scorer, blind_protocol=solver.blind_protocol)
            bundle = review_candidate_for_policy(source, binding=binding, validation_receipt=checked_validation_receipt(p.original.validation),
                author_identity=p.original.author_identity, blind_solve_receipt=blind, reviewers=reviewers,
                policy=p.policy, blind_protocol=solver.blind_protocol)
        plan = build_finite_ambiguity_plan(source, spec=p.spec, inputs=inputs)
        ambiguity = ambiguity_owner.run(source, plan, spec=p.spec, inputs=inputs, run_id=uuid4())
        result = CompletedPrivateReview(bundle, ambiguity)
        self._results[p.preparation_id] = (result, ambiguity_owner)
        return result

    def settle_review(self, p: PreparedPrivateReview) -> None:
        if self._require(p) is None:
            raise PrivateNativePending('private_committed_review_cannot_repeat_settlement')
        if p.preparation_id not in self._started:
            raise PrivateNativePending('private_native_review_not_started')
        self.pipeline.budget.settle(lease=p.original.lease, reservation_id=p.original.reservation_id,
            settlement_key='private.native.review.'+p.preparation_id.hex,usage_state='unknown',actual=None,cost_amount=None,receipt_hash=None)

    def persist_review(self, p: PreparedPrivateReview, result: CompletedPrivateReview) -> tuple[UUID, UUID]:
        if self._require(p) is None:
            raise PrivateNativePending('private_committed_review_cannot_rewrite_history')
        original = self._results.get(p.preparation_id)
        if original is None or original[0] is not result:
            raise PrivateNativePending('private_native_review_result_identity_required')
        now = self._guard(p.ref, p.original.lease)
        self._artifact(p.ref, p.original.lease, p.original.artifact_id)
        settled = self.conn.execute('SELECT id FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=%s AND user_id=%s AND epoch=%s',
            (p.original.reservation_id, p.ref.user_id, p.ref.epoch)).fetchone()
        if settled is None:
            raise PrivateNativePending('private_native_review_settlement_required')
        blind = self.conn.execute('INSERT INTO ' + QUALITY_TABLE + ' (id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,version_id,kind,job_id,payload_json,checked_at,valid_until) '
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'blind',%s,%s,%s,%s) RETURNING id",
            (uuid4(),p.ref.user_id,p.ref.epoch,p.ref.scope_id,p.ref.pack_task_id,p.ref.slot_id,p.ref.root_id,
             UUID(p.original.binding.version_key),p.original.lease.job_id,Jsonb(result.bundle.blind_solve.model_dump(mode='json')),
             now,min(p.original.lease.expires_at,p.original.lease.parent_deadline))).fetchone()
        if blind is None:
            raise PrivateNativePending('private_native_blind_storage_required')
        payload = {'schema_version': 'private_native_review_v1', 'ref': p.ref.model_dump(mode='json'),
            'lease': p.original.lease.model_dump(mode='json'), 'artifact_id': str(p.original.artifact_id),
            'spec': p.spec.model_dump(mode='json'), 'policy':p.policy.model_dump(mode='json'),
            'bundle': result.bundle.model_dump(mode='json'),
            'ambiguity': result.ambiguity.model_dump(mode='json'), 'reservation_id': str(p.original.reservation_id)}
        self.conn.execute('INSERT INTO ' + QUALITY_TABLE + ' (id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,version_id,kind,job_id,payload_json,checked_at,valid_until) '
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'review',%s,%s,%s,%s)",
            (p.preparation_id, p.ref.user_id, p.ref.epoch, p.ref.scope_id, p.ref.pack_task_id, p.ref.slot_id, p.ref.root_id,
             UUID(p.original.binding.version_key), p.original.lease.job_id, Jsonb(payload), now,
             min(p.original.lease.expires_at, p.original.lease.parent_deadline)))
        return UUID(str(blind['id'])), p.preparation_id

    def _committed(self, table: str, row_id: UUID, payload_hash: str, *, ref: PrivateSlotRef) -> None:
        if table not in {'tutor_item_supply_private_pipeline_receipts', QUALITY_TABLE}:
            raise PrivateNativePending('private_native_receipt_table_required')
        hash_column = 'receipt_hash' if table.endswith('pipeline_receipts') else 'payload_hash'
        row = self.conn.execute('SELECT ' + hash_column + ' AS hash,xmin::text::bigint=(txid_current() %% 4294967296) AS own '
            'FROM ' + table + ' WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s',
            (row_id, ref.user_id, ref.epoch, ref.scope_id)).fetchone()
        if row is None or row['own'] or row['hash'] != payload_hash:
            raise PrivateNativePending('private_native_committed_receipt_required')

    def _evidence(self, p: PreparedPrivateReview, result: CompletedPrivateReview) -> tuple[AdmissionEvidenceV2, tuple[str, ...], str]:
        ports = self._require(p)
        raw = self._results.get(p.preparation_id)
        inputs = prepare_finite_candidate_validation(p.original.source, spec=p.spec, materials=p.request.materials)
        static = inputs.static_facts
        if static is None or static.validation != p.original.validation:
            raise PrivateNativePending('private_native_original_machine_required')
        if ports is None:
            # Only SQL527's original committed7/UNKNOWN/binding chain plus this
            # fresh concrete issuer admits HISTORICAL evidence. No fake score,
            # reconstructed blind answer or new role run is synthesized.
            resumed = self._committed_reviews.get(p.preparation_id)
            if resumed is None or resumed.result is not result:
                raise PrivateNativePending('private_native_committed_result_identity_required')
            resumed.owner.require(resumed)
        else:
            scorer, _, _ = ports
            if (raw is None or raw[0] is not result
                    or not scorer.verify(result.bundle.blind_solve.score, p.original.source)
                    or not raw[1].verify(result.ambiguity, p.original.source, spec=p.spec, inputs=inputs)):
                raise PrivateNativePending('private_native_original_machine_and_blind_required')
            issued = scorer._issued.get(result.bundle.blind_solve.score.receipt_hash)
            if issued is None or canonical_hash(issued[2]) != result.bundle.blind_solve.solution_hash:
                raise PrivateNativePending('private_native_actual_blind_answer_required')
        reports = {r.role.value: r for r in result.bundle.reports}
        if len(reports) != 6 or any(reports[k].material_failure for k in ('curriculum', 'technical', 'ambiguity')):
            raise PrivateNativePending('private_native_coverage_pending')
        contested = {'coverage_gap', 'curriculum_mismatch', 'technical_failure', 'ambiguity', 'rubric_mismatch', 'profile_gap', 'unique_answer'}
        if any(f.safe_code in contested for r in result.bundle.reports for f in r.findings):
            raise PrivateNativePending('private_native_contested_coverage_pending')
        machine = (canonical_hash(static.model_dump(mode='json')),)
        proof = canonical_hash({'target': p.spec.target_definition_hash, 'source': p.original.source.source_hash,
            'spec': p.spec.specification_hash, 'clauses': [c.model_dump(mode='json') for c in p.spec.coverage_blueprint.clauses],
            'machine': list(machine), 'interpretation': result.ambiguity.receipt_hash,
            'reviews': {k: reports[k].report_hash for k in ('curriculum', 'technical', 'ambiguity')}})
        claims: set[str] = set()
        for material, expected in zip(p.request.materials, GenerationReceiptV2.model_validate_json(json.dumps(
                self._artifact(p.ref, p.original.lease, p.original.artifact_id)['receipt_json'])).sources, strict=True):
            current = self.source_authority.assert_current(material, expected)
            claims.update(current.claim_receipt_hashes)
        if not claims or sum(o.accepted for o in static.options) != 1 or sum(not o.accepted for o in static.options) != 3:
            raise PrivateNativePending('private_native_complete_unique_propositions_required')
        probes = tuple(ProbeOutcomeV2.model_validate({'probe': name, 'passed': True, 'receipt_hash': digest}) for name, digest in (
            ('correct', canonical_hash({'machine': machine, 'accepted': True})),
            ('incorrect', canonical_hash({'machine': machine, 'accepted': False})),
            ('ambiguity', result.ambiguity.receipt_hash)))
        return AdmissionEvidenceV2(binding=p.original.binding, validation_receipt_hash=p.original.validation.evidence_hash,
            source_current=True, source_claim_receipt_hashes=tuple(sorted(claims)), coverage_proof_hash=proof,
            probes=probes, scorer_available=True), machine, proof

    def issue(self, p: PreparedPrivateReview, result: CompletedPrivateReview, *,
              validation_receipt_id: UUID, blind_receipt_id: UUID, review_receipt_id: UUID,
              normal_readmission_id: UUID | None = None) -> PrivateNativeQualityV1:
        now = self._guard(p.ref, p.original.lease)
        self._require(p)
        if p.ref.parent_version_id is not None and self._normal.get(p.preparation_id) != normal_readmission_id:
            raise PrivateNativePending('private_native_normal_child_authority_required')
        if p.ref.parent_version_id is None and normal_readmission_id is not None:
            raise PrivateNativePending('private_native_normal_lineage_required')
        self._committed(QUALITY_TABLE, validation_receipt_id,
            canonical_hash(p.original.validation.model_dump(mode='json')), ref=p.ref)
        self._committed(QUALITY_TABLE, blind_receipt_id,
            result.bundle.blind_solve.receipt_hash, ref=p.ref)
        review_row = self.conn.execute('SELECT payload_json FROM ' + QUALITY_TABLE + " WHERE id=%s AND kind='review'",
            (review_receipt_id,)).fetchone()
        if review_row is None:
            raise PrivateNativePending('private_native_review_committed_required')
        self._committed(QUALITY_TABLE, review_receipt_id, canonical_hash(review_row['payload_json']), ref=p.ref)
        payload = review_row['payload_json']
        if (payload['bundle'] != result.bundle.model_dump(mode='json')
                or payload['spec'] != p.spec.model_dump(mode='json')
                or payload['ambiguity'] != result.ambiguity.model_dump(mode='json')
                or review_receipt_id != p.preparation_id):
            raise PrivateNativePending('private_native_review_binding_required')
        evidence, machine, proof = self._evidence(p, result)
        with finite_review_context(p.original.source, spec=p.spec, materials=p.request.materials):
            evaluation = evaluate_admission(p.original.source, binding=p.original.binding, policy=p.policy,
                validation_receipt=p.original.validation, author_identity=p.original.author_identity,
                bundle=result.bundle, evidence=evidence, enabled=True)
        if evaluation.disposition != 'eligible_internal':
            raise PrivateNativePending('private_native_full_risk_admission_pending')
        a = self._artifact(p.ref, p.original.lease, p.original.artifact_id)
        expiry = min(p.original.lease.expires_at, p.original.lease.parent_deadline)
        if p.preparation_id not in self._committed_reviews:
            expiry = min(expiry, result.ambiguity.parent_deadline_at)
        for material in p.request.materials:
            reviews = self.source_authority._current.governance.source_reviews
            coordinate = material.binding.evidence[0].binding
            review = None if reviews is None else reviews.resolve(coordinate.source_handle, coordinate.document_handle)
            if review is None or review.grant is None:
                raise PrivateNativePending('private_native_source_grant_required')
            expiry = min(expiry, review.grant.retained_until)
        require_aware(now)
        facts = PrivateNativeQualityV1(receipt_id=uuid4(), ref=p.ref, lease=p.original.lease,
            generation_artifact_id=p.original.artifact_id, version_id=UUID(str(a['version_id'])), source=p.original.source,
            spec=p.spec, request=p.request,
            source_receipts=GenerationReceiptV2.model_validate_json(json.dumps(a['receipt_json'])).sources,
            validation_receipt_id=validation_receipt_id, validation=p.original.validation, blind_receipt_id=blind_receipt_id,
            review_receipt_id=review_receipt_id, bundle=result.bundle, ambiguity=result.ambiguity,
            machine_hashes=machine, clause_proof_hash=proof, evidence=evidence, evaluation=evaluation,
            normal_readmission_id=normal_readmission_id, checked_at=now, valid_until=expiry)
        self._guard(p.ref, p.original.lease)
        self.conn.execute('INSERT INTO ' + QUALITY_TABLE + ' (id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,version_id,kind,job_id,payload_json,checked_at,valid_until) '
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'admission',%s,%s,%s,%s)",
            (facts.receipt_id, p.ref.user_id, p.ref.epoch, p.ref.scope_id, p.ref.pack_task_id, p.ref.slot_id, p.ref.root_id,
             facts.version_id, facts.lease.job_id, Jsonb(facts.model_dump(mode='json')), now, expiry))
        self._issued[facts.receipt_id] = (facts, p, result)
        return facts

    def verify(self, facts: PrivateNativeQualityV1) -> PrivateNativeQualityV1:
        saved = self._issued.get(facts.receipt_id)
        if saved is None or saved[0] is not facts:
            raise PrivateNativePending('private_native_facts_identity_required')
        now = self._guard(facts.ref, facts.lease)
        evidence, machine, proof = self._evidence(saved[1], saved[2])
        if not facts.checked_at <= now < facts.valid_until or (evidence, machine, proof) != (facts.evidence, facts.machine_hashes, facts.clause_proof_hash):
            raise PrivateNativePending('private_native_facts_current_required')
        row = self.conn.execute('SELECT payload_hash FROM ' + QUALITY_TABLE + ' WHERE id=%s AND user_id=%s AND epoch=%s',
            (facts.receipt_id, facts.ref.user_id, facts.ref.epoch)).fetchone()
        if row is None or row['payload_hash'] != facts.receipt_hash:
            raise PrivateNativePending('private_native_facts_storage_required')
        return facts
