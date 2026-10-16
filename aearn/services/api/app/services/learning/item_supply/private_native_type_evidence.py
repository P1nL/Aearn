"""PRIVATE whole-pack issuer: actual private publication/type/mapping/complete exposure."""
from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
import json
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.private_native_publication import PrivateNativePublicationQuery
from app.services.learning.item_supply.contracts import ClauseCoverageV1, SourceAuthorizationFactsV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_course_mapping import FiniteCourseMappingOwner
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.native_type_contracts import NativeRelationReport, NativeResolvedContent
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.pack_contracts import CompleteExposureV2, FamilyMemberEvidenceV2, NativeCandidateV1, NativeProofV1, PackCandidateV2, PackInputsV2, PackSnapshotV2
from app.services.learning.item_supply.private_enhancement_contracts import IssuedPrivatePackCapability, PrivateNativePending, PrivateResolvedContent
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.type_evidence import ContentRelationshipEvidenceV2, KCTypeEvidenceV2, RelationshipReviewV2, TypeProfileV2, relationship_binding_hash


class PrivateNativeTypeEvidenceOwner:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, query: PrivateNativePublicationQuery,
                 mapping_owner: FiniteCourseMappingOwner, enabled: bool = False,
                 public_owner: NativeTypeEvidenceOwner | None = None) -> None:
        if (type(query) is not PrivateNativePublicationQuery or query.conn is not conn or query.settings is not settings
                or type(mapping_owner) is not FiniteCourseMappingOwner or mapping_owner.conn is not conn):
            raise PrivateNativePending('private_type_concrete_current_owners_required')
        self.conn, self.settings, self.query, self.mapping_owner, self.enabled = conn, settings, query, mapping_owner, enabled
        self.user_id, self.epoch = query.user_id, query.epoch
        if public_owner is not None and (type(public_owner) is not NativeTypeEvidenceOwner
                or public_owner.conn is not conn or public_owner.settings is not settings
                or public_owner.mapping_owner is not mapping_owner
                or (public_owner.user_id,public_owner.epoch)!=(self.user_id,self.epoch)):
            raise PrivateNativePending('private_type_original_public_exposure_owner_required')
        self.public_owner=public_owner
        self._issued: dict[UUID, tuple[IssuedPrivatePackCapability, str, int]] = {}

    def _guard(self) -> tuple[datetime, int]:
        if not self.enabled:
            raise PrivateNativePending('private_type_disabled')
        now = self.query._guard()
        row = self.conn.execute('SELECT txid_current() AS txid').fetchone()
        if row is None:
            raise PrivateNativePending('private_type_transaction_required')
        return now, int(row['txid'])

    def resolve_mapping(self, receipt_id: UUID) -> FiniteCourseMappingReceiptV1:
        self._guard()
        public = self.public_owner
        if public is not None:
            if (type(public) is not NativeTypeEvidenceOwner or public.conn is not self.conn
                    or public.settings is not self.settings or public.mapping_owner is not self.mapping_owner
                    or (public.user_id, public.epoch) != (self.user_id, self.epoch)):
                raise PrivateNativePending('private_type_original_public_exposure_owner_required')
            cap = NativeTypeEvidenceOwner._source_binding(public)
            if cap is not None:
                # Original PUBLIC source owner, not PUBLIC content/quality authority.
                # Issuer failures must never fall back to raw legacy mapping.
                mapping = public.resolve_mapping(receipt_id)
                now, _ = self._guard()
                if now >= cap.source_deadline:
                    raise PrivateNativePending('private_type_current_mapping_required')
                return mapping
        result = self.mapping_owner.resolve(receipt_id=receipt_id, user_id=self.user_id, epoch=self.epoch)
        if result.receipt is None:
            raise PrivateNativePending('private_type_current_mapping_required')
        self._guard()
        return result.receipt

    def _candidate(self, resolved: PrivateResolvedContent, mapping: FiniteCourseMappingReceiptV1) -> PackCandidateV2:
        now, _ = self._guard()
        p, q, content = resolved.publication, resolved.quality, resolved.content
        spec, source = q.spec, q.source
        if (resolved.observed_at is None or resolved.valid_until is None or not resolved.observed_at <= now < resolved.valid_until
                or resolved.source_set_hash is None or (q.ref.user_id, q.ref.epoch) != (self.user_id, self.epoch)
                or q.ref.mapping_receipt_id != mapping.receipt_id or spec.target_id != mapping.target_id
                or spec.target_definition_hash != mapping.target_definition_hash):
            raise PrivateNativePending('private_type_actual_current_content_required')
        entry = next(e for e in mapping.pack_request.demands if e.slot == spec.allocation.slot)
        scope = entry.demand.scope
        if q.ref.goal_scope_id != entry.storage_scope_id or any(getattr(spec.coverage_blueprint.scope, k) != getattr(scope, k) for k in (
                'runtime_profile_id', 'runtime_profile_hash', 'scorer_version', 'assistance_policy_hash', 'subject_id',
                'subject_version', 'required_facets', 'required_capabilities', 'assessment_contract_version')):
            raise PrivateNativePending('private_type_exact_goal_contract_required')
        clauses = tuple(ClauseCoverageV1(clause_id=c, clause_hash=h) for _, _, c, h in mapping.pack_request.clause_mapping)
        static = prepare_finite_candidate_validation(source, spec=spec, materials=q.request.materials).static_facts
        if static is None:
            raise PrivateNativePending('private_type_execution_receipt_owner_required')
        deadline = resolved.valid_until
        authorization_hash = canonical_hash({'mapping': mapping.mapping_hash, 'sources': resolved.source_set_hash,
            'publication': p.publication_hash, 'goal': entry.demand.objective_hash, 'observed': now.isoformat()})
        source_ref = 'private-native-sources.' + canonical_hash([m.binding.evidence[0].binding.model_dump(mode='json') for m in q.request.materials])
        source_version = 'source-set-v1.' + canonical_hash([m.model_dump(mode='json') for m in q.request.materials])
        auth = SourceAuthorizationFactsV1(authorization_hash=authorization_hash, source_ref=source_ref,
            source_version=source_version, source_usage='assessment_evidence', scope_hash=scope.scope_hash,
            objective_hash=entry.demand.objective_hash, content_hash=source.content_hash, evidence_hash=q.clause_proof_hash,
            checked_at=now, valid_until=deadline, active=True)
        proof = NativeProofV1(proof_id=str(q.receipt_id), blueprint_hash=entry.blueprint.blueprint_hash,
            scope_hash=scope.scope_hash, objective_hash=entry.demand.objective_hash, item_handle=p.item_handle,
            content_hash=source.content_hash, clauses=clauses, slot=entry.slot, candidate_family_id=spec.allocation.family_id,
            matrix_hash=entry.blueprint.matrix_hash, policy_version=entry.blueprint.policy_version,
            runtime_profile_id=scope.runtime_profile_id, runtime_profile_hash=scope.runtime_profile_hash,
            assessment_contract_version=scope.assessment_contract_version, scorer_version=scope.scorer_version,
            assistance_policy_hash=scope.assistance_policy_hash, source_ref=source_ref, source_version=source_version,
            source_usage='assessment_evidence', evidence_hash=q.clause_proof_hash, authorization_hash=authorization_hash,
            authorization_checked_at=now, authorization_valid_until=deadline, issuer_version='private_native_type_v1',
            checked_at=now, valid_until=deadline)
        candidate = NativeCandidateV1(scope=scope, item_handle=p.item_handle, content_hash=source.content_hash,
            candidate_family_id=spec.allocation.family_id, objective_hash=entry.demand.objective_hash,
            blueprint_hash=entry.blueprint.blueprint_hash, matrix_hash=entry.blueprint.matrix_hash,
            policy_version=entry.blueprint.policy_version, slot=entry.slot, clauses=clauses, source_ref=source_ref,
            source_version=source_version, source_usage='assessment_evidence', evidence_hash=q.clause_proof_hash,
            visibility='private', owner_ref=scope.owner_ref, proof=proof, current_authorization=auth,
            published=True, materialized=True, runtime_available=True, available_capabilities=scope.required_capabilities)
        type_evidence = KCTypeEvidenceV2(scope_hash=scope.scope_hash, objective_hash=entry.demand.objective_hash,
            target_definition_hash=mapping.target_definition_hash, course_mapping_hash=mapping.mapping_hash,
            runtime_profile_id=scope.runtime_profile_id, runtime_profile_hash=scope.runtime_profile_hash,
            scorer_version=scope.scorer_version, assistance_policy_hash=scope.assistance_policy_hash,
            validation_receipt_hash=q.validation.evidence_hash, item_review_bundle_hash=q.bundle.bundle_hash,
            receipt_id=uuid5(q.receipt_id, 'private-type.' + scope.scope_hash), checked_at=now, valid_until=deadline, content=content,
            truth_derivation_hash=static.instance_hash,
            all_options_verification_hash=canonical_hash([o.model_dump(mode='json') for o in static.options]),
            blind_solve_receipt_hash=q.bundle.blind_solve.receipt_hash, ambiguity_review_receipt_hash=q.ambiguity.receipt_hash,
            misconception_review_receipt_hash=next(r.report_hash for r in q.bundle.reports if r.role.value == 'ambiguity'),
            receipt_hash=canonical_hash({'quality': q.receipt_hash, 'mapping': mapping.mapping_hash, 'current': authorization_hash}))
        family = next(f for f in families_for_course(spec.target_id) if f.family_id == spec.allocation.family_id)
        member_data = dict(family_id=family.family_id, family_definition_hash=family.definition_hash,
            allocation_variant_id=spec.allocation.variant_id, allocation_definition_hash=spec.allocation.definition_hash,
            allocation_receipt_hash=canonical_hash(spec.allocation.model_dump(mode='json')),
            target_definition_hash=spec.target_definition_hash, actual_public_task_hash=source.public.public_hash,
            actual_fixture_hash=content.actual_fixture_hash, semantic_signature=family.definition_hash,
            course_mapping_hash=mapping.mapping_hash, candidate_content_hash=source.content_hash, slot=entry.slot,
            purpose=source.public.purpose.value)
        member = FamilyMemberEvidenceV2.model_validate({**member_data, 'receipt_hash': canonical_hash(member_data)})
        return PackCandidateV2(candidate=candidate, member=member, type_evidence=type_evidence,
            publication_id=p.publication_id, materialization_id=p.materialization_id, proof_id=q.receipt_id,
            version_id=p.version_id, owner_id=self.user_id, epoch=self.epoch, storage_scope_id=entry.storage_scope_id,
            original_publication_hash=p.publication_hash, original_materialization_hash=p.materialization_hash,
            original_proof_hash=q.clause_proof_hash, complete_source_set_hash=resolved.source_set_hash,
            runtime_or_static_observation_hash=authorization_hash, observed_at=now, valid_until=deadline)

    def _relations(self, ids: tuple[UUID, ...], mapping: FiniteCourseMappingReceiptV1,
                   contents: Mapping[UUID, PrivateResolvedContent | NativeResolvedContent], exposure: CompleteExposureV2) -> tuple[ContentRelationshipEvidenceV2, ...]:
        now, _ = self._guard()
        relations: dict[str, ContentRelationshipEvidenceV2] = {}
        for rid in ids:
            row = self.conn.execute("SELECT * FROM tutor_item_supply_private_native_quality_evidence WHERE id=%s AND user_id=%s AND epoch=%s AND kind='relation' FOR SHARE",
                (rid, self.user_id, self.epoch)).fetchone()
            if row is None or row['payload_hash'] != canonical_hash(row['payload_json']) or not row['checked_at'] <= now < row['valid_until']:
                raise PrivateNativePending('private_type_current_relations_required')
            payload = row['payload_json']
            if payload['mapping_hash'] != mapping.mapping_hash or payload['request_hash'] != mapping.pack_request.request_hash:
                raise PrivateNativePending('private_type_relation_goal_required')
            reports = tuple(NativeRelationReport.model_validate_json(json.dumps(r)) for r in payload['reports'])
            if ({r.role for r in reports} != {'curriculum', 'technical', 'ambiguity', 'adversarial'} or len(reports) != 4
                    or len({r.actor_id for r in reports}) != 4 or len({r.run.run_id for r in reports}) != 4
                    or any(not r.checked_at <= now < r.valid_until for r in reports)):
                raise PrivateNativePending('private_type_four_independent_roles_required')
            exact={v:c.content for v,c in contents.items()}
            for record in exposure.records:
                exact.setdefault(record.content.version_id,record.content)
            for pair in payload['pairs']:
                left, right = (exact.get(UUID(pair[k])) for k in ('left_version_id', 'right_version_id'))
                if left is None or right is None:
                    continue
                profile = cast(TypeProfileV2, 'kc')
                binding = relationship_binding_hash(profile=profile, request_hash=mapping.pack_request.request_hash, left=left, right=right)
                if binding != pair['binding_hash']:
                    raise PrivateNativePending('private_type_actual_relation_binding_required')
                reviews = []
                for report in reports:
                    judgment = next((j for j in report.judgments if j.binding_hash == binding), None)
                    if judgment is None or report.actor_id in {left.author_id, right.author_id}:
                        raise PrivateNativePending('private_type_relation_author_conflict')
                    reviews.append(RelationshipReviewV2(role=report.role, actor_id=report.actor_id,
                        receipt_id=uuid5(report.receipt_id, binding), receipt_hash=canonical_hash({'report': report.receipt_hash, 'judgment': judgment.model_dump(mode='json')}),
                        covered_binding_hashes=(binding,), conclusion=judgment.conclusion, rationale_evidence_hash=judgment.rationale_evidence_hash,
                        checked_at=report.checked_at, valid_until=report.valid_until))
                relation = ContentRelationshipEvidenceV2(profile=profile, request_hash=mapping.pack_request.request_hash,
                    left=left, right=right, exposure_receipt_hash=exposure.completeness_receipt_hash,
                    exposure_watermark=exposure.watermark, reviews=tuple(reviews), receipt_id=rid, receipt_hash=row['payload_hash'],
                    checked_at=row['checked_at'], valid_until=row['valid_until'])
                if binding in relations and relations[binding] != relation:
                    raise PrivateNativePending('private_type_conflicting_relation_batches')
                relations[binding] = relation
        return tuple(relations[k] for k in sorted(relations))

    def _inputs(self, mapping_id: UUID, version_ids: tuple[UUID, ...], exposure_id: UUID,
                relation_ids: tuple[UUID, ...]) -> PackInputsV2:
        if not 5 <= len(version_ids) <= 16 or len(set(version_ids)) != len(version_ids) or not 1 <= len(relation_ids) <= 16:
            raise PrivateNativePending('private_type_bounded_complete_inputs_required')
        mapping = self.resolve_mapping(mapping_id)
        contents = {v: self.query.resolve_content(v) for v in version_ids}
        if len({c.quality.ref.pack_task_id for c in contents.values()}) != 1 or len({c.quality.ref.slot_id for c in contents.values()}) != len(contents):
            raise PrivateNativePending('private_type_same_task_fixed_slots_required')
        row = self.conn.execute('SELECT item_supply_internal.private_native_exposure_current(%s,%s,%s) AS payload',
            (exposure_id, self.user_id, self.epoch)).fetchone()
        if row is None or row['payload'] is None:
            raise PrivateNativePending('private_type_complete_current_exposure_required')
        exposure = CompleteExposureV2.model_validate_json(json.dumps(row['payload']))
        return PackInputsV2(request=mapping.pack_request, candidates=tuple(self._candidate(c, mapping) for c in contents.values()),
            exposure=exposure, relationships=self._relations(relation_ids, mapping, contents, exposure))

    def resolve_pack(self, mapping_receipt_id: UUID, version_ids: tuple[UUID, ...], exposure_snapshot_id: UUID,
                     relation_receipt_ids: tuple[UUID, ...]) -> IssuedPrivatePackCapability:
        inputs = self._inputs(mapping_receipt_id, version_ids, exposure_snapshot_id, relation_receipt_ids)
        now, txid = self._guard()
        result = build_pack(inputs, now=now)
        if result.snapshot is None:
            raise PrivateNativePending('private_type_whole_pack_unavailable')
        eid = uuid4()
        payload = {'schema_version': 'private_native_eligibility_v1', 'mapping_id': str(mapping_receipt_id),
            'versions': [str(v) for v in version_ids], 'relations': [str(v) for v in relation_receipt_ids],
            'exposure_id': str(exposure_snapshot_id), 'inputs_hash': inputs.inputs_hash, 'snapshot': result.snapshot.model_dump(mode='json')}
        self.conn.execute('INSERT INTO tutor_item_supply_private_native_eligibility '
            '(id,user_id,epoch,scope_id,pack_task_id,mapping_id,exposure_snapshot_id,payload_json,checked_at,valid_until,txid) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (eid, self.user_id, self.epoch, self.query.resolve_content(version_ids[0]).quality.ref.scope_id,
             self.query.resolve_content(version_ids[0]).quality.ref.pack_task_id, mapping_receipt_id, exposure_snapshot_id,
             Jsonb(payload), now, result.snapshot.valid_until, txid))
        cap = IssuedPrivatePackCapability(eid, result.snapshot)
        self._issued[eid] = (cap, canonical_hash(payload), txid)
        return cap

    def require_pack(self, cap: IssuedPrivatePackCapability) -> PackSnapshotV2:
        now, txid = self._guard()
        saved = self._issued.get(cap.eligibility_id)
        row = self.conn.execute('SELECT * FROM tutor_item_supply_private_native_eligibility WHERE id=%s AND user_id=%s AND epoch=%s',
            (cap.eligibility_id, self.user_id, self.epoch)).fetchone()
        if (type(cap) is not IssuedPrivatePackCapability or saved is None or saved[0] is not cap or saved[2] != txid
                or row is None or row['txid'] != txid or row['payload_hash'] != saved[1] or now >= row['valid_until']
                or cap.snapshot.model_dump(mode='json') != row['payload_json']['snapshot']):
            raise PrivateNativePending('private_type_same_tx_issued_cap_required')
        p = row['payload_json']
        fresh = self._inputs(UUID(p['mapping_id']), tuple(UUID(v) for v in p['versions']), UUID(p['exposure_id']), tuple(UUID(v) for v in p['relations']))
        # Time-derived observation hashes change on re-read. Immutable selected
        # bindings and actual complete exposure must not; no cached ready grant.
        wanted = {(c.version_id, c.publication_id, c.materialization_id, c.proof_id, canonical_hash(c.type_evidence.content.model_dump(mode='json'))) for c in cap.snapshot.selected}
        rebuilt=build_pack(fresh,now=self._guard()[0]).snapshot
        available = set() if rebuilt is None else {
            (c.version_id,c.publication_id,c.materialization_id,c.proof_id,
             canonical_hash(c.type_evidence.content.model_dump(mode='json'))) for c in rebuilt.selected}
        if wanted!=available or fresh.request != cap.snapshot.request:
            raise PrivateNativePending('private_type_selection_changed')
        checked_model(cap.snapshot, PackSnapshotV2)
        return cap.snapshot
