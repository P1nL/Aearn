"""Seven focused P6 checks; PG is explicit opt-in and main owns bootstrap.

The PG cases below are synthetic storage/ledger tests, not OS execution evidence.
No hard-coded admin DSN, bootstrap, provider, Docker, Attempt or Gate operation.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import inspect
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import CheckViolation, InsufficientPrivilege
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
import pytest

from app.core.config import Settings
from app.db.schema import SCHEMA_FRAGMENT_NAMES
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.jobs import CheckpointV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts, SupplyRuntimeError
from app.services.learning.item_supply.sandbox.contracts import (
    ObservationV2, RunV2, TerminalReceiptV2, run_digest,
)
from app.services.learning.item_supply.sandbox.pipeline import SandboxExecutionPipeline
from app.services.learning.item_supply.sandbox.repository import (
    SANDBOX_DATABASE, SandboxArtifactRepository, SandboxRepository, execution_resources,
)
from app.services.learning.item_supply.storage import export_private_supply, purge_private_supply
from app.services.learning.item_supply.storage_tables import P6_PRIVATE_TABLES, PRIVATE_TABLES, SHARED_TABLES
from app.services.tutor import cutover
from tests.learning.test_item_supply_generation import SyntheticAuthority
from tests.learning.test_item_supply_pipeline import Provider, private_pipeline


class SandboxFixtureProvider(Provider):
    provider_key = "synthetic"
    configured_model = "fixture"


class ClockOnly:
    def execute(self, query: str) -> Any:
        assert query == "SELECT clock_timestamp() AS now"
        return SimpleNamespace(fetchone=lambda: {"now": datetime.now(UTC)})


def test_execution_only_shape_is_exact_and_does_not_invent_usage() -> None:
    assert execution_resources(ResourceAmounts(execution_seconds=5)).requests == 0
    for value in (ResourceAmounts(), ResourceAmounts(execution_seconds=1, requests=1),
                  ResourceAmounts(execution_seconds=1, input_tokens=1),
                  ResourceAmounts(execution_seconds=1, fetches=1)):
        with pytest.raises(SupplyRuntimeError, match="EXECUTION_ONLY_RESOURCE_SHAPE_REQUIRED"):
            execution_resources(value)


def test_default_p3_reserve_still_rejects_zero_request_and_tokens() -> None:
    result = ItemSupplyBudgetRepository(ClockOnly()).reserve(  # type: ignore[arg-type]
        lease=None, reservation_key="execution.pure",  # type: ignore[arg-type]
        amounts=ResourceAmounts(execution_seconds=5), now=datetime.now(UTC))
    assert result.allowed is False
    assert result.reason == "LEGACY_ENVELOPE_REQUIRES_REQUEST_AND_TOKEN"


def test_disabled_or_active_transaction_never_calls_executor() -> None:
    conn = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS))
    pipeline = SandboxExecutionPipeline(conn, Settings.model_validate(  # type: ignore[arg-type]
        {"learning_item_supply_enabled": False}))
    assert pipeline.prepare_execution(lease=None, scope_id=uuid4(), artifact_id=uuid4(),  # type: ignore[arg-type]
        mode="synthetic", execution_port=None, actor_id=uuid4()) is None  # type: ignore[arg-type]
    with pytest.raises(PipelineRepositoryError, match="EXECUTOR_IO_REQUIRES_IDLE_TRANSACTION"):
        pipeline.run_execution(None, None)  # type: ignore[arg-type]


def test_470_is_explicit_private_inventory_and_children_first_purge() -> None:
    fragment = "470_learning_item_supply_sandbox_execution.sql"
    assert fragment in SCHEMA_FRAGMENT_NAMES
    assert len(P6_PRIVATE_TABLES) == 3
    assert set(P6_PRIVATE_TABLES) <= set(PRIVATE_TABLES)
    schema_dir = Path(__file__).parents[2] / "app/db/schema"
    sql = (schema_dir / fragment).read_text(encoding="utf-8")
    assert "NEW.requests<>0 OR NEW.tokens<>0 OR NEW.resources<>0" in sql
    assert "check_execution_intent(i.id)" in sql
    # P3 stores values inside the frozen profile envelope, not at its root.
    assert "c.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms'" in sql
    assert "c.profile_snapshot_json->'values'" not in sql
    assert "ALTER TABLE tutor_item_supply_shared_reservations" not in sql
    purge = sql[sql.index("CREATE OR REPLACE FUNCTION purge_item_supply_private"):]
    assert purge.index("DELETE FROM tutor_item_supply_private_sandbox_observations") < purge.index(
        "DELETE FROM tutor_item_supply_private_sandbox_runs") < purge.index(
        "DELETE FROM tutor_item_supply_private_execution_intents") < purge.index(
        "DELETE FROM tutor_item_supply_private_generation_artifacts")
    facts_table = "tutor_item_supply_private_admission_facts"
    assert facts_table in PRIVATE_TABLES and facts_table not in SHARED_TABLES
    assert facts_table in cutover.CUTOVER_TARGET_TUTOR_TABLES
    assert facts_table not in cutover.CUTOVER_SHARED_TUTOR_TABLES
    assert sum(name == facts_table for name, _ in cutover._TARGET_COUNT_SQL) == 1
    # Existing projection is tuple-derived and does not read private payloads.
    projection = inspect.getsource(export_private_supply)
    assert "for table in PRIVATE_TABLES:" in projection
    assert all(field not in projection for field in ("payload_json", "hidden", "stdout"))
    facts_sql = (schema_dir / "481_learning_item_supply_admission_facts.sql").read_text(encoding="utf-8")
    assert "REFERENCES tutor_item_supply_private_generation_artifacts" in facts_sql
    assert "ON DELETE CASCADE" in facts_sql
    assert "enforce_item_supply_immutable('private')" in facts_sql
    assert "GRANT EXECUTE" not in facts_sql


@pytest.fixture
def sandbox_conn() -> Iterator[Connection[dict[str, Any]]]:
    if os.environ.get("AEARN_P6_POSTGRES_TESTS") != "1":
        pytest.skip("main-owned P6 PostgreSQL tests not enabled")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.fail("P6 database URL required", pytrace=False)
    facts = conninfo_to_dict(dsn)
    if facts.get("dbname") != SANDBOX_DATABASE:
        pytest.fail("exact P6 disposable database required", pytrace=False)
    connection = psycopg.connect(dsn, row_factory=dict_row)
    connection.execute("SELECT 1")  # All inner transactions are rollback-safe savepoints.
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def fixture_intent(conn: Connection[dict[str, Any]]) -> Any:
    fx = private_pipeline(conn)
    conn.execute("UPDATE users SET display_name=%s WHERE id=%s", (f"sandbox.p6.{fx.user}", fx.user))
    artifacts = SandboxArtifactRepository(conn)
    # Offline typed candidate fixture; not a provider call or live RAG receipt.
    result = generate_candidate(fx.request, provider=SandboxFixtureProvider(fx.payload),
                                source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged", result.safe_summary()
    row = artifacts.store_generation(lease=fx.lease, scope_id=fx.scope.id,
        request=fx.request, result=result, artifact_key=f"fixture.{uuid4().hex}",
        now=datetime.now(UTC), mode="synthetic")
    fx.pipeline.runtime.checkpoint(fx.lease, CheckpointV1(stage="generating", attempt=1,
        status="completed", receipt_hash=row["artifact_hash"], safe_reason="candidate_staged"), now=datetime.now(UTC))
    fx.lease = fx.pipeline.runtime.refresh_lease(fx.lease, now=datetime.now(UTC))
    # A completed generating checkpoint advances the stage, not the lease state.
    assert fx.pipeline.runtime.next_stage(fx.lease) == "validating"
    assert fx.pipeline.runtime._control(fx.lease, now=datetime.now(UTC))["state"] == "leased"
    repository = SandboxRepository(conn)
    intent = repository.create_intent(lease=fx.lease, scope_id=fx.scope.id, artifact=row,
        reservation_key=f"execution.{UUID(str(row['id'])).hex}",
        resources=ResourceAmounts(execution_seconds=20), now=datetime.now(UTC))
    reserved = fx.pipeline.budget.reserve_execution(lease=fx.lease, intent_id=intent.id, now=datetime.now(UTC))
    assert reserved.allowed and reserved.reservation_id is not None
    fx.intent, fx.reservation_id, fx.repository = intent, reserved.reservation_id, repository
    return fx


def test_pg_zero_headers_use_original_resource_reservation_and_unknown_settlement(sandbox_conn: Connection[dict[str, Any]]) -> None:
    fx = fixture_intent(sandbox_conn)
    budget = fx.pipeline.budget
    repeated = budget.reserve_execution(lease=fx.lease, intent_id=fx.intent.id, now=datetime.now(UTC))
    assert repeated.reservation_id == fx.reservation_id and repeated.reason == "REPLAY"
    row = sandbox_conn.execute("SELECT requests,tokens,resources FROM tutor_item_supply_private_reservations WHERE id=%s",
                               (fx.reservation_id,)).fetchone()
    assert row == {"requests": 0, "tokens": 0, "resources": 0}
    amounts = budget._reservation_amounts(fx.lease, fx.reservation_id)
    assert amounts == ResourceAmounts(execution_seconds=20).as_dict()
    first = budget.settle(lease=fx.lease, reservation_id=fx.reservation_id, settlement_key="execution.fixture",
        usage_state="unknown", actual=None, cost_amount=None, receipt_hash=None)
    second = budget.settle(lease=fx.lease, reservation_id=fx.reservation_id, settlement_key="execution.fixture",
        usage_state="unknown", actual=None, cost_amount=None, receipt_hash=None)
    assert first == second
    settlement_count = sandbox_conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=%s",
                                            (fx.reservation_id,)).fetchone()
    assert settlement_count is not None and settlement_count["n"] == 1


def test_pg_forged_zero_header_or_old_intent_cannot_bypass_guard(sandbox_conn: Connection[dict[str, Any]]) -> None:
    fx = fixture_intent(sandbox_conn)
    with pytest.raises(CheckViolation), sandbox_conn.transaction():
        sandbox_conn.execute(
            "INSERT INTO tutor_item_supply_private_reservations(user_id,epoch,scope_id,root_id,window_id,job_id,lease_generation,reservation_key,requests,tokens,resources) "
            "SELECT user_id,epoch,scope_id,root_id,window_id,job_id,lease_generation,'execution.forged',0,0,0 "
            "FROM tutor_item_supply_private_reservations WHERE id=%s", (fx.reservation_id,))
    with pytest.raises(CheckViolation), sandbox_conn.transaction():
        sandbox_conn.execute("UPDATE tutor_item_supply_private_execution_intents SET content_hash=%s WHERE id=%s",
                             ("0" * 64, fx.intent.id))
    sandbox_conn.execute("UPDATE tutor_item_supply_private_job_controls SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE job_id=%s",
                         (fx.lease.job_id,))
    with pytest.raises(SupplyRuntimeError):
        fx.pipeline.budget.reserve_execution(lease=fx.lease, intent_id=fx.intent.id, now=datetime.now(UTC))


class SyntheticTerminalAuthority:
    def __init__(self, receipt: TerminalReceiptV2) -> None:
        self.receipt = receipt
        self.verifications = 0

    def resolve(self, **kwargs: Any) -> TerminalReceiptV2:
        return self.receipt

    def verify(self, *, run: RunV2, receipt: TerminalReceiptV2) -> bool:
        self.verifications += 1
        return receipt == self.receipt and receipt.run_hash == run_digest(run)


def test_pg_observation_exact_replay_and_origin_mutation_rejected(sandbox_conn: Connection[dict[str, Any]]) -> None:
    fx = fixture_intent(sandbox_conn)
    control = sandbox_conn.execute("INSERT INTO users(display_name) VALUES('P6 unchanged control') RETURNING *").fetchone()
    assert control is not None
    run = RunV2(source_run=uuid4(), namespace=fx.intent.actor_namespace, tenant_id=fx.user,
        actor_id=uuid4(), scope_hash=fx.scope.scope_hash, content_hash=fx.intent.content_hash,
        profile_hash=fx.intent.profile_hash, origin="simulation")
    terminal = TerminalReceiptV2(terminal_receipt_id=uuid4(), source_run=run.source_run,
        run_hash=run_digest(run), scenario="typical_error", attempt=1, origin="simulation",
        outcome="incorrect", authority_kind="sandbox_scenario", authority_identity="fixture.synthetic",
        evidence_hash="a" * 64, duration_ms=1)
    observation = ObservationV2(run=run, terminal_receipt=terminal)
    authority = SyntheticTerminalAuthority(terminal)
    fx.repository.record_run(intent=fx.intent, reservation_id=fx.reservation_id, run=run,
        executor_receipts=(), observations=(observation,), resolver=authority)
    first = fx.repository.record_observation(user_id=fx.user, epoch=1, scope_id=fx.scope.id,
        observation=observation, resolver=authority)
    replay = fx.repository.record_observation(user_id=fx.user, epoch=1, scope_id=fx.scope.id,
        observation=observation, resolver=authority)
    assert first == replay and authority.verifications >= 3
    observation_count = sandbox_conn.execute("SELECT count(*) AS n FROM tutor_item_supply_private_sandbox_observations WHERE source_run=%s",
                                             (run.source_run,)).fetchone()
    assert observation_count is not None and observation_count["n"] == 1
    with pytest.raises(CheckViolation), sandbox_conn.transaction():
        sandbox_conn.execute("UPDATE tutor_item_supply_private_sandbox_observations SET origin='deterministic_probe' WHERE id=%s", (first,))
    summary = fx.repository.observation_summary(user_id=fx.user, epoch=1, scope_id=fx.scope.id,
                                               run=run, resolver=authority)
    assert (summary.sample_count, summary.terminal_count, summary.completed_count) == (1, 1, 1)
    assert summary.origin == "simulation" and summary.passed_count == 0
    # Existing export remains an opaque ID/scope/time inventory, not raw source.
    exported = export_private_supply(sandbox_conn, fx.user)
    for table in P6_PRIVATE_TABLES:
        inventory = exported[table]
        assert isinstance(inventory, dict) and inventory["records"]
        assert set(inventory["records"][0]) == {"id", "scope_id", "created_at"}
    maintenance = sandbox_conn.execute(
        "SELECT has_function_privilege(current_user,'purge_item_supply_private(uuid,boolean)','EXECUTE') AS allowed"
    ).fetchone()
    assert maintenance is not None
    if maintenance["allowed"]:
        assert purge_private_supply(sandbox_conn, fx.user) == 2
        for table in P6_PRIVATE_TABLES:
            private_count = sandbox_conn.execute(f"SELECT count(*) AS n FROM {table} WHERE user_id=%s", (fx.user,)).fetchone()
            assert private_count is not None and private_count["n"] == 0
        with pytest.raises(ValueError):
            fx.repository.read_observations(user_id=fx.user, epoch=1, scope_id=fx.scope.id,
                                            run=run, resolver=authority)
    else:
        # Ordinary runtime is NOT maintenance. Do not grant privilege in a test.
        with pytest.raises(InsufficientPrivilege), sandbox_conn.transaction():
            purge_private_supply(sandbox_conn, fx.user)
    assert sandbox_conn.execute("SELECT * FROM users WHERE id=%s", (control["id"],)).fetchone() == control
