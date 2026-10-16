"""Synthetic component seams only. No PG, HTTP, original author or live authority acceptance.

Database/source ports and revision context are deliberately synthetic. The real
producer observes a staged DTO; the real new issuer/writer/lineage caller code
is exercised without restoring producer registries on the fresh pipeline.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.native_revision_contracts import NativeRevisionAuthorInputBindingV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.shared_generation_durability import (
    IssuedRevisionGenerationPersistence, RevisionGenerationDurability,
)
from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
from tests.learning.test_item_supply_shared_pipeline import setup


def fixture(monkeypatch, *, usage=True, post_fence=False):
    gp,conn,request,lease,provider,authority,calls,settlements,checkpoints = setup(monkeypatch,usage=usage)
    original_execute = conn.execute
    state = dict(prep=None,output=None,settlement=None,lineage=None,top=1,depth=1,subxid=100,
                 fail_output=False,fail_artifact=False,artifact_txid=None)

    @contextmanager
    def transaction():
        outer = conn.info.transaction_status == TransactionStatus.IDLE
        if outer:
            state["top"] += 1
        state["depth"] += 1
        state["subxid"] += 1
        conn.info.transaction_status = TransactionStatus.INTRANS
        before = state["output"]
        try:
            yield
        except Exception:
            state["output"] = before
            raise
        finally:
            state["depth"] -= 1
            conn.info.transaction_status = TransactionStatus.IDLE if outer else TransactionStatus.INTRANS

    def execute(sql,params=()):
        conn.statements.append(sql)
        if sql == "SELECT txid_current() AS top_txid":
            row = {"top_txid":state["top"]}
        elif "to_regclass" in sql and "controlled" in sql:
            row = dict(t=None,execution_t=None)
        elif "to_regclass" in sql and "revision_preparations" in sql:
            row = dict(table_id="synthetic" if state["prep"] else None)
        elif "FROM tutor_item_supply_shared_revision_preparations" in sql:
            row = state["prep"]
        elif "FROM tutor_item_supply_shared_runtime_settlements" in sql:
            row = state["settlement"]
            if row is not None:
                row = dict(row,same_transaction=row["capture_txid"] == state["top"])
        elif sql.startswith("INSERT INTO tutor_item_supply_shared_revision_generation_outputs"):
            if state["fail_output"]:
                raise ValueError("synthetic journal unavailable")
            payload = params[-1].obj
            row = dict(preparation_id=params[0],root_id=params[1],job_id=params[2],candidate_id=params[3],
                reservation_id=params[4],settlement_id=params[5],payload_json=payload,snapshot_hash=canonical_hash(payload),
                capture_txid=state["top"],xmin=state["subxid"])
            state["output"] = row
        elif "FROM tutor_item_supply_shared_revision_generation_outputs" in sql:
            row = state["output"]
            if row is not None:
                assert "capture_txid=txid_current()" in sql or sql.startswith("SELECT snapshot_hash")
                row = dict(row,same_transaction=row["capture_txid"] == state["top"])
        elif "assert_revision_generation_output_current" in sql:
            row = None  # Synthetic SQL port, NOT evidence of the actual receiver.
        elif sql.startswith("INSERT INTO tutor_item_supply_shared_generation_artifacts"):
            if state["fail_artifact"]:
                raise ValueError("synthetic artifact storage failure")
            if conn.row is None:
                state["artifact_txid"] = state["top"]
            return original_execute(sql,params)
        elif "FROM tutor_item_supply_shared_generation_artifacts a" in sql:
            row = dict(conn.row,same_transaction=state["artifact_txid"] == state["top"]) if conn.row else None
        elif "FROM tutor_item_supply_shared_checkpoints" in sql:
            row = {"ok":1} if checkpoints else None
        elif sql.startswith("INSERT INTO tutor_item_supply_shared_revision_lineage"):
            state["lineage"] = dict(id=params[0],payload_json=params[-1].obj)
            row = None
        elif "FROM tutor_item_supply_shared_revision_lineage" in sql:
            row = state["lineage"]
        else:
            return original_execute(sql,params)
        return SimpleNamespace(fetchone=lambda:row)

    monkeypatch.setattr(conn,"execute",execute)
    monkeypatch.setattr(conn,"transaction",transaction)
    prepared = gp.prepare_generation(lease=lease,request=request,provider=provider,source_authority=authority)
    context = SimpleNamespace(context_hash="a"*64)
    p = SimpleNamespace(preparation_id=uuid4(),lease=lease,request=request,context=context,
        deadline_at=lease.expires_at,investigation=SimpleNamespace(original=SimpleNamespace(persistent_committed_frame={})))
    state["prep"] = dict(id=p.preparation_id,root_id=uuid4(),child_job_id=lease.job_id,candidate_id=request.candidate_id,
        parent_artifact_id=uuid4(),snapshot_hash="b"*64,payload_json=dict(request=request.model_dump(mode="json"),
        child_lease=lease.model_dump(mode="json"),context_hash=context.context_hash,deadline_at=lease.expires_at.isoformat(),parent_substantive_hash="c"*64))
    trace = SimpleNamespace(context=context,binding=None)
    checks = []

    def fence(*a,**kw):
        checks.append(1)
        if post_fence and len(checks)>1:
            raise ValueError("synthetic source expired after IO")
        return context

    synthetic_revision = SimpleNamespace(_issued=lambda p:None,generation_context=fence)
    gp._revision[prepared.reservation_id] = (synthetic_revision,p,trace)
    from app.services.learning.item_supply import shared_pipeline
    original_generate = shared_pipeline.generate_candidate

    def generate(req,**kw):
        kw.pop("supplemental_context")
        kw.pop("revision_trace")
        kw.pop("deadline_at")
        trace.binding = NativeRevisionAuthorInputBindingV1(request_hash=canonical_hash(req.model_dump(mode="json")),
            context_hash=context.context_hash,envelope_hash="d"*64,messages_hash="e"*64,output_schema_hash="f"*64,input_bytes=100)
        return original_generate(req,**kw)

    monkeypatch.setattr(shared_pipeline,"generate_candidate",generate)
    conn.info.transaction_status = TransactionStatus.IDLE
    result = gp.run_generation(prepared,provider)

    def settle(**kw):
        settlements.append(kw)
        state["settlement"] = dict(id=uuid4(),reservation_id=prepared.reservation_id,
            usage_state=kw["usage_state"],capture_txid=state["top"])

    monkeypatch.setattr(gp.budget,"settle",settle)
    monkeypatch.setattr(gp.runtime,"refresh_lease",lambda value,**kw:value)
    return gp,conn,prepared,result,authority,state,calls,settlements,checkpoints


def fresh_pipeline(monkeypatch,gp):
    fresh = SharedGenerationPipeline(gp.conn,gp.settings.model_copy(update={"learning_item_network_enabled":False}),
        enabled=True,trusted_model_bindings=gp._models)
    # Reuse explicitly synthetic repository/current-source ports, not author registries.
    fresh.artifacts = gp.artifacts
    fresh.runtime = gp.runtime
    fresh.budget = gp.budget
    assert not fresh._prepared and not fresh._results and not fresh._revision and not fresh._started
    return fresh


def test_journal_failure_retains_known_and_unknown_settlement(monkeypatch):
    for usage in (True,False):
        with monkeypatch.context() as m:
            gp,conn,prepared,result,_,state,calls,settlements,_ = fixture(m,usage=usage)
            state["fail_output"] = True
            with conn.transaction():
                outcome = gp.settle_generation(prepared,result)
                assert conn.info.transaction_status == TransactionStatus.INTRANS
            assert outcome.durability == "settled_only"
            assert settlements[0]["usage_state"] == ("known" if usage else "unknown")
            assert state["output"] is None and state["settlement"] is not None and len(calls)==1


def test_nested_savepoint_output_is_not_committed(monkeypatch):
    gp,conn,prepared,result,authority,state,_,_,_ = fixture(monkeypatch)
    with conn.transaction():
        assert gp.settle_generation(prepared,result).durability == "durable"
        assert state["output"]["xmin"] != state["top"]
        assert state["output"]["capture_txid"] == state["top"]
        with pytest.raises(PipelineRepositoryError,match="GENERATION_DURABLE_BINDING_NOT_COMMITTED"):
            gp.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)


def test_process_boundary_persistence_only_roundtrip(monkeypatch):
    gp,conn,prepared,result,authority,state,calls,settlements,checkpoints = fixture(monkeypatch)
    with conn.transaction():
        gp.settle_generation(prepared,result)
    fresh = fresh_pipeline(monkeypatch,gp)
    state["fail_artifact"] = True
    with conn.transaction():
        cap = fresh.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)
        with pytest.raises(ValueError,match="artifact storage"):
            fresh.commit_revision_persistence(cap)
    assert len(calls)==len(settlements)==1 and not checkpoints
    state["fail_artifact"] = False
    restarted = fresh_pipeline(monkeypatch,gp)
    with conn.transaction():
        cap = restarted.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)
        stage = restarted.commit_revision_persistence(cap)
        with pytest.raises(PipelineRepositoryError,match="COMMITTED_GENERATION_REQUIRED"):
            restarted.persist_revision_lineage(cap)
    with conn.transaction():
        assert restarted.persist_revision_lineage(cap)==state["prep"]["id"]
        assert restarted.persist_revision_lineage(cap)==state["prep"]["id"]
        assert restarted.commit_revision_persistence(cap).artifact_id==stage.artifact_id
    assert len(calls)==len(settlements)==len(checkpoints)==1
    assert not restarted._prepared and not restarted._started and not restarted._results


def test_nested_artifact_and_reissued_lineage_wait_for_separate_top(monkeypatch):
    gp,conn,prepared,result,authority,state,calls,settlements,checkpoints = fixture(monkeypatch)
    with conn.transaction():
        gp.settle_generation(prepared,result)
    fresh = fresh_pipeline(monkeypatch,gp)
    with pytest.raises(PipelineRepositoryError,match="PERSISTENCE_TRANSACTION_REQUIRED"):
        fresh.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)
    with conn.transaction():
        with conn.transaction():
            cap = fresh.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)
            fresh.commit_revision_persistence(cap)
        with pytest.raises(PipelineRepositoryError,match="COMMITTED_GENERATION_REQUIRED"):
            fresh.persist_revision_lineage(cap)
        restarted = fresh_pipeline(monkeypatch,gp)
        cap = restarted.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)
        with pytest.raises(PipelineRepositoryError,match="COMMITTED_GENERATION_REQUIRED"):
            restarted.persist_revision_lineage(cap)
    with conn.transaction():
        assert restarted.persist_revision_lineage(cap)==state["prep"]["id"]
        assert restarted.persist_revision_lineage(cap)==state["prep"]["id"]
    assert len(calls)==len(settlements)==len(checkpoints)==1


def test_missing_history_and_forged_cap_rejected(monkeypatch):
    gp,conn,prepared,result,authority,state,_,_,_ = fixture(monkeypatch)
    with conn.transaction(),pytest.raises(PipelineRepositoryError,match="GENERATION_DURABLE_BINDING_MISSING"):
        gp.prepare_revision_persistence(UUID("c8593cb3-2360-48c0-a7f8-a3a69c930184"),source_authority=authority)
    with conn.transaction():
        gp.settle_generation(prepared,result)
    with conn.transaction():
        cap = gp.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)
        with pytest.raises(PipelineRepositoryError,match="PERSISTENCE_ISSUER_REQUIRED"):
            gp.commit_revision_persistence(replace(cap))
        with pytest.raises(PipelineRepositoryError,match="PERSISTENCE_ISSUER_REQUIRED"):
            RevisionGenerationDurability(gp).commit(cap)


def test_repository_rejects_forged_persistence_owner(monkeypatch):
    gp,conn,prepared,result,authority,state,_,_,_ = fixture(monkeypatch)
    verified = []

    def forged_verify(cap):
        verified.append(cap)
        return {"preparation_id":state["prep"]["id"]},state["prep"],prepared.lease

    fake_owner = SimpleNamespace(conn=conn,generation=SimpleNamespace(artifacts=gp.artifacts),verify=forged_verify)
    cap = IssuedRevisionGenerationPersistence(fake_owner,state["prep"]["id"],"0"*64,prepared.request,result,authority)
    with conn.transaction(),pytest.raises(PipelineRepositoryError,match="GENERATION_PERSISTENCE_ISSUER_REQUIRED"):
        gp.artifacts.store_generation(lease=prepared.lease,request=prepared.request,result=result,
            artifact_key="generation."+prepared.request.candidate_id.hex,now=datetime.now(UTC),
            source_authority=authority,persistence=cap)
    assert not verified and conn.row is None and state["output"] is None


def test_post_io_fence_failure_preserves_observation_not_recovery_authority(monkeypatch):
    gp,conn,prepared,result,authority,state,calls,settlements,_ = fixture(monkeypatch,post_fence=True)
    assert result.state=="failed" and result.source is None
    with conn.transaction():
        assert gp.settle_generation(prepared,result).durability=="durable"
    assert state["output"]["payload_json"]["result"]["state"]=="staged"
    assert state["output"]["payload_json"]["returned_state"]=="failed"
    with conn.transaction(),pytest.raises(PipelineRepositoryError,match="DURABLE_BINDING_CHANGED"):
        gp.prepare_revision_persistence(state["prep"]["id"],source_authority=authority)
    assert len(calls)==len(settlements)==1
