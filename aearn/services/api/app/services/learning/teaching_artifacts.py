"""Exact Learning Item materialization for atomic teaching Artifact commits."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection
from pydantic import ValidationError

from app.core.config import Settings
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionKind,
    TutorArtifactDifficulty,
    TutorArtifactExerciseWorkspacePresentationV1,
    TutorArtifactKind,
    TutorArtifactKnowledgeCheckPresentationV1,
    TutorArtifactModelCodeReviewPresentationV2,
    TutorArtifactOptionV1,
    TutorArtifactOwnerKind,
    TutorArtifactPresentationV1,
    TutorArtifactPurpose,
    TutorArtifactSourceReferenceV1,
    TutorArtifactSqlWorkspacePresentationV1,
    TutorArtifactSqlWorkspacePresentationV2,
    TutorArtifactState,
    TutorArtifactCreate,
    normalize_newlines,
    sha256_text,
)
from app.services.learning.artifacts.demonstrations import build_demonstration_presentation
from app.services.learning.artifacts.knowledge_checks import build_hint_pages
from app.services.learning.artifacts.conversation_events import (
    ArtifactConversationEventError,
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.repository import (
    LearningArtifactRepositoryError,
    LearningArtifactWriteResult,
    PostgresLearningArtifactRepository,
)
from app.services.learning.item_bank.contracts import (
    LearningItemCodeContentV1,
    LearningItemDemoContentV1,
    LearningItemDemoContentV2,
    LearningItemInteraction,
    LearningItemKnowledgeCheckContentV1,
    LearningItemModelReviewContentV1,
    LearningItemModelReviewContentV2,
    LearningItemPublicV1,
    LearningItemSourceReferenceV1,
    LearningItemSqlContentV1,
    LearningItemSqlContentV2,
)
from app.services.learning.practice.model_review_contracts import (
    MODEL_REVIEW_CORE_CATEGORIES,
)
from app.services.learning.practice.model_review_diff import build_model_review_artifact_v2
from app.services.learning.teaching_contracts import (
    TeachingInteractionIntent,
    TeachingLearnerResponseMode,
    TeachingStepDecision,
)


class TeachingArtifactCommitError(ValueError):
    """The selected Artifact can no longer be proven safe and executable."""


@dataclass(frozen=True, slots=True)
class PreparedTeachingArtifact:
    """Fully validated public Artifact input held under current transaction locks."""

    request: TutorArtifactCreate
    creation_key: str
    interaction_intent: TeachingInteractionIntent
    artifact_handle: str
    learning_item_version_id: str
    publication_event_id: str
    publication_state_version: int
    learning_item_content_hash: str


class PostgresTeachingArtifactMaterializer:
    """Revalidate a selected Learning Item and project one exact Artifact facade.

    The materializer reads only published public content plus the immutable Practice
    materialization receipt. It never reads private tests, answers, rubrics, or
    submissions and never creates score, mastery, progress, Gate, or Review state.
    """

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings,
    ) -> None:
        self._conn = conn
        self._settings = settings

    def prepare(
        self,
        *,
        step: TeachingStepDecision,
        run_id: str,
        user_id: str,
        conversation_id: str,
        teaching_session_id: str,
        checkpoint_id: str,
        checkpoint_source_hash: str,
        session_version: int,
        learning_track_id: str,
        knowledge_key: str,
        track_version: int,
        progress_version: int,
        assignment_version: int,
        available_capabilities: Sequence[str],
    ) -> PreparedTeachingArtifact:
        interaction = step.interaction
        if (
            interaction is None
            or interaction.mode is not TeachingLearnerResponseMode.ARTIFACT
            or interaction.artifact_handle is None
        ):
            raise TeachingArtifactCommitError(
                "teaching Artifact materialization requires an exact v3 interaction"
            )
        if (
            not self._settings.tutor_learning_artifacts_enabled
            or not self._settings.tutor_artifact_teaching_mode_enabled
        ):
            raise TeachingArtifactCommitError(
                "teaching Artifact materialization is disabled"
            )
        capabilities = tuple(str(item) for item in available_capabilities)
        if len(capabilities) != len(set(capabilities)) or len(capabilities) > 64:
            raise TeachingArtifactCommitError(
                "teaching Artifact runtime capability scope is invalid"
            )

        row = self._conn.execute(
            """
            SELECT versions.id AS version_id, versions.item_key, versions.version,
                   versions.item_kind, versions.purpose, versions.knowledge_key,
                   versions.language_id, versions.difficulty,
                   versions.runtime_profile_key, versions.required_capabilities_json,
                   versions.public_hash, versions.content_hash, versions.handle,
                   public.public_json, public.public_hash AS stored_public_hash,
                   publication.id AS publication_event_id,
                   publication.item_handle AS publication_handle,
                   publication.content_hash AS publication_content_hash,
                   publication.state AS publication_state,
                   publication.state_version AS publication_state_version,
                   materializations.id AS materialization_id,
                   materializations.item_handle AS materialization_handle,
                   materializations.content_hash AS materialization_content_hash,
                   materializations.exercise_version_id,
                   materializations.exercise_key AS materialization_exercise_key,
                   materializations.exercise_version AS materialization_exercise_version,
                   materializations.exercise_content_hash AS materialization_exercise_content_hash,
                   materializations.rubric_hash AS materialization_rubric_hash,
                   exercises.exercise_key, exercises.version AS exercise_version,
                   exercises.source_kind AS exercise_source_kind,
                   exercises.required_capabilities_json AS exercise_capabilities_json,
                   exercises.runtime_profile_key AS exercise_runtime_profile_key,
                   exercises.validation_status AS exercise_validation_status,
                   exercises.content_hash AS exercise_content_hash
            FROM tutor_learning_item_versions AS versions
            JOIN tutor_learning_item_public_contents AS public
              ON public.version_id = versions.id
            JOIN LATERAL (
              SELECT events.id, events.item_handle, events.content_hash,
                     events.state, events.state_version
              FROM tutor_learning_item_publication_events AS events
              WHERE events.version_id = versions.id
              ORDER BY events.state_version DESC
              LIMIT 1
            ) AS publication ON true
            LEFT JOIN tutor_learning_item_practice_materializations AS materializations
              ON materializations.version_id = versions.id
            LEFT JOIN tutor_exercise_versions AS exercises
              ON exercises.id = materializations.exercise_version_id
            WHERE versions.handle = %s
            FOR UPDATE OF versions
            """,
            (interaction.artifact_handle,),
        ).fetchone()
        if row is None:
            raise TeachingArtifactCommitError(
                "selected teaching Artifact handle is no longer available"
            )

        public = self._validate_learning_item(
            row=row,
            expected_handle=interaction.artifact_handle,
            expected_knowledge_key=knowledge_key,
            available_capabilities=capabilities,
            intent=interaction.intent,
        )
        self._validate_runtime(row=row, public=public)
        exercise_version_id = self._validate_practice_materialization(
            row=row,
            public=public,
        )
        presentation = _artifact_presentation(
            public=public,
            exercise_version_id=exercise_version_id,
            runtime_profile_key=_optional_string(row.get("runtime_profile_key")),
        )
        source_references = _artifact_source_references(
            public=public,
            checkpoint_id=checkpoint_id,
            checkpoint_version=session_version,
            checkpoint_source_hash=checkpoint_source_hash,
            exercise_version_id=exercise_version_id,
            exercise_content_hash=_optional_string(row.get("exercise_content_hash")),
        )
        request = TutorArtifactCreate(
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=run_id,
            learning_track_id=learning_track_id,
            knowledge_key=knowledge_key,
            teaching_session_id=teaching_session_id,
            checkpoint_id=checkpoint_id,
            track_version=track_version,
            progress_version=progress_version,
            assignment_version=assignment_version,
            owner_kind=TutorArtifactOwnerKind.LEARNING_ITEM,
            owner_id=str(row["version_id"]),
            owner_version=_positive_int(
                row.get("publication_state_version"),
                "publication_state_version",
            ),
            owner_context_version=session_version,
            artifact_kind=_artifact_kind(public),
            purpose=TutorArtifactPurpose(public.purpose.value),
            state=TutorArtifactState.ACTIVE,
            blocking=True,
            title=public.title,
            instruction_markdown=public.instruction_markdown,
            difficulty=TutorArtifactDifficulty(public.difficulty.value),
            presentation=presentation,
            allowed_actions=_allowed_artifact_actions(public),
            source_references=source_references,
        )
        return PreparedTeachingArtifact(
            request=request,
            creation_key=f"teaching-artifact:{run_id}",
            interaction_intent=interaction.intent,
            artifact_handle=interaction.artifact_handle,
            learning_item_version_id=str(row["version_id"]),
            publication_event_id=str(row["publication_event_id"]),
            publication_state_version=_positive_int(
                row.get("publication_state_version"),
                "publication_state_version",
            ),
            learning_item_content_hash=str(row["content_hash"]),
        )

    def create(
        self,
        prepared: PreparedTeachingArtifact,
        *,
        occurred_at: datetime,
    ) -> LearningArtifactWriteResult:
        repository = PostgresLearningArtifactRepository(
            self._conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(self._conn),
        )
        try:
            result = repository.create_artifact(
                prepared.request,
                creation_key=prepared.creation_key,
                occurred_at=occurred_at,
            )
        except (LearningArtifactRepositoryError, ArtifactConversationEventError) as exc:
            raise TeachingArtifactCommitError(
                "teaching Artifact could not be committed atomically"
            ) from exc
        if result.idempotent_replayed:
            raise TeachingArtifactCommitError(
                "fresh teaching Artifact commit unexpectedly replayed prior authority"
            )
        artifact = result.artifact
        if (
            artifact.turn_id != prepared.request.turn_id
            or artifact.checkpoint_id != prepared.request.checkpoint_id
            or artifact.owner_kind is not TutorArtifactOwnerKind.LEARNING_ITEM
            or artifact.owner_id != prepared.learning_item_version_id
            or artifact.owner_version != prepared.publication_state_version
            or result.artifact_event_sequence != 1
        ):
            raise TeachingArtifactCommitError(
                "teaching Artifact projection differs from prepared authority"
            )
        return result

    def _validate_learning_item(
        self,
        *,
        row: Mapping[str, object],
        expected_handle: str,
        expected_knowledge_key: str,
        available_capabilities: tuple[str, ...],
        intent: TeachingInteractionIntent,
    ) -> LearningItemPublicV1:
        if (
            str(row.get("publication_state") or "") != "published"
            or str(row.get("handle") or "") != expected_handle
            or str(row.get("publication_handle") or "") != expected_handle
            or str(row.get("content_hash") or "")
            != str(row.get("publication_content_hash") or "")
            or str(row.get("knowledge_key") or "") != expected_knowledge_key
        ):
            raise TeachingArtifactCommitError(
                "selected Learning Item publication or scope is stale"
            )
        try:
            public = LearningItemPublicV1.model_validate(row.get("public_json"))
        except ValidationError as exc:
            raise TeachingArtifactCommitError(
                "published Learning Item public content is invalid"
            ) from exc
        if (
            public.public_hash != str(row.get("public_hash") or "")
            or public.public_hash != str(row.get("stored_public_hash") or "")
            or public.item_key != str(row.get("item_key") or "")
            or public.version != str(row.get("version") or "")
            or public.kind.value != str(row.get("item_kind") or "")
            or public.purpose.value != str(row.get("purpose") or "")
            or public.difficulty.value != str(row.get("difficulty") or "")
        ):
            raise TeachingArtifactCommitError(
                "published Learning Item content identity is stale"
            )
        required = _string_tuple(row.get("required_capabilities_json"))
        if not set(required).issubset(available_capabilities):
            raise TeachingArtifactCommitError(
                "selected Learning Item runtime capabilities are no longer available"
            )
        expected_interaction = _learning_item_interaction(intent)
        if expected_interaction not in public.allowed_interactions:
            raise TeachingArtifactCommitError(
                "selected Learning Item no longer supports the requested interaction"
            )
        return public

    def _validate_runtime(
        self,
        *,
        row: Mapping[str, object],
        public: LearningItemPublicV1,
    ) -> None:
        runtime_profile_key = _optional_string(row.get("runtime_profile_key"))
        if runtime_profile_key is None:
            if public.kind.value in {"code", "sql", "demo"}:
                raise TeachingArtifactCommitError(
                    "runtime-backed Learning Item has no runtime profile"
                )
            return
        runtime_rows = self._conn.execute(
            """
            SELECT runtime_tier, language, runner, supports_realtime_preview,
                   supports_tests, archived_at
            FROM runtime_profiles
            WHERE runtime_tier = %s AND language = %s AND archived_at IS NULL
            ORDER BY slug
            FOR SHARE
            """,
            (runtime_profile_key, str(row["language_id"])),
        ).fetchall()
        if len(runtime_rows) != 1:
            raise TeachingArtifactCommitError(
                "Learning Item runtime profile is unavailable or ambiguous"
            )
        runtime = runtime_rows[0]
        if isinstance(
            public.content,
            (LearningItemDemoContentV1, LearningItemDemoContentV2),
        ):
            if (
                str(runtime.get("runner") or "") != "browser"
                or not bool(runtime.get("supports_realtime_preview"))
            ):
                raise TeachingArtifactCommitError(
                    "demonstration runtime is not interaction-ready"
                )
        elif isinstance(public.content, LearningItemCodeContentV1):
            if public.content.exercise_type == "browser_preview":
                ready = (
                    str(runtime.get("runner") or "") == "browser"
                    and bool(runtime.get("supports_realtime_preview"))
                    and bool(runtime.get("supports_tests"))
                )
            else:
                ready = bool(runtime.get("supports_tests"))
            if not ready:
                raise TeachingArtifactCommitError(
                    "code Artifact runtime is not ready"
                )
        elif isinstance(public.content, (LearningItemSqlContentV1, LearningItemSqlContentV2)) and (
            str(runtime.get("runner") or "") != "sql"
            or not bool(runtime.get("supports_tests"))
        ):
            raise TeachingArtifactCommitError(
                "SQL Artifact runtime is not ready"
            )

    @staticmethod
    def _validate_practice_materialization(
        *,
        row: Mapping[str, object],
        public: LearningItemPublicV1,
    ) -> str | None:
        if isinstance(
            public.content,
            (LearningItemDemoContentV1, LearningItemDemoContentV2),
        ):
            if row.get("materialization_id") is not None:
                raise TeachingArtifactCommitError(
                    "demonstration Learning Item must remain its own authority"
                )
            return None
        exercise_version_id = _optional_string(row.get("exercise_version_id"))
        expected_capabilities = _string_tuple(row.get("required_capabilities_json"))
        if (
            row.get("materialization_id") is None
            or exercise_version_id is None
            or str(row.get("materialization_handle") or "")
            != str(row.get("handle") or "")
            or str(row.get("materialization_content_hash") or "")
            != str(row.get("content_hash") or "")
            or str(row.get("materialization_exercise_key") or "") != public.item_key
            or str(row.get("materialization_exercise_version") or "")
            != public.version
            or str(row.get("exercise_key") or "") != public.item_key
            or str(row.get("exercise_version") or "") != public.version
            or str(row.get("exercise_source_kind") or "") != "curated_fixture"
            or str(row.get("exercise_validation_status") or "") != "ready"
            or str(row.get("exercise_content_hash") or "")
            != str(row.get("materialization_exercise_content_hash") or "")
            or _string_tuple(row.get("exercise_capabilities_json"))
            != expected_capabilities
            or _optional_string(row.get("exercise_runtime_profile_key"))
            != _optional_string(row.get("runtime_profile_key"))
        ):
            raise TeachingArtifactCommitError(
                "Learning Item Practice materialization is stale or unavailable"
            )
        return exercise_version_id


def _learning_item_interaction(
    intent: TeachingInteractionIntent,
) -> LearningItemInteraction:
    try:
        return LearningItemInteraction(
            {
                TeachingInteractionIntent.STRUCTURED_ANSWER: "respond",
                TeachingInteractionIntent.EDIT_CODE: "edit",
                TeachingInteractionIntent.RUN_CODE: "run",
                TeachingInteractionIntent.REVIEW_DIFF: "review",
                TeachingInteractionIntent.EXECUTE_QUERY: "query",
                TeachingInteractionIntent.INTERACT_WITH_DEMO: "observe",
            }[intent]
        )
    except KeyError as exc:
        raise TeachingArtifactCommitError(
            "teaching interaction intent is not an Artifact intent"
        ) from exc


def _artifact_kind(public: LearningItemPublicV1) -> TutorArtifactKind:
    return TutorArtifactKind(
        {
            "code": "exercise_workspace",
            "sql": "sql_workspace",
            "demo": "demonstration",
            "knowledge_check": "knowledge_check",
            "model_review": "model_code_review",
        }[public.kind.value]
    )


def _artifact_presentation(
    *,
    public: LearningItemPublicV1,
    exercise_version_id: str | None,
    runtime_profile_key: str | None,
) -> TutorArtifactPresentationV1:
    content = public.content
    if isinstance(content, LearningItemCodeContentV1):
        exercise_id = _required_string(exercise_version_id, "exercise_version_id")
        return TutorArtifactExerciseWorkspacePresentationV1(
            exercise_version_id=exercise_id,
            language_id=content.language_id,
            editor_mode="code",
            starter_content=content.starter_code,
            starter_content_hash=sha256_text(content.starter_code),
            editable=True,
            live_preview=content.exercise_type == "browser_preview",
            runtime_profile_key=runtime_profile_key,
        )
    if isinstance(content, LearningItemSqlContentV1):
        exercise_id = _required_string(exercise_version_id, "exercise_version_id")
        return TutorArtifactSqlWorkspacePresentationV1(
            exercise_version_id=exercise_id,
            dialect=content.dialect,
            starter_query=content.starter_query,
            starter_query_hash=sha256_text(content.starter_query),
            schema_markdown=content.schema_markdown,
            max_rows=content.max_rows,
        )
    if isinstance(content, LearningItemSqlContentV2):
        exercise_id = _required_string(exercise_version_id, "exercise_version_id")
        return TutorArtifactSqlWorkspacePresentationV2(
            exercise_version_id=exercise_id,
            dialect=content.dialect,
            starter_query=content.starter_query,
            starter_query_hash=sha256_text(content.starter_query),
            tables=content.tables,
            max_rows=content.max_rows,
        )
    if isinstance(content, (LearningItemDemoContentV1, LearningItemDemoContentV2)):
        return build_demonstration_presentation(
            content=content,
            item_version=public.version,
            instruction_markdown=public.instruction_markdown,
        )
    if isinstance(content, LearningItemKnowledgeCheckContentV1):
        response_kind = {
            "single_choice": "single_select",
            "multiple_choice": "multi_select",
            "prediction": "prediction",
            "ordering": "ordering",
            "code_range": "code_range",
            "short_text": "short_text",
        }[content.response_kind]
        option_count = len(content.options)
        return TutorArtifactKnowledgeCheckPresentationV1(
            response_kind=response_kind,  # type: ignore[arg-type]
            prompt_markdown=content.prompt_markdown,
            options=tuple(
                TutorArtifactOptionV1(value=item.option_id, label=item.label)
                for item in content.options
            ),
            minimum_selections=(option_count if response_kind == "ordering" else 1),
            maximum_selections=(option_count if response_kind in {"multi_select", "ordering"} else 1),
            maximum_text_length=2_000,
            hints=build_hint_pages(public),
        )
    if isinstance(
        content,
        (LearningItemModelReviewContentV1, LearningItemModelReviewContentV2),
    ):
        exercise_id = _required_string(exercise_version_id, "exercise_version_id")
        if isinstance(content, LearningItemModelReviewContentV1):
            review_target = build_model_review_artifact_v2(
                language_id=content.artifact.language_id,
                runtime_label=content.artifact.runtime_label,
                modified_code=normalize_newlines(content.artifact.model_code),
            )
        else:
            artifact = content.artifact
            review_target = build_model_review_artifact_v2(
                language_id=artifact.language_id,
                runtime_label=artifact.runtime_label,
                source_code=artifact.source_code,
                modified_code=artifact.modified_code,
            )
            if review_target != artifact:
                raise TeachingArtifactCommitError(
                    "published model review diff identity is not canonical"
                )
        return TutorArtifactModelCodeReviewPresentationV2(
            exercise_version_id=exercise_id,
            presentation_hash=review_target.presentation_hash,
            review_target=review_target,
            review_categories=MODEL_REVIEW_CORE_CATEGORIES,
        )
    raise TeachingArtifactCommitError(
        "Learning Item public content cannot be materialized as an Artifact"
    )


def _allowed_artifact_actions(
    public: LearningItemPublicV1,
) -> tuple[TutorArtifactActionKind, ...]:
    actions: list[TutorArtifactActionKind] = []
    if public.hints:
        actions.append(TutorArtifactActionKind.REQUEST_HINT)
    if isinstance(public.content, LearningItemKnowledgeCheckContentV1):
        actions.append(TutorArtifactActionKind.REQUEST_DIRECT_ANSWER)
    if isinstance(public.content, LearningItemDemoContentV2):
        actions.append(TutorArtifactActionKind.COMPLETE_DEMO)
    elif not isinstance(public.content, LearningItemDemoContentV1):
        actions.append(
            {
                "code": TutorArtifactActionKind.RUN,
                "sql": TutorArtifactActionKind.RUN,
                "knowledge_check": TutorArtifactActionKind.RESPOND,
                "model_review": TutorArtifactActionKind.COMPLETE_REVIEW,
            }[public.kind.value]
        )
    actions.append(TutorArtifactActionKind.CANCEL)
    return tuple(actions)


def _artifact_source_references(
    *,
    public: LearningItemPublicV1,
    checkpoint_id: str,
    checkpoint_version: int,
    checkpoint_source_hash: str,
    exercise_version_id: str | None,
    exercise_content_hash: str | None,
) -> tuple[TutorArtifactSourceReferenceV1, ...]:
    references = [
        TutorArtifactSourceReferenceV1(
            kind="teaching_checkpoint",
            reference_id=checkpoint_id,
            reference_version=checkpoint_version,
            content_hash=checkpoint_source_hash,
            label="Current teaching checkpoint",
        )
    ]
    if exercise_version_id is not None:
        references.append(
            TutorArtifactSourceReferenceV1(
                kind="exercise_version",
                reference_id=exercise_version_id,
                content_hash=exercise_content_hash,
                label="Published Practice authority",
            )
        )
    remaining = 12 - len(references)
    source_id_counts = Counter(item.source_id for item in public.source_references)
    references.extend(
        _artifact_source_reference(
            item,
            index=index,
            duplicate_source_id=source_id_counts[item.source_id] > 1,
        )
        for index, item in enumerate(public.source_references[:remaining])
    )
    return tuple(references)


def _artifact_source_reference(
    source: LearningItemSourceReferenceV1,
    *,
    index: int,
    duplicate_source_id: bool,
) -> TutorArtifactSourceReferenceV1:
    reference_id = source.source_id
    if duplicate_source_id:
        reference_id = f"source:{sha256_text(f'{source.source_id}:{source.source_version}:{source.locator}:{index}')}"
    label = f"{source.source_version} · {source.locator}"[:240]
    return TutorArtifactSourceReferenceV1(
        kind="source_citation",
        reference_id=reference_id,
        content_hash=source.content_hash,
        label=label,
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(str(item) for item in value)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TeachingArtifactCommitError(f"{label} must be positive")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise TeachingArtifactCommitError(f"{label} must be positive") from exc
    if parsed < 1:
        raise TeachingArtifactCommitError(f"{label} must be positive")
    return parsed


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized if normalized else None


def _required_string(value: str | None, label: str) -> str:
    if value is None:
        raise TeachingArtifactCommitError(f"{label} is required")
    return value


__all__ = (
    "PostgresTeachingArtifactMaterializer",
    "PreparedTeachingArtifact",
    "TeachingArtifactCommitError",
)
