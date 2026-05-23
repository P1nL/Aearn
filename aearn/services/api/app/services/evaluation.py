from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.services.runtime_runner import RuntimeExecutionResult


def build_code_completion_result(
    exercise: Mapping[str, object],
    runtime_result: RuntimeExecutionResult,
    *,
    hint_usage_count: int,
    error_count: int,
    explanation: str | None,
    explanation_check_result: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    requires_explanation = bool(exercise.get("requires_explanation", False))
    explanation_result = _build_explanation_result(
        requires_explanation,
        explanation,
        explanation_check_result,
    )
    test_gate = runtime_result.test_pass_rate >= 1.0
    runtime_gate = runtime_result.runtime_status == "success"
    explanation_gate = bool(explanation_result["passed"])

    score_breakdown: dict[str, int] = {
        "completion_correctness": 2 if runtime_result.core_blank_gate else 1 if runtime_result.any_blank_passed else 0,
        "runtime_and_tests": _runtime_and_test_score(runtime_result),
        "error_diagnosis": _error_diagnosis_score(runtime_result, explanation, error_count),
        "explanation_check": _int_or_zero(explanation_result.get("score")),
    }
    hard_gates = {
        "runtime_gate": runtime_gate,
        "test_gate": test_gate,
        "core_blank_gate": runtime_result.core_blank_gate,
        "explanation_gate": explanation_gate,
    }
    weak_points = _weak_points(exercise, runtime_result)

    result, fsrs_rating, next_action = _fallback_outcome(
        runtime_result=runtime_result,
        hard_gates=hard_gates,
        test_pass_rate=runtime_result.test_pass_rate,
        hint_usage_count=hint_usage_count,
        error_count=error_count,
    )
    score = sum(int(value) for value in score_breakdown.values())
    feedback = _feedback_text(result, runtime_result, weak_points, hint_usage_count, error_count)
    evaluation_status = "evaluated" if _is_valid_result(result, score, score_breakdown, hard_gates, fsrs_rating) else "needs_manual_review"

    response: dict[str, object] = {
        "result": result,
        "score": score,
        "score_breakdown": score_breakdown,
        "hard_gates": hard_gates,
        "test_pass_rate": runtime_result.test_pass_rate,
        "hint_usage_count": hint_usage_count,
        "error_count": error_count,
        "weak_points": weak_points,
        "error_cause": runtime_result.error_message,
        "feedback": feedback,
        "next_action": next_action,
        "fsrs_rating": fsrs_rating,
    }
    service_fields: dict[str, object] = {
        "evaluation_status": evaluation_status,
        "explanation_check_result": explanation_result,
    }
    return response, service_fields


def mastery_score_for(result: str, score: int) -> float:
    capped = max(0, min(score, 8))
    if result == "failed":
        return round(max(capped / 8, 0.18), 4)
    if result == "partial":
        return round(max(capped / 8, 0.42), 4)
    return round(max(capped / 8, 0.68), 4)


def knowledge_point_status_for(result: str) -> str:
    if result in {"partial", "passed", "easy"}:
        return "reviewing"
    return "learning"


def schedule_days_for(fsrs_rating: str) -> int:
    if fsrs_rating == "Again":
        return 1
    if fsrs_rating == "Hard":
        return 2
    if fsrs_rating == "Easy":
        return 7
    return 4


def _build_explanation_result(
    requires_explanation: bool,
    explanation: str | None,
    explanation_check_result: Mapping[str, object] | None,
) -> dict[str, object]:
    if not requires_explanation:
        return {
            "result": "skipped",
            "score": 2,
            "passed": True,
            "follow_up_required": False,
        }
    if explanation_check_result is not None:
        result = str(explanation_check_result.get("result", "failed"))
        score = _int_or_zero(explanation_check_result.get("score", 0))
        follow_up_required = bool(explanation_check_result.get("follow_up_required", False))
        return {
            "result": result,
            "score": score,
            "passed": result == "passed" and score >= 2,
            "follow_up_required": follow_up_required,
        }
    if explanation and explanation.strip():
        return {
            "result": "partial",
            "score": 1,
            "passed": False,
            "follow_up_required": True,
        }
    return {
        "result": "missing",
        "score": 0,
        "passed": False,
        "follow_up_required": True,
    }


def _runtime_and_test_score(runtime_result: RuntimeExecutionResult) -> int:
    if runtime_result.runtime_status != "success":
        return 0
    if runtime_result.test_pass_rate >= 1.0:
        return 2
    if runtime_result.test_pass_rate >= 0.8:
        return 1
    return 0


def _error_diagnosis_score(
    runtime_result: RuntimeExecutionResult,
    explanation: str | None,
    error_count: int,
) -> int:
    if runtime_result.runtime_status != "success":
        return 2 if explanation and explanation.strip() else 0
    if error_count <= 0:
        return 2
    if error_count == 1:
        return 1
    return 0


def _weak_points(
    exercise: Mapping[str, object],
    runtime_result: RuntimeExecutionResult,
) -> list[str]:
    weak_points: list[str] = []
    if not runtime_result.core_blank_gate:
        code_blanks = exercise.get("code_blanks", [])
        if isinstance(code_blanks, Sequence):
            for blank in code_blanks:
                if not isinstance(blank, Mapping):
                    continue
                weak_points.append(str(blank.get("expected_concept", "核心补全未通过")))
    if runtime_result.runtime_status != "success":
        weak_points.append(runtime_result.error_message or "运行未成功")
    elif runtime_result.test_pass_rate < 1.0:
        weak_points.append("visible_tests")
    return weak_points


def _fallback_outcome(
    *,
    runtime_result: RuntimeExecutionResult,
    hard_gates: Mapping[str, object],
    test_pass_rate: float,
    hint_usage_count: int,
    error_count: int,
) -> tuple[str, str, str]:
    if runtime_result.runtime_status != "success":
        return "failed", "Again", "explain_error"
    if not bool(hard_gates["core_blank_gate"]):
        return "failed", "Again", "retry_same"
    if not bool(hard_gates["test_gate"]):
        if test_pass_rate < 0.8:
            return "partial", "Hard", "show_hint"
        return "failed", "Again", "explain_error"
    if not bool(hard_gates["explanation_gate"]):
        return "partial", "Hard", "review_variant"
    if hint_usage_count == 0 and error_count == 0 and test_pass_rate >= 1.0:
        return "easy", "Easy", "schedule_review"
    if hint_usage_count >= 2 or error_count >= 2:
        return "passed", "Hard", "review_variant"
    return "passed", "Good", "schedule_review"


def _feedback_text(
    result: str,
    runtime_result: RuntimeExecutionResult,
    weak_points: Sequence[str],
    hint_usage_count: int,
    error_count: int,
) -> str:
    if result == "easy":
        return "代码与测试一次通过，可以进入后续复习。"
    if result == "passed":
        if hint_usage_count > 0 or error_count > 0:
            return "结果已通过，但这次仍依赖了一些修正信号，建议用变体题再巩固一次。"
        return "代码通过测试，可以进入复习调度。"
    if result == "partial":
        return "部分测试通过，但还需要继续修补关键逻辑。"
    if runtime_result.runtime_status != "success":
        return runtime_result.error_message or "运行未成功，需要先修复错误。"
    if weak_points:
        return f"核心点仍未通过：{weak_points[0]}。"
    return "当前提交未达到通过门槛。"


def _is_valid_result(
    result: str,
    score: int,
    score_breakdown: Mapping[str, object],
    hard_gates: Mapping[str, object],
    fsrs_rating: str,
) -> bool:
    if result not in {"failed", "partial", "passed", "easy"}:
        return False
    if fsrs_rating not in {"Again", "Hard", "Good", "Easy"}:
        return False
    if score != sum(_int_or_zero(value) for value in score_breakdown.values()):
        return False
    if score < 0 or score > 8:
        return False
    if (not bool(hard_gates["runtime_gate"]) or not bool(hard_gates["test_gate"]) or not bool(hard_gates["core_blank_gate"])) and result in {"passed", "easy"}:
        return False
    return True


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
