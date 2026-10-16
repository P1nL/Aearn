"""Exact Learning Item materialization for atomic teaching Artifact commits."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

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
    canonical_hash,
    stable_key,
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

from app.services.learning.item_supply.private_enhancement_contracts import PrivateTeachingDeliveryContext

if TYPE_CHECKING:
    from app.services.learning.item_supply.finite_course_mapping_contracts import FiniteCourseMappingReceiptV1
    from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability, NativeResolvedContent
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2


class TeachingArtifactCommitError(ValueError):
    """The selected Artifact can no longer be proven safe and executable."""


@dataclass(frozen=True, slots=True)
class NativeTeachingPracticeDeliveryContext:
    """Explicit internal injection; persisted references are DATA, not authority.

    The original concrete owner must be alive on the writer's connection. Nothing
    here restores an old capability or enables API/worker composition globally.
    """

    exposure_owner: NativeExposureOwnerV2 = field(repr=False)
    mapping_receipt_id: UUID
    reservation_key: str
    selected_version_id: UUID
    _prepared: dict[str, PreparedTeachingArtifact] = field(
        default_factory=dict, init=False, repr=False, compare=False,
    )


@dataclass(frozen=True, slots=True)
class _PreparedNativePracticeDelivery:
    context: NativeTeachingPracticeDeliveryContext = field(repr=False)
    capability: IssuedNativePackCapability = field(repr=False)
    delivery_id: UUID
    creation_receipt_id: UUID
    prepared_hash: str


@dataclass(frozen=True, slots=True)
class _PreparedPrivatePracticeDelivery:
    context: PrivateTeachingDeliveryContext = field(repr=False)
    receipt_id: UUID
    prepared_hash: str


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
    native_practice_delivery: _PreparedNativePracticeDelivery | None = field(
        default=None, repr=False, compare=False,
    )
    private_practice_delivery: _PreparedPrivatePracticeDelivery | None = field(default=None, repr=False, compare=False)


class PostgresTeachingArtifactMaterializer:
    """Revalidate a selected Learning Item and project one exact Artifact facade.

    The materializer reads only published public content plus the immutable Practice
    materialization receipt. The opt-in native branch delegates private evidence
    to its original concrete owner; only public content reaches the Artifact.
    Neither branch creates score, mastery, progress, Gate, or Review state.
    """

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings,
        native_practice_delivery: NativeTeachingPracticeDeliveryContext | PrivateTeachingDeliveryContext | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._private_practice_delivery = native_practice_delivery if type(native_practice_delivery) is PrivateTeachingDeliveryContext else None
        self._native_practice_delivery = native_practice_delivery if type(native_practice_delivery) is NativeTeachingPracticeDeliveryContext else None
        if native_practice_delivery is not None and self._private_practice_delivery is None and self._native_practice_delivery is None:
            raise TeachingArtifactCommitError('teaching delivery concrete context required')

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

        if interaction.artifact_handle.startswith('lip:v2:'):
            return self._prepare_private(step=step, run_id=run_id, user_id=user_id,
                conversation_id=conversation_id, teaching_session_id=teaching_session_id,
                checkpoint_id=checkpoint_id, checkpoint_source_hash=checkpoint_source_hash,
                session_version=session_version, learning_track_id=learning_track_id, knowledge_key=knowledge_key,
                track_version=track_version, progress_version=progress_version, assignment_version=assignment_version,
                available_capabilities=capabilities)
        native_locked_version = self._lock_native_practice_version(interaction.artifact_handle)
        # Native source/current fences and the exact version lock have completed
        # before this NEW READ COMMITTED statement reads publication/materialization.
        # With no explicit context, the legacy query and lock order stay unchanged.
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

        from app.services.learning.catalog_scope import (
            LearningCatalogScopeError, resolve_session_catalog_knowledge_key,
        )
        try:
            catalog_key = resolve_session_catalog_knowledge_key(
                self._conn, user_id=user_id, track_id=learning_track_id,
                teaching_session_id=teaching_session_id, knowledge_key=knowledge_key,
            )
        except LearningCatalogScopeError as exc:
            raise TeachingArtifactCommitError("teaching Artifact catalog authority is missing") from exc
        public = self._validate_learning_item(
            row=row,
            expected_handle=interaction.artifact_handle,
            expected_knowledge_key=(self._native_public_catalog(catalog_key)
                                    if native_locked_version is not None else catalog_key),
            available_capabilities=capabilities,
            intent=interaction.intent,
        )
        self._validate_runtime(row=row, public=public)
        native_content = None
        if str(row.get("exercise_source_kind") or "") == "registered_author":
            if native_locked_version != str(row["version_id"]):
                raise TeachingArtifactCommitError("native teaching practice source-first identity is required")
            # Re-resolve current source/runtime with a fresh server clock after
            # the bank-lock wait and fresh event/materialization read, not discovery.
            native_content = self._resolve_native_content(row=row, public=public)
        elif native_locked_version is not None:
            raise TeachingArtifactCommitError("native teaching practice discovered provenance changed")
        exercise_version_id = self._validate_practice_materialization(
            row=row,
            public=public,
            native_content=native_content,
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
        native_delivery = (
            self._prepare_native_practice_delivery(row=row, request=request, content=native_content)
            if native_content is not None else None
        )
        prepared = PreparedTeachingArtifact(
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
            native_practice_delivery=native_delivery,
        )
        if native_delivery is not None:
            native_delivery.context._prepared[prepared.creation_key] = prepared
        return prepared

    def create(
        self,
        prepared: PreparedTeachingArtifact,
        *,
        occurred_at: datetime,
    ) -> LearningArtifactWriteResult:
        if prepared.private_practice_delivery is not None:
            self._require_private_practice_delivery(prepared)
        elif prepared.artifact_handle.startswith('lip:v2:'):
            raise TeachingArtifactCommitError('private issued preparation cannot be removed')
        elif prepared.native_practice_delivery is not None:
            self._require_native_practice_delivery(prepared)
        else:
            # A serialized/copied preparation cannot erase the native issuer.
            # This read changes no legacy curated publication or writer policy.
            material = self._conn.execute(
                "SELECT e.source_kind FROM tutor_learning_item_practice_materializations m "
                "JOIN tutor_exercise_versions e ON e.id=m.exercise_version_id WHERE m.version_id=%s",
                (prepared.learning_item_version_id,),
            ).fetchone()
            if material is not None and material["source_kind"] == "registered_author":
                raise TeachingArtifactCommitError("native teaching practice issued preparation is required")
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

    def _private_context(self, context: PrivateTeachingDeliveryContext | None) -> PrivateTeachingDeliveryContext:
        from app.services.learning.item_supply.private_native_exposure import PrivateNativeExposureOwner
        from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner
        if (type(context) is not PrivateTeachingDeliveryContext or type(context.exposure_owner) is not PrivateNativeExposureOwner
                or type(context.exposure_owner.type_owner) is not PrivateNativeTypeEvidenceOwner
                or context.exposure_owner.conn is not self._conn or context.exposure_owner.type_owner.settings is not self._settings
                or not context.exposure_owner.enabled or not context.exposure_owner.type_owner.enabled
                or any(type(v) is not UUID for v in (context.mapping_receipt_id,context.reservation_id,context.selected_version_id,context.run_id,context.pack_task_id))
                or context.purpose not in {'knowledge_check','remediation','transfer_check'}
                or ((context.purpose=='knowledge_check')!=(context.parent_artifact_id is None))
                or (context.parent_artifact_id is not None and type(context.parent_artifact_id) is not UUID)
                or not self._settings.tutor_learning_artifacts_enabled or not self._settings.tutor_artifact_teaching_mode_enabled):
            raise TeachingArtifactCommitError('private concrete same-connection current delivery owner required')
        context.exposure_owner.type_owner._guard()
        return context

    def _prepare_private(self, *, step: TeachingStepDecision, run_id: str, user_id: str,
                         conversation_id: str, teaching_session_id: str, checkpoint_id: str,
                         checkpoint_source_hash: str, session_version: int, learning_track_id: str,
                         knowledge_key: str, track_version: int, progress_version: int,
                         assignment_version: int, available_capabilities: tuple[str, ...]) -> PreparedTeachingArtifact:
        from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
        try:
            context = self._private_context(self._private_practice_delivery)
            owner = context.exposure_owner
            interaction = step.interaction
            if (interaction is None or interaction.artifact_handle != 'lip:v2:' + str(context.selected_version_id)
                    or context.run_id != UUID(run_id) or owner.user_id != UUID(user_id)):
                raise TeachingArtifactCommitError('private exact advertised per-run practice required')
            mapping = owner.type_owner.resolve_mapping(context.mapping_receipt_id)
            content = owner.type_owner.query.resolve_content(context.selected_version_id)
            q, publication = content.quality, content.publication
            public = q.source.public
            if (q.ref.pack_task_id != context.pack_task_id or q.ref.mapping_receipt_id != context.mapping_receipt_id
                    or q.ref.slot != ('remediation' if context.purpose=='remediation' else 'practice')
                    or public.kind.value != 'knowledge_check'
                    or public.purpose.value != ('remediation' if context.purpose=='remediation' else 'knowledge_check')
                    or _learning_item_interaction(interaction.intent) not in public.allowed_interactions
                    or not set(q.source.blueprint.required_capabilities).issubset(available_capabilities)):
                raise TeachingArtifactCommitError('private current mapped original practice contract required')
            exercise = self._conn.execute('SELECT source_kind,validation_status,content_hash FROM tutor_exercise_versions WHERE id=%s',
                (publication.exercise_version_id,)).fetchone()
            if (exercise is None or exercise['source_kind'] != 'registered_author' or exercise['validation_status'] != 'ready'
                    or exercise['content_hash'] != publication.exercise_content_hash):
                raise TeachingArtifactCommitError('private actual original exercise authority required')
            owner.type_owner.query.resolve_content(context.selected_version_id)
            request = TutorArtifactCreate(user_id=user_id, conversation_id=conversation_id, turn_id=run_id,
                learning_track_id=learning_track_id, knowledge_key=knowledge_key, teaching_session_id=teaching_session_id,
                checkpoint_id=checkpoint_id, track_version=track_version, progress_version=progress_version,
                assignment_version=assignment_version, owner_kind=TutorArtifactOwnerKind.LEARNING_ITEM,
                owner_id=str(context.selected_version_id), owner_version=1, owner_context_version=session_version,
                artifact_kind=TutorArtifactKind.KNOWLEDGE_CHECK, purpose=TutorArtifactPurpose(context.purpose),
                state=TutorArtifactState.ACTIVE, blocking=True, title=public.title, instruction_markdown=public.instruction_markdown,
                difficulty=TutorArtifactDifficulty(public.difficulty.value),
                presentation=_artifact_presentation(public=public,exercise_version_id=str(publication.exercise_version_id),runtime_profile_key=None),
                allowed_actions=_allowed_artifact_actions(public),
                source_references=_artifact_source_references(public=public,checkpoint_id=checkpoint_id,checkpoint_version=session_version,
                    checkpoint_source_hash=checkpoint_source_hash,exercise_version_id=str(publication.exercise_version_id),
                    exercise_content_hash=publication.exercise_content_hash))
            self._require_native_teaching_scope(request=request, context=context, mapping=mapping)
            receipt = owner.prepare_practice_delivery(reservation_id=context.reservation_id,version_id=context.selected_version_id,
                run_id=context.run_id,creation_payload=request.model_dump(mode='json'),purpose=context.purpose,parent_artifact_id=context.parent_artifact_id)
            delivery = _PreparedPrivatePracticeDelivery(context,receipt,canonical_hash(request.model_dump(mode='json')))
            prepared = PreparedTeachingArtifact(request=request,creation_key=f'teaching-artifact:{run_id}',
                interaction_intent=interaction.intent,artifact_handle=publication.item_handle,
                learning_item_version_id=str(context.selected_version_id),publication_event_id=str(publication.publication_id),
                publication_state_version=1,learning_item_content_hash=q.source.content_hash,private_practice_delivery=delivery)
            context._prepared[prepared.creation_key] = prepared
            return prepared
        except PrivateNativePending as exc:
            raise TeachingArtifactCommitError('private original current delivery unavailable') from exc

    def _require_private_practice_delivery(self, prepared: PreparedTeachingArtifact) -> None:
        delivery = prepared.private_practice_delivery
        if type(delivery) is not _PreparedPrivatePracticeDelivery:
            raise TeachingArtifactCommitError('private issued preparation required')
        context = self._private_context(delivery.context)
        if (context is not self._private_practice_delivery or context._prepared.get(prepared.creation_key) is not prepared
                or prepared.creation_key != f'teaching-artifact:{context.run_id}'
                or prepared.learning_item_version_id != str(context.selected_version_id)
                or delivery.prepared_hash != canonical_hash(prepared.request.model_dump(mode='json'))):
            raise TeachingArtifactCommitError('private same original prepared request required')
        mapping = context.exposure_owner.type_owner.resolve_mapping(context.mapping_receipt_id)
        self._require_native_teaching_scope(request=prepared.request,context=context,mapping=mapping)
        checked = self._conn.execute('SELECT item_supply_internal.private_native_consumer_current(%s) AS ok',
            (delivery.receipt_id,)).fetchone()
        self._private_context(context)
        if checked is None or checked['ok'] is not True:
            raise TeachingArtifactCommitError('private current same-TX creation receipt required')

    def _native_context(
        self, context: NativeTeachingPracticeDeliveryContext | None,
    ) -> NativeTeachingPracticeDeliveryContext:
        if (
            not self._settings.tutor_learning_artifacts_enabled
            or not self._settings.tutor_artifact_teaching_mode_enabled
        ):
            raise TeachingArtifactCommitError("native teaching Artifact materialization is disabled")
        if type(context) is not NativeTeachingPracticeDeliveryContext:
            raise TeachingArtifactCommitError("native teaching practice concrete context is required")
        # Lazy imports keep the legacy/default-off path outside the native graph.
        from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
        from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
        owner = context.exposure_owner
        if (
            type(owner) is not NativeExposureOwnerV2
            or owner.conn is not self._conn
            or type(owner.type_owner) is not NativeTypeEvidenceOwner
            or owner.type_owner.conn is not self._conn
            or owner.type_owner.settings is not self._settings
            or owner.user_id != owner.type_owner.user_id
            or owner.epoch != owner.type_owner.epoch
            or not owner.enabled
            or type(context.mapping_receipt_id) is not UUID
            or type(context.selected_version_id) is not UUID
        ):
            raise TeachingArtifactCommitError("native teaching practice same-connection owner is required")
        return context

    def _lock_native_practice_version(self, expected_handle: str) -> str | None:
        """Discover DATA only, then follow ORIGINAL concrete source -> bank order."""
        if self._native_practice_delivery is None:
            return None
        from app.services.learning.item_supply.native_exposure_contracts import NativeExposurePending
        from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
        from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposurePending

        discovered = self._conn.execute(
            "SELECT v.id AS version_id,e.source_kind FROM tutor_learning_item_versions v "
            "LEFT JOIN tutor_learning_item_practice_materializations m ON m.version_id=v.id "
            "LEFT JOIN tutor_exercise_versions e ON e.id=m.exercise_version_id WHERE v.handle=%s",
            (expected_handle,),
        ).fetchone()
        if discovered is None or discovered["source_kind"] != "registered_author":
            return None
        context = self._native_context(self._native_practice_delivery)
        if str(context.selected_version_id) != str(discovered["version_id"]):
            raise TeachingArtifactCommitError("native teaching practice exact selected version is required")
        try:
            # ORIGINAL exposure owner requires READ COMMITTED and the current
            # user/epoch transaction before any native bank lock is acquired.
            context.exposure_owner._lock()
            context.exposure_owner.type_owner.resolve_mapping(context.mapping_receipt_id)
            # This ORIGINAL owner locks current corpus/source before its bank
            # SHARE lock and re-fences source time after that lock wait.
            content = context.exposure_owner.type_owner.resolve_content(context.selected_version_id, current=True)
        except (NativeTypeEvidencePending, NativeTypeExposurePending, NativeExposurePending) as exc:
            raise TeachingArtifactCommitError("native teaching practice current content is unavailable") from exc
        if (
            content.consumption is None
            or content.content.version_id != context.selected_version_id
            or content.content.item_handle != expected_handle
            or content.publication.version_id != context.selected_version_id
        ):
            raise TeachingArtifactCommitError("native teaching practice exact source-first identity is required")
        locked = self._conn.execute(
            "SELECT id FROM tutor_learning_item_versions WHERE id=%s AND handle=%s FOR UPDATE",
            (context.selected_version_id, expected_handle),
        ).fetchone()
        if locked is None:
            raise TeachingArtifactCommitError("native teaching practice exact bank version is unavailable")
        # No event/materialization from the discovery snapshot is consumed.
        # prepare performs its original full read as a separate statement and
        # calls the original current owner again after this possible lock wait.
        return str(context.selected_version_id)

    def _native_public_catalog(self, actual_catalog: str) -> str:
        from app.services.learning.item_supply.native_consumer_bridge import creation_catalog

        context = self._native_context(self._native_practice_delivery)
        try:
            return creation_catalog(context, actual_catalog=actual_catalog)
        except (TypeError, ValueError) as exc:
            raise TeachingArtifactCommitError("native teaching practice catalog mapping is unavailable") from exc

    def _resolve_native_content(
        self, *, row: Mapping[str, object], public: LearningItemPublicV1,
    ) -> NativeResolvedContent:
        from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending

        context = self._native_context(self._native_practice_delivery)
        if str(context.selected_version_id) != str(row["version_id"]):
            raise TeachingArtifactCommitError("native teaching practice exact selected version is required")
        try:
            content = context.exposure_owner.type_owner.resolve_content(context.selected_version_id, current=True)
        except NativeTypeEvidencePending as exc:
            raise TeachingArtifactCommitError("native teaching practice current content is unavailable") from exc
        proof = content.publication
        if (
            content.consumption is None
            or content.source.public != public
            or content.spec.allocation.slot != "practice"
            or content.content.item_handle != str(row["handle"])
            or content.content.content_hash != str(row["content_hash"])
            or str(proof.version_id) != str(row["version_id"])
            or str(proof.publication_event_id) != str(row["publication_event_id"])
            or str(proof.materialization_id) != str(row["materialization_id"])
            or str(proof.exercise_version_id) != str(row["exercise_version_id"])
        ):
            raise TeachingArtifactCommitError("native teaching practice exact public materialization is required")
        return content

    def _prepare_native_practice_delivery(
        self, *, row: Mapping[str, object], request: TutorArtifactCreate,
        content: NativeResolvedContent,
    ) -> _PreparedNativePracticeDelivery:
        from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
        from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposurePending

        context = self._native_context(self._native_practice_delivery)
        owner = context.exposure_owner
        try:
            mapping = owner.type_owner.resolve_mapping(context.mapping_receipt_id)
            self._require_native_teaching_scope(request=request, context=context, mapping=mapping)
            # Reservation JSON provides exact reference coordinates only. Fresh
            # concrete resolve_pack/require_pack below supplies current authority.
            reserved = self._conn.execute(
                "SELECT request_json FROM tutor_item_supply_type_exposure_reservations "
                "WHERE user_id=%s AND epoch=%s AND operation_key=%s FOR SHARE",
                (owner.user_id, owner.epoch, stable_key(context.reservation_key, label="native type reservation")),
            ).fetchone()
            if reserved is None or not isinstance(reserved["request_json"], dict):
                raise TeachingArtifactCommitError("native teaching practice reservation is required")
            refs = reserved["request_json"]
            if refs.get("mapping_receipt_id") != str(context.mapping_receipt_id):
                raise TeachingArtifactCommitError("native teaching practice exact reservation mapping is required")
            observation = owner.snapshot_v2()
            if observation.snapshot_id is None:
                raise TeachingArtifactCommitError("native teaching practice complete current exposure is required")
            capability = owner.type_owner.resolve_pack(
                mapping_receipt_id=context.mapping_receipt_id,
                candidate_version_ids=tuple(UUID(v) for v in refs["candidate_version_ids"]),
                exposure_snapshot_id=observation.snapshot_id,
                relation_receipt_ids=tuple(UUID(v) for v in refs["relation_receipt_ids"]),
            )
            pack = owner.type_owner.require_pack(capability)
            practice = next((c for c in pack.selected if c.member.slot == "practice"
                             and c.version_id == context.selected_version_id), None)
            if (
                pack.request != mapping.pack_request
                or practice is None
                or practice.owner_id is not None or practice.epoch is not None
                or practice.storage_scope_id != pack.request.storage_scope_id
                or practice.candidate.visibility != "public" or practice.candidate.owner_ref is not None
                or practice.type_evidence.content != content.content
                or str(practice.materialization_id) != str(row["materialization_id"])
                or str(practice.publication_id) != str(row["publication_event_id"])
                or practice.proof_id != content.publication.proof_id
            ):
                raise TeachingArtifactCommitError("native teaching practice exact complete-pack member is required")
            delivery_id = owner.prepare_practice_delivery(
                reservation_key=context.reservation_key,
                version_id=context.selected_version_id,
                delivery_key=f"teaching-artifact:{request.turn_id}",
            )
            from app.services.learning.item_supply.native_consumer_bridge import persist_creation

            creation_receipt_id = persist_creation(context, capability=capability,
                                                   delivery_id=delivery_id, request=request)
        except (NativeTypeEvidencePending, NativeTypeExposurePending, KeyError, TypeError, ValueError) as exc:
            raise TeachingArtifactCommitError("native teaching practice current delivery is unavailable") from exc
        return _PreparedNativePracticeDelivery(
            context=context, capability=capability, delivery_id=delivery_id,
            creation_receipt_id=creation_receipt_id,
            prepared_hash=canonical_hash(request.model_dump(mode="json")),
        )

    def _require_native_practice_delivery(self, prepared: PreparedTeachingArtifact) -> None:
        from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending

        delivery = prepared.native_practice_delivery
        if type(delivery) is not _PreparedNativePracticeDelivery:
            raise TeachingArtifactCommitError("native teaching practice issued preparation is required")
        context = self._native_context(delivery.context)
        if (
            context._prepared.get(prepared.creation_key) is not prepared
            or prepared.creation_key != f"teaching-artifact:{prepared.request.turn_id}"
            or delivery.prepared_hash != canonical_hash(prepared.request.model_dump(mode="json"))
            or prepared.learning_item_version_id != str(context.selected_version_id)
            or prepared.request.owner_id != prepared.learning_item_version_id
        ):
            raise TeachingArtifactCommitError("native teaching practice issued preparation is required")
        owner = context.exposure_owner
        try:
            pack = owner.type_owner.require_pack(delivery.capability)
            mapping = owner.type_owner.resolve_mapping(context.mapping_receipt_id)
            self._require_native_teaching_scope(request=prepared.request, context=context, mapping=mapping)
        except NativeTypeEvidencePending as exc:
            raise TeachingArtifactCommitError("native teaching practice authority expired before write") from exc
        row = self._conn.execute(
            "SELECT d.version_id,d.binding_json,d.delivery_key,d.delivery_txid=txid_current() AS current_tx,"
            "e.mapping_receipt_id,e.request_hash,e.valid_until>clock_timestamp() AS current_eligibility,"
            "item_supply_internal.type_exposure_current(d.exposure_snapshot_id,d.user_id,d.epoch) AS exposure "
            "FROM tutor_item_supply_type_exposure_deliveries d "
            "JOIN tutor_item_supply_native_eligibility e ON e.id=d.eligibility_id AND e.user_id=d.user_id AND e.epoch=d.epoch "
            "WHERE d.id=%s AND d.user_id=%s AND d.epoch=%s AND d.scope_id=%s FOR SHARE OF d,e",
            (delivery.delivery_id, owner.user_id, owner.epoch, pack.request.storage_scope_id),
        ).fetchone()
        practice = next((c for c in pack.selected if c.member.slot == "practice"
                         and c.version_id == context.selected_version_id), None)
        if (
            row is None or practice is None
            or row["current_tx"] is not True or row["current_eligibility"] is not True
            or row["exposure"] is None
            or str(row["version_id"]) != prepared.learning_item_version_id
            or row["binding_json"] != practice.type_evidence.content.model_dump(mode="json")
            or row["delivery_key"] != prepared.creation_key
            or str(row["mapping_receipt_id"]) != str(context.mapping_receipt_id)
            or row["request_hash"] != mapping.pack_request.request_hash
            or pack.request != mapping.pack_request
            or practice.candidate.item_handle != prepared.artifact_handle
            or practice.candidate.content_hash != prepared.learning_item_content_hash
            or str(practice.publication_id) != prepared.publication_event_id
            or prepared.publication_state_version != prepared.request.owner_version
        ):
            raise TeachingArtifactCommitError("native teaching practice same-transaction delivery is required")
        # Sample/fence again after the persisted-delivery lock wait. The original
        # writer's502 capture remains the final DB effect check, not this DTO.
        try:
            owner.type_owner.require_pack(delivery.capability)
        except NativeTypeEvidencePending as exc:
            raise TeachingArtifactCommitError("native teaching practice authority expired before write") from exc

        self._native_context(context)
        creation = self._conn.execute(
            "SELECT item_supply_internal.native_consumer_receipt_current(%s) AS current",
            (delivery.creation_receipt_id,),
        ).fetchone()
        if creation is None or creation["current"] is not True:
            raise TeachingArtifactCommitError("native teaching practice creation receiver authority is required")
        self._native_context(context)

    def _require_native_teaching_scope(
        self, *, request: TutorArtifactCreate,
        context: NativeTeachingPracticeDeliveryContext | PrivateTeachingDeliveryContext,
        mapping: FiniteCourseMappingReceiptV1,
    ) -> None:
        node = mapping.frozen_node
        owner = context.exposure_owner
        checkpoint_reference = next((r for r in request.source_references if r.kind == "teaching_checkpoint"), None)
        if (
            (str(node.user_id), node.epoch, str(node.track_id), node.knowledge_key)
            != (request.user_id, owner.epoch, request.learning_track_id, request.knowledge_key)
            or node.user_id != owner.user_id
            or request.turn_id is None or request.teaching_session_id is None
            or request.checkpoint_id is None or request.owner_context_version is None
            or checkpoint_reference is None
            or checkpoint_reference.reference_id != request.checkpoint_id
            or checkpoint_reference.reference_version != request.owner_context_version
        ):
            raise TeachingArtifactCommitError("native teaching practice exact learner scope is required")
        row = self._conn.execute(
            """SELECT scopes.active_plan_revision_id,nodes.id AS node_id,
                      sessions.version AS session_version,checkpoints.source_hash,
                      tracks.version AS track_version,progress.version AS progress_version,
                      assignments.assignment_version
               FROM tutor_run_teaching_scopes scopes
               JOIN tutor_teaching_sessions sessions ON sessions.id=scopes.teaching_session_id
                 AND sessions.user_id=scopes.user_id AND sessions.conversation_id=scopes.conversation_id
                 AND sessions.track_id=scopes.track_id AND sessions.knowledge_key=scopes.knowledge_key
                 AND sessions.active_plan_revision_id=scopes.active_plan_revision_id
               JOIN tutor_teaching_session_checkpoints checkpoints ON checkpoints.id=sessions.current_checkpoint_id
                 AND checkpoints.teaching_session_id=sessions.id AND checkpoints.user_id=scopes.user_id
                 AND checkpoints.conversation_id=scopes.conversation_id AND checkpoints.source_run_id=scopes.run_id
                 AND checkpoints.predecessor_checkpoint_id=scopes.checkpoint_id
                 AND checkpoints.session_version=sessions.version
               JOIN tutor_learning_tracks tracks ON tracks.id=scopes.track_id AND tracks.user_id=scopes.user_id
               JOIN tutor_track_active_plans active ON active.track_id=scopes.track_id AND active.user_id=scopes.user_id
                 AND active.revision_id=scopes.active_plan_revision_id
               JOIN tutor_track_plan_nodes nodes ON nodes.revision_id=active.revision_id
                 AND nodes.track_id=scopes.track_id AND nodes.user_id=scopes.user_id AND nodes.knowledge_key=scopes.knowledge_key
               JOIN tutor_track_node_progress progress ON progress.track_id=scopes.track_id
                 AND progress.user_id=scopes.user_id AND progress.knowledge_key=scopes.knowledge_key
               JOIN tutor_lesson_assignments assignments ON assignments.id=scopes.lesson_assignment_id
                 AND assignments.user_id=scopes.user_id AND assignments.track_id=scopes.track_id
                 AND assignments.knowledge_key=scopes.knowledge_key AND assignments.status='active'
                 AND assignments.document_id=scopes.document_id
               JOIN tutor_lesson_documents documents ON documents.id=assignments.document_id
                 AND documents.content_hash=scopes.document_content_hash
               WHERE scopes.run_id=%s AND scopes.user_id=%s AND scopes.conversation_id=%s
                 AND scopes.teaching_session_id=%s AND scopes.track_id=%s AND scopes.knowledge_key=%s
                 AND checkpoints.id=%s AND sessions.version=scopes.session_version+1
                 AND sessions.status IN ('active','paused')
                 AND sessions.track_version=scopes.track_version AND tracks.version=scopes.track_version
                 AND sessions.progress_version=scopes.progress_version AND progress.version=scopes.progress_version
                 AND sessions.lesson_assignment_id=scopes.lesson_assignment_id
                 AND sessions.assignment_version=scopes.assignment_version AND assignments.assignment_version=scopes.assignment_version
                 AND sessions.document_id=scopes.document_id AND sessions.document_content_hash=scopes.document_content_hash
               FOR SHARE OF sessions,tracks,active,nodes,progress,assignments""",
            (request.turn_id, request.user_id, request.conversation_id, request.teaching_session_id,
             request.learning_track_id, request.knowledge_key, request.checkpoint_id),
        ).fetchone()
        if row is None or row["source_hash"] != checkpoint_reference.content_hash or (
            str(row["active_plan_revision_id"]), str(row["node_id"]), row["session_version"],
            row["track_version"], row["progress_version"], row["assignment_version"],
        ) != (
            str(node.revision_id), str(node.node_id), request.owner_context_version,
            request.track_version, request.progress_version, request.assignment_version,
        ):
            raise TeachingArtifactCommitError("native teaching practice exact current turn context is required")

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
        native_content: NativeResolvedContent | None = None,
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
            or str(row.get("exercise_source_kind") or "")
            != ("registered_author" if native_content is not None else "curated_fixture")
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
    "NativeTeachingPracticeDeliveryContext",
    "PostgresTeachingArtifactMaterializer",
    "PreparedTeachingArtifact",
    "TeachingArtifactCommitError",
)
