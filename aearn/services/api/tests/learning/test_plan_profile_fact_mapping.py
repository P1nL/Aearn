"""Confirmed fact projection must tell the model the exact compact profile target."""
from collections.abc import Mapping

from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
from app.services.learning.planning_facts import PlanningFact, PlanningFactField, PlanningFactState


def test_confirmed_fact_projection_maps_profile_fields_without_rewriting_values() -> None:
    values: dict[PlanningFactField, object] = {
        PlanningFactField.LANGUAGE_ID: "python",
        PlanningFactField.GOAL_TEXT: "Build tools",
        PlanningFactField.TARGET_LEVEL: "intermediate",
        PlanningFactField.WEEKLY_MINUTES: 180,
        PlanningFactField.EXPERIENCE_LEVEL: "beginner",
        PlanningFactField.TEACHING_PREFERENCES: ["examples"],
        PlanningFactField.PACE_CONSTRAINTS: "每周三次，每次一小时。",
    }
    for field, value in values.items():
        fact = PlanningFact(
            fact_id="fact-id", session_id="session-id", field_key=field,
            value=value, value_hash="a" * 64, revision=1, state=PlanningFactState.CONFIRMED,
            source_message_id="message-id", source_run_id="run-id", source_input_revision=1,
            supersedes_fact_id=None,
        )
        content = fact.as_context_source().content
        assert isinstance(content, Mapping)
        assert content["field_key"] == field.value
        assert content["profile_field"] == (
            "pace_summary" if field is PlanningFactField.PACE_CONSTRAINTS else field.value
        )
        assert content["profile_value_policy"] == "copy_exact"
        assert content["value"] is value
        assert "profile_field" not in fact.as_public_dict()

    description = LearningPlanDraftCapabilityInput.model_fields["profile_json"].description
    assert description is not None
    assert "pace_constraints maps to pace_summary" in description
    assert "Copy confirmed fact values exactly" in description
    assert "generate only missing or explicitly reopened fields" in description
