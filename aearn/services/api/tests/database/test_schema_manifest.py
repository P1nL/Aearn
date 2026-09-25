from __future__ import annotations

from typing import cast

from psycopg import Connection

from app.db.bootstrap import apply_schema
from app.db.schema import (
    SCHEMA_DIRECTORY,
    SCHEMA_FRAGMENT_NAMES,
    load_schema_fragments,
    load_schema_text,
    schema_fragment_paths,
)


EXPECTED_SCHEMA_FRAGMENT_NAMES = (
    "000_foundation.sql",
    "010_core_learning.sql",
    "020_grounding.sql",
    "030_legacy_messages.sql",
    "040_tutor_runtime.sql",
    "050_tutor_learner_state.sql",
    "060_tutor_conversation.sql",
    "070_learning_tracks.sql",
    "080_lesson_teaching_practice.sql",
    "090_model_review.sql",
    "100_review_context.sql",
    "110_thread_turn_codex.sql",
    "120_learning_artifacts.sql",
    "130_learning_item_bank.sql",
    "140_learning_item_governance.sql",
    "150_tutor_branch_continuation.sql",
    "160_teaching_artifact_commit.sql",
    "170_teaching_demonstrations.sql",
    "180_knowledge_checks.sql",
    "190_model_review_artifacts.sql",
    "200_sql_learning_workspace.sql",
    "210_tutor_branch_supersession.sql",
    "220_plan_catalog_knowledge_scope.sql",
    "230_artifact_authority_supersession.sql",
    "240_deepseek_flash_runtime_cutover.sql",
    "250_source_inspection_artifacts.sql",
    "260_rag_subject_corpus.sql",
    "270_rag_discovery_jobs.sql",
    "280_rag_candidate_staging.sql",
    "290_rag_discovery_context.sql",
    "300_rag_candidate_policy.sql",
    "310_rag_campaign_authority.sql",
)


class RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_schema_manifest_is_explicit_complete_and_not_natural_sort_dependent() -> None:
    assert SCHEMA_FRAGMENT_NAMES == EXPECTED_SCHEMA_FRAGMENT_NAMES
    paths = schema_fragment_paths()
    assert tuple(path.name for path in paths) == EXPECTED_SCHEMA_FRAGMENT_NAMES
    assert {path.name for path in SCHEMA_DIRECTORY.glob("*.sql")} == set(EXPECTED_SCHEMA_FRAGMENT_NAMES)
    assert not (SCHEMA_DIRECTORY.parent / "schema.sql").exists()


def test_schema_combined_view_and_apply_order_match_the_manifest() -> None:
    fragments = load_schema_fragments()
    assert tuple(fragment.name for fragment in fragments) == EXPECTED_SCHEMA_FRAGMENT_NAMES
    assert load_schema_text() == "".join(fragment.sql for fragment in fragments)
    assert fragments[0].sql.startswith("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    assert "Child 09 conversation-native SQL workspace" in fragments[-12].sql
    assert "tutor_branch_authority_replacement_valid" in fragments[-11].sql
    assert "tutor_plan_catalog_knowledge_key" in fragments[-10].sql
    assert "tutor_artifact_supersession_successor" in fragments[-9].sql
    assert "deepseek-flash" in fragments[-8].sql
    assert "source_inspection" in fragments[-7].sql
    assert "grounding_corpus_versions" in fragments[-6].sql
    assert "rag_budget_periods" in fragments[-5].sql
    assert "rag_candidate_captures" in fragments[-4].sql
    assert "rag_discovery_private_contexts" in fragments[-3].sql
    assert "rag_candidate_access_policies" in fragments[-2].sql
    assert "rag_campaign_principals" in fragments[-1].sql

    recorder = RecordingConnection()
    apply_schema(cast(Connection[dict[str, object]], recorder))
    assert recorder.statements == [fragment.sql for fragment in fragments]


def test_schema_fragments_do_not_own_transaction_commits() -> None:
    for fragment in load_schema_fragments():
        normalized = fragment.sql.upper()
        assert "\nCOMMIT;" not in normalized, fragment.name
        assert "\nROLLBACK;" not in normalized, fragment.name


def test_bootstrap_retries_the_complete_transaction_after_deadlock(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from psycopg.errors import DeadlockDetected

    import app.db.bootstrap as bootstrap

    class RetryConnection:
        def __init__(self, *, fail: bool) -> None:
            self.fail = fail
            self.committed = False

        def execute(self, _statement: str, _params: object = None) -> None:
            if self.fail:
                self.fail = False
                raise DeadlockDetected("test bootstrap deadlock")

        def commit(self) -> None:
            self.committed = True

    class ConnectionContext:
        def __init__(self, connection: RetryConnection) -> None:
            self.connection = connection

        def __enter__(self) -> RetryConnection:
            return self.connection

        def __exit__(self, *_args: object) -> None:
            return None

    connections = [RetryConnection(fail=True), RetryConnection(fail=False)]
    sleeps: list[float] = []
    monkeypatch.setattr(bootstrap, "connect", lambda: ConnectionContext(connections.pop(0)))
    monkeypatch.setattr(bootstrap, "sleep", sleeps.append)
    for name in (
        "apply_schema",
        "seed_runtime_profiles",
        "seed_language_courses",
        "archive_language_courses",
        "seed_learning_intents",
        "seed_language_course_intent_tags",
        "require_language_course_intent_coverage",
        "import_curated_learning_item_sources",
    ):
        monkeypatch.setattr(bootstrap, name, lambda _conn: None)

    bootstrap.bootstrap_database()

    assert sleeps == [bootstrap._BOOTSTRAP_RETRY_DELAY_SECONDS]
    assert not connections
