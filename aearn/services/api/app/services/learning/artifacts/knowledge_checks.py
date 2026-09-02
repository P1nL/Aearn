"""Server-authoritative scoring and assistance for Learning Item knowledge checks."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from psycopg import Connection
from pydantic import ValidationError

from app.services.learning.item_bank.contracts import (
    LearningItemKnowledgeCheckContentV1,
    LearningItemKnowledgeCheckPrivateV1,
    LearningItemPublicV1,
    LearningItemRemediationPolicyV1,
    normalize_answer,
    parse_code_range_answer,
)

from .contracts import (
    TutorArtifactCodeRangeResponse,
    TutorArtifactHintPageV1,
    TutorArtifactKnowledgeCheckPresentationV1,
    TutorArtifactRequestDirectAnswerAction,
    TutorArtifactRequestHintAction,
    TutorArtifactRespondAction,
    TutorArtifactResponseV1,
    TutorArtifactState,
    TutorArtifactTextResponse,
    TutorPublicArtifactItem,
    canonical_hash,
)
from .owner_adapters import ArtifactMutation, ArtifactOwnerActionInvalid, ArtifactOwnerVersionConflict


KNOWLEDGE_CHECK_SCORE_POLICY_VERSION = "knowledge_check_score_v1"
KNOWLEDGE_CHECK_DISCLOSURE_POLICY_VERSION = "knowledge_check_disclosure_v1"


class KnowledgeCheckDisclosureLevel(StrEnum):
    HINT_ONLY = "hint_only"
    EXPLANATION = "explanation"
    WORKED_ANSWER = "worked_answer"


@dataclass(frozen=True, slots=True)
class KnowledgeCheckDisclosureDecision:
    allowed_disclosure_level: KnowledgeCheckDisclosureLevel
    assistance_kind: str
    independent_mastery_eligible: bool


def disclosure_decision(
    *,
    first_failure: str,
    prior_incorrect_count: int,
    direct_answer_requested: bool = False,
) -> KnowledgeCheckDisclosureDecision:
    if direct_answer_requested:
        level = KnowledgeCheckDisclosureLevel.WORKED_ANSWER
        assistance_kind = "direct_answer"
    elif prior_incorrect_count > 0:
        level = KnowledgeCheckDisclosureLevel.WORKED_ANSWER
        assistance_kind = "remediated"
    elif first_failure == "hint_then_remediate":
        level = KnowledgeCheckDisclosureLevel.HINT_ONLY
        assistance_kind = "independent"
    elif first_failure == "explain_then_remediate":
        level = KnowledgeCheckDisclosureLevel.EXPLANATION
        assistance_kind = "independent"
    else:
        level = KnowledgeCheckDisclosureLevel.WORKED_ANSWER
        assistance_kind = "independent"
    return KnowledgeCheckDisclosureDecision(
        allowed_disclosure_level=level,
        assistance_kind=assistance_kind,
        independent_mastery_eligible=False,
    )


def apply_knowledge_check_action(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    action: TutorArtifactRequestHintAction | TutorArtifactRequestDirectAnswerAction | TutorArtifactRespondAction,
    owner_context_version: int,
) -> ArtifactMutation:
    presentation = artifact.presentation
    if not isinstance(presentation, TutorArtifactKnowledgeCheckPresentationV1):
        raise ArtifactOwnerActionInvalid("knowledge-check action requires a knowledge-check presentation")
    public, private, remediation_policy = _load_authority(conn, artifact=artifact)
    if isinstance(action, TutorArtifactRequestHintAction):
        return _apply_hint(
            conn,
            artifact=artifact,
            presentation=presentation,
            public=public,
            requested_level=action.hint_level,
            owner_context_version=owner_context_version,
        )
    if isinstance(action, TutorArtifactRequestDirectAnswerAction):
        return _apply_direct_answer(
            conn,
            artifact=artifact,
            presentation=presentation,
            public=public,
            private=private,
            owner_context_version=owner_context_version,
        )
    return _apply_response(
        conn,
        artifact=artifact,
        presentation=presentation,
        public=public,
        private=private,
        remediation_policy=remediation_policy,
        response=action.response,
        owner_context_version=owner_context_version,
    )


def _apply_hint(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    presentation: TutorArtifactKnowledgeCheckPresentationV1,
    public: LearningItemPublicV1,
    requested_level: int | None,
    owner_context_version: int,
) -> ArtifactMutation:
    if presentation.answer_locked:
        raise ArtifactOwnerActionInvalid("answered knowledge check is immutable")
    next_level = requested_level or len(presentation.revealed_hint_levels) + 1
    if next_level != len(presentation.revealed_hint_levels) + 1 or next_level > len(public.hints):
        raise ArtifactOwnerActionInvalid("knowledge-check hint level is unavailable or out of order")
    _insert_assistance_receipt(
        conn,
        artifact=artifact,
        assistance_kind="hint",
        hint_level=next_level,
    )
    revealed = (*presentation.revealed_hint_levels, next_level)
    return ArtifactMutation(
        state=TutorArtifactState.ACTIVE,
        owner_version=artifact.owner_version,
        owner_context_version=owner_context_version,
        presentation=presentation.model_copy(update={"revealed_hint_levels": revealed}),
        allowed_actions=artifact.allowed_actions,
        active_attempt=None,
        safe_event_payload={
            "assistance_kind": "hint",
            "hint_level": next_level,
            "assistance_recorded": True,
        },
    )


def _apply_direct_answer(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    presentation: TutorArtifactKnowledgeCheckPresentationV1,
    public: LearningItemPublicV1,
    private: LearningItemKnowledgeCheckPrivateV1,
    owner_context_version: int,
) -> ArtifactMutation:
    if presentation.answer_locked:
        raise ArtifactOwnerActionInvalid("answered knowledge check is immutable")
    assistance_receipt_id = _insert_assistance_receipt(
        conn,
        artifact=artifact,
        assistance_kind="direct_answer",
        hint_level=None,
    )
    transfer_handle = _select_transfer(conn, artifact=artifact, public=public)
    if transfer_handle is None:
        raise ArtifactOwnerVersionConflict(
            "knowledge-check direct answer transfer is unavailable"
        )
    response_receipt_id, result_hash = _insert_response_receipt(
        conn,
        artifact=artifact,
        response_kind="direct_answer",
        response_json={"kind": "direct_answer"},
        outcome="incorrect",
        assistance_kind="direct_answer",
        independent_mastery_eligible=False,
    )
    completed = presentation.model_copy(
        update={
            "answer_locked": True,
            "outcome": "incorrect",
            "assistance_kind": "direct_answer",
            "evaluation_markdown": private.answer_explanation_markdown
            + (" 接下来完成迁移检查。" if transfer_handle is not None else ""),
            "response_receipt_id": response_receipt_id,
            "remediation_handle": None,
            "transfer_handle": transfer_handle,
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
            "response_receipt_id": response_receipt_id,
            "assistance_receipt_id": assistance_receipt_id,
            "outcome": "incorrect",
            "assistance_kind": "direct_answer",
            "independent_mastery_eligible": False,
            "result_hash": result_hash,
            "transfer_handle": transfer_handle,
            "disclosure_policy_version": KNOWLEDGE_CHECK_DISCLOSURE_POLICY_VERSION,
        },
    )


def _apply_response(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    presentation: TutorArtifactKnowledgeCheckPresentationV1,
    public: LearningItemPublicV1,
    private: LearningItemKnowledgeCheckPrivateV1,
    remediation_policy: LearningItemRemediationPolicyV1 | None,
    response: TutorArtifactResponseV1,
    owner_context_version: int,
) -> ArtifactMutation:
    if presentation.answer_locked:
        raise ArtifactOwnerActionInvalid("answered knowledge check is immutable")
    response_json = response.model_dump(mode="json")
    correct = _score(public.content, private, response)
    prior = 1 if artifact.purpose.value == "remediation" else 0
    first_failure = remediation_policy.first_failure if remediation_policy is not None else "direct_explanation"
    disclosure = disclosure_decision(first_failure=first_failure, prior_incorrect_count=prior)
    if artifact.purpose.value == "remediation":
        assistance_kind = "remediated"
    elif presentation.revealed_hint_levels:
        assistance_kind = "hinted"
    else:
        assistance_kind = "independent"
    independent = correct and assistance_kind == "independent"
    remediation_handle: str | None = None
    transfer_handle: str | None = None
    should_remediate = (
        not correct
        and prior == 0
        and artifact.purpose.value == "knowledge_check"
        and first_failure in {"hint_then_remediate", "explain_then_remediate"}
    )
    if should_remediate:
        remediation_handle = _select_remediation(
            conn,
            artifact=artifact,
            public=public,
            successor_item_key=public.remediation_item_key,
        )
        if remediation_handle is None:
            raise ArtifactOwnerVersionConflict(
                "knowledge-check remediation successor is unavailable"
            )
    elif not correct and artifact.purpose.value == "remediation":
        transfer_handle = _select_transfer(conn, artifact=artifact, public=public)
        if transfer_handle is None:
            raise ArtifactOwnerVersionConflict(
                "knowledge-check transfer successor is unavailable"
            )
    evaluation = _evaluation_markdown(
        correct=correct,
        disclosure=disclosure.allowed_disclosure_level,
        explanation=private.answer_explanation_markdown,
        has_remediation=remediation_handle is not None,
        has_transfer=transfer_handle is not None,
    )
    receipt_id, result_hash = _insert_response_receipt(
        conn,
        artifact=artifact,
        response_kind=response.kind,
        response_json=response_json,
        outcome="correct" if correct else "incorrect",
        assistance_kind=assistance_kind,
        independent_mastery_eligible=independent,
    )
    completed = presentation.model_copy(
        update={
            "answer_locked": True,
            "outcome": "correct" if correct else "incorrect",
            "assistance_kind": assistance_kind,
            "evaluation_markdown": evaluation,
            "response_receipt_id": receipt_id,
            "remediation_handle": remediation_handle,
            "transfer_handle": transfer_handle,
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
            "response_receipt_id": receipt_id,
            "outcome": completed.outcome,
            "assistance_kind": assistance_kind,
            "independent_mastery_eligible": independent,
            "result_hash": result_hash,
            "remediation_handle": remediation_handle,
            "transfer_handle": transfer_handle,
            "disclosure_policy_version": KNOWLEDGE_CHECK_DISCLOSURE_POLICY_VERSION,
        },
    )


def _score(
    content: object,
    private: LearningItemKnowledgeCheckPrivateV1,
    response: TutorArtifactResponseV1,
) -> bool:
    if not isinstance(content, LearningItemKnowledgeCheckContentV1):
        raise ArtifactOwnerVersionConflict("knowledge-check public content is invalid")
    accepted = tuple(normalize_answer(item) for item in private.accepted_answers)
    option_ids = {item.option_id for item in content.options}
    if content.response_kind == "single_choice":
        if response.kind != "single_select" or response.value not in option_ids:
            raise ArtifactOwnerActionInvalid("knowledge-check response does not match its presentation")
        return normalize_answer(response.value) == accepted[0]
    if content.response_kind == "multiple_choice":
        if response.kind != "multi_select" or not set(response.values) <= option_ids:
            raise ArtifactOwnerActionInvalid("knowledge-check response does not match its presentation")
        return frozenset(normalize_answer(item) for item in response.values) == frozenset(accepted)
    if content.response_kind == "ordering":
        if (
            response.kind != "ordering"
            or len(response.values) != len(content.options)
            or set(response.values) != option_ids
        ):
            raise ArtifactOwnerActionInvalid("knowledge-check ordering does not match its presentation")
        return tuple(normalize_answer(item) for item in response.values) == accepted
    if content.response_kind in {"short_text", "prediction"}:
        if not isinstance(response, TutorArtifactTextResponse) or response.kind != content.response_kind or len(response.text) > 2_000:
            raise ArtifactOwnerActionInvalid("knowledge-check response does not match its presentation")
        return normalize_answer(response.text) in accepted
    if content.response_kind == "code_range":
        if not isinstance(response, TutorArtifactCodeRangeResponse):
            raise ArtifactOwnerActionInvalid("knowledge-check response does not match its presentation")
        expected_start, expected_end, expected_category = parse_code_range_answer(accepted[0])
        return (
            response.start_line == expected_start
            and response.end_line == expected_end
            and normalize_answer(response.category) == expected_category
        )
    raise ArtifactOwnerVersionConflict("knowledge-check response kind is unsupported")


def _insert_assistance_receipt(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    assistance_kind: str,
    hint_level: int | None,
) -> str:
    receipt_id = str(uuid4())
    assistance_hash = canonical_hash(
        {
            "artifact_id": artifact.id,
            "artifact_version": artifact.version,
            "assistance_kind": assistance_kind,
            "hint_level": hint_level,
        }
    )
    conn.execute(
        """
        INSERT INTO tutor_knowledge_check_assistance_receipts (
          id,artifact_id,user_id,conversation_id,learning_track_id,knowledge_key,
          teaching_session_id,checkpoint_id,artifact_version,assistance_kind,hint_level,
          assistance_hash
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            artifact.version,
            assistance_kind,
            hint_level,
            assistance_hash,
        ),
    )
    return receipt_id


def _insert_response_receipt(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    response_kind: str,
    response_json: Mapping[str, object],
    outcome: str,
    assistance_kind: str,
    independent_mastery_eligible: bool,
) -> tuple[str, str]:
    response_hash = canonical_hash(response_json)
    result_hash = canonical_hash(
        {
            "artifact_id": artifact.id,
            "response_hash": response_hash,
            "outcome": outcome,
            "assistance_kind": assistance_kind,
            "score_policy": KNOWLEDGE_CHECK_SCORE_POLICY_VERSION,
        }
    )
    receipt_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO tutor_knowledge_check_response_receipts (
          id,artifact_id,user_id,conversation_id,learning_track_id,knowledge_key,
          teaching_session_id,checkpoint_id,learning_item_version_id,artifact_version,
          response_kind,response_json,response_hash,outcome,assistance_kind,
          independent_mastery_eligible,result_hash,score_policy_version
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)
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
            artifact.version,
            response_kind,
            _canonical_json(response_json),
            response_hash,
            outcome,
            assistance_kind,
            independent_mastery_eligible,
            result_hash,
            KNOWLEDGE_CHECK_SCORE_POLICY_VERSION,
        ),
    )
    return receipt_id, result_hash


def _load_authority(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
) -> tuple[LearningItemPublicV1, LearningItemKnowledgeCheckPrivateV1, LearningItemRemediationPolicyV1 | None]:
    row = conn.execute(
        """
        SELECT public.public_json, private.private_json, blueprints.blueprint_json
        FROM tutor_learning_item_versions AS versions
        JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
        JOIN tutor_learning_item_private_contents AS private ON private.version_id=versions.id
        JOIN tutor_learning_item_blueprints AS blueprints ON blueprints.id=versions.blueprint_id
        JOIN tutor_learning_item_publication_events AS publication
          ON publication.version_id=versions.id AND publication.state_version=%s AND publication.state='published'
        WHERE versions.id=%s AND versions.knowledge_key=%s
        """,
        (artifact.owner_version, artifact.owner_id, artifact.knowledge_key),
    ).fetchone()
    if row is None:
        raise ArtifactOwnerVersionConflict("Learning Item knowledge-check authority is stale")
    try:
        public = LearningItemPublicV1.model_validate(row["public_json"])
        private_payload = row["private_json"]
        if not isinstance(private_payload, Mapping):
            raise TypeError("stored knowledge-check private payload is invalid")
        private = LearningItemKnowledgeCheckPrivateV1.model_validate(private_payload["content"])
        blueprint = row["blueprint_json"]
        policy_payload = blueprint.get("remediation_policy") if isinstance(blueprint, Mapping) else None
        policy = LearningItemRemediationPolicyV1.model_validate(policy_payload) if policy_payload else None
    except (KeyError, TypeError, ValidationError) as exc:
        raise ArtifactOwnerVersionConflict("stored knowledge-check authority is invalid") from exc
    return public, private, policy


def _select_remediation(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    public: LearningItemPublicV1,
    successor_item_key: str | None,
) -> str | None:
    if successor_item_key is None:
        return None
    current = int(public.difficulty.value[1:])
    return _select_successor(
        conn,
        artifact=artifact,
        public=public,
        purpose="remediation",
        difficulties=tuple(
            dict.fromkeys((f"D{max(1, current - 1)}", f"D{current}"))
        ),
        item_key=successor_item_key,
    )


def _select_transfer(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    public: LearningItemPublicV1,
) -> str | None:
    return _select_successor(
        conn,
        artifact=artifact,
        public=public,
        purpose="transfer_check",
        difficulties=(public.difficulty.value,),
        item_key=None,
    )


def _select_successor(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    public: LearningItemPublicV1,
    purpose: str,
    difficulties: tuple[str, ...],
    item_key: str | None,
) -> str | None:
    user_id = _owner_user_id(conn, artifact.id)
    rows = conn.execute(
        """
        SELECT versions.handle,public.public_json
        FROM tutor_learning_item_versions AS versions
        JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
        JOIN LATERAL (
          SELECT state FROM tutor_learning_item_publication_events
          WHERE version_id=versions.id ORDER BY state_version DESC LIMIT 1
        ) AS publication ON publication.state='published'
        JOIN tutor_track_active_plans AS active_plan
          ON active_plan.track_id=%s AND active_plan.user_id=%s
        JOIN tutor_track_plan_nodes AS node
          ON node.revision_id=active_plan.revision_id
         AND node.track_id=active_plan.track_id
         AND node.user_id=active_plan.user_id
         AND node.knowledge_key=%s
        WHERE versions.knowledge_key=%s AND versions.purpose=%s
          AND versions.difficulty=ANY(%s::text[])
          AND versions.required_capabilities_json <@ node.required_capabilities_json
          AND (%s::text IS NULL OR versions.item_key=%s)
          AND versions.id<>%s
          AND NOT EXISTS (
            SELECT 1 FROM tutor_learning_artifacts AS used
            WHERE used.user_id=%s AND used.learning_track_id=%s
              AND used.knowledge_key=%s AND used.owner_kind='learning_item'
              AND used.owner_id=versions.id
          )
        ORDER BY versions.item_key,versions.version,versions.handle
        """,
        (
            artifact.learning_track_id,
            user_id,
            artifact.knowledge_key,
            artifact.knowledge_key,
            purpose,
            list(difficulties),
            item_key,
            item_key,
            artifact.owner_id,
            user_id,
            artifact.learning_track_id,
            artifact.knowledge_key,
        ),
    ).fetchall()
    current_signature = _knowledge_check_signature(public)
    valid: list[str] = []
    for row in rows:
        try:
            candidate = LearningItemPublicV1.model_validate(row["public_json"])
        except ValidationError as exc:
            raise ArtifactOwnerVersionConflict("successor knowledge-check authority is invalid") from exc
        if _knowledge_check_signature(candidate) == current_signature:
            continue
        valid.append(str(row["handle"]))
    return valid[0] if valid else None


def _knowledge_check_signature(public: LearningItemPublicV1) -> str:
    content = public.content
    if not isinstance(content, LearningItemKnowledgeCheckContentV1):
        raise ArtifactOwnerVersionConflict("knowledge-check successor content is invalid")
    return canonical_hash(
        {
            "response_kind": content.response_kind,
            "prompt": normalize_answer(content.prompt_markdown),
            "options": sorted(
                (item.option_id, normalize_answer(item.label)) for item in content.options
            ),
        }
    )


def _evaluation_markdown(
    *,
    correct: bool,
    disclosure: KnowledgeCheckDisclosureLevel,
    explanation: str,
    has_remediation: bool,
    has_transfer: bool,
) -> str:
    if correct:
        return "回答正确。"
    if disclosure is KnowledgeCheckDisclosureLevel.HINT_ONLY:
        suffix = " 已为你准备一次更低一级的补救检查。" if has_remediation else ""
        return "这次回答暴露了一个概念误区。先抓住题目中的关键关系，再完成补救检查。" + suffix
    suffix = " 接下来完成迁移检查。" if has_transfer else ""
    return explanation + suffix


def _owner_user_id(conn: Connection[dict[str, object]], artifact_id: str) -> str:
    row = conn.execute("SELECT user_id::text AS user_id FROM tutor_learning_artifacts WHERE id=%s", (artifact_id,)).fetchone()
    if row is None:
        raise ArtifactOwnerVersionConflict("knowledge-check Artifact scope is missing")
    return str(row["user_id"])


def _canonical_json(value: Mapping[str, object]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_hint_pages(public: LearningItemPublicV1) -> tuple[TutorArtifactHintPageV1, ...]:
    labels = {1: "方向", 2: "概念", 3: "结构"}
    return tuple(
        TutorArtifactHintPageV1(level=hint.level, label=labels[hint.level], markdown=hint.markdown)  # type: ignore[arg-type]
        for hint in public.hints
    )


__all__ = (
    "KNOWLEDGE_CHECK_DISCLOSURE_POLICY_VERSION",
    "KNOWLEDGE_CHECK_SCORE_POLICY_VERSION",
    "KnowledgeCheckDisclosureDecision",
    "KnowledgeCheckDisclosureLevel",
    "apply_knowledge_check_action",
    "build_hint_pages",
    "disclosure_decision",
)
