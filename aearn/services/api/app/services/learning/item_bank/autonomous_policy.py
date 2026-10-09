"""Additive v2 skeleton; never relaxes or writes legacy v1 receipts."""
from __future__ import annotations

from app.services.learning.item_supply.storage_contracts import (
    AdmissionDecisionV2,
    AutonomousEvidencePolicyV2,
    checked_model,
)


def evaluate_autonomous_admission(
    policy: AutonomousEvidencePolicyV2, *, admission_key: str, enabled: bool = False,
) -> AdmissionDecisionV2:
    checked_model(policy, AutonomousEvidencePolicyV2)
    # P2 persists policy/evidence identity only. Even with the switch enabled,
    # absent trusted risk/review/execution resolvers can never authorize release.
    return AdmissionDecisionV2(
        admission_key=admission_key,
        decision="evidence_pending" if enabled else "blocked",
        safe_reason="trusted_adapters_pending" if enabled else "feature_disabled",
    )
