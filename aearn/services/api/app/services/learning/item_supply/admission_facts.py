"""Bounded pre-admission facts issuer. No P7 inventory, public flag or external IO."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.admission_facts_contracts import (
    AmbiguityBudgetBindingV1, BlindExecutionProofV1, ClauseTargetMappingV1, IssuedAdmissionFactsV1, PreAdmissionCoverageReceiptV1,
    PythonTaskTargetV1, RunnerTerminalProofV1, TaskAmbiguityReceiptV1,
)
from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1, CoverageBlueprintV1, SupplyScopeV1
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.pipeline_repository import PipelineArtifactRepository
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvidenceV2, BlindScoreV2, ProbeOutcomeV2, check_subject, receipt_digest,
)
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort
from app.services.learning.item_supply.storage import PostgresPrivateSupplyStorage
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2, checked_model
from app.services.learning.item_supply.validation_adapter import CandidateExecutionEvidenceV2
from app.services.learning.item_supply.task_ambiguity_owner import (
    AdmissionFactsPending, TaskAmbiguityOwner, require_finite_target, target_clauses,
)
from app.services.learning.item_supply.sandbox.python_goal_scorer import (
    PYTHON_GOAL_ID, PYTHON_GOAL_SCORER_VERSION, source_scorer_version,
)

if TYPE_CHECKING:
    from app.services.learning.item_supply.pipeline import CompletedReview, PreparedReview

TABLE = "tutor_item_supply_private_admission_facts"


class AdmissionFactsOwner:
    def __init__(self, conn: Connection[dict[str,Any]], *, rag_authority: RagSourceAuthority,
                 execution_owner: SandboxCandidateExecutionPort, ambiguity_owner: TaskAmbiguityOwner,
                 blind_scorer: SandboxBlindAnswerScorer | None = None, enabled: bool = False) -> None:
        self.conn = conn
        self.rag_authority = rag_authority
        self.execution_owner = execution_owner
        self.ambiguity_owner = ambiguity_owner
        self.blind_scorer = blind_scorer
        self.enabled = enabled
        self._issued: dict[UUID,IssuedAdmissionFactsV1] = {}

    def _require_python_runner_issuer(self) -> RunnerPort:
        """The Python goal needs one actual issuer, not a live-shaped port bool.

        Inspect only already-loaded internal owner classes; the API never imports
        Docker or creates an execution client. Original in-memory receipts must
        pass the bridge's own verifier again, independent of an injected verify.
        """
        bridge_module = sys.modules.get("aearn_executor.item_supply_bridge")
        client_module = sys.modules.get("aearn_executor.docker_client")
        bridge_type = getattr(bridge_module, "ItemSupplyRunnerBridge", None)
        client_type = getattr(client_module, "DockerContainerRuntimeClient", None)
        runner = self.execution_owner._runner
        if (bridge_type is None or client_type is None or type(runner) is not bridge_type
                or getattr(runner, "_live", None) is not True
                or type(getattr(runner, "_client", None)) is not client_type
                or self.ambiguity_owner._runner is not runner
                or type(self.blind_scorer) is not SandboxBlindAnswerScorer
                or self.blind_scorer._runner is not runner):
            raise AdmissionFactsPending("admission_python_actual_runner_issuer_missing")
        return runner

    def _verify_python_runner_issuer(self, execution: CandidateExecutionEvidenceV2,
                                     ambiguity: TaskAmbiguityReceiptV1, blind_score: BlindScoreV2) -> None:
        runner = self._require_python_runner_issuer()
        if type(self.blind_scorer) is not SandboxBlindAnswerScorer:
            raise AdmissionFactsPending("admission_python_actual_runner_issuer_missing")
        candidate_run = self.execution_owner._runs.get(execution.run_id)
        ambiguity_run = self.ambiguity_owner._runs.get(ambiguity.run_id)
        blind_run = self.blind_scorer._issued.get(blind_score.receipt_hash)
        if candidate_run is None or ambiguity_run is None or blind_run is None:
            raise AdmissionFactsPending("admission_python_runner_receipts_unavailable")
        pairs = [(terminal, task.wire) for task, terminal in
                 zip(candidate_run.tasks, candidate_run.receipts, strict=True)]
        pairs.extend(zip(ambiguity_run[1], (ambiguity.plan.correct, ambiguity.plan.counterexample), strict=True))
        pairs.append((blind_run.receipt, blind_run.request))
        if any(not type(runner).verify(runner, terminal, request=request) for terminal, request in pairs):
            raise AdmissionFactsPending("admission_python_runner_seal_unverified")

    def _transaction(self) -> datetime:
        if (not self.enabled or self.conn.autocommit
                or self.conn.info.transaction_status != TransactionStatus.INTRANS):
            raise AdmissionFactsPending("admission_facts_gate_closed")
        if (type(self.rag_authority) is not RagSourceAuthority or self.rag_authority.connection is not self.conn
                or type(self.execution_owner) is not SandboxCandidateExecutionPort
                or type(self.ambiguity_owner) is not TaskAmbiguityOwner):
            raise AdmissionFactsPending("admission_facts_owner_missing")
        row = self.conn.execute("SELECT current_database() AS db,clock_timestamp() AS now").fetchone()
        if row is None or row["db"] != "aearn_b1d_sandbox_20261001":
            raise AdmissionFactsPending("admission_facts_isolated_owner_required")
        return row["now"]

    def _frozen(self, prepared: PreparedReview, lease: JobLeaseV1, now: datetime
                ) -> tuple[dict[str,Any],SupplyScopeV1,AssessmentSupplyDemandV1,CoverageBlueprintV1,dict[str,Any]]:
        if prepared.mode != "live" or lease.visibility != "private" or lease.owner_id is None or lease.owner_epoch is None:
            raise AdmissionFactsPending("admission_live_owner_required")
        if (lease.job_id != prepared.lease.job_id or lease.owner_id != prepared.lease.owner_id
                or lease.owner_epoch != prepared.lease.owner_epoch or lease.generation != prepared.lease.generation
                or lease.state_version != prepared.lease.state_version or lease.profile != prepared.lease.profile):
            raise AdmissionFactsPending("admission_facts_lease_stale")
        artifacts = PipelineArtifactRepository(self.conn)
        artifact = artifacts.get_generation(lease=lease,scope_id=prepared.scope_id,
            artifact_id=prepared.artifact_id,now=now,mode="live")
        if (artifact["source_hash"] != prepared.source.source_hash or artifact["content_hash"] != prepared.source.content_hash
                or prepared.binding.candidate_key != str(artifact["candidate_id"])
                or prepared.binding.version_key != str(artifact["version_id"])
                or prepared.binding.profile_hash != lease.profile.profile_hash
                or prepared.binding.policy_hash != AutonomousEvidencePolicyV2().policy_hash):
            raise AdmissionFactsPending("admission_candidate_stale")
        storage = PostgresPrivateSupplyStorage(self.conn,user_id=lease.owner_id,expected_epoch=lease.owner_epoch)
        stored = storage._scope(prepared.scope_id)
        scope = SupplyScopeV1.model_validate_json(json.dumps(stored["snapshot_json"]))
        node = self.conn.execute(
            """SELECT n.id,n.title,n.description,n.required_capabilities_json,n.prerequisite_keys_json,t.language_id
               FROM tutor_track_plan_nodes n JOIN tutor_track_active_plans p
                 ON p.revision_id=n.revision_id AND p.track_id=n.track_id AND p.user_id=n.user_id
               JOIN tutor_learning_tracks t ON t.id=n.track_id AND t.user_id=n.user_id
               WHERE n.user_id=%s AND n.track_id=%s AND n.revision_id=%s AND n.knowledge_key=%s
               FOR SHARE OF n,p,t""",
            (lease.owner_id,stored["track_id"],stored["revision_id"],stored["knowledge_key"]),
        ).fetchone()
        if node is None:
            raise AdmissionFactsPending("admission_active_node_missing")
        node_snapshot = {key:str(value) if isinstance(value,UUID) else value for key,value in node.items()}
        scope_hash = canonical_hash({"contract":scope.model_dump(mode="json"),"track_id":str(stored["track_id"]),
            "revision_id":str(stored["revision_id"]),"node_id":str(node["id"])})
        if (stored["objective_hash"] != canonical_hash(node_snapshot) or stored["scope_hash"] != scope_hash
                or node["description"] != prepared.source.public.instruction_markdown
                or tuple(node["required_capabilities_json"]) != prepared.source.blueprint.required_capabilities
                or scope.required_capabilities != prepared.source.blueprint.required_capabilities
                or scope.language_id != prepared.source.blueprint.language_id
                or node["language_id"] != scope.language_id
                or scope.knowledge_key != prepared.source.blueprint.knowledge_key
                or scope.runtime_profile_id != prepared.source.blueprint.runtime_profile_id
                or scope.item_kind != prepared.source.public.kind or scope.purpose != prepared.source.public.purpose):
            raise AdmissionFactsPending("admission_target_mapping_unproven")
        if isinstance(require_finite_target(prepared.source), PythonTaskTargetV1) and (
                scope.scorer_version != PYTHON_GOAL_SCORER_VERSION or scope.assessment_contract_version != PYTHON_GOAL_ID):
            raise AdmissionFactsPending("admission_python_scoring_contract_mismatch")
        from app.services.learning.item_supply.generation_demand import (
            GenerationDemandError, frozen_private_demand,
        )

        frozen_request = GenerationRequestV2.model_validate_json(json.dumps(artifact["request_json"]))
        try:
            demand = frozen_private_demand(self.conn, lease=lease, scope_id=prepared.scope_id, request=frozen_request)
        except GenerationDemandError as error:
            raise AdmissionFactsPending(str(error).lower()) from None
        row = self.conn.execute(
            "SELECT * FROM tutor_item_supply_shared_blueprints WHERE blueprint_hash=%s FOR SHARE",(demand.blueprint_hash,),
        ).fetchone()
        if row is None:
            raise AdmissionFactsPending("admission_coverage_blueprint_missing")
        blueprint = CoverageBlueprintV1.model_validate_json(json.dumps(row["snapshot_json"]))
        if (blueprint.blueprint_hash != row["blueprint_hash"] or blueprint.blueprint_hash != demand.blueprint_hash
                or blueprint.objective_hash != demand.objective_hash or blueprint.matrix_hash != demand.matrix_hash
                or blueprint.matrix_hash != build_support_matrix().matrix_hash
                or blueprint.policy_version != demand.policy_version
                or blueprint.scope.model_dump(exclude={"visibility","owner_ref"}) != scope.model_dump(exclude={"visibility","owner_ref"})
                or blueprint.clauses != target_clauses(prepared.source)):
            raise AdmissionFactsPending("admission_coverage_blueprint_unproven")
        return artifact,scope,demand,blueprint,node_snapshot

    def _ambiguity_budget(self, prepared: PreparedReview, lease: JobLeaseV1,
                          completed: CompletedReview, ambiguity: TaskAmbiguityReceiptV1
                          ) -> tuple[AmbiguityBudgetBindingV1,tuple[BlindExecutionProofV1,...]]:
        if (type(self.blind_scorer) is not SandboxBlindAnswerScorer
                or not self.blind_scorer.verify(completed.bundle.blind_solve.score,prepared.source)
                or completed.bundle.binding != prepared.binding):
            raise AdmissionFactsPending("admission_blind_execution_owner_unverified")
        reservation = self.conn.execute(
            "SELECT * FROM tutor_item_supply_private_reservations WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s AND job_id=%s FOR SHARE",
            (prepared.reservation_id,lease.owner_id,lease.owner_epoch,prepared.scope_id,lease.job_id),
        ).fetchone()
        if (reservation is None or reservation["lease_generation"] != lease.generation
                or reservation["reservation_key"] != "review."+prepared.artifact_id.hex
                or len(prepared.attempt_bounds) != 7
                or reservation["requests"] < sum(prepared.attempt_bounds) or reservation["tokens"] <= 0
                or reservation["created_at"] > ambiguity.started_at):
            raise AdmissionFactsPending("review_full_aggregate_not_prereserved")
        allocations = self.conn.execute(
            "SELECT resource_kind,reserved_amount FROM tutor_item_supply_runtime_global_reservation_amounts WHERE reservation_namespace='private' AND reservation_id=%s FOR SHARE",
            (prepared.reservation_id,),
        ).fetchall()
        values: dict[str,int] = {}
        for row in allocations:
            kind,amount = row["resource_kind"],int(row["reserved_amount"])
            if kind in values and values[kind] != amount:
                raise AdmissionFactsPending("review_aggregate_allocations_conflict")
            values[kind] = amount
        reserved = ResourceAmounts.model_validate(values)
        if (reserved.execution_seconds < 30 or reserved.requests != reservation["requests"]
                or reserved.input_tokens+reserved.output_tokens != reservation["tokens"]):
            raise AdmissionFactsPending("review_execution_30_bound_missing")
        settlement = self.conn.execute(
            "SELECT * FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=%s AND user_id=%s AND epoch=%s ORDER BY sequence DESC LIMIT 1 FOR SHARE",
            (prepared.reservation_id,lease.owner_id,lease.owner_epoch),
        ).fetchone()
        # The existing review ports do not attest per-attempt HTTP/token usage.
        # Preserve their conservative UNKNOWN aggregate, never invent known zeros.
        if settlement is None or settlement["usage_state"] != "unknown":
            raise AdmissionFactsPending("review_conservative_settlement_missing")
        blind_score = completed.bundle.blind_solve.score
        blind = tuple(BlindExecutionProofV1.model_validate_json(json.dumps(raw))
            for raw in self.blind_scorer.receipts(blind_score))
        actual = ResourceAmounts(execution_seconds=self.ambiguity_owner.resource_usage(ambiguity).execution_seconds
            + self.blind_scorer.resource_usage(blind_score).execution_seconds)
        if actual.execution_seconds > reserved.execution_seconds:
            raise AdmissionFactsPending("review_execution_bound_exceeded")
        proof = AmbiguityBudgetBindingV1(reservation_id=prepared.reservation_id,
            settlement_id=settlement["id"],root_id=reservation["root_id"],reserved=reserved,
            actual_execution=actual,reserved_at=reservation["created_at"],settled_at=settlement["created_at"],
            receipt_hash=canonical_hash({"ambiguity":ambiguity.receipt_hash,"blind":blind_score.receipt_hash}))
        return proof,blind

    def _build(self, prepared: PreparedReview, lease: JobLeaseV1, ambiguity: TaskAmbiguityReceiptV1,
               *, completed_review: CompletedReview, checked_at: datetime | None = None, valid_until: datetime | None = None
               ) -> tuple[PreAdmissionCoverageReceiptV1,AdmissionEvidenceV2]:
        now = self._transaction()
        target = require_finite_target(prepared.source)
        artifact,scope,demand,blueprint,node = self._frozen(prepared,lease,now)
        validation = prepared.validation
        check_subject(prepared.source,prepared.binding,validation)
        execution = validation.execution_evidence
        if (validation.state != "machine_verified" or execution is None or execution.mode != "live"
                or execution.isolation != "approved_os_boundary"
                or execution.scorer_version != source_scorer_version(prepared.source)
                or not self.execution_owner.verify(execution,prepared.source)):
            raise AdmissionFactsPending("admission_execution_owner_unverified")
        if (ambiguity.plan.target != target or ambiguity.plan.scorer_version != source_scorer_version(prepared.source)
                or not self.ambiguity_owner.verify(ambiguity,prepared.source)):
            raise AdmissionFactsPending("admission_ambiguity_owner_unverified")
        ambiguity_budget,blind_terminals = self._ambiguity_budget(prepared,lease,completed_review,ambiguity)
        if isinstance(target, PythonTaskTargetV1):
            self._verify_python_runner_issuer(execution, ambiguity, completed_review.bundle.blind_solve.score)
        counts = self.execution_owner.scorer_counts(execution)
        if not counts["positive_cases"] or not counts["negative_cases"] or counts["pending_cases"]:
            raise AdmissionFactsPending("admission_scorer_facts_incomplete")
        request = GenerationRequestV2.model_validate_json(json.dumps(artifact["request_json"]))
        generation = GenerationReceiptV2.model_validate_json(json.dumps(artifact["receipt_json"]))
        if request.blueprint != prepared.source.blueprint or request.profile != lease.profile or len(request.materials) != len(generation.sources):
            raise AdmissionFactsPending("admission_frozen_generation_stale")
        expiries = [lease.expires_at,lease.parent_deadline,ambiguity.parent_deadline_at]
        claims: set[str] = set()
        for material,expected in zip(request.materials,generation.sources,strict=True):
            current = self.rag_authority.assert_current(material,expected)
            claims.update(current.claim_receipt_hashes)
            reviews = self.rag_authority._current.governance.source_reviews
            if reviews is None:
                raise AdmissionFactsPending("admission_current_source_missing")
            coordinate = material.binding.evidence[0].binding
            review = reviews.resolve(coordinate.source_handle,coordinate.document_handle)
            if review is None or review.grant is None:
                raise AdmissionFactsPending("admission_current_source_missing")
            expiries.append(review.grant.retained_until)
        bound = min(expiries)
        stamp = now if checked_at is None else checked_at
        expiry = bound if valid_until is None else valid_until
        if not claims or not stamp <= now < expiry <= bound:
            raise AdmissionFactsPending("admission_facts_expired")
        raw = self.execution_owner.receipts(execution)
        terminals = tuple(RunnerTerminalProofV1.model_validate_json(json.dumps(p)) for p in raw)
        if isinstance(target, PythonTaskTargetV1):
            all_locks = {t.lock_fingerprint for t in terminals + ambiguity.terminals}
            all_locks.update(t.lock_fingerprint for t in blind_terminals)
            if all_locks != {scope.runtime_profile_hash} or scope.runtime_profile_hash == "0" * 64:
                raise AdmissionFactsPending("admission_python_runtime_hash_mismatch")
            if completed_review.bundle.blind_solve.score.scorer_version != PYTHON_GOAL_SCORER_VERSION:
                raise AdmissionFactsPending("admission_python_scoring_contract_mismatch")
        starter = next((t for t in terminals if t.probe_name == "starter_rejected"),None)
        if starter is None:
            raise AdmissionFactsPending("admission_incorrect_semantic_receipt_missing")
        try:
            facts = json.loads(starter.result.stdout)["cases"]
            terminal_code = "python_terminal" if isinstance(target, PythonTaskTargetV1) else "sqlite_terminal"
            if not facts or any(f["status"] != "success" or f["code"] != terminal_code for f in facts):
                raise ValueError("not semantic")
            if isinstance(target, PythonTaskTargetV1) and any(
                    f.get("goal_contract_id") != PYTHON_GOAL_ID or type(f.get("goal_satisfied")) is not bool for f in facts):
                raise ValueError("goal semantic facts missing")
        except (ValueError,KeyError,TypeError):
            raise AdmissionFactsPending("admission_incorrect_semantic_receipt_missing") from None
        probes = {p.name:p for p in execution.probes}
        mapping = {"correct":"reference","incorrect":"starter_rejected","equivalent":"equivalent",
            "known_wrong":"wrong_rejected","boundary":"boundary","scorer_counterexample":"scorer_counterexample"}
        if any(name not in probes or probes[name].status != "passed" for name in mapping.values()):
            raise AdmissionFactsPending("admission_executed_profile_incomplete")
        coverage = PreAdmissionCoverageReceiptV1(binding=prepared.binding,scope_hash=request.scope_hash,
            objective_hash=demand.objective_hash,demand=demand,coverage_blueprint=blueprint,
            item_blueprint=prepared.source.blueprint,active_node_snapshot=node,target=target,
            mappings=tuple(ClauseTargetMappingV1(clause_id=c.clause_id,clause_hash=c.clause_hash,
                capability=cast(Literal["sql.select.where","sql.order_by","python.assignment"],c.clause_id),declaration_hash=ambiguity.plan.target.target_hash,
                execution_proof_hash=probes["reference"].proof_hash) for c in blueprint.clauses),
            source_receipts=generation.sources,execution=execution,execution_terminals=terminals,
            scorer_counts=counts,ambiguity_receipt_hash=ambiguity.receipt_hash,ambiguity_budget=ambiguity_budget,
            blind_score=completed_review.bundle.blind_solve.score,blind_terminals=blind_terminals,checked_at=stamp,valid_until=expiry)
        outcomes = tuple(ProbeOutcomeV2.model_validate({"probe":name,"passed":True,"receipt_hash":probes[raw_name].proof_hash})
            for name,raw_name in mapping.items()) + (ProbeOutcomeV2(probe="ambiguity",passed=True,receipt_hash=ambiguity.receipt_hash),)
        evidence = AdmissionEvidenceV2(binding=prepared.binding,validation_receipt_hash=receipt_digest(validation),
            source_current=True,source_claim_receipt_hashes=tuple(sorted(claims)),coverage_proof_hash=coverage.receipt_hash,
            probes=outcomes,execution_receipt_hash=canonical_hash(execution.model_dump(mode="json")),
            execution_isolated=True,runner_available=True,scorer_available=True,
            known_misjudgments=counts["false_positives"]+counts["false_negatives"])
        return coverage,evidence

    def issue(self, prepared_review: PreparedReview, *, lease: JobLeaseV1,
              ambiguity_receipt: TaskAmbiguityReceiptV1, completed_review: CompletedReview) -> IssuedAdmissionFactsV1:
        lease = checked_model(lease,JobLeaseV1)
        ambiguity_receipt = checked_model(ambiguity_receipt,TaskAmbiguityReceiptV1)
        coverage,evidence = self._build(prepared_review,lease,ambiguity_receipt,
            completed_review=completed_review)
        if lease.owner_id is None or lease.owner_epoch is None:
            raise AdmissionFactsPending("admission_private_owner_required")
        receipt = IssuedAdmissionFactsV1(receipt_id=uuid4(),user_id=lease.owner_id,epoch=lease.owner_epoch,
            scope_id=prepared_review.scope_id,generation_artifact_id=prepared_review.artifact_id,
            version_id=UUID(prepared_review.binding.version_key),lease=lease,coverage=coverage,
            ambiguity=ambiguity_receipt,evidence=evidence,derivations={
                "correct":"actual_reference_scorer_terminal","incorrect":"actual_starter_semantic_rejection",
                "ambiguity":"explicit_python_goal_same_stdout_pair" if isinstance(coverage.target, PythonTaskTargetV1)
                    else "independent_declared_task_duplicate_order_pair"})
        self.conn.execute(
            f"""INSERT INTO {TABLE}
               (id,user_id,epoch,scope_id,job_id,lease_generation,lease_state_version,lease_owner,
                generation_artifact_id,version_id,source_hash,content_hash,payload_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (receipt.receipt_id,receipt.user_id,receipt.epoch,receipt.scope_id,lease.job_id,lease.generation,
             lease.state_version,lease.lease_owner,receipt.generation_artifact_id,receipt.version_id,
             prepared_review.source.source_hash,prepared_review.source.content_hash,Jsonb(receipt.model_dump(mode="json"))),
        )
        self._issued[receipt.receipt_id] = receipt
        return receipt

    def verify(self, receipt: IssuedAdmissionFactsV1, prepared_review: PreparedReview, *, lease: JobLeaseV1,
               completed_review: CompletedReview) -> AdmissionEvidenceV2:
        receipt = checked_model(receipt,IssuedAdmissionFactsV1)
        self._transaction()
        if self._issued.get(receipt.receipt_id) != receipt:
            raise AdmissionFactsPending("admission_facts_owner_receipts_unavailable")
        row = self.conn.execute(f"SELECT payload_json,payload_hash FROM {TABLE} WHERE id=%s AND user_id=%s AND epoch=%s FOR SHARE",
            (receipt.receipt_id,lease.owner_id,lease.owner_epoch)).fetchone()
        if (row is None or row["payload_json"] != receipt.model_dump(mode="json")
                or row["payload_hash"] != receipt.receipt_hash or receipt.scope_id != prepared_review.scope_id
                or receipt.generation_artifact_id != prepared_review.artifact_id
                or receipt.user_id != lease.owner_id or receipt.epoch != lease.owner_epoch
                or receipt.lease.generation != lease.generation or receipt.lease.state_version != lease.state_version
                or receipt.lease.job_id != lease.job_id or receipt.lease.lease_owner != lease.lease_owner):
            raise AdmissionFactsPending("admission_facts_receipt_stale")
        coverage,evidence = self._build(prepared_review,lease,receipt.ambiguity,
            completed_review=completed_review,
            checked_at=receipt.coverage.checked_at,valid_until=receipt.coverage.valid_until)
        if coverage != receipt.coverage or evidence != receipt.evidence:
            raise AdmissionFactsPending("admission_facts_changed")
        return evidence


def build_admission_evidence(conn: Connection[dict[str,Any]], *, prepared_review: PreparedReview,
                             lease: JobLeaseV1, facts_owner: AdmissionFactsOwner,
                             ambiguity_receipt: TaskAmbiguityReceiptV1,
                             completed_review: CompletedReview) -> IssuedAdmissionFactsV1:
    if type(facts_owner) is not AdmissionFactsOwner or facts_owner.conn is not conn:
        raise AdmissionFactsPending("admission_facts_owner_missing")
    return facts_owner.issue(prepared_review,lease=lease,ambiguity_receipt=ambiguity_receipt,
        completed_review=completed_review)
