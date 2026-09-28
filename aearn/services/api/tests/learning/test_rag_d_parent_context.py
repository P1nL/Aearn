"""D required parent facts remain exact or fail under existing context limits."""
import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import TutorContextError, TutorContextInput, TutorContextSource
from app.services.grounding.material_binding_repository import MaterialBindingStale, goal_hash_for_node
from app.services.learning.material_selection import PostgresMaterialPlanningConsumer, parent_snapshot_sources


def parent() -> dict:
    node = {"knowledge_key": "python.values", "title": "变量", "description": "保留完整目标",
            "is_core": True, "prerequisite_keys": [], "required_capabilities": [],
            "catalog_knowledge_key": None}
    return {"profile_json": {"language_id": "python", "goal_text": "学习 Python", "pace_summary": "按目标学习"},
            "plan_json": {"title": "Python", "target_level": "beginner", "modules": [
                {"module_key": "basics", "title": "基础", "description": "", "nodes": [node]},
            ]}}


def context(sources: tuple[TutorContextSource, ...]) -> TutorContextInput:
    return TutorContextInput(run_id=str(uuid4()), conversation_id=str(uuid4()),
                             input_revision=1, current_input_required=False, required_facts=sources)


def test_parent_facts_are_exact_in_provider_selection() -> None:
    original = parent()
    sources = parent_snapshot_sources(original, str(uuid4()))
    selected = TutorContextBuilder().build(context(sources), token_budget=10000)
    units = [unit for item in selected.items for unit in json.loads(item.content)["items"]]
    assert [unit["profile"] for unit in units if "profile" in unit] == [original["profile_json"]]
    expected = original["plan_json"]["modules"][0]["nodes"][0]
    assert [unit["node"] for unit in units if "node" in unit] == [expected]
    assert [unit["goal_hash"] for unit in units if "node" in unit] == [goal_hash_for_node(expected)]


def test_parent_oversize_or_redaction_never_silently_changes_goal() -> None:
    oversized = copy.deepcopy(parent())
    oversized["plan_json"]["modules"][0]["nodes"][0]["description"] = "x" * 1300
    with pytest.raises(MaterialBindingStale):
        parent_snapshot_sources(oversized, str(uuid4()))
    protected = parent()
    protected["profile_json"]["api_key"] = "synthetic-secret-must-not-be-sent"
    with pytest.raises(MaterialBindingStale):
        parent_snapshot_sources(protected, str(uuid4()))


def test_parent_context_obeys_existing_fact_count_and_token_caps() -> None:
    sources = parent_snapshot_sources(parent(), str(uuid4()))
    with pytest.raises(TutorContextError, match="TUTOR_REQUIRED_FACTS_UNREPRESENTABLE"):
        TutorContextBuilder().build(context(sources), token_budget=1)
    too_many = tuple(TutorContextSource(f"overflow-{i}", sources[0].content) for i in range(9))
    with pytest.raises(TutorContextError, match="TUTOR_REQUIRED_FACTS_UNREPRESENTABLE"):
        TutorContextBuilder().build(context(too_many), token_budget=10000)


def test_feedback_and_parent_share_transaction_and_missing_parent_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"inside": False}

    @contextmanager
    def transaction():
        state["inside"] = True
        try:
            yield
        finally:
            state["inside"] = False

    consumer = object.__new__(PostgresMaterialPlanningConsumer)
    consumer._conn = SimpleNamespace(autocommit=False, transaction=transaction)
    run = SimpleNamespace()

    def feedback(*_args):
        assert state["inside"]
        return {"kind": "material_planning_feedback"}

    def disappeared(*_args):
        assert state["inside"]
        return ()  # Simulate a consumed/stale parent at the helper boundary.

    monkeypatch.setattr(consumer, "feedback_for_context", feedback)
    monkeypatch.setattr(consumer, "parent_facts_for_context", disappeared)
    with pytest.raises(MaterialBindingStale, match="no exact parent"):
        consumer.context_for_run(run, {})
    assert not state["inside"]
