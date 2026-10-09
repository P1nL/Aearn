"""P2 PostgreSQL-only synthetic verification; self-contained --noconftest.

Ordinary tests roll back. Concurrency tests commit only named synthetic users on
this exact disposable DB, then perform guarded schema-owner fixture teardown.
No business DB, role, worker/provider IO.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.errors import CheckViolation, ForeignKeyViolation, GeneratedAlways, InsufficientPrivilege
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.db.bootstrap import bootstrap_database
from app.services.learning.item_bank.autonomous_policy import evaluate_autonomous_admission
from app.services.learning.item_bank.contracts import (
    LearningItemInteraction, LearningItemKind, LearningItemPrivateV1, LearningItemPublicV1,
    LearningItemPurpose, canonical_hash,
)
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1, CoverageBlueprintV1, ObjectiveClauseV1, SupplyScopeV1,
)
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.storage import (
    PostgresPrivateSupplyStorage, PostgresSharedSupplyStorage, SupplyStorageError,
    purge_private_supply,
)
from app.services.learning.item_supply.storage_contracts import (
    AutonomousEvidencePolicyV2, EvidenceV2, ObservationV2, checked_model,
)
from app.services.learning.item_supply.storage_tables import (
    EPOCH_TABLE, P2_PRIVATE_TABLES, PRIVATE_TABLES, SHARED_TABLES,
)

DSN = "postgresql://postgres:postgres@127.0.0.1:5432/aearn_b1b_fixture_20260930"
H = "a"*64
P = "autonomous_evidence_policy_v2"


@pytest.fixture(scope="module", autouse=True)
def schema() -> None:
    assert os.environ.get("DATABASE_URL") == DSN
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert os.environ.get("LLM_TYPE") == "disabled"
    assert os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1"
    # Validate exact dedicated database before allowing the owning bootstrap.
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        assert conn.execute("SELECT current_database() AS db").fetchone()["db"] == "aearn_b1b_fixture_20260930"
    bootstrap_database()
    bootstrap_database()


@pytest.fixture
def conn() -> Iterator[Connection[dict[str, object]]]:
    connection = psycopg.connect(DSN, row_factory=dict_row)
    # Ensure conn.transaction() is a savepoint, including for tests whose first
    # statement is an expected negative insert. Never commit a failed assertion.
    connection.execute("SELECT 1")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def insert(conn: Connection[dict[str, object]], table: str, **facts: object) -> dict[str, object]:
    values = tuple(Jsonb(v) if isinstance(v, dict) else v for v in facts.values())
    return conn.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, facts)),
        sql.SQL(",").join(sql.Placeholder() for _ in facts),
    ), values).fetchone()


def scope(user: UUID | None = None) -> SupplyScopeV1:
    return SupplyScopeV1(
        course_family="python-core", course_version="1.0", knowledge_key="python.functions",
        language_id="python", subject_id="route.python", subject_version="1.0",
        required_facets=("functions",), runtime_profile_id="python-v1", runtime_profile_hash=H,
        item_kind=LearningItemKind.CODE, purpose=LearningItemPurpose.EXERCISE,
        interaction=LearningItemInteraction.EDIT, required_capabilities=("python_stdout_test",),
        assessment_contract_version="gate-v1", scorer_version="scorer-v1", assistance_policy_hash=H,
        visibility="private" if user else "public", owner_ref=f"user:{user}" if user else None,
    )


def owner(conn: Connection[dict[str, object]]) -> dict[str, object]:
    user = insert(conn, "users", display_name="P2 synthetic") ["id"]
    track = insert(conn, "tutor_learning_tracks", user_id=user, language_id="python", goal_text="synthetic", target_level="basic")["id"]
    revision = insert(conn, "tutor_track_plan_revisions", track_id=track, user_id=user, status="active",
                      title="synthetic", target_level="basic", plan_json={}, generator_version="synthetic",
                      policy_version="synthetic", change_reason="fixture", content_hash=H, activated_at=datetime.now(UTC))["id"]
    insert(conn, "tutor_track_active_plans", track_id=track, user_id=user, revision_id=revision)
    module = insert(conn, "tutor_track_plan_modules", revision_id=revision, track_id=track, user_id=user,
                    module_key="functions", title="synthetic", order_index=0)["id"]
    insert(conn, "tutor_track_plan_nodes", module_id=module, revision_id=revision, track_id=track, user_id=user,
           knowledge_key="python.functions", title="synthetic", description="function behavior", order_index=0)
    repo = PostgresPrivateSupplyStorage(conn, user_id=user, expected_epoch=1)
    frozen = repo.bind_scope(track_id=track, revision_id=revision, scope=scope(user))
    material = repo.store_material(scope_id=frozen.id, material_key="private-source", content_text="PRIVATE SECRET")
    candidate = repo.store_candidate(scope_id=frozen.id, candidate_key="candidate", material_id=material)
    payload = conn.execute("SELECT p.public_json AS pub,q.private_json AS priv FROM tutor_learning_item_public_contents p "
                           "JOIN tutor_learning_item_private_contents q ON q.version_id=p.version_id LIMIT 1").fetchone()
    public = LearningItemPublicV1.model_validate(payload["pub"])
    private = LearningItemPrivateV1.model_validate(payload["priv"])
    version = repo.store_version(scope_id=frozen.id, candidate_id=candidate, version=1, public=public, private=private)
    return dict(user=user, track=track, revision=revision, repo=repo, scope=frozen, material=material,
                candidate=candidate, version=version, public=public, private=private)


def shared(conn: Connection[dict[str, object]]) -> dict[str, object]:
    repo = PostgresSharedSupplyStorage(conn)
    repo.register_policy(AutonomousEvidencePolicyV2())
    blueprint = CoverageBlueprintV1(scope=scope(), objective_hash=H,
        clauses=(ObjectiveClauseV1(clause_id="functions", clause_hash=H),),
        matrix_hash=build_support_matrix().matrix_hash, policy_version=P)
    return dict(repo=repo, blueprint=blueprint, blueprint_id=repo.register_blueprint(blueprint))


def populate(conn: Connection[dict[str, object]], o: dict[str, object]) -> dict[str, object]:
    shared(conn)
    base = dict(user_id=o["user"], epoch=1, scope_id=o["scope"].id)
    def add(name: str, **facts: object) -> dict[str, object]:
        return insert(conn, "tutor_item_supply_private_"+name, **base, **facts)
    root = add("budget_roots", canonical_key=canonical_hash(str(o["user"])), policy_class="synthetic")
    window = add("budget_windows", root_id=root["id"], pool_key="user-enhancement", provider_key="disabled",
                 window_start=datetime.now(UTC), window_end=datetime.now(UTC)+timedelta(hours=1), request_cap=10, token_cap=1000, resource_cap=1000)
    job = add("jobs", root_id=root["id"], job_key="synthetic")
    child = add("jobs", root_id=root["id"], parent_job_id=job["id"], job_key="child")
    add("job_events", job_id=job["id"], event_key="event", event_kind="created", lease_generation=0, state_version=1, safe_reason="synthetic")
    reservation = add("reservations", root_id=root["id"], window_id=window["id"], job_id=job["id"], lease_generation=1,
                      reservation_key="reservation", requests=1, tokens=100, resources=1)
    usage = add("usage_events", reservation_id=reservation["id"], job_id=job["id"], settlement_key="usage", usage_state="unknown")
    evidence = o["repo"].store_evidence(scope_id=o["scope"].id, job_id=job["id"], version_id=o["version"].id,
                                       evidence=EvidenceV2(evidence_key="evidence", producer_identity="synthetic", evidence_kind="probe", receipt_hash=H))
    o["repo"].store_observation(scope_id=o["scope"].id, job_id=job["id"], observation=ObservationV2(
        origin="simulation", event_key="observation", event_kind="answer", receipt_hash=H))
    proof = add("proofs", evidence_id=evidence, version_id=o["version"].id, item_hash=o["version"].payload_hash,
                policy_version=P, objective_hash=o["scope"].objective_hash, scope_hash=o["scope"].scope_hash,
                environment_hash=H, proof_key="proof")
    o["repo"].store_admission(scope_id=o["scope"].id, evidence_id=evidence,
                            decision=evaluate_autonomous_admission(AutonomousEvidencePolicyV2(), admission_key="admission"))
    demand = AssessmentSupplyDemandV1(demand_id="synthetic", learner_ref=f"user:{o['user']}", scope=scope(o["user"]),
        objective_hash=o["scope"].objective_hash, blueprint_hash=H, matrix_hash=build_support_matrix().matrix_hash, policy_version=P, input_revision=1)
    demand_id = o["repo"].store_demand(scope_id=o["scope"].id, request_key="request", demand=demand)
    result = add("results", demand_id=demand_id, result_version=1, status="pending", safe_reason="preparing")
    event = conn.execute("SELECT id,version_id FROM tutor_learning_item_publication_events LIMIT 1").fetchone()
    ref = add("publication_refs", version_id=o["version"].id, publication_event_id=event["id"], shared_version_id=event["version_id"])
    add("result_items", result_id=result["id"], proof_id=proof["id"], publication_ref_id=ref["id"])
    add("bindings", result_id=result["id"], version_id=o["version"].id, binding_key="binding")
    add("cache", version_id=o["version"].id, cache_key="cache", expires_at=datetime.now(UTC)+timedelta(hours=1))
    add("staging", candidate_id=o["candidate"], stage_key="stage", public_json=o["public"].model_dump(mode="json"), private_json=o["private"].model_dump(mode="json"))
    add("subscriptions", demand_id=demand_id, private_job_id=child["id"], subscription_key="subscription")
    return dict(base=base, job=job, child=child, reservation=reservation, usage=usage, evidence=evidence, demand=demand)


def test_full_bootstrap_manifest_and_partition(conn):
    from app.db.schema import SCHEMA_FRAGMENT_NAMES, load_schema_fragments
    from app.services.tutor.cutover import CUTOVER_SHARED_TUTOR_TABLES, CUTOVER_TARGET_TUTOR_TABLES
    assert SCHEMA_FRAGMENT_NAMES[-1] == "450_learning_item_supply_runtime.sql"
    assert SCHEMA_FRAGMENT_NAMES[-2] == "440_learning_item_supply_sandbox.sql"
    assert "COMMIT;" not in load_schema_fragments()[-1].sql.upper()
    assert set(SHARED_TABLES) <= CUTOVER_SHARED_TUTOR_TABLES
    assert set(PRIVATE_TABLES) | {EPOCH_TABLE} <= CUTOVER_TARGET_TUTOR_TABLES
    actual = {r["tablename"] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'tutor_%'")}
    assert actual == CUTOVER_SHARED_TUTOR_TABLES | CUTOVER_TARGET_TUTOR_TABLES


def test_typed_idempotency_hash_and_private_lookup(conn):
    a,b = owner(conn),owner(conn)
    repo = a["repo"]
    assert repo.store_material(scope_id=a["scope"].id, material_key="private-source", content_text="PRIVATE SECRET") == a["material"]
    with pytest.raises(SupplyStorageError):
        repo.store_material(scope_id=a["scope"].id, material_key="private-source", content_text="changed")
    with pytest.raises(SupplyStorageError):
        b["repo"].get_version(scope_id=b["scope"].id, handle=a["version"].handle)
    assert repo.store_version(scope_id=a["scope"].id, candidate_id=a["candidate"], version=1,
                              public=a["public"], private=a["private"]) == a["version"]
    with pytest.raises(GeneratedAlways), conn.transaction():
        conn.execute("INSERT INTO tutor_item_supply_private_versions(user_id,epoch,scope_id,candidate_id,version,public_json,private_json,payload_hash) "
                     "VALUES(%s,1,%s,%s,2,%s,%s,%s)", (a["user"],a["scope"].id,a["candidate"],Jsonb(a["public"].model_dump(mode="json")),Jsonb(a["private"].model_dump(mode="json")),H))


def test_cross_owner_and_half_source_db_rejected(conn):
    a,b = owner(conn),owner(conn)
    with pytest.raises(ForeignKeyViolation), conn.transaction():
        insert(conn,"tutor_item_supply_private_candidates",user_id=b["user"],epoch=1,scope_id=b["scope"].id,material_id=a["material"],candidate_key="cross")
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn,"tutor_item_supply_private_materials",user_id=a["user"],epoch=1,scope_id=a["scope"].id,
               material_key="half",content_text="private",source_subject="route.python")


def test_immutable_db_mutation_and_forged_guc_denied(conn):
    a = owner(conn)
    shared(conn)
    conn.execute("SELECT set_config('aearn.learning_track_purge_user_id',%s,true)",(str(a["user"]),))
    conn.execute("SELECT set_config('aearn.item_supply_purge_user_id',%s,true)",(str(a["user"]),))
    for statement,args in [
        ("DELETE FROM tutor_item_supply_private_versions WHERE id=%s",(a["version"].id,)),
        ("UPDATE tutor_item_supply_private_materials SET content_text='changed' WHERE id=%s",(a["material"],)),
        ("UPDATE tutor_item_supply_user_epochs SET epoch=epoch+1 WHERE user_id=%s",(a["user"],)),
        ("DELETE FROM tutor_item_supply_shared_policies",()),
    ]:
        with pytest.raises(CheckViolation), conn.transaction():
            conn.execute(statement,args)
    # PUBLIC cannot create an unforgeable permit or call the maintenance purge.
    row = conn.execute("SELECT proacl FROM pg_proc WHERE oid='purge_item_supply_private(uuid,boolean)'::regprocedure").fetchone()
    assert "=X/" not in str(row["proacl"]).replace('postgres=X/', '')
    assert conn.execute("SELECT count(*) AS n FROM item_supply_internal.reset_permits").fetchone()["n"] == 0


def test_all_private_responsibilities_export_reset_two_users_and_epoch(conn):
    a,b = owner(conn),owner(conn)
    populate(conn,a)
    populate(conn,b)
    for table in P2_PRIVATE_TABLES:
        assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE user_id=%s").format(sql.Identifier(table)),(a["user"],)).fetchone()["n"] > 0
    snapshot = {t:conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(t))).fetchone()["n"] for t in SHARED_TABLES}
    from app.services.repositories.local_user_data_repository import export_user_data,reset_user_data
    exported = export_user_data(conn,str(a["user"]))["item_supply_private_summaries"]
    assert set(PRIVATE_TABLES) <= exported.keys()
    assert "PRIVATE SECRET" not in json.dumps(exported,default=str)
    assert a["version"].payload_hash not in json.dumps(exported,default=str)
    for table in PRIVATE_TABLES:
        assert set(exported[table]) == {"records", "truncated"}
        assert all(set(row) == {"id", "scope_id", "created_at"} for row in exported[table]["records"])
    assert str(b["version"].id) not in json.dumps(exported,default=str)
    reset_user_data(conn,str(a["user"]))
    for table in PRIVATE_TABLES:
        assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE user_id=%s").format(sql.Identifier(table)),(a["user"],)).fetchone()["n"] == 0
        other_count = conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE user_id=%s").format(sql.Identifier(table)),(b["user"],)).fetchone()["n"]
        assert other_count > 0 if table in P2_PRIVATE_TABLES else other_count == 0
    for t,count in snapshot.items():
        assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(t))).fetchone()["n"] == count
    assert conn.execute("SELECT epoch FROM tutor_item_supply_user_epochs WHERE user_id=%s",(a["user"],)).fetchone()["epoch"] == 2
    with pytest.raises(SupplyStorageError,match="stale"):
        a["repo"].store_material(scope_id=a["scope"].id,material_key="private-source",content_text="revival")
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn,"tutor_item_supply_private_materials",user_id=a["user"],epoch=1,scope_id=a["scope"].id,material_key="late-worker",content_text="revival")


def test_purge_rollback_and_delete_user_epoch(conn):
    a = owner(conn)
    populate(conn,a)
    with pytest.raises(RuntimeError),conn.transaction():
        purge_private_supply(conn,a["user"])
        raise RuntimeError("caller rollback")
    assert a["repo"].get_version(scope_id=a["scope"].id,handle=a["version"].handle) == a["version"]
    from app.services.repositories.local_user_data_repository import delete_user_data
    delete_user_data(conn,str(a["user"]))
    assert conn.execute("SELECT epoch,enabled FROM tutor_item_supply_user_epochs WHERE user_id=%s",(a["user"],)).fetchone() == dict(epoch=2,enabled=False)
    with pytest.raises(SupplyStorageError):
        PostgresPrivateSupplyStorage(conn,user_id=a["user"],expected_epoch=2)._check_epoch()


def test_scope_revalidated_after_active_plan_change(conn):
    a = owner(conn)
    conn.execute("DELETE FROM tutor_track_active_plans WHERE track_id=%s",(a["track"],))
    with pytest.raises(SupplyStorageError):
        a["repo"].get_version(scope_id=a["scope"].id,handle=a["version"].handle)


def test_usage_unknown_policy_isolation_and_terminal_fence(conn):
    a = owner(conn)
    data = populate(conn,a)
    assert data["usage"]["input_tokens"] is None and data["usage"]["cost_amount"] is None
    with pytest.raises(CheckViolation),conn.transaction():
        insert(conn,"tutor_item_supply_private_usage_events",**data["base"],reservation_id=data["reservation"]["id"],job_id=data["job"]["id"],
               settlement_key="fake-free",usage_state="unknown",input_tokens=0)
    with pytest.raises(ForeignKeyViolation),conn.transaction():
        insert(conn,"tutor_item_supply_private_evidence",**data["base"],job_id=data["job"]["id"],version_id=a["version"].id,
               item_hash=a["version"].payload_hash,schema_version="item_supply_evidence_v2",policy_version="learning_item_agent_review_policy_v1",
               evidence_key="mixed",producer_identity="synthetic",evidence_kind="probe",receipt_hash=H)
    conn.execute("UPDATE tutor_item_supply_private_jobs SET state='cancelled',state_version=state_version+1,terminal_at=now() WHERE id=%s",(data["child"]["id"],))
    with pytest.raises(CheckViolation),conn.transaction():
        conn.execute("UPDATE tutor_item_supply_private_jobs SET state='pending',state_version=state_version+1,terminal_at=NULL WHERE id=%s",(data["child"]["id"],))


def test_observation_identity_and_v2_admission_never_publish(conn):
    a = owner(conn)
    data=populate(conn,a)
    with pytest.raises(ValueError):
        ObservationV2(origin="simulation",event_key="fake",event_kind="answer",receipt_hash=H,actor_id=a["user"])
    with pytest.raises(CheckViolation),conn.transaction():
        insert(conn,"tutor_item_supply_private_observations",**data["base"],job_id=data["job"]["id"],schema_version="observation_v2",
               origin="real_learner",event_key="fake-real",event_kind="answer",receipt_hash=H)
    with pytest.raises(CheckViolation),conn.transaction():
        insert(conn,"tutor_item_supply_private_observations",**data["base"],job_id=data["job"]["id"],schema_version="observation_v2",
               origin="real_learner",event_key="invented",event_kind="answer",receipt_hash=H,collector_identity="synthetic",
               actor_id=a["user"],session_id=uuid4(),terminal_receipt_id=uuid4(),attempt_id=uuid4())
    for enabled in (False,True):
        decision=evaluate_autonomous_admission(AutonomousEvidencePolicyV2(),admission_key="synthetic",enabled=enabled)
        assert decision.decision in ("blocked","evidence_pending")
    with pytest.raises(ValueError):
        checked_model(AutonomousEvidencePolicyV2().model_copy(update={"publication_enabled":True}),AutonomousEvidencePolicyV2)


def test_default_off_and_pure_entry_unchanged(monkeypatch):
    from app.core.config import Settings
    for name in ("GENERATION","NETWORK","V2_ADMISSION","SUPPLY"):
        monkeypatch.delenv("LEARNING_ITEM_"+name+"_ENABLED",raising=False)
    settings=Settings()
    assert not any((settings.learning_item_generation_enabled,settings.learning_item_network_enabled,
                    settings.learning_item_v2_admission_enabled,settings.learning_item_supply_enabled))
    import inspect
    import app.services.learning.item_supply as pure
    assert "storage" not in inspect.getsource(pure)


def test_maintenance_privileges_not_granted_to_untrusted_role(conn):
    a = owner(conn)
    # Built-in read role exists already; no cluster role creation or grants.
    with conn.transaction():
        conn.execute("SET LOCAL ROLE pg_read_all_data")
        try:
            with pytest.raises(InsufficientPrivilege),conn.transaction():
                conn.execute("SELECT purge_item_supply_private(%s,false)",(a["user"],))
            with pytest.raises(InsufficientPrivilege),conn.transaction():
                conn.execute("INSERT INTO item_supply_internal.reset_permits VALUES(txid_current(),%s)",(a["user"],))
        finally:
            conn.execute("RESET ROLE")
    assert a["repo"].get_version(scope_id=a["scope"].id,handle=a["version"].handle) == a["version"]


def test_shared_budget_job_and_subscription_remain_private_on_reset(conn):
    a,b = owner(conn),owner(conn)
    data_a=populate(conn,a)
    data_b=populate(conn,b)
    s=shared(conn)
    root=insert(conn,"tutor_item_supply_shared_budget_roots",blueprint_id=s["blueprint_id"],canonical_key=H,policy_class="shared")
    job=insert(conn,"tutor_item_supply_shared_jobs",root_id=root["id"],job_key="shared")
    subscriptions=[]
    for o,data in ((a,data_a),(b,data_b)):
        demand=conn.execute("SELECT id FROM tutor_item_supply_private_demands WHERE user_id=%s",(o["user"],)).fetchone()
        subscriptions.append(insert(conn,"tutor_item_supply_private_subscriptions",**data["base"],demand_id=demand["id"],
                                    shared_job_id=job["id"],subscription_key="shared-subscriber"))
    assert all("user_id" not in row and "scope_id" not in row for row in (root,job))
    purge_private_supply(conn,a["user"])
    assert conn.execute("SELECT state FROM tutor_item_supply_shared_jobs WHERE id=%s",(job["id"],)).fetchone()["state"] == "pending"
    assert conn.execute("SELECT state FROM tutor_item_supply_private_subscriptions WHERE id=%s",(subscriptions[1]["id"],)).fetchone()["state"] == "active"
    with pytest.raises(CheckViolation),conn.transaction():
        insert(conn,"tutor_item_supply_shared_jobs",root_id=root["id"],job_key="forged-terminal",state="completed",terminal_at=datetime.now(UTC))


def test_cutover_counts_payload_but_retains_epoch_without_blocking(conn):
    from app.services.tutor.cutover import HarnessCutoverService
    a=owner(conn)
    decision=HarnessCutoverService(conn).get_decision(user_id=str(a["user"]))
    assert decision["state"] == "blocked_target_state"
    from app.services.repositories.local_user_data_repository import reset_user_data
    reset_user_data(conn,str(a["user"]))
    decision=HarnessCutoverService(conn).get_decision(user_id=str(a["user"]))
    assert decision["state"] == "verified"
    assert conn.execute("SELECT epoch FROM tutor_item_supply_user_epochs WHERE user_id=%s",(a["user"],)).fetchone()["epoch"] == 2


def test_each_private_table_rejects_ordinary_update_delete(conn):
    a=owner(conn)
    populate(conn,a)
    for table in P2_PRIVATE_TABLES:
        row=conn.execute(sql.SQL("SELECT id FROM {} WHERE user_id=%s LIMIT 1").format(sql.Identifier(table)),(a["user"],)).fetchone()
        assert row is not None
        for command in ("UPDATE {} SET created_at=created_at WHERE id=%s", "DELETE FROM {} WHERE id=%s"):
            with pytest.raises(CheckViolation),conn.transaction():
                conn.execute(sql.SQL(command).format(sql.Identifier(table)),(row["id"],))


def test_final_exact_scope_constraints_installed_after_repeat_bootstrap(conn):
    a=owner(conn)
    data=populate(conn,a)
    with pytest.raises(ForeignKeyViolation),conn.transaction():
        insert(conn,"tutor_item_supply_private_proofs",**data["base"],evidence_id=data["evidence"],version_id=a["version"].id,
               item_hash=a["version"].payload_hash,policy_version=P,objective_hash=H,scope_hash=a["scope"].scope_hash,
               environment_hash=H,proof_key="forged-objective")
    for name in ("chk_item_supply_private_scope_namespace","chk_item_supply_shared_blueprint_namespace","fk_item_supply_proof_exact_scope"):
        assert conn.execute("SELECT convalidated FROM pg_constraint WHERE conname=%s",(name,)).fetchone()["convalidated"] is True


def test_original_instance_cannot_be_laundered_through_json(conn):
    from pydantic import Field
    from app.services.learning.item_supply.storage_contracts import SourceCoordinatesV2
    source = SourceCoordinatesV2(subject="route.python", corpus_id=uuid4(), document_id=uuid4(),
                                chunk_id=uuid4(), receipt_id=uuid4())
    for field in ("corpus_id", "document_id", "chunk_id", "receipt_id"):
        with pytest.raises(ValueError):
            checked_model(source.model_copy(update={field: str(getattr(source, field))}), SourceCoordinatesV2)
    # JSON strict mode relaxes tuples, but original strict instances must not.
    policy = AutonomousEvidencePolicyV2()
    with pytest.raises(ValueError):
        checked_model(policy.model_copy(update={"required_review_roles": list(policy.required_review_roles)}), AutonomousEvidencePolicyV2)
    class HiddenSource(SourceCoordinatesV2):
        private_payload: str = Field(default="SECRET", exclude=True)
    evidence = EvidenceV2(evidence_key="nested", producer_identity="synthetic", evidence_kind="probe", receipt_hash=H)
    with pytest.raises(ValueError):
        checked_model(evidence.model_copy(update={"source": HiddenSource(**source.__dict__)}), EvidenceV2)
    a = owner(conn)
    class HiddenPublicContent(type(a["public"].content)):
        private_payload: str = Field(default="SECRET", exclude=True)
    forged_public = a["public"].model_copy(update={"content": HiddenPublicContent(**a["public"].content.__dict__)})
    with pytest.raises(ValueError):
        a["repo"].store_version(scope_id=a["scope"].id, candidate_id=a["candidate"], version=2,
                                public=forged_public, private=a["private"])
    code_payload = conn.execute("SELECT private_json FROM tutor_learning_item_private_contents "
                                "WHERE private_json->'content'->>'type'='code' LIMIT 1").fetchone()
    code_private = LearningItemPrivateV1.model_validate(code_payload["private_json"])
    private_content = code_private.content
    forged_test = private_content.tests[0].model_copy(update={"order_index": True})
    with pytest.raises(ValueError):
        checked_model(code_private.model_copy(update={"content": private_content.model_copy(
            update={"tests": (forged_test, *private_content.tests[1:])})}), LearningItemPrivateV1)


def test_multirow_lineage_cycles_cannot_defeat_reset(conn):
    a = owner(conn)
    data = populate(conn, a)
    x, y = uuid4(), uuid4()
    with pytest.raises(CheckViolation), conn.transaction():
        conn.execute("INSERT INTO tutor_item_supply_private_candidates(id,user_id,epoch,scope_id,candidate_key,parent_candidate_id) "
                     "VALUES(%s,%s,1,%s,'cycle-x',%s),(%s,%s,1,%s,'cycle-y',%s)",
                     (x, a["user"], a["scope"].id, y, y, a["user"], a["scope"].id, x))
    with pytest.raises(CheckViolation), conn.transaction():
        conn.execute("INSERT INTO tutor_item_supply_private_jobs(id,user_id,epoch,scope_id,root_id,job_key,parent_job_id) "
                     "VALUES(%s,%s,1,%s,%s,'cycle-x',%s),(%s,%s,1,%s,%s,'cycle-y',%s)",
                     (x, a["user"], a["scope"].id, data["job"]["root_id"], y,
                      y, a["user"], a["scope"].id, data["job"]["root_id"], x))


def test_security_definer_search_path_cannot_implicitly_prepend_temp(conn):
    rows = conn.execute("SELECT proname,proconfig,EXISTS (SELECT 1 FROM aclexplode("
                        "COALESCE(proacl,acldefault('f',proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') "
                        "AS public_execute FROM pg_proc WHERE prosecdef AND "
                        "(proname LIKE 'enforce_item_supply_%' OR proname IN ('permitted','purge_item_supply_private'))").fetchall()
    assert len(rows) >= 10
    for row in rows:
        assert row["proconfig"] == ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]
        assert row["public_execute"] is False


def learning_authority(conn, o):
    """Synthetic lawful DB coordinates, NOT a real learner or trusted collector."""
    base = dict(user_id=o["user"], track_id=o["track"], knowledge_key="python.functions")
    insert(conn, "tutor_track_node_progress", **base, status="available", source_plan_revision_id=o["revision"])
    standard = insert(conn, "tutor_lesson_documents", document_kind="standard", language_id="python",
                      knowledge_key="python.functions", schema_version="lesson_document_v1", content_standard_version="synthetic",
                      generator_version=str(uuid4()), policy_version="synthetic", source_set_hash=H,
                      title="synthetic standard", coverage_keys_json=Jsonb([]), blocks_json=Jsonb([]), content_hash=H)["id"]
    docs = []
    for n in (1, 2):
        docs.append(insert(conn, "tutor_lesson_documents", **base, document_kind="personalized", language_id="python",
            active_plan_revision_id=o["revision"], standard_document_id=standard, schema_version="lesson_document_v1",
            content_standard_version="synthetic", generator_version=f"synthetic-{n}", policy_version="synthetic",
            source_set_hash=H, profile_hash=H, title="synthetic authority", coverage_keys_json=Jsonb([]),
            blocks_json=Jsonb([]), content_hash=H)["id"])
    assignment = insert(conn, "tutor_lesson_assignments", **base, document_id=docs[0], source_plan_revision_id=o["revision"],
                        assignment_version=1, status="active", expected_progress_version=1, content_hash=H,
                        activated_at=datetime.now(UTC))["id"]
    conversation = insert(conn, "tutor_conversations", user_id=o["user"])["id"]
    session = insert(conn, "tutor_teaching_sessions", **base, conversation_id=conversation, track_version=1,
                     active_plan_revision_id=o["revision"], progress_version=1, lesson_assignment_id=assignment,
                     assignment_version=1, document_id=docs[0], document_content_hash=H)["id"]
    exercise = insert(conn, "tutor_exercise_versions", language_id="python",
                      exercise_key=f"synthetic-{uuid4()}", exercise_type="code_completion", version="synthetic",
                      source_kind="curated_fixture", title="synthetic exercise", learner_prompt_json={},
                      starter_artifact_json={}, required_capabilities_json=Jsonb([]), execution_required=False,
                      public_feedback_policy_version="synthetic", validation_status="ready", content_hash=H,
                      published_at=datetime.now(UTC))["id"]
    attempts, terminals = [], []
    for n, doc in enumerate(docs):
        gate_key = f"synthetic-gate-{n}"
        slot = insert(conn, "tutor_lesson_gate_slots", **base, document_id=doc, block_id=gate_key, gate_key=gate_key,
                      gate_kind="independent_practice", assessment_contract_version="synthetic",
                      required_capabilities_json=Jsonb([]), learner_prompt_hash=H, learner_prompt="synthetic")["id"]
        binding = insert(conn, "tutor_lesson_gate_bindings", **base, document_id=doc, slot_id=slot, gate_key=gate_key,
                         exercise_version_id=exercise, requirement_kind="required", pass_policy_version="synthetic",
                         pass_threshold=1.0, execution_requirement="optional", slot_contract_hash=H,
                         binding_contract_hash=H, published_at=datetime.now(UTC))["id"]
        attempt = insert(conn, "tutor_exercise_attempts", **base, attempt_type="submit", plan_revision_id=o["revision"],
                         expected_track_version=1, expected_progress_version=1, lesson_assignment_id=assignment,
                         document_id=doc, gate_binding_id=binding, exercise_version_id=exercise, submission_hash=H,
                         hint_state_hash=H, independence="independent", idempotency_key=f"synthetic-{n}",
                         request_hash=H, accepted_at=datetime.now(UTC))["id"]
        terminal = insert(conn, "tutor_exercise_attempt_results", attempt_id=attempt, user_id=o["user"], outcome="failed",
                          score=0.0, safe_feedback_json={}, capability_scores_json={}, policy_version="synthetic",
                          result_hash=H, terminal_at=datetime.now(UTC))["id"]
        attempts.append(attempt)
        terminals.append(terminal)
    return dict(session=session, attempts=attempts, terminals=terminals)


def test_real_observation_uses_exact_terminal_document_and_owner(conn):
    a, b = owner(conn), owner(conn)
    da, db = populate(conn, a), populate(conn, b)
    aa, ab = learning_authority(conn, a), learning_authority(conn, b)
    observation = ObservationV2(origin="real_learner", event_key="lawful-synthetic", event_kind="answer", receipt_hash=H,
                                collector_identity="synthetic-db-not-real-collector", session_id=aa["session"],
                                actor_id=a["user"], terminal_receipt_id=aa["terminals"][0], attempt_id=aa["attempts"][0])
    a["repo"].store_observation(scope_id=a["scope"].id, job_id=da["job"]["id"], observation=observation)
    # Same user, track, node and assignment are insufficient: different document.
    with pytest.raises(CheckViolation), conn.transaction():
        a["repo"].store_observation(scope_id=a["scope"].id, job_id=da["job"]["id"], observation=observation.model_copy(
            update={"event_key": "wrong-document", "terminal_receipt_id": aa["terminals"][1], "attempt_id": aa["attempts"][1]}))
    for updates in (
        {"session_id": ab["session"]},
        {"terminal_receipt_id": ab["terminals"][0], "attempt_id": ab["attempts"][0]},
        {"terminal_receipt_id": aa["terminals"][1]},
    ):
        with pytest.raises((CheckViolation, ForeignKeyViolation)), conn.transaction():
            a["repo"].store_observation(scope_id=a["scope"].id, job_id=da["job"]["id"], observation=observation.model_copy(
                update={"event_key": "wrong-authority", **updates}))
    with pytest.raises(SupplyStorageError):
        b["repo"].store_observation(scope_id=b["scope"].id, job_id=db["job"]["id"], observation=observation)
    from app.services.repositories.local_user_data_repository import reset_user_data
    reset_user_data(conn, str(a["user"]))
    assert conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_observations WHERE user_id=%s", (a["user"],)).fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM tutor_exercise_attempt_results WHERE user_id=%s", (b["user"],)).fetchone()["n"] == 2


@pytest.fixture
def committed_owner(conn):
    # Real two-connection races require committed coordinates. No other fixture
    # user may exist; abort rather than cleaning someone else's records.
    assert conn.execute("SELECT count(*) AS n FROM tutor_item_supply_user_epochs").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"] == 0
    o = owner(conn)
    conn.commit()
    try:
        yield o
    finally:
        conn.rollback()
        from app.services.repositories.local_user_data_repository import reset_user_data
        reset_user_data(conn, str(o["user"]))
        # Retained epochs intentionally have no business DELETE path. This is
        # disposable-fixture teardown by its trusted schema owner, AFTER all
        # behavioral assertions. Exact row ownership and emptiness are checked
        # under exclusive lock before TRUNCATE (never disable a guard for tests).
        conn.execute("LOCK TABLE tutor_item_supply_user_epochs IN ACCESS EXCLUSIVE MODE")
        rows = conn.execute("SELECT user_id FROM tutor_item_supply_user_epochs").fetchall()
        assert {r["user_id"] for r in rows} == {o["user"]}
        for table in PRIVATE_TABLES:
            assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"] == 0
        conn.execute("TRUNCATE TABLE tutor_item_supply_user_epochs")
        conn.execute("DELETE FROM users WHERE id=%s", (o["user"],))
        conn.commit()


def raced_write(connection, o, operation):
    repo = PostgresPrivateSupplyStorage(connection, user_id=o["user"], expected_epoch=1)
    if operation == "bind":
        repo.bind_scope(track_id=o["track"], revision_id=o["revision"], scope=scope(o["user"]))
    elif operation == "store":
        repo.store_material(scope_id=o["scope"].id, material_key="in-flight", content_text="SYNTHETIC RACE")
    else:
        insert(connection, "tutor_item_supply_private_materials", user_id=o["user"], epoch=1,
               scope_id=o["scope"].id, material_key="direct-late-worker", content_text="SYNTHETIC RACE")


def switch_revision(connection, o):
    connection.execute("UPDATE tutor_track_plan_revisions SET status='superseded' WHERE id=%s", (o["revision"],))
    revision = insert(connection, "tutor_track_plan_revisions", track_id=o["track"], user_id=o["user"], status="active",
                      title="replacement", target_level="basic", plan_json={}, generator_version="synthetic",
                      policy_version="synthetic", change_reason="fixture switch", content_hash="b"*64,
                      activated_at=datetime.now(UTC))["id"]
    connection.execute("UPDATE tutor_track_active_plans SET revision_id=%s WHERE track_id=%s AND user_id=%s",
                       (revision, o["track"], o["user"]))


def other_connection(action, ready):
    with psycopg.connect(DSN, row_factory=dict_row) as connection:
        connection.execute("SET LOCAL lock_timeout='5s'")
        connection.execute("SET LOCAL statement_timeout='8s'")
        pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        ready.put(pid)
        try:
            action(connection)
            connection.commit()
            return "accepted"
        except (SupplyStorageError, CheckViolation) as exc:
            connection.rollback()
            return type(exc).__name__


def assert_other_connection_blocked(conn, pid, future):
    blocker = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
    deadline = monotonic() + 3
    while monotonic() < deadline:
        row = conn.execute("SELECT pg_blocking_pids(%s) AS blockers", (pid,)).fetchone()
        if blocker in row["blockers"]:
            return
        if future.done():
            pytest.fail(f"two-connection operation bypassed lock: {future.result()}")
        sleep(0.01)
    pytest.fail("two-connection operation did not demonstrably wait for the owner lock")


@pytest.mark.parametrize("operation", ("bind", "store", "sql"))
@pytest.mark.parametrize("reset_first", (True, False))
def test_concurrent_reset_fences_late_bind_store_and_sql(conn, committed_owner, operation, reset_first):
    o = committed_owner
    ready = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            if reset_first:
                purge_private_supply(conn, o["user"])
                future = pool.submit(other_connection, lambda c: raced_write(c, o, operation), ready)
            else:
                raced_write(conn, o, operation)
                future = pool.submit(other_connection, lambda c: purge_private_supply(c, o["user"]), ready)
            pid = ready.get(timeout=3)
            assert_other_connection_blocked(conn, pid, future)
            conn.commit()
            outcome = future.result(timeout=8)
        finally:
            conn.rollback()  # Always unblock the second connection on assertion failure.
    expected = ("CheckViolation" if operation == "sql" else "SupplyStorageError") if reset_first else "accepted"
    assert outcome == expected
    assert conn.execute("SELECT epoch FROM tutor_item_supply_user_epochs WHERE user_id=%s", (o["user"],)).fetchone()["epoch"] == 2
    for table in PRIVATE_TABLES:
        assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE user_id=%s").format(sql.Identifier(table)), (o["user"],)).fetchone()["n"] == 0


@pytest.mark.parametrize("operation", ("bind", "store", "sql"))
@pytest.mark.parametrize("switch_first", (True, False))
def test_concurrent_active_revision_fences_bind_store_and_sql(conn, committed_owner, operation, switch_first):
    o = committed_owner
    ready = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            if switch_first:
                switch_revision(conn, o)
                future = pool.submit(other_connection, lambda c: raced_write(c, o, operation), ready)
            else:
                raced_write(conn, o, operation)
                future = pool.submit(other_connection, lambda c: switch_revision(c, o), ready)
            pid = ready.get(timeout=3)
            assert_other_connection_blocked(conn, pid, future)
            conn.commit()
            outcome = future.result(timeout=8)
        finally:
            conn.rollback()
    expected = ("CheckViolation" if operation == "sql" else "SupplyStorageError") if switch_first else "accepted"
    assert outcome == expected
    repo = PostgresPrivateSupplyStorage(conn, user_id=o["user"], expected_epoch=1)
    with pytest.raises(SupplyStorageError):
        repo.store_material(scope_id=o["scope"].id, material_key="after-switch", content_text="revival")
    with pytest.raises(CheckViolation), conn.transaction():
        raced_write(conn, o, "sql")


@pytest.mark.parametrize("where", ("root", "scope", "clause", "minimum"))
def test_shared_blueprint_cannot_hide_private_mapping_or_payload(conn, where):
    a = owner(conn)
    data = shared(conn)
    snapshot = data["blueprint"].model_dump(mode="json")
    target = {"root": snapshot, "scope": snapshot["scope"], "clause": snapshot["clauses"][0], "minimum": snapshot["minimum"]}[where]
    target["private_payload"] = {"user_id": str(a["user"]), "payload_hash": a["version"].payload_hash, "answer": "PRIVATE SECRET"}
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn, "tutor_item_supply_shared_blueprints", blueprint_hash=canonical_hash(snapshot), objective_hash=H,
               matrix_hash=data["blueprint"].matrix_hash, policy_version=P, snapshot_json=snapshot)


def test_shared_policy_cannot_weaken_persisted_v2_gate(conn):
    policy = AutonomousEvidencePolicyV2().model_dump(mode="json")
    for updates in ({"publication_enabled": True}, {"required_review_roles": ["curriculum"]},
                    {"risk_adapter_required": False}, {"independent_second_bundle_required": False},
                    {"private_payload": "SECRET"}):
        with pytest.raises(CheckViolation), conn.transaction():
            insert(conn, "tutor_item_supply_shared_policies", policy_version=P, policy_hash=canonical_hash({**policy, **updates}), policy_json={**policy, **updates})


@pytest.mark.parametrize("where", ("root", "language", "alias", "course", "slice"))
def test_shared_matrix_has_no_private_json_side_channel(conn, where):
    matrix = build_support_matrix().model_dump(mode="json")
    if where == "alias":
        matrix["languages"][0]["aliases"] = [{"private_payload": "SECRET"}]
    else:
        target = {"root": matrix, "language": matrix["languages"][0], "course": matrix["public_course_languages"][0],
                  "slice": matrix["first_batch_slices"][0]}[where]
        target["private_payload"] = {"user_id": str(uuid4()), "payload_hash": H, "answer": "SECRET"}
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn, "tutor_item_supply_shared_matrices", matrix_hash=canonical_hash(matrix), snapshot_json=matrix)


def test_same_owner_different_scope_composite_fks(conn):
    a = owner(conn)
    data = populate(conn, a)
    frozen = a["repo"].bind_scope(track_id=a["track"], revision_id=a["revision"],
                                scope=scope(a["user"]).model_copy(update={"runtime_profile_hash": "b"*64}))
    material = a["repo"].store_material(scope_id=frozen.id, material_key="other-scope-material", content_text="PRIVATE")
    candidate = a["repo"].store_candidate(scope_id=frozen.id, candidate_key="other-scope-candidate", material_id=material)
    version = a["repo"].store_version(scope_id=frozen.id, candidate_id=candidate, version=1, public=a["public"], private=a["private"])
    for table, facts in (
        ("candidates", dict(candidate_key="scope-mismatch", material_id=material)),
        ("candidates", dict(candidate_key="parent-mismatch", parent_candidate_id=candidate)),
        ("versions", dict(candidate_id=candidate, version=2, public_json=a["public"].model_dump(mode="json"), private_json=a["private"].model_dump(mode="json"))),
        ("evidence", dict(job_id=data["job"]["id"], version_id=version.id, item_hash=version.payload_hash,
                          schema_version="item_supply_evidence_v2", policy_version=P, evidence_key="wrong-version-scope",
                          producer_identity="synthetic", evidence_kind="probe", receipt_hash=H)),
    ):
        with pytest.raises(ForeignKeyViolation), conn.transaction():
            insert(conn, "tutor_item_supply_private_"+table, **data["base"], **facts)


@pytest.mark.parametrize("deleting", (False, True))
def test_full_owner_reset_and_delete_rollback_are_atomic(conn, deleting):
    from app.services.repositories.local_user_data_repository import delete_user_data, reset_user_data
    a, b = owner(conn), owner(conn)
    populate(conn, a)
    populate(conn, b)
    before = {t: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(t))).fetchone()["n"]
              for t in PRIVATE_TABLES+SHARED_TABLES}
    with pytest.raises(RuntimeError), conn.transaction():
        (delete_user_data if deleting else reset_user_data)(conn, str(a["user"]))
        raise RuntimeError("caller full-owner rollback")
    after = {t: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(t))).fetchone()["n"]
             for t in PRIVATE_TABLES+SHARED_TABLES}
    assert after == before
    assert conn.execute("SELECT deleted_at FROM users WHERE id=%s", (a["user"],)).fetchone()["deleted_at"] is None
    assert conn.execute("SELECT epoch,enabled FROM tutor_item_supply_user_epochs WHERE user_id=%s", (a["user"],)).fetchone() == dict(epoch=1, enabled=True)
    assert conn.execute("SELECT count(*) AS n FROM item_supply_internal.reset_permits").fetchone()["n"] == 0
    assert a["repo"].get_version(scope_id=a["scope"].id, handle=a["version"].handle) == a["version"]
    assert b["repo"].get_version(scope_id=b["scope"].id, handle=b["version"].handle) == b["version"]


@pytest.mark.parametrize("kind", ("policy", "matrix", "blueprint", "scope", "demand"))
def test_snapshot_hashes_cannot_be_forged_by_direct_sql(conn, kind):
    a = owner(conn)
    data = shared(conn)
    if kind == "policy":
        table = "tutor_item_supply_shared_policies"
        facts = dict(policy_version=P, policy_hash=H, policy_json=AutonomousEvidencePolicyV2().model_dump(mode="json"))
    elif kind == "matrix":
        table = "tutor_item_supply_shared_matrices"
        facts = dict(matrix_hash=H, snapshot_json=build_support_matrix().model_dump(mode="json"))
    elif kind == "blueprint":
        table = "tutor_item_supply_shared_blueprints"
        facts = dict(blueprint_hash="b"*64, objective_hash=H, matrix_hash=data["blueprint"].matrix_hash,
                     policy_version=P, snapshot_json=data["blueprint"].model_dump(mode="json"))
    elif kind == "scope":
        table = "tutor_item_supply_private_scopes"
        facts = dict(user_id=a["user"], epoch=1, track_id=a["track"], revision_id=a["revision"],
                     knowledge_key="python.functions", scope_hash=H, objective_hash=H, snapshot_json=scope(a["user"]).model_dump(mode="json"))
    else:
        table = "tutor_item_supply_private_demands"
        demand = AssessmentSupplyDemandV1(demand_id="synthetic", learner_ref=f"user:{a['user']}", scope=scope(a["user"]),
                 objective_hash=a["scope"].objective_hash, blueprint_hash=H, matrix_hash=build_support_matrix().matrix_hash, policy_version=P, input_revision=1)
        facts = dict(user_id=a["user"], epoch=1, scope_id=a["scope"].id, request_key="forged-demand", demand_hash=H,
                     snapshot_json=demand.model_dump(mode="json"))
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn, table, **facts)
