from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.services.learning.artifacts.contracts import ARTIFACT_PROTECTED_MARKERS
from app.services.tutor.conversation_contracts import (
    TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION,
    TUTOR_CONVERSATION_READABLE_SNAPSHOT_VERSIONS,
    TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION,
    TUTOR_CONVERSATION_SNAPSHOT_V4_VERSION,
    TUTOR_CONVERSATION_SNAPSHOT_V5_VERSION,
    TUTOR_CONVERSATION_SNAPSHOT_VERSION,
    TutorConversationEventKind,
    validate_conversation_event_payload,
    validate_public_item,
)
from app.services.tutor.persistence import TutorConversationSnapshot
from app.services.tutor.public_api import _conversation_snapshot_payload


def _artifact_payload() -> dict[str, object]:
    return {
        "kind": "artifact",
        "id": "artifact-1",
        "conversation_id": "conversation-1",
        "turn_id": None,
        "learning_track_id": "track-1",
        "knowledge_key": "python.variables",
        "teaching_session_id": "teaching-session-1",
        "checkpoint_id": "checkpoint-1",
        "artifact_version": 1,
        "artifact_kind": "knowledge_check",
        "purpose": "knowledge_check",
        "owner_kind": "teaching_practice",
        "owner_id": "checkpoint-1",
        "owner_version": 1,
        "state": "active",
        "blocking": True,
        "title": "变量赋值检查",
        "instruction_markdown": "选择赋值后变量的值。",
        "difficulty": "D1",
        "presentation": {
            "type": "knowledge_check_v1",
            "response_kind": "single_select",
            "prompt_markdown": "执行 value = 2 后，value 是多少？",
            "options": [
                {"value": "2", "label": "2"},
                {"value": "3", "label": "3"},
            ],
            "minimum_selections": 1,
            "maximum_selections": 1,
            "maximum_text_length": 2_000,
        },
        "allowed_actions": ["respond"],
        "source_references": [],
        "active_attempt": None,
        "branch_summary": None,
        "version": 1,
        "created_at": "2026-08-31T00:00:00+00:00",
        "updated_at": "2026-08-31T00:00:00+00:00",
        "terminal_at": None,
    }


def test_public_item_union_accepts_strict_learner_safe_artifact() -> None:
    artifact = validate_public_item(_artifact_payload())

    assert artifact["kind"] == "artifact"
    assert artifact["presentation"]["type"] == "knowledge_check_v1"  # type: ignore[index]
    assert artifact["allowed_actions"] == ["respond"]

    with pytest.raises(ValidationError):
        validate_public_item({**artifact, "raw_submission": "private learner answer"})

    protected = {**artifact, "title": ARTIFACT_PROTECTED_MARKERS[0]}
    with pytest.raises(ValueError, match="protected marker"):
        validate_public_item(protected)


def test_artifact_conversation_event_is_reference_only_and_strict() -> None:
    payload = validate_conversation_event_payload(
        TutorConversationEventKind.ITEM_ADDED,
        {
            "item": {
                "item_id": "artifact-1",
                "item_kind": "artifact",
                "turn_id": None,
            }
        },
    )

    assert payload == {
        "item": {
            "item_id": "artifact-1",
            "item_kind": "artifact",
        }
    }
    assert "presentation" not in repr(payload)
    assert "submission" not in repr(payload)

    with pytest.raises(ValidationError):
        validate_conversation_event_payload(
            TutorConversationEventKind.ITEM_UPDATED,
            {
                "item": {
                    "item_id": "artifact-1",
                    "item_kind": "artifact",
                    "turn_id": None,
                    "submission": "must never enter SSE",
                }
            },
        )


def test_snapshot_v4_is_current_while_v3_remains_a_readable_contract() -> None:
    assert TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION == "tutor_conversation_event_v3"
    assert TUTOR_CONVERSATION_SNAPSHOT_VERSION == TUTOR_CONVERSATION_SNAPSHOT_V5_VERSION
    assert TUTOR_CONVERSATION_READABLE_SNAPSHOT_VERSIONS == {
        TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION,
        TUTOR_CONVERSATION_SNAPSHOT_V4_VERSION,
        TUTOR_CONVERSATION_SNAPSHOT_V5_VERSION,
    }

    legacy = TutorConversationSnapshot(
        conversation_id="conversation-1",
        title=None,
        control_version=1,
        control_state="idle",
        queue_paused=False,
        queue_pause_reason=None,
        pending_count=0,
        max_pending=10,
        active_turn=None,
        active_thinking=None,
        active_runtime_output=None,
        active_artifact=None,
        pending_requests=(),
        queue=(),
        timeline=(),
        next_cursor=None,
        has_more=False,
        stream_cursor="legacy-cursor",
        snapshot_version=TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION,
    )
    legacy_payload = _conversation_snapshot_payload(legacy)
    assert legacy_payload["snapshot_version"] == TUTOR_CONVERSATION_SNAPSHOT_V3_VERSION
    assert "active_artifact" not in legacy_payload

    current = replace(
        legacy,
        snapshot_version=TUTOR_CONVERSATION_SNAPSHOT_V4_VERSION,
    )
    assert _conversation_snapshot_payload(current)["active_artifact"] is None
