from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


GENERATOR_VERSION = "review_seed_bank_v1"
CORE_REVIEW_EXERCISE_TYPES = {
    "code_blank",
    "fix_bug",
    "explain_code",
    "implement_function",
    "review_ai_patch",
}


class ReviewSeedBankValidationError(ValueError):
    pass


def build_review_seed_bank_payload(context: Mapping[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    knowledge_point_id = str(context["knowledge_point_id"])
    title = _text(context.get("title"), "当前知识点")
    description = _text(context.get("description"), f"复习 {title} 的核心行为。")
    language = _text(context.get("language"), "javascript")
    runtime_tier = _text(context.get("runtime_tier"), "browser_preview")
    weak_points = _string_list(context.get("weak_points_json"))
    seed_count = _target_seed_count(context)
    supported_types = supported_review_exercise_types(runtime_tier)
    type_cycle = _type_cycle(supported_types)

    seeds: list[dict[str, object]] = []
    for index in range(seed_count):
        exercise_type = type_cycle[index % len(type_cycle)]
        misconception = _misconception_for(index, weak_points, language)
        seed = _build_seed(
            knowledge_point_id=knowledge_point_id,
            title=title,
            description=description,
            language=language,
            runtime_tier=runtime_tier,
            exercise_type=exercise_type,
            misconception=misconception,
            index=index,
        )
        seeds.append(seed)

    quality_report = validate_review_seed_bank(
        seeds,
        knowledge_point_id=knowledge_point_id,
        high_risk=_is_high_risk(context),
        requires_review_ai_patch="review_ai_patch" in supported_types,
        supported_exercise_types=supported_types,
    )
    return seeds, quality_report


def validate_review_seed_bank(
    seeds: Sequence[Mapping[str, object]],
    *,
    knowledge_point_id: str,
    high_risk: bool,
    requires_review_ai_patch: bool = True,
    supported_exercise_types: Sequence[str] | None = None,
) -> dict[str, object]:
    min_count, max_count = (12, 16) if high_risk else (8, 12)
    if len(seeds) < min_count or len(seeds) > max_count:
        raise ReviewSeedBankValidationError("seed count is outside required range")

    supported_types = set(supported_exercise_types or tuple(CORE_REVIEW_EXERCISE_TYPES))
    seen_fingerprints: set[str] = set()
    exercise_types: set[str] = set()
    rejected: list[str] = []
    for seed in seeds:
        seed_id = _required_text(seed, "id")
        exercise_type = _required_text(seed, "exercise_type")
        if exercise_type not in supported_types:
            rejected.append(f"{seed_id}: unsupported exercise_type")
            continue
        exercise_types.add(exercise_type)
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
    if rejected:
        raise ReviewSeedBankValidationError("; ".join(rejected))
    return {
        "seed_count": len(seeds),
        "exercise_types": sorted(exercise_types),
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


def _build_seed(
    *,
    knowledge_point_id: str,
    title: str,
    description: str,
    language: str,
    runtime_tier: str,
    exercise_type: str,
    misconception: str,
    index: int,
) -> dict[str, object]:
    suffix = f"{exercise_type}_{index + 1:02d}"
    if exercise_type == "review_ai_patch":
        return _review_ai_patch_seed(
            knowledge_point_id=knowledge_point_id,
            title=title,
            description=description,
            language=language,
            runtime_tier=runtime_tier,
            misconception=misconception,
            suffix=suffix,
        )
    return _practice_seed(
        knowledge_point_id=knowledge_point_id,
        title=title,
        description=description,
        language=language,
        runtime_tier=runtime_tier,
        exercise_type=exercise_type,
        misconception=misconception,
        suffix=suffix,
        index=index,
    )


def _review_ai_patch_seed(
    *,
    knowledge_point_id: str,
    title: str,
    description: str,
    language: str,
    runtime_tier: str,
    misconception: str,
    suffix: str,
) -> dict[str, object]:
    original_code, ai_diff, expected_risk = _patch_material(language, title)
    return {
        "id": f"seed_{_slug(title)}_{suffix}",
        "exercise_type": "review_ai_patch",
        "difficulty": 3,
        "target_misconception": misconception,
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": runtime_tier,
        "prompt_markdown": (
            f"围绕 **{title}** 审查一段 AI 生成改动。你需要判断它是否满足需求，"
            f"并给出基于 diff、需求或测试的证据。\n\n复习变体编号：{suffix}。"
        ),
        "starter_code": original_code,
        "solution_reference": "",
        "visible_tests_summary": ["结论必须引用需求、diff 或可见测试信号，不能只说 tests passed。"],
        "metadata": {
            "requirement": f"{description} 请保持 {title} 的关键行为可验证。",
            "original_code": original_code,
            "ai_diff": ai_diff,
            "review_focus": f"{title} 的当前知识点风险与 AI 改动是否一致。",
            "expected_risk": expected_risk,
            "expected_verdict": "fail",
            "expected_next_actions": ["reject", "request_change"],
        },
        "rubric": {
            "verdict_correctness": "0-2",
            "evidence_grounding": "0-2",
            "knowledge_point_alignment": "0-2",
            "actionability": "0-2",
        },
    }


def _practice_seed(
    *,
    knowledge_point_id: str,
    title: str,
    description: str,
    language: str,
    runtime_tier: str,
    exercise_type: str,
    misconception: str,
    suffix: str,
    index: int,
) -> dict[str, object]:
    starter_code, _solution_reference, blank_value, expected_concept = _practice_material(language, exercise_type, index)
    return {
        "id": f"seed_{_slug(title)}_{suffix}",
        "exercise_type": exercise_type,
        "difficulty": 2 if exercise_type in {"code_blank", "explain_code"} else 3,
        "target_misconception": misconception,
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": runtime_tier,
        "prompt_markdown": (
            f"围绕 **{title}** 完成一个复习变体。\n\n"
            f"复习目标：{description}\n\n"
            f"先独立完成，再用自己的话说明你验证了什么。\n\n复习变体编号：{suffix}。"
        ),
        "starter_code": starter_code,
        "visible_tests_summary": ["可见检查会验证核心补全和最小运行行为。"],
        "metadata": {
            "review_focus": f"{title} 的迁移应用",
            "required_patterns": [blank_value],
            "target_misconception": misconception,
        },
        "rubric": {
            "completion_correctness": "0-2",
            "runtime_and_tests": "0-2",
            "error_diagnosis": "0-2",
            "explanation_check": "0-2",
        },
        "code_blanks": [
            {
                "blank_key": "blank_1",
                "placeholder": blank_value,
                "expected_concept": expected_concept,
                "acceptable_patterns_json": [{"type": "literal", "value": blank_value}],
                "is_core": True,
                "order_index": 0,
            }
        ],
        "test_cases": [
            {
                "case_type": "visible" if runtime_tier != "browser_preview" else "preview_assertion",
                "input_json": {"review_seed": suffix},
                "expected_output_json": {"contains": blank_value},
                "assertion_code": None,
                "weight": 1,
                "is_critical": True,
                "timeout_ms": 5000,
                "order_index": 0,
            }
        ],
    }


def _practice_material(language: str, exercise_type: str, index: int) -> tuple[str, str, str, str]:
    if language == "python":
        blank = "total" if index % 2 == 0 else "len(scores)"
        starter = (
            "def summarize_scores(scores):\n"
            "    total = sum(scores)\n"
            "    print(f\"total={total}\")\n"
            "    return __BLANK_1__\n"
        )
        solution = starter.replace("__BLANK_1__", blank)
        concept = "区分 stdout 和返回值，返回调用方真正需要继续使用的值。"
        return starter, solution, blank, concept
    if language == "html_css":
        blank = "active"
        starter = "<button class=\"pill __BLANK_1__\">Review ready</button>\n"
        return starter, starter.replace("__BLANK_1__", blank), blank, "把交互态类名放在真实 DOM 元素上。"
    blank = "count"
    if exercise_type == "fix_bug":
        blank = "outside_handler"
    starter = (
        "let count = 0;\n"
        "button.addEventListener('click', () => {\n"
        "  count += 1;\n"
        "  output.textContent = String(__BLANK_1__);\n"
        "});\n"
    )
    solution = starter.replace("__BLANK_1__", "count")
    concept = "跨点击共享的状态需要位于回调可访问且不会每次重建的作用域。"
    return starter, solution, "count" if blank == "outside_handler" else blank, concept


def _patch_material(language: str, title: str) -> tuple[str, str, str]:
    if language == "python":
        return (
            "def summarize_scores(scores):\n    total = sum(scores)\n    return total\n",
            "-    return total\n+    print(total)\n",
            "调用方拿不到返回值，stdout 不能替代函数返回。",
        )
    if language == "html_css":
        return (
            "<button class=\"pill active\">Ready</button>\n",
            "-<button class=\"pill active\">Ready</button>\n+<button class=\"pill\">Ready</button>\n",
            "AI 改动移除了交互态类名，预览断言会失去目标状态。",
        )
    return (
        "let count = 0;\nbutton.addEventListener('click', () => {\n  count += 1;\n  output.textContent = String(count);\n});\n",
        "-let count = 0;\n button.addEventListener('click', () => {\n+  let count = 0;\n   count += 1;\n   output.textContent = String(count);\n });\n",
        f"AI 把 {title} 相关状态放进回调内部，多次点击会重置。",
    )


def _validate_review_ai_patch_seed(seed_id: str, seed: Mapping[str, object]) -> None:
    metadata = seed.get("metadata")
    rubric = seed.get("rubric")
    if not isinstance(metadata, Mapping) or not isinstance(rubric, Mapping):
        raise ReviewSeedBankValidationError(f"{seed_id}: review_ai_patch metadata and rubric are required")
    for key in ("requirement", "original_code", "ai_diff", "review_focus", "expected_risk"):
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
    forbidden = ("solution_reference", "api_key", "secret", "raw prompt", "provider error", "hidden_case", "hidden_test")
    if any(token in joined for token in forbidden):
        raise ReviewSeedBankValidationError(f"{seed_id}: unsafe hidden or provider detail")


def _target_seed_count(context: Mapping[str, object]) -> int:
    return 12 if _is_high_risk(context) else 8


def _is_high_risk(context: Mapping[str, object]) -> bool:
    weak_points = _string_list(context.get("weak_points_json"))
    if len(weak_points) >= 2:
        return True
    mastery = context.get("mastery_score")
    if isinstance(mastery, int | float) and mastery < 0.45:
        return True
    if "core" in _text(context.get("title"), "").lower():
        return True
    if _text(context.get("last_fsrs_rating"), "") == "Again":
        return True
    if _int(context.get("lapses"), 0) > 0:
        return True
    if _int(context.get("order_index"), 0) <= 1:
        return True
    return False


def _type_cycle(supported_types: Sequence[str]) -> list[str]:
    preferred = ["code_blank", "fix_bug", "review_ai_patch", "explain_code", "implement_function"]
    ordered = [exercise_type for exercise_type in preferred if exercise_type in supported_types]
    return ordered or ["explain_code"]


def _misconception_for(index: int, weak_points: Sequence[str], language: str) -> str:
    if weak_points:
        return weak_points[index % len(weak_points)]
    if language == "python":
        defaults = ["return_vs_stdout", "value_flow_error", "test_evidence_gap"]
    elif language == "html_css":
        defaults = ["selector_state_gap", "class_application_error", "preview_evidence_gap"]
    else:
        defaults = ["state_scope_error", "event_handler_state_reset", "insufficient_test_evidence"]
    return defaults[index % len(defaults)]


def _fingerprint(*values: str) -> str:
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def _required_text(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReviewSeedBankValidationError(f"missing required field {key}")
    return value.strip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [str(item) for item in value if str(item).strip()]


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


def _slug(value: str) -> str:
    ascii_slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    compact = "_".join(part for part in ascii_slug.split("_") if part)
    return compact[:36] or "knowledge_point"
