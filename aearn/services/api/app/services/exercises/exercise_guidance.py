from __future__ import annotations

from collections.abc import Mapping, Sequence


def resolve_blank(exercise: Mapping[str, object], blank_identifier: str) -> Mapping[str, object] | None:
    code_blanks = exercise.get("code_blanks", [])
    if not isinstance(code_blanks, Sequence):
        return None
    for blank in code_blanks:
        if not isinstance(blank, Mapping):
            continue
        if str(blank.get("id")) == blank_identifier or str(blank.get("blank_key")) == blank_identifier:
            return blank
    return None


def build_hint_response(
    exercise: Mapping[str, object],
    *,
    blank: Mapping[str, object],
    hint_level: str,
    current_code: str,
    hint_usage_count: int,
) -> dict[str, object]:
    runtime_profile = exercise.get("runtime_profile", {})
    language = str(runtime_profile.get("language", "")) if isinstance(runtime_profile, Mapping) else ""
    blank_key = str(blank.get("blank_key", ""))
    expected_concept = str(blank.get("expected_concept", "当前空缺"))
    placeholder = str(blank.get("placeholder", ""))

    if hint_level == "nudge":
        content = f"先只盯住 {expected_concept} 相关的那一行，确认它应该出现在什么位置，不要一次改完整题。"
        affected_score = {"max_result": "easy", "score_penalty_hint": 0}
    elif hint_level == "concept":
        content = _concept_hint(language, blank_key, expected_concept)
        affected_score = {"max_result": "passed", "score_penalty_hint": 1}
    else:
        content = _code_shape_hint(language, blank_key, placeholder, current_code)
        affected_score = {"max_result": "passed", "score_penalty_hint": 2}

    return {
        "hint": {
            "hint_level": hint_level,
            "content": content,
        },
        "hint_usage_count": hint_usage_count,
        "affected_score": affected_score,
        "next_action": "retry_same",
    }


def build_error_explanation_response(
    exercise: Mapping[str, object],
    *,
    error_message: str,
    stderr: str,
    failed_tests: Sequence[Mapping[str, object]],
    current_code: str,
    related_knowledge_points: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    runtime_profile = exercise.get("runtime_profile", {})
    language = str(runtime_profile.get("language", "")) if isinstance(runtime_profile, Mapping) else ""
    error_cause = _classify_error_cause(language, error_message, stderr, failed_tests, current_code)
    explanation, fix_suggestion = _error_feedback(error_cause, language)
    return {
        "error_cause": error_cause,
        "explanation": explanation,
        "fix_suggestion": fix_suggestion,
        "related_knowledge_points": list(related_knowledge_points),
        "next_action": "retry_same",
    }


def build_explanation_check_response(
    exercise: Mapping[str, object],
    *,
    explanation: str,
    focus: str,
    round_number: int,
) -> dict[str, object]:
    runtime_profile = exercise.get("runtime_profile", {})
    language = str(runtime_profile.get("language", "")) if isinstance(runtime_profile, Mapping) else ""
    normalized = explanation.strip()
    score = _score_explanation(language, normalized, focus)
    if score >= 2:
        return {
            "result": "passed",
            "score": 2,
            "score_breakdown": {"explanation_check": 2},
            "follow_up_required": False,
            "feedback": _passed_feedback(language),
            "next_action": "advance_next",
        }

    if score == 1:
        return {
            "result": "partial",
            "score": 1,
            "score_breakdown": {"explanation_check": 1},
            "follow_up_required": round_number < 2,
            "feedback": _partial_feedback(language, focus),
            "next_action": "retry_same" if round_number < 2 else "review_variant",
        }

    return {
        "result": "failed",
        "score": 0,
        "score_breakdown": {"explanation_check": 0},
        "follow_up_required": round_number < 2,
        "feedback": _failed_feedback(language, focus),
        "next_action": "retry_same" if round_number < 2 else "review_variant",
    }


def _concept_hint(language: str, blank_key: str, expected_concept: str) -> str:
    if language == "javascript" and blank_key == "blank_1":
        return "先确认事件监听是绑在按钮节点上，而不是把状态逻辑塞进监听器定义之外的无关位置。"
    if language == "javascript" and blank_key == "blank_2":
        return "点击回调里要先更新共享状态，再把最新值同步到页面；如果把状态放进回调里，每次点击都会重置。"
    if language == "python":
        return "这里要区分 stdout 和 return：`print(...)` 只负责输出，真正给测试断言的是返回值。"
    if language == "html_css":
        return "这一题的关键是把交互态类名补到正确元素上，让预览和选择器断言都能看到它。"
    return expected_concept


def _code_shape_hint(language: str, blank_key: str, placeholder: str, current_code: str) -> str:
    if language == "javascript" and blank_key == "blank_1":
        return '保留当前结构，只把 `button.<事件绑定>("click", () => { ... })` 这一小段形状补出来。'
    if language == "javascript" and blank_key == "blank_2":
        return "回调内部应该只有两步：更新共享状态，再把状态写回 output；不要在回调里重新声明状态变量。"
    if language == "python":
        return "保持 `print(...)` 不动，只把 `return <已计算结果>` 这一小段补完整。"
    if placeholder and placeholder not in current_code:
        return f"只补局部结构，目标形状接近 `{placeholder}`，不要重写整段题目。"
    return "只补当前空缺附近的最小代码形状，不要一次重写整题。"


def _classify_error_cause(
    language: str,
    error_message: str,
    stderr: str,
    failed_tests: Sequence[Mapping[str, object]],
    current_code: str,
) -> str:
    lowered_error = f"{error_message}\n{stderr}".lower()
    if "timed out" in lowered_error or "timeout" in lowered_error:
        return "timeout_loop"
    if language == "python" and (
        "syntaxerror" in lowered_error or "invalid syntax" in lowered_error or "syntax error" in lowered_error
    ):
        return "python_syntax_error"
    if "undefinedvariable" in current_code.lower() or "is not defined" in lowered_error:
        return "undefined_reference"
    if language == "javascript" and (_looks_like_state_scope_error(current_code) or _mentions_three_clicks(failed_tests)):
        return "state_scope_error"
    if failed_tests:
        return "boundary_condition_error"
    return "runtime_error"


def _error_feedback(error_cause: str, language: str) -> tuple[str, str]:
    if error_cause == "python_syntax_error":
        return (
            "代码在语法阶段就失败了，所以 stdout 和测试都还没真正开始执行。",
            "先回到报错行附近，检查冒号、括号、缩进和字符串闭合，再重新运行。",
        )
    if error_cause == "state_scope_error":
        return (
            "状态变量被放进了事件回调内部，每次点击都会重新初始化，所以连续点击时结果一直回到 1。",
            "把状态变量移到事件回调外层，只在回调里执行累加和页面同步。",
        )
    if error_cause == "undefined_reference":
        return (
            "当前代码引用了一个没有定义的名字，运行器在真正进入业务逻辑前就中断了。",
            "先找到未定义的变量或函数名，确认它来自正确的作用域或已经提前声明。",
        )
    if error_cause == "boundary_condition_error":
        return (
            "主路径可能已经接近正确，但边界条件没有覆盖住，所以额外测试仍然失败。",
            "优先对照失败摘要检查状态生命周期、返回值边界或多次触发后的行为。",
        )
    if error_cause == "timeout_loop":
        return (
            "代码进入了无法结束的循环或等待，运行器在达到超时上限后主动中止。",
            "先删掉无限循环，缩小到最小可验证逻辑，再逐步恢复剩余代码。",
        )
    if language == "python":
        return (
            "当前运行失败来自 Python 代码执行阶段，先把 stderr 对应的语句修正，再看测试。",
            "从 stderr 指向的行开始，检查变量名、缩进和返回值是否和题面一致。",
        )
    return (
        "当前失败说明代码和预期行为之间还有一个关键差异，先定位哪一行没有满足题面的行为约束。",
        "对照失败摘要，只修一处最相关的位置，再重新运行验证。",
    )


def _score_explanation(language: str, explanation: str, focus: str) -> int:
    lowered = explanation.lower()
    if language == "javascript":
        contradiction = ("回调里" in explanation or "事件函数里" in explanation) and not any(
            token in explanation for token in ("外层", "外部", "回调外", "监听器外")
        )
        if contradiction:
            return 0
        signals = 0
        if any(token in explanation for token in ("外层", "外部", "回调外", "监听器外")):
            signals += 1
        if any(token in explanation for token in ("共享状态", "累加", "count", "state", "闭包")):
            signals += 1
        if any(token in explanation for token in ("重新初始化", "每次点击", "重置", "作用域", "scope")):
            signals += 1
        if focus == "boundary_condition" and any(token in explanation for token in ("三次", "多次点击", "连续点击")):
            signals += 1
        return 2 if signals >= 3 else 1 if signals >= 2 else 0

    if language == "python":
        signals = 0
        if "return" in lowered:
            signals += 1
        if "print" in lowered or "stdout" in lowered:
            signals += 1
        if any(token in explanation for token in ("不是返回值", "不能替代", "断言", "测试")):
            signals += 1
        return 2 if signals >= 3 else 1 if signals >= 2 else 0

    if language == "html_css":
        signals = 0
        if "active" in lowered:
            signals += 1
        if any(token in explanation for token in ("类名", "class", "选择器", "preview")):
            signals += 1
        return 2 if signals >= 2 else 1 if signals == 1 else 0

    if len(explanation) >= 24:
        return 1
    return 0


def _passed_feedback(language: str) -> str:
    if language == "python":
        return "解释已经区分了 `print` 和 `return` 的职责，也覆盖了测试为什么只看返回值。"
    return "解释覆盖了关键代码的主路径和失败原因，已经能支撑你自己完成下一次修改。"


def _partial_feedback(language: str, focus: str) -> str:
    if language == "javascript" and focus == "boundary_condition":
        return "你已经说到主路径，但还没明确解释为什么连续触发时旧写法会重置状态。"
    if language == "python":
        return "你提到了输出或返回值中的一部分，但还没有把两者和测试断言的关系说完整。"
    return "主路径已经接近，但边界条件、状态生命周期或修改原因还不够稳定。"


def _failed_feedback(language: str, focus: str) -> str:
    if language == "javascript" and focus == "core_logic":
        return "还没有解释清楚状态变量为什么必须放在回调外层，以及错误写法会怎样破坏多次点击。"
    if language == "python":
        return "当前解释还没说明 `print` 和 `return` 各自负责什么，因此无法证明你理解了这题。"
    return "当前解释和代码行为还对不上，需要直接回到关键代码和失败证据。"


def _looks_like_state_scope_error(current_code: str) -> bool:
    listener_index = current_code.find("addEventListener")
    if listener_index < 0:
        return False
    prefix = current_code[:listener_index]
    return "let count = 0" not in prefix and "const count = 0" not in prefix and "var count = 0" not in prefix


def _mentions_three_clicks(failed_tests: Sequence[Mapping[str, object]]) -> bool:
    for test in failed_tests:
        message = str(test.get("message", ""))
        case_id = str(test.get("case_id", ""))
        if "三次" in message or "three" in message.lower() or "three_clicks" in case_id.lower():
            return True
    return False
