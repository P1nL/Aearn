from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.errors import CheckViolation
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactCompleteReviewAction,
    TutorPublicArtifactItem,
)
from app.services.learning.artifacts.service import LearningArtifactServiceError
from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1,
    canonical_hash,
)
from app.services.learning.item_bank.repository import (
    PostgresLearningItemBankRepository,
)
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.practice.model_review_contracts import code_hash
from app.services.learning.practice.model_review_semantics import (
    SemanticReasonCode,
    SemanticReviewReceipt,
    SemanticVerdict,
    StrictSemanticVerdict,
)
from app.services.learning.practice.model_review_diff import (
    build_model_review_artifact_v2,
)
from app.services.learning.teaching_sessions import TeachingSessionRepository
from app.services.repositories.local_user_data_repository import (
    export_user_data,
    reset_user_data,
)
from app.services.tutor.continuation import (
    TutorContinuationDispatcher,
    TutorContinuationIntentProducer,
)
from tests.learning.test_learning_item_bank_repository import _import, _publish
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
NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
SOURCE = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "services"
    / "learning"
    / "item_bank"
    / "sources"
    / "curated"
    / "model-review-zero-boundary-v1.json"
)


def _source(
    *,
    suffix: str,
    capability: str,
    purpose: str,
    difficulty: str,
    remediation_key: str | None,
    diff: bool = False,
) -> LearningItemSourceV1:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    item_key = f"python.review.artifact.{suffix}"
    payload["blueprint"].update(
        {
            "blueprint_key": f"{item_key}.blueprint",
            "knowledge_key": "python.variables",
            "purpose": purpose,
            "difficulty_profile": {
                "base": difficulty,
                "reasoning_depth": int(difficulty[1:]),
                "concept_count": 2,
                "context_novelty": 2,
                "transfer_distance": 2,
                "response_complexity": 2,
                "scaffolding": 2,
            },
            "required_capabilities": [capability],
            "remediation_policy": (
                {
                    "first_failure": "explain_then_remediate",
                    "second_failure": "explain_then_transfer",
                    "successor_item_key": remediation_key,
                }
                if remediation_key is not None
                else None
            ),
        }
    )
    source_ref = {
        "source_id": "aearn.docs",
        "source_version": "2026.09",
        "locator": f"model-review.{suffix}",
        "content_hash": canonical_hash({"source": suffix}),
    }
    payload["blueprint"]["source_references"] = [source_ref]
    payload["public"].update(
        {
            "item_key": item_key,
            "purpose": purpose,
            "difficulty": difficulty,
            "remediation_item_key": remediation_key,
            "source_references": [source_ref],
        }
    )
    payload["private"].update({"item_key": item_key})
    if purpose == "remediation":
        model_code = "def ratio(total, count):\n    return total / count"
        payload["public"]["content"]["artifact"].update(
            {
                "model_code": model_code,
                "code_hash": code_hash(model_code),
                "line_count": 2,
            }
        )
    elif diff:
        legacy = payload["public"]["content"]
        modified_code = legacy["artifact"]["model_code"]
        target = build_model_review_artifact_v2(
            language_id=legacy["artifact"]["language_id"],
            runtime_label=legacy["artifact"]["runtime_label"],
            source_code="def average(total, count):\n    return 0",
            modified_code=modified_code,
        )
        payload["public"]["content"] = {
            "type": "model_review_v2",
            "prompt": legacy["prompt"],
            "artifact": target.model_dump(mode="json"),
        }
    return LearningItemSourceV1.model_validate(payload)


def _publish_source(conn, source: LearningItemSourceV1, key: str) -> str:  # type: ignore[no-untyped-def]
    validation = validate_learning_item(source)
    assert validation.passed
    imported = _import(
        PostgresLearningItemBankRepository(conn), source, validation, key=key
    )
    publication = _publish(conn, imported.handle, key)
    assert publication.state == "published"
    return imported.handle


def _semantic_act(
    service,
    *,
    conversation_id: str,
    artifact_id: str,
    request: TutorArtifactActionRequest,
    verdict: SemanticVerdict = SemanticVerdict.VERIFIED,
):  # type: ignore[no-untyped-def]
    prepared = service.prepare_model_review_v2(
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        request=request,
    )
    if prepared.replay is not None:
        return prepared.replay
    assert prepared.prepared is not None
    receipt = SemanticReviewReceipt(
        request_binding_hash=prepared.prepared.semantic_request.binding_hash,
        verdict=StrictSemanticVerdict(
            verdict=verdict,
            reason_code=(
                SemanticReasonCode.AUTHORITY_SUPPORTED
                if verdict is SemanticVerdict.VERIFIED
                else SemanticReasonCode.AUTHORITY_CONTRADICTION
            ),
        ),
        model="fake-semantic-reviewer",
        usage=None,
    )
    return service.finalize_model_review_v2(
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        request=request,
        prepared=prepared.prepared,
        semantic_receipt=receipt,
    )


def test_model_review_artifact_receipt_remediation_and_continuation_are_authoritative() -> (
    None
):
    settings = _artifact_settings()
    capability = f"artifact.review.{uuid4().hex}"
    suffix = uuid4().hex[:12]
    remediation_source = _source(
        suffix=f"{suffix}.remediation",
        capability=capability,
        purpose="remediation",
        difficulty="D2",
        remediation_key=None,
    )
    original_source = _source(
        suffix=f"{suffix}.original",
        capability=capability,
        purpose="code_review",
        difficulty="D3",
        remediation_key=remediation_source.public.item_key,
        diff=True,
    )
    with connection() as conn:
        remediation_handle = _publish_source(
            conn, remediation_source, f"review-remediation-{suffix}"
        )
        original_handle = _publish_source(
            conn, original_source, f"review-original-{suffix}"
        )
        scope, run_id = _open_guided(
            conn, settings=settings, required_capability=capability
        )

    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(
            artifact_handle=original_handle, interaction_intent="review_diff"
        ),
    )
    assert (
        result.terminal_outcome is not None
        and result.terminal_outcome.value == "completed"
    )

    with connection() as conn:
        row = conn.execute(
            "SELECT id::text AS id FROM tutor_learning_artifacts WHERE turn_id=%s",
            (run_id,),
        ).fetchone()
        assert row is not None
        artifact_id = str(row["id"])
        service = _artifact_service(conn)
        artifact = service.read_artifact(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=artifact_id,
        )
        assert artifact.presentation.type == "model_code_review_v2"
        target = artifact.presentation.review_target
        assert target.presentation_mode == "diff"
        assert target.source_code is not None
        assert target.source_hash != target.modified_hash
        unauthorized_projection = artifact.model_dump(mode="json")
        unauthorized_projection["allowed_actions"] = ["cancel"]
        with pytest.raises(ValueError, match="complete-review authority"):
            TutorPublicArtifactItem.model_validate(unauthorized_projection)
        assert any(
            line.kind.value == "removed" and line.source_line == 2
            for line in target.hunks[0].lines
        )
        assert any(
            line.kind.value == "added" and line.modified_line == 2
            for line in target.hunks[0].lines
        )
        assert "weak_testing" not in artifact.presentation.review_categories
        unsupported_category = TutorArtifactActionRequest(
            user_id=str(scope["user_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=artifact.teaching_session_id,
            client_action_id=f"review-disabled-category:{suffix}",
            expected_artifact_version=artifact.version,
            action=TutorArtifactCompleteReviewAction(
                review_submission={
                    "schema_version": "model_code_review_submission_v2",
                    "presentation_hash": artifact.presentation.presentation_hash,
                    "verdict": "correctness_issue",
                    "findings": [
                        {
                            "client_finding_id": "finding-disabled-category",
                            "hunk_id": target.hunks[0].hunk_id,
                            "side": "modified",
                            "start_line": 2,
                            "end_line": 2,
                            "category": "weak_testing",
                            "severity": "medium",
                            "explanation": "the exercise does not expose weak testing as a scored topic",
                        }
                    ],
                }
            ),
        )
        with pytest.raises(LearningArtifactServiceError) as unsupported:
            _semantic_act(
                service,
                conversation_id=artifact.conversation_id,
                artifact_id=artifact.id,
                request=unsupported_category,
            )
        assert unsupported.value.code == "LEARNING_ARTIFACT_ACTION_INVALID"
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s",
            (artifact.id,),
        ).fetchone() == {"count": 0}

        boundary_action = TutorArtifactCompleteReviewAction(
            review_submission={
                "schema_version": "model_code_review_submission_v2",
                "presentation_hash": artifact.presentation.presentation_hash,
                "verdict": "uncertain",
                "findings": [],
            }
        )
        stale_request = TutorArtifactActionRequest(
            user_id=str(scope["user_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=artifact.teaching_session_id,
            client_action_id=f"review-stale:{suffix}",
            expected_artifact_version=artifact.version + 1,
            action=boundary_action,
        )
        with pytest.raises(LearningArtifactServiceError) as stale:
            _semantic_act(
                service,
                conversation_id=artifact.conversation_id,
                artifact_id=artifact.id,
                request=stale_request,
            )
        assert stale.value.code == "LEARNING_ARTIFACT_VERSION_CONFLICT"

        scoped_requests = (
            (
                "user",
                str(uuid4()),
                str(scope["track_id"]),
                artifact.teaching_session_id,
                artifact.conversation_id,
            ),
            (
                "track",
                str(scope["user_id"]),
                str(uuid4()),
                artifact.teaching_session_id,
                artifact.conversation_id,
            ),
            (
                "session",
                str(scope["user_id"]),
                str(scope["track_id"]),
                str(uuid4()),
                artifact.conversation_id,
            ),
            (
                "conversation",
                str(scope["user_id"]),
                str(scope["track_id"]),
                artifact.teaching_session_id,
                str(uuid4()),
            ),
        )
        for label, user_id, track_id, session_id, conversation_id in scoped_requests:
            with pytest.raises(LearningArtifactServiceError) as scope_error:
                _semantic_act(
                    service,
                    conversation_id=conversation_id,
                    artifact_id=artifact.id,
                    request=TutorArtifactActionRequest(
                        user_id=user_id,
                        learning_track_id=track_id,
                        teaching_session_id=session_id,
                        client_action_id=f"review-scope-{label}:{suffix}",
                        expected_artifact_version=artifact.version,
                        action=boundary_action,
                    ),
                )
            assert scope_error.value.code == "LEARNING_ARTIFACT_NOT_FOUND"

        mastery_before = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone()
        request = TutorArtifactActionRequest(
            user_id=str(scope["user_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=artifact.teaching_session_id,
            client_action_id=f"review:{suffix}",
            expected_artifact_version=artifact.version,
            action=TutorArtifactCompleteReviewAction(
                review_submission={
                    "schema_version": "model_code_review_submission_v2",
                    "presentation_hash": artifact.presentation.presentation_hash,
                    "verdict": "correctness_issue",
                    "findings": [
                        {
                            "client_finding_id": "finding-1",
                            "hunk_id": target.hunks[0].hunk_id,
                            "side": "source",
                            "start_line": 2,
                            "end_line": 2,
                            "category": "fabricated_api",
                            "severity": "high",
                            "explanation": "the code calls a fabricated API that is not in the contract",
                        }
                    ],
                }
            ),
        )
        with pytest.raises(LearningArtifactServiceError) as bypass:
            service.act(
                conversation_id=artifact.conversation_id,
                artifact_id=artifact.id,
                request=request,
            )
        assert bypass.value.code == "LEARNING_ARTIFACT_ACTION_INVALID"
        completed = _semantic_act(
            service,
            conversation_id=artifact.conversation_id,
            artifact_id=artifact.id,
            request=request,
        )
        assert completed.artifact.state.value == "completed"
        assert completed.artifact.active_attempt is None
        assert completed.artifact.presentation.outcome == "failed"
        assert completed.artifact.presentation.remediation_handle == remediation_handle
        receipt = conn.execute(
            """
            SELECT submission_json,safe_feedback_json,result_hash,remediation_handle
            FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s
            """,
            (artifact.id,),
        ).fetchone()
        assert (
            receipt is not None and receipt["remediation_handle"] == remediation_handle
        )
        assert receipt["submission_json"]["findings"][0]["explanation"].startswith(
            "the code calls"
        )
        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_model_review_artifact_receipts SET score=0.5 WHERE artifact_id=%s",
                    (artifact.id,),
                )
        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "DELETE FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s",
                    (artifact.id,),
                )
        serialized = json.dumps(
            completed.artifact.model_dump(mode="json"), ensure_ascii=False
        ).casefold()
        assert "the code calls" not in serialized
        assert "expected_findings" not in serialized
        mastery_after = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone()
        assert mastery_after == mastery_before

        replay = _semantic_act(
            service,
            conversation_id=artifact.conversation_id,
            artifact_id=artifact.id,
            request=request,
        )
        assert replay.idempotent_replayed is True
        assert replay.artifact_event_id == completed.artifact_event_id
        conflicting = request.model_copy(
            update={
                "action": TutorArtifactCompleteReviewAction(
                    review_submission={
                        "schema_version": "model_code_review_submission_v2",
                        "presentation_hash": artifact.presentation.presentation_hash,
                        "verdict": "no_correctness_issue",
                        "findings": [],
                    }
                )
            }
        )
        with pytest.raises(LearningArtifactServiceError) as conflict:
            _semantic_act(
                service,
                conversation_id=artifact.conversation_id,
                artifact_id=artifact.id,
                request=conflicting,
            )
        assert conflict.value.code == "IDEMPOTENCY_CONFLICT"

        intent = TutorContinuationIntentProducer(conn).record_model_review_evaluation(
            user_id=str(scope["user_id"]),
            conversation_id=artifact.conversation_id,
            artifact_id=artifact.id,
            artifact_event_id=completed.artifact_event_id,
            artifact_event_sequence=completed.artifact_event_sequence,
            occurred_at=NOW,
        )
        dispatched = TutorContinuationDispatcher(conn, settings=settings).dispatch_next(
            user_id=str(scope["user_id"]),
            conversation_id=artifact.conversation_id,
            claimant_id=f"review-evaluation:{suffix}",
            now=NOW,
        )
        assert (
            dispatched is not None and dispatched.intent.intent_id == intent.intent_id
        )
        context = TeachingSessionRepository(conn, settings=settings).teaching_context(
            run_id=dispatched.run_id,
            user_id=str(scope["user_id"]),
        )
        assert (
            context["stimulus"]["safe_payload"]["reason_code"]
            == "model_review_evaluation"
        )
        candidates = context["artifact_candidates"]["candidates"]
        assert [item["handle"] for item in candidates] == [remediation_handle]

        exported = export_user_data(conn, str(scope["user_id"]))
        summaries = exported["model_review_artifact_summaries"]
        summary = next(item for item in summaries if item["artifact_id"] == artifact.id)
        serialized_summary = json.dumps(summary, ensure_ascii=False).casefold()
        for protected in (
            "submission_json",
            "safe_feedback_json",
            "presentation_hash",
            "submission_hash",
            "result_hash",
            "receipt_hash",
            "expected_findings",
            "private_rubric",
        ):
            assert protected not in serialized_summary
        reset = reset_user_data(conn, str(scope["user_id"]))
        assert reset["summary"]["counts"]["model_review_artifact_receipts"] == 0
        assert reset["summary"]["counts"]["learning_artifacts"] == 0


def test_model_review_artifact_passes_without_successor_or_mastery_double_write() -> (
    None
):
    settings = _artifact_settings()
    capability = f"artifact.review.{uuid4().hex}"
    suffix = uuid4().hex[:12]
    source = _source(
        suffix=f"{suffix}.pass",
        capability=capability,
        purpose="code_review",
        difficulty="D2",
        remediation_key=None,
    )
    with connection() as conn:
        handle = _publish_source(conn, source, f"review-pass-{suffix}")
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )

    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(
            artifact_handle=handle,
            interaction_intent="review_diff",
        ),
    )
    assert result.terminal_outcome is not None
    assert result.terminal_outcome.value == "completed"

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
        assert artifact.presentation.type == "model_code_review_v2"
        target = artifact.presentation.review_target
        mastery_before = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone()
        completed = _semantic_act(
            service,
            conversation_id=artifact.conversation_id,
            artifact_id=artifact.id,
            request=TutorArtifactActionRequest(
                user_id=str(scope["user_id"]),
                learning_track_id=str(scope["track_id"]),
                teaching_session_id=artifact.teaching_session_id,
                client_action_id=f"review-pass:{suffix}",
                expected_artifact_version=artifact.version,
                action=TutorArtifactCompleteReviewAction(
                    review_submission={
                        "schema_version": "model_code_review_submission_v2",
                        "presentation_hash": artifact.presentation.presentation_hash,
                        "verdict": "correctness_issue",
                        "findings": [
                            {
                                "client_finding_id": "finding-pass",
                                "hunk_id": target.hunks[0].hunk_id,
                                "side": "modified",
                                "start_line": 2,
                                "end_line": 2,
                                "category": "logic_boundary",
                                "severity": "high",
                                "explanation": "count can be zero, so division needs a guard",
                            }
                        ],
                    }
                ),
            ),
        )
        assert completed.artifact.state.value == "completed"
        assert completed.artifact.presentation.outcome == "passed"
        assert completed.artifact.presentation.remediation_handle is None
        receipt = conn.execute(
            """
            SELECT outcome,remediation_handle,submission_json
            FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s
            """,
            (artifact.id,),
        ).fetchone()
        assert receipt is not None
        assert receipt["outcome"] == "passed"
        assert receipt["remediation_handle"] is None
        assert (
            receipt["submission_json"]["findings"][0]["client_finding_id"]
            == "finding-pass"
        )
        assert (
            conn.execute(
                "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id=%s",
                (scope["user_id"],),
            ).fetchone()
            == mastery_before
        )

        intent = TutorContinuationIntentProducer(conn).record_model_review_evaluation(
            user_id=str(scope["user_id"]),
            conversation_id=artifact.conversation_id,
            artifact_id=artifact.id,
            artifact_event_id=completed.artifact_event_id,
            artifact_event_sequence=completed.artifact_event_sequence,
            occurred_at=NOW,
        )
        dispatched = TutorContinuationDispatcher(conn, settings=settings).dispatch_next(
            user_id=str(scope["user_id"]),
            conversation_id=artifact.conversation_id,
            claimant_id=f"review-pass-evaluation:{suffix}",
            now=NOW,
        )
        assert dispatched is not None
        assert dispatched.intent.intent_id == intent.intent_id
        context = TeachingSessionRepository(conn, settings=settings).teaching_context(
            run_id=dispatched.run_id,
            user_id=str(scope["user_id"]),
        )
        assert context is not None
        assert (
            context["stimulus"]["safe_payload"]["reason_code"]
            == "model_review_evaluation"
        )
        assert context["artifact_candidates"]["candidates"] == []

    bootstrap_database()
    bootstrap_database()
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as verify:
        assert verify.execute(
            "SELECT count(*)::int AS count FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s",
            (artifact.id,),
        ).fetchone() == {"count": 1}


def test_failed_model_review_without_published_remediation_rolls_back_everything() -> (
    None
):
    settings = _artifact_settings()
    capability = f"artifact.review.{uuid4().hex}"
    suffix = uuid4().hex[:12]
    source = _source(
        suffix=f"{suffix}.no-remediation",
        capability=capability,
        purpose="code_review",
        difficulty="D3",
        remediation_key=None,
        diff=True,
    )
    with connection() as conn:
        handle = _publish_source(conn, source, f"review-no-remediation-{suffix}")
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )

    _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(
            artifact_handle=handle,
            interaction_intent="review_diff",
        ),
    )
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
        assert artifact.presentation.type == "model_code_review_v2"
        target = artifact.presentation.review_target
        with pytest.raises(LearningArtifactServiceError) as unavailable:
            _semantic_act(
                service,
                conversation_id=artifact.conversation_id,
                artifact_id=artifact.id,
                request=TutorArtifactActionRequest(
                    user_id=str(scope["user_id"]),
                    learning_track_id=str(scope["track_id"]),
                    teaching_session_id=artifact.teaching_session_id,
                    client_action_id=f"review-no-remediation:{suffix}",
                    expected_artifact_version=artifact.version,
                    action=TutorArtifactCompleteReviewAction(
                        review_submission={
                            "schema_version": "model_code_review_submission_v2",
                            "presentation_hash": artifact.presentation.presentation_hash,
                            "verdict": "correctness_issue",
                            "findings": [
                                {
                                    "client_finding_id": "finding-no-remediation",
                                    "hunk_id": target.hunks[0].hunk_id,
                                    "side": "modified",
                                    "start_line": 2,
                                    "end_line": 2,
                                    "category": "fabricated_api",
                                    "severity": "high",
                                    "explanation": "the code relies on an API that the contract never provides",
                                }
                            ],
                        }
                    ),
                ),
            )
        assert unavailable.value.code == "LEARNING_ARTIFACT_VERSION_CONFLICT"
        current = service.read_artifact(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=artifact.id,
        )
        assert current.state.value == "active"
        assert current.version == artifact.version
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_model_review_artifact_receipts WHERE artifact_id=%s",
            (artifact.id,),
        ).fetchone() == {"count": 0}
        assert conn.execute(
            """
            SELECT count(*)::int AS count FROM tutor_learning_artifact_events
            WHERE artifact_id=%s AND event_kind='action'
            """,
            (artifact.id,),
        ).fetchone() == {"count": 0}
