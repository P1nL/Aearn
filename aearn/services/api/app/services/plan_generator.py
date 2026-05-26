from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from app.models.onboarding import (
    DraftKnowledgePoint,
    DraftModule,
    Language,
    PlanDraft,
    PlanGenerateRequest,
    RuntimeBoundary,
)


UNSUPPORTED_LANGUAGES: list[Language] = ["java", "cpp"]


COURSE_TEMPLATES: dict[str, list[DraftModule]] = {
    "javascript": [
        DraftModule(
            temp_id="mod_draft_js_dom_events",
            title="DOM events and shared state",
            description="Practice event listeners, state variables, and DOM updates.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                DraftKnowledgePoint(
                    temp_id="kp_draft_js_event_listener",
                    title="Event listener placement",
                    description="Understand how callbacks connect user actions to DOM changes.",
                    skill_tags=["dom", "event"],
                    exercise_refs=["ex_dom_click_count"],
                ),
                DraftKnowledgePoint(
                    temp_id="kp_draft_js_state_scope",
                    title="State scope across callbacks",
                    description="Keep shared state outside the callback so repeated events compose.",
                    skill_tags=["state", "scope"],
                    exercise_refs=["ex_dom_state_scope"],
                ),
            ],
        ),
        DraftModule(
            temp_id="mod_draft_js_ai_verification",
            title="Verify AI-generated DOM code",
            description="Use visible DOM assertions to check generated code instead of trusting it.",
            order_index=1,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                DraftKnowledgePoint(
                    temp_id="kp_draft_js_dom_assertions",
                    title="DOM assertion reading",
                    description="Read test feedback and connect failures to DOM state.",
                    skill_tags=["testing", "dom"],
                    exercise_refs=["ex_dom_visible_assertions"],
                ),
            ],
        ),
    ],
    "html_css": [
        DraftModule(
            temp_id="mod_draft_html_css_interaction",
            title="Interactive layout states",
            description="Practice simple layout changes, form states, and browser preview checks.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                DraftKnowledgePoint(
                    temp_id="kp_draft_css_state_class",
                    title="State classes and selectors",
                    description="Connect user interaction states to CSS selectors.",
                    skill_tags=["css", "state"],
                    exercise_refs=["ex_css_state_class"],
                ),
                DraftKnowledgePoint(
                    temp_id="kp_draft_html_accessible_controls",
                    title="Accessible control structure",
                    description="Use semantic controls before styling interaction states.",
                    skill_tags=["html", "accessibility"],
                    exercise_refs=["ex_html_control_structure"],
                ),
            ],
        ),
    ],
    "python": [
        DraftModule(
            temp_id="mod_draft_python_functions",
            title="Functions, stdout, and tests",
            description="Practice small Python functions and verify behavior with stdout/tests.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                DraftKnowledgePoint(
                    temp_id="kp_draft_python_return_values",
                    title="Return values vs stdout",
                    description="Separate function return values from printed output.",
                    skill_tags=["function", "stdout"],
                    exercise_refs=["ex_python_return_stdout"],
                ),
                DraftKnowledgePoint(
                    temp_id="kp_draft_python_visible_tests",
                    title="Reading visible test failures",
                    description="Use assertion messages to correct generated Python code.",
                    skill_tags=["testing", "debugging"],
                    exercise_refs=["ex_python_visible_tests"],
                ),
            ],
        ),
    ],
    "java": [
        DraftModule(
            temp_id="mod_draft_java_static_reading",
            title="Java static code reading",
            description="First version keeps Java as a reading and completion placeholder.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=1,
            knowledge_points=[
                DraftKnowledgePoint(
                    temp_id="kp_draft_java_method_shape",
                    title="Method shape and type signatures",
                    description="Read method signatures without running a Java sandbox yet.",
                    skill_tags=["java", "types"],
                ),
            ],
        ),
    ],
    "cpp": [
        DraftModule(
            temp_id="mod_draft_cpp_static_reading",
            title="C++ static code reading",
            description="First version keeps C++ as a reading and completion placeholder.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=1,
            knowledge_points=[
                DraftKnowledgePoint(
                    temp_id="kp_draft_cpp_function_shape",
                    title="Function shape and standard output",
                    description="Read C++ function structure without running a compiler sandbox yet.",
                    skill_tags=["cpp", "types"],
                ),
            ],
        ),
    ],
}


def validate_generation_input(payload: PlanGenerateRequest) -> str | None:
    if payload.mode == "goal_based":
        if not payload.goal_text or not payload.goal_text.strip():
            return "goal_text is required for goal_based mode"
    if payload.mode == "material_based":
        if not any(material.content.strip() for material in payload.materials):
            return "at least one material with content is required for material_based mode"
    return None


def build_plan_draft(
    payload: PlanGenerateRequest,
    user: Mapping[str, object],
    course: Mapping[str, object],
) -> PlanDraft:
    language = str(course["language"])
    runtime_profile = course["runtime_profile"]
    if not isinstance(runtime_profile, Mapping):
        raise TypeError("runtime_profile must be a mapping")

    modules = COURSE_TEMPLATES[language]
    goal_text = _goal_text(payload)
    source_attribution = _source_attribution(payload, course)
    draft_id = _draft_id(payload, course)
    runtime_tier = str(runtime_profile["runtime_tier"])

    return PlanDraft(
        draft_id=draft_id,
        user_id=str(user["id"]),
        language_course_id=str(course["id"]),
        goal_text=goal_text,
        language=language,  # type: ignore[arg-type]
        target_level=payload.target_level,
        mode=payload.mode,
        deadline=payload.time_budget.deadline if payload.time_budget else None,
        modules=modules,
        runtime_boundary=RuntimeBoundary(
            runtime_tier=runtime_tier,  # type: ignore[arg-type]
            unsupported_languages=UNSUPPORTED_LANGUAGES,
            notice=_runtime_notice(runtime_tier),
        ),
        source_attribution=source_attribution,
    )


def has_supported_mvp_runtime(plan_draft: PlanDraft) -> bool:
    return plan_draft.runtime_boundary.runtime_tier in {"browser_preview", "python_stdout_test"}


def normalize_target_level(target_level: str) -> str:
    if target_level == "beginner_to_intermediate":
        return "beginner"
    return target_level


def _goal_text(payload: PlanGenerateRequest) -> str:
    if payload.mode == "goal_based":
        return (payload.goal_text or "").strip()

    titles = [material.title for material in payload.materials if material.title]
    if titles:
        return f"Learn from provided materials: {', '.join(titles)}"
    return "Learn from provided programming materials"


def _draft_id(payload: PlanGenerateRequest, course: Mapping[str, object]) -> str:
    body = {
        "user_id": payload.user_id,
        "mode": payload.mode,
        "goal_text": payload.goal_text,
        "language": payload.language,
        "course_id": str(course["id"]),
        "materials": [material.model_dump() for material in payload.materials],
        "target_level": payload.target_level,
        "time_budget": payload.time_budget.model_dump(mode="json") if payload.time_budget else None,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"plan_draft_{digest}"


def _runtime_notice(runtime_tier: str) -> str:
    if runtime_tier == "browser_preview":
        return "This course can use browser preview and DOM assertions in the first MVP."
    if runtime_tier == "python_stdout_test":
        return "This course can use Python stdout and visible tests in the first MVP."
    return "Java/C++ compile-and-run sandbox is planned later; first MVP shows static reading and completion boundaries only."


def _source_attribution(payload: PlanGenerateRequest, course: Mapping[str, object]) -> list[str]:
    sources = [f"Course template: {course['title']}"]
    if payload.mode == "goal_based" and payload.goal_text:
        sources.append("User goal: goal_text")
    if payload.mode == "material_based":
        material_titles = [material.title or material.type for material in payload.materials]
        sources.append(f"User materials: {', '.join(material_titles)}")
    sources.append("Runtime capability: M1 seed catalog")
    return sources
