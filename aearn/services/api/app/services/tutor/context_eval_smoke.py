"""Explicit opt-in five-turn real-provider smoke for Tutor context governance."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter

from app.agents.harness.context_budget import (
    TutorContextBudgetPlanner,
    build_tutor_context_budget_policy,
)
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextInput,
    TutorContextSource,
    TutorPolicySnapshot,
    TutorRunSnapshot,
)
from app.core.config import Settings, get_settings
from app.services.llm.llm_client import select_llm_protocol
from app.services.tutor.latest_input_smoke import evaluate_smoke_message
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway


REAL_PROVIDER_SMOKE_ENV = "TUTOR_REAL_PROVIDER_SMOKE"
_MAX_TURNS = 5
_MAX_PROVIDER_ATTEMPTS = 10
_TURNS = (
    "我想做个网站",
    "绘画作品，迪士尼风格，零基础",
    "我已经有了",
    "你不是应该教我编程语言吗",
    "我应该学哪些语言",
)


@dataclass(frozen=True)
class TutorContextSmokeReport:
    status: str
    provider: str
    protocol: str
    model: str
    executed_at: str
    policy_version: str
    turns: tuple[dict[str, object], ...]
    total_provider_attempts: int
    fake_contract_verified: bool = False
    real_provider_behavior_sampled: bool = True
    release_approved: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "protocol": self.protocol,
            "model": self.model,
            "executed_at": self.executed_at,
            "policy_version": self.policy_version,
            "turns": list(self.turns),
            "total_provider_attempts": self.total_provider_attempts,
            "fake_contract_verified": self.fake_contract_verified,
            "real_provider_behavior_sampled": self.real_provider_behavior_sampled,
            "release_approved": self.release_approved,
        }


def evaluate_context_smoke_turn(turn_index: int, message: str) -> dict[str, bool]:
    if turn_index == 3:
        legacy = evaluate_smoke_message("already_has_resource", message)
    elif turn_index == 4:
        legacy = evaluate_smoke_message("teaching_direction_correction", message)
    elif turn_index == 5:
        legacy = evaluate_smoke_message("language_advice_first", message)
    else:
        nonempty = bool(message.strip())
        legacy = {
            "latest_turn_relevant": nonempty,
            "correction_acknowledged": True,
            "no_rejected_step_repeated": True,
            "answer_first": nonempty,
            "stale_path_abandoned": True,
        }
    return {
        "answers_current_input": legacy["latest_turn_relevant"],
        "acknowledges_user_correction": legacy["correction_acknowledged"],
        "avoids_repeating_completed_steps": legacy["no_rejected_step_repeated"],
        "avoids_rejected_path": legacy["no_rejected_step_repeated"],
        "answers_advice_before_procedure": legacy["answer_first"],
        "does_not_force_stale_teaching_path": legacy["stale_path_abandoned"],
    }


def run_real_provider_smoke(*, settings: Settings) -> TutorContextSmokeReport:
    if settings.llm_configuration_status != "configured":
        raise ValueError("Tutor real-provider smoke requires a complete provider configuration")
    policy = build_tutor_context_budget_policy(settings)
    planner = TutorContextBudgetPlanner()
    builder = TutorContextBuilder()
    gateway = PrimaryTutorProviderGateway(settings=settings)
    history: list[TutorContextSource] = []
    reports: list[dict[str, object]] = []
    total_attempts = 0
    for turn_index, current_input in enumerate(_TURNS, start=1):
        if turn_index > _MAX_TURNS:
            break
        run = TutorRunSnapshot(
            run_id=f"real-smoke-run-{turn_index}",
            conversation_id="real-smoke-conversation",
            user_id="real-smoke-user",
            origin="interactive",
            input_revision=1,
            policy=TutorPolicySnapshot(
                deadline=datetime.now(UTC) + timedelta(minutes=2),
                max_iterations=1,
                max_model_calls=1,
                context_token_budget=policy.capability.maximum_dynamic_target_tokens,
                context_budget_policy=policy,
            ),
        )
        context_input = TutorContextInput(
            run_id=run.run_id,
            conversation_id=run.conversation_id,
            input_revision=run.input_revision,
            current_input_required=True,
            current_input=TutorContextSource(f"current:{turn_index}", current_input),
            recent_messages=tuple(history),
        )
        selection = planner.build_context(
            run=run,
            context_input=context_input,
            builder=builder,
        )
        started = perf_counter()
        result = gateway.decide(run=run, context=selection)
        provider_latency_ms = max(0, round((perf_counter() - started) * 1000))
        total_attempts += len(result.attempts)
        if total_attempts > _MAX_PROVIDER_ATTEMPTS:
            raise RuntimeError("Tutor real-provider smoke attempt limit exceeded")
        usage_attempts = [attempt.usage for attempt in result.attempts if attempt.usage is not None]
        input_tokens = sum(usage.input_tokens or 0 for usage in usage_attempts) if usage_attempts else None
        cached_tokens = sum(usage.cached_input_tokens or 0 for usage in usage_attempts) if usage_attempts else None
        output_tokens = sum(usage.output_tokens or 0 for usage in usage_attempts) if usage_attempts else None
        cache_ratio = (
            cached_tokens / input_tokens
            if input_tokens is not None and input_tokens > 0 and cached_tokens is not None
            else None
        )
        public_message = (
            result.decision.public_message
            if result.decision is not None and result.decision.public_message is not None
            else None
        )
        rubric = evaluate_context_smoke_turn(turn_index, public_message or "")
        reports.append(
            {
                "turn_index": turn_index,
                "status": "completed" if public_message is not None else "unavailable",
                "public_message": public_message,
                "safe_code": result.safe_code,
                "budget_mode": (
                    selection.checkpoint_metadata.budget_mode.value
                    if selection.checkpoint_metadata.budget_mode is not None
                    else None
                ),
                "estimated_total_input_tokens": selection.checkpoint_metadata.estimated_total_input_tokens,
                "actual_input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "output_tokens": output_tokens,
                "cache_ratio": cache_ratio,
                "provider_latency_ms": provider_latency_ms,
                "attempt_count": len(result.attempts),
                "rubric": rubric,
            }
        )
        history.append(
            TutorContextSource(
                f"history:learner:{turn_index}",
                {"role": "user", "content": current_input},
            )
        )
        if public_message is not None:
            history.append(
                TutorContextSource(
                    f"history:tutor:{turn_index}",
                    {"role": "assistant", "content": public_message},
                )
            )
    passed = len(reports) == _MAX_TURNS and all(
        report["status"] == "completed"
        and isinstance(report["rubric"], dict)
        and all(bool(value) for value in report["rubric"].values())
        for report in reports
    )
    return TutorContextSmokeReport(
        status="passed" if passed else "failed",
        provider=settings.llm_provider_type,
        protocol=select_llm_protocol(settings).value,
        model=str(settings.llm_model or "unavailable"),
        executed_at=datetime.now(UTC).date().isoformat(),
        policy_version=policy.policy_version,
        turns=tuple(reports),
        total_provider_attempts=total_attempts,
    )


def main() -> int:
    if os.getenv(REAL_PROVIDER_SMOKE_ENV) != "1":
        print(json.dumps({"status": "disabled", "required_env": REAL_PROVIDER_SMOKE_ENV}))
        return 2
    settings = get_settings()
    if settings.llm_configuration_status != "configured":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "configuration_status": settings.llm_configuration_status,
                }
            )
        )
        return 2
    report = run_real_provider_smoke(settings=settings)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
