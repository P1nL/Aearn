from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from aearn_worker.review_seed_bank_core import (
    GENERATOR_VERSION,
    ReviewSeedBankValidationError,
    build_review_seed_bank_payload,
    persist_failed_seed_bank,
    persist_ready_seed_bank,
    supported_review_exercise_types,
    validate_review_seed_bank as validate_review_seed_bank_payload,
)
from psycopg import Connection

from app.services.exercise_repository import get_exercise
from app.services.teaching_chunks import index_current_knowledge_point_chunks


REVIEW_CORE_TYPES = ("code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch")


class ReviewSeedBankGenerationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        seeds, quality_report = _generate_seed_bank(context=context, runtime_profile=runtime_profile)
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
        exercise = get_exercise(conn, str(existing["id"]))
        if exercise is None:
            raise RuntimeError("materialized review exercise could not be loaded")
        return exercise

    metadata = _seed_metadata(seed)
    metadata["review_seed"] = {
        "seed_bank_id": str(seed_bank["id"]),
        "seed_id": seed_id,
        "target_misconception": seed.get("target_misconception"),
        "review_focus": seed.get("review_focus"),
    }
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
    *,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    generation_context = {
        "knowledge_point_id": str(context["id"]),
        "title": context.get("title"),
        "description": context.get("description"),
        "language": runtime_profile.get("language"),
        "runtime_tier": runtime_profile.get("runtime_tier"),
        "weak_points_json": context.get("weak_points_json") or [],
        "last_fsrs_rating": context.get("last_fsrs_rating"),
        "lapses": context.get("lapses"),
        "order_index": context.get("order_index"),
        "mastery_score": context.get("mastery_score"),
    }
    try:
        seeds, quality_report = build_review_seed_bank_payload(generation_context)
        validate_review_seed_bank(seeds, context=context, runtime_profile=runtime_profile)
    except (KeyError, ValueError, ReviewSeedBankValidationError) as exc:
        raise ReviewSeedBankGenerationError("REVIEW_SEED_BANK_GENERATION_FAILED", str(exc)) from exc
    return seeds, quality_report


def _seed_for_type(
    exercise_type: str,
    *,
    index: int,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> dict[str, object]:
    language = str(runtime_profile.get("language") or "javascript")
    title = str(context.get("title") or "当前知识点")
    knowledge_point_id = str(context["id"])
    misconception = _misconception_for(index)
    seed_id = f"seed_{exercise_type}_{index + 1:02d}"
    base = {
        "id": seed_id,
        "exercise_type": exercise_type,
        "difficulty": 2 + (index % 3),
        "target_misconception": misconception,
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": str(runtime_profile.get("runtime_tier") or ""),
        "title": f"{title}：{_type_title(exercise_type)}",
        "warmup_question": f"先回忆：{title} 里最容易导致 {misconception} 的判断点是什么？",
        "warmup_expected_focus": _expected_focus(language),
        "warmup_keywords": _warmup_keywords(language),
        "review_focus": _expected_focus(language),
        "estimated_minutes": 8,
    }
    if exercise_type == "review_ai_patch":
        seed = base | _review_patch_seed(language=language, title=title)
    elif exercise_type == "fix_bug":
        seed = base | _fix_bug_seed(language=language, title=title)
    elif exercise_type == "implement_function":
        seed = base | _implement_function_seed(language=language, title=title)
    elif exercise_type == "explain_code":
        seed = base | _explain_code_seed(language=language, title=title)
    else:
        seed = base | _code_blank_seed(language=language, title=title)
    seed["prompt_markdown"] = f"{seed['prompt_markdown']}\n\n复习变体编号：{index + 1}。"
    return seed


def _code_blank_seed(*, language: str, title: str) -> dict[str, object]:
    if language == "python":
        return {
            "prompt_markdown": f"围绕 **{title}** 补全函数返回值，并解释 stdout 不能替代 return。",
            "starter_code": "def summarize_scores(scores):\n    total = sum(scores)\n    print(f\"total={total}\")\n    return __BLANK_1__\n",
            "visible_test_policy": "visible_and_hidden_summary",
            "requires_explanation": True,
            "metadata": {"required_patterns": ["return total"], "stdout_success": "total=9"},
            "code_blanks": [
                {
                    "blank_key": "blank_1",
                    "placeholder": "total",
                    "expected_concept": "返回已经计算出的 total。",
                    "acceptable_patterns_json": [{"type": "literal", "value": "total"}, {"type": "regex", "value": r"return\s+total"}],
                    "is_core": True,
                    "order_index": 0,
                }
            ],
            "test_cases": [_visible_case({"scores": [2, 3, 4]}, {"return": 9})],
        }
    return {
        "prompt_markdown": f"围绕 **{title}** 补全事件绑定和共享状态更新。",
        "starter_code": (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n\n"
            "button.__BLANK_1__(\"click\", () => {\n"
            "  __BLANK_2__;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        ),
        "visible_test_policy": "visible_and_hidden_summary",
        "requires_explanation": True,
        "metadata": {
            "required_patterns": ["addEventListener", "count += 1", "output.textContent"],
            "preview_html": {
                "success": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">1</p>",
                "failure": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">0</p>",
            },
        },
        "code_blanks": [
            {
                "blank_key": "blank_1",
                "placeholder": "addEventListener",
                "expected_concept": "绑定点击监听器。",
                "acceptable_patterns_json": [{"type": "literal", "value": "addEventListener"}],
                "is_core": True,
                "order_index": 0,
            },
            {
                "blank_key": "blank_2",
                "placeholder": "count += 1",
                "expected_concept": "在回调里递增外层共享状态。",
                "acceptable_patterns_json": [{"type": "literal", "value": "count += 1"}, {"type": "regex", "value": r"count\s*\+=\s*1"}],
                "is_core": True,
                "order_index": 1,
            },
        ],
        "test_cases": [
            _visible_case({"event": "click"}, {"textContent": "1"}),
            _preview_case({"selector": "#counter-output"}, {"textContent": "1"}, order_index=1),
        ],
    }


def _fix_bug_seed(*, language: str, title: str) -> dict[str, object]:
    if language == "python":
        return {
            "prompt_markdown": f"修复 **{title}** 相关代码：函数应返回计算值，不能只 print。",
            "starter_code": "def summarize_scores(scores):\n    total = sum(scores)\n    print(f\"total={total}\")\n    return None\n",
            "visible_test_policy": "visible_and_hidden_summary",
            "requires_explanation": True,
            "metadata": {"required_patterns": ["return total"], "stdout_success": "total=9"},
            "code_blanks": [],
            "test_cases": [_visible_case({"scores": [2, 3, 4]}, {"return": 9})],
        }
    return {
        "prompt_markdown": f"修复 **{title}** 相关代码：连续点击时计数必须持续递增。",
        "starter_code": (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n\n"
            "button.addEventListener(\"click\", () => {\n"
            "  let count = 0;\n"
            "  count += 1;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        ),
        "visible_test_policy": "visible_and_hidden_summary",
        "requires_explanation": True,
        "metadata": {"required_patterns": ["let count = 0", "addEventListener", "count += 1", "output.textContent"]},
        "code_blanks": [],
        "test_cases": [
            _visible_case({"event": "click"}, {"textContent": "1"}),
            _hidden_summary_case({"event": "three_clicks"}, {"textContent": "3"}, order_index=1),
        ],
    }


def _implement_function_seed(*, language: str, title: str) -> dict[str, object]:
    if language == "python":
        return {
            "prompt_markdown": f"实现一个最小函数来验证 **{title}**：返回总分并保留可观察输出。",
            "starter_code": "def summarize_scores(scores):\n    # TODO: return the total and print it for observation\n    pass\n",
            "visible_test_policy": "visible_and_hidden_summary",
            "requires_explanation": True,
            "metadata": {"required_patterns": ["sum(scores)", "return total"], "stdout_success": "total=9"},
            "code_blanks": [],
            "test_cases": [_visible_case({"scores": [2, 3, 4]}, {"return": 9})],
        }
    return {
        "prompt_markdown": f"实现 **{title}** 的最小交互：按钮点击后把共享 count 写回页面。",
        "starter_code": (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n"
            "// TODO: bind click and update output\n"
        ),
        "visible_test_policy": "visible_and_hidden_summary",
        "requires_explanation": True,
        "metadata": {"required_patterns": ["addEventListener", "count += 1", "output.textContent"]},
        "code_blanks": [],
        "test_cases": [
            _visible_case({"event": "click"}, {"textContent": "1"}),
            _hidden_summary_case({"event": "three_clicks"}, {"textContent": "3"}, order_index=1),
        ],
    }


def _explain_code_seed(*, language: str, title: str) -> dict[str, object]:
    starter = (
        "def summarize_scores(scores):\n    total = sum(scores)\n    print(f\"total={total}\")\n    return total\n"
        if language == "python"
        else (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n"
            "button.addEventListener(\"click\", () => {\n"
            "  count += 1;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
    )
    return {
        "prompt_markdown": f"阅读代码并解释 **{title}** 的关键风险点：为什么当前结构能通过可见验证？",
        "starter_code": starter,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": {"required_patterns": _required_patterns_for(language)},
        "code_blanks": [],
        "test_cases": [_visible_case({"read": "explain"}, {"understanding": True})],
    }


def _review_patch_seed(*, language: str, title: str) -> dict[str, object]:
    original_code = (
        "def summarize_scores(scores):\n    total = sum(scores)\n    print(f\"total={total}\")\n    return total\n"
        if language == "python"
        else (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n"
            "button.addEventListener(\"click\", () => {\n"
            "  count += 1;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
    )
    ai_diff = (
        "-    return total\n+    print(total)\n+    return None"
        if language == "python"
        else "-let count = 0;\n button.addEventListener(\"click\", () => {\n+  let count = 0;\n   count += 1;"
    )
    expected_risk = (
        "函数不再返回调用方需要的值"
        if language == "python"
        else "count 被移进回调后每次点击都会重新初始化，连续点击不会累加"
    )
    return {
        "prompt_markdown": f"审核 AI 对 **{title}** 的修改。不要只看测试是否通过，要给出结论、证据、知识点风险和下一步。",
        "starter_code": original_code,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": {
            "requirement": "保留原有可见行为，并确保关键状态或返回值仍能被后续调用验证。",
            "original_code": original_code,
            "ai_diff": ai_diff,
            "review_focus": _expected_focus(language),
            "expected_risk": expected_risk,
            "expected_verdict": "fail",
            "expected_next_action": "request_change",
            "rubric": {
                "verdict_correctness": "0-2",
                "evidence_grounding": "0-2",
                "knowledge_point_alignment": "0-2",
                "actionability": "0-2",
            },
        },
        "code_blanks": [],
        "test_cases": [],
    }


def _visible_case(input_json: Mapping[str, object], expected_output_json: Mapping[str, object], *, order_index: int = 0) -> dict[str, object]:
    return {
        "case_type": "visible",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": True,
        "timeout_ms": 5000,
        "order_index": order_index,
    }


def _hidden_summary_case(input_json: Mapping[str, object], expected_output_json: Mapping[str, object], *, order_index: int) -> dict[str, object]:
    return {
        "case_type": "hidden",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": False,
        "timeout_ms": 5000,
        "order_index": order_index,
    }


def _preview_case(input_json: Mapping[str, object], expected_output_json: Mapping[str, object], *, order_index: int) -> dict[str, object]:
    return {
        "case_type": "preview_assertion",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": False,
        "timeout_ms": 5000,
        "order_index": order_index,
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


def _contains_forbidden_material(seed: Mapping[str, object]) -> bool:
    serialized = json.dumps(_string_values(seed), ensure_ascii=False).lower()
    forbidden = ("hidden test source", "api_key", "sk-", "traceback", "raw prompt", "provider error")
    if any(item in serialized for item in forbidden):
        return True
    solution_reference = seed.get("solution_reference")
    return isinstance(solution_reference, str) and bool(solution_reference.strip())


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


def _fingerprint(exercise_type: str, misconception: str, prompt: str, code: str) -> str:
    payload = f"{exercise_type}|{misconception}|{prompt}|{code[:256]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_high_risk(context: Mapping[str, object]) -> bool:
    weak_points = _string_list(context.get("weak_points_json"))
    if len(weak_points) >= 2:
        return True
    mastery = context.get("mastery_score")
    if isinstance(mastery, int | float) and mastery < 0.45:
        return True
    return "core" in str(context.get("title") or "").lower()


def _misconception_for(index: int) -> str:
    values = ("state_scope_error", "test_only_reasoning", "return_vs_output", "missing_actionable_fix")
    return values[index % len(values)]


def _type_title(exercise_type: str) -> str:
    labels = {
        "code_blank": "短补全",
        "fix_bug": "缺陷修复",
        "explain_code": "代码解释",
        "implement_function": "最小实现",
        "review_ai_patch": "AI 补丁审核",
    }
    return labels.get(exercise_type, "复习变体")


def _expected_focus(language: str) -> str:
    if language == "python":
        return "区分 return value 与 stdout，确认调用方能继续使用结果"
    return "状态应位于能跨事件复用的作用域，并用需求、diff 与可见行为共同判断"


def _warmup_keywords(language: str) -> list[str]:
    if language == "python":
        return ["return", "返回", "stdout", "调用方", "结果"]
    return ["state", "count", "作用域", "事件", "diff", "需求"]


def _required_patterns_for(language: str) -> list[str]:
    if language == "python":
        return ["return total"]
    return ["addEventListener", "count += 1", "output.textContent"]


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
