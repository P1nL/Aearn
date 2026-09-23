"""DB-backed fixture architecture evidence; exclusive prebootstrapped DB only.

The test owns an outer transaction and rolls back all candidate/pointer writes.
The separate CLI subprocess demonstration is exercised by rag_v2_demo.py.
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.services.grounding.corpus_fixture_policy import FIXTURE_VERSION
from app.services.grounding.corpus_service import CorpusService
from app.services.grounding.fixtures_v2 import fixture_scenarios, validate_fixture_scenarios
from app.services.grounding.hybrid_retrieval import (
    DeterministicFakeEmbeddingRetriever, EmbeddingCandidate,
    SyntheticEmbeddingConfig, retrieve_grounding_v2, synthetic_embedding_receipt,
)
from app.services.grounding.retrieval_contracts import (
    ActiveCorpusSelector, ExactCorpusSelector, GroundingRetrievalRequest,
)
from app.services.grounding.subject_registry import is_public_subject_candidate
from app.services.learning.contracts import LearningPlan, LearningPlanModule, LearningPlanNode
from app.services.learning.plan_coverage import (
    NodeSourceRequirement, PlanCoveragePreflightService,
    PlanCoverageShadowAdapter, PostgresPlanFactReader,
)


@pytest.fixture()
def isolated_corpus():  # type: ignore[no-untyped-def]
    dsn = os.getenv("DATABASE_URL", "")
    try:
        url = urlsplit(dsn)
        name = unquote(url.path.lstrip("/"))
        query = parse_qsl(url.query, strict_parsing=True)
        resolved = conninfo_to_dict(dsn)
        valid = (url.scheme in {"postgres", "postgresql"}
                 and url.hostname in {"localhost", "127.0.0.1", "::1"}
                 and not url.fragment and not any(ord(c) < 32 or ord(c) == 127 for c in dsn)
                 and all(key in {"sslmode", "connect_timeout"} for key, _ in query)
                 and resolved.get("host") in {"localhost", "127.0.0.1", "::1"}
                 and resolved.get("dbname") == name and not resolved.get("hostaddr")
                 and name.startswith("aearn_rag260_cli_retrieval_")
                 and os.getenv("RAG_V2_INTEGRATION_DB_CONFIRM") == name
                 and os.getenv("PYTHON_DOTENV_DISABLED") == "1"
                 and os.getenv("LLM_TYPE") == "disabled"
                 and os.getenv("CODEX_RUNTIME_ENABLED") == "false"
                 and not any(os.getenv(key) for key in (
                     "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGHOST", "PGHOSTADDR",
                     "PGDATABASE", "PGPORT", "PGPASSFILE", "PGTARGETSESSIONATTRS")))
    except Exception:
        valid = False
    if not valid:
        pytest.skip("requires explicitly confirmed, offline, local retrieval test DB")
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as conn:
        identity = conn.execute(
            "SELECT current_database() AS database, host(inet_server_addr()) AS server_address"
        ).fetchone()
        if (identity is None or identity["database"] != name or conn.info.dbname != name
                or conn.info.host not in {"localhost", "127.0.0.1", "::1"}
                or identity["server_address"] is None):
            pytest.fail("connected database scope mismatch before write")
        address = ipaddress.ip_address(identity["server_address"])
        if address.is_unspecified or address.is_multicast or not (address.is_loopback or address.is_private):
            pytest.fail("connected server address outside disposable scope")
        try:
            yield conn
        finally:
            conn.rollback()


def _request(subject: str, facets: tuple[str, ...], *, query: str,
             selector: ActiveCorpusSelector | ExactCorpusSelector,
             version: str = FIXTURE_VERSION, mode: str = "disabled") -> GroundingRetrievalRequest:
    return GroundingRetrievalRequest(
        subject_id=subject, subject_version=version, corpus_selector=selector,
        query_text=query, required_facets=facets, stage="lesson_authoring",
        embedding_mode=mode,  # type: ignore[arg-type]
    )


def test_ten_subject_lifecycle_fts_embedding_and_blocked_langchain(isolated_corpus) -> None:  # type: ignore[no-untyped-def]
    conn = isolated_corpus
    scenarios = fixture_scenarios()
    assert len(scenarios) == 10 and validate_fixture_scenarios() == ()
    service = CorpusService(conn)
    published: dict[str, tuple[UUID, str]] = {}
    for scenario in scenarios:
        key = uuid4().hex
        created = service.reindex(scenario.subject_id, FIXTURE_VERSION, mode="fixture", idempotency_key=key)
        corpus_id = UUID(str(created["corpus_id"]))
        checked = service.validate(corpus_id, expected_generation=0, idempotency_key=f"v-{key}")
        assert checked["ok"] and checked["validation"]["passed"]  # type: ignore[index]
        difference = service.diff(corpus_id, idempotency_key=f"d-{key}")
        assert difference["base_generation"] == 0
        summary = str(checked["summary_hash"])
        activated = service.activate(corpus_id, expected_generation=0, summary_hash=summary,
                                     idempotency_key=f"a-{key}")
        assert activated["code"] == "ACTIVATED"
        published[scenario.subject_id] = corpus_id, summary

        request = _request(scenario.subject_id, scenario.required_facets,
                           query=scenario.query_text,
                           selector=ActiveCorpusSelector(expected_generation=1,
                                                         expected_summary_hash=summary))
        result = retrieve_grounding_v2(conn, request)
        assert result.plan is not None and result.plan.synthetic_fixture
        assert result.plan.corpus_id == corpus_id
        assert result.coverage.status == "satisfied"
        assert result.coverage.covered_facets == scenario.required_facets
        assert result.coverage.source_count >= 2
        assert result == retrieve_grounding_v2(conn, request)
        assert not is_public_subject_candidate(scenario.subject_id)

        wrong_version = retrieve_grounding_v2(conn, _request(
            scenario.subject_id, scenario.required_facets, query=scenario.query_text,
            selector=ActiveCorpusSelector(), version="fixture-v2"))
        assert wrong_version.evidence == () and wrong_version.coverage.status == "unavailable"
        cross_scope = retrieve_grounding_v2(conn, _request(
            scenario.subject_id, scenario.required_facets, query=scenario.query_text,
            selector=ExactCorpusSelector(corpus_id=corpus_id, expected_summary_hash="0" * 64)))
        assert cross_scope.evidence == () and cross_scope.coverage.status == "unavailable"

    web_id, web_hash = published["route.web-platform"]
    parent_fallback = retrieve_grounding_v2(conn, _request(
        "web.react", ("components",), query="React components",
        selector=ExactCorpusSelector(corpus_id=web_id, expected_summary_hash=web_hash)))
    assert parent_fallback.plan is None and parent_fallback.evidence == ()
    assert parent_fallback.coverage.status == "unavailable"
    assert parent_fallback.coverage.reason_codes == ("VERSION_MISMATCH",)
    sql_dialect = retrieve_grounding_v2(conn, _request(
        "route.sql", ("postgresql-dialect",), query="PostgreSQL dialect",
        selector=ActiveCorpusSelector()))
    assert sql_dialect.plan is None and sql_dialect.evidence == ()
    assert sql_dialect.coverage.status == "unavailable"
    assert sql_dialect.coverage.reason_codes == ("FACET_INVALID",)

    # Base Python cannot lend its corpus to the Python AI/optional LangChain facet.
    _, ai_hash = published["python.ai-applications"]
    missing = retrieve_grounding_v2(conn, _request(
        "python.ai-applications", ("langchain-core",), query="LangChain core",
        selector=ActiveCorpusSelector(expected_generation=1, expected_summary_hash=ai_hash)))
    # This facet has no published source snapshot. Resolution closes before a
    # plan exists; neither base Python nor unrelated AI facets can fill the gap.
    assert missing.plan is None and missing.evidence == ()
    assert missing.coverage.status == "unavailable"
    assert missing.coverage.reason_codes == ("SOURCE_SCOPE_EMPTY",)
    assert missing.coverage.subject_id == "python.ai-applications"
    assert missing.coverage.corpus_id is None
    assert missing.coverage.covered_facets == ()
    assert missing.coverage.missing_facets == ("langchain-core",)

    scenario = scenarios[0]
    fts_request = _request(scenario.subject_id, scenario.required_facets,
                           query=scenario.query_text, selector=ActiveCorpusSelector(), mode="optional")
    fts = retrieve_grounding_v2(conn, fts_request)
    assert fts.plan is not None and fts.evidence
    config = SyntheticEmbeddingConfig(model_id="test-fake-v1", dimension=3, normalization_version="unit-v1")
    first = fts.evidence[0]
    candidate = EmbeddingCandidate(
        corpus_id=fts.plan.corpus_id, chunk_id=first.chunk_id, chunk_hash=first.chunk_hash,
        synthetic_receipt=synthetic_embedding_receipt(fts.plan, config),
        model_id=config.model_id, dimension=config.dimension,
        normalization_version=config.normalization_version,
    )
    good = retrieve_grounding_v2(conn, fts_request,
                                 embedding=DeterministicFakeEmbeddingRetriever((candidate,)),
                                 synthetic_config=config)
    invalid = retrieve_grounding_v2(conn, fts_request,
                                    embedding=DeterministicFakeEmbeddingRetriever((
                                        candidate.model_copy(update={"chunk_hash": "0" * 64}),
                                    )), synthetic_config=config)
    assert good.coverage.status == "satisfied" and "EMBEDDING_UNAVAILABLE" not in good.coverage.reason_codes
    assert invalid == fts

    draft = LearningPlan(
        title="Synthetic LangChain goal", target_level="beginner", generator_version="fixture-v1",
        policy_version="fixture-v1", change_reason="demo",
        modules=(LearningPlanModule(
            module_key="m1", title="LangChain", description="", order_index=0,
            is_core=True, is_skippable=False,
            nodes=(LearningPlanNode(knowledge_key="lc-overview", title="LangChain core",
                                    description="", order_index=0, is_core=True,
                                    prerequisite_keys=(), required_capabilities=("lesson", "practice")),),
        ),),
    )
    requirement = NodeSourceRequirement(
        knowledge_key="lc-overview", subject_id="python.ai-applications",
        subject_version=FIXTURE_VERSION, required_facets=("langchain-core",),
        required_capabilities=("lesson", "practice"), expected_corpus_generation=1,
        expected_corpus_summary_hash=ai_hash,
    )
    adapter = PlanCoverageShadowAdapter(PlanCoveragePreflightService(
        PostgresPlanFactReader(conn, retrieve=retrieve_grounding_v2)), enabled=True)
    report = adapter.evaluate(draft, (requirement,), expected_plan_hash=draft.content_hash)
    assert report is not None and report.activation_blocked
    assert report.nodes[0].status == "unavailable"
    assert report.nodes[0].missing_facets == ("langchain-core",)
    assert report.nodes[0].allowed_actions == ("wait_for_release",)
    assert "SOURCE_SCOPE_EMPTY" in report.nodes[0].reason_codes
    assert "PUBLIC_RELEASE_UNAVAILABLE" in report.nodes[0].reason_codes
