"""Explicit new teaching admission only; current/source grants remain independent."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.agents.harness.contracts import (
    TutorContextBudgetPolicy, TutorExecutionProfile, TutorPolicySnapshot, TutorTerminalOutcome,
)

MVP_RUN_SECONDS = 2400
MVP_HTTP_SECONDS = 300
MVP_FINISH_RESERVE_SECONDS = 300
MVP_PHYSICAL_ATTEMPTS = 16
MVP_SOFT_CLOSE_AFTER = 6
MVP_SOFT_CLOSE_HINT = (
    "Server execution hint: six logical decisions are already complete. Prefer a coherent, "
    "bounded teaching segment, an answerable question, or a necessary clarification, then "
    "legally wait for the real learner. Do not force completion, answer your own question, "
    "claim mastery, or bypass any source/current/decision Gate. This is a soft hint only."
)


class MVPExecutionStopped(RuntimeError):
    def __init__(self, outcome: TutorTerminalOutcome, safe_code: str) -> None:
        super().__init__(safe_code)
        self.outcome = outcome
        self.safe_code = safe_code


def teaching_admission_policy(
    *, now: datetime, context_token_budget: int, context_budget_policy: TutorContextBudgetPolicy | None,
    execution_profile: TutorExecutionProfile | None = None,
) -> TutorPolicySnapshot:
    if execution_profile is not None and execution_profile is not TutorExecutionProfile.MVP_TEACHING_V1:
        raise ValueError("unsupported teaching execution profile")
    explicit = execution_profile is TutorExecutionProfile.MVP_TEACHING_V1
    return TutorPolicySnapshot(
        deadline=now + timedelta(seconds=MVP_RUN_SECONDS if explicit else 300),
        max_iterations=8 if explicit else 4, max_model_calls=8 if explicit else 3,
        max_capability_calls=6 if explicit else 2, max_effects=2,
        context_token_budget=context_token_budget, lease_duration_seconds=30,
        context_budget_policy=context_budget_policy, execution_profile=execution_profile,
    )
