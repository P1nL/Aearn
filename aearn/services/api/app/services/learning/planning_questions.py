"""Server-owned typed catalog for Tutor planning questions."""
from __future__ import annotations

from collections.abc import Mapping

from psycopg import Connection

from app.services.learning.planning_facts import (
    PlanningFactError,
    PlanningFactField,
    normalize_planning_fact,
)


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


def build_planning_question_presentation(
    conn: Connection[dict[str, object]],
    *,
    question_key: str,
) -> dict[str, object]:
    try:
        field = PlanningFactField(question_key)
    except ValueError as exc:
        raise PlanningQuestionCatalogError("planning question key is unsupported") from exc

    if field is PlanningFactField.LANGUAGE_ID:
        rows = conn.execute(
            """
            SELECT DISTINCT ON (language) language, title
            FROM language_courses
            WHERE archived_at IS NULL
            ORDER BY language, level, title, id
            """
        ).fetchall()
        options: list[dict[str, object]] = [
            {"value": str(row["language"]), "label": str(row["title"])}
            for row in rows[:24]
        ]
        if not options:
            raise PlanningQuestionCatalogError("published language catalog is empty")
        return _selection(field, options=options, multiple=False, recommended=options[0]["value"])
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
) -> object:
    if catalog_version != PLANNING_QUESTION_CATALOG_VERSION:
        raise PlanningQuestionCatalogError("planning question catalog version is stale")
    try:
        field = PlanningFactField(question_key)
        normalized = normalize_planning_fact(field, value)
    except (ValueError, PlanningFactError) as exc:
        raise PlanningQuestionCatalogError("planning question value is invalid") from exc
    presentation = build_planning_question_presentation(conn, question_key=question_key)
    if presentation["type"] == "single_select":
        allowed = _option_values(presentation)
        if str(normalized) not in allowed:
            raise PlanningQuestionCatalogError("planning question value is outside the catalog")
    if presentation["type"] == "multi_select":
        allowed = _option_values(presentation)
        if not isinstance(normalized, list) or not set(str(item) for item in normalized).issubset(allowed):
            raise PlanningQuestionCatalogError("planning question values are outside the catalog")
    return normalized


def _selection(
    field: PlanningFactField,
    *,
    options: list[dict[str, object]],
    multiple: bool,
    recommended: object,
    maximum_selections: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "multi_select" if multiple else "single_select",
        "field_key": field.value,
        "options": options,
        "recommended": recommended,
    }
    if maximum_selections is not None:
        payload["maximum_selections"] = maximum_selections
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
