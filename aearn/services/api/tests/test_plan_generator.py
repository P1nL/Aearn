from app.services.plan_generator import COURSE_TEMPLATES


EXPECTED_MODULE_TITLES = {
    "javascript": [
        "JavaScript language basics",
        "Control flow and functions",
        "Objects and shared state",
        "DOM events and shared state",
        "Async behavior and modules",
        "Verify AI-generated DOM code",
    ],
    "python": [
        "Python basics and value flow",
        "Control flow and functions",
        "Data structures",
        "Modules and input/output",
        "Errors, exceptions, and visible tests",
        "Classes and AI-generated code review",
    ],
    "html_css": [
        "HTML document structure",
        "Forms, controls, and accessibility",
        "CSS selectors, cascade, and box model",
        "Text and visual styling",
        "CSS layout systems",
        "Responsive structure and visual review",
    ],
}


def test_supported_mvp_course_templates_follow_official_doc_taxonomy() -> None:
    for language in ("javascript", "python", "html_css"):
        modules = COURSE_TEMPLATES[language]

        assert [module.title for module in modules] == EXPECTED_MODULE_TITLES[language]
        assert modules[0].is_skippable is False
        assert [module.order_index for module in modules] == list(range(len(modules)))
        assert all(module.knowledge_points for module in modules)
