"""Conversation-native model review v2 backed by published item authority."""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from psycopg import Connection
from pydantic import ValidationError

from app.services.learning.item_bank.contracts import (
    LearningItemModelReviewContentV1,
    LearningItemModelReviewContentV2,
    LearningItemModelReviewPrivateV1,
    LearningItemPrivateV1,
    LearningItemPublicV1,
)
from app.services.learning.practice.model_review_contracts import (
    ModelCodeReviewSubmissionV2,
    ModelReviewAssistanceKind,
    upgrade_model_review_rubric_v1,
)
from app.services.learning.practice.model_review_scoring import evaluate_model_code_review_v2

from .contracts import (
    TutorArtifactCompleteReviewAction,
    TutorArtifactModelCodeReviewPresentationV2,
    TutorArtifactState,
    TutorPublicArtifactItem,
    canonical_hash,
)
from .owner_adapters import ArtifactMutation, ArtifactOwnerActionInvalid, ArtifactOwnerVersionConflict


MODEL_REVIEW_ARTIFACT_RECEIPT_VERSION = "model_review_artifact_receipt_v1"


def apply_model_review_action(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    action: TutorArtifactCompleteReviewAction,
    owner_context_version: int,
) -> ArtifactMutation:
    presentation = artifact.presentation
    if not isinstance(presentation, TutorArtifactModelCodeReviewPresentationV2):
        raise ArtifactOwnerActionInvalid("model review v2 action requires a v2 presentation")
    if presentation.submission_locked:
        raise ArtifactOwnerActionInvalid("completed model review submission is immutable")
    submission = action.review_submission
    if not isinstance(submission, ModelCodeReviewSubmissionV2):
        raise ArtifactOwnerActionInvalid("model review Artifact requires submission v2")
    if any(
        finding.category not in presentation.review_categories
        for finding in submission.findings
    ):
        raise ArtifactOwnerActionInvalid(
            "model review finding category is not enabled by this presentation"
        )
    public, private, exercise_version_id, required_capabilities = _load_authority(conn, artifact=artifact)
    submission.validate_presentation(presentation.review_target)
    rubric = upgrade_model_review_rubric_v1(private.rubric, presentation.review_target)
    result = evaluate_model_code_review_v2(
        submission=submission,
        presentation=presentation.review_target,
        rubric=rubric,
        required_capabilities=required_capabilities,
        assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
        threshold=private.score_policy.threshold,
        now=datetime.now(UTC),
    )
    outcome = result.outcome.value
    remediation_handle = None
    if outcome != "passed":
        remediation_handle = _select_remediation(
            conn,
            artifact=artifact,
            public=public,
            line_count=presentation.review_target.line_count,
        )
        if remediation_handle is None:
            raise ArtifactOwnerVersionConflict("model review remediation successor is unavailable")
    receipt_id = str(uuid4())
    receipt_identity = {
        "artifact_id": artifact.id,
        "artifact_version": artifact.version,
        "learning_item_version_id": artifact.owner_id,
        "exercise_version_id": exercise_version_id,
        "presentation_hash": presentation.review_target.presentation_hash,
        "submission_hash": submission.submission_hash,
        "outcome": outcome,
        "score": result.score,
        "result_hash": result.result_hash,
        "remediation_handle": remediation_handle,
        "policy_version": result.policy_version,
    }
    conn.execute(
        """
        INSERT INTO tutor_model_review_artifact_receipts (
          id,artifact_id,user_id,conversation_id,learning_track_id,knowledge_key,
          teaching_session_id,checkpoint_id,learning_item_version_id,exercise_version_id,
          artifact_version,presentation_hash,submission_json,submission_hash,verdict,
          outcome,score,assistance_kind,safe_feedback_json,result_hash,remediation_handle,
          policy_version,receipt_hash
        ) VALUES (
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,
          %s,%s,%s,%s::jsonb,%s,%s,%s,%s
        )
        """,
        (
            receipt_id,
            artifact.id,
            _owner_user_id(conn, artifact.id),
            artifact.conversation_id,
            artifact.learning_track_id,
            artifact.knowledge_key,
            artifact.teaching_session_id,
            artifact.checkpoint_id,
            artifact.owner_id,
            exercise_version_id,
            artifact.version,
            presentation.review_target.presentation_hash,
            submission.canonical_json(),
            submission.submission_hash,
            submission.verdict.value,
            outcome,
            result.score,
            ModelReviewAssistanceKind.INDEPENDENT.value,
            _json(result.safe_feedback),
            result.result_hash,
            remediation_handle,
            result.policy_version,
            canonical_hash(receipt_identity),
        ),
    )
    evaluation = str(result.safe_feedback.get("message") or "代码审查已由服务器评分。")
    if remediation_handle is not None:
        evaluation += " 已为你准备一个范围更小或难度更低的审查变体。"
    completed = presentation.model_copy(
        update={
            "submission_locked": True,
            "outcome": outcome,
            "score": result.score,
            "evaluation_markdown": evaluation,
            "review_receipt_id": receipt_id,
            "result_hash": result.result_hash,
            "remediation_handle": remediation_handle,
        }
    )
    return ArtifactMutation(
        state=TutorArtifactState.COMPLETED,
        owner_version=artifact.owner_version,
        owner_context_version=owner_context_version,
        presentation=completed,
        allowed_actions=(),
        active_attempt=None,
        safe_event_payload={
            "review_receipt_id": receipt_id,
            "outcome": outcome,
            "score": result.score,
            "result_hash": result.result_hash,
            "remediation_handle": remediation_handle,
            "policy_version": result.policy_version,
        },
    )


def _load_authority(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
) -> tuple[LearningItemPublicV1, LearningItemModelReviewPrivateV1, str, tuple[str, ...]]:
    row = conn.execute(
        """
        SELECT public.public_json,private.private_json,materializations.exercise_version_id,
               versions.required_capabilities_json,
               materializations.item_handle,materializations.content_hash,
               versions.handle,versions.content_hash AS version_content_hash
        FROM tutor_learning_item_versions AS versions
        JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
        JOIN tutor_learning_item_private_contents AS private ON private.version_id=versions.id
        JOIN tutor_learning_item_practice_materializations AS materializations
          ON materializations.version_id=versions.id
        JOIN tutor_learning_item_publication_events AS publication
          ON publication.version_id=versions.id AND publication.state_version=%s
         AND publication.state='published'
        WHERE versions.id=%s AND versions.knowledge_key=%s AND versions.item_kind='model_review'
        """,
        (artifact.owner_version, artifact.owner_id, artifact.knowledge_key),
    ).fetchone()
    if row is None:
        raise ArtifactOwnerVersionConflict("Learning Item model review authority is stale")
    try:
        public = LearningItemPublicV1.model_validate(row["public_json"])
        private = LearningItemPrivateV1.model_validate(row["private_json"])
        if not isinstance(
            public.content,
            (LearningItemModelReviewContentV1, LearningItemModelReviewContentV2),
        ):
            raise TypeError("model review public content is invalid")
        if not isinstance(private.content, LearningItemModelReviewPrivateV1):
            raise TypeError("model review private content is invalid")
        exercise_version_id = str(row["exercise_version_id"])
        raw_capabilities = row.get("required_capabilities_json")
        if not isinstance(raw_capabilities, list):
            raise TypeError("model review capabilities are invalid")
        required_capabilities = tuple(str(item) for item in raw_capabilities)
        if (
            not exercise_version_id
            or str(row["item_handle"]) != str(row["handle"])
            or str(row["content_hash"]) != str(row["version_content_hash"])
        ):
            raise TypeError("model review practice materialization is stale")
    except (KeyError, TypeError, ValidationError) as exc:
        raise ArtifactOwnerVersionConflict("stored model review authority is invalid") from exc
    return public, private.content, exercise_version_id, required_capabilities


def _select_remediation(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    public: LearningItemPublicV1,
    line_count: int,
) -> str | None:
    user_id = _owner_user_id(conn, artifact.id)
    difficulty = int(public.difficulty.value[1:])
    difficulties = tuple(dict.fromkeys((f"D{max(1, difficulty - 1)}", f"D{difficulty}")))
    rows = conn.execute(
        """
        SELECT versions.handle,versions.difficulty,public.public_json
        FROM tutor_learning_item_versions AS versions
        JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
        JOIN tutor_learning_item_practice_materializations AS materializations
          ON materializations.version_id=versions.id
        JOIN LATERAL (
          SELECT state FROM tutor_learning_item_publication_events
          WHERE version_id=versions.id ORDER BY state_version DESC LIMIT 1
        ) AS publication ON publication.state='published'
        JOIN tutor_track_active_plans AS active_plan
          ON active_plan.track_id=%s AND active_plan.user_id=%s
        JOIN tutor_track_plan_nodes AS node
          ON node.revision_id=active_plan.revision_id
         AND node.track_id=active_plan.track_id AND node.user_id=active_plan.user_id
         AND node.knowledge_key=%s
        WHERE versions.knowledge_key=%s AND versions.item_kind='model_review'
          AND versions.purpose='remediation' AND versions.difficulty=ANY(%s::text[])
          AND versions.required_capabilities_json <@ node.required_capabilities_json
          AND (%s::text IS NULL OR versions.item_key=%s)
          AND versions.id<>%s
          AND NOT EXISTS (
            SELECT 1 FROM tutor_learning_artifacts AS used
            WHERE used.user_id=%s AND used.learning_track_id=%s
              AND used.knowledge_key=%s AND used.owner_kind='learning_item'
              AND used.owner_id=versions.id
          )
        ORDER BY CASE WHEN versions.difficulty=%s THEN 0 ELSE 1 END,
                 versions.item_key,versions.version,versions.handle
        """,
        (
            artifact.learning_track_id,
            user_id,
            artifact.knowledge_key,
            artifact.knowledge_key,
            list(difficulties),
            public.remediation_item_key,
            public.remediation_item_key,
            artifact.owner_id,
            user_id,
            artifact.learning_track_id,
            artifact.knowledge_key,
            difficulties[0],
        ),
    ).fetchall()
    current_signature = _review_signature(public)
    for row in rows:
        try:
            candidate = LearningItemPublicV1.model_validate(row["public_json"])
        except ValidationError as exc:
            raise ArtifactOwnerVersionConflict("model review remediation authority is invalid") from exc
        if not isinstance(
            candidate.content,
            (LearningItemModelReviewContentV1, LearningItemModelReviewContentV2),
        ):
            raise ArtifactOwnerVersionConflict("model review remediation content is invalid")
        if _review_signature(candidate) == current_signature:
            continue
        candidate_lines = candidate.content.artifact.line_count
        if candidate.difficulty.value == public.difficulty.value and candidate_lines >= line_count:
            continue
        return str(row["handle"])
    return None


def _review_signature(public: LearningItemPublicV1) -> str:
    content = public.content
    if isinstance(content, LearningItemModelReviewContentV1):
        identity = {
            "presentation_mode": "code",
            "source_hash": None,
            "modified_hash": content.artifact.code_hash,
            "diff_hash": None,
            "line_count": content.artifact.line_count,
        }
    elif isinstance(content, LearningItemModelReviewContentV2):
        identity = {
            "presentation_mode": content.artifact.presentation_mode,
            "source_hash": content.artifact.source_hash,
            "modified_hash": content.artifact.modified_hash,
            "diff_hash": content.artifact.diff_hash,
            "line_count": content.artifact.line_count,
        }
    else:
        raise ArtifactOwnerVersionConflict("model review content is invalid")
    return canonical_hash(
        {
            "requirements": list(content.prompt.requirements),
            "artifact": identity,
        }
    )


def _owner_user_id(conn: Connection[dict[str, object]], artifact_id: str) -> str:
    row = conn.execute(
        "SELECT user_id::text AS user_id FROM tutor_learning_artifacts WHERE id=%s",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ArtifactOwnerVersionConflict("model review Artifact scope is missing")
    return str(row["user_id"])


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = (
    "MODEL_REVIEW_ARTIFACT_RECEIPT_VERSION",
    "apply_model_review_action",
)
