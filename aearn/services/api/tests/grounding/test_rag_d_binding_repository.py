"""D repository scoped retry/fence checks; PG requires explicit disposable URL."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding.autonomous.contracts import (
    LearningMaterialDemand, RagEvidenceBinding, SubjectScope,
)
from app.services.grounding.material_binding_repository import (
    MaterialBindingConflict, MaterialBindingStale, MaterialTransactionRequired,
    PostgresMaterialBindingRepository, _authorize, goal_hash_for_node,
)
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceBindingV2, EvidenceCoordinate,
    MaterialSelectionEntry, MaterialSelectionResult, NodeMaterialRequirement, digest,
)


def _receipt(value: MaterialSelectionResult, conn: psycopg.Connection | None = None) -> CurrentMaterialAuthorizationReceipt:
    checked_at = (conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
                  if conn is not None else datetime.now(UTC))
    return CurrentMaterialAuthorizationReceipt(
        kind="selection", object_digest=value.selection_digest, draft=value.draft,
        purposes=tuple(sorted({entry.purpose for entry in value.entries})),
        authorization_digest="9" * 64, checked_at=checked_at,
    )


class _Clock:
    def fetchone(self):  # type: ignore[no-untyped-def]
        return {"now": datetime.now(UTC)}


class _FakeConnection:
    def execute(self, _query):  # type: ignore[no-untyped-def]
        return _Clock()


def _selection(scope: DraftScope, node: dict[str, object]) -> MaterialSelectionResult:
    demand = LearningMaterialDemand(
        scope=SubjectScope(subject_id="route.sql", subject_version="sqlite-docs-v1",
                           facets=("queries",)),
        demand_hash="a" * 64, plan_ref=f"draft.{scope.draft_id}",
        node_ref="node.sql.select", draft_revision=scope.draft_version,
        purpose="main_teaching", reading_level="beginner", language="zh",
    )
    goal_hash = goal_hash_for_node(node)
    requirement = NodeMaterialRequirement(node_id="sql.select", goal_hash=goal_hash,
                                          prerequisites=(), demand=demand)
    entry = MaterialSelectionEntry(node_id="sql.select", goal_hash=goal_hash,
                                   purpose="main_teaching", status="gap",
                                   gaps=("missing_material",))
    data = dict(handle=f"selection.{uuid4().hex}", draft=scope,
                requirements=(requirement,), entries=(entry,))
    return MaterialSelectionResult(**data, selection_digest=digest(
        MaterialSelectionResult.model_construct(**data, selection_digest="0" * 64).payload()))


def test_callback_must_return_fresh_exact_receipt() -> None:
    scope = DraftScope(user_id=str(uuid4()), conversation_id=str(uuid4()),
                       session_id=str(uuid4()), draft_id=str(uuid4()), draft_version=1,
                       content_hash="b" * 64, source_run_id=str(uuid4()),
                       source_input_revision=1)
    node = {"knowledge_key": "sql.select", "title": "SELECT", "description": "query rows",
            "is_core": True, "prerequisite_keys": [], "required_capabilities": ["sql.query"]}
    selection = _selection(scope, node)
    conn = _FakeConnection()
    for returned in (None, True, False, {"allowed": True}):
        with pytest.raises(MaterialBindingConflict):
            _authorize(lambda *_: returned, conn, selection)  # type: ignore[arg-type]
    assert _authorize(lambda *_: _receipt(selection), conn, selection).object_digest == selection.selection_digest  # type: ignore[arg-type]
    wrong = _receipt(selection).model_copy(update={"object_digest": "0" * 64})
    with pytest.raises(MaterialBindingConflict):
        _authorize(lambda *_: wrong, conn, selection)  # type: ignore[arg-type]
    old = _receipt(selection).model_copy(update={"checked_at": datetime.now(UTC) - timedelta(minutes=2)})
    with pytest.raises(MaterialBindingConflict):
        _authorize(lambda *_: old, conn, selection)  # type: ignore[arg-type]


@pytest.fixture()
def conn():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_D_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("D PostgreSQL requires AEARN_RAG_D_TEST_DATABASE_URL")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_d_"):
        pytest.fail("D refuses non-aearn_rag260_c_d_ database")
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        assert db.execute("SELECT current_database() AS name").fetchone()["name"] == name
        assert db.execute("SELECT to_regclass('rag_plan_material_bindings') AS name").fetchone()["name"]
        yield db
        db.rollback()


def _seed(conn):  # type: ignore[no-untyped-def]
    user_id, conversation_id, parent, target, session, draft = (str(uuid4()) for _ in range(6))
    catalog = "c" * 64
    conn.execute("INSERT INTO users(id,display_name) VALUES (%s,'D synthetic')", (user_id,))
    conn.execute("INSERT INTO tutor_conversations(id,user_id) VALUES (%s,%s)",
                 (conversation_id, user_id))
    conn.execute("INSERT INTO tutor_catalog_snapshots(digest,manifest_json,redaction_version) "
                 "VALUES (%s,'{}'::jsonb,'test') ON CONFLICT DO NOTHING", (catalog,))
    for run_id, terminal in ((parent, True), (target, False)):
        conn.execute(
            "INSERT INTO tutor_runs(id,user_id,conversation_id,origin,status,policy_json,"
            "policy_version,policy_fingerprint,catalog_digest,input_revision,"
            "terminal_outcome,terminal_at) VALUES (%s,%s,%s,'interactive',%s,'{}'::jsonb,"
            "'test',%s,%s,%s,%s,%s)",
            (run_id, user_id, conversation_id, 'completed' if terminal else 'queued',
             'd' * 64, catalog, 1 if terminal else 2,
             'completed' if terminal else None, datetime.now(UTC) if terminal else None),
        )
        conn.execute(
            "INSERT INTO tutor_run_learning_scopes(run_id,user_id,conversation_id,scope_kind,"
            "task_kind,scope_version) VALUES (%s,%s,%s,'plan_drafting','plan_drafting',0)",
            (run_id, user_id, conversation_id),
        )
    conn.execute("INSERT INTO tutor_learning_plan_sessions(id,user_id,conversation_id) "
                 "VALUES (%s,%s,%s)", (session, user_id, conversation_id))
    node = {"knowledge_key": "sql.select", "title": "SELECT", "description": "query rows",
            "order_index": 0, "is_core": True, "prerequisite_keys": [],
            "required_capabilities": ["sql.query"]}
    plan = {"title": "SQL", "target_level": "beginner", "modules": [
        {"module_key": "base", "title": "Base", "description": "", "order_index": 0,
         "is_core": True, "is_skippable": False, "nodes": [node]}]}
    conn.execute(
        "INSERT INTO tutor_learning_plan_drafts(id,session_id,user_id,draft_version,"
        "language_id,goal_text,target_level,weekly_minutes,experience_level,pace_summary,"
        "profile_json,plan_json,source_summary_json,content_hash,generator_version,"
        "policy_version,change_reason,source_run_id,source_input_revision) "
        "VALUES (%s,%s,%s,1,'python','Learn SQL','beginner',120,'beginner','steady',"
        "'{}'::jsonb,%s::jsonb,'[{}]'::jsonb,%s,'test','test','initial',%s,1)",
        (draft, session, user_id, json.dumps(plan), 'b' * 64, parent),
    )
    conn.execute("UPDATE tutor_learning_plan_sessions SET current_draft_id=%s,"
                 "status='draft_ready',version=2 WHERE id=%s", (draft, session))
    scope = DraftScope(user_id=user_id, conversation_id=conversation_id, session_id=session,
                       draft_id=draft, draft_version=1, content_hash="b" * 64,
                       source_run_id=parent, source_input_revision=1)
    return scope, node, target


def test_selection_assignment_exact_target_and_replay(conn) -> None:  # type: ignore[no-untyped-def]
    scope, node, target = _seed(conn)
    repo = PostgresMaterialBindingRepository(conn)
    selection = _selection(scope, node)
    assert repo.record_selection(selection, idempotency_key="select.test") == selection
    assert repo.record_selection(selection, idempotency_key="select.test") == selection
    assert repo.get_selection(handle=selection.handle, draft=scope) == selection
    with pytest.raises(MaterialBindingConflict):
        repo.record_selection(_selection(scope, node), idempotency_key="select.test")
    with pytest.raises(MaterialBindingConflict):
        repo.assign_feedback(handle=selection.handle, draft=scope, target_run_id=target,
                             target_input_revision=2, expected_session_version=2,
                             current_authorization=lambda *_: None)  # type: ignore[arg-type]
    ref = repo.assign_feedback(handle=selection.handle, draft=scope, target_run_id=target,
                               target_input_revision=2, expected_session_version=2,
                               current_authorization=lambda _, value: _receipt(value, _))
    assert repo.get_feedback_for_target(user_id=scope.user_id, conversation_id=scope.conversation_id,
                                        target_run_id=target, target_input_revision=2) == ref
    conn.execute("UPDATE tutor_runs SET status='failed' WHERE id=%s", (target,))
    with pytest.raises(MaterialBindingStale):
        repo.get_feedback_for_target(user_id=scope.user_id, conversation_id=scope.conversation_id,
                                     target_run_id=target, target_input_revision=2)
    conn.execute("UPDATE tutor_runs SET status='queued' WHERE id=%s", (target,))
    assert repo.assign_feedback(handle=selection.handle, draft=scope, target_run_id=target,
                                target_input_revision=2, expected_session_version=2,
                                current_authorization=lambda _, value: _receipt(value, _)) == ref
    with pytest.raises(MaterialBindingStale):
        repo.get_feedback_for_target(user_id=scope.user_id, conversation_id=scope.conversation_id,
                                     target_run_id=target, target_input_revision=3)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE rag_material_selections SET selection_digest=%s WHERE handle=%s",
                         ('f' * 64, selection.handle))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE rag_material_selections SET target_input_revision=3 WHERE handle=%s",
                         (selection.handle,))


def test_assignment_rejects_terminal_status_without_terminal_receipt(conn) -> None:  # type: ignore[no-untyped-def]
    scope, node, target = _seed(conn)
    selection = _selection(scope, node)
    repo = PostgresMaterialBindingRepository(conn)
    repo.record_selection(selection, idempotency_key="select.failed")
    conn.execute("UPDATE tutor_runs SET status='failed' WHERE id=%s", (target,))
    with pytest.raises(MaterialBindingStale):
        repo.assign_feedback(handle=selection.handle, draft=scope, target_run_id=target,
                             target_input_revision=2, expected_session_version=2,
                             current_authorization=lambda _, value: _receipt(value, _))


def test_direct_partial_assignment_and_foreign_user_purge_are_denied(conn) -> None:  # type: ignore[no-untyped-def]
    scope, node, target = _seed(conn)
    selection = _selection(scope, node)
    repo = PostgresMaterialBindingRepository(conn)
    repo.record_selection(selection, idempotency_key="select.purge")
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE rag_material_selections SET target_run_id=%s WHERE handle=%s",
                         (target, selection.handle))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("DELETE FROM rag_material_selections WHERE handle=%s", (selection.handle,))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("SELECT set_config('aearn.learning_track_purge_user_id',%s,true)",
                         (str(uuid4()),))
            conn.execute("DELETE FROM rag_material_selections WHERE handle=%s", (selection.handle,))
    assert repo.get_selection(handle=selection.handle, draft=scope) == selection
    with conn.transaction():
        conn.execute("SELECT set_config('aearn.learning_track_purge_user_id',%s,true)",
                     (scope.user_id,))
        conn.execute("DELETE FROM rag_material_selections WHERE handle=%s", (selection.handle,))
    assert conn.execute("SELECT count(*) AS n FROM rag_material_selections WHERE handle=%s",
                        (selection.handle,)).fetchone()["n"] == 0


def test_pending_feedback_stales_when_exact_job_finishes(conn) -> None:  # type: ignore[no-untyped-def]
    scope, node, target = _seed(conn)
    gap = _selection(scope, node)
    job_id = str(uuid4())
    raw = gap.model_dump(mode="json", exclude={"selection_digest"})
    raw["entries"][0].update(status="pending", preparation_job_id=job_id)
    selection = MaterialSelectionResult.model_validate_json(json.dumps(
        {**raw, "selection_digest": digest(raw)}))
    demand = selection.requirements[0].demand
    conn.execute(
        "INSERT INTO rag_discovery_jobs(id,operation_key,request_hash,query_hash,demand_hash,"
        "subject_id,subject_version,purpose,policy_id,policy_generation,root_id,"
        "delegation_id,delegation_generation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,1)",
        (job_id, f"operation.{uuid4().hex}", "1" * 64, "2" * 64, demand.demand_hash,
         demand.scope.subject_id, demand.scope.subject_version, demand.purpose,
         "policy.test", "root.test", "delegation.test"),
    )
    repo = PostgresMaterialBindingRepository(conn)
    repo.record_selection(selection, idempotency_key="select.pending")
    repo.assign_feedback(handle=selection.handle, draft=scope, target_run_id=target,
                         target_input_revision=2, expected_session_version=2,
                         current_authorization=lambda _, value: _receipt(value, _))
    conn.execute("UPDATE rag_discovery_jobs SET state='leased',lease_owner_id='worker.test',"
                 "lease_generation=1,lease_expires_at=clock_timestamp()+interval '1 hour' "
                 "WHERE id=%s", (job_id,))
    conn.execute("UPDATE rag_discovery_jobs SET state='completed',lease_owner_id=NULL,"
                 "lease_expires_at=NULL,terminal_at=clock_timestamp() WHERE id=%s", (job_id,))
    with pytest.raises(MaterialBindingStale):
        repo.get_feedback_for_target(user_id=scope.user_id, conversation_id=scope.conversation_id,
                                     target_run_id=target, target_input_revision=2)
    with pytest.raises(MaterialBindingStale):
        repo.assign_feedback(handle=selection.handle, draft=scope, target_run_id=target,
                             target_input_revision=2, expected_session_version=2,
                             current_authorization=lambda _, value: _receipt(value, _))


def test_reject_autocommit_even_if_transaction_open(conn) -> None:  # type: ignore[no-untyped-def]
    # Repository refuses implicit/autocommit connections; no test-side toggle while shared DB is in use.
    repo = PostgresMaterialBindingRepository(conn)
    assert isinstance(repo, PostgresMaterialBindingRepository)
    assert conn.autocommit is False
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
    with pytest.raises(MaterialTransactionRequired):
        PostgresMaterialBindingRepository(_AutocommitProxy(conn)).get_selection(  # type: ignore[arg-type]
            handle=f"selection.{uuid4().hex}", draft=DraftScope(
                user_id=str(uuid4()), conversation_id=str(uuid4()), session_id=str(uuid4()),
                draft_id=str(uuid4()), draft_version=1, content_hash="a" * 64,
                source_run_id=str(uuid4()), source_input_revision=1))


class _AutocommitProxy:
    autocommit = True

    def __init__(self, conn):  # type: ignore[no-untyped-def]
        self.info = conn.info


def test_freeze_natural_key_and_replay_require_current_receipt(conn) -> None:  # type: ignore[no-untyped-def]
    scope, node, _ = _seed(conn)
    gap = _selection(scope, node)
    requirement = gap.requirements[0]
    demand = requirement.demand
    a = RagEvidenceBinding(
        scope=demand.scope, demand_hash=demand.demand_hash, purpose=demand.purpose,
        source_handle="source.test", document_handle="document.test", document_revision="v1",
        document_hash="1" * 64, admission_receipt_id="admit.test",
    )
    coordinate = EvidenceCoordinate(
        binding=a, subject_id=demand.scope.subject_id, corpus_version_id=str(uuid4()),
        active_generation=1, summary_hash="2" * 64, validation_hash="3" * 64,
        registry_digest="4" * 64, source_review_id=str(uuid4()),
        source_policy_id="policy.test", source_policy_generation=1,
        chunk_id="chunk.sql", chunk_hash="5" * 64, approved_excerpt_hash="6" * 64,
        retrieval_hash="7" * 64, coverage_hash="8" * 64,
    )
    ready = MaterialSelectionEntry(node_id=requirement.node_id, goal_hash=requirement.goal_hash,
                                   purpose=demand.purpose, status="ready",
                                   covered_facets=demand.scope.facets, evidence=(coordinate,))
    selection_data = dict(handle=gap.handle, draft=scope, requirements=(requirement,),
                          entries=(ready,))
    selection = MaterialSelectionResult(**selection_data, selection_digest=digest(
        MaterialSelectionResult.model_construct(**selection_data,
                                                 selection_digest="0" * 64).payload()))
    repo = PostgresMaterialBindingRepository(conn)
    repo.record_selection(selection, idempotency_key="select.ready")
    data = dict(selection_handle=selection.handle, selection_digest=selection.selection_digest,
                draft=scope, node_id=requirement.node_id, goal_hash=requirement.goal_hash,
                purpose=demand.purpose, evidence=(coordinate,))
    binding = EvidenceBindingV2(**data, binding_digest=digest(
        EvidenceBindingV2.model_construct(**data, binding_digest="0" * 64).payload()))

    def authorized(_, exact: EvidenceBindingV2) -> CurrentMaterialAuthorizationReceipt:  # type: ignore[no-untyped-def]
        return CurrentMaterialAuthorizationReceipt(
            kind="binding", object_digest=exact.binding_digest, draft=exact.draft,
            purposes=(exact.purpose,), authorization_digest="9" * 64,
            checked_at=_.execute("SELECT clock_timestamp() AS now").fetchone()["now"],
        )

    with pytest.raises(MaterialBindingConflict):
        repo.freeze_binding(binding=binding, idempotency_key="freeze.test",
                            current_authorization=lambda *_: None)  # type: ignore[arg-type]
    assert repo.freeze_binding(binding=binding, idempotency_key="freeze.test",
                               current_authorization=authorized) == binding
    assert repo.freeze_binding(binding=binding, idempotency_key="freeze.test",
                               current_authorization=authorized) == binding
    assert repo.freeze_binding(binding=binding, idempotency_key="freeze.other",
                               current_authorization=authorized) == binding
    assert conn.execute("SELECT count(*) AS n FROM rag_plan_material_bindings "
                        "WHERE draft_id=%s", (scope.draft_id,)).fetchone()["n"] == 1
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE rag_plan_material_bindings SET binding_digest=%s "
                         "WHERE draft_id=%s", ("0" * 64, scope.draft_id))
