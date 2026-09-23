"""Tutor-driven, read-only Lesson source candidates and atomic Artifact sidecars."""
from __future__ import annotations

from collections.abc import Mapping
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata
from typing import Literal, cast

from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import Settings
from app.models.lesson_documents import (
    LessonBlockReferenceSourceV1,
    LessonContextReferenceSourceV1,
)
from app.services.learning.artifacts.contracts import (
    TutorArtifactCreate,
    TutorArtifactKind,
    TutorArtifactOwnerKind,
    TutorArtifactPurpose,
    TutorArtifactSourceInspectorPresentationV1,
    TutorArtifactSourceReferenceV1,
    TutorArtifactState,
    canonical_hash,
)
from app.services.learning.artifacts.conversation_events import (
    ArtifactConversationEventError,
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.repository import (
    LearningArtifactRepositoryError,
    LearningArtifactWriteResult,
    PostgresLearningArtifactRepository,
)
from app.services.learning.lesson_contracts import LessonBlock, lesson_block_payload
from app.services.learning.lesson_projection import lesson_block_public_text
from app.services.learning.lesson_references import (
    LessonDocumentReferenceError,
    LessonDocumentReferenceResolver,
)
from app.services.learning.lesson_repository import (
    LessonNotFound,
    PostgresLessonDocumentRepository,
)
from app.services.learning.teaching_contracts import TeachingStepDecision, stable

SOURCE_INSPECTOR_HANDLE_PREFIX = "lesson-source:"
_SOURCE_CANDIDATE_SCHEMA_VERSION = "lesson_source_candidate_v1"
_SOURCE_BINDING_SCHEMA_VERSION = "lesson_source_binding_v1"
_MAX_SOURCE_CANDIDATES = 2
_MAX_PROVIDER_EXCERPT = 320


class SourceInspectorCommitError(ValueError):
    """A selected Lesson source can no longer be proven current and safe."""


class SourceInspectorCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["lesson_source_candidate_v1"] = "lesson_source_candidate_v1"
    handle: str = Field(min_length=78, max_length=78, pattern=r"^lesson-source:[0-9a-f]{64}$")
    source_kind: Literal["context_reference", "lesson_block"]
    source_id: str = Field(min_length=1, max_length=240)
    user_id: str = Field(min_length=1, max_length=120)
    conversation_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    track_id: str = Field(min_length=1, max_length=120)
    knowledge_key: str = Field(min_length=1, max_length=160)
    assignment_id: str = Field(min_length=1, max_length=120)
    assignment_version: int = Field(ge=1)
    document_id: str = Field(min_length=1, max_length=120)
    document_content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    block_id: str = Field(min_length=1, max_length=160)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=12)
    selected_citation_id: str | None = Field(default=None, min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    excerpt: str = Field(min_length=1, max_length=800)
    recently_displayed: bool = Field(default=False, strict=True)

    @field_validator("knowledge_key", "block_id")
    @classmethod
    def stable_keys(cls, value: str) -> str:
        return stable(value, "Lesson source candidate key")

    @field_validator("citation_ids")
    @classmethod
    def bounded_citations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not item or len(item) > 160 for item in value):
            raise ValueError("Lesson source candidate citations are invalid")
        return value

    @model_validator(mode="after")
    def exact_handle(self) -> "SourceInspectorCandidate":
        if self.handle != _candidate_handle(self.binding_identity()):
            raise ValueError("Lesson source candidate handle does not match its exact binding")
        if self.selected_citation_id is not None and self.selected_citation_id not in self.citation_ids:
            raise ValueError("selected Lesson citation is not present in the frozen block")
        return self

    def binding_identity(self) -> dict[str, object]:
        return {
            "schema_version": _SOURCE_BINDING_SCHEMA_VERSION,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "track_id": self.track_id,
            "knowledge_key": self.knowledge_key,
            "assignment_id": self.assignment_id,
            "assignment_version": self.assignment_version,
            "document_id": self.document_id,
            "document_content_hash": self.document_content_hash,
            "block_id": self.block_id,
            "citation_ids": list(self.citation_ids),
            "selected_citation_id": self.selected_citation_id,
            "excerpt_hash": canonical_hash({"excerpt": self.excerpt}),
        }

    def provider_evidence(self) -> dict[str, object]:
        return {
            "kind": _SOURCE_CANDIDATE_SCHEMA_VERSION,
            "handle": self.handle,
            "title": self.title,
            "excerpt": self.excerpt[:_MAX_PROVIDER_EXCERPT],
            "recently_displayed": self.recently_displayed,
        }


@dataclass(frozen=True, slots=True)
class PreparedSourceInspector:
    request: TutorArtifactCreate
    creation_key: str
    source_handle: str


class PostgresSourceInspectorMaterializer:
    """Build exact run-scoped source choices and create selected sidecars atomically."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._resolver = LessonDocumentReferenceResolver(conn)
        self._lessons = PostgresLessonDocumentRepository(conn)

    def build_candidates(
        self,
        *,
        scope: Mapping[str, object],
        allow_sources: bool = True,
    ) -> tuple[SourceInspectorCandidate, ...]:
        if not allow_sources or not self._feature_enabled():
            return ()
        normalized = _scope_identity(scope)
        query, recent_blocks, has_learner_input = self._retrieval_context(scope=normalized)
        candidates: list[SourceInspectorCandidate] = []
        seen: set[tuple[str, str, str]] = set()

        def admit(candidate: SourceInspectorCandidate) -> None:
            identity = (candidate.document_id, candidate.document_content_hash, candidate.block_id)
            if identity not in seen:
                seen.add(identity)
                candidates.append(candidate.model_copy(update={
                    "recently_displayed": identity in recent_blocks,
                }))

        references = self._conn.execute(
            """SELECT id::text AS reference_id FROM tutor_message_context_references
               WHERE run_id=%s AND user_id=%s AND reference_kind='lesson_selection'
               ORDER BY reference_index,id LIMIT 2""",
            (normalized["run_id"], normalized["user_id"]),
        ).fetchall()
        for reference in references:
            try:
                resolved = self._resolver.resolve(
                    user_id=normalized["user_id"], conversation_id=normalized["conversation_id"],
                    track_id=normalized["track_id"], knowledge_key=normalized["knowledge_key"],
                    source=LessonContextReferenceSourceV1(reference_id=str(reference["reference_id"])),
                )
                admit(_candidate_from_resolved(scope=normalized, resolved=resolved))
            except (LessonDocumentReferenceError, TypeError, ValueError):
                continue
            if len(candidates) >= _MAX_SOURCE_CANDIDATES:
                return tuple(candidates)
        try:
            document = self._lessons.load_document(document_id=normalized["document_id"])
        except (LessonNotFound, TypeError, ValueError):
            return tuple(candidates)
        ranked = _rank_source_blocks(document.blocks, query=query)
        if not ranked and not has_learner_input:
            # Opening/continuing a lesson without learner text may introduce its
            # first cited concept. This fallback never replaces an unrelated query.
            ranked = tuple(block for block in document.blocks if block.type == "concept" and block.citation_ids)
        for block in ranked:
            if len(candidates) >= _MAX_SOURCE_CANDIDATES:
                break
            try:
                resolved = self._resolver.resolve(
                    user_id=normalized["user_id"], conversation_id=normalized["conversation_id"],
                    track_id=normalized["track_id"], knowledge_key=normalized["knowledge_key"],
                    source=LessonBlockReferenceSourceV1(
                        document_id=normalized["document_id"],
                        document_content_hash=normalized["document_content_hash"],
                        assignment_version=_positive_int(normalized["assignment_version"], "assignment_version"),
                        block_id=block.block_id, citation_id=block.citation_ids[0],
                    ),
                )
                admit(_candidate_from_resolved(scope=normalized, resolved=resolved))
            except (LessonDocumentReferenceError, TypeError, ValueError):
                continue
        return tuple(candidates)

    def _retrieval_context(
        self, *, scope: Mapping[str, str],
    ) -> tuple[str, frozenset[tuple[str, str, str]], bool]:
        # This run's persisted input and frozen checkpoint, not mutable session state.
        # Learner text only ranks candidates; it never supplies source authority.
        row = self._conn.execute(
            """SELECT checkpoints.state_json,
                      (SELECT messages.content FROM tutor_run_input_events inputs
                       JOIN tutor_messages messages ON messages.id=inputs.message_id
                         AND messages.conversation_id=inputs.conversation_id
                       WHERE inputs.run_id=runs.id AND inputs.input_revision<=runs.input_revision
                       ORDER BY inputs.input_revision DESC LIMIT 1) AS input_text
               FROM tutor_run_teaching_scopes scopes
               JOIN tutor_runs runs ON runs.id=scopes.run_id AND runs.user_id=scopes.user_id
               JOIN tutor_teaching_session_checkpoints checkpoints ON checkpoints.id=scopes.checkpoint_id
                 AND checkpoints.user_id=scopes.user_id
               WHERE scopes.run_id=%s AND scopes.user_id=%s""",
            (scope["run_id"], scope["user_id"]),
        ).fetchone()
        if row is None:
            raise SourceInspectorCommitError("source retrieval run scope is missing")
        state = row.get("state_json")
        state = state if isinstance(state, Mapping) else {}
        focus = state.get("active_focus") or state.get("objective")
        focus = focus if isinstance(focus, Mapping) else {}
        query = str(row.get("input_text") or focus.get("summary") or "")[:2000]
        # Only the last three teaching turns committed before this run began.
        # The cutoff makes this metadata stable when Gate/commit rebuild candidates.
        rows = self._conn.execute(
            """WITH recent_turns AS (
                 SELECT prior.id FROM tutor_runs current_run
                 JOIN tutor_runs prior ON prior.user_id=current_run.user_id
                   AND prior.conversation_id=current_run.conversation_id
                 JOIN tutor_teaching_action_receipts receipts ON receipts.run_id=prior.id
                 JOIN tutor_run_teaching_scopes scopes ON scopes.run_id=prior.id
                 WHERE current_run.id=%s AND current_run.user_id=%s
                   AND prior.terminal_outcome='completed' AND prior.terminal_at<current_run.created_at
                   AND scopes.track_id=%s AND scopes.document_id=%s AND scopes.document_content_hash=%s
                 ORDER BY prior.terminal_at DESC,prior.id DESC LIMIT 3
               )
               SELECT artifacts.presentation_json FROM tutor_learning_artifacts artifacts
               JOIN recent_turns ON recent_turns.id=artifacts.turn_id
               WHERE artifacts.user_id=%s AND artifacts.conversation_id=%s
                 AND artifacts.learning_track_id=%s AND artifacts.artifact_kind='source_inspector'
                 AND artifacts.purpose='source_inspection'""",
            (scope["run_id"], scope["user_id"], scope["track_id"], scope["document_id"],
             scope["document_content_hash"], scope["user_id"], scope["conversation_id"], scope["track_id"]),
        ).fetchall()
        recent = frozenset(
            (str(p["document_id"]), str(p["document_content_hash"]), str(p["block_id"]))
            for item in rows
            if isinstance(p := item.get("presentation_json"), Mapping)
            and all(key in p for key in ("document_id", "document_content_hash", "block_id"))
        )
        return query, recent, bool(row.get("input_text"))

    def prepare_selected(
        self,
        *,
        context: Mapping[str, object],
        scope: Mapping[str, object],
        step: TeachingStepDecision,
        next_checkpoint_id: str,
        next_session_version: int,
    ) -> tuple[PreparedSourceInspector, ...]:
        namespaced_handles = tuple(
            handle
            for handle in step.source_handles
            if handle.startswith(SOURCE_INSPECTOR_HANDLE_PREFIX)
        )
        if not namespaced_handles:
            return ()
        if any(not is_source_inspector_handle(handle) for handle in namespaced_handles):
            raise SourceInspectorCommitError("selected Lesson source handle is invalid")
        selected_handles = namespaced_handles
        if not self._feature_enabled():
            raise SourceInspectorCommitError("source-inspection Artifact materialization is disabled")
        visible = parse_source_inspector_candidates(context)
        visible_by_handle = {candidate.handle: candidate for candidate in visible}
        if len(selected_handles) != len(set(selected_handles)) or not set(selected_handles).issubset(visible_by_handle):
            raise SourceInspectorCommitError("selected Lesson source was not visible in this run")
        current = self.build_candidates(scope=scope, allow_sources=bool(visible))
        current_by_handle = {candidate.handle: candidate for candidate in current}
        if any(
            handle not in current_by_handle
            or current_by_handle[handle] != visible_by_handle[handle]
            for handle in selected_handles
        ):
            raise SourceInspectorCommitError("selected Lesson source binding is stale")
        normalized = _scope_identity(scope)
        prepared: list[PreparedSourceInspector] = []
        for handle in selected_handles:
            candidate = current_by_handle[handle]
            request = TutorArtifactCreate(
                user_id=normalized["user_id"],
                conversation_id=normalized["conversation_id"],
                turn_id=normalized["run_id"],
                learning_track_id=normalized["track_id"],
                knowledge_key=normalized["knowledge_key"],
                teaching_session_id=normalized["teaching_session_id"],
                checkpoint_id=next_checkpoint_id,
                track_version=_positive_int(normalized["track_version"], "track_version"),
                progress_version=_positive_int(normalized["progress_version"], "progress_version"),
                assignment_version=_positive_int(normalized["assignment_version"], "assignment_version"),
                owner_kind=TutorArtifactOwnerKind.TEACHING_PRACTICE,
                owner_id=next_checkpoint_id,
                owner_version=next_session_version,
                owner_context_version=next_session_version,
                artifact_kind=TutorArtifactKind.SOURCE_INSPECTOR,
                purpose=TutorArtifactPurpose.SOURCE_INSPECTION,
                state=TutorArtifactState.READY,
                blocking=False,
                title=f"来源 · {candidate.title}"[:240],
                instruction_markdown="查看 Tutor 本轮讲解所引用的冻结课程来源。",
                presentation=TutorArtifactSourceInspectorPresentationV1(
                    document_id=candidate.document_id,
                    document_content_hash=candidate.document_content_hash,
                    block_id=candidate.block_id,
                    excerpt=candidate.excerpt,
                    citation_ids=candidate.citation_ids,
                ),
                allowed_actions=(),
                source_references=(
                    TutorArtifactSourceReferenceV1(
                        kind="lesson_document",
                        reference_id=candidate.document_id,
                        reference_version=candidate.assignment_version,
                        content_hash=candidate.document_content_hash,
                        label="冻结课程文档",
                    ),
                ),
            )
            prepared.append(
                PreparedSourceInspector(
                    request=request,
                    creation_key=(
                        f"source-inspection:{normalized['run_id']}:"
                        f"{handle.removeprefix(SOURCE_INSPECTOR_HANDLE_PREFIX)}"
                    ),
                    source_handle=handle,
                )
            )
        return tuple(prepared)

    def create(
        self,
        prepared: PreparedSourceInspector,
        *,
        occurred_at: datetime,
    ) -> LearningArtifactWriteResult:
        if not self._feature_enabled():
            raise SourceInspectorCommitError("source-inspection Artifact materialization is disabled")
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
            raise SourceInspectorCommitError(
                "source-inspection Artifact could not be committed atomically"
            ) from exc
        artifact = result.artifact
        if result.idempotent_replayed:
            raise SourceInspectorCommitError(
                "fresh source-inspection commit unexpectedly replayed prior authority"
            )
        if (
            artifact.turn_id != prepared.request.turn_id
            or artifact.checkpoint_id != prepared.request.checkpoint_id
            or artifact.owner_kind is not TutorArtifactOwnerKind.TEACHING_PRACTICE
            or artifact.owner_id != prepared.request.owner_id
            or artifact.owner_version != prepared.request.owner_version
            or artifact.purpose is not TutorArtifactPurpose.SOURCE_INSPECTION
            or artifact.state is not TutorArtifactState.READY
            or artifact.blocking
            or artifact.allowed_actions
            or len(artifact.source_references) != 1
            or artifact.source_references[0].kind != "lesson_document"
            or result.artifact_event_sequence != 1
        ):
            raise SourceInspectorCommitError(
                "source-inspection Artifact projection differs from prepared authority"
            )
        return result

    def _feature_enabled(self) -> bool:
        return (
            self._settings.tutor_learning_artifacts_enabled
            and self._settings.tutor_artifact_teaching_mode_enabled
        )


def parse_source_inspector_candidates(
    context: Mapping[str, object],
) -> tuple[SourceInspectorCandidate, ...]:
    raw = context.get("source_inspection_candidates", ())
    if raw in (None, (), []):
        return ()
    if not isinstance(raw, (list, tuple)) or len(raw) > _MAX_SOURCE_CANDIDATES:
        raise SourceInspectorCommitError("source-inspection candidate context is invalid")
    try:
        candidates = tuple(SourceInspectorCandidate.model_validate(item) for item in raw)
    except (TypeError, ValueError) as exc:
        raise SourceInspectorCommitError("source-inspection candidate context is invalid") from exc
    handles = tuple(candidate.handle for candidate in candidates)
    if len(handles) != len(set(handles)):
        raise SourceInspectorCommitError("source-inspection candidate handles are duplicated")
    return candidates


def source_inspector_candidate_handles(context: Mapping[str, object]) -> frozenset[str]:
    return frozenset(candidate.handle for candidate in parse_source_inspector_candidates(context))


def validate_source_inspector_evidence(value: object) -> tuple[dict[str, object], ...]:
    if value in (None, (), []):
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_SOURCE_CANDIDATES:
        raise SourceInspectorCommitError("source-inspection provider evidence is invalid")
    validated: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"kind", "handle", "title", "excerpt", "recently_displayed"}:
            raise SourceInspectorCommitError("source-inspection provider evidence is invalid")
        handle = str(item.get("handle") or "")
        title = str(item.get("title") or "").strip()
        excerpt = str(item.get("excerpt") or "").strip()
        if (
            item.get("kind") != _SOURCE_CANDIDATE_SCHEMA_VERSION
            or not is_source_inspector_handle(handle)
            or not title
            or len(title) > 160
            or not excerpt
            or len(excerpt) > _MAX_PROVIDER_EXCERPT
            or type(item.get("recently_displayed")) is not bool
        ):
            raise SourceInspectorCommitError("source-inspection provider evidence is invalid")
        validated.append({
            "kind": _SOURCE_CANDIDATE_SCHEMA_VERSION,
            "handle": handle,
            "title": title,
            "excerpt": excerpt,
            "recently_displayed": item["recently_displayed"],
        })
    if len({str(item["handle"]) for item in validated}) != len(validated):
        raise SourceInspectorCommitError("source-inspection provider evidence is duplicated")
    return tuple(validated)


def is_source_inspector_handle(value: object) -> bool:
    text = str(value or "")
    return (
        len(text) == 78
        and text.startswith(SOURCE_INSPECTOR_HANDLE_PREFIX)
        and all(character in "0123456789abcdef" for character in text[-64:])
    )


def _candidate_from_resolved(
    *,
    scope: Mapping[str, str],
    resolved: Mapping[str, object],
) -> SourceInspectorCandidate:
    assignment = _mapping(resolved.get("assignment"), "assignment")
    document = _mapping(resolved.get("document"), "document")
    target = _mapping(resolved.get("target"), "target")
    citations = target.get("citation_ids")
    if not isinstance(citations, (list, tuple)):
        raise ValueError("resolved Lesson citations are invalid")
    blocks = document.get("blocks")
    block_title = next((str(block.get("title") or "") for block in blocks
                        if isinstance(block, Mapping) and block.get("block_id") == target.get("block_id")), "") if isinstance(blocks, (list, tuple)) else ""
    values: dict[str, object] = {
        "source_kind": str(resolved.get("source_kind") or ""),
        "source_id": str(resolved.get("source_id") or ""),
        "user_id": scope["user_id"],
        "conversation_id": scope["conversation_id"],
        "run_id": scope["run_id"],
        "track_id": scope["track_id"],
        "knowledge_key": scope["knowledge_key"],
        "assignment_id": str(assignment.get("assignment_id") or ""),
        "assignment_version": _positive_int(
            assignment.get("assignment_version"),
            "source assignment_version",
        ),
        "document_id": str(assignment.get("document_id") or ""),
        "document_content_hash": str(document.get("content_hash") or ""),
        "block_id": str(target.get("block_id") or ""),
        "citation_ids": tuple(str(item) for item in citations),
        "selected_citation_id": (
            str(target["selected_citation_id"])
            if target.get("selected_citation_id") is not None
            else None
        ),
        "title": (block_title or str(document.get("title") or "课程来源"))[:160],
        "excerpt": str(target.get("safe_excerpt") or ""),
    }
    identity = {
        "schema_version": _SOURCE_BINDING_SCHEMA_VERSION,
        "source_kind": values["source_kind"],
        "source_id": values["source_id"],
        "user_id": values["user_id"],
        "conversation_id": values["conversation_id"],
        "run_id": values["run_id"],
        "track_id": values["track_id"],
        "knowledge_key": values["knowledge_key"],
        "assignment_id": values["assignment_id"],
        "assignment_version": values["assignment_version"],
        "document_id": values["document_id"],
        "document_content_hash": values["document_content_hash"],
        "block_id": values["block_id"],
        "citation_ids": list(cast(tuple[str, ...], values["citation_ids"])),
        "selected_citation_id": values["selected_citation_id"],
        "excerpt_hash": canonical_hash({"excerpt": values["excerpt"]}),
    }
    return SourceInspectorCandidate.model_validate(
        {"handle": _candidate_handle(identity), **values}
    )


def _scope_identity(scope: Mapping[str, object]) -> dict[str, str]:
    values = {
        "run_id": str(scope.get("run_id") or ""),
        "user_id": str(scope.get("user_id") or ""),
        "conversation_id": str(scope.get("conversation_id") or ""),
        "teaching_session_id": str(scope.get("teaching_session_id") or ""),
        "track_id": str(scope.get("track_id") or ""),
        "knowledge_key": stable(str(scope.get("knowledge_key") or ""), "source knowledge_key"),
        "assignment_id": str(scope.get("lesson_assignment_id") or ""),
        "assignment_version": str(_positive_int(scope.get("assignment_version"), "assignment_version")),
        "document_id": str(scope.get("document_id") or ""),
        "document_content_hash": str(scope.get("document_content_hash") or ""),
        "track_version": str(_positive_int(scope.get("track_version"), "track_version")),
        "progress_version": str(_positive_int(scope.get("progress_version"), "progress_version")),
    }
    if any(not values[key] for key in (
        "run_id", "user_id", "conversation_id", "teaching_session_id",
        "track_id", "assignment_id", "document_id", "document_content_hash",
    )):
        raise SourceInspectorCommitError("source-inspection run scope is incomplete")
    if len(values["document_content_hash"]) != 64:
        raise SourceInspectorCommitError("source-inspection document hash is invalid")
    return values


def _source_terms(text: str) -> frozenset[str]:
    """Small lexical shortlist, not semantic policy or a trigger to create cards."""
    normalized = unicodedata.normalize("NFKC", text[:16000]).casefold()
    words = set(re.findall(r"[a-z_][a-z_0-9]{1,}", normalized))
    for phrase in re.findall(r"[\u3400-\u9fff]+", normalized):
        words.update(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return frozenset(words)


def _rank_source_blocks(blocks: tuple[LessonBlock, ...], *, query: str) -> tuple[LessonBlock, ...]:
    # Use the same public text projection as the exact-source resolver. Never
    # index Gate answers/private contracts or arbitrary metadata as evidence.
    eligible = tuple(block for block in blocks if block.citation_ids
                     and block.type in {"concept", "authority_note", "code_example", "comparison"})
    query_terms = _source_terms(query)
    if not query_terms:
        return ()
    terms = {block.block_id: _source_terms(lesson_block_public_text(block)) for block in eligible}
    frequency = Counter(term for values in terms.values() for term in values)
    scored: list[tuple[float, str, LessonBlock]] = []
    for block in eligible:
        overlap = query_terms & terms[block.block_id]
        if not overlap:
            continue
        title_terms = _source_terms(str(lesson_block_payload(block).get("title") or ""))
        score = sum((3.0 if term in title_terms else 1.0) / frequency[term] for term in overlap)
        score /= max(1, len(terms[block.block_id])) ** 0.25
        scored.append((score, block.block_id, block))
    return tuple(item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1])))


def _candidate_handle(identity: Mapping[str, object]) -> str:
    return f"{SOURCE_INSPECTOR_HANDLE_PREFIX}{canonical_hash(identity)}"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    parsed = int(cast(int | float | str, value))
    if parsed < 1:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


__all__ = (
    "PostgresSourceInspectorMaterializer",
    "PreparedSourceInspector",
    "SOURCE_INSPECTOR_HANDLE_PREFIX",
    "SourceInspectorCandidate",
    "SourceInspectorCommitError",
    "is_source_inspector_handle",
    "parse_source_inspector_candidates",
    "source_inspector_candidate_handles",
    "validate_source_inspector_evidence",
)
