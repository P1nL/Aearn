"""450 governance regressions; the main session alone owns fixture bootstrap.

No bootstrap, role changes, commit, database creation or global cleanup here.
Every PostgreSQL test checks the dedicated database and rolls back its writes.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row

from app.db.schema import SCHEMA_FRAGMENT_NAMES, load_schema_fragments
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.calibration import (
    CalibrationDecisionV1,
    CalibrationObservationV1,
)
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1
from app.services.learning.item_supply.jobs import CheckpointV1
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.parameter_profiles import (
    ExecutionParameterProfileV1,
    ParameterValuesV1,
    ProfileKeyV1,
)
from app.services.learning.item_supply.policies import (
    RESOURCE_KINDS,
    CoverageObligationV1,
    ResourceAmounts,
    RetryPolicyV1,
    derive_runtime_contract_hash,
)
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.storage_tables import (
    EPOCH_TABLE,
    P3_PRIVATE_TABLES,
    P3_SHARED_TABLES,
    PRIVATE_TABLES,
    SHARED_TABLES,
)
from app.services.repositories.local_user_data_repository import (
    delete_user_data,
    export_user_data,
    reset_user_data,
)
from app.services.tutor.cutover import (
    CUTOVER_SHARED_TUTOR_TABLES,
    CUTOVER_TARGET_TUTOR_TABLES,
)
from tests.learning.test_item_supply_storage import H, P, insert, owner, scope, shared

DSN = "postgresql://postgres:postgres@127.0.0.1:5432/aearn_b1b_fixture_20260930"
ANONYMOUS_USAGE_TABLE = "tutor_item_supply_runtime_global_usage_facts"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    assert os.environ.get("DATABASE_URL") == DSN
    for key, value in (
        ("PYTHON_DOTENV_DISABLED", "1"),
        ("LLM_TYPE", "disabled"),
        ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1"),
    ):
        assert os.environ.get(key) == value
    with psycopg.connect(DSN, row_factory=dict_row) as connection:
        try:
            assert (
                connection.execute("SELECT current_database() AS db").fetchone()["db"]
                == "aearn_b1b_fixture_20260930"
            )
            yield connection
        finally:
            connection.rollback()


def private_runtime(conn):
    # One transaction-wide limit window for both users; runtime itself uses DB clock.
    now = conn.execute("SELECT transaction_timestamp() AS now").fetchone()["now"]
    shared(conn)
    data = owner(conn)
    contract = scope(data["user"])
    demand = AssessmentSupplyDemandV1(
        demand_id=f"schema.{uuid4().hex}",
        learner_ref=f"user:{data['user']}",
        scope=contract,
        objective_hash=data["scope"].objective_hash,
        blueprint_hash=H,
        matrix_hash=build_support_matrix().matrix_hash,
        policy_version=P,
        input_revision=1,
    )
    demand_id = data["repo"].store_demand(
        scope_id=data["scope"].id, request_key=demand.demand_id, demand=demand
    )
    obligation = CoverageObligationV1(
        blueprint_hash=H,
        scope_hash=data["scope"].scope_hash,
        objective_hash=data["scope"].objective_hash,
        purpose=contract.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(contract),
        visibility="private",
        policy_version=P,
        owner_id=data["user"],
    )
    values = ParameterValuesV1(
        connection_timeout_ms=1000,
        first_token_timeout_ms=2000,
        stream_idle_timeout_ms=2000,
        request_timeout_ms=10000,
        stage_deadline_ms=60000,
        parent_deadline_ms=600000,
        discussion_rounds=4,
        revision_rounds=4,
        investigation_rounds=4,
    )
    profile = ExecutionParameterProfileV1(
        profile_key=ProfileKeyV1(
            provider="provider.synthetic",
            model_version=f"model.{uuid4().hex}",
            agent_role="generator",
            item_kind="code",
            risk_tier="medium",
            difficulty="intermediate",
            input_size_bucket="medium",
            runtime="python.v1",
        ),
        version=1,
        state="stable",
        initial=values,
        current=values,
        last_stable=values,
        floor=values,
        ceiling=values,
        measurement_window_started_at=now,
        change_reason="synthetic.schema",
        trusted_initial_evidence=("trusted.synthetic",),
    )
    repo, budget = ItemSupplyRuntimeRepository(conn), ItemSupplyBudgetRepository(conn)
    root = repo.ensure_private_root(
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        demand_id=demand_id,
        obligation=obligation,
        pool="enhancement",
        provider_key="provider.synthetic",
    )
    insert(
        conn,
        "tutor_item_supply_private_budget_windows",
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        root_id=root,
        pool_key="enhancement",
        provider_key="provider.synthetic",
        window_start=now - timedelta(hours=1),
        window_end=now + timedelta(hours=1),
        request_cap=100,
        token_cap=10000,
        resource_cap=10000,
    )
    for resource in RESOURCE_KINDS:
        for dimension, key in (
            ("system", "item-supply"),
            ("provider", "provider.synthetic"),
            ("window", "item-supply"),
            ("pool", "enhancement"),
        ):
            budget.register_global_limit(
                dimension_kind=dimension,
                dimension_key=key,
                resource_kind=resource,
                window_start=now - timedelta(hours=1),
                window_end=now + timedelta(hours=1),
                cap_amount=10000,
            )
        budget.register_user_limit(
            user_id=data["user"],
            epoch=1,
            resource_kind=resource,
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
            cap_amount=10000,
        )
    job = repo.enqueue(
        root_id=root,
        stage_key=f"schema.{uuid4().hex}",
        profile=profile,
        now=now,
        priority=100,
        aging_seconds=60,
        visibility="private",
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        retry_policy=RetryPolicyV1(
            max_transient_attempts=3, initial_backoff_ms=100, maximum_backoff_ms=1000
        ),
    )
    lease = repo.claim(
        root_id=root,
        lease_owner="schema.worker",
        now=now,
        lease_seconds=300,
        visibility="private",
        user_id=data["user"],
        epoch=1,
    )
    assert lease and lease.job_id == job
    repo.checkpoint(
        lease,
        CheckpointV1(
            stage="generating",
            attempt=1,
            status="completed",
            receipt_hash=H,
            safe_reason="synthetic",
        ),
        now=now,
    )
    lease = repo.refresh_lease(lease, now=now)
    reservation = budget.reserve(
        lease=lease,
        reservation_key="schema.reserve",
        amounts=ResourceAmounts(requests=1, input_tokens=10, output_tokens=5),
        now=now,
    )
    assert reservation.allowed and reservation.reservation_id
    budget.settle(
        lease=lease,
        reservation_id=reservation.reservation_id,
        settlement_key="schema.known",
        usage_state="known",
        actual=ResourceAmounts(requests=1, input_tokens=10, output_tokens=5),
        cost_amount=None,
        receipt_hash=H,
    )
    return {
        **data,
        "runtime": repo,
        "budget": budget,
        "lease": lease,
        "profile": profile,
        "now": now,
        "reservation": reservation.reservation_id,
        "root": root,
    }


def rows_for_user(conn, table, user):
    return conn.execute(
        sql.SQL("SELECT * FROM {} WHERE user_id=%s ORDER BY id").format(
            sql.Identifier(table)
        ),
        (user,),
    ).fetchall()


def test_static_450_manifest_classification_and_purge_topology():
    assert SCHEMA_FRAGMENT_NAMES[-1] == "450_learning_item_supply_runtime.sql"
    fragment = load_schema_fragments()[-1].sql
    tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (tutor_[a-z_]+)", fragment))
    assert tables == set(P3_PRIVATE_TABLES) | set(P3_SHARED_TABLES)
    assert not set(P3_PRIVATE_TABLES) & set(P3_SHARED_TABLES)
    assert set(SHARED_TABLES) <= CUTOVER_SHARED_TUTOR_TABLES
    assert set(PRIVATE_TABLES) | {EPOCH_TABLE} <= CUTOVER_TARGET_TUTOR_TABLES
    assert not re.search(r"(?m)^\s*COMMIT\s*;", fragment, re.I)
    purge = fragment.split("CREATE OR REPLACE FUNCTION purge_item_supply_private", 1)[
        1
    ].split("END $$;", 1)[0]
    for table in PRIVATE_TABLES:
        assert f"DELETE FROM {table}" in purge
    for table in (*SHARED_TABLES, EPOCH_TABLE):
        assert f"DELETE FROM {table} " not in purge
    assert purge.index(
        "DELETE FROM tutor_item_supply_private_job_controls"
    ) < purge.index("DELETE FROM tutor_item_supply_private_jobs")
    assert purge.index(
        "DELETE FROM tutor_item_supply_private_obligations"
    ) < purge.index("DELETE FROM tutor_item_supply_private_budget_roots")


@pytest.mark.parametrize(
    "contract,expression",
    [
        (ExecutionParameterProfileV1, "snapshot"),
        (ProfileKeyV1, "snapshot->'profile_key'"),
        (CalibrationObservationV1, "snapshot"),
        (CalibrationDecisionV1, "snapshot"),
    ],
)
def test_static_450_snapshot_keys_cover_current_strict_contract(contract, expression):
    fragment = load_schema_fragments()[-1].sql
    if contract in (ExecutionParameterProfileV1, ProfileKeyV1):
        branch = fragment.split(
            "ELSIF TG_TABLE_NAME='tutor_item_supply_parameter_profiles'", 1
        )[1].split("ELSIF TG_TABLE_NAME=", 1)[0]
    elif contract is CalibrationObservationV1:
        branch = fragment.split(
            "ELSIF TG_TABLE_NAME='tutor_item_supply_profile_observations'", 1
        )[1].split("ELSE", 1)[0]
    else:
        branch = fragment.split("snapshot := NEW.event_json;", 1)[1].split(
            "END IF;", 1
        )[0]
    matcher = re.search(
        re.escape("runtime_snapshot_keys(" + expression)
        + r", ARRAY\[([^\]]*)\], ARRAY\[([^\]]*)\]\)",
        branch,
    )
    assert matcher is not None
    allowed = set(re.findall(r"'([^']+)'", matcher.group(1) + matcher.group(2)))
    assert set(contract.model_fields) == allowed


@pytest.mark.parametrize(
    "field,updates",
    [
        ("current", {"discussion_rounds": 65}),
        ("current", {"connection_timeout_ms": 100_000}),
        ("current", {"parent_deadline_ms": 2_592_000_001}),
        ("floor", {"request_timeout_ms": 11_000}),
        ("ceiling", {"request_timeout_ms": 9000}),
        ("trusted_initial_evidence", []),
    ],
)
def test_pg_450_profile_rejects_self_hashed_invalid_parameter_contract(
    conn, field, updates
):
    data = private_runtime(conn)
    snapshot = data["profile"].model_dump(mode="json")
    snapshot["version"] += 1
    if isinstance(updates, dict):
        snapshot[field].update(updates)
    else:
        snapshot[field] = updates
    with pytest.raises(CheckViolation), conn.transaction():
        insert(
            conn,
            "tutor_item_supply_parameter_profiles",
            profile_key_hash=canonical_hash(snapshot["profile_key"]),
            profile_version=snapshot["version"],
            profile_hash=canonical_hash(snapshot),
            state="stable",
            profile_json=snapshot,
        )


def test_pg_450_inventory_and_privilege_guards(conn):
    actual = {
        r["tablename"]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'tutor_%'"
        )
    }
    assert actual == CUTOVER_SHARED_TUTOR_TABLES | CUTOVER_TARGET_TUTOR_TABLES
    rows = conn.execute(
        "SELECT proconfig,EXISTS(SELECT 1 FROM aclexplode(COALESCE(proacl,acldefault('f',proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute FROM pg_proc WHERE proname LIKE 'enforce_item_supply_runtime_%'"
    ).fetchall()
    assert len(rows) >= 6
    assert all(
        r["proconfig"]
        == ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]
        and not r["public_execute"]
        for r in rows
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM pg_constraint WHERE conname='supply_runtime_allocation_owner_resource'"
        ).fetchone()["n"]
        == 1
    )


@pytest.mark.parametrize("timeout", [False, True])
def test_pg_450_current_observation_including_timeout_parameter_is_storable(
    conn, timeout
):
    from tests.learning.test_item_supply_calibration import profile, observation

    p = profile()
    pid = ItemSupplyRuntimeRepository(conn).register_profile(p)
    updates = (
        dict(
            completed=False,
            right_censored=True,
            termination="timeout",
            timeout_parameter="request_timeout_ms",
        )
        if timeout
        else {}
    )
    o = observation(p, **updates)
    insert(
        conn,
        "tutor_item_supply_profile_observations",
        profile_id=pid,
        observation_key=o.observation_key,
        observation_json=o.model_dump(mode="json"),
    )


@pytest.mark.parametrize("latest_unknown", [False, True])
def test_pg_450_existing_detailed_actuals_are_retained_before_private_reset(
    conn, latest_unknown
):
    data = private_runtime(conn)
    common = dict(
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        reservation_id=data["reservation"],
    )
    known = insert(
        conn,
        "tutor_item_supply_private_runtime_settlements",
        **common,
        sequence=2,
        settlement_key="legacy.known",
        usage_state="known",
        receipt_hash="b" * 64,
    )
    actual = ResourceAmounts(requests=20, input_tokens=30, output_tokens=15)
    for kind, amount in actual.as_dict().items():
        insert(
            conn,
            "tutor_item_supply_private_runtime_settlement_amounts",
            user_id=data["user"],
            epoch=1,
            scope_id=data["scope"].id,
            settlement_id=known["id"],
            resource_kind=kind,
            actual_amount=amount,
        )
    if latest_unknown:
        insert(
            conn,
            "tutor_item_supply_private_runtime_settlements",
            **common,
            sequence=3,
            settlement_key="legacy.unknown",
            usage_state="unknown",
        )
    # Execute only the additive factual INSERT block, not bootstrap/DDL or guard
    # disabling. This simulates pre-anonymous-ledger rows with source truth alive.
    fragment = load_schema_fragments()[-1].sql.split(
        "-- Retain existing detailed usage facts", 1
    )[1]
    block = re.search(r"DO \$\$.*?END \$\$;", fragment, re.S).group()
    conn.execute(block)
    before = conn.execute(
        "SELECT count(*) AS n FROM tutor_item_supply_runtime_global_usage_facts WHERE reservation_id=%s",
        (data["reservation"],),
    ).fetchone()["n"]
    conn.execute(block)
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM tutor_item_supply_runtime_global_usage_facts WHERE reservation_id=%s",
            (data["reservation"],),
        ).fetchone()["n"]
        == before
    )
    assert (
        data["budget"]._effective("private", data["reservation"], "requests", 1) == 20
    )
    reset_user_data(conn, str(data["user"]))
    assert (
        data["budget"]._effective("private", data["reservation"], "requests", 1) == 20
    )


@pytest.mark.parametrize("deleting", [False, True])
def test_pg_450_export_reset_delete_two_owners_and_tombstone(conn, deleting):
    first, second = private_runtime(conn), private_runtime(conn)
    before_shared = {
        table: conn.execute(
            sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
        ).fetchall()
        for table in SHARED_TABLES
    }
    before_other = {
        table: rows_for_user(conn, table, second["user"]) for table in PRIVATE_TABLES
    }
    assert all(before_other[t] for t in P3_PRIVATE_TABLES)
    exported = export_user_data(conn, str(first["user"]))[
        "item_supply_private_summaries"
    ]
    assert set(PRIVATE_TABLES) <= exported.keys()
    serialized = json.dumps(exported, default=str)
    assert (
        str(second["user"]) not in serialized
        and first["version"].payload_hash not in serialized
    )
    for table in P3_PRIVATE_TABLES:
        assert exported[table]["records"]
        assert all(
            set(r) == {"id", "scope_id", "created_at"}
            for r in exported[table]["records"]
        )
    (delete_user_data if deleting else reset_user_data)(conn, str(first["user"]))
    assert all(
        not rows_for_user(conn, table, first["user"]) for table in PRIVATE_TABLES
    )
    assert all(
        rows_for_user(conn, table, second["user"]) == before_other[table]
        for table in PRIVATE_TABLES
    )
    assert all(
        conn.execute(
            sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
        ).fetchall()
        == before_shared[table]
        for table in SHARED_TABLES
    )
    assert conn.execute(
        "SELECT epoch,enabled FROM tutor_item_supply_user_epochs WHERE user_id=%s",
        (first["user"],),
    ).fetchone() == {"epoch": 2, "enabled": not deleting}
    with pytest.raises(CheckViolation), conn.transaction():
        insert(
            conn,
            "tutor_item_supply_private_runtime_user_limits",
            user_id=first["user"],
            epoch=1,
            resource_kind="requests",
            window_start=first["now"],
            window_end=first["now"] + timedelta(hours=1),
            cap_amount=1,
        )


def test_pg_450_private_limit_owner_resource_fk(conn):
    first, second = private_runtime(conn), private_runtime(conn)
    foreign_limit = conn.execute(
        "SELECT id FROM tutor_item_supply_private_runtime_user_limits WHERE user_id=%s AND resource_kind='requests'",
        (second["user"],),
    ).fetchone()["id"]
    wrong_resource = first["budget"].register_user_limit(
        user_id=first["user"],
        epoch=1,
        resource_kind="fetches",
        window_start=first["now"],
        window_end=first["now"] + timedelta(hours=1),
        cap_amount=10,
    )
    for limit in (foreign_limit, wrong_resource):
        with pytest.raises(ForeignKeyViolation), conn.transaction():
            insert(
                conn,
                "tutor_item_supply_private_runtime_reservation_amounts",
                user_id=first["user"],
                epoch=1,
                scope_id=first["scope"].id,
                reservation_id=first["reservation"],
                limit_id=limit,
                resource_kind="requests",
                reserved_amount=1,
            )


@pytest.mark.parametrize("latest_unknown", [False, True])
def test_pg_450_reset_preserves_global_actual_overage(conn, latest_unknown):
    data = private_runtime(conn)
    data["budget"].settle(
        lease=data["lease"],
        reservation_id=data["reservation"],
        settlement_key="schema.overage",
        usage_state="known",
        actual=ResourceAmounts(requests=20, input_tokens=30, output_tokens=15),
        cost_amount=None,
        receipt_hash="e" * 64,
    )
    if latest_unknown:
        data["budget"].settle(
            lease=data["lease"],
            reservation_id=data["reservation"],
            settlement_key="schema.after.overage.unknown",
            usage_state="unknown",
            actual=None,
            cost_amount=None,
            receipt_hash=None,
        )
    limits = conn.execute(
        "SELECT limit_id,resource_kind FROM tutor_item_supply_runtime_global_reservation_amounts WHERE reservation_namespace='private' AND reservation_id=%s ORDER BY limit_id",
        (data["reservation"],),
    ).fetchall()
    before = {
        row["limit_id"]: data["budget"]._global_used(
            row["limit_id"], row["resource_kind"]
        )
        for row in limits
    }
    expected = ResourceAmounts(requests=20, input_tokens=30, output_tokens=15).as_dict()
    assert before == {row["limit_id"]: expected[row["resource_kind"]] for row in limits}
    reset_user_data(conn, str(data["user"]))
    after = {
        row["limit_id"]: data["budget"]._global_used(
            row["limit_id"], row["resource_kind"]
        )
        for row in limits
    }
    # The confirmed private purge must not erase already incurred system/provider cost.
    # This assertion intentionally remains strict pending the budget owner's repair.
    assert after == before


def test_pg_450_anonymous_usage_exact_columns_source_guard_and_retention(conn):
    data = private_runtime(conn)
    columns = {
        row["column_name"]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
            (ANONYMOUS_USAGE_TABLE,),
        )
    }
    assert columns == {
        "id",
        "reservation_namespace",
        "reservation_id",
        "settlement_id",
        "sequence",
        "resource_kind",
        "usage_state",
        "actual_amount",
        "created_at",
    }
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM pg_constraint WHERE conrelid=%s::regclass AND contype='f'",
            (ANONYMOUS_USAGE_TABLE,),
        ).fetchone()["n"]
        == 0
    )
    unique_columns = conn.execute(
        "SELECT array_agg(a.attname ORDER BY k.ord) AS columns FROM pg_constraint c "
        "CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum,ord) "
        "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum "
        "WHERE c.conrelid=%s::regclass AND c.contype='u' GROUP BY c.oid",
        (ANONYMOUS_USAGE_TABLE,),
    ).fetchall()
    assert {tuple(row["columns"]) for row in unique_columns} == {
        ("reservation_namespace", "reservation_id", "sequence", "resource_kind"),
        ("settlement_id", "resource_kind"),
    }
    known = insert(
        conn,
        "tutor_item_supply_private_runtime_settlements",
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        reservation_id=data["reservation"],
        sequence=2,
        settlement_key="schema.fact.known",
        usage_state="known",
        receipt_hash="d" * 64,
    )
    for resource, amount in (("requests", 7), ("input_tokens", 0)):
        insert(
            conn,
            "tutor_item_supply_private_runtime_settlement_amounts",
            user_id=data["user"],
            epoch=1,
            scope_id=data["scope"].id,
            settlement_id=known["id"],
            resource_kind=resource,
            actual_amount=amount,
        )
    facts = dict(
        reservation_namespace="private",
        reservation_id=data["reservation"],
        settlement_id=known["id"],
        sequence=2,
        resource_kind="requests",
        usage_state="known",
        actual_amount=7,
    )
    for change in (
        {"reservation_namespace": "public"},
        {"reservation_id": uuid4()},
        {"settlement_id": uuid4()},
        {"sequence": 3},
        {"resource_kind": "fetches"},
        {"usage_state": "unknown", "actual_amount": None},
        {"actual_amount": None},
        {"actual_amount": -1},
        {"actual_amount": 8},
    ):
        with pytest.raises(CheckViolation), conn.transaction():
            insert(conn, ANONYMOUS_USAGE_TABLE, **{**facts, **change})
    fact = insert(conn, ANONYMOUS_USAGE_TABLE, **facts)
    insert(
        conn,
        ANONYMOUS_USAGE_TABLE,
        **{**facts, "resource_kind": "input_tokens", "actual_amount": 0},
    )
    with pytest.raises(UniqueViolation), conn.transaction():
        insert(conn, ANONYMOUS_USAGE_TABLE, **facts)
    for statement in (
        "UPDATE {} SET actual_amount=actual_amount WHERE id=%s",
        "DELETE FROM {} WHERE id=%s",
    ):
        with pytest.raises(CheckViolation), conn.transaction():
            conn.execute(
                sql.SQL(statement).format(sql.Identifier(ANONYMOUS_USAGE_TABLE)),
                (fact["id"],),
            )
    unknown = insert(
        conn,
        "tutor_item_supply_private_runtime_settlements",
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        reservation_id=data["reservation"],
        sequence=3,
        settlement_key="schema.fact.unknown",
        usage_state="unknown",
    )
    unknown_facts = {
        **facts,
        "settlement_id": unknown["id"],
        "sequence": 3,
        "usage_state": "unknown",
        "actual_amount": None,
    }
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn, ANONYMOUS_USAGE_TABLE, **{**unknown_facts, "actual_amount": 0})
    insert(conn, ANONYMOUS_USAGE_TABLE, **unknown_facts)
    before = conn.execute(
        sql.SQL(
            "SELECT * FROM {} WHERE reservation_namespace='private' AND reservation_id=%s ORDER BY id"
        ).format(sql.Identifier(ANONYMOUS_USAGE_TABLE)),
        (data["reservation"],),
    ).fetchall()
    reset_user_data(conn, str(data["user"]))
    assert (
        conn.execute(
            sql.SQL(
                "SELECT * FROM {} WHERE reservation_namespace='private' AND reservation_id=%s ORDER BY id"
            ).format(sql.Identifier(ANONYMOUS_USAGE_TABLE)),
            (data["reservation"],),
        ).fetchall()
        == before
    )
    assert not rows_for_user(
        conn, "tutor_item_supply_private_runtime_settlements", data["user"]
    )
    # No post-purge stale writer can invent anonymous facts without live source truth.
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn, ANONYMOUS_USAGE_TABLE, **{**facts, "sequence": 4})


def test_pg_450_private_append_only_and_control_identity(conn):
    data = private_runtime(conn)
    for table in P3_PRIVATE_TABLES:
        if table.endswith("_job_controls"):
            continue
        row = rows_for_user(conn, table, data["user"])[0]
        for statement in (
            "UPDATE {} SET created_at=created_at WHERE id=%s",
            "DELETE FROM {} WHERE id=%s",
        ):
            with pytest.raises(CheckViolation), conn.transaction():
                conn.execute(
                    sql.SQL(statement).format(sql.Identifier(table)), (row["id"],)
                )
    for assignment in (
        "parent_deadline=parent_deadline+interval '1 hour'",
        "epoch=epoch+1",
        "profile_snapshot_json=jsonb_set(profile_snapshot_json,'{profile_hash}','\""
        + "f" * 64
        + "\"')",
        "lease_generation=lease_generation+1",
        "state='completed',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL",
    ):
        with pytest.raises(CheckViolation), conn.transaction():
            conn.execute(
                sql.SQL(
                    "UPDATE tutor_item_supply_private_job_controls SET "
                    + assignment
                    + " WHERE job_id=%s"
                ),
                (data["lease"].job_id,),
            )
    with pytest.raises(CheckViolation), conn.transaction():
        conn.execute(
            "DELETE FROM tutor_item_supply_private_job_controls WHERE job_id=%s",
            (data["lease"].job_id,),
        )


def test_pg_450_checkpoint_db_generation_and_expiry_fence(conn):
    data = private_runtime(conn)
    facts = dict(
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        job_id=data["lease"].job_id,
        stage="validating",
        attempt=1,
        status="completed",
        lease_generation=data["lease"].generation + 1,
        receipt_hash=H,
        safe_reason="synthetic",
    )
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn, "tutor_item_supply_private_checkpoints", **facts)
    conn.execute(
        "UPDATE tutor_item_supply_private_job_controls SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE job_id=%s",
        (data["lease"].job_id,),
    )
    with pytest.raises(CheckViolation), conn.transaction():
        conn.execute(
            "UPDATE tutor_item_supply_private_job_controls SET lease_expires_at=clock_timestamp()+interval '1 minute' WHERE job_id=%s",
            (data["lease"].job_id,),
        )
    facts["lease_generation"] = data["lease"].generation
    with pytest.raises(CheckViolation), conn.transaction():
        insert(conn, "tutor_item_supply_private_checkpoints", **facts)


def test_pg_450_unknown_usage_has_no_actual_or_cost(conn):
    data = private_runtime(conn)
    common = dict(
        user_id=data["user"],
        epoch=1,
        scope_id=data["scope"].id,
        reservation_id=data["reservation"],
        sequence=2,
        settlement_key="schema.unknown",
        usage_state="unknown",
    )
    with pytest.raises(CheckViolation), conn.transaction():
        insert(
            conn,
            "tutor_item_supply_private_runtime_settlements",
            **common,
            cost_amount=0,
        )
    unknown = insert(conn, "tutor_item_supply_private_runtime_settlements", **common)
    with pytest.raises(CheckViolation), conn.transaction():
        insert(
            conn,
            "tutor_item_supply_private_runtime_settlement_amounts",
            user_id=data["user"],
            epoch=1,
            scope_id=data["scope"].id,
            settlement_id=unknown["id"],
            resource_kind="requests",
            actual_amount=0,
        )


@pytest.mark.parametrize("nested", [False, True])
def test_pg_450_shared_profile_rejects_private_payload_and_hash(conn, nested):
    data = private_runtime(conn)
    snapshot = data["profile"].model_dump(mode="json")
    snapshot["version"] += 1
    if nested:
        snapshot["profile_key"]["private_content_hash"] = data["version"].payload_hash
    else:
        snapshot["private_owner"] = str(data["user"])
    with pytest.raises(CheckViolation), conn.transaction():
        insert(
            conn,
            "tutor_item_supply_parameter_profiles",
            profile_key_hash=canonical_hash(snapshot["profile_key"]),
            profile_version=snapshot["version"],
            profile_hash=canonical_hash(snapshot),
            state="stable",
            profile_json=snapshot,
        )
    snapshot = data["profile"].model_dump(mode="json")
    snapshot["version"] += 1
    with pytest.raises(CheckViolation), conn.transaction():
        insert(
            conn,
            "tutor_item_supply_parameter_profiles",
            profile_key_hash=data["profile"].profile_key.key_hash,
            profile_version=snapshot["version"],
            profile_hash="f" * 64,
            state="stable",
            profile_json=snapshot,
        )


def test_pg_450_shared_runtime_facts_append_only(conn):
    data = private_runtime(conn)
    for table in (
        "tutor_item_supply_parameter_profiles",
        "tutor_item_supply_runtime_global_limits",
        "tutor_item_supply_runtime_global_reservation_amounts",
    ):
        row = conn.execute(
            sql.SQL("SELECT id FROM {} ORDER BY id LIMIT 1").format(
                sql.Identifier(table)
            )
        ).fetchone()
        assert row
        for statement in (
            "UPDATE {} SET created_at=created_at WHERE id=%s",
            "DELETE FROM {} WHERE id=%s",
        ):
            with pytest.raises(CheckViolation), conn.transaction():
                conn.execute(
                    sql.SQL(statement).format(sql.Identifier(table)), (row["id"],)
                )
    profile_id = conn.execute(
        "SELECT profile_id FROM tutor_item_supply_private_job_controls WHERE job_id=%s",
        (data["lease"].job_id,),
    ).fetchone()["profile_id"]
    for table, key, payload in (
        (
            "tutor_item_supply_profile_observations",
            "observation_key",
            "observation_json",
        ),
        ("tutor_item_supply_profile_events", "event_key", "event_json"),
    ):
        facts = {
            "profile_id": profile_id,
            key: "schema.secret",
            payload: {"private_content_hash": H, "owner_id": str(data["user"])},
        }
        if key == "event_key":
            facts["action"] = "hold"
        with pytest.raises(CheckViolation), conn.transaction():
            insert(conn, table, **facts)
