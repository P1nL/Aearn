"""PostgreSQL repository for the shared immutable Learning Item Bank."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal
from uuid import UUID

from psycopg import Connection

from app.services.learning.item_bank.contracts import (
    LEARNING_ITEM_COMPILER_VERSION,
    LearningItemDifficulty,
    LearningItemKind,
    LearningItemPurpose,
    LearningItemSourceV1,
    LearningItemValidationReceiptV1,
    canonical_hash,
    canonical_json,
    learning_item_handle,
    learning_item_uuid,
    require_sha256,
    stable_key,
)
from app.services.learning.item_bank.validation import validate_learning_item

IMPORTER_VERSION = "learning_item_repository_v1"
PublicationState = Literal[
    "machine_verified",
    "agent_reviewed",
    "pilot",
    "published",
    "quarantined",
    "retired",
]
PublicationAuthorityKind = Literal[
    "validation",
    "agent_review",
    "pilot",
    "human_approval",
    "operator",
]
_HANDLE = re.compile(r"^li:[0-9a-f]{64}$")
_ALLOWED_STATES = frozenset(
    {"machine_verified", "agent_reviewed", "pilot", "published", "quarantined", "retired"}
)
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "machine_verified": frozenset({"agent_reviewed", "quarantined", "retired"}),
    "agent_reviewed": frozenset({"pilot", "quarantined", "retired"}),
    "pilot": frozenset({"published", "quarantined", "retired"}),
    "published": frozenset({"quarantined", "retired"}),
    "quarantined": frozenset({"retired"}),
    "retired": frozenset(),
}


class LearningItemBankError(ValueError):
    """Base safe error for item-bank persistence."""


class LearningItemImportConflict(LearningItemBankError):
    """An immutable identity was replayed with different content."""


class LearningItemPublicationConflict(LearningItemBankError):
    """A publication transition was stale, conflicting, or invalid."""


class LearningItemNotFound(LearningItemBankError):
    """The requested immutable item version does not exist."""


@dataclass(frozen=True, slots=True)
class LearningItemImportResult:
    item_id: str
    version_id: str
    handle: str
    content_hash: str
    validation_receipt_id: str
    import_receipt_id: str
    publication_event_id: str
    publication_state: PublicationState
    publication_state_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class LearningItemPublicationResult:
    version_id: str
    event_id: str
    handle: str
    state: PublicationState
    state_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class PublishedLearningItemCandidate:
    handle: str
    item_key: str
    version: str
    kind: str
    purpose: str
    knowledge_key: str
    language_id: str
    difficulty: str
    title: str
    summary: str
    required_capabilities: tuple[str, ...]
    allowed_interactions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "handle": self.handle,
            "item_key": self.item_key,
            "version": self.version,
            "kind": self.kind,
            "purpose": self.purpose,
            "knowledge_key": self.knowledge_key,
            "language_id": self.language_id,
            "difficulty": self.difficulty,
            "title": self.title,
            "summary": self.summary,
            "required_capabilities": list(self.required_capabilities),
            "allowed_interactions": list(self.allowed_interactions),
        }


class PostgresLearningItemBankRepository:
    """Caller-transaction-owned persistence for compiled, validated items."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def import_validated_source(
        self,
        *,
        source: LearningItemSourceV1,
        validation: LearningItemValidationReceiptV1,
        import_key: str,
        source_path: str,
        source_file_hash: str,
        imported_at: datetime,
        creator_identity: str = "curated.manual",
    ) -> LearningItemImportResult:
        key = stable_key(import_key, label="learning item import key")
        relative_path = _source_path(source_path)
        file_hash = require_sha256(source_file_hash, label="learning item source file hash")
        content_hash = source.content_hash
        handle = learning_item_handle(source.public.item_key, source.public.version, content_hash)
        creator = stable_key(creator_identity, label="Learning Item creator identity")
        expected_validation = validate_learning_item(source)
        if not validation.passed:
            raise LearningItemBankError("failed validation receipt cannot be imported")
        if validation != expected_validation:
            raise LearningItemImportConflict(
                "validation receipt does not match current deterministic validation"
            )
        if validation.item_handle != handle or validation.content_hash != content_hash:
            raise LearningItemImportConflict("validation receipt is not bound to item content")
        request_hash = canonical_hash(
            {
                "importer_version": IMPORTER_VERSION,
                "import_key": key,
                "source_path": relative_path,
                "source_file_hash": file_hash,
                "source_hash": source.source_hash,
                "content_hash": content_hash,
                "validation_receipt_hash": validation.receipt_hash,
            }
        )
        self._conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('learning-item-import'), hashtext(%s))",
            (key,),
        )
        existing = self._conn.execute(
            """
            SELECT receipts.*, versions.item_id, versions.creator_identity,
                   publications.id AS publication_event_id,
                   publications.state AS publication_state,
                   publications.state_version AS publication_state_version
            FROM tutor_learning_item_import_receipts AS receipts
            JOIN tutor_learning_item_versions AS versions ON versions.id=receipts.version_id
            JOIN LATERAL (
              SELECT id,state,state_version
              FROM tutor_learning_item_publication_events
              WHERE version_id=receipts.version_id
              ORDER BY state_version DESC LIMIT 1
            ) AS publications ON true
            WHERE receipts.import_key=%s
            FOR UPDATE OF receipts
            """,
            (key,),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise LearningItemImportConflict("learning item import key conflicts with stored content")
            if str(existing["creator_identity"]) != creator:
                raise LearningItemImportConflict("learning item import creator conflicts with stored content")
            return _import_result(existing, replayed=True)

        item_id, version_id = self._ensure_immutable_content(source, creator_identity=creator)
        validation_id = self._ensure_validation(validation, version_id=version_id)
        publication_id = self._ensure_initial_publication(
            version_id=version_id,
            handle=handle,
            content_hash=content_hash,
            validation_hash=validation.receipt_hash,
            policy_version=validation.policy_version,
            validation_id=validation_id,
            import_key=key,
            occurred_at=imported_at,
        )
        receipt_id = str(learning_item_uuid("import", key))
        inserted = self._conn.execute(
            """
            INSERT INTO tutor_learning_item_import_receipts (
              id,version_id,validation_receipt_id,initial_publication_event_id,
              import_key,source_path,source_file_hash,source_hash,content_hash,item_handle,
              request_hash,importer_version,imported_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (import_key) DO NOTHING
            RETURNING id
            """,
            (
                receipt_id,
                version_id,
                validation_id,
                publication_id,
                key,
                relative_path,
                file_hash,
                source.source_hash,
                content_hash,
                handle,
                request_hash,
                IMPORTER_VERSION,
                imported_at,
            ),
        ).fetchone()
        if inserted is None:
            raise LearningItemImportConflict("learning item import raced with conflicting content")
        return LearningItemImportResult(
            item_id=item_id,
            version_id=version_id,
            handle=handle,
            content_hash=content_hash,
            validation_receipt_id=validation_id,
            import_receipt_id=receipt_id,
            publication_event_id=publication_id,
            publication_state="machine_verified",
            publication_state_version=1,
            replayed=False,
        )

    def append_publication_state(
        self,
        *,
        handle: str,
        expected_state_version: int,
        next_state: PublicationState,
        transition_key: str,
        authority_kind: PublicationAuthorityKind,
        authority_hash: str,
        policy_version: str,
        occurred_at: datetime,
        reason_code: str | None = None,
        authority_reference_id: str | None = None,
    ) -> LearningItemPublicationResult:
        item_handle = _handle(handle)
        if next_state not in _ALLOWED_STATES or next_state == "machine_verified":
            raise LearningItemPublicationConflict("publication state is invalid")
        key = stable_key(transition_key, label="publication transition key")
        policy = stable_key(policy_version, label="publication policy version")
        evidence_hash = require_sha256(authority_hash, label="publication authority hash")
        reason = stable_key(reason_code, label="publication reason code") if reason_code is not None else None
        reference_id = _uuid_or_none(
            authority_reference_id,
            label="publication authority reference",
        )
        if (next_state in {"quarantined", "retired"}) != (reason is not None):
            raise LearningItemPublicationConflict("quarantine and retirement require exactly one safe reason")
        request_hash = canonical_hash(
            {
                "handle": item_handle,
                "expected_state_version": expected_state_version,
                "next_state": next_state,
                "transition_key": key,
                "authority_kind": authority_kind,
                "authority_hash": evidence_hash,
                "policy_version": policy,
                "reason_code": reason,
                "authority_reference_id": reference_id,
            }
        )
        version = self._conn.execute(
            "SELECT id,content_hash FROM tutor_learning_item_versions WHERE handle=%s FOR UPDATE",
            (item_handle,),
        ).fetchone()
        if version is None:
            raise LearningItemNotFound("learning item version was not found")
        version_id = str(version["id"])
        replay = self._conn.execute(
            """SELECT id,state,state_version,request_hash FROM tutor_learning_item_publication_events
               WHERE version_id=%s AND transition_key=%s""",
            (version_id, key),
        ).fetchone()
        if replay is not None:
            if str(replay["request_hash"]) != request_hash:
                raise LearningItemPublicationConflict("publication transition key conflicts with stored request")
            return LearningItemPublicationResult(
                version_id=version_id,
                event_id=str(replay["id"]),
                handle=item_handle,
                state=_publication_state(replay["state"]),
                state_version=_int_value(replay["state_version"]),
                replayed=True,
            )
        current = self._conn.execute(
            """SELECT id,state,state_version FROM tutor_learning_item_publication_events
               WHERE version_id=%s ORDER BY state_version DESC LIMIT 1 FOR UPDATE""",
            (version_id,),
        ).fetchone()
        if current is None or _int_value(current["state_version"]) != expected_state_version:
            raise LearningItemPublicationConflict("publication state version is stale")
        current_state = str(current["state"])
        if next_state not in _ALLOWED_TRANSITIONS[current_state]:
            raise LearningItemPublicationConflict("publication state transition is invalid")
        state_version = expected_state_version + 1
        event_id = str(learning_item_uuid("import", f"publication:{version_id}:{key}"))
        self._conn.execute(
            """
            INSERT INTO tutor_learning_item_publication_events (
              id,version_id,item_handle,content_hash,predecessor_event_id,state_version,state,
              transition_key,request_hash,authority_kind,authority_hash,authority_reference_id,
              policy_version,reason_code,occurred_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                event_id,
                version_id,
                item_handle,
                str(version["content_hash"]),
                current["id"],
                state_version,
                next_state,
                key,
                request_hash,
                authority_kind,
                evidence_hash,
                reference_id,
                policy,
                reason,
                occurred_at,
            ),
        )
        return LearningItemPublicationResult(
            version_id=version_id,
            event_id=event_id,
            handle=item_handle,
            state=next_state,
            state_version=state_version,
            replayed=False,
        )

    def published_candidates(
        self,
        *,
        knowledge_key: str,
        purpose: LearningItemPurpose | str | None = None,
        language_id: str | None = None,
        kinds: Sequence[LearningItemKind | str] = (),
        difficulties: Sequence[LearningItemDifficulty | str] = (),
        available_capabilities: Sequence[str] | None = None,
        exact_capabilities: bool = False,
        unused_handles: Sequence[str] = (),
        required_handles: Sequence[str] = (),
        excluded_purposes: Sequence[LearningItemPurpose | str] = (),
        limit: int = 8,
    ) -> tuple[PublishedLearningItemCandidate, ...]:
        key = stable_key(knowledge_key, label="candidate knowledge key")
        if not 1 <= limit <= 8:
            raise ValueError("candidate limit must be between 1 and 8")
        normalized_purpose = LearningItemPurpose(purpose).value if purpose is not None else None
        normalized_language = (
            stable_key(language_id, label="candidate language")
            if language_id is not None
            else None
        )
        kind_values = tuple(LearningItemKind(item).value for item in kinds)
        if len(kind_values) != len(set(kind_values)):
            raise ValueError("candidate kinds must be unique")
        difficulty_values = tuple(LearningItemDifficulty(item).value for item in difficulties)
        if available_capabilities is None:
            return ()
        capabilities = tuple(
            stable_key(item, label="candidate capability")
            for item in available_capabilities
        )
        if len(capabilities) != len(set(capabilities)) or len(capabilities) > 64:
            raise ValueError("candidate capabilities must be unique and bounded")
        excluded = tuple(_handle(item) for item in unused_handles)
        if len(excluded) != len(set(excluded)) or len(excluded) > 128:
            raise ValueError("unused candidate handles must be unique and bounded")
        required = tuple(_handle(item) for item in required_handles)
        if len(required) != len(set(required)) or len(required) > 8:
            raise ValueError("required candidate handles must be unique and bounded")
        excluded_purpose_values = tuple(
            LearningItemPurpose(item).value for item in excluded_purposes
        )
        if len(excluded_purpose_values) != len(set(excluded_purpose_values)):
            raise ValueError("excluded candidate purposes must be unique")
        rows = self._conn.execute(
            """
            SELECT versions.handle,versions.item_key,versions.version,versions.item_kind,versions.purpose,
                   versions.knowledge_key,versions.language_id,versions.difficulty,
                   versions.required_capabilities_json,public.title,public.candidate_summary,
                   public.allowed_interactions_json
            FROM tutor_learning_item_versions AS versions
            JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
            JOIN LATERAL (
              SELECT state FROM tutor_learning_item_publication_events
              WHERE version_id=versions.id ORDER BY state_version DESC LIMIT 1
            ) AS publication ON publication.state='published'
            WHERE versions.knowledge_key=%s
              AND NOT EXISTS (
                SELECT 1 FROM tutor_learning_item_validation_receipts native_validation
                WHERE native_validation.version_id=versions.id
                  AND native_validation.schema_version='candidate_validation_v2'
              )
              AND (%s::text IS NULL OR versions.purpose=%s)
              AND (%s::text IS NULL OR versions.language_id=%s)
              AND (cardinality(%s::text[]) = 0 OR versions.item_kind=ANY(%s::text[]))
              AND (cardinality(%s::text[]) = 0 OR versions.difficulty=ANY(%s::text[]))
              AND versions.required_capabilities_json <@ %s::jsonb
              AND (NOT %s OR %s::jsonb <@ versions.required_capabilities_json)
              AND (cardinality(%s::text[]) = 0 OR NOT versions.handle=ANY(%s::text[]))
              AND (cardinality(%s::text[]) = 0 OR versions.handle=ANY(%s::text[]))
              AND (cardinality(%s::text[]) = 0 OR NOT versions.purpose=ANY(%s::text[]))
            ORDER BY versions.difficulty,versions.item_key,versions.version,versions.handle
            LIMIT %s
            """,
            (
                key,
                normalized_purpose,
                normalized_purpose,
                normalized_language,
                normalized_language,
                list(kind_values),
                list(kind_values),
                list(difficulty_values),
                list(difficulty_values),
                canonical_json(list(capabilities)),
                exact_capabilities,
                canonical_json(list(capabilities)),
                list(excluded),
                list(excluded),
                list(required),
                list(required),
                list(excluded_purpose_values),
                list(excluded_purpose_values),
                limit,
            ),
        ).fetchall()
        return tuple(
            PublishedLearningItemCandidate(
                handle=str(row["handle"]),
                item_key=str(row["item_key"]),
                version=str(row["version"]),
                kind=str(row["item_kind"]),
                purpose=str(row["purpose"]),
                knowledge_key=str(row["knowledge_key"]),
                language_id=str(row["language_id"]),
                difficulty=str(row["difficulty"]),
                title=str(row["title"]),
                summary=str(row["candidate_summary"]),
                required_capabilities=_strings(row["required_capabilities_json"]),
                allowed_interactions=_strings(row["allowed_interactions_json"]),
            )
            for row in rows
        )

    def _ensure_immutable_content(
        self, source: LearningItemSourceV1, *, creator_identity: str,
    ) -> tuple[str, str]:
        """Common persistence only; the calling importer owns typed validation.

        Keep the original IDs, hashes, collision checks and insert order for both
        curated V1 and explicitly admitted native V2 content. This is not an
        import/publication entrypoint and cannot mint validation authority.
        """
        blueprint, public = source.blueprint, source.public
        blueprint_id = str(learning_item_uuid("blueprint", f"{blueprint.blueprint_key}@{blueprint.version}"))
        item_id = str(learning_item_uuid("item", public.item_key))
        version_id = str(learning_item_uuid("version", f"{public.item_key}@{public.version}"))
        private_id = str(learning_item_uuid("private", f"{public.item_key}@{public.version}"))
        self._ensure_blueprint(source, blueprint_id)
        self._ensure_item(item_id=item_id, item_key=public.item_key, item_kind=public.kind.value)
        self._ensure_version(
            source, version_id=version_id, item_id=item_id, blueprint_id=blueprint_id,
            handle=learning_item_handle(public.item_key, public.version, source.content_hash),
            creator_identity=creator_identity,
        )
        self._ensure_public(source, version_id=version_id)
        self._ensure_private(source, private_id=private_id, version_id=version_id)
        return item_id, version_id

    def _ensure_blueprint(self, source: LearningItemSourceV1, blueprint_id: str) -> None:
        blueprint = source.blueprint
        row = self._conn.execute(
            """
            INSERT INTO tutor_learning_item_blueprints (
              id,blueprint_key,version,knowledge_key,item_kind,purpose,language_id,difficulty,risk_tier,
              runtime_profile_key,required_capabilities_json,blueprint_json,blueprint_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
            ON CONFLICT (blueprint_key,version) DO NOTHING RETURNING id,blueprint_hash
            """,
            (
                blueprint_id,
                blueprint.blueprint_key,
                blueprint.version,
                blueprint.knowledge_key,
                blueprint.item_kind.value,
                blueprint.purpose.value,
                blueprint.language_id,
                blueprint.difficulty_profile.base.value,
                blueprint.publication_policy.risk_tier.value,
                blueprint.runtime_profile_id,
                canonical_json(list(blueprint.required_capabilities)),
                canonical_json(blueprint.model_dump(mode="json")),
                blueprint.blueprint_hash,
            ),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT id,blueprint_hash FROM tutor_learning_item_blueprints WHERE blueprint_key=%s AND version=%s",
                (blueprint.blueprint_key, blueprint.version),
            ).fetchone()
        if row is None or str(row["id"]) != blueprint_id or str(row["blueprint_hash"]) != blueprint.blueprint_hash:
            raise LearningItemImportConflict("learning item blueprint identity conflicts with stored content")

    def _ensure_item(self, *, item_id: str, item_key: str, item_kind: str) -> None:
        self._conn.execute(
            "INSERT INTO tutor_learning_items (id,item_key,item_kind) VALUES (%s,%s,%s) ON CONFLICT (item_key) DO NOTHING",
            (item_id, item_key, item_kind),
        )
        row = self._conn.execute(
            "SELECT id,item_kind FROM tutor_learning_items WHERE item_key=%s",
            (item_key,),
        ).fetchone()
        if row is None or str(row["id"]) != item_id or str(row["item_kind"]) != item_kind:
            raise LearningItemImportConflict("learning item identity conflicts with stored kind")

    def _ensure_version(
        self,
        source: LearningItemSourceV1,
        *,
        version_id: str,
        item_id: str,
        blueprint_id: str,
        handle: str,
        creator_identity: str,
    ) -> None:
        blueprint = source.blueprint
        public = source.public
        self._conn.execute(
            """
            INSERT INTO tutor_learning_item_versions (
              id,item_id,blueprint_id,item_key,version,item_kind,purpose,knowledge_key,language_id,difficulty,
              risk_tier,runtime_profile_key,required_capabilities_json,source_schema_version,compiler_version,
              source_hash,blueprint_hash,public_hash,private_hash,content_hash,handle,creator_identity
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (item_key,version) DO NOTHING
            """,
            (
                version_id,
                item_id,
                blueprint_id,
                public.item_key,
                public.version,
                public.kind.value,
                public.purpose.value,
                blueprint.knowledge_key,
                blueprint.language_id,
                public.difficulty.value,
                blueprint.publication_policy.risk_tier.value,
                blueprint.runtime_profile_id,
                canonical_json(list(blueprint.required_capabilities)),
                source.schema_version,
                LEARNING_ITEM_COMPILER_VERSION,
                source.source_hash,
                blueprint.blueprint_hash,
                public.public_hash,
                source.private.private_hash,
                source.content_hash,
                handle,
                creator_identity,
            ),
        )
        row = self._conn.execute(
            """SELECT id,content_hash,handle,source_hash,creator_identity
               FROM tutor_learning_item_versions WHERE item_key=%s AND version=%s""",
            (public.item_key, public.version),
        ).fetchone()
        if (
            row is None
            or str(row["id"]) != version_id
            or str(row["content_hash"]) != source.content_hash
            or str(row["handle"]) != handle
            or str(row["source_hash"]) != source.source_hash
            or str(row["creator_identity"]) != creator_identity
        ):
            raise LearningItemImportConflict("learning item version identity conflicts with stored content")

    def _ensure_public(self, source: LearningItemSourceV1, *, version_id: str) -> None:
        public = source.public
        self._conn.execute(
            """
            INSERT INTO tutor_learning_item_public_contents (
              version_id,schema_version,public_json,public_hash,title,candidate_summary,allowed_interactions_json
            ) VALUES (%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb) ON CONFLICT (version_id) DO NOTHING
            """,
            (
                version_id,
                public.schema_version,
                canonical_json(public.model_dump(mode="json")),
                public.public_hash,
                public.title,
                _candidate_summary(public.instruction_markdown),
                canonical_json([item.value for item in public.allowed_interactions]),
            ),
        )
        row = self._conn.execute(
            "SELECT public_hash FROM tutor_learning_item_public_contents WHERE version_id=%s",
            (version_id,),
        ).fetchone()
        if row is None or str(row["public_hash"]) != public.public_hash:
            raise LearningItemImportConflict("learning item public content conflicts with stored content")

    def _ensure_private(self, source: LearningItemSourceV1, *, private_id: str, version_id: str) -> None:
        private = source.private
        self._conn.execute(
            """INSERT INTO tutor_learning_item_private_contents (id,version_id,schema_version,private_json,private_hash)
               VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT (version_id) DO NOTHING""",
            (
                private_id,
                version_id,
                private.schema_version,
                canonical_json(private.model_dump(mode="json")),
                private.private_hash,
            ),
        )
        row = self._conn.execute(
            "SELECT id,private_hash FROM tutor_learning_item_private_contents WHERE version_id=%s",
            (version_id,),
        ).fetchone()
        if row is None or str(row["id"]) != private_id or str(row["private_hash"]) != private.private_hash:
            raise LearningItemImportConflict("learning item private content conflicts with stored content")

    def _ensure_validation(self, validation: LearningItemValidationReceiptV1, *, version_id: str) -> str:
        validation_id = str(learning_item_uuid("import", f"validation:{validation.receipt_hash}"))
        self._conn.execute(
            """
            INSERT INTO tutor_learning_item_validation_receipts (
              id,version_id,item_handle,content_hash,schema_version,policy_version,compiler_version,
              receipt_json,receipt_hash,passed
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,true)
            ON CONFLICT (version_id,policy_version,compiler_version)
              WHERE schema_version='learning_item_validation_v1' DO NOTHING
            """,
            (
                validation_id,
                version_id,
                validation.item_handle,
                validation.content_hash,
                validation.schema_version,
                validation.policy_version,
                validation.compiler_version,
                canonical_json(validation.model_dump(mode="json")),
                validation.receipt_hash,
            ),
        )
        row = self._conn.execute(
            """SELECT id,receipt_hash FROM tutor_learning_item_validation_receipts
               WHERE version_id=%s AND policy_version=%s AND compiler_version=%s""",
            (version_id, validation.policy_version, validation.compiler_version),
        ).fetchone()
        if row is None or str(row["id"]) != validation_id or str(row["receipt_hash"]) != validation.receipt_hash:
            raise LearningItemImportConflict("learning item validation receipt conflicts with stored receipt")
        return validation_id

    def _ensure_initial_publication(
        self,
        *,
        version_id: str,
        handle: str,
        content_hash: str,
        validation_hash: str,
        policy_version: str,
        validation_id: str,
        import_key: str,
        occurred_at: datetime,
    ) -> str:
        existing = self._conn.execute(
            "SELECT id,state,authority_hash FROM tutor_learning_item_publication_events WHERE version_id=%s AND state_version=1",
            (version_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["state"]) != "machine_verified" or str(existing["authority_hash"]) != validation_hash:
                raise LearningItemImportConflict("learning item initial publication receipt conflicts")
            return str(existing["id"])
        transition_key = stable_key(f"import:{import_key}", label="initial publication transition")
        event_id = str(learning_item_uuid("import", f"publication:{version_id}:1"))
        request_hash = canonical_hash(
            {"version_id": version_id, "state": "machine_verified", "validation_hash": validation_hash}
        )
        self._conn.execute(
            """
            INSERT INTO tutor_learning_item_publication_events (
              id,version_id,item_handle,content_hash,predecessor_event_id,state_version,state,
              transition_key,request_hash,authority_kind,authority_hash,authority_reference_id,
              policy_version,reason_code,occurred_at
            ) VALUES (%s,%s,%s,%s,NULL,1,'machine_verified',%s,%s,'validation',%s,%s,%s,NULL,%s)
            """,
            (
                event_id,
                version_id,
                handle,
                content_hash,
                transition_key,
                request_hash,
                validation_hash,
                validation_id,
                policy_version,
                occurred_at,
            ),
        )
        return event_id


def _source_path(value: str) -> str:
    normalized = str(value).strip().replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(normalized)
    parts = posix_path.parts
    if (
        not normalized
        or len(normalized) > 320
        or posix_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("learning item source path must be a safe relative path")
    return posix_path.as_posix()


def _candidate_summary(value: str) -> str:
    compact = " ".join(str(value).split())
    if not compact:
        raise ValueError("learning item candidate summary is empty")
    return compact if len(compact) <= 480 else compact[:477].rstrip() + "..."


def _handle(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _HANDLE.fullmatch(normalized):
        raise ValueError("learning item handle is invalid")
    return normalized


def _uuid_or_none(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError("stored Learning Item candidate array is invalid")
    return tuple(value)


def _publication_state(value: object) -> PublicationState:
    state = str(value)
    if state not in _ALLOWED_STATES:
        raise RuntimeError("stored Learning Item publication state is invalid")
    return state  # type: ignore[return-value]


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RuntimeError("stored Learning Item integer is invalid")
    return int(value)


def _import_result(row: Mapping[str, object], *, replayed: bool) -> LearningItemImportResult:
    return LearningItemImportResult(
        item_id=str(row["item_id"]),
        version_id=str(row["version_id"]),
        handle=str(row["item_handle"]),
        content_hash=str(row["content_hash"]),
        validation_receipt_id=str(row["validation_receipt_id"]),
        import_receipt_id=str(row["id"]),
        publication_event_id=str(row["publication_event_id"]),
        publication_state=_publication_state(row["publication_state"]),
        publication_state_version=_int_value(row["publication_state_version"]),
        replayed=replayed,
    )


__all__ = (
    "IMPORTER_VERSION",
    "LearningItemBankError",
    "LearningItemImportConflict",
    "LearningItemImportResult",
    "LearningItemNotFound",
    "LearningItemPublicationConflict",
    "LearningItemPublicationResult",
    "PostgresLearningItemBankRepository",
    "PublishedLearningItemCandidate",
)
