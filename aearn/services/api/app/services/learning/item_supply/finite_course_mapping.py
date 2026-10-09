"""Concrete same-connection frozen D -> original P3 mapping, not pack readiness."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.grounding.assessment_course_adapter import ConfirmedAssessmentCourseReader
from app.services.grounding.current_authorization import EvidenceDenied
from app.services.grounding.autonomous.source_assessment_profiles import SourceAssessmentDenied
from app.services.grounding.material_binding_repository import goal_hash_for_node
from app.services.learning.item_bank.contracts import (
    LearningItemInteraction, LearningItemKind, LearningItemPurpose, canonical_hash,
)
from app.services.learning.item_bank.native_publication import NativePublishedItemQuery, NativePublicationPending
from app.services.learning.item_bank.native_publication_contracts import NativeInternalRuntimeBindingV1
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1, CoverageBlueprintV1, ObjectiveClauseV1, Slot, SupplyScopeV1,
)
from app.services.learning.item_supply.finite_course_mapping_contracts import (
    FiniteCourseMappingReceiptV1, FiniteCourseMappingResultV1, FiniteCourseProfileV1,
    FrozenCourseNodeV1, StoredCourseDemandV1,
)
from app.services.learning.item_supply.finite_course_targets import (
    finite_node_description as finite_node_description,
    get_finite_course_target,
)
from app.services.learning.item_supply.finite_targets.python_kc import PYTHON_KC_SCORER_VERSION
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.pack_contracts import AuthorizedSubDemandV1, PackRequestV1
from app.services.learning.item_supply.repository import lock_private_namespace
from app.services.learning.item_supply.storage import FrozenPrivateScope, PostgresPrivateSupplyStorage
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.sandbox.python_state_scorer import PYTHON_STATE_SCORER_VERSION
from app.services.learning.item_supply.sandbox.execution_contracts import RUNNER_VERSION
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION

_SLOTS: tuple[Slot, ...] = ("practice", "assessment", "remediation")
_REASONS = {
    "CONFIRMED_COURSE_MISSING": "confirmed_course_missing",
    "FROZEN_NODE_MISMATCH": "frozen_node_mismatch",
    "ASSESSMENT_BINDING_MISSING": "assessment_binding_missing",
    "ASSESSMENT_SELECTION_PENDING": "assessment_selection_pending",
}


def _mapping_hash(node: FrozenCourseNodeV1, profile: FiniteCourseProfileV1) -> str:
    node = checked_model(node, FrozenCourseNodeV1)
    profile = checked_model(profile, FiniteCourseProfileV1)
    target = get_finite_course_target(profile.target_id)
    actual_goal = goal_hash_for_node({
        "knowledge_key": node.knowledge_key, "title": node.title, "description": node.description,
        "is_core": node.is_core, "prerequisite_keys": list(node.prerequisite_keys),
        "required_capabilities": list(node.required_capabilities), "catalog_knowledge_key": node.catalog_knowledge_key,
    })
    if (node.description != finite_node_description(target.target_id)
            or node.language_id != target.language_id
            or node.required_capabilities != target.required_capabilities
            or node.goal_hash != actual_goal):
        raise EvidenceDenied("FROZEN_NODE_MISMATCH")
    return canonical_hash({"domain": "finite-course-mapping-v1", "node": node.model_dump(mode="json"),
                           "target": target.definition_hash, "profile": profile.profile_hash})


def _scope(node: FrozenCourseNodeV1, profile: FiniteCourseProfileV1, slot: Slot) -> SupplyScopeV1:
    target = get_finite_course_target(profile.target_id)
    return SupplyScopeV1(course_family="finite."+target.target_id,course_version=profile.course_version,
        knowledge_key=node.knowledge_key,language_id=target.language_id,subject_id=target.subject_id,
        subject_version=profile.subject_version,required_facets=target.required_facets,
        dialect="sqlite" if target.language_id == "sql" else None,
        runtime_profile_id=target.assessment.runtime_profile_id or "static-exact-v1",
        runtime_profile_hash=profile.runtime_profile_hash,item_kind=LearningItemKind(target.assessment.item_kind),
        purpose=LearningItemPurpose("remediation" if slot == "remediation" else target.assessment.purpose),
        interaction=LearningItemInteraction(target.assessment.interaction),
        required_capabilities=node.required_capabilities,assessment_contract_version=target.target_id,
        scorer_version=profile.scorer_version,assistance_policy_hash=profile.assistance_policy_hash,
        visibility="private",owner_ref="user:"+str(node.user_id))


def _pack(node: FrozenCourseNodeV1, profile: FiniteCourseProfileV1, mapping_hash: str,
          scopes: Mapping[Slot, FrozenPrivateScope]) -> PackRequestV1:
    """Pure projection from actual P3 scope results; NEVER substitute T objective."""
    target = get_finite_course_target(profile.target_id)
    clause_mapping = tuple((c.clause_id,c.definition_hash,c.clause_id.lower(),canonical_hash({
        "domain": "frozen-course-clause-v1", "goal_hash": node.goal_hash,
        "clause_definition_hash": c.definition_hash,
    })) for c in target.clauses)
    clauses = tuple(ObjectiveClauseV1(clause_id=c[2],clause_hash=c[3]) for c in clause_mapping)
    matrix_hash = build_support_matrix().matrix_hash
    demands = []
    for slot in _SLOTS:
        blueprint = CoverageBlueprintV1(scope=_scope(node,profile,slot),objective_hash=scopes[slot].objective_hash,
            clauses=clauses,matrix_hash=matrix_hash,policy_version=profile.policy_version)
        demand = AssessmentSupplyDemandV1(demand_id="course."+mapping_hash+"."+slot,
            learner_ref="user:"+str(node.user_id),scope=blueprint.scope,objective_hash=blueprint.objective_hash,
            blueprint_hash=blueprint.blueprint_hash,matrix_hash=matrix_hash,policy_version=profile.policy_version,
            input_revision=node.source_input_revision)
        demands.append(AuthorizedSubDemandV1(slot=slot,storage_scope_id=scopes[slot].id,
            demand=demand,blueprint=blueprint,mapping_receipt_hash=mapping_hash))
    return PackRequestV1(target_id=target.target_id,target_definition_hash=target.definition_hash,
        learner_id=node.user_id,epoch=node.epoch,track_id=node.track_id,revision_id=node.revision_id,
        node_id=node.node_id,storage_scope_id=scopes["practice"].id,course_mapping_hash=mapping_hash,
        clause_mapping=clause_mapping,demands=tuple(demands))


class FiniteCourseMappingOwner:
    def __init__(self, conn: Connection[dict[str, Any]], *, current_authority: ConfirmedAssessmentCourseReader,
                 profiles: Mapping[str, FiniteCourseProfileV1], runtime_owner: NativePublishedItemQuery | None = None,
                 enabled: bool = False) -> None:
        if type(current_authority) is not ConfirmedAssessmentCourseReader or current_authority.conn is not conn:
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self.conn, self.current_authority, self.enabled = conn, current_authority, enabled
        if runtime_owner is not None and (type(runtime_owner) is not NativePublishedItemQuery or runtime_owner.conn is not conn):
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self.runtime_owner = runtime_owner
        self.profiles = {k: checked_model(v,FiniteCourseProfileV1) for k,v in profiles.items()}
        if any(k != v.profile_id for k,v in self.profiles.items()):
            raise ValueError("profile registry key mismatch")

    def _transaction(self) -> None:
        if self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self.current_authority.authority._current.require_transaction()

    def bind(self, *, user_id: UUID, epoch: int, track_id: UUID, revision_id: UUID, node_id: UUID,
             session_id: UUID, target_id: str, profile_id: str,
             assessment_binding_id: UUID) -> FiniteCourseMappingResultV1:
        if not self.enabled:
            return FiniteCourseMappingResultV1(status="pending",reason="gate_closed")
        self._transaction()
        profile = self.profiles.get(profile_id)
        if profile is None or profile.target_id != target_id:
            return FiniteCourseMappingResultV1(status="pending",reason="profile_missing")
        # Original reset lock order. Never silently create/refresh an absent epoch.
        lock_private_namespace(self.conn,user_id,epoch)
        try:
            course = self.current_authority.read(user_id=user_id,epoch=epoch,track_id=track_id,
                revision_id=revision_id,node_id=node_id,session_id=session_id,
                assessment_binding_id=assessment_binding_id)
            mapping_hash = _mapping_hash(course.node,profile)
            owner = self.runtime_owner
            if owner is None or target_id not in owner._bindings:
                return FiniteCourseMappingResultV1(status="pending",reason="profile_missing")
            runtime = checked_model(owner._bindings[target_id],NativeInternalRuntimeBindingV1)
            target = get_finite_course_target(target_id)
            scorer = {"python-state-update-v1":PYTHON_STATE_SCORER_VERSION,
                "sqlite-predicate-order-v1":GATE_PASS_POLICY_VERSION,
                "python-kc-binding-v1":PYTHON_KC_SCORER_VERSION}[target_id]
            if (runtime.runtime_profile_hash != profile.runtime_profile_hash
                    or runtime.scorer_version != profile.scorer_version or profile.scorer_version != scorer
                    or runtime.runtime_lock is not None and runtime.runner_version != RUNNER_VERSION
                    or runtime.runtime_id != (target.assessment.runtime_profile_id or "static-exact-v1")):
                return FiniteCourseMappingResultV1(status="pending",reason="profile_missing")
            try:
                owner.artifacts.require_owner()
                clock = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
                if clock is None:
                    raise EvidenceDenied("AUTHORITY_MISSING")
                owner._current_runtime(runtime,now=clock["now"])
            except NativePublicationPending:
                return FiniteCourseMappingResultV1(status="pending",reason="profile_missing")
            current = self.current_authority.authorize(course,target_id=target_id)
            requirement = next(r for r in course.selection.requirements if (r.node_id,r.goal_hash,r.demand.purpose) == (
                course.node.knowledge_key,course.node.goal_hash,"assessment_evidence"))
            if (requirement.demand.scope.subject_id != target.subject_id
                    or requirement.demand.scope.subject_version != profile.subject_version
                    or requirement.demand.scope.facets != target.required_facets):
                raise EvidenceDenied("FROZEN_NODE_MISMATCH")
            # Nested savepoint only; the caller still owns commit/rollback. A late
            # source failure must not leave orphan P3 registrations in this tx.
            with self.conn.transaction():
                storage = PostgresPrivateSupplyStorage(self.conn,user_id=user_id,expected_epoch=epoch)
                scopes = {slot: storage.bind_scope(track_id=track_id,revision_id=revision_id,
                    scope=_scope(course.node,profile,slot)) for slot in _SLOTS}
                request = _pack(course.node,profile,mapping_hash,scopes)
                stored = tuple(StoredCourseDemandV1(slot=d.slot,scope_id=d.storage_scope_id,
                    demand_id=storage.store_demand(scope_id=d.storage_scope_id,
                        request_key=d.demand.demand_id,demand=d.demand)) for d in request.demands)
                audit_hash = canonical_hash({"binding": current.binding_digest,
                    "exact_evidence": current.exact_evidence_digest,
                    "sources": current.original_source_digests,"generation": current.active_generation})
                receipt = FiniteCourseMappingReceiptV1(receipt_id=uuid4(),frozen_node=course.node,
                    target_id=target.target_id,target_definition_hash=target.definition_hash,profile=profile,
                    mapping_hash=mapping_hash,pack_request=request,stored_demands=stored,
                    source_authorization_hash=audit_hash,checked_at=current.checked_at)
                receipt = self._store(receipt)
                # Final fences after *all* P3/mapping conflict lock waits. A
                # failure rolls the nested savepoint back, never commits here.
                clock = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
                if clock is None:
                    raise EvidenceDenied("AUTHORITY_MISSING")
                try:
                    owner._current_runtime(runtime,now=clock["now"])
                except NativePublicationPending:
                    raise EvidenceDenied("AUTHORITY_MISSING") from None
                self.current_authority.authorize(course,target_id=target_id)
            return FiniteCourseMappingResultV1(status="mapped_internal",reason="exact_frozen_mapping",receipt=receipt)
        except (EvidenceDenied,SourceAssessmentDenied) as exc:
            return FiniteCourseMappingResultV1.model_validate({"status":"pending",
                "reason":_REASONS.get(str(exc),"source_or_claim_stale")})

    def _store(self, receipt: FiniteCourseMappingReceiptV1) -> FiniteCourseMappingReceiptV1:
        n = receipt.frozen_node
        d = {d.slot:d for d in receipt.stored_demands}
        self.conn.execute(
            """INSERT INTO tutor_item_supply_finite_course_mappings
               (id,user_id,epoch,track_id,revision_id,node_id,knowledge_key,session_id,draft_id,
                selection_handle,selection_digest,assessment_binding_id,binding_digest,goal_hash,
                mapping_hash,practice_scope_id,practice_demand_id,assessment_scope_id,assessment_demand_id,
                remediation_scope_id,remediation_demand_id,receipt_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (user_id,epoch,mapping_hash) DO NOTHING""",
            (receipt.receipt_id,n.user_id,n.epoch,n.track_id,n.revision_id,n.node_id,n.knowledge_key,n.session_id,n.draft_id,
             n.selection_handle,n.selection_digest,n.assessment_binding_id,n.assessment_binding_digest,n.goal_hash,
             receipt.mapping_hash,d["practice"].scope_id,d["practice"].demand_id,
             d["assessment"].scope_id,d["assessment"].demand_id,d["remediation"].scope_id,d["remediation"].demand_id,
             Jsonb(receipt.model_dump(mode="json"))),
        )
        row = self.conn.execute("SELECT receipt_json FROM tutor_item_supply_finite_course_mappings "
            "WHERE user_id=%s AND epoch=%s AND mapping_hash=%s FOR SHARE",
            (n.user_id,n.epoch,receipt.mapping_hash)).fetchone()
        if row is None:
            raise ValueError("immutable mapping storage missing")
        persisted = FiniteCourseMappingReceiptV1.model_validate_json(json.dumps(row["receipt_json"]))
        excluded = {"receipt_id","checked_at","source_authorization_hash"}
        if persisted.model_dump(exclude=excluded) != receipt.model_dump(exclude=excluded):
            raise ValueError("immutable mapping replay conflict")
        return persisted

    def resolve(self, *, receipt_id: UUID, user_id: UUID, epoch: int) -> FiniteCourseMappingResultV1:
        if not self.enabled:
            return FiniteCourseMappingResultV1(status="pending",reason="gate_closed")
        self._transaction()
        lock_private_namespace(self.conn,user_id,epoch)
        row = self.conn.execute("SELECT receipt_json FROM tutor_item_supply_finite_course_mappings "
            "WHERE id=%s AND user_id=%s AND epoch=%s FOR SHARE",(receipt_id,user_id,epoch)).fetchone()
        if row is None:
            return FiniteCourseMappingResultV1(status="pending",reason="mapping_missing_or_stale")
        saved = FiniteCourseMappingReceiptV1.model_validate_json(json.dumps(row["receipt_json"]))
        n = saved.frozen_node
        if (saved.receipt_id != receipt_id or (n.user_id,n.epoch) != (user_id,epoch)
                or saved.profile != self.profiles.get(saved.profile.profile_id)
                or _mapping_hash(n,saved.profile) != saved.mapping_hash
                or get_finite_course_target(saved.target_id).definition_hash != saved.target_definition_hash):
            return FiniteCourseMappingResultV1(status="pending",reason="mapping_missing_or_stale")
        # bind re-reads confirmed D, validates clauses, re-authorizes current claims
        # and re-resolves original immutable P3 rows; replay cannot create a wallet.
        return self.bind(user_id=user_id,epoch=epoch,track_id=n.track_id,revision_id=n.revision_id,
            node_id=n.node_id,session_id=n.session_id,target_id=saved.target_id,profile_id=saved.profile.profile_id,
            assessment_binding_id=n.assessment_binding_id)
