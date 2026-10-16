"""Fixed-case evidence for one original revision; never restores investigation IO."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import TYPE_CHECKING, Any, NoReturn
from uuid import UUID
from psycopg.pq import TransactionStatus
from psycopg.transaction import Transaction
from psycopg.types.json import Jsonb
from app.services.learning.item_bank.contracts import LearningItemReviewRole, LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.diagnostic_policy import parse_bundle
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef, PersistentPublicPhaseRecord, PersistentPublicVersionRecord
from app.services.learning.item_supply.persistent_pack_repair import PersistentCloneFindingV1, PersistentInvestigationInputV1, PersistentInvestigationReportV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.public_normal_source_ingress import PUBLIC_NORMAL_RECEIVER_PINS
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2, ProviderIdentityV2, ReviewInputV2
from app.services.learning.item_supply.review_deliberation import review_disputes
from app.services.learning.item_supply.review_protocol import make_review_request, report_protocol, verify_review_report
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_source_successor import IssuedSourceMappingSuccessor
    from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
    from app.services.learning.item_supply.native_revision import NativeRevisionOwner, PreparedNativeRevision
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_fresh_committed_revision import FreshRevisionExecution

TASK = UUID("6739d3c5-6619-44ce-970f-0ab1e49f3acc")
PHASE = UUID("baa4d9d7-411d-452f-acf3-ed9551c12743")
JOB = UUID("b2c4f8cf-3600-4cc0-ab79-efcae56f4dd1")
ROOT = UUID("7d4b85ba-a0ec-4348-ac11-3401c6bded47")
RECEIPT = UUID("87596016-7639-4ed9-8f05-684b7bf8027c")
ARTIFACT = UUID("a6433494-8167-4f2b-ad39-82a20ce62cde")
RESERVATION = UUID("07895b24-4fe9-4e76-b6e4-a3abad9093de")
PREP_SHA = "9f289b161cc69a3bb02eea06e47d329a9ad1ff243d3ca9185801b4eb104ac5a7"
RECEIPT_SHA = "0a5cd30a9e689b901bba452599c93db1a794367cec7b5069c3f3113215eae4c6"
JOURNAL = "tutor_item_supply_shared_persistent_pack_journal"
PRIVATE = "tutor_item_supply_private_persistent_pack_journal"
_PHASE_PINS = {
    "phase_result": "eeb4caed12ffcbf8bf4a3172ce673096dc301d37e82f66e10268cfa04118ea21",
    "dispatch_started": "ca4271ccc47457b76af2c06459d571a061802aac92994ff132fd43af9103e02e",
    "stage_started": "ed9817861f4cbb2e2e757c20602fc76781aeab0ae27c5511410144ba565d4455",
    "phase": "2e77964d9c09acd05f7fd0455a8fd1e5f4cf909a86996944730ec1a9b004b765",
    "stage_result": "a0511b096e06fe8a6e5b0118f3e4a4241f444aab3d95a5b2d53dc52e49decb61",
}

@dataclass(frozen=True, repr=False)
class RevisionOnlyContext:
    owner: PersistentPackTaskOwner
    task: PersistentPackTaskRef
    record: PersistentPublicPhaseRecord
    version: PersistentPublicVersionRecord
    execution: FreshRevisionExecution | None = None
    source_successor: IssuedSourceMappingSuccessor | None = None

@dataclass(frozen=True, repr=False)
class CommittedRevisionParent:
    artifact_id: UUID
    artifact_hash: str
    source: LearningItemSourceV1
    spec: FiniteCandidateSpecV1
    request: GenerationRequestV2
    binding: CandidateBindingV2

@dataclass(frozen=True, repr=False)
class CommittedInvestigationEvidence:
    owner: NativeReviewInvestigationOwner
    persistent_phase: RevisionOnlyContext
    original: CommittedRevisionParent
    preparation_id: UUID
    root_id: UUID
    lease: JobLeaseV1
    request: PersistentInvestigationInputV1
    report: PersistentInvestigationReportV1
    identity: ProviderIdentityV2
    deadline_at: datetime
    source_deadlines: tuple[tuple[str, str, datetime], ...]

    def seal(self) -> str:
        p = self.original
        with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
            return canonical_hash(dict(phase=self.persistent_phase.record.model_dump(mode="json"),
                version=self.persistent_phase.version.model_dump(mode="json"),
                parent=dict(artifact_id=str(p.artifact_id), artifact_hash=p.artifact_hash,
                    source=p.source.model_dump(mode="json"), spec=p.spec.model_dump(mode="json"),
                    request=p.request.model_dump(mode="json"), binding=p.binding.model_dump(mode="json")),
                preparation_id=str(self.preparation_id), root_id=str(self.root_id), lease=self.lease.model_dump(mode="json"),
                request=self.request.input_payload, report=self.report.model_dump(mode="json"),
                identity=self.identity.model_dump(mode="json"), deadline=self.deadline_at.isoformat(),
                sources=[(b,c,t.isoformat()) for b,c,t in self.source_deadlines]))

def _deny() -> NoReturn:
    raise PipelineRepositoryError("COMMITTED_REVISION_EXACT_CURRENT_EVIDENCE_REQUIRED")

def _contracts(conn: Any) -> None:
    pins = dict(PUBLIC_NORMAL_RECEIVER_PINS)
    pins["item_supply_internal.persistent_registered_family_revision_matches(jsonb)"] = "21e3c91fc8d3efb576fc456aaf17de1040e5296d66985b276e9ee610e5984ae3"
    for signature, digest in pins.items():
        row = conn.execute("SELECT p.prosrc,p.prosecdef,p.prokind,p.proconfig FROM pg_proc p WHERE p.oid=to_regprocedure(%s)", (signature,)).fetchone()
        if (row is None or row["prosecdef"] is not True or row["prokind"] != "f"
                or row["proconfig"] != ["search_path=pg_catalog, public, item_supply_internal, pg_temp"]
                or hashlib.sha256(row["prosrc"].replace("\r\n", "\n").encode()).hexdigest() != digest):
            _deny()

def require_context(context: RevisionOnlyContext) -> None:
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    if type(context) is not RevisionOnlyContext or type(context.owner) is not PersistentPackTaskOwner:
        _deny()
    core, task, phase = context.owner, context.task, context.record
    entry = core._revision_contexts.get(PHASE)
    if (entry is None or entry[0] is not context or entry[1] != canonical_hash(phase.model_dump(mode="json"))
            or task.pack_task_id != TASK or (phase.phase_id, phase.job_id, phase.root_id) != (PHASE, JOB, ROOT)):
        _deny()
    if context.source_successor is None:
        core._task(task)
    else:
        from app.services.learning.item_supply.persistent_pack_source_successor import require
        if context.execution is None:
            _deny()
        require(context.source_successor,core,task)
    now = core._guard()
    if context.execution is None:
        if now >= min(phase.valid_until, phase.lease.expires_at, phase.lease.parent_deadline):
            raise PipelineRepositoryError("COMMITTED_REVISION_ORIGINAL_LEASE_EXPIRED_NO_RENEWAL")
        core.runtime._control(phase.lease, now=now, compare_version=False)
    else:
        from app.services.learning.item_supply.persistent_pack_fresh_committed_revision import require_execution
        require_execution(context)
    if core.conn.execute("SELECT 1 FROM " + PRIVATE + " WHERE pack_task_id=%s AND user_id=%s AND epoch=%s AND record_kind IN('pause','stop')",
            (TASK, task.user_id, task.epoch)).fetchone():
        _deny()
    rows = core.conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction FROM " + JOURNAL +
        " WHERE phase_id=%s FOR SHARE", (PHASE,)).fetchall()
    if (len(rows) != 5 or {r["record_kind"]: r["payload_hash"] for r in rows} != _PHASE_PINS
            or any(r["same_transaction"] or r["public_task_id"] != task.public_task_id or r["root_id"] != ROOT or r["job_id"] != JOB
                or canonical_hash(r["payload_json"]) != r["payload_hash"] for r in rows)
            or context.version != core._versions(task).get(context.version.slot)):
        _deny()
    if context.execution is None:
        core.conn.execute("SELECT item_supply_internal.assert_persistent_pack_phase(%s)", (Jsonb(phase.model_dump(mode="json")),))
    held = core.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(%s) AS held", (JOB,)).fetchone()
    if held is None or held["held"] is not False:
        _deny()
    if context.execution is None:
        _contracts(core.conn)

def _facts(owner: NativeReviewInvestigationOwner, context: RevisionOnlyContext) -> tuple[CommittedInvestigationEvidence, dict[str, Any]]:
    from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
    if type(owner) is not NativeReviewInvestigationOwner:
        _deny()
    require_context(context)
    owner._guard()
    core, conn, historical_lease = context.owner, owner.conn, context.record.lease
    lease = historical_lease if context.execution is None else context.execution.lease
    if owner.conn is not core.conn or owner.review.settings != core.settings:
        _deny()
    prep = conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
        "FROM tutor_item_supply_shared_review_investigation_preparations WHERE id=%s FOR SHARE", (RECEIPT,)).fetchone()
    row = conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
        "FROM tutor_item_supply_shared_review_investigation_receipts WHERE id=%s FOR SHARE", (RECEIPT,)).fetchone()
    if prep is None or row is None:
        _deny()
    assert prep is not None and row is not None
    for fact, digest in ((prep, PREP_SHA), (row, RECEIPT_SHA)):
        if (fact["same_transaction"] or fact["snapshot_hash"] != digest or canonical_hash(fact["payload_json"]) != digest
                or (fact["root_id"],fact["job_id"],fact["generation_artifact_id"],fact["reservation_id"]) != (ROOT,JOB,ARTIFACT,RESERVATION)):
            _deny()
    payload, result = prep["payload_json"], row["payload_json"]
    if row["preparation_id"] != RECEIPT or payload["lease"] != historical_lease.model_dump(mode="json"):
        _deny()
    reservation = conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
        "FROM tutor_item_supply_shared_reservations WHERE id=%s FOR SHARE", (RESERVATION,)).fetchone()
    settled = conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
        "FROM tutor_item_supply_shared_runtime_settlements WHERE id=%s FOR SHARE", (row["settlement_id"],)).fetchone()
    if (reservation is None or settled is None or reservation["same_transaction"] or settled["same_transaction"]
            or (reservation["root_id"],reservation["job_id"],reservation["lease_generation"]) != (ROOT,JOB,historical_lease.generation)
            or reservation["reservation_key"] != payload["reservation_key"] or settled["reservation_id"] != RESERVATION
            or settled["settlement_key"] != payload["reservation_key"] or settled["usage_state"] != "unknown"
            or owner.budget._reservation_amounts(historical_lease,RESERVATION) != payload["resources"]):
        _deny()
    authority = core.type_owner.source_authority
    continuation = owner.review.continuation_owner
    if type(continuation) is not SharedCandidateContinuationOwner:
        _deny()
    assert continuation is not None
    if context.execution is None:
        adopted = continuation.resolve(lease=lease, artifact_id=ARTIFACT, spec=context.version.specification, source_authority=authority)
    else:
        from app.services.learning.item_supply.persistent_pack_fresh_committed_revision import historical_parent
        adopted = historical_parent(owner,context)
    source, request, spec = adopted.source, adopted.original_request, context.version.specification
    review = conn.execute("SELECT * FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s AND generation_artifact_id=%s "
        "AND artifact_kind='review_bundle' AND mode='live' FOR SHARE", (UUID(payload["review_receipt_id"]),ARTIFACT)).fetchone()
    validation = conn.execute("SELECT * FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s AND generation_artifact_id=%s "
        "AND artifact_kind='validation' AND mode='live' FOR SHARE", (UUID(payload["validation_receipt_id"]),ARTIFACT)).fetchone()
    if review is None or validation is None or adopted.inputs.static_facts is None:
        _deny()
    assert review is not None and validation is not None and adopted.inputs.static_facts is not None
    valid = adopted.inputs.static_facts.validation
    if validation["receipt_hash"] != valid.evidence_hash or validation["payload_json"] != valid.model_dump(mode="json"):
        _deny()
    now = core._guard()
    sources = []
    if context.source_successor is None:
        source_reviews = authority._current.governance.source_reviews
        for material in request.materials:
            coordinate = material.binding.evidence[0].binding
            grant = None if source_reviews is None else source_reviews.resolve(coordinate.source_handle,coordinate.document_handle)
            if grant is None or grant.grant is None or grant.grant.retained_until <= now:
                _deny()
            assert grant is not None and grant.grant is not None
            sources.append((material.binding.binding_digest,material.exact_claims[0].claim_receipt_id,grant.grant.retained_until))
        stored_sources = tuple((x["binding_digest"],x["claim_receipt_id"],datetime.fromisoformat(x["retained_until"])) for x in payload["source_deadlines"])
        if tuple(sources) != stored_sources:
            _deny()
    else:
        # Old investigation payload/hash above remains exact historical DATA.
        # This separately issued current proof supplies ONLY the new execution's sources.
        sources.extend(context.source_successor.source_deadlines)
    deadline = datetime.fromisoformat(payload["deadline_at"]) if context.execution is None else context.execution.valid_until
    bounds = (deadline,lease.expires_at,lease.parent_deadline)
    if now >= min((*bounds,prep["valid_until"]) if context.execution is None else bounds):
        raise PipelineRepositoryError("COMMITTED_REVISION_ORIGINAL_LEASE_EXPIRED_NO_RENEWAL")
    with finite_review_context(source,spec=spec,materials=request.materials):
        bundle = parse_bundle(review["payload_json"])
        if bundle.bundle_hash != review["receipt_hash"] or bundle.bundle_hash != payload["review_receipt_hash"]:
            _deny()
        for report in bundle.reports:
            verify_review_report(report,make_review_request(source,binding=bundle.binding,validation_receipt=valid,
                role=report.role,protocol=report_protocol(report)))
        clones = tuple(PersistentCloneFindingV1.model_validate_json(json.dumps(d)) for d in payload["request_payload"]["disputes"]
            if d.get("schema_version") == "persistent_deterministic_clone_finding_v1")
        if len(clones) != 1:
            _deny()
        original_input = PersistentInvestigationInputV1(review_receipt_id=UUID(payload["review_receipt_id"]),
            review_receipt_hash=review["receipt_hash"],bundle=bundle,
            review_input=ReviewInputV2(binding=bundle.binding,role=LearningItemReviewRole.TECHNICAL,source=source,validation_receipt=valid),
            execution_profile_hash=historical_lease.profile.profile_hash,disputes=(*review_disputes(bundle),*clones),
            revision_allocation=owner._select_registered_child_allocation(context,spec))
        owner._persistent_finding(context,original_input)
        if original_input.input_payload != payload["request_payload"] or original_input.input_hash != payload["request_hash"]:
            _deny()
        report_data = PersistentInvestigationReportV1.model_validate_json(json.dumps(result["report"]))
        report_data.verify_input(original_input)
        identity = ProviderIdentityV2.model_validate_json(json.dumps(payload["identity"]))
        if (report_data.run.provider_identity != identity or result["safe_reason"] != "investigation_analysis_pending_revision_owner"
                or result["preparation_hash"] != PREP_SHA or result["request_hash"] != original_input.input_hash
                or identity.model != core.settings.llm_model
                or owner.review._models.get((identity.provider,identity.model_version)) != identity.model):
            _deny()
        if context.execution is None:
            conn.execute("SELECT item_supply_internal.assert_persistent_normal_repair(%s::jsonb)", (Jsonb(payload),))
        else:
            conn.execute("SELECT item_supply_internal.assert_committed_revision_execution(%s::jsonb)", (Jsonb(context.execution.payload),))
    parent = CommittedRevisionParent(ARTIFACT,adopted.original_artifact["artifact_hash"],source,spec,request,bundle.binding)
    return CommittedInvestigationEvidence(owner,context,parent,RECEIPT,ROOT,lease,original_input,report_data,identity,deadline,tuple(sources)), row

def issue_evidence(owner: NativeReviewInvestigationOwner, context: RevisionOnlyContext) -> CommittedInvestigationEvidence:
    evidence, _ = _facts(owner,context)
    owner._committed_revision_proofs[RECEIPT] = (evidence,evidence.seal())
    return evidence

def require_evidence(owner: NativeReviewInvestigationOwner, proof: CommittedInvestigationEvidence) -> dict[str, Any]:
    if type(proof) is not CommittedInvestigationEvidence or proof.owner is not owner:
        _deny()
    entry = owner._committed_revision_proofs.get(RECEIPT)
    if entry is None or entry[0] is not proof or entry[1] != proof.seal():
        _deny()
    current, row = _facts(owner,proof.persistent_phase)
    if current.seal() != entry[1]:
        _deny()
    return row

def prepare_committed_revision(core: PersistentPackTaskOwner, task: PersistentPackTaskRef, *, transaction: Transaction) -> tuple[NativeRevisionOwner, PreparedNativeRevision]:
    from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
    from app.services.learning.item_supply.native_revision import NativeRevisionOwner
    from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
    from app.services.learning.item_supply.persistent_pack_pipeline import PersistentPublicPipeline
    from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
    from app.services.learning.item_supply.shared_review import SharedReviewPipeline
    if (type(core) is not PersistentPackTaskOwner or type(task) is not PersistentPackTaskRef or task.pack_task_id != TASK
            or type(transaction) is not Transaction or getattr(transaction,"_conn",None) is not core.conn
            or transaction.status != transaction.Status.ACTIVE or not getattr(transaction,"_outer_transaction",False)
            or getattr(transaction,"_stack_index",-1) != 0 or getattr(core.conn,"_num_transactions",0) != 1
            or core.conn.info.transaction_status != TransactionStatus.INTRANS):
        raise PipelineRepositoryError("COMMITTED_REVISION_ORIGINAL_TOP_REQUIRED")
    prior = transaction.force_rollback
    transaction.force_rollback = True
    try:
        core._task(task)
        core.conn.execute("SELECT pg_advisory_xact_lock(hashtext('committed-revision'),hashtext(%s))", (str(RECEIPT),))
        if core.conn.execute("SELECT 1 FROM tutor_item_supply_shared_revision_preparations WHERE investigation_receipt_id=%s", (RECEIPT,)).fetchone():
            raise PipelineRepositoryError("COMMITTED_REVISION_RECEIPT_ONCE_CONSUMED")
        row = core.conn.execute("SELECT payload_json FROM " + JOURNAL + " WHERE phase_id=%s AND record_kind='phase'", (PHASE,)).fetchone()
        if row is None:
            _deny()
        assert row is not None
        phase = PersistentPublicPhaseRecord.model_validate_json(json.dumps(row["payload_json"]))
        versions = [v for v in core._versions(task).values() if v.revision_id == phase.revision_id and v.artifact_id == ARTIFACT]
        if len(versions) != 1:
            _deny()
        context = RevisionOnlyContext(core,task,phase,versions[0])
        core._revision_contexts[PHASE] = (context,canonical_hash(phase.model_dump(mode="json")))
        require_context(context)
        pipeline = PersistentPublicPipeline(core)
        model = pipeline.provider.configured_model
        bindings = {(pipeline.provider.provider_key,model):model}
        continuation = SharedCandidateContinuationOwner(core.conn,core.settings,enabled=True)
        review = SharedReviewPipeline(core.conn,core.settings,enabled=True,continuation_owner=continuation,trusted_model_bindings=bindings)
        investigator = NativeReviewInvestigationOwner(review,enabled=True,protocol="scalar-evidence-v2")
        evidence = investigator.issue_committed_revision(context)
        generation = SharedGenerationPipeline(core.conn,core.settings,enabled=True,trusted_model_bindings=bindings)
        revision = NativeRevisionOwner(investigator,generation,enabled=True)
        prepared = revision.prepare_committed(evidence)
        if prepared is None:
            raise PipelineRepositoryError("COMMITTED_REVISION_RECEIPT_ONCE_CONSUMED")
        transaction.force_rollback = prior
        return revision, prepared
    except BaseException:
        core._revision_contexts.pop(PHASE,None)
        raise
