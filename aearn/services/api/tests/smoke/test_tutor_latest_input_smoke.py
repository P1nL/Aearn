from __future__ import annotations

import pytest

from app.services.tutor import latest_input_smoke
from app.services.tutor.latest_input_smoke import evaluate_smoke_message


def test_live_provider_smoke_is_disabled_before_provider_construction_by_default(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AEARN_RUN_TUTOR_LATEST_INPUT_SMOKE", raising=False)
    monkeypatch.setattr(
        latest_input_smoke,
        "get_settings",
        lambda: pytest.fail("settings must not load while live smoke is disabled"),
    )

    assert latest_input_smoke.main() == 2
    assert '"status": "disabled"' in capsys.readouterr().out


def test_latest_input_smoke_rubric_accepts_direct_language_advice_and_abandons_stale_path() -> None:
    rubric = evaluate_smoke_message(
        "language_advice_first",
        "可以先学 JavaScript、HTML 和 CSS；如果之后想做后端，再补 Python。你更想先做网页还是自动化？",
    )

    assert rubric == {
        "latest_turn_relevant": True,
        "correction_acknowledged": True,
        "no_rejected_step_repeated": True,
        "answer_first": True,
        "stale_path_abandoned": True,
    }


def test_latest_input_smoke_rubric_rejects_repeated_stale_image_setup() -> None:
    rubric = evaluate_smoke_message(
        "teaching_direction_correction",
        "请先准备图片并新建图片文件夹，然后继续 HTML。",
    )

    assert rubric["latest_turn_relevant"] is False
    assert rubric["correction_acknowledged"] is False
    assert rubric["no_rejected_step_repeated"] is False
    assert rubric["stale_path_abandoned"] is False
