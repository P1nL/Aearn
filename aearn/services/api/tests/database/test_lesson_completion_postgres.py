"""Opt-in SQL597 receiver tests on a Main-prepared, schema-only local test DB.

No import-time connection, bootstrap, DDL, provider, or cleanup. The original
seven receiver cases keep synthetic/current=false evidence. The two opt-in
http_fetch owner cases consume Main's already-ingested real source and exercise
complete_stage/atomic publication with a fixed author, never a real model.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from typing import cast
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning import lesson_authoring as authoring
from app.services.learning import lesson_completion_stages as stages
from app.services.learning.lesson_contracts import (
    LESSON_COMPLETION_VERSION, LESSON_EVIDENCE_VERSION, LessonDocumentDraft,
    LessonEvidenceUnit, LessonSourceSnapshot, canonical_source_set_hash,
)
from app.services.learning.lesson_quality import LessonQualityReport
from app.services.learning.lesson_repository import (
    LessonAuthoringRunRecord, LessonScopeRecord, LessonVersionConflict,
    PostgresLessonDocumentRepository,
)
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.llm.completion_policy import resolve_completion_stage_policy
from tests.support.learning_track_support import sample_plan
from tests.support.lesson_document_support import author_candidate_payload, sample_source_snapshot


_URL_ENV = "AEARN_COMPLETION_TEST_DATABASE_URL"
_REQUIRED_TABLES = (
    "users", "tutor_learning_tracks", "tutor_track_plan_revisions",
    "tutor_track_active_plans", "tutor_track_plan_modules", "tutor_track_plan_nodes",
    "tutor_track_node_progress", "tutor_mastery_states", "grounding_chunks",
    "tutor_lesson_authoring_runs", "tutor_lesson_authoring_stage_attempts",
    "tutor_lesson_documents", "tutor_lesson_source_snapshots",
    "tutor_lesson_block_citations", "tutor_lesson_gate_slots",
)


def _connection_options() -> dict[str, str]:
    raw = os.environ.get(_URL_ENV)
    if raw is None:
        pytest.skip(f"Set {_URL_ENV} explicitly to a Main-prepared schema-only test database")
    try:
        url = urlsplit(raw)
        database = unquote(url.path.removeprefix("/"))
        port = url.port or 5432
        if (url.scheme not in {"postgresql", "postgres"}
                or url.hostname not in {"localhost", "127.0.0.1"}
                or not re.fullmatch(r"aearn_completion_b_test_[a-z0-9_]+", database)
                or not url.username or not 1 <= port <= 65535 or url.query or url.fragment):
            raise ValueError
    except ValueError:
        # Never print the supplied URL/credentials or fall back to DATABASE_URL.
        raise ValueError(f"Unsafe {_URL_ENV}: require an explicit local aearn_completion_b_test_* URL without query/fragment") from None
    return {
        "host": cast(str, url.hostname), "hostaddr": "127.0.0.1", "port": str(port),
        "dbname": database, "user": unquote(cast(str, url.username)),
        "password": unquote(url.password or ""), "passfile": os.devnull,
        "connect_timeout": "3", "application_name": "completion-b-lesson-pg-test",
        "options": "-c search_path=public -c statement_timeout=10000 -c lock_timeout=2000",
    }


@dataclass
class LessonTestDatabase:
    options: dict[str, str] = field(repr=False)
    users: set[str] = field(default_factory=set)

    @contextmanager
    def connect(self) -> Iterator[Connection[dict[str, object]]]:
        # Explicit options also prevent libpq environment/service routing from
        # replacing the validated loopback host and database name.
        with psycopg.connect(make_conninfo(**self.options), autocommit=True, row_factory=dict_row) as conn:
            row = conn.execute("SELECT current_database() AS name").fetchone()
            assert row is not None and row["name"] == self.options["dbname"]
            yield conn


@pytest.fixture
def lesson_db() -> LessonTestDatabase:
    db = LessonTestDatabase(_connection_options())
    with db.connect() as conn:
        missing = conn.execute(
            "SELECT name FROM unnest(%s::text[]) AS required(name) WHERE to_regclass('public.' || name) IS NULL",
            (list(_REQUIRED_TABLES),),
        ).fetchall()
        assert not missing, f"Main must prepare the schema first; missing tables: {[row['name'] for row in missing]}"
        # Fail, never bootstrap or skip, when the isolated clone lacks SQL597.
        conn.execute("SELECT completion_contract_version FROM tutor_lesson_authoring_runs LIMIT 0")
        conn.execute("SELECT evidence_schema_version, evidence_units_json FROM tutor_lesson_source_snapshots LIMIT 0")
    return db  # Intentional audit retention; no teardown deletes.


def _now(conn: Connection[dict[str, object]]) -> datetime:
    row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
    assert row is not None and isinstance(row["now"], datetime)
    return row["now"]


def _snapshot() -> LessonSourceSnapshot:
    text = "Synthetic fixture: 名称绑定值; assignment binds a name to a value. " * 30
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    document_digest = hashlib.sha256(("Synthetic fixture document\n" + text).encode("utf-8")).hexdigest()
    return replace(sample_source_snapshot(), grounding_chunk_id=f"completion-b-test-{uuid4().hex}",
        document_content_hash=document_digest, chunk_content_hash=digest,
        evidence_excerpt=" ".join(text.split())[:1200], evidence_schema_version=LESSON_EVIDENCE_VERSION,
        evidence_units=(LessonEvidenceUnit(text, digest, 0, len(text.encode("utf-8"))),))


def _new_scope(db: LessonTestDatabase, *, user_id: str | None = None) -> LessonScopeRecord:
    with db.connect() as conn, conn.transaction():
        if user_id is None:
            user_id = str(uuid4())
            conn.execute("INSERT INTO users (id, display_name) VALUES (%s, %s)",
                (user_id, f"completion-b-lesson-pg:{user_id}"))
            db.users.add(user_id)
        assert user_id in db.users, "Only users created by this fixture are writable"
        plan = sample_plan()
        plan = replace(plan, modules=(replace(plan.modules[0], nodes=(plan.modules[0].nodes[0],)),))
        track_id = PostgresLearningTrackRepository(conn).create_track(
            user_id=user_id, language_id="python", goal_text="Synthetic Lesson stage receiver test",
            target_level="beginner", plan=plan,
        )
        scope = PostgresLessonDocumentRepository(conn).read_scope(
            user_id=user_id, track_id=track_id, knowledge_key="python.variables")
    print(f"synthetic Lesson scope retained: user={user_id} track={track_id}")
    return scope


@dataclass(frozen=True)
class StageWork:
    scope: LessonScopeRecord
    run: LessonAuthoringRunRecord
    snapshot: LessonSourceSnapshot
    request: authoring.LessonAuthoringRequest
    dependency: dict[str, object]
    document: LessonDocumentDraft
    quality: LessonQualityReport
    candidate: dict[str, object]
    standard_attempt_id: str | None = None


def _work(db: LessonTestDatabase, *, scope: LessonScopeRecord | None = None,
          snapshot: LessonSourceSnapshot | None = None) -> StageWork:
    scope, snapshot = scope or _new_scope(db), snapshot or _snapshot()
    with db.connect() as conn, conn.transaction():
        repo = PostgresLessonDocumentRepository(conn)
        run, replayed = repo.create_or_replay_authoring_run(
            scope=scope, run_kind="prepare", idempotency_key=f"pg-fixture-{uuid4().hex}",
            request_hash=authoring._hash_json({"fixture": uuid4().hex}),
            profile_hash=authoring._hash_json(repo.read_personalization_context(scope)),
            completion_contract_version=LESSON_COMPLETION_VERSION,
        )
        assert not replayed
    with db.connect() as conn, conn.transaction():
        repo = PostgresLessonDocumentRepository(conn)
        claimed = repo.claim_authoring_run(run_id=run.run_id, owner="lesson-pg-fixture", now=_now(conn))
        assert claimed is not None
        repo.mark_authoring_running(run_id=run.run_id, lease_generation=claimed.lease_generation)
        repo.set_authoring_source_set(run_id=run.run_id, lease_generation=claimed.lease_generation,
            source_set_hash=canonical_source_set_hash((snapshot,)))
        run = repo.read_authoring_run(run_id=run.run_id)
    evidence, handles = authoring._authoring_evidence((snapshot,))
    request = authoring.LessonAuthoringRequest(
        "standard", scope.language_id, scope.knowledge_key, scope.node_title,
        scope.goal_text, scope.target_level, scope.required_capabilities, "unseen", 0.0, evidence,
        citation_handles=tuple(handles.items()), completion_contract_version=LESSON_COMPLETION_VERSION,
    )
    policy = resolve_completion_stage_policy(Settings(llm_type="disabled",
        tutor_default_context_window_tokens=64_000, tutor_default_output_reserve_tokens=16_384), "lesson_authoring")
    dependency = stages.stage_dependency(run=run, scope=scope, snapshots=(snapshot,),
        stage_kind="standard", policy={**asdict(policy), "provider": "synthetic", "model": "not-called"})
    candidate = author_candidate_payload(title=scope.node_title)
    document, quality, feedback = stages._validate(candidate, request, handles, (snapshot,), 1)
    assert document is not None and quality is not None and feedback is None and quality.passed
    return StageWork(scope, run, snapshot, request, dependency, document, quality, candidate)


def _begin(conn: Connection[dict[str, object]], work: StageWork) -> dict[str, object] | None:
    return PostgresLessonDocumentRepository(conn).begin_completion_attempt(
        run=work.run, stage_kind=work.request.document_kind, dependency=work.dependency,
        request_hash=authoring._hash_json(authoring._safe_request_payload(work.request)),
        standard_attempt_id=work.standard_attempt_id, now=_now(conn),
    )


def _save(conn: Connection[dict[str, object]], work: StageWork, intent: Mapping[str, object],
          *, unknown: bool = False) -> dict[str, object]:
    # A receiver fixture, not a fabricated provider receipt or charged request.
    result: dict[str, object] = {"synthetic_fixture": True, "physical_dispatch_attempts": 0, "usage": None}
    if not unknown:
        result.update(candidate=work.candidate, candidate_hash=authoring._hash_json(work.candidate))
    return PostgresLessonDocumentRepository(conn).save_completion_result(
        attempt=intent, result=result, feedback={}, execution_outcome="unknown" if unknown else "known",
        usage_status="unknown", now=_now(conn))


def _decide(conn: Connection[dict[str, object]], work: StageWork, saved: Mapping[str, object]) -> dict[str, object]:
    return PostgresLessonDocumentRepository(conn).decide_completion_result(
        run=work.run, attempt=saved, document=work.document,
        quality=work.quality.safe_summary(), now=_now(conn))


def _saved(db: LessonTestDatabase, work: StageWork, *, unknown: bool = False) -> dict[str, object]:
    with db.connect() as conn, conn.transaction():
        intent = _begin(conn, work)
        assert intent is not None
    with db.connect() as conn, conn.transaction():
        return _save(conn, work, intent, unknown=unknown)


def _accepted(db: LessonTestDatabase, work: StageWork) -> dict[str, object]:
    saved = _saved(db, work)
    with db.connect() as conn, conn.transaction():
        return _decide(conn, work, saved)


def _row(conn: Connection[dict[str, object]], attempt_id: object) -> dict[str, object] | None:
    return conn.execute("SELECT * FROM tutor_lesson_authoring_stage_attempts WHERE id = %s", (attempt_id,)).fetchone()


def _expire_own_lease(conn: Connection[dict[str, object]], work: StageWork) -> None:
    # Shorten only this freshly generated synthetic lease; never extend it or
    # alter immutable intent/result timestamps to simulate execution closure.
    row = conn.execute("""UPDATE tutor_lesson_authoring_runs
        SET lease_expires_at = clock_timestamp() - interval '1 second'
        WHERE id = %s AND user_id = %s AND lease_generation = %s RETURNING id""",
        (work.run.run_id, work.run.user_id, work.run.lease_generation)).fetchone()
    assert row is not None


def test_result_requires_prior_commit_and_recovers_on_independent_connection(lesson_db: LessonTestDatabase) -> None:
    work = _work(lesson_db)
    with lesson_db.connect() as writer, lesson_db.connect() as observer:
        with writer.transaction():
            intent = _begin(writer, work)
            assert intent is not None and _row(observer, intent["id"]) is None
        visible = _row(observer, intent["id"])
        assert visible is not None and visible["state"] == "intent"
        with writer.transaction():
            saved = _save(writer, work, intent)
            visible = _row(observer, intent["id"])
            assert visible is not None and visible["state"] == "intent"
            with pytest.raises(psycopg.errors.CheckViolation, match="Lesson decision"):
                with writer.transaction():  # Savepoint preserves the real result write.
                    _decide(writer, work, saved)
        visible = _row(observer, intent["id"])
        assert visible is not None and visible["state"] == "result_saved"
        assert visible["result_transaction_id"] is not None
        with writer.transaction():
            _expire_own_lease(writer, work)
    with lesson_db.connect() as successor, successor.transaction():
        repo = PostgresLessonDocumentRepository(successor)
        reclaimed = repo.claim_authoring_run(run_id=work.run.run_id, owner="lesson-pg-successor", now=_now(successor))
        assert reclaimed is not None and reclaimed.state == "running"
        assert reclaimed.lease_generation == work.run.lease_generation + 1
    work = replace(work, run=reclaimed)
    with lesson_db.connect() as receiver, receiver.transaction():
        durable = _row(receiver, saved["id"])
        assert durable is not None
        # No source admission is forged: the schema-only sample is not current.
        assert not PostgresLessonDocumentRepository(receiver).evidence_is_current((work.snapshot,))
        accepted = _decide(receiver, work, durable)
        assert accepted["state"] == "accepted"
        assert accepted["decision_lease_generation"] == reclaimed.lease_generation
        assert accepted["result_json"] == durable["result_json"]
    with lesson_db.connect() as reader:
        final = _row(reader, saved["id"])
        assert final is not None and final["document_hash"] == work.document.content_hash
        assert PostgresLessonDocumentRepository(reader).read_authoring_run(run_id=work.run.run_id).assignment_id is None


def test_saved_result_cannot_be_terminalized_as_failed(lesson_db: LessonTestDatabase) -> None:
    work = _work(lesson_db)
    saved = _saved(lesson_db, work)
    with lesson_db.connect() as conn:
        with pytest.raises(LessonVersionConflict, match="reconciliation"):
            with conn.transaction():
                PostgresLessonDocumentRepository(conn).fail_authoring_run(run_id=work.run.run_id,
                    lease_generation=work.run.lease_generation, failure_code="FIXTURE", failure_message="fixture", now=_now(conn))
        with pytest.raises(psycopg.errors.CheckViolation, match="Committed Lesson results"):
            with conn.transaction():
                conn.execute("""UPDATE tutor_lesson_authoring_runs
                    SET state = 'failed', lease_owner = NULL, lease_expires_at = NULL, terminal_at = clock_timestamp()
                    WHERE id = %s AND user_id = %s""", (work.run.run_id, work.run.user_id))
        assert PostgresLessonDocumentRepository(conn).read_authoring_run(run_id=work.run.run_id).state == "running"
    with lesson_db.connect() as conn, conn.transaction():
        assert _decide(conn, work, saved)["state"] == "accepted"


def test_standard_reuse_is_exact_same_user_course_dependency(lesson_db: LessonTestDatabase) -> None:
    original = _work(lesson_db)
    accepted = _accepted(lesson_db, original)
    repeat = _work(lesson_db, scope=original.scope, snapshot=original.snapshot)
    assert repeat.dependency == original.dependency
    with lesson_db.connect() as conn, conn.transaction():
        repo = PostgresLessonDocumentRepository(conn)
        rows = repo.read_completion_attempts(run=repeat.run, stage_kind="standard", dependency=repeat.dependency)
        assert len(rows) == 1 and rows[0]["id"] == accepted["id"] and rows[0]["state"] == "accepted"
        assert _begin(conn, repeat) is None
        assert repo.read_authoring_run(run_id=repeat.run.run_id).attempt_count == 0
        assert not repo.read_completion_attempts(run=repeat.run, stage_kind="standard",
            dependency={**repeat.dependency, "node_description": "different applicability"})
    for scope in (_new_scope(lesson_db, user_id=original.run.user_id), _new_scope(lesson_db)):
        other = _work(lesson_db, scope=scope, snapshot=original.snapshot)
        with lesson_db.connect() as conn, conn.transaction():
            repo = PostgresLessonDocumentRepository(conn)
            assert not repo.read_completion_attempts(run=other.run, stage_kind="standard", dependency=original.dependency)
            assert _begin(conn, other) is not None


def _raw_intent(conn: Connection[dict[str, object]], work: StageWork, *, seconds: float = 600) -> dict[str, object]:
    """Direct receiver fixture for a legal short request window or a guard denial."""
    deadline = _now(conn) + timedelta(seconds=seconds)
    row = conn.execute("""INSERT INTO tutor_lesson_authoring_stage_attempts (
        run_id, user_id, track_id, knowledge_key, stage_kind, attempt_index, stage_attempt_index,
        lease_generation, dependency_hash, dependency_json, request_hash, request_deadline_at, result_deadline_at
        ) VALUES (%s,%s,%s,%s,'standard',1,1,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (work.run.run_id, work.run.user_id, work.run.track_id, work.run.knowledge_key,
         work.run.lease_generation, authoring._hash_json(work.dependency), Jsonb(work.dependency),
         authoring._hash_json(authoring._safe_request_payload(work.request)), deadline, deadline + timedelta(seconds=60))).fetchone()
    assert row is not None
    conn.execute("UPDATE tutor_lesson_authoring_runs SET attempt_count = 1 WHERE id = %s AND user_id = %s",
        (work.run.run_id, work.run.user_id))
    return row


@pytest.mark.parametrize("state", ["outcome_unknown", "expired_intent"])
def test_unclosed_execution_blocks_reclaim_and_new_dispatch_intent(lesson_db: LessonTestDatabase, state: str) -> None:
    work = _work(lesson_db)
    if state == "outcome_unknown":
        attempt = _saved(lesson_db, work, unknown=True)
    else:
        with lesson_db.connect() as conn, conn.transaction():
            attempt = _raw_intent(conn, work, seconds=0.1)
        time.sleep(0.15)  # Real short deadline expiry, not an immutable timestamp rewrite.
        with lesson_db.connect() as conn:
            assert cast(datetime, attempt["request_deadline_at"]) < _now(conn)
    with lesson_db.connect() as conn, conn.transaction():
        _expire_own_lease(conn, work)
    with lesson_db.connect() as conn, conn.transaction():
        assert PostgresLessonDocumentRepository(conn).claim_authoring_run(
            run_id=work.run.run_id, owner="must-not-reclaim", now=_now(conn)) is None
    fresh = _work(lesson_db, scope=work.scope, snapshot=work.snapshot)
    with lesson_db.connect() as conn:
        with pytest.raises(LessonVersionConflict, match="reconciliation"):
            with conn.transaction():
                _begin(conn, fresh)
        with pytest.raises(psycopg.errors.CheckViolation, match="already has"):
            with conn.transaction():
                _raw_intent(conn, fresh)
        rows = PostgresLessonDocumentRepository(conn).read_completion_attempts(
            run=fresh.run, stage_kind="standard", dependency=fresh.dependency)
        assert len(rows) == 1 and rows[0]["id"] == attempt["id"]
        assert rows[0]["state"] == ("intent" if state == "expired_intent" else state)


def _copy_snapshot(conn: Connection[dict[str, object]], document_id: str, citation_id: str,
                   version: str | None, units: list[dict[str, object]]) -> dict[str, object]:
    row = conn.execute("""INSERT INTO tutor_lesson_source_snapshots (
        document_id, user_id, track_id, knowledge_key, citation_id, source_id, display_name,
        provider, trust_tier, source_type, source_version_label, source_version_kind, canonical_url,
        section_path_json, grounding_chunk_id, document_content_hash, chunk_content_hash,
        fetched_at, snapshotted_at, evidence_excerpt, evidence_schema_version, evidence_units_json)
        SELECT document_id, user_id, track_id, knowledge_key, %s, source_id, display_name,
        provider, trust_tier, source_type, source_version_label, source_version_kind, canonical_url,
        section_path_json, grounding_chunk_id, document_content_hash, chunk_content_hash,
        fetched_at, snapshotted_at, evidence_excerpt, %s, %s
        FROM tutor_lesson_source_snapshots WHERE document_id = %s AND citation_id = %s RETURNING *""",
        ("cite_" + uuid4().hex[:16], version, Jsonb(units), document_id, citation_id)).fetchone()
    assert row is not None
    return row


def test_full_evidence_roundtrip_and_null_version_guard(lesson_db: LessonTestDatabase) -> None:
    work = _work(lesson_db)
    with lesson_db.connect() as conn, conn.transaction():
        document_id = PostgresLessonDocumentRepository(conn)._insert_or_reuse_document(
            document_kind="standard", document=work.document, snapshots=(work.snapshot,),
            user_id=None, track_id=None, active_plan_revision_id=None, standard_document_id=None, profile_hash=None,
            generator_version=f"completion-pg-fixture-{uuid4().hex}", policy_version="synthetic-receiver-only",
            source_set_hash=canonical_source_set_hash((work.snapshot,)),
            change_summary={"synthetic_fixture": True}, quality_summary=work.quality.safe_summary())
    with lesson_db.connect() as conn:
        loaded, = PostgresLessonDocumentRepository(conn).load_source_snapshots(document_id=document_id)
        assert loaded.evidence_units == work.snapshot.evidence_units
        assert len(loaded.evidence_excerpt) == 1200
        unit = loaded.evidence_units[0]
        assert unit.end_byte == len(unit.text.encode("utf-8")) > len(unit.text)
        units = [unit.payload()]
        with pytest.raises(psycopg.errors.CheckViolation) as rejected:
            with conn.transaction():
                _copy_snapshot(conn, document_id, loaded.citation_id, None, units)
        assert rejected.value.diag.constraint_name == "chk_lesson_evidence_units_version"
        with pytest.raises(psycopg.errors.CheckViolation, match="bytes/hash/scope"):
            with conn.transaction():
                _copy_snapshot(conn, document_id, loaded.citation_id, LESSON_EVIDENCE_VERSION,
                    [{**units[0], "end_byte": unit.end_byte - 1}])
        with conn.transaction():
            legacy = _copy_snapshot(conn, document_id, loaded.citation_id, None, [])
        assert legacy["evidence_schema_version"] is None and legacy["evidence_units_json"] == []


def test_scoped_purge_requires_capability_and_respects_deferred_self_fk(lesson_db: LessonTestDatabase) -> None:
    standard = _work(lesson_db)
    parent = _accepted(lesson_db, standard)
    request = replace(standard.request, document_kind="personalized", standard_document=standard.document)
    with lesson_db.connect() as conn:
        personalization = PostgresLessonDocumentRepository(conn).read_personalization_context(standard.scope)
    dependency = stages.stage_dependency(run=standard.run, scope=standard.scope, snapshots=(standard.snapshot,),
        stage_kind="personalized", policy=cast(Mapping[str, object], standard.dependency["stage_policy"]),
        standard_dependency_hash=authoring._hash_json(standard.dependency),
        standard_document_hash=standard.document.content_hash, personalization=personalization)
    candidate = author_candidate_payload(personalized=True, title=standard.document.title)
    document, quality, feedback = stages._validate(candidate, request, dict(request.citation_handles), (standard.snapshot,), 1)
    assert document is not None and quality is not None and feedback is None
    personal = replace(standard, request=request, dependency=dependency, document=document,
        quality=quality, candidate=candidate, standard_attempt_id=str(parent["id"]))
    child = _accepted(lesson_db, personal)
    assert child["standard_attempt_id"] == parent["id"]
    with lesson_db.connect() as conn:
        with pytest.raises(psycopg.errors.CheckViolation, match="confirmed user purge"):
            with conn.transaction():
                conn.execute("DELETE FROM tutor_lesson_authoring_stage_attempts WHERE id = %s AND user_id = %s",
                    (parent["id"], standard.run.user_id))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)", (standard.run.user_id,))
                row = conn.execute("SELECT tutor_learning_track_purge_allowed(%s) AS allowed", (standard.run.user_id,)).fetchone()
                assert row is not None and row["allowed"] is True
                conn.execute("DELETE FROM tutor_lesson_authoring_stage_attempts WHERE id = %s AND user_id = %s",
                    (parent["id"], standard.run.user_id))  # Fails at COMMIT, not a disabled constraint.
        assert _row(conn, parent["id"]) is not None and _row(conn, child["id"]) is not None
        with conn.transaction():
            conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)", (standard.run.user_id,))
            for row_id in (parent["id"], child["id"]):  # Parent first deliberately exercises DEFERRABLE NO ACTION.
                deleted = conn.execute("DELETE FROM tutor_lesson_authoring_stage_attempts WHERE id = %s AND user_id = %s RETURNING id",
                    (row_id, standard.run.user_id)).fetchone()
                assert deleted is not None
        assert _row(conn, parent["id"]) is None and _row(conn, child["id"]) is None
        assert PostgresLessonDocumentRepository(conn).read_authoring_run(run_id=standard.run.run_id).attempt_count == 2


# The original seven receiver cases above intentionally keep synthetic/current=false
# evidence. The following owner cases instead require Main's separately authorized,
# already-ingested single http_fetch capture; they never fetch or seed sources.
_LESSON_HTTP_SEED = "https://docs.python.org/3/tutorial/introduction.html"
_LESSON_HTTP_KEY = "python.width"
_LESSON_HTTP_TITLE = "Python width and height assignment"


@dataclass(frozen=True)
class HttpFetchLessonOwner:
    db: LessonTestDatabase
    settings: Settings = field(repr=False)
    scope: LessonScopeRecord
    snapshots: tuple[LessonSourceSnapshot, ...]

    def clock(self) -> datetime:
        with self.db.connect() as conn:
            return _now(conn)

    def prepare(self) -> LessonAuthoringRunRecord:
        from app.services.learning.lesson_service import LessonDocumentService

        with self.db.connect() as conn:
            result = LessonDocumentService(conn).prepare(
                user_id=self.scope.user_id, track_id=self.scope.track_id, knowledge_key=self.scope.knowledge_key,
                expected_track_version=self.scope.track_version, expected_progress_version=self.scope.progress_version,
                idempotency_key=f"http-source-owner-{uuid4().hex}", completion_driven=True,
            )
            assert result["should_dispatch"] is True
            projection = cast(dict[str, object], result["authoring_run"])
            run = PostgresLessonDocumentRepository(conn).read_authoring_run(run_id=str(projection["run_id"]))
            assert run.state == "pending" and run.completion_contract_version == LESSON_COMPLETION_VERSION
            return run


@pytest.fixture
def http_fetch_lesson_owner(lesson_db: LessonTestDatabase, monkeypatch: pytest.MonkeyPatch) -> HttpFetchLessonOwner:
    from app.services.grounding.grounding_index_repository import _chunk_from_row
    from app.services.grounding.grounding_processing import is_admissible_lesson_source
    from app.services.grounding.grounding_sources import get_grounding_source
    from app.services.learning import lesson_service

    source = get_grounding_source("python-tutorial")
    assert source is not None and _LESSON_HTTP_SEED in source.seed_urls
    required = ("Main must first ingest the already-fetched python-tutorial introduction.html "
                "http_fetch capture into this dedicated TEST database; this test will not fetch/reindex or invent current provenance")
    # Use the original coverage retrieval and source admission unchanged. A width
    # node selects the actual Numbers/assignment example rather than unrelated
    # plural-'variables' text from string concatenation.
    with lesson_db.connect() as conn:
        try:
            snapshots = authoring._load_evidence_snapshots(
                conn, "python", _LESSON_HTTP_KEY, _LESSON_HTTP_TITLE, _now(conn),
                completion_driven=True, required_topics=(_LESSON_HTTP_KEY,),
            )
        except authoring.LessonAuthoringFailure:
            pytest.fail(required, pytrace=False)
        assert snapshots, required
        for snapshot in snapshots:
            assert (snapshot.source_id, snapshot.canonical_url) == (source.source_id, _LESSON_HTTP_SEED), required
            row = conn.execute("SELECT * FROM grounding_chunks WHERE chunk_id = %s", (snapshot.grounding_chunk_id,)).fetchone()
            assert row is not None, required
            chunk = _chunk_from_row(row)
            assert chunk.provenance.kind == "http_fetch" and is_admissible_lesson_source(chunk), required
            assert chunk.provenance.requested_url == _LESSON_HTTP_SEED, required
            assert snapshot.evidence_schema_version == LESSON_EVIDENCE_VERSION
            assert snapshot.evidence_units[0].text == chunk.text and "width" in chunk.text.casefold()
        assert PostgresLessonDocumentRepository(conn).evidence_is_current(snapshots), required

    # New private plan only; no mutation or re-tagging of persisted source rows.
    with lesson_db.connect() as conn, conn.transaction():
        user_id = str(uuid4())
        conn.execute("INSERT INTO users (id, display_name) VALUES (%s, %s)",
            (user_id, f"completion-b-lesson-http-owner:{user_id}"))
        lesson_db.users.add(user_id)
        plan = sample_plan()
        node = replace(plan.modules[0].nodes[0], knowledge_key=_LESSON_HTTP_KEY,
            title=_LESSON_HTTP_TITLE, description="Bind and read numeric variables using width and height.")
        plan = replace(plan, modules=(replace(plan.modules[0], nodes=(node,)),))
        track_id = PostgresLearningTrackRepository(conn).create_track(user_id=user_id, language_id="python",
            goal_text="Understand numeric assignment using width and height", target_level="beginner", plan=plan)
        scope = PostgresLessonDocumentRepository(conn).read_scope(user_id=user_id, track_id=track_id, knowledge_key=node.knowledge_key)
    settings = Settings(llm_type="disabled", tutor_completion_driven_enabled=True,
        tutor_default_context_window_tokens=64_000, tutor_default_output_reserve_tokens=16_384)
    # Connection/configuration injection only. These are still real independent
    # PG connections, real policies, heartbeat, repositories and source fences.
    monkeypatch.setattr(authoring, "connect", lesson_db.connect)
    monkeypatch.setattr(stages, "connect", lesson_db.connect)
    monkeypatch.setattr(stages, "get_settings", lambda: settings)
    monkeypatch.setattr(lesson_service, "get_settings", lambda: settings)
    print(f"http_fetch Lesson owner retained: user={user_id} track={track_id}")
    return HttpFetchLessonOwner(lesson_db, settings, scope, snapshots)


@dataclass
class FixedHttpSourceLessonAuthor:
    """Fixed typed content, real citations; deliberately zero model/HTTP calls."""

    owner: HttpFetchLessonOwner
    run_id: str
    calls: list[str] = field(default_factory=list)

    def author(self, request: authoring.LessonAuthoringRequest) -> authoring.LessonAuthoringResponse:
        from app.agents.harness.contracts import TutorExecutionProfile
        from app.services.llm.http_execution import current_http_execution

        execution = current_http_execution()
        assert execution is not None and execution.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1
        assert execution.max_attempts == 1 and 0 < execution.before_send() <= 600
        evidence, handles = authoring._authoring_evidence(self.owner.snapshots)
        assert request.evidence == evidence and request.previous_attempt_feedback is None
        with self.owner.db.connect() as conn:
            repository = PostgresLessonDocumentRepository(conn)
            assert repository.evidence_is_current(self.owner.snapshots)
            # An independent connection must see the committed intent, no early
            # assignment, and (for personalization) the already accepted standard.
            rows = conn.execute("""SELECT * FROM tutor_lesson_authoring_stage_attempts
                WHERE run_id = %s AND user_id = %s ORDER BY attempt_index""",
                (self.run_id, self.owner.scope.user_id)).fetchall()
            assert rows and rows[-1]["stage_kind"] == request.document_kind and rows[-1]["state"] == "intent"
            assert rows[-1]["request_hash"] == authoring._hash_json(authoring._safe_request_payload(request))
            if request.document_kind == "personalized":
                assert len(rows) == 2 and rows[0]["stage_kind"] == "standard" and rows[0]["state"] == "accepted"
                assert request.standard_document is not None and request.standard_document.content_hash == rows[0]["document_hash"]
            else:
                assert len(rows) == 1
            assert not conn.execute("SELECT id FROM tutor_lesson_assignments WHERE user_id = %s AND track_id = %s",
                (self.owner.scope.user_id, self.owner.scope.track_id)).fetchall()
            assert repository.read_authoring_run(run_id=self.run_id).state == "running"
        candidate = author_candidate_payload(personalized=request.document_kind == "personalized", title=request.title)
        candidate["knowledge_key"] = request.knowledge_key
        candidate["coverage_keys"] = [request.knowledge_key]
        for block in cast(list[dict[str, object]], candidate["blocks"]):
            if block.get("citation_ids"):
                block["citation_ids"] = [request.evidence[0].handle]
            if "coverage_keys" in block:
                block["coverage_keys"] = [request.knowledge_key]
            if block["type"] == "concept":
                block["paragraphs"] = ["用等号将数值保存到 width 和 height，再在表达式中读取它们。"
                    if request.document_kind == "standard" else "结合你的学习目标，用 width 和 height 计算矩形面积。"]
            elif block["type"] == "authority_note":
                block["statement"] = "使用等号为变量赋值，再在表达式中读取这些变量。"
            elif block["type"] == "code_example":
                block["code"] = "width = 20\nheight = 5 * 9\narea = width * height"
            elif block["type"] == "comparison":
                block["rows"] = [["width", "20"], ["height", "45"]]
            elif block["type"] == "exercise_gate":
                block["gate_key"] = f"{request.knowledge_key}.basic"
                block["required_capabilities"] = [request.knowledge_key]
        # Exercise the original typed parser; handles resolve to the persisted
        # capture's actual citation ids, never the support builder's placeholder.
        typed = authoring._parse_author_candidate(candidate, handles)
        authoring._assert_candidate_identity(typed, request)
        self.calls.append(request.document_kind)
        return authoring.LessonAuthoringResponse(candidate, "synthetic-fixture", "fixed-width-lesson", "fixture")


def _assert_http_owner_published(owner: HttpFetchLessonOwner, run_id: str) -> tuple[LessonAuthoringRunRecord, list[dict[str, object]]]:
    with owner.db.connect() as conn:
        repository = PostgresLessonDocumentRepository(conn)
        run = repository.read_authoring_run(run_id=run_id, user_id=owner.scope.user_id)
        assert run.state == "completed", f"Actual Lesson owner stopped: {run.state} / {run.failure_code}"
        assert run.attempt_count == 2 and run.standard_document_id is not None and run.personalized_document_id is not None
        rows = conn.execute("SELECT * FROM tutor_lesson_authoring_stage_attempts WHERE run_id = %s ORDER BY attempt_index", (run_id,)).fetchall()
        assert [(row["stage_kind"], row["state"]) for row in rows] == [("standard", "accepted"), ("personalized", "accepted")]
        assert rows[1]["standard_attempt_id"] == rows[0]["id"]
        for row in rows:
            assert row["result_transaction_id"] is not None and row["execution_outcome"] == "known"
            assert row["usage_status"] == "unknown"
            assert cast(dict[str, object], row["result_json"])["physical_dispatch_attempts"] == 0
        assignments = conn.execute("SELECT * FROM tutor_lesson_assignments WHERE user_id = %s AND track_id = %s",
            (owner.scope.user_id, owner.scope.track_id)).fetchall()
        assert len(assignments) == 1
        assignment = assignments[0]
        assert str(assignment["id"]) == run.assignment_id and str(assignment["document_id"]) == run.personalized_document_id
        assert assignment["assignment_version"] == 1 and assignment["status"] == "active"
        real_citations = {snapshot.citation_id for snapshot in owner.snapshots}
        for document_id, stage_row in ((run.standard_document_id, rows[0]), (run.personalized_document_id, rows[1])):
            document = repository.load_document(document_id=document_id)
            assert document.content_hash == stage_row["document_hash"]
            cited = {citation for block in document.blocks for citation in block.citation_ids}
            assert cited and cited <= real_citations
            frozen = repository.load_source_snapshots(document_id=document_id)
            assert canonical_source_set_hash(frozen) == canonical_source_set_hash(owner.snapshots) == run.source_set_hash
            assert repository.evidence_is_current(frozen)
            assert {item.citation_id: item.evidence_units for item in frozen} == {
                item.citation_id: item.evidence_units for item in owner.snapshots}
        return run, rows


def test_http_fetch_owner_dispatches_complete_stages_then_publishes_once(http_fetch_lesson_owner: HttpFetchLessonOwner) -> None:
    owner = http_fetch_lesson_owner
    pending = owner.prepare()
    port = FixedHttpSourceLessonAuthor(owner, pending.run_id)
    authoring.dispatch_lesson_authoring_run(pending.run_id, author=port, now=owner.clock)
    assert port.calls == ["standard", "personalized"]
    published, _rows = _assert_http_owner_published(owner, pending.run_id)
    # Completed dispatch is a no-op: no extra author or assignment history.
    authoring.dispatch_lesson_authoring_run(pending.run_id, author=port, now=owner.clock)
    again, _rows = _assert_http_owner_published(owner, pending.run_id)
    assert again.assignment_id == published.assignment_id and port.calls == ["standard", "personalized"]


def test_http_fetch_owner_resumes_committed_standard_without_reauthoring(http_fetch_lesson_owner: HttpFetchLessonOwner) -> None:
    owner = http_fetch_lesson_owner
    pending = owner.prepare()
    with owner.db.connect() as conn, conn.transaction():
        repository = PostgresLessonDocumentRepository(conn)
        claimed = repository.claim_authoring_run(run_id=pending.run_id, owner="http-source-standard-worker", now=_now(conn))
        assert claimed is not None
        running = repository.mark_authoring_running(run_id=pending.run_id, lease_generation=claimed.lease_generation)
        repository.set_authoring_source_set(run_id=running.run_id, lease_generation=running.lease_generation,
            source_set_hash=canonical_source_set_hash(owner.snapshots))
    evidence, handles = authoring._authoring_evidence(owner.snapshots)
    request = authoring.LessonAuthoringRequest(
        "standard", owner.scope.language_id, owner.scope.knowledge_key, owner.scope.node_title,
        owner.scope.goal_text, owner.scope.target_level, owner.scope.required_capabilities, "unseen", 0.0, evidence,
        completion_contract_version=LESSON_COMPLETION_VERSION,
    )
    policy = resolve_completion_stage_policy(owner.settings, "lesson_authoring")
    dependency = stages.stage_dependency(run=running, scope=owner.scope, snapshots=owner.snapshots, stage_kind="standard",
        policy={**asdict(policy), "provider": owner.settings.llm_provider_type, "model": owner.settings.llm_model})
    port = FixedHttpSourceLessonAuthor(owner, running.run_id)
    # No direct synthetic insert/decide: the original complete_stage performs
    # current checks, intent/result COMMITs and independent acceptance itself.
    with stages.LessonLeaseHeartbeat(running, owner.clock) as heartbeat:
        standard, quality, accepted = stages.complete_stage(run=running, request=request, dependency=dependency,
            snapshots=owner.snapshots, handles=handles, port=port, clock=owner.clock, heartbeat=heartbeat)
    assert quality.passed and accepted["document_hash"] == standard.content_hash and port.calls == ["standard"]
    with owner.db.connect() as conn:
        committed = _row(conn, accepted["id"])
        assert committed is not None and committed["state"] == "accepted"
        assert not conn.execute("SELECT id FROM tutor_lesson_assignments WHERE user_id = %s AND track_id = %s",
            (owner.scope.user_id, owner.scope.track_id)).fetchall()
        assert PostgresLessonDocumentRepository(conn).read_authoring_run(run_id=running.run_id).state == "running"
        with conn.transaction():
            # Shorten this new test run's lease only, after its heartbeat exited.
            # The accepted standard and all its evidence/deadlines stay immutable.
            changed = conn.execute("""UPDATE tutor_lesson_authoring_runs
                SET lease_expires_at = clock_timestamp() - interval '1 second'
                WHERE id = %s AND user_id = %s AND lease_generation = %s RETURNING id""",
                (running.run_id, owner.scope.user_id, running.lease_generation)).fetchone()
            assert changed is not None
    authoring.dispatch_lesson_authoring_run(running.run_id, author=port, now=owner.clock)
    finished, rows = _assert_http_owner_published(owner, running.run_id)
    assert finished.lease_generation == running.lease_generation + 1
    assert rows[0] == committed and port.calls == ["standard", "personalized"]
