"""OFFLINE native consumer protocol, not PG/OS/provider/learner acceptance.

Real signatures use ephemeral fixture keys and the existing OFFLINE seal stub.
The pre-existing C audit/teaching baseline is a fixed fixture boundary; private
bridge, proof validation, factory, canonical resolvers and current authorization
are real code, not true callbacks or supplied mapping IDs.
"""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services.grounding.autonomous.corpus_governance import CorpusGovernance
from app.services.grounding.autonomous.actual_d_lifecycle import actual_d_private_counts, export_actual_d_private
from app.services.grounding.autonomous.source_assessment_profiles import (
    SourceAssessmentDenied, run_source_assessment, sign_source_assessment, source_proof_hash,
    source_request, storage_profile_id,
)
from app.services.grounding.assessment_material_factory import (
    compose_assessment_authority, create_assessment_material, create_assessment_preparation_material,
)
from app.services.grounding.assessment_course_selection import AssessmentCourseSelectionProducer, _selection
from app.services.grounding.assessment_course_adapter import ConfirmedAssessmentCourseReader
from app.services.grounding.corpus_repository import _hash
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_binding_repository import PostgresMaterialBindingRepository
from app.services.grounding.material_contracts_v2 import CurrentMaterialAuthorizationReceipt
from app.services.grounding.material_contracts_v2 import MaterialSelectionEntry
from app.services.grounding.public_course_contracts import public_course_demand
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_course_mapping import _mapping_hash, _pack
from app.services.learning.item_supply.storage import FrozenPrivateScope
from app.services.learning.plan_drafting import draft_artifact_from_row
from app.services.learning.plan_service import LearningPlanSessionService
from tests.grounding import test_actual_d_finite_source as prior
from tests.grounding.test_actual_d_private_lifecycle import installed_protocol as _installed_protocol
from tests.learning.test_item_supply_finite_course_mapping import profile
from tests.grounding.test_assessment_course_selection import coordinate


@pytest.fixture(name="installed_protocol")
def _provenance_protocol(monkeypatch):
    _installed_protocol.__wrapped__(monkeypatch)


def evidence_row(signed):
    p, q = signed.payload, signed.payload.prepared
    proof_hash = source_proof_hash(signed)
    applicability = source_request(q.profile_id)[2]
    return dict(id=p.evidence_id,capture_id=q.capture_id,source_handle=q.source_handle,document_handle=q.document_handle,
        document_hash=q.document_hash,policy_id=q.policy_id,policy_generation=q.policy_generation,root_id=q.budget.root_id,
        profile_id=storage_profile_id(q),demand_hash=q.demand.demand_hash,claim_hash=q.claim_hash,execution_handle=p.execution_handle,
        claim_handle=p.claim_handle,service_key_id=signed.service_key_id,proof_hash=proof_hash,terminal_hash=canonical_hash(p.terminal),
        issued_at=p.issued_at,expires_at=p.expires_at,review_id=p.review_id,admission_id=p.admission_id,claim_id=p.claim_id,
        review_receipt_hash=proof_hash,quality_evidence_hash=proof_hash,storage_receipt_id=q.storage_receipt_id,license_id=q.license_id,
        origin="official",reading_level=q.reading_level,subject_id=q.demand.scope.subject_id,subject_version=q.demand.scope.subject_version,
        document_revision=q.document_hash,status="reviewed",quality_code="QUALIFIED",reading_fit="suitable",version_fit="current",
        technical_status="correct",conflict_status="resolved",known_error="absent",immutable_history_allowed=True,
        receipt_handle=p.admission_handle,admission_generation=q.policy_generation,active=True,admission_revoked=None,claim_revoked=None,
        stored_claim_handle=p.claim_handle,stored_claim_hash=q.claim_hash,stored_demand_hash=q.demand.demand_hash,applicability=applicability,
        applicability_hash=hashlib.sha256(applicability.encode()).hexdigest(),source_document_hash=q.document_hash,
        execution_receipt_handle=p.execution_handle,verification_receipt_hash=proof_hash,method="isolated_execution",
        execution_scope_json=q.execution_scope.model_dump(mode="json"),facets=list(q.demand.scope.facets),
        covered_facets=list(q.demand.scope.facets),scope_facets=list(q.demand.scope.facets),review_usages=["assessment_evidence"],
        admission_usages=["assessment_evidence"],signed_proof=signed.model_dump(mode="json"),revoked_at=None,
        private_user_id=UUID(q.actual_d.draft.user_id) if hasattr(q,"actual_d") else None,
        private_epoch=q.actual_d.user_epoch if hasattr(q,"actual_d") else None,lineage_family="family.python")


class BridgeProtocol(prior.OfflineD):
    def __init__(self):
        super().__init__("python-state-update-v1")
        self.evidence = {}
        self.bridge = None
        self.carrier_enabled = True
        self.now = prior.NOW
        self.cid, self.track_id, self.revision_id = uuid4(), uuid4(), uuid4()
        self.event_id = uuid4()
        self.generation = 1
        self.chunks = []
        self.saved_selections = {}
        self.bindings = []
        self.trace = []
        self.session["version"] = 1
        self.provenance_installed = True

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        self.trace.append(q)
        row, rows = None, []
        if q.startswith("SELECT count(*) AS count"):
            if "FROM rag_actual_d_private_provenance" in q:
                row = {"count":int(self.bridge is not None and self.bridge["user_id"]==params[0])}
            else:
                row = {"count":sum(r["signed_proof"]["payload"]["format"]==params[0] and
                    r["signed_proof"]["payload"]["prepared"].get("actual_d",{}).get("draft",{}).get("user_id")==params[1]
                    for r in self.evidence.values())}
        elif q.startswith("SELECT id,issued_at,expires_at,revoked_at,count(*) OVER"):
            rows = [dict(id=r["id"],issued_at=r["issued_at"],expires_at=r["expires_at"],revoked_at=r["revoked_at"],total_count=1)
                for r in self.evidence.values() if r["private_user_id"]==params[0]]
        elif q.startswith("SELECT private_evidence_id AS id,created_at,count(*) OVER"):
            rows = ([dict(id=self.bridge["private_evidence_id"],created_at=prior.NOW,total_count=1)] if self.bridge else [])
        elif "to_regclass('public.rag_actual_d_private_provenance')" in q:
            row = {"present":self.provenance_installed,"installed":self.provenance_installed}
        elif "to_regclass('public.rag_assessment_source_evidence')" in q:
            row = {"present":True}
        elif q.startswith("SELECT e.id AS public_evidence_id"):
            rows = ([dict(public_evidence_id=self.public.evidence_id,corpus_id=self.cid,generation=self.generation)]
                    if self.carrier_enabled and self.evidence[self.public.evidence_id]["revoked_at"] is None else [])
        elif "FROM rag_assessment_source_evidence" in q:
            if "WHERE e.id=%s" in q or "WHERE id=%s" in q:
                row = self.evidence.get(params[0])
            elif "WHERE demand_hash=%s" in q:
                rows = [r for r in self.evidence.values() if (r["demand_hash"],r["policy_id"],r["policy_generation"],r["root_id"]) == params
                        and r["revoked_at"] is None and r["issued_at"]<=self.now<r["expires_at"]]
            elif "WHERE source_handle=%s AND document_handle=%s" in q:
                row = next((r for r in self.evidence.values() if (r["source_handle"],r["document_handle"]) == params),None)
            else:
                column = "execution_handle" if "WHERE execution_handle=" in q else "claim_handle"
                row = next((r for r in self.evidence.values() if r[column] == params[0]),None)
                if "signed_proof->'payload'->>'format'=%s" in q and row and row["private_user_id"] is None:
                    row = None
        elif q.startswith("SELECT * FROM rag_actual_d_private_provenance"):
            row = self.bridge
        elif q.startswith("INSERT INTO rag_actual_d_private_provenance"):
            keys = ("private_evidence_id","user_id","epoch","draft_id","node_id","goal_hash","target_id","public_evidence_id",
                    "corpus_id","generation","document_id","document_hash","private_proof_hash","public_proof_hash","chunks_json")
            self.bridge = dict(zip(keys, (*params[:-1],params[-1].obj), strict=True))
        elif "JOIN rag_corpus_validation_receipts r" in q:
            rows = [dict(content=c["content"],chunk_hash=c["chunk_hash"],facets_json=c["facets_json"],
                subject_id="route.python",subject_version="1.0",state="published",summary_hash=self.corpus["summary_hash"],
                receipt_summary=self.corpus["summary_hash"],document_hash=self.public.prepared.document_hash) for c in self.chunks]
        elif "FROM grounding_corpus_versions" in q:
            row = self.corpus
        elif "FROM grounding_active_corpora" in q:
            row = dict(corpus_version_id=self.cid,subject_id="route.python",generation=self.generation,activation_event_id=self.event_id)
        elif "FROM grounding_corpus_chunks" in q:
            if q.startswith("SELECT chunk_id,document_id,chunk_hash"):
                rows = [{k:c[k] for k in ("chunk_id","document_id","chunk_hash")} for c in self.chunks]
            elif "JOIN rag_corpus_validation_receipts" in q:
                rows = [dict(content=c["content"],chunk_hash=c["chunk_hash"],facets_json=c["facets_json"],
                    subject_id="route.python",subject_version="1.0",state="published",summary_hash=self.corpus["summary_hash"],
                    receipt_summary=self.corpus["summary_hash"],document_hash=self.public.prepared.document_hash) for c in self.chunks]
            else:
                rows = [dict(c,active_generation=self.generation) for c in self.chunks]
        elif "FROM grounding_corpus_source_snapshots" in q:
            rows = self.source_rows
        elif "FROM grounding_corpus_documents" in q:
            rows = self.document_rows
        elif "FROM rag_corpus_validation_receipts" in q:
            row = self.c_receipt
        elif q.startswith("SELECT handle,selection_digest"):
            stored = self.saved_selections.get(params[1])
            row = stored
        elif q.startswith("SELECT snapshot_json, idempotency_key"):
            rows = [r for key,r in self.saved_selections.items() if key==params[1]]
        elif q.startswith("INSERT INTO rag_material_selections"):
            self.saved_selections[params[11]] = dict(handle=params[0],snapshot_json=json.loads(params[10]),selection_digest=params[9])
        elif q.startswith("SELECT snapshot_json,selection_digest") and "FROM rag_material_selections" in q:
            row = next((r for r in self.saved_selections.values() if r["handle"]==params[0]),None)
            if row is None:
                row = dict(snapshot_json=self.selection.model_dump(mode="json"),selection_digest=self.selection.selection_digest)
        elif q.startswith("SELECT binding_json") and "FROM rag_plan_material_bindings" in q:
            rows = self.bindings
        elif q.startswith("INSERT INTO rag_plan_material_bindings"):
            self.bindings.append(dict(id=uuid4(),node_id=params[5],goal_hash=params[6],purpose=params[7],binding_digest=params[8],
                binding_json=json.loads(params[9]),idempotency_key=params[10],selection_handle=params[0],selection_digest=params[1]))
        elif q.startswith("SELECT id FROM rag_plan_material_bindings"):
            row = self.bindings[0] if self.bindings else None
        elif "FROM rag_plan_material_bindings b" in q:
            b = self.bindings[0]
            sel = next(r for r in self.saved_selections.values() if r["handle"]==b["binding_json"]["selection_handle"])
            row = dict(b,snapshot_json=sel["snapshot_json"],selection_digest=sel["selection_digest"],draft_version=self.scope.draft_version,
                content_hash=self.scope.content_hash,source_run_id=self.scope.source_run_id,source_input_revision=self.scope.source_input_revision,
                conversation_id=self.scope.conversation_id)
        elif "FROM tutor_track_plan_nodes n" in q:
            row = self.confirmed_node
        elif "FROM tutor_learning_plan_sessions AS sessions" in q or "FROM tutor_learning_plan_sessions sessions" in q:
            row = {**self.parent,**self.session}
        elif q.startswith("UPDATE tutor_learning_plan_sessions SET status = 'confirmed'"):
            assert (params[2],params[3],params[4],params[5]) == (self.scope.session_id,self.scope.user_id,self.session["version"],self.scope.draft_id)
            assert self.session["status"]=="draft_ready"
            self.session.update(status="confirmed",confirmed_track_id=params[0],confirmed_at=params[1],version=self.session["version"]+1)
            row = self.session
        elif "pg_advisory_xact_lock" in q or "FROM tutor_api_idempotency_records" in q or q.startswith("INSERT INTO tutor_api_idempotency_records"):
            row = None
        elif "clock_timestamp()" in q:
            row = {"now":self.now}
        else:
            return super().execute(sql,params)
        return SimpleNamespace(fetchone=lambda:row,fetchall=lambda:rows)


def setup(monkeypatch, *, teaching_baseline=False):
    conn = BridgeProtocol()
    if teaching_baseline:
        # Existing D teaching acceptance is outside private bridge authority.
        # Preserve ALL original draft nodes and requirements, not a fake one-node course.
        entries = tuple(MaterialSelectionEntry.model_validate_json(json.dumps(dict(
            node_id=r.node_id,goal_hash=r.goal_hash,purpose=r.demand.purpose,status="ready",
            covered_facets=list(r.demand.scope.facets),evidence=[coordinate(r.demand).model_dump(mode="json")])))
            for r in conn.selection.requirements)
        conn.selection = _selection(handle=conn.selection.handle,draft=conn.scope,requirements=conn.selection.requirements,entries=entries)
    repo = prior.repository(monkeypatch,conn)
    private_q = prior.prepare(repo,conn)
    private_signed, _, key = prior.sign(repo,private_q)
    public_q = repo.prepare(capture_id=private_q.capture_id,document_handle="document.public-fixture",
        demand=public_course_demand(conn.target_id),profile_id=storage_profile_id(private_q))
    runner = prior.ProtocolStub(prior.public_course_source_request(conn.target_id)[1])
    public_signed = sign_source_assessment(run_source_assessment(public_q,runner=runner,run_id=uuid4()),runner=runner,
        service_key_id="service.test",private_key=key,now=prior.NOW)
    conn.private, conn.public = private_signed.payload, public_signed.payload
    conn.evidence = {s.payload.evidence_id:evidence_row(s) for s in (private_signed,public_signed)}
    conn.source_rows = [dict(source_id=public_q.source_handle,source_hash=public_q.document_hash)]
    conn.document_rows = [dict(document_id=public_q.document_handle,source_id=public_q.source_handle,document_hash=public_q.document_hash)]
    for i, text in enumerate(repo.excerpts(conn.public,conn.captures["select"])):
        conn.chunks.append(dict(chunk_id="fixture.chunk."+str(i),document_id=public_q.document_handle,source_id=public_q.source_handle,
            content=text,chunk_hash=hashlib.sha256(text.encode()).hexdigest(),facets_json=list(public_q.demand.scope.facets),
            document_hash=public_q.document_hash,source_review_id=conn.public.review_id,review_id=conn.public.review_id,
            policy_id=public_q.policy_id,policy_generation=public_q.policy_generation,review_receipt_hash=source_proof_hash(public_signed),
            receipt_handle=conn.public.admission_handle))
    validation, coverage = {"valid":True}, {"covered":1}
    admissions, facets = "c"*64,"d"*64
    source_hash = _hash(conn.source_rows)
    content_hash = _hash([conn.document_rows,[{k:c[k] for k in ("chunk_id","document_id","chunk_hash")} for c in conn.chunks]])
    summary = _hash([str(conn.cid),"e"*64,source_hash,content_hash,validation,coverage,"fixture-fts-v1","fixture-coverage-v1"])
    conn.corpus = dict(id=conn.cid,subject_id="route.python",subject_version="1.0",registry_digest="e"*64,state="published",generation=1,
        source_set_hash=source_hash,content_hash=content_hash,summary_hash=summary,retrieval_policy_version="fixture-fts-v1",
        coverage_policy_version="fixture-coverage-v1",coverage_summary_json=coverage,validation_summary_json=validation)
    conn.c_receipt = dict(summary_hash=summary,admission_digest=admissions,coverage_digest=facets,review_policy_generation=1,partial_coverage=False)
    # An already-accepted PUBLIC C audit boundary, not a private bridge checker.
    monkeypatch.setattr(CorpusGovernance,"_audit",lambda self,cid,**kw:(validation,coverage,admissions,facets,1,False))
    return conn, repo


def preparation_owner(conn,repo,monkeypatch):
    teaching = object.__new__(EvidenceSelection)
    teaching.conn, teaching.selections = conn, PostgresMaterialBindingRepository(conn)
    monkeypatch.setattr(teaching,"require_transaction",repo.require_transaction)
    return AssessmentCourseSelectionProducer(conn,receipts=repo,teaching_authority=teaching,enabled=True)


def test_real_factory_canonical_current_owner_and_replay(installed_protocol,monkeypatch):
    conn, repo = setup(monkeypatch)
    owner = preparation_owner(conn,repo,monkeypatch)
    authority = owner._assessment()
    before = copy.deepcopy(conn.evidence[conn.public.evidence_id])
    q = conn.private.prepared
    kwargs = dict(receipts=repo,authority=authority,claim_receipt_id=conn.private.claim_handle,draft=conn.scope,
                  node_id=q.actual_d.node_id,goal_hash=q.actual_d.goal_hash,enabled=True)
    _,formal = compose_assessment_authority(conn,receipts=repo,enabled=True)
    with pytest.raises(SourceAssessmentDenied,match="PRIVATE_PHASE_DENIED"):
        create_assessment_material(conn,**(kwargs|{"authority":formal}))
    material = create_assessment_preparation_material(conn,owner=owner,**kwargs)
    assert material.binding.evidence[0].binding.document_handle == conn.public.prepared.document_handle
    assert material.exact_claims[0].claim_receipt_id == conn.private.claim_handle
    assert material.binding.draft.user_id == conn.scope.user_id and conn.bridge["epoch"] == 1
    assert create_assessment_preparation_material(conn,owner=owner,**kwargs) == material
    assert authority._claims.resolve(conn.private.claim_handle).document_handle == conn.public.prepared.document_handle
    assert conn.evidence[conn.public.evidence_id] == before
    assert sum(q.startswith("INSERT INTO rag_actual_d_private_provenance") for q in conn.trace)==1
    counts = actual_d_private_counts(conn,UUID(conn.scope.user_id))
    assert set(counts.values())=={1} and len(counts)==5
    assert set(actual_d_private_counts(conn,uuid4()).values())=={0}
    exported = export_actual_d_private(conn,UUID(conn.scope.user_id))
    assert set(exported["provenance"]["items"][0])=={"id","status","created_at"}
    assert "private_proof_hash" not in json.dumps(exported) and "signed_proof" not in json.dumps(exported)
    conn.session["status"] = "confirmed"
    with pytest.raises(SourceAssessmentDenied,match="PRIVATE_PHASE_DENIED"):
        create_assessment_preparation_material(conn,owner=owner,**kwargs)
    assert create_assessment_material(conn,**(kwargs|{"authority":formal})) == material


def test_original_selection_freeze_confirmed_reader_and_496_projection(installed_protocol,monkeypatch):
    conn,repo = setup(monkeypatch,teaching_baseline=True)
    _,authority = compose_assessment_authority(conn,receipts=repo,enabled=True)
    teaching = object.__new__(EvidenceSelection)
    teaching.conn, teaching.selections = conn, PostgresMaterialBindingRepository(conn)
    # Bounded pre-existing teaching fixture only. No private claim/factory/current
    # callback is replaced; they independently reconstruct both signed proofs.
    monkeypatch.setattr(teaching,"require_transaction",repo.require_transaction)

    def accepted_teaching(db,selection):
        assert db is conn and {r.node_id for r in selection.requirements} == {"course.base","course.target"}
        assert all(r.demand.purpose=="main_teaching" for r in selection.requirements)
        return CurrentMaterialAuthorizationReceipt(kind="selection",object_digest=selection.selection_digest,draft=selection.draft,
            purposes=("main_teaching",),authorization_digest="6"*64,checked_at=prior.NOW)

    monkeypatch.setattr(teaching,"authorize_selection",accepted_teaching)
    producer = AssessmentCourseSelectionProducer(conn,receipts=repo,teaching_authority=teaching,enabled=True)
    result = producer.produce(user_id=UUID(conn.scope.user_id),session_id=UUID(conn.scope.session_id),draft_id=UUID(conn.scope.draft_id),
        base_selection_handle=conn.selection.handle,claim_handles_by_node={"course.target":(conn.private.claim_handle,)},
        operation_key="fixture.private-bridge")
    assert result.status=="stored_internal" and len(result.assessment_bindings)==1
    assert len(result.selection.requirements)==3 and len(conn.bindings)==1
    # ORIGINAL confirm service + original repository CAS, not manually setting
    # status to evade the bootstrap order. Track-storage/UI projection are fixed
    # offline boundaries; no material/claim/current authorization is substituted.
    service = LearningPlanSessionService(conn)
    monkeypatch.setattr(service._track_repository,"create_track",lambda **kw:str(conn.track_id))
    monkeypatch.setattr(service._track_service,"read_track",lambda **kw:{"track":{"track_id":str(conn.track_id)}})
    monkeypatch.setattr(service._facts,"public_projection",lambda **kw:{})
    confirmed = service.confirm_session(user_id=conn.scope.user_id,session_id=conn.scope.session_id,
        expected_session_version=1,draft_id=conn.scope.draft_id,draft_version=conn.scope.draft_version,
        content_hash=conn.scope.content_hash,idempotency_key="fixture.private-confirm")
    assert confirmed["session"]["status"]=="confirmed" and conn.session["version"]==2
    artifact = draft_artifact_from_row(conn.parent)
    n = next(n for m in conn.parent["plan_json"]["modules"] for n in m["nodes"] if n["knowledge_key"]=="course.target")
    nid = uuid4()
    conn.confirmed_node = dict(n,id=nid,language_id="python",plan_content_hash=artifact.plan.content_hash,
        plan_json=conn.parent["plan_json"],prerequisite_keys_json=n["prerequisite_keys"],required_capabilities_json=n["required_capabilities"],
        catalog_knowledge_key=n.get("catalog_knowledge_key"))
    reader = ConfirmedAssessmentCourseReader(conn,receipts=repo,authority=authority)
    course = reader.read(user_id=UUID(conn.scope.user_id),epoch=1,track_id=conn.track_id,revision_id=conn.revision_id,
        node_id=nid,session_id=UUID(conn.scope.session_id),assessment_binding_id=result.assessment_bindings[0].binding_id)
    current = reader.authorize(course,target_id=conn.target_id)
    assert current.covered_facets == ("fundamentals",)
    mapping_hash = _mapping_hash(course.node,profile(conn.target))
    scopes = {slot:FrozenPrivateScope(uuid4(),canonical_hash(slot),canonical_hash("original-P3-fixture"))
              for slot in ("practice","assessment","remediation")}
    pack = _pack(course.node,profile(conn.target),mapping_hash,scopes)
    assert pack.course_mapping_hash==mapping_hash and len(pack.demands)==3
    assert all(d.demand.scope.knowledge_key=="course.target" for d in pack.demands)


@pytest.mark.parametrize("fault", ["crossowner","revoked","private_revoked","generation","hash","spans","epoch","purpose","expiry","absent504","off","input_revision","phase"])
def test_private_bridge_negatives(installed_protocol,monkeypatch,fault):
    conn,repo = setup(monkeypatch)
    owner = preparation_owner(conn,repo,monkeypatch)
    authority = owner._assessment()
    q = conn.private.prepared
    kwargs = dict(receipts=repo,authority=authority,claim_receipt_id=conn.private.claim_handle,draft=conn.scope,
                  node_id=q.actual_d.node_id,goal_hash=q.actual_d.goal_hash,enabled=True)
    if fault == "crossowner":
        kwargs["draft"] = conn.scope.model_copy(update={"user_id":str(uuid4())})
    elif fault == "revoked":
        conn.evidence[conn.public.evidence_id]["revoked_at"] = prior.NOW
    elif fault == "private_revoked":
        conn.evidence[conn.private.evidence_id]["revoked_at"] = prior.NOW
    elif fault == "hash":
        conn.chunks[0]["chunk_hash"] = "0"*64
    elif fault == "spans":
        conn.chunks.pop()
    elif fault == "purpose":
        conn.carrier_enabled = False  # no PUBLIC assessment-authorized carrier
    elif fault == "epoch":
        conn.epoch = 2
    elif fault == "expiry":
        conn.now = conn.private.expires_at
    elif fault == "generation":
        create_assessment_preparation_material(conn,owner=owner,**kwargs)
        conn.generation = 2
    elif fault == "absent504":
        conn.provenance_installed = False
    elif fault == "off":
        repo.actual_d_private_provenance_enabled = False
    elif fault == "input_revision":
        conn.run["input_revision"] += 1
    elif fault == "phase":
        conn.session["status"] = "confirmed"
    with pytest.raises((SourceAssessmentDenied,ValueError)):
        create_assessment_preparation_material(conn,owner=owner,**kwargs)


def test_504_sql_private_classification_and_original_tail_order():
    from pathlib import Path

    schema = Path(__file__).parents[2]/"app"/"db"/"schema"
    ddl = (schema/"504_rag_actual_d_private_provenance.sql").read_text(encoding="utf8")
    tail = (schema/"503_rag_actual_d_private_lifecycle.sql").read_text(encoding="utf8")
    assert "FOREIGN KEY(private_evidence_id,user_id,epoch)" in ddl
    assert "REFERENCES grounding_corpus_documents(corpus_version_id,document_id)" in ddl
    assert "carrier.private_user_id IS NOT NULL" in ddl and "original->'demand'->>'purpose'" in ddl
    assert "rag_actual_d_private_delete_allowed(OLD.private_evidence_id)" in ddl
    assert "private provenance exact chunks mismatch" in ddl and "private provenance final source or generation stale" in ddl
    assert "UPDATE rag_assessment_source_evidence" not in ddl and "INSERT INTO grounding_" not in ddl
    assert tail.index("DELETE FROM public.rag_actual_d_private_provenance") < tail.index("DELETE FROM rag_source_claim_receipts")
