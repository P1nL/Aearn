"""Private P4/P5 append-only artifacts in caller-owned transactions."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.diagnostic_policy import AdmissionEvaluationV3, ReviewBundleV3
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.private_enhancement_contracts import PrivateSlotRef
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvaluationV2, BlindSolveReceiptV2, ReviewBundleV2,
)
from app.services.learning.item_supply.storage import PostgresPrivateSupplyStorage
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

ArtifactKind = Literal["validation", "blind_solve", "review_bundle", "admission_evaluation"]
if TYPE_CHECKING:
    from app.services.learning.item_supply.private_generation_persistence_phase import IssuedPrivateGenerationPersistencePhase

ArtifactMode = Literal["live", "synthetic"]

PipelineReceipt = CandidateValidationV2 | BlindSolveReceiptV2 | ReviewBundleV2 | AdmissionEvaluationV2 | ReviewBundleV3 | AdmissionEvaluationV3
_TYPES: dict[str, type[BaseModel]] = {
    "validation": CandidateValidationV2, "blind_solve": BlindSolveReceiptV2,
    "review_bundle": ReviewBundleV2, "admission_evaluation": AdmissionEvaluationV2,
}


class PipelineRepositoryError(ValueError):
    """Only stable codes leave this boundary, not artifacts or provider payloads."""


class PipelineArtifactRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn
        self.runtime = ItemSupplyRuntimeRepository(conn)

    def _context(self, lease: JobLeaseV1, scope_id: UUID, now: datetime, mode: ArtifactMode) -> JobLeaseV1:
        lease = checked_model(lease, JobLeaseV1)
        if lease.visibility != "private" or lease.owner_id is None or lease.owner_epoch is None:
            raise PipelineRepositoryError("PRIVATE_PIPELINE_REQUIRED")
        if mode not in ("live", "synthetic"):
            raise PipelineRepositoryError("PIPELINE_MODE_INVALID")
        current = self.runtime._control(lease, now=now)
        if UUID(str(current["scope_id"])) != scope_id:
            raise PipelineRepositoryError("PIPELINE_SCOPE_MISMATCH")
        if mode == "synthetic":
            database = self.conn.execute("SELECT current_database() AS db").fetchone()
            if database is None or database["db"] not in ("aearn_b1b_fixture_20260930", "aearn_b1d_sandbox_20261001"):
                raise PipelineRepositoryError("SYNTHETIC_PIPELINE_OUTSIDE_FIXTURE")
        return lease

    def store_generation(
        self, *, lease: JobLeaseV1, scope_id: UUID, request: GenerationRequestV2,
        result: GenerationResultV2, artifact_key: str, now: datetime,
        mode: ArtifactMode, source_authority: RagSourceAuthority | None = None,
        private_slot_ref: PrivateSlotRef | None = None,
        persistence_phase: IssuedPrivateGenerationPersistencePhase | None = None,
    ) -> dict[str, Any]:
        lease = self._context(lease, scope_id, now, mode)
        request = checked_model(request, GenerationRequestV2)
        result = checked_model(result, GenerationResultV2)
        if result.state != "staged" or result.source is None or result.receipt is None:
            raise PipelineRepositoryError("PIPELINE_CANDIDATE_NOT_STAGED")
        source = checked_model(result.source, LearningItemSourceV1)
        receipt = result.receipt
        profile_matches = request.profile == lease.profile
        if persistence_phase is not None:
            from app.services.learning.item_supply.private_generation_persistence_phase import (
                IssuedPrivateGenerationPersistencePhase, PrivateGenerationPersistencePhaseOwner,
            )
            cap = persistence_phase
            if (type(cap) is not IssuedPrivateGenerationPersistencePhase
                    or type(cap.owner) is not PrivateGenerationPersistencePhaseOwner
                    or cap.owner.conn is not self.conn or cap.owner.pipeline.artifacts is not self):
                raise PipelineRepositoryError('PRIVATE_PERSISTENCE_PHASE_OWNER_REQUIRED')
            current = cap.owner.require(cap)
            if (mode != 'live' or lease != current.lease or scope_id != cap.ref.scope_id
                    or private_slot_ref != cap.ref or request != cap.request or result != cap.result
                    or artifact_key != 'generation.'+cap.request.candidate_id.hex
                    or source_authority is not cap.owner.facts.source_authority):
                raise PipelineRepositoryError('PRIVATE_PERSISTENCE_PHASE_EXACT_DATA_REQUIRED')
            # Historical generation profile is sealed by 560; only this exact
            # separately committed bridge supplies the different current writer.
            profile_matches = True
        scope = self.conn.execute(
            "SELECT scope_hash FROM tutor_item_supply_private_scopes WHERE id=%s AND user_id=%s AND epoch=%s",
            (scope_id, lease.owner_id, lease.owner_epoch),
        ).fetchone()
        if (scope is None or request.scope_hash != scope["scope_hash"]
                or receipt.scope_hash != request.scope_hash or receipt.candidate_id != request.candidate_id
                or not profile_matches or source.blueprint != request.blueprint
                or (source.public.item_key, source.public.version) != (request.item_key, request.version)):
            raise PipelineRepositoryError("PIPELINE_REQUEST_MISMATCH")
        if mode == "live":
            if request.demand_binding is not None:
                from app.services.learning.item_supply.generation_demand import frozen_private_demand

                frozen_private_demand(self.conn, lease=lease, scope_id=scope_id, request=request)
            if (not isinstance(source_authority, RagSourceAuthority) or source_authority.connection is not self.conn
                    or receipt.provider.mode != "provider" or len(receipt.sources) != len(request.materials)):
                raise PipelineRepositoryError("PIPELINE_AUTHORITY_REQUIRED")
            for material, expected in zip(request.materials, receipt.sources, strict=True):
                source_authority.assert_current(material, expected)
        if lease.owner_id is None or lease.owner_epoch is None:
            raise PipelineRepositoryError("PRIVATE_PIPELINE_REQUIRED")
        storage = PostgresPrivateSupplyStorage(self.conn, user_id=lease.owner_id, expected_epoch=lease.owner_epoch)
        candidate_key=f"b1c.{request.candidate_id.hex}"
        version_number=1
        if private_slot_ref is not None:
            ref=checked_model(private_slot_ref,PrivateSlotRef)
            if mode!='live' or (ref.user_id,ref.epoch,ref.scope_id)!=(lease.owner_id,lease.owner_epoch,scope_id):
                raise PipelineRepositoryError('PRIVATE_NATIVE_EXACT_SLOT_REQUIRED')
            phase=self.conn.execute(
                "SELECT payload_json->'ref' AS ref FROM tutor_item_supply_private_persistent_pack_journal "
                "WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND record_kind='phase' "
                "AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=%s "
                "AND item_supply_internal.private_pack_slot_current(%s,%s,%s,%s,%s,%s,%s,%s)",
                (ref.pack_task_id,ref.user_id,ref.epoch,ref.scope_id,str(lease.job_id),ref.pack_task_id,
                 ref.slot_id,ref.business_item_id,ref.root_id,ref.user_id,ref.epoch,ref.scope_id,lease.job_id)).fetchone()
            if phase is None or phase['ref']!=ref.model_dump(mode='json'):
                raise PipelineRepositoryError('PRIVATE_NATIVE_ORIGINAL_PHASE_REQUIRED')
            candidate_key='private.native.'+ref.business_item_id.hex
            if ref.parent_version_id is not None:
                parent=self.conn.execute(
                    'SELECT v.version,v.public_json,c.candidate_key FROM tutor_item_supply_private_versions v '
                    'JOIN tutor_item_supply_private_candidates c ON c.id=v.candidate_id AND c.user_id=v.user_id AND c.epoch=v.epoch '
                    'WHERE v.id=%s AND v.user_id=%s AND v.epoch=%s AND v.scope_id=%s FOR SHARE OF v,c',
                    (ref.parent_version_id,ref.user_id,ref.epoch,ref.scope_id)).fetchone()
                if (parent is None or parent['candidate_key']!=candidate_key
                        or parent['public_json']['item_key']!=source.public.item_key):
                    raise PipelineRepositoryError('PRIVATE_NATIVE_SAME_BUSINESS_VERSION_CHAIN_REQUIRED')
                version_number=int(parent['version'])+1
        candidate = storage.store_candidate(scope_id=scope_id, candidate_key=candidate_key)
        version = storage.store_version(scope_id=scope_id, candidate_id=candidate, version=version_number,
                                        public=source.public, private=source.private)
        source_json, receipt_json = source.model_dump(mode="json"), receipt.model_dump(mode="json")
        request_json = request.model_dump(mode="json")
        expected_hash = canonical_hash({"source": source_json, "receipt": receipt_json})
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_private_generation_artifacts "
            "(user_id,epoch,scope_id,job_id,lease_generation,lease_state_version,candidate_id,version_id,artifact_key,source_hash,content_hash,mode,source_json,receipt_json,request_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(job_id,lease_generation,artifact_key) DO NOTHING RETURNING *",
            (lease.owner_id, lease.owner_epoch, scope_id, lease.job_id, lease.generation, lease.state_version,
             candidate, version.id, artifact_key, source.source_hash, source.content_hash, mode,
             Jsonb(source_json), Jsonb(receipt_json), Jsonb(request_json)),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM tutor_item_supply_private_generation_artifacts WHERE job_id=%s AND lease_generation=%s AND artifact_key=%s AND user_id=%s AND epoch=%s",
                (lease.job_id, lease.generation, artifact_key, lease.owner_id, lease.owner_epoch),
            ).fetchone()
        if (row is None or row["artifact_hash"] != expected_hash or row["mode"] != mode
                or row["request_json"] != request_json):
            raise PipelineRepositoryError("PIPELINE_GENERATION_CONFLICT")
        return row

    def get_generation(self, *, lease: JobLeaseV1, scope_id: UUID, artifact_id: UUID, now: datetime, mode: ArtifactMode) -> dict[str, Any]:
        self._context(lease, scope_id, now, mode)
        row = self.conn.execute(
            "SELECT * FROM tutor_item_supply_private_generation_artifacts WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND job_id=%s AND lease_generation=%s",
            (artifact_id, lease.owner_id, lease.owner_epoch, scope_id, lease.job_id, lease.generation),
        ).fetchone()
        if row is None or row["mode"] != mode:
            raise PipelineRepositoryError("PIPELINE_ARTIFACT_UNAVAILABLE")
        return row

    def store_receipt(
        self, *, lease: JobLeaseV1, scope_id: UUID, artifact_id: UUID,
        kind: ArtifactKind, payload: PipelineReceipt, artifact_key: str,
        now: datetime, mode: ArtifactMode,
    ) -> dict[str, Any]:
        generation = self.get_generation(lease=lease, scope_id=scope_id, artifact_id=artifact_id, now=now, mode=mode)
        expected_type = _TYPES.get(kind)
        if expected_type is None or type(payload) is not expected_type:
            raise PipelineRepositoryError("PIPELINE_RECEIPT_TYPE_INVALID")
        checked = checked_model(payload, expected_type)
        data = checked.model_dump(mode="json")
        binding = data.get("binding", data)
        if not isinstance(binding, dict) or binding.get("content_hash") != generation["content_hash"] or binding.get("source_hash") != generation["source_hash"]:
            raise PipelineRepositoryError("PIPELINE_RECEIPT_STALE")
        if data.get("publication_enabled", False) is not False:
            raise PipelineRepositoryError("PIPELINE_CANNOT_PUBLISH")
        if isinstance(checked, (BlindSolveReceiptV2, ReviewBundleV2, AdmissionEvaluationV2)):
            if (checked.binding.version_key != str(generation["version_id"])
                    or checked.binding.candidate_key != str(generation["candidate_id"])):
                raise PipelineRepositoryError("PIPELINE_VERSION_MISMATCH")
        expected_hash = canonical_hash(data)
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_private_pipeline_receipts "
            "(user_id,epoch,scope_id,job_id,lease_generation,lease_state_version,generation_artifact_id,version_id,content_hash,artifact_key,artifact_kind,schema_version,mode,payload_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(job_id,lease_generation,artifact_kind,artifact_key) DO NOTHING RETURNING *",
            (lease.owner_id, lease.owner_epoch, scope_id, lease.job_id, lease.generation, lease.state_version,
             artifact_id, generation["version_id"], generation["content_hash"], artifact_key, kind,
             data["schema_version"], mode, Jsonb(data)),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM tutor_item_supply_private_pipeline_receipts WHERE job_id=%s AND lease_generation=%s AND artifact_kind=%s AND artifact_key=%s AND user_id=%s AND epoch=%s",
                (lease.job_id, lease.generation, kind, artifact_key, lease.owner_id, lease.owner_epoch),
            ).fetchone()
        if row is None or row["receipt_hash"] != expected_hash or row["mode"] != mode:
            raise PipelineRepositoryError("PIPELINE_RECEIPT_CONFLICT")
        return row
