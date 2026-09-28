"""D learner-owned inventory; exclusive, prebootstrapped disposable PostgreSQL only."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.services.repositories.local_user_data_repository import (
    delete_user_data,
    get_user_data_summary,
    reset_user_data,
)


@pytest.fixture
def d_conn():  # type: ignore[no-untyped-def]
    url = os.environ.get("AEARN_RAG_D_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("D user inventory requires explicit disposable PostgreSQL")
    parts = urlsplit(url)
    name = unquote(parts.path.lstrip("/"))
    try:
        query = parse_qsl(parts.query, strict_parsing=True)
        resolved = conninfo_to_dict(url)
    except (ValueError, psycopg.Error):
        pytest.fail("D user inventory rejects malformed database URL")
    if (parts.scheme not in {"postgres", "postgresql"}
            or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            or not name.startswith("aearn_rag260_c_d_")
            or parts.fragment or any(ord(char) < 32 or ord(char) == 127 for char in url)
            or any(key not in {"sslmode", "connect_timeout"} for key, _ in query)
            or resolved.get("host") not in {"localhost", "127.0.0.1", "::1"}
            or resolved.get("dbname") != name or resolved.get("hostaddr")
            or any(os.environ.get(key) for key in (
                "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGHOST", "PGHOSTADDR",
                "PGDATABASE", "PGPORT", "PGPASSFILE", "PGTARGETSESSIONATTRS",
            ))
            or os.environ.get("PYTHON_DOTENV_DISABLED") != "1"
            or os.environ.get("LLM_TYPE") != "disabled"):
        pytest.fail("D user inventory refuses non-disposable or provider-enabled database")
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as conn:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == name
        try:
            yield conn
        finally:
            conn.rollback()


def _seed(conn, user_id: UUID) -> tuple[UUID, str]:  # type: ignore[no-untyped-def]
    conversation_id, run_id, target_run_id, session_id, draft_id = (uuid4() for _ in range(5))
    digest = uuid4().hex + uuid4().hex
    handle = "selection." + uuid4().hex
    conn.execute("INSERT INTO users(id, display_name) VALUES (%s, 'D inventory fixture')", (user_id,))
    conn.execute("INSERT INTO tutor_conversations(id, user_id) VALUES (%s, %s)", (conversation_id, user_id))
    conn.execute(
        "INSERT INTO tutor_catalog_snapshots(digest, manifest_json, redaction_version) "
        "VALUES (%s, '{}', 'fixture-v1') ON CONFLICT (digest) DO NOTHING", (digest,),
    )
    conn.execute(
        "INSERT INTO tutor_runs(id, user_id, conversation_id, origin, status, policy_json, "
        "policy_version, policy_fingerprint, catalog_digest, input_revision, "
        "terminal_outcome, terminal_at) "
        "VALUES (%s, %s, %s, 'interactive', 'completed', '{}', 'fixture-v1', %s, %s, 1, "
        "'completed', now())", (run_id, user_id, conversation_id, digest, digest),
    )
    conn.execute(
        "INSERT INTO tutor_runs(id, user_id, conversation_id, origin, status, policy_json, "
        "policy_version, policy_fingerprint, catalog_digest, input_revision, "
        "terminal_outcome, terminal_at) "
        "VALUES (%s, %s, %s, 'interactive', 'completed', '{}', 'fixture-v1', %s, %s, 1, "
        "'completed', now())", (target_run_id, user_id, conversation_id, digest, digest),
    )
    conn.execute(
        "INSERT INTO tutor_conversation_learning_scopes(conversation_id, user_id, scope_kind) "
        "VALUES (%s, %s, 'plan_drafting')", (conversation_id, user_id),
    )
    conn.execute(
        "INSERT INTO tutor_run_learning_scopes(run_id, user_id, conversation_id, scope_kind, "
        "task_kind, scope_version) VALUES (%s, %s, %s, 'plan_drafting', 'plan_drafting', 1)",
        (run_id, user_id, conversation_id),
    )
    conn.execute(
        "INSERT INTO tutor_run_learning_scopes(run_id, user_id, conversation_id, scope_kind, "
        "task_kind, scope_version) VALUES (%s, %s, %s, 'plan_drafting', 'plan_drafting', 1)",
        (target_run_id, user_id, conversation_id),
    )
    conn.execute(
        "INSERT INTO tutor_learning_plan_sessions(id, user_id, conversation_id, status, current_draft_id) "
        "VALUES (%s, %s, %s, 'draft_ready', %s)",
        (session_id, user_id, conversation_id, draft_id),
    )
    conn.execute(
        "INSERT INTO tutor_learning_plan_drafts(id, session_id, user_id, draft_version, "
        "language_id, goal_text, target_level, weekly_minutes, experience_level, "
        "pace_summary, profile_json, plan_json, source_summary_json, content_hash, "
        "generator_version, policy_version, change_reason, source_run_id, source_input_revision) "
        "VALUES (%s, %s, %s, 1, 'python', 'Learn Python', 'beginner', 120, 'beginner', "
        "'steady', '{}', '{}', '[{}]', %s, 'fixture-v1', 'fixture-v1', 'initial', %s, 1)",
        (draft_id, session_id, user_id, digest, run_id),
    )
    conn.execute(
        "INSERT INTO rag_material_selections(handle, user_id, conversation_id, session_id, "
        "draft_id, draft_version, content_hash, source_run_id, source_input_revision, "
        "selection_digest, snapshot_json, idempotency_key) "
        "VALUES (%s, %s, %s, %s, %s, 1, %s, %s, 1, %s, '{}', 'fixture-selection')",
        (handle, user_id, conversation_id, session_id, draft_id, digest, run_id, digest),
    )
    conn.execute(
        "UPDATE rag_material_selections SET target_run_id = %s, target_input_revision = 1, "
        "expected_session_version = 1, assignment_digest = %s, assigned_at = now() "
        "WHERE handle = %s", (target_run_id, digest, handle),
    )
    conn.execute(
        "INSERT INTO rag_plan_material_bindings(selection_handle, selection_digest, user_id, "
        "session_id, draft_id, node_id, goal_hash, purpose, binding_digest, binding_json, "
        "idempotency_key) VALUES (%s, %s, %s, %s, %s, 'python.basics', %s, "
        "'main_teaching', %s, '{}', 'fixture-binding')",
        (handle, digest, user_id, session_id, draft_id, digest, digest),
    )
    return draft_id, handle


def _counts(conn, user_id: UUID) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    return tuple(conn.execute(f"SELECT count(*) AS n FROM {table} WHERE user_id = %s", (user_id,))
                 .fetchone()["n"] for table in (
                     "rag_plan_material_bindings", "rag_material_selections", "tutor_learning_plan_drafts",
                 ))


@pytest.mark.parametrize("operation", [reset_user_data, delete_user_data])
def test_d_owned_receipts_purge_and_rollback_with_other_user_and_shared_corpus(d_conn, operation):  # type: ignore[no-untyped-def]
    owner, other = uuid4(), uuid4()
    owner_draft, _ = _seed(d_conn, owner)
    other_draft, _ = _seed(d_conn, other)
    def current_pointer(user_id: UUID) -> tuple[str, UUID | None]:
        row = d_conn.execute(
            "SELECT status, current_draft_id FROM tutor_learning_plan_sessions WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        assert row is not None
        return row["status"], row["current_draft_id"]

    # Real draft_ready sessions point at the exact draft being purged; do not
    # hide the FK restriction by seeding current_draft_id as NULL.
    assert current_pointer(owner) == ("draft_ready", owner_draft)
    assert current_pointer(other) == ("draft_ready", other_draft)
    shared_before = d_conn.execute("SELECT count(*) AS n FROM grounding_corpus_versions").fetchone()["n"]
    assert _counts(d_conn, owner) == (1, 1, 1)
    assert _counts(d_conn, other) == (1, 1, 1)
    # Neither a generic delete nor another user's purge grant may erase D history.
    with pytest.raises(psycopg.Error), d_conn.transaction():
        d_conn.execute("DELETE FROM rag_plan_material_bindings WHERE user_id = %s", (owner,))
    with pytest.raises(psycopg.Error), d_conn.transaction():
        d_conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)",
                       (str(other),))
        d_conn.execute("DELETE FROM rag_plan_material_bindings WHERE user_id = %s", (owner,))
    assert _counts(d_conn, owner) == (1, 1, 1)
    summary = get_user_data_summary(d_conn, str(owner))["counts"]
    assert summary["rag_material_selections"] == summary["rag_plan_material_bindings"] == 1

    # The same reset/delete operation must roll back all D and legacy rows if
    # any later step in the caller-owned transaction fails.
    with pytest.raises(RuntimeError), d_conn.transaction():
        operation(d_conn, str(owner))
        assert _counts(d_conn, owner) == (0, 0, 0)
        raise RuntimeError("simulate later transaction failure")
    assert _counts(d_conn, owner) == (1, 1, 1)
    assert _counts(d_conn, other) == (1, 1, 1)
    assert current_pointer(owner) == ("draft_ready", owner_draft)
    assert current_pointer(other) == ("draft_ready", other_draft)
    assert d_conn.execute("SELECT deleted_at FROM users WHERE id = %s", (owner,)).fetchone()["deleted_at"] is None

    operation(d_conn, str(owner))
    assert _counts(d_conn, owner) == (0, 0, 0)
    assert _counts(d_conn, other) == (1, 1, 1)
    assert current_pointer(other) == ("draft_ready", other_draft)
    assert d_conn.execute("SELECT deleted_at FROM users WHERE id = %s", (other,)).fetchone()["deleted_at"] is None
    assert d_conn.execute("SELECT count(*) AS n FROM grounding_corpus_versions").fetchone()["n"] == shared_before
