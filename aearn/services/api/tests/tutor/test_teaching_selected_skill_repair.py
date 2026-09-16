"""Offline guards for the selected teaching Skill's provider action phase."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextInput,
    TutorContextSection,
    TutorContextSelection,
    TutorContextSource,
    TutorPolicySnapshot,
    TutorProviderAttemptOutcome,
    TutorRunSnapshot,
    TutorTerminalOutcome,
)
from app.core.config import Settings
from app.services.llm.llm_client import LLMJsonResponse, LLMVisibleOutputObserver, OpenAICompatibleClient
from app.services.tutor.decision_protocol import (
    canonical_tutor_provider_items_example,
    canonical_tutor_teaching_step_example,
)
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway


_SELECTED_SOURCE = "catalog:selected:tutor.lesson-teaching@1.2.1"
_REJECTED_TEXT = "Discarded candidate marker 972."
_ISSUE = "action.type:teaching_step_required"


class _SequencedJsonClient:
    model = "offline-primary-model"

    def __init__(self, contents: list[dict[str, object]]) -> None:
        self._contents = list(contents)
        self.messages: list[tuple[dict[str, str], ...]] = []
        self.calls = 0

    def complete_json(
        self, messages: Sequence[Mapping[str, str]], *,
        temperature: float | None = None, max_tokens: int | None = None,
        timeout_seconds: float | None = None, output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None, thinking_mode: Literal["enabled", "disabled"] | None = None,
        capture_provider_body: bool = False, visible_output_observer: LLMVisibleOutputObserver | None = None,
    ) -> LLMJsonResponse:
        del temperature, max_tokens, timeout_seconds, output_schema, schema_name, thinking_mode, capture_provider_body
        assert visible_output_observer is None
        self.calls += 1
        self.messages.append(tuple(dict(message) for message in messages))
        return LLMJsonResponse(content=self._contents.pop(0), model=self.model)


class _RecordingThinkingSink:
    def __init__(self) -> None:
        self.operations: list[tuple[str, int, str]] = []

    def begin_attempt(self, attempt_index: int) -> None:
        self.operations.append(("begin", attempt_index, ""))

    def append_text(self, attempt_index: int, text: str) -> None:
        self.operations.append(("append", attempt_index, text))

    def complete_attempt(self, attempt_index: int) -> None:
        self.operations.append(("complete", attempt_index, ""))

    def reset_attempt(self, attempt_index: int) -> None:
        self.operations.append(("reset", attempt_index, ""))

    def discard_attempt(self, attempt_index: int) -> None:
        self.operations.append(("discard", attempt_index, ""))

    def discard_current(self) -> None:
        raise AssertionError("Gateway must discard the exact rejected attempt")


def _run(*, stimulus_kind: str = "domain_event") -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="selected-teaching-run", conversation_id="selected-teaching-conversation",
        user_id="selected-teaching-user", input_revision=int(stimulus_kind == "learner_message"), origin="interactive",
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
    )


def _context(
    *, teaching: bool = True, selected_source: str | None = _SELECTED_SOURCE,
    stimulus_kind: str = "domain_event", event_kind: str = "assignment_changed",
) -> TutorContextSelection:
    stimulus = {"kind": stimulus_kind}
    if stimulus_kind == "domain_event":
        stimulus["event_kind"] = event_kind
    elif stimulus_kind == "teaching_control":
        stimulus["control_key"] = "open_session"
    learner_input = stimulus_kind == "learner_message"
    run = _run(stimulus_kind=stimulus_kind)
    return TutorContextBuilder().build(
        TutorContextInput(
            run_id=run.run_id, conversation_id=run.conversation_id,
            input_revision=run.input_revision, current_input_required=learner_input,
            current_input=(TutorContextSource("message-current", "Explain variables.") if learner_input else None),
            teaching_session=(
                (TutorContextSource("teaching-session:fixture", {
                    "session": {"session_id": "fixture", "mode": "guided", "progress_status": "in_progress"},
                    "stimulus": stimulus,
                }),) if teaching else ()
            ),
            system_descriptors=(
                (TutorContextSource(selected_source, {"instruction": "Return one teaching_step."}),)
                if selected_source else ()
            ),
        ),
        token_budget=2000,
    )


def _payload(action_type: str = "select_skill") -> dict[str, object]:
    payload = json.loads(canonical_tutor_provider_items_example())
    payload["message"]["text"] = _REJECTED_TEXT
    payload["message"]["public_thinking_text"] = _REJECTED_TEXT
    payload["action"] = {"type": action_type}
    if action_type == "select_skill":
        payload["action"].update(skill_id="tutor.lesson-teaching", version="1.2.1")
    elif action_type == "request_capability":
        payload["action"].update(capability_id="grounding.retrieve", arguments=[])
    elif action_type == "propose_effect":
        payload["action"].update(effect_type="memory.upsert", payload=[])
    elif action_type == "wait_for_input":
        payload["action"]["continuation_kind"] = "clarification"
    return payload


def _teaching_payload() -> dict[str, object]:
    return json.loads(canonical_tutor_teaching_step_example())


def test_repeated_selection_exhausts_existing_repair_without_acceptance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _SequencedJsonClient([_payload(), _payload(), _teaching_payload()])
    with caplog.at_level(logging.WARNING):
        result = PrimaryTutorProviderGateway(
            settings=Settings(llm_type="disabled"), client=client,
        ).decide(run=_run(), context=_context())

    assert client.calls == 2
    assert result.decision is None
    assert result.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    assert result.safe_code == "TUTOR_PROVIDER_DECISION_INVALID"
    assert [attempt.attempt_index for attempt in result.attempts] == [1, 2]
    assert all(attempt.outcome is TutorProviderAttemptOutcome.REPAIRABLE_REJECTED for attempt in result.attempts)
    assert all(attempt.diagnostic_code == result.safe_code for attempt in result.attempts)
    assert _ISSUE in client.messages[1][-1]["content"]
    assert client.messages[1][:-1] == client.messages[0]
    assert _REJECTED_TEXT not in json.dumps(client.messages[1])
    assert _REJECTED_TEXT not in caplog.text
    assert '"field_path":"action.type"' in caplog.text
    assert '"stage":"teaching_step_required"' in caplog.text


@pytest.mark.parametrize("stimulus_kind,event_kind", [
    ("domain_event", "assignment_changed"),
    ("domain_event", "gate_terminal"),
    ("teaching_control", ""),
    ("learner_message", ""),
])
@pytest.mark.parametrize("action_type", [
    "select_skill", "turn_completed", "wait_for_input", "request_capability", "propose_effect",
])
def test_non_teaching_action_replaced_once_for_selected_teaching_scope(
    stimulus_kind: str, event_kind: str, action_type: str,
) -> None:
    client = _SequencedJsonClient([_payload(action_type), _teaching_payload()])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client,
    ).decide(
        run=_run(stimulus_kind=stimulus_kind),
        context=_context(stimulus_kind=stimulus_kind, event_kind=event_kind),
    )

    assert client.calls == 2
    assert result.decision is not None and result.decision.teaching_step is not None
    assert not result.decision.skill_references
    assert [attempt.outcome for attempt in result.attempts] == [
        TutorProviderAttemptOutcome.REPAIRABLE_REJECTED, TutorProviderAttemptOutcome.ACCEPTED,
    ]
    assert _ISSUE in client.messages[1][-1]["content"]
    assert _REJECTED_TEXT not in json.dumps(client.messages[1])


def test_first_selection_without_selected_skill_remains_accepted() -> None:
    client = _SequencedJsonClient([_payload()])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client,
    ).decide(run=_run(), context=_context(selected_source=None))

    assert client.calls == 1
    assert result.decision is not None and result.decision.teaching_step is None
    assert result.decision.skill_references[0].skill_id == "tutor.lesson-teaching"
    assert result.attempts[0].outcome is TutorProviderAttemptOutcome.ACCEPTED


@pytest.mark.parametrize("selected_source", [None, _SELECTED_SOURCE])
def test_non_teaching_scope_ignores_skill_mentions_in_provider_text(selected_source: str | None) -> None:
    payload = _payload("turn_completed")
    message = payload["message"]
    assert isinstance(message, dict)
    message["text"] = f"TEACHING_SESSION teaching-session:fixture {_SELECTED_SOURCE}"
    client = _SequencedJsonClient([payload])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client,
    ).decide(run=_run(), context=_context(teaching=False, selected_source=selected_source))

    assert client.calls == 1
    assert result.decision is not None
    assert result.decision.terminal_outcome is TutorTerminalOutcome.COMPLETED


@pytest.mark.parametrize("selected_source", [
    "catalog:eligible-skills", "catalog:selected:tutor.lesson-teaching@1.2.0",
    "catalog:selected:tutor.lesson-teaching@1.2.10", "catalog:selected:tutor.other@1.2.1",
])
def test_only_exact_selected_skill_marker_enters_repair(selected_source: str) -> None:
    client = _SequencedJsonClient([_payload()])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client,
    ).decide(run=_run(), context=_context(selected_source=selected_source))

    assert client.calls == 1
    assert result.decision is not None
    # The final catalog/teaching Gate remains responsible for accepting these actions.
    assert result.attempts[0].outcome is TutorProviderAttemptOutcome.ACCEPTED


def test_selected_marker_outside_system_section_is_not_authority() -> None:
    context = _context()
    context = replace(context, items=tuple(
        replace(item, section=TutorContextSection.RECENT_MESSAGES)
        if item.source_id == _SELECTED_SOURCE else item for item in context.items
    ))
    client = _SequencedJsonClient([_payload()])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client,
    ).decide(run=_run(), context=context)
    assert client.calls == 1
    assert result.decision is not None


def test_legal_teaching_step_is_accepted_without_replacement() -> None:
    client = _SequencedJsonClient([_teaching_payload()])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client,
    ).decide(run=_run(), context=_context())
    assert client.calls == 1
    assert result.decision is not None and result.decision.teaching_step is not None
    assert result.attempts[0].outcome is TutorProviderAttemptOutcome.ACCEPTED


@pytest.mark.parametrize("replacement_valid", [False, True])
def test_provisional_thinking_is_discarded_before_repair_and_never_completed_on_rejection(
    replacement_valid: bool,
) -> None:
    contents = [_payload(), _teaching_payload() if replacement_valid else _payload()]
    calls: list[Mapping[str, object]] = []

    def transport(
        url: str, headers: Mapping[str, str], payload: Mapping[str, object], timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, timeout
        calls.append(payload)
        return {"type": "response.completed", "response": {
            "model": "deepseek-flash", "output": [{
                "type": "message", "content": [{
                    "type": "output_text", "text": json.dumps(contents.pop(0)),
                }],
            }],
        }}

    settings = Settings(
        llm_type="deepseek", deepseek_model="deepseek-flash",
        deepseek_api_key="test-key", deepseek_base_url="https://fixture.invalid/v1",
    )
    sink = _RecordingThinkingSink()
    result = PrimaryTutorProviderGateway(
        settings=settings, client=OpenAICompatibleClient(settings, transport=transport),
    ).decide(run=_run(), context=_context(), thinking_sink=sink)

    assert len(calls) == 2
    assert ("complete", 1, "") not in sink.operations
    assert ("discard", 1, "") in sink.operations
    assert sink.operations.index(("discard", 1, "")) < sink.operations.index(("begin", 2, ""))
    assert "".join(text for op, index, text in sink.operations if op == "append" and index == 1) == _REJECTED_TEXT
    if replacement_valid:
        assert result.decision is not None and result.decision.teaching_step is not None
        assert sink.operations[-1] == ("complete", 2, "")
    else:
        assert result.decision is None
        assert result.safe_code == "TUTOR_PROVIDER_DECISION_INVALID"
        assert not any(op == "complete" for op, _, _ in sink.operations)
        assert sink.operations[-1] == ("discard", 2, "")
