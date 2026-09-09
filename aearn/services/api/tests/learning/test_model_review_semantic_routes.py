from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.main import app
from app.routes import learning_artifacts as artifact_routes
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactCompleteReviewAction,
)
from app.services.learning.artifacts.service import LearningArtifactServiceError
from app.services.learning.practice.model_review_semantics import (
    SemanticReasonCode,
    SemanticReviewReceipt,
    SemanticReviewUnavailable,
    SemanticVerdict,
    StrictSemanticVerdict,
)
from tests.learning.test_model_review_artifacts import _publish_source, _source
from tests.support.teaching_session_support import connection, database_available
from tests.tutor.test_tutor_teaching_artifact_commit import (
    _ArtifactTeachingProvider,
    _artifact_service,
    _artifact_settings,
    _dispatch_artifact,
    _open_guided,
)

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL is not available"
)
_DB_NAME = "aearn_semantic_review_20260909"


@pytest.fixture(autouse=True)
def _assert_isolated_database() -> None:
    assert os.environ.get("LLM_TYPE") == "disabled"
    with connection() as conn:
        name = conn.execute("SELECT current_database() AS name").fetchone()["name"]
    assert name == _DB_NAME
    assert name != "postgres"


@dataclass
class _ReviewFixture:
    scope: dict[str, str | int]
    artifact_id: str
    artifact: object
    request: TutorArtifactActionRequest


def _materialize_review(
    *,
    explanation: str = "count can be zero, so division needs a guard",
    with_remediation: bool = False,
) -> _ReviewFixture:
    settings = _artifact_settings()
    capability = f"semantic.route.{uuid4().hex}"
    suffix = uuid4().hex[:12]
    remediation = (
        _source(
            suffix=f"{suffix}.remediation",
            capability=capability,
            purpose="remediation",
            difficulty="D2",
            remediation_key=None,
        )
        if with_remediation
        else None
    )
    source = _source(
        suffix=suffix,
        capability=capability,
        purpose="code_review",
        difficulty="D3",
        remediation_key=remediation.public.item_key
        if remediation is not None
        else None,
        diff=True,
    )
    with connection() as conn:
        if remediation is not None:
            _publish_source(conn, remediation, f"semantic-remediation-{suffix}")
        handle = _publish_source(conn, source, f"semantic-route-{suffix}")
        scope, run_id = _open_guided(
            conn, settings=settings, required_capability=capability
        )
    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(
            artifact_handle=handle, interaction_intent="review_diff"
        ),
    )
    assert result.terminal_outcome is not None
    with connection() as conn:
        row = conn.execute(
            "SELECT id::text AS id FROM tutor_learning_artifacts WHERE turn_id=%s",
            (run_id,),
        ).fetchone()
        assert row is not None
        service = _artifact_service(conn)
        artifact = service.read_artifact(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=str(row["id"]),
        )
        target = artifact.presentation.review_target
        request = TutorArtifactActionRequest(
            user_id=str(scope["user_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=artifact.teaching_session_id,
            client_action_id=f"semantic:{suffix}",
            expected_artifact_version=artifact.version,
            action=TutorArtifactCompleteReviewAction(
                review_submission={
                    "schema_version": "model_code_review_submission_v2",
                    "presentation_hash": artifact.presentation.presentation_hash,
                    "verdict": "correctness_issue",
                    "findings": [
                        {
                            "client_finding_id": "finding-semantic",
                            "hunk_id": target.hunks[0].hunk_id,
                            "side": "modified",
                            "start_line": 2,
                            "end_line": 2,
                            "category": "logic_boundary",
                            "severity": "high",
                            "explanation": explanation,
                        }
                    ],
                }
            ),
        )
    return _ReviewFixture(
        scope=scope, artifact_id=str(row["id"]), artifact=artifact, request=request
    )


class _FakeReviewer:
    verdict = SemanticVerdict.VERIFIED
    calls = 0
    prepare_connections: list[object] = []

    def review(self, request, *, deterministic_pass):  # type: ignore[no-untyped-def]
        type(self).calls += 1
        assert deterministic_pass is True
        assert type(self).prepare_connections
        prepare_conn = type(self).prepare_connections[-1]
        assert prepare_conn.closed
        assert prepare_conn.info.transaction_status is TransactionStatus.UNKNOWN
        reason = (
            SemanticReasonCode.AUTHORITY_SUPPORTED
            if self.verdict is SemanticVerdict.VERIFIED
            else SemanticReasonCode.AUTHORITY_CONTRADICTION
        )
        return SemanticReviewReceipt(
            request_binding_hash=request.binding_hash,
            verdict=StrictSemanticVerdict(verdict=self.verdict, reason_code=reason),
            model="fake",
            usage=None,
        )


def _configure_route(
    monkeypatch: pytest.MonkeyPatch, reviewer: type[_FakeReviewer]
) -> list[str]:
    settings = Settings(
        llm_type="disabled",
        tutor_learning_artifacts_enabled=True,
        tutor_artifact_teaching_mode_enabled=True,
        tutor_thread_turn_v2_enabled=True,
    )
    monkeypatch.setattr(artifact_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(artifact_routes, "runtime_gate_error", lambda **_kwargs: None)
    monkeypatch.setattr(
        artifact_routes, "thread_turn_v2_gate_error", lambda **_kwargs: None
    )
    original_connect = artifact_routes.connect
    connections: list[object] = []

    @contextmanager
    def tracked_connect():  # type: ignore[no-untyped-def]
        with original_connect() as conn:
            connections.append(conn)
            reviewer.prepare_connections = connections
            yield conn

    monkeypatch.setattr(artifact_routes, "connect", tracked_connect)
    monkeypatch.setattr(artifact_routes, "PrimarySemanticReviewer", reviewer)
    dispatches: list[str] = []
    monkeypatch.setattr(
        artifact_routes,
        "enqueue_tutor_interactive_dispatch",
        lambda job_id, **_kwargs: dispatches.append(job_id),
    )
    reviewer.calls = 0
    return dispatches


def _post(
    client: TestClient,
    fixture: _ReviewFixture,
    request: TutorArtifactActionRequest | None = None,
):  # type: ignore[no-untyped-def]
    body = (request or fixture.request).model_dump(mode="json", exclude_none=False)
    return client.post(
        f"/api/tutor/conversations/{fixture.scope['conversation_id']}/artifacts/{fixture.artifact_id}/actions",
        json=body,
    )


def test_verified_route_closes_prepare_transaction_replays_and_dispatches_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _materialize_review()
    dispatches = _configure_route(monkeypatch, _FakeReviewer)
    with TestClient(app) as client:
        first = _post(client, fixture)
        replay = _post(client, fixture)
        conflicting = fixture.request.model_copy(
            update={
                "action": TutorArtifactCompleteReviewAction(
                    review_submission={
                        "schema_version": "model_code_review_submission_v2",
                        "presentation_hash": fixture.request.action.review_submission.presentation_hash,
                        "verdict": "no_correctness_issue",
                        "findings": [],
                    }
                )
            }
        )
        conflict = _post(client, fixture, conflicting)
    assert first.status_code == 200
    assert first.json()["artifact"]["presentation"]["outcome"] == "passed"
    assert replay.status_code == 200 and replay.json()["idempotent_replayed"] is True
    assert (
        conflict.status_code == 409
        and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )
    assert _FakeReviewer.calls == 1
    assert len(dispatches) == 1
    with connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*)::int AS count FROM tutor_continuation_intents WHERE artifact_id=%s",
                (fixture.artifact_id,),
            ).fetchone()["count"]
            == 1
        )


def test_semantic_rejection_persists_consistent_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Rejected(_FakeReviewer):
        verdict = SemanticVerdict.REJECTED

    fixture = _materialize_review(with_remediation=True)
    _configure_route(monkeypatch, Rejected)
    with TestClient(app) as client:
        response = _post(client, fixture)
    assert response.status_code == 200
    presentation = response.json()["artifact"]["presentation"]
    assert presentation["outcome"] == "failed"
    assert "语义解释" in presentation["evaluation_markdown"]
    with connection() as conn:
        receipt = conn.execute(
            "SELECT outcome,score,safe_feedback_json,policy_version,result_hash FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s",
            (fixture.artifact_id,),
        ).fetchone()
    assert receipt["outcome"] == "failed"
    assert receipt["score"] < 0.8
    assert receipt["safe_feedback_json"]["next_action"] == "review_variant"
    assert (
        receipt["safe_feedback_json"]["reason_code"]
        == "semantic_authority_contradiction"
    )
    assert receipt["policy_version"] == "model_code_review_score_v2"
    assert (
        receipt["safe_feedback_json"]["semantic_policy_version"]
        == "model_code_review_score_v2_semantic_v1"
    )
    assert receipt["result_hash"] == presentation["result_hash"]


def test_uncertain_is_recoverable_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Unavailable(_FakeReviewer):
        def review(self, request, *, deterministic_pass):  # type: ignore[no-untyped-def]
            receipt = SemanticReviewReceipt(
                request_binding_hash=request.binding_hash,
                verdict=StrictSemanticVerdict(
                    verdict=SemanticVerdict.UNCERTAIN,
                    reason_code=SemanticReasonCode.PROVIDER_UNAVAILABLE,
                ),
                model=None,
                usage=None,
            )
            raise SemanticReviewUnavailable(receipt=receipt)

    fixture = _materialize_review()
    _configure_route(monkeypatch, Unavailable)
    with TestClient(app) as client:
        response = _post(client, fixture)
    assert (
        response.status_code == 503 and response.json()["error"]["recoverable"] is True
    )
    with connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*)::int AS count FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s",
                (fixture.artifact_id,),
            ).fetchone()["count"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*)::int AS count FROM tutor_learning_artifact_events WHERE artifact_id=%s AND event_kind='action'",
                (fixture.artifact_id,),
            ).fetchone()["count"]
            == 0
        )


def test_stale_prepare_finalize_is_rejected_without_receipt() -> None:
    fixture = _materialize_review()
    with connection() as conn:
        service = _artifact_service(conn)
        prepared = service.prepare_model_review_v2(
            conversation_id=str(fixture.scope["conversation_id"]),
            artifact_id=fixture.artifact_id,
            request=fixture.request,
        )
        assert prepared.prepared is not None
        conn.execute(
            "UPDATE tutor_teaching_sessions SET version=version+1 WHERE id=%s",
            (fixture.request.teaching_session_id,),
        )
        with pytest.raises(LearningArtifactServiceError) as stale:
            service.finalize_model_review_v2(
                conversation_id=str(fixture.scope["conversation_id"]),
                artifact_id=fixture.artifact_id,
                request=fixture.request,
                prepared=prepared.prepared,
                semantic_receipt=None,
            )
        assert stale.value.code == "LEARNING_ARTIFACT_VERSION_CONFLICT"
        conn.rollback()
