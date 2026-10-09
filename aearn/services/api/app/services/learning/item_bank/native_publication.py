"""Default-off native V2 publication in the ORIGINAL bank, isolated B1d only.

No V1 review/pilot/human receipt, second catalog, private owner, Attempt or Gate.
Actual current facts are verified by their original process owner, not JSON seals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank.contracts import (
    LearningItemPublicV1, LearningItemSourceV1, canonical_hash, learning_item_handle, learning_item_uuid,
)
from app.services.learning.item_bank.native_import import NativeLearningItemBankImporter
from app.services.learning.item_bank.native_publication_contracts import (
    NativeConsumptionProofV1, NativeInternalRuntimeBindingV1, NativePublicationPending, NativePublicationProofV1,
    build_native_practice_material,
)
from app.services.learning.item_bank.practice_adapter import LEARNING_ITEM_PRACTICE_ADAPTER_VERSION
from app.services.learning.item_bank.repository import LearningItemImportResult
from app.services.learning.item_supply.finite_candidate_factory import (
    FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1, check_finite_public_spec,
)
from app.services.learning.item_supply.generation_contracts import SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.sandbox.execution_contracts import RUNNER_VERSION
from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.diagnostic_policy import (
    AutonomousEvidencePolicyV3, diagnostic_warnings, policy_for_hash,
)
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.tutor.execution import ExecutionIntentRepository


def _runtime(spec: FiniteCandidateSpecV1, approved: dict[str, NativeInternalRuntimeBindingV1]) -> NativeInternalRuntimeBindingV1:
    scope = spec.coverage_blueprint.scope
    binding = approved.get(spec.target_id)
    if binding is None:
        raise NativePublicationPending("native_internal_runtime_binding_unapproved")
    binding = checked_model(binding, NativeInternalRuntimeBindingV1)
    if (binding.runtime_id != scope.runtime_profile_id or binding.runtime_profile_hash != scope.runtime_profile_hash
            or binding.scorer_version != scope.scorer_version
            or (binding.runtime_lock is not None and binding.runner_version != RUNNER_VERSION)):
        raise NativePublicationPending("native_internal_runtime_binding_stale")
    return binding


class NativeLearningItemPublicationService:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, importer: NativeLearningItemBankImporter,
                 facts_owner: SharedAdmissionFactsOwner, approved_internal_bindings: tuple[NativeInternalRuntimeBindingV1, ...] = (),
                 enabled: bool = False) -> None:
        self.conn, self.settings, self.enabled = conn, settings, enabled
        if (type(importer) is not NativeLearningItemBankImporter or importer.conn is not conn
                or type(facts_owner) is not SharedAdmissionFactsOwner or facts_owner.conn is not conn):
            raise NativePublicationPending("native_publication_concrete_owners_required")
        self.importer, self.facts_owner = importer, facts_owner
        self._runtime_bindings: dict[str, NativeInternalRuntimeBindingV1] = {
            b.target_id: checked_model(b, NativeInternalRuntimeBindingV1) for b in approved_internal_bindings}
        if len(self._runtime_bindings) != len(approved_internal_bindings):
            raise NativePublicationPending("native_internal_runtime_binding_duplicate")

    def _guard(self) -> datetime:
        if not self.enabled or not self.settings.learning_item_supply_enabled or not self.settings.learning_item_v2_admission_enabled:
            raise NativePublicationPending("native_publication_disabled")
        self.importer.artifacts.require_owner()
        return server_clock(self.conn, datetime.now(UTC))

    def _facts(self, facts: IssuedSharedAdmissionFactsV1, lease: JobLeaseV1,
               spec: FiniteCandidateSpecV1) -> None:
        now = self._guard()
        evidence = SharedAdmissionFactsOwner.verify(self.facts_owner, facts, lease=lease)
        policy = policy_for_hash(facts.evaluation.binding.policy_hash)
        if (facts.evaluation.disposition != "eligible_internal" or facts.target_proof is None
                or facts.evaluation.policy_version != policy.policy_version
                or facts.evaluation.binding.policy_hash != policy.policy_hash
                or facts.evaluation.evidence_hash != canonical_hash(evidence.model_dump(mode="json"))
                or facts.evaluation.publication_enabled or facts.publication_enabled
                or facts.lease != lease or not facts.checked_at <= now < facts.valid_until
                or facts.specification_hash != spec.specification_hash or facts.target_id != spec.target_id
                or facts.target_definition_hash != spec.target_definition_hash
                or facts.coverage_blueprint_hash != spec.coverage_blueprint.blueprint_hash
                or not evidence.source_current):
            raise NativePublicationPending("native_publication_current_admission_required")
        runtime = _runtime(spec, self._runtime_bindings)
        if facts.runtime_profile_hash != runtime.runtime_profile_hash or facts.scorer_version != runtime.scorer_version:
            raise NativePublicationPending("native_publication_runtime_facts_mismatch")

    def _committed_stages(self, facts: IssuedSharedAdmissionFactsV1) -> None:
        rows = self.conn.execute(
            "SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts WHERE id=ANY(%s::uuid[]) FOR SHARE",
            ([facts.validation_receipt_id, facts.blind_receipt_id, facts.review_receipt_id],),
        ).fetchall()
        expected = {facts.validation_receipt_id: ("validation", facts.validation_receipt_hash),
                    facts.blind_receipt_id: ("blind_solve", facts.blind_receipt_hash),
                    facts.review_receipt_id: ("review_bundle", facts.review_receipt_hash)}
        if len(rows) != len(expected):
            raise NativePublicationPending("native_publication_committed_stages_missing")
        for row in rows:
            kind, digest = expected[UUID(str(row["id"]))]
            if (row["same_transaction"] or row["artifact_kind"] != kind or row["receipt_hash"] != digest
                    or row["receipt_hash"] != canonical_hash(row["payload_json"])
                    or UUID(str(row["job_id"])) != facts.lease.job_id or row["lease_generation"] != facts.lease.generation
                    or UUID(str(row["generation_artifact_id"])) != facts.generation_artifact_id
                    or UUID(str(row["version_id"])) != facts.version_id
                    or row["source_hash"] != facts.evidence.binding.source_hash
                    or row["content_hash"] != facts.evidence.binding.content_hash
                    or row.get("continuation_binding_hash") != facts.continuation_binding_hash):
                raise NativePublicationPending("native_publication_committed_stage_mismatch")

    def publish_internal(self, imported: LearningItemImportResult, *, lease: JobLeaseV1,
                         spec: FiniteCandidateSpecV1, facts_receipt: IssuedSharedAdmissionFactsV1) -> NativePublicationProofV1:
        """All effects rollback together, even when caller catches a final-fence error.

        The approved V2 policy is an explicit authority alternative inside the
        original event chain. It does not manufacture V1 aggregate pilot/human data.
        """
        self._guard()
        lease, spec = checked_model(lease, JobLeaseV1), checked_model(spec, FiniteCandidateSpecV1)
        facts = checked_model(facts_receipt, IssuedSharedAdmissionFactsV1)
        with self.conn.transaction():
            self._facts(facts, lease, spec)
            self._committed_stages(facts)
            data = self.importer._load(lease=lease, artifact_id=facts.generation_artifact_id,
                validation_receipt_id=facts.validation_receipt_id, spec=spec)
            source, generation = data.generation.source, data.generation
            if spec.blueprint.version == FLEXIBLE_FACTORY_VERSION and (
                    facts.public_task_hash != source.public.public_hash or facts.target_proof is None
                    or facts.target_proof.public_task_hash != source.public.public_hash):
                raise NativePublicationPending("native_publication_actual_public_proof_mismatch")
            if (UUID(imported.version_id) != facts.version_id or UUID(imported.item_id) != facts.item_id
                    or imported.content_hash != source.content_hash
                    or imported.handle != learning_item_handle(source.public.item_key, source.public.version, source.content_hash)
                    or data.validation.evidence_hash != facts.validation_receipt_hash):
                raise NativePublicationPending("native_publication_import_identity_mismatch")
            bank = self.conn.execute(
                "SELECT v.id,v.handle,v.content_hash,v.creator_identity,r.id AS validation_id,r.receipt_hash,r.receipt_json,"
                "r.native_generation_artifact_id,r.native_validation_receipt_id,r.native_specification_hash "
                "FROM tutor_learning_item_versions v JOIN tutor_learning_item_validation_receipts r ON r.version_id=v.id "
                "WHERE v.id=%s AND r.id=%s AND r.schema_version='candidate_validation_v2' AND r.passed IS NULL FOR UPDATE OF v",
                (facts.version_id, imported.validation_receipt_id),
            ).fetchone()
            if (bank is None or bank["handle"] != imported.handle or bank["content_hash"] != source.content_hash
                    or bank["receipt_hash"] != data.validation.evidence_hash
                    or bank["receipt_json"] != data.validation.model_dump(mode="json")
                    or UUID(str(bank["native_generation_artifact_id"])) != facts.generation_artifact_id
                    or UUID(str(bank["native_validation_receipt_id"])) != facts.validation_receipt_id
                    or bank["native_specification_hash"] != spec.specification_hash
                    or bank["creator_identity"] != f"native.author.{generation.receipt.provider.run_id.hex}"):
                raise NativePublicationPending("native_publication_bank_v2_authority_mismatch")
            current = self.conn.execute("SELECT * FROM tutor_learning_item_publication_events WHERE version_id=%s "
                                        "ORDER BY state_version DESC LIMIT 1", (facts.version_id,)).fetchone()
            proof_id = learning_item_uuid("materialization", f"native-proof:{facts.version_id}:{facts.receipt_id}")
            existing = self.conn.execute("SELECT proof_json,proof_hash FROM tutor_learning_item_native_publication_proofs WHERE id=%s",
                                          (proof_id,)).fetchone()
            if existing is not None:
                proof = NativePublicationProofV1.model_validate_json(json.dumps(existing["proof_json"]))
                if (existing["proof_hash"] != proof.proof_hash or proof.facts_hash != facts.receipt_hash
                        or current is None or current["state"] != "published"
                        or UUID(str(current["id"])) != proof.publication_event_id):
                    raise NativePublicationPending("native_publication_replay_conflict")
                self._facts(facts, lease, spec)
                return proof
            if current is None or current["state"] != "machine_verified" or current["state_version"] != 1:
                raise NativePublicationPending("native_publication_initial_state_required")
            evaluation_row = self.importer.artifacts.store_receipt(lease=lease, artifact_id=facts.generation_artifact_id,
                kind="admission_evaluation", payload=facts.evaluation, artifact_key=f"native_admission.{facts.receipt_id.hex}",
                now=facts.checked_at, source_authority=self.importer.authority, spec=spec, continuation_owner=self.importer.continuation)
            material = build_native_practice_material(source, spec=spec, materials=generation.request.materials)
            exercise_id = UUID(PostgresExerciseGateRepository(self.conn).ensure_exercise_authority(
                material.exercise, material.rubric, now=facts.checked_at))
            material_hash = canonical_hash({"adapter_version": LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
                "learning_item_version_id": imported.version_id, "learning_item_handle": imported.handle,
                "learning_item_content_hash": source.content_hash, "exercise_version_id": str(exercise_id),
                "exercise_content_hash": material.exercise.content_hash, "rubric_hash": material.rubric.rubric_hash})
            material_id = learning_item_uuid("materialization", f"{facts.version_id}:{material_hash}")
            event_ids = {state: learning_item_uuid("import", f"native-publication:{facts.version_id}:{facts.receipt_id}:{state}")
                         for state in ("agent_reviewed", "pilot", "published")}
            assert facts.target_proof is not None
            proof = NativePublicationProofV1(proof_id=proof_id, version_id=facts.version_id, item_handle=imported.handle,
                generation_artifact_id=facts.generation_artifact_id, source_hash=source.source_hash, content_hash=source.content_hash,
                specification_hash=spec.specification_hash, target_id=spec.target_id, target_definition_hash=spec.target_definition_hash,
                clauses=tuple({"clause_id": m.clause_id, "clause_hash": m.clause_hash,
                               "interpretation_hash": m.interpretation_hash} for m in facts.target_proof.mappings),
                materials=generation.request.materials, source_receipts=generation.receipt.sources, lease=lease,
                runtime=_runtime(spec, self._runtime_bindings), bank_validation_id=UUID(imported.validation_receipt_id),
                validation_receipt_id=facts.validation_receipt_id, validation_hash=facts.validation_receipt_hash,
                review_receipt_id=facts.review_receipt_id, review_hash=facts.review_receipt_hash,
                evaluation_receipt_id=UUID(str(evaluation_row["id"])), evaluation_hash=facts.evaluation.evaluation_hash,
                facts_receipt_id=facts.receipt_id, facts_hash=facts.receipt_hash,
                evidence_hash=canonical_hash(facts.evidence.model_dump(mode="json")), materialization_id=material_id,
                exercise_version_id=exercise_id, materialization_hash=material_hash,
                runner_material_hash=canonical_hash(dict(material.runner_payload)), publication_event_id=event_ids["published"],
                review_event_id=event_ids["agent_reviewed"], pilot_event_id=event_ids["pilot"],
                policy_hash=facts.evaluation.binding.policy_hash, checked_at=facts.checked_at,
                valid_until=min(facts.valid_until, lease.expires_at, lease.parent_deadline))
            self._facts(facts, lease, spec)
            self.conn.execute("INSERT INTO tutor_learning_item_native_publication_proofs "
                "(id,version_id,generation_artifact_id,facts_receipt_id,evaluation_receipt_id,materialization_id,"
                "publication_event_id,proof_json,runner_material_json) VALUES(" + ",".join(["%s"] * 9) + ")",
                (proof_id, facts.version_id, facts.generation_artifact_id, facts.receipt_id, proof.evaluation_receipt_id,
                 material_id, proof.publication_event_id, Jsonb(proof.model_dump(mode="json")), Jsonb(dict(material.runner_payload))))
            predecessor = UUID(str(current["id"]))
            for state, state_version in (("agent_reviewed", 2), ("pilot", 3), ("published", 4)):
                if state == "published":
                    self.conn.execute("INSERT INTO tutor_learning_item_practice_materializations "
                        "(id,version_id,item_handle,content_hash,exercise_version_id,exercise_key,exercise_version,"
                        "exercise_content_hash,rubric_hash,adapter_version,receipt_hash,materialized_at,native_publication_txid) "
                        "VALUES(" + ",".join(["%s"] * 12) + ",txid_current())",
                        (material_id, facts.version_id, imported.handle, source.content_hash, exercise_id,
                         material.exercise.exercise_key, material.exercise.version, material.exercise.content_hash,
                         material.rubric.rubric_hash, LEARNING_ITEM_PRACTICE_ADAPTER_VERSION, material_hash, facts.checked_at))
                transition = f"native.{state}.{facts.receipt_id.hex}"
                self.conn.execute("INSERT INTO tutor_learning_item_publication_events "
                    "(id,version_id,item_handle,content_hash,predecessor_event_id,state_version,state,transition_key,"
                    "request_hash,authority_kind,authority_hash,authority_reference_id,policy_version,reason_code,occurred_at) "
                    "VALUES(" + ",".join(["%s"] * 15) + ")",
                    (event_ids[state], facts.version_id, imported.handle, source.content_hash, predecessor, state_version, state,
                     transition, canonical_hash({"proof_hash": proof.proof_hash, "state": state, "predecessor": str(predecessor)}),
                     "native_v2", proof.proof_hash, proof.proof_id, facts.evaluation.policy_version, None, facts.checked_at))
                predecessor = event_ids[state]
            self._facts(facts, lease, spec)
            final = self.importer._load(lease=lease, artifact_id=facts.generation_artifact_id,
                validation_receipt_id=facts.validation_receipt_id, spec=spec)
            if final.generation.source != source or final.validation != data.validation:
                raise NativePublicationPending("native_publication_final_binding_changed")
            return proof


@dataclass(frozen=True)
class NativePublishedItemData:
    version_id: UUID
    handle: str
    public: LearningItemPublicV1
    proof_id: UUID
    materialization_id: UUID
    consumption_proof: NativeConsumptionProofV1
    publication_enabled: bool = False
    inventory_ready: bool = False
    evidence_policy_version: str = "autonomous_evidence_policy_v2"
    diagnostic_warnings: tuple[str, ...] = ()


class NativePublishedItemQuery:
    """Exact internal current-proof query. Never a 2/2/1 pack-ready selector."""
    def __init__(self, conn: Connection[dict[str, Any]], *,
                 approved_internal_bindings: tuple[NativeInternalRuntimeBindingV1, ...] = (),
                 runtime_owner: ExecutionIntentRepository | None = None, enabled: bool = False) -> None:
        self.conn = conn
        self.artifacts = SharedPipelineArtifactRepository(conn, enabled=enabled)
        if runtime_owner is not None and (type(runtime_owner) is not ExecutionIntentRepository or runtime_owner._conn is not conn):
            raise NativePublicationPending("native_current_runtime_owner_required")
        self.runtime_owner = runtime_owner
        self._bindings: dict[str, NativeInternalRuntimeBindingV1] = {
            b.target_id: checked_model(b, NativeInternalRuntimeBindingV1) for b in approved_internal_bindings}

    def _current_runtime(self, binding: NativeInternalRuntimeBindingV1, *, now: datetime) -> str | None:
        if binding.runtime_lock is None:
            return None  # The actual static scorer is rechecked below; never OS health.
        owner = self.runtime_owner
        if owner is None or owner._registry.lock_for(binding.runtime_id) != binding.runtime_lock:
            raise NativePublicationPending("native_current_runtime_owner_or_lock_unavailable")
        available = owner.availability_for_runtime(binding.runtime_id, now=now)
        if not available.available:
            raise NativePublicationPending("native_current_runtime_health_unavailable")
        return owner._registry.fingerprint

    def _require_actual_public_proof(self, proof: NativePublicationProofV1, source: LearningItemSourceV1,
                                    spec: FiniteCandidateSpecV1) -> tuple[str, ...]:
        """Read proof-bound immutable audit DATA, never restore an issuer capability.

        The existing native proof references the original admission facts by ID
        AND digest. Those facts already carry the reviewed actual public hash;
        template equivalence alone cannot authorize arbitrary V3 presentation.
        Legacy strict versions need no new historical facts lookup.
        """
        if spec.blueprint.version != FLEXIBLE_FACTORY_VERSION and proof.policy_hash != AutonomousEvidencePolicyV3().policy_hash:
            return ()
        row = self.conn.execute(
            "SELECT payload_json,payload_hash FROM tutor_item_supply_shared_admission_facts WHERE id=%s",
            (proof.facts_receipt_id,),
        ).fetchone()
        if row is None:
            raise NativePublicationPending("native_published_actual_public_proof_missing")
        try:
            facts = IssuedSharedAdmissionFactsV1.model_validate_json(json.dumps(row["payload_json"]))
        except (ValueError, TypeError, KeyError):
            raise NativePublicationPending("native_published_actual_public_proof_missing") from None
        target = facts.target_proof
        if (facts.receipt_hash != row["payload_hash"] or facts.receipt_hash != proof.facts_hash
                or facts.receipt_id != proof.facts_receipt_id
                or facts.generation_artifact_id != proof.generation_artifact_id or facts.version_id != proof.version_id
                or facts.lease != proof.lease or facts.specification_hash != spec.specification_hash
                or facts.target_id != proof.target_id or facts.target_definition_hash != proof.target_definition_hash
                or facts.public_task_hash != source.public.public_hash
                or facts.ambiguity.plan.public_task_hash != source.public.public_hash
                or facts.evidence.binding.source_hash != source.source_hash
                or facts.evidence.binding.content_hash != source.content_hash
                or facts.validation_receipt_id != proof.validation_receipt_id
                or facts.validation_receipt_hash != proof.validation_hash
                or facts.review_receipt_id != proof.review_receipt_id or facts.review_receipt_hash != proof.review_hash
                or canonical_hash(facts.evidence.model_dump(mode="json")) != proof.evidence_hash
                or facts.evaluation.disposition != "eligible_internal" or target is None
                or target.public_task_hash != source.public.public_hash or target.source_hash != source.source_hash
                or target.specification_hash != spec.specification_hash
                or target.target_id != spec.target_id or target.target_definition_hash != spec.target_definition_hash):
            raise NativePublicationPending("native_published_actual_public_proof_mismatch")
        if (facts.evaluation.policy_version != policy_for_hash(proof.policy_hash).policy_version
                or facts.evaluation.binding.policy_hash != proof.policy_hash):
            raise NativePublicationPending("native_published_policy_mismatch")
        return diagnostic_warnings(facts.evaluation)

    def query_exact(self, *, handle: str, spec: FiniteCandidateSpecV1,
                    source_authority: RagSourceAuthority) -> NativePublishedItemData | None:
        self.artifacts.require_owner()
        self.artifacts.require_source(source_authority)
        spec = checked_model(spec, FiniteCandidateSpecV1)
        runtime = _runtime(spec, self._bindings)
        row = self.conn.execute("SELECT p.proof_json,p.proof_hash,p.runner_material_json,c.public_json,g.source_json,"
            "g.request_json,g.root_id,g.job_id,g.lease_generation,"
            "m.exercise_content_hash,m.rubric_hash,m.receipt_hash AS materialization_hash,e.occurred_at "
            "FROM tutor_learning_item_native_publication_proofs p "
            "JOIN tutor_learning_item_versions v ON v.id=p.version_id "
            "JOIN tutor_learning_item_public_contents c ON c.version_id=v.id "
            "JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=p.generation_artifact_id "
            "JOIN tutor_learning_item_practice_materializations m ON m.id=p.materialization_id AND m.version_id=v.id "
            "JOIN LATERAL(SELECT id,state,occurred_at FROM tutor_learning_item_publication_events WHERE version_id=v.id "
            "ORDER BY state_version DESC LIMIT 1) e ON e.id=p.publication_event_id AND e.state='published' "
            "WHERE v.handle=%s", (handle,)).fetchone()
        if row is None:
            return None
        proof = NativePublicationProofV1.model_validate_json(json.dumps(row["proof_json"]))
        now = server_clock(self.conn, datetime.now(UTC))
        if (proof.proof_hash != row["proof_hash"] or proof.item_handle != handle or proof.runtime != runtime
                or proof.specification_hash != spec.specification_hash or proof.target_definition_hash != spec.target_definition_hash
                or proof.policy_hash != policy_for_hash(proof.policy_hash).policy_hash
                or not proof.checked_at <= row["occurred_at"] < proof.valid_until):
            return None
        # Historical publishing authorization is NOT renewed. Current consumption
        # independently checks unchanged source, materialization, policy and health;
        # it never asks whether the old producer job is still leased/completed.
        source = LearningItemSourceV1.model_validate_json(json.dumps(row["source_json"]))
        if (source.source_hash, source.content_hash) != (proof.source_hash, proof.content_hash):
            raise NativePublicationPending("native_published_source_snapshot_mismatch")
        warnings = self._require_actual_public_proof(proof, source, spec)
        if self.artifacts.published_generation_policy(row).policy_hash != proof.policy_hash:
            raise NativePublicationPending("native_published_generation_policy_mismatch")
        materialization = build_native_practice_material(source, spec=spec, materials=proof.materials)
        if (row["exercise_content_hash"] != materialization.exercise.content_hash
                or row["rubric_hash"] != materialization.rubric.rubric_hash
                or row["materialization_hash"] != proof.materialization_hash
                or dict(materialization.runner_payload) != row["runner_material_json"]
                or canonical_hash(row["runner_material_json"]) != proof.runner_material_hash):
            raise NativePublicationPending("native_published_materialization_mismatch")
        # Match publication's source -> bank-version lock order. Discovery above
        # is not a current-state fence: quarantine may commit while source checks
        # wait. Lock the version, then use a NEW read-committed statement to see
        # the latest event (a SELECT snapshot taken before the lock wait is old).
        for material, receipt in zip(proof.materials, proof.source_receipts, strict=True):
            source_authority.assert_current(material, receipt)
        locked = self.conn.execute(
            "SELECT id FROM tutor_learning_item_versions WHERE id=%s AND handle=%s FOR SHARE",
            (proof.version_id, handle),
        ).fetchone()
        if locked is None:
            return None
        current_event = self.conn.execute(
            "SELECT id,state FROM tutor_learning_item_publication_events WHERE version_id=%s "
            "ORDER BY state_version DESC LIMIT 1", (proof.version_id,),
        ).fetchone()
        if (current_event is None or current_event["state"] != "published"
                or UUID(str(current_event["id"])) != proof.publication_event_id):
            return None
        # Recheck source time bounds after any bank-lock wait. The historical
        # producer lease/facts remain audit data and are never renewed here.
        current_receipts = []
        for material, receipt in zip(proof.materials, proof.source_receipts, strict=True):
            current = checked_model(source_authority.assert_current(material, receipt), SourceReceiptV2)
            current_receipts.append(canonical_hash(current.model_dump(mode="json")))
        checked_at = server_clock(self.conn, now)
        health_hash = self._current_runtime(runtime, now=checked_at)
        public = LearningItemPublicV1.model_validate_json(json.dumps(row["public_json"]))
        if public != source.public:
            raise NativePublicationPending("native_published_public_snapshot_mismatch")
        try:
            check_finite_public_spec(public, spec)
        except ValueError:
            raise NativePublicationPending("native_published_public_snapshot_mismatch") from None
        consumption = NativeConsumptionProofV1(publication_proof_id=proof.proof_id, publication_proof_hash=proof.proof_hash,
            version_id=proof.version_id, source_hash=proof.source_hash, content_hash=proof.content_hash,
            specification_hash=proof.specification_hash, materialization_hash=proof.materialization_hash,
            current_source_receipt_hashes=tuple(current_receipts), runtime_profile_hash=runtime.runtime_profile_hash,
            scorer_version=runtime.scorer_version, runtime_health_registry_hash=health_hash, checked_at=checked_at)
        return NativePublishedItemData(proof.version_id, handle, public, proof.proof_id, proof.materialization_id, consumption, evidence_policy_version=policy_for_hash(proof.policy_hash).policy_version,
            diagnostic_warnings=warnings)
