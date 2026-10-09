"""Opt-in private publication while the original live admission issuer is alive.

Caller owns the short transaction. No provider/executor IO, shared catalog writes,
Attempt/Gate writes, seal rehydration, lease refresh or implicit commit happens here.
"""
from __future__ import annotations

from datetime import datetime
import json
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.practice_adapter import LEARNING_ITEM_PRACTICE_ADAPTER_VERSION
from app.services.learning.item_bank.private_publication_contracts import (
    PrivatePracticeMaterializationV1,
    PrivatePublicationReceiptV1,
    PrivatePublishedCoverageV1,
    PrivateSourceBindingV1,
)
from app.services.learning.item_bank.private_publication_repository import PostgresPrivatePublicationRepository
from app.services.learning.item_supply.admission import evaluate_admission_v2
from app.services.learning.item_supply.admission_facts import AdmissionFactsOwner
from app.services.learning.item_supply.admission_facts_contracts import IssuedAdmissionFactsV1
from app.services.learning.item_supply.contracts import ClauseCoverageV1
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineArtifactRepository
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvaluationV2, ReviewBundleV2
from app.services.learning.item_supply.sandbox.python_goal_scorer import source_scorer_version
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2, checked_model
from app.services.learning.practice.quality import require_exercise_quality

if TYPE_CHECKING:
    from app.services.learning.item_supply.pipeline import CompletedReview, PreparedReview


class PrivatePublicationError(ValueError):
    """Stable internal codes only, never source/provider/private payloads."""


def transaction_clock(conn: Connection[dict[str, Any]]) -> datetime:
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise PrivatePublicationError("PRIVATE_PUBLICATION_TRANSACTION_REQUIRED")
    row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
    if row is None or not isinstance(row["now"], datetime) or row["now"].tzinfo is None:
        raise PrivatePublicationError("PRIVATE_PUBLICATION_CLOCK_UNAVAILABLE")
    return row["now"]


def source_bindings(
    artifact: dict[str, Any], source: LearningItemSourceV1,
) -> tuple[PrivateSourceBindingV1, ...]:
    """Reconstruct persisted exact coordinates, NOT a terminal/facts authority."""
    try:
        request = GenerationRequestV2.model_validate_json(json.dumps(artifact["request_json"]))
        receipt = GenerationReceiptV2.model_validate_json(json.dumps(artifact["receipt_json"]))
        stored_source = LearningItemSourceV1.model_validate_json(json.dumps(artifact["source_json"]))
    except (ValueError, TypeError, KeyError):
        raise PrivatePublicationError("PRIVATE_PUBLICATION_GENERATION_INVALID") from None
    if (artifact["mode"] != "live" or receipt.provider.mode != "provider"
            or stored_source != source or artifact["source_hash"] != source.source_hash
            or artifact["content_hash"] != source.content_hash
            or request.blueprint != source.blueprint
            or (request.item_key, request.version) != (source.public.item_key, source.public.version)
            or (request.public_template is not None and request.public_template != source.public)
            or receipt.candidate_id != request.candidate_id or receipt.scope_hash != request.scope_hash
            or receipt.source_hash != source.source_hash or receipt.content_hash != source.content_hash
            or len(receipt.sources) != len(request.materials)):
        raise PrivatePublicationError("PRIVATE_PUBLICATION_GENERATION_MISMATCH")
    return tuple(PrivateSourceBindingV1(material=material, receipt=expected)
                 for material, expected in zip(request.materials, receipt.sources, strict=True))


def current_sources(
    conn: Connection[dict[str, Any]], authority: RagSourceAuthority,
    sources: tuple[PrivateSourceBindingV1, ...],
) -> None:
    if type(authority) is not RagSourceAuthority or authority.connection is not conn:
        raise PrivatePublicationError("PRIVATE_PUBLICATION_SOURCE_OWNER_REQUIRED")
    for binding in sources:
        authority.assert_current(binding.material, binding.receipt)


def candidate_family(facts: IssuedAdmissionFactsV1) -> str:
    # Deliberately conservative: cosmetic/numeric/source revisions of this finite
    # target must NOT manufacture independent assessment families.
    scope = facts.coverage.demand.scope
    return "family:" + canonical_hash({
        "assessment_contract": scope.assessment_contract_version,
        "capabilities": scope.required_capabilities, "kind": scope.item_kind.value,
        "runtime": scope.runtime_profile_id,
    })


class LearningItemPublicationService:
    def __init__(self, conn: Connection[dict[str, Any]],
                 repository: PostgresPrivatePublicationRepository, *, enabled: bool = False) -> None:
        self.conn = conn
        self.repository = repository
        self.enabled = enabled

    def _stored_review(
        self, prepared: PreparedReview, completed: CompletedReview, lease: JobLeaseV1,
        evaluation: AdmissionEvaluationV2, evaluation_receipt_id: UUID,
    ) -> None:
        rows = self.conn.execute(
            """SELECT * FROM tutor_item_supply_private_pipeline_receipts
               WHERE user_id=%s AND epoch=%s AND scope_id=%s AND generation_artifact_id=%s
                 AND job_id=%s AND lease_generation=%s AND lease_state_version=%s
                 AND artifact_key IN (%s,%s,%s) FOR SHARE""",
            (lease.owner_id, lease.owner_epoch, prepared.scope_id, prepared.artifact_id,
             lease.job_id, lease.generation, lease.state_version,
             "blind_solve." + completed.bundle.bundle_id.hex,
             "review_bundle." + completed.bundle.bundle_id.hex,
             "admission_evaluation." + completed.bundle.bundle_id.hex),
        ).fetchall()
        expected = {"blind_solve": completed.bundle.blind_solve,
                    "review_bundle": completed.bundle, "admission_evaluation": evaluation}
        if len(rows) != len(expected) or {row["artifact_kind"] for row in rows} != set(expected):
            raise PrivatePublicationError("PRIVATE_PUBLICATION_REVIEW_MISSING")
        for row in rows:
            payload = expected[row["artifact_kind"]].model_dump(mode="json")
            if (row["mode"] != "live" or row["payload_json"] != payload
                    or row["receipt_hash"] != canonical_hash(payload)
                    or str(row["version_id"]) != prepared.binding.version_key
                    or row["content_hash"] != prepared.source.content_hash
                    or (row["artifact_kind"] == "admission_evaluation"
                        and UUID(str(row["id"])) != evaluation_receipt_id)):
                raise PrivatePublicationError("PRIVATE_PUBLICATION_REVIEW_MISMATCH")

    def publish_internal_private(
        self, prepared_review: PreparedReview, completed_review: CompletedReview, *,
        lease: JobLeaseV1, facts_owner: AdmissionFactsOwner, facts_receipt: IssuedAdmissionFactsV1,
        evaluation: AdmissionEvaluationV2, evaluation_receipt_id: UUID,
    ) -> PrivatePublicationReceiptV1:
        if self.enabled is not True:
            raise PrivatePublicationError("PRIVATE_PUBLICATION_DISABLED")
        if (type(self.repository) is not PostgresPrivatePublicationRepository
                or self.repository.conn is not self.conn
                or type(facts_owner) is not AdmissionFactsOwner or facts_owner.conn is not self.conn):
            raise PrivatePublicationError("PRIVATE_PUBLICATION_OWNER_REQUIRED")
        transaction_clock(self.conn)
        lease = checked_model(lease, JobLeaseV1)
        source = checked_model(prepared_review.source, LearningItemSourceV1)
        evaluation = checked_model(evaluation, AdmissionEvaluationV2)
        facts_receipt = checked_model(facts_receipt, IssuedAdmissionFactsV1)
        bundle = checked_model(completed_review.bundle, ReviewBundleV2)
        if (prepared_review.mode != "live" or lease.visibility != "private"
                or lease.owner_id is None or lease.owner_epoch is None
                or evaluation.disposition != "eligible_internal"
                or self.repository.user_id != lease.owner_id or self.repository.expected_epoch != lease.owner_epoch):
            raise PrivatePublicationError("PRIVATE_PUBLICATION_LIVE_ELIGIBLE_REQUIRED")
        # This calls the ORIGINAL process-local facts, runner, blind and ambiguity
        # verifiers. Loading facts JSON alone cannot authorize publication.
        evidence = facts_owner.verify(facts_receipt, prepared_review, lease=lease,
                                      completed_review=completed_review)
        expected = evaluate_admission_v2(source, binding=prepared_review.binding,
            policy=AutonomousEvidencePolicyV2(), validation_receipt=prepared_review.validation,
            author_identity=prepared_review.author_identity, bundle=bundle, evidence=evidence, enabled=True)
        if expected != evaluation:
            raise PrivatePublicationError("PRIVATE_PUBLICATION_EVALUATION_MISMATCH")
        self._stored_review(prepared_review, completed_review, lease, evaluation, evaluation_receipt_id)
        artifact = PipelineArtifactRepository(self.conn).get_generation(
            lease=lease, scope_id=prepared_review.scope_id, artifact_id=prepared_review.artifact_id,
            now=transaction_clock(self.conn), mode="live")
        sources = source_bindings(artifact, source)
        if tuple(binding.receipt for binding in sources) != facts_receipt.coverage.source_receipts:
            raise PrivatePublicationError("PRIVATE_PUBLICATION_SOURCE_SET_MISMATCH")
        version = self.conn.execute(
            """SELECT * FROM tutor_item_supply_private_versions
               WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s FOR UPDATE""",
            (facts_receipt.version_id, lease.owner_id, lease.owner_epoch, prepared_review.scope_id),
        ).fetchone()
        demand = self.conn.execute(
            """SELECT id FROM tutor_item_supply_private_demands
               WHERE user_id=%s AND epoch=%s AND scope_id=%s AND demand_hash=%s FOR SHARE""",
            (lease.owner_id, lease.owner_epoch, prepared_review.scope_id, facts_receipt.coverage.demand.demand_hash),
        ).fetchall()
        if (version is None or len(demand) != 1
                or version["public_json"] != source.public.model_dump(mode="json")
                or version["private_json"] != source.private.model_dump(mode="json")
                or UUID(str(version["candidate_id"])) != UUID(prepared_review.binding.candidate_key)):
            raise PrivatePublicationError("PRIVATE_PUBLICATION_VERSION_DEMAND_MISMATCH")
        # UUIDs and timestamps are deterministic for exact retry within this live
        # issuer window; a retry is never a new lease or admission grant.
        seed = f"aearn:private-publication:v1:{facts_receipt.receipt_id}:{evaluation_receipt_id}"
        materialization_id = uuid5(NAMESPACE_URL, seed + ":materialization")
        publication_id = uuid5(NAMESPACE_URL, seed + ":publication")
        proof_id = uuid5(NAMESPACE_URL, seed + ":proof")
        coverage = facts_receipt.coverage
        scope = coverage.demand.scope
        runtime_locks = {terminal.lock_fingerprint for terminal in coverage.execution_terminals}
        runtime_locks.update(terminal.lock_fingerprint for terminal in facts_receipt.ambiguity.terminals)
        runtime_locks.update(terminal.lock_fingerprint for terminal in coverage.blind_terminals)
        if runtime_locks != {scope.runtime_profile_hash} or scope.scorer_version != source_scorer_version(source):
            raise PrivatePublicationError("PRIVATE_PUBLICATION_RUNTIME_SCORER_MISMATCH")
        materialization = PrivatePracticeMaterializationV1(user_id=lease.owner_id, epoch=lease.owner_epoch,
            scope_id=prepared_review.scope_id, version_id=facts_receipt.version_id,
            source_hash=source.source_hash, content_hash=source.content_hash,
            version_payload_hash=version["payload_hash"],
            materialization_id=materialization_id, source=source,
            adapter_version=LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
            scorer_version=source_scorer_version(source), runtime_profile_id=scope.runtime_profile_id,
            runtime_profile_hash=scope.runtime_profile_hash, created_at=coverage.checked_at)
        material = materialization.authority_material()
        require_exercise_quality(material.exercise, material.rubric,
                                 model_review_validation=material.model_review_validation)
        publication = PrivatePublicationReceiptV1(user_id=lease.owner_id, epoch=lease.owner_epoch,
            scope_id=prepared_review.scope_id, version_id=facts_receipt.version_id,
            source_hash=source.source_hash, content_hash=source.content_hash,
            version_payload_hash=version["payload_hash"],
            publication_id=publication_id, materialization_id=materialization_id,
            proof_id=proof_id, generation_artifact_id=prepared_review.artifact_id,
            facts_receipt_id=facts_receipt.receipt_id, evaluation_receipt_id=evaluation_receipt_id,
            handle=version["handle"], transition_key="publish." + facts_receipt.receipt_id.hex, predecessor_event_id=None,
            state_version=1, state="published", checked_at=coverage.checked_at,
            admission_valid_until=coverage.valid_until)
        proof = PrivatePublishedCoverageV1(user_id=lease.owner_id, epoch=lease.owner_epoch,
            scope_id=prepared_review.scope_id, version_id=facts_receipt.version_id,
            source_hash=source.source_hash, content_hash=source.content_hash,
            version_payload_hash=version["payload_hash"],
            publication_id=publication_id, materialization_id=materialization_id,
            proof_id=proof_id, generation_artifact_id=prepared_review.artifact_id,
            facts_receipt_id=facts_receipt.receipt_id, evaluation_receipt_id=evaluation_receipt_id,
            demand_id=UUID(str(demand[0]["id"])), demand=coverage.demand, blueprint=coverage.coverage_blueprint,
            clauses=tuple(ClauseCoverageV1(clause_id=m.clause_id, clause_hash=m.clause_hash)
                          for m in coverage.mappings),
            candidate_family_id=candidate_family(facts_receipt), slot="assessment", sources=sources,
            checked_at=coverage.checked_at, valid_until=coverage.valid_until)
        # All potential lock waits precede the final issuer/source/DB-clock fence.
        self._final_fence(facts_owner, facts_receipt, prepared_review, completed_review, lease, sources)
        self.repository.append_materialization(materialization)
        stored = self.repository.append_publication(publication)
        self.repository.append_proof(proof)
        # Repository inserts/triggers can also wait. Any failure propagates to the
        # caller transaction, rolling back materialization/event/proof together.
        self._final_fence(facts_owner, facts_receipt, prepared_review, completed_review, lease, sources)
        return stored

    def _final_fence(self, owner: AdmissionFactsOwner, facts: IssuedAdmissionFactsV1,
                     prepared: PreparedReview, completed: CompletedReview, lease: JobLeaseV1,
                     sources: tuple[PrivateSourceBindingV1, ...]) -> None:
        owner.verify(facts, prepared, lease=lease, completed_review=completed)
        current_sources(self.conn, owner.rag_authority, sources)
        now = transaction_clock(self.conn)
        if not facts.coverage.checked_at <= now < facts.coverage.valid_until:
            raise PrivatePublicationError("PRIVATE_PUBLICATION_ADMISSION_EXPIRED")
