"""Offline real bounded-adapter protocol; no HTTP/PG or production authority."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.grounding.assessment_course_adapter import ConfirmedAssessmentCourseReader
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository, PostgresAssessmentClaimResolver
from app.services.grounding.current_authorization import CurrentAuthorization
from app.services.learning.item_bank.native_publication import NativePublishedItemQuery
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository, ReservationResult
from app.services.learning.item_supply.finite_course_mapping import FiniteCourseMappingOwner
from app.services.learning.item_supply.native_relation_review import NativeRelationReviewProducer, ROLES, relation_prompt
from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner, reconstruct_native_content
from app.services.learning.item_supply.finite_targets.python_kc import _spec, _truth
from app.services.learning.item_supply.type_evidence import relationship_reason
from app.services.learning.item_supply.pack_contracts import CompleteExposureV2
from app.services.learning.item_bank.contracts import canonical_hash
from tests.learning.test_item_supply_finite_candidate_validation import _context, _source
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
from app.services.learning.item_supply.review_provider import BoundedOpenAIReviewClient
from app.services.llm.llm_client import LLMJsonResponse
from tests.learning.test_item_supply_native_type_evidence import mapped_receipt, original_row


class OfflineRelationConnection:
    autocommit = False
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.prepared, self.calls, self.settlements = {}, [], []
        self.active = True
    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == TransactionStatus.IDLE
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        finally:
            self.info.transaction_status = TransactionStatus.IDLE
    def execute(self,sql,params=()):
        self.calls.append(sql)
        if "profile_json->'profile_key'" in sql:
            row = {"key_json":{"provider":"openai","model_version":"offline-v1"}}
        elif sql.startswith("INSERT INTO tutor_item_supply_native_relation_preparations"):
            self.prepared[params[0]] = params
            row = None
        elif sql.startswith("SELECT id FROM tutor_item_supply_native_relation_preparations"):
            row = {"id":params[0]} if params[0] in self.prepared else None
        elif "runtime_settlements" in sql:
            row = {"same_transaction":False,"usage_state":"unknown"}
        else:
            row = None
        return SimpleNamespace(fetchone=lambda:row)


def setup(monkeypatch):
    row, issuer, args, _ = original_row(monkeypatch)
    left = reconstruct_native_content(row)
    def alternate_candidate(target):
        spec, materials = _context(target,slot=3)
        question, truth = _spec("counterexample",False), _truth("counterexample",False)
        accepted = {o.label:(o.rhs,o.saved,o.observation,o.reason)==truth for o in question.options}
        options = spec.public_template.content.options
        private = dict(type="knowledge_check",accepted_answers=[o.option_id for o in options if accepted[o.label]],
            answer_explanation_markdown=question.explanation,tests=[dict(id="option."+o.option_id,
                case_type="visible" if i==0 else "hidden",input_json={"answer":o.option_id},
                expected_output_json={"accepted":accepted[o.label]},order_index=i,is_critical=True) for i,o in enumerate(options)],
            score_policy=dict(kind="static_exact",policy_version="static_exact_v1",threshold=1.0))
        return spec,materials,_source(spec,private)
    with monkeypatch.context() as scoped:
        scoped.setattr("tests.learning.test_item_supply_shared_admission_facts._candidate",alternate_candidate)
        second, _, _, _ = original_row(scoped)
    right = reconstruct_native_content(second)
    mapping = mapped_receipt(left)
    conn = OfflineRelationConnection()
    # Concrete classes, DB/C IO deliberately mocked. This is NOT a live grant.
    receipts = object.__new__(AssessmentReceiptRepository)
    receipts.conn = conn
    claims = PostgresAssessmentClaimResolver(receipts)
    current = CurrentAuthorization(conn,governance=SimpleNamespace(conn=conn,
        source_reviews=SimpleNamespace(assessment_receipts=receipts)),claim_resolver=claims)
    authority = RagSourceAuthority(current,claims)
    reader = ConfirmedAssessmentCourseReader(conn,receipts=receipts,authority=authority)
    query = NativePublishedItemQuery(conn,enabled=True)
    mapper = FiniteCourseMappingOwner(conn,current_authority=reader,profiles={},runtime_owner=query,enabled=True)
    settings = Settings(learning_item_supply_enabled=True,learning_item_network_enabled=True,
        learning_item_v2_admission_enabled=True,llm_type="openai",openai_api_key="OFFLINE-NOT-A-KEY",
        openai_base_url="http://127.0.0.1:1",openai_model="offline-model")
    owner = NativeTypeEvidenceOwner(conn,settings,user_id=mapping.frozen_node.user_id,epoch=1,
        query=query,source_authority=authority,mapping_owner=mapper,enabled=True)
    def guard():
        if not conn.active:
            raise NativeTypeEvidencePending("native_old_epoch")
        return datetime.now(UTC),99
    monkeypatch.setattr(owner,"_guard",guard)
    monkeypatch.setattr(owner,"resolve_mapping",lambda rid:mapping)
    monkeypatch.setattr(owner,"resolve_content",lambda v,current=True: left if v==left.content.version_id else right)
    monkeypatch.setattr(owner,"source_deadline",lambda c:datetime.now(UTC)+timedelta(days=3))
    identities = {role:ProviderIdentityV2(identity="native.relation."+role,provider="openai",
        model="offline-model",model_version="offline-v1") for role in ROLES}
    producer = NativeRelationReviewProducer(owner,identities=identities,
        trusted_model_bindings={("openai","offline-v1"):"offline-model"},enabled=True)
    monkeypatch.setattr(ItemSupplyBudgetRepository,"_job_meta",lambda *a,**k:{"root_id":left.facts.root_id,"provider_key":"openai"})
    monkeypatch.setattr(ItemSupplyBudgetRepository,"reserve",lambda *a,**k:ReservationResult(True,"RESERVED",uuid4()))
    monkeypatch.setattr(ItemSupplyBudgetRepository,"settle",lambda *a,**k:conn.settlements.append(k))
    prepared = producer.prepare(mapping_receipt_id=mapping.receipt_id,anchor_version_id=left.content.version_id,
        lease=left.publication.lease,pairs=((left.content.version_id,right.content.version_id),))
    return producer,prepared,conn


def install_response(monkeypatch,conn,*,verdict="conflict",wrong_reference=False,fail=False):
    seen = []
    def complete(self,messages,**kwargs):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        assert self.request_attempt_bound == 1 and kwargs["capture_provider_body"] is False
        seen.append(messages)
        if fail:
            raise ValueError("OFFLINE transport failure")
        payload = json.loads(messages[1]["content"])
        hashes = {i["version_id"]:i["field_hashes"] for i in payload["items"]}
        votes=[]
        for pair in payload["pairs"]:
            refs = [dict(version_id=pair[k],pointer="/verified_answer",value_hash=hashes[pair[k]]["/verified_answer"])
                for k in ("left_version_id","right_version_id")]
            if wrong_reference:
                refs[0]["value_hash"]="0"*64
            votes.append(dict(binding_hash=pair["binding_hash"],conclusion=verdict,
                rationale="These exact verified propositions expose the same decisive answer, not merely a common method.",references=refs))
        return LLMJsonResponse(content={"judgments":votes},model="offline-model",usage=None)
    monkeypatch.setattr(BoundedOpenAIReviewClient,"complete_json",complete)
    return seen


def test_original_root_four_peer_blind_calls_and_honest_unknown(monkeypatch):
    producer,p,conn=setup(monkeypatch)
    anchor=next(c for c in p.contents if c.content.version_id==p.anchor_version_id)
    assert p.resources.requests==4 and p.root_id==anchor.facts.root_id
    assert p.anchor_version_id in {c.content.version_id for c in p.contents}
    conn.info.transaction_status=TransactionStatus.IDLE
    seen=install_response(monkeypatch,conn)
    run=producer.run(p)
    assert len(seen)==4 and len(run.reports)==4
    assert len({r.actor_id for r in run.reports})==4
    assert len({r.run.run_id for r in run.reports})==4
    assert all(r.run.provider_identity.model=="offline-model" for r in run.reports)
    assert all(r.judgments[0].conclusion=="conflict" for r in run.reports)
    assert all("reports" not in json.loads(m[1]["content"]) for m in seen)
    assert all(r.run.input_tokens is None and r.run.output_tokens is None for r in run.reports)
    producer.settle(p,run)
    assert conn.settlements[0]["usage_state"]=="unknown" and conn.settlements[0]["actual"] is None
    assert conn.settlements[0]["cost_amount"] is None
    with pytest.raises(NativeTypeEvidencePending,match="batch_replay"):
        producer.run(p)


@pytest.mark.parametrize("wrong_reference,fail",[(True,False),(False,True)])
def test_unbound_provider_output_and_transport_failure_remain_pending(monkeypatch,wrong_reference,fail):
    producer,p,conn=setup(monkeypatch)
    conn.info.transaction_status=TransactionStatus.IDLE
    install_response(monkeypatch,conn,wrong_reference=wrong_reference,fail=fail)
    run=producer.run(p)
    assert run.safe_reason=="native_relation_provider_or_evidence_pending" and not run.reports
    producer.settle(p,run)
    assert conn.settlements[0]["usage_state"]=="unknown"


def test_wrong_prepared_json_clone_forged_result_and_busy_transaction_deny(monkeypatch):
    producer,p,conn=setup(monkeypatch)
    with pytest.raises(NativeTypeEvidencePending,match="prepared_seal"):
        producer.run(replace(p))
    with pytest.raises(NativeTypeEvidencePending,match="idle_io"):
        producer.run(p)
    conn.info.transaction_status=TransactionStatus.IDLE
    install_response(monkeypatch,conn)
    run=producer.run(p)
    with pytest.raises(NativeTypeEvidencePending,match="actual_provider_run"):
        producer.settle(p,replace(run))
    # Lost epoch blocks new effects, but still retains original shared accounting.
    conn.active=False
    producer.settle(p,run)
    with pytest.raises(NativeTypeEvidencePending,match="old_epoch"):
        producer.persist(p,run)


def test_missing_anchor_wrong_profile_and_reviewer_identity_cannot_get_new_wallet(monkeypatch):
    producer,p,conn=setup(monkeypatch)
    with pytest.raises(NativeTypeEvidencePending,match="original_published_anchor"):
        producer.prepare(mapping_receipt_id=p.mapping_receipt_id,anchor_version_id=uuid4(),lease=p.lease,pairs=p.pairs)
    wrong=p.lease.model_copy(update={"lease_owner":"not.original"})
    with pytest.raises(NativeTypeEvidencePending,match="original_published_anchor"):
        producer.prepare(mapping_receipt_id=p.mapping_receipt_id,anchor_version_id=p.anchor_version_id,lease=wrong,pairs=p.pairs)
    producer.bindings.clear()
    with pytest.raises(NativeTypeEvidencePending,match="provider_profile"):
        producer._client(p.lease,"technical")
    with pytest.raises(NativeTypeEvidencePending,match="four_independent"):
        NativeRelationReviewProducer(producer.owner,identities={"technical":producer.identities["technical"]},trusted_model_bindings={})


def test_prompt_judges_answer_exposure_not_general_method_transfer():
    prompt=relation_prompt("technical",{})[0]["content"]
    assert "Shared general methods are intended learning transfer" in prompt
    assert "Different family/seed labels never establish nonredundancy" in prompt
    assert "twelve-direction" in prompt and "BOTH actual items" in prompt


def test_new_evidence_outlives_producer_lease_without_authorizing_old_io(monkeypatch):
    producer,p,conn=setup(monkeypatch)
    assert p.evidence_valid_until > p.valid_until
    assert p.evidence_valid_until <= datetime.now(UTC)+timedelta(days=7)
    conn.info.transaction_status=TransactionStatus.IDLE
    install_response(monkeypatch,conn,verdict="nonredundant")
    run=producer.run(p)
    assert all(r.valid_until==p.evidence_valid_until for r in run.reports)
    # New owner reads durable reviews as history, never reconstructs an old run
    # capability or asks whether its completed producer is still leased.
    batch = dict(id=p.preparation_id,request_hash=p.payload["request_hash"],
        checked_at=datetime.now(UTC),valid_until=p.evidence_valid_until,
        payload_json={"pairs":p.payload["pairs"],"reports":[r.model_dump(mode="json") for r in run.reports]})
    batch["payload_hash"]=canonical_hash(batch["payload_json"])
    class HistoryConnection:
        def execute(self,*args):
            return SimpleNamespace(fetchone=lambda:batch)
    history_owner=SimpleNamespace(conn=HistoryConnection(),user_id=producer.owner.user_id,epoch=producer.owner.epoch)
    mapping=producer.owner.resolve_mapping(p.mapping_receipt_id)
    later=p.valid_until+timedelta(seconds=1)
    exposure=CompleteExposureV2(learner_id=producer.owner.user_id,epoch=1,collector_version="offline-current-v2",
        watermark=2,completeness_receipt_hash=canonical_hash("fresh exposure"),observed_at=later,
        valid_until=later+timedelta(seconds=30),records=())
    relationships=NativeTypeEvidenceOwner._relations(history_owner,(p.preparation_id,),mapping,
        {c.content.version_id:c for c in p.contents},exposure,later)
    assert len(relationships)==1 and relationship_reason(relationships[0],now=later) is None
    newer=exposure.model_copy(update={"watermark":3,"completeness_receipt_hash":canonical_hash("new fresh exposure"),
        "observed_at":later+timedelta(seconds=1),"valid_until":later+timedelta(seconds=31)})
    reused=NativeTypeEvidenceOwner._relations(history_owner,(p.preparation_id,),mapping,
        {c.content.version_id:c for c in p.contents},newer,later+timedelta(seconds=1))[0]
    stable=relationships[0]
    assert reused.receipt_id==stable.receipt_id==p.preparation_id
    assert reused.receipt_hash==stable.receipt_hash==batch["payload_hash"]
    assert (reused.checked_at,reused.valid_until,reused.reviews)==(stable.checked_at,stable.valid_until,stable.reviews)
    assert reused.exposure_watermark!=stable.exposure_watermark and reused.exposure_receipt_hash!=stable.exposure_receipt_hash
    assert reused.binding_hash==stable.binding_hash and relationship_reason(reused,now=later+timedelta(seconds=1)) is None
    # The ORIGINAL P3 fence still blocks old provider/commit operations.
    monkeypatch.setattr(producer.owner,"_guard",lambda:(later,99))
    with pytest.raises(NativeTypeEvidencePending,match="original_lease_current"):
        producer._fence(p)
    with pytest.raises(NativeTypeEvidencePending,match="original_lease_current"):
        producer.persist(p,run)
    with pytest.raises(NativeTypeEvidencePending,match="relation_current_bound"):
        NativeTypeEvidenceOwner._relations(history_owner,(p.preparation_id,),mapping,
            {c.content.version_id:c for c in p.contents},exposure,p.evidence_valid_until)


def test_source_and_seven_day_caps_are_frozen_not_renewed_by_projection(monkeypatch):
    producer,p,conn=setup(monkeypatch)
    # Configuration mutation cannot enlarge the original in-process seal.
    object.__setattr__(p,"evidence_valid_until",p.evidence_valid_until+timedelta(days=1))
    with pytest.raises(NativeTypeEvidencePending,match="prepared_seal"):
        producer._verify_prepared(p)


def test_first_issue_deadline_respects_short_source_and_seven_day_maximum(monkeypatch):
    producer,p,conn=setup(monkeypatch)
    start=datetime.now(UTC)
    monkeypatch.setattr(producer.owner,"source_deadline",lambda c:start+timedelta(days=14))
    seven=producer.prepare(mapping_receipt_id=p.mapping_receipt_id,anchor_version_id=p.anchor_version_id,
        lease=p.lease,pairs=p.pairs)
    assert start+timedelta(days=6) < seven.evidence_valid_until <= datetime.now(UTC)+timedelta(days=7)
    assert seven.root_id==p.root_id and seven.lease==p.lease
    short_deadline=datetime.now(UTC)+timedelta(minutes=2)
    monkeypatch.setattr(producer.owner,"source_deadline",lambda c:short_deadline)
    short=producer.prepare(mapping_receipt_id=p.mapping_receipt_id,anchor_version_id=p.anchor_version_id,
        lease=p.lease,pairs=p.pairs)
    assert short.evidence_valid_until==short_deadline
    assert short.valid_until<=short_deadline and short.lease.expires_at==p.lease.expires_at
