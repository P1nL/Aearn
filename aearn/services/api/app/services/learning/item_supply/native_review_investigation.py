"""Default-off concrete native investigation owner, original shared writer only.

Caller commits prepare, run is IDLE, caller separately commits UNKNOWN settle,
then persist in a fresh short transaction. No checkpoint, facts or publication.
Persisted rows are audit DATA and cannot rehydrate the in-process capabilities.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
from app.services.learning.item_bank.contracts import LearningItemReviewRole, canonical_hash
from app.services.learning.item_supply.diagnostic_policy import checked_bundle
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.native_review_investigation_contracts import (
    InvestigationProtocol, NativeReviewInvestigationInputV1, NativeReviewInvestigationReportV1,
    checked_investigation_protocol, investigation_prompt_version,
)
from app.services.learning.item_supply.native_review_investigation_provider import NativeReviewInvestigator
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.private_investigation_diagnostics import (
    PrivateInvestigationAudit, PrivateInvestigationAuditSink,
)
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2, ReviewInputV2
from app.services.learning.item_supply.review_deliberation import review_disputes
from app.services.learning.item_supply.review_observability import ReviewFailureObservation, observe_review_failure
from app.services.learning.item_supply.review_protocol import make_review_request, report_protocol, verify_review_report
from app.services.learning.item_supply.review_provider import AutonomousReviewError
from app.services.learning.item_supply.shared_review import PreparedSharedReview, SharedReviewPipeline, SharedReviewResult
from app.services.learning.item_supply.storage_contracts import checked_model


@dataclass(frozen=True, repr=False)
class PreparedNativeReviewInvestigation:
    preparation_id: UUID
    root_id: UUID
    lease: JobLeaseV1
    original: PreparedSharedReview
    original_result: SharedReviewResult
    blind_receipt_id: UUID
    review_receipt_id: UUID
    continuation_binding_hash: str | None
    reservation_id: UUID
    request: NativeReviewInvestigationInputV1
    identity: ProviderIdentityV2
    resources: ResourceAmounts
    source_deadlines: tuple[tuple[str, str, datetime], ...]
    deadline_at: datetime
    timeout_seconds: float

    @property
    def reservation_key(self) -> str:
        return "investigate." + self.original.artifact_id.hex + "." + self.review_receipt_id.hex

    def payload(self) -> dict[str, Any]:
        return {"schema_version": "native_shared_review_investigation_preparation_v1",
            "preparation_id": str(self.preparation_id), "root_id": str(self.root_id),
            "lease": self.lease.model_dump(mode="json"), "generation_artifact_id": str(self.original.artifact_id),
            "artifact_hash": self.original.artifact_hash, "validation_receipt_id": str(self.original.validation_receipt_id),
            "blind_receipt_id": str(self.blind_receipt_id), "review_receipt_id": str(self.review_receipt_id),
            "review_receipt_hash": self.request.review_receipt_hash,
            "original_review_reservation_id": str(self.original.reservation_id),
            "continuation_binding_hash": self.continuation_binding_hash,
            "reservation_id": str(self.reservation_id), "reservation_key": self.reservation_key,
            "request_hash": self.request.input_hash, "request_payload": self.request.input_payload,
            "identity": self.identity.model_dump(mode="json"), "resources": self.resources.model_dump(mode="json"),
            "source_deadlines": [{"binding_digest": b, "claim_receipt_id": c, "retained_until": t.isoformat()}
                for b,c,t in self.source_deadlines], "deadline_at": self.deadline_at.isoformat(),
            "timeout_seconds": self.timeout_seconds, "publication_enabled": False, "admission_eligible": False}


@dataclass(frozen=True, repr=False)
class NativeReviewInvestigationRun:
    preparation_id: UUID
    reservation_id: UUID
    report: NativeReviewInvestigationReportV1 | None
    safe_reason: str
    observation: ReviewFailureObservation | None = field(default=None, repr=False)

    def payload(self, p: PreparedNativeReviewInvestigation) -> dict[str, Any]:
        return {"schema_version": "native_shared_review_investigation_receipt_v1",
            "preparation_id": str(self.preparation_id), "reservation_id": str(self.reservation_id),
            "preparation_hash": canonical_hash(p.payload()), "request_hash": p.request.input_hash,
            "review_receipt_id": str(p.review_receipt_id), "review_receipt_hash": p.request.review_receipt_hash,
            "disputes": [d.model_dump(mode="json") for d in p.request.disputes],
            "report": None if self.report is None else self.report.model_dump(mode="json"),
            "observation": None if self.observation is None else self.observation.payload(),
            "safe_reason": self.safe_reason, "state": "investigation_pending_revision_owner",
            "usage_state": "unknown", "blockers_discharged": False,
            "publication_enabled": False, "admission_eligible": False}


class NativeReviewInvestigationOwner:
    def __init__(self, review: SharedReviewPipeline, *, enabled: bool = False,
                 protocol: InvestigationProtocol = "legacy-v1",
                 private_investigation_audit_sink: PrivateInvestigationAuditSink | None = None) -> None:
        if type(review) is not SharedReviewPipeline:
            raise PipelineRepositoryError("INVESTIGATION_ORIGINAL_SHARED_OWNER_REQUIRED")
        self.review, self.conn, self.enabled = review, review.conn, enabled
        self.protocol = checked_investigation_protocol(protocol)
        if private_investigation_audit_sink is not None and not callable(private_investigation_audit_sink):
            raise ValueError("private investigation sink must be callable")
        self._audit_sink = private_investigation_audit_sink
        self.budget = review.budget
        self._prepared: dict[UUID, tuple[PreparedNativeReviewInvestigation, str, NativeReviewInvestigator, Any]] = {}
        self._runs: dict[UUID, tuple[NativeReviewInvestigationRun, str]] = {}
        self._started: set[UUID] = set()
        # Process-only protocol/full-envelope seals. No change to 508 payloads.
        self._sender_seals: dict[UUID, tuple[InvestigationProtocol, str]] = {}
        self._audits: dict[UUID, PrivateInvestigationAudit] = {}

    def private_audit_status(self, p: PreparedNativeReviewInvestigation) -> Mapping[str, object]:
        self._issued(p)
        audit = self._audits.get(p.preparation_id)
        return ({"enabled": False, "attempted": 0, "written": 0, "failed": 0,
                 "data_only": True, "acceptance_asserted": False} if audit is None else audit.status())

    def _guard(self) -> datetime:
        if not self.enabled or not self.review.review_enabled:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_DISABLED")
        self.review.artifacts.require_owner()
        row = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_review_investigation_preparations') AS p, "
            "to_regclass('public.tutor_item_supply_shared_review_investigation_receipts') AS r, "
            "to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()') AS guard").fetchone()
        if row is None or row["p"] is None or row["r"] is None or row["guard"] is None:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_SCHEMA_REQUIRED")
        if checked_investigation_protocol(self.protocol) == "scalar-evidence-v2":
            capability = self.conn.execute("SELECT pg_get_functiondef("
                "to_regprocedure('item_supply_internal.enforce_shared_review_investigation_insert()')) AS definition").fetchone()
            predicate = "(report->'run'->>'prompt_version' IS NULL OR report->'run'->>'prompt_version' NOT IN " \
                "('native-shared-review-investigation-v1', 'native-shared-review-investigation-v2'))"
            if (capability is None or not isinstance(capability["definition"], str)
                    or predicate not in " ".join(capability["definition"].split())):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_V2_INSTALLED_GUARD_REQUIRED")
        return server_clock(self.conn, datetime.now(UTC))

    def _original(self, original: PreparedSharedReview, result: SharedReviewResult, lease: JobLeaseV1,
                  review_receipt_id: UUID) -> tuple[dict[str, Any], dict[str, Any], UUID, tuple[tuple[str, str, datetime], ...]]:
        now = self._guard()
        authority, solver, reviewers, _ = self.review._issued(original)
        scorer = self.review._result(original, result)
        lease = checked_model(lease, JobLeaseV1)
        if (lease.visibility != "public" or lease.owner_id is not None or lease.owner_epoch is not None
                or (lease.job_id, lease.generation, lease.profile, lease.lease_owner) != (
                    original.lease.job_id, original.lease.generation, original.lease.profile, original.lease.lease_owner)
                or lease.state_version < original.lease.state_version
                or self.review.runtime.next_stage(lease) not in {"reviewing", "investigating"}
                or lease.profile.values.discussion_rounds < 2 or lease.profile.values.investigation_rounds < 1):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_CURRENT_STAGE_PROFILE_REQUIRED")
        # Original p has an older state_version after a legitimate checkpoint;
        # validate current operation via _load, NEVER manufacture a checkpoint.
        a, source, request, validation = self.review._load(lease=lease, artifact_id=original.artifact_id,
            validation_receipt_id=original.validation_receipt_id, spec=original.spec, authority=authority,
            allowed_stages=("reviewing", "investigating"))
        meta = self.review.artifacts.context(lease, now=now)
        if self.review._identities(lease, solver, reviewers) != original.provider_identities:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_REVIEW_BINDINGS_CHANGED")
        if ((source, request, validation, a["artifact_hash"]) != (
                original.source, original.request, original.validation, original.artifact_hash)
                or self.review.artifacts.generation_policy(lease, request, now=now).policy_hash != original.binding.policy_hash):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_SOURCE_CHANGED")
        if result.bundle is None or result.blind is None:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMPLETE_REVIEW_REQUIRED")
        bundle = checked_bundle(result.bundle)
        if (bundle.binding != original.binding or bundle.blind_solve != result.blind
                or bundle.author_identity != original.author_identity
                or tuple(r.run.provider_identity for r in bundle.reports) != original.provider_identities[1:]
                or result.blind.run.provider_identity != original.provider_identities[0]
                or not scorer.verify(result.blind.score, original.source)):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_REVIEW_ISSUER_REQUIRED")
        with finite_review_context(source, spec=original.spec, materials=request.materials):
            for report in bundle.reports:
                if report_protocol(report) != original.review_protocol:
                    raise PipelineRepositoryError("NATIVE_INVESTIGATION_REVIEW_PROTOCOL_CHANGED")
                verify_review_report(report, make_review_request(source, binding=original.binding,
                    validation_receipt=validation, role=report.role, protocol=original.review_protocol))
        row = self.conn.execute("SELECT r.*,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.id=%s FOR SHARE", (review_receipt_id,)).fetchone()
        if (row is None or row["same_transaction"] or row["artifact_kind"] != "review_bundle"
                or row["job_id"] != lease.job_id or row["lease_generation"] != lease.generation
                or row["lease_owner"] != lease.lease_owner or row["generation_artifact_id"] != original.artifact_id
                or row["artifact_key"] != "review_bundle."+original.reservation_id.hex
                or row["receipt_hash"] != bundle.bundle_hash or row["payload_json"] != bundle.model_dump(mode="json")):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_ORIGINAL_BUNDLE_REQUIRED")
        blind = self.conn.execute("SELECT r.id,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.job_id=%s AND r.lease_generation=%s "
            "AND r.generation_artifact_id=%s AND r.artifact_kind='blind_solve' AND r.receipt_hash=%s "
            "AND r.payload_json=%s AND r.artifact_key=%s", (lease.job_id, lease.generation, original.artifact_id,
                result.blind.receipt_hash, Jsonb(result.blind.model_dump(mode="json")), "blind_solve."+original.reservation_id.hex)).fetchall()
        if len(blind) != 1 or blind[0]["same_transaction"]:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_BLIND_REQUIRED")
        review_usage = self.conn.execute("SELECT s.*,s.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=%s AND s.settlement_key=%s",
            (original.reservation_id, "review."+original.artifact_id.hex)).fetchone()
        if review_usage is None or review_usage["same_transaction"] or review_usage["usage_state"] != "unknown":
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_REVIEW_SETTLEMENT_REQUIRED")
        review_reservation = self.budget._reservation_by_key(lease,"review."+original.artifact_id.hex)
        if (review_reservation is None or review_reservation["id"] != original.reservation_id
                or review_reservation["root_id"] != meta["root_id"] or review_reservation["lease_generation"] != lease.generation
                or self.budget._reservation_amounts(lease,original.reservation_id) != original.resources.as_dict()):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_REVIEW_RESERVATION_REQUIRED")
        terminal = self.conn.execute("SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts WHERE generation_artifact_id=%s) "
            "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts WHERE generation_artifact_id=%s "
            "AND artifact_kind='admission_evaluation') OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events WHERE version_id=%s) AS terminal",
            (original.artifact_id, original.artifact_id, a["version_id"])).fetchone()
        if terminal is None or terminal["terminal"]:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_FINAL_HISTORY_RETAINED")
        deadlines = []
        source_reviews = authority._current.governance.source_reviews
        for material in request.materials:
            coordinate = material.binding.evidence[0].binding
            review = None if source_reviews is None else source_reviews.resolve(coordinate.source_handle, coordinate.document_handle)
            if review is None or review.grant is None or review.grant.retained_until <= now:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_CURRENT_SOURCE_GRANT_REQUIRED")
            deadlines.append((material.binding.binding_digest, material.exact_claims[0].claim_receipt_id, review.grant.retained_until))
        return meta, row, UUID(str(blind[0]["id"])), tuple(deadlines)

    def _adapter(self, lease: JobLeaseV1, meta: dict[str, Any], *, timeout: float) -> NativeReviewInvestigator:
        key = meta["key"]
        settings = self.review.settings
        identity = ProviderIdentityV2(identity="deepseek.native.shared.investigator", provider=key.provider,
            model=settings.llm_model, model_version=key.model_version)
        adapter = NativeReviewInvestigator(settings, profile=lease.profile, identity=identity, timeout_seconds=timeout,
            protocol=self.protocol)
        if (meta["provider_key"] != identity.provider or self.review._models.get((key.provider, key.model_version)) != identity.model):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_FROZEN_MODEL_BINDING_REQUIRED")
        return adapter

    def _issued(self, p: PreparedNativeReviewInvestigation) -> NativeReviewInvestigator:
        if type(p) is not PreparedNativeReviewInvestigation:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_PREPARED_REQUIRED")
        entry = self._prepared.get(p.preparation_id)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            if entry is None or entry[0] is not p or entry[1] != canonical_hash(p.payload()):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_PREPARED_REQUIRED")
        sender = self._sender_seals.get(p.preparation_id)
        adapter = entry[2]
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            if (sender is None or type(adapter) is not NativeReviewInvestigator
                    or checked_investigation_protocol(self.protocol) != sender[0]
                    or checked_investigation_protocol(adapter.protocol) != sender[0]
                    or adapter.envelope_hash(p.request) != sender[1]):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_ENVELOPE_CHANGED")
        return adapter

    def prepare(self, *, original: PreparedSharedReview, result: SharedReviewResult,
                lease: JobLeaseV1, review_receipt_id: UUID) -> PreparedNativeReviewInvestigation | None:
        meta, row, blind_id, sources = self._original(original, result, lease, review_receipt_id)
        if result.bundle is None:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMPLETE_REVIEW_REQUIRED")
        disputes = review_disputes(result.bundle)
        if not disputes:
            return None
        now = server_clock(self.conn, datetime.now(UTC))
        deadline = min(lease.expires_at, lease.parent_deadline, lease.profile.parent_deadline_at,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms), *(t for _,_,t in sources))
        timeout = min(3600.0, lease.profile.values.request_timeout_ms/1000, (deadline-now).total_seconds())
        if timeout <= 0:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_DEADLINE_REACHED")
        with finite_review_context(original.source, spec=original.spec, materials=original.request.materials):
            request = NativeReviewInvestigationInputV1(review_receipt_id=review_receipt_id,
                review_receipt_hash=row["receipt_hash"], bundle=checked_bundle(result.bundle),
                review_input=ReviewInputV2(binding=original.binding, role=LearningItemReviewRole.TECHNICAL,
                    source=original.source, validation_receipt=original.validation), disputes=disputes)
            adapter = self._adapter(lease, meta, timeout=timeout)
            if adapter.identity.identity in {original.author_identity, *(i.identity for i in original.provider_identities)}:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_AUTHOR_REVIEW_SEPARATION_REQUIRED")
            resources = adapter.resource_plan(request)
            sender = (checked_investigation_protocol(self.protocol), adapter.envelope_hash(request))
            key = "investigate."+original.artifact_id.hex+"."+review_receipt_id.hex
            reserved = self.budget.reserve(lease=lease, reservation_key=key, amounts=resources, now=now)
            if not reserved.allowed or reserved.reservation_id is None or reserved.reason == "REPLAY":
                return None
            p = PreparedNativeReviewInvestigation(uuid4(), UUID(str(meta["root_id"])), lease, original, result,
                blind_id, review_receipt_id, row["continuation_binding_hash"], reserved.reservation_id,
                request, adapter.identity, resources, sources, deadline, timeout)
            payload = p.payload()
        self.conn.execute("INSERT INTO tutor_item_supply_shared_review_investigation_preparations "
            "(id,root_id,job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,review_receipt_id,reservation_id,payload_json,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (p.preparation_id,p.root_id,lease.job_id,lease.lease_owner,
                lease.generation,lease.state_version,original.artifact_id,review_receipt_id,p.reservation_id,Jsonb(payload),deadline))
        self._prepared[p.preparation_id] = (p, canonical_hash(payload), adapter, self.review.settings.model_copy(deep=True))
        self._sender_seals[p.preparation_id] = sender
        if self._audit_sink is not None:
            with finite_review_context(original.source, spec=original.spec, materials=original.request.materials):
                context = {"preparation_id": str(p.preparation_id), "reservation_id": str(p.reservation_id),
                    "root_id": str(p.root_id), "job_id": str(p.lease.job_id),
                    "review_receipt_id": str(p.review_receipt_id), "review_receipt_hash": request.review_receipt_hash,
                    "binding": request.binding.model_dump(mode="json"), "source_hash": original.source.source_hash,
                    "request_input_hash": request.input_hash, "envelope_hash": sender[1],
                    "protocol": sender[0], "prompt_version": investigation_prompt_version(sender[0]),
                    "provider_identity": p.identity.model_dump(mode="json"), "run_id": None}
                self._audits[p.preparation_id] = PrivateInvestigationAudit(self._audit_sink, context=context)
        return p

    def _fence(self, p: PreparedNativeReviewInvestigation, *, committed: bool = True) -> datetime:
        adapter = self._issued(p)
        meta, _, _, sources = self._original(p.original, p.original_result, p.lease, p.review_receipt_id)
        now = server_clock(self.conn, datetime.now(UTC))
        if (meta["root_id"] != p.root_id or now >= p.deadline_at or sources != p.source_deadlines
                or self.review.settings != self._prepared[p.preparation_id][3]
                or adapter.identity != p.identity or adapter.timeout_seconds != p.timeout_seconds
                or adapter.client.frozen_profile != p.lease.profile
                or adapter.client._settings != self._prepared[p.preparation_id][3]
                or self._adapter(p.lease, meta, timeout=p.timeout_seconds).identity != p.identity):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_CURRENT_FENCE_CHANGED")
        row = self.conn.execute("SELECT p.*,p.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_review_investigation_preparations p WHERE p.id=%s", (p.preparation_id,)).fetchone()
        reservation = self.budget._reservation_by_key(p.lease, p.reservation_key)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            payload = p.payload()
            resources = adapter.resource_plan(p.request)
        if (row is None or (committed and row["same_transaction"]) or row["snapshot_hash"] != canonical_hash(payload)
                or row["payload_json"] != payload or reservation is None or reservation["id"] != p.reservation_id
                or reservation["root_id"] != p.root_id or reservation["lease_generation"] != p.lease.generation
                or self.budget._reservation_amounts(p.lease,p.reservation_id) != p.resources.as_dict() or resources != p.resources):
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_RESERVATION_REQUIRED")
        return now

    def run(self, p: PreparedNativeReviewInvestigation) -> NativeReviewInvestigationRun:
        adapter = self._issued(p)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_IDLE_REQUIRED")
        if p.preparation_id in self._started:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ALREADY_DISPATCHED")
        self._started.add(p.preparation_id)
        report, observation = None, None
        reason = "investigation_analysis_pending_revision_owner"
        try:
            with self.conn.transaction():
                now = self._fence(p)
            # Price/hash remain frozen; invocation timeout can ONLY decrease.
            remaining = (p.deadline_at-max(now, datetime.now(UTC))).total_seconds()
            if remaining <= 0:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_DEADLINE_REACHED")
            if self.conn.info.transaction_status != TransactionStatus.IDLE:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_IDLE_REQUIRED")
            with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
                report = adapter.investigate(p.request, deadline_at=p.deadline_at, remaining_seconds=remaining,
                    expected_envelope_hash=self._sender_seals[p.preparation_id][1],
                    private_audit=self._audits.get(p.preparation_id))
            with self.conn.transaction():
                self._fence(p)
        except Exception as exc:
            # A returned analysis is not a valid result after an owner fence fails.
            # The separately settled reservation remains UNKNOWN either way.
            report = None
            reason = "investigation_provider_or_fence_pending"
            observation = exc.observation if isinstance(exc, AutonomousReviewError) else None
            if observation is None:
                observation = observe_review_failure(exc, phase="evidence_verification")
            audit = self._audits.get(p.preparation_id)
            if audit is not None:
                audit.failure(phase=observation.phase, safe_code=observation.safe_code)
        result = NativeReviewInvestigationRun(p.preparation_id,p.reservation_id,report,reason,observation)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            self._runs[p.preparation_id] = (result,canonical_hash(result.payload(p)))
        return result

    def _result(self, p: PreparedNativeReviewInvestigation, result: NativeReviewInvestigationRun) -> None:
        self._issued(p)
        entry = self._runs.get(p.preparation_id)
        with finite_review_context(p.original.source, spec=p.original.spec, materials=p.original.request.materials):
            if (type(result) is not NativeReviewInvestigationRun or entry is None or entry[0] is not result
                    or result.preparation_id != p.preparation_id or result.reservation_id != p.reservation_id
                    or entry[1] != canonical_hash(result.payload(p))):
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_RESULT_REQUIRED")
            if result.report is not None:
                result.report.verify_input(p.request, expected_protocol=self._sender_seals[p.preparation_id][0])
                if (result.report.run.provider_identity != p.identity
                        or result.report.run.prompt_version != investigation_prompt_version(self._sender_seals[p.preparation_id][0])
                        or result.report.run.max_output_tokens != DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
                        or result.report.run.timeout_seconds > p.timeout_seconds):
                    raise PipelineRepositoryError("NATIVE_INVESTIGATION_ACTUAL_RUN_BINDING_REQUIRED")

    def settle(self, p: PreparedNativeReviewInvestigation, result: NativeReviewInvestigationRun) -> None:
        self._result(p,result)
        self.budget.settle(lease=p.lease,reservation_id=p.reservation_id,settlement_key=p.reservation_key,
            usage_state="unknown",actual=None,cost_amount=None,receipt_hash=None)

    def persist(self, p: PreparedNativeReviewInvestigation, result: NativeReviewInvestigationRun) -> UUID:
        self._result(p,result)
        self._fence(p)
        usage = self.conn.execute("SELECT s.*,s.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=%s AND s.settlement_key=%s",
            (p.reservation_id,p.reservation_key)).fetchone()
        if usage is None or usage["same_transaction"] or usage["usage_state"] != "unknown":
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_COMMITTED_UNKNOWN_SETTLEMENT_REQUIRED")
        with finite_review_context(p.original.source,spec=p.original.spec,materials=p.original.request.materials):
            payload = result.payload(p)
        receipt_id = p.preparation_id  # One immutable result per preparation, including failures.
        row = self.conn.execute("INSERT INTO tutor_item_supply_shared_review_investigation_receipts "
            "(id,preparation_id,root_id,job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,review_receipt_id,reservation_id,settlement_id,payload_json,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(preparation_id) DO NOTHING RETURNING id",
            (receipt_id,p.preparation_id,p.root_id,p.lease.job_id,p.lease.lease_owner,p.lease.generation,p.lease.state_version,
                p.original.artifact_id,p.review_receipt_id,p.reservation_id,usage["id"],Jsonb(payload),p.deadline_at)).fetchone()
        if row is None:
            prior = self.conn.execute("SELECT id,snapshot_hash,payload_json FROM tutor_item_supply_shared_review_investigation_receipts WHERE preparation_id=%s",
                (p.preparation_id,)).fetchone()
            if prior is None or prior["snapshot_hash"] != canonical_hash(payload) or prior["payload_json"] != payload:
                raise PipelineRepositoryError("NATIVE_INVESTIGATION_IMMUTABLE_RESULT_CONFLICT")
            return UUID(str(prior["id"]))
        return UUID(str(row["id"]))
