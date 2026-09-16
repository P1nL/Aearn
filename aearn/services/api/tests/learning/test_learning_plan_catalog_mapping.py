from __future__ import annotations

import json

from dataclasses import replace
from typing import cast

from psycopg import Connection

import pytest

from app.services.learning.contracts import LearningPlanNode
from app.services.learning.plan_capability import (
    PLANNING_CATALOG_DESCRIPTOR_LIMIT,
    PLANNING_CATALOG_DESCRIPTOR_SCHEMA_VERSION,
    read_planning_catalog_descriptor,
    project_planning_catalog_descriptor,
    validate_planning_catalog_mapping_rows,
)
from app.services.learning.plan_tools import (
    LearningPlanDraftModuleInput,
    LearningPlanDraftNodeInput,
    LearningPlanDraftToolInput,
    _domain_module,
)


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...]) -> _FakeResult:
        self.calls.append((query, params))
        return _FakeResult(self.rows)


def _module(
    module_key: str,
    node_key: str,
    *,
    catalog_key: str | None = None,
) -> LearningPlanDraftModuleInput:
    return LearningPlanDraftModuleInput(
        stable_key=module_key,
        title=module_key.title(),
        nodes=(
            LearningPlanDraftNodeInput(
                stable_key=node_key,
                title=node_key.title(),
                required_capabilities=("python",),
                catalog_knowledge_key=catalog_key,
            ),
        ),
    )


def _domain_node(
    *,
    knowledge_key: str = "n1_1",
    required_capabilities: tuple[str, ...] = ("python",),
    catalog_knowledge_key: str | None = "python.variables",
) -> LearningPlanNode:
    return LearningPlanNode(
        knowledge_key=knowledge_key,
        title="Variables",
        description="",
        order_index=0,
        is_core=True,
        prerequisite_keys=(),
        required_capabilities=required_capabilities,
        catalog_knowledge_key=catalog_knowledge_key,
    )


def test_typed_node_mapping_is_preserved_without_changing_step_identity() -> None:
    tool_input = LearningPlanDraftToolInput(
        modules=(
            _module("foundations", "n1_1", catalog_key="Python.Variables"),
            _module("practice", "n2_1"),
        )
    )

    domain = _domain_module(tool_input.modules[0])
    node = domain.nodes[0]

    assert node.knowledge_key == "n1_1"
    assert node.catalog_knowledge_key == "python.variables"

    description = LearningPlanDraftNodeInput.model_json_schema()["properties"]["catalog_knowledge_key"]["description"]
    assert "progress" in description
    assert "content" in description
    assert "title" in description


def test_catalog_descriptor_is_public_only_sorted_and_bounded() -> None:
    rows = [
        {
            "knowledge_key": "python.topic9",
            "required_capabilities_json": ["python"],
            "title": "must not be projected",
            "private_json": {"answer": "must not be projected"},
        }
    ] + [
        {
            "knowledge_key": f"python.topic{index}",
            "required_capabilities_json": ["python"],
            "candidate_summary": "must not be projected",
        }
        for index in range(10)
    ]

    descriptor = project_planning_catalog_descriptor(rows, language_id="py")

    assert descriptor["schema_version"] == PLANNING_CATALOG_DESCRIPTOR_SCHEMA_VERSION
    items = descriptor["items"]
    assert isinstance(items, list)
    assert len(items) == PLANNING_CATALOG_DESCRIPTOR_LIMIT
    assert items == sorted(items, key=lambda item: item["knowledge_key"])
    assert all(set(item) == {"knowledge_key", "required_capabilities"} for item in items)
    assert "private_json" not in descriptor
    assert "title" not in descriptor


def test_context_catalog_reader_uses_canonical_language_and_latest_public_metadata() -> None:
    connection = _FakeConnection(
        [{"knowledge_key": "python.variables", "required_capabilities_json": ["python"]}]
    )

    descriptor = read_planning_catalog_descriptor(cast(Connection[dict[str, object]], connection), language_id="py")

    assert descriptor is not None
    assert descriptor["items"] == [
        {"knowledge_key": "python.variables", "required_capabilities": ["python"]}
    ]
    assert connection.calls
    query, params = connection.calls[0]
    assert params[0] == "python" and params[-1] == PLANNING_CATALOG_DESCRIPTOR_LIMIT
    assert "python" in json.loads(str(params[1]))
    assert "required_capabilities_json <@" in query
    assert "tutor_learning_item_private_contents" not in query
    assert "publication.state = 'published'" in query


def test_explicit_mapping_does_not_inherit_optional_catalog_read_failure() -> None:
    from app.services.learning.plan_capability import validate_planning_catalog_mappings

    class UnavailableConnection:
        def execute(self, *_args: object) -> None:
            raise RuntimeError("catalog unavailable")

    unavailable = cast(Connection[dict[str, object]], UnavailableConnection())
    assert read_planning_catalog_descriptor(unavailable, language_id="python") is None
    with pytest.raises(ValueError) as failure:
        validate_planning_catalog_mappings(unavailable, language_id="python", nodes=(_domain_node(),))
    assert getattr(failure.value, "diagnostic_code", None) == "learning_plan_catalog_mapping_invalid"


def test_catalog_descriptor_does_not_advertise_ungranted_fixture_capabilities() -> None:
    descriptor = project_planning_catalog_descriptor([
        {"knowledge_key":"python.variables","required_capabilities_json":["atomic.fixture.ungranted"]},
        {"knowledge_key":"python.variables","required_capabilities_json":["python"]},
    ], language_id="python")
    assert descriptor["items"] == [{"knowledge_key":"python.variables","required_capabilities":["python"]}]


def test_explicit_mapping_uses_capability_subset_and_legacy_nodes_stay_direct() -> None:
    mapped = _domain_node(required_capabilities=("python", "runner"))
    validate_planning_catalog_mapping_rows(
        [
            {
                "knowledge_key": "python.variables",
                "required_capabilities_json": ["python"],
            }
        ],
        nodes=(mapped,),
    )

    legacy = replace(mapped, catalog_knowledge_key=None, required_capabilities=())
    validate_planning_catalog_mapping_rows([], nodes=(legacy,))

    incompatible = replace(mapped, required_capabilities=("javascript",))
    with pytest.raises(ValueError) as captured:
        validate_planning_catalog_mapping_rows(
            [
                {
                    "knowledge_key": "python.variables",
                    "required_capabilities_json": ["python"],
                }
            ],
            nodes=(incompatible,),
        )
    assert getattr(captured.value, "diagnostic_code", None) == "learning_plan_catalog_mapping_invalid"


def test_owner_preflight_queries_only_explicit_keys_and_keeps_db_fence_authoritative() -> None:
    connection = _FakeConnection(
        [{"knowledge_key": "python.variables", "required_capabilities_json": ["python"]}]
    )
    from app.services.learning.plan_capability import validate_planning_catalog_mappings

    validate_planning_catalog_mappings(
        cast(Connection[dict[str, object]], connection),
        language_id="python",
        nodes=(_domain_node(),),
    )

    query, params = connection.calls[0]
    assert params == ("python", ["python.variables"])
    assert "tutor_learning_item_private_contents" not in query
    assert "publication.state = 'published'" in query
