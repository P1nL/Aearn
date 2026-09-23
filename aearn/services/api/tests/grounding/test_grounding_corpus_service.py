"""Serial, disposable-DB acceptance for the local corpus service."""
from __future__ import annotations

import json
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.services.grounding.corpus_contracts import CorpusCandidate
from app.services.grounding.corpus_fixtures import FIXTURE_VERSION, fixture_registry_digest, fixture_slices
from app.services.grounding.corpus_repository import CorpusConflict
from app.services.grounding.corpus_service import (
    CorpusOperationError, CorpusService, _chunk, _document, _source,
)
from app.services.grounding.subject_registry import get_grounding_subject


@pytest.fixture()
def service():  # type: ignore[no-untyped-def]
    db = urlsplit(get_settings().database_url).path.lstrip("/")
    if not db.startswith("aearn_rag260_cli_"):
        pytest.skip("requires an exclusively assigned disposable corpus CLI database")
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        conn.execute("SELECT 1")  # Caller rollback encloses service-owned savepoints.
        yield CorpusService(conn)
        conn.rollback()


def _key() -> str:
    return f"test-{uuid4().hex}"


def _build(service: CorpusService, subject: str = "python.fastapi") -> tuple[UUID, str]:
    result = service.reindex(subject, FIXTURE_VERSION, mode="fixture", idempotency_key=_key())
    assert result["code"] == "REINDEXED"
    candidate_id = UUID(str(result["corpus_id"]))
    checked = service.validate(candidate_id, expected_generation=0, idempotency_key=_key())
    assert checked["code"] == "VALIDATED"
    return candidate_id, str(checked["summary_hash"])


def test_lifecycle_replay_cas_diff_rollback_and_retire(service: CorpusService) -> None:
    key = _key()
    legacy_before = service.conn.execute("SELECT count(*) AS n FROM grounding_chunks").fetchone()
    first = service.reindex("web.react", FIXTURE_VERSION, mode="fixture", idempotency_key=key)
    assert first["counts"] == {"sources": 3, "documents": 3, "chunks": 3, "failures": 0}
    assert service.reindex("web.react", FIXTURE_VERSION, mode="fixture", idempotency_key=key)["event_id"] == first["event_id"]
    assert service.status("web.react")["active"] is None
    corpus_id = UUID(str(first["corpus_id"]))
    validation_key = _key()
    checked = service.validate(corpus_id, expected_generation=0, idempotency_key=validation_key)
    assert checked["coverage"] == {"required": 3, "covered": 3, "source_diversity": 3, "fixture_only": True}
    assert service.validate(corpus_id, expected_generation=0, idempotency_key=validation_key)["event_id"] == checked["event_id"]
    diff_key = _key()
    diff = service.diff(corpus_id, idempotency_key=diff_key)
    assert diff["base_corpus_id"] is None
    assert diff["counts"]["chunks_added"] == 3
    assert service.status("web.react")["active"] is None
    with pytest.raises(CorpusConflict):
        service.activate(corpus_id, expected_generation=0, summary_hash="0" * 64, idempotency_key=_key())
    activation_key = _key()
    active = service.activate(corpus_id, expected_generation=0, summary_hash=str(checked["summary_hash"]),
                              idempotency_key=activation_key)
    assert service.activate(corpus_id, expected_generation=0, summary_hash=str(checked["summary_hash"]),
                            idempotency_key=activation_key)["event_id"] == active["event_id"]
    assert service.validate(corpus_id, expected_generation=0,
                            idempotency_key=validation_key)["event_id"] == checked["event_id"]
    assert service.diff(corpus_id, idempotency_key=diff_key)["base_corpus_id"] is None
    with pytest.raises(CorpusConflict):
        service.activate(corpus_id, expected_generation=0, summary_hash=str(checked["summary_hash"]),
                         idempotency_key=_key())
    with pytest.raises(CorpusConflict):
        service.retire(corpus_id, idempotency_key=_key())
    second_id, second_hash = _build(service, "web.react")
    newer_diff_key = _key()
    newer_diff = service.diff(second_id, idempotency_key=newer_diff_key)
    assert newer_diff["base_corpus_id"] == str(corpus_id)
    assert newer_diff["base_generation"] == 1
    service.activate(second_id, expected_generation=1, summary_hash=second_hash, idempotency_key=_key())
    assert service.diff(second_id, idempotency_key=newer_diff_key)["base_corpus_id"] == str(corpus_id)
    rollback_key = _key()
    rolled = service.rollback("web.react", corpus_id, expected_generation=2, idempotency_key=rollback_key)
    assert rolled["observed_generation"] == 3
    assert service.rollback("web.react", corpus_id, expected_generation=2,
                            idempotency_key=rollback_key)["event_id"] == rolled["event_id"]
    assert service.status("web.react")["active"] == {"corpus_id": str(corpus_id), "generation": 3}
    service.retire(second_id, idempotency_key=_key())
    assert service.repo.version(second_id).state == "retired"
    assert service.conn.execute("SELECT count(*) AS n FROM grounding_chunks").fetchone() == legacy_before


def test_missing_facet_source_failure_and_tampered_scope_fail_closed(service: CorpusService) -> None:
    def fail_one(item):  # type: ignore[no-untyped-def]
        if item.facet == "routing":
            raise RuntimeError("secret DSN and raw source body must not persist")
        return item.content
    failed_service = CorpusService(service.conn, fixture_renderer=fail_one)
    first = failed_service.reindex("python.fastapi", FIXTURE_VERSION, mode="fixture", idempotency_key=_key())
    assert first["counts"]["failures"] == 1
    corpus_id = UUID(str(first["corpus_id"]))
    checked = service.validate(corpus_id, expected_generation=0, idempotency_key=_key())
    assert checked["ok"] is False and checked["code"] == "VALIDATION_FAILED"
    assert checked["coverage"]["covered"] == 2
    assert service.repo.version(corpus_id).state == "failed"
    assert service.status("python.fastapi")["active"] is None
    source = service.conn.execute("SELECT source_kind,source_id FROM grounding_corpus_source_snapshots WHERE corpus_version_id=%s LIMIT 1", (corpus_id,)).fetchone()
    assert source["source_kind"] == "fixture" and source["source_id"].startswith("fixture.python.fastapi.")
    document = service.conn.execute("SELECT diagnostic_code FROM grounding_corpus_documents WHERE corpus_version_id=%s AND parse_status='failed'", (corpus_id,)).fetchone()
    assert document["diagnostic_code"] == "FIXTURE_PROCESS_FAILED"
    other = service.reindex("python.fastapi", FIXTURE_VERSION, mode="fixture", idempotency_key=_key())
    other_id = UUID(str(other["corpus_id"]))
    service.conn.execute("UPDATE grounding_corpus_source_snapshots SET source_kind='documentation' WHERE corpus_version_id=%s", (other_id,))
    rejected = service.validate(other_id, expected_generation=0, idempotency_key=_key())
    assert rejected["ok"] is False and rejected["validation"]["reason_code"] == "SOURCE_SCOPE_INVALID"


def test_version_fetch_and_subject_fail_without_candidate(service: CorpusService) -> None:
    for subject, version, mode, code in (
        ("python.fastapi", "arbitrary-v3", "fixture", "VERSION_UNSUPPORTED"),
        ("python.fastapi", FIXTURE_VERSION, "fetch", "FETCH_NOT_READY"),
        ("unknown.framework", FIXTURE_VERSION, "fixture", "SUBJECT_UNSUPPORTED"),
    ):
        with pytest.raises(CorpusOperationError, match=code):
            service.reindex(subject, version, mode=mode, idempotency_key=_key())
    assert service.conn.execute("SELECT count(*) AS n FROM grounding_corpus_versions WHERE subject_version='arbitrary-v3'").fetchone()["n"] == 0


@pytest.mark.parametrize("subject_id", (
    "route.python", "route.typescript-javascript", "route.web-platform", "route.sql",
    "python.ai-applications", "python.fastapi", "typescript.nodejs", "web.react",
    "web.platform", "sql.postgresql-foundations",
))
def test_registered_subject_fixture_slice_is_exact_and_not_public(service: CorpusService, subject_id: str) -> None:
    candidate_id, summary_hash = _build(service, subject_id)
    assert len(summary_hash) == 64
    rows = service.conn.execute(
        "SELECT source_kind,allowed_domains_json,facets_json FROM grounding_corpus_source_snapshots "
        "WHERE corpus_version_id=%s", (candidate_id,),
    ).fetchall()
    assert all(row["source_kind"] == "fixture" and row["allowed_domains_json"] == ["fixtures.aearn.invalid"]
               for row in rows)
    assert service.status(subject_id)["active"] is None


def test_all_source_failures_are_persisted_but_never_validated(service: CorpusService) -> None:
    def reject(_item):  # type: ignore[no-untyped-def]
        raise RuntimeError("never expose this raw exception")
    failed = CorpusService(service.conn, fixture_renderer=reject)
    result = failed.reindex("route.sql", FIXTURE_VERSION, mode="fixture", idempotency_key=_key())
    assert result["counts"]["failures"] == 2
    checked = service.validate(UUID(str(result["corpus_id"])), expected_generation=0, idempotency_key=_key())
    assert checked["ok"] is False and checked["counts"]["chunks"] == 0
    assert checked["validation"]["reason_code"] == "MISSING_FACETS"
    assert checked["coverage"]["source_diversity"] == 0


def test_repository_boolean_cannot_forge_operator_validation(service: CorpusService) -> None:
    created = service.reindex("python.fastapi", FIXTURE_VERSION, mode="fixture", idempotency_key=_key())
    corpus_id = UUID(str(created["corpus_id"]))
    forged = service.repo.finalize_validation(
        corpus_id, passed=True, expected_generation=0,
        validation_summary={"passed": True, "sources": 3},
        coverage_summary={"required": 3, "covered": 3, "fixture_only": True},
        idempotency_key=_key(),
    )
    assert forged.summary_hash is not None
    with pytest.raises(CorpusOperationError, match="CORPUS_SCOPE_INVALID"):
        service.activate(corpus_id, expected_generation=0,
                         summary_hash=forged.summary_hash, idempotency_key=_key())
    with pytest.raises(CorpusOperationError, match="CORPUS_SCOPE_INVALID"):
        service.diff(corpus_id, idempotency_key=_key())
    assert service.status("python.fastapi")["active"] is None


def test_unregistered_candidate_cannot_validate_even_with_exact_fixture_snapshots(
    service: CorpusService,
) -> None:
    subject = get_grounding_subject("python.fastapi")
    assert subject is not None
    corpus_id = uuid4()
    service.repo.create_candidate(CorpusCandidate(
        corpus_id=corpus_id, subject_id=subject.subject_id, subject_version=FIXTURE_VERSION,
        registry_digest=fixture_registry_digest(subject), retrieval_policy_version="wrong-fts-v1",
        coverage_policy_version="fixture-facets-v1",
    ), idempotency_key=_key())
    for item in fixture_slices(subject):
        source = _source(corpus_id, subject, item)
        document = _document(corpus_id, subject, item, source)
        service.repo.add_source(source)
        service.repo.add_document(document)
        service.repo.add_chunk(_chunk(corpus_id, subject, item, source, document))
    checked = service.validate(corpus_id, expected_generation=0, idempotency_key=_key())
    assert checked["ok"] is False and checked["validation"]["error_count"] == 2
    assert checked["validation"]["reason_code"] == "OPERATOR_PROVENANCE_INVALID"
    assert service.repo.version(corpus_id).state == "failed"


def test_failed_write_rolls_back_without_committing_caller_work(
    service: CorpusService, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.conn.execute("CREATE TEMP TABLE corpus_caller_marker (value text)")
    service.conn.execute("INSERT INTO corpus_caller_marker VALUES ('caller-owned')")
    key = _key()
    original_add_chunk = service.repo.add_chunk
    with monkeypatch.context() as patch:
        patch.setattr(service.repo, "add_chunk", lambda _chunk: (_ for _ in ()).throw(RuntimeError("injected")))
        with pytest.raises(RuntimeError, match="injected"):
            service.reindex("route.sql", FIXTURE_VERSION, mode="fixture", idempotency_key=key)
    assert service.conn.execute("SELECT value FROM corpus_caller_marker").fetchone()["value"] == "caller-owned"
    assert service.conn.execute("SELECT count(*) AS n FROM grounding_corpus_events WHERE idempotency_key=%s", (key,)).fetchone()["n"] == 0
    service.repo.add_chunk = original_add_chunk
    assert service.reindex("route.sql", FIXTURE_VERSION, mode="fixture", idempotency_key=key)["code"] == "REINDEXED"


def test_idempotency_key_conflicts_and_retire_replay(service: CorpusService) -> None:
    key = _key()
    first = service.reindex("route.sql", FIXTURE_VERSION, mode="fixture", idempotency_key=key)
    with pytest.raises(CorpusConflict):
        service.reindex("web.react", FIXTURE_VERSION, mode="fixture", idempotency_key=key)
    corpus_id = UUID(str(first["corpus_id"]))
    retire_key = _key()
    retired = service.retire(corpus_id, idempotency_key=retire_key)
    assert service.retire(corpus_id, idempotency_key=retire_key)["event_id"] == retired["event_id"]
    with pytest.raises(CorpusConflict):
        service.retire(corpus_id, idempotency_key=_key())


def test_validate_key_cannot_cross_pass_and_failure_outcomes(service: CorpusService) -> None:
    def reject(_item):  # type: ignore[no-untyped-def]
        raise RuntimeError("source failure")
    failed = CorpusService(service.conn, fixture_renderer=reject)
    failed_id = UUID(str(failed.reindex("route.sql", FIXTURE_VERSION, mode="fixture",
                                        idempotency_key=_key())["corpus_id"]))
    passed_id = UUID(str(service.reindex("route.sql", FIXTURE_VERSION, mode="fixture",
                                           idempotency_key=_key())["corpus_id"]))
    key = _key()
    first = service.validate(failed_id, expected_generation=0, idempotency_key=key)
    assert first["ok"] is False
    with pytest.raises(CorpusConflict, match="validation key reused"):
        service.validate(passed_id, expected_generation=0, idempotency_key=key)
    assert service.repo.version(passed_id).state == "candidate"
    assert service.validate(failed_id, expected_generation=0, idempotency_key=key)["event_id"] == first["event_id"]


def test_fts_validation_checks_index_readiness(service: CorpusService) -> None:
    created = service.reindex("route.sql", FIXTURE_VERSION, mode="fixture", idempotency_key=_key())
    service.conn.execute("DROP INDEX idx_grounding_corpus_chunks_search")
    # A same-named but unrelated B-tree must not masquerade as the FTS GIN index.
    service.conn.execute("CREATE INDEX idx_grounding_corpus_chunks_search ON grounding_corpus_chunks (chunk_id)")
    result = service.validate(UUID(str(created["corpus_id"])), expected_generation=0, idempotency_key=_key())
    assert result["ok"] is False
    assert result["validation"]["reason_code"] == "FTS_UNAVAILABLE"
    assert service.status("route.sql")["active"] is None


def test_status_is_bounded_even_with_ten_recent_versions(service: CorpusService) -> None:
    for _ in range(10):
        service.reindex("route.sql", FIXTURE_VERSION, mode="fixture", idempotency_key=_key())
    status = service.status("route.sql")
    assert len(status["recent"]) == 10
    assert len(json.dumps(status).encode("utf-8")) < 8192
