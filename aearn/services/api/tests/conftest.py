from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.services.exercises import adaptive_exercise_service
from app.services.exercises.adaptive_exercise_service import GeneratedAdaptiveCandidate


@pytest.fixture(autouse=True)
def disable_live_adaptive_model_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adaptive_exercise_service, "build_model_candidate", _fake_adaptive_model_candidate)


def _fake_adaptive_model_candidate(
    model_context: Mapping[str, object],
    template: object,
) -> GeneratedAdaptiveCandidate:
    fallback = getattr(template, "fallback_payload")
    assert isinstance(fallback, Mapping)
    required_skill_tags = model_context.get("required_skill_tags")
    target_skill_tags = list(required_skill_tags) if isinstance(required_skill_tags, list) else []
    return GeneratedAdaptiveCandidate(
        content={
            "candidate": {
                "title": f"{fallback['title']}：模型生成练习",
                "prompt_markdown": fallback["prompt_markdown"],
                "starter_code": fallback["starter_code"],
                "solution_reference": fallback["solution_reference"],
                "metadata_json": fallback["metadata_json"],
                "exercise_intent": "Align the exercise with the current route knowledge point.",
                "target_skill_tags": target_skill_tags,
                "alignment_claims": target_skill_tags,
            }
        },
        model="fake-adaptive-exercise-model",
    )
