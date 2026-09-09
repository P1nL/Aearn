from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.pq import TransactionStatus

from app.main import app
from app.routes import exercise_gates as routes
from app.services.learning.practice.model_review_templates import (
    ModelReviewAuthorCandidateV2,
    select_model_review_template,
)
from app.services.learning.practice.model_review_repository import (
    PostgresModelReviewRepository,
)
from app.services.learning.practice.model_review_semantics import (
    SemanticReasonCode,
    SemanticReviewReceipt,
    SemanticReviewUnavailable,
    SemanticVerdict,
    StrictSemanticVerdict,
)
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.learning.practice.service import ExerciseGateService
from tests.learning.test_model_code_review_repository import (
    _model_review_document,
    _publish,
)
from tests.support.teaching_session_support import connection, database_available
from app.services.grounding.grounding_index_repository import replace_grounding_chunks
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.learning.track_repository import PostgresLearningTrackRepository
from tests.support.learning_track_support import sample_plan
from tests.support.lesson_document_support import sample_source_snapshot

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL unavailable"
)
_DB = "aearn_semantic_review_20260909"


@pytest.fixture(autouse=True)
def _isolated_database() -> None:
    assert os.environ.get("LLM_TYPE") == "disabled"
    with connection() as conn:
        assert (
            conn.execute("SELECT current_database() AS name").fetchone()["name"] == _DB
        )


def _gate_scope(lesson_repo):  # type: ignore[no-untyped-def]
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    published = _publish(
        conn,
        lesson_repository,
        user_id,
        track_id,
        snapshot,
        action="initial",
        standard_document=_model_review_document(personalized=False),
        personalized_document=_model_review_document(personalized=True),
    )
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime.now(UTC),
    )
    practice = PostgresExerciseGateRepository(conn)
    model_reviews = PostgresModelReviewRepository(conn)
    scope = practice.read_scope(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables"
    )
    slot = model_reviews.read_slot(scope=scope, gate_key="python.variables.basic")
    run, created = model_reviews.create_or_replay_authoring_run(
        scope=scope,
        slot=slot,
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
    )
    assert created
    claimed = model_reviews.claim(
        run_id=run.run_id, owner="gate-route-test", now=datetime.now(UTC)
    )
    assert claimed is not None
    running = model_reviews.mark_running(claimed)
    model_reviews.ensure_internal_run(run=running, now=datetime.now(UTC))
    running = model_reviews.read_authoring_run(run_id=running.run_id, user_id=user_id)
    template = select_model_review_template(
        language_id=running.language_id,
        knowledge_key=running.knowledge_key,
        required_capabilities=running.required_capabilities,
        mastery_level=running.mastery_level,
    )
    exercise, rubric = template.build_exercise(
        author=ModelReviewAuthorCandidateV2.model_validate(
            template.canonical_author_example()
        ),
        knowledge_key=running.knowledge_key,
        required_capabilities=running.required_capabilities,
    )
    candidate = model_reviews.create_candidate(
        run=running, exercise=exercise, rubric=rubric
    )
    validation = model_reviews.create_or_replay_validation(
        run=running,
        candidate=candidate,
        action_invocation_id=f"gate-route-{uuid4().hex[:12]}",
    )
    for check_type in (
        "schema",
        "parser",
        "compile_or_typecheck",
        "visible_tests",
        "hidden_tests",
        "finding_reachability",
        "rubric_consistency",
        "coverage",
        "redaction",
    ):
        conn.execute(
            """INSERT INTO tutor_model_review_validation_checks
            (validation_run_id,user_id,check_type,status,execution_job_id,proof_hash,safe_code)
            VALUES (%s,%s,%s,'passed',NULL,%s,'model_review_check_passed')""",
            (validation.validation_id, user_id, check_type, "a" * 64),
        )
    conn.execute(
        "UPDATE tutor_model_review_validation_runs SET state='running' WHERE id=%s",
        (validation.validation_id,),
    )
    conn.execute(
        """UPDATE tutor_model_review_validation_runs SET state='verified',authority_hash=%s,
        check_summary_code='all_checks_passed',safe_summary='verified',terminal_at=%s WHERE id=%s""",
        ("b" * 64, datetime.now(UTC), validation.validation_id),
    )
    model_reviews.attach_action_receipt(
        validation_id=validation.validation_id,
        user_id=user_id,
        action_receipt_hash="c" * 64,
    )
    conn.execute(
        "UPDATE tutor_model_review_candidates SET state='verified' WHERE id=%s",
        (candidate.candidate_id,),
    )
    model_reviews.publish(
        run=model_reviews.read_authoring_run(run_id=running.run_id, user_id=user_id),
        candidate=model_reviews.read_candidate(
            candidate_id=candidate.candidate_id, user_id=user_id
        ),
        validation=model_reviews.read_validation(
            validation_id=validation.validation_id, user_id=user_id
        ),
        now=datetime.now(UTC),
    )
    gate = ExerciseGateService(conn).read_gates(
        user_id=user_id, track_id=track_id, knowledge_key="python.variables"
    )["items"][0]
    evidence = ExerciseGateService(conn).model_review_evidence(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=f"evidence-{uuid4()}",
    )
    reference = rubric.reference_answer
    expected_verdict = str(reference["expected_verdict"])
    expected_findings = reference.get("expected_findings") or []
    findings = []
    for index, expected in enumerate(expected_findings):
        line_range = expected["accepted_line_ranges"][0]
        tokens = (
            " ".join(str(token) for token in expected.get("matcher_tokens", ()))
            or "contract evidence"
        )
        findings.append(
            {
                "client_finding_id": f"finding-route-{index}",
                "finding_kind": expected["finding_kind"],
                "start_line": line_range["start_line"],
                "end_line": line_range["end_line"],
                "category": expected["category"],
                "severity": expected["severity"],
                "trigger_condition": tokens,
                "principle": tokens,
                "impact": tokens,
                "validation_method": tokens,
                "suggested_fix": tokens,
            }
        )
    authoritative_submission = {
        "schema_version": "model_code_review_submission_v1",
        "verdict": expected_verdict,
        "findings": findings,
        "supplemental_note": None,
    }
    conn.commit()
    return {
        "user_id": user_id,
        "track_id": track_id,
        "track_version": 1,
        "progress_version": int(started["progress_version"]),
        "assignment_version": 1,
        "gate_version": int(evidence["gate_version"]),
        "review_submission": authoritative_submission,
    }


def _passing_submission() -> dict[str, object]:
    return {
        "schema_version": "model_code_review_submission_v1",
        "verdict": "no_correctness_issue",
        "findings": [],
        "supplemental_note": None,
    }


@pytest.fixture
def gate_scope():  # type: ignore[no-untyped-def]
    with connection() as conn:
        suffix = uuid4().hex[:12]
        user = conn.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
            (f"Gate Semantic {suffix}",),
        ).fetchone()
        assert user is not None
        user_id = str(user["id"])
        track_id = PostgresLearningTrackRepository(conn).create_track(
            user_id=user_id,
            language_id="python",
            goal_text="Gate semantic route test",
            target_level="beginner",
            plan=sample_plan(),
        )
        snapshot = sample_source_snapshot()
        replace_grounding_chunks(
            conn,
            (
                GroundingChunk(
                    chunk_id=snapshot.grounding_chunk_id,
                    source_id=snapshot.source_id,
                    language_id="python",
                    title="Variables",
                    section_path=snapshot.section_path,
                    canonical_url=snapshot.canonical_url,
                    source_type=snapshot.source_type,
                    source_trust_tier=snapshot.trust_tier,
                    fetched_at=snapshot.fetched_at,
                    content_hash=snapshot.chunk_content_hash,
                    text=snapshot.evidence_excerpt,
                    topic_tags=("basics",),
                    source_version_label=snapshot.source_version_label,
                    source_version_kind=snapshot.source_version_kind,
                    document_content_hash=snapshot.document_content_hash,
                ),
            ),
            source_ids=(snapshot.source_id,),
        )
        conn.commit()
        scope = _gate_scope(
            (conn, PostgresLessonDocumentRepository(conn), user_id, track_id, snapshot)
        )
        yield scope
        # Intentionally retain dedicated-database evidence. Model-review publication
        # and validation receipts are append-only and must not be deleted by tests.


def _payload(
    scope: dict[str, object], *, key: str, submission: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "user_id": scope["user_id"],
        "client_action_id": key,
        "attempt_type": "submit",
        "submission": None,
        "review_submission": submission or scope["review_submission"],
        "expected_track_version": scope["track_version"],
        "expected_progress_version": scope["progress_version"],
        "expected_assignment_version": scope["assignment_version"],
        "expected_gate_version": scope["gate_version"],
    }


def _url(scope: dict[str, object]) -> str:
    return f"/api/learning-tracks/{scope['track_id']}/lessons/python.variables/gates/python.variables.basic/attempts"


def _configure(monkeypatch: pytest.MonkeyPatch, mode: str):
    calls: list[bool] = []
    conns: list[object] = []
    monkeypatch.setattr(routes, "runtime_gate_error", lambda **_kwargs: None)
    original = routes.connect

    @contextmanager
    def tracked():  # type: ignore[no-untyped-def]
        with original() as conn:
            conns.append(conn)
            yield conn

    monkeypatch.setattr(routes, "connect", tracked)

    class Fake:
        def review(self, request, *, deterministic_pass):  # type: ignore[no-untyped-def]
            calls.append(deterministic_pass)
            assert conns[0].closed
            assert conns[0].info.transaction_status is TransactionStatus.UNKNOWN
            if mode == "unavailable":
                raise SemanticReviewUnavailable(
                    receipt=SemanticReviewReceipt(
                        request.binding_hash,
                        StrictSemanticVerdict(
                            verdict=SemanticVerdict.UNCERTAIN,
                            reason_code=SemanticReasonCode.PROVIDER_UNAVAILABLE,
                        ),
                        None,
                        None,
                    )
                )
            verdict = (
                SemanticVerdict.VERIFIED
                if mode == "verified"
                else SemanticVerdict.REJECTED
            )
            reason = (
                SemanticReasonCode.AUTHORITY_SUPPORTED
                if mode == "verified"
                else SemanticReasonCode.AUTHORITY_CONTRADICTION
            )
            return SemanticReviewReceipt(
                request.binding_hash,
                StrictSemanticVerdict(verdict=verdict, reason_code=reason),
                "fake",
                None,
            )

    monkeypatch.setattr(routes, "PrimarySemanticReviewer", Fake)
    return calls


@pytest.mark.parametrize(
    "mode,status,outcome",
    (
        ("verified", 200, "passed"),
        ("rejected", 200, "failed"),
        ("unavailable", 503, None),
    ),
)
def test_gate_route_semantic_outcomes(gate_scope, monkeypatch, mode, status, outcome):  # type: ignore[no-untyped-def]
    scope = gate_scope
    calls = _configure(monkeypatch, mode)
    with TestClient(app) as client:
        response = client.post(_url(scope), json=_payload(scope, key=f"gate-{uuid4()}"))
    assert response.status_code == status
    assert calls == [True]
    if outcome is not None:
        assert response.json()["result"]["outcome"] == outcome
    with connection() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id=%s AND gate_binding_id IS NOT NULL",
            (scope["user_id"],),
        ).fetchone()["count"]
    assert count == (0 if mode == "unavailable" else 1)


def test_gate_route_replay_conflict_and_stale(gate_scope, monkeypatch):  # type: ignore[no-untyped-def]
    scope = gate_scope
    calls = _configure(monkeypatch, "verified")
    key = f"gate-{uuid4()}"
    payload = _payload(scope, key=key)
    with TestClient(app) as client:
        first = client.post(_url(scope), json=payload)
        replay = client.post(_url(scope), json=payload)
        changed = dict(scope["review_submission"])
        changed["supplemental_note"] = "different bounded body"
        conflict = client.post(
            _url(scope), json=_payload(scope, key=key, submission=changed)
        )
    assert first.status_code == 200
    assert replay.status_code == 200 and replay.json()["idempotent_replayed"] is True
    assert conflict.status_code == 409
    assert calls == [True]


def test_gate_route_unverified_has_no_provider_or_attempt(gate_scope, monkeypatch):  # type: ignore[no-untyped-def]
    scope = gate_scope
    calls: list[int] = []
    error = type(
        "GateError",
        (),
        {
            "code": "CUTOVER_NOT_VERIFIED",
            "message": "not verified",
            "status_code": 409,
            "details": {},
            "recoverable": True,
        },
    )()
    monkeypatch.setattr(routes, "runtime_gate_error", lambda **_kwargs: error)
    monkeypatch.setattr(routes, "PrimarySemanticReviewer", lambda: calls.append(1))
    with TestClient(app) as client:
        response = client.post(
            _url(scope), json=_payload(scope, key=f"unverified-{uuid4()}")
        )
    assert response.status_code == 409 and calls == []
    with connection() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id=%s AND gate_binding_id IS NOT NULL",
            (scope["user_id"],),
        ).fetchone()["count"]
    assert count == 0


def test_gate_route_stale_has_no_provider_or_attempt(gate_scope, monkeypatch):  # type: ignore[no-untyped-def]
    scope = gate_scope
    calls = _configure(monkeypatch, "verified")
    payload = _payload(scope, key=f"stale-{uuid4()}")
    payload["expected_gate_version"] = int(scope["gate_version"]) + 1
    with TestClient(app) as client:
        response = client.post(_url(scope), json=payload)
    assert response.status_code == 409
    assert calls == []
    with connection() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id=%s AND gate_binding_id IS NOT NULL",
            (scope["user_id"],),
        ).fetchone()["count"]
    assert count == 0
