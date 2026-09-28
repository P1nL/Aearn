"""C shared admission facts are not learner-private state or B quarantine reads."""
from __future__ import annotations

import inspect
import os
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services.grounding import hybrid_retrieval
from app.services.repositories import local_user_data_repository
from app.services.tutor import cutover
from tests.grounding.test_rag_b_inventory import _PRIVATE, _SHARED

_C_SHARED = frozenset({
    "rag_registered_source_policies", "rag_registered_fetch_attempts",
    "rag_registered_supplemental_authorizations", "rag_registered_supplemental_revocations",
    "rag_registered_final_followup_allowances",
    "rag_candidate_use_grants",
    "rag_registered_source_captures", "rag_source_reviews",
    "rag_source_admissions", "rag_source_claim_receipts",
    "rag_corpus_admission_links", "rag_corpus_validation_receipts",
})

# D adds learner-private selection/binding/semantic-review receipts. They are not C shared
# source facts and introduce no additional direct corpus-writer relationships.
_D_PRIVATE = frozenset({"rag_material_selections", "rag_plan_material_bindings",
                        "rag_material_semantic_reviews"})


def test_c_not_visible_to_old_consumers_or_user_purge() -> None:
    assert not _C_SHARED & (cutover.CUTOVER_SHARED_TUTOR_TABLES | cutover.CUTOVER_TARGET_TUTOR_TABLES)
    for module in (hybrid_retrieval, local_user_data_repository, cutover):
        source = inspect.getsource(module)
        assert all(table not in source for table in _C_SHARED), module.__name__


def test_c_inventory_and_only_intended_corpus_links() -> None:
    dsn = os.environ.get("AEARN_RAG_C_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("C inventory requires explicit disposable database")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_"):
        pytest.fail("C inventory refuses non-aearn_rag260_c_ database")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == name
        names = {row["tablename"] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'rag_%'"
        ).fetchall()}
        assert names == _SHARED | _PRIVATE | _C_SHARED | _D_PRIVATE
        fks = conn.execute(
            "SELECT conrelid::regclass::text AS child, confrelid::regclass::text AS parent "
            "FROM pg_constraint WHERE contype='f' AND conrelid::regclass::text LIKE 'rag_%'"
        ).fetchall()
        cross = {(row["child"], row["parent"]) for row in fks if row["parent"].startswith("grounding_")}
        assert cross == {
            ("rag_corpus_admission_links", "grounding_corpus_documents"),
            ("rag_corpus_validation_receipts", "grounding_corpus_versions"),
            ("rag_corpus_validation_receipts", "grounding_corpus_events"),
        }
