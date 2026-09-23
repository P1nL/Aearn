from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from time import sleep
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.grounding.corpus_contracts import CorpusCandidate, CorpusChunk, CorpusDocument, CorpusSource
from app.services.grounding.corpus_repository import CorpusConflict, CorpusRepository


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def isolated_bootstrap() -> None:
    db = urlsplit(get_settings().database_url).path.lstrip("/")
    if not db.startswith("aearn_rag260_"):
        pytest.skip("corpus authority tests require a dedicated disposable PostgreSQL database")
    bootstrap_database()
    bootstrap_database()


@pytest.fixture()
def conn(isolated_bootstrap: None):  # type: ignore[no-untyped-def]
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as connection:
        yield connection
        connection.rollback()


def _candidate(repo: CorpusRepository, *, subject: str | None = None) -> CorpusCandidate:
    subject = subject or f"test.corpus-{uuid4().hex}"
    candidate = CorpusCandidate(
        corpus_id=uuid4(),subject_id=subject,subject_version="v1",registry_digest=_digest("registry"),
        retrieval_policy_version="fts-v1",coverage_policy_version="coverage-v1",
    )
    event = repo.create_candidate(candidate,idempotency_key=f"create-{candidate.corpus_id}")
    assert event.event_kind == "reindex_started"
    return candidate


def _fill(repo: CorpusRepository, candidate: CorpusCandidate) -> None:
    common = dict(corpus_id=candidate.corpus_id,subject_id=candidate.subject_id,subject_version=candidate.subject_version)
    repo.add_source(CorpusSource(
        **common,source_id="source-1",source_hash=_digest("source"),trust_tier="official",
        source_kind="documentation",source_version="v1",allowed_domains=("docs.example.org",),
        seed_urls=("https://docs.example.org/start",),facets=("fundamentals",),
    ))
    repo.add_document(CorpusDocument(
        **common,document_id="document-1",source_id="source-1",source_hash=_digest("source"),
        trust_tier="official",canonical_url="https://docs.example.org/start",
        final_url="https://docs.example.org/start",content_type="text/html",document_version="v1",
        fetched_at=datetime.now(UTC),document_hash=_digest("document"),parse_status="parsed",
    ))
    repo.add_chunk(CorpusChunk(
        **common,chunk_id="chunk-1",document_id="document-1",source_id="source-1",
        source_hash=_digest("source"),trust_tier="official",document_hash=_digest("document"),
        ordinal=0,title="Example",section_path="Introduction",content="Functions and modules.",
        facets=("fundamentals",),topic_tags=("functions",),chunk_hash=_digest("Functions and modules."),
    ))


def _validated(repo: CorpusRepository, *, subject: str | None = None) -> CorpusCandidate:
    candidate = _candidate(repo,subject=subject)
    _fill(repo,candidate)
    event = repo.finalize_validation(
        candidate.corpus_id,passed=True,expected_generation=0,
        validation_summary={"status":"passed"},coverage_summary={"facet_count":1},
        idempotency_key=f"validate-{candidate.corpus_id}",
    )
    assert event.event_kind == "validation_passed"
    return candidate


def test_source_and_document_dto_reject_credential_urls() -> None:
    corpus_id = uuid4()
    source = CorpusSource(
        corpus_id=corpus_id, subject_id="python.core", subject_version="v1",
        source_id="source-1", source_hash=_digest("source"), trust_tier="official",
        source_kind="documentation", source_version="v1", allowed_domains=("docs.example.org",),
        seed_urls=("https://docs.example.org/start",), facets=("fundamentals",),
    )
    with pytest.raises(ValueError):
        CorpusSource.model_validate(source.model_dump() | {
            "seed_urls": ("https://user:secret@docs.example.org/start",),
        })
    with pytest.raises(ValueError):
        CorpusSource.model_validate(source.model_dump() | {
            "seed_urls": ("https://docs.example.org/start?api_token=secret",),
        })
    with pytest.raises(ValueError):
        CorpusSource.model_validate(source.model_dump() | {
            "allowed_domains": ("user:secret@docs.example.org",),
        })
    document = CorpusDocument(
        corpus_id=corpus_id, document_id="document-1", source_id=source.source_id,
        subject_id=source.subject_id, subject_version=source.subject_version,
        source_hash=source.source_hash, trust_tier="official",
        canonical_url="https://docs.example.org/start", final_url="https://docs.example.org/start",
        content_type="text/html", document_version="v1", fetched_at=datetime.now(UTC),
        document_hash=_digest("document"), parse_status="parsed",
    )
    with pytest.raises(ValueError):
        CorpusDocument.model_validate(document.model_dump() | {
            "final_url": "https://user:secret@docs.example.org/start",
        })


def test_manifest_bootstrap_repeatable_legacy_tables_and_fts(conn) -> None:  # type: ignore[no-untyped-def]
    tables = {row["table_name"] for row in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'grounding_%'"
    )}
    assert {"grounding_corpus_versions","grounding_active_corpora","grounding_corpus_source_snapshots",
            "grounding_corpus_documents","grounding_corpus_chunks","grounding_corpus_events",
            "grounding_chunks","grounding_reindex_runs"} <= tables
    repo = CorpusRepository(conn)
    candidate = _validated(repo)
    row = conn.execute(
        "SELECT search_vector @@ plainto_tsquery('simple','functions') AS hit FROM grounding_corpus_chunks WHERE corpus_version_id=%s",
        (candidate.corpus_id,),
    ).fetchone()
    assert row is not None and row["hit"] is True


def test_lifecycle_replay_conflict_and_history(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    first = _validated(repo)
    validated = repo.version(first.corpus_id)
    assert validated.state == "validated" and validated.summary_hash is not None
    key = f"activate-{first.corpus_id}"
    event = repo.activate(first.corpus_id,expected_generation=0,summary_hash=validated.summary_hash,idempotency_key=key)
    assert repo.activate(first.corpus_id,expected_generation=0,summary_hash=validated.summary_hash,idempotency_key=key) == event
    assert repo.active(first.subject_id).generation == 1
    with pytest.raises(CorpusConflict):
        repo.activate(first.corpus_id,expected_generation=1,summary_hash=validated.summary_hash,idempotency_key=key)
    with pytest.raises(CorpusConflict):
        repo.retire(first.corpus_id,expected_generation=2,idempotency_key=f"retire-{first.corpus_id}")
    second = _validated(repo,subject=first.subject_id)
    event2 = repo.activate(second.corpus_id,expected_generation=1,
                           summary_hash=repo.version(second.corpus_id).summary_hash,
                           idempotency_key=f"activate-{second.corpus_id}")
    assert event2.observed_generation == 2
    rolled = repo.rollback(first.subject_id,first.corpus_id,expected_generation=2,idempotency_key=f"rollback-{first.corpus_id}")
    assert rolled.observed_generation == 3 and repo.active(first.subject_id).corpus_id == first.corpus_id
    retired = repo.retire(second.corpus_id,expected_generation=2,idempotency_key=f"retire-{second.corpus_id}")
    assert repo.retire(second.corpus_id,expected_generation=2,idempotency_key=f"retire-{second.corpus_id}") == retired
    assert repo.version(second.corpus_id).state == "retired"
    assert {event.event_kind for event in repo.history(first.subject_id)} >= {"activated","rolled_back","retired"}


def test_failed_candidate_and_stale_activation_leave_no_publication(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    first = _candidate(repo)
    failed = repo.finalize_validation(first.corpus_id,passed=False,expected_generation=0,
                                      validation_summary={"status":"failed"},coverage_summary={},
                                      idempotency_key=f"failed-{first.corpus_id}")
    assert failed.event_kind == "validation_failed" and repo.version(first.corpus_id).state == "failed"
    candidate = _validated(repo,subject=first.subject_id)
    with pytest.raises(CorpusConflict):
        repo.activate(candidate.corpus_id,expected_generation=1,
                      summary_hash=repo.version(candidate.corpus_id).summary_hash,
                      idempotency_key=f"stale-{candidate.corpus_id}")
    assert repo.version(candidate.corpus_id).state == "validated"
    assert repo.active(first.subject_id) is None
    assert all(event.event_kind != "activated" for event in repo.history(first.subject_id))


def test_database_rejects_bypass_scope_and_sealed_mutations(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    candidate = _validated(repo)
    def rejected(exc_type, statement: str, params: tuple[object, ...]) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(exc_type):
            with conn.transaction():
                conn.execute(statement, params)

    rejected(psycopg.errors.CheckViolation,
             "UPDATE grounding_corpus_chunks SET content='forged' WHERE corpus_version_id=%s",(candidate.corpus_id,))
    rejected(psycopg.errors.CheckViolation,
             "DELETE FROM grounding_corpus_source_snapshots WHERE corpus_version_id=%s",(candidate.corpus_id,))
    rejected(psycopg.errors.CheckViolation,
             "INSERT INTO grounding_corpus_chunks (corpus_version_id,chunk_id) VALUES (%s,'forged')",(candidate.corpus_id,))
    rejected(psycopg.errors.CheckViolation,
             "UPDATE grounding_corpus_versions SET registry_digest=%s,generation=2 WHERE id=%s",
             (_digest("forged"),candidate.corpus_id))
    rejected(psycopg.errors.CheckViolation,
             "DELETE FROM grounding_corpus_events WHERE corpus_version_id=%s",(candidate.corpus_id,))
    other = _candidate(repo)
    rejected(psycopg.errors.ForeignKeyViolation,
             """INSERT INTO grounding_corpus_source_snapshots
                (corpus_version_id,subject_id,subject_version,source_id,source_hash,trust_tier,source_kind,
                 source_version,allowed_domains_json,seed_urls_json,facets_json)
                VALUES (%s,%s,'v1','foreign',%s,'official','documentation','v1','["docs.example.org"]','[]','["fundamentals"]')""",
             (other.corpus_id,candidate.subject_id,_digest("foreign")))

def test_two_connections_first_activation_has_one_winner(isolated_bootstrap: None) -> None:
    dsn = get_settings().database_url
    with psycopg.connect(dsn,row_factory=dict_row) as setup:
        repo = CorpusRepository(setup)
        first = _validated(repo)
        second = _validated(repo,subject=first.subject_id)
        summaries = (repo.version(first.corpus_id).summary_hash,repo.version(second.corpus_id).summary_hash)
    def activate(index: int) -> str:
        try:
            with psycopg.connect(dsn,row_factory=dict_row) as connection:
                repository = CorpusRepository(connection)
                repository.activate((first,second)[index].corpus_id,expected_generation=0,
                                    summary_hash=summaries[index],idempotency_key=f"race-{uuid4()}")
            return "won"
        except CorpusConflict:
            return "lost"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(activate,(0,1)))
    assert sorted(results) == ["lost","won"]
    with psycopg.connect(dsn,row_factory=dict_row) as check:
        repository = CorpusRepository(check)
        assert repository.active(first.subject_id).generation == 1
        assert len([v for v in (repository.version(first.corpus_id),repository.version(second.corpus_id)) if v.state == "published"]) == 1
        assert len([e for e in repository.history(first.subject_id) if e.event_kind == "activated"]) == 1


def test_candidate_retirement_and_direct_pointer_bypass(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    candidate = _candidate(repo)
    retired = repo.retire(candidate.corpus_id,expected_generation=0,idempotency_key=f"retire-{candidate.corpus_id}")
    assert retired.event_kind == "retired" and repo.version(candidate.corpus_id).state == "retired"
    with pytest.raises(CorpusConflict):
        repo.finalize_validation(candidate.corpus_id,passed=True,expected_generation=1,
                                 validation_summary={},coverage_summary={},idempotency_key=f"invalid-{candidate.corpus_id}")
    # A manually forged pointer without a matching published corpus/activation receipt is denied in SQL.
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                """INSERT INTO grounding_active_corpora
                   (subject_id,corpus_version_id,generation,activation_event_id,activation_event_kind)
                   VALUES (%s,%s,1,%s,'activated')""",
                (candidate.subject_id,candidate.corpus_id,uuid4()),
            )


def test_document_hash_lineage_rejects_cross_source(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    candidate = _candidate(repo)
    _fill(repo,candidate)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            conn.execute(
                """UPDATE grounding_corpus_documents SET source_hash=%s
                   WHERE corpus_version_id=%s AND document_id='document-1'""",
                (_digest("wrong-source"),candidate.corpus_id),
            )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            conn.execute(
                """UPDATE grounding_corpus_chunks SET document_hash=%s
                   WHERE corpus_version_id=%s AND chunk_id='chunk-1'""",
                (_digest("wrong-document"),candidate.corpus_id),
            )
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                """UPDATE grounding_corpus_chunks SET content='forged'
                   WHERE corpus_version_id=%s AND chunk_id='chunk-1'""",
                (candidate.corpus_id,),
            )


def test_sealed_child_cannot_be_reparented_to_candidate(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    sealed = _validated(repo)
    candidate = _candidate(repo, subject=sealed.subject_id)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "UPDATE grounding_corpus_source_snapshots SET corpus_version_id=%s WHERE corpus_version_id=%s",
                (candidate.corpus_id, sealed.corpus_id),
            )
    assert conn.execute(
        "SELECT corpus_version_id FROM grounding_corpus_source_snapshots WHERE source_id='source-1' AND corpus_version_id=%s",
        (sealed.corpus_id,),
    ).fetchone() is not None


def test_failed_publication_rolls_back_all_writes_even_if_caught(conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    candidate = _validated(repo)
    summary = repo.version(candidate.corpus_id).summary_hash

    def fail_pointer(*_args: object) -> None:
        raise CorpusConflict("injected pointer failure")

    monkeypatch.setattr(repo, "_advance_pointer", fail_pointer)
    with pytest.raises(CorpusConflict):
        repo.activate(candidate.corpus_id, expected_generation=0, summary_hash=summary,
                      idempotency_key=f"failed-pointer-{candidate.corpus_id}")
    assert repo.version(candidate.corpus_id).state == "validated"
    assert repo.active(candidate.subject_id) is None
    assert all(event.event_kind != "activated" for event in repo.history(candidate.subject_id))
    # The caller can commit other work without accidentally publishing the failed operation.
    assert conn.execute("SELECT 1 AS alive").fetchone()["alive"] == 1


def test_sql_urls_and_genesis_receipt_are_guarded(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    candidate = _candidate(repo)
    _fill(repo, candidate)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE grounding_corpus_documents SET final_url=%s WHERE corpus_version_id=%s",
                         ("https://user:secret@docs.example.org/start", candidate.corpus_id))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE grounding_corpus_source_snapshots SET seed_urls_json=%s WHERE corpus_version_id=%s",
                         ('["https://docs.example.org/start?token=secret"]', candidate.corpus_id))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE grounding_corpus_source_snapshots SET facets_json=%s WHERE corpus_version_id=%s",
                         ('[{"secret": "raw"}]', candidate.corpus_id))

    repo.finalize_validation(candidate.corpus_id, passed=True, expected_generation=0,
                             validation_summary={"status": "passed"}, coverage_summary={},
                             idempotency_key=f"validate-{candidate.corpus_id}")
    summary = repo.version(candidate.corpus_id).summary_hash
    event = repo.activate(candidate.corpus_id, expected_generation=0, summary_hash=summary,
                          idempotency_key=f"activate-{candidate.corpus_id}")
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("DELETE FROM grounding_active_corpora WHERE subject_id=%s", (candidate.subject_id,))
    assert repo.active(candidate.subject_id).activation_event_id == event.event_id


def test_genesis_pointer_needs_activation_not_rollback_receipt(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    candidate = _validated(repo)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE grounding_corpus_versions SET state='published', generation=2, published_at=now() WHERE id=%s",
                         (candidate.corpus_id,))
            event_id = uuid4()
            conn.execute(
                """INSERT INTO grounding_corpus_events
                   (id,corpus_version_id,subject_id,event_kind,operation_id,idempotency_key,request_hash,
                    summary_hash,expected_generation,observed_generation)
                   VALUES (%s,%s,%s,'rolled_back',%s,%s,%s,%s,0,1)""",
                (event_id, candidate.corpus_id, candidate.subject_id, uuid4(), f"forged-{event_id}",
                 _digest("forged-request"), repo.version(candidate.corpus_id).summary_hash),
            )
            conn.execute(
                """INSERT INTO grounding_active_corpora
                   (subject_id,corpus_version_id,generation,activation_event_id,activation_event_kind)
                   VALUES (%s,%s,1,%s,'rolled_back')""",
                (candidate.subject_id, candidate.corpus_id, event_id),
            )
    assert repo.version(candidate.corpus_id).state == "validated"
    assert repo.active(candidate.subject_id) is None


def test_operator_metadata_rejects_secret_and_nested_json(conn) -> None:  # type: ignore[no-untyped-def]
    repo = CorpusRepository(conn)
    candidate = _candidate(repo)
    with pytest.raises(ValueError):
        repo.finalize_validation(candidate.corpus_id, passed=False, expected_generation=0,
                                 validation_summary={"api_token": "secret"}, coverage_summary={},
                                 idempotency_key=f"unsafe-{candidate.corpus_id}")
    assert repo.version(candidate.corpus_id).state == "candidate"
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("UPDATE grounding_corpus_versions SET generation=1, validation_summary_json=%s WHERE id=%s",
                         ('{"safe": {"nested": "secret"}}', candidate.corpus_id))
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                """INSERT INTO grounding_corpus_events
                   (id,corpus_version_id,subject_id,event_kind,operation_id,idempotency_key,request_hash,counts_json)
                   VALUES (%s,%s,%s,'reindex_completed',%s,%s,%s,%s)""",
                (uuid4(), candidate.corpus_id, candidate.subject_id, uuid4(), f"bad-counts-{candidate.corpus_id}",
                 _digest("bad-counts"), '{"secret": "raw"}'),
            )


def test_candidate_child_edit_serializes_with_validation(isolated_bootstrap: None) -> None:
    dsn = get_settings().database_url
    with psycopg.connect(dsn, row_factory=dict_row) as setup:
        candidate = _candidate(CorpusRepository(setup))
        _fill(CorpusRepository(setup), candidate)
    started = Event()

    def seal() -> None:
        with psycopg.connect(dsn, row_factory=dict_row) as other:
            started.set()
            CorpusRepository(other).finalize_validation(
                candidate.corpus_id, passed=True, expected_generation=0,
                validation_summary={"status": "passed"}, coverage_summary={},
                idempotency_key=f"seal-after-edit-{candidate.corpus_id}",
            )

    with psycopg.connect(dsn, row_factory=dict_row) as editor:
        with ThreadPoolExecutor(max_workers=1) as pool:
            editor.execute(
                "UPDATE grounding_corpus_chunks SET content=%s, chunk_hash=%s WHERE corpus_version_id=%s",
                ("Updated candidate text.", _digest("Updated candidate text."), candidate.corpus_id),
            )
            future = pool.submit(seal)
            started_ok = started.wait(timeout=3)
            sleep(0.1)
            blocked = not future.done()
            editor.commit()
            future.result(timeout=10)
            assert started_ok and blocked, "validation must wait for the child edit's parent lock"
    with psycopg.connect(dsn, row_factory=dict_row) as check:
        assert CorpusRepository(check).version(candidate.corpus_id).state == "validated"
        assert check.execute("SELECT content FROM grounding_corpus_chunks WHERE corpus_version_id=%s",
                             (candidate.corpus_id,)).fetchone()["content"] == "Updated candidate text."
