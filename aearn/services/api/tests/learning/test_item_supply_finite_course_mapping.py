"""Three focused OFFLINE cases. No live D/source/PG/pack-readiness evidence."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.grounding.assessment_course_adapter import ConfirmedAssessmentCourseReader
from app.services.grounding.autonomous.assessment_contracts import ClaimEvidenceReceipt, ExecutionScope
from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, RagBudgetDelegation, RagEvidenceBinding, SubjectScope
from app.services.grounding.autonomous.assessment_receipt_repository import (
    AssessmentReceiptRepository, PostgresAssessmentClaimResolver,
)
from app.services.grounding.current_authorization import CurrentAuthorization, EvidenceDenied
from app.services.grounding.material_binding_repository import goal_hash_for_node
from app.services.learning.contracts import (
    LearningPlan, LearningPlanModule, LearningPlanNode, canonical_plan_payload,
)
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_course_mapping import (
    FiniteCourseMappingOwner, _mapping_hash, _pack, finite_node_description,
)
from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseProfileV1, FrozenCourseNodeV1
from app.services.learning.item_supply.finite_course_targets import finite_course_targets
from app.services.learning.item_supply.finite_targets.python_kc import PYTHON_KC_SCORER_VERSION
from app.services.learning.item_supply.pack_builder import _validate_request
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.sandbox.python_state_scorer import PYTHON_STATE_SCORER_VERSION
from app.services.learning.item_supply.storage import FrozenPrivateScope
from app.services.learning.plan_drafting import CompactPlanProfile, LearningPlanDraftArtifact
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION


def profile(target):
    scorer = {"python-state-update-v1":PYTHON_STATE_SCORER_VERSION,
        "sqlite-predicate-order-v1":GATE_PASS_POLICY_VERSION,"python-kc-binding-v1":PYTHON_KC_SCORER_VERSION}[target.target_id]
    runtime = canonical_hash({"runtime":"static-exact-v1","scorer_version":scorer,
        "assessment_contract":target.target_id}) if target.assessment.runtime_profile_id is None else canonical_hash("OFFLINE-lock")
    return FiniteCourseProfileV1(profile_id="offline."+target.target_id,target_id=target.target_id,
        course_version="1.0",subject_version="1.0",runtime_profile_hash=runtime,scorer_version=scorer,
        assistance_policy_hash=canonical_hash("OFFLINE-policy"),policy_version="offline-policy-v1",
        public_spec_version="finite-public-spec-v1")


def frozen(target):
    fields = dict(knowledge_key="actual.fixture.step",title="Frozen learner node",
        description=finite_node_description(target.target_id),is_core=True,prerequisite_keys=[],
        required_capabilities=list(target.required_capabilities),catalog_knowledge_key=None)
    return FrozenCourseNodeV1(user_id=uuid4(),epoch=1,track_id=uuid4(),revision_id=uuid4(),node_id=uuid4(),
        session_id=uuid4(),draft_id=uuid4(),draft_version=2,draft_content_hash=canonical_hash("draft"),
        source_run_id=uuid4(),source_input_revision=5,
        plan_content_hash=canonical_hash("plan"),language_id=target.language_id,goal_hash=goal_hash_for_node(fields),
        selection_handle="selection."+"a"*32,selection_digest=canonical_hash("selection"),
        assessment_binding_id=uuid4(),assessment_binding_digest=canonical_hash("binding"),
        **{**fields,"prerequisite_keys":(),"required_capabilities":target.required_capabilities})


def test_exact_three_target_projection_uses_original_p3_objective_and_scope_ids():
    for target in finite_course_targets():
        n, p = frozen(target), profile(target)
        assert len(n.description) <= 300 and all(c.statement in n.description for c in target.clauses)
        mapping = _mapping_hash(n,p)
        # These are offline P3 return-value fixtures, NOT a registered course or grant.
        original = canonical_hash({"id":str(n.node_id),"description":n.description})
        primary = FrozenPrivateScope(uuid4(),canonical_hash("primary"),original)
        remediation = FrozenPrivateScope(uuid4(),canonical_hash("remediation"),original)
        request = _pack(n,p,mapping,{"practice":primary,"assessment":primary,"remediation":remediation})
        assert request.storage_scope_id == primary.id
        assert tuple(d.storage_scope_id for d in request.demands) == (primary.id,primary.id,remediation.id)
        assert len({d.demand.demand_id for d in request.demands}) == 3
        assert request.demands[0].blueprint == request.demands[1].blueprint
        assert all(d.demand.objective_hash == original for d in request.demands)
        assert all(d.demand.input_revision == n.source_input_revision for d in request.demands)
        assert all(d.demand.scope.knowledge_key == n.knowledge_key for d in request.demands)
        assert request.clause_mapping == tuple((c.clause_id,c.definition_hash,c.clause_id.lower(),canonical_hash({
            "domain":"frozen-course-clause-v1","goal_hash":n.goal_hash,"clause_definition_hash":c.definition_hash,
        })) for c in target.clauses)
        _validate_request(SimpleNamespace(request=request))
        with pytest.raises(EvidenceDenied,match="FROZEN_NODE_MISMATCH"):
            _mapping_hash(n.model_copy(update={"description":target.display_id}),p)


class OfflineConfirmedConnection:
    """SQL-shaped fixture. Any unrecognized query (especially write) fails."""
    autocommit = False

    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        target = finite_course_targets()[0]
        self.frozen = frozen(target)
        n = self.frozen
        plan_node = LearningPlanNode(knowledge_key=n.knowledge_key,title=n.title,description=n.description,
            order_index=0,is_core=True,prerequisite_keys=(),required_capabilities=n.required_capabilities)
        plan = LearningPlan(title="Offline real-shaped draft",target_level="basic",generator_version="fixture-v1",
            policy_version="fixture-v1",change_reason="Initial fixture",modules=(LearningPlanModule(
                module_key="module.fixture",title="Fixture",description="",order_index=0,is_core=True,
                is_skippable=False,nodes=(plan_node,)),))
        compact = CompactPlanProfile(language_id="python",goal_text="Fixture",target_level="basic",weekly_minutes=60,
            experience_level="beginner",teaching_preferences=[],pace_summary="Fixture",title="Fixture")
        artifact = LearningPlanDraftArtifact(compact,plan,())
        self.node = {"id":n.node_id,"knowledge_key":n.knowledge_key,"title":n.title,"description":n.description,
            "is_core":True,"catalog_knowledge_key":None,"prerequisite_keys_json":[],
            "required_capabilities_json":list(n.required_capabilities),"language_id":"python",
            "plan_content_hash":plan.content_hash,"plan_json":canonical_plan_payload(plan)}
        self.session = {"status":"confirmed","confirmed_track_id":n.track_id,"current_draft_id":n.draft_id,
            "conversation_id":uuid4()}
        self.draft = {"id":n.draft_id,"profile_json":compact.model_dump(mode="json"),
            "plan_json":canonical_plan_payload(plan),"source_summary_json":[],"generator_version":"fixture-v1",
            "policy_version":"fixture-v1","change_reason":"Initial fixture","draft_version":2,
            "source_run_id":uuid4(),"source_input_revision":2,"content_hash":artifact.content_hash}
        self.sql = []

    def execute(self, text, params=()):
        self.sql.append(text)
        if text.startswith("SELECT id FROM users"):
            row = {"id":self.frozen.user_id}
        elif text.startswith("SELECT epoch,enabled"):
            row = {"epoch":1,"enabled":True}
        elif "FROM tutor_track_plan_nodes n" in text:
            row = self.node
        elif "FROM tutor_learning_plan_sessions" in text:
            row = self.session
        elif "FROM tutor_learning_plan_drafts" in text:
            row = self.draft
        elif "FROM rag_plan_material_bindings b" in text:
            row = None  # No true persisted assessment selection/freeze exists.
        else:
            raise AssertionError("unexpected offline query: "+text)
        return SimpleNamespace(fetchone=lambda:row)


def _assert_claim_lock_order_and_prepared_actor(reader, monkeypatch):
    """Negative unit seam only: no persisted selection/producer or mapped result."""
    node = reader.conn.frozen
    scope = SubjectScope(subject_id="route.python",subject_version="1.0",facets=("fundamentals",))
    demand = LearningMaterialDemand(scope=scope,demand_hash=canonical_hash("OFFLINE-demand"),
        plan_ref="draft."+str(node.draft_id),node_ref="node."+node.knowledge_key,draft_revision=node.draft_version,
        purpose="assessment_evidence",reading_level="beginner",language="zh")
    binding = RagEvidenceBinding(scope=scope,demand_hash=demand.demand_hash,purpose="assessment_evidence",
        source_handle="source.offline",document_handle="doc.offline",document_revision="1.0",
        document_hash=canonical_hash("OFFLINE-doc"),admission_receipt_id="admission.offline",claim_receipt_id="claim.offline")
    target_id = finite_course_targets()[0].target_id
    execution = public_course_execution_scope(target_id)
    applicability = public_course_source_request(target_id)[2]
    resolved = ClaimEvidenceReceipt(receipt_id="claim.offline",demand_hash=demand.demand_hash,
        purpose="assessment_evidence",admission_receipt_id="admission.offline",claim_hash=canonical_hash("OFFLINE-claim"),
        scope=scope,source_handle=binding.source_handle,document_handle=binding.document_handle,
        document_revision=binding.document_revision,document_hash=binding.document_hash,applicability=applicability,
        method="isolated_execution",execution_receipt_id="execution.offline",execution_scope=execution,verified=True,revoked=False)
    coord = SimpleNamespace(binding=binding,claim_id=resolved.receipt_id,
        claim_receipt_hash=canonical_hash(resolved.model_dump(mode="json")),execution_receipt_id=resolved.execution_receipt_id,
        corroboration_id=None)
    course = SimpleNamespace(node=node,binding=SimpleNamespace(node_id=node.knowledge_key,goal_hash=node.goal_hash,evidence=(coord,)),
        selection=SimpleNamespace(requirements=(SimpleNamespace(node_id=node.knowledge_key,goal_hash=node.goal_hash,
            demand=demand,prerequisites=node.prerequisite_keys),)))
    events = []

    def resolve_claim(self, handle):
        assert handle == "claim.offline"
        events.append("corpus-before-proof")
        return resolved

    def find_claim(self, handle):
        assert events == ["corpus-before-proof"] and handle == "claim.offline"
        events.append("prepared-proof")
        prepared = SimpleNamespace(demand=demand,claim_hash=resolved.claim_hash,execution_scope=execution,
            consume_actor="service.offline-prepared",policy_id="policy.offline",policy_generation=1,
            budget=RagBudgetDelegation(root_id="root.offline",delegation_id="delegation.offline",generation=1,
                expires_at=datetime.now(UTC)+timedelta(minutes=1)))
        return SimpleNamespace(prepared=prepared),None,None

    def deny_current(self, value, purpose, *, request, exact_item_claims):
        assert events == ["corpus-before-proof","prepared-proof"]
        assert request.actor_id == "service.offline-prepared" and purpose == "assessment_evidence"
        assert exact_item_claims[0].binding == binding
        raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE")

    monkeypatch.setattr(PostgresAssessmentClaimResolver,"resolve",resolve_claim)
    monkeypatch.setattr(AssessmentReceiptRepository,"_find",find_claim)
    monkeypatch.setattr(CurrentAuthorization,"check_current_authorization",deny_current)
    with pytest.raises(EvidenceDenied,match="SOURCE_AUTHORIZATION_STALE"):
        reader.authorize(course,target_id=target_id)
    # A current proof for another semantic oracle must deny BEFORE the current
    # authority callback, not merely match draft/node/fundamentals.
    events.clear()
    resolved = resolved.model_copy(update={"execution_scope":ExecutionScope(runtime_profile="python-stdout-v1",
        input_hash=canonical_hash("OFFLINE-legacy-sum"),semantics_hash=canonical_hash("OFFLINE-legacy-sum"))})
    coord.claim_receipt_hash = canonical_hash(resolved.model_dump(mode="json"))
    with pytest.raises(EvidenceDenied,match="CLAIM_VERIFICATION_REQUIRED"):
        reader.authorize(course,target_id=target_id)
    assert events == ["corpus-before-proof","prepared-proof"]
    # Missing current claim must stop before any prepared-proof lock/authority load.
    events.clear()
    monkeypatch.setattr(PostgresAssessmentClaimResolver,"resolve",lambda self, handle: None)
    with pytest.raises(EvidenceDenied,match="CLAIM_VERIFICATION_REQUIRED"):
        reader.authorize(course)
    assert events == []


def test_concrete_confirmed_reader_reconstructs_and_mapping_stays_pending(monkeypatch):
    conn = OfflineConfirmedConnection()
    # Real concrete object types, only DB/transaction IO is replaced offline.
    receipts = object.__new__(AssessmentReceiptRepository)
    receipts.conn = conn
    claims = PostgresAssessmentClaimResolver(receipts)
    current = CurrentAuthorization(conn,governance=SimpleNamespace(
        conn=conn,source_reviews=SimpleNamespace(assessment_receipts=receipts)),claim_resolver=claims)
    monkeypatch.setattr(CurrentAuthorization,"require_transaction",lambda self:None)
    authority = RagSourceAuthority(current,claims)
    reader = ConfirmedAssessmentCourseReader(conn,receipts=receipts,authority=authority)
    p = profile(finite_course_targets()[0])
    owner = FiniteCourseMappingOwner(conn,current_authority=reader,profiles={p.profile_id:p},enabled=True)
    n = conn.frozen
    args = dict(user_id=n.user_id,epoch=1,track_id=n.track_id,revision_id=n.revision_id,node_id=n.node_id,
        session_id=n.session_id,target_id=p.target_id,profile_id=p.profile_id,assessment_binding_id=n.assessment_binding_id)
    assert owner.bind(**args).reason == "assessment_binding_missing"
    assert any("FROM rag_plan_material_bindings b" in q for q in conn.sql)
    conn.node["plan_content_hash"] = canonical_hash("different active revision")
    assert owner.bind(**args).reason == "frozen_node_mismatch"
    conn.node["plan_content_hash"] = conn.draft["content_hash"]  # Distinct hash domain is NOT plan authority.
    assert owner.bind(**args).reason == "frozen_node_mismatch"
    conn.session["status"] = "draft_ready"
    assert owner.bind(**args).reason == "confirmed_course_missing"
    assert all(not q.lstrip().startswith(("INSERT","UPDATE","DELETE")) for q in conn.sql)
    owner.enabled = False
    count = len(conn.sql)
    assert owner.bind(**args).reason == "gate_closed" and len(conn.sql) == count
    _assert_claim_lock_order_and_prepared_actor(reader,monkeypatch)


def test_496_private_fk_and_reset_order_contract_is_not_a_new_purge_owner():
    sql = Path("app/db/schema/496_learning_item_finite_course_mapping.sql").read_text(encoding="utf-8")
    assert "REFERENCES tutor_track_plan_nodes(id,revision_id,track_id,user_id)" in sql
    assert "REFERENCES rag_plan_material_bindings(id,user_id,session_id,draft_id,selection_handle,selection_digest" in sql
    assert "item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true" in sql
    assert "AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs" in sql
    assert "DELETE FROM tutor_item_supply_finite_course_mappings WHERE user_id=NEW.user_id" in sql
    assert "REVOKE ALL ON FUNCTION item_supply_internal.purge_finite_course_mapping_on_epoch_advance() FROM PUBLIC" in sql
    assert "DELETE FROM tutor_item_supply_private_scopes" not in sql
    assert "CREATE OR REPLACE FUNCTION purge_item_supply_private" not in sql
