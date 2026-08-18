from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agents.codex_spike.preflight import resolve_codex_executable
from app.agents.codex_spike.real_smoke import run_real_deepseek_smoke

_APPROVAL_TOKEN = "approved-2026-08-18-codex-sidecar-spike"


@pytest.mark.real_provider
@pytest.mark.asyncio
async def test_real_deepseek_v4_flash_tool_repair_smoke(tmp_path: Path) -> None:
    if os.environ.get("AEARN_CODEX_REAL_SMOKE_APPROVAL") != _APPROVAL_TOKEN:
        pytest.skip("not_run_requires_approval")
    base_url = os.environ.get("DEEPSEEK_BASE_URL")
    if not base_url:
        pytest.fail("DEEPSEEK_BASE_URL is required after approval")
    executable = resolve_codex_executable()
    if executable is None:
        pytest.fail("Codex executable is required after approval")
    result = await run_real_deepseek_smoke(approved=True, root=tmp_path / "real-smoke", base_url=base_url, executable=executable)
    assert result.status == "completed"
    assert result.model == "deepseek-v4-flash"
    assert result.model_provider == "aearn_deepseek"
    assert result.endpoint.endswith("/responses")
    assert result.tool_attempts == (1, 2)
    assert result.retained_raw_prompt is False
    assert result.retained_raw_response is False
