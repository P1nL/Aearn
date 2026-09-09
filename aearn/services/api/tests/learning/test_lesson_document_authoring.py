from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.grounding.grounding_index_repository import run_and_persist_fixture_grounding_reindex
from app.services.learning.lesson_authoring import (
    LessonAuthoringFailure,
    LessonAuthoringRequest,
    LessonAuthoringResponse,
    dispatch_lesson_authoring_run,
)
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.learning.lesson_service import LessonDocumentService
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.llm.contracts import LLMUsage
from tests.support.learning_track_support import sample_plan
from tests.support.lesson_document_support import author_candidate_payload


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _database_available(), reason="PostgreSQL is required for Lesson authoring tests.")


class FakeLessonAuthor:
    def __init__(self, *, invalid: bool = False, unavailable: bool = False, personalized_title: str = "Python 变量：个性化") -> None:
        self.invalid = invalid
        self.unavailable = unavailable
        self.personalized_title = personalized_title
        self.requests: list[LessonAuthoringRequest] = []

    def author(self, request: LessonAuthoringRequest) -> LessonAuthoringResponse:
        self.requests.append(request)
        if self.unavailable:
            raise LessonAuthoringFailure("LESSON_DOCUMENT_GENERATION_UNAVAILABLE", "课程生成服务当前不可用。", outcome="unavailable")
        candidate = author_candidate_payload(
            personalized=request.document_kind == "personalized",
            title=self.personalized_title if request.document_kind == "personalized" else "Python 变量",
        )
        if self.invalid:
            candidate["unknown"] = True
        return LessonAuthoringResponse(
            candidate=candidate,
            provider="fake-primary",
            model="fake-lesson-author",
            protocol="responses",
            usage=LLMUsage(input_tokens=120, output_tokens=80, total_tokens=200),
        )


@pytest.fixture()
def authoring_scope(monkeypatch: pytest.MonkeyPatch):
    import app.services.learning.lesson_authoring as lesson_authoring

    # These tests deliberately index offline fixtures and inject fake authors.
    # Scope the opt-in to this fixture; runtime and unrelated tests stay default-deny.
    monkeypatch.setattr(
        lesson_authoring, "_load_evidence_snapshots",
        partial(lesson_authoring._load_evidence_snapshots, allow_fixtures_for_tests=True),
    )
    bootstrap_database()
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        run_and_persist_fixture_grounding_reindex(conn)
        user = conn.execute("INSERT INTO users (display_name) VALUES (%s) RETURNING id", (f"Lesson Author {uuid4().hex[:10]}",)).fetchone()
        assert user is not None
        user_id = str(user["id"])
        track_id = PostgresLearningTrackRepository(conn).create_track(
            user_id=user_id, language_id="python", goal_text="Learn Python variables",
            target_level="beginner", plan=sample_plan(),
        )
        service = LessonDocumentService(conn)
        prepared = service.prepare(
            user_id=user_id, track_id=track_id, knowledge_key="python.variables",
            expected_track_version=1, expected_progress_version=1,
            idempotency_key=f"prepare-{uuid4()}",
        )
        conn.commit()
        run = prepared["authoring_run"]
        assert isinstance(run, dict)
        yield conn, user_id, track_id, str(run["run_id"])
        conn.rollback()


def test_dispatch_generates_standard_personalized_assignment_and_safe_attempts(authoring_scope) -> None:
    conn, user_id, track_id, run_id = authoring_scope
    fake = FakeLessonAuthor()
    dispatch_lesson_authoring_run(run_id, author=fake, now=lambda: datetime(2026, 8, 11, tzinfo=UTC))

    state = PostgresLessonDocumentRepository(conn).read_lesson_state(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables",
    )
    assert state["assignment"] is not None
    assert state["document"] is not None
    assert len(fake.requests) == 2
    assert fake.requests[0].evidence[0].handle == "S1"
    assert "https://" not in fake.requests[0].evidence[0].evidence_excerpt

    receipts = conn.execute(
        "SELECT attempt_index, provider, model, protocol, outcome, usage_available, input_tokens, output_tokens FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s ORDER BY attempt_index",
        (run_id,),
    ).fetchall()
    assert [row["attempt_index"] for row in receipts] == [1, 2]
    assert all(row["provider"] == "fake-primary" and row["outcome"] == "success" for row in receipts)
    assert all(row["usage_available"] is True for row in receipts)


def test_invalid_or_unavailable_author_fails_closed_without_partial_document(authoring_scope) -> None:
    conn, user_id, track_id, run_id = authoring_scope
    dispatch_lesson_authoring_run(run_id, author=FakeLessonAuthor(invalid=True))

    run = conn.execute("SELECT state, failure_code FROM tutor_lesson_authoring_runs WHERE id = %s", (run_id,)).fetchone()
    assert run is not None
    assert run["state"] == "failed"
    assert run["failure_code"] == "LESSON_DOCUMENT_INVALID"
    assert conn.execute("SELECT count(*)::int AS count FROM tutor_lesson_documents WHERE user_id = %s", (user_id,)).fetchone()["count"] == 0
    assert conn.execute("SELECT count(*)::int AS count FROM tutor_lesson_assignments WHERE track_id = %s", (track_id,)).fetchone()["count"] == 0


class RepairLessonAuthor(FakeLessonAuthor):
    def __init__(self, failures: set[int], *, quality: bool = False):
        super().__init__()
        self.failures = failures
        self.quality = quality

    def author(self, request):
        response = super().author(request)
        if len(self.requests) in self.failures:
            if self.quality:
                response.candidate["blocks"][2]["citation_ids"] = []
            else:
                response.candidate["untrusted-secret-field"] = "provider-body-secret"
        return response


@pytest.mark.parametrize("failures,quality,expected_calls,completed", [
    ({1}, False, 3, True), ({2}, False, 3, True), ({2}, True, 3, True),
    ({1, 2}, False, 2, False), ({1, 3}, False, 3, False),
])
def test_shared_repair_budget_and_receipts(authoring_scope, failures, quality, expected_calls, completed):
    import json
    from app.services.learning.lesson_authoring import _author_messages
    conn, user_id, track_id, run_id = authoring_scope
    fake = RepairLessonAuthor(failures, quality=quality)
    dispatch_lesson_authoring_run(run_id, author=fake)
    assert len(fake.requests) == expected_calls
    run = conn.execute("SELECT * FROM tutor_lesson_authoring_runs WHERE id = %s", (run_id,)).fetchone()
    assert run["state"] == ("completed" if completed else "failed")
    receipts = conn.execute("SELECT * FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s ORDER BY attempt_index", (run_id,)).fetchall()
    assert len(receipts) == expected_calls
    assert [r["outcome"] for r in receipts] == ["invalid" if i in failures else "success" for i in range(1, expected_calls + 1)]
    repaired_requests = [r for r in fake.requests if r.previous_attempt_feedback is not None]
    assert len(repaired_requests) == 1
    repair = repaired_requests[0]
    feedback = repair.previous_attempt_feedback
    assert feedback.document_kind == repair.document_kind
    assert feedback.previous_attempt_index == 1
    wire = json.loads(_author_messages(repair)[1]["content"])
    assert wire["previous_attempt_feedback"] == feedback.payload()
    assert "provider-body-secret" not in json.dumps(wire)
    assert "untrusted-secret-field" not in json.dumps(wire)
    if repair.document_kind == "personalized":
        assert repair.standard_document is not None
        assert all(c.startswith("S") for b in wire["standard_document"]["blocks"] for c in b["citation_ids"])
    diagnostic = receipts[min(failures) - 1]["diagnostic_json"]
    assert diagnostic["feedback_hash"] == feedback.content_hash
    assert "constraint" not in json.dumps(diagnostic)
    assignment_count = conn.execute("SELECT count(*) AS count FROM tutor_lesson_assignments WHERE track_id = %s", (track_id,)).fetchone()["count"]
    assert assignment_count == int(completed)
    dispatch_lesson_authoring_run(run_id, author=fake)
    assert len(fake.requests) == expected_calls
    public = LessonDocumentService(conn).read(user_id=user_id, track_id=track_id, knowledge_key="python.variables")
    assert "diagnostic_json" not in json.dumps(public)
    if completed:
        ready = LessonDocumentService(conn).prepare(user_id=user_id, track_id=track_id, knowledge_key="python.variables", expected_track_version=1, expected_progress_version=1, idempotency_key="ready-replay")
        assert ready == {"status": "ready", "track_id": track_id, "knowledge_key": "python.variables", "authoring_run": None, "should_dispatch": False, "idempotent_replayed": True}


def test_unavailable_is_not_repaired(authoring_scope):
    conn, _, _, run_id = authoring_scope
    fake = FakeLessonAuthor(unavailable=True)
    dispatch_lesson_authoring_run(run_id, author=fake)
    assert len(fake.requests) == 1
    row = conn.execute("SELECT outcome, usage_available, input_tokens, diagnostic_json FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s", (run_id,)).fetchone()
    assert row["outcome"] == "unavailable"
    assert row["usage_available"] is False and row["input_tokens"] is None
    assert row["diagnostic_json"]["issue_codes"] == ["LESSON_PROVIDER_UNAVAILABLE"]


def test_cancelled_read_is_exact_missing(authoring_scope):
    conn, user_id, track_id, run_id = authoring_scope
    conn.execute("UPDATE tutor_lesson_authoring_runs SET state = 'cancelled', terminal_at = now() WHERE id = %s", (run_id,))
    state = LessonDocumentService(conn).read(user_id=user_id, track_id=track_id, knowledge_key="python.variables")
    assert state["status"] == "missing"
    assert set(state) == {"status", "track_id", "module_key", "module_diagnostic_allowed", "knowledge_key", "track_version", "progress_version", "progress_status"}


@pytest.mark.parametrize("failure_kind", ["no_evidence", "source_integrity", "unknown", "stale", "lease", "source_stale"])
def test_nonrepairable_failures_never_start_repair(authoring_scope, monkeypatch, failure_kind):
    import app.services.learning.lesson_authoring as module
    from dataclasses import replace
    conn, _, track_id, run_id = authoring_scope
    fake = FakeLessonAuthor()
    original_load = module._load_evidence_snapshots
    if failure_kind == "no_evidence":
        monkeypatch.setattr(module, "_load_evidence_snapshots", lambda *args: ())
    elif failure_kind == "source_integrity":
        monkeypatch.setattr(module, "_load_evidence_snapshots", lambda *args: tuple(replace(s, display_name="Wrong registry metadata") for s in original_load(*args)))
    else:
        original_author = fake.author
        def fail(request):
            response = original_author(request)
            if failure_kind == "unknown":
                raise RuntimeError("SECRET internal error")
            if failure_kind == "stale":
                conn.execute("UPDATE tutor_learning_tracks SET version = version + 1 WHERE id = %s", (track_id,))
            elif failure_kind == "lease":
                conn.execute("UPDATE tutor_lesson_authoring_runs SET lease_generation = lease_generation + 1 WHERE id = %s", (run_id,))
            else:
                monkeypatch.setattr(PostgresLessonDocumentRepository, "evidence_is_current", lambda *args: False)
            conn.commit()
            response.candidate["extra"] = True
            return response
        fake.author = fail
    dispatch_lesson_authoring_run(run_id, author=fake)
    assert len(fake.requests) == (0 if failure_kind == "no_evidence" else 1)
    assert all(r.previous_attempt_feedback is None for r in fake.requests)
    assert conn.execute("SELECT count(*) AS count FROM tutor_lesson_assignments WHERE track_id = %s", (track_id,)).fetchone()["count"] == 0


def test_receipt_additive_legacy_default_check_and_immutability(authoring_scope):
    from app.db.bootstrap import apply_schema
    conn, user_id, _, run_id = authoring_scope
    # Transaction rollback restores the new schema and all pre-existing diagnostics.
    conn.execute("ALTER TABLE tutor_lesson_authoring_attempt_receipts DROP COLUMN diagnostic_json")
    conn.execute("INSERT INTO tutor_lesson_authoring_attempt_receipts (run_id,user_id,attempt_index,provider,model,protocol,outcome,request_hash) VALUES (%s,%s,1,'fake','fake','responses','failed',%s)", (run_id, user_id, "a" * 64))
    apply_schema(conn)
    apply_schema(conn)
    row = conn.execute("SELECT diagnostic_json FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s", (run_id,)).fetchone()
    assert row["diagnostic_json"] == {}
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("INSERT INTO tutor_lesson_authoring_attempt_receipts (run_id,user_id,attempt_index,provider,model,protocol,outcome,request_hash,diagnostic_json) VALUES (%s,%s,2,'fake','fake','responses','failed',%s,'[]')", (run_id, user_id, "b" * 64))
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("UPDATE tutor_lesson_authoring_attempt_receipts SET diagnostic_json = '{}' WHERE run_id = %s", (run_id,))
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("DELETE FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s", (run_id,))
    conn.rollback()


def test_same_key_prepare_replays_compact_pending_and_failed(authoring_scope):
    conn, user_id, track_id, run_id = authoring_scope
    run = PostgresLessonDocumentRepository(conn).read_authoring_run(run_id=run_id)
    service = LessonDocumentService(conn)
    def replay():
        return service.prepare(user_id=user_id, track_id=track_id, knowledge_key="python.variables", expected_track_version=1, expected_progress_version=1, idempotency_key=run.idempotency_key)
    pending = replay()
    assert set(pending) == {"status", "track_id", "knowledge_key", "authoring_run", "should_dispatch", "idempotent_replayed"}
    assert pending["status"] == "preparing" and pending["idempotent_replayed"] is True
    assert pending["should_dispatch"] is False
    assert pending["authoring_run"]["run_id"] == run_id
    conn.commit()
    dispatch_lesson_authoring_run(run_id, author=FakeLessonAuthor(unavailable=True))
    failed = replay()
    assert set(failed) == set(pending)
    assert failed["status"] == "failed" and failed["should_dispatch"] is False
    assert failed["authoring_run"]["run_id"] == run_id


def test_provider_invalid_metadata_reaches_receipt_and_repairs(authoring_scope):
    import json
    from types import SimpleNamespace
    from app.services.learning.lesson_authoring import PrimaryLessonDocumentAuthor
    from app.services.llm.llm_client import LLMInvalidResponseError, LLMInvalidResponseKind
    conn, _, _, run_id = authoring_scope
    from app.services.llm.contracts import LLMResponseDiagnostics
    usage = LLMUsage(input_tokens=19, output_tokens=8, total_tokens=27, reasoning_tokens=2)
    diagnostics = LLMResponseDiagnostics(response_status="completed", requested_max_output_tokens=12000,
                                         requested_reasoning_effort="none", visible_output_chars=8)
    class Client:
        calls = 0
        def complete_json(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise LLMInvalidResponseError("PRIVATE RAW BODY", kind=LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT, model="metadata-model", usage=usage, response_diagnostics=diagnostics)
            payload = json.loads(messages[1]["content"])
            return SimpleNamespace(content=author_candidate_payload(personalized=payload["document_kind"] == "personalized"), model="metadata-model", usage=usage)
    client = Client()
    # Override stored fields, not computed properties; the injected client stays offline.
    settings = get_settings().model_copy(update={
        "llm_type": "deepseek", "deepseek_model": "deepseek-v4-flash",
        "deepseek_api_key": "test-only", "deepseek_base_url": "https://provider.invalid",
    })
    dispatch_lesson_authoring_run(run_id, author=PrimaryLessonDocumentAuthor(settings, client=client))
    assert client.calls == 3
    receipts = conn.execute("SELECT model, protocol, input_tokens, output_tokens, outcome, diagnostic_json FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s ORDER BY attempt_index", (run_id,)).fetchall()
    assert [r["outcome"] for r in receipts] == ["invalid", "success", "success"]
    assert receipts[0]["model"] == "metadata-model" and receipts[0]["protocol"] == "deepseek_responses"
    assert receipts[0]["input_tokens"] == 19 and receipts[0]["output_tokens"] == 8
    assert receipts[0]["diagnostic_json"]["issue_codes"] == ["LESSON_PROVIDER_CONTENT_NOT_JSON_OBJECT"]
    assert receipts[0]["diagnostic_json"]["reasoning_tokens"] == 2
    assert receipts[0]["diagnostic_json"]["provider_response"]["requested_reasoning_effort"] == "none"
    assert "PRIVATE RAW BODY" not in json.dumps(receipts)



def test_cancelled_prepare_same_key_replays_compact_missing(authoring_scope):
    conn, user_id, track_id, run_id = authoring_scope
    repository = PostgresLessonDocumentRepository(conn)
    run = repository.read_authoring_run(run_id=run_id)
    conn.execute("UPDATE tutor_lesson_authoring_runs SET state = 'cancelled', terminal_at = now() WHERE id = %s", (run_id,))
    replay = LessonDocumentService(conn).prepare(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables",
        expected_track_version=1, expected_progress_version=1,
        idempotency_key=run.idempotency_key,
    )
    assert replay == {
        "status": "missing", "track_id": track_id, "knowledge_key": "python.variables",
        "authoring_run": None, "should_dispatch": False, "idempotent_replayed": True,
    }


def test_reclaimed_run_does_not_restore_semantic_repair_budget(authoring_scope):
    from datetime import timedelta
    conn, _, track_id, run_id = authoring_scope
    repository = PostgresLessonDocumentRepository(conn)
    claimed = repository.claim_authoring_run(
        run_id=run_id, owner="previous-dispatcher",
        now=datetime.now(UTC) - timedelta(minutes=10),
    )
    assert claimed is not None
    conn.commit()
    fake = RepairLessonAuthor({1})
    dispatch_lesson_authoring_run(run_id, author=fake)
    assert len(fake.requests) == 1
    assert fake.requests[0].previous_attempt_feedback is None
    run = repository.read_authoring_run(run_id=run_id)
    assert run.state == "failed" and run.failure_code == "LESSON_DOCUMENT_INVALID"
    assert conn.execute("SELECT count(*) AS count FROM tutor_lesson_assignments WHERE track_id = %s", (track_id,)).fetchone()["count"] == 0


def test_fatal_quality_issue_after_feedback_limit_never_enables_repair(authoring_scope, monkeypatch):
    import app.services.learning.lesson_authoring as module
    from app.services.learning.lesson_quality import LessonQualityError, LessonQualityIssue, LessonQualityReport
    conn, _, track_id, run_id = authoring_scope
    def reject(*args, **kwargs):
        issues = tuple(LessonQualityIssue("LESSON_CITATION_REQUIRED", "safe") for _ in range(12))
        issues += (LessonQualityIssue("LESSON_SOURCE_REGISTRY_MISMATCH", "safe"),)
        raise LessonQualityError(LessonQualityReport(passed=False, issues=issues, citation_coverage=0, covered_capabilities=(), gate_keys=()))
    monkeypatch.setattr(module, "require_lesson_quality", reject)
    fake = FakeLessonAuthor()
    dispatch_lesson_authoring_run(run_id, author=fake)
    assert len(fake.requests) == 1
    receipt = conn.execute("SELECT outcome, diagnostic_json FROM tutor_lesson_authoring_attempt_receipts WHERE run_id = %s", (run_id,)).fetchone()
    assert receipt["outcome"] == "invalid"
    assert len(receipt["diagnostic_json"]["issue_codes"]) == 12
    assert receipt["diagnostic_json"]["issue_codes"][0] == "LESSON_SOURCE_REGISTRY_MISMATCH"
    assert conn.execute("SELECT count(*) AS count FROM tutor_lesson_assignments WHERE track_id = %s", (track_id,)).fetchone()["count"] == 0
