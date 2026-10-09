"""Bounded internal P7 snapshots. Data identity never grants admission authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1,
    canonical_hash,
    canonical_json,
)
from app.services.learning.item_bank.practice_adapter import (
    LEARNING_ITEM_PRACTICE_ADAPTER_VERSION,
    ExerciseAuthorityMaterial,
    build_exercise_authority,
)
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1,
    ClauseCoverageV1,
    CoverageBlueprintV1,
    Digest,
    Identifier,
    SafeReason,
    Slot,
    SupplyGapV1,
    require_aware,
)
from app.services.learning.item_supply.evidence import material_digest, require_exact_material
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2, SourceReceiptV2
from app.services.learning.item_supply.sandbox.python_goal_scorer import compile_goal_tests
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.practice.contracts import ExerciseSourceKind

PrivateItemHandle = Annotated[str, Field(
    min_length=43, max_length=43,
    pattern=r"^lip:v2:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
)]
MAX_PRIVATE_SNAPSHOT_BYTES = 1_048_576
MAX_PRIVATE_SELECTIONS = 64


def _bounded(value: object) -> None:
    if len(canonical_json(value).encode("utf-8")) > MAX_PRIVATE_SNAPSHOT_BYTES:
        raise ValueError("private snapshot exceeds bound")


class PrivateIdentityV1(StorageContract):
    user_id: UUID
    epoch: int = Field(ge=1, le=9_223_372_036_854_775_807)
    scope_id: UUID
    version_id: UUID

    def identity(self) -> tuple[UUID, int, UUID, UUID]:
        return self.user_id, self.epoch, self.scope_id, self.version_id


class PrivatePracticeMaterializationV1(PrivateIdentityV1):
    schema_version: Literal["private_practice_materialization_v1"] = "private_practice_materialization_v1"
    materialization_id: UUID
    source: LearningItemSourceV1 = Field(repr=False)
    source_hash: Digest
    content_hash: Digest
    # This is the existing PostgreSQL public_json::text || private_json::text
    # digest. It is NOT source_hash or LearningItemSourceV1.content_hash.
    version_payload_hash: Digest
    adapter_version: Identifier
    scorer_version: Identifier
    runtime_profile_id: Identifier
    runtime_profile_hash: Digest
    created_at: datetime

    @model_validator(mode="after")
    def exact_material(self) -> PrivatePracticeMaterializationV1:
        source = checked_model(self.source, LearningItemSourceV1)
        require_aware(self.created_at)
        if (self.source_hash != source.source_hash or self.content_hash != source.content_hash
                or self.adapter_version != LEARNING_ITEM_PRACTICE_ADAPTER_VERSION
                or self.runtime_profile_id != source.blueprint.runtime_profile_id):
            raise ValueError("private material identity mismatch")
        self.authority_material()
        _bounded(self.model_dump(mode="json"))
        return self

    def authority_material(self) -> ExerciseAuthorityMaterial:
        """Rebuild existing ExerciseVersion/rubric/runner; never accept naked dicts."""
        source = checked_model(self.source, LearningItemSourceV1)
        material = build_exercise_authority(source)
        if material is None:
            raise ValueError("private practice material unavailable")
        # The legacy pure adapter defaults to Git-curated fixtures. P7's concrete
        # publisher instead binds these snapshots to its actual registered live
        # generation artifact; never relabel that generation as curated content.
        exercise = replace(material.exercise, source_kind=ExerciseSourceKind.REGISTERED_AUTHOR)
        rubric = material.rubric
        runner_payload = dict(material.runner_payload)
        if source.blueprint.language_id == "python":
            # Reuse the exact server-owned compiler used by P5/P6. Its finite
            # goal declaration must survive materialization, or a constant with
            # matching stdout could replace the actual assignment objective.
            tests = compile_goal_tests(source)
            rubric = replace(rubric, private_test_bundle=tests)
            runner_payload["test_cases"] = list(tests)
        return replace(material, exercise=exercise, rubric=rubric, runner_payload=runner_payload)

    def storage_snapshot(self) -> dict[str, object]:
        """Derived JSON is storage only. The strictly typed source remains authority."""
        material = self.authority_material()
        payload: dict[str, object] = {
            "materialization": self.model_dump(mode="json"),
            "exercise": material.exercise.public_payload(),
            "rubric": {
                "rubric_version": material.rubric.rubric_version,
                "private_test_bundle": [dict(test) for test in material.rubric.private_test_bundle],
                "reference_answer": dict(material.rubric.reference_answer),
                "score_policy": dict(material.rubric.score_policy),
            },
            "runner_material": dict(material.runner_payload),
            "standard_submission": material.standard_submission,
            "starter_submission": material.starter_submission,
            "model_review_validation": (
                material.model_review_validation.model_dump(mode="json")
                if material.model_review_validation is not None else None
            ),
        }
        _bounded(payload)
        return payload

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self, PrivatePracticeMaterializationV1).storage_snapshot())


class PrivatePublicationReceiptV1(PrivateIdentityV1):
    schema_version: Literal["private_publication_receipt_v1"] = "private_publication_receipt_v1"
    publication_id: UUID
    generation_artifact_id: UUID
    facts_receipt_id: UUID
    evaluation_receipt_id: UUID
    materialization_id: UUID
    proof_id: UUID
    handle: PrivateItemHandle
    source_hash: Digest
    content_hash: Digest
    version_payload_hash: Digest
    transition_key: Identifier
    predecessor_event_id: UUID | None
    state_version: int = Field(ge=1, le=9_223_372_036_854_775_807)
    state: Literal["published", "quarantined", "retired"]
    checked_at: datetime
    admission_valid_until: datetime

    @model_validator(mode="after")
    def transition_shape(self) -> PrivatePublicationReceiptV1:
        require_aware(self.checked_at)
        require_aware(self.admission_valid_until)
        if self.state == "published":
            if (self.state_version != 1 or self.predecessor_event_id is not None
                    or self.admission_valid_until <= self.checked_at):
                raise ValueError("invalid initial private publication")
        elif (self.state_version < 2 or self.predecessor_event_id is None
              or self.predecessor_event_id == self.publication_id):
            raise ValueError("invalid private publication successor")
        return self

    @property
    def request_hash(self) -> str:
        return canonical_hash(checked_model(self, PrivatePublicationReceiptV1).model_dump(mode="json"))


class PrivateSourceBindingV1(StorageContract):
    material: PublicMaterialV2 = Field(repr=False)
    receipt: SourceReceiptV2

    @model_validator(mode="after")
    def exact_source(self) -> PrivateSourceBindingV1:
        material = require_exact_material(self.material)
        receipt = checked_model(self.receipt, SourceReceiptV2)
        coordinate = material.binding.evidence[0]
        if (receipt.mode != "current_authority"
                or receipt.material_digest != material_digest(material)
                or receipt.binding_digest != material.binding.binding_digest
                or str(receipt.corpus_version_id) != coordinate.corpus_version_id
                or receipt.active_generation != coordinate.active_generation
                or receipt.claim_receipt_hashes != (coordinate.claim_receipt_hash,)):
            raise ValueError("private source binding mismatch")
        require_aware(datetime.fromisoformat(receipt.checked_at_iso))
        _bounded(self.model_dump(mode="json"))
        return self


class PrivatePublishedCoverageV1(PrivateIdentityV1):
    schema_version: Literal["private_published_coverage_v1"] = "private_published_coverage_v1"
    proof_id: UUID
    publication_id: UUID
    materialization_id: UUID
    generation_artifact_id: UUID
    facts_receipt_id: UUID
    evaluation_receipt_id: UUID
    demand_id: UUID
    demand: AssessmentSupplyDemandV1
    blueprint: CoverageBlueprintV1
    clauses: tuple[ClauseCoverageV1, ...] = Field(min_length=1, max_length=64)
    candidate_family_id: Identifier
    slot: Slot
    source_hash: Digest
    content_hash: Digest
    version_payload_hash: Digest
    sources: tuple[PrivateSourceBindingV1, ...] = Field(min_length=1, max_length=12, repr=False)
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def exact_coverage(self) -> PrivatePublishedCoverageV1:
        demand = checked_model(self.demand, AssessmentSupplyDemandV1)
        blueprint = checked_model(self.blueprint, CoverageBlueprintV1)
        require_aware(self.checked_at)
        require_aware(self.valid_until)
        if (self.valid_until <= self.checked_at or demand.scope.visibility != "private"
                or demand.learner_ref != f"user:{self.user_id}"
                or demand.scope.owner_ref != f"user:{self.user_id}"
                or demand.scope.model_dump(exclude={"visibility", "owner_ref"})
                != blueprint.scope.model_dump(exclude={"visibility", "owner_ref"})
                or (blueprint.scope.visibility == "private" and blueprint.scope.owner_ref != demand.scope.owner_ref)
                or demand.blueprint_hash != blueprint.blueprint_hash
                or demand.objective_hash != blueprint.objective_hash
                or demand.matrix_hash != blueprint.matrix_hash
                or demand.policy_version != blueprint.policy_version):
            raise ValueError("private demand blueprint mismatch")
        expected = {(clause.clause_id, clause.clause_hash) for clause in blueprint.clauses}
        actual = {(clause.clause_id, clause.clause_hash) for clause in self.clauses}
        if len(actual) != len(self.clauses) or not actual <= expected:
            raise ValueError("private clause coverage mismatch")
        sources = tuple(checked_model(source, PrivateSourceBindingV1) for source in self.sources)
        if len({source.receipt.material_digest for source in sources}) != len(sources):
            raise ValueError("duplicate private source binding")
        if any(source.material.binding.evidence[0].subject_id != demand.scope.subject_id for source in sources):
            raise ValueError("private source subject mismatch")
        _bounded(self.model_dump(mode="json"))
        return self

    @property
    def proof_hash(self) -> str:
        return canonical_hash(checked_model(self, PrivatePublishedCoverageV1).model_dump(mode="json"))


class PrivateSupplySelectionV1(StorageContract):
    handle: PrivateItemHandle
    publication_id: UUID
    materialization_id: UUID
    proof_id: UUID


class PrivateSupplyResultV1(StorageContract):
    schema_version: Literal["private_supply_result_v1"] = "private_supply_result_v1"
    status: Literal["ready_exact", "gap", "pending", "failed", "stale"]
    demand_hash: Digest
    blueprint_hash: Digest
    selected: tuple[PrivateSupplySelectionV1, ...] = Field(default=(), max_length=MAX_PRIVATE_SELECTIONS)
    gaps: tuple[SupplyGapV1, ...] = Field(default=(), max_length=192)
    reasons: tuple[SafeReason, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def coherent_result(self) -> PrivateSupplyResultV1:
        if (len(set(self.selected_handles)) != len(self.selected)
                or len(set(self.reasons)) != len(self.reasons)):
            raise ValueError("duplicate private supply selection")
        if self.status == "ready_exact" and (not self.selected or self.gaps or self.reasons):
            raise ValueError("private ready result incomplete")
        return self

    @property
    def selected_handles(self) -> tuple[str, ...]:
        return tuple(item.handle for item in self.selected)


class PrivatePublishedRecordV1(StorageContract):
    publication: PrivatePublicationReceiptV1
    materialization: PrivatePracticeMaterializationV1 = Field(repr=False)
    proof: PrivatePublishedCoverageV1 = Field(repr=False)

    @model_validator(mode="after")
    def exact_record(self) -> PrivatePublishedRecordV1:
        publication, materialization, proof = self.publication, self.materialization, self.proof
        if (publication.identity() != materialization.identity()
                or publication.identity() != proof.identity()
                or publication.materialization_id != materialization.materialization_id
                or publication.materialization_id != proof.materialization_id
                or publication.publication_id != proof.publication_id
                or publication.proof_id != proof.proof_id
                or publication.generation_artifact_id != proof.generation_artifact_id
                or publication.facts_receipt_id != proof.facts_receipt_id
                or publication.evaluation_receipt_id != proof.evaluation_receipt_id
                or publication.state != "published"):
            raise ValueError("private publication record mismatch")
        for name in ("source_hash", "content_hash", "version_payload_hash"):
            if not getattr(publication, name) == getattr(materialization, name) == getattr(proof, name):
                raise ValueError("private publication hash mismatch")
        scope = proof.demand.scope
        item = materialization.source.blueprint
        if (materialization.runtime_profile_id != scope.runtime_profile_id
                or materialization.runtime_profile_hash != scope.runtime_profile_hash
                or materialization.scorer_version != scope.scorer_version
                or item.language_id != scope.language_id or item.knowledge_key != scope.knowledge_key
                or item.item_kind != scope.item_kind or item.purpose != scope.purpose
                or set(item.required_capabilities) != set(scope.required_capabilities)
                or scope.interaction not in item.allowed_interactions
                or proof.checked_at != publication.checked_at
                or proof.valid_until != publication.admission_valid_until):
            raise ValueError("private publication scope mismatch")
        return self
