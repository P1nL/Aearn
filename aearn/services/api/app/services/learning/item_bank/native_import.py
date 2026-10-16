"""Default-off native DATA ingestion into the original immutable Learning Item Bank.

Only a committed, current-operation CandidateValidationV2 is admitted. No runner,
V1 runtime validator, publication, exercise, inventory or final-facts authority is
created here. Stored terminal JSON is audited as DATA, never rehydrated as seals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.config import Settings
if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
from app.services.learning.item_bank.contracts import (
    LEARNING_ITEM_COMPILER_VERSION, LearningItemKind, canonical_hash, learning_item_handle,
    learning_item_uuid, stable_key,
)
from app.services.learning.item_bank.repository import (
    LearningItemBankError, LearningItemImportConflict, LearningItemImportResult,
    PostgresLearningItemBankRepository, _import_result,
)
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.sandbox.execution_contracts import RUNNER_VERSION
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
from app.services.learning.item_supply.shared_pipeline_repository import (
    ResolvedSharedGeneration, SharedPipelineArtifactRepository,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2
from app.services.learning.item_supply.validators.profiles import required_probes

NATIVE_IMPORTER_VERSION = "learning_item_native_repository_v2"
NATIVE_VALIDATION_POLICY = "learning_item_native_import_v2"


@dataclass(frozen=True)
class _ValidatedNativeData:
    generation: ResolvedSharedGeneration
    validation: CandidateValidationV2
    row: dict[str, Any]


def _check_validation_binding(
    generation: ResolvedSharedGeneration, *, lease: JobLeaseV1,
    spec: FiniteCandidateSpecV1, row: dict[str, Any],
) -> _ValidatedNativeData:
    """Audit an already committed row; this pure helper grants no execution rights."""
    source, artifact = generation.source, generation.artifact
    validation = CandidateValidationV2.model_validate_json(json.dumps(row["payload_json"]))
    preparation, evidence = row["preparation_json"], row["evidence_json"]
    if (row["same_transaction"] is not False or row["evidence_same_transaction"] is not False
            or row["preparation_same_transaction"] is not False
            or row["artifact_kind"] != "validation" or row["schema_version"] != "candidate_validation_v2"
            or row["mode"] != "live" or row["publication_enabled"] is not False
            or UUID(str(row["job_id"])) != lease.job_id or row["lease_generation"] != lease.generation
            or UUID(str(row["generation_artifact_id"])) != UUID(str(artifact["id"]))
            or UUID(str(row["item_id"])) != learning_item_uuid("item", source.public.item_key)
            or UUID(str(row["version_id"])) != learning_item_uuid("version", f"{source.public.item_key}@{source.public.version}")
            or (row["item_id"], row["version_id"]) != (artifact["item_id"], artifact["version_id"])
            or (row["source_hash"], row["content_hash"]) != (source.source_hash, source.content_hash)
            or validation.state != "machine_verified" or validation.source_hash != source.source_hash
            or validation.content_hash != source.content_hash or row["receipt_hash"] != validation.evidence_hash
            or preparation["spec"] != spec.model_dump(mode="json")
            or preparation["request"] != generation.request.model_dump(mode="json")
            or preparation["artifact_id"] != str(artifact["id"]) or preparation["artifact_hash"] != artifact["artifact_hash"]
            or (preparation["source_hash"], preparation["content_hash"]) != (source.source_hash, source.content_hash)
            or preparation["lease"]["job_id"] != str(lease.job_id)
            or preparation["lease"]["generation"] != lease.generation
            or preparation["lease"]["profile"] != lease.profile.model_dump(mode="json")
            or row["preparation_hash"] != canonical_hash(preparation)
            or row["evidence_hash"] != canonical_hash(evidence)
            or evidence["validation"] != validation.model_dump(mode="json")
            or evidence["publication_enabled"] is not False
            or row["artifact_key"] != f"validation.{UUID(str(row['preparation_id'])).hex}"):
        raise LearningItemBankError("NATIVE_BANK_COMMITTED_VALIDATION_MISMATCH")
    # Pure finite source/spec checks. Only KC invokes its genuine static proof;
    # code/SQL builds the registered plan without executing a submission.
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=generation.request.materials)
    if preparation["inputs"] != inputs.model_dump(mode="json"):
        raise LearningItemBankError("NATIVE_BANK_FINITE_SPECIFICATION_MISMATCH")
    if inputs.static_facts is not None:
        if (source.public.kind is not LearningItemKind.KNOWLEDGE_CHECK
                or validation != inputs.static_facts.validation or evidence["terminals"] != []
                or evidence["actual"] is not None or row["reservation_id"] is not None):
            raise LearningItemBankError("NATIVE_BANK_STATIC_PROOF_MISMATCH")
    else:
        execution, scope = validation.execution_evidence, spec.coverage_blueprint.scope
        assert inputs.probe_plan is not None
        if (execution is None or validation.mode != "live" or validation.legacy_receipt is not None
                or execution.mode != "live" or execution.isolation != "approved_os_boundary"
                or execution.kind != source.public.kind.value or execution.language != source.blueprint.language_id
                or execution.runtime_profile_id != source.blueprint.runtime_profile_id
                or execution.scorer_version != scope.scorer_version or execution.runner_version != RUNNER_VERSION
                or execution.dialect != ("sqlite" if source.public.kind is LearningItemKind.SQL else None)
                or {p.name for p in execution.probes} != set(required_probes(source, finite_spec=spec))
                or len({p.name for p in execution.probes}) != len(execution.probes)
                or any(p.status != "passed" or p.profile_version != inputs.probe_plan.profile_id for p in execution.probes)
                or row["reservation_id"] is None or not evidence["terminals"]
                or any(t["lock_fingerprint"] != scope.runtime_profile_hash or t["run_id"] != str(execution.run_id)
                       or t["mode"] != "live" or t["isolation"] != "approved_os_boundary"
                       for t in evidence["terminals"])):
            raise LearningItemBankError("NATIVE_BANK_EXECUTION_BINDING_MISMATCH")
    return _ValidatedNativeData(generation, validation, row)


class NativeLearningItemBankImporter:
    """Internal caller-transaction-owned B1d importer, never a publication port."""

    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 artifacts: SharedPipelineArtifactRepository, source_authority: RagSourceAuthority,
                 continuation_owner: SharedCandidateContinuationOwner | None = None,
                 enabled: bool = False, committed_admission: IssuedCommittedChildAdmission | None = None) -> None:
        self.conn, self.settings, self.enabled = conn, settings, enabled
        if type(artifacts) is not SharedPipelineArtifactRepository or artifacts.conn is not conn:
            raise LearningItemBankError("NATIVE_BANK_SHARED_OWNER_REQUIRED")
        artifacts.require_source(source_authority)
        if continuation_owner is not None and (type(continuation_owner) is not SharedCandidateContinuationOwner
                                               or continuation_owner.conn is not conn):
            raise LearningItemBankError("NATIVE_BANK_CONTINUATION_OWNER_REQUIRED")
        self.artifacts, self.authority, self.continuation = artifacts, source_authority, continuation_owner
        self.bank = PostgresLearningItemBankRepository(conn)
        self.committed_admission = committed_admission
        if committed_admission is not None:
            from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
            if (type(committed_admission) is not IssuedCommittedChildAdmission or committed_admission.owner.conn is not conn
                    or continuation_owner is not None or committed_admission.owner.type_owner.source_authority is not source_authority):
                raise LearningItemBankError("COMMITTED_ADMISSION_NATIVE_IMPORT_OWNER_REQUIRED")

    def _load(self, *, lease: JobLeaseV1, artifact_id: UUID, validation_receipt_id: UUID,
              spec: FiniteCandidateSpecV1) -> _ValidatedNativeData:
        if self.committed_admission is not None:
            from app.services.learning.item_supply.persistent_pack_committed_admission import require
            frame = self.committed_admission
            require(frame)
            q = frame.quality
            if (lease != frame.lease or artifact_id != q.artifact["id"] or validation_receipt_id != q.validation_row["id"]
                    or spec != q.spec):
                raise LearningItemBankError("COMMITTED_ADMISSION_IMPORT_EXACT_QUALITY_REQUIRED")
            historical_row = dict(q.validation_row)
            historical_row.update(preparation_id=q.validation_preparation["id"],preparation_json=q.validation_preparation["payload_json"],
                preparation_hash=q.validation_preparation["payload_hash"],preparation_same_transaction=q.validation_preparation["same_transaction"],
                evidence_id=q.validation_evidence["id"],evidence_json=q.validation_evidence["payload_json"],
                evidence_hash=q.validation_evidence["payload_hash"],evidence_same_transaction=q.validation_evidence["same_transaction"],
                reservation_id=q.validation_evidence["reservation_id"])
            # Historical validation DATA is checked against its ACTUAL producer lease.
            # New use is separately authorized by require(frame), never the old lease.
            return _check_validation_binding(frame.generation_data(),lease=q.validation_lease,spec=spec,row=historical_row)
        now = server_clock(self.conn, datetime.now(UTC))
        generation = self.artifacts.resolve_generation(lease=lease, artifact_id=artifact_id, now=now,
            source_authority=self.authority, spec=spec, continuation_owner=self.continuation)
        if generation.receipt.provider.mode != "provider" or not generation.receipt.sources:
            raise LearningItemBankError("NATIVE_BANK_REAL_GENERATION_REQUIRED")
        meta = self.artifacts.context(lease, now=now)
        if (meta["coverage"] != spec.coverage_blueprint
                or UUID(str(meta["root_id"])) != UUID(str(generation.artifact["root_id"]))):
            raise LearningItemBankError("NATIVE_BANK_CURRENT_ROOT_MISMATCH")
        row = self.conn.execute(
            "SELECT r.*,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction,"
            "p.id AS preparation_id,p.payload_json AS preparation_json,p.payload_hash AS preparation_hash,"
            "p.xmin::text::bigint=(txid_current() %% 4294967296) AS preparation_same_transaction,"
            "e.id AS evidence_id,e.payload_json AS evidence_json,e.payload_hash AS evidence_hash,e.reservation_id,"
            "e.xmin::text::bigint=(txid_current() %% 4294967296) AS evidence_same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r "
            "JOIN tutor_item_supply_shared_validation_preparations p ON p.generation_artifact_id=r.generation_artifact_id "
            "AND p.job_id=r.job_id AND p.lease_generation=r.lease_generation "
            "JOIN tutor_item_supply_shared_validation_evidence e ON e.preparation_id=p.id "
            "WHERE r.id=%s AND r.generation_artifact_id=%s AND r.job_id=%s AND r.lease_generation=%s "
            "AND r.artifact_kind='validation' AND r.mode='live'",
            (validation_receipt_id, artifact_id, lease.job_id, lease.generation),
        ).fetchone()
        if row is None:
            raise LearningItemBankError("NATIVE_BANK_CURRENT_COMMITTED_VALIDATION_REQUIRED")
        return _check_validation_binding(generation, lease=lease, spec=spec, row=row)

    def import_candidate(self, *, lease: JobLeaseV1, artifact_id: UUID, validation_receipt_id: UUID,
                         spec: FiniteCandidateSpecV1, import_key: str) -> LearningItemImportResult:
        if not self.enabled or not self.settings.learning_item_supply_enabled:
            raise LearningItemBankError("NATIVE_BANK_IMPORT_DISABLED")
        self.artifacts.require_owner()
        lease, spec = checked_model(lease, JobLeaseV1), checked_model(spec, FiniteCandidateSpecV1)
        key = stable_key(import_key, label="native learning item import key")
        # A savepoint also rolls back content on the final current-source fence.
        # No commit: the operator owns the outer short transaction.
        with self.conn.transaction():
            data = self._load(lease=lease, artifact_id=artifact_id, validation_receipt_id=validation_receipt_id, spec=spec)
            result = self._persist(data, lease=lease, spec=spec, key=key)
            final = self._load(lease=lease, artifact_id=artifact_id, validation_receipt_id=validation_receipt_id, spec=spec)
            if final.validation != data.validation or final.generation.source != data.generation.source:
                raise LearningItemImportConflict("NATIVE_BANK_FINAL_BINDING_CHANGED")
            return result

    def _persist(self, data: _ValidatedNativeData, *, lease: JobLeaseV1,
                 spec: FiniteCandidateSpecV1, key: str) -> LearningItemImportResult:
        source, validation, row = data.generation.source, data.validation, data.row
        artifact_id = UUID(str(data.generation.artifact["id"]))
        creator = f"native.author.{data.generation.receipt.provider.run_id.hex}"
        request_hash = canonical_hash({"importer_version": NATIVE_IMPORTER_VERSION, "import_key": key,
            "generation_artifact_id": str(artifact_id), "shared_validation_receipt_id": str(row["id"]),
            "validation_evidence_id": str(row["evidence_id"]), "validation_hash": validation.evidence_hash,
            "specification_hash": spec.specification_hash, "source_hash": source.source_hash,
            "content_hash": source.content_hash, "creator_identity": creator})
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtext('learning-item-import'), hashtext(%s))", (key,))
        existing = self.conn.execute(
            "SELECT receipts.*,versions.item_id,versions.creator_identity,publications.id AS publication_event_id,"
            "publications.state AS publication_state,publications.state_version AS publication_state_version "
            "FROM tutor_learning_item_import_receipts receipts "
            "JOIN tutor_learning_item_versions versions ON versions.id=receipts.version_id "
            "JOIN LATERAL (SELECT id,state,state_version FROM tutor_learning_item_publication_events "
            "WHERE version_id=receipts.version_id ORDER BY state_version DESC LIMIT 1) publications ON true "
            "WHERE receipts.import_key=%s FOR UPDATE OF receipts", (key,),
        ).fetchone()
        if existing is not None:
            if (existing["request_hash"] != request_hash or existing["creator_identity"] != creator
                    or existing["importer_version"] != NATIVE_IMPORTER_VERSION
                    or existing["publication_state"] != "machine_verified"):
                raise LearningItemImportConflict("NATIVE_BANK_IMPORT_REPLAY_CONFLICT")
            return _import_result(existing, replayed=True)
        item_id, version_id = self.bank._ensure_immutable_content(source, creator_identity=creator)
        handle = learning_item_handle(source.public.item_key, source.public.version, source.content_hash)
        original_event_id = self._initial_event_for_recovery(data, version_id=version_id, handle=handle)
        # Validation payload hashes identify DATA, not the operation that produced
        # it. Static KC may have identical payloads in two current operations.
        shared_validation_id = UUID(str(row["id"]))
        validation_id = str(learning_item_uuid("import", f"native-validation:{shared_validation_id}"))
        self.conn.execute(
            "INSERT INTO tutor_learning_item_validation_receipts "
            "(id,version_id,item_handle,content_hash,schema_version,policy_version,compiler_version,receipt_json,receipt_hash,passed,"
            "native_generation_artifact_id,native_validation_receipt_id,native_validation_evidence_id,"
            "native_specification_hash,native_import_lease_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s) "
            "ON CONFLICT(native_validation_receipt_id) WHERE schema_version='candidate_validation_v2' DO NOTHING",
            (validation_id, version_id, handle, source.content_hash, validation.schema_version, NATIVE_VALIDATION_POLICY,
             LEARNING_ITEM_COMPILER_VERSION, Jsonb(validation.model_dump(mode="json")), validation.evidence_hash,
             artifact_id, row["id"], row["evidence_id"], spec.specification_hash, Jsonb(lease.model_dump(mode="json"))),
        )
        stored = self.conn.execute(
            "SELECT id,version_id,receipt_hash,native_validation_receipt_id,native_generation_artifact_id,"
            "native_validation_evidence_id,native_specification_hash FROM tutor_learning_item_validation_receipts "
            "WHERE native_validation_receipt_id=%s AND schema_version='candidate_validation_v2'",
            (shared_validation_id,),
        ).fetchone()
        if (stored is None or str(stored["id"]) != validation_id or stored["receipt_hash"] != validation.evidence_hash
                or str(stored["version_id"]) != version_id
                or UUID(str(stored["native_validation_receipt_id"])) != shared_validation_id
                or UUID(str(stored["native_generation_artifact_id"])) != artifact_id
                or UUID(str(stored["native_validation_evidence_id"])) != UUID(str(row["evidence_id"]))
                or stored["native_specification_hash"] != spec.specification_hash):
            raise LearningItemImportConflict("NATIVE_BANK_VALIDATION_IMMUTABLE_CONFLICT")
        now = server_clock(self.conn, datetime.now(UTC))
        event_id = original_event_id or self.bank._ensure_initial_publication(version_id=version_id, handle=handle,
            content_hash=source.content_hash, validation_hash=validation.evidence_hash,
            policy_version=NATIVE_VALIDATION_POLICY, validation_id=validation_id, import_key=key, occurred_at=now)
        import_id = str(learning_item_uuid("import", key))
        # Native source_path is a logical DB snapshot locator, never a Git file.
        # Its source_file_hash hashes those exact canonical stored source bytes.
        inserted = self.conn.execute(
            "INSERT INTO tutor_learning_item_import_receipts "
            "(id,version_id,validation_receipt_id,initial_publication_event_id,import_key,source_path,source_file_hash,"
            "source_hash,content_hash,item_handle,request_hash,importer_version,imported_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(import_key) DO NOTHING RETURNING id",
            (import_id, version_id, validation_id, event_id, key, f"native/shared-generation/{artifact_id}.json",
             source.source_hash, source.source_hash, source.content_hash, handle, request_hash, NATIVE_IMPORTER_VERSION, now),
        ).fetchone()
        if inserted is None:
            raise LearningItemImportConflict("NATIVE_BANK_IMPORT_CONFLICT")
        return LearningItemImportResult(item_id, version_id, handle, source.content_hash, validation_id,
                                        import_id, event_id, "machine_verified", 1, False)

    def _initial_event_for_recovery(
        self, data: _ValidatedNativeData, *, version_id: str, handle: str,
    ) -> str | None:
        """Reuse only the original, still-unpublished native initial authority.

        Lock the immutable version as publication writers do. A new operation
        appends its own validation/import receipt, never rewrites the first event
        or pretends the fresh validation authorized that historical event.
        """
        self.conn.execute("SELECT id FROM tutor_learning_item_versions WHERE id=%s FOR UPDATE", (version_id,))
        event = self.conn.execute(
            "SELECT events.id,events.version_id,events.item_handle,events.content_hash,events.state,events.state_version,"
            "events.predecessor_event_id,events.authority_kind,events.authority_hash,events.policy_version,"
            "validation.schema_version,validation.passed,validation.receipt_hash,"
            "validation.native_generation_artifact_id,validation.receipt_json->>'source_hash' AS validation_source_hash,"
            "EXISTS(SELECT 1 FROM tutor_learning_item_import_receipts imports "
            "WHERE imports.version_id=events.version_id AND imports.initial_publication_event_id=events.id "
            "AND imports.validation_receipt_id=validation.id AND imports.importer_version=%s "
            "AND imports.source_hash=%s AND imports.content_hash=%s) AS initial_native_import "
            "FROM tutor_learning_item_publication_events events "
            "LEFT JOIN tutor_learning_item_validation_receipts validation ON validation.id=events.authority_reference_id "
            "AND validation.version_id=events.version_id "
            "WHERE events.version_id=%s ORDER BY events.state_version DESC LIMIT 1",
            (NATIVE_IMPORTER_VERSION, data.generation.source.source_hash, data.generation.source.content_hash, version_id),
        ).fetchone()
        if event is None:
            return None
        if (str(event["version_id"]) != version_id or event["item_handle"] != handle
                or event["content_hash"] != data.generation.source.content_hash
                or event["state"] != "machine_verified" or event["state_version"] != 1
                or event["predecessor_event_id"] is not None or event["authority_kind"] != "validation"
                or event["schema_version"] != "candidate_validation_v2" or event["passed"] is not None
                or event["policy_version"] != NATIVE_VALIDATION_POLICY
                or event["authority_hash"] != event["receipt_hash"]
                or str(event["native_generation_artifact_id"]) != str(data.generation.artifact["id"])
                or event["validation_source_hash"] != data.generation.source.source_hash
                or event["initial_native_import"] is not True):
            raise LearningItemImportConflict("NATIVE_BANK_UNPUBLISHED_RECOVERY_REQUIRED")
        return str(event["id"])
