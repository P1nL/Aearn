"""Coverage is resource evidence, not lesson mastery or source authorization."""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.services.grounding.coverage import select_evidence
from app.services.grounding.retrieval_contracts import (
    ActiveCorpusSelector, EvidenceBudgetPolicy, GroundingRetrievalPlan,
    GroundingRetrievalRequest, RetrievalCandidate,
)


def _plan(*, max_chunks: int = 3, max_characters: int = 100,
          max_estimated_tokens: int = 100) -> GroundingRetrievalPlan:
    return GroundingRetrievalPlan(
        request_hash="r", plan_hash="p", subject_id="web.react", subject_version="fixture-v1",
        corpus_id=uuid4(), corpus_summary_hash="s", corpus_content_hash="c", registry_digest="d",
        retrieval_policy_version="fixture-fts-v1", coverage_policy_version="fixture-facets-v1",
        stage="plan_preflight", required_facets=("components", "state"), optional_facets=(),
        allowed_source_ids=("first", "second"), allowed_trust_tiers=("official",),
        minimum_source_diversity=2, synthetic_fixture=True,
        budget=EvidenceBudgetPolicy(max_chunks=max_chunks, max_characters=max_characters,
                                    max_estimated_tokens=max_estimated_tokens,
                                    per_facet_limit=3, per_channel_limit=6),
    )


def _candidate(chunk: str, facet: str, source: str, rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk, source_id=source, document_id=f"doc-{chunk}", title="Synthetic",
        section_path=facet, content=f"{facet} test", facets=(facet,), trust_tier="official",
        source_hash="0" * 64, document_hash="1" * 64, chunk_hash="2" * 64, fts_rank=rank,
    )


def test_facets_and_diversity_both_required() -> None:
    plan = _plan()
    candidates = (_candidate("1", "components", "first", 1),
                  _candidate("2", "state", "first", 2))
    _, partial = select_evidence(plan, candidates)
    assert partial.status == "partial" and partial.missing_facets == ()
    assert partial.reason_codes == ("SOURCE_DIVERSITY_LOW",)
    selected, satisfied = select_evidence(plan, (*candidates, _candidate("3", "state", "second", 3)))
    assert satisfied.status == "satisfied" and satisfied.source_count == 2
    assert satisfied.report_hash == select_evidence(plan, (*candidates, _candidate("3", "state", "second", 3)))[1].report_hash
    assert len(selected) == 2


def test_budget_exhaustion_and_missing_facets() -> None:
    candidates = (_candidate("1", "components", "first", 1),
                  _candidate("2", "state", "second", 2))
    selected, report = select_evidence(_plan(max_chunks=1), candidates)
    assert len(selected) == 1 and report.status == "partial"
    assert report.budget_state == "exhausted" and "BUDGET_EXHAUSTED" in report.reason_codes
    empty, insufficient = select_evidence(_plan(max_characters=1, max_estimated_tokens=1), candidates)
    assert empty == () and insufficient.status == "insufficient"
    assert insufficient.missing_facets == ("components", "state")


def test_request_is_closed_and_extra_forbidden() -> None:
    data = dict(subject_id="web.react", subject_version="fixture-v1",
                corpus_selector=ActiveCorpusSelector(), query_text="React state",
                required_facets=("components",), stage="review")
    assert GroundingRetrievalRequest(**data).required_facets == ("components",)
    for changes in ({"required_facets": ("unknown",)}, {"required_facets": ()},
                    {"stage": "generation"}, {"budget_profile": "unbounded"},
                    {"source_url": "https://example.org"}):
        with pytest.raises(ValidationError):
            GroundingRetrievalRequest.model_validate(data | changes)
