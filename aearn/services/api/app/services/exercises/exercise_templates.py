from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


ADAPTIVE_TEMPLATE_GENERATOR_VERSION = "adaptive_template_v2"
ADAPTIVE_TEMPLATE_PROMPT_VERSION = "adaptive_template_prompt_v2"


@dataclass(frozen=True, slots=True)
class CanonicalExerciseTemplate:
    template_id: str
    template_version: str
    language_id: str
    runtime_tier: str
    runner_key: str
    exercise_type: str
    difficulty: int
    fallback_payload: Mapping[str, object]


def select_canonical_exercise_template(
    *,
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
    fallback_template: Mapping[str, object],
) -> CanonicalExerciseTemplate:
    language = str(runtime_profile.get("language") or "unknown")
    runtime_tier = str(runtime_profile.get("runtime_tier") or "none")
    runner_key = str(runtime_profile.get("runner") or "none")
    exercise_type = str(fallback_template.get("exercise_type") or "code_blank")
    template_family = _template_family(language, runtime_tier, exercise_type)
    return CanonicalExerciseTemplate(
        template_id=f"{template_family}-v1",
        template_version="1.0.0",
        language_id=language,
        runtime_tier=runtime_tier,
        runner_key=runner_key,
        exercise_type=exercise_type,
        difficulty=_int_or_default(fallback_template.get("difficulty"), 1),
        fallback_payload=fallback_template,
    )


def _template_family(language: str, runtime_tier: str, exercise_type: str) -> str:
    normalized_language = language.replace("_", "-")
    normalized_runtime = runtime_tier.replace("_", "-")
    normalized_type = exercise_type.replace("_", "-")
    return f"{normalized_language}-{normalized_runtime}-{normalized_type}"


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default
