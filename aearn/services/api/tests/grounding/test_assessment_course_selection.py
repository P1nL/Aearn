"""Three OFFLINE protocol cases, not C claims/PG/D learner acceptance."""
import copy
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus

import app.services.grounding.assessment_course_selection as module
from app.services.grounding.assessment_course_selection import AssessmentCourseSelectionProducer, _binding, _selection
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.assessment_contracts import ExecutionScope
from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, RagEvidenceBinding, SubjectScope
from app.services.grounding.current_authorization import AuthorizationReceipt, EvidenceDenied
from app.services.grounding.public_course_contracts import public_course_demand
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_binding_repository import PostgresMaterialBindingRepository, goal_hash_for_node
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceCoordinate, MaterialSelectionEntry,
    NodeMaterialRequirement, digest,
)
from app.services.learning.item_supply.finite_course_mapping import finite_node_description
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority

NOW = datetime(2026,10,6,5,0,tzinfo=UTC)


def coordinate(demand, *, claim=None):
    binding = RagEvidenceBinding(scope=demand.scope,demand_hash=demand.demand_hash,purpose=demand.purpose,
        source_handle="source.offline",document_handle="document.offline",document_revision="r1",
        document_hash="a"*64,admission_receipt_id="admission.offline",claim_receipt_id=claim)
    return EvidenceCoordinate(binding=binding,subject_id="route.python",corpus_version_id=str(uuid4()),
        active_generation=1,summary_hash="b"*64,validation_hash="c"*64,registry_digest="d"*64,
        source_review_id=str(uuid4()),source_policy_id="policy.offline",source_policy_generation=1,
        chunk_id="chunk.offline",chunk_hash="e"*64,approved_excerpt_hash="e"*64,retrieval_hash="f"*64,
        coverage_hash="1"*64,claim_id=claim,claim_receipt_hash="2"*64 if claim else None,
        execution_receipt_id="execution.offline" if claim else None)


class OfflineConnection:
    autocommit = False

    def __init__(self, *, blocked=False):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.scope = DraftScope(user_id=str(uuid4()),session_id=str(uuid4()),conversation_id=str(uuid4()),
            draft_id=str(uuid4()),draft_version=2,content_hash="3"*64,source_run_id=str(uuid4()),source_input_revision=5)
        s = self.scope
        self.nodes = [dict(knowledge_key="course.base",title="Base",description="Actual fixture prerequisite",
                          is_core=True,prerequisite_keys=[],required_capabilities=["python.assignment"]),
                      dict(knowledge_key="course.state",title="State",description=finite_node_description("python-state-update-v1"),
                          is_core=True,prerequisite_keys=["course.base"],required_capabilities=["python.assignment"])]
        self.parent = dict(id=s.draft_id,draft_version=s.draft_version,content_hash=s.content_hash,
            source_run_id=s.source_run_id,source_input_revision=s.source_input_revision,
            profile_json={"language_id":"python"},plan_json={"modules":[{"nodes":self.nodes}]},
            run_conversation_id=s.conversation_id)
        self.session = dict(id=s.session_id,user_id=s.user_id,conversation_id=s.conversation_id,
            current_draft_id=s.draft_id,version=1,status="draft_ready")
        reqs,entries = [],[]
        for node,purpose in ((self.nodes[0],"main_teaching"),(self.nodes[1],"main_teaching"),
                             (self.nodes[1],"supplementary_explanation")):
            demand = LearningMaterialDemand(scope=SubjectScope(subject_id="route.python",subject_version="1.0",
                facets=("fundamentals",)),demand_hash=digest((node["knowledge_key"],purpose)),
                plan_ref="draft."+s.draft_id,node_ref="node."+node["knowledge_key"],draft_revision=2,
                purpose=purpose,reading_level="beginner",language="zh")
            reqs.append(NodeMaterialRequirement(node_id=node["knowledge_key"],goal_hash=goal_hash_for_node(node),
                prerequisites=tuple(node["prerequisite_keys"]),demand=demand))
            entries.append(MaterialSelectionEntry(node_id=node["knowledge_key"],goal_hash=goal_hash_for_node(node),
                purpose=purpose,status="gap" if blocked and node is self.nodes[0] else "ready",
                gaps=("missing_material",) if blocked and node is self.nodes[0] else (),
                evidence=() if blocked and node is self.nodes[0] else (coordinate(demand),),
                covered_facets=() if blocked and node is self.nodes[0] else ("fundamentals",)))
        self.base = _selection(handle="selection."+"4"*32,draft=s,requirements=tuple(reqs),entries=tuple(entries))
        self.selections = {self.base.handle:dict(snapshot_json=self.base.model_dump(mode="json"),
            selection_digest=self.base.selection_digest,idempotency_key="base-original")}
        self.bindings,self.sql = {},[]
        self.claim_demand = LearningMaterialDemand(scope=reqs[1].demand.scope,demand_hash="5"*64,
            plan_ref="draft."+s.draft_id,node_ref="node.course.state",draft_revision=2,
            purpose="assessment_evidence",reading_level="beginner",language="zh")
        self.assessment_coordinate = coordinate(self.claim_demand,claim="claim.offline")
        self.source_available = True
        self.source_calls,self.source_fail_at = 0,None
        self.source_execution_scope = public_course_execution_scope("python-state-update-v1")
        self.source_applicability = public_course_source_request("python-state-update-v1")[2]
        self.source_actor,self.source_trace = "service.actual-d-fixture",[]

    @contextmanager
    def transaction(self):
        saved = copy.deepcopy((self.selections,self.bindings))
        try:
            yield
        except Exception:
            self.selections,self.bindings = saved
            raise

    def execute(self, text, params=()):
        q = " ".join(text.split())
        self.sql.append(q)
        row, rows = None, []
        if q == "SHOW transaction_isolation":
            row = {"transaction_isolation":"read committed"}
        elif q == "SHOW transaction_read_only":
            row = {"transaction_read_only":"off"}
        elif "clock_timestamp()" in q:
            row = {"now":NOW}
        elif "FROM tutor_learning_plan_sessions" in q:
            row = self.session
        elif "FROM tutor_learning_plan_drafts" in q:
            row = self.parent
        elif q.startswith("SELECT snapshot_json,selection_digest"):
            row = self.selections.get(params[0])
        elif q.startswith("SELECT snapshot_json, idempotency_key"):
            rows = [r for h,r in self.selections.items() if (r["idempotency_key"]==params[1]
                or r["selection_digest"]==params[2] or h==params[3])]
        elif q.startswith("INSERT INTO rag_material_selections"):
            self.selections[params[0]] = dict(snapshot_json=json.loads(params[10]),
                selection_digest=params[9],idempotency_key=params[11])
        elif q.startswith("SELECT binding_json,idempotency_key"):
            rows = [r for r in self.bindings.values() if (r["node_id"]==params[1] and r["goal_hash"]==params[2]
                and r["purpose"]==params[3]) or r["idempotency_key"]==params[4]]
        elif q.startswith("INSERT INTO rag_plan_material_bindings"):
            self.bindings[params[7]] = dict(id=uuid4(),node_id=params[5],goal_hash=params[6],purpose=params[7],
                binding_digest=params[8],binding_json=json.loads(params[9]),idempotency_key=params[10])
        elif q.startswith("SELECT id FROM rag_plan_material_bindings"):
            row = next((r for r in self.bindings.values() if r["node_id"]==params[2] and r["binding_digest"]==params[3]),None)
        else:
            raise AssertionError("unexpected offline SQL: "+q)
        return SimpleNamespace(fetchone=lambda:row,fetchall=lambda:rows)


def producer(monkeypatch, conn):
    receipts = object.__new__(AssessmentReceiptRepository)
    receipts.conn = conn
    monkeypatch.setattr(AssessmentReceiptRepository,"require_transaction",lambda self:None)
    def find(self,h):
        conn.source_trace.append("proof")
        return (SimpleNamespace(prepared=SimpleNamespace(demand=conn.claim_demand,
            execution_scope=conn.source_execution_scope,consume_actor=conn.source_actor)),None,None)
    monkeypatch.setattr(AssessmentReceiptRepository,"_find",find)
    teaching = object.__new__(EvidenceSelection)
    teaching.conn = conn
    teaching.selections = PostgresMaterialBindingRepository(conn)
    monkeypatch.setattr(EvidenceSelection,"require_transaction",lambda self:None)
    def teaching_current(self, db, selection):
        assert db is conn and all(r.demand.purpose != "assessment_evidence" for r in selection.requirements)
        assert {r.node_id for r in selection.requirements if r.demand.purpose=="main_teaching"} == {"course.base","course.state"}
        return CurrentMaterialAuthorizationReceipt(kind="selection",object_digest=selection.selection_digest,
            draft=selection.draft,purposes=tuple(sorted({e.purpose for e in selection.entries})),
            authorization_digest="6"*64,checked_at=NOW)
    monkeypatch.setattr(EvidenceSelection,"authorize_selection",teaching_current)
    def check_current(binding,purpose,**kwargs):
        assert binding.purpose==purpose=="assessment_evidence" and kwargs["exact_item_claims"]
        return AuthorizationReceipt(binding_digest=binding.binding_digest,purpose=purpose,
            corpus_version_id=conn.assessment_coordinate.corpus_version_id,active_generation=1,
            source_policy_generations=(("policy.offline",1),),admission_receipt_ids=("admission.offline",),
            original_source_digests=(),exact_evidence_digest="7"*64,covered_facets=("fundamentals",),checked_at=NOW)
    def resolve(h):
        conn.source_trace.append("canonical-resolver")
        return SimpleNamespace(execution_scope=conn.source_execution_scope,applicability=conn.source_applicability)
    authority = RagSourceAuthority(SimpleNamespace(check_current_authorization=check_current),SimpleNamespace(resolve=resolve))
    monkeypatch.setattr(module,"compose_assessment_authority",lambda db,**kwargs:(None,authority))
    def factory(db, **kwargs):
        assert db is conn and kwargs["claim_receipt_id"]=="claim.offline" and kwargs["node_id"]=="course.state"
        assert kwargs["draft"]==conn.scope
        conn.source_calls += 1
        if not conn.source_available or conn.source_fail_at is not None and conn.source_calls >= conn.source_fail_at:
            raise EvidenceDenied("SOURCE_UNAVAILABLE")
        coord = conn.assessment_coordinate
        temporary = _selection(handle="selection."+"8"*32,draft=conn.scope,
            requirements=(NodeMaterialRequirement(node_id="course.state",goal_hash=kwargs["goal_hash"],
                prerequisites=(),demand=conn.claim_demand),),
            entries=(MaterialSelectionEntry(node_id="course.state",goal_hash=kwargs["goal_hash"],purpose="assessment_evidence",
                status="ready",covered_facets=("fundamentals",),evidence=(coord,)),))
        binding = _binding(temporary,temporary.entries[0])
        exact_claim = VerifiedClaim(claim_hash="9"*64,scope=coord.binding.scope,binding=coord.binding,
            claim_receipt_id="claim.offline",applicability=conn.source_applicability,
            execution_scope=conn.source_execution_scope)
        # Protocol double, not a real source/claim permission; never used in prod.
        return PublicMaterialV2.model_construct(binding=binding,access_request=SimpleNamespace(
            demand_hash=conn.claim_demand.demand_hash,actor_id=conn.source_actor),exact_claims=(exact_claim,),excerpt="OFFLINE fixture")
    monkeypatch.setattr(module,"create_assessment_material",factory)
    return AssessmentCourseSelectionProducer(conn,receipts=receipts,teaching_authority=teaching,enabled=True)


def arguments(conn):
    s = conn.scope
    return dict(user_id=UUID(s.user_id),session_id=UUID(s.session_id),draft_id=UUID(s.draft_id),
        base_selection_handle=conn.base.handle,claim_handles_by_node={"course.state":("claim.offline",)},
        operation_key="offline.operation")


def test_whole_draft_claim_binding_uses_original_repository_and_persisted_identity(monkeypatch):
    conn = OfflineConnection()
    owner = producer(monkeypatch,conn)
    result = owner.produce(**arguments(conn))
    assert result.status == "stored_internal" and len(result.assessment_bindings)==1
    assert conn.source_trace[:2] == ["canonical-resolver","proof"]
    assert result.selection.handle != "selection."+"8"*32  # Not factory-local identity.
    assert result.selection.requirements[:3] == conn.base.requirements
    assert result.selection.entries[:3] == conn.base.entries
    assert all(r.node_id in {"course.base","course.state"} for r in result.selection.requirements)
    stored = next(iter(conn.bindings.values()))["binding_json"]
    assert stored["selection_handle"] == result.selection.handle
    assert stored["selection_digest"] == result.selection.selection_digest
    assert stored["binding_digest"] == result.assessment_bindings[0].binding_digest
    assert result.assessment_bindings[0].binding_id == next(iter(conn.bindings.values()))["id"]
    assert len(conn.bindings)==1  # Do not refreeze/overwrite existing teaching natural keys.
    replay = owner.produce(**arguments(conn))
    assert replay.assessment_bindings == result.assessment_bindings and len(conn.selections)==2


def test_dependency_and_absent_source_remain_gaps_without_assessment_freeze(monkeypatch):
    conn = OfflineConnection(blocked=True)
    owner = producer(monkeypatch,conn)
    blocked = owner.produce(**arguments(conn))
    assert blocked.status == "pending" and not blocked.assessment_bindings and not conn.bindings
    assessment = next(e for e in blocked.selection.entries if e.purpose=="assessment_evidence")
    assert assessment.status == "gap" and "prerequisite_blocked" in assessment.gaps
    conn = OfflineConnection()
    owner = producer(monkeypatch,conn)
    conn.source_available = False
    missing = owner.produce(**arguments(conn))
    assert missing.status == "pending" and not conn.bindings
    assert next(e for e in missing.selection.entries if e.purpose=="assessment_evidence").gaps==("source_stale",)
    conn = OfflineConnection()
    owner = producer(monkeypatch,conn)
    conn.source_fail_at = 4  # The final fence after original INSERT/freeze lock waits.
    late = owner.produce(**arguments(conn))
    assert late.reason == "source_or_claim_stale" and late.selection is None
    assert len(conn.selections)==1 and not conn.bindings  # Same savepoint rollback.


def test_disabled_cross_draft_claim_and_missing_main_requirement_never_write(monkeypatch):
    conn = OfflineConnection()
    owner = producer(monkeypatch,conn)
    owner.enabled = False
    count = len(conn.sql)
    assert owner.produce(**arguments(conn)).status == "disabled" and len(conn.sql)==count
    owner.enabled = True
    old_default = owner.teaching_authority._select(NodeMaterialRequirement(node_id="course.state",
        goal_hash=goal_hash_for_node(conn.nodes[1]),prerequisites=("course.base",),demand=conn.claim_demand))
    assert old_default.status == "gap" and old_default.gaps == ("claim_unverified",)
    conn.source_execution_scope = ExecutionScope(runtime_profile="python-stdout-v1",input_hash="0"*64,semantics_hash="0"*64)
    unsupported = owner.produce(**arguments(conn))
    assert unsupported.reason == "finite_source_issuer_required" and len(conn.selections)==1 and not conn.bindings
    conn.source_execution_scope = public_course_execution_scope("python-state-update-v1")
    actual_demand = conn.claim_demand
    conn.claim_demand = public_course_demand("python-state-update-v1")
    assert owner.produce(**arguments(conn)).reason == "claim_scope_mismatch"
    assert len(conn.selections)==1 and not conn.bindings  # PUBLIC proof is never relabeled.
    conn.claim_demand = actual_demand
    conn.claim_demand = conn.claim_demand.model_copy(update={"plan_ref":"draft."+str(uuid4())})
    denied = owner.produce(**arguments(conn))
    assert denied.reason == "claim_scope_mismatch" and len(conn.selections)==1 and not conn.bindings
    # A selection that omits prerequisite node is rejected by original whole-
    # draft membership, not silently accepted as a one-node course.
    narrowed = _selection(handle=conn.base.handle,draft=conn.scope,
        requirements=conn.base.requirements[:1],entries=conn.base.entries[:1])
    conn.selections[conn.base.handle]["snapshot_json"] = narrowed.model_dump(mode="json")
    conn.selections[conn.base.handle]["selection_digest"] = narrowed.selection_digest
    assert owner.produce(**arguments(conn)).reason == "draft_or_selection_stale" and not conn.bindings
