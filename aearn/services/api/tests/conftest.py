from __future__ import annotations

import pytest

from app.services.exercises import adaptive_exercise_service


@pytest.fixture(autouse=True)
def disable_live_adaptive_model_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adaptive_exercise_service, "build_model_candidate", lambda _context, _template: None)
