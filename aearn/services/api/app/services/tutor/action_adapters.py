"""Adapters that preserve existing capability and execution authorities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from psycopg import Connection

from app.agents.harness.actions import (
    ActionAuthorityKind,
    ActionAuthorityReference,
    ActionDescriptor,
    ActionFence,
    ActionExecutionResult,
    ActionExecutionStatus,
    ActionLifecycleStatus,
    ActionResourceRequest,
    ActionVerificationResult,
    ActionVerificationStatus,
    build_action_invocation,
    default_action_descriptors,
)
from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorLease,
    TutorPayloadField,
    TutorRunSnapshot,
    payload_mapping_from_fields,
)
from app.agents.harness.skill_catalog import SkillCatalogSnapshot
from app.services.learning.planning_facts import PostgresPlanningFactRepository
from app.services.tutor.action_runtime import (
    ActionReceiptStore,
    ActionVerifier,
    ControlledActionRuntime,
)
from app.services.tutor.capability_policy import CapabilityPolicyResolver
from app.services.tutor.ports import Clock, TutorCapabilityGateway
from app.services.tutor.skill_selection import TutorSkillSelectionStore


class CapabilityInvocationRecorder(Protocol):
    def record_capability_invocation(
        self,
        *,
        user_id: str,
        run_id: str,
        lease: TutorLease,
        input_revision: int,
        request: TutorCapabilityRequest,
        result: TutorCapabilityResult,
        capability_version: str,
        catalog_digest: str,
        policy_fingerprint: str,
        duration_ms: int = 0,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ExistingExecutionJobEvidence:
    job_id: str
    state: str
    evidence_hash: str


class ExistingExecutionJobReader(Protocol):
    def read_action_job(
        self,
        *,
        user_id: str,
        intent_proof_id: str,
    ) -> ExistingExecutionJobEvidence | None: ...


class PostgresExistingExecutionJobReader:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def read_action_job(
        self,
        *,
        user_id: str,
        intent_proof_id: str,
    ) -> ExistingExecutionJobEvidence | None:
        row = self._conn.execute(
            """
            SELECT id::text AS id, state, result_hash, lock_fingerprint,
                   source_reference_hash, test_reference_hash
            FROM tutor_execution_jobs
            WHERE user_id = %s AND intent_id = %s
            """,
            (user_id, intent_proof_id),
        ).fetchone()
        if row is None:
            return None
        evidence_hash = str(row.get("result_hash") or "")
        if len(evidence_hash) != 64:
            evidence_hash = _hash_mapping(
                {
                    "job_id": str(row["id"]),
                    "state": str(row["state"]),
                    "lock_fingerprint": str(row["lock_fingerprint"]),
                    "source_reference_hash": str(row["source_reference_hash"]),
                    "test_reference_hash": str(row["test_reference_hash"]),
                }
            )
        return ExistingExecutionJobEvidence(
            job_id=str(row["id"]),
            state=str(row["state"]),
            evidence_hash=evidence_hash,
        )


class ExistingExecutionJobActionAdapter:
    """Read an already-created durable job; never launch a process or create authority."""

    def __init__(self, reader: ExistingExecutionJobReader) -> None:
        self._reader = reader

    def execute(self, invocation):
        proof_id = str(invocation.arguments.get("intent_proof_id") or "")
        evidence = self._reader.read_action_job(
            user_id=invocation.user_id,
            intent_proof_id=proof_id,
        )
        if evidence is None:
            return ActionExecutionResult(
                status=ActionExecutionStatus.RETRYABLE_FAILED,
                safe_summary="Execution job authority is not available yet.",
                diagnostic_code="execution_job_retryable",
            )
        authority = ActionAuthorityReference(
            ActionAuthorityKind.EXECUTION_JOB,
            evidence.job_id,
            evidence.evidence_hash,
        )
        if evidence.state in {"pending", "claimed", "launch_reserved", "running"}:
            return ActionExecutionResult(
                status=ActionExecutionStatus.RETRYABLE_FAILED,
                authority=authority,
                safe_summary="Execution job has not reached a terminal state.",
                diagnostic_code="execution_job_retryable",
            )
        if evidence.state == "timed_out":
            return ActionExecutionResult(
                status=ActionExecutionStatus.TIMED_OUT,
                authority=authority,
                safe_summary="Execution job reached its time limit.",
                diagnostic_code="execution_job_timed_out",
            )
        if evidence.state == "cancelled":
            return ActionExecutionResult(
                status=ActionExecutionStatus.CANCELLED,
                authority=authority,
                safe_summary="Execution job was cancelled.",
                diagnostic_code="execution_job_cancelled",
            )
        if evidence.state != "completed":
            return ActionExecutionResult(
                status=ActionExecutionStatus.PERMANENT_FAILED,
                authority=authority,
                safe_summary="Execution job did not complete successfully.",
                diagnostic_code="execution_job_failed",
            )
        return ActionExecutionResult(
            status=ActionExecutionStatus.SUCCEEDED,
            authority=authority,
            output={
                "status": "completed",
                "execution_job_id": evidence.job_id,
                "execution_state": evidence.state,
            },
            safe_summary="Durable execution job authority was verified.",
        )


class PostgresCapabilityAuthorityVerifier:
    """Verify the existing capability receipt instead of trusting adapter output."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def verify(self, *, descriptor, invocation, execution) -> ActionVerificationResult:
        authority = execution.authority
        if authority is None or authority.kind is not ActionAuthorityKind.CAPABILITY_INVOCATION:
            return _verification_failed(descriptor, authority, "capability_authority_missing")
        row = self._conn.execute(
            """
            SELECT status, result_hash, capability_id, capability_version, input_revision,
                   catalog_digest, policy_fingerprint
            FROM tutor_capability_invocations
            WHERE id = %s AND run_id = %s
            """,
            (authority.reference_id, invocation.run_id),
        ).fetchone()
        if (
            row is None
            or str(row["status"]) != "completed"
            or str(row["result_hash"]) != str(authority.reference_hash or "")
            or str(row["capability_id"]) != descriptor.action_id
            or str(row["capability_version"]) != descriptor.version
            or _as_int(row["input_revision"]) != invocation.input_revision
            or str(row["catalog_digest"]) != invocation.catalog_digest
            or str(row["policy_fingerprint"]) != invocation.policy_fingerprint
        ):
            return _verification_failed(descriptor, authority, "capability_authority_mismatch")
        try:
            descriptor.output_model.model_validate(execution.output or {})
        except ValueError:
            return _verification_failed(descriptor, authority, "action_output_invalid")
        return _verification_verified(descriptor, authority, "Capability authority receipt verified.")


class PostgresGroundingActionVerifier(PostgresCapabilityAuthorityVerifier):
    """Verify allowlisted citation identities bound to the capability receipt."""

    def verify(self, *, descriptor, invocation, execution) -> ActionVerificationResult:
        base = super().verify(
            descriptor=descriptor,
            invocation=invocation,
            execution=execution,
        )
        if base.status is not ActionVerificationStatus.VERIFIED:
            return base
        output = execution.output or {}
        source_ids = tuple(str(item) for item in output.get("source_ids", ()))
        citation_ids = tuple(str(item) for item in output.get("citation_ids", ()))
        content_hashes = tuple(str(item) for item in output.get("content_hashes", ()))
        if (
            not (len(source_ids) == len(citation_ids) == len(content_hashes))
            or not set(source_ids).issubset(invocation.resource_request.source_ids)
        ):
            return _verification_failed(descriptor, execution.authority, "grounding_evidence_mismatch")
        authority = execution.authority
        if authority is None:
            return _verification_failed(descriptor, None, "grounding_authority_missing")
        return _verification_verified(
            descriptor,
            authority,
            "Grounding source and citation evidence verified.",
        )


class PostgresLearningPlanActionVerifier:
    """Verify draft lineage, content hash, and current planning facts."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def verify(self, *, descriptor, invocation, execution) -> ActionVerificationResult:
        authority = execution.authority
        output = execution.output or {}
        if authority is None or authority.kind is not ActionAuthorityKind.PLAN_DRAFT:
            return _verification_failed(descriptor, authority, "plan_draft_authority_missing")
        row = self._conn.execute(
            """
            SELECT drafts.content_hash, drafts.facts_fingerprint, drafts.source_input_revision
            FROM tutor_learning_plan_drafts AS drafts
            WHERE drafts.id = %s AND drafts.user_id = %s AND drafts.source_run_id = %s
            """,
            (authority.reference_id, invocation.user_id, invocation.run_id),
        ).fetchone()
        facts = PostgresPlanningFactRepository(self._conn)
        current_facts = facts.current_facts_for_run(
            user_id=invocation.user_id,
            run_id=invocation.run_id,
        )
        current_fingerprint = facts.facts_fingerprint(current_facts)
        if (
            row is None
            or _as_int(row["source_input_revision"]) != invocation.input_revision
            or str(row["content_hash"]) != str(authority.reference_hash or "")
            or str(output.get("draft_id") or "") != authority.reference_id
            or str(output.get("content_hash") or "") != str(row["content_hash"])
            or str(row.get("facts_fingerprint") or "") != current_fingerprint
        ):
            return _verification_failed(descriptor, authority, "plan_draft_authority_mismatch")
        try:
            descriptor.output_model.model_validate(output)
        except ValueError:
            return _verification_failed(descriptor, authority, "action_output_invalid")
        return _verification_verified(descriptor, authority, "Learning plan draft authority verified.")


class PostgresExecutionJobActionVerifier:
    """Verify one terminal safe execution result without reading private inputs."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def verify(self, *, descriptor, invocation, execution) -> ActionVerificationResult:
        authority = execution.authority
        if authority is None or authority.kind is not ActionAuthorityKind.EXECUTION_JOB:
            return _verification_failed(descriptor, authority, "execution_job_authority_missing")
        row = self._conn.execute(
            """
            SELECT state, result_hash
            FROM tutor_execution_jobs
            WHERE id = %s AND user_id = %s AND run_id = %s
            """,
            (authority.reference_id, invocation.user_id, invocation.run_id),
        ).fetchone()
        if (
            row is None
            or str(row["state"]) != "completed"
            or str(row.get("result_hash") or "") != str(authority.reference_hash or "")
        ):
            return _verification_failed(descriptor, authority, "execution_job_authority_mismatch")
        try:
            descriptor.output_model.model_validate(execution.output or {})
        except ValueError:
            return _verification_failed(descriptor, authority, "action_output_invalid")
        return _verification_verified(descriptor, authority, "Execution job terminal result verified.")


class ControlledCapabilityGateway:
    """Run existing capability owners through the shared Action Runtime contract."""

    def __init__(
        self,
        *,
        catalog: SkillCatalogSnapshot,
        policy_resolver: CapabilityPolicyResolver,
        selection_store: TutorSkillSelectionStore,
        authority_gateway: TutorCapabilityGateway,
        authority_recorder: CapabilityInvocationRecorder,
        receipt_store: ActionReceiptStore,
        fence: ActionFence,
        clock: Clock,
        policy_fingerprint_loader: Callable[[TutorRunSnapshot], str],
        verifier_factory: Callable[[ActionDescriptor], ActionVerifier],
    ) -> None:
        self._catalog = catalog
        self._policy_resolver = policy_resolver
        self._selection_store = selection_store
        self._authority_gateway = authority_gateway
        self._authority_recorder = authority_recorder
        self._receipt_store = receipt_store
        self._fence = fence
        self._clock = clock
        self._policy_fingerprint_loader = policy_fingerprint_loader
        self._verifier_factory = verifier_factory
        self._descriptors = {item.action_id: item for item in default_action_descriptors()}

    def dispatch(
        self,
        *,
        run: TutorRunSnapshot,
        request: TutorCapabilityRequest,
    ) -> TutorCapabilityResult:
        descriptor = self._descriptors.get(request.capability_id)
        if descriptor is None or request.capability_id in {"runner.execute", "model-code-review.validate"}:
            return TutorCapabilityResult(
                request_id=request.request_id,
                status=TutorCapabilityStatus.DENIED,
                safe_result=(TutorPayloadField("code", "unknown_action_descriptor"),),
                diagnostic_code="unknown_action_descriptor",
            )
        if run.lease is None:
            return TutorCapabilityResult(
                request_id=request.request_id,
                status=TutorCapabilityStatus.DENIED,
                safe_result=(TutorPayloadField("code", "action_lease_required"),),
                diagnostic_code="action_lease_required",
            )

        policy = self._policy_resolver.resolve(run=run, catalog=self._catalog)
        selected = self._selection_store.get(
            run_id=run.run_id,
            input_revision=run.input_revision,
        )
        adapter = _CapabilityAuthorityActionAdapter(
            gateway=self._authority_gateway,
            recorder=self._authority_recorder,
            request=request,
            run=run,
            descriptor=descriptor,
            catalog_digest=self._catalog.digest,
            policy_fingerprint=self._policy_fingerprint_loader(run),
            clock=self._clock,
        )
        arguments = payload_mapping_from_fields(request.arguments)
        if arguments is None:
            return TutorCapabilityResult(
                request_id=request.request_id,
                status=TutorCapabilityStatus.DENIED,
                safe_result=(TutorPayloadField("code", "capability_arguments_invalid"),),
                diagnostic_code="capability_arguments_invalid",
            )
        invocation = build_action_invocation(
            descriptor=descriptor,
            run=run,
            invocation_id=_invocation_id(run.run_id, request.request_id),
            idempotency_key=request.request_id,
            arguments=arguments,
            resource_request=_capability_resources(
                descriptor=descriptor,
                allowed_source_ids=policy.allowed_source_ids,
                arguments=arguments,
            ),
            task_kind=_capability_task_kind(request.capability_id),
            catalog_digest=self._catalog.digest,
            policy_fingerprint=self._policy_fingerprint_loader(run),
            selected_skill_reference=selected.reference.key if selected is not None else None,
            action_generation=run.capability_call_count + 1,
            requested_at=self._clock.now(),
        )
        runtime = ControlledActionRuntime(
            descriptors=(descriptor,),
            adapters={descriptor.owner_adapter_id: adapter},
            verifiers={descriptor.verifier_id: self._verifier_factory(descriptor)},
            fence=self._fence,
            store=self._receipt_store,
            clock=self._clock.now,
            approved_source_ids=policy.allowed_source_ids,
        )
        outcome = runtime.execute(invocation)
        if adapter.result is not None:
            if outcome.receipt.status is ActionLifecycleStatus.VERIFIED:
                return replace(adapter.result, continue_run=True)
            if adapter.result.status is not TutorCapabilityStatus.COMPLETED:
                return adapter.result
            code = outcome.receipt.diagnostic_code or "action_not_verified"
            return TutorCapabilityResult(
                request_id=request.request_id,
                status=TutorCapabilityStatus.UNAVAILABLE,
                safe_result=(TutorPayloadField("code", code),),
                diagnostic_code=code,
            )
        if outcome.receipt.status is ActionLifecycleStatus.VERIFIED:
            return TutorCapabilityResult(
                request_id=request.request_id,
                status=TutorCapabilityStatus.COMPLETED,
                continue_run=True,
                diagnostic_code="action_replayed",
            )
        status = (
            TutorCapabilityStatus.DENIED
            if outcome.receipt.status is ActionLifecycleStatus.DENIED
            else TutorCapabilityStatus.UNAVAILABLE
        )
        code = outcome.receipt.diagnostic_code or "action_not_verified"
        return TutorCapabilityResult(
            request_id=request.request_id,
            status=status,
            safe_result=(TutorPayloadField("code", code),),
            diagnostic_code=code,
        )


class _CapabilityAuthorityActionAdapter:
    def __init__(
        self,
        *,
        gateway: TutorCapabilityGateway,
        recorder: CapabilityInvocationRecorder,
        request: TutorCapabilityRequest,
        run: TutorRunSnapshot,
        descriptor: ActionDescriptor,
        catalog_digest: str,
        policy_fingerprint: str,
        clock: Clock,
    ) -> None:
        self._gateway = gateway
        self._recorder = recorder
        self._request = request
        self._run = run
        self._descriptor = descriptor
        self._catalog_digest = catalog_digest
        self._policy_fingerprint = policy_fingerprint
        self._clock = clock
        self.result: TutorCapabilityResult | None = None

    def execute(self, invocation) -> ActionExecutionResult:
        started = _utc(self._clock.now())
        result = self._gateway.dispatch(run=self._run, request=self._request)
        self.result = result
        duration_ms = max(0, round((_utc(self._clock.now()) - started).total_seconds() * 1000))
        if self._run.lease is None:
            raise ValueError("controlled capability adapter requires an owned lease")
        authority = self._recorder.record_capability_invocation(
            user_id=self._run.user_id,
            run_id=self._run.run_id,
            lease=self._run.lease,
            input_revision=self._run.input_revision,
            request=self._request,
            result=result,
            capability_version=self._descriptor.version,
            catalog_digest=self._catalog_digest,
            policy_fingerprint=self._policy_fingerprint,
            duration_ms=duration_ms,
        )
        output = _capability_output(self._descriptor, result)
        authority_id = getattr(authority, "invocation_id", None)
        if not isinstance(authority_id, str) or not authority_id:
            return ActionExecutionResult(
                status=ActionExecutionStatus.PERMANENT_FAILED,
                safe_summary="Capability authority receipt was invalid.",
                diagnostic_code="capability_authority_invalid",
                duration_ms=duration_ms,
            )
        authority_reference = ActionAuthorityReference(
            ActionAuthorityKind.CAPABILITY_INVOCATION,
            authority_id,
            _payload_fields_hash(result.safe_result),
        )
        if result.status is TutorCapabilityStatus.COMPLETED:
            if self._descriptor.action_id == "learning.plan.draft":
                authority_reference = ActionAuthorityReference(
                    ActionAuthorityKind.PLAN_DRAFT,
                    str(output.get("draft_id") or ""),
                    str(output.get("content_hash") or ""),
                )
            return ActionExecutionResult(
                status=ActionExecutionStatus.SUCCEEDED,
                authority=authority_reference,
                output=output,
                safe_summary="Capability completed under its existing authority.",
                duration_ms=duration_ms,
            )
        if result.status is TutorCapabilityStatus.DENIED:
            return ActionExecutionResult(
                status=ActionExecutionStatus.DENIED,
                authority=authority_reference,
                safe_summary="Capability authority denied the request.",
                diagnostic_code=result.diagnostic_code or "capability_denied",
                duration_ms=duration_ms,
            )
        diagnostic = result.diagnostic_code or "capability_unavailable"
        retryable = diagnostic in self._descriptor.retry_policy.retryable_codes
        return ActionExecutionResult(
            status=(
                ActionExecutionStatus.RETRYABLE_FAILED
                if retryable
                else ActionExecutionStatus.PERMANENT_FAILED
            ),
            authority=authority_reference,
            safe_summary="Capability authority is unavailable.",
            diagnostic_code=diagnostic,
            duration_ms=duration_ms,
        )


def _capability_resources(
    *,
    descriptor: ActionDescriptor,
    allowed_source_ids: tuple[str, ...],
    arguments: Mapping[str, object],
) -> ActionResourceRequest:
    input_bytes = len(json.dumps(arguments, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    source_ids = allowed_source_ids if descriptor.action_id == "grounding.retrieve" else ()
    return ActionResourceRequest(
        source_ids=source_ids,
        network_class=descriptor.resource_profile.network_class,
        input_bytes=input_bytes,
        expected_output_bytes=descriptor.resource_profile.max_output_bytes,
        cost_units=1,
    )


def _capability_task_kind(capability_id: str) -> str:
    return "plan_drafting" if capability_id == "learning.plan.draft" else "general_tutor"


def _capability_output(
    descriptor: ActionDescriptor,
    result: TutorCapabilityResult,
) -> dict[str, object]:
    fields = {field.key: field.value for field in result.safe_result}
    if descriptor.action_id == "learning.plan.draft":
        return {
            "status": "completed",
            "draft_id": str(fields.get("draft_id") or ""),
            "draft_version": _int(fields.get("draft_version")),
            "content_hash": str(fields.get("content_hash") or ""),
            "quality_status": str(fields.get("quality_status") or ""),
        }
    source_ids: list[str] = []
    citation_ids: list[str] = []
    content_hashes: list[str] = []
    for index in range(1, 5):
        citation_value = fields.get(f"citation_{index}")
        content_hash = fields.get(f"content_hash_{index}")
        if citation_value is None or content_hash is None:
            continue
        try:
            citation = json.loads(str(citation_value))
        except json.JSONDecodeError:
            continue
        if not isinstance(citation, Mapping):
            continue
        source_id = str(citation.get("source_id") or "")
        citation_id = str(citation.get("citation_id") or "")
        if source_id and citation_id:
            source_ids.append(source_id)
            citation_ids.append(citation_id)
            content_hashes.append(str(content_hash))
    return {
        "status": "completed",
        "source_ids": source_ids,
        "citation_ids": citation_ids,
        "content_hashes": content_hashes,
    }


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _verification_failed(
    descriptor: ActionDescriptor,
    authority: ActionAuthorityReference | None,
    code: str,
) -> ActionVerificationResult:
    return ActionVerificationResult(
        status=ActionVerificationStatus.FAILED,
        verifier_id=descriptor.verifier_id,
        verifier_version=descriptor.verifier_version,
        authority=authority,
        safe_summary="Action authority verification failed.",
        diagnostic_code=code,
    )


def _verification_verified(
    descriptor: ActionDescriptor,
    authority: ActionAuthorityReference,
    summary: str,
) -> ActionVerificationResult:
    return ActionVerificationResult(
        status=ActionVerificationStatus.VERIFIED,
        verifier_id=descriptor.verifier_id,
        verifier_version=descriptor.verifier_version,
        authority=authority,
        safe_summary=summary,
    )


def _hash_mapping(value: Mapping[str, object]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _payload_fields_hash(fields: tuple[TutorPayloadField, ...]) -> str:
    payload = [{"key": field.key, "value": field.value} for field in fields]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _invocation_id(run_id: str, request_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}:{request_id}".encode("utf-8")).hexdigest()
    return f"action-{digest[:32]}"


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ControlledCapabilityGateway",
    "ExistingExecutionJobActionAdapter",
    "ExistingExecutionJobEvidence",
    "PostgresCapabilityAuthorityVerifier",
    "PostgresExecutionJobActionVerifier",
    "PostgresGroundingActionVerifier",
    "PostgresExistingExecutionJobReader",
    "PostgresLearningPlanActionVerifier",
]
