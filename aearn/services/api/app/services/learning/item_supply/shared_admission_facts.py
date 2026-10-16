"""Default-off native PUBLIC final facts. No IO, publication, or inventory authority.

Only the original same-process validation/review owners can issue or refresh a
fence. 493 stores audit projections, never reconstructible runner capabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sys
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.admission import evaluate_admission
from app.services.learning.item_supply.admission_facts_contracts import RunnerTerminalProofV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.finite_task_ambiguity import FiniteTaskAmbiguityOwner
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvidenceV2, ProbeOutcomeV2, check_subject, execution_receipt_digest,
)
from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort
from app.services.learning.item_supply.shared_admission_facts_contracts import (
    IssuedSharedAdmissionFactsV1, SharedClauseProofV1, SharedFactsBudgetV1, SharedTargetProofV1,
)
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.shared_review import PreparedSharedReview, SharedReviewPipeline, SharedReviewResult
from app.services.learning.item_supply.shared_validation import SharedValidationPipeline
from app.services.learning.item_supply.shared_validation_contracts import PreparedSharedValidation, SharedValidationResult
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.diagnostic_policy import policy_for_hash
from app.services.learning.item_supply.validation_adapter import validate_candidate
from app.services.learning.item_supply.validators.profiles import required_probes

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
    from app.services.learning.item_supply.committed_admission_quality import CommittedChildQuality
    from app.services.learning.item_supply.committed_admission_facts import CommittedQualityObservation
    from app.services.learning.item_supply.native_normal_revision_readmission import (
        NativeNormalRevisionReadmissionOwner, PreparedNormalRevisionReadmission,
    )

TABLE = "tutor_item_supply_shared_admission_facts"
_PROBES = {"correct": "reference", "incorrect": "starter_rejected", "equivalent": "equivalent",
           "known_wrong": "wrong_rejected", "boundary": "boundary", "scorer_counterexample": "scorer_counterexample"}


class SharedAdmissionFactsPending(PipelineRepositoryError):
    """Absent/stale original authority is pending, not a synthetic successful fact."""


@dataclass(frozen=True)
class _Originals:
    validation_prepared: PreparedSharedValidation
    validation_result: SharedValidationResult
    validation_receipt_id: UUID
    review_prepared: PreparedSharedReview
    review_result: SharedReviewResult
    blind_receipt_id: UUID
    review_receipt_id: UUID
    normal_readmission: PreparedNormalRevisionReadmission | None = None


def _target_proof(p: PreparedSharedReview | CommittedChildQuality, result: SharedReviewResult | CommittedQualityObservation,
                  machine_hashes: tuple[str, ...]) -> SharedTargetProofV1 | None:
    """Pure composition AFTER concrete owner verification; no authority on its own.

    A finite scorer checks a conjunction of all three registered clauses. Each
    mapping binds that complete check, not a guessed general-family capability.
    """
    if result.bundle is None or result.blind is None or result.ambiguity is None:
        return None
    reports = {r.role.value: r for r in result.bundle.reports}
    roles = ("curriculum", "technical", "ambiguity")
    if any(role not in reports or reports[role].material_failure for role in roles):
        return None
    # A contested coverage/interpretation finding cannot become coverage merely
    # because its author gave it a minor severity or an overall approved vote.
    contested = {"coverage_gap", "curriculum_mismatch", "technical_failure", "ambiguity", "rubric_mismatch", "profile_gap", "unique_answer"}
    if any(f.safe_code in contested for r in result.bundle.reports for f in r.findings):
        return None
    target = get_finite_course_target(p.spec.target_id)
    if (target.definition_hash != p.spec.target_definition_hash or not machine_hashes
            or tuple((c.clause_id, c.clause_hash) for c in p.spec.coverage_blueprint.clauses)
            != tuple((c.clause_id.lower(), c.definition_hash) for c in target.clauses)):
        raise SharedAdmissionFactsPending("SHARED_REGISTERED_CLAUSES_MISMATCH")
    interpretation_hash = canonical_hash(result.ambiguity.plan.interpretation.model_dump(mode="json"))
    return SharedTargetProofV1(target_id=target.target_id, target_definition_hash=target.definition_hash,
        specification_hash=p.spec.specification_hash, source_hash=p.source.source_hash,
        public_task_hash=p.inputs.public_task_hash, instance_hash=p.inputs.instance_hash,
        coverage_blueprint_hash=p.spec.coverage_blueprint.blueprint_hash,
        inputs_hash=canonical_hash(p.inputs.model_dump(mode="json")), validation_receipt_hash=p.validation.evidence_hash,
        blind_receipt_hash=result.blind.receipt_hash, ambiguity_receipt_hash=result.ambiguity.receipt_hash,
        mappings=tuple(SharedClauseProofV1(clause_id=c.clause_id.lower(), clause_hash=c.definition_hash,
            interpretation_hash=interpretation_hash, machine_proof_hashes=machine_hashes,
            curriculum_report_hash=reports["curriculum"].report_hash,
            technical_report_hash=reports["technical"].report_hash,
            ambiguity_report_hash=reports["ambiguity"].report_hash) for c in target.clauses))


class SharedAdmissionFactsOwner:
    def __init__(self, conn: Connection[dict[str, Any]], *, validation_pipeline: SharedValidationPipeline | None = None,
                 review_pipeline: SharedReviewPipeline | None = None, enabled: bool = False,
                 normal_readmission_owner: NativeNormalRevisionReadmissionOwner | None = None,
                 committed_admission: IssuedCommittedChildAdmission | None = None) -> None:
        self.conn, self.enabled = conn, enabled
        self.normal_readmission_owner: NativeNormalRevisionReadmissionOwner | None = normal_readmission_owner
        self._committed_admission = committed_admission
        self._committed_issued: dict[UUID, IssuedSharedAdmissionFactsV1] = {}
        self._committed_pending: IssuedSharedAdmissionFactsV1 | None = None
        if committed_admission is not None:
            from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
            if (type(committed_admission) is not IssuedCommittedChildAdmission or committed_admission.owner.conn is not conn
                    or validation_pipeline is not None or review_pipeline is not None or normal_readmission_owner is None
                    or normal_readmission_owner._committed_admission is not committed_admission):
                raise SharedAdmissionFactsPending("COMMITTED_ADMISSION_FACTS_ORIGINAL_OWNERS_REQUIRED")
            self.normal_readmission_owner = normal_readmission_owner
            self.artifacts = SharedPipelineArtifactRepository(conn,enabled=enabled)
            return
        if validation_pipeline is None or review_pipeline is None:
            raise SharedAdmissionFactsPending("SHARED_FACTS_CONCRETE_SAME_CONNECTION_OWNERS_REQUIRED")
        self.validation_pipeline, self.review_pipeline = validation_pipeline, review_pipeline
        self.artifacts = SharedPipelineArtifactRepository(conn, enabled=enabled)
        self._issued: dict[UUID, tuple[IssuedSharedAdmissionFactsV1, _Originals]] = {}
        self.normal_readmission_owner = normal_readmission_owner
        self._normal_pending: dict[UUID, tuple[IssuedSharedAdmissionFactsV1, _Originals]] = {}
        if normal_readmission_owner is not None:
            from app.services.learning.item_supply.native_normal_revision_readmission import NativeNormalRevisionReadmissionOwner
            if (type(normal_readmission_owner) is not NativeNormalRevisionReadmissionOwner
                    or normal_readmission_owner.conn is not conn
                    or normal_readmission_owner.recheck.validation is not validation_pipeline
                    or normal_readmission_owner.recheck.review is not review_pipeline):
                raise SharedAdmissionFactsPending("NORMAL_READMISSION_SAME_ORIGINAL_FACTS_OWNERS_REQUIRED")

    def _transaction(self) -> datetime:
        vp, rp = self.validation_pipeline, self.review_pipeline
        if (type(self) is not SharedAdmissionFactsOwner or not self.enabled
                or type(vp) is not SharedValidationPipeline or type(rp) is not SharedReviewPipeline
                or vp.conn is not self.conn or rp.conn is not self.conn
                or vp.settings is not rp.settings
                or not vp.validation_enabled or not rp.review_enabled or self.conn.autocommit
                or vp.continuation_owner is not rp.continuation_owner):
            raise SharedAdmissionFactsPending("SHARED_FACTS_CONCRETE_SAME_CONNECTION_OWNERS_REQUIRED")
        # Admission is independently gated on the shared operation settings.
        # Adoption needs neither new generation nor the legacy V1 review flag.
        if not vp.settings.learning_item_v2_admission_enabled:
            raise SharedAdmissionFactsPending("SHARED_FACTS_V2_ADMISSION_DISABLED")
        if self.normal_readmission_owner is not None:
            from app.services.learning.item_supply.native_normal_revision_readmission import NativeNormalRevisionReadmissionOwner
            normal = self.normal_readmission_owner
            if (type(normal) is not NativeNormalRevisionReadmissionOwner or normal.conn is not self.conn
                    or normal.recheck.validation is not vp or normal.recheck.review is not rp):
                raise SharedAdmissionFactsPending("NORMAL_READMISSION_SAME_ORIGINAL_FACTS_OWNERS_REQUIRED")
        self.artifacts.require_owner()
        return server_clock(self.conn, datetime.now(UTC))

    def _committed(self, receipt_id: UUID, kind: str, payload: Any, *, lease: JobLeaseV1,
                   artifact_id: UUID, continuation_hash: str | None) -> None:
        row = self.conn.execute(
            "SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s AND artifact_kind=%s "
            "AND generation_artifact_id=%s AND job_id=%s AND lease_generation=%s AND mode='live'",
            (receipt_id, kind, artifact_id, lease.job_id, lease.generation),
        ).fetchone()
        data = payload.model_dump(mode="json")
        if (row is None or row["same_transaction"] or row["payload_json"] != data
                or row["receipt_hash"] != canonical_hash(data) or row["lease_owner"] != lease.lease_owner
                or row["continuation_binding_hash"] != continuation_hash):
            raise SharedAdmissionFactsPending("SHARED_FACTS_COMMITTED_STAGE_RECEIPT_REQUIRED")

    def _budget(self, lease: JobLeaseV1, *, root_id: UUID, reservation_id: UUID, key: str,
                resources: ResourceAmounts, actual: ResourceAmounts | None,
                receipt_hash: str | None) -> SharedFactsBudgetV1:
        budget = self.validation_pipeline.budget
        reservation = budget._reservation_by_key(lease, key)
        if (reservation is None or UUID(str(reservation["id"])) != reservation_id
                or UUID(str(reservation["root_id"])) != root_id
                or reservation["lease_generation"] != lease.generation
                or budget._reservation_amounts(lease, reservation_id) != resources.as_dict()):
            raise SharedAdmissionFactsPending("SHARED_FACTS_RESERVATION_MISMATCH")
        row = self.conn.execute(
            "SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=%s AND settlement_key=%s",
            (reservation_id, key),
        ).fetchone()
        state: Literal["known", "unknown"] = "unknown" if actual is None else "known"
        if (row is None or row["same_transaction"] or row["usage_state"] != state
                or row["receipt_hash"] != receipt_hash or row["cost_amount"] is not None):
            raise SharedAdmissionFactsPending("SHARED_FACTS_COMMITTED_USAGE_REQUIRED")
        sid = UUID(str(row["id"]))
        amounts = budget._settlement_amounts("shared", sid)
        if amounts != ({} if actual is None else actual.as_dict()):
            raise SharedAdmissionFactsPending("SHARED_FACTS_USAGE_MISMATCH")
        return SharedFactsBudgetV1(reservation_id=reservation_id, settlement_id=sid,
            settlement_key=key, reserved=resources, usage_state=state, actual=actual, receipt_hash=receipt_hash)

    @staticmethod
    def _runner(port: SandboxCandidateExecutionPort | None) -> RunnerPort | None:
        if port is None:
            return None
        if type(port) is not SandboxCandidateExecutionPort:
            raise SharedAdmissionFactsPending("SHARED_FACTS_ORIGINAL_EXECUTION_PORT_REQUIRED")
        bridge = getattr(sys.modules.get("aearn_executor.item_supply_bridge"), "ItemSupplyRunnerBridge", None)
        client = getattr(sys.modules.get("aearn_executor.docker_client"), "DockerContainerRuntimeClient", None)
        runner = port._runner
        if (bridge is None or client is None or type(runner) is not bridge
                or getattr(runner, "_live", None) is not True or type(getattr(runner, "_client", None)) is not client):
            raise SharedAdmissionFactsPending("SHARED_FACTS_ACTUAL_ORIGINAL_RUNNER_REQUIRED")
        return runner

    def _machine(self, o: _Originals, port: SandboxCandidateExecutionPort | None,
                 runner: RunnerPort | None) -> tuple[tuple[RunnerTerminalProofV1, ...], tuple[RunnerTerminalProofV1, ...],
                                                     dict[str, int], tuple[ProbeOutcomeV2, ...], tuple[str, ...], ResourceAmounts]:
        p, result = o.review_prepared, o.review_result
        validation = o.validation_result.validation
        if result.blind is None or result.bundle is None or result.ambiguity is None or validation is None:
            raise SharedAdmissionFactsPending("SHARED_FACTS_COMPLETE_ORIGINAL_RESULTS_REQUIRED")
        # This is the peer's funded/cached concrete owner API, not a caller bool.
        verified = SharedReviewPipeline.verified_review_evidence(self.review_pipeline, p, result, runner=runner)
        if (verified.binding != p.binding or verified.blind != result.blind
                or verified.bundle != result.bundle or verified.ambiguity != result.ambiguity):
            raise SharedAdmissionFactsPending("SHARED_FACTS_REVIEW_PROJECTION_CHANGED")
        scorer = SharedReviewPipeline._result(self.review_pipeline, p, result)
        review_runner, ambiguity_owner = SharedReviewPipeline._ambiguity_context(self.review_pipeline, p)
        if review_runner is not runner or type(ambiguity_owner) is not FiniteTaskAmbiguityOwner:
            raise SharedAdmissionFactsPending("SHARED_FACTS_SAME_RUNNER_REQUIRED")
        ambiguity_usage, ambiguity_proofs = FiniteTaskAmbiguityOwner.verified_evidence(
            ambiguity_owner, result.ambiguity, p.source, spec=p.spec, inputs=p.inputs, runner=runner)
        if ambiguity_proofs != verified.ambiguity_terminals:
            raise SharedAdmissionFactsPending("SHARED_FACTS_AMBIGUITY_PROJECTION_CHANGED")
        outcomes: tuple[ProbeOutcomeV2, ...]
        if p.inputs.static_facts is not None:
            facts = p.inputs.static_facts
            if (port is not None or runner is not None or type(scorer) is not FiniteStaticBlindScorer
                    or not FiniteStaticBlindScorer.verify(scorer, result.blind.score, p.source)
                    or validation != facts.validation or validation.mode != "static"
                    or verified.blind_terminals or ambiguity_proofs or verified.execution_usage != ResourceAmounts()):
                raise SharedAdmissionFactsPending("SHARED_STATIC_FACTS_MISMATCH")
            # Bind the ACTUAL provider answer held by the original scorer, not an
            # expected answer copied from the source or receipt passed boolean.
            issued = scorer._issued.get(result.blind.score.receipt_hash)
            if issued is None or canonical_hash(issued[2]) != result.blind.solution_hash:
                raise SharedAdmissionFactsPending("SHARED_STATIC_BLIND_ANSWER_MISMATCH")
            counts = {"positive_cases": sum(f.accepted for f in facts.options),
                      "negative_cases": sum(not f.accepted for f in facts.options),
                      "false_positives": 0, "false_negatives": 0, "pending_cases": 0}
            if counts["positive_cases"] != 1 or counts["negative_cases"] != 3:
                raise SharedAdmissionFactsPending("SHARED_STATIC_UNIQUE_PROPOSITIONS_REQUIRED")
            fh = canonical_hash(facts.model_dump(mode="json"))
            outcomes = tuple(ProbeOutcomeV2.model_validate({"probe": name, "passed": True,
                "receipt_hash": canonical_hash({"facts": fh, "options": [f.model_dump(mode="json") for f in facts.options if f.accepted == accepted]})})
                for name, accepted in (("correct", True), ("incorrect", False)))
            machine: tuple[str, ...] = (fh,)
            validation_proofs: tuple[RunnerTerminalProofV1, ...] = ()
            blind_proofs: tuple[RunnerTerminalProofV1, ...] = ()
            blind_usage = ResourceAmounts()
        else:
            execution = validation.execution_evidence
            if (port is None or runner is None or execution is None or type(scorer) is not SandboxBlindAnswerScorer
                    or scorer._runner is not runner or scorer._finite_spec != p.spec
                    or port._finite_spec != p.spec or port._plan != p.inputs.probe_plan
                    or port._source_runs.get(p.source.source_hash) != execution.run_id
                    or not SandboxCandidateExecutionPort.verify(port, execution, p.source)
                    or not SandboxBlindAnswerScorer.verify(scorer, result.blind.score, p.source)):
                raise SharedAdmissionFactsPending("SHARED_FACTS_ORIGINAL_EXECUTION_UNVERIFIED")
            SharedValidationPipeline._verify_terminal(o.validation_prepared, o.validation_result, port)
            if validate_candidate(p.source, execution_port=port, finite_spec=p.spec) != validation:
                raise SharedAdmissionFactsPending("SHARED_FACTS_VALIDATION_CHANGED")
            run = port._runs[execution.run_id]
            blind_run = scorer._issued[result.blind.score.receipt_hash]
            ambiguity_run = ambiguity_owner._runs[result.ambiguity.run_id]
            pairs = [(receipt, task.wire) for task, receipt in zip(run.tasks, run.receipts, strict=True)]
            pairs.append((blind_run.receipt, blind_run.request))
            a_requests = (result.ambiguity.plan.correct, result.ambiguity.plan.alternative)
            if any(request is None for request in a_requests):
                raise SharedAdmissionFactsPending("SHARED_FACTS_AMBIGUITY_WIRES_MISSING")
            pairs.extend((receipt, request) for receipt, request in zip(ambiguity_run[0], a_requests, strict=True) if request is not None)
            if any(not type(runner).verify(runner, receipt, request=request) for receipt, request in pairs):
                raise SharedAdmissionFactsPending("SHARED_FACTS_ORIGINAL_BRIDGE_SEAL_INVALID")
            if (any(receipt.lock_fingerprint != p.spec.coverage_blueprint.scope.runtime_profile_hash for receipt, _ in pairs)
                    or execution.scorer_version != p.spec.coverage_blueprint.scope.scorer_version
                    or result.blind.score.scorer_version != execution.scorer_version
                    or canonical_hash(blind_run.request.submission) != result.blind.solution_hash):
                raise SharedAdmissionFactsPending("SHARED_FACTS_RUNTIME_SCORER_OR_ANSWER_MISMATCH")
            # Infrastructure failure is not an incorrect-answer semantic proof.
            for name in ("starter_rejected", "wrong_rejected", "boundary"):
                terminal = next((t for t in run.receipts if t.probe_name == name), None)
                try:
                    cases = [] if terminal is None else json.loads(terminal.result.stdout)["cases"]
                    code = "python_terminal" if p.spec.python_goal is not None else "sqlite_terminal"
                    if not cases or any(c["status"] != "success" or c["code"] != code for c in cases):
                        raise ValueError("semantic terminal missing")
                except (ValueError, KeyError, TypeError):
                    raise SharedAdmissionFactsPending("SHARED_FACTS_SEMANTIC_REJECTION_PENDING") from None
            probes = {probe.name: probe for probe in execution.probes}
            if tuple(probes) != required_probes(p.source, finite_spec=p.spec) or any(probe.status != "passed" for probe in probes.values()):
                raise SharedAdmissionFactsPending("SHARED_FACTS_NATIVE_PROFILE_INCOMPLETE")
            counts = SandboxCandidateExecutionPort.scorer_counts(port, execution)
            if not counts["positive_cases"] or not counts["negative_cases"] or counts["pending_cases"]:
                raise SharedAdmissionFactsPending("SHARED_FACTS_SCORER_INCOMPLETE")
            outcomes = tuple(ProbeOutcomeV2.model_validate({"probe": name, "passed": probes[raw].status == "passed",
                "receipt_hash": probes[raw].proof_hash}) for name, raw in _PROBES.items())
            machine = tuple(probe.proof_hash for probe in execution.probes)
            validation_proofs = tuple(RunnerTerminalProofV1.model_validate_json(json.dumps(t.to_payload())) for t in run.receipts)
            blind_proofs = (RunnerTerminalProofV1.model_validate_json(json.dumps(blind_run.receipt.to_payload())),)
            blind_usage = SandboxBlindAnswerScorer.resource_usage(scorer, result.blind.score)
            if blind_proofs != verified.blind_terminals:
                raise SharedAdmissionFactsPending("SHARED_FACTS_BLIND_PROJECTION_CHANGED")
        usage = ResourceAmounts(execution_seconds=blind_usage.execution_seconds + ambiguity_usage.execution_seconds)
        if usage != verified.execution_usage or usage.execution_seconds > p.resources.execution_seconds:
            raise SharedAdmissionFactsPending("SHARED_FACTS_REVIEW_EXECUTION_USAGE_MISMATCH")
        outcomes += (ProbeOutcomeV2(probe="ambiguity", passed=True, receipt_hash=result.ambiguity.receipt_hash),)
        return validation_proofs, blind_proofs, counts, outcomes, machine, usage

    def _build(self, o: _Originals, *, lease: JobLeaseV1, receipt_id: UUID,
               checked_at: datetime | None = None, valid_until: datetime | None = None) -> IssuedSharedAdmissionFactsV1:
        now = self._transaction()
        lease = checked_model(lease, JobLeaseV1)
        vp, rp = self.validation_pipeline, self.review_pipeline
        v, p, result = o.validation_prepared, o.review_prepared, o.review_result
        authority, _ = SharedValidationPipeline._issued(vp, v)
        port = SharedValidationPipeline._result(vp, v, o.validation_result)
        review_authority, _, _, _ = SharedReviewPipeline._issued(rp, p)
        if type(authority) is not RagSourceAuthority or review_authority is not authority:
            raise SharedAdmissionFactsPending("SHARED_FACTS_SAME_CURRENT_SOURCE_OWNER_REQUIRED")
        if (p.lease != lease or v.lease.job_id != lease.job_id or v.lease.generation != lease.generation
                or v.lease.lease_owner != lease.lease_owner or v.lease.profile != lease.profile
                or v.artifact_id != p.artifact_id or v.artifact_hash != p.artifact_hash
                or v.request != p.request or v.source != p.source or v.spec != p.spec or v.inputs != p.inputs
                or o.validation_receipt_id != p.validation_receipt_id or o.validation_result.validation != p.validation):
            raise SharedAdmissionFactsPending("SHARED_FACTS_ORIGINAL_CONTEXT_MISMATCH")
        resolved = self.artifacts.resolve_generation(lease=lease, artifact_id=p.artifact_id, now=now,
            source_authority=authority, spec=p.spec, continuation_owner=rp.continuation_owner)
        a = resolved.artifact
        controlled_schema = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_controlled_counterexample_preparations') AS p, "
            "to_regprocedure('item_supply_internal.controlled_counterexample_held(uuid)') AS guard").fetchone()
        if controlled_schema is not None and controlled_schema["p"] is not None:
            if controlled_schema["guard"] is None:
                raise SharedAdmissionFactsPending("SHARED_CONTROLLED_EXPERIMENT_HELD")
            held = self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(%s) AS held",
                (a["job_id"],)).fetchone()
            if held is None or held["held"] is not False:
                raise SharedAdmissionFactsPending("SHARED_CONTROLLED_EXPERIMENT_HELD")
        revision_schema = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_revision_preparations') AS p, "
            "to_regprocedure('item_supply_internal.native_revision_descendant(uuid)') AS guard").fetchone()
        if revision_schema is not None and revision_schema["p"] is not None:
            if revision_schema["guard"] is None:
                raise SharedAdmissionFactsPending("SHARED_REVISION_DISCHARGE_OWNER_PENDING")
            descendant = self.conn.execute("SELECT item_supply_internal.native_revision_descendant(%s) AS revision",
                (a["job_id"],)).fetchone()
            if descendant is None:
                raise SharedAdmissionFactsPending("SHARED_REVISION_DISCHARGE_OWNER_PENDING")
            if descendant["revision"] is not False:
                owner, permit = self.normal_readmission_owner, o.normal_readmission
                if owner is None or permit is None:
                    raise SharedAdmissionFactsPending("SHARED_REVISION_DISCHARGE_OWNER_PENDING")
                current_child = owner.verify_context(permit, lease=lease)
                if (current_child.validation_prepared is not v or current_child.validation_result is not o.validation_result
                        or current_child.review_prepared is not p or current_child.review_result is not result
                        or (current_child.validation_receipt_id, current_child.blind_receipt_id, current_child.review_receipt_id)
                        != (o.validation_receipt_id, o.blind_receipt_id, o.review_receipt_id)):
                    raise SharedAdmissionFactsPending("NORMAL_READMISSION_ORIGINAL_CHILD_INPUTS_MISMATCH")
            elif o.normal_readmission is not None:
                raise SharedAdmissionFactsPending("NORMAL_READMISSION_REVISION_DESCENDANT_REQUIRED")
        continuation_hash = None if resolved.continuation_binding is None else resolved.continuation_binding.binding_hash
        meta = self.artifacts.context(lease, now=now)
        if (resolved.lease != lease or resolved.source != p.source or resolved.request != p.request
                or a["artifact_hash"] != p.artifact_hash or meta["coverage"] != p.spec.coverage_blueprint
                or UUID(str(meta["root_id"])) != UUID(str(a["root_id"]))
                or vp._continuation_bindings.get(v.preparation_id) != continuation_hash
                or p.binding.candidate_key != str(a["item_id"]) or p.binding.version_key != str(a["version_id"])
                or p.binding.profile_hash != lease.profile.profile_hash
                or p.binding.policy_hash != self.artifacts.generation_policy(lease, p.request, now=now).policy_hash):
            raise SharedAdmissionFactsPending("SHARED_FACTS_NATIVE_ARTIFACT_MISMATCH")
        SharedReviewPipeline._fence(rp, p)
        inputs = prepare_finite_candidate_validation(p.source, spec=p.spec, materials=p.request.materials)
        if inputs != p.inputs or result.blind is None or result.bundle is None or result.ambiguity is None:
            raise SharedAdmissionFactsPending("SHARED_FACTS_INPUTS_OR_REVIEW_PENDING")
        self._committed(o.validation_receipt_id, "validation", p.validation, lease=lease,
                        artifact_id=p.artifact_id, continuation_hash=continuation_hash)
        self._committed(o.blind_receipt_id, "blind_solve", result.blind, lease=lease,
                        artifact_id=p.artifact_id, continuation_hash=continuation_hash)
        self._committed(o.review_receipt_id, "review_bundle", result.bundle, lease=lease,
                        artifact_id=p.artifact_id, continuation_hash=continuation_hash)
        row = self.conn.execute(
            "SELECT e.payload_hash,p.payload_hash AS preparation_hash,e.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_validation_evidence e JOIN tutor_item_supply_shared_validation_preparations p "
            "ON p.id=e.preparation_id WHERE p.id=%s", (v.preparation_id,),
        ).fetchone()
        if (row is None or row["same_transaction"] or row["preparation_hash"] != canonical_hash(vp._payload(v))
                or row["payload_hash"] != canonical_hash(vp._result_payload(o.validation_result))):
            raise SharedAdmissionFactsPending("SHARED_FACTS_COMMITTED_VALIDATION_EVIDENCE_REQUIRED")
        runner = self._runner(port)
        with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
            check_subject(p.source, p.binding, p.validation)
            terminals, blind_terminals, counts, outcomes, machine, review_usage = self._machine(o, port, runner)
        root_id = UUID(str(a["root_id"]))
        validation_budget = None
        if port is not None:
            if v.reservation_id is None or v.resources is None or o.validation_result.actual is None:
                raise SharedAdmissionFactsPending("SHARED_FACTS_VALIDATION_BUDGET_MISSING")
            validation_budget = self._budget(lease, root_id=root_id, reservation_id=v.reservation_id,
                key=f"shared.execution.{v.preparation_id.hex}", resources=v.resources, actual=o.validation_result.actual,
                receipt_hash=canonical_hash({"receipts": o.validation_result.terminal_receipts}))
        review_budget = self._budget(lease, root_id=root_id, reservation_id=p.reservation_id,
            key=f"review.{p.artifact_id.hex}", resources=p.resources, actual=None, receipt_hash=None)
        expiry_bounds = [lease.expires_at, lease.parent_deadline, lease.profile.parent_deadline_at, result.ambiguity.parent_deadline_at]
        if o.normal_readmission is not None:
            expiry_bounds.append(o.normal_readmission.valid_until)
        if port is not None:
            scorer = SharedReviewPipeline._result(rp, p, result)
            if port._deadline is None or type(scorer) is not SandboxBlindAnswerScorer:
                raise SharedAdmissionFactsPending("SHARED_FACTS_RUNTIME_DEADLINE_MISSING")
            expiry_bounds.extend((port._deadline, scorer._deadline))
        claims: set[str] = set()
        for material, expected in zip(p.request.materials, resolved.receipt.sources, strict=True):
            current = RagSourceAuthority.assert_current(authority, material, expected)
            claims.update(current.claim_receipt_hashes)
            reviews = authority._current.governance.source_reviews
            coordinate = material.binding.evidence[0].binding
            review = None if reviews is None else reviews.resolve(coordinate.source_handle, coordinate.document_handle)
            if review is None or review.grant is None:
                raise SharedAdmissionFactsPending("SHARED_FACTS_CURRENT_C_MISSING")
            expiry_bounds.append(review.grant.retained_until)
        bound = min(expiry_bounds)
        stamp, expiry = now if checked_at is None else checked_at, bound if valid_until is None else valid_until
        if not claims or not stamp <= now < expiry <= bound:
            raise SharedAdmissionFactsPending("SHARED_FACTS_EXPIRED")
        proof = _target_proof(p, result, machine)
        evidence = AdmissionEvidenceV2(binding=p.binding, validation_receipt_hash=p.validation.evidence_hash,
            source_current=True, source_claim_receipt_hashes=tuple(sorted(claims)),
            coverage_proof_hash=None if proof is None else proof.proof_hash, probes=outcomes,
            execution_receipt_hash=execution_receipt_digest(p.validation), execution_isolated=port is not None,
            runner_available=runner is not None, scorer_available=True,
            known_misjudgments=counts["false_positives"] + counts["false_negatives"])
        with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
            evaluation = evaluate_admission(p.source, binding=p.binding, policy=policy_for_hash(p.binding.policy_hash),
                validation_receipt=p.validation, author_identity=p.author_identity,
                bundle=result.bundle, evidence=evidence, enabled=True)
        if evaluation.evidence_hash != canonical_hash(evidence.model_dump(mode="json")):
            raise SharedAdmissionFactsPending("SHARED_FACTS_ADMISSION_CONTEXT_INVALID")
        # Last fence after reads/composition; no lease/deadline renewal.
        end = server_clock(self.conn, now)
        self.artifacts.runtime._control(lease, now=end)
        if end >= expiry:
            raise SharedAdmissionFactsPending("SHARED_FACTS_EXPIRED")
        scope = p.spec.coverage_blueprint.scope
        return IssuedSharedAdmissionFactsV1(receipt_id=receipt_id, root_id=root_id,
            generation_artifact_id=p.artifact_id, artifact_hash=p.artifact_hash,
            item_id=UUID(str(a["item_id"])), version_id=UUID(str(a["version_id"])), lease=lease,
            continuation_binding_hash=continuation_hash, target_id=p.spec.target_id,
            target_definition_hash=p.spec.target_definition_hash, specification_hash=p.spec.specification_hash,
            public_task_hash=inputs.public_task_hash, instance_hash=inputs.instance_hash,
            inputs_hash=canonical_hash(inputs.model_dump(mode="json")), coverage_blueprint_hash=p.spec.coverage_blueprint.blueprint_hash,
            profile_hash=lease.profile.profile_hash, runtime_profile_hash=scope.runtime_profile_hash,
            scorer_version=scope.scorer_version, validation_preparation_id=v.preparation_id,
            validation_receipt_id=o.validation_receipt_id, blind_receipt_id=o.blind_receipt_id,
            review_receipt_id=o.review_receipt_id, validation_receipt_hash=p.validation.evidence_hash,
            blind_receipt_hash=result.blind.receipt_hash, review_receipt_hash=result.bundle.bundle_hash,
            validation_budget=validation_budget, review_budget=review_budget, review_execution_usage=review_usage,
            validation_terminals=terminals, blind_terminals=blind_terminals, ambiguity=result.ambiguity,
            scorer_counts=counts, target_proof=proof, evidence=evidence, evaluation=evaluation,
            checked_at=stamp, valid_until=expiry)

    def issue(self, *, lease: JobLeaseV1, validation_prepared: PreparedSharedValidation,
              validation_result: SharedValidationResult, validation_receipt_id: UUID,
              review_prepared: PreparedSharedReview, review_result: SharedReviewResult,
              blind_receipt_id: UUID, review_receipt_id: UUID,
              normal_readmission: PreparedNormalRevisionReadmission | None = None) -> IssuedSharedAdmissionFactsV1:
        originals = _Originals(validation_prepared, validation_result, validation_receipt_id,
                               review_prepared, review_result, blind_receipt_id, review_receipt_id, normal_readmission)
        # No issuance replay with a newly chosen expiry. Caller can verify its
        # original fact, but cannot renew it under the same stage receipts.
        if any(o.review_receipt_id == review_receipt_id for _, o in self._issued.values()):
            raise SharedAdmissionFactsPending("SHARED_FACTS_ALREADY_ISSUED_USE_VERIFY")
        facts = self._build(originals, lease=lease, receipt_id=uuid4() if normal_readmission is None else normal_readmission.receipt_id)
        if normal_readmission is not None:
            owner = self.normal_readmission_owner
            if owner is None:
                raise SharedAdmissionFactsPending("NORMAL_READMISSION_ORIGINAL_OWNER_REQUIRED")
            # Original full source/machine/coverage/risk evaluation already ran.
            # SQL sees this sealed side receipt BEFORE the unchanged facts INSERT.
            self._normal_pending[facts.receipt_id] = (facts, originals)
            try:
                owner.persist(normal_readmission, facts_owner=self, facts=facts)
            finally:
                self._normal_pending.pop(facts.receipt_id, None)
        row = self.conn.execute(
            f"INSERT INTO {TABLE}(id,root_id,job_id,lease_owner,lease_generation,lease_state_version,profile_hash,"
            "generation_artifact_id,item_id,version_id,source_hash,content_hash,continuation_binding_hash,"
            "validation_preparation_id,validation_receipt_id,blind_receipt_id,review_receipt_id,payload_json) "
            "VALUES(" + ",".join(["%s"] * 18) + ") RETURNING payload_hash",
            (facts.receipt_id, facts.root_id, lease.job_id, lease.lease_owner, lease.generation, lease.state_version,
             facts.profile_hash, facts.generation_artifact_id, facts.item_id, facts.version_id,
             facts.evidence.binding.source_hash, facts.evidence.binding.content_hash, facts.continuation_binding_hash,
             facts.validation_preparation_id, validation_receipt_id, blind_receipt_id, review_receipt_id,
             Jsonb(facts.model_dump(mode="json"))),
        ).fetchone()
        if row is None or row["payload_hash"] != facts.receipt_hash:
            raise SharedAdmissionFactsPending("SHARED_FACTS_STORAGE_HASH_MISMATCH")
        self._issued[facts.receipt_id] = (facts, originals)
        return facts

    def verify(self, facts: IssuedSharedAdmissionFactsV1, *, lease: JobLeaseV1) -> AdmissionEvidenceV2:
        if self._committed_admission is not None:
            from app.services.learning.item_supply.committed_admission_facts import verify
            return verify(self,facts,lease=lease)
        self._transaction()
        facts = checked_model(facts, IssuedSharedAdmissionFactsV1)
        original = self._issued.get(facts.receipt_id)
        if original is None or original[0] != facts or facts.lease != checked_model(lease, JobLeaseV1):
            raise SharedAdmissionFactsPending("SHARED_FACTS_ORIGINAL_ISSUER_REQUIRED")
        row = self.conn.execute(f"SELECT payload_json,payload_hash FROM {TABLE} WHERE id=%s FOR SHARE", (facts.receipt_id,)).fetchone()
        if row is None or row["payload_json"] != facts.model_dump(mode="json") or row["payload_hash"] != facts.receipt_hash:
            raise SharedAdmissionFactsPending("SHARED_FACTS_PERSISTED_RECEIPT_MISMATCH")
        current = self._build(original[1], lease=lease, receipt_id=facts.receipt_id,
                              checked_at=facts.checked_at, valid_until=facts.valid_until)
        if current != facts:
            raise SharedAdmissionFactsPending("SHARED_FACTS_CURRENT_EVIDENCE_CHANGED")
        if original[1].normal_readmission is not None:
            if self.normal_readmission_owner is None:
                raise SharedAdmissionFactsPending("NORMAL_READMISSION_ORIGINAL_OWNER_REQUIRED")
            self.normal_readmission_owner.verify_persisted(original[1].normal_readmission, facts=facts)
        return facts.evidence

    def preview_committed(self, frame: IssuedCommittedChildAdmission) -> IssuedSharedAdmissionFactsV1:
        """Full evaluation DATA in caller rollback; not a facts issuance or publication permit."""
        from app.services.learning.item_supply.committed_admission_facts import build
        return build(self,frame,committed=False)

    def issue_committed(self, frame: IssuedCommittedChildAdmission) -> IssuedSharedAdmissionFactsV1:
        from app.services.learning.item_supply.committed_admission_facts import issue
        return issue(self,frame)
