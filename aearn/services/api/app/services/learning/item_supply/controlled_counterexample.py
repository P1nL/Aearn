"""Default-off ORIGINAL SharedGeneration issuer for one marked counterexample."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4
from psycopg.types.json import Jsonb
from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.controlled_counterexample_contracts import (
    ControlledAuthorTrace, ControlledCounterexampleContext, PreparedControlledCounterexample, checked_controlled_context,
)
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationResultV2, SourceReceiptV2
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.storage_contracts import checked_model
if TYPE_CHECKING:
    from app.services.learning.item_supply.controlled_case_execution import ControlledCaseExecutionOwner, IssuedControlledCaseExecution
    from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
    from app.services.learning.item_supply.shared_pipeline_contracts import PreparedSharedGeneration


class ControlledCounterexampleOwner:
    def __init__(self, generation: SharedGenerationPipeline, *, enabled: bool = False) -> None:
        self.generation, self.conn, self.enabled = generation,generation.conn,enabled
        self._prepared: dict[UUID,tuple[PreparedControlledCounterexample,str,Any,Any]] = {}
        self._generations: dict[UUID,tuple[PreparedSharedGeneration,PreparedControlledCounterexample,ControlledAuthorTrace]] = {}
        self._runs: dict[UUID,tuple[GenerationResultV2,str]] = {}
        self._executions: dict[UUID,tuple[ControlledCaseExecutionOwner,IssuedControlledCaseExecution]] = {}

    def _guard(self) -> datetime:
        from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
        if type(self.generation) is not SharedGenerationPipeline or not self.enabled or not self.generation.generation_enabled:
            raise PipelineRepositoryError("CONTROLLED_COUNTEREXAMPLE_DISABLED")
        self.generation.artifacts.require_owner()
        row = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_controlled_counterexample_preparations') AS p, "
            "to_regclass('public.tutor_item_supply_shared_controlled_counterexample_receipts') AS r, "
            "to_regprocedure('item_supply_internal.controlled_counterexample_held(uuid)') AS g").fetchone()
        if row is None or any(row[k] is None for k in ("p","r","g")):
            raise PipelineRepositoryError("CONTROLLED_COUNTEREXAMPLE_511_REQUIRED")
        return server_clock(self.conn,datetime.now(timezone.utc))

    def prepare(self, *, lease: Any, request: GenerationRequestV2, context: ControlledCounterexampleContext,
                provider: Any, source_authority: Any, evidence_policy: Any,
                execution_owner: ControlledCaseExecutionOwner | None = None,
                execution: IssuedControlledCaseExecution | None = None) -> PreparedControlledCounterexample:
        now = self._guard()
        context = checked_controlled_context(context)
        context.check_request(request)
        if execution_owner is not None or execution is not None:
            from app.services.learning.item_supply.controlled_case_execution import ControlledCaseExecutionOwner, IssuedControlledCaseExecution
            if (type(execution_owner) is not ControlledCaseExecutionOwner or type(execution) is not IssuedControlledCaseExecution
                    or execution_owner.conn is not self.conn):
                raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_ORIGINAL_OWNER_PAIR_REQUIRED")
            execution_owner.verify(execution,lease=lease,context=context,candidate_id=request.candidate_id,now=now)
        if lease.visibility != "public" or lease.owner_id is not None or lease.owner_epoch is not None:
            raise PipelineRepositoryError("CONTROLLED_PUBLIC_ORIGINAL_LEASE_REQUIRED")
        settings = self.generation.settings
        if (not settings.uses_deepseek_v4_flash_responses or settings.tutor_max_output_tokens != DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
                or provider.request_attempt_bound != 1 or provider._settings != settings):
            raise PipelineRepositoryError("CONTROLLED_ONE_FORMAL_ORIGINAL_AUTHOR_REQUIRED")
        binding = self.generation._binding(lease,request,provider,now=now)
        self.generation.artifacts.require_source(source_authority)
        if self.generation.runtime.next_stage(lease) != "generating":
            raise PipelineRepositoryError("CONTROLLED_ORIGINAL_GENERATING_REQUIRED")
        meta = self.generation.artifacts.request_context(lease,request,now=now)
        # Reuse current accounting only when original effective usage leaves the
        # full bounded experiment capacity; never reset or enlarge old limits.
        caps = dict(requests=17,input_tokens=4194304,output_tokens=17*DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS,
            execution_seconds=1,fetches=1,candidates=2,revision_rounds=1,investigation_rounds=1)
        from app.services.learning.item_supply.development_model_accounting import accounting_batch_for_lease
        development = accounting_batch_for_lease(self.conn, lease, now=now)
        limit_filter, limit_params = "", ()
        if development is not None:
            limit_filter, limit_params = " AND id=ANY(%s::uuid[])", (development["global_limit_ids"],)
        elif self.generation.budget._development_accounting_available():
            limit_filter = " AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_development_model_accounting_batches dev WHERE tutor_item_supply_runtime_global_limits.id=ANY(dev.global_limit_ids))"
        limits = self.conn.execute("SELECT * FROM tutor_item_supply_runtime_global_limits WHERE window_start<=%s AND window_end>%s "
            "AND ((dimension_kind='system' AND dimension_key='item-supply') OR (dimension_kind='window' AND dimension_key='item-supply') "
            "OR (dimension_kind='pool' AND dimension_key='base') OR (dimension_kind='provider' AND dimension_key=%s))" + limit_filter + " FOR SHARE",
            (now,now,binding[0]) + limit_params).fetchall()
        dims = {("system","item-supply"),("window","item-supply"),("pool","base"),("provider",binding[0])}
        if (len(limits)!=32 or {(r["dimension_kind"],r["dimension_key"],r["resource_kind"]) for r in limits}
                != {(d,k,t) for d,k in dims for t in caps}
                or (development is None and any(self.generation.budget._global_used(r["id"],r["resource_kind"])
                    + caps[r["resource_kind"]] > r["cap_amount"] for r in limits))):
            raise PipelineRepositoryError("CONTROLLED_CURRENT_PERIOD_CAPACITY_REQUIRED")
        sources = tuple(checked_model(source_authority.authorize(m),SourceReceiptV2) for m in request.materials)
        deadlines = [lease.expires_at,lease.parent_deadline,lease.profile.parent_deadline_at,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms)]
        if execution is not None:
            deadlines.append(execution.deadline_at)
        for material in request.materials:
            coordinate = material.binding.evidence[0].binding
            source_reviews = source_authority._current.governance.source_reviews
            review = None if source_reviews is None else source_reviews.resolve(coordinate.source_handle,coordinate.document_handle)
            claim = material.exact_claims[0]
            evidence = self.conn.execute("SELECT ev.expires_at FROM rag_source_claim_receipts cr JOIN rag_assessment_source_evidence ev "
                "ON ev.id=cr.assessment_evidence_id WHERE cr.receipt_handle=%s AND cr.claim_hash=%s "
                "AND cr.revoked_at IS NULL AND ev.revoked_at IS NULL",(claim.claim_receipt_id,claim.claim_hash)).fetchall()
            if review is None or review.grant is None or len(evidence)!=1 or evidence[0]["expires_at"] is None:
                raise PipelineRepositoryError("CONTROLLED_CURRENT_SOURCE_LIFETIME_REQUIRED")
            deadlines.extend((review.grant.retained_until,evidence[0]["expires_at"]))
        policy = self.generation.artifacts.freeze_generation_policy(lease,request,policy=evidence_policy,now=now)
        p = PreparedControlledCounterexample(uuid4(),UUID(str(meta["root_id"])),lease,request,context,sources,binding,policy.policy_hash,min(deadlines))
        if p.deadline_at <= now or any(s.mode!="current_authority" for s in sources):
            raise PipelineRepositoryError("CONTROLLED_CURRENT_SOURCE_DEADLINE_REQUIRED")
        if execution is None:
            self.conn.execute("INSERT INTO tutor_item_supply_shared_controlled_counterexample_preparations "
                "(id,experiment_key,root_id,job_id,candidate_id,lease_owner,lease_generation,lease_state_version,payload_json,valid_until) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(p.preparation_id,context.experiment_key,p.root_id,lease.job_id,
                request.candidate_id,lease.lease_owner,lease.generation,lease.state_version,Jsonb(p.payload()),p.deadline_at))
        else:
            assert execution_owner is not None
            self.conn.execute("INSERT INTO tutor_item_supply_shared_controlled_execution_preparations "
                "(id,execution_id,experiment_key,root_id,job_id,candidate_id,lease_owner,lease_generation,lease_state_version,payload_json,valid_until) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(p.preparation_id,execution.execution_id,context.experiment_key,
                p.root_id,lease.job_id,request.candidate_id,lease.lease_owner,lease.generation,lease.state_version,Jsonb(p.payload()),p.deadline_at))
            execution_owner.attach(execution,p.preparation_id)
            self._executions[p.preparation_id] = (execution_owner,execution)
        self._prepared[p.preparation_id] = (p,canonical_hash(p.payload()),source_authority,provider)
        return p

    def issued(self, p: PreparedControlledCounterexample) -> tuple[Any,Any]:
        entry = self._prepared.get(p.preparation_id)
        if type(p) is not PreparedControlledCounterexample or entry is None or entry[0] is not p or entry[1]!=canonical_hash(p.payload()):
            raise PipelineRepositoryError("CONTROLLED_ORIGINAL_PREPARED_REQUIRED")
        p.context.check_request(p.request)
        execution = self._executions.get(p.preparation_id)
        if execution is not None:
            if execution[0].conn is not self.conn:
                raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_SAME_CONNECTION_REQUIRED")
            execution[0].verify_identity(execution[1],lease=p.lease,context=p.context,candidate_id=p.request.candidate_id,
                preparation_id=p.preparation_id)
        return entry[2],entry[3]

    def _tables(self, p: PreparedControlledCounterexample) -> tuple[str,str]:
        # Only an original in-process prepared object selects the parallel branch.
        if p.preparation_id in self._executions:
            return ("tutor_item_supply_shared_controlled_execution_preparations",
                "tutor_item_supply_shared_controlled_execution_receipts")
        return ("tutor_item_supply_shared_controlled_counterexample_preparations",
            "tutor_item_supply_shared_controlled_counterexample_receipts")

    def fence(self, p: PreparedControlledCounterexample) -> None:
        authority,provider = self.issued(p)
        now = self._guard()
        execution = self._executions.get(p.preparation_id)
        if execution is not None:
            execution[0].verify(execution[1],lease=p.lease,context=p.context,candidate_id=p.request.candidate_id,
                now=now,preparation_id=p.preparation_id)
        if (provider.request_attempt_bound!=1 or provider._settings!=self.generation.settings
                or not self.generation.settings.uses_deepseek_v4_flash_responses
                or self.generation.settings.tutor_max_output_tokens!=DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS):
            raise PipelineRepositoryError("CONTROLLED_ONE_FORMAL_ORIGINAL_AUTHOR_REQUIRED")
        preparation_table,_ = self._tables(p)
        row = self.conn.execute("SELECT p.*,p.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            f"FROM {preparation_table} p WHERE p.id=%s FOR SHARE",(p.preparation_id,)).fetchone()
        if (row is None or row["same_transaction"] or row["snapshot_hash"]!=canonical_hash(p.payload())
                or row["payload_json"]!=p.payload() or now>=p.deadline_at
                or self.generation._binding(p.lease,p.request,provider,now=now)!=p.producer_binding
                or self.generation.runtime.next_stage(p.lease)!="generating"):
            raise PipelineRepositoryError("CONTROLLED_COMMITTED_CURRENT_PREPARATION_REQUIRED")
        for material,receipt in zip(p.request.materials,p.sources,strict=True):
            authority.assert_current(material,receipt)

    def attach(self, gen: PreparedSharedGeneration, p: PreparedControlledCounterexample) -> None:
        self.issued(p)
        if (gen.request!=p.request or gen.lease!=p.lease or gen.sources!=p.sources or gen.producer_binding!=p.producer_binding
                or gen.evidence_policy_hash!=p.evidence_policy_hash or gen.attempt_bound!=1):
            raise PipelineRepositoryError("CONTROLLED_ORIGINAL_GENERATION_MISMATCH")
        self._generations[gen.reservation_id] = (gen,p,ControlledAuthorTrace(p.context))

    def original_generation(self, gen: PreparedSharedGeneration) -> tuple[PreparedControlledCounterexample,ControlledAuthorTrace]:
        entry = self._generations.get(gen.reservation_id)
        if entry is None or entry[0] is not gen:
            raise PipelineRepositoryError("CONTROLLED_ORIGINAL_GENERATION_REQUIRED")
        self.issued(entry[1])
        if entry[2].context is not entry[1].context:
            raise PipelineRepositoryError("CONTROLLED_ORIGINAL_CONTEXT_CHANGED")
        return entry[1],entry[2]

    def observe_result(self, gen: PreparedSharedGeneration, result: GenerationResultV2) -> None:
        self.original_generation(gen)
        self._runs[gen.reservation_id] = (result,canonical_hash(result.model_dump(mode="json")))

    def verify_result(self, gen: PreparedSharedGeneration, result: GenerationResultV2) -> None:
        self.original_generation(gen)
        entry = self._runs.get(gen.reservation_id)
        if entry is None or entry[0] is not result or entry[1]!=canonical_hash(result.model_dump(mode="json")):
            raise PipelineRepositoryError("CONTROLLED_ORIGINAL_RESULT_REQUIRED")

    def persist_author_trace(self, gen: PreparedSharedGeneration, result: GenerationResultV2) -> UUID:
        p,trace = self.original_generation(gen)
        self.generation._result(gen,result)
        self.fence(p)
        self.generation.artifacts.reservation(gen.lease,gen.request,attempts=1,settled=True)
        if trace.binding is None or trace.envelope is None:
            raise PipelineRepositoryError("CONTROLLED_ACTUAL_AUTHOR_ENVELOPE_PENDING")
        if (trace.binding.request_hash!=canonical_hash(p.request.model_dump(mode="json"))
                or trace.binding.context_hash!=p.context.context_hash or trace.binding.envelope_hash!=canonical_hash(trace.envelope)):
            raise PipelineRepositoryError("CONTROLLED_ACTUAL_AUTHOR_ENVELOPE_CHANGED")
        if result.source is not None:
            p.context.check_source(result.source)
        usage = self.conn.execute("SELECT * FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=%s "
            "AND settlement_key=%s",(gen.reservation_id,"generation."+gen.request.candidate_id.hex)).fetchone()
        if usage is None:
            raise PipelineRepositoryError("CONTROLLED_AUTHOR_SETTLEMENT_REQUIRED")
        payload = {"schema_version":"controlled_counterexample_author_receipt_v1","preparation_id":str(p.preparation_id),
            "preparation_hash":canonical_hash(p.payload()),"request_hash":trace.binding.request_hash,"context_hash":p.context.context_hash,
            "lease":gen.lease.model_dump(mode="json"),"binding":trace.binding.model_dump(mode="json"),"actual_envelope":trace.envelope,
            "result":result.model_dump(mode="json"),"result_hash":canonical_hash(result.model_dump(mode="json")),
            "reservation_id":str(gen.reservation_id),"settlement_id":str(usage["id"]),"usage_state":usage["usage_state"],
            "publication_enabled":False,"admission_eligible":False}
        _,receipt_table = self._tables(p)
        self.conn.execute(f"INSERT INTO {receipt_table} "
            "(id,preparation_id,root_id,job_id,candidate_id,reservation_id,settlement_id,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (p.preparation_id,p.preparation_id,p.root_id,gen.lease.job_id,gen.request.candidate_id,gen.reservation_id,usage["id"],Jsonb(payload))).fetchone()
        return p.preparation_id

    def writer_binding(self, gen: PreparedSharedGeneration, result: GenerationResultV2) -> None:
        p,trace = self.original_generation(gen)
        self.generation._result(gen,result)
        self.fence(p)
        if result.source is None:
            raise PipelineRepositoryError("CONTROLLED_ORIGINAL_SOURCE_PENDING")
        p.context.check_source(result.source)
        _,receipt_table = self._tables(p)
        row = self.conn.execute("SELECT r.*,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            f"FROM {receipt_table} r WHERE r.preparation_id=%s FOR SHARE",(p.preparation_id,)).fetchone()
        if (row is None or row["same_transaction"] or trace.binding is None
                or trace.envelope is None or trace.binding.envelope_hash!=canonical_hash(trace.envelope)
                or canonical_hash(row["payload_json"]["actual_envelope"])!=canonical_hash(trace.envelope)
                or row["payload_json"]["result_hash"]!=canonical_hash(result.model_dump(mode="json"))
                or row["payload_json"]["binding"]!=trace.binding.model_dump(mode="json")
                or row["reservation_id"]!=gen.reservation_id):
            raise PipelineRepositoryError("CONTROLLED_COMMITTED_ORIGINAL_AUTHOR_TRACE_REQUIRED")
