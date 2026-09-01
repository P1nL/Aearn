"""组合各持久化职责、持有唯一 caller-owned connection 的 facade。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings

from ._namespace import *

if TYPE_CHECKING:
    from .adapters import PostgresTutorRunStore
from .conversation import ConversationPersistenceMixin
from .interaction import InteractionPersistenceMixin
from .public_process import PublicProcessPersistenceMixin
from .dispatch import DispatchPersistenceMixin
from .run import RunPersistenceMixin
from .effects import EffectsPersistenceMixin
from .curation import CurationPersistenceMixin
from .diagnostics import DiagnosticsPersistenceMixin


class PostgresTutorRepository(
    ConversationPersistenceMixin,
    InteractionPersistenceMixin,
    PublicProcessPersistenceMixin,
    DispatchPersistenceMixin,
    RunPersistenceMixin,
    EffectsPersistenceMixin,
    CurationPersistenceMixin,
    DiagnosticsPersistenceMixin,
):
    """Scoped target persistence with transaction-level lifecycle methods."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        projector: TutorSafeProjection | None = None,
        failpoint: Failpoint | None = None,
        effect_handlers: Mapping[str, EffectHandler] | None = None,
        effect_descriptors: Sequence[EffectDescriptor] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._projector = projector or TutorSafeProjection()
        self._failpoint = failpoint
        self._effect_handlers = dict(effect_handlers or {})
        # This value is server configuration, never exposed in API payloads or logs.
        self._cursor_signing_key = hashlib.sha256(
            self._settings.tutor_cursor_signing_key.encode("utf-8")
        ).digest()
        descriptors = tuple(default_effect_descriptors() if effect_descriptors is None else effect_descriptors)
        self._effect_descriptors = {descriptor.effect_type: descriptor for descriptor in descriptors}
        if len(self._effect_descriptors) != len(descriptors):
            raise ValueError("effect descriptors must have unique effect types")
        for effect_type in self._effect_handlers:
            _safe_key(effect_type, label="registered effect type")

    def record_catalog_snapshot(self, catalog: SkillCatalogSnapshot) -> str:
        catalog_payload = {
            "catalog_digest": catalog.digest,
            "skills": [
                {
                    "skill_id": skill.manifest.id,
                    "skill_version": skill.manifest.version,
                    "manifest_hash": skill.manifest_hash,
                    "instruction_hash": skill.instruction_hash,
                    "evaluation_hash": skill.evaluation_hash,
                    "required_capability_ids": list(skill.manifest.requires_capabilities),
                    "allowed_effect_types": list(skill.manifest.allowed_effect_types),
                    "policy_tags": list(skill.manifest.policy_tags),
                }
                for skill in catalog.skills
            ],
        }
        safe_catalog = self._projector.project(catalog_payload)
        existing = self._conn.execute(
            "SELECT manifest_json FROM tutor_catalog_snapshots WHERE digest = %s",
            (catalog.digest,),
        ).fetchone()
        if existing is not None:
            if self._projector.export(existing["manifest_json"]) != safe_catalog:
                raise TutorCatalogEvidenceError("catalog digest conflicts with stored evidence")
            return catalog.digest
        self._conn.execute(
            """
            INSERT INTO tutor_catalog_snapshots (digest, manifest_json, redaction_version)
            VALUES (%s, %s::jsonb, %s)
            """,
            (catalog.digest, _json(safe_catalog), self._projector.version),
        )
        return catalog.digest

    def as_run_store(self, *, user_id: str) -> "PostgresTutorRunStore":
        from .adapters import PostgresTutorRunStore

        return PostgresTutorRunStore(repository=self, user_id=user_id)

    def _trip_failpoint(self, stage: str) -> None:
        if self._failpoint is not None:
            self._failpoint(stage)
