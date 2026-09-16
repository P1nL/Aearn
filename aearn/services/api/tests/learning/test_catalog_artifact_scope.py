"""Mapped content uses real isolated owners; provider responses are synthetic."""
from dataclasses import replace
from uuid import uuid4

from tests.learning.test_gate_catalog_mapping import _require_dedicated_database

from app.agents.harness.contracts import TutorTerminalOutcome
from app.services.learning.artifacts.knowledge_checks import _load_authority
from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository
from app.services.learning.item_bank.repository import PostgresLearningItemBankRepository
from tests.learning.test_gate_catalog_mapping import learning_item_source, import_learning_item, publish_learning_item
import tests.support.teaching_session_support as teaching_support
from tests.support.learning_track_support import sample_plan
from tests.tutor.test_tutor_teaching_artifact_commit import (
    _artifact_settings, _open_guided, _dispatch_artifact, _ArtifactTeachingProvider, connection,
    _published_knowledge_item,
)


def test_mapped_catalog_materializes_artifact_without_relabeling_progress(monkeypatch) -> None:
    _require_dedicated_database()
    catalog_key = f"python.catalog.{uuid4().hex[:12]}"
    settings = _artifact_settings()
    plan = sample_plan()
    mapped = replace(plan, modules=(replace(plan.modules[0], nodes=(
        replace(plan.nodes[0], catalog_knowledge_key=catalog_key), plan.nodes[1],
    )),))
    with connection() as conn:
        source, validation = learning_item_source(f"test.catalog.artifact.{uuid4().hex[:12]}",knowledge_key=catalog_key,capability="python")
        imported = import_learning_item(PostgresLearningItemBankRepository(conn), source, validation, key=f"catalog-artifact:{catalog_key}")
        publish_learning_item(conn, imported.handle, f"catalog-artifact:{catalog_key}")
        with monkeypatch.context() as patch:
            patch.setattr(teaching_support, "sample_plan", lambda: mapped)
            scope, run_id = _open_guided(conn, settings=settings, required_capability="python")
    provider = _ArtifactTeachingProvider(artifact_handle=imported.handle)
    result = _dispatch_artifact(settings=settings,scope=scope,run_id=run_id,provider=provider)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert provider.selected_handle == imported.handle
    with connection() as conn:
        row = conn.execute("SELECT id,knowledge_key,owner_id FROM tutor_learning_artifacts WHERE turn_id=%s",(run_id,)).fetchone()
        assert row and row["knowledge_key"] == "python.variables"
        artifact = PostgresLearningArtifactRepository(conn).read_artifact(
            user_id=str(scope["user_id"]),conversation_id=str(scope["conversation_id"]),artifact_id=str(row["id"]),
        )
        public, _private, _policy = _load_authority(conn, artifact=artifact)
        assert public.item_key == source.public.item_key
        assert conn.execute("SELECT tutor_artifact_catalog_knowledge_key(%s) AS key",(row["id"],)).fetchone() == {"key":catalog_key}
        progress = conn.execute("SELECT status FROM tutor_track_node_progress WHERE track_id=%s AND knowledge_key='python.variables'",(scope["track_id"],)).fetchone()
        assert progress and progress["status"] != "completed"


def test_small_provider_budget_still_rejects_artifact_before_provider_or_writes() -> None:
    _require_dedicated_database()
    settings = _artifact_settings(input_limit=4_096)
    with connection() as conn:
        handle, _version, _publication, capability = _published_knowledge_item(conn)
        scope, run_id = _open_guided(conn, settings=settings, required_capability=capability)
    provider = _ArtifactTeachingProvider(artifact_handle=handle)
    result = _dispatch_artifact(settings=settings, scope=scope, run_id=run_id, provider=provider)
    assert result.diagnostic_code == "TUTOR_CONTEXT_REQUIRED_OVERFLOW"
    assert provider.calls == 0
    with connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM tutor_learning_artifacts WHERE turn_id=%s",(run_id,)).fetchone() == {"n":0}
