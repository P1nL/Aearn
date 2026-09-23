"""Disposable-DB exact-scope and synthetic augmentation checks."""
from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.grounding.corpus_service import CorpusService
from app.services.grounding.corpus_repository import CorpusRepository
from app.services.grounding.hybrid_retrieval import (
    DeterministicFakeEmbeddingRetriever, EmbeddingCandidate, SyntheticEmbeddingConfig,
    retrieve_grounding_v2, synthetic_embedding_receipt,
)
from app.services.grounding.retrieval_contracts import (
    ActiveCorpusSelector, ExactCorpusSelector, GroundingRetrievalRequest,
)


@pytest.fixture(scope="module", autouse=True)
def isolated_bootstrap() -> None:
    name = urlsplit(get_settings().database_url).path.lstrip("/")
    if not name.startswith("aearn_rag260_cli_retrieval_"):
        pytest.skip("requires the exclusively assigned retrieval database")
    bootstrap_database()


@pytest.fixture()
def published(isolated_bootstrap: None):  # type: ignore[no-untyped-def]
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        conn.execute("SELECT 1")  # Hold the outer rollback; service writes use savepoints.
        service = CorpusService(conn)
        def build(subject: str) -> tuple[UUID, str]:
            key = uuid4().hex
            created = service.reindex(subject, "fixture-v1", mode="fixture", idempotency_key=key)
            corpus_id = UUID(str(created["corpus_id"]))
            checked = service.validate(corpus_id, expected_generation=0, idempotency_key=f"v-{key}")
            summary = str(checked["summary_hash"])
            service.activate(corpus_id, expected_generation=0, summary_hash=summary, idempotency_key=f"a-{key}")
            return corpus_id, summary
        yield conn, service, build
        conn.rollback()


def _request(subject: str, facets: tuple[str, ...], selector: ActiveCorpusSelector | ExactCorpusSelector,
             *, stage: str = "lesson_authoring", mode: str = "disabled", profile: str = "standard") -> GroundingRetrievalRequest:
    return GroundingRetrievalRequest.model_validate({
        "subject_id": subject, "subject_version": "fixture-v1", "corpus_selector": selector,
        "query_text": "synthetic concept", "required_facets": facets, "stage": stage,
        "budget_profile": profile, "embedding_mode": mode,
    })


def test_fts_exact_scope_repeatable_and_variable_plan(published) -> None:  # type: ignore[no-untyped-def]
    conn, _, build = published
    fastapi_id, fastapi_hash = build("python.fastapi")
    build("route.python")
    simple = _request("python.fastapi", ("http",), ActiveCorpusSelector())
    complex_request = _request("python.fastapi", ("http", "routing", "validation"), ActiveCorpusSelector())
    a = retrieve_grounding_v2(conn, simple)
    b = retrieve_grounding_v2(conn, simple)
    complex_result = retrieve_grounding_v2(conn, complex_request)
    assert a == b and a.coverage.status == "satisfied"
    assert a.plan and complex_result.plan
    assert a.plan.budget.max_chunks < complex_result.plan.budget.max_chunks
    assert complex_result.coverage.status == "satisfied"
    assert set(complex_result.coverage.covered_facets) == {"http", "routing", "validation"}
    assert complex_result.coverage.source_count >= 2
    assert all(item.source_id.startswith("fixture.python.fastapi.") for item in complex_result.evidence)
    assert complex_result.coverage.report_hash == retrieve_grounding_v2(conn, complex_request).coverage.report_hash
    pinned = _request("python.fastapi", ("http",), ExactCorpusSelector(corpus_id=fastapi_id,
                                                                           expected_summary_hash=fastapi_hash))
    assert retrieve_grounding_v2(conn, pinned).coverage.status == "satisfied"
    assert retrieve_grounding_v2(conn, _request("route.python", ("syntax",),
        ExactCorpusSelector(corpus_id=fastapi_id, expected_summary_hash=fastapi_hash))).coverage.reason_codes == ("VERSION_MISMATCH",)
    assert retrieve_grounding_v2(conn, _request("python.fastapi", ("http",),
        ExactCorpusSelector(corpus_id=fastapi_id, expected_summary_hash="0" * 64))).coverage.reason_codes == ("CORPUS_STALE",)


def test_wrong_version_unpublished_and_retired_fail_closed(published) -> None:  # type: ignore[no-untyped-def]
    conn, service, build = published
    corpus_id, summary = build("web.react")
    wrong = _request("web.react", ("components",), ActiveCorpusSelector()).model_copy(update={"subject_version": "v2"})
    assert retrieve_grounding_v2(conn, wrong).coverage.reason_codes == ("VERSION_MISMATCH",)
    new = service.reindex("web.react", "fixture-v1", mode="fixture", idempotency_key=uuid4().hex)
    unvalidated_id = UUID(str(new["corpus_id"]))
    exact = ExactCorpusSelector(corpus_id=unvalidated_id, expected_summary_hash=summary)
    assert retrieve_grounding_v2(conn, _request("web.react", ("components",), exact)).coverage.reason_codes == ("CORPUS_UNPUBLISHED",)
    assert retrieve_grounding_v2(conn, _request("web.react", ("components",),
        ActiveCorpusSelector(expected_generation=2))).coverage.reason_codes == ("CORPUS_STALE",)
    service.retire(unvalidated_id, idempotency_key=uuid4().hex)
    assert retrieve_grounding_v2(conn, _request("web.react", ("components",), exact)).coverage.reason_codes == ("CORPUS_RETIRED",)
    assert retrieve_grounding_v2(conn, _request("web.react", ("components",),
        ExactCorpusSelector(corpus_id=corpus_id, expected_summary_hash=summary))).coverage.status == "satisfied"


def test_synthetic_embedding_revalidated_and_fallback(published) -> None:  # type: ignore[no-untyped-def]
    conn, _, build = published
    corpus_id, _ = build("python.fastapi")
    request = _request("python.fastapi", ("http", "routing", "validation"), ActiveCorpusSelector(), mode="optional")
    baseline = retrieve_grounding_v2(conn, request)
    assert baseline.coverage.status == "satisfied" and "EMBEDDING_UNAVAILABLE" in baseline.coverage.reason_codes
    assert baseline.plan
    config = SyntheticEmbeddingConfig(model_id="fake-v1", dimension=3, normalization_version="unit-v1")
    row = conn.execute("SELECT chunk_id,chunk_hash FROM grounding_corpus_chunks WHERE corpus_version_id=%s AND facets_json ? %s",
                       (corpus_id, "validation")).fetchone()
    assert row is not None
    valid = EmbeddingCandidate(corpus_id=corpus_id, chunk_id=row["chunk_id"], chunk_hash=row["chunk_hash"],
                               synthetic_receipt=synthetic_embedding_receipt(baseline.plan, config),
                               model_id=config.model_id, dimension=config.dimension,
                               normalization_version=config.normalization_version)
    augmented = retrieve_grounding_v2(conn, request,
        embedding=DeterministicFakeEmbeddingRetriever((valid,)), synthetic_config=config)
    assert augmented.coverage.status == "satisfied"
    assert "EMBEDDING_UNAVAILABLE" not in augmented.coverage.reason_codes
    for bad in (valid.model_copy(update={"dimension": 4}),
                valid.model_copy(update={"corpus_id": uuid4()}),
                valid.model_copy(update={"chunk_hash": "0" * 64}),
                valid.model_copy(update={"synthetic_receipt": "0" * 64})):
        degraded = retrieve_grounding_v2(conn, request,
            embedding=DeterministicFakeEmbeddingRetriever((bad,)), synthetic_config=config)
        assert degraded.coverage.status == baseline.coverage.status
        assert degraded.coverage.covered_facets == baseline.coverage.covered_facets
        assert degraded.evidence == baseline.evidence
        assert degraded.coverage.report_hash == baseline.coverage.report_hash
    other_id, _ = build("route.python")
    wrong_scope = valid.model_copy(update={"chunk_id": row["chunk_id"], "corpus_id": other_id})
    assert retrieve_grounding_v2(conn, request,
        embedding=DeterministicFakeEmbeddingRetriever((wrong_scope,)), synthetic_config=config).evidence == baseline.evidence


def test_framework_does_not_fallback_to_base_language(published) -> None:  # type: ignore[no-untyped-def]
    conn, _, build = published
    build("route.python")
    absent = _request("python.fastapi", ("http",), ActiveCorpusSelector())
    assert retrieve_grounding_v2(conn, absent).coverage.reason_codes == ("CORPUS_MISSING",)
    build("python.fastapi")
    invalid = absent.model_copy(update={"required_facets": ("fundamentals",)})
    assert retrieve_grounding_v2(conn, invalid).coverage.reason_codes == ("FACET_INVALID",)


def test_registry_drift_and_embedding_scope_denied(published, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    conn, _, build = published
    build("python.fastapi")
    other_id, _ = build("route.python")
    request = _request("python.fastapi", ("http", "routing", "validation"), ActiveCorpusSelector(), mode="optional")
    baseline = retrieve_grounding_v2(conn, request)
    assert baseline.plan
    config = SyntheticEmbeddingConfig(model_id="fake-v1", dimension=3, normalization_version="unit-v1")
    other = conn.execute("SELECT chunk_id,chunk_hash FROM grounding_corpus_chunks WHERE corpus_version_id=%s LIMIT 1",
                         (other_id,)).fetchone()
    assert other is not None
    forged = EmbeddingCandidate(corpus_id=baseline.plan.corpus_id, chunk_id=other["chunk_id"],
        chunk_hash=other["chunk_hash"], synthetic_receipt=synthetic_embedding_receipt(baseline.plan, config),
        model_id=config.model_id, dimension=config.dimension, normalization_version=config.normalization_version)
    denied = retrieve_grounding_v2(conn, request,
        embedding=DeterministicFakeEmbeddingRetriever((forged,)), synthetic_config=config)
    assert denied.evidence == baseline.evidence
    assert denied.coverage.covered_facets == baseline.coverage.covered_facets

    from app.services.grounding import retrieval_planner
    from app.services.grounding.subject_registry import get_grounding_subject
    subject = get_grounding_subject("python.fastapi")
    assert subject is not None
    original = retrieval_planner.get_grounding_subject
    monkeypatch.setattr(retrieval_planner, "get_grounding_subject",
                        lambda name: subject.model_copy(update={"display_name": "Changed"}) if name == subject.subject_id else original(name))
    stale = retrieve_grounding_v2(conn, request)
    assert stale.coverage.status == "unavailable"
    assert stale.coverage.reason_codes == ("CORPUS_STALE",)


def test_copied_fixture_digest_does_not_authorize_extra_source(published) -> None:  # type: ignore[no-untyped-def]
    conn, service, _ = published
    created = service.reindex("python.fastapi", "fixture-v1", mode="fixture", idempotency_key=uuid4().hex)
    corpus_id = UUID(str(created["corpus_id"]))
    # Low-level publication can seal a source not present in the fixture registry.
    # The old joined-subset check ignored sources without parsed chunks.
    conn.execute(
        """INSERT INTO grounding_corpus_source_snapshots
           (corpus_version_id,subject_id,subject_version,source_id,source_hash,trust_tier,
            source_kind,source_version,allowed_domains_json,seed_urls_json,facets_json)
           SELECT corpus_version_id,subject_id,subject_version,'fixture.python.fastapi.extra',
                  source_hash,trust_tier,source_kind,source_version,allowed_domains_json,
                  seed_urls_json,facets_json
           FROM grounding_corpus_source_snapshots WHERE corpus_version_id=%s LIMIT 1""",
        (corpus_id,),
    )
    repo = CorpusRepository(conn)
    sealed = repo.finalize_validation(
        corpus_id, passed=True, expected_generation=0,
        validation_summary={"passed": True}, coverage_summary={"fixture_only": True},
        idempotency_key=uuid4().hex,
    )
    assert sealed.summary_hash is not None
    repo.activate(corpus_id, expected_generation=0, summary_hash=sealed.summary_hash,
                  idempotency_key=uuid4().hex)
    result = retrieve_grounding_v2(conn, _request("python.fastapi", ("http",), ActiveCorpusSelector()))
    assert result.evidence == () and result.coverage.reason_codes == ("CORPUS_STALE",)


def test_malformed_adapter_runtime_error_degrades_to_fts(published) -> None:  # type: ignore[no-untyped-def]
    conn, _, build = published
    build("python.fastapi")
    request = _request("python.fastapi", ("http",), ActiveCorpusSelector(), mode="optional")
    baseline = retrieve_grounding_v2(conn, request)

    class ExplodingCandidate:
        @property
        def chunk_id(self) -> str:
            raise RuntimeError("invalid adapter attribute")

    class MalformedAdapter:
        def search(self, request):  # type: ignore[no-untyped-def]
            return (ExplodingCandidate(),)

    result = retrieve_grounding_v2(
        conn, request, embedding=MalformedAdapter(),
        synthetic_config=SyntheticEmbeddingConfig(model_id="fake-v1", dimension=3,
                                                   normalization_version="unit-v1"),
    )
    assert result == baseline
