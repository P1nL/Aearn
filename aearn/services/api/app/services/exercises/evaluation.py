from __future__ import annotations

from collections.abc import Mapping, Sequence
from app.services.runners.runtime_runner import RuntimeExecutionResult


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


def build_review_ai_patch_completion_result(
    exercise: Mapping[str, object],
    answer: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    metadata = exercise.get("metadata_json")
    if not isinstance(metadata, Mapping):
        metadata = {}
    expected_verdict = str(metadata.get("expected_verdict") or "fail")
    expected_risk = str(metadata.get("expected_risk") or "")
    expected_next_actions = metadata.get("expected_next_actions") or ["reject", "request_change"]
    if not isinstance(expected_next_actions, Sequence) or isinstance(expected_next_actions, str):
        expected_next_actions = ["reject", "request_change"]

    verdict = str(answer.get("verdict") or "")
    evidence = str(answer.get("evidence") or "")
    knowledge_point_risk = str(answer.get("knowledge_point_risk") or "")
    learner_next_action = str(answer.get("next_action") or "")
    score_breakdown = {
        "verdict_correctness": 2 if verdict == expected_verdict else 1 if verdict == "uncertain" else 0,
        "evidence_grounding": _review_evidence_score(evidence),
        "knowledge_point_alignment": _review_alignment_score(knowledge_point_risk, expected_risk),
        "actionability": 2 if learner_next_action in {str(item) for item in expected_next_actions} else 1 if learner_next_action else 0,
    }
    score = sum(score_breakdown.values())
    result, fsrs_rating, next_action = _review_ai_patch_outcome(score_breakdown)
    weak_points = _review_ai_patch_weak_points(score_breakdown)
    feedback = _review_ai_patch_feedback(result, score_breakdown, expected_risk)
    hard_gates = {
        "runtime_gate": True,
        "test_gate": score_breakdown["evidence_grounding"] >= 2,
        "core_blank_gate": score_breakdown["verdict_correctness"] >= 2,
        "explanation_gate": score_breakdown["knowledge_point_alignment"] >= 2,
    }
    response: dict[str, object] = {
        "result": result,
        "score": score,
        "score_breakdown": score_breakdown,
        "hard_gates": hard_gates,
        "test_pass_rate": 1.0 if score_breakdown["verdict_correctness"] >= 2 else 0.0,
        "hint_usage_count": 0,
        "error_count": 0 if score_breakdown["verdict_correctness"] >= 2 else 1,
        "weak_points": weak_points,
        "error_cause": weak_points[0] if weak_points else None,
        "feedback": feedback,
        "next_action": next_action,
        "fsrs_rating": fsrs_rating,
        "review_ai_patch_result": {
            "verdict": verdict,
            "expected_verdict": expected_verdict,
            "evidence_quality": "strong" if score_breakdown["evidence_grounding"] >= 2 else "weak",
            "expected_risk": expected_risk,
            "learner_next_action": learner_next_action,
        },
    }
    service_fields: dict[str, object] = {
        "evaluation_status": "evaluated",
        "explanation_check_result": response["review_ai_patch_result"],
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


def _review_evidence_score(evidence: str) -> int:
    normalized = evidence.lower()
    grounded_markers = ("diff", "test", "requirement", "需求", "测试", "改动", "证据")
    if len(evidence.strip()) >= 40 and any(marker in normalized for marker in grounded_markers):
        return 2
    if evidence.strip():
        return 1
    return 0


def _review_alignment_score(knowledge_point_risk: str, expected_risk: str) -> int:
    if not knowledge_point_risk.strip():
        return 0
    risk_tokens = [token for token in expected_risk.replace("，", " ").replace("。", " ").split() if len(token) >= 2]
    if risk_tokens and any(token in knowledge_point_risk for token in risk_tokens[:6]):
        return 2
    aligned_markers = ("状态", "作用域", "返回", "stdout", "class", "selector", "风险", "知识点")
    if any(marker in knowledge_point_risk for marker in aligned_markers):
        return 2
    return 1


def _review_ai_patch_outcome(score_breakdown: Mapping[str, int]) -> tuple[str, str, str]:
    if score_breakdown["verdict_correctness"] == 0:
        return "failed", "Again", "review_variant"
    if score_breakdown["evidence_grounding"] < 2:
        return "partial", "Hard", "review_variant"
    if all(score >= 2 for score in score_breakdown.values()):
        return "easy", "Easy", "schedule_review"
    if sum(score_breakdown.values()) >= 6:
        return "passed", "Good", "schedule_review"
    return "partial", "Hard", "review_variant"


def _review_ai_patch_weak_points(score_breakdown: Mapping[str, int]) -> list[str]:
    weak_points: list[str] = []
    if score_breakdown["verdict_correctness"] < 2:
        weak_points.append("incorrect_review_verdict")
    if score_breakdown["evidence_grounding"] < 2:
        weak_points.append("insufficient_test_or_diff_evidence")
    if score_breakdown["knowledge_point_alignment"] < 2:
        weak_points.append("knowledge_point_risk_not_aligned")
    if score_breakdown["actionability"] < 2:
        weak_points.append("next_action_not_actionable")
    return weak_points


def _review_ai_patch_feedback(
    result: str,
    score_breakdown: Mapping[str, int],
    expected_risk: str,
) -> str:
    if result == "failed":
        return "审查结论和当前知识点风险不一致，需要重新判断 AI 改动是否满足需求。"
    if score_breakdown["evidence_grounding"] < 2:
        return "结论方向可以，但证据不足。需要引用需求、diff 或可见测试，而不是只说 tests passed。"
    if result == "easy":
        return "审查结论、证据、知识点风险和下一步都清楚，可以进入复习调度。"
    if expected_risk:
        return f"审查基本成立。继续把证据和风险说得更具体：{expected_risk}"
    return "审查基本成立，下一次继续强化证据链。"


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
