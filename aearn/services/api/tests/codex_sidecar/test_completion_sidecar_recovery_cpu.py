"""Exercise the actual durable draft reader; only storage/catalog ports are CPU seams."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.services.learning import plan_tools as module
from app.services.learning.plan_drafting import CompactPlanModule, CompactPlanNode
from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.planning_facts import PlanningFactField
from app.services.learning.plan_tools import LearningPlanToolService, LearningPlanToolStatus


@pytest.fixture
def durable_reader(monkeypatch):
    values = {PlanningFactField.LANGUAGE_ID: "python", PlanningFactField.GOAL_TEXT: "Automate work",
              PlanningFactField.TARGET_LEVEL: "intermediate", PlanningFactField.WEEKLY_MINUTES: 240,
              PlanningFactField.EXPERIENCE_LEVEL: "beginner", PlanningFactField.TEACHING_PREFERENCES: ["examples"],
              PlanningFactField.PACE_CONSTRAINTS: "Four sessions"}
    session = {"id": "session", "current_draft_id": "draft", "preferred_language_id": "python"}
    artifact = module.build_validated_learning_plan_artifact(
        session=session, profile=module._profile_from_facts(values), change_reason="Initial draft",
        modules=(
            CompactPlanModule(module_key="basics", title="Basics", nodes=[CompactPlanNode(knowledge_key="variables", title="Variables")]),
            CompactPlanModule(module_key="files", title="Files", nodes=[CompactPlanNode(knowledge_key="files", title="Files")]),
        ))
    row = {"id": "draft", "draft_version": 1, "facts_fingerprint": "facts", "facts_revision": 1,
           "content_hash": artifact.content_hash, "change_reason": "Initial draft",
           "plan_json": canonical_plan_payload(artifact.plan)}
    trace = []
    class Connection:
        depth = 0
        @contextmanager
        def transaction(self):
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1
    conn = Connection()
    def session_for_run(**kwargs):
        assert conn.depth > 0 and kwargs["for_update"] is True
        trace.append("session_locked")
        return session
    def catalog(*args, **kwargs):
        assert conn.depth > 0 and "session_locked" in trace
        trace.append("catalog_current")
    reader = LearningPlanToolService.__new__(LearningPlanToolService)
    reader._conn = conn
    reader._run = SimpleNamespace(user_id="user", run_id="run", input_revision=1)
    reader._expected = SimpleNamespace(facts_fingerprint="facts", facts_revision=1)
    reader._sessions = SimpleNamespace(draft_for_source=lambda **kw: row, active_session_for_run=session_for_run)
    reader._facts = SimpleNamespace(profile_fact_state=lambda **kw: (values, "facts", 1, ()))
    reader._fence_result = lambda: None
    monkeypatch.setattr(module, "validate_planning_catalog_mappings", catalog)
    return reader, row, session, trace


def test_actual_durable_reader_rebuilds_exact_artifact_under_session_lock(durable_reader):
    reader, row, _session, trace = durable_reader
    result = reader.recover_committed_draft()
    assert result.status is LearningPlanToolStatus.COMPLETED and result.replayed
    assert result.data["content_hash"] == row["content_hash"]
    assert result.data["module_count"] == result.data["node_count"] == 2
    assert trace == ["session_locked", "catalog_current"]
    assert reader._conn.depth == 0  # No transaction may leak into native IO.


@pytest.mark.parametrize("changed", ["content_hash", "current_draft_id"])
def test_actual_durable_reader_rejects_changed_saved_identity(durable_reader, changed):
    reader, row, session, _trace = durable_reader
    (row if changed == "content_hash" else session)[changed] = "replacement"
    result = reader.recover_committed_draft()
    assert result.status is LearningPlanToolStatus.CONFLICT
    assert reader._conn.depth == 0


def test_actual_durable_reader_does_not_bypass_current_catalog(durable_reader, monkeypatch):
    reader, _row, _session, _trace = durable_reader
    def reject_catalog(*args, **kwargs):
        raise ValueError("catalog_mapping_now_invalid")
    monkeypatch.setattr(module, "validate_planning_catalog_mappings", reject_catalog)
    with pytest.raises(ValueError, match="catalog_mapping_now_invalid"):
        reader.recover_committed_draft()
    assert reader._conn.depth == 0
