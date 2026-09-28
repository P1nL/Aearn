"""B1/B2 inventory boundaries; candidate quarantine is not corpus authority."""
from __future__ import annotations

import inspect
import os
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.repositories import local_user_data_repository
from app.services.tutor import cutover
from app.services.grounding import hybrid_retrieval

_SHARED = frozenset({
    "rag_budget_authority_roots", "rag_budget_periods", "rag_budget_reservations",
    "rag_budget_attempts", "rag_discovery_jobs", "rag_discovery_receipts",
    "rag_discovery_candidates", "rag_candidate_captures", "rag_candidate_fragments",
    "rag_candidate_intake_leases",
    "rag_discovery_query_contexts", "rag_candidate_access_policies", "rag_candidate_access_rules",
    "rag_campaign_principals", "rag_campaign_definitions", "rag_campaign_issued_contexts",
})
_PRIVATE = frozenset({"rag_discovery_job_refs", "rag_candidate_private_refs",
                      "rag_discovery_actor_owners", "rag_discovery_private_contexts"})


def test_quarantine_and_budget_not_wired_into_existing_consumers_or_user_purge() -> None:
    assert not (_SHARED | _PRIVATE) & (cutover.CUTOVER_SHARED_TUTOR_TABLES | cutover.CUTOVER_TARGET_TUTOR_TABLES)
    for module in (local_user_data_repository, cutover, hybrid_retrieval):
        source = inspect.getsource(module)
        for table in _SHARED | _PRIVATE:
            assert table not in source, (module.__name__, table)


def test_pg_staging_tables_are_separate_from_active_corpus() -> None:
    url = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not url:
        pytest.skip("B inventory PostgreSQL not executed: explicit disposable database required")
    name = urlsplit(url).path.lstrip("/")
    if not name.startswith("aearn_rag260_"):
        pytest.fail("B inventory refuses non-disposable database")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        if conn.execute("SELECT current_database() AS name").fetchone()["name"] != name:
            pytest.fail("current_database mismatch")
        names = {row["tablename"] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'rag_%'"
        ).fetchall()}
        # Later C tables are a separate layer; keep B inventory exhaustive for B rows.
        assert _SHARED | _PRIVATE <= names
        fks = conn.execute(
            "SELECT conrelid::regclass::text AS child, confrelid::regclass::text AS parent "
            "FROM pg_constraint WHERE contype='f' AND conrelid::regclass::text LIKE 'rag_%'"
        ).fetchall()
        assert all(not row["parent"].startswith("grounding_")
                   for row in fks if row["child"] in _SHARED | _PRIVATE)
        assert conn.execute("SELECT count(*) AS n FROM rag_candidate_captures").fetchone()["n"] >= 0


def test_pg_local_user_export_reset_delete_unlinks_only_owned_rag_refs() -> None:
    """Explicit disposable DB: two users, one shared job, no private spill."""
    url = os.environ.get("AEARN_RAG_B_TEST_DATABASE_URL")
    if not url:
        pytest.skip("B local-user PostgreSQL not executed: explicit disposable database required")
    name = urlsplit(url).path.lstrip("/")
    if not name.startswith("aearn_rag260_"):
        pytest.fail("B local-user integration refuses non-disposable database")
    from uuid import uuid4
    from app.services.repositories.local_user_data_repository import (
        export_user_data, reset_user_data, delete_user_data,
    )

    with psycopg.connect(url, row_factory=dict_row) as conn:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == name
        users = (uuid4(), uuid4())
        actors = tuple("actor." + uuid4().hex for _ in users)
        key = uuid4().hex
        for user, actor in zip(users, actors):
            conn.execute("INSERT INTO users(id,display_name) VALUES (%s,'rag isolated user')", (user,))
            conn.execute("INSERT INTO rag_discovery_actor_owners(actor_id,user_id) VALUES (%s,%s)", (actor,user))
        job = conn.execute(
            "INSERT INTO rag_discovery_jobs(operation_key,request_hash,query_hash,demand_hash,"
            "subject_id,subject_version,purpose,policy_id,policy_generation,root_id,"
            "delegation_id,delegation_generation) "
            "VALUES (%s,%s,%s,%s,'route.python','fixture-v1','main_teaching',"
            "'policy.001',2,'root.001','delegation.001',1) RETURNING id",
            ("job."+key, "a"*64, "b"*64, "c"*64),
        ).fetchone()["id"]
        for actor in actors:
            conn.execute("INSERT INTO rag_discovery_job_refs(job_id,actor_id,demand_hash) "
                         "VALUES (%s,%s,%s)", (job,actor,"c"*64))
        first = export_user_data(conn,str(users[0]))
        assert first["rag_discovery_refs"] == {"job_ids": [str(job)], "candidate_ids": []}
        assert str(users[1]) not in str(first["rag_discovery_refs"])
        reset_user_data(conn,str(users[0]))
        assert export_user_data(conn,str(users[0]))["rag_discovery_refs"]["job_ids"] == []
        assert export_user_data(conn,str(users[1]))["rag_discovery_refs"]["job_ids"] == [str(job)]
        assert conn.execute("SELECT count(*) AS n FROM rag_discovery_jobs WHERE id=%s",(job,)).fetchone()["n"] == 1
        delete_user_data(conn,str(users[1]))
        assert conn.execute("SELECT count(*) AS n FROM rag_discovery_actor_owners WHERE user_id = ANY(%s)",
                            (list(users),)).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM rag_discovery_job_refs WHERE job_id=%s",(job,)).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM rag_discovery_jobs WHERE id=%s",(job,)).fetchone()["n"] == 1
        conn.rollback()
