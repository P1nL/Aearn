"""Concrete finite KC blind scorer: static exact, no OS or answer-key projection."""
from __future__ import annotations

from datetime import UTC, datetime
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import FiniteKcValidationFactsV1, prepare_finite_candidate_validation
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import BlindScoreV2, CandidateBindingV2, check_subject
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.practice.contracts import ExerciseAttemptOutcome
from app.services.learning.practice.policies import evaluate_static_reasoning


class FiniteStaticBlindScorer:
    def __init__(self, *, binding: CandidateBindingV2, spec: FiniteCandidateSpecV1,
                 materials: tuple[PublicMaterialV2, ...]) -> None:
        self.binding = checked_model(binding, CandidateBindingV2)
        self.spec = checked_model(spec, FiniteCandidateSpecV1)
        self.materials = tuple(checked_model(m, PublicMaterialV2) for m in materials)
        self._issued: dict[str, tuple[BlindScoreV2, str, str]] = {}

    def _facts(self, source: LearningItemSourceV1) -> FiniteKcValidationFactsV1:
        source = checked_model(source, LearningItemSourceV1)
        check_subject(source, self.binding)
        facts = prepare_finite_candidate_validation(source, spec=self.spec, materials=self.materials).static_facts
        if facts is None or self.spec.target_id != "python-kc-binding-v1":
            raise ValueError("finite_static_blind_context_required")
        return facts

    def resource_plan(self, source: LearningItemSourceV1) -> ResourceAmounts:
        self._facts(source)
        return ResourceAmounts()

    def _score(self, source: LearningItemSourceV1, answer: str) -> BlindScoreV2:
        facts = self._facts(source)
        if type(answer) is not str or not 1 <= len(answer) <= 48000:
            raise ValueError("finite_static_blind_answer_invalid")
        evaluated = evaluate_static_reasoning(answer=answer, accepted_answers=(facts.correct_option_id,),
            required_capabilities=source.blueprint.required_capabilities, threshold=1.0, now=datetime.now(UTC))
        passed = evaluated.outcome is ExerciseAttemptOutcome.PASSED
        digest = canonical_hash({"binding": self.binding.model_dump(mode="json"),
            "source_hash": source.source_hash, "specification_hash": self.spec.specification_hash,
            "static_facts_hash": canonical_hash(facts.model_dump(mode="json")),
            "solution_hash": canonical_hash(answer), "passed": passed})
        return BlindScoreV2(passed=passed, scorer_identity="finite-static-blind-scorer",
                            scorer_version=facts.scorer_version, receipt_hash=digest)

    def score(self, source: LearningItemSourceV1, *, answer: str) -> BlindScoreV2:
        if self._issued:
            previous = next(iter(self._issued.values()))
            if previous[1:] != (source.source_hash, answer):
                raise ValueError("finite_static_blind_answer_allowance_spent")
        result = self._score(source, answer)
        self._issued[result.receipt_hash] = (result, source.source_hash, answer)
        return result

    def verify(self, score: BlindScoreV2, source: LearningItemSourceV1) -> bool:
        try:
            score = checked_model(score, BlindScoreV2)
            issued = self._issued.get(score.receipt_hash)
            return (issued is not None and issued[0] == score and issued[1] == source.source_hash
                    and self._score(source, issued[2]) == score)
        except (ValueError, TypeError, AttributeError):
            return False
