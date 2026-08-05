"""Deterministic trusted-evidence to mastery-state projection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.learning.contracts import (
    MasteryEvidence,
    MasteryIndependence,
    MasteryLevel,
)


PROJECTOR_VERSION = "learning_mastery_v1"
_MAX_SUMMARY_ITEMS = 8


@dataclass(frozen=True, slots=True)
class MasteryProjection:
    knowledge_key: str
    confidence: float
    mastery_level: MasteryLevel
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    evidence_count: int
    last_evidence_id: str | None
    projector_version: str = PROJECTOR_VERSION


class MasteryProjector:
    """Project only persisted, trusted evidence summaries; no model text is accepted directly."""

    def project(self, *, knowledge_key: str, evidence: Sequence[MasteryEvidence]) -> MasteryProjection:
        scoped = tuple(item for item in evidence if item.knowledge_key == knowledge_key)
        if not scoped:
            return MasteryProjection(
                knowledge_key=knowledge_key,
                confidence=0.0,
                mastery_level=MasteryLevel.UNSEEN,
                strengths=(),
                weaknesses=(),
                evidence_count=0,
                last_evidence_id=None,
            )

        weighted_total = 0.0
        weight_total = 0.0
        independent_count = 0
        strength_counts: dict[str, int] = {}
        weakness_counts: dict[str, int] = {}
        for item in scoped:
            weight = _independence_weight(item.independence)
            weighted_total += item.score * weight
            weight_total += weight
            independent_count += int(item.independence is MasteryIndependence.INDEPENDENT)
            _merge_summary_terms(strength_counts, item.summary, key="strengths")
            _merge_summary_terms(weakness_counts, item.summary, key="weaknesses")

        score = weighted_total / weight_total if weight_total else 0.0
        evidence_factor = min(1.0, len(scoped) / 4)
        independence_factor = 0.75 + 0.25 * (independent_count / len(scoped))
        confidence = round(max(0.0, min(1.0, score * evidence_factor * independence_factor)), 4)
        return MasteryProjection(
            knowledge_key=knowledge_key,
            confidence=confidence,
            mastery_level=_mastery_level(confidence=confidence, evidence_count=len(scoped), independent_count=independent_count),
            strengths=_rank_terms(strength_counts),
            weaknesses=_rank_terms(weakness_counts),
            evidence_count=len(scoped),
            last_evidence_id=scoped[-1].evidence_id,
        )


def _independence_weight(independence: MasteryIndependence) -> float:
    return {
        MasteryIndependence.INDEPENDENT: 1.0,
        MasteryIndependence.HINTED: 0.72,
        MasteryIndependence.REMEDIATED: 0.58,
    }[independence]


def _mastery_level(*, confidence: float, evidence_count: int, independent_count: int) -> MasteryLevel:
    if evidence_count == 0:
        return MasteryLevel.UNSEEN
    if confidence < 0.25:
        return MasteryLevel.EMERGING
    if confidence < 0.55:
        return MasteryLevel.DEVELOPING
    if confidence < 0.8 or independent_count < 2:
        return MasteryLevel.PROFICIENT
    return MasteryLevel.DURABLE


def _merge_summary_terms(target: dict[str, int], summary: Mapping[str, object], *, key: str) -> None:
    raw = summary.get(key)
    if not isinstance(raw, list | tuple):
        return
    for item in raw[:_MAX_SUMMARY_ITEMS]:
        term = str(item or "").strip()
        if not term or len(term) > 160:
            continue
        target[term] = target.get(term, 0) + 1


def _rank_terms(counts: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(item for item, _count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:_MAX_SUMMARY_ITEMS])
