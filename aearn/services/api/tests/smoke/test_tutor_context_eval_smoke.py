from __future__ import annotations

import pytest

from app.services.tutor import context_eval_smoke
from app.services.tutor.context_eval_smoke import evaluate_context_smoke_turn


def test_context_eval_smoke_is_disabled_before_settings_or_provider_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("TUTOR_REAL_PROVIDER_SMOKE", raising=False)
    monkeypatch.setattr(
        context_eval_smoke,
        "get_settings",
        lambda: pytest.fail("settings must not load while real smoke is disabled"),
    )

    assert context_eval_smoke.main() == 2
    assert '"status": "disabled"' in capsys.readouterr().out


def test_context_eval_smoke_rubric_keeps_correction_and_advice_bounded() -> None:
    correction = evaluate_context_smoke_turn(4, "明白，我们改为学习 Python，不再继续旧的网站图片步骤。")
    advice = evaluate_context_smoke_turn(5, "建议先学 JavaScript，再按需要补 Python 和 SQL。")

    assert all(correction.values())
    assert all(advice.values())
