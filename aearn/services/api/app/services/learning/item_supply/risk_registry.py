"""Default-deny registry: no adapters imply no high-risk autonomy."""
from __future__ import annotations

from typing import Protocol

from app.services.learning.item_bank.contracts import LearningItemCodeContentV1, LearningItemKind, LearningItemSourceV1
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2, RiskEvidenceV2
from app.services.learning.item_supply.storage_contracts import checked_model


class RiskAdapterPortV2(Protocol):
    @property
    def risk(self) -> str: ...

    @property
    def version(self) -> str: ...

    def verifies(self, binding: CandidateBindingV2, evidence: RiskEvidenceV2) -> bool: ...


class RiskAdapterRegistry:
    def __init__(self, adapters: tuple[RiskAdapterPortV2, ...] = ()) -> None:
        self._adapters = {adapter.risk: adapter for adapter in adapters}
        if len(self._adapters) != len(adapters):
            raise ValueError("duplicate risk adapter registration")

    def verifies(self, binding: CandidateBindingV2, evidence: RiskEvidenceV2) -> bool:
        try:
            binding = checked_model(binding, CandidateBindingV2)
            evidence = checked_model(evidence, RiskEvidenceV2)
            adapter = self._adapters.get(evidence.risk)
            return (adapter is not None and adapter.version == evidence.adapter_version
                    and adapter.verifies(binding, evidence) is True)
        except Exception:
            return False


def required_critical_risks(source: LearningItemSourceV1) -> tuple[str, ...]:
    source = checked_model(source, LearningItemSourceV1)
    risks = {"source_security", "privacy"}
    if source.public.kind is LearningItemKind.SQL:
        risks.add("sql")
    elif source.public.kind is LearningItemKind.CODE:
        content = source.public.content
        risks.add("browser_preview" if isinstance(content, LearningItemCodeContentV1)
                  and content.exercise_type == "browser_preview" else "code_execution")
    elif source.public.kind is LearningItemKind.DEMO:
        risks.add("browser_preview")
    elif source.public.kind is LearningItemKind.MODEL_REVIEW:
        risks.add("model_review")
    return tuple(sorted(risks))
