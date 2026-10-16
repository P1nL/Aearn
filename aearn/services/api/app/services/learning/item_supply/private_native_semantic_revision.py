"""PRIVATE registered semantic child issuer; original generation/review writers.

The generic compiler supplies DATA only. Parent investigation/resume, PRIVATE
phase, current sources, reservation, SQL531 and complete new recheck issue all
actual authority. No public admission capability, relabeled receipt or seed swap.
Relation-only investigation is NOT synthesized as a six-peer finding here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.admission import evaluate_admission
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_semantic_revision_data import (
    RegisteredSemanticChildInputV1, RegisteredSemanticChildPlanV1,
    compile_registered_semantic_child, registered_semantic_child_kinds,
    verify_registered_semantic_child,
)
from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2, GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline import PreparedGeneration
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.private_finite_factory import build_private_generation_request
from app.services.learning.item_supply.private_native_admission_facts import (
    QUALITY_TABLE, CompletedPrivateReview, PreparedPrivateReview,
)
from app.services.learning.item_supply.private_native_committed_progress import (
    PrivateNativeCommittedProgressOwner,
)
from app.services.learning.item_supply.private_native_review_loop import PrivateNativeNormalReviewLoopOwner
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider
from app.services.learning.item_supply.review_deliberation import substantive_revision_hash


@dataclass(frozen=True)
class IssuedPrivateSemanticParent:
    owner: PrivateNativeSemanticReadmissionOwner
    resume_id: UUID
    investigation_id: UUID
    ref: PrivateSlotRef
    parent_ref: PrivateSlotRef
    lease: JobLeaseV1
    version_id: UUID
    spec: FiniteCandidateSpecV1
    request: GenerationRequestV2
    source: LearningItemSourceV1
    directive: str



@dataclass(frozen=True)
class PreparedPrivateSemanticRevision:
    preparation_id: UUID
    investigation_id: UUID
    parent_resume_id: UUID
    ref: PrivateSlotRef
    lease: JobLeaseV1
    plan: RegisteredSemanticChildPlanV1
    compiler_input: RegisteredSemanticChildInputV1
    generation: PreparedGeneration
    parent_source: LearningItemSourceV1
    directive: str


class PrivateNativeSemanticReadmissionOwner:
    """Independent PRIVATE issuer; default-off; no JSON preparation restoration."""

    def __init__(self, loop: PrivateNativeNormalReviewLoopOwner, *,
                 progress: PrivateNativeCommittedProgressOwner, enabled: bool = False) -> None:
        if (type(loop) is not PrivateNativeNormalReviewLoopOwner
                or type(progress) is not PrivateNativeCommittedProgressOwner
                or progress.facts_owner is not loop.facts_owner):
            raise PrivateNativePending('private_semantic_original_concrete_owners_required')
        self.loop, self.progress, self.facts_owner = loop, progress, loop.facts_owner
        self.conn, self.enabled = loop.conn, enabled
        self._parents: dict[UUID, tuple[IssuedPrivateSemanticParent, str]] = {}
        self._prepared: dict[UUID, tuple[PreparedPrivateSemanticRevision, OpenAICompatibleGenerationProvider, str]] = {}
        self._runs: dict[UUID, GenerationResultV2 | None] = {}
        self._children: dict[UUID, PreparedPrivateSemanticRevision] = {}

    def _installed(self) -> None:
        if not self.enabled:
            raise PrivateNativePending('private_semantic_disabled')
        row = self.conn.execute(
            "SELECT to_regprocedure('item_supply_internal.assert_private_native_semantic_normal("
            "tutor_item_supply_private_native_quality_evidence)') IS NOT NULL "
            "AND to_regprocedure('item_supply_internal.assert_private_native_semantic_preparation("
            "tutor_item_supply_private_persistent_pack_journal)') IS NOT NULL AS ok").fetchone()
        if row is None or row['ok'] is not True:
            raise PrivateNativePending('private_semantic_original531_receiver_required')

    @staticmethod
    def _seal(p: PreparedPrivateSemanticRevision) -> str:
        return canonical_hash({'ref': p.ref.model_dump(mode='json'), 'lease': p.lease.model_dump(mode='json'),
            'investigation_id': str(p.investigation_id), 'parent_resume_id': str(p.parent_resume_id),
            'plan': p.plan.model_dump(mode='json'), 'compiler_input': p.compiler_input.model_dump(mode='json'),
            'request': p.generation.request.model_dump(mode='json'), 'directive': p.directive,
            'parent_source_hash': p.parent_source.source_hash})

    def _require(self, p: PreparedPrivateSemanticRevision) -> OpenAICompatibleGenerationProvider:
        saved = self._prepared.get(p.preparation_id)
        if saved is None or saved[0] is not p or saved[2] != self._seal(p):
            raise PrivateNativePending('private_semantic_concrete_preparation_identity_required')
        verify_registered_semantic_child(p.compiler_input, p.plan)
        return saved[1]

    @staticmethod
    def _parent_seal(p: IssuedPrivateSemanticParent) -> str:
        return canonical_hash({'ref': p.ref.model_dump(mode='json'), 'parent_ref': p.parent_ref.model_dump(mode='json'),
            'lease': p.lease.model_dump(mode='json'), 'investigation_id': str(p.investigation_id),
            'version_id': str(p.version_id), 'spec': p.spec.model_dump(mode='json'),
            'request': p.request.model_dump(mode='json'), 'source_hash': p.source.source_hash, 'directive': p.directive})

    def issue_parent(self, investigation_id: UUID, *, ref: PrivateSlotRef,
                     lease: JobLeaseV1) -> IssuedPrivateSemanticParent:
        self._installed()
        self.facts_owner._guard(ref, lease)
        investigation = self.conn.execute('SELECT payload_json FROM ' + QUALITY_TABLE +
            " WHERE id=%s AND kind='investigation' AND user_id=%s AND epoch=%s AND scope_id=%s AND pack_task_id=%s AND slot_id=%s AND root_id=%s",
            (investigation_id, ref.user_id, ref.epoch, ref.scope_id, ref.pack_task_id, ref.slot_id, ref.root_id)).fetchone()
        if investigation is None:
            raise PrivateNativePending('private_semantic_actual_private_investigation_required')
        inv = investigation['payload_json']
        if inv['schema_version'] != 'private_native_investigation_v1':
            raise PrivateNativePending('private_semantic_relation_investigation_owner_pending')
        row = self.conn.execute('SELECT payload_json FROM ' + QUALITY_TABLE + " WHERE id=%s AND kind='review'",
            (UUID(inv['parent_review_id']),)).fetchone()
        if row is None:
            raise PrivateNativePending('private_semantic_parent_review_required')
        payload = row['payload_json']
        old = checked_model(payload['ref'], PrivateSlotRef)
        actual_parent = UUID(payload['bundle']['binding']['version_key'])
        if (ref.parent_version_id != actual_parent
                or ref.model_dump(exclude={'parent_version_id'}) != old.model_dump(exclude={'parent_version_id'})):
            raise PrivateNativePending('private_semantic_exact_immutable_parent_and_current_child_refs_required')
        artifact = self.facts_owner._artifact(ref, lease, UUID(payload['artifact_id']))
        source = LearningItemSourceV1.model_validate_json(json.dumps(artifact['source_json']))
        request = GenerationRequestV2.model_validate_json(json.dumps(artifact['request_json']))
        spec = checked_model(payload['spec'], FiniteCandidateSpecV1)
        evidence_ids: dict[str, UUID] = {}
        for kind, evidence in (('validation', payload['bundle']['binding']), ('blind', payload['bundle']['blind_solve'])):
            if kind == 'validation':
                saved = self.conn.execute('SELECT id FROM ' + QUALITY_TABLE +
                    " WHERE kind='validation' AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s AND job_id=%s "
                    "AND payload_json->>'source_hash'=%s AND payload_json->>'content_hash'=%s ORDER BY created_at,id LIMIT 1",
                    (ref.user_id, ref.epoch, ref.scope_id, actual_parent, UUID(payload['lease']['job_id']),
                        source.source_hash, source.content_hash)).fetchone()
            else:
                saved = self.conn.execute('SELECT id FROM ' + QUALITY_TABLE +
                    " WHERE kind='blind' AND user_id=%s AND epoch=%s AND scope_id=%s AND version_id=%s AND job_id=%s "
                    "AND payload_json=%s ORDER BY created_at,id LIMIT 1",
                    (ref.user_id, ref.epoch, ref.scope_id, actual_parent, UUID(payload['lease']['job_id']), Jsonb(evidence))).fetchone()
            if saved is None:
                raise PrivateNativePending('private_semantic_complete_actual_parent_evidence_required')
            evidence_ids[kind] = UUID(str(saved['id']))
        directive = '\n'.join(a['proposed_revision'] for a in inv['output']['analyses'] if a.get('proposed_revision'))
        if not directive:
            raise PrivateNativePending('private_semantic_specific_substantive_investigation_required')
        rid = uuid4()
        frame = {'schema_version': 'private_native_semantic_parent_resume_v1',
            'ref': ref.model_dump(mode='json'), 'parent_ref': old.model_dump(mode='json'),
            'investigation_id': str(investigation_id), 'lease': lease.model_dump(mode='json'),
            'review_id': inv['parent_review_id'], 'validation_id': str(evidence_ids['validation']),
            'blind_id': str(evidence_ids['blind']), 'artifact_id': str(artifact['id'])}
        self.conn.execute('SELECT item_supply_internal.private_native_semantic_parent_record(%s,%s)', (rid, Jsonb(frame)))
        parent = IssuedPrivateSemanticParent(self, rid, investigation_id, ref, old, lease,
            actual_parent, spec, request, source, directive)
        self._parents[rid] = (parent, self._parent_seal(parent))
        self.require_parent(parent)
        return parent

    def require_parent(self, parent: IssuedPrivateSemanticParent) -> None:
        saved = self._parents.get(parent.resume_id)
        if (type(parent) is not IssuedPrivateSemanticParent or parent.owner is not self
                or saved is None or saved[0] is not parent or saved[1] != self._parent_seal(parent)):
            raise PrivateNativePending('private_semantic_fresh_concrete_parent_issuer_required')
        self.facts_owner._guard(parent.ref, parent.lease)
        checked = self.conn.execute('SELECT item_supply_internal.private_native_semantic_parent_current(%s,%s) AS ok',
            (parent.resume_id, parent.lease.job_id)).fetchone()
        if checked is None or checked['ok'] is not True:
            raise PrivateNativePending('private_semantic_current_original_parent_receiver_required')

    def prepare_revision(self, investigation_id: UUID, *, parent: IssuedPrivateSemanticParent,
                         ref: PrivateSlotRef, lease: JobLeaseV1, child_version: str,
                         provider: OpenAICompatibleGenerationProvider) -> PreparedPrivateSemanticRevision:
        self._installed()
        self.require_parent(parent)
        if type(provider) is not OpenAICompatibleGenerationProvider or provider.request_attempt_bound != 1:
            raise PrivateNativePending('private_semantic_original_once_author_required')
        if parent.ref != ref or parent.lease != lease or parent.investigation_id != investigation_id:
            raise PrivateNativePending('private_semantic_same_task_root_business_slot_required')
        actual_parent = parent.version_id
        if parent.spec.target_id != 'python-kc-binding-v1':
            raise PrivateNativePending('private_semantic_execution_recheck_owner_not_available')
        choices = registered_semantic_child_kinds(parent.spec)
        if not choices:
            raise PrivateNativePending('private_semantic_registered_substantive_revision_not_available')
        compiler_input = RegisteredSemanticChildInputV1(
            business_item_id=ref.business_item_id, root_id=ref.root_id, parent_version_id=actual_parent,
            parent_specification=parent.spec, materials=parent.request.materials,
            selected_task_kind=choices[0], child_item_key=parent.source.public.item_key,
            child_version=child_version)
        plan = compile_registered_semantic_child(compiler_input)
        verify_registered_semantic_child(compiler_input, plan)
        request = build_private_generation_request(self.facts_owner, ref=ref, lease=lease,
            spec=plan.child_specification, materials=compiler_input.materials,
            limits=GenerationLimitsV2(max_input_bytes=262144,
                max_output_tokens=self.facts_owner.settings.tutor_max_output_tokens, max_output_bytes=262144))
        gen = self.facts_owner.pipeline.prepare_generation(lease=lease, scope_id=ref.scope_id,
            request=request, provider=provider, source_authority=self.facts_owner.source_authority, mode='live')
        if gen is None:
            raise PrivateNativePending('private_semantic_original_generation_reservation_required')
        p = PreparedPrivateSemanticRevision(uuid4(), investigation_id, parent.resume_id, ref, lease,
            plan, compiler_input, gen, parent.source, parent.directive)
        frame = {'schema_version': 'private_native_semantic_revision_phase_v1', 'ref': ref.model_dump(mode='json'),
            'lease': lease.model_dump(mode='json'), 'investigation_id': str(investigation_id),
            'parent_version_id': str(actual_parent), 'parent_resume_id': str(parent.resume_id),
            'request': request.model_dump(mode='json'), 'directive_hash': canonical_hash(p.directive),
            'compiler_plan': plan.model_dump(mode='json'), 'compiler_plan_hash': plan.plan_hash}
        self.conn.execute('SELECT item_supply_internal.private_pack_prepare_auxiliary(%s,%s,%s,%s,%s,%s)',
            (ref.pack_task_id, p.preparation_id, lease.job_id, gen.reservation_id, Jsonb(frame),
                min(lease.expires_at, lease.parent_deadline)))
        self._prepared[p.preparation_id] = (p, provider, self._seal(p))
        return p

    def run_revision(self, p: PreparedPrivateSemanticRevision) -> GenerationResultV2:
        provider = self._require(p)
        if p.preparation_id in self._runs or self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PrivateNativePending('private_semantic_committed_idle_once_required')
        with self.conn.transaction():
            self._installed()
            self.facts_owner._guard(p.ref, p.lease)
            for material, expected in zip(p.generation.request.materials, p.generation.sources, strict=True):
                self.facts_owner.source_authority.assert_current(material, expected)
            row = self.conn.execute('SELECT item_supply_internal.private_pack_auxiliary_committed(%s,%s) AS ok',
                (p.ref.pack_task_id, p.preparation_id)).fetchone()
            if row is None or row['ok'] is not True:
                raise PrivateNativePending('private_semantic_committed_preparation_required')
        self._runs[p.preparation_id] = None  # Never reconstruct/replay a paid preparation.
        result = self.facts_owner.pipeline.run_generation(p.generation, provider)
        self._runs[p.preparation_id] = result
        return result

    def settle_revision(self, p: PreparedPrivateSemanticRevision, result: GenerationResultV2) -> None:
        self._require(p)
        if self._runs.get(p.preparation_id) is not result:
            raise PrivateNativePending('private_semantic_original_author_result_required')
        self.facts_owner.pipeline.settle_generation(p.generation, result)

    def persist_revision(self, p: PreparedPrivateSemanticRevision, result: GenerationResultV2) -> UUID:
        self._require(p)
        self.facts_owner._guard(p.ref, p.lease)
        if self._runs.get(p.preparation_id) is not result:
            raise PrivateNativePending('private_semantic_actual_once_result_required')
        stored = self.facts_owner.pipeline.commit_generation(p.generation, result,
            source_authority=self.facts_owner.source_authority, private_slot_ref=p.ref)
        if stored.artifact_id is None:
            raise PrivateNativePending('private_semantic_original_new_artifact_required')
        self._children[stored.artifact_id] = p
        return stored.artifact_id

    def issue_current_re_admission(self, p: PreparedPrivateReview, result: CompletedPrivateReview, *,
                                   validation_receipt_id: UUID, blind_receipt_id: UUID,
                                   review_receipt_id: UUID) -> UUID:
        self._installed()
        self.facts_owner._require(p)
        child = self._children.get(p.original.artifact_id)
        if (child is None or p.ref != child.ref or p.spec != child.plan.child_specification
                or p.original.source.public.content != child.plan.child_specification.public_template.content
                or substantive_revision_hash(p.original.source) == substantive_revision_hash(child.parent_source)):
            raise PrivateNativePending('private_semantic_exact_issued_registered_child_required')
        self._require(child)
        now = self.facts_owner._guard(p.ref, p.original.lease)
        self.facts_owner._committed(QUALITY_TABLE, validation_receipt_id,
            canonical_hash(p.original.validation.model_dump(mode='json')), ref=p.ref)
        self.facts_owner._committed(QUALITY_TABLE, blind_receipt_id, result.bundle.blind_solve.receipt_hash, ref=p.ref)
        row = self.conn.execute('SELECT payload_json FROM ' + QUALITY_TABLE + " WHERE id=%s AND kind='review'",
            (review_receipt_id,)).fetchone()
        if row is None or review_receipt_id != p.preparation_id:
            raise PrivateNativePending('private_semantic_complete_actual_child_review_required')
        self.facts_owner._committed(QUALITY_TABLE, review_receipt_id, canonical_hash(row['payload_json']), ref=p.ref)
        if row['payload_json']['bundle'] != result.bundle.model_dump(mode='json'):
            raise PrivateNativePending('private_semantic_actual_new_blind_and_six_peer_required')
        evidence, machine, clause_proof = self.facts_owner._evidence(p, result)
        with finite_review_context(p.original.source, spec=p.spec, materials=p.request.materials):
            evaluation = evaluate_admission(p.original.source, binding=p.original.binding, policy=p.policy,
                validation_receipt=p.original.validation, author_identity=p.original.author_identity,
                bundle=result.bundle, evidence=evidence, enabled=True)
        if evaluation.disposition != 'eligible_internal':
            raise PrivateNativePending('private_semantic_new_child_full_risk_pending')
        investigation = self.conn.execute('SELECT payload_json,payload_hash FROM ' + QUALITY_TABLE +
            " WHERE id=%s AND kind='investigation' AND user_id=%s AND epoch=%s AND scope_id=%s",
            (child.investigation_id, p.ref.user_id, p.ref.epoch, p.ref.scope_id)).fetchone()
        if investigation is None:
            raise PrivateNativePending('private_semantic_original_investigation_required')
        parent_review_id = UUID(investigation['payload_json']['parent_review_id'])
        parent_review = self.conn.execute('SELECT payload_hash FROM ' + QUALITY_TABLE +
            " WHERE id=%s AND kind='review' AND user_id=%s AND epoch=%s",
            (parent_review_id, p.ref.user_id, p.ref.epoch)).fetchone()
        if parent_review is None:
            raise PrivateNativePending('private_semantic_original_parent_review_required')
        artifact = self.facts_owner._artifact(p.ref, p.original.lease, p.original.artifact_id)
        payload: dict[str, Any] = {'schema_version': 'private_native_semantic_normal_readmission_v1',
            'ref': p.ref.model_dump(mode='json'), 'investigation_id': str(child.investigation_id),
            'investigation_hash': investigation['payload_hash'], 'revision_preparation_id': str(child.preparation_id),
            'revision_request_hash': canonical_hash(child.generation.request.model_dump(mode='json')),
            'child_artifact_id': str(p.original.artifact_id), 'child_artifact_hash': artifact['artifact_hash'],
            'parent_version_id': str(p.ref.parent_version_id), 'parent_review_id': str(parent_review_id),
            'parent_review_hash': parent_review['payload_hash'],
            'parent_substantive_hash': substantive_revision_hash(child.parent_source),
            'child_substantive_hash': substantive_revision_hash(p.original.source),
            'validation_id': str(validation_receipt_id), 'validation_hash': canonical_hash(p.original.validation.model_dump(mode='json')),
            'blind_id': str(blind_receipt_id), 'blind_hash': result.bundle.blind_solve.receipt_hash,
            'review_id': str(review_receipt_id), 'review_hash': canonical_hash(row['payload_json']),
            'policy': p.policy.model_dump(mode='json'), 'evidence': evidence.model_dump(mode='json'),
            'machine_hashes': list(machine), 'clause_proof_hash': clause_proof,
            'evaluation': evaluation.model_dump(mode='json'), 'source_hash': p.original.source.source_hash,
            'content_hash': p.original.source.content_hash}
        rid = uuid4()
        self.conn.execute('INSERT INTO ' + QUALITY_TABLE +
            ' (id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,version_id,kind,job_id,payload_json,checked_at,valid_until) '
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'normal',%s,%s,%s,%s)",
            (rid, p.ref.user_id, p.ref.epoch, p.ref.scope_id, p.ref.pack_task_id, p.ref.slot_id, p.ref.root_id,
                UUID(p.original.binding.version_key), p.original.lease.job_id, Jsonb(payload), now,
                min(p.original.lease.expires_at, p.original.lease.parent_deadline)))
        self.facts_owner._normal[p.preparation_id] = rid  # Only after original SQL531 receiver succeeds.
        return rid

