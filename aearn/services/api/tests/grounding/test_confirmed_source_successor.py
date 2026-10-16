"""Pure/synthetic successor checks. No DB, source authority, oracle or model acceptance."""
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.confirmed_source_successor import same_supported_source
from app.services.grounding.autonomous.source_assessment_profiles import PreparedSourceAssessment, SourceAssessmentDenied
from app.services.grounding.public_course_contracts import public_course_demand
from tests.grounding.test_actual_d_finite_source import OfflineD, prepare, repository


def private_prepared(monkeypatch):
    conn = OfflineD("python-kc-binding-v1")
    repo = repository(monkeypatch,conn)
    return repo,prepare(repo,conn)


def public_prepared(q):
    data = q.model_dump(exclude={"actual_d"})
    data.update(profile_id="python-binding-source-v1",demand=public_course_demand("python-kc-binding-v1").model_dump())
    return PreparedSourceAssessment.model_validate(data)


def test_public_scaffolding_and_offsets_change_but_supported_bytes_do_not(monkeypatch):
    _,q = private_prepared(monkeypatch)
    old = public_prepared(q)
    new = old.model_copy(update={"capture_id":uuid4(),"document_handle":"document.new.public","document_hash":"f"*64,
        "spans":tuple(s.model_copy(update={"start_byte":s.start_byte+127,"end_byte":s.end_byte+127}) for s in old.spans)})
    same_supported_source(old,new)
    assert old.document_hash != new.document_hash and old.spans != new.spans


def test_changed_supported_span_denies_even_when_document_hash_claims_same(monkeypatch):
    _,q = private_prepared(monkeypatch)
    old = public_prepared(q)
    new = old.model_copy(update={"spans":(old.spans[0].model_copy(update={"sha256":"0"*64}),*old.spans[1:])})
    with pytest.raises(SourceAssessmentDenied,match="SUPPORTED_CONTENT_CHANGED"):
        same_supported_source(old,new)


def test_private_new_oracle_same_confirmed_scope_and_no_public_substitution(monkeypatch):
    _,old = private_prepared(monkeypatch)
    new = old.model_copy(update={"capture_id":uuid4(),"document_handle":"document.new.private","document_hash":"f"*64,
        "actual_d":old.actual_d.model_copy(update={"oracle_run_id":uuid4()})})
    same_supported_source(old,new)
    changed = new.model_copy(update={"actual_d":new.actual_d.model_copy(update={"goal_hash":"0"*64})})
    with pytest.raises(SourceAssessmentDenied,match="CONFIRMED_SCOPE_CHANGED"):
        same_supported_source(old,changed)
    with pytest.raises(SourceAssessmentDenied,match="SUPPORTED_CONTENT_CHANGED"):
        same_supported_source(old,public_prepared(new))


def test_original_confirmed_entry_rejects_unregistered_mapping(monkeypatch):
    repo,q = private_prepared(monkeypatch)
    with pytest.raises(SourceAssessmentDenied,match="SOURCE_CONFIRMED_SUCCESSOR_REQUIRED"):
        repo.prepare_confirmed_successor(capture_id=uuid4(),document_handle=q.document_handle,mapping_receipt_id=uuid4())


def test_current_pack_material_continuity_is_complete_and_receipt_coordinates_are_data():
    import json
    from app.services.learning.item_bank.contracts import canonical_hash
    from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
    from app.services.learning.item_supply.persistent_pack_current_source_materials import require_material_continuity
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for

    old = materials_for("python-kc-binding-v1")[0]
    raw = old.model_dump(mode="json")
    coordinate = raw["binding"]["evidence"][0]
    coordinate["binding"].update(document_handle="document.new.public",document_hash="f"*64,
        document_revision="f"*64,admission_receipt_id="admission.new",claim_receipt_id="source-claim.new")
    coordinate.update(claim_id="source-claim.new",claim_receipt_hash="e"*64,chunk_id="chunk.new.0")
    raw["exact_claims"][0].update(binding=coordinate["binding"],claim_receipt_id="source-claim.new",claim_hash="d"*64)
    raw["binding"]["binding_digest"] = canonical_hash({k:v for k,v in raw["binding"].items() if k != "binding_digest"})
    new = PublicMaterialV2.model_validate_json(json.dumps(raw))
    require_material_continuity(old,new)  # Pure obligations only; NEVER source permission.
    for changed in (
        new.model_copy(update={"excerpt":new.excerpt+"changed"}),
        new.model_copy(update={"binding":new.binding.model_copy(update={"course_goal_hash":"0"*64})}),
        new.model_copy(update={"exact_claims":(new.exact_claims[0].model_copy(update={"applicability":"different"}),)}),
    ):
        with pytest.raises(PipelineRepositoryError,match="OBLIGATIONS_CHANGED"):
            require_material_continuity(old,changed)
    assert old.model_dump(mode="json") != raw


def test_current_pack_source_rejects_json_and_revision_cap_without_default_alias():
    from types import SimpleNamespace
    from app.services.learning.item_supply.persistent_pack_current_source import require, source_origin_payload
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

    assert source_origin_payload(SimpleNamespace()) is None
    for fake in ({"record_id":str(uuid4())},SimpleNamespace(record_id=uuid4(),purpose="revision_only")):
        with pytest.raises(PipelineRepositoryError,match="ORIGINAL_ISSUER_REQUIRED"):
            require(fake)
        with pytest.raises(PipelineRepositoryError,match="ORIGINAL_TYPE_OWNER_REQUIRED"):
            source_origin_payload(SimpleNamespace(current_source_binding=fake))


def test_current_pack_access_policy_budget_successor_is_signed_metadata_not_goal_change(monkeypatch):
    from datetime import timedelta
    from app.services.grounding.autonomous.access_policy import AccessRequest
    from app.services.grounding.public_course_contracts import PUBLIC_COURSE_ACTOR
    from app.services.learning.item_supply.persistent_pack_current_source_materials import (
        require_material_continuity, require_signed_access,
    )
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for

    _, private = private_prepared(monkeypatch)
    old_prepared = public_prepared(private)
    new_prepared = old_prepared.model_copy(update={"policy_id":"source.policy.successor","policy_generation":old_prepared.policy_generation+1,
        "budget":old_prepared.budget.model_copy(update={"root_id":"root.source.successor","delegation_id":"delegation.source.successor",
            "expires_at":old_prepared.budget.expires_at+timedelta(days=1)})})
    material = materials_for("python-kc-binding-v1")[0]
    def access(p):
        return AccessRequest(demand_hash=p.demand.demand_hash,scope=p.demand.scope,purpose="assessment_evidence",
            actor_id=PUBLIC_COURSE_ACTOR,action="consume",policy_id=p.policy_id,policy_generation=p.policy_generation,budget=p.budget)
    old=material.model_copy(update={"access_request":access(old_prepared)})
    new=material.model_copy(update={"access_request":access(new_prepared)})
    before=old.model_dump(mode="json")
    require_material_continuity(old,new)  # DATA continuity does not issue a cap.
    require_signed_access(old,old_prepared,at=old_prepared.prepared_at)
    require_signed_access(new,new_prepared,at=new_prepared.prepared_at)
    with pytest.raises(PipelineRepositoryError,match="SIGNED_ACCESS_METADATA_CHANGED"):
        require_signed_access(new,old_prepared,at=old_prepared.prepared_at)
    with pytest.raises(PipelineRepositoryError,match="SIGNED_ACCESS_METADATA_CHANGED"):
        require_signed_access(old,old_prepared,at=old_prepared.budget.expires_at)
    changed_actor=new.model_copy(update={"access_request":new.access_request.model_copy(update={"actor_id":"service.wrong.actor"})})
    with pytest.raises(PipelineRepositoryError,match="OBLIGATIONS_CHANGED"):
        require_material_continuity(old,changed_actor)
    assert old.model_dump(mode="json")==before


def test_current_pack_same_fence_mapping_is_returned_once_and_legacy_abi_stays(monkeypatch):
    from datetime import timedelta
    from types import SimpleNamespace
    from app.services.learning.item_supply import persistent_pack_source_successor as successor
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for

    _, private = private_prepared(monkeypatch)
    prepared = public_prepared(private)
    public = materials_for("python-kc-binding-v1")[:1]
    course = materials_for("python-kc-binding-v1")[1:]
    until = prepared.prepared_at + timedelta(hours=1)
    current = SimpleNamespace(claim_handle="source-claim.new",prepared=prepared,evidence_id=uuid4(),expires_at=until)
    mapping = object()
    calls = []
    parent = dict(request_json={},artifact_hash="a"*64)
    conn = SimpleNamespace(execute=lambda sql,params: SimpleNamespace(fetchone=lambda:
        {"signed_proof":{}} if "signed_proof" in sql else parent))
    receipts = SimpleNamespace(conn=conn,_find=lambda claim: (current,None,None),
        private_provenance=lambda claim: SimpleNamespace(public=current))
    reviews = SimpleNamespace(resolve=lambda *args: SimpleNamespace(grant=SimpleNamespace(retained_until=until)))
    authority = SimpleNamespace(connection=conn,authorize=lambda material: calls.append("authorize"),
        _current=SimpleNamespace(governance=SimpleNamespace(source_reviews=reviews)))
    def resolve(**kwargs):
        calls.append(("mapping",kwargs))
        return mapping
    owner = SimpleNamespace(resolve_source_successor=resolve,current_authority=SimpleNamespace(receipts=receipts))
    core = SimpleNamespace(conn=conn,type_owner=SimpleNamespace(mapping_owner=owner,source_authority=authority),
        _guard=lambda: prepared.prepared_at)
    task = SimpleNamespace(mapping_receipt_id=uuid4(),user_id=uuid4(),epoch=1)
    monkeypatch.setattr(successor,"_history",lambda *args: calls.append("history"))
    monkeypatch.setattr(successor.SignedSourceAssessment,"model_validate_json",
        lambda raw: SimpleNamespace(payload=SimpleNamespace(prepared=prepared)))
    monkeypatch.setattr(successor.GenerationRequestV2,"model_validate_json",lambda raw: SimpleNamespace(materials=public))

    actual_parent,deadlines,deadline,actual_mapping = successor._current_with_mapping(core,task,public,course)
    assert actual_parent is parent and actual_mapping is mapping and deadline == until
    assert calls == ["history",("mapping",dict(receipt_id=task.mapping_receipt_id,user_id=task.user_id,epoch=1,materials=course)),"authorize"]
    calls.clear()
    assert successor._current(core,task,public,course) == (parent,deadlines,until)
    assert [call[0] for call in calls if isinstance(call,tuple)] == ["mapping"]


def test_current_pack_same_fence_origin_reuses_selection_but_rechecks_each_call(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from app.services.learning.item_supply import persistent_pack_current_source as source
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for

    now = datetime(2026,10,14,tzinfo=timezone.utc)
    public = materials_for("python-kc-binding-v1")[:1]
    course = materials_for("python-kc-binding-v1")[1:]
    mapping = SimpleNamespace(mapping_hash="a"*64,model_dump=lambda **kwargs: {"mapping_hash":"a"*64})
    state = dict(mapping=mapping,selection_hash="b"*64,selected=[],receiver=True)
    calls = []
    events = []
    def execute(sql,params=None):
        if "clock_timestamp" in sql:
            return SimpleNamespace(fetchone=lambda: dict(now=now,txid=17))
        assert "current_pack_source_origin_current" in sql
        calls.append("sql549")
        return SimpleNamespace(fetchone=lambda: dict(ok=state["receiver"]))
    def authorize(material):
        calls.append("authorize")
        return SimpleNamespace(model_dump=lambda **kwargs: dict(binding_digest=material.binding.binding_digest))
    def resolve(**kwargs):
        calls.append("mapping")
        return state["mapping"]
    core = SimpleNamespace(conn=SimpleNamespace(execute=execute),_current_source_bindings={},_current_source_origins={},
        _guard=lambda: now,type_owner=SimpleNamespace(source_authority=SimpleNamespace(authorize=authorize),
            mapping_owner=SimpleNamespace(resolve_source_successor=resolve)))
    def event(task,kind,payload,**kwargs):
        events.append((kind,payload))
        return uuid4()
    core._private_event = event
    task = SimpleNamespace(user_id=uuid4(),epoch=1,mapping_receipt_id=uuid4(),model_dump=lambda **kwargs: {"epoch":1})
    data = dict(public_materials=[m.model_dump(mode="json") for m in public],course_materials=[m.model_dump(mode="json") for m in course])
    receipts = tuple(authorize(m) for m in (*public,*course))
    cap = source.IssuedCurrentPackSourceBinding(core,uuid4(),task,source.canonical_hash(data),state["selection_hash"],
        source._authorization(mapping,public,course,receipts),now+timedelta(hours=1),public,course,mapping)
    core._current_source_bindings[cap.binding_id] = (cap,source._seal(cap))
    def current(*args):
        calls.append("fresh")
        return {},(),cap.source_deadline,resolve(receipt_id=task.mapping_receipt_id,user_id=task.user_id,epoch=task.epoch,materials=course)
    def selection(*args):
        calls.append("selection")
        state["selected"] = [{"version_id":str(uuid4())}]
        return state["selected"],state["selection_hash"]
    monkeypatch.setattr(source,"_data",lambda *args: data)
    monkeypatch.setattr(source,"_current_with_mapping",current)
    monkeypatch.setattr(source,"_selection",selection)
    calls.clear()

    assert cap.require() is mapping
    rid,payload = source.origin(cap)
    assert payload["selected"] is state["selected"]
    assert source.origin(cap) == (rid,payload)
    assert calls.count("fresh") == calls.count("mapping") == calls.count("selection") == 3
    assert calls.count("sql549") == 1 and len(events) == 1
    assert events[0][0] == source.KIND
    state["selection_hash"] = "c"*64
    with pytest.raises(PipelineRepositoryError,match="CURRENT_BINDING_CHANGED"):
        source.origin(cap)
    state["selection_hash"] = cap.selection_hash
    state["mapping"] = SimpleNamespace(mapping_hash="d"*64)
    with pytest.raises(PipelineRepositoryError,match="CURRENT_BINDING_CHANGED"):
        cap.require()
    state["mapping"] = mapping
    state["receiver"] = False
    with pytest.raises(PipelineRepositoryError,match="ORIGIN_STALE"):
        source.origin(cap)
    assert len(events) == 1 and calls.count("sql549") == 2
