"""Normal revision output DATA and a distinct, persistence-only issuer.

No provider/reservation/settlement replay and no hydration of author capabilities.
Callers commit settlement/output, artifact/checkpoint, and lineage separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.native_revision_contracts import NativeRevisionAuthorInputBindingV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.review_deliberation import substantive_revision_hash
from app.services.learning.item_supply.shared_pipeline_contracts import (
    GenerationSettlementOutcome, PreparedSharedGeneration, SharedPipelineStageResult,
)

if TYPE_CHECKING:
    from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline


@dataclass(frozen=True, repr=False)
class IssuedRevisionGenerationPersistence:
    owner: RevisionGenerationDurability
    preparation_id: UUID
    snapshot_hash: str
    request: GenerationRequestV2
    result: GenerationResultV2
    source_authority: RagSourceAuthority


class RevisionGenerationDurability:
    def __init__(self, generation: SharedGenerationPipeline) -> None:
        self.generation = generation
        self.conn = generation.conn
        self._issued: dict[UUID, IssuedRevisionGenerationPersistence] = {}
        self._artifact_observations: dict[UUID, tuple[IssuedRevisionGenerationPersistence, int, UUID, str]] = {}

    def required(self, prepared: PreparedSharedGeneration) -> bool:
        from app.services.learning.item_supply.persistent_pack_committed_revision import CommittedInvestigationEvidence
        revision = self.generation._revision.get(prepared.reservation_id)
        if revision is None:
            return False
        investigation = revision[1].investigation
        return (isinstance(investigation, CommittedInvestigationEvidence)
                or investigation.original.persistent_committed_frame is not None)

    def capture(self, prepared: PreparedSharedGeneration, result: GenerationResultV2) -> GenerationSettlementOutcome:
        """Settlement already succeeded. Isolate ONLY the output append in a savepoint."""
        gp = self.generation
        if not self.required(prepared) or prepared.reservation_id not in gp._observed_revision_outputs:
            return GenerationSettlementOutcome("not_applicable", "generation_settled")
        try:
            with self.conn.transaction():
                gp._result(prepared, result)
                observed, seal = gp._observed_revision_outputs[prepared.reservation_id]
                if prepared.reservation_id not in gp._started or seal != canonical_hash(observed.model_dump(mode="json")):
                    raise PipelineRepositoryError("GENERATION_OBSERVED_OUTPUT_CHANGED")
                binding = gp.revision_author_binding(prepared, result)
                revision = gp._revision[prepared.reservation_id][1]
                p = self.conn.execute("SELECT * FROM tutor_item_supply_shared_revision_preparations WHERE id=%s FOR SHARE",
                    (revision.preparation_id,)).fetchone()
                s = self.conn.execute("SELECT * FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=%s AND settlement_key=%s",
                    (prepared.reservation_id, "generation." + prepared.request.candidate_id.hex)).fetchone()
                if p is None or s is None:
                    raise PipelineRepositoryError("GENERATION_DURABLE_PARENT_MISSING")
                payload = dict(schema_version="normal_revision_generation_output_v1",
                    preparation_id=str(revision.preparation_id), preparation_hash=p["snapshot_hash"],
                    lease=prepared.lease.model_dump(mode="json"), request=prepared.request.model_dump(mode="json"),
                    request_hash=canonical_hash(prepared.request.model_dump(mode="json")),
                    result=observed.model_dump(mode="json"), returned_state=result.state, returned_safe_reason=result.safe_reason,
                    author_input=binding.model_dump(mode="json"), evidence_policy_hash=prepared.evidence_policy_hash,
                    producer_binding=list(prepared.producer_binding), deadline_at=p["payload_json"]["deadline_at"])
                row = self.conn.execute("INSERT INTO tutor_item_supply_shared_revision_generation_outputs "
                    "(preparation_id,root_id,job_id,candidate_id,reservation_id,settlement_id,payload_json) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(preparation_id) DO NOTHING RETURNING snapshot_hash",
                    (revision.preparation_id,p["root_id"],prepared.lease.job_id,prepared.request.candidate_id,
                     prepared.reservation_id,s["id"],Jsonb(payload))).fetchone()
                if row is None:
                    row = self.conn.execute("SELECT snapshot_hash FROM tutor_item_supply_shared_revision_generation_outputs WHERE preparation_id=%s",
                        (revision.preparation_id,)).fetchone()
                if row is None or row["snapshot_hash"] != canonical_hash(payload):
                    raise PipelineRepositoryError("GENERATION_DURABLE_OUTPUT_CONFLICT")
        except Exception:
            # Caller MUST commit the outer settlement transaction, then stop.
            # No failed journal append can pretend that paid usage was zero.
            return GenerationSettlementOutcome("settled_only", "generation_output_not_durable_settlement_retained")
        return GenerationSettlementOutcome("durable", "generation_output_durable")

    def committed_output(self, preparation_id: UUID) -> dict[str, Any]:
        self.generation.artifacts.require_owner()
        row = self.conn.execute("SELECT o.*,o.capture_txid=txid_current() AS same_transaction "
            "FROM tutor_item_supply_shared_revision_generation_outputs o WHERE preparation_id=%s FOR SHARE", (preparation_id,)).fetchone()
        if row is None:
            raise PipelineRepositoryError("GENERATION_DURABLE_BINDING_MISSING")
        if row["same_transaction"]:
            raise PipelineRepositoryError("GENERATION_DURABLE_BINDING_NOT_COMMITTED")
        if row["snapshot_hash"] != canonical_hash(row["payload_json"]):
            raise PipelineRepositoryError("GENERATION_DURABLE_BINDING_CHANGED")
        return row

    def prepare(self, preparation_id: UUID, *, source_authority: RagSourceAuthority) -> IssuedRevisionGenerationPersistence:
        self._transaction_id()
        row = self.committed_output(preparation_id)
        d = row["payload_json"]
        cap = IssuedRevisionGenerationPersistence(self, preparation_id, row["snapshot_hash"],
            GenerationRequestV2.model_validate_json(json.dumps(d["request"])),
            GenerationResultV2.model_validate_json(json.dumps(d["result"])), source_authority)
        output,_,lease = self._current(cap)
        self._issued[preparation_id] = cap
        self._artifact_observations.pop(preparation_id, None)
        self._observe_artifact(cap, output, lease)
        return cap

    def _current(self, cap: IssuedRevisionGenerationPersistence) -> tuple[dict[str, Any], dict[str, Any], JobLeaseV1]:
        gp = self.generation
        if not gp.enabled or not gp.settings.learning_item_supply_enabled or not gp.settings.learning_item_generation_enabled:
            raise PipelineRepositoryError("GENERATION_PERSISTENCE_DISABLED")
        gp.artifacts.require_source(cap.source_authority)
        row = self.committed_output(cap.preparation_id)
        d = row["payload_json"]
        if (row["snapshot_hash"] != cap.snapshot_hash or d["request"] != cap.request.model_dump(mode="json")
                or d["result"] != cap.result.model_dump(mode="json") or d["returned_state"] != "staged"
                or cap.result.source is None or cap.result.receipt is None):
            raise PipelineRepositoryError("GENERATION_DURABLE_BINDING_CHANGED")
        self.conn.execute("SELECT item_supply_internal.assert_revision_generation_output_current(%s)", (cap.preparation_id,))
        p = self.conn.execute("SELECT * FROM tutor_item_supply_shared_revision_preparations WHERE id=%s FOR SHARE", (cap.preparation_id,)).fetchone()
        if p is None or p["snapshot_hash"] != d["preparation_hash"]:
            raise PipelineRepositoryError("GENERATION_DURABLE_PARENT_CHANGED")
        binding = NativeRevisionAuthorInputBindingV1.model_validate_json(json.dumps(d["author_input"]))
        if binding.request_hash != canonical_hash(d["request"]) or binding.context_hash != p["payload_json"]["context_hash"]:
            raise PipelineRepositoryError("REVISION_ACTUAL_AUTHOR_CONTEXT_REQUIRED")
        if substantive_revision_hash(cap.result.source) == p["payload_json"]["parent_substantive_hash"]:
            raise PipelineRepositoryError("REVISION_SUBSTANTIVE_NEW_CONTENT_REQUIRED")
        frozen = JobLeaseV1.model_validate_json(json.dumps(d["lease"]))
        lease = gp.runtime.refresh_lease(frozen, now=datetime.now(UTC))
        meta = gp.artifacts.request_context(lease, cap.request, now=datetime.now(UTC))
        key = meta["key"]
        provider = cap.result.receipt.provider
        if (provider.provider != meta["provider_key"] or provider.model != provider.configured_model
                or provider.configured_model != gp._models.get((key.provider,key.model_version))
                or d["producer_binding"] != [provider.provider,provider.configured_model]
                or gp.artifacts.generation_policy(lease,cap.request,now=datetime.now(UTC)).policy_hash != d["evidence_policy_hash"]):
            raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
        for material, expected in zip(cap.request.materials,cap.result.receipt.sources,strict=True):
            cap.source_authority.assert_current(material,expected)
        if gp.artifacts.reservation(lease,cap.request,attempts=provider.request_attempt_bound,settled=True) != row["reservation_id"]:
            raise PipelineRepositoryError("SHARED_GENERATION_RESERVATION_MISMATCH")
        return row,p,lease

    def verify(self, cap: IssuedRevisionGenerationPersistence) -> tuple[dict[str, Any], dict[str, Any], JobLeaseV1]:
        if type(cap) is not IssuedRevisionGenerationPersistence or cap.owner is not self or self._issued.get(cap.preparation_id) is not cap:
            raise PipelineRepositoryError("GENERATION_PERSISTENCE_ISSUER_REQUIRED")
        return self._current(cap)

    def _transaction_id(self) -> int:
        if self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise PipelineRepositoryError("GENERATION_PERSISTENCE_TRANSACTION_REQUIRED")
        row = self.conn.execute("SELECT txid_current() AS top_txid").fetchone()
        if row is None:
            raise PipelineRepositoryError("GENERATION_PERSISTENCE_TRANSACTION_REQUIRED")
        return int(row["top_txid"])

    def _artifact(self, cap: IssuedRevisionGenerationPersistence, output: dict[str, Any], lease: JobLeaseV1) -> dict[str, Any] | None:
        assert cap.result.source is not None and cap.result.receipt is not None
        a = self.conn.execute("SELECT a.* FROM tutor_item_supply_shared_generation_artifacts a "
            "WHERE job_id=%s AND candidate_id=%s FOR SHARE", (lease.job_id,cap.request.candidate_id)).fetchone()
        if a is None:
            return None
        if (a["reservation_id"] != output["reservation_id"]
                or a["source_json"] != cap.result.source.model_dump(mode="json")
                or a["receipt_json"] != cap.result.receipt.model_dump(mode="json") or a["request_json"] != cap.request.model_dump(mode="json")
                or a["artifact_hash"] != canonical_hash(dict(source=a["source_json"],receipt=a["receipt_json"],request=a["request_json"]))):
            raise PipelineRepositoryError("REVISION_ORIGINAL_COMMITTED_GENERATION_REQUIRED")
        if self.conn.execute("SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=%s AND stage='generating' "
                "AND status='completed' AND receipt_hash=%s",(lease.job_id,a["artifact_hash"])).fetchone() is None:
            return None
        return a

    def _observe_artifact(self, cap: IssuedRevisionGenerationPersistence, output: dict[str, Any], lease: JobLeaseV1) -> None:
        a = self._artifact(cap, output, lease)
        if a is not None:
            self._artifact_observations[cap.preparation_id] = (cap,self._transaction_id(),UUID(str(a["id"])),a["artifact_hash"])

    def commit(self, cap: IssuedRevisionGenerationPersistence) -> SharedPipelineStageResult:
        self._transaction_id()
        output,_,lease = self.verify(cap)
        gp = self.generation
        row = gp.artifacts.store_generation(lease=lease,request=cap.request,result=cap.result,
            artifact_key="generation."+cap.request.candidate_id.hex,now=datetime.now(UTC),
            source_authority=cap.source_authority,persistence=cap)
        checkpoint = self.conn.execute("SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=%s "
            "AND stage='generating' AND status='completed' AND receipt_hash=%s",(lease.job_id,row["artifact_hash"])).fetchone()
        if checkpoint is None:
            control = gp.runtime._control(lease,now=datetime.now(UTC))
            gp.runtime.checkpoint(lease,CheckpointV1(stage="generating",attempt=control["attempt_count"],
                status="completed",receipt_hash=row["artifact_hash"],safe_reason="candidate_staged"),now=datetime.now(UTC))
        self._observe_artifact(cap, output, lease)
        return SharedPipelineStageResult("staged","candidate_staged",UUID(str(row["id"])))

    def lineage(self, cap: IssuedRevisionGenerationPersistence) -> UUID:
        top_txid = self._transaction_id()
        output,p,lease = self.verify(cap)
        assert cap.result.source is not None and cap.result.receipt is not None
        observed = self._artifact_observations.get(cap.preparation_id)
        if observed is None or observed[0] is not cap or observed[1] == top_txid:
            raise PipelineRepositoryError("REVISION_ORIGINAL_COMMITTED_GENERATION_REQUIRED")
        a = self._artifact(cap, output, lease)
        if a is None or (UUID(str(a["id"])),a["artifact_hash"]) != observed[2:]:
            raise PipelineRepositoryError("REVISION_ORIGINAL_COMMITTED_GENERATION_REQUIRED")
        # The immutable settlement is already referenced by the committed output.
        # A subtransaction xmin alone cannot establish a separate TOP commit.
        s = self.conn.execute("SELECT s.* "
            "FROM tutor_item_supply_shared_runtime_settlements s WHERE id=%s",(output["settlement_id"],)).fetchone()
        if s is None or s["reservation_id"] != output["reservation_id"]:
            raise PipelineRepositoryError("REVISION_COMMITTED_AUTHOR_SETTLEMENT_REQUIRED")
        payload = dict(schema_version="native_shared_revision_lineage_v1",preparation_id=str(p["id"]),
            preparation_hash=p["snapshot_hash"],root_id=str(p["root_id"]),lease=lease.model_dump(mode="json"),
            parent_artifact_id=str(p["parent_artifact_id"]),child_artifact_id=str(a["id"]),child_artifact_hash=a["artifact_hash"],
            context_hash=p["payload_json"]["context_hash"],author_input=output["payload_json"]["author_input"],
            provider_receipt_hash=canonical_hash(cap.result.receipt.provider.model_dump(mode="json")),
            reservation_id=str(output["reservation_id"]),settlement_id=str(s["id"]),usage_state=s["usage_state"],
            child_substantive_hash=substantive_revision_hash(cap.result.source),publication_enabled=False,blockers_discharged=False,admission_eligible=False)
        prior = self.conn.execute("SELECT * FROM tutor_item_supply_shared_revision_lineage WHERE preparation_id=%s FOR SHARE",(p["id"],)).fetchone()
        if prior is not None:
            if any(prior["payload_json"].get(k) != v for k,v in payload.items() if k != "lease"):
                raise PipelineRepositoryError("GENERATION_PERSISTENCE_LINEAGE_CONFLICT")
            return UUID(str(prior["id"]))
        self.conn.execute("INSERT INTO tutor_item_supply_shared_revision_lineage "
            "(id,preparation_id,root_id,parent_artifact_id,child_artifact_id,child_job_id,reservation_id,settlement_id,payload_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",(p["id"],p["id"],p["root_id"],p["parent_artifact_id"],a["id"],lease.job_id,
                output["reservation_id"],s["id"],Jsonb(payload)))
        return UUID(str(p["id"]))
