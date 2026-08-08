"""Explicit opt-in live-provider smoke for the Tutor latest-input teaching contract."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextInput,
    TutorContextSelection,
    TutorContextSource,
    TutorPolicySnapshot,
    TutorRunSnapshot,
)
from app.core.config import get_settings
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway


_LIVE_SMOKE_ENV = "AEARN_RUN_TUTOR_LATEST_INPUT_SMOKE"


@dataclass(frozen=True)
class TutorLatestInputSmokeCase:
    case_id: str
    current_input: str
    history: tuple[tuple[str, str], ...]


def _cases() -> tuple[TutorLatestInputSmokeCase, ...]:
    return (
        TutorLatestInputSmokeCase(
            case_id="already_has_resource",
            current_input="我已经有了",
            history=(
                ("user", "我想做个网站"),
                ("assistant", "我们先准备绘画作品图片，再继续 HTML。"),
                ("user", "绘画作品，迪士尼风格，零基础"),
            ),
        ),
        TutorLatestInputSmokeCase(
            case_id="teaching_direction_correction",
            current_input="你不是应该教我编程语言吗",
            history=(
                ("user", "我想做个网站"),
                ("assistant", "先下载图片并建立 HTML 文件夹。"),
                ("user", "我已经有了"),
            ),
        ),
        TutorLatestInputSmokeCase(
            case_id="language_advice_first",
            current_input="我应该学哪些语言",
            history=(
                ("user", "我想做个网站"),
                ("assistant", "先准备图片和 HTML 文件。"),
                ("user", "绘画作品，迪士尼风格，零基础"),
                ("user", "我已经有了"),
                ("user", "你不是应该教我编程语言吗"),
            ),
        ),
    )


def evaluate_smoke_message(case_id: str, message: str) -> dict[str, bool]:
    normalized = message.strip()
    lower = normalized.lower()
    language_markers = (
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "rust",
        "c#",
        "c++",
        "sql",
        "php",
        "kotlin",
        "swift",
    )
    acknowledgement_markers = ("明白", "好的", "对", "是的", "抱歉", "调整", "改为", "不再", "已经")
    stale_instruction_markers = ("下载图片", "寻找图片", "新建图片文件夹", "先准备图片", "继续图片优先")
    direct_answer = any(marker in lower for marker in language_markers)
    correction_acknowledged = any(marker in normalized for marker in acknowledgement_markers)
    stale_path_abandoned = not any(marker in normalized for marker in stale_instruction_markers)
    no_rejected_step_repeated = stale_path_abandoned
    if case_id == "already_has_resource":
        latest_turn_relevant = correction_acknowledged and stale_path_abandoned
        answer_first = latest_turn_relevant
    elif case_id == "teaching_direction_correction":
        latest_turn_relevant = correction_acknowledged and direct_answer
        answer_first = latest_turn_relevant
    else:
        latest_turn_relevant = direct_answer
        correction_acknowledged = True
        answer_first = direct_answer
    return {
        "latest_turn_relevant": latest_turn_relevant,
        "correction_acknowledged": correction_acknowledged,
        "no_rejected_step_repeated": no_rejected_step_repeated,
        "answer_first": answer_first,
        "stale_path_abandoned": stale_path_abandoned,
    }


def _snapshot(case: TutorLatestInputSmokeCase, *, context_token_budget: int) -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id=f"live-smoke-{case.case_id}",
        conversation_id=f"live-smoke-conversation-{case.case_id}",
        user_id="live-smoke-user",
        input_revision=1,
        origin="interactive",
        policy=TutorPolicySnapshot(
            deadline=datetime.now(UTC) + timedelta(minutes=2),
            max_iterations=1,
            max_model_calls=1,
            context_token_budget=context_token_budget,
        ),
    )


def _selection(case: TutorLatestInputSmokeCase, *, token_budget: int) -> TutorContextSelection:
    return TutorContextBuilder().build(
        TutorContextInput(
            run_id=f"live-smoke-{case.case_id}",
            conversation_id=f"live-smoke-conversation-{case.case_id}",
            input_revision=1,
            current_input_required=True,
            current_input=TutorContextSource(f"current:{case.case_id}", case.current_input),
            recent_messages=tuple(
                TutorContextSource(
                    f"history:{case.case_id}:{index}",
                    {"role": role, "content": content},
                )
                for index, (role, content) in enumerate(case.history, start=1)
            ),
        ),
        token_budget=token_budget,
    )


def main() -> int:
    if os.getenv(_LIVE_SMOKE_ENV) != "1":
        print(json.dumps({"status": "disabled", "required_env": _LIVE_SMOKE_ENV}, ensure_ascii=False))
        return 2

    settings = get_settings()
    gateway = PrimaryTutorProviderGateway(settings=settings)
    reports: list[dict[str, object]] = []
    for case in _cases():
        snapshot = _snapshot(case, context_token_budget=settings.tutor_context_token_budget)
        result = gateway.decide(
            run=snapshot,
            context=_selection(case, token_budget=settings.tutor_context_token_budget),
        )
        if result.decision is None or result.decision.public_message is None:
            reports.append(
                {
                    "case_id": case.case_id,
                    "status": "unavailable",
                    "safe_code": result.safe_code or "MODEL_UNAVAILABLE",
                    "rubric": {
                        "latest_turn_relevant": False,
                        "correction_acknowledged": False,
                        "no_rejected_step_repeated": False,
                        "answer_first": False,
                        "stale_path_abandoned": False,
                    },
                }
            )
            continue
        public_message = result.decision.public_message
        reports.append(
            {
                "case_id": case.case_id,
                "status": "completed",
                "public_message": public_message,
                "rubric": evaluate_smoke_message(case.case_id, public_message),
            }
        )

    passed = True
    for report in reports:
        rubric = report.get("rubric")
        if not isinstance(rubric, dict) or not all(bool(value) for value in rubric.values()):
            passed = False
    print(json.dumps({"status": "passed" if passed else "failed", "cases": reports}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
