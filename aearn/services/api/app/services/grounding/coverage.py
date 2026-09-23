"""Deterministic evidence selection and resource coverage, not learner mastery."""
from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from app.services.grounding.retrieval_contracts import (
    CoverageReport, CoverageStatus, GroundingRetrievalPlan, GroundingRetrievalRequest,
    ReasonCode, RetrievalCandidate, SelectedGroundingEvidence, stable_hash,
)


def _tokens(text: str) -> int:
    # Conservative deterministic upper estimate. Never use a provider token counter.
    return max(1, len(text.encode("utf-8")))


def unavailable_report(request: GroundingRetrievalRequest, code: ReasonCode) -> CoverageReport:
    fields: dict[str, object] = {
        "request_hash": stable_hash(request.model_dump(mode="json")),
        "corpus_summary_hash": None, "registry_digest": None,
        "status": "unavailable", "subject_id": request.subject_id,
        "subject_version": request.subject_version, "corpus_id": None,
        "required_facets": request.required_facets, "covered_facets": (),
        "missing_facets": request.required_facets, "source_count": 0, "trust_tiers": (),
        "freshness_state": "stale" if code == "CORPUS_STALE" else "unavailable",
        "version_state": "mismatch" if code == "VERSION_MISMATCH" else "unavailable",
        "budget_state": "unavailable", "used_characters": 0,
        "used_estimated_tokens": 0, "used_chunks": 0, "reason_codes": (code,),
    }
    return CoverageReport.model_validate({**fields, "report_hash": stable_hash(fields)})


def select_evidence(
    plan: GroundingRetrievalPlan, candidates: Sequence[RetrievalCandidate], *,
    embedding_unavailable: bool = False,
) -> tuple[tuple[SelectedGroundingEvidence, ...], CoverageReport]:
    selected: list[SelectedGroundingEvidence] = []
    covered: set[str] = set()
    sources: set[str] = set()
    remaining = list(candidates)
    chars = tokens = 0
    budget_blocked = False
    while remaining and (len(covered) < len(plan.required_facets)
                         or len(sources) < plan.minimum_source_diversity):
        if len(selected) >= plan.budget.max_chunks:
            budget_blocked = True
            break
        # Preserve RRF within equivalent facet/trust/diversity priorities.
        remaining.sort(key=lambda item: (
            -len(set(item.facets) & (set(plan.required_facets) - covered)),
            0 if item.trust_tier == "official" else 1,
            0 if item.source_id not in sources else 1,
            _rrf_key(item), item.source_id, item.chunk_id,
        ))
        candidate = remaining.pop(0)
        relevant = set(candidate.facets) & set(plan.required_facets)
        needed = relevant - covered
        novel_source = candidate.source_id not in sources
        # Optional-only content cannot satisfy required evidence diversity.
        if not relevant or (not needed and (not novel_source or len(sources) >= plan.minimum_source_diversity)):
            continue
        char_count = len(candidate.content)
        token_count = _tokens(candidate.content)
        if chars + char_count > plan.budget.max_characters or tokens + token_count > plan.budget.max_estimated_tokens:
            budget_blocked = True
            continue
        selected.append(SelectedGroundingEvidence(
            **candidate.model_dump(exclude={"fts_rank", "embedding_rank"}),
            estimated_tokens=token_count,
        ))
        covered.update(set(candidate.facets) & set(plan.required_facets))
        sources.add(candidate.source_id)
        chars += char_count
        tokens += token_count
    missing = tuple(facet for facet in plan.required_facets if facet not in covered)
    reasons: list[ReasonCode] = []
    if missing:
        reasons.append("FACET_MISSING")
    if len(sources) < plan.minimum_source_diversity:
        reasons.append("SOURCE_DIVERSITY_LOW")
    if budget_blocked:
        reasons.append("BUDGET_EXHAUSTED")
    if embedding_unavailable:
        reasons.append("EMBEDDING_UNAVAILABLE")
    status: CoverageStatus = (
        "satisfied" if not missing and len(sources) >= plan.minimum_source_diversity
        else "partial" if selected else "insufficient"
    )
    fields: dict[str, object] = {
        "request_hash": plan.request_hash, "corpus_summary_hash": plan.corpus_summary_hash,
        "registry_digest": plan.registry_digest,
        "status": status, "subject_id": plan.subject_id, "subject_version": plan.subject_version,
        "corpus_id": plan.corpus_id, "required_facets": plan.required_facets,
        "covered_facets": tuple(f for f in plan.required_facets if f in covered),
        "missing_facets": missing, "source_count": len(sources),
        "trust_tiers": tuple(sorted({item.trust_tier for item in selected})),
        "freshness_state": "current", "version_state": "exact",
        "budget_state": "exhausted" if budget_blocked else "within",
        "used_characters": chars, "used_estimated_tokens": tokens,
        "used_chunks": len(selected), "reason_codes": tuple(reasons),
    }
    return tuple(selected), CoverageReport.model_validate({**fields, "report_hash": stable_hash(fields)})


def _rrf_key(candidate: RetrievalCandidate) -> Fraction:
    a = candidate.fts_rank
    b = candidate.embedding_rank
    return -(Fraction(1, 60 + a) if a is not None else Fraction(0)
             ) - (Fraction(1, 60 + b) if b is not None else Fraction(0))
