from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings


def test_start_dev_starts_codex_worker_by_default_with_explicit_opt_out() -> None:
    aearn_root = Path(__file__).resolve().parents[3]
    script = (aearn_root / "scripts" / "start-dev.ps1").read_text(encoding="utf-8")
    package = json.loads((aearn_root / "package.json").read_text(encoding="utf-8"))

    assert "[switch]$NoCodexWorker" in script
    assert "if (-not $NoCodexWorker)" in script
    assert "-Q tutor-codex" in script
    assert "--pool=solo --concurrency=1" in script
    assert "codexWorkerPid" in script
    assert "worker(?!.*tutor-codex)" in script
    assert package["scripts"]["dev:no-codex"].endswith("-NoCodexWorker")

    worker_app = (
        aearn_root / "services" / "worker" / "aearn_worker" / "worker_app.py"
    ).read_text(encoding="utf-8")
    assert '"tutor.codex.dispatch"' in worker_app
    assert '"tutor.codex.reconcile"' in worker_app
    assert '"tutor.codex.runtime_health"' in worker_app
    assert 'queue="tutor-codex"' in worker_app


def test_codex_runtime_config_defaults_enabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CODEX_RUNTIME_ENABLED", raising=False)
    settings = Settings()
    assert settings.codex_runtime_enabled is True
    assert settings.tutor_codex_plan_drafting_enabled is True
    assert settings.tutor_codex_runtime_health_max_age_seconds == 90
