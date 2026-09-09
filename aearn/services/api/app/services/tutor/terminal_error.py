"""Learner-safe terminal projection and the Queue retry outcome authority.

Conversation busy/version/input checks remain owned by the Queue controller.
No provider text or unknown diagnostic identifier is ever public copy.
"""
from __future__ import annotations


def terminal_is_recoverable(outcome: str | None, diagnostic_code: str | None) -> bool:
    return (
        outcome in {"failed", "model_unavailable"}
        or (outcome == "blocked_policy" and diagnostic_code == "capability_denied")
        or (outcome == "budget_exhausted" and diagnostic_code == "deadline_exhausted")
    )


def terminal_error_code(outcome: str | None, diagnostic_code: str | None = None) -> str:
    if diagnostic_code == "legacy_continuation_requires_new_turn":
        return "TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN"
    return {
        "model_unavailable": "MODEL_UNAVAILABLE",
        "blocked_policy": "CAPABILITY_DENIED",
        "budget_exhausted": "TUTOR_RUN_UNAVAILABLE",
        "cancelled": "RUN_NOT_ACTIVE",
    }.get(outcome or "", "TUTOR_RUN_FAILED")


def terminal_error_message(code: str, *, recoverable: bool) -> str:
    if code == "TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN":
        return "旧的等待步骤已结束，请发送一条新消息继续。"
    if code == "TUTOR_DISPATCH_FAILED" and recoverable:
        return "Tutor 暂时无法完成本轮处理，请重试。"
    message = {
        "MODEL_UNAVAILABLE": "Tutor 服务暂时不可用，本轮未能完成。",
        "CAPABILITY_DENIED": "Tutor 未能安全完成本轮处理。",
        "TUTOR_RUN_UNAVAILABLE": "本轮处理已达到运行限制，未能完成。",
        "RUN_NOT_ACTIVE": "本轮处理已结束。",
    }.get(code, "Tutor 暂时无法完成本轮处理。")
    return message + ("你可以重试本轮。" if recoverable else "请调整问题后发送一条新消息。")
