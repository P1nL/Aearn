"""Default-off native issuer: reconstruct 493/494 facts on the same connection.

Old producer leases are historical. Current consumption has independent source,
publication, runtime, mapping and complete exposure fences. No JSON is a capability.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import json
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.native_publication import NativePublishedItemQuery
from app.services.learning.item_bank.native_publication_contracts import NativeConsumptionProofV1, NativePublicationPending, NativePublicationProofV1, build_native_practice_material
from app.services.learning.item_bank.practice_adapter import LEARNING_ITEM_PRACTICE_ADAPTER_VERSION
from app.services.learning.item_supply.admission import evaluate_admission
from app.services.learning.item_supply.contracts import ClauseCoverageV1, SourceAuthorizationFactsV1, Usage
from app.services.learning.item_supply.evidence import SourceEvidenceDenied, material_digest
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_course_mapping import FiniteCourseMappingOwner
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.native_type_contracts import (
    IssuedNativePackCapability, NativeRelationReport, NativeResolvedContent, NativeTypeEvidencePending,
)
from app.services.learning.item_supply.native_type_fingerprints import native_content_identity
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import (
    CompleteExposureV2, FamilyMemberEvidenceV2, NativeScopedCandidateV2, NativeScopedProofV2,
    PackCandidateV2, PackInputsV2, PackSnapshotV2,
)
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import lock_private_namespace, server_clock
from app.services.learning.item_supply.review_contracts_v2 import BlindSolveReceiptV2
from app.services.learning.item_supply.diagnostic_policy import completed_blind_allowed, parse_bundle, policy_for_hash
from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
from app.services.learning.item_supply.shared_continuation import (
    SharedCandidateContinuationBindingV1, bind_shared_candidate_continuation,
)
from app.services.learning.item_supply.sandbox.probe_plans import submission_fingerprint
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.type_evidence import (
    ContentRelationshipEvidenceV2, KCTypeEvidenceV2, PythonTypeEvidenceV2, RelationshipReviewV2,
    SQLiteTypeEvidenceV2, TypeAssessmentEvidenceV2, TypeProfileV2, relationship_binding_hash,
)
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

# Main integrates classification/export constants into the existing inventory.
NATIVE_TYPE_PRIVATE_TABLES = (
    "tutor_item_supply_native_content_facts", "tutor_item_supply_native_relation_preparations",
    "tutor_item_supply_native_relation_batches", "tutor_item_supply_native_eligibility",
)


def _model(model: type[Any], raw: Any) -> Any:
    return model.model_validate_json(json.dumps(raw))


def _original_profile_binding(row: dict[str, Any], request: GenerationRequestV2,
                              spec: FiniteCandidateSpecV1, facts: IssuedSharedAdmissionFactsV1) -> None:
    preparation = row["preparation_json"]
    lease = _model(JobLeaseV1, preparation["lease"])
    # State versions/heartbeats may advance between preparation and facts. The
    # original job/generation/owner/profile/deadline contract must not change.
    history_fields = {"state_version", "expires_at"}
    if (request != _model(GenerationRequestV2, row["request_json"])
            or canonical_hash(preparation) != row["preparation_hash"]
            or lease.profile.profile_hash != row["preparation_profile_hash"]
            or lease.model_dump(exclude=history_fields) != facts.lease.model_dump(exclude=history_fields)
            or UUID(str(row["root_id"])) != facts.root_id
            or preparation.get("continuation_binding_hash") != facts.continuation_binding_hash):
        raise ValueError("original preparation profile mismatch")
    continuation = row["continuation_row"]
    if UUID(str(row["job_id"])) == facts.lease.job_id:
        if (request.profile != lease.profile or row["lease_generation"] != lease.generation
                or facts.continuation_binding_hash is not None or continuation is not None):
            raise ValueError("original generation profile mismatch")
        return
    # A cross-job historical read needs the actual immutable491 row. Do not call
    # the live continuation owner, renew a lease, or restore an execution permit.
    if continuation is None or facts.continuation_binding_hash is None:
        raise ValueError("original continuation missing")
    binding = _model(SharedCandidateContinuationBindingV1, continuation["binding_json"])
    original = row["continuation_original"]
    if (continuation["binding_hash"] != binding.binding_hash
            or binding.binding_hash != facts.continuation_binding_hash
            or binding.adoption_lease.job_id != lease.job_id or binding.adoption_lease.profile != lease.profile
            or original["request_json"] != row["request_json"] or original["source_json"] != row["source_json"]
            or UUID(str(original["job_id"])) != UUID(str(row["job_id"]))
            or original["lease_generation"] != row["lease_generation"]
            or UUID(str(original["root_id"])) != facts.root_id
            or UUID(str(original["id"])) != facts.generation_artifact_id
            or original["artifact_hash"] != facts.artifact_hash):
        raise ValueError("original continuation binding mismatch")
    expected, _, _, _, _ = bind_shared_candidate_continuation(
        artifact=original, spec=spec, lease=binding.adoption_lease, operation_key=binding.operation_key)
    if binding != expected:
        raise ValueError("original continuation data changed")
    coordinates = {"job_id": binding.adoption_lease.job_id, "root_id": binding.root_id,
        "generation_artifact_id": binding.generation_artifact_id, "original_job_id": binding.original_job_id,
        "item_id": binding.item_id, "version_id": binding.version_id}
    if (any(UUID(str(continuation[key])) != value for key, value in coordinates.items())
            or continuation["original_lease_generation"] != binding.original_lease_generation
            or continuation["source_hash"] != binding.source_hash or continuation["content_hash"] != binding.content_hash
            or continuation["operation_key"] != binding.operation_key
            or continuation["publication_enabled"] is not False
            or binding.item_id != facts.item_id or binding.version_id != facts.version_id):
        raise ValueError("original continuation stored coordinates mismatch")


def reconstruct_native_content(row: dict[str, Any]) -> NativeResolvedContent:
    """Reconstruct immutable originals, never restore old issuance capabilities."""
    try:
        proof = _model(NativePublicationProofV1, row["proof_json"])
        spec = _model(FiniteCandidateSpecV1, row["preparation_json"]["spec"])
        source = _model(LearningItemSourceV1, row["source_json"])
        request = _model(GenerationRequestV2, row["preparation_json"]["request"])
        facts = _model(IssuedSharedAdmissionFactsV1, row["facts_json"])
        _original_profile_binding(row, request, spec, facts)
        validation = _model(CandidateValidationV2, row["validation_json"])
        blind = _model(BlindSolveReceiptV2, row["blind_json"])
        bundle = parse_bundle(row["review_json"])
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=proof.materials)
        material = build_native_practice_material(source, spec=spec, materials=proof.materials)
        material_hash = canonical_hash({"adapter_version": LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
            "learning_item_version_id": str(proof.version_id), "learning_item_handle": proof.item_handle,
            "learning_item_content_hash": source.content_hash, "exercise_version_id": str(proof.exercise_version_id),
            "exercise_content_hash": material.exercise.content_hash, "rubric_hash": material.rubric.rubric_hash})
        target = facts.target_proof
        with finite_review_context(source, spec=spec, materials=proof.materials):
            expected_evaluation = evaluate_admission(source, binding=bundle.binding,
                policy=policy_for_hash(proof.policy_hash), validation_receipt=validation,
                author_identity=bundle.author_identity, bundle=bundle, evidence=facts.evidence, enabled=True)
        if (request.materials != proof.materials or request.blueprint != source.blueprint
                or row["preparation_json"]["source_hash"] != source.source_hash
                or row["preparation_json"]["content_hash"] != source.content_hash
                or str(facts.generation_artifact_id) != row["preparation_json"]["artifact_id"]
                or facts.artifact_hash != row["preparation_json"]["artifact_hash"]
                or proof.evaluation_hash != facts.evaluation.evaluation_hash
                or proof.proof_hash != row["proof_hash"] or facts.receipt_hash != row["facts_hash"]
                or proof.facts_hash != facts.receipt_hash or proof.facts_receipt_id != facts.receipt_id
                or proof.generation_artifact_id != facts.generation_artifact_id
                or proof.version_id != facts.version_id or facts.evidence.binding.candidate_key != str(facts.item_id)
                or proof.lease != facts.lease or proof.specification_hash != spec.specification_hash
                or (source.source_hash, source.content_hash) != (proof.source_hash, proof.content_hash)
                or source.public.model_dump(mode="json") != row["public_json"]
                or facts.specification_hash != spec.specification_hash or facts.inputs_hash != inputs.inputs_hash
                or facts.public_task_hash != source.public.public_hash or facts.instance_hash != inputs.instance_hash
                or facts.evidence.binding != bundle.binding or facts.evaluation != expected_evaluation
                or expected_evaluation.disposition != "eligible_internal" or target is None
                or target.proof_hash != facts.evidence.coverage_proof_hash
                or facts.evidence.binding.policy_hash != proof.policy_hash
                or facts.evidence.binding.profile_hash != facts.profile_hash
                or (facts.evidence.binding.source_hash, facts.evidence.binding.content_hash)
                    != (source.source_hash, source.content_hash)
                or facts.validation_receipt_hash != validation.evidence_hash
                or facts.blind_receipt_hash != blind.receipt_hash or facts.review_receipt_hash != bundle.bundle_hash
                or (proof.validation_hash, proof.review_hash) != (validation.evidence_hash, bundle.bundle_hash)
                or bundle.blind_solve != blind or not completed_blind_allowed(blind, policy_for_hash(proof.policy_hash))
                or proof.validation_receipt_id != facts.validation_receipt_id
                or proof.review_receipt_id != facts.review_receipt_id
                or canonical_hash(facts.evidence.model_dump(mode="json")) != proof.evidence_hash
                or target.source_hash != source.source_hash or target.public_task_hash != source.public.public_hash
                or target.specification_hash != spec.specification_hash
                or target.validation_receipt_hash != validation.evidence_hash
                or target.blind_receipt_hash != blind.receipt_hash
                or target.ambiguity_receipt_hash != facts.ambiguity.receipt_hash
                or material.exercise.content_hash != row["exercise_content_hash"]
                or material.rubric.rubric_hash != row["rubric_hash"]
                or dict(material.runner_payload) != row["runner_material_json"]
                or canonical_hash(row["runner_material_json"]) != proof.runner_material_hash
                or row["materialization_hash"] != proof.materialization_hash or proof.materialization_hash != material_hash
                or not proof.checked_at <= row["published_at"] < proof.valid_until):
            raise ValueError("original binding mismatch")
        for material_source, receipt in zip(proof.materials, proof.source_receipts, strict=True):
            coordinate = material_source.binding.evidence[0]
            if (receipt.material_digest != material_digest(material_source)
                    or receipt.binding_digest != material_source.binding.binding_digest
                    or str(receipt.corpus_version_id) != coordinate.corpus_version_id
                    or receipt.active_generation != coordinate.active_generation):
                raise ValueError("original complete source receipt mismatch")
        reports = {r.role.value: r for r in bundle.reports}
        mappings = tuple((c.clause_id, c.clause_hash) for c in target.mappings)
        if (mappings != tuple((c.clause_id, c.clause_hash) for c in spec.coverage_blueprint.clauses)
                or any(c.curriculum_report_hash != reports["curriculum"].report_hash
                    or c.technical_report_hash != reports["technical"].report_hash
                    or c.ambiguity_report_hash != reports["ambiguity"].report_hash for c in target.mappings)):
            raise ValueError("original clause report mismatch")
        if inputs.static_facts is not None:
            if (validation != inputs.static_facts.validation or facts.validation_terminals
                    or facts.blind_terminals or facts.scorer_counts != dict(positive_cases=1,
                        negative_cases=3, false_positives=0, false_negatives=0, pending_cases=0)):
                raise ValueError("original static facts mismatch")
        else:
            execution = validation.execution_evidence
            plan = inputs.probe_plan
            if (execution is None or plan is None or not facts.validation_terminals or not facts.blind_terminals
                    or execution.mode != "live" or execution.isolation != "approved_os_boundary"
                    or facts.scorer_counts.get("pending_cases") != 0
                    or facts.scorer_counts.get("false_positives") != 0 or facts.scorer_counts.get("false_negatives") != 0
                    or not facts.scorer_counts.get("positive_cases") or not facts.scorer_counts.get("negative_cases")
                    or any(t.mode != "live" or t.isolation != "approved_os_boundary"
                        or t.lock_fingerprint != proof.runtime.runtime_profile_hash for t in facts.validation_terminals)
                    or any(p.status != "passed" for p in execution.probes)):
                raise ValueError("original execution facts mismatch")
        content = native_content_identity(source, spec, proof, bundle)
        return NativeResolvedContent(source, spec, proof, content, facts)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration):
        raise NativeTypeEvidencePending("native_original_facts_invalid") from None


class NativeTypeEvidenceOwner:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, user_id: UUID,
                 epoch: int, query: NativePublishedItemQuery, source_authority: RagSourceAuthority,
                 mapping_owner: FiniteCourseMappingOwner, enabled: bool = False) -> None:
        if (type(query) is not NativePublishedItemQuery or query.conn is not conn
                or type(source_authority) is not RagSourceAuthority or source_authority.connection is not conn
                or type(mapping_owner) is not FiniteCourseMappingOwner or mapping_owner.conn is not conn
                or mapping_owner.runtime_owner is not query):
            raise NativeTypeEvidencePending("native_type_concrete_same_connection_required")
        self.conn, self.settings, self.user_id, self.epoch = conn, settings, user_id, epoch
        self.query, self.source_authority, self.mapping_owner, self.enabled = query, source_authority, mapping_owner, enabled
        self._issued: dict[UUID, tuple[IssuedNativePackCapability, int, str, UUID, tuple[UUID, ...], UUID, tuple[UUID, ...]]] = {}

    def _guard(self) -> tuple[datetime, int]:
        if (not self.enabled or not self.settings.learning_item_supply_enabled
                or not self.settings.learning_item_v2_admission_enabled):
            raise NativeTypeEvidencePending("native_type_disabled")
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise NativeTypeEvidencePending("native_type_transaction_required")
        self.query.artifacts.require_owner()
        lock_private_namespace(self.conn, self.user_id, self.epoch)
        row = self.conn.execute("SELECT clock_timestamp() AS now,txid_current() AS txid").fetchone()
        if row is None:
            raise NativeTypeEvidencePending("native_type_clock_missing")
        return row["now"], int(row["txid"])

    def resolve_mapping(self, receipt_id: UUID) -> FiniteCourseMappingReceiptV1:
        self._guard()
        result = self.mapping_owner.resolve(receipt_id=receipt_id, user_id=self.user_id, epoch=self.epoch)
        if result.receipt is None:
            raise NativeTypeEvidencePending("native_mapping_current_required")
        return result.receipt

    def resolve_content(self, version_id: UUID, current: bool = True) -> NativeResolvedContent:
        self._guard()
        if type(current) is not bool:
            raise NativeTypeEvidencePending("native_content_current_mode_invalid")
        rows = self.conn.execute(
            "SELECT n.proof_json,n.proof_hash,n.runner_material_json,g.source_json,c.public_json,"
            "g.request_json,g.root_id,g.job_id,g.lease_generation,"
            "f.payload_json AS facts_json,f.payload_hash AS facts_hash,p.payload_json AS preparation_json,"
            "p.payload_hash AS preparation_hash,p.profile_hash AS preparation_profile_hash,"
            "to_jsonb(adoption) AS continuation_row,"
            "to_jsonb(g)||jsonb_build_object('canonical_key',roots.canonical_key,'coverage_json',bp.snapshot_json,"
            "'provider_key',obligation.provider_key,"
            "'generation_completed',EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp "
            "WHERE cp.job_id=g.job_id AND cp.lease_generation=g.lease_generation AND cp.stage='generating' "
            "AND cp.status='completed' AND cp.receipt_hash=g.artifact_hash),"
            "'generation_settled',EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s "
            "WHERE s.reservation_id=g.reservation_id AND s.settlement_key='generation.'||replace(g.candidate_id::text,'-',''))) "
            "AS continuation_original,"
            "v.payload_json AS validation_json,b.payload_json AS blind_json,r.payload_json AS review_json,"
            "m.exercise_content_hash,m.rubric_hash,m.receipt_hash AS materialization_hash,e.occurred_at AS published_at "
            "FROM tutor_learning_item_native_publication_proofs n "
            "JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=n.generation_artifact_id "
            "JOIN tutor_item_supply_shared_budget_roots roots ON roots.id=g.root_id "
            "JOIN tutor_item_supply_shared_blueprints bp ON bp.id=roots.blueprint_id "
            "JOIN tutor_item_supply_shared_obligations obligation ON obligation.root_id=roots.id "
            "JOIN tutor_learning_item_public_contents c ON c.version_id=n.version_id "
            "JOIN tutor_item_supply_shared_admission_facts f ON f.id=n.facts_receipt_id "
            "JOIN tutor_item_supply_shared_validation_preparations p ON p.id=f.validation_preparation_id "
            "AND p.job_id=f.job_id AND p.root_id=f.root_id AND p.lease_generation=f.lease_generation "
            "AND p.profile_hash=f.profile_hash AND p.continuation_binding_hash IS NOT DISTINCT FROM f.continuation_binding_hash "
            "LEFT JOIN tutor_item_supply_shared_candidate_continuations adoption ON adoption.job_id=f.job_id "
            "JOIN tutor_item_supply_shared_pipeline_receipts v ON v.id=f.validation_receipt_id "
            "JOIN tutor_item_supply_shared_pipeline_receipts b ON b.id=f.blind_receipt_id "
            "JOIN tutor_item_supply_shared_pipeline_receipts r ON r.id=f.review_receipt_id "
            "JOIN tutor_learning_item_practice_materializations m ON m.id=n.materialization_id "
            "JOIN tutor_learning_item_publication_events e ON e.id=n.publication_event_id AND e.state='published' "
            "WHERE n.version_id=%s ORDER BY n.created_at DESC LIMIT 2", (version_id,)).fetchall()
        if len(rows) != 1:
            raise NativeTypeEvidencePending("native_exact_original_publication_required")
        resolved = reconstruct_native_content(rows[0])
        if self.query.artifacts.published_generation_policy(rows[0]).policy_hash != resolved.publication.policy_hash:
            raise NativeTypeEvidencePending("native_content_generation_policy_mismatch")
        if resolved.publication.version_id != version_id:
            raise NativeTypeEvidencePending("native_content_version_mismatch")
        if current:
            try:
                found = self.query.query_exact(handle=resolved.content.item_handle, spec=resolved.spec,
                    source_authority=self.source_authority)
            except (NativePublicationPending, SourceEvidenceDenied):
                raise NativeTypeEvidencePending("native_content_current_required") from None
            if found is None or found.proof_id != resolved.publication.proof_id:
                raise NativeTypeEvidencePending("native_content_current_required")
            resolved = replace(resolved, consumption=found.consumption_proof)
        self._persist_content(resolved)
        return resolved

    def _persist_content(self, resolved: NativeResolvedContent) -> None:
        p, content = resolved.publication, resolved.content.model_dump(mode="json")
        self.conn.execute("INSERT INTO tutor_item_supply_native_content_facts "
            "(id,user_id,epoch,version_id,proof_id,proof_hash,content_json) VALUES(%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(user_id,epoch,version_id,proof_id) DO NOTHING",
            (uuid4(), self.user_id, self.epoch, p.version_id, p.proof_id, p.proof_hash, Jsonb(content)))
        row = self.conn.execute("SELECT content_json,content_hash,proof_hash FROM tutor_item_supply_native_content_facts "
            "WHERE user_id=%s AND epoch=%s AND version_id=%s AND proof_id=%s",
            (self.user_id, self.epoch, p.version_id, p.proof_id)).fetchone()
        if row is None or row["content_json"] != content or row["content_hash"] != canonical_hash(content) or row["proof_hash"] != p.proof_hash:
            raise NativeTypeEvidencePending("native_content_immutable_conflict")

    def source_deadline(self, resolved: NativeResolvedContent) -> datetime:
        deadline: datetime | None = None
        for material in resolved.publication.materials:
            reviews = self.source_authority._current.governance.source_reviews
            if reviews is None:
                raise NativeTypeEvidencePending("native_source_current_deadline_missing")
            review = reviews.resolve(material.binding.evidence[0].binding.source_handle, material.binding.evidence[0].binding.document_handle)
            if review is None or review.grant is None:
                raise NativeTypeEvidencePending("native_source_current_deadline_missing")
            deadline = review.grant.retained_until if deadline is None else min(deadline, review.grant.retained_until)
        if deadline is None:
            raise NativeTypeEvidencePending("native_source_current_deadline_missing")
        return deadline

    def _deadline(self, resolved: NativeResolvedContent, now: datetime) -> datetime:
        # Fresh bounded observation, never renewal of an old producer fact lease.
        deadline = min(now + timedelta(seconds=30), self.source_deadline(resolved))
        if deadline <= now:
            raise NativeTypeEvidencePending("native_source_current_deadline_missing")
        return deadline

    def _candidate(self, resolved: NativeResolvedContent, mapping: FiniteCourseMappingReceiptV1,
                   now: datetime) -> PackCandidateV2:
        source, spec, p, facts = resolved.source, resolved.spec, resolved.publication, resolved.facts
        if resolved.consumption is None:
            raise NativeTypeEvidencePending("native_candidate_current_consumption_required")
        current = checked_model(resolved.consumption, NativeConsumptionProofV1)
        if ((current.publication_proof_id, current.publication_proof_hash, current.version_id,
             current.source_hash, current.content_hash, current.specification_hash, current.materialization_hash)
                != (p.proof_id, p.proof_hash, p.version_id, p.source_hash, p.content_hash,
                    p.specification_hash, p.materialization_hash)
                or current.runtime_profile_hash != p.runtime.runtime_profile_hash
                or current.scorer_version != p.runtime.scorer_version or current.checked_at > now
                or len(current.current_source_receipt_hashes) != len(p.materials)):
            raise NativeTypeEvidencePending("native_candidate_current_consumption_mismatch")
        slot = spec.allocation.slot
        entry = next(e for e in mapping.pack_request.demands if e.slot == slot)
        scope = entry.demand.scope
        if (spec.target_id != mapping.target_id or spec.target_definition_hash != mapping.target_definition_hash
                or any(getattr(spec.coverage_blueprint.scope, k) != getattr(scope, k) for k in (
                    "runtime_profile_id", "runtime_profile_hash", "scorer_version", "assistance_policy_hash",
                    "subject_id", "subject_version", "required_facets", "required_capabilities", "assessment_contract_version"))):
            raise NativeTypeEvidencePending("native_candidate_mapping_mismatch")
        target = facts.target_proof
        if target is None or tuple((a, b) for a, b, _, _ in mapping.pack_request.clause_mapping) != tuple(
                (c.clause_id.upper(), c.clause_hash) for c in target.mappings):
            raise NativeTypeEvidencePending("native_clause_mapping_mismatch")
        clauses = tuple(ClauseCoverageV1(clause_id=c, clause_hash=h) for _, _, c, h in mapping.pack_request.clause_mapping)
        deadline = self._deadline(resolved, now)
        source_set_hash = canonical_hash(list(resolved.consumption.current_source_receipt_hashes))
        authorization_hash = canonical_hash({"mapping": mapping.source_authorization_hash,
            "publication": p.proof_hash, "source_set": source_set_hash,
            "current_consumption": canonical_hash(resolved.consumption.model_dump(mode="json")), "checked_at": now.isoformat()})
        common = dict(scope_hash=scope.scope_hash, objective_hash=entry.demand.objective_hash,
            target_definition_hash=mapping.target_definition_hash, course_mapping_hash=mapping.mapping_hash,
            runtime_profile_id=scope.runtime_profile_id, runtime_profile_hash=scope.runtime_profile_hash,
            scorer_version=scope.scorer_version, assistance_policy_hash=scope.assistance_policy_hash,
            validation_receipt_hash=facts.validation_receipt_hash, item_review_bundle_hash=facts.review_receipt_hash,
            receipt_id=uuid4(), checked_at=now, valid_until=deadline, content=resolved.content)
        if spec.target_id == "python-kc-binding-v1":
            static = prepare_finite_candidate_validation(source, spec=spec, materials=p.materials).static_facts
            if static is None:
                raise NativeTypeEvidencePending("native_static_facts_missing")
            extra = dict(truth_derivation_hash=static.instance_hash,
                all_options_verification_hash=canonical_hash([o.model_dump(mode="json") for o in static.options]),
                blind_solve_receipt_hash=facts.blind_receipt_hash, ambiguity_review_receipt_hash=facts.ambiguity.receipt_hash,
                misconception_review_receipt_hash=next(c.ambiguity_report_hash for c in target.mappings))
            evidence_type: type[Any] = KCTypeEvidenceV2
        else:
            inputs = prepare_finite_candidate_validation(source, spec=spec, materials=p.materials)
            plan = inputs.probe_plan
            terminals = {t.probe_name: t for t in facts.validation_terminals}
            required = ("reference", "equivalent", "wrong_rejected", "boundary")
            if plan is None or any(name not in terminals for name in required):
                raise NativeTypeEvidencePending("native_execution_controls_missing")
            extra = dict(terminal_receipt_hash=canonical_hash([t.model_dump(mode="json") for t in facts.validation_terminals]),
                scorer_receipt_hash=canonical_hash(facts.scorer_counts),
                reference_submission_hash=submission_fingerprint(source,
                    getattr(source.private.content, "standard_answer", getattr(source.private.content, "standard_query", ""))),
                equivalent_submission_hash=submission_fingerprint(source, plan.equivalent),
                reference_execution_hash=canonical_hash(terminals["reference"].model_dump(mode="json")),
                equivalent_execution_hash=canonical_hash(terminals["equivalent"].model_dump(mode="json")),
                wrong_solution_control_hash=canonical_hash(terminals["wrong_rejected"].model_dump(mode="json")),
                hardcoded_control_hash=canonical_hash({"boundary_terminal": terminals["boundary"].model_dump(mode="json"),
                    "independent_cases": plan.boundary_cases_json, "independent_tests": plan.boundary_tests_json}),
                boundary_control_hash=canonical_hash(terminals["boundary"].model_dump(mode="json")))
            evidence_type = PythonTypeEvidenceV2 if spec.python_goal is not None else SQLiteTypeEvidenceV2
        type_evidence: TypeAssessmentEvidenceV2 = evidence_type(**common, **extra,
            receipt_hash=canonical_hash({"facts": facts.receipt_hash, "scope": scope.scope_hash,
                "objective": entry.demand.objective_hash, "mapping": mapping.mapping_hash,
                "checked_at": now.isoformat(), "extra": extra}))
        source_coordinates = [m.binding.evidence[0].binding.model_dump(mode="json") for m in p.materials]
        # One bounded identity for the ENTIRE verified material/claim set. This is
        # not a grant or a guessed first-source alias; current native query checks
        # all original coordinates before this projection is issued.
        source_ref = "native-sources." + canonical_hash(source_coordinates)
        source_version = "source-set-v1." + canonical_hash([m.model_dump(mode="json") for m in p.materials])
        if any(m.binding.purpose != "assessment_evidence" for m in p.materials):
            raise NativeTypeEvidencePending("native_complete_source_purpose_mismatch")
        source_usage: Usage = "assessment_evidence"
        auth = SourceAuthorizationFactsV1(authorization_hash=authorization_hash,
            source_ref=source_ref, source_version=source_version, source_usage=source_usage,
            scope_hash=scope.scope_hash, objective_hash=entry.demand.objective_hash, content_hash=source.content_hash,
            evidence_hash=target.proof_hash, checked_at=now, valid_until=deadline, active=True)
        proof = NativeScopedProofV2(mapping_receipt_id=mapping.receipt_id, learner_id=self.user_id,
            epoch=self.epoch, storage_scope_id=entry.storage_scope_id, course_mapping_hash=mapping.mapping_hash,proof_id=str(p.proof_id), blueprint_hash=entry.blueprint.blueprint_hash,
            scope_hash=scope.scope_hash, objective_hash=entry.demand.objective_hash, item_handle=p.item_handle,
            content_hash=source.content_hash, clauses=clauses, slot=slot, candidate_family_id=spec.allocation.family_id,
            matrix_hash=entry.blueprint.matrix_hash, policy_version=entry.blueprint.policy_version,
            runtime_profile_id=scope.runtime_profile_id, runtime_profile_hash=scope.runtime_profile_hash,
            assessment_contract_version=scope.assessment_contract_version, scorer_version=scope.scorer_version,
            assistance_policy_hash=scope.assistance_policy_hash, source_ref=source_ref,
            source_version=source_version, source_usage=source_usage, evidence_hash=target.proof_hash,
            authorization_hash=auth.authorization_hash, authorization_checked_at=now,
            authorization_valid_until=deadline, issuer_version="native_type_evidence_v1", checked_at=now, valid_until=deadline)
        candidate = NativeScopedCandidateV2(mapping_receipt_id=mapping.receipt_id, learner_id=self.user_id,
            epoch=self.epoch, storage_scope_id=entry.storage_scope_id, course_mapping_hash=mapping.mapping_hash,scope=scope, item_handle=p.item_handle, content_hash=source.content_hash,
            candidate_family_id=spec.allocation.family_id, objective_hash=entry.demand.objective_hash,
            blueprint_hash=entry.blueprint.blueprint_hash, matrix_hash=entry.blueprint.matrix_hash,
            policy_version=entry.blueprint.policy_version, slot=slot, clauses=clauses, source_ref=source_ref,
            source_version=source_version, source_usage=source_usage, evidence_hash=target.proof_hash,
            visibility="public", owner_ref=None, proof=proof, current_authorization=auth,
            published=True, materialized=True, runtime_available=True, available_capabilities=scope.required_capabilities)
        family = next(f for f in families_for_course(spec.target_id) if f.family_id == spec.allocation.family_id)
        member_data: dict[str, Any] = dict(family_id=family.family_id, family_definition_hash=family.definition_hash,
            allocation_variant_id=spec.allocation.variant_id, allocation_definition_hash=spec.allocation.definition_hash,
            allocation_receipt_hash=canonical_hash(spec.allocation.model_dump(mode="json")),
            target_definition_hash=spec.target_definition_hash, actual_public_task_hash=source.public.public_hash,
            actual_fixture_hash=resolved.content.actual_fixture_hash, semantic_signature=family.definition_hash,
            course_mapping_hash=mapping.mapping_hash, candidate_content_hash=source.content_hash,
            slot=slot, purpose=source.public.purpose.value)
        member = FamilyMemberEvidenceV2(**member_data, receipt_hash=canonical_hash(member_data))
        return PackCandidateV2(candidate=candidate, member=member, type_evidence=type_evidence,
            publication_id=p.publication_event_id, materialization_id=p.materialization_id, proof_id=p.proof_id,
            version_id=p.version_id, owner_id=None, epoch=None, storage_scope_id=entry.storage_scope_id,
            original_publication_hash=p.proof_hash, original_materialization_hash=p.materialization_hash,
            original_proof_hash=target.proof_hash, complete_source_set_hash=source_set_hash,
            runtime_or_static_observation_hash=canonical_hash(resolved.consumption.model_dump(mode="json")),
            observed_at=now, valid_until=deadline)

    def _exposure(self, snapshot_id: UUID, now: datetime) -> CompleteExposureV2:
        row = self.conn.execute("SELECT * FROM tutor_item_supply_type_exposure_snapshots "
            "WHERE id=%s AND user_id=%s AND epoch=%s FOR SHARE",
            (snapshot_id, self.user_id, self.epoch)).fetchone()
        if row is None or row["snapshot_hash"] != canonical_hash(row["snapshot_json"]):
            raise NativeTypeEvidencePending("native_exposure_snapshot_missing")
        exposure = _model(CompleteExposureV2, row["snapshot_json"])
        valid = self.conn.execute("SELECT item_supply_internal.type_exposure_current(%s,%s,%s) AS current",
            (snapshot_id, self.user_id, self.epoch)).fetchone()
        if (valid is None or valid["current"] != row["snapshot_json"] or exposure.learner_id != self.user_id
                or exposure.epoch != self.epoch or not exposure.observed_at <= now < exposure.valid_until
                or row["checked_at"] != exposure.observed_at or row["valid_until"] != exposure.valid_until):
            raise NativeTypeEvidencePending("native_exposure_current_required")
        for event in exposure.records:
            original = self.resolve_content(event.content.version_id, current=False)
            if original.content != event.content:
                raise NativeTypeEvidencePending("native_historical_exposure_content_mismatch")
        return exposure

    def _relations(self, ids: tuple[UUID, ...], mapping: FiniteCourseMappingReceiptV1,
                   contents: dict[UUID, NativeResolvedContent], exposure: CompleteExposureV2,
                   now: datetime) -> tuple[ContentRelationshipEvidenceV2, ...]:
        from uuid import uuid5
        relations: dict[str, ContentRelationshipEvidenceV2] = {}
        for receipt_id in ids:
            row = self.conn.execute("SELECT * FROM tutor_item_supply_native_relation_batches "
                "WHERE id=%s AND user_id=%s AND epoch=%s AND mapping_receipt_id=%s FOR SHARE",
                (receipt_id, self.user_id, self.epoch, mapping.receipt_id)).fetchone()
            if (row is None or row["request_hash"] != mapping.pack_request.request_hash
                    or row["payload_hash"] != canonical_hash(row["payload_json"])
                    or not row["checked_at"] <= now < row["valid_until"]):
                raise NativeTypeEvidencePending("native_relation_current_bound_required")
            payload = row["payload_json"]
            reports = tuple(_model(NativeRelationReport, r) for r in payload["reports"])
            if ({r.role for r in reports} != {"curriculum", "technical", "ambiguity", "adversarial"}
                    or len(reports) != 4 or len({r.actor_id for r in reports}) != 4
                    or len({r.run.run_id for r in reports}) != 4
                    or any(not r.checked_at <= now < r.valid_until for r in reports)):
                raise NativeTypeEvidencePending("native_relation_independence_missing")
            for pair in payload["pairs"]:
                left, right = (contents.get(UUID(pair[k])) for k in ("left_version_id", "right_version_id"))
                if left is None or right is None:
                    # A persisted batch may cover other actual items; it never
                    # adds new comparisons by projection to this request.
                    continue
                profile = cast(TypeProfileV2, {"python-kc-binding-v1": "kc", "python-state-update-v1": "python",
                    "sqlite-predicate-order-v1": "sqlite"}[mapping.target_id])
                binding = relationship_binding_hash(profile=profile, request_hash=mapping.pack_request.request_hash,
                    left=left.content, right=right.content)
                if binding != pair["binding_hash"]:
                    raise NativeTypeEvidencePending("native_relation_content_mismatch")
                reviews = []
                for report in reports:
                    judgment = next((j for j in report.judgments if j.binding_hash == binding), None)
                    if judgment is None or report.actor_id in {left.content.author_id, right.content.author_id}:
                        raise NativeTypeEvidencePending("native_relation_pair_review_missing")
                    # Unique, deterministic projection of an actual immutable
                    # batch judgment; never fabricate a new provider run.
                    projection_hash = canonical_hash({"report": report.receipt_hash,
                        "judgment": judgment.model_dump(mode="json")})
                    reviews.append(RelationshipReviewV2(role=report.role, actor_id=report.actor_id,
                        receipt_id=uuid5(report.receipt_id, binding), receipt_hash=projection_hash,
                        covered_binding_hashes=(binding,), conclusion=judgment.conclusion,
                        rationale_evidence_hash=judgment.rationale_evidence_hash,
                        checked_at=report.checked_at, valid_until=report.valid_until))
                relation = ContentRelationshipEvidenceV2(profile=profile, request_hash=mapping.pack_request.request_hash,
                    left=left.content, right=right.content, exposure_receipt_hash=exposure.completeness_receipt_hash,
                    exposure_watermark=exposure.watermark, reviews=tuple(reviews),
                    # Exact stable501 batch identity/interval. The pair and
                    # current exposure are eligibility projections, not renewed
                    # immutable review data under an old receipt ID.
                    receipt_id=receipt_id, receipt_hash=row["payload_hash"],
                    checked_at=row["checked_at"], valid_until=row["valid_until"])
                old = relations.get(binding)
                if old is not None and old != relation:
                    raise NativeTypeEvidencePending("native_relation_conflicting_batches")
                relations[binding] = relation
        return tuple(relations[k] for k in sorted(relations))

    def _inputs(self, mapping_id: UUID, candidates: tuple[UUID, ...], exposure_id: UUID,
                relation_ids: tuple[UUID, ...]) -> PackInputsV2:
        self._guard()
        if (not 5 <= len(candidates) <= 16 or len(set(candidates)) != len(candidates)
                or not 1 <= len(relation_ids) <= 16 or len(set(relation_ids)) != len(relation_ids)):
            raise NativeTypeEvidencePending("native_pack_inputs_bound_invalid")
        mapping = self.resolve_mapping(mapping_id)
        contents = {v: self.resolve_content(v, current=True) for v in candidates}
        # query_exact stamps each consumption proof with a fresh DB clock.
        # Observe after those reads, not before, or valid proofs appear future-dated.
        now, _ = self._guard()
        exposure = self._exposure(exposure_id, now)
        records = tuple(self._candidate(c, mapping, now) for c in contents.values())
        for event in exposure.records:
            contents.setdefault(event.content.version_id, self.resolve_content(event.content.version_id, current=False))
        relations = self._relations(relation_ids, mapping, contents, exposure, now)
        # Recheck after every lock wait; pure build receives this new DB clock.
        self._guard()
        return PackInputsV2(request=mapping.pack_request, candidates=records, relationships=relations, exposure=exposure)

    def resolve_pack(self, mapping_receipt_id: UUID, candidate_version_ids: tuple[UUID, ...],
                     exposure_snapshot_id: UUID, relation_receipt_ids: tuple[UUID, ...]) -> IssuedNativePackCapability:
        inputs = self._inputs(mapping_receipt_id, candidate_version_ids, exposure_snapshot_id, relation_receipt_ids)
        now, txid = self._guard()
        result = build_pack(inputs, now=now)
        if result.snapshot is None:
            raise NativeTypeEvidencePending("native_pack_" + result.status)
        snapshot = result.snapshot
        eid = uuid4()
        self.conn.execute("INSERT INTO tutor_item_supply_native_eligibility "
            "(id,user_id,epoch,mapping_receipt_id,exposure_snapshot_id,request_hash,inputs_hash,"
            "snapshot_json,checked_at,valid_until,txid,candidate_version_ids,relation_receipt_ids) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (eid, self.user_id, self.epoch, mapping_receipt_id, exposure_snapshot_id, inputs.request.request_hash,
             inputs.inputs_hash, Jsonb(snapshot.model_dump(mode="json")), now, snapshot.valid_until, txid,
             list(candidate_version_ids), list(relation_receipt_ids)))
        cap = IssuedNativePackCapability(eid, snapshot)
        self._issued[eid] = (cap, txid, snapshot.snapshot_hash, mapping_receipt_id,
                            candidate_version_ids, exposure_snapshot_id, relation_receipt_ids)
        return cap

    def require_pack(self, capability: IssuedNativePackCapability) -> PackSnapshotV2:
        if type(capability) is not IssuedNativePackCapability:
            raise NativeTypeEvidencePending("native_pack_owner_capability_required")
        now, txid = self._guard()
        entry = self._issued.get(capability.eligibility_id)
        if (entry is None or entry[0] is not capability or entry[1] != txid
                or capability.snapshot.snapshot_hash != entry[2]
                or not capability.snapshot.checked_at <= now < capability.snapshot.valid_until):
            raise NativeTypeEvidencePending("native_pack_owner_capability_required")
        row = self.conn.execute("SELECT snapshot_hash FROM tutor_item_supply_native_eligibility "
            "WHERE id=%s AND user_id=%s AND epoch=%s AND txid=%s AND valid_until>clock_timestamp() FOR SHARE",
            (capability.eligibility_id, self.user_id, self.epoch, txid)).fetchone()
        if row is None or row["snapshot_hash"] != entry[2]:
            raise NativeTypeEvidencePending("native_pack_persisted_capability_missing")
        self.resolve_mapping(entry[3])
        self._exposure(entry[5], now)
        for version in entry[4]:
            self.resolve_content(version, current=True)
        # Still-valid original content relation rows, including conflict/uncertain
        # vetoes, cannot be swapped by mutating the capability object.
        final = server_clock(self.conn, now)
        if final >= capability.snapshot.valid_until:
            raise NativeTypeEvidencePending("native_pack_deadline_elapsed")
        return capability.snapshot
