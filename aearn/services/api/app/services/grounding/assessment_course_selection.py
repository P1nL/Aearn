"""Default-off actual D assessment selection/freeze; no acquisition or confirm.

Preserves the entire persisted draft selection, including main-teaching needs.
Hashes/DTOs do not authorize evidence: original C/claim owners recheck every use.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Literal, TYPE_CHECKING
from uuid import UUID

from psycopg import Connection
from pydantic import Field, model_validator

from app.services.grounding.assessment_material_factory import (
    compose_assessment_authority, create_assessment_material,
    compose_assessment_preparation_authority, create_assessment_preparation_material,
)
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.contracts import FrozenContract, LearningMaterialDemand, revalidate
from app.services.grounding.autonomous.source_assessment_profiles import PreparedSourceAssessment, SourceAssessmentDenied
from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.current_authorization import AuthorizationReceipt, EvidenceDenied
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_binding_repository import (
    MaterialBindingStale, PostgresMaterialBindingRepository, _check_members, _plan_nodes,
    _scope_from_draft, goal_hash_for_node,
)
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceBindingV2, EvidenceCoordinate,
    MaterialSelectionEntry, MaterialSelectionResult, NodeMaterialRequirement,
    apply_material_dependencies, digest,
)
from app.services.learning.item_supply.finite_course_mapping import finite_node_description
from app.services.learning.item_supply.finite_course_targets import finite_course_targets
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority

if TYPE_CHECKING:
    from app.services.grounding.autonomous.public_python_teaching_review import PublicPythonTeachingVerifier


class FrozenAssessmentCourseBinding(FrozenContract):
    node_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    binding_id: UUID
    binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class AssessmentCourseSelectionResult(FrozenContract):
    status: Literal["disabled","pending","stored_internal"]
    reason: Literal["gate_closed","material_gap","assessment_frozen_internal","draft_or_selection_stale",
                    "assessment_demand_missing","claim_scope_mismatch","source_or_claim_stale","finite_source_issuer_required"]
    selection: MaterialSelectionResult | None = None
    assessment_bindings: tuple[FrozenAssessmentCourseBinding, ...] = Field(default=(),max_length=128)

    @model_validator(mode="after")
    def non_ready(self) -> AssessmentCourseSelectionResult:
        if ((self.status == "stored_internal") != bool(self.assessment_bindings)
                or self.assessment_bindings and self.selection is None
                or self.status == "disabled" and self.selection is not None):
            raise ValueError("assessment producer result mismatch")
        return self


def _selection(*, handle: str, draft: DraftScope, requirements: tuple[NodeMaterialRequirement, ...],
               entries: tuple[MaterialSelectionEntry, ...]) -> MaterialSelectionResult:
    entries = apply_material_dependencies(requirements,entries)
    payload = dict(handle=handle,draft=draft.model_dump(mode="json"),
        requirements=[r.model_dump(mode="json") for r in requirements],
        entries=[e.model_dump(mode="json") for e in entries],contract_version="rag_d_selection_v2")
    return MaterialSelectionResult.model_validate_json(json.dumps({**payload,"selection_digest":digest(payload)}))


def _binding(selection: MaterialSelectionResult, entry: MaterialSelectionEntry) -> EvidenceBindingV2:
    # Freeze preserves exact entry order. Assessment entries are canonicalized
    # before selection hashing, not reordered behind its immutable digest.
    payload = dict(contract_version="rag_d_binding_v2",selection_handle=selection.handle,
        selection_digest=selection.selection_digest,draft=selection.draft.model_dump(mode="json"),
        node_id=entry.node_id,goal_hash=entry.goal_hash,purpose=entry.purpose,
        evidence=[c.model_dump(mode="json") for c in entry.evidence])
    return EvidenceBindingV2.model_validate_json(json.dumps({**payload,"binding_digest":digest(payload)}))


def _pairs(selection: MaterialSelectionResult) -> tuple[tuple[NodeMaterialRequirement, MaterialSelectionEntry], ...]:
    by_key = {(e.node_id,e.goal_hash,e.purpose):e for e in selection.entries}
    return tuple((r,by_key[(r.node_id,r.goal_hash,r.demand.purpose)]) for r in selection.requirements)


class AssessmentCourseSelectionProducer:
    def __init__(self, conn: Connection[dict[str, Any]], *, receipts: AssessmentReceiptRepository,
                 teaching_authority: EvidenceSelection,
                 teaching_verifier: PublicPythonTeachingVerifier | None = None,
                 enabled: bool = False) -> None:
        if (type(receipts) is not AssessmentReceiptRepository or receipts.conn is not conn
                or type(teaching_authority) is not EvidenceSelection or teaching_authority.conn is not conn
                or teaching_authority.selections is None or teaching_authority.selections.conn is not conn):
            raise EvidenceDenied("AUTHORITY_MISSING")
        self.conn, self.receipts, self.teaching_authority = conn, receipts, teaching_authority
        self.teaching_verifier, self.enabled = teaching_verifier, enabled
        self.repo = PostgresMaterialBindingRepository(conn)

    def _guard(self) -> None:
        if not self.enabled:
            raise EvidenceDenied("GATE_CLOSED")
        self.teaching_authority.require_transaction()
        self.receipts.require_transaction()

    def _assessment(self) -> RagSourceAuthority:
        if getattr(self.receipts,"actual_d_private_provenance_enabled",False):
            _, authority = compose_assessment_preparation_authority(self.conn,receipts=self.receipts,owner=self,
                teaching_verifier=self.teaching_verifier,enabled=True)
            return authority
        _, authority = compose_assessment_authority(self.conn,receipts=self.receipts,
            teaching_verifier=self.teaching_verifier,enabled=True)
        return authority

    def _load(self, *, user_id: UUID, session_id: UUID, draft_id: UUID) -> tuple[DraftScope, dict[str, Any]]:
        # Original session-before-draft lock order; do not upgrade a shared
        # session lock after a second producer has taken that same lock.
        session = self.conn.execute("SELECT conversation_id,current_draft_id,status FROM tutor_learning_plan_sessions "
            "WHERE id=%s AND user_id=%s FOR UPDATE",(session_id,user_id)).fetchone()
        if session is None or session["status"] != "draft_ready" or str(session["current_draft_id"]) != str(draft_id):
            raise MaterialBindingStale("exact draft-ready course required")
        row = self.conn.execute(
            "SELECT * FROM tutor_learning_plan_drafts WHERE id=%s AND user_id=%s AND session_id=%s FOR SHARE",
            (draft_id,user_id,session_id),
        ).fetchone()
        if row is None:
            raise MaterialBindingStale("exact draft-ready course required")
        scope = DraftScope(user_id=str(user_id),session_id=str(session_id),draft_id=str(draft_id),
            conversation_id=str(session["conversation_id"]),draft_version=row["draft_version"],
            content_hash=row["content_hash"],source_run_id=str(row["source_run_id"]),
            source_input_revision=row["source_input_revision"])
        # Reuse original session/current-draft/source-run lock and scope checks.
        _scope_from_draft(self.conn,scope,lock=True)
        return scope,row

    def _teaching_current(self, selection: MaterialSelectionResult, parent: Mapping[str, object]) -> CurrentMaterialAuthorizationReceipt:
        nodes = _plan_nodes(parent)
        _check_members(selection,parent)
        if {r.node_id for r in selection.requirements if r.demand.purpose == "main_teaching"} != set(nodes):
            raise MaterialBindingStale("entire draft main-teaching requirements must be preserved")
        pairs = [(r,e) for r,e in _pairs(selection)
                 if r.demand.purpose != "assessment_evidence"]
        # Original selector still owns teaching/access checks. This read-only
        # projection excludes assessment solely because its old guard denies it;
        # no node or main requirement is dropped, and no projection is persisted.
        teaching = _selection(handle=selection.handle,draft=selection.draft,
            requirements=tuple(r for r,_ in pairs),entries=tuple(e for _,e in pairs))
        _check_members(teaching,parent)
        return self.teaching_authority.authorize_selection(self.conn,teaching)

    def _check_demand(self, demand: LearningMaterialDemand, *, scope: DraftScope,
                      node: Mapping[str, object], language_id: str,
                      main: NodeMaterialRequirement) -> TargetId:
        target_id = self._target_id(node,language_id)
        target = next(t for t in finite_course_targets() if t.target_id == target_id)
        if (demand.purpose != "assessment_evidence" or demand.plan_ref != "draft."+scope.draft_id
                or demand.node_ref != "node."+str(node["knowledge_key"])
                or demand.draft_revision != scope.draft_version
                or demand.scope.subject_id != target.subject_id or demand.scope.facets != target.required_facets
                or demand.scope.subject_version != main.demand.scope.subject_version
                or demand.scope.subject_id != main.demand.scope.subject_id
                or demand.reading_level != main.demand.reading_level or demand.language != main.demand.language):
            raise EvidenceDenied("CLAIM_SCOPE_MISMATCH")
        return target_id

    def _target_id(self, node: Mapping[str, object], language_id: str) -> TargetId:
        targets = [t for t in finite_course_targets() if node.get("description") == finite_node_description(t.target_id)
                   and language_id == t.language_id
                   and node.get("required_capabilities") == list(t.required_capabilities)]
        if len(targets) != 1:
            raise EvidenceDenied("CLAIM_SCOPE_MISMATCH")
        return targets[0].target_id

    def _finite_prepared(self, authority: RagSourceAuthority, handle: str, target_id: TargetId) -> PreparedSourceAssessment:
        # Canonical resolver locks active corpus BEFORE source proof/policy rows.
        # PUBLIC finite receipts cannot be rebound to D; old D sum/print/filter
        # proofs do not establish these finite target semantics.
        resolved = authority._claims.resolve(handle)
        if resolved is None:
            raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
        persisted,_,_ = self.receipts._find(handle)
        q = persisted.prepared
        execution = public_course_execution_scope(target_id)
        applicability = public_course_source_request(target_id)[2]
        if (q.execution_scope != execution or resolved.execution_scope != execution
                or resolved.applicability != applicability):
            raise EvidenceDenied("FINITE_SOURCE_ISSUER_REQUIRED")
        return q

    def _assessment_current(self, selection: MaterialSelectionResult, entry: MaterialSelectionEntry,
                            parent: Mapping[str, object]) -> AuthorizationReceipt:
        authority = self._assessment()
        requirement = next(r for r in selection.requirements if (r.node_id,r.goal_hash,r.demand.purpose) == (
            entry.node_id,entry.goal_hash,"assessment_evidence"))
        main = next(r for r in selection.requirements if (r.node_id,r.demand.purpose) == (entry.node_id,"main_teaching"))
        nodes = _plan_nodes(parent)
        profile = parent["profile_json"]
        if not isinstance(profile,dict):
            raise MaterialBindingStale("actual draft profile required")
        target_id = self._check_demand(requirement.demand,scope=selection.draft,node=nodes[entry.node_id],
                           language_id=profile["language_id"],main=main)
        request = None
        claims: dict[str, VerifiedClaim] = {}
        for coordinate in entry.evidence:
            handle = coordinate.binding.claim_receipt_id
            if handle is None:
                raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
            prepared = self._finite_prepared(authority,handle,target_id)
            if prepared.demand != requirement.demand:
                raise EvidenceDenied("CLAIM_SCOPE_MISMATCH")
            # ORIGINAL factory re-resolves prepared claim, source, current pointer
            # and permissions. Exact chunk, not a rewritten excerpt/old JSON.
            factory = create_assessment_preparation_material if getattr(authority._claims,"preparation_owner",None) is self else create_assessment_material
            owner_args: dict[str, Any] = {"owner":self} if factory is create_assessment_preparation_material else {}
            material = factory(self.conn,receipts=self.receipts,authority=authority,**owner_args,
                claim_receipt_id=handle,draft=selection.draft,node_id=entry.node_id,goal_hash=entry.goal_hash,
                chunk_id=coordinate.chunk_id,enabled=True)
            if (material.binding.evidence != (coordinate,) or request is not None and request != material.access_request
                    or material.access_request.actor_id != prepared.consume_actor
                    or material.exact_claims[0].execution_scope != public_course_execution_scope(target_id)
                    or material.exact_claims[0].applicability != public_course_source_request(target_id)[2]):
                raise EvidenceDenied("BINDING_MISMATCH")
            request = material.access_request
            claim = material.exact_claims[0]
            if handle in claims and claims[handle] != claim:
                raise EvidenceDenied("BINDING_MISMATCH")
            claims[handle] = claim
        if request is None:
            raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
        binding = _binding(selection,entry)
        current = authority._current.check_current_authorization(binding,"assessment_evidence",
            request=request,exact_item_claims=tuple(claims.values()))
        if tuple(current.covered_facets) != requirement.demand.scope.facets or set(entry.covered_facets) != set(current.covered_facets):
            raise EvidenceDenied("EVIDENCE_INSUFFICIENT")
        return current

    def authorize_selection(self, conn: Connection[dict[str, Any]], selection: MaterialSelectionResult) -> CurrentMaterialAuthorizationReceipt:
        if conn is not self.conn:
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self._guard()
        selection = revalidate(selection,MaterialSelectionResult)
        parent = _scope_from_draft(conn,selection.draft,lock=False)
        teaching = self._teaching_current(selection,parent)
        receipts = [teaching.authorization_digest]
        for entry in selection.entries:
            if entry.purpose == "assessment_evidence" and entry.status == "ready":
                current = self._assessment_current(selection,entry,parent)
                receipts.append(digest({"binding":current.binding_digest,"evidence":current.exact_evidence_digest,
                    "sources":current.original_source_digests,"generation":current.active_generation}))
        now = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if now is None:
            raise EvidenceDenied("AUTHORITY_MISSING")
        return CurrentMaterialAuthorizationReceipt(kind="selection",object_digest=selection.selection_digest,
            draft=selection.draft,purposes=tuple(sorted({r.demand.purpose for r in selection.requirements})),
            authorization_digest=digest(receipts),checked_at=now["now"])

    def authorize_binding(self, conn: Connection[dict[str, Any]], binding: EvidenceBindingV2) -> CurrentMaterialAuthorizationReceipt:
        if conn is not self.conn:
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        self._guard()
        binding = revalidate(binding,EvidenceBindingV2)
        if binding.purpose != "assessment_evidence":
            return self.teaching_authority.authorize_binding(conn,binding)
        selection = self.repo.get_selection(handle=binding.selection_handle,draft=binding.draft)
        parent = _scope_from_draft(conn,binding.draft,lock=False)
        self._teaching_current(selection,parent)
        entry = next((e for e in selection.entries if (e.node_id,e.goal_hash,e.purpose) == (
            binding.node_id,binding.goal_hash,binding.purpose)),None)
        if (entry is None or entry.status != "ready" or _binding(selection,entry) != binding):
            raise EvidenceDenied("BINDING_MISMATCH")
        current = self._assessment_current(selection,entry,parent)
        return CurrentMaterialAuthorizationReceipt(kind="binding",object_digest=binding.binding_digest,
            draft=binding.draft,purposes=("assessment_evidence",),authorization_digest=digest({
                "evidence":current.exact_evidence_digest,"sources":current.original_source_digests,
                "generation":current.active_generation}),checked_at=current.checked_at)

    def produce(self, *, user_id: UUID, session_id: UUID, draft_id: UUID,
                base_selection_handle: str, claim_handles_by_node: Mapping[str, tuple[str, ...]],
                operation_key: str) -> AssessmentCourseSelectionResult:
        if not self.enabled:
            return AssessmentCourseSelectionResult(status="disabled",reason="gate_closed")
        if (not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{2,79}",operation_key)
                or not claim_handles_by_node or len(claim_handles_by_node)>128
                or any(type(handles) is not tuple or len(handles)>12 or len(set(handles)) != len(handles)
                       or any(type(h) is not str or re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,159}",h) is None for h in handles)
                       for handles in claim_handles_by_node.values())):
            raise ValueError("bounded operation and exact claim references required")
        self._guard()
        try:
            scope,parent = self._load(user_id=user_id,session_id=session_id,draft_id=draft_id)
            base = self.repo.get_selection(handle=base_selection_handle,draft=scope)
            self._teaching_current(base,parent)
            nodes = _plan_nodes(parent)
            if set(claim_handles_by_node)-set(nodes):
                raise EvidenceDenied("CLAIM_SCOPE_MISMATCH")
            if any(e.purpose == "assessment_evidence" and e.status == "ready" and e.node_id not in claim_handles_by_node
                   for e in base.entries):
                raise MaterialBindingStale("all existing ready assessment needs must be rechecked")
            authority = self._assessment()
            pairs = {(r.node_id,r.goal_hash,r.demand.purpose):(r,e) for r,e in _pairs(base)}
            for key,handles in claim_handles_by_node.items():
                node = nodes[key]
                goal = goal_hash_for_node(node)
                prior = pairs.get((key,goal,"assessment_evidence"))
                main = next(r for r in base.requirements if (r.node_id,r.demand.purpose) == (key,"main_teaching"))
                profile = parent["profile_json"]
                if not isinstance(profile,dict):
                    raise MaterialBindingStale("actual draft profile required")
                target_id = self._target_id(node,profile["language_id"])
                demands = [self._finite_prepared(authority,h,target_id).demand for h in handles]
                if not demands and prior is None:
                    return AssessmentCourseSelectionResult(status="pending",reason="assessment_demand_missing")
                if demands:
                    demand = demands[0]
                else:
                    assert prior is not None
                    demand = prior[0].demand
                if any(d != demand for d in demands) or prior is not None and prior[0].demand != demand:
                    raise EvidenceDenied("CLAIM_SCOPE_MISMATCH")
                self._check_demand(demand,scope=scope,node=node,language_id=profile["language_id"],main=main)
                prerequisites = node["prerequisite_keys"]
                if not isinstance(prerequisites,list):
                    raise MaterialBindingStale("actual node prerequisites required")
                req = NodeMaterialRequirement(node_id=key,goal_hash=goal,
                    prerequisites=tuple(prerequisites),demand=demand)
                coordinates: list[EvidenceCoordinate] = []
                gaps: tuple[Literal["claim_unverified","source_stale"], ...] = ()
                if not handles:
                    gaps = ("claim_unverified",)
                else:
                    try:
                        for handle in handles:
                            factory = create_assessment_preparation_material if getattr(authority._claims,"preparation_owner",None) is self else create_assessment_material
                            owner_args: dict[str, Any] = {"owner":self} if factory is create_assessment_preparation_material else {}
                            material = factory(self.conn,receipts=self.receipts,authority=authority,**owner_args,
                                claim_receipt_id=handle,draft=scope,node_id=key,goal_hash=goal,enabled=True)
                            coordinates.extend(material.binding.evidence)
                    except (EvidenceDenied,SourceAssessmentDenied):
                        gaps = ("source_stale",)
                        coordinates = []
                evidence = tuple(sorted(coordinates,key=lambda c:digest(c.model_dump(mode="json"))))
                entry = MaterialSelectionEntry(node_id=key,goal_hash=goal,purpose="assessment_evidence",
                    status="gap" if gaps else "ready",gaps=gaps,evidence=evidence,
                    covered_facets=() if gaps else demand.scope.facets)
                pairs[(key,goal,"assessment_evidence")] = (req,entry)
            selection = _selection(handle="selection."+digest({"draft":scope.model_dump(mode="json"),
                "base":base.handle,"operation":operation_key})[:32],draft=scope,
                requirements=tuple(r for r,_ in pairs.values()),entries=tuple(e for _,e in pairs.values()))
            _check_members(selection,parent)
            self.authorize_selection(self.conn,selection)
            frozen = []
            # Nested savepoint. Any late current fence/conflict rolls back this
            # whole producer slice; caller alone owns outer commit/confirm.
            with self.conn.transaction():
                saved = self.repo.record_selection(selection,idempotency_key="assessment-course:"+operation_key)
                for entry in saved.entries:
                    if entry.purpose != "assessment_evidence" or entry.status != "ready":
                        continue
                    binding = self.repo.freeze_binding(binding=_binding(saved,entry),
                        idempotency_key="assessment:"+operation_key+":"+digest(entry.node_id)[:24],
                        current_authorization=self.authorize_binding)
                    row = self.conn.execute("SELECT id FROM rag_plan_material_bindings WHERE user_id=%s AND draft_id=%s "
                        "AND node_id=%s AND purpose='assessment_evidence' AND binding_digest=%s FOR SHARE",
                        (user_id,draft_id,entry.node_id,binding.binding_digest)).fetchone()
                    if row is None:
                        raise MaterialBindingStale("frozen assessment identity unavailable")
                    frozen.append(FrozenAssessmentCourseBinding(node_id=entry.node_id,binding_id=UUID(str(row["id"])),
                        binding_digest=binding.binding_digest))
                self.authorize_selection(self.conn,saved)
            return AssessmentCourseSelectionResult(status="stored_internal" if frozen else "pending",
                reason="assessment_frozen_internal" if frozen else "material_gap",selection=saved,
                assessment_bindings=tuple(frozen))
        except MaterialBindingStale:
            return AssessmentCourseSelectionResult(status="pending",reason="draft_or_selection_stale")
        except (EvidenceDenied,SourceAssessmentDenied) as exc:
            return AssessmentCourseSelectionResult(status="pending",reason=(
                "finite_source_issuer_required" if str(exc)=="FINITE_SOURCE_ISSUER_REQUIRED" else
                "claim_scope_mismatch" if str(exc)=="CLAIM_SCOPE_MISMATCH" else "source_or_claim_stale"))
