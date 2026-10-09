"""Fixed teaching profiles; expected outcomes are not execution evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.learning.item_supply.sandbox.contracts import ScenarioName, TerminalOutcome


@dataclass(frozen=True)
class ScenarioProfileV2:
    scenario: ScenarioName
    expected_outcome: TerminalOutcome
    assistance: Literal["none", "hint", "answer_request", "remediation"] = "none"
    replay: bool = False


SCENARIOS: tuple[ScenarioProfileV2, ...] = (
    ScenarioProfileV2("independent_correct", "correct"),
    ScenarioProfileV2("typical_error", "incorrect"),
    ScenarioProfileV2("partially_correct", "partial"),
    ScenarioProfileV2("equivalent_solution", "equivalent"),
    ScenarioProfileV2("boundary_ambiguity", "ambiguous"),
    ScenarioProfileV2("after_hint", "correct", assistance="hint"),
    ScenarioProfileV2("answer_request", "answer_requested", assistance="answer_request"),
    ScenarioProfileV2("after_remediation", "correct", assistance="remediation"),
    ScenarioProfileV2("refresh_replay", "correct", replay=True),
    ScenarioProfileV2("stale_scope", "stale_scope"),
    ScenarioProfileV2("provider_executor_failure", "executor_failed"),
)


def scenario_profile(scenario: ScenarioName) -> ScenarioProfileV2:
    for profile in SCENARIOS:
        if profile.scenario == scenario:
            return profile
    raise ValueError("sandbox scenario unavailable")
