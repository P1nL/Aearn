"""Offline guards + explicitly scoped PostgreSQL tests of the real cutover owner."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import psycopg
from psycopg.rows import dict_row
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_preflight as preflight

NAME = "aearn_rag260_c_d_gatefixture_unit"
SUMMARY = {"schema_ready": True, "worker_import_ready": True, "legacy_post_tombstone": True,
           "snapshot_history_readable": True, "legacy_nonterminal": 0, "active_legacy_leases": 0,
           "ambiguous_effects": 0}


class FakeConnection:
    """Only unit orchestration fake, never live gate evidence."""
    autocommit = False

    def __init__(self, *, name=NAME, audit=True):
        self.name, self.audit, self.statements = name, audit, []

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if "current_database" in sql:
            return SimpleNamespace(fetchone=lambda: {"name": self.name})
        return SimpleNamespace(fetchall=lambda: ([{"kind": k, "state": s} for k, s in (
            ("preparing", "preparing"), ("preflight", "ready"), ("enabled", "enabled"))] if self.audit else []))


class FakeService:
    def __init__(self, *, enabled=False, summary=None):
        self.calls = []
        self.summary = deepcopy(SUMMARY if summary is None else summary)
        self.state, self.generation = ("enabled", 1) if enabled else ("idle", 0)

    def _lock(self):
        self.calls.append("lock")

    def dry_run(self):
        self.calls.append("dry_run")
        return {"summary": self.summary, "would_block": False}

    def status(self, *, settings):
        assert settings.llm_type == "disabled" and settings.rag_evidence_consumer_enabled is False
        return {"state": self.state, "generation": self.generation, "summary_hash": "a" * 64,
                "effective_enabled": self.state == "enabled", "cutover_version": "test-owner-v1"}

    def prepare(self, *, expected_generation, idempotency_key):
        self.calls.append("prepare")
        assert expected_generation == self.generation
        self.state, self.generation = "ready", self.generation + 1
        return {"state": "ready", "generation": self.generation, "summary_hash": "a" * 64}

    def enable(self, *, expected_generation, summary_hash, idempotency_key):
        self.calls.append("enable")
        assert expected_generation == self.generation and summary_hash == "a" * 64
        self.state = "enabled"

    def assert_mutation_allowed(self, *, settings):
        self.calls.append("assert_mutation_allowed")
        assert self.state == "enabled" and settings.tutor_thread_turn_v2_enabled


def inject(monkeypatch, service):
    from app.services.tutor import thread_turn_cutover
    monkeypatch.setattr(thread_turn_cutover, "TutorThreadTurnCutoverService", lambda _: service)
    from app.services.llm.llm_client import OpenAICompatibleClient
    monkeypatch.setattr(OpenAICompatibleClient, "complete_json", lambda *_a, **_k: pytest.fail("provider called"))


def test_default_off_has_zero_connection_or_file_access(monkeypatch):
    monkeypatch.setattr(preflight.psycopg, "connect", lambda *_a, **_k: pytest.fail("DB called"))
    with pytest.raises(preflight.PreflightDenied, match="DEFAULT_OFF"):
        preflight.run(SimpleNamespace(execute=False, database_name=NAME, operation_id="unit-gate"))


@pytest.mark.parametrize("name", ["postgres", "aearn_d", "aearn_rag260_c_live_history", "aearn_rag260_c_d_", NAME + "/x"])
def test_database_name_guard(name):
    with pytest.raises(preflight.PreflightDenied, match="DATABASE_DENIED"):
        preflight.guard_request(execute=True, database_name=name, operation_id="unit-gate")


def test_declared_config_dsn_must_all_match():
    config = {"approved": True, "database_name": NAME}
    with pytest.raises(preflight.PreflightDenied, match="DATABASE_DENIED"):
        preflight.guard_config(config, "dbname=postgres", database_name=NAME)
    with pytest.raises(preflight.PreflightDenied, match="CONTROL_CONFIG_DENIED"):
        preflight.guard_config(config, "dbname=" + NAME, database_name=NAME + "_other")
    preflight.guard_config(config, "dbname=" + NAME, database_name=NAME)


def test_wrong_actual_database_precedes_service_owner(monkeypatch):
    service = FakeService()
    inject(monkeypatch, service)
    with pytest.raises(preflight.PreflightDenied, match="DATABASE_DENIED"):
        preflight.execute_on_connection(FakeConnection(name="postgres"), execute=True,
                                        database_name=NAME, operation_id="unit-gate")
    assert service.calls == []


def test_only_real_owner_methods_can_transition(monkeypatch):
    service, conn = FakeService(), FakeConnection()
    inject(monkeypatch, service)
    result = preflight.execute_on_connection(conn, execute=True, database_name=NAME, operation_id="unit-gate")
    assert result["status"] == "enabled_by_service" and result["model_calls"] == 0
    assert service.calls == ["lock", "dry_run", "prepare", "enable", "assert_mutation_allowed"]
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "TRUNCATE")) for sql in conn.statements)


@pytest.mark.parametrize("field,value,code", [("worker_import_ready", False, "CUTOVER_DEPENDENCIES_NOT_READY"),
    ("legacy_nonterminal", 1, "CUTOVER_LEGACY_WORK_PRESENT"),
    ("active_legacy_leases", 1, "CUTOVER_LEGACY_WORK_PRESENT"),
    ("ambiguous_effects", 1, "CUTOVER_LEGACY_WORK_PRESENT")])
def test_dirty_or_unready_inventory_never_prepares(monkeypatch, field, value, code):
    summary = {**SUMMARY, field: value}
    service = FakeService(summary=summary)
    inject(monkeypatch, service)
    with pytest.raises(preflight.PreflightDenied, match=code):
        preflight.execute_on_connection(FakeConnection(), execute=True, database_name=NAME, operation_id="unit-gate")
    assert "prepare" not in service.calls and "enable" not in service.calls


def test_already_enabled_requires_owner_audit_and_does_not_reenable(monkeypatch):
    service = FakeService(enabled=True)
    inject(monkeypatch, service)
    result = preflight.execute_on_connection(FakeConnection(), execute=True, database_name=NAME, operation_id="unit-gate")
    assert result["status"] == "already_enabled_verified"
    assert "prepare" not in service.calls and "enable" not in service.calls
    with pytest.raises(preflight.PreflightDenied, match="CUTOVER_SERVICE_AUDIT_MISSING"):
        preflight.execute_on_connection(FakeConnection(audit=False), execute=True,
                                        database_name=NAME, operation_id="unit-gate")


@pytest.fixture
def pg():
    dsn = os.getenv("AEARN_RAG_D_GATE_FIXTURE_DSN")
    if not dsn:
        pytest.skip("dedicated gate fixture DB not explicitly provided")
    expected = psycopg.conninfo.conninfo_to_dict(dsn).get("dbname", "")
    if not expected.startswith("aearn_rag260_c_d_gatefixture_"):
        pytest.fail("refusing non-gate-fixture DB")
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3) as conn:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == expected
        yield conn, expected
        conn.rollback()


def test_pg_owner_enable_repeat_and_audit(pg):
    conn, name = pg
    from app.core.config import Settings
    from app.services.tutor.thread_turn_cutover import TutorThreadTurnCutoverService
    result = preflight.execute_on_connection(conn, execute=True, database_name=name, operation_id="pg-owner-enable")
    conn.commit()
    assert result["effective_enabled"] is True and result["summary_hash"] != "0" * 64
    assert {"preparing", "preflight", "enabled"} <= set(result["audit_event_kinds"])
    before = conn.execute("SELECT count(*) AS n FROM tutor_thread_turn_cutover_events").fetchone()["n"]
    repeated = preflight.execute_on_connection(conn, execute=True, database_name=name, operation_id="pg-owner-enable")
    assert repeated["status"] == "already_enabled_verified" and repeated["generation"] == result["generation"]
    assert conn.execute("SELECT count(*) AS n FROM tutor_thread_turn_cutover_events").fetchone()["n"] == before
    TutorThreadTurnCutoverService(conn).assert_mutation_allowed(settings=Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True))


def test_pg_actual_enable_denial_rolls_back_preflight(pg, monkeypatch):
    conn, name = pg
    from app.services.tutor.thread_turn_cutover import TutorThreadTurnCutoverService
    from app.services.tutor.cutover import CutoverError
    service = TutorThreadTurnCutoverService(conn)
    status = service.status()
    service.rollback(expected_generation=int(status["generation"]), idempotency_key="pg-test-rollback")
    before = conn.execute("SELECT state,generation,summary_hash FROM tutor_thread_turn_cutovers").fetchone()
    events = conn.execute("SELECT count(*) AS n FROM tutor_thread_turn_cutover_events").fetchone()["n"]
    real_enable = TutorThreadTurnCutoverService.enable
    def wrong_hash(self, **kwargs):
        return real_enable(self, **{**kwargs, "summary_hash": "0" * 64})
    monkeypatch.setattr(TutorThreadTurnCutoverService, "enable", wrong_hash)
    with pytest.raises(CutoverError) as error:
        preflight.execute_on_connection(conn, execute=True, database_name=name, operation_id="pg-failure")
    assert error.value.code == "TUTOR_CUTOVER_NOT_READY"
    assert conn.execute("SELECT state,generation,summary_hash FROM tutor_thread_turn_cutovers").fetchone() == before
    assert conn.execute("SELECT count(*) AS n FROM tutor_thread_turn_cutover_events").fetchone()["n"] == events


def test_pg_actual_service_rejects_stale_generation(pg):
    conn, _name = pg
    from app.services.tutor.thread_turn_cutover import TutorThreadTurnCutoverService
    from app.services.tutor.cutover import CutoverError
    service = TutorThreadTurnCutoverService(conn)
    status = service.status()
    ready = service.rollback(expected_generation=int(status["generation"]), idempotency_key="pg-test-stale")
    with pytest.raises(CutoverError) as error:
        service.enable(expected_generation=int(ready["generation"]) - 1,
                       summary_hash=str(ready["summary_hash"]), idempotency_key="pg-stale-enable")
    assert error.value.code == "TUTOR_CUTOVER_GENERATION_CONFLICT"
    assert service.status()["state"] == "ready"
