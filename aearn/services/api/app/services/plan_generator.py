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
            title="JavaScript 语言基础",
            description="对应 MDN JavaScript 指南基础：值、变量、字符串和数组。",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_values_variables",
                    "值、变量与类型",
                    "理解 JavaScript 如何存储值以及类型转换的时机。",
                    ["javascript", "types"],
                    ["ex_js_values_variables"],
                ),
                _kp(
                    "kp_draft_js_strings_arrays",
                    "字符串与索引集合",
                    "使用字符串和数组作为浏览器交互可检查的可见数据。",
                    ["strings", "arrays"],
                    ["ex_js_strings_arrays"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_control_flow_functions",
            title="控制流与函数",
            description="在连接浏览器交互之前，掌握分支、循环和函数。",
            order_index=1,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_condition_loop",
                    "条件与循环",
                    "追踪给定输入时哪个分支或循环体会执行。",
                    ["control_flow", "loops"],
                    ["ex_js_condition_loop"],
                ),
                _kp(
                    "kp_draft_js_function_contract",
                    "函数契约",
                    "区分参数、返回值和副作用。",
                    ["functions", "contracts"],
                    ["ex_js_function_contract"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_objects_state",
            title="对象与共享状态",
            description="用对象属性和作用域状态表示变化的浏览器数据。",
            order_index=2,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_object_access",
                    "对象属性访问",
                    "读取和更新对象字段而不破坏数据结构。",
                    ["objects", "state"],
                    ["ex_js_object_access"],
                ),
                _kp(
                    "kp_draft_js_state_scope",
                    "回调间的状态作用域",
                    "将共享状态放在回调外部，使重复事件可以组合。",
                    ["state", "scope"],
                    ["ex_dom_state_scope"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_dom_events",
            title="DOM 事件与共享状态",
            description="练习事件监听器、状态变量和 DOM 更新。",
            order_index=3,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_js_event_listener",
                    "事件监听器放置",
                    "理解回调如何将用户操作连接到 DOM 变化。",
                    ["dom", "event"],
                    ["ex_dom_click_count"],
                ),
                _kp(
                    "kp_draft_js_dom_updates",
                    "DOM 查询与更新流程",
                    "将选中的元素、文本内容和类名连接到用户可见的变化。",
                    ["dom", "browser_preview"],
                    ["ex_dom_update_flow"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_async_modules",
            title="异步行为与模块",
            description="阅读基于 Promise 的代码和模块边界，不隐藏运行时顺序。",
            order_index=4,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_js_promise_order",
                    "Promise 时序",
                    "区分立即执行的代码和异步结果返回后才执行的代码。",
                    ["promises", "async"],
                    ["ex_js_promise_order"],
                ),
                _kp(
                    "kp_draft_js_module_boundaries",
                    "模块导入导出边界",
                    "解释哪些名称被导出、导入以及对文件可用。",
                    ["modules", "imports"],
                    ["ex_js_module_boundaries"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_js_ai_verification",
            title="验证 AI 生成的 DOM 代码",
            description="使用可见的 DOM 断言检查生成的代码，而不是盲目信任。",
            order_index=5,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_js_dom_assertions",
                    "DOM 断言阅读",
                    "阅读测试反馈并将失败与 DOM 状态关联。",
                    ["testing", "dom"],
                    ["ex_dom_visible_assertions"],
                ),
                _kp(
                    "kp_draft_js_generated_code_review",
                    "生成代码审查",
                    "在编辑前对照需求检查 AI 生成的 DOM 代码。",
                    ["ai_review", "verification"],
                    ["ex_js_generated_code_review"],
                ),
            ],
        ),
    ],
    "html_css": [
        _module(
            temp_id="mod_draft_html_document_structure",
            title="HTML 文档结构",
            description="对应 MDN HTML 结构化内容：标题、区块、链接和文本。",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_html_semantic_structure",
                    "语义结构",
                    "使用标题、区块和地标使内容结构清晰可理解。",
                    ["html", "semantics"],
                    ["ex_html_semantic_structure"],
                ),
                _kp(
                    "kp_draft_html_links_media",
                    "链接、图片与文本内容",
                    "为导航、内容和嵌入资源选择正确的元素。",
                    ["html", "content"],
                    ["ex_html_links_media"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_html_forms_accessibility",
            title="表单、控件与无障碍",
            description="在设置交互状态样式之前，先构建可用的控件。",
            order_index=1,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_html_accessible_controls",
                    "无障碍控件结构",
                    "在添加视觉样式之前，先使用标签、按钮和输入框。",
                    ["html", "accessibility"],
                    ["ex_html_control_structure"],
                ),
                _kp(
                    "kp_draft_html_form_feedback",
                    "表单反馈结构",
                    "用语义化标记表示验证、辅助文本和状态消息。",
                    ["forms", "accessibility"],
                    ["ex_html_form_feedback"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_css_selectors_cascade",
            title="CSS 选择器、层叠与盒模型",
            description="对应 MDN 样式基础：选择器、层叠、继承和间距。",
            order_index=2,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_css_selector_specificity",
                    "选择器与优先级",
                    "预测选择器重叠时哪条 CSS 规则生效。",
                    ["css", "selectors"],
                    ["ex_css_selector_specificity"],
                ),
                _kp(
                    "kp_draft_css_box_model",
                    "盒模型间距",
                    "用外边距、边框、内边距和内容尺寸解释布局变化。",
                    ["css", "box_model"],
                    ["ex_css_box_model"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_css_text_visual_style",
            title="文本与视觉样式",
            description="在保持内容层次的同时设置可读文本、颜色和状态样式。",
            order_index=3,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_css_text_hierarchy",
                    "文本层次",
                    "使用字号、字重和间距支持可读的内容顺序。",
                    ["css", "typography"],
                    ["ex_css_text_hierarchy"],
                ),
                _kp(
                    "kp_draft_css_state_class",
                    "状态类与选择器",
                    "将交互状态连接到 CSS 类和选择器。",
                    ["css", "state"],
                    ["ex_css_state_class"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_html_css_interaction",
            title="CSS 布局系统",
            description="使用常规流、弹性盒、网格和定位构建稳定布局。",
            order_index=4,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_css_flex_grid",
                    "弹性盒与网格布局",
                    "根据布局的方向和结构选择弹性盒或网格。",
                    ["css", "layout"],
                    ["ex_css_flex_grid"],
                ),
                _kp(
                    "kp_draft_css_positioning",
                    "定位与溢出",
                    "解释定位元素何时脱离常规流以及溢出如何表现。",
                    ["css", "positioning"],
                    ["ex_css_positioning"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_html_css_responsive_review",
            title="响应式结构与视觉审查",
            description="在不同宽度下检查生成的布局，在样式打磨前修复结构。",
            order_index=5,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_css_responsive_breakpoints",
                    "响应式断点检查",
                    "使用浏览器预览宽度捕捉生成 CSS 中的布局假设。",
                    ["css", "responsive"],
                    ["ex_css_responsive_breakpoints"],
                ),
                _kp(
                    "kp_draft_html_visual_review",
                    "生成页面审查",
                    "对照层次、响应性和无障碍检查生成的标记和 CSS。",
                    ["html", "css", "ai_review"],
                    ["ex_html_visual_review"],
                ),
            ],
        ),
    ],
    "python": [
        _module(
            temp_id="mod_draft_python_informal_intro",
            title="Python 基础与值流动",
            description="对应 Python 官方教程入门：表达式、字符串、变量和输出。",
            order_index=0,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_python_values_expressions",
                    "值、表达式与名称",
                    "追踪 Python 如何求值表达式并将名称绑定到值。",
                    ["python", "values"],
                    ["ex_python_values_expressions"],
                ),
                _kp(
                    "kp_draft_python_return_values",
                    "返回值与标准输出",
                    "区分函数返回值和打印输出。",
                    ["function", "stdout"],
                    ["ex_python_return_stdout"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_functions",
            title="控制流与函数",
            description="使用 if 语句、循环、函数定义和参数。",
            order_index=1,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_python_condition_paths",
                    "条件路径",
                    "追踪 if/elif 分支如何为可见输入选择不同结果。",
                    ["conditionals", "debugging"],
                    ["ex_python_condition_paths"],
                ),
                _kp(
                    "kp_draft_python_function_arguments",
                    "函数参数与返回路径",
                    "解释参数如何进入函数以及每个分支如何返回值。",
                    ["functions", "control_flow"],
                    ["ex_python_function_arguments"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_data_structures",
            title="数据结构",
            description="使用列表、字典、集合、元组和推导式来组织数据。",
            order_index=2,
            is_skippable=False,
            estimated_sessions=4,
            knowledge_points=[
                _kp(
                    "kp_draft_python_sequence_operations",
                    "列表与序列操作",
                    "理解有序数据的索引、切片、修改和迭代。",
                    ["lists", "sequences"],
                    ["ex_python_sequence_operations"],
                ),
                _kp(
                    "kp_draft_python_mapping_transform",
                    "字典与集合查找",
                    "使用基于键的查找和成员检查来简化数据转换。",
                    ["dicts", "sets"],
                    ["ex_python_mapping_transform"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_modules_io",
            title="模块与输入输出",
            description="用导入组织可复用代码，理解标准输出、文件和格式化输出。",
            order_index=3,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_python_import_boundaries",
                    "导入与模块边界",
                    "解释哪些名称属于模块以及导入如何暴露它们。",
                    ["modules", "imports"],
                    ["ex_python_import_boundaries"],
                ),
                _kp(
                    "kp_draft_python_io_formatting",
                    "输入输出与格式化",
                    "使用格式化输出和可见的标准输出，不与返回值混淆。",
                    ["io", "stdout"],
                    ["ex_python_io_formatting"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_errors_testing",
            title="错误、异常与可见测试",
            description="使用回溯信息和断言消息定位并解释失败原因。",
            order_index=4,
            is_skippable=False,
            estimated_sessions=3,
            knowledge_points=[
                _kp(
                    "kp_draft_python_traceback_reading",
                    "回溯信息阅读",
                    "从回溯中识别出错行、异常类型和可能原因。",
                    ["exceptions", "debugging"],
                    ["ex_python_traceback_reading"],
                ),
                _kp(
                    "kp_draft_python_visible_tests",
                    "阅读可见测试失败",
                    "使用断言消息修正生成的 Python 代码。",
                    ["testing", "debugging"],
                    ["ex_python_visible_tests"],
                ),
            ],
        ),
        _module(
            temp_id="mod_draft_python_classes_ai_verification",
            title="类与 AI 生成代码审查",
            description="阅读简单类结构，用边界示例验证生成的代码片段。",
            order_index=5,
            is_skippable=True,
            estimated_sessions=2,
            knowledge_points=[
                _kp(
                    "kp_draft_python_class_shape",
                    "类的形状与对象状态",
                    "阅读小型类中的 __init__、实例属性和方法调用。",
                    ["classes", "objects"],
                    ["ex_python_class_shape"],
                ),
                _kp(
                    "kp_draft_python_edge_examples",
                    "边界示例检查",
                    "创建小示例来暴露遗漏的分支或错误的假设。",
                    ["testing", "edge_cases"],
                    ["ex_python_edge_examples"],
                ),
            ],
        ),
    ],
    "java": [
        _module(
            temp_id="mod_draft_java_static_reading",
            title="Java 静态代码阅读",
            description="首版将 Java 作为阅读和补全的占位课程。",
            order_index=0,
            is_skippable=False,
            estimated_sessions=1,
            knowledge_points=[
                _kp(
                    "kp_draft_java_method_shape",
                    "方法形状与类型签名",
                    "在没有 Java 沙箱的情况下阅读方法签名。",
                    ["java", "types"],
                ),
            ],
        ),
    ],
    "cpp": [
        _module(
            temp_id="mod_draft_cpp_static_reading",
            title="C++ 静态代码阅读",
            description="首版将 C++ 作为阅读和补全的占位课程。",
            order_index=0,
            is_skippable=False,
            estimated_sessions=1,
            knowledge_points=[
                _kp(
                    "kp_draft_cpp_function_shape",
                    "函数形状与标准输出",
                    "在没有编译器沙箱的情况下阅读 C++ 函数结构。",
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
