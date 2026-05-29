from app.services.plan_generator import COURSE_TEMPLATES


EXPECTED_MODULE_TITLES = {
    "javascript": [
        "JavaScript 语言基础",
        "控制流与函数",
        "对象与共享状态",
        "DOM 事件与共享状态",
        "异步行为与模块",
        "验证 AI 生成的 DOM 代码",
    ],
    "python": [
        "Python 基础与值流动",
        "控制流与函数",
        "数据结构",
        "模块与输入输出",
        "错误、异常与可见测试",
        "类与 AI 生成代码审查",
    ],
    "html_css": [
        "HTML 文档结构",
        "表单、控件与无障碍",
        "CSS 选择器、层叠与盒模型",
        "文本与视觉样式",
        "CSS 布局系统",
        "响应式结构与视觉审查",
    ],
}


def test_supported_mvp_course_templates_follow_official_doc_taxonomy() -> None:
    for language in ("javascript", "python", "html_css"):
        modules = COURSE_TEMPLATES[language]

        assert [module.title for module in modules] == EXPECTED_MODULE_TITLES[language]
        assert modules[0].is_skippable is False
        assert [module.order_index for module in modules] == list(range(len(modules)))
        assert all(module.knowledge_points for module in modules)
