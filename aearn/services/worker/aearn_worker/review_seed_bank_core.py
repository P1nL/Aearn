from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


GENERATOR_VERSION = "review_candidate_pool_v1"
CORE_REVIEW_EXERCISE_TYPES = {
    "code_blank",
    "fix_bug",
    "explain_code",
    "implement_function",
    "review_ai_patch",
}
REVIEW_CANDIDATE_CAPABILITIES = {
    "basic_application",
    "concept_explanation",
    "debugging",
    "transfer_or_review",
}
_NORMAL_COUNT_RANGE = (10, 12)
_HIGH_RISK_COUNT_RANGE = (12, 16)
_HARD_CANDIDATE_CAP = 18
_CAPABILITY_EXERCISE_TYPES = {
    "basic_application": {"code_blank", "implement_function"},
    "concept_explanation": {"explain_code"},
    "debugging": {"fix_bug"},
    "transfer_or_review": {"implement_function", "review_ai_patch"},
}


class ReviewSeedBankValidationError(ValueError):
    pass


def build_review_seed_bank_payload(context: Mapping[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    del context
    raise ReviewSeedBankValidationError("review seed bank generation requires a model-generated candidate")


def validate_review_seed_bank(
    seeds: Sequence[Mapping[str, object]],
    *,
    knowledge_point_id: str,
    high_risk: bool,
    requires_review_ai_patch: bool = True,
    supported_exercise_types: Sequence[str] | None = None,
) -> dict[str, object]:
    min_count, max_count = _HIGH_RISK_COUNT_RANGE if high_risk else _NORMAL_COUNT_RANGE
    if len(seeds) > _HARD_CANDIDATE_CAP:
        raise ReviewSeedBankValidationError("candidate count exceeds hard cap")
    if len(seeds) < min_count or len(seeds) > max_count:
        raise ReviewSeedBankValidationError("candidate count is outside required range")

    supported_types = set(supported_exercise_types or tuple(CORE_REVIEW_EXERCISE_TYPES))
    seen_fingerprints: set[str] = set()
    exercise_types: set[str] = set()
    capabilities: set[str] = set()
    focus_tags: set[str] = set()
    core_candidate_count = 0
    rejected: list[str] = []
    for seed in seeds:
        seed_id = _required_text(seed, "id")
        exercise_type = _required_text(seed, "exercise_type")
        if exercise_type not in supported_types:
            rejected.append(f"{seed_id}: unsupported exercise_type")
            continue
        exercise_types.add(exercise_type)
        capability = _required_text(seed, "capability")
        if capability not in REVIEW_CANDIDATE_CAPABILITIES:
            rejected.append(f"{seed_id}: invalid capability")
        elif exercise_type not in _CAPABILITY_EXERCISE_TYPES[capability]:
            rejected.append(f"{seed_id}: capability does not match exercise_type")
        else:
            capabilities.add(capability)
        candidate_focus_tags = _string_list(seed.get("focus_tags"))
        if not candidate_focus_tags:
            rejected.append(f"{seed_id}: focus_tags are required")
        focus_tags.update(candidate_focus_tags)
        _validate_selection_objects(seed_id, seed)
        metadata = _metadata(seed)
        _required_text(metadata, "selection_reason")
        if not isinstance(metadata.get("is_core"), bool):
            rejected.append(f"{seed_id}: metadata.is_core must be boolean")
        elif bool(metadata.get("is_core")):
            core_candidate_count += 1
        if _required_text(seed, "knowledge_point_id") != knowledge_point_id:
            rejected.append(f"{seed_id}: wrong knowledge_point_id")
        if not (1 <= _int(seed.get("difficulty"), 0) <= 5):
            rejected.append(f"{seed_id}: invalid difficulty")
        prompt = _required_text(seed, "prompt_markdown")
        starter_code = _text(seed.get("starter_code"), "")
        if len(starter_code) > 4000:
            rejected.append(f"{seed_id}: code too long")
        _reject_leaks(seed_id, prompt, starter_code)
        fingerprint = _fingerprint(exercise_type, _text(seed.get("target_misconception"), ""), prompt, starter_code)
        if fingerprint in seen_fingerprints:
            rejected.append(f"{seed_id}: duplicate seed")
        seen_fingerprints.add(fingerprint)
        if exercise_type == "review_ai_patch":
            _validate_review_ai_patch_seed(seed_id, seed)
        if exercise_type != "review_ai_patch":
            _validate_practice_seed(seed_id, seed)

    required_types = set(supported_types)
    if not requires_review_ai_patch:
        required_types.discard("review_ai_patch")
    missing_types = sorted(required_types - exercise_types)
    if missing_types:
        rejected.append(f"missing required types: {', '.join(missing_types)}")
    if requires_review_ai_patch and "review_ai_patch" not in exercise_types:
        rejected.append("missing required review_ai_patch seed")
    required_capabilities = _required_capabilities(supported_types, requires_review_ai_patch=requires_review_ai_patch)
    missing_capabilities = sorted(required_capabilities - capabilities)
    if missing_capabilities:
        rejected.append(f"missing required capabilities: {', '.join(missing_capabilities)}")
    if rejected:
        raise ReviewSeedBankValidationError("; ".join(rejected))
    return {
        "candidate_count": len(seeds),
        "seed_count": len(seeds),
        "exercise_types": sorted(exercise_types),
        "capabilities": sorted(capabilities),
        "core_candidate_count": core_candidate_count,
        "focus_tag_count": len(focus_tags),
        "high_risk": high_risk,
        "generator_version": GENERATOR_VERSION,
        "safety": "validated",
    }


def supported_review_exercise_types(runtime_tier: str) -> tuple[str, ...]:
    if runtime_tier == "compiled_sandbox_later":
        return ("explain_code",)
    return ("code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch")


def persist_ready_seed_bank(
    conn: Any,
    *,
    user_id: str,
    plan_id: str,
    knowledge_point_id: str,
    seeds: Sequence[Mapping[str, object]],
    quality_report: Mapping[str, object],
) -> Mapping[str, object]:
    row = conn.execute(
        """
        INSERT INTO review_seed_banks (
          user_id, plan_id, knowledge_point_id, generator_version, status,
          seed_count, seeds_json, quality_report_json, failure_code,
          failure_message, generated_at
        )
        VALUES (%s, %s, %s, %s, 'ready', %s, %s::jsonb, %s::jsonb, NULL, NULL, now())
        ON CONFLICT (user_id, knowledge_point_id, generator_version) DO UPDATE SET
          plan_id = EXCLUDED.plan_id,
          status = 'ready',
          seed_count = EXCLUDED.seed_count,
          seeds_json = EXCLUDED.seeds_json,
          quality_report_json = EXCLUDED.quality_report_json,
          failure_code = NULL,
          failure_message = NULL,
          generated_at = now()
        RETURNING *
        """,
        (
            user_id,
            plan_id,
            knowledge_point_id,
            GENERATOR_VERSION,
            len(seeds),
            json.dumps(list(seeds), ensure_ascii=False),
            json.dumps(dict(quality_report), ensure_ascii=False),
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("review seed bank upsert returned no row")
    return row


def persist_failed_seed_bank(
    conn: Any,
    *,
    user_id: str,
    plan_id: str,
    knowledge_point_id: str,
    failure_code: str,
    failure_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO review_seed_banks (
          user_id, plan_id, knowledge_point_id, generator_version, status,
          seed_count, seeds_json, quality_report_json, failure_code, failure_message, generated_at
        )
        VALUES (%s, %s, %s, %s, 'failed', 0, '[]'::jsonb, '{}'::jsonb, %s, %s, NULL)
        ON CONFLICT (user_id, knowledge_point_id, generator_version) DO UPDATE SET
          plan_id = EXCLUDED.plan_id,
          status = 'failed',
          seed_count = 0,
          seeds_json = '[]'::jsonb,
          quality_report_json = '{}'::jsonb,
          failure_code = EXCLUDED.failure_code,
          failure_message = EXCLUDED.failure_message,
          generated_at = NULL
        """,
        (user_id, plan_id, knowledge_point_id, GENERATOR_VERSION, failure_code, failure_message[:500]),
    )


def _validate_review_ai_patch_seed(seed_id: str, seed: Mapping[str, object]) -> None:
    metadata = seed.get("metadata")
    rubric = seed.get("rubric")
    if not isinstance(metadata, Mapping) or not isinstance(rubric, Mapping):
        raise ReviewSeedBankValidationError(f"{seed_id}: review_ai_patch metadata and rubric are required")
    for key in ("requirement", "original_code", "ai_diff", "review_focus", "expected_risk", "expected_verdict", "expected_next_action"):
        _required_text(metadata, key)
    for key in ("verdict_correctness", "evidence_grounding", "knowledge_point_alignment", "actionability"):
        _required_text(rubric, key)
    _reject_leaks(seed_id, *(_text(metadata.get(key), "") for key in ("requirement", "original_code", "ai_diff", "review_focus", "expected_risk")))


def _validate_practice_seed(seed_id: str, seed: Mapping[str, object]) -> None:
    _required_text(seed, "starter_code")
    code_blanks = seed.get("code_blanks")
    if not isinstance(code_blanks, Sequence) or not code_blanks:
        raise ReviewSeedBankValidationError(f"{seed_id}: practice seed requires code_blanks")


def _reject_leaks(seed_id: str, *values: str) -> None:
    joined = "\n".join(values).lower()
    forbidden = (
        "solution_reference",
        "api_key",
        "api key",
        "secret",
        "sk-",
        "raw prompt",
        "raw_prompt",
        "provider error",
        "provider_error",
        "hidden answer",
        "answer key",
        "hidden_case",
        "hidden_test",
        "hidden test",
    )
    if any(token in joined for token in forbidden):
        raise ReviewSeedBankValidationError(f"{seed_id}: unsafe hidden or provider detail")


def _validate_selection_objects(seed_id: str, seed: Mapping[str, object]) -> None:
    recommended_for = seed.get("recommended_for")
    if not isinstance(recommended_for, Mapping):
        raise ReviewSeedBankValidationError(f"{seed_id}: recommended_for is required")
    if not any(_string_list(recommended_for.get(key)) for key in ("recall_levels", "weak_points", "after_result")):
        raise ReviewSeedBankValidationError(f"{seed_id}: recommended_for must include selection signals")
    avoid_if = seed.get("avoid_if")
    if not isinstance(avoid_if, Mapping):
        raise ReviewSeedBankValidationError(f"{seed_id}: avoid_if is required")


def _required_capabilities(supported_types: set[str], *, requires_review_ai_patch: bool) -> set[str]:
    required: set[str] = set()
    if supported_types & {"code_blank", "implement_function"}:
        required.add("basic_application")
    if "explain_code" in supported_types:
        required.add("concept_explanation")
    if "fix_bug" in supported_types:
        required.add("debugging")
    if "review_ai_patch" in supported_types and requires_review_ai_patch:
        required.add("transfer_or_review")
    elif "implement_function" in supported_types and len(supported_types) >= 3:
        required.add("transfer_or_review")
    return required


def _metadata(seed: Mapping[str, object]) -> Mapping[str, object]:
    metadata = seed.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ReviewSeedBankValidationError(f"{_text(seed.get('id'), 'seed')}: metadata is required")
    return metadata


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _fingerprint(*values: str) -> str:
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def _required_text(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReviewSeedBankValidationError(f"missing required field {key}")
    return value.strip()


def _text(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback
