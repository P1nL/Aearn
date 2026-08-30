"""Server-owned typed catalog for Tutor planning questions."""
from __future__ import annotations

from collections.abc import Mapping

from psycopg import Connection

from app.services.learning.planning_facts import (
    PlanningFactError,
    PlanningFactField,
    normalize_planning_fact,
)
from app.services.learning.planning_intent import PlanningLanguageIntent


PLANNING_QUESTION_CATALOG_VERSION = "tutor_planning_questions_v1"

_TARGET_LEVEL_OPTIONS: tuple[dict[str, object], ...] = (
    {"value": "beginner", "label": "入门"},
    {"value": "intermediate", "label": "进阶"},
    {"value": "advanced", "label": "高级"},
)
_EXPERIENCE_OPTIONS: tuple[dict[str, object], ...] = (
    {"value": "new", "label": "完全没有经验"},
    {"value": "beginner", "label": "了解基础"},
    {"value": "intermediate", "label": "做过小型项目"},
    {"value": "advanced", "label": "有较多实践经验"},
)
_TEACHING_PREFERENCE_OPTIONS: tuple[dict[str, object], ...] = (
    {"value": "examples_first", "label": "先看示例"},
    {"value": "concept_first", "label": "先讲概念"},
    {"value": "practice_heavy", "label": "多做练习"},
    {"value": "concise_feedback", "label": "反馈尽量简洁"},
)


class PlanningQuestionCatalogError(ValueError):
    pass


_PLANNING_QUESTION_PROMPTS: Mapping[PlanningFactField, str] = {
    PlanningFactField.LANGUAGE_ID: "你想学习哪门编程语言？",
    PlanningFactField.EXPERIENCE_LEVEL: "你目前有多少相关编程经验？",
    PlanningFactField.GOAL_TEXT: "你希望通过这次学习完成什么具体目标？",
    PlanningFactField.TARGET_LEVEL: "你希望达到什么学习层级？",
    PlanningFactField.WEEKLY_MINUTES: "你每周大约能投入多少学习时间？",
    PlanningFactField.TEACHING_PREFERENCES: "你偏好怎样的教学方式？",
    PlanningFactField.PACE_CONSTRAINTS: "你的学习节奏还有哪些限制或偏好？",
}

_PLANNING_FACT_MEANINGS: Mapping[PlanningFactField, str] = {
    PlanningFactField.LANGUAGE_ID: (
        "学习者要学习的编程语言或已发布课程；不是教学内容或界面使用的自然语言。"
    ),
    PlanningFactField.EXPERIENCE_LEVEL: "学习者此前与编程相关的经验等级。",
    PlanningFactField.GOAL_TEXT: "学习者希望通过本次学习完成的具体目标或应用方向。",
    PlanningFactField.TARGET_LEVEL: "学习者希望达到的课程掌握层级。",
    PlanningFactField.WEEKLY_MINUTES: "学习者每周可以投入的学习时间。",
    PlanningFactField.TEACHING_PREFERENCES: "学习者偏好的教学方式。",
    PlanningFactField.PACE_CONSTRAINTS: "学习者对进度安排、频率或节奏的限制与偏好。",
}


def planning_question_prompt(question_key: str | PlanningFactField) -> str:
    """Return the exact server-owned learner-facing question for one planning fact."""
    return _PLANNING_QUESTION_PROMPTS[_planning_question_field(question_key)]


def build_planning_question_model_descriptor(
    question_key: str | PlanningFactField,
) -> dict[str, object]:
    """Describe one missing fact without giving the model authority over its question."""
    field = _planning_question_field(question_key)
    return {
        "field_key": field.value,
        "meaning": _PLANNING_FACT_MEANINGS[field],
        "exact_question": _PLANNING_QUESTION_PROMPTS[field],
        "wording_policy": (
            "可先简短确认已知事实，然后必须逐字使用 exact_question 作为唯一问题；"
            "不得改写字段含义、补充括号示例、添加选项或提出第二个问题。"
        ),
        "response_authority": "aearn_typed_request",
    }


def _planning_question_field(question_key: str | PlanningFactField) -> PlanningFactField:
    if isinstance(question_key, PlanningFactField):
        return question_key
    try:
        return PlanningFactField(str(question_key))
    except ValueError as exc:
        raise PlanningQuestionCatalogError("planning question key is unsupported") from exc


def build_planning_question_presentation(
    conn: Connection[dict[str, object]],
    *,
    question_key: str,
    language_intent: PlanningLanguageIntent | None = None,
) -> dict[str, object]:
    field = _planning_question_field(question_key)

    if field is PlanningFactField.LANGUAGE_ID:
        rows = _language_course_rows(conn, language_intent=language_intent)
        options: list[dict[str, object]] = []
        seen_languages: set[str] = set()
        for row in rows:
            language = str(row["language"])
            if language in seen_languages:
                continue
            seen_languages.add(language)
            options.append({"value": language, "label": str(row["title"])})
            if len(options) >= 24:
                break
        if not options:
            raise PlanningQuestionCatalogError("published language catalog is empty")
        return _selection(
            field,
            options=options,
            multiple=False,
            recommended=None,
            selection_scope=(language_intent.selection_scope if language_intent is not None else "full_catalog"),
            selection_reason_code=(language_intent.reason_code if language_intent is not None else "no_intent_signal"),
            intent_policy_version=(language_intent.policy_version if language_intent is not None else None),
        )
    if field is PlanningFactField.TARGET_LEVEL:
        return _selection(field, options=list(_TARGET_LEVEL_OPTIONS), multiple=False, recommended="beginner")
    if field is PlanningFactField.EXPERIENCE_LEVEL:
        return _selection(field, options=list(_EXPERIENCE_OPTIONS), multiple=False, recommended="new")
    if field is PlanningFactField.TEACHING_PREFERENCES:
        return _selection(
            field,
            options=list(_TEACHING_PREFERENCE_OPTIONS),
            multiple=True,
            recommended=["examples_first", "practice_heavy"],
            maximum_selections=4,
        )
    if field is PlanningFactField.WEEKLY_MINUTES:
        return {
            "type": "integer",
            "field_key": field.value,
            "minimum": 15,
            "maximum": 10_080,
            "step": 15,
            "recommended": 300,
            "unit": "minutes_per_week",
        }
    maximum = 2_000 if field is PlanningFactField.GOAL_TEXT else 240
    return {
        "type": "text",
        "field_key": field.value,
        "minimum_length": 1,
        "maximum_length": maximum,
        "multiline": True,
    }


def format_planning_question_value(
    *,
    presentation: Mapping[str, object],
    value: object,
) -> str:
    presentation_type = str(presentation.get("type") or "")
    if presentation_type == "text":
        display = str(value).strip()
        if display:
            return display
        raise PlanningQuestionCatalogError("planning question display text is empty")
    if presentation_type == "integer":
        if presentation.get("unit") == "minutes_per_week" and isinstance(value, int):
            return f"每周 {value} 分钟"
        raise PlanningQuestionCatalogError("planning question integer display is unsupported")
    if presentation_type in {"single_select", "multi_select"}:
        raw_values = [value] if presentation_type == "single_select" else value
        if not isinstance(raw_values, list):
            raise PlanningQuestionCatalogError("planning question selection display is invalid")
        labels_by_value: dict[str, str] = {}
        raw_options = presentation.get("options")
        if not isinstance(raw_options, list):
            raise PlanningQuestionCatalogError("planning question display options are invalid")
        for option in raw_options:
            if not isinstance(option, Mapping):
                raise PlanningQuestionCatalogError("planning question display option is invalid")
            option_value = str(option.get("value") or "")
            option_label = str(option.get("label") or "").strip()
            if not option_value or not option_label:
                raise PlanningQuestionCatalogError("planning question display option is invalid")
            labels_by_value[option_value] = option_label
        labels: list[str] = []
        for selected in raw_values:
            label = labels_by_value.get(str(selected))
            if label is None:
                raise PlanningQuestionCatalogError("planning question display value is outside the catalog")
            labels.append(label)
        if labels:
            return "、".join(labels)
        raise PlanningQuestionCatalogError("planning question display selection is empty")
    raise PlanningQuestionCatalogError("planning question display type is unsupported")


def validate_planning_question_value(
    conn: Connection[dict[str, object]],
    *,
    question_key: str,
    catalog_version: str,
    value: object,
    presentation: Mapping[str, object] | None = None,
) -> object:
    if catalog_version != PLANNING_QUESTION_CATALOG_VERSION:
        raise PlanningQuestionCatalogError("planning question catalog version is stale")
    try:
        field = _planning_question_field(question_key)
        normalized = normalize_planning_fact(field, value)
    except (ValueError, PlanningFactError) as exc:
        raise PlanningQuestionCatalogError("planning question value is invalid") from exc
    presentation = presentation or build_planning_question_presentation(conn, question_key=question_key)
    if presentation["type"] == "single_select":
        allowed = _option_values(presentation)
        if str(normalized) not in allowed:
            raise PlanningQuestionCatalogError("planning question value is outside the catalog")
    if presentation["type"] == "multi_select":
        allowed = _option_values(presentation)
        if not isinstance(normalized, list) or not set(str(item) for item in normalized).issubset(allowed):
            raise PlanningQuestionCatalogError("planning question values are outside the catalog")
    return normalized


def _language_course_rows(
    conn: Connection[dict[str, object]],
    *,
    language_intent: PlanningLanguageIntent | None,
) -> list[dict[str, object]]:
    candidate_ids = language_intent.candidate_course_ids if language_intent is not None else ()
    if candidate_ids:
        rows = conn.execute(
            """
            SELECT courses.id, courses.language, courses.title, courses.level, candidates.ordinality
            FROM unnest(%s::uuid[]) WITH ORDINALITY AS candidates(course_id, ordinality)
            JOIN language_courses AS courses ON courses.id = candidates.course_id
            WHERE courses.archived_at IS NULL
            ORDER BY candidates.ordinality
            """,
            (list(candidate_ids),),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, language, title, level
            FROM language_courses
            WHERE archived_at IS NULL
            ORDER BY language, level, title, id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _selection(
    field: PlanningFactField,
    *,
    options: list[dict[str, object]],
    multiple: bool,
    recommended: object,
    maximum_selections: int | None = None,
    selection_scope: str | None = None,
    selection_reason_code: str | None = None,
    intent_policy_version: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "multi_select" if multiple else "single_select",
        "field_key": field.value,
        "options": options,
        "recommended": recommended,
    }
    if maximum_selections is not None:
        payload["maximum_selections"] = maximum_selections
    if selection_scope is not None:
        payload["selection_scope"] = selection_scope
        payload["selection_reason_code"] = selection_reason_code
        payload["intent_policy_version"] = intent_policy_version
    return payload


def _option_values(presentation: Mapping[str, object]) -> set[str]:
    raw_options = presentation.get("options")
    if not isinstance(raw_options, list):
        raise PlanningQuestionCatalogError("planning question options are invalid")
    values: set[str] = set()
    for option in raw_options:
        if not isinstance(option, Mapping) or not str(option.get("value") or ""):
            raise PlanningQuestionCatalogError("planning question option is invalid")
        values.add(str(option["value"]))
    return values
