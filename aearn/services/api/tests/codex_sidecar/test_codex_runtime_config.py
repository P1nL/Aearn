from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.agents.runtime.codex_config import (
    CODEX_ENV_KEY,
    CODEX_MODEL_PROVIDER,
    CodexRuntimeConfig,
    ensure_codex_runtime_home,
)
from app.core.config import (
    DEEPSEEK_V4_FLASH_CODEX_AUTO_COMPACT_TOKENS,
    DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS,
    DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS,
    DEEPSEEK_V4_FLASH_MODEL,
)


def _config(tmp_path: Path) -> CodexRuntimeConfig:
    return CodexRuntimeConfig(
        enabled=True,
        executable_path=None,
        home_root=tmp_path / "runtime-home",
        model=DEEPSEEK_V4_FLASH_MODEL,
        model_provider=CODEX_MODEL_PROVIDER,
        base_url="https://api.deepseek.example/v1",
        env_key=CODEX_ENV_KEY,
        allowed_versions=frozenset(),
        startup_timeout_s=3,
        request_timeout_s=2,
        turn_timeout_s=30,
        shutdown_timeout_s=2,
        notification_queue_size=64,
    )


def test_codex_runtime_home_uses_one_exact_local_compaction_contract(tmp_path: Path) -> None:
    home = ensure_codex_runtime_home(_config(tmp_path))
    text = home.config_path.read_text(encoding="utf-8")

    assert f"model_context_window = {DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS}" in text
    assert f"model_max_output_tokens = {DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS}" in text
    assert f"model_auto_compact_token_limit = {DEEPSEEK_V4_FLASH_CODEX_AUTO_COMPACT_TOKENS}" in text
    assert 'model_auto_compact_token_limit_scope = "total"' in text
    assert 'wire_api = "responses"' in text
    assert "remote_compaction" not in text
    assert home.config_fingerprint == hashlib.sha256(text.encode()).hexdigest()


def test_codex_runtime_home_rejects_remote_or_drifted_compaction(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(ValueError, match="remote compaction"):
        ensure_codex_runtime_home(replace(config, remote_compaction_supported=True))
    with pytest.raises(ValueError, match="verified DeepSeek V4 Flash contract"):
        ensure_codex_runtime_home(replace(config, model_auto_compact_token_limit=949_999))
