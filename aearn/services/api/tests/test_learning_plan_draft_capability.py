from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
from app.services.learning.plan_drafting import (
    LearningPlanSourceSummary,
    decode_plan_draft,
)


def _profile(**updates: object) -> str:
    value = {
        "language_id": "python",
        "goal_text": "Automate routine work",
        "target_level": "intermediate",
        "weekly_minutes": 180,
        "experience_level": "beginner",
        "teaching_preferences": ["examples"],
        "pace_summary": "Three sessions per week.",
        "title": "Python Automation",
    }
    value.update(updates)
    return json.dumps(value, separators=(",", ":"))


def _module(key: str, node: str, *, prerequisite: str | None = None) -> str:
    item: dict[str, object] = {
        "module_key": key,
        "title": key.title(),
        "nodes": [
            {
                "knowledge_key": node,
                "title": node.rsplit(".", 1)[-1].title(),
                "required_capabilities": ["python"],
            }
        ],
    }
    if prerequisite is not None:
        item["nodes"][0]["prerequisite_keys"] = [prerequisite]  # type: ignore[index]
    return json.dumps(item, separators=(",", ":"))


def test_compact_plan_decode_is_deterministic_and_preserves_server_versions() -> None:
    sources = (LearningPlanSourceSummary("python-tutorial", "Python Tutorial", "official"),)
    first = decode_plan_draft(
        profile_json=_profile(),
        module_json_values=(
            _module("foundations", "python.variables"),
            _module("automation", "python.files", prerequisite="python.variables"),
        ),
        sources=sources,
        change_reason="Create a typed draft.",
    )
    second = decode_plan_draft(
        profile_json=_profile(),
        module_json_values=(
            _module("foundations", "python.variables"),
            _module("automation", "python.files", prerequisite="python.variables"),
        ),
        sources=sources,
        change_reason="Create a typed draft.",
    )
    assert first.content_hash == second.content_hash
    assert first.plan.generator_version == "learning-plan-draft-capability-v1"
    assert first.plan.policy_version == "learning-plan-draft-policy-v1"
    assert [node.knowledge_key for node in first.plan.nodes] == ["python.variables", "python.files"]


def test_compact_capability_input_rejects_execution_targets_and_module_gaps() -> None:
    with pytest.raises(ValidationError):
        LearningPlanDraftCapabilityInput(
            profile_json=_profile(goal_text="Read https://untrusted.example"),
            module_1=_module("foundations", "python.variables"),
            module_2=_module("automation", "python.files"),
        )
    with pytest.raises(ValidationError):
        LearningPlanDraftCapabilityInput(
            profile_json=_profile(),
            module_1=_module("foundations", "python.variables"),
            module_2=_module("automation", "python.files"),
            module_4=_module("testing", "python.testing"),
        )


def test_compact_plan_rejects_cycles_duplicate_keys_and_more_than_eight_modules() -> None:
    sources = (LearningPlanSourceSummary("python-tutorial", "Python Tutorial", "official"),)
    with pytest.raises(ValueError):
        decode_plan_draft(
            profile_json=_profile(),
            module_json_values=(
                _module("first", "python.first", prerequisite="python.second"),
                _module("second", "python.second", prerequisite="python.first"),
            ),
            sources=sources,
            change_reason="Reject a cycle.",
        )
    with pytest.raises(ValueError):
        decode_plan_draft(
            profile_json=_profile(),
            module_json_values=tuple(_module(f"module-{index}", f"python.node-{index}") for index in range(9)),
            sources=sources,
            change_reason="Reject too many modules.",
        )
