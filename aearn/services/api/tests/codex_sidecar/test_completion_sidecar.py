"""CPU-only completion Sidecar contracts; no database or real App Server."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.runtime.codex_adapter import CodexAppServerRuntime
from app.agents.runtime.codex_config import CodexRuntimeConfig
from app.agents.runtime.codex_supervisor import RuntimeUnavailableError
from app.agents.runtime.learning_plan_tools import LearningPlanToolBudget
from app.core.config import Settings
from app.services.tutor.runtime_projection import (
    PostgresTutorRuntimeProjectionRepository,
    TutorRuntimeProjectionEvent,
    TutorRuntimeProjectionFence,
    TutorRuntimeProjectionStatus,
)
from tests.codex_sidecar.test_planning_runtime_limits import FakeAppServer, _notification, _request


def test_completion_config_keeps_rpc_and_legacy_bounds_and_discloses_wire_limit() -> None:
    config = CodexRuntimeConfig.from_settings(Settings())
    assert not config.completion_driven_enabled
    assert config.completion_turn_timeout_s == 900
    assert config.turn_timeout_s == 300
    assert config.startup_timeout_s == config.request_timeout_s == 15
    assert not config.model_max_output_tokens_wire_enforced
    assert not config.remote_compaction_supported
    assert LearningPlanToolBudget(max_wall_seconds=900).max_wall_seconds == 900
    assert LearningPlanToolBudget().max_wall_seconds == 300


@pytest.mark.parametrize("completion,expected", [(False, 300), (True, 900)])
def test_adapter_uses_admitted_work_turn_not_rpc_deadline(tmp_path, completion, expected) -> None:
    server = FakeAppServer(tmp_path, [
        _notification("turn/completed", turn={"id": "private-turn", "status": "completed"}),
    ])
    server.config = replace(server.config, turn_timeout_s=300,
                            completion_driven_enabled=True, completion_turn_timeout_s=900)
    result = asyncio.run(CodexAppServerRuntime(server).run_turn(_request(completion_driven=completion)))
    assert result.metrics.effective_timeout_seconds == expected
    assert result.metrics.effective_max_total_text_chars == server.config.max_visible_text_chars


def test_adapter_rejects_unadmitted_completion_before_preparing_turn(tmp_path) -> None:
    server = FakeAppServer(tmp_path, [])
    with pytest.raises(RuntimeUnavailableError, match="runtime_completion_profile_disabled"):
        asyncio.run(CodexAppServerRuntime(server).run_turn(_request(completion_driven=True)))
    assert server.registry is None
    assert server.timeline == []


def test_adapter_caps_work_turn_at_remaining_batch_time(tmp_path) -> None:
    server = FakeAppServer(tmp_path, [
        _notification("turn/completed", turn={"id": "private-turn", "status": "completed"}),
    ])
    server.config = replace(server.config, completion_driven_enabled=True, completion_turn_timeout_s=900)
    result = asyncio.run(CodexAppServerRuntime(server).run_turn(
        _request(completion_driven=True, timeout_seconds=42),
    ))
    assert result.metrics.effective_timeout_seconds == 42


def test_internal_terminal_closes_only_binding_not_original_run() -> None:
    statements = []
    binding = {"id": "binding", "step_attempt_id": "step", "final_message_id": None}

    def execute(sql, args):
        statements.append((sql, args))
        return SimpleNamespace(fetchone=lambda: binding)

    repository = PostgresTutorRuntimeProjectionRepository.__new__(PostgresTutorRuntimeProjectionRepository)
    repository._conn = SimpleNamespace(execute=execute)
    discarded = []
    repository._discard_streaming_text_items = lambda **kwargs: discarded.append(kwargs)
    status, item, kind = repository._project_terminal(
        binding=binding, run={"id": "original-run"},
        fence=TutorRuntimeProjectionFence(1, "owner", 1, 1),
        event=TutorRuntimeProjectionEvent(
            kind="turn_completed", thread_id="thread", sequence=2,
            occurred_at=datetime.now(UTC), terminal_status="completed",
        ),
    )
    assert status is TutorRuntimeProjectionStatus.APPLIED
    assert item is kind is None
    assert len(discarded) == 1
    assert statements[-1][1][0] == "completed"
    assert not any("UPDATE tutor_runs" in sql for sql, _ in statements)


def test_binding_sql_adds_no_table_and_preserves_scope_and_terminal_identity() -> None:
    sql = (Path(__file__).resolve().parents[2] / "app/db/schema/598_tutor_completion_sidecar_bindings.sql").read_text()
    assert "CREATE TABLE" not in sql
    assert "FOREIGN KEY (step_attempt_id, run_id, user_id, conversation_id)" in sql
    assert "REFERENCES tutor_run_step_attempts(id, run_id, user_id, conversation_id)" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "WHERE step_attempt_id IS NULL" in sql
    assert "ON tutor_run_runtime_bindings(step_attempt_id)" in sql
    assert "WHERE state IN ('thread_bound', 'running')" in sql
    assert "NEW.step_attempt_id IS DISTINCT FROM OLD.step_attempt_id" in sql
    assert "Tutor runtime terminal binding is immutable" in sql
