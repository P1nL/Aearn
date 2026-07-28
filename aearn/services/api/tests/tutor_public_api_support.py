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
    TutorDecision,
    TutorProviderResult,
    TutorRunResult,
    TutorRunStatus,
    TutorTerminalOutcome,
)
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.main import app
from app.services.tutor.interactive import TutorInteractiveRunDispatcher


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
    settings = Settings(tutor_harness_enabled=True, llm_type="disabled")
    monkeypatch.setattr(tutor_route, "get_settings", lambda: settings)
    return settings


def create_tutor_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"Tutor API {uuid.uuid4().hex[:10]}",
            "learning_style": "practice_first",
            "teaching_preference": "step_by_step",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert isinstance(user, dict)
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
    outcome: TutorTerminalOutcome = TutorTerminalOutcome.COMPLETED
    calls: list[tuple[str, int]] = field(default_factory=list)

    def decide(self, *, run, context) -> TutorProviderResult:  # type: ignore[no-untyped-def]
        self.calls.append((run.run_id, run.input_revision))
        if self.outcome is TutorTerminalOutcome.COMPLETED:
            return TutorProviderResult(
                decision=TutorDecision(public_message=self.message, terminal_outcome=TutorTerminalOutcome.COMPLETED)
            )
        return TutorProviderResult(decision=None, terminal_outcome=self.outcome, safe_code="fixture_terminal")


def terminal_dispatcher(*, settings: Settings, message: str = "请先比较变量声明的位置与可见范围。") -> tuple[TutorInteractiveRunDispatcher, TerminalTutorProvider]:
    provider = TerminalTutorProvider(message=message)
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