"""Main-only TOP rollback probe of the original first investigation preparation.

Does not call run_phase, stage_start, sender, provider or any network method.
Does not restore a failed phase/lease/Prepared capability. The caller must
compose a NEW disposable concrete original owner graph and discard it afterward.
The returned coordinates/counts are DATA, never permission to repeat paid work.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Any
from uuid import UUID
from psycopg.pq import TransactionStatus
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
from app.services.learning.item_supply.persistent_pack_candidate import PersistentCandidateExecutor
from app.services.learning.item_supply.persistent_pack_contracts import BlockedPackPhase, PersistentPackTaskRef
from app.services.learning.item_supply.persistent_pack_diagnostics import collect_persistent_pack_diagnostics, observe_persistent_pack_failure
from app.services.learning.item_supply.shared_validation import SharedValidationPipeline

PREPARATION_PROBE_ACK = "p7-investigation-prepare-rollback-only-20261012"
_COUNT_TABLES = (
    "tutor_item_supply_shared_review_investigation_preparations",
    "tutor_item_supply_shared_review_investigation_receipts",
    "tutor_item_supply_shared_reservations",
    "tutor_item_supply_shared_generation_artifacts",
    "tutor_item_supply_shared_checkpoints",
)
# Diagnostic vocabulary from the original prepare_next_phase/candidate/pipeline
# blockers only. This is not an authority or a list of recoverable outcomes.
_BLOCKED_PHASE_REASONS = frozenset({
    "pack_already_ready_no_new_paid",
    "consumer_stopped",
    "current_source_or_content_unavailable",
    "opaque_phase_outcome_unknown_no_paid_replay",
    "unstarted_live_phase_wait_original_expiry",
    "unstarted_phase_original_runtime_pending",
    "original_phase_still_unsettled",
    "committed_relationship_requires_same_slot_revision",
    "persistent_relation_523_receiver_required",
    "persistent_private_exposure_repair_attachment_required",
    "original_author_started_without_adoptable_data_no_repeat",
    "original_current_public_materials_required",
    "original_approved_runtime_and_runner_required",
    "committed_author_data_required_no_repeat",
    "controlled_ancestry_unconditional_hold",
    "started_stage_outcome_unknown_no_paid_replay",
    "immutable_failed_stage_requires_substantive_finding_owner",
    "committed_relationship_repair_owner_required",
    "persistent_normal_525_receiver_required",
    "committed_quality_requires_original_facts_continuation",
})


def _closed_blocked_phase_reason(reason: object) -> str:
    # Never stringify raw reasons/IDs or invoke subclass equality/hash hooks.
    return reason if type(reason) is str and reason in _BLOCKED_PHASE_REASONS else "unknown_blocked_reason"


def probe_original_investigation_preparation(owner: PersistentPackTaskOwner, task: PersistentPackTaskRef,
        *, failed_phase_id: UUID, main_only_ack: str) -> dict[str, Any]:
    if (type(owner) is not PersistentPackTaskOwner or type(task) is not PersistentPackTaskRef
            or main_only_ack != PREPARATION_PROBE_ACK
            or owner.conn.info.transaction_status != TransactionStatus.IDLE):
        raise ValueError("main_only_disposable_original_owner_top_rollback_required")
    result: dict[str, Any] = dict(schema_version="persistent_investigation_preparation_probe_v1",
        failed_phase_id=str(failed_phase_id),failed_usage_unknown_retained=True,
        prior_actual_http_attempts=None,rollback_requested=True,acceptance_asserted=False,
        preparation_observed=False,network_methods_called_by_probe=False,
        execution_capability_returned=False,graph_reuse_for_execution=False)
    with collect_persistent_pack_diagnostics() as diagnostics:
        try:
            # OWN TOP transaction: nesting under an outer rollback would change
            # fresh-row xmin to a subxid and violate the original 517 contract.
            with owner.conn.transaction(force_rollback=True):
                owner._task(task)
                rows = owner.conn.execute("SELECT record_kind,payload_json,job_id,root_id FROM "
                    "tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=%s AND phase_id=%s",
                    (task.public_task_id,failed_phase_id)).fetchall()
                phases = [r for r in rows if r["record_kind"]=="phase"]
                outcomes = [r for r in rows if r["record_kind"]=="phase_result"]
                if (len(phases)!=1 or len(outcomes)!=1
                        or phases[0]["payload_json"]["kind"]!="candidate"
                        or outcomes[0]["payload_json"]["status"]!="outcome_unknown"
                        or len([r for r in rows if r["record_kind"]=="dispatch_started"])!=1
                        or any(r["record_kind"] in ("stage_started","stage_result") for r in rows)):
                    raise ValueError("probe_requires_exact_failed_first_preparation_phase")
                failed_job = phases[0]["job_id"]
                counts = {}
                for table in _COUNT_TABLES:
                    # Only closed module-owned original table names enter SQL.
                    row = owner.conn.execute("SELECT count(*) AS count FROM "+table+" WHERE job_id=%s",(failed_job,)).fetchone()
                    if row is None:
                        raise ValueError("probe_original_count_read_unavailable")
                    counts[table] = row["count"]
                result["prior_original_counts"] = counts
                if any(counts.values()):
                    raise ValueError("probe_requires_no_committed_first_investigation_work")
                # Fresh original prepared DATA/frames for diagnosis, all rolled
                # back. No old lease or Prepared object is loaded from JSON.
                phase = owner.prepare_next_phase(task)
                if isinstance(phase,BlockedPackPhase):
                    result["safe_reason"] = "original_fresh_preparation_blocked"
                    result["blocked_phase_reason"] = _closed_blocked_phase_reason(phase.safe_reason)
                else:
                    executor = phase.prepared.get("candidate_executor")
                    if (type(executor) is not PersistentCandidateExecutor or phase.version is None
                            or phase.record.kind!="candidate" or phase.record.root_id!=phases[0]["root_id"]
                            or phase.prepared.get("resume_stage")!="committed_review_repair"):
                        raise ValueError("probe_requires_original_same_root_committed_review_repair")
                    SharedValidationPipeline(owner.conn,owner.settings,enabled=True,
                        continuation_owner=phase.prepared["continuation_owner"])
                    investigator = NativeReviewInvestigationOwner(phase.prepared["review_owner"],enabled=True,
                        protocol="scalar-evidence-v2")
                    executor.remaining(phase,phase.record.lease,9)
                    review = phase.prepared["review"]
                    with finite_review_context(review.source,spec=review.spec,materials=review.request.materials):
                        prepared = investigator.prepare_persistent(phase=phase,original=review,
                            result=phase.prepared["reviewed"],review_receipt_id=phase.prepared["review_id"],
                            clone_pair=phase.prepared.get("clone_pair"))
                    if prepared is None or prepared.resources.requests!=1 or prepared.resources.output_tokens!=61440:
                        raise ValueError("probe_original_formal_investigation_prepare_required")
                    result["preparation_observed"] = True
                    result["safe_reason"] = "original_investigation_preparation_returned_rollback_only"
        except Exception as exc:
            observe_persistent_pack_failure(exc,operation="preparation_probe")
            result["safe_reason"] = "original_investigation_preparation_probe_failed"
    result["observations"] = [asdict(item) for item in diagnostics.observations]
    result["diagnostic_unavailable"] = diagnostics.diagnostic_unavailable
    return result
