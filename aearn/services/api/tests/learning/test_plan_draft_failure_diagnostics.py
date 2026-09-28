"""Small offline regressions for plan validation cause projection; no DB fixtures."""
from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock

import pytest
from psycopg import Connection

from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorCapabilityStatus,
    TutorPolicySnapshot,
    TutorRunSnapshot,
)
from app.services.learning.plan_capability import (
    LearningPlanDraftCapabilityError,
    LearningPlanDraftCapabilityHandler,
)
from app.services.learning.planning_facts import PlanningFactError
from app.services.tutor.capability_gateway import CatalogCapabilityGateway
from tests.learning.test_learning_plan_draft_capability import _module, _profile


def _input(**updates: str) -> LearningPlanDraftCapabilityInput:
    return LearningPlanDraftCapabilityInput(**{
        "profile_json": _profile(),
        "module_1": _module("first", "python.first"),
        "module_2": _module("second", "python.second"),
        **updates,
    })


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="diagnostic-run", conversation_id="diagnostic-conversation",
        user_id="diagnostic-user", origin="interactive", input_revision=1,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
    )


@pytest.fixture
def handler(monkeypatch: pytest.MonkeyPatch) -> LearningPlanDraftCapabilityHandler:
    # Deliberately has no execute/connect method, so accidental SQL is a test failure.
    conn = Mock(spec=["transaction"])
    conn.transaction.side_effect = nullcontext
    result = LearningPlanDraftCapabilityHandler(cast(Connection[dict[str, object]], conn))
    monkeypatch.setattr(result._repository, "active_session_for_run", Mock(return_value={
        "id": "diagnostic-session", "preferred_language_id": "python",
    }))
    monkeypatch.setattr(result._repository, "record_safe_error", Mock())
    monkeypatch.setattr(result._repository, "append_draft", Mock())
    return result


def _fields(error: LearningPlanDraftCapabilityError) -> dict[str, str]:
    assert error.code == "LEARNING_PLAN_DRAFT_INVALID"
    assert error.diagnostic_code == "learning_plan_draft_invalid"
    assert error.status is TutorCapabilityStatus.DENIED
    return {field.key: field.value for field in error.safe_diagnostics}


def test_compact_failures_only_project_known_fields(handler: LearningPlanDraftCapabilityHandler) -> None:
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        handler._artifact(session={}, capability_input=_input(profile_json=_profile(weekly_minutes="private-value")))
    assert _fields(caught.value)["field_path"] == "profile.weekly_minutes"
    assert _fields(caught.value)["stage"] == "compact_profile"
    assert "private-value" not in repr(caught.value.safe_diagnostics)

    module = json.loads(_module("first", "python.first"))
    module["private-extra-key"] = "private-value"
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        handler._artifact(session={}, capability_input=_input(module_1=json.dumps(module)))
    assert _fields(caught.value)["stage"] == "compact_modules"
    assert _fields(caught.value)["field_path"] == "modules"
    assert "private-" not in repr(caught.value.safe_diagnostics)


def test_domain_and_session_rejections_preserve_valid_plan(handler: LearningPlanDraftCapabilityHandler) -> None:
    assert handler._artifact(session={}, capability_input=_input()).profile.language_id == "python"
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        handler._artifact(session={}, capability_input=_input(
            module_1=_module("first", "python.first", prerequisite="python.second"),
            module_2=_module("second", "python.second", prerequisite="python.first"),
        ))
    assert _fields(caught.value)["stage"] == "plan_domain"
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        handler._artifact(session={"preferred_language_id": "sql"}, capability_input=_input())
    assert _fields(caught.value)["stage"] == "session_language"
    assert _fields(caught.value)["field_path"] == "profile.language_id"


def test_fact_message_allowlist_maps_pace_and_keeps_unknown_failure_closed(
    handler: LearningPlanDraftCapabilityHandler, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(handler._facts, "validate_profile", Mock(side_effect=[
        PlanningFactError("plan profile conflicts with confirmed fact pace_constraints"),
        PlanningFactError("plan profile conflicts with confirmed fact private-value"),
    ]))
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        handler.generate(run=_run(), capability_input=_input())
    assert _fields(caught.value)["stage"] == "confirmed_fact_conflict"
    assert _fields(caught.value)["field_path"] == "profile.pace_summary"
    with pytest.raises(LearningPlanDraftCapabilityError) as caught:
        handler.generate(run=_run(), capability_input=_input())
    assert _fields(caught.value)["stage"] == "confirmed_fact_validation"
    assert _fields(caught.value)["field_path"] == "profile"
    assert "private-value" not in repr(caught.value.safe_diagnostics)
    cast(Mock, handler._repository.append_draft).assert_not_called()


def test_gateway_exposes_safe_diagnostics_in_result_and_log(
    handler: LearningPlanDraftCapabilityHandler, caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = CatalogCapabilityGateway(
        catalog=Mock(), policy_resolver=Mock(), selection_store=Mock(), learning_plan_handler=handler,
    )
    result = gateway._dispatch_learning_plan(
        request=TutorCapabilityRequest(request_id="diagnostic-request", capability_id="learning.plan.draft"),
        run=_run(), arguments=_input(profile_json=_profile(weekly_minutes="private-value")).model_dump(),
    )
    fields = {field.key: field.value for field in result.safe_result}
    assert result.status is TutorCapabilityStatus.DENIED
    assert result.diagnostic_code == "learning_plan_draft_invalid"
    assert fields["code"] == "LEARNING_PLAN_DRAFT_INVALID"
    assert fields["stage"] == "compact_profile"
    assert fields["field_path"] == "profile.weekly_minutes"
    assert fields["repair_guidance"]
    assert "learning_plan_draft_validation_failed" in caplog.text
    assert "profile.weekly_minutes" in caplog.text
    assert "private-value" not in caplog.text + repr(result)
    assert LearningPlanDraftCapabilityError(
        code="UNCHANGED", diagnostic_code="unchanged", status=TutorCapabilityStatus.DENIED,
    ).safe_diagnostics == ()
