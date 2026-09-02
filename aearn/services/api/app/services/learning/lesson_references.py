"""Resolve exact, learner-safe LessonDocument references for the Desktop drawer."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from psycopg import Connection

from app.models.lesson_documents import (
    LessonArtifactReferenceSourceV1,
    LessonBlockReferenceSourceV1,
    LessonContextReferenceSourceV1,
    LessonDocumentReferenceSourceV1,
)
from app.services.learning.artifacts.contracts import (
    TutorArtifactSourceInspectorPresentationV1,
)
from app.services.learning.artifacts.repository import (
    LearningArtifactNotFound,
    PostgresLearningArtifactRepository,
)
from app.services.learning.context_references import (
    ContextReferenceError,
    PostgresTutorContextReferenceRepository,
)
from app.services.learning.contracts import stable_key
from app.services.learning.lesson_contracts import lesson_block_payload
from app.services.learning.lesson_projection import (
    lesson_block_public_text,
    normalize_lesson_text,
    project_lesson_document,
    project_lesson_source,
)
from app.services.learning.lesson_repository import (
    LessonNotFound,
    PostgresLessonDocumentRepository,
)

_REFERENCE_SCHEMA_VERSION = "lesson_document_reference_v1"
_MAX_EXCERPT = 800
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LessonDocumentReferenceError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable


@dataclass(frozen=True, slots=True)
class _ReferenceIdentity:
    source_kind: str
    source_id: str
    document_id: str
    document_content_hash: str
    assignment_version: int
    block_id: str
    safe_excerpt: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    citation_ids: tuple[str, ...] = ()
    selected_citation_id: str | None = None


class LessonDocumentReferenceResolver:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._lessons = PostgresLessonDocumentRepository(conn)
        self._context_references = PostgresTutorContextReferenceRepository(conn)
        self._artifacts = PostgresLearningArtifactRepository(conn)

    def resolve(
        self,
        *,
        user_id: str,
        conversation_id: str,
        track_id: str,
        knowledge_key: str,
        source: LessonDocumentReferenceSourceV1,
    ) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        track = _uuid(track_id, "track_id")
        knowledge = stable_key(knowledge_key, label="knowledge_key")
        self._require_conversation_scope(
            user_id=user,
            conversation_id=conversation,
            track_id=track,
        )
        if isinstance(source, LessonBlockReferenceSourceV1):
            document_id = _uuid(source.document_id, "document_id")
            block_id = stable_key(source.block_id, label="block_id")
            identity = _ReferenceIdentity(
                source_kind=source.kind,
                source_id=f"{document_id}:{block_id}",
                document_id=document_id,
                document_content_hash=source.document_content_hash,
                assignment_version=source.assignment_version,
                block_id=block_id,
                selected_citation_id=source.citation_id,
            )
        elif isinstance(source, LessonContextReferenceSourceV1):
            identity = self._context_identity(
                user_id=user,
                conversation_id=conversation,
                track_id=track,
                knowledge_key=knowledge,
                reference_id=source.reference_id,
            )
        else:
            assert isinstance(source, LessonArtifactReferenceSourceV1)
            identity = self._artifact_identity(
                user_id=user,
                conversation_id=conversation,
                track_id=track,
                knowledge_key=knowledge,
                artifact_id=source.artifact_id,
                artifact_version=source.artifact_version,
            )
        return self._resolve_identity(
            user_id=user,
            conversation_id=conversation,
            track_id=track,
            knowledge_key=knowledge,
            identity=identity,
        )

    def _require_conversation_scope(
        self,
        *,
        user_id: str,
        conversation_id: str,
        track_id: str,
    ) -> None:
        row = self._conn.execute(
            """
            SELECT 1
            FROM tutor_conversation_learning_scopes
            WHERE conversation_id=%s AND user_id=%s
              AND scope_kind='learning_track' AND learning_track_id=%s
            """,
            (conversation_id, user_id, track_id),
        ).fetchone()
        if row is None:
            raise _not_found()

    def _context_identity(
        self,
        *,
        user_id: str,
        conversation_id: str,
        track_id: str,
        knowledge_key: str,
        reference_id: str,
    ) -> _ReferenceIdentity:
        try:
            reference = self._context_references.read_lesson_selection_reference(
                user_id=user_id,
                conversation_id=conversation_id,
                track_id=track_id,
                knowledge_key=knowledge_key,
                reference_id=_uuid(reference_id, "reference_id"),
            )
        except ContextReferenceError as exc:
            raise LessonDocumentReferenceError(
                "DOCUMENT_REFERENCE_NOT_FOUND" if exc.status_code == 404 else "DOCUMENT_REFERENCE_STALE",
                "课程引用不存在或已失效。",
                status_code=404 if exc.status_code == 404 else 409,
            ) from exc
        return _ReferenceIdentity(
            source_kind="context_reference",
            source_id=str(reference["reference_id"]),
            document_id=str(reference["document_id"]),
            document_content_hash=str(reference["document_content_hash"]),
            assignment_version=_positive_int(reference.get("assignment_version")),
            block_id=str(reference["block_id"]),
            safe_excerpt=str(reference["safe_excerpt"]),
            start_offset=_non_negative_int(reference.get("start_offset")),
            end_offset=_positive_int(reference.get("end_offset")),
        )

    def _artifact_identity(
        self,
        *,
        user_id: str,
        conversation_id: str,
        track_id: str,
        knowledge_key: str,
        artifact_id: str,
        artifact_version: int,
    ) -> _ReferenceIdentity:
        try:
            artifact = self._artifacts.read_artifact(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=_uuid(artifact_id, "artifact_id"),
            )
        except LearningArtifactNotFound as exc:
            raise _not_found() from exc
        presentation = artifact.presentation
        if (
            artifact.learning_track_id != track_id
            or artifact.knowledge_key != knowledge_key
            or artifact.version != artifact_version
            or not isinstance(presentation, TutorArtifactSourceInspectorPresentationV1)
        ):
            raise _stale()
        references = tuple(
            item
            for item in artifact.source_references
            if item.kind == "lesson_document"
            and item.reference_id == presentation.document_id
            and item.content_hash == presentation.document_content_hash
            and item.reference_version is not None
        )
        if len(references) != 1:
            raise _stale()
        reference = references[0]
        return _ReferenceIdentity(
            source_kind="artifact",
            source_id=artifact.id,
            document_id=presentation.document_id,
            document_content_hash=presentation.document_content_hash,
            assignment_version=cast(int, reference.reference_version),
            block_id=presentation.block_id,
            safe_excerpt=presentation.excerpt,
            citation_ids=presentation.citation_ids,
        )

    def _resolve_identity(
        self,
        *,
        user_id: str,
        conversation_id: str,
        track_id: str,
        knowledge_key: str,
        identity: _ReferenceIdentity,
    ) -> dict[str, object]:
        if not _SHA256.fullmatch(identity.document_content_hash):
            raise _stale()
        assignment = self._conn.execute(
            """
            SELECT assignments.id::text AS assignment_id,
                   assignments.assignment_version,assignments.status,
                   assignments.document_id::text,assignments.content_hash
            FROM tutor_lesson_assignments AS assignments
            JOIN tutor_lesson_documents AS documents
              ON documents.id=assignments.document_id
             AND documents.user_id=assignments.user_id
             AND documents.track_id=assignments.track_id
             AND documents.knowledge_key=assignments.knowledge_key
            WHERE assignments.user_id=%s AND assignments.track_id=%s
              AND assignments.knowledge_key=%s AND assignments.document_id=%s
              AND assignments.assignment_version=%s
            """,
            (
                user_id,
                track_id,
                knowledge_key,
                identity.document_id,
                identity.assignment_version,
            ),
        ).fetchone()
        if assignment is None:
            raise _not_found()
        if str(assignment["content_hash"]) != identity.document_content_hash:
            raise _stale()
        try:
            document = self._lessons.load_document(document_id=identity.document_id)
            sources = self._lessons.load_source_snapshots(document_id=identity.document_id)
        except LessonNotFound as exc:
            raise _not_found() from exc
        if document.content_hash != identity.document_content_hash or document.knowledge_key != knowledge_key:
            raise _stale()
        block = next((item for item in document.blocks if item.block_id == identity.block_id), None)
        if block is None:
            raise _stale()
        block_payload = lesson_block_payload(block)
        canonical = normalize_lesson_text(lesson_block_public_text(block))
        excerpt = self._validated_excerpt(identity=identity, canonical=canonical)
        citation_ids = identity.citation_ids or block.citation_ids
        if any(item not in block.citation_ids for item in citation_ids):
            raise _stale()
        if identity.selected_citation_id is not None and identity.selected_citation_id not in block.citation_ids:
            raise _stale()
        current = self._conn.execute(
            """
            SELECT id::text AS assignment_id,document_id::text,assignment_version,
                   content_hash,status
            FROM tutor_lesson_assignments
            WHERE user_id=%s AND track_id=%s AND knowledge_key=%s AND status='active'
            """,
            (user_id, track_id, knowledge_key),
        ).fetchone()
        current_payload = _assignment_payload(current) if current is not None else None
        exact_current = bool(
            current is not None
            and str(current["document_id"]) == identity.document_id
            and str(current["content_hash"]) == identity.document_content_hash
            and _positive_int(current.get("assignment_version")) == identity.assignment_version
        )
        return {
            "schema_version": _REFERENCE_SCHEMA_VERSION,
            "source_kind": identity.source_kind,
            "source_id": identity.source_id,
            "conversation_id": conversation_id,
            "learning_track_id": track_id,
            "knowledge_key": knowledge_key,
            "reference_status": "current" if exact_current else "historical",
            "assignment": _assignment_payload(assignment),
            "current_assignment": current_payload,
            "document": project_lesson_document(document),
            "sources": [project_lesson_source(item) for item in sources],
            "target": {
                "block_id": identity.block_id,
                "block_content_hash": _sha256_json(block_payload),
                "safe_excerpt": excerpt,
                "citation_ids": list(citation_ids),
                "selected_citation_id": identity.selected_citation_id,
            },
        }

    @staticmethod
    def _validated_excerpt(*, identity: _ReferenceIdentity, canonical: str) -> str:
        if identity.start_offset is not None or identity.end_offset is not None:
            if identity.start_offset is None or identity.end_offset is None:
                raise _stale()
            if (
                identity.end_offset > len(canonical)
                or canonical[identity.start_offset : identity.end_offset]
                != normalize_lesson_text(identity.safe_excerpt)
            ):
                raise _stale()
            return normalize_lesson_text(identity.safe_excerpt)
        if identity.safe_excerpt is not None:
            excerpt = normalize_lesson_text(identity.safe_excerpt)
            if not excerpt or excerpt not in canonical:
                raise _stale()
            return excerpt[:_MAX_EXCERPT]
        return canonical[:_MAX_EXCERPT]


def _assignment_payload(row: dict[str, object] | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "assignment_id": str(row["assignment_id"]),
        "document_id": str(row["document_id"]),
        "assignment_version": _positive_int(row.get("assignment_version")),
        "status": str(row["status"]),
        "content_hash": str(row["content_hash"]),
    }


def _uuid(value: object, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LessonDocumentReferenceError(
            "DOCUMENT_REFERENCE_INVALID",
            f"{label} 格式不合法。",
            status_code=422,
            recoverable=False,
        ) from exc


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        raise _stale()
    try:
        parsed = int(cast(int | float | str, value))
    except (TypeError, ValueError) as exc:
        raise _stale() from exc
    if parsed < 1:
        raise _stale()
    return parsed


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        raise _stale()
    try:
        parsed = int(cast(int | float | str, value))
    except (TypeError, ValueError) as exc:
        raise _stale() from exc
    if parsed < 0:
        raise _stale()
    return parsed


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _not_found() -> LessonDocumentReferenceError:
    return LessonDocumentReferenceError(
        "DOCUMENT_REFERENCE_NOT_FOUND",
        "来源文档不存在或不属于当前学习范围。",
        status_code=404,
        recoverable=False,
    )


def _stale() -> LessonDocumentReferenceError:
    return LessonDocumentReferenceError(
        "DOCUMENT_REFERENCE_STALE",
        "来源文档版本或定位信息已经更新。",
        status_code=409,
    )


__all__ = ("LessonDocumentReferenceError", "LessonDocumentReferenceResolver")
