"""Default-off native issuer: reconstruct 493/494 facts on the same connection.

Old producer leases are historical. Current consumption has independent source,
publication, runtime, mapping and complete exposure fences. No JSON is a capability.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime
import json
from typing import TYPE_CHECKING, Any, Iterator, cast
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
from app.services.learning.item_supply.native_exposure_contracts import CURRENT_PACK_TTL
from app.services.learning.item_supply.native_type_fingerprints import native_content_identity
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import (
    AuthorizedSubDemandV1, CompleteExposureV2, FamilyMemberEvidenceV2, NativeScopedCandidateV2, NativeScopedProofV2,
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

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposureSnapshot


@dataclass
class _CurrentPackData:
    txid: int
    mapping_id: UUID
    versions: tuple[UUID, ...]
    relation_ids: tuple[UUID, ...]
    exposure_owner: NativeExposureOwnerV2
    source_binding: IssuedCurrentPackSourceBinding | None
    mapping: FiniteCourseMappingReceiptV1 | None = None
    contents: dict[UUID, NativeResolvedContent] = field(default_factory=dict)
    historical: dict[UUID, NativeResolvedContent] = field(default_factory=dict)
    published_at: dict[UUID, datetime] = field(default_factory=dict)
    source_deadlines: dict[UUID, datetime] = field(default_factory=dict)
    extras: dict[UUID, tuple[type[Any], dict[str, Any]]] = field(default_factory=dict)
    projections: dict[UUID, tuple[PackCandidateV2, dict[str, Any], dict[str, Any]]] = field(default_factory=dict)
    relation_rows: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    observation: NativeTypeExposureSnapshot | None = None
    inputs: PackInputsV2 | None = None
    capability: IssuedNativePackCapability | None = None

# Main integrates classification/export constants into the existing inventory.
NATIVE_TYPE_PRIVATE_TABLES = (
    "tutor_item_supply_native_content_facts", "tutor_item_supply_native_relation_preparations",
    "tutor_item_supply_native_relation_batches", "tutor_item_supply_native_eligibility",
)


def _model(model: type[Any], raw: Any) -> Any:
    return model.model_validate_json(json.dumps(raw))


def _original_profile_binding(row: dict[str, Any], request: GenerationRequestV2,
                              spec: FiniteCandidateSpecV1, facts: IssuedSharedAdmissionFactsV1) -> str:
    if "committed_admission_history" in row:
        from app.services.learning.item_supply.native_committed_admission_history import verify_committed_admission_history
        return verify_committed_admission_history(row, request, spec, facts)
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
        return facts.profile_hash
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
    return facts.profile_hash


def reconstruct_native_content(row: dict[str, Any]) -> NativeResolvedContent:
    """Reconstruct immutable originals, never restore old issuance capabilities."""
    try:
        proof = _model(NativePublicationProofV1, row["proof_json"])
        spec = _model(FiniteCandidateSpecV1, row["preparation_json"]["spec"])
        source = _model(LearningItemSourceV1, row["source_json"])
        request = _model(GenerationRequestV2, row["preparation_json"]["request"])
        facts = _model(IssuedSharedAdmissionFactsV1, row["facts_json"])
        historical_quality_profile = _original_profile_binding(row, request, spec, facts)
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
                or facts.evidence.binding.profile_hash != historical_quality_profile
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


def require_content_mapping_identity(resolved: NativeResolvedContent,
                                     mapping: FiniteCourseMappingReceiptV1) -> AuthorizedSubDemandV1:
    """Pure immutable identity check; does not issue current candidate eligibility."""
    spec = resolved.spec
    entry = next((e for e in mapping.pack_request.demands if e.slot == spec.allocation.slot), None)
    if entry is None:
        raise NativeTypeEvidencePending("native_candidate_mapping_mismatch")
    scope = entry.demand.scope
    if (spec.target_id != mapping.target_id or spec.target_definition_hash != mapping.target_definition_hash
            or any(getattr(spec.coverage_blueprint.scope, k) != getattr(scope, k) for k in (
                "runtime_profile_id", "runtime_profile_hash", "scorer_version", "assistance_policy_hash",
                "subject_id", "subject_version", "required_facets", "required_capabilities", "assessment_contract_version"))):
        raise NativeTypeEvidencePending("native_candidate_mapping_mismatch")
    target = resolved.facts.target_proof
    if target is None or tuple((a, b) for a, b, _, _ in mapping.pack_request.clause_mapping) != tuple(
            (c.clause_id.upper(), c.clause_hash) for c in target.mappings):
        raise NativeTypeEvidencePending("native_clause_mapping_mismatch")
    return entry


class NativeTypeEvidenceOwner:
    # Preserve legacy dynamic attributes while making the new context explicit.
    __slots__ = ("current_source_binding", "__dict__", "__weakref__")

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
        self.current_source_binding: IssuedCurrentPackSourceBinding | None = None
        self._pack_scope: _CurrentPackData | None = None

    def _clear_pack_scope(self) -> None:
        scope = getattr(self, '_pack_scope', None)
        if scope is not None:
            if scope.capability is not None:
                self._issued.pop(scope.capability.eligibility_id, None)
            scope.contents.clear()
            scope.historical.clear()
            scope.published_at.clear()
            scope.source_deadlines.clear()
            scope.extras.clear()
            scope.projections.clear()
            scope.relation_rows.clear()
            scope.mapping = None
            scope.inputs = scope.observation = scope.capability = None
            self._pack_scope = None

    def _current_pack_data(self) -> _CurrentPackData | None:
        scope = getattr(self, '_pack_scope', None)
        if scope is not None and (scope.source_binding is not NativeTypeEvidenceOwner._source_binding(self)
                or scope.exposure_owner.type_owner is not self
                or scope.exposure_owner.conn is not self.conn
                or (scope.exposure_owner.user_id, scope.exposure_owner.epoch) != (self.user_id, self.epoch)):
            self._clear_pack_scope()
            raise NativeTypeEvidencePending('native_pack_scope_original_owner_required')
        return scope

    @staticmethod
    def _validate_pack_refs(candidates: tuple[UUID, ...], relations: tuple[UUID, ...]) -> None:
        if (not isinstance(candidates, tuple) or not isinstance(relations, tuple)
                or not 5 <= len(candidates) <= 16 or not 1 <= len(relations) <= 16
                or any(type(v) is not UUID for v in (*candidates, *relations))
                or len(set(candidates)) != len(candidates) or len(set(relations)) != len(relations)):
            raise NativeTypeEvidencePending('native_pack_inputs_bound_invalid')

    @contextmanager
    def current_pack(self, mapping_receipt_id: UUID, candidate_version_ids: tuple[UUID, ...],
                     relation_receipt_ids: tuple[UUID, ...], exposure_owner: NativeExposureOwnerV2
                     ) -> Iterator[IssuedNativePackCapability]:
        """Original verification and exact fresh issuance, valid only in this TOP.

        Local data never replaces current C/D, bank, epoch or SQL502 authority.
        The caller must keep this scope open through the original Artifact writer.
        """
        from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
        if (type(self) is not NativeTypeEvidenceOwner or type(exposure_owner) is not NativeExposureOwnerV2
                or exposure_owner.type_owner is not self or exposure_owner.conn is not self.conn
                or (exposure_owner.user_id, exposure_owner.epoch) != (self.user_id, self.epoch)
                or getattr(self, '_pack_scope', None) is not None
                or type(mapping_receipt_id) is not UUID
                or not isinstance(candidate_version_ids, tuple) or not isinstance(relation_receipt_ids, tuple)
                or not 5 <= len(candidate_version_ids) <= 16 or not 1 <= len(relation_receipt_ids) <= 16
                or any(type(v) is not UUID for v in (*candidate_version_ids, *relation_receipt_ids))
                or len(set(candidate_version_ids)) != len(candidate_version_ids)
                or len(set(relation_receipt_ids)) != len(relation_receipt_ids)):
            raise NativeTypeEvidencePending('native_pack_scope_original_owner_required')
        _, txid = self._guard()
        candidate_version_ids = tuple(sorted(candidate_version_ids, key=str))
        relation_receipt_ids = tuple(sorted(relation_receipt_ids, key=str))
        source = NativeTypeEvidenceOwner._source_binding(self)
        scope = _CurrentPackData(txid, mapping_receipt_id, candidate_version_ids,
            relation_receipt_ids, exposure_owner, source)
        try:
            # Source owner enters BEFORE all expensive core verification. It owns
            # its original exact signed data/origin and dynamic PUBLIC/PRIVATE fences.
            with source.current_scope() if source is not None else nullcontext():
                self._pack_scope = scope
                mapping = self.resolve_mapping(mapping_receipt_id)
                scope.mapping = mapping
                for version in candidate_version_ids:
                    resolved = self.resolve_content(version, current=True)
                    scope.contents[version] = resolved
                    # Precompute immutable type/static/runner facts, not authority.
                    now, _ = self._guard()
                    self._candidate(resolved, mapping, now)
                history = exposure_owner._prepare_history()
                scope.historical.update(history.contents)
                contents = {**scope.historical, **scope.contents}
                now, _ = self._guard()
                relation_args = self._relation_arguments(relation_receipt_ids, mapping, contents, now)
                # Re-fence every selected source -> bank and relation after front
                # lock waits, before the true collector clock starts its 30s TTL.
                self.resolve_mapping(mapping_receipt_id)
                for resolved in scope.contents.values():
                    self._require_scoped_content(resolved)
                self._require_scoped_relations(scope)
                observation = exposure_owner._snapshot_from_history(history)
                if observation.snapshot_id is None or observation.exposure is None:
                    raise NativeTypeEvidencePending('native_complete_exposure_required')
                scope.observation = observation
                now, _ = self._guard()
                records = tuple(self._candidate(c, mapping, now) for c in scope.contents.values())
                relations = tuple(ContentRelationshipEvidenceV2(**args,
                    exposure_receipt_hash=observation.exposure.completeness_receipt_hash,
                    exposure_watermark=observation.exposure.watermark) for args in relation_args)
                scope.inputs = PackInputsV2(request=mapping.pack_request, candidates=records,
                    relationships=relations, exposure=observation.exposure)
                # One uninterrupted original issuer invocation: front retained
                # source -> bank locks and verified exact immutable DATA; the
                # real fresh collector and pure projections just completed.
                # Do not run _inputs' whole dynamic loop and then immediately
                # repeat it in first require_pack. That ORIGINAL final fence
                # below still runs after issuance, before any cap can escape.
                capability = self._issue_pack_from_inputs(scope.inputs, mapping_receipt_id,
                    candidate_version_ids, observation.snapshot_id, relation_receipt_ids)
                scope.capability = capability
                self.require_pack(capability)
                yield capability
                # Delivery's original capture may now add an inbox event. No
                # further cap reuse is allowed, but successful creation must not
                # be undone by inventing an additional post-delivery exposure use.
                # Still forbid a scope crossing commit/rollback into another TOP.
                self._guard()
        finally:
            self._clear_pack_scope()

    def _scoped_observation(self, owner: NativeExposureOwnerV2) -> NativeTypeExposureSnapshot | None:
        scope = NativeTypeEvidenceOwner._current_pack_data(self)
        if scope is None or scope.observation is None:
            return None
        self._guard()
        if (scope.exposure_owner is not owner or scope.capability is None
                or scope.observation.snapshot_id is None or scope.observation.exposure is None):
            raise NativeTypeEvidencePending('native_pack_scope_original_owner_required')
        try:
            # Snapshot is original exposure DATA, not a whole-pack permission.
            # Keep its own exact current mapping/source, epoch, persisted issuer,
            # SQL502 and lock-post clock fences; effects separately require pack.
            self._require_pack_identity(scope.capability)
            self.resolve_mapping(scope.mapping_id)
            self._exposure(scope.observation.snapshot_id, self._guard()[0])
            final, _ = self._guard()
            if not scope.observation.exposure.observed_at <= final < scope.observation.exposure.valid_until:
                raise NativeTypeEvidencePending('native_exposure_current_required')
        except Exception:
            self._clear_pack_scope()
            raise
        return scope.observation

    def _require_scoped_content(self, resolved: NativeResolvedContent) -> None:
        try:
            self._require_scoped_content_current(resolved)
        except Exception:
            self._clear_pack_scope()
            raise

    def _require_scoped_content_current(self, resolved: NativeResolvedContent) -> None:
        """Retained original immutable data + ORIGINAL current source/bank ports."""
        scope = NativeTypeEvidenceOwner._current_pack_data(self)
        if scope is None or scope.contents.get(resolved.content.version_id) is not resolved:
            raise NativeTypeEvidencePending('native_pack_scope_exact_content_required')
        p = resolved.publication
        def source_fence() -> None:
            if scope.source_binding is not None:
                # Checks SQL549 AND original repository PUBLIC/PRIVATE predicates.
                scope.source_binding.current_receipts(query=self.query, proof=p,
                    published_at=scope.published_at[p.version_id],
                    source_authority=self.source_authority)
            else:
                for material, receipt in zip(p.materials, p.source_receipts, strict=True):
                    self.source_authority.assert_current(material, receipt)
        source_fence()
        self._lock_scoped_bank(resolved)
        source_fence()  # Same original source -> bank / lock-post ordering.
        self._require_scoped_runtime(resolved)

    def _lock_scoped_bank(self, resolved: NativeResolvedContent) -> None:
        """Original version lock and separate post-lock latest event statement."""
        p = resolved.publication
        locked = self.conn.execute('SELECT id FROM tutor_learning_item_versions WHERE id=%s AND handle=%s FOR SHARE',
            (p.version_id, p.item_handle)).fetchone()
        event = self.conn.execute('SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=%s '
            'ORDER BY state_version DESC LIMIT 1', (p.version_id,)).fetchone()
        if (locked is None or event is None or event['state'] != 'published'
                or UUID(str(event['id'])) != p.publication_event_id):
            raise NativeTypeEvidencePending('native_content_current_required')

    def _require_scoped_runtime(self, resolved: NativeResolvedContent) -> None:
        """Original runtime/scorer binding and actual health port, never cached."""
        p = resolved.publication
        now, _ = self._guard()
        from app.services.learning.item_bank.native_publication import _runtime
        runtime = _runtime(resolved.spec, self.query._bindings)
        if runtime != p.runtime:
            raise NativeTypeEvidencePending('native_content_runtime_current_required')
        health = self.query._current_runtime(runtime, now=now)
        if resolved.consumption is None or health != resolved.consumption.runtime_health_registry_hash:
            raise NativeTypeEvidencePending('native_content_runtime_current_required')

    def _require_scoped_relations(self, scope: _CurrentPackData) -> None:
        now, _ = self._guard()
        for receipt, original in scope.relation_rows.items():
            row = self.conn.execute('SELECT * FROM tutor_item_supply_native_relation_batches '
                'WHERE id=%s AND user_id=%s AND epoch=%s AND mapping_receipt_id=%s FOR SHARE',
                (receipt, self.user_id, self.epoch, scope.mapping_id)).fetchone()
            if row != original or not original['checked_at'] <= now < original['valid_until']:
                raise NativeTypeEvidencePending('native_relation_current_bound_required')
            if any(not datetime.fromisoformat(r['checked_at']) <= now < datetime.fromisoformat(r['valid_until'])
                    for r in original['payload_json']['reports']):
                raise NativeTypeEvidencePending('native_relation_current_bound_required')

    def _source_binding(self, cap: IssuedCurrentPackSourceBinding | None = None) -> IssuedCurrentPackSourceBinding | None:
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
        cap = getattr(self, "current_source_binding", None) if cap is None else cap
        if cap is None:
            return None
        if (type(self) is not NativeTypeEvidenceOwner or type(cap) is not IssuedCurrentPackSourceBinding
                or type(cap.owner) is not PersistentPackTaskOwner or cap.owner.type_owner is not self
                or cap.owner.conn is not self.conn or cap.owner.user_id != self.user_id or cap.owner.epoch != self.epoch):
            raise NativeTypeEvidencePending("native_current_source_original_owner_required")
        return cap

    def attach_current_source_binding(self, cap: IssuedCurrentPackSourceBinding) -> None:
        from app.services.learning.item_supply.persistent_pack_current_source import IssuedCurrentPackSourceBinding
        if type(cap) is not IssuedCurrentPackSourceBinding:
            raise NativeTypeEvidencePending("native_current_source_original_owner_required")
        original = NativeTypeEvidenceOwner._source_binding(self, cap)
        assert original is not None
        original.require()
        self.current_source_binding = original

    def _guard(self) -> tuple[datetime, int]:
        if (not self.enabled or not self.settings.learning_item_supply_enabled
                or not self.settings.learning_item_v2_admission_enabled):
            raise NativeTypeEvidencePending("native_type_disabled")
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            self._clear_pack_scope()
            raise NativeTypeEvidencePending("native_type_transaction_required")
        self.query.artifacts.require_owner()
        lock_private_namespace(self.conn, self.user_id, self.epoch)
        row = self.conn.execute("SELECT clock_timestamp() AS now,txid_current() AS txid").fetchone()
        if row is None:
            raise NativeTypeEvidencePending("native_type_clock_missing")
        scope = getattr(self, '_pack_scope', None)
        if scope is not None and int(row['txid']) != scope.txid:
            self._clear_pack_scope()
            raise NativeTypeEvidencePending('native_pack_scope_transaction_changed')
        return row["now"], int(row["txid"])

    def resolve_mapping(self, receipt_id: UUID) -> FiniteCourseMappingReceiptV1:
        self._guard()
        cap = NativeTypeEvidenceOwner._source_binding(self)
        if cap is not None:
            mapping = cap.resolve_mapping(receipt_id)
            scope = NativeTypeEvidenceOwner._current_pack_data(self)
            if scope is not None and (receipt_id != scope.mapping_id
                    or scope.mapping is not None and mapping != scope.mapping):
                raise NativeTypeEvidencePending('native_pack_scope_exact_mapping_required')
            return mapping
        result = self.mapping_owner.resolve(receipt_id=receipt_id, user_id=self.user_id, epoch=self.epoch)
        if result.receipt is None:
            from app.core.source_fence_diagnostics import observe_source_fence
            observe_source_fence("mapping_resolve", result.reason)
            raise NativeTypeEvidencePending("native_mapping_current_required")
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None and (receipt_id != scoped.mapping_id
                or scoped.mapping is not None and scoped.mapping != result.receipt):
            raise NativeTypeEvidencePending('native_pack_scope_exact_mapping_required')
        return result.receipt

    def resolve_content(self, version_id: UUID, current: bool = True) -> NativeResolvedContent:
        self._guard()
        if type(current) is not bool:
            raise NativeTypeEvidencePending("native_content_current_mode_invalid")
        scope = NativeTypeEvidenceOwner._current_pack_data(self)
        if scope is not None:
            cached = scope.contents.get(version_id) if current else (
                scope.historical.get(version_id) or scope.contents.get(version_id))
            if cached is not None:
                if current:
                    self.resolve_mapping(scope.mapping_id)
                    self._require_scoped_content(cached)
                return cached
            if scope.observation is not None:
                raise NativeTypeEvidencePending('native_pack_scope_exact_content_required')
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
        if not rows:
            from app.services.learning.item_supply.native_committed_admission_history import read_committed_admission_row
            historical = read_committed_admission_row(self.conn, version_id)
            if historical is not None:
                rows = [historical]
        if len(rows) != 1:
            raise NativeTypeEvidencePending("native_exact_original_publication_required")
        resolved = reconstruct_native_content(rows[0])
        if self.query.artifacts.published_generation_policy(rows[0]).policy_hash != resolved.publication.policy_hash:
            raise NativeTypeEvidencePending("native_content_generation_policy_mismatch")
        if resolved.publication.version_id != version_id:
            raise NativeTypeEvidencePending("native_content_version_mismatch")
        if current:
            try:
                cap = NativeTypeEvidenceOwner._source_binding(self)
                if cap is None:
                    found = self.query.query_exact(handle=resolved.content.item_handle, spec=resolved.spec,
                        source_authority=self.source_authority)
                else:
                    found = self.query.query_exact(handle=resolved.content.item_handle, spec=resolved.spec,
                        source_authority=self.source_authority, current_source_binding=cap)
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
        cap = NativeTypeEvidenceOwner._source_binding(self)
        if cap is not None:
            cap.require()
            proof = resolved.publication
            publication = self.conn.execute(
                "SELECT e.occurred_at FROM tutor_learning_item_native_publication_proofs n "
                "JOIN tutor_learning_item_publication_events e ON e.id=n.publication_event_id AND e.version_id=n.version_id "
                "WHERE n.id=%s AND n.version_id=%s AND n.proof_hash=%s AND e.state='published' FOR SHARE OF n,e",
                (proof.proof_id, proof.version_id, proof.proof_hash)).fetchone()
            if publication is None:
                raise NativeTypeEvidencePending("native_current_source_exact_publication_required")
            scoped = NativeTypeEvidenceOwner._current_pack_data(self)
            if scoped is not None:
                scoped.published_at[proof.version_id] = publication['occurred_at']
            cap.current_receipts(query=self.query, proof=proof, published_at=publication["occurred_at"],
                source_authority=self.source_authority)
            if scoped is not None:
                scoped.source_deadlines[proof.version_id] = cap.source_deadline
            return cap.source_deadline
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
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None:
            scoped.source_deadlines[resolved.content.version_id] = deadline
        return deadline

    def _deadline(self, resolved: NativeResolvedContent, now: datetime) -> datetime:
        # Fresh bounded observation, never renewal of an old producer fact lease.
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None and scoped.observation is not None and scoped.inputs is None:
            # Initial projection is DATA computation, not another source use.
            # The closed front supplied these exact bounds; _inputs and first
            # require_pack still re-fence CURRENT authority before any cap escapes.
            source_deadline = scoped.source_deadlines[resolved.content.version_id]
        else:
            source_deadline = self.source_deadline(resolved)
        deadline = min(now + CURRENT_PACK_TTL, source_deadline)
        if scoped is not None and scoped.observation is not None and scoped.observation.exposure is not None:
            deadline = min(deadline, scoped.observation.exposure.valid_until,
                *(r['valid_until'] for r in scoped.relation_rows.values()),
                *(datetime.fromisoformat(report['valid_until']) for row in scoped.relation_rows.values()
                  for report in row['payload_json']['reports']))
        if deadline <= now:
            raise NativeTypeEvidencePending("native_source_current_deadline_missing")
        return deadline

    def _candidate(self, resolved: NativeResolvedContent, mapping: FiniteCourseMappingReceiptV1,
                   now: datetime) -> PackCandidateV2:
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None:
            if scoped.contents.get(resolved.content.version_id) is not resolved or mapping != scoped.mapping:
                raise NativeTypeEvidencePending('native_pack_scope_exact_content_required')
            if scoped.inputs is not None:
                if (scoped.capability is None or scoped.observation is None
                        or scoped.observation.snapshot_id is None):
                    raise NativeTypeEvidencePending('native_pack_scope_issuance_required')
                try:
                    self._require_pack_identity(scoped.capability)
                    self.resolve_mapping(scoped.mapping_id)
                    self._require_scoped_content(resolved)
                    self._require_scoped_relations(scoped)
                    self._exposure(scoped.observation.snapshot_id, self._guard()[0])
                    record = next(c for c in scoped.inputs.candidates if c.version_id == resolved.content.version_id)
                    final, _ = self._guard()
                    if not record.observed_at <= final < record.valid_until:
                        raise NativeTypeEvidencePending('native_pack_deadline_elapsed')
                    return record
                except Exception:
                    self._clear_pack_scope()
                    raise
            if scoped.observation is not None:
                # This front template was never issued/persisted as authority.
                # Keep its exact already-verified immutable DATA, not expensive
                # publication/source/facts reconstruction after snapshot issuance.
                template, authorization_data, type_data = scoped.projections[resolved.content.version_id]
                original_candidate = template.candidate
                if not isinstance(original_candidate, NativeScopedCandidateV2):
                    raise NativeTypeEvidencePending('native_pack_scope_exact_content_required')
                deadline = self._deadline(resolved, now)
                authorization_hash = canonical_hash({**authorization_data, 'checked_at': now.isoformat()})
                authorization = original_candidate.current_authorization.model_copy(update={
                    'authorization_hash': authorization_hash, 'checked_at': now, 'valid_until': deadline})
                proof = original_candidate.proof.model_copy(update={
                    'authorization_hash': authorization_hash, 'authorization_checked_at': now,
                    'authorization_valid_until': deadline, 'checked_at': now, 'valid_until': deadline})
                candidate = original_candidate.model_copy(update={
                    'proof': proof, 'current_authorization': authorization})
                evidence = template.type_evidence.model_copy(update={'receipt_id': uuid4(),
                    'checked_at': now, 'valid_until': deadline,
                    'receipt_hash': canonical_hash({**type_data, 'checked_at': now.isoformat()})})
                # Original PackInputs/build_pack validation and SQL501 issuance
                # still validate the resulting typed projection before it escapes.
                return template.model_copy(update={'candidate': candidate, 'type_evidence': evidence,
                    'observed_at': now, 'valid_until': deadline})
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
        entry = require_content_mapping_identity(resolved, mapping)
        cap = NativeTypeEvidenceOwner._source_binding(self)
        mapping_source_hash = mapping.source_authorization_hash
        if cap is not None:
            initial_projection = scoped is not None and scoped.observation is not None and scoped.inputs is None
            if not initial_projection and cap.resolve_mapping(mapping.receipt_id) != mapping:
                raise NativeTypeEvidencePending("native_current_source_mapping_mismatch")
            mapping_source_hash = cap.source_authorization_hash
        scope = entry.demand.scope
        target = facts.target_proof
        assert target is not None  # Checked by the shared immutable identity check above.
        clauses = tuple(ClauseCoverageV1(clause_id=c, clause_hash=h) for _, _, c, h in mapping.pack_request.clause_mapping)
        deadline = self._deadline(resolved, now)
        source_set_hash = canonical_hash(list(resolved.consumption.current_source_receipt_hashes))
        authorization_data = {"mapping": mapping_source_hash,
            "publication": p.proof_hash, "source_set": source_set_hash,
            "current_consumption": canonical_hash(resolved.consumption.model_dump(mode="json"))}
        authorization_hash = canonical_hash({**authorization_data, "checked_at": now.isoformat()})
        common = dict(scope_hash=scope.scope_hash, objective_hash=entry.demand.objective_hash,
            target_definition_hash=mapping.target_definition_hash, course_mapping_hash=mapping.mapping_hash,
            runtime_profile_id=scope.runtime_profile_id, runtime_profile_hash=scope.runtime_profile_hash,
            scorer_version=scope.scorer_version, assistance_policy_hash=scope.assistance_policy_hash,
            validation_receipt_hash=facts.validation_receipt_hash, item_review_bundle_hash=facts.review_receipt_hash,
            receipt_id=uuid4(), checked_at=now, valid_until=deadline, content=resolved.content)
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None and p.version_id in scoped.extras:
            evidence_type, extra = scoped.extras[p.version_id]
        else:
            if spec.target_id == "python-kc-binding-v1":
                static = prepare_finite_candidate_validation(source, spec=spec, materials=p.materials).static_facts
                if static is None:
                    raise NativeTypeEvidencePending("native_static_facts_missing")
                extra = dict(truth_derivation_hash=static.instance_hash,
                    all_options_verification_hash=canonical_hash([o.model_dump(mode="json") for o in static.options]),
                    blind_solve_receipt_hash=facts.blind_receipt_hash, ambiguity_review_receipt_hash=facts.ambiguity.receipt_hash,
                    misconception_review_receipt_hash=next(c.ambiguity_report_hash for c in target.mappings))
                evidence_type = KCTypeEvidenceV2
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
            if scoped is not None:
                scoped.extras[p.version_id] = evidence_type, extra
        type_data = {"facts": facts.receipt_hash, "scope": scope.scope_hash,
                "objective": entry.demand.objective_hash, "mapping": mapping.mapping_hash,
                "extra": extra}
        type_evidence: TypeAssessmentEvidenceV2 = evidence_type(**common, **extra,
            receipt_hash=canonical_hash({**type_data, "checked_at": now.isoformat()}))
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
        record = PackCandidateV2(candidate=candidate, member=member, type_evidence=type_evidence,
            publication_id=p.publication_event_id, materialization_id=p.materialization_id, proof_id=p.proof_id,
            version_id=p.version_id, owner_id=None, epoch=None, storage_scope_id=entry.storage_scope_id,
            original_publication_hash=p.proof_hash, original_materialization_hash=p.materialization_hash,
            original_proof_hash=target.proof_hash, complete_source_set_hash=source_set_hash,
            runtime_or_static_observation_hash=canonical_hash(resolved.consumption.model_dump(mode="json")),
            observed_at=now, valid_until=deadline)
        if scoped is not None:
            scoped.projections[p.version_id] = record, authorization_data, type_data
        return record

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
        return tuple(ContentRelationshipEvidenceV2(**args,
            exposure_receipt_hash=exposure.completeness_receipt_hash,
            exposure_watermark=exposure.watermark) for args in self._relation_arguments(ids, mapping, contents, now))

    def _relation_arguments(self, ids: tuple[UUID, ...], mapping: FiniteCourseMappingReceiptV1,
                            contents: dict[UUID, NativeResolvedContent], now: datetime
                            ) -> tuple[dict[str, Any], ...]:
        from uuid import uuid5
        relations: dict[str, dict[str, Any]] = {}
        for receipt_id in ids:
            row = self.conn.execute("SELECT * FROM tutor_item_supply_native_relation_batches "
                "WHERE id=%s AND user_id=%s AND epoch=%s AND mapping_receipt_id=%s FOR SHARE",
                (receipt_id, self.user_id, self.epoch, mapping.receipt_id)).fetchone()
            if (row is None or row["request_hash"] != mapping.pack_request.request_hash
                    or row["payload_hash"] != canonical_hash(row["payload_json"])
                    or not row["checked_at"] <= now < row["valid_until"]):
                raise NativeTypeEvidencePending("native_relation_current_bound_required")
            scoped = NativeTypeEvidenceOwner._current_pack_data(self)
            if scoped is not None:
                scoped.relation_rows[receipt_id] = row
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
                relation = dict(profile=profile, request_hash=mapping.pack_request.request_hash,
                    left=left.content, right=right.content, reviews=tuple(reviews),
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
        NativeTypeEvidenceOwner._validate_pack_refs(candidates, relation_ids)
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None and scoped.inputs is not None:
            if (mapping_id != scoped.mapping_id or set(candidates) != set(scoped.versions)
                    or set(relation_ids) != set(scoped.relation_ids) or scoped.observation is None
                    or exposure_id != scoped.observation.snapshot_id):
                raise NativeTypeEvidencePending('native_pack_scope_exact_inputs_required')
            self.resolve_mapping(mapping_id)
            for content in scoped.contents.values():
                self._require_scoped_content(content)
            self._require_scoped_relations(scoped)
            self._exposure(exposure_id, self._guard()[0])
            return scoped.inputs
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
        NativeTypeEvidenceOwner._validate_pack_refs(candidate_version_ids, relation_receipt_ids)
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None and scoped.capability is not None:
            if (mapping_receipt_id != scoped.mapping_id or set(candidate_version_ids) != set(scoped.versions)
                    or set(relation_receipt_ids) != set(scoped.relation_ids) or scoped.observation is None
                    or exposure_snapshot_id != scoped.observation.snapshot_id):
                raise NativeTypeEvidencePending('native_pack_scope_exact_inputs_required')
            self.require_pack(scoped.capability)
            return scoped.capability
        inputs = self._inputs(mapping_receipt_id, candidate_version_ids, exposure_snapshot_id, relation_receipt_ids)
        return self._issue_pack_from_inputs(inputs, mapping_receipt_id, candidate_version_ids,
            exposure_snapshot_id, relation_receipt_ids)

    def _issue_pack_from_inputs(self, inputs: PackInputsV2, mapping_receipt_id: UUID,
                               candidate_version_ids: tuple[UUID, ...], exposure_snapshot_id: UUID,
                               relation_receipt_ids: tuple[UUID, ...]) -> IssuedNativePackCapability:
        """The original issuer body; no new authority or scope permission flag.

        Strict resolve_pack still obtains its inputs from the original _inputs.
        Initial current_pack instead supplies EXACT local DATA, then runs the
        original dynamic require_pack before yielding to any consumer.
        """
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None and (inputs is not scoped.inputs or scoped.capability is not None
                or mapping_receipt_id != scoped.mapping_id or scoped.mapping is None
                or inputs.request != scoped.mapping.pack_request
                or candidate_version_ids != scoped.versions or relation_receipt_ids != scoped.relation_ids
                or scoped.observation is None or exposure_snapshot_id != scoped.observation.snapshot_id
                or inputs.exposure != scoped.observation.exposure):
            raise NativeTypeEvidencePending('native_pack_scope_exact_inputs_required')
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
        try:
            return NativeTypeEvidenceOwner._require_pack(self, capability)
        except Exception:
            # A failed dynamic fence or aborted/rolled-back transaction discards
            # this call's data. Catching the failure cannot revive the scope.
            NativeTypeEvidenceOwner._clear_pack_scope(self)
            raise

    def _require_pack_identity(self, capability: IssuedNativePackCapability) -> datetime:
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
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is not None and scoped.capability is not capability:
            raise NativeTypeEvidencePending('native_pack_scope_exact_capability_required')
        return now

    def _require_pack(self, capability: IssuedNativePackCapability) -> PackSnapshotV2:
        now = NativeTypeEvidenceOwner._require_pack_identity(self, capability)
        entry = self._issued[capability.eligibility_id]
        self.resolve_mapping(entry[3])
        self._exposure(entry[5], self._guard()[0])
        scoped = NativeTypeEvidenceOwner._current_pack_data(self)
        if scoped is None:
            for version in entry[4]:
                self.resolve_content(version, current=True)
        elif scoped.source_binding is None:
            for version in entry[4]:
                self._require_scoped_content(scoped.contents[version])
        else:
            contents = tuple(scoped.contents[version] for version in entry[4])
            proof_bindings = tuple((content.publication, scoped.published_at[content.content.version_id])
                for content in contents)
            # The ORIGINAL source owner validates the exact original cap/proof
            # set and identical PUBLIC/PRIVATE source once before these bank
            # locks and fully again after ALL locks/health reads. No user yield,
            # callback, provider IO or body write occurs inside this invocation.
            # Next independent verifier enters a NEW initial/final source use.
            with scoped.source_binding.current_pack_invocation(query=self.query,
                    source_authority=self.source_authority, proof_bindings=proof_bindings):
                for content in contents:
                    self._lock_scoped_bank(content)
                    self._require_scoped_runtime(content)
                # Relation SHARE waits belong BEFORE the original source owner's
                # complete post-source/config/SQL549/clock fence on context exit.
                self._require_scoped_relations(scoped)
        if scoped is not None:
            if scoped.capability is not capability:
                raise NativeTypeEvidencePending('native_pack_scope_exact_capability_required')
            if scoped.source_binding is None:
                self._require_scoped_relations(scoped)
        # Still-valid original content relation rows, including conflict/uncertain
        # vetoes, cannot be swapped by mutating the capability object.
        final = server_clock(self.conn, now)
        # Source/bank/relation lock waits may expose a new actual inbox or consume
        # the window. SQL502 and the final DB clock are BOTH rechecked afterwards.
        self._exposure(entry[5], final)
        final = server_clock(self.conn, final)
        if final >= capability.snapshot.valid_until:
            raise NativeTypeEvidencePending("native_pack_deadline_elapsed")
        return capability.snapshot
