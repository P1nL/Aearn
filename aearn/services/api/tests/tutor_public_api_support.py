from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import (
    TutorCheckpointReason,
    TutorContinuationKind,
    TutorDecision,
    TutorProviderResult,
    TutorRunResult,
    TutorRunStatus,
    TutorTerminalOutcome,
)
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.thread_turn_cutover import THREAD_TURN_CUTOVER_VERSION


def tutor_database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def tutor_client() -> Iterator[TestClient]:
    if not tutor_database_available():
        pytest.skip("PostgreSQL is not available; run aearn infra compose for Tutor API tests.")
    bootstrap_database()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def tutor_api_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(llm_type="disabled", tutor_thread_turn_v2_enabled=True)
    monkeypatch.setattr(tutor_route, "get_settings", lambda: settings)
    return settings


def create_tutor_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"Tutor API {uuid.uuid4().hex[:10]}",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert isinstance(user, dict)
    decision = client.get(f"/api/harness/cutover?user_id={user['id']}")
    assert decision.status_code == 200
    assert decision.json()["state"] == "verified"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO tutor_thread_turn_cutovers (
              cutover_version, state, generation, summary_hash, counts_json, ready_at, enabled_at
            ) VALUES (%s, 'enabled', 1, %s, '{}'::jsonb, now(), now())
            ON CONFLICT (cutover_version) DO UPDATE
            SET state = 'enabled', generation = GREATEST(tutor_thread_turn_cutovers.generation, 1),
                summary_hash = EXCLUDED.summary_hash, counts_json = '{}'::jsonb,
                block_code = NULL, ready_at = now(), enabled_at = now()
            """,
            (THREAD_TURN_CUTOVER_VERSION, "0" * 64),
        )
        conn.commit()
    return user


def action_payload(user_id: str, action_id: str, **extra: object) -> dict[str, object]:
    return {"user_id": user_id, "client_action_id": action_id, **extra}


def assert_error(response, code: str, status_code: int) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == status_code
    payload = response.json()
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"].get("request_id"), str)


@dataclass
class RecordingTutorDispatcher:
    calls: list[tuple[str, str]] = field(default_factory=list)

    def dispatch(self, *, user_id: str, run_id: str) -> TutorRunResult:
        self.calls.append((user_id, run_id))
        return TutorRunResult(
            run_id=run_id,
            status=TutorRunStatus.WAITING_FOR_INPUT,
            input_revision=0,
            iteration_count=0,
            model_call_count=0,
            capability_call_count=0,
            effect_count=0,
        )


@dataclass
class TerminalTutorProvider:
    message: str
    public_thinking_text: str = "我先定位学习者当前最需要澄清的概念。\n\n接着选择一个能够马上验证理解的小例子。"
    outcome: TutorTerminalOutcome = TutorTerminalOutcome.COMPLETED
    conversation_title: str | None = None
    stream_public_thinking: bool = False
    calls: list[tuple[str, int]] = field(default_factory=list)

    def decide(self, *, run, context, thinking_sink=None) -> TutorProviderResult:  # type: ignore[no-untyped-def]
        del context
        self.calls.append((run.run_id, run.input_revision))
        if self.stream_public_thinking and thinking_sink is not None and self.outcome is TutorTerminalOutcome.COMPLETED:
            thinking_sink.begin_attempt(1)
            thinking_sink.append_text(1, self.public_thinking_text)
            thinking_sink.complete_attempt(1)
        if self.outcome is TutorTerminalOutcome.COMPLETED:
            return TutorProviderResult(
                decision=TutorDecision(
                    public_message=self.message,
                    public_thinking_text=self.public_thinking_text,
                    conversation_title=self.conversation_title,
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            )
        return TutorProviderResult(decision=None, terminal_outcome=self.outcome, safe_code="fixture_terminal")


def terminal_dispatcher(
    *,
    settings: Settings,
    message: str = "请先比较变量声明的位置与可见范围。",
    conversation_title: str | None = None,
    public_thinking_text: str = "我先定位学习者当前最需要澄清的概念。\n\n接着选择一个能够马上验证理解的小例子。",
    stream_public_thinking: bool = False,
) -> tuple[TutorInteractiveRunDispatcher, TerminalTutorProvider]:
    provider = TerminalTutorProvider(
        message=message,
        public_thinking_text=public_thinking_text,
        conversation_title=conversation_title,
        stream_public_thinking=stream_public_thinking,
    )
    return (
        TutorInteractiveRunDispatcher(settings=settings, provider_factory=lambda _settings: provider),
        provider,
    )


@dataclass
class WaitingTutorProvider:
    message: str
    continuation_kind: TutorContinuationKind = TutorContinuationKind.CLARIFICATION
    question_key: str | None = None
    public_thinking_text: str = "我先确认当前信息还不足以安全给出下一步。"
    stream_public_thinking: bool = False
    calls: list[tuple[str, int]] = field(default_factory=list)

    def decide(self, *, run, context, thinking_sink=None) -> TutorProviderResult:  # type: ignore[no-untyped-def]
        del context
        self.calls.append((run.run_id, run.input_revision))
        if self.stream_public_thinking and thinking_sink is not None:
            thinking_sink.begin_attempt(1)
            thinking_sink.append_text(1, self.public_thinking_text)
            thinking_sink.complete_attempt(1)
        return TutorProviderResult(
            decision=TutorDecision(
                public_message=self.message,
                public_thinking_text=self.public_thinking_text,
                question_key=self.question_key,
                checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT,
                continuation_kind=self.continuation_kind,
            )
        )


def waiting_dispatcher(
    *,
    settings: Settings,
    message: str,
    continuation_kind: TutorContinuationKind = TutorContinuationKind.CLARIFICATION,
    question_key: str | None = None,
    public_thinking_text: str = "我先确认当前信息还不足以安全给出下一步。",
    stream_public_thinking: bool = False,
) -> tuple[TutorInteractiveRunDispatcher, WaitingTutorProvider]:
    provider = WaitingTutorProvider(
        message=message,
        continuation_kind=continuation_kind,
        question_key=question_key,
        public_thinking_text=public_thinking_text,
        stream_public_thinking=stream_public_thinking,
    )
    return (
        TutorInteractiveRunDispatcher(settings=settings, provider_factory=lambda _settings: provider),
        provider,
    )


def parse_sse_events(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        if not frame.strip():
            continue
        event_type = ""
        event_id: str | None = None
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("id:"):
                event_id = line.removeprefix("id:").strip()
            elif line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        events.append({"id": event_id, "event": event_type, "data": json.loads("\n".join(data_lines))})
    return events
