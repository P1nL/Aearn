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


def _kp(
    temp_id: str,
    title: str,
    description: str,
    skill_tags: list[str],
    exercise_refs: list[str] | None = None,
) -> DraftKnowledgePoint:
    return DraftKnowledgePoint(
        temp_id=temp_id,
        title=title,
        description=description,
        skill_tags=skill_tags,
        exercise_refs=exercise_refs or [],
    )


def _module(
    temp_id: str,
    title: str,
    description: str,
    order_index: int,
    *,
    is_skippable: bool,
    estimated_sessions: int,
    knowledge_points: list[DraftKnowledgePoint],
) -> DraftModule:
    return DraftModule(
        temp_id=temp_id,
        title=title,
        description=description,
        order_index=order_index,
        is_skippable=is_skippable,
        estimated_sessions=estimated_sessions,
        knowledge_points=knowledge_points,
    )


COURSE_TEMPLATES: dict[str, list[DraftModule]] = {
    "javascript": [
        _module(
            temp_id="mod_draft_js_language_basics",
            title="JavaScript language basics",
            description="Mirror MDN JavaScript Guide basics: values, variables, strings, and arrays.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_values_variables",
                    "Values, variables, and types",
                    "Explain how JavaScript stores values and when type conversion matters.",
                    ["javascript", "types"],
                    ["ex_js_values_variables"],
                ),
                _kp(
                    "kp_draft_js_strings_arrays",
                    "Strings and indexed collections",
                    "Use strings and arrays as visible data that browser interactions can inspect.",
                    ["strings", "arrays"],
                    ["ex_js_strings_arrays"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_control_flow_functions",
            title="Control flow and functions",
            description="Use branches, loops, and functions before wiring browser interactions.",
            order_index=1,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_condition_loop",
                    "Conditionals and loops",
                    "Trace which branch or loop body runs for a given input.",
                    ["control_flow", "loops"],
                    ["ex_js_condition_loop"],
                ),
                _kp(
                    "kp_draft_js_function_contract",
                    "Function contracts",
                    "Keep parameters, return values, and side effects separate.",
                    ["functions", "contracts"],
                    ["ex_js_function_contract"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_objects_state",
            title="Objects and shared state",
            description="Represent changing browser data with object properties and scoped state.",
            order_index=2,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_object_access",
                    "Object property access",
                    "Read and update object fields without losing the shape of the data.",
                    ["objects", "state"],
                    ["ex_js_object_access"],
                ),
                _kp(
                    "kp_draft_js_state_scope",
                    "State scope across callbacks",
                    "Keep shared state outside callbacks so repeated events compose.",
                    ["state", "scope"],
                    ["ex_dom_state_scope"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_dom_events",
            title="DOM events and shared state",
            description="Practice event listeners, state variables, and DOM updates.",
            order_index=3,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_event_listener",
                    "Event listener placement",
                    "Understand how callbacks connect user actions to DOM changes.",
                    ["dom", "event"],
                    ["ex_dom_click_count"],
                ),
                _kp(
                    "kp_draft_js_dom_updates",
                    "DOM query and update flow",
                    "Connect selected elements, text content, and classes to user-visible changes.",
                    ["dom", "browser_preview"],
                    ["ex_dom_update_flow"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_async_modules",
            title="Async behavior and modules",
            description="Read promise-based code and module boundaries without hiding runtime order.",
            order_index=4,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_js_promise_order",
                    "Promise timing",
                    "Distinguish immediate code from code that runs after an async result.",
                    ["promises", "async"],
                    ["ex_js_promise_order"],
                ),
                _kp(
                    "kp_draft_js_module_boundaries",
                    "Module import/export boundaries",
                    "Explain which names are exported, imported, and available to a file.",
                    ["modules", "imports"],
                    ["ex_js_module_boundaries"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_ai_verification",
            title="Verify AI-generated DOM code",
            description="Use visible DOM assertions to check generated code instead of trusting it.",
            order_index=5,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_js_dom_assertions",
                    "DOM assertion reading",
                    "Read test feedback and connect failures to DOM state.",
                    ["testing", "dom"],
                    ["ex_dom_visible_assertions"],
                ),
                _kp(
                    "kp_draft_js_generated_code_review",
                    "Generated code review",
                    "Check AI-generated DOM code against requirements before editing.",
                    ["ai_review", "verification"],
                    ["ex_js_generated_code_review"],
                ),
            ],
        ),
    ],
    "html_css": [
        _module(
            temp_id="mod_draft_html_document_structure",
            title="HTML document structure",
            description="Mirror MDN HTML structuring content: headings, sections, links, and text.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_html_semantic_structure",
                    "Semantic structure",
                    "Use headings, sections, and landmarks to make content understandable.",
                    ["html", "semantics"],
                    ["ex_html_semantic_structure"],
                ),
                _kp(
                    "kp_draft_html_links_media",
                    "Links, images, and text content",
                    "Choose the right element for navigation, content, and embedded assets.",
                    ["html", "content"],
                    ["ex_html_links_media"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_html_forms_accessibility",
            title="Forms, controls, and accessibility",
            description="Build usable controls before styling interaction states.",
            order_index=1,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_html_accessible_controls",
                    "Accessible control structure",
                    "Use labels, buttons, and inputs before adding visual styling.",
                    ["html", "accessibility"],
                    ["ex_html_control_structure"],
                ),
                _kp(
                    "kp_draft_html_form_feedback",
                    "Form feedback structure",
                    "Represent validation, helper text, and status messages in semantic markup.",
                    ["forms", "accessibility"],
                    ["ex_html_form_feedback"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_css_selectors_cascade",
            title="CSS selectors, cascade, and box model",
            description="Mirror MDN styling basics: selectors, cascade, inheritance, and spacing.",
            order_index=2,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_css_selector_specificity",
                    "Selectors and specificity",
                    "Predict which CSS rule applies when selectors overlap.",
                    ["css", "selectors"],
                    ["ex_css_selector_specificity"],
                ),
                _kp(
                    "kp_draft_css_box_model",
                    "Box model spacing",
                    "Use margin, border, padding, and content size to explain layout changes.",
                    ["css", "box_model"],
                    ["ex_css_box_model"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_css_text_visual_style",
            title="Text and visual styling",
            description="Style readable text, color, and states while preserving content hierarchy.",
            order_index=3,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_css_text_hierarchy",
                    "Text hierarchy",
                    "Use font size, weight, and spacing to support readable content order.",
                    ["css", "typography"],
                    ["ex_css_text_hierarchy"],
                ),
                _kp(
                    "kp_draft_css_state_class",
                    "State classes and selectors",
                    "Connect interaction states to CSS classes and selectors.",
                    ["css", "state"],
                    ["ex_css_state_class"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_html_css_interaction",
            title="CSS layout systems",
            description="Use normal flow, flexbox, grid, and positioning to build stable layouts.",
            order_index=4,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_css_flex_grid",
                    "Flexbox and grid layout",
                    "Choose flexbox or grid based on the direction and structure of the layout.",
                    ["css", "layout"],
                    ["ex_css_flex_grid"],
                ),
                _kp(
                    "kp_draft_css_positioning",
                    "Positioning and overflow",
                    "Explain when positioned elements leave normal flow and how overflow appears.",
                    ["css", "positioning"],
                    ["ex_css_positioning"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_html_css_responsive_review",
            title="Responsive structure and visual review",
            description="Check generated layouts across widths and fix structure before styling polish.",
            order_index=5,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_css_responsive_breakpoints",
                    "Responsive breakpoint checks",
                    "Use browser preview widths to catch layout assumptions in generated CSS.",
                    ["css", "responsive"],
                    ["ex_css_responsive_breakpoints"],
                ),
                _kp(
                    "kp_draft_html_visual_review",
                    "Generated page review",
                    "Inspect generated markup and CSS against hierarchy, responsiveness, and accessibility.",
                    ["html", "css", "ai_review"],
                    ["ex_html_visual_review"],
                ),
            ],
        ),
    ],
    "python": [
        _module(
            temp_id="mod_draft_python_informal_intro",
            title="Python basics and value flow",
            description="Mirror the official Python Tutorial introduction: expressions, strings, variables, and output.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_python_values_expressions",
                    "Values, expressions, and names",
                    "Trace how Python evaluates expressions and binds names to values.",
                    ["python", "values"],
                    ["ex_python_values_expressions"],
                ),
                _kp(
                    "kp_draft_python_return_values",
                    "Return values vs stdout",
                    "Separate function return values from printed output.",
                    ["function", "stdout"],
                    ["ex_python_return_stdout"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_functions",
            title="Control flow and functions",
            description="Use if statements, loops, function definitions, and arguments.",
            order_index=1,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_python_condition_paths",
                    "Condition paths",
                    "Trace how if/elif branches choose different outcomes for visible inputs.",
                    ["conditionals", "debugging"],
                    ["ex_python_condition_paths"],
                ),
                _kp(
                    "kp_draft_python_function_arguments",
                    "Function arguments and return paths",
                    "Explain how arguments enter a function and how each branch returns a value.",
                    ["functions", "control_flow"],
                    ["ex_python_function_arguments"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_data_structures",
            title="Data structures",
            description="Use lists, dictionaries, sets, tuples, and comprehensions to shape data.",
            order_index=2,
            is_skippable=False,
            estimated_sessions=4,
            knowledge_points=[
                _kp(
                    "kp_draft_python_sequence_operations",
                    "Lists and sequence operations",
                    "Read indexing, slicing, mutation, and iteration over ordered data.",
                    ["lists", "sequences"],
                    ["ex_python_sequence_operations"],
                ),
                _kp(
                    "kp_draft_python_mapping_transform",
                    "Dictionaries and set lookups",
                    "Use key-based lookup and membership checks to simplify transformations.",
                    ["dicts", "sets"],
                    ["ex_python_mapping_transform"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_modules_io",
            title="Modules and input/output",
            description="Organize reusable code with imports and interpret stdout, files, and formatted output.",
            order_index=3,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_python_import_boundaries",
                    "Import and module boundaries",
                    "Explain which names belong to a module and how imports expose them.",
                    ["modules", "imports"],
                    ["ex_python_import_boundaries"],
                ),
                _kp(
                    "kp_draft_python_io_formatting",
                    "Input/output and formatting",
                    "Use formatted output and visible stdout without confusing it with return values.",
                    ["io", "stdout"],
                    ["ex_python_io_formatting"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_errors_testing",
            title="Errors, exceptions, and visible tests",
            description="Use tracebacks and assertion messages to locate and explain failures.",
            order_index=4,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_python_traceback_reading",
                    "Traceback reading",
                    "Identify the failing line, exception type, and likely cause from a traceback.",
                    ["exceptions", "debugging"],
                    ["ex_python_traceback_reading"],
                ),
                _kp(
                    "kp_draft_python_visible_tests",
                    "Reading visible test failures",
                    "Use assertion messages to correct generated Python code.",
                    ["testing", "debugging"],
                    ["ex_python_visible_tests"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_classes_ai_verification",
            title="Classes and AI-generated code review",
            description="Read simple class structure and verify generated snippets with edge examples.",
            order_index=5,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_python_class_shape",
                    "Class shape and object state",
                    "Read __init__, instance attributes, and method calls in small classes.",
                    ["classes", "objects"],
                    ["ex_python_class_shape"],
                ),
                _kp(
                    "kp_draft_python_edge_examples",
                    "Edge example checks",
                    "Create small examples that expose missing branches or wrong assumptions.",
                    ["testing", "edge_cases"],
                    ["ex_python_edge_examples"],
                ),
            ],
        ),
    ],
    "java": [
        _module(
            temp_id="mod_draft_java_static_reading",
            title="Java static code reading",
            description="First version keeps Java as a reading and completion placeholder.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=1,
            knowledge_points=[
                _kp(
                    "kp_draft_java_method_shape",
                    "Method shape and type signatures",
                    "Read method signatures without running a Java sandbox yet.",
                    ["java", "types"],
                ),
            ],
        ),
    ],
    "cpp": [
        _module(
            temp_id="mod_draft_cpp_static_reading",
            title="C++ static code reading",
            description="First version keeps C++ as a reading and completion placeholder.",
            order_index=0,
            is_skippable=False,
            estimated_sessions=1,
            knowledge_points=[
                _kp(
                    "kp_draft_cpp_function_shape",
                    "Function shape and standard output",
                    "Read C++ function structure without running a compiler sandbox yet.",
                    ["cpp", "types"],
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
    taxonomy_source = _official_taxonomy_source(str(course["language"]))
    if taxonomy_source:
        sources.append(taxonomy_source)
    if payload.mode == "goal_based" and payload.goal_text:
        sources.append("User goal: goal_text")
    if payload.mode == "material_based":
        material_titles = [material.title or material.type for material in payload.materials]
        sources.append(f"User materials: {', '.join(material_titles)}")
    sources.append("Runtime capability: M1 seed catalog")
    return sources


def _official_taxonomy_source(language: str) -> str | None:
    if language == "python":
        return "Official documentation taxonomy: Python Tutorial"
    if language == "javascript":
        return "Official documentation taxonomy: MDN JavaScript Guide"
    if language == "html_css":
        return "Official documentation taxonomy: MDN HTML/CSS learning modules"
    return None
