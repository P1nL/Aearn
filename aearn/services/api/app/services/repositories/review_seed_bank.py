from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from aearn_worker.review_seed_bank_core import (
    GENERATOR_VERSION,
    ReviewSeedBankValidationError,
    persist_failed_seed_bank,
    persist_ready_seed_bank,
    supported_review_exercise_types,
    validate_review_seed_bank as validate_review_seed_bank_payload,
)
from psycopg import Connection

from app.services.curriculum.teaching_chunks import index_current_knowledge_point_chunks
from app.services.exercises.exercise_repository import get_exercise
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    OpenAICompatibleClient,
)


REVIEW_CORE_TYPES = ("code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch")
_REVIEW_SEED_BANK_MAX_TOKENS = 12000
_REVIEW_SEED_BANK_MIN_TIMEOUT_SECONDS = 75.0
_REVIEW_SEED_BANK_PROMPT_VERSION = "review_candidate_pool_prompt_v1"
_SAFE_MODEL_EXCEPTIONS = (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    TypeError,
    ValueError,
)


class ReviewSeedBankGenerationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class GeneratedReviewSeedBank:
    content: Mapping[str, object]
    model: str | None = None


ReviewSeedBankGenerator = Callable[[Mapping[str, object]], GeneratedReviewSeedBank | None]


def ensure_review_seed_bank_placeholders_for_plan(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
    knowledge_point_rows: Sequence[Mapping[str, object]],
) -> None:
    for row in knowledge_point_rows:
        conn.execute(
            """
            INSERT INTO review_seed_banks (
              user_id, plan_id, knowledge_point_id, generator_version, status, quality_report_json
            )
            VALUES (%s, %s, %s, %s, 'generating', %s::jsonb)
            ON CONFLICT (user_id, knowledge_point_id, generator_version) DO NOTHING
            """,
            (
                user_id,
                plan_id,
                str(row["id"]),
                GENERATOR_VERSION,
                json.dumps({"queued_by": "confirm_plan"}),
            ),
        )


def ensure_ready_review_seed_bank(
    conn: Connection[dict[str, object]],
    *,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> Mapping[str, object]:
    existing = _load_seed_bank(
        conn,
        user_id=str(context["user_id"]),
        knowledge_point_id=str(context["id"]),
    )
    if existing is not None and existing["status"] == "ready" and _valid_bank_row(existing, context=context, runtime_profile=runtime_profile):
        return existing

    try:
        seeds, quality_report = _generate_seed_bank(conn, context=context, runtime_profile=runtime_profile)
    except ReviewSeedBankGenerationError as exc:
        _persist_failed_seed_bank(
            conn,
            user_id=str(context["user_id"]),
            plan_id=str(context["plan_id"]),
            knowledge_point_id=str(context["id"]),
            failure_code=exc.code,
            failure_message=exc.message,
        )
        raise
    return _persist_ready_seed_bank(
        conn,
        user_id=str(context["user_id"]),
        plan_id=str(context["plan_id"]),
        knowledge_point_id=str(context["id"]),
        seeds=seeds,
        quality_report=quality_report,
    )


def generate_review_seed_bank_for_knowledge_point(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> Mapping[str, object]:
    context = {
        **dict(knowledge_point),
        "id": str(knowledge_point["id"]),
        "user_id": user_id,
        "plan_id": plan_id,
        "weak_points_json": knowledge_point.get("weak_points_json") or [],
        "mastery_score": knowledge_point.get("mastery_score"),
    }
    return ensure_ready_review_seed_bank(conn, context=context, runtime_profile=runtime_profile)


def serialize_seed_bank(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "generator_version": row["generator_version"],
        "seed_count": _int_or_zero(row.get("seed_count")),
        "generated_at": _iso_or_none(row.get("generated_at")),
        "quality_report": row.get("quality_report_json") if isinstance(row.get("quality_report_json"), Mapping) else {},
    }


def select_review_seed(
    *,
    seed_bank: Mapping[str, object],
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> Mapping[str, object]:
    seeds = _seed_list(seed_bank.get("seeds_json"))
    if not seeds:
        raise ReviewSeedBankGenerationError("EMPTY_REVIEW_SEED_BANK", "review seed bank has no seeds")

    supported = set(_supported_types(runtime_profile))
    scored_seeds = [
        (_candidate_selection_score(seed, context=context, supported=supported), index, seed)
        for index, seed in enumerate(seeds)
    ]
    selected = max(scored_seeds, key=lambda item: (item[0], -item[1]))
    if selected[0] > 0:
        return selected[2]

    weak_points = " ".join(_string_list(context.get("weak_points_json"))).lower()
    if "patch" in weak_points or "ai" in weak_points or "review" in weak_points:
        for seed in seeds:
            if seed.get("exercise_type") == "review_ai_patch":
                return seed

    if str(context.get("last_fsrs_rating") or "") == "Again":
        for seed in seeds:
            if seed.get("exercise_type") == "fix_bug":
                return seed

    target_type = "code_blank" if "code_blank" in supported else next(iter(supported), "explain_code")
    for seed in seeds:
        if seed.get("exercise_type") == target_type:
            return seed
    return seeds[0]


def materialize_review_seed_exercise(
    conn: Connection[dict[str, object]],
    *,
    seed_bank: Mapping[str, object],
    seed: Mapping[str, object],
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> dict[str, object]:
    seed_id = str(seed["id"])
    slug = f"review-{context['id']}-{seed_id}"
    existing = conn.execute(
        """
        SELECT id
        FROM exercises
        WHERE slug = %s
          AND archived_at IS NULL
          AND deleted_at IS NULL
        LIMIT 1
        """,
        (slug,),
    ).fetchone()
    if existing is not None:
        _ensure_review_seed_metadata(
            conn,
            exercise_id=str(existing["id"]),
            seed_bank=seed_bank,
            seed=seed,
        )
        exercise = get_exercise(conn, str(existing["id"]))
        if exercise is None:
            raise RuntimeError("materialized review exercise could not be loaded")
        return exercise

    metadata = _seed_metadata(seed)
    metadata["seed_generator_version"] = GENERATOR_VERSION
    metadata["review_seed"] = _review_seed_provenance(seed_bank=seed_bank, seed=seed)
    created = conn.execute(
        """
        INSERT INTO exercises (
          slug, knowledge_point_id, runtime_profile_id, title, exercise_type,
          prompt_markdown, starter_code, solution_reference, visible_test_policy,
          difficulty, estimated_minutes, requires_explanation, metadata_json
        )
        VALUES (
          %(slug)s, %(knowledge_point_id)s, %(runtime_profile_id)s, %(title)s, %(exercise_type)s,
          %(prompt_markdown)s, %(starter_code)s, %(solution_reference)s, %(visible_test_policy)s,
          %(difficulty)s, %(estimated_minutes)s, %(requires_explanation)s, %(metadata_json)s::jsonb
        )
        RETURNING id
        """,
        {
            "slug": slug,
            "knowledge_point_id": str(context["id"]),
            "runtime_profile_id": str(runtime_profile["id"]),
            "title": seed.get("title") or f"{context['title']}：复习变体",
            "exercise_type": seed["exercise_type"],
            "prompt_markdown": seed["prompt_markdown"],
            "starter_code": seed.get("starter_code") or "",
            "solution_reference": _seed_solution_reference(seed),
            "visible_test_policy": seed.get("visible_test_policy") or "visible_and_hidden_summary",
            "difficulty": _as_int(seed.get("difficulty"), 2),
            "estimated_minutes": _as_int(seed.get("estimated_minutes"), 8),
            "requires_explanation": bool(seed.get("requires_explanation", False)),
            "metadata_json": json.dumps(metadata),
        },
    ).fetchone()
    if created is None:
        raise RuntimeError("review exercise insert returned no row")

    exercise_id = str(created["id"])
    for index, blank in enumerate(_mapping_list(seed.get("code_blanks"))):
        conn.execute(
            """
            INSERT INTO code_blanks (
              exercise_id, blank_key, placeholder, expected_concept,
              acceptable_patterns_json, is_core, order_index
            )
            VALUES (
              %(exercise_id)s, %(blank_key)s, %(placeholder)s, %(expected_concept)s,
              %(acceptable_patterns_json)s::jsonb, %(is_core)s, %(order_index)s
            )
            ON CONFLICT (exercise_id, blank_key) DO NOTHING
            """,
            {
                "exercise_id": exercise_id,
                "blank_key": str(blank.get("blank_key") or f"blank_{index + 1}"),
                "placeholder": str(blank.get("placeholder") or ""),
                "expected_concept": str(blank.get("expected_concept") or seed.get("review_focus") or "核心概念"),
                "acceptable_patterns_json": json.dumps(blank.get("acceptable_patterns_json") or []),
                "is_core": bool(blank.get("is_core", True)),
                "order_index": _as_int(blank.get("order_index"), index),
            },
        )

    for index, test_case in enumerate(_mapping_list(seed.get("test_cases"))):
        conn.execute(
            """
            INSERT INTO test_cases (
              exercise_id, case_type, input_json, expected_output_json, assertion_code,
              weight, is_critical, timeout_ms, order_index
            )
            VALUES (
              %(exercise_id)s, %(case_type)s, %(input_json)s::jsonb, %(expected_output_json)s::jsonb,
              %(assertion_code)s, %(weight)s, %(is_critical)s, %(timeout_ms)s, %(order_index)s
            )
            ON CONFLICT (exercise_id, order_index) DO NOTHING
            """,
            {
                "exercise_id": exercise_id,
                "case_type": str(test_case.get("case_type") or "visible"),
                "input_json": json.dumps(test_case.get("input_json") or {}),
                "expected_output_json": json.dumps(test_case.get("expected_output_json") or {}),
                "assertion_code": test_case.get("assertion_code"),
                "weight": _as_float(test_case.get("weight"), 1.0),
                "is_critical": bool(test_case.get("is_critical", False)),
                "timeout_ms": _as_int(test_case.get("timeout_ms"), 5000),
                "order_index": _as_int(test_case.get("order_index"), index),
            },
        )

    exercise = get_exercise(conn, exercise_id)
    if exercise is None:
        raise RuntimeError("created review exercise could not be loaded")
    index_current_knowledge_point_chunks(conn, str(context["id"]))
    return exercise


def _ensure_review_seed_metadata(
    conn: Connection[dict[str, object]],
    *,
    exercise_id: str,
    seed_bank: Mapping[str, object],
    seed: Mapping[str, object],
) -> None:
    row = conn.execute(
        "SELECT metadata_json FROM exercises WHERE id = %s LIMIT 1",
        (exercise_id,),
    ).fetchone()
    metadata_value = row.get("metadata_json") if row is not None else None
    metadata = dict(metadata_value) if isinstance(metadata_value, Mapping) else {}
    metadata.update(_seed_metadata(seed))
    metadata["seed_generator_version"] = GENERATOR_VERSION
    metadata["review_seed"] = _review_seed_provenance(seed_bank=seed_bank, seed=seed)
    conn.execute(
        "UPDATE exercises SET metadata_json = %s::jsonb WHERE id = %s",
        (json.dumps(metadata), exercise_id),
    )


def build_review_warmup(seed: Mapping[str, object], context: Mapping[str, object]) -> dict[str, object]:
    keywords = _string_list(seed.get("warmup_keywords"))
    if not keywords:
        keywords = [str(context.get("title") or "核心概念")]
    return {
        "question": str(seed.get("warmup_question") or f"先用一句话回忆：{context['title']} 最容易错在哪里？"),
        "expected_focus": str(seed.get("warmup_expected_focus") or seed.get("review_focus") or context["title"]),
        "keywords": keywords[:6],
        "result": "pending",
        "repair_count": 0,
        "last_answer": None,
        "feedback": None,
    }

def validate_review_seed_bank(
    seeds: Sequence[Mapping[str, object]],
    *,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> dict[str, object]:
    try:
        return validate_review_seed_bank_payload(
            seeds,
            knowledge_point_id=str(context["id"]),
            high_risk=_is_high_risk(context),
            requires_review_ai_patch=_supports_review_ai_patch(runtime_profile),
            supported_exercise_types=_supported_types(runtime_profile),
        )
    except ReviewSeedBankValidationError as exc:
        raise ReviewSeedBankGenerationError(
            "REVIEW_SEED_BANK_GENERATION_FAILED",
            str(exc),
        ) from exc


def _load_seed_bank(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT *
        FROM review_seed_banks
        WHERE user_id = %s
          AND knowledge_point_id = %s
          AND generator_version = %s
        LIMIT 1
        """,
        (user_id, knowledge_point_id, GENERATOR_VERSION),
    ).fetchone()


def _persist_ready_seed_bank(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
    knowledge_point_id: str,
    seeds: Sequence[Mapping[str, object]],
    quality_report: Mapping[str, object],
) -> Mapping[str, object]:
    return persist_ready_seed_bank(
        conn,
        user_id=user_id,
        plan_id=plan_id,
        knowledge_point_id=knowledge_point_id,
        seeds=seeds,
        quality_report=quality_report,
    )


def _persist_failed_seed_bank(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
    knowledge_point_id: str,
    failure_code: str,
    failure_message: str,
) -> None:
    persist_failed_seed_bank(
        conn,
        user_id=user_id,
        plan_id=plan_id,
        knowledge_point_id=knowledge_point_id,
        failure_code=failure_code,
        failure_message=failure_message,
    )


def _valid_bank_row(
    row: Mapping[str, object],
    *,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> bool:
    try:
        validate_review_seed_bank(_seed_list(row.get("seeds_json")), context=context, runtime_profile=runtime_profile)
    except ReviewSeedBankGenerationError:
        return False
    return True


def _generate_seed_bank(
    conn: Connection[dict[str, object]],
    *,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
    candidate_generator: ReviewSeedBankGenerator | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    generation_context = _review_seed_generation_context(conn, context=context, runtime_profile=runtime_profile)
    generator = candidate_generator or build_model_review_seed_bank
    try:
        generated = generator(generation_context)
    except _SAFE_MODEL_EXCEPTIONS as exc:
        raise ReviewSeedBankGenerationError("REVIEW_SEED_BANK_GENERATION_FAILED", exc.__class__.__name__) from exc
    if generated is None:
        raise ReviewSeedBankGenerationError("REVIEW_SEED_BANK_GENERATION_FAILED", "review seed bank model is unavailable")

    try:
        seeds = _seeds_from_generated(generated.content, generation_context)
        if any(_contains_forbidden_material(seed) for seed in seeds):
            raise ReviewSeedBankValidationError("unsafe hidden, solution, provider, or secret material")
        quality_report = validate_review_seed_bank(seeds, context=context, runtime_profile=runtime_profile)
    except (KeyError, ValueError, ReviewSeedBankValidationError) as exc:
        raise ReviewSeedBankGenerationError("REVIEW_SEED_BANK_GENERATION_FAILED", str(exc)) from exc

    quality_report = {
        **quality_report,
        "generation_source": "llm",
        "generation_model": generated.model or "",
        "prompt_version": _REVIEW_SEED_BANK_PROMPT_VERSION,
        "adaptation_inputs": _quality_adaptation_inputs(generation_context),
    }
    return seeds, quality_report


def build_model_review_seed_bank(context: Mapping[str, object]) -> GeneratedReviewSeedBank | None:
    try:
        client = OpenAICompatibleClient()
    except LLMConfigurationError:
        return None
    result = client.complete_json(
        _review_seed_model_messages(context),
        max_tokens=_REVIEW_SEED_BANK_MAX_TOKENS,
        timeout_seconds=_REVIEW_SEED_BANK_MIN_TIMEOUT_SECONDS,
    )
    return GeneratedReviewSeedBank(content=result.content, model=result.model)


def _review_seed_generation_context(
    conn: Connection[dict[str, object]],
    *,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> dict[str, object]:
    supported_types = _supported_types(runtime_profile)
    high_risk = _is_high_risk(context)
    latest_attempt = _load_latest_attempt_summary(
        conn,
        user_id=str(context["user_id"]),
        knowledge_point_id=str(context["id"]),
        attempt_id=str(context["last_attempt_id"]) if context.get("last_attempt_id") else None,
    )
    return {
        "task": "review_candidate_pool",
        "generator_version": GENERATOR_VERSION,
        "prompt_version": _REVIEW_SEED_BANK_PROMPT_VERSION,
        "knowledge_point_id": str(context["id"]),
        "knowledge_point_title": _bounded_text(str(context.get("title") or ""), 180),
        "knowledge_point_description": _bounded_text(str(context.get("description") or ""), 900),
        "skill_tags": _string_list(context.get("skill_tags_json"))[:10],
        "lesson_outline": _bounded_lesson_outline(context.get("lesson_outline_json")),
        "runtime_profile": {
            "language": str(runtime_profile.get("language") or ""),
            "runtime_tier": str(runtime_profile.get("runtime_tier") or ""),
            "runner": str(runtime_profile.get("runner") or ""),
            "supports_tests": bool(runtime_profile.get("supports_tests")),
            "supports_stdout": bool(runtime_profile.get("supports_stdout")),
        },
        "learner_state": {
            "weak_points": _string_list(context.get("weak_points_json"))[:8],
            "mastery_score": _context_mastery_score(context),
            "last_fsrs_rating": str(context.get("last_fsrs_rating") or ""),
            "review_count": _as_int(context.get("reps"), _as_int(context.get("review_count"), 0)),
            "lapse_count": _as_int(context.get("lapses"), _as_int(context.get("lapse_count"), 0)),
            "last_exercise_result": str(context.get("last_exercise_result") or context.get("kp_last_exercise_result") or ""),
            "last_exercise_score": _float_or_none(context.get("last_exercise_score") or context.get("kp_last_exercise_score")),
            "latest_attempt": latest_attempt,
        },
        "supported_exercise_types": list(supported_types),
        "requires_review_ai_patch": "review_ai_patch" in supported_types,
        "target_seed_count": 12 if high_risk else 10,
        "high_risk": high_risk,
        "candidate_contract": {
            "required_fields": [
                "id",
                "exercise_type",
                "difficulty",
                "capability",
                "target_misconception",
                "focus_tags",
                "recommended_for",
                "avoid_if",
                "knowledge_point_id",
                "runtime_tier",
                "title",
                "warmup_question",
                "warmup_expected_focus",
                "warmup_keywords",
                "review_focus",
                "prompt_markdown",
                "starter_code",
                "code_blanks",
                "test_cases",
                "metadata",
            ],
            "allowed_capabilities": [
                "basic_application",
                "concept_explanation",
                "debugging",
                "transfer_or_review",
            ],
            "metadata_fields": [
                "selection_reason",
                "is_core",
            ],
            "review_ai_patch_metadata_fields": [
                "requirement",
                "original_code",
                "ai_diff",
                "review_focus",
                "expected_risk",
                "expected_verdict",
                "expected_next_action",
            ],
            "forbidden": [
                "solution_reference",
                "hidden test bodies",
                "hidden expected values",
                "raw prompts",
                "provider errors",
                "API keys",
                "secrets",
            ],
        },
    }


def _review_seed_model_messages(context: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You generate Aearn review candidate pools. The candidates must be model-generated, "
                "adapted to the learner_state, safe to persist, and useful for a later backend graph to select from. "
                "Return JSON only. Generate a candidate pool, not a fixed display order. "
                "Never decide FSRS rating, due_at, final review count, session completion, or persistence. "
                "Never include solution_reference, hidden test bodies, hidden expected values, "
                "raw prompts, provider errors, API keys, or secrets."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "generate_review_candidate_pool",
                    "generation_policy": (
                        "Generate exactly target_seed_count unique candidates. Cover every supported_exercise_type at least once. "
                        "Cover basic_application, concept_explanation, debugging, and transfer_or_review when supported. "
                        "Use learner_state weak_points, mastery_score, last_fsrs_rating, review_count, lapse_count, "
                        "and latest_attempt to choose misconceptions, focus_tags, capability, selection metadata, and difficulty. "
                        "Each candidate must include recommended_for, avoid_if, metadata.selection_reason, and metadata.is_core. "
                        "For review_ai_patch, include requirement, "
                        "original_code, ai_diff, expected risk, expected verdict, expected next action, and rubric. "
                        "For practice seeds, include starter_code, code_blanks, and visible or preview test summaries only."
                    ),
                    "bounded_review_context": context,
                    "response_shape": {
                        "candidate_pool": {
                            "candidates": [],
                            "quality_notes": [],
                        }
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]


def _seeds_from_generated(
    generated: Mapping[str, object],
    context: Mapping[str, object],
) -> list[dict[str, object]]:
    payload: object = generated
    if isinstance(generated.get("seed_bank"), Mapping):
        payload = generated["seed_bank"]
    if isinstance(generated.get("candidate_pool"), Mapping):
        payload = generated["candidate_pool"]
    if isinstance(payload, Mapping):
        raw_seeds = payload.get("candidates")
        if raw_seeds is None:
            raw_seeds = payload.get("seeds")
    else:
        raw_seeds = payload
    if not isinstance(raw_seeds, list):
        raise ReviewSeedBankValidationError("model response must include candidates")

    seeds: list[dict[str, object]] = []
    runtime_context = context.get("runtime_profile")
    runtime_tier = str(runtime_context.get("runtime_tier") or "") if isinstance(runtime_context, Mapping) else ""
    for index, raw_seed in enumerate(raw_seeds):
        if not isinstance(raw_seed, Mapping):
            raise ReviewSeedBankValidationError("each seed must be an object")
        seed = dict(raw_seed)
        seed["id"] = _safe_seed_id(seed.get("id"), index=index)
        seed["knowledge_point_id"] = str(context["knowledge_point_id"])
        seed["runtime_tier"] = runtime_tier
        seed["generator_version"] = str(context.get("generator_version") or GENERATOR_VERSION)
        if "metadata_json" in seed and "metadata" not in seed and isinstance(seed["metadata_json"], Mapping):
            seed["metadata"] = seed["metadata_json"]
        if not isinstance(seed.get("warmup_keywords"), list):
            seed["warmup_keywords"] = _string_list(seed.get("warmup_keywords"))[:6]
        seeds.append(seed)
    return seeds


def _load_latest_attempt_summary(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
    attempt_id: str | None,
) -> dict[str, object] | None:
    if attempt_id:
        where_sql = "attempts.id = %(attempt_id)s"
        params: dict[str, object] = {"attempt_id": attempt_id, "user_id": user_id, "knowledge_point_id": knowledge_point_id}
    else:
        where_sql = "attempts.user_id = %(user_id)s AND exercises.knowledge_point_id = %(knowledge_point_id)s"
        params = {"user_id": user_id, "knowledge_point_id": knowledge_point_id}
    row = conn.execute(
        f"""
        SELECT
          attempts.id,
          attempts.attempt_type,
          attempts.runtime_status,
          attempts.test_pass_rate,
          attempts.score,
          attempts.fsrs_rating,
          attempts.error_cause,
          attempts.hint_usage_count,
          attempts.error_count,
          attempts.created_at
        FROM attempts
        JOIN exercises ON exercises.id = attempts.exercise_id
        WHERE {where_sql}
          AND attempts.user_id = %(user_id)s
          AND exercises.knowledge_point_id = %(knowledge_point_id)s
        ORDER BY attempts.created_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    return {
        "attempt_id": str(row["id"]),
        "attempt_type": str(row["attempt_type"]),
        "runtime_status": str(row["runtime_status"]),
        "test_pass_rate": _as_float(row.get("test_pass_rate"), 0.0),
        "score": _as_float(row.get("score"), 0.0),
        "fsrs_rating": str(row.get("fsrs_rating") or ""),
        "error_cause": str(row.get("error_cause") or ""),
        "hint_usage_count": _as_int(row.get("hint_usage_count"), 0),
        "error_count": _as_int(row.get("error_count"), 0),
        "created_at": _iso_or_none(row.get("created_at")),
    }


def _quality_adaptation_inputs(context: Mapping[str, object]) -> dict[str, object]:
    learner_state = context.get("learner_state")
    runtime_profile = context.get("runtime_profile")
    return {
        "weak_point_count": len(_string_list(learner_state.get("weak_points") if isinstance(learner_state, Mapping) else [])),
        "mastery_score": learner_state.get("mastery_score") if isinstance(learner_state, Mapping) else None,
        "last_fsrs_rating": learner_state.get("last_fsrs_rating") if isinstance(learner_state, Mapping) else "",
        "review_count": learner_state.get("review_count") if isinstance(learner_state, Mapping) else 0,
        "lapse_count": learner_state.get("lapse_count") if isinstance(learner_state, Mapping) else 0,
        "has_latest_attempt": bool(isinstance(learner_state, Mapping) and learner_state.get("latest_attempt")),
        "runtime_language": runtime_profile.get("language") if isinstance(runtime_profile, Mapping) else "",
        "runtime_tier": runtime_profile.get("runtime_tier") if isinstance(runtime_profile, Mapping) else "",
    }


def _supported_types(runtime_profile: Mapping[str, object]) -> tuple[str, ...]:
    runtime_tier = str(runtime_profile.get("runtime_tier") or "")
    supported = supported_review_exercise_types(runtime_tier)
    return tuple(exercise_type for exercise_type in REVIEW_CORE_TYPES if exercise_type in supported)


def _supports_review_ai_patch(runtime_profile: Mapping[str, object]) -> bool:
    return "review_ai_patch" in _supported_types(runtime_profile)


def _seed_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], seed) for seed in value if isinstance(seed, Mapping)]


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _seed_metadata(seed: Mapping[str, object]) -> dict[str, object]:
    metadata = seed.get("metadata")
    if isinstance(metadata, Mapping):
        result = dict(metadata)
        rubric = seed.get("rubric")
        if "rubric" not in result and isinstance(rubric, Mapping):
            result["rubric"] = dict(rubric)
        return result
    metadata_json = seed.get("metadata_json")
    if isinstance(metadata_json, Mapping):
        return dict(metadata_json)
    return {}


def _review_seed_provenance(
    *,
    seed_bank: Mapping[str, object],
    seed: Mapping[str, object],
) -> dict[str, object]:
    metadata = _seed_metadata(seed)
    return {
        "seed_bank_id": str(seed_bank["id"]),
        "seed_id": str(seed["id"]),
        "candidate_id": str(seed["id"]),
        "target_misconception": seed.get("target_misconception"),
        "review_focus": seed.get("review_focus"),
        "capability": seed.get("capability"),
        "focus_tags": _string_list(seed.get("focus_tags")),
        "selection_reason": metadata.get("selection_reason"),
        "is_core": bool(metadata.get("is_core", False)),
    }


def _candidate_selection_score(
    seed: Mapping[str, object],
    *,
    context: Mapping[str, object],
    supported: set[str],
) -> int:
    exercise_type = str(seed.get("exercise_type") or "")
    if exercise_type not in supported:
        return -100

    score = 0
    weak_points = {item.lower() for item in _string_list(context.get("weak_points_json"))}
    focus_values = {
        str(seed.get("target_misconception") or "").lower(),
        *{item.lower() for item in _string_list(seed.get("focus_tags"))},
    }
    recommended_for = seed.get("recommended_for")
    if isinstance(recommended_for, Mapping):
        focus_values.update(item.lower() for item in _string_list(recommended_for.get("weak_points")))
    if weak_points and weak_points & focus_values:
        score += 10

    weak_text = " ".join(sorted(weak_points))
    if exercise_type == "review_ai_patch" and any(token in weak_text for token in ("patch", "ai", "review")):
        score += 30
    if str(context.get("last_fsrs_rating") or "") == "Again":
        if exercise_type == "fix_bug":
            score += 20
        if seed.get("capability") == "debugging":
            score += 10
    if seed.get("capability") == "basic_application":
        score += 2
    metadata = _seed_metadata(seed)
    if bool(metadata.get("is_core")):
        score += 1
    return score


def _seed_solution_reference(seed: Mapping[str, object]) -> str | None:
    if seed.get("exercise_type") == "review_ai_patch":
        return None
    starter_code = str(seed.get("starter_code") or "")
    if not starter_code:
        return None
    solution = starter_code
    for blank in _mapping_list(seed.get("code_blanks")):
        key = str(blank.get("blank_key") or "").upper()
        placeholder = str(blank.get("placeholder") or "")
        if key and placeholder:
            solution = solution.replace(f"__{key}__", placeholder)
    return solution


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _bounded_lesson_outline(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    outline: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        outline.append(
            {
                "id": _bounded_text(str(item.get("id") or ""), 80),
                "title": _bounded_text(str(item.get("title") or ""), 160),
                "note": _bounded_text(str(item.get("note") or item.get("summary") or ""), 360),
            }
        )
        if len(outline) >= 6:
            break
    return outline


def _bounded_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _safe_seed_id(value: object, *, index: int) -> str:
    if isinstance(value, str) and value.strip():
        candidate = value.strip()
    else:
        candidate = f"model_seed_{index + 1:02d}"
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in candidate)
    return safe[:96] or f"model_seed_{index + 1:02d}"


def _contains_forbidden_material(seed: Mapping[str, object]) -> bool:
    serialized = json.dumps(_string_values(seed), ensure_ascii=False).lower()
    forbidden = (
        "hidden answer",
        "hidden test source",
        "hidden_case",
        "hidden_test",
        "api_key",
        "api key",
        "sk-",
        "secret",
        "traceback",
        "raw prompt",
        "raw_prompt",
        "provider error",
        "provider_error",
    )
    if any(item in serialized for item in forbidden):
        return True
    solution_reference = seed.get("solution_reference")
    if isinstance(solution_reference, str) and solution_reference.strip():
        return True
    return any(str(case.get("case_type") or "").lower() == "hidden" for case in _mapping_list(seed.get("test_cases")))


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_string_values(item))
        return result
    if isinstance(value, list):
        list_result: list[str] = []
        for item in value:
            list_result.extend(_string_values(item))
        return list_result
    return []


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _context_mastery_score(context: Mapping[str, object]) -> float | None:
    value = context.get("mastery_score")
    if value is None:
        value = context.get("kp_mastery_score")
    return _float_or_none(value)


def _is_high_risk(context: Mapping[str, object]) -> bool:
    weak_points = _string_list(context.get("weak_points_json"))
    if len(weak_points) >= 2:
        return True
    mastery = _context_mastery_score(context)
    if mastery is not None and mastery < 0.45:
        return True
    if str(context.get("last_fsrs_rating") or "") == "Again":
        return True
    if _as_int(context.get("lapses"), 0) > 0:
        return True
    if context.get("order_index") is not None and _as_int(context.get("order_index"), 0) <= 1:
        return True
    return "core" in str(context.get("title") or "").lower()


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
