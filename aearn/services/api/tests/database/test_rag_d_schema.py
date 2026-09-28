"""D additive schema checks, never a business database or provider."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema
from app.db.schema import load_schema_fragments


def test_fragment_exists_once_and_preserves_existing_authority() -> None:
    names = [fragment.name for fragment in load_schema_fragments()]
    assert names.count("370_rag_plan_material_bindings.sql") == 1
    fragment = next(f.sql for f in load_schema_fragments()
                    if f.name == "370_rag_plan_material_bindings.sql")
    assert "CREATE TABLE IF NOT EXISTS rag_material_selections" in fragment
    assert "CREATE TABLE IF NOT EXISTS rag_plan_material_bindings" in fragment
    assert "tutor_learning_track_purge_allowed" in fragment
    assert "CREATE TABLE IF NOT EXISTS grounding_corpus" not in fragment
    assert "ON DELETE CASCADE" not in fragment


def test_disposable_schema_bootstraps_twice_and_has_scoped_fks() -> None:
    dsn = os.environ.get("AEARN_RAG_D_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("D schema requires explicitly disposable PostgreSQL")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_d_"):
        pytest.fail("D schema refuses non-aearn_rag260_c_d_ database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == name
        apply_schema(conn)
        apply_schema(conn)
        constraints = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid IN "
            "('rag_material_selections'::regclass,'rag_plan_material_bindings'::regclass)"
        ).fetchall()
        names = {str(r["conname"]) for r in constraints}
        assert {"fk_rag_d_selection_draft", "fk_rag_d_selection_target_run",
                "fk_rag_d_binding_selection", "uq_rag_d_binding_natural",
                "uq_rag_d_selection_target", "chk_rag_d_assignment_atomic"} <= names
        triggers = conn.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid IN "
            "('rag_material_selections'::regclass,'rag_plan_material_bindings'::regclass) "
            "AND NOT tgisinternal"
        ).fetchall()
        assert {"trg_rag_d_selection_append_only", "trg_rag_d_binding_append_only"} <= {
            str(r["tgname"]) for r in triggers}
        conn.rollback()
