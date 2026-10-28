from typing import Any, cast
from uuid import uuid4

import pytest
from psycopg import Connection as PgConnection

from app.services.tutor.completion_data import (
    COMPLETION_PRIVATE_TABLES,
    completion_execution_counts,
    export_completion_summary,
    purge_lesson_completion_stages,
)


class Connection:
    def __init__(self, tables: tuple[str, ...]) -> None:
        self.tables = tables
        self.calls: list[tuple[str, object]] = []
        self.rows: list[dict[str, object]] = []

    def execute(self, sql: str, params: object = None) -> Any:
        self.calls.append((sql, params))
        if "to_regclass" in sql:
            self.rows = [{"name": name, "present": name in self.tables} for name in COMPLETION_PRIVATE_TABLES]
        elif "count(*)" in sql:
            self.rows = [{"count": 2}]
        else:
            self.rows = []
        return self

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None


def _connection(conn: Connection) -> PgConnection[dict[str, object]]:
    return cast(PgConnection[dict[str, object]], conn)


def test_legacy_installation_does_not_query_nonexistent_tables() -> None:
    conn = Connection(())
    assert completion_execution_counts(_connection(conn), "user-one") == {}
    purge_lesson_completion_stages(_connection(conn), "user-one")
    assert all("to_regclass" in sql for sql, _params in conn.calls)


def test_inventory_is_scoped_and_exports_no_private_payloads() -> None:
    conn = Connection(COMPLETION_PRIVATE_TABLES)
    result = export_completion_summary(_connection(conn), "user-one")
    assert result["counts"] == dict.fromkeys(COMPLETION_PRIVATE_TABLES, 2)
    assert result["private_requests_results_and_source_units"] == "omitted"
    queries = [(sql, params) for sql, params in conn.calls if "count(*)" in sql]
    assert len(queries) == 3
    assert all("WHERE user_id = %s" in sql and params == ("user-one",) for sql, params in queries)
    assert all("request_json" not in sql and "result_json" not in sql for sql, _ in conn.calls)


def test_lesson_purge_does_not_erase_retained_tutor_history() -> None:
    conn = Connection(COMPLETION_PRIVATE_TABLES)
    purge_lesson_completion_stages(_connection(conn), "user-one")
    deletes = [(sql, params) for sql, params in conn.calls if sql.startswith("DELETE")]
    assert deletes == [("DELETE FROM tutor_lesson_authoring_stage_attempts WHERE user_id = %s", ("user-one",))]


def test_missing_count_is_not_reported_as_zero() -> None:
    class MissingCount(Connection):
        def fetchone(self) -> None:
            return None
    with pytest.raises(ValueError, match="unavailable"):
        completion_execution_counts(_connection(MissingCount(COMPLETION_PRIVATE_TABLES)), "user-one")


def test_completion_tables_are_private_cutover_targets() -> None:
    from app.services.tutor.cutover import CUTOVER_SHARED_TUTOR_TABLES, CUTOVER_TARGET_TUTOR_TABLES

    assert set(COMPLETION_PRIVATE_TABLES) <= CUTOVER_TARGET_TUTOR_TABLES
    assert not set(COMPLETION_PRIVATE_TABLES) & CUTOVER_SHARED_TUTOR_TABLES


@pytest.mark.parametrize("failed_query", ["to_regclass", "count(*)"])
def test_inventory_query_failure_is_not_treated_as_absent_or_zero(failed_query: str) -> None:
    class FailedQuery(Connection):
        def execute(self, sql: str, params: object = None) -> Any:
            if failed_query in sql:
                raise RuntimeError("offline inventory query failed")
            return super().execute(sql, params)

    with pytest.raises(RuntimeError, match="inventory query failed"):
        export_completion_summary(_connection(FailedQuery(COMPLETION_PRIVATE_TABLES)), "user-one")


def test_installed_completion_counts_reach_cutover_target_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tutor import cutover

    class InventoryConnection(Connection):
        def execute(self, sql: str, params: object = None) -> Any:
            result = super().execute(sql, params)
            if "FROM users" in sql:
                self.rows = [{}]
            return result

    conn = InventoryConnection(COMPLETION_PRIVATE_TABLES)
    user_id = str(uuid4())
    service = cutover.HarnessCutoverService(_connection(conn))
    monkeypatch.setattr(service, "_count", lambda *_args: 0)
    monkeypatch.setattr(service, "_legacy_thread_ids", lambda *_args: ())
    monkeypatch.setattr(service, "_checkpoint_inventory", lambda threads: cutover.CheckpointInventory(
        "not_configured", {}, (), threads))
    monkeypatch.setattr(cutover, "actual_d_private_counts", lambda *_args: {})
    inventory = service._inventory(user_id)
    assert inventory.has_target_state
    assert {name: inventory.target_counts[name] for name in COMPLETION_PRIVATE_TABLES} == dict.fromkeys(
        COMPLETION_PRIVATE_TABLES, 2)
    assert all(params == (user_id,) for sql, params in conn.calls if "count(*)" in sql)
    assert not any("DELETE" in sql for sql, _params in conn.calls)
