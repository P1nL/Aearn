"""Offline B1 qualification/projection port checks; no C/PG/provider is implied."""
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.contracts import SourceDiscoverySuggestion
from app.services.grounding.autonomous.qualified_corpus import (
    QualificationSnapshot, QualifiedCorpusAdapter, QualifiedDocument,
)
from app.services.grounding.autonomous.query_projection import (
    ServerQueryProjectionResolver, TrustedQueryContext,
)
from tests.grounding.rag_material_helpers import Sources, assessment, demand


class CorpusAuthority:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    def resolve(self, full):
        self.calls += 1
        return self.snapshot


class QueryAuthority:
    def __init__(self, context):
        self.context = context
        self.calls = 0

    def resolve(self, full):
        self.calls += 1
        return self.context


def doc(**changes):
    source = Sources().resolve("source.blog", "document.001")
    base = QualifiedDocument(assessment=assessment(), authorization=source,
                             covered_facets=("syntax",))
    return base.model_copy(update=changes)


def snapshot(*documents, **changes):
    base = QualificationSnapshot(
        demand=demand(), receipt_id="qualification.001", corpus_id=uuid4(),
        subject_id="route.python", subject_version="3.12", active=True,
        state="published", synthetic_fixture=False, documents=documents,
    )
    return base.model_copy(update=changes)


def suggestion(**changes):
    base = SourceDiscoverySuggestion(demand_hash=demand().demand_hash,
                                     query_terms=("private.user.001",), reason="coverage_gap")
    return base.model_copy(update=changes)


def context(**changes):
    base = TrustedQueryContext(demand=demand(), approved_facets=("syntax",),
                               receipt_id="query.context.001", authorized=True)
    return base.model_copy(update=changes)


def test_no_c_authority_or_unavailable_snapshot_is_unknown():
    assert QualifiedCorpusAdapter(None).assess(demand()) is None
    assert QualifiedCorpusAdapter(CorpusAuthority(None)).assess(demand()) is None


def test_current_exact_admission_with_coverage_and_readability_is_sufficient():
    result = QualifiedCorpusAdapter(CorpusAuthority(snapshot(doc()))).assess(demand())
    assert result is not None
    assert result.status == "sufficient"
    assert result.receipt_id == "qualification.001"


@pytest.mark.parametrize("changes", [
    {"active": False}, {"state": "validated"}, {"synthetic_fixture": True},
    {"subject_id": "route.sql"}, {"demand": demand().model_copy(update={"node_ref": "node.002"})},
])
def test_phase_i_published_or_stale_scope_cannot_claim_ready(changes):
    assert QualifiedCorpusAdapter(CorpusAuthority(snapshot(doc(), **changes))).assess(demand()) is None


def test_version_and_missing_coverage_are_explicit_gaps_not_ready():
    adapter = QualifiedCorpusAdapter(CorpusAuthority(snapshot(doc(), subject_version="3.11")))
    assert adapter.assess(demand()).gap_reason == "version_stale"
    assert QualifiedCorpusAdapter(CorpusAuthority(snapshot())).assess(demand()).gap_reason == "coverage_gap"


@pytest.mark.parametrize("assessment_change,authorization_change,document_change,reason", [
    ({"reading_level": "advanced"}, {"reading_level": "advanced"}, {}, "reading_level"),
    ({}, {"revoked": True}, {}, "coverage_gap"),
    ({}, {"readable": False}, {}, "coverage_gap"),
    ({}, {"reviewed": False}, {}, "coverage_gap"),
    ({}, {"document_revision": "v2"}, {}, "coverage_gap"),
    ({}, {"policy_generation": 3}, {}, "coverage_gap"),
    ({}, {"admission_receipt_id": "admission.002"}, {}, "coverage_gap"),
    ({}, {}, {"unresolved_conflict": True}, "conflict"),
    ({"allowed_usages": ("supplementary_explanation",)},
     {"allowed_usages": ("supplementary_explanation",)}, {}, "coverage_gap"),
])
def test_current_authority_version_purpose_readability_conflict_and_revocation(
    assessment_change, authorization_change, document_change, reason,
):
    base = doc()
    changed = base.model_copy(update={
        "assessment": base.assessment.model_copy(update=assessment_change),
        "authorization": base.authorization.model_copy(update=authorization_change),
        **document_change,
    })
    result = QualifiedCorpusAdapter(CorpusAuthority(snapshot(changed))).assess(demand())
    assert result is not None and result.status == "gap" and result.gap_reason == reason


def test_invalid_nested_copy_and_authority_failure_fail_closed():
    malformed = doc().model_copy(update={"covered_facets": ("other",)})
    assert QualifiedCorpusAdapter(CorpusAuthority(
        snapshot(doc()).model_copy(update={"documents": (malformed,)})
    )).assess(demand()) is None

    class Broken:
        def resolve(self, full):
            raise RuntimeError("private details")

    assert QualifiedCorpusAdapter(Broken()).assess(demand()) is None


def test_projection_uses_only_server_taxonomy_and_language_not_model_text():
    authority = QueryAuthority(context())
    terms = ServerQueryProjectionResolver(authority).project(demand(), suggestion())
    assert terms == ("Python", "syntax", "中文 教程")
    assert "private" not in " ".join(terms)
    assert authority.calls == 1
    english = demand().model_copy(update={"language": "en"})
    authority.context = context(demand=english)
    assert ServerQueryProjectionResolver(authority).project(english, suggestion()) == (
        "Python", "syntax", "English tutorial",
    )


def test_projection_requires_current_full_demand_and_approved_scope():
    assert ServerQueryProjectionResolver(None).project(demand(), suggestion()) is None
    authority = QueryAuthority(None)
    projector = ServerQueryProjectionResolver(authority)
    assert projector.project(demand(), suggestion()) is None
    assert projector.project(demand(), suggestion(demand_hash="b" * 64)) is None
    assert authority.calls == 1
    for changed in (
        {"authorized": False}, {"approved_facets": ("functions",)},
        {"demand": demand().model_copy(update={"node_ref": "node.002"})},
    ):
        authority.context = context(**changed)
        assert projector.project(demand(), suggestion()) is None


def test_projection_revalidates_nested_bypass_and_closes_resolver_exception():
    authority = QueryAuthority(context(demand=demand().model_copy(update={"language": "secret"})))
    assert ServerQueryProjectionResolver(authority).project(demand(), suggestion()) is None

    class Broken:
        def resolve(self, full):
            raise RuntimeError("private conversation")

    assert ServerQueryProjectionResolver(Broken()).project(demand(), suggestion()) is None


def test_phase_i_pointer_and_search_suggestion_are_not_c_admission():
    from app.services.grounding.corpus_contracts import ActiveCorpus

    pointer = ActiveCorpus(subject_id="route.python", corpus_id=uuid4(),
                           generation=1, activation_event_id=uuid4())
    assert QualifiedCorpusAdapter(CorpusAuthority(pointer)).assess(demand()) is None
    assert QualifiedCorpusAdapter(CorpusAuthority(suggestion())).assess(demand()) is None
