"""Read-only confirmed D assessment bridge. Does not select, freeze or grant.

An actual draft-ready claim-aware selection/freeze remains a separate owner.
This adapter never relabels teaching evidence or reconstructs authority from JSON.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.autonomous.assessment_receipt_repository import (
    AssessmentReceiptRepository, PostgresAssessmentClaimResolver,
)
from app.services.grounding.current_authorization import AuthorizationReceipt, EvidenceDenied
from app.services.grounding.material_binding_repository import MaterialBindingStale, _check_members, goal_hash_for_node
from app.services.grounding.material_contracts_v2 import EvidenceBindingV2, MaterialSelectionResult
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_course_mapping_contracts import FrozenCourseNodeV1
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.plan_drafting import draft_artifact_from_row


@dataclass(frozen=True)
class ConfirmedAssessmentCourse:
    node: FrozenCourseNodeV1
    binding: EvidenceBindingV2
    selection: MaterialSelectionResult


class ConfirmedAssessmentCourseReader:
    def __init__(self, conn: Connection[dict[str, Any]], *, receipts: AssessmentReceiptRepository,
                 authority: RagSourceAuthority) -> None:
        if (type(receipts) is not AssessmentReceiptRepository or receipts.conn is not conn
                or type(authority) is not RagSourceAuthority or authority.connection is not conn
                or type(authority._claims) is not PostgresAssessmentClaimResolver
                or authority._claims.repository is not receipts
                or authority._current.claim_resolver is not authority._claims
                or authority._current.governance.source_reviews is None
                or authority._current.governance.source_reviews.assessment_receipts is not receipts):
            raise EvidenceDenied("AUTHORITY_MISSING")
        self.conn, self.receipts, self.authority = conn, receipts, authority

    def read(self, *, user_id: UUID, epoch: int, track_id: UUID, revision_id: UUID,
             node_id: UUID, session_id: UUID, assessment_binding_id: UUID) -> ConfirmedAssessmentCourse:
        self.authority._current.require_transaction()
        node = self.conn.execute(
            """SELECT n.*, t.language_id, r.content_hash AS plan_content_hash, r.plan_json
               FROM tutor_track_plan_nodes n JOIN tutor_track_active_plans p
                 ON (p.user_id,p.track_id,p.revision_id)=(n.user_id,n.track_id,n.revision_id)
               JOIN tutor_track_plan_revisions r ON (r.id,r.track_id,r.user_id)=(n.revision_id,n.track_id,n.user_id)
               JOIN tutor_learning_tracks t ON (t.id,t.user_id)=(n.track_id,n.user_id)
               WHERE n.id=%s AND n.user_id=%s AND n.track_id=%s AND n.revision_id=%s
                 AND r.status='active' AND t.status='active' FOR SHARE OF p,n,r,t""",
            (node_id,user_id,track_id,revision_id),
        ).fetchone()
        session = self.conn.execute(
            "SELECT * FROM tutor_learning_plan_sessions WHERE id=%s AND user_id=%s FOR SHARE",
            (session_id,user_id),
        ).fetchone()
        if (node is None or session is None or session["status"] != "confirmed"
                or str(session["confirmed_track_id"]) != str(track_id)):
            raise EvidenceDenied("CONFIRMED_COURSE_MISSING")
        draft = self.conn.execute(
            "SELECT * FROM tutor_learning_plan_drafts WHERE id=%s AND session_id=%s AND user_id=%s FOR SHARE",
            (session["current_draft_id"],session_id,user_id),
        ).fetchone()
        if draft is None:
            raise EvidenceDenied("CONFIRMED_COURSE_MISSING")
        artifact = draft_artifact_from_row(draft)
        # Draft artifact hash and plan hash have different domains. Never compare
        # them to each other, and reject a later active revision of the same track.
        if (artifact.content_hash != draft["content_hash"]
                or artifact.plan.content_hash != node["plan_content_hash"]
                or canonical_plan_payload(artifact.plan) != node["plan_json"]
                or artifact.profile.language_id != node["language_id"]):
            raise EvidenceDenied("FROZEN_NODE_MISMATCH")
        frozen_nodes = [n for m in artifact.plan.modules for n in m.nodes
                        if n.knowledge_key == node["knowledge_key"]]
        if len(frozen_nodes) != 1:
            raise EvidenceDenied("FROZEN_NODE_MISMATCH")
        frozen = asdict(frozen_nodes[0])
        frozen["prerequisite_keys"] = list(frozen_nodes[0].prerequisite_keys)
        frozen["required_capabilities"] = list(frozen_nodes[0].required_capabilities)
        goal = goal_hash_for_node(frozen)
        if (any(frozen[k] != node[k] for k in ("knowledge_key","title","description","is_core","catalog_knowledge_key"))
                or frozen["prerequisite_keys"] != node["prerequisite_keys_json"]
                or frozen["required_capabilities"] != node["required_capabilities_json"]):
            raise EvidenceDenied("FROZEN_NODE_MISMATCH")
        row = self.conn.execute(
            """SELECT b.*, s.snapshot_json, s.conversation_id, s.draft_version,
                      s.content_hash, s.source_run_id, s.source_input_revision
               FROM rag_plan_material_bindings b JOIN rag_material_selections s
                 ON (s.handle,s.draft_id,s.session_id,s.user_id,s.selection_digest)=
                    (b.selection_handle,b.draft_id,b.session_id,b.user_id,b.selection_digest)
               WHERE b.id=%s AND b.user_id=%s AND b.session_id=%s AND b.draft_id=%s
                 AND b.node_id=%s AND b.purpose='assessment_evidence' FOR SHARE OF b,s""",
            (assessment_binding_id,user_id,session_id,draft["id"],node["knowledge_key"]),
        ).fetchone()
        if row is None:
            raise EvidenceDenied("ASSESSMENT_BINDING_MISSING")
        binding = EvidenceBindingV2.model_validate_json(json.dumps(row["binding_json"]))
        selection = MaterialSelectionResult.model_validate_json(json.dumps(row["snapshot_json"]))
        try:
            _check_members(selection,draft)  # Same original whole-draft/node/dependency contract.
        except MaterialBindingStale:
            raise EvidenceDenied("FROZEN_NODE_MISMATCH") from None
        scope = binding.draft
        if (selection.draft != scope or binding.selection_handle != selection.handle
                or binding.selection_digest != selection.selection_digest
                or (row["selection_handle"], row["selection_digest"], row["binding_digest"], row["goal_hash"]) != (
                    selection.handle,selection.selection_digest,binding.binding_digest,goal)
                or binding.node_id != node["knowledge_key"] or binding.goal_hash != goal
                or binding.purpose != "assessment_evidence"
                or (scope.user_id,scope.session_id,scope.draft_id,scope.conversation_id) != (
                    str(user_id),str(session_id),str(draft["id"]),str(session["conversation_id"]))
                or (scope.draft_version,scope.content_hash,scope.source_run_id,scope.source_input_revision) != (
                    draft["draft_version"],draft["content_hash"],str(draft["source_run_id"]),draft["source_input_revision"])
                or (row["draft_version"],row["content_hash"],str(row["source_run_id"]),row["source_input_revision"],
                    str(row["conversation_id"])) != (scope.draft_version,scope.content_hash,scope.source_run_id,
                        scope.source_input_revision,scope.conversation_id)):
            raise EvidenceDenied("FROZEN_NODE_MISMATCH")
        entries = [e for e in selection.entries if (e.node_id,e.goal_hash,e.purpose) == (
            binding.node_id,goal,"assessment_evidence")]
        if (len(entries) != 1 or entries[0].status != "ready"
                or entries[0].evidence != binding.evidence):
            raise EvidenceDenied("ASSESSMENT_SELECTION_PENDING")
        result = FrozenCourseNodeV1(user_id=user_id,epoch=epoch,track_id=track_id,revision_id=revision_id,
            node_id=node_id,session_id=session_id,draft_id=UUID(scope.draft_id),draft_version=scope.draft_version,
            source_run_id=UUID(scope.source_run_id),source_input_revision=scope.source_input_revision,
            draft_content_hash=scope.content_hash,plan_content_hash=node["plan_content_hash"],
            knowledge_key=node["knowledge_key"],title=node["title"],description=node["description"],
            language_id=node["language_id"],is_core=node["is_core"],
            prerequisite_keys=tuple(node["prerequisite_keys_json"]),
            required_capabilities=tuple(node["required_capabilities_json"]),
            catalog_knowledge_key=node["catalog_knowledge_key"],goal_hash=goal,
            selection_handle=selection.handle,selection_digest=selection.selection_digest,
            assessment_binding_id=assessment_binding_id,assessment_binding_digest=binding.binding_digest)
        return ConfirmedAssessmentCourse(result,binding,selection)

    def authorize(self, course: ConfirmedAssessmentCourse, *, target_id: TargetId | None = None) -> AuthorizationReceipt:
        """Resolve ORIGINAL prepared claims and access delegation on this conn."""
        with self.receipts._sqlite_analysis_scope():
            return self._authorize(course, target_id=target_id)

    def _authorize(self, course: ConfirmedAssessmentCourse, *, target_id: TargetId | None) -> AuthorizationReceipt:
        binding = course.binding
        reqs = [r for r in course.selection.requirements if (r.node_id,r.goal_hash,r.demand.purpose) == (
            binding.node_id,binding.goal_hash,"assessment_evidence")]
        if len(reqs) != 1:
            raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
        requirement = reqs[0]
        required_execution = public_course_execution_scope(target_id) if target_id is not None else None
        required_applicability = public_course_source_request(target_id)[2] if target_id is not None else None
        request: AccessRequest | None = None
        claims: dict[str, VerifiedClaim] = {}
        for coord in binding.evidence:
            handle = coord.binding.claim_receipt_id
            if handle is None:
                raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
            # The concrete resolver locks corpus version BEFORE proof/source
            # rows. Loading prepared authority first reverses C's lock order.
            resolved = self.authority._claims.resolve(handle)
            if resolved is None:
                raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
            persisted, _, _ = self.receipts._find(handle)
            q = persisted.prepared
            # Demand/facet identity is NOT semantic coverage. Legacy sum/print
            # or filter/order proofs cannot authorize the finite state/predicate
            # curriculum, even when bound to the same actual draft and node.
            if target_id is not None and (q.execution_scope != required_execution
                    or resolved.execution_scope != required_execution
                    or resolved.applicability != required_applicability):
                raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
            if (q.demand != requirement.demand
                    or requirement.prerequisites != course.node.prerequisite_keys
                    or coord.claim_id != handle
                    or coord.claim_receipt_hash != canonical_hash(resolved.model_dump(mode="json"))
                    or coord.execution_receipt_id != resolved.execution_receipt_id
                or coord.corroboration_id is not None):
                raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
            access = AccessRequest(demand_hash=q.demand.demand_hash,scope=q.demand.scope,
                purpose="assessment_evidence",actor_id=q.consume_actor,action="consume",policy_id=q.policy_id,
                policy_generation=q.policy_generation,budget=q.budget)
            if request is not None and request != access:
                raise EvidenceDenied("BINDING_MISMATCH")
            request = access
            claim = VerifiedClaim(claim_hash=q.claim_hash,scope=q.demand.scope,binding=coord.binding,
                claim_receipt_id=handle,applicability=resolved.applicability,execution_scope=q.execution_scope)
            if handle in claims and claims[handle] != claim:
                raise EvidenceDenied("BINDING_MISMATCH")
            claims[handle] = claim
        if request is None:
            raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
        return self.authority._current.check_current_authorization(binding,"assessment_evidence",
            request=request,exact_item_claims=tuple(claims.values()))
