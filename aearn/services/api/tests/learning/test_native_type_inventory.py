"""Pure private inventory/export contract checks; no database authority."""
from datetime import UTC, datetime
from contextlib import nullcontext
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.tutor import cutover
from app.services.learning.item_supply.storage import export_private_supply
from app.services.learning.item_supply.storage_tables import (
    NATIVE_TYPE_UNSCOPED_TABLES,
    P7_NATIVE_TYPE_EVIDENCE_TABLES,
    P7_NATIVE_TYPE_EXPOSURE_TABLES,
    PRIVATE_TABLES,
    SHARED_TABLES,
)
from app.services.tutor.cutover import CUTOVER_TARGET_TUTOR_TABLES


def test_native_type_private_inventory_not_shared_audit():
    tables = (*P7_NATIVE_TYPE_EXPOSURE_TABLES, *P7_NATIVE_TYPE_EVIDENCE_TABLES)
    assert len(tables) == len(set(tables)) == 7
    assert all(PRIVATE_TABLES.count(table) == 1 for table in tables)
    assert set(tables) <= CUTOVER_TARGET_TUTOR_TABLES
    assert set(tables).isdisjoint(SHARED_TABLES)
    assert len(NATIVE_TYPE_UNSCOPED_TABLES) == 5


class _EmptyRows:
    def fetchall(self):
        return []

    def fetchone(self):
        return None


class _ExportConnection:
    """Records generated SQL only; deliberately no psycopg connection."""
    def __init__(self):
        self.queries = []

    def execute(self, query, parameters):
        self.queries.append((query if isinstance(query, str) else query.as_string(None), parameters))
        return _EmptyRows()


def test_native_type_export_never_selects_source_or_receipt_payloads():
    conn, user = _ExportConnection(), uuid4()
    result = export_private_supply(conn, user)  # type: ignore[arg-type]
    for table in (*P7_NATIVE_TYPE_EXPOSURE_TABLES, *P7_NATIVE_TYPE_EVIDENCE_TABLES):
        assert result[table] == {"records": [], "truncated": False}
        rows = [(sql, args) for sql, args in conn.queries if f'FROM "{table}" ' in sql]
        assert len(rows) == 1
        sql, args = rows[0]
        assert args == (user,)
        assert "WHERE user_id=%s" in sql and "LIMIT 1001" in sql
        assert "created_at" in sql
        assert ("NULL::uuid AS scope_id" in sql) == (table in NATIVE_TYPE_UNSCOPED_TABLES)
        assert not any(field in sql for field in ("payload_json", "content_json", "snapshot_json", "bindings_json"))


def test_native_type_export_row_is_only_opaque_identity_and_time():
    class OneRow(_EmptyRows):
        def fetchall(self):
            return [{"id": uuid4(), "scope_id": None, "created_at": datetime(2026, 10, 6, tzinfo=UTC)}]

    class OneRowConnection(_ExportConnection):
        def execute(self, query, parameters):
            self.queries.append((query if isinstance(query, str) else query.as_string(None), parameters))
            return OneRow()

    result = export_private_supply(OneRowConnection(), uuid4())  # type: ignore[arg-type]
    for table in NATIVE_TYPE_UNSCOPED_TABLES:
        assert set(result[table]["records"][0]) == {"id", "scope_id", "created_at"}


_BIRTH = "tutor_item_supply_native_exposure_births"
_CONTAMINATION = (
    "tutor_item_supply_native_exposure_inbox",
    "tutor_item_supply_native_exposure_watermarks",
    "tutor_item_supply_native_content_facts",
)


def _birth_cutover_decision(monkeypatch, extra_table=None):
    """Execute the generated count predicates locally; original decision flow.

    Only unrelated inventory and receipt persistence are offline doubles. This
    is not PostgreSQL/reset acceptance and never opens a configured database.
    """
    user = str(uuid4())
    queries = dict(cutover._TARGET_COUNT_SQL)
    with sqlite3.connect(":memory:") as counts:
        for table in (_BIRTH, *_CONTAMINATION):
            counts.execute(f"CREATE TABLE {table} (user_id TEXT)")
        counts.execute(f"INSERT INTO {_BIRTH} VALUES (?)", (user,))
        if extra_table is not None:
            counts.execute(f"INSERT INTO {extra_table} VALUES (?)", (user,))
        tracked = {queries[t] for t in (_BIRTH, *_CONTAMINATION)}

        def count(query, owner):
            if query not in tracked:
                return 0
            return counts.execute(query.replace("::int", "").replace("%s", "?"), (owner,)).fetchone()[0]

        conn = SimpleNamespace(transaction=nullcontext,
            execute=lambda *a: SimpleNamespace(fetchone=lambda: {}))
        service = cutover.HarnessCutoverService(conn)  # type: ignore[arg-type]
        # Recheck the same previously blocked owner, rather than bypass its gate.
        record = {"user_id": user, "state": "blocked_target_state"}
        monkeypatch.setattr(service, "_lock_active_user", lambda *a, **k: {})
        monkeypatch.setattr(service, "_ensure_record_locked", lambda *a: record)
        monkeypatch.setattr(service, "_load_record_locked", lambda *a: record)
        monkeypatch.setattr(service, "_mark_verified_locked", lambda r, **k: r.update(state="verified"))
        monkeypatch.setattr(service, "_mark_blocked_locked", lambda r, **k: r.update(state=k["state"]))
        monkeypatch.setattr(service, "_count", count)
        monkeypatch.setattr(service, "_legacy_thread_ids", lambda *a: ())
        monkeypatch.setattr(service, "_checkpoint_inventory", lambda threads: cutover.CheckpointInventory(
            "not_configured", {}, (), threads))
        monkeypatch.setattr(cutover, "actual_d_private_counts", lambda *a: {})
        inventory = service._inventory(user)
        result = service.get_decision(user_id=user)
        assert counts.execute(f"SELECT count(*) FROM {_BIRTH}").fetchone()[0] == 1
        return inventory, result


def test_birth_only_user_initializes_without_reclassifying_or_deleting_birth(monkeypatch):
    inventory, result = _birth_cutover_decision(monkeypatch)
    assert inventory.target_counts[_BIRTH] == 0
    assert result["state"] == "verified"
    assert PRIVATE_TABLES.count(_BIRTH) == 1
    assert _BIRTH in cutover.CUTOVER_TARGET_TUTOR_TABLES
    assert _BIRTH not in cutover.CUTOVER_SHARED_TUTOR_TABLES | cutover.CUTOVER_RETAINED_TUTOR_TABLES
    assert set(PRIVATE_TABLES) <= cutover.CUTOVER_TARGET_TUTOR_TABLES
    assert cutover.CUTOVER_TARGET_TUTOR_TABLES.isdisjoint(cutover.CUTOVER_SHARED_TUTOR_TABLES)


@pytest.mark.parametrize("table", _CONTAMINATION)
def test_birth_does_not_hide_real_private_target_state(monkeypatch, table):
    inventory, result = _birth_cutover_decision(monkeypatch, table)
    assert inventory.target_counts[table] == 1
    assert result["state"] == "blocked_target_state"
    assert result["code"] == "CUTOVER_TARGET_STATE_PRESENT"
