"""Offline regressions for target-scoped feedback and exact context parts."""
from __future__ import annotations

import json
import os
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

os.environ["DATABASE_URL"] = "postgresql://disabled:disabled@127.0.0.1:1/unreachable"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["LLM_TYPE"] = "disabled"

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import TutorContextSection, TutorContextSource
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, SubjectScope
from app.services.grounding.material_contracts_v2 import (
    DraftScope,
    MaterialSelectionEntry,
    NodeMaterialRequirement,
    digest,
)
from app.services.learning import material_selection as subject


def _draft() -> DraftScope:
    return DraftScope(
        user_id=str(uuid4()),
        conversation_id=str(uuid4()),
        session_id=str(uuid4()),
        draft_id=str(uuid4()),
        draft_version=2,
        content_hash="a" * 64,
        source_run_id=str(uuid4()),
        source_input_revision=1,
    )


def _requirement(draft: DraftScope) -> NodeMaterialRequirement:
    demand = LearningMaterialDemand(
        scope=SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",)),
        demand_hash="b" * 64,
        plan_ref=f"draft.{draft.draft_id}",
        node_ref="node.sql.queries",
        draft_revision=draft.draft_version,
        purpose="supplementary_explanation",
        reading_level="beginner",
        language="en",
    )
    return NodeMaterialRequirement(
        node_id="sql.queries",
        goal_hash="c" * 64,
        prerequisites=(),
        demand=demand,
    )


def test_feedback_target_pair_uses_distinct_idempotency_and_only_replays_exact_target(
    monkeypatch,
) -> None:
    draft = _draft()
    requirement = _requirement(draft)
    entry = MaterialSelectionEntry(
        node_id=requirement.node_id,
        goal_hash=requirement.goal_hash,
        purpose=requirement.demand.purpose,
        status="gap",
        gaps=("missing_material",),
    )
    saved: dict[str, object] = {}
    recorded_keys: list[str] = []
    authority_calls: list[int] = []

    class Result:
        def __init__(self, handle: str) -> None:
            self.handle = handle
            self.draft = draft
            self.requirements = (requirement,)
            self.entries = (entry,)

    class Query:
        def __init__(self, row: object | None) -> None:
            self.row = row

        def fetchone(self) -> object | None:
            return self.row

    class Connection:
        def execute(self, _sql: str, params: tuple[object, ...]) -> Query:
            key = str(params[3])
            existing = saved.get(key)
            return Query({"handle": existing.handle} if existing is not None else None)

    class Repository:
        def record_selection(self, result: Result, *, idempotency_key: str) -> Result:
            recorded_keys.append(idempotency_key)
            saved[idempotency_key] = result
            return result

        def get_selection(self, *, handle: str, draft: DraftScope) -> Result:
            assert draft == globals_draft
            return next(value for value in saved.values() if value.handle == handle)  # type: ignore[attr-defined]

    class Authority:
        def resolve_evidence(
            self,
            _draft_scope: DraftScope,
            _requirements: tuple[NodeMaterialRequirement, ...],
        ) -> Result:
            authority_calls.append(len(authority_calls) + 1)
            return Result(f"selection.target.{authority_calls[-1]}")

    globals_draft = draft
    consumer = object.__new__(subject.PostgresMaterialPlanningConsumer)
    consumer._conn = Connection()
    consumer._repo = Repository()
    consumer._authority = Authority()
    consumer._requirements = object()
    monkeypatch.setattr(subject, "_scope", lambda *_args: draft)
    monkeypatch.setattr(subject, "_requirements", lambda *_args: (requirement,))

    first_target = (str(uuid4()), 1)
    second_target = (str(uuid4()), 1)
    first = consumer._select({}, draft.conversation_id, feedback_target=first_target)
    second = consumer._select({}, draft.conversation_id, feedback_target=second_target)
    replay = consumer._select({}, draft.conversation_id, feedback_target=first_target)

    assert first.handle != second.handle
    assert replay is first
    assert authority_calls == [1, 2]
    assert recorded_keys == [
        f"feedback:{draft.draft_id}:{digest(first_target)}",
        f"feedback:{draft.draft_id}:{digest(second_target)}",
    ]


def test_oversize_feedback_parts_reconstruct_every_entry_without_truncation(monkeypatch) -> None:
    run = SimpleNamespace(run_id=str(uuid4()), input_revision=3)
    entries = [
        {
            "node_id": f"sql.node.{index}",
            "purpose": "supplementary_explanation",
            "status": "ready",
            "covered_facets": ["queries"],
            "gaps": [],
            "evidence_count": 1,
            "recommended": [{
                "source_handle": "source." + (chr(97 + index) * 140),
                "document_handle": "document." + (chr(107 + index) * 140),
                "document_revision": "revision." + (chr(117 + index) * 120),
                "purpose": "supplementary_explanation",
            }],
        }
        for index in range(4)
    ]
    feedback = {
        "kind": "material_planning_feedback",
        "schema_version": "rag_d_selection_v2",
        "parent_draft_version": 2,
        "entries": entries,
        "omitted_entry_count": 0,
        "instruction": "Preserve every goal and prerequisite; never invent source coverage.",
    }
    assert len(json.dumps(feedback, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) > 1200
    parent = TutorContextSource(
        source_id="material-parent:test:0",
        content={"kind": "material_parent_snapshot", "draft_id": "test", "part": 0, "items": []},
    )
    consumer = object.__new__(subject.PostgresMaterialPlanningConsumer)
    consumer._conn = object()
    monkeypatch.setattr(subject, "material_transaction", lambda _conn: nullcontext())
    monkeypatch.setattr(consumer, "feedback_for_context", lambda *_args: feedback)
    monkeypatch.setattr(consumer, "parent_facts_for_context", lambda *_args: (parent,))

    header, sources = consumer.context_for_run(run, {})

    assert header is not None
    assert header["entries"] == []
    parts = [source for source in sources if source.content.get("kind") == "material_planning_feedback_part"]
    assert sources[0] == parent
    assert header["entry_parts"] == len(parts) and len(parts) > 1
    assert [entry for part in parts for entry in part.content["entries"]] == entries
    assert [part.content["part"] for part in parts] == list(range(len(parts)))
    builder = TutorContextBuilder(config=TutorContextBuilderConfig())
    for part in parts:
        serialized, truncated = builder._serialize_source(TutorContextSection.REQUIRED_FACTS, part)
        assert not truncated
        assert len(serialized) <= 1200
        assert json.loads(serialized) == part.content
