"""Native internal bank provenance; not family/inventory or learner authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Literal
from uuid import UUID

from aearn_shared.execution import RuntimeImageLockV1
from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.practice_adapter import ExerciseAuthorityMaterial, build_exercise_authority
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2, SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.sandbox.python_goal_scorer import compile_goal_tests
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.practice.contracts import ExerciseSourceKind
from app.services.learning.practice.quality import require_exercise_quality


class NativePublicationPending(ValueError):
    """Bounded internal denial, never implicit permission or exception details."""


class NativeInternalRuntimeBindingV1(StorageContract):
    """Explicit server-approved B1d configuration, not a public registry change."""
    target_id: TargetId
    runtime_id: str
    runtime_profile_hash: Digest
    scorer_version: str
    runner_version: str | None = None
    runtime_lock: RuntimeImageLockV1 | None = None

    @model_validator(mode="after")
    def exact_static_shape(self) -> NativeInternalRuntimeBindingV1:
        expected = {"python-kc-binding-v1": "static-exact-v1", "python-state-update-v1": "python-stdout-v1",
                    "sqlite-predicate-order-v1": "sqlite-query-v1"}[self.target_id]
        if self.runtime_id != expected:
            raise ValueError("native_runtime_target_mismatch")
        if self.target_id == "python-kc-binding-v1":
            if self.runtime_lock is not None or self.runner_version is not None:
                raise ValueError("native_static_os_binding_denied")
        elif (self.runtime_lock is None or self.runner_version is None
                or self.runtime_lock.runtime_id != self.runtime_id
                or self.runtime_lock.fingerprint != self.runtime_profile_hash):
            raise ValueError("native_internal_pinned_runtime_required")
        return self


class NativePublicationProofV1(StorageContract):
    schema_version: Literal["native_learning_item_publication_v1"] = "native_learning_item_publication_v1"
    proof_id: UUID
    version_id: UUID
    item_handle: str = Field(pattern=r"^li:[0-9a-f]{64}$")
    generation_artifact_id: UUID
    source_hash: Digest
    content_hash: Digest
    specification_hash: Digest
    target_id: TargetId
    target_definition_hash: Digest
    clauses: tuple[dict[str, str], ...]
    materials: tuple[PublicMaterialV2, ...] = Field(min_length=1, max_length=12, repr=False)
    source_receipts: tuple[SourceReceiptV2, ...] = Field(min_length=1, max_length=12, repr=False)
    lease: JobLeaseV1
    runtime: NativeInternalRuntimeBindingV1
    bank_validation_id: UUID
    validation_receipt_id: UUID
    validation_hash: Digest
    review_receipt_id: UUID
    review_hash: Digest
    evaluation_receipt_id: UUID
    evaluation_hash: Digest
    facts_receipt_id: UUID
    facts_hash: Digest
    evidence_hash: Digest
    materialization_id: UUID
    exercise_version_id: UUID
    materialization_hash: Digest
    runner_material_hash: Digest
    publication_event_id: UUID
    review_event_id: UUID
    pilot_event_id: UUID
    policy_hash: Digest
    checked_at: datetime
    valid_until: datetime
    origin: Literal["native_internal_b1d"] = "native_internal_b1d"
    publication_enabled: Literal[False] = False
    family_independence_status: Literal["pending"] = "pending"
    inventory_ready: Literal[False] = False

    @model_validator(mode="after")
    def bound_shape(self) -> NativePublicationProofV1:
        if (self.lease.visibility != "public" or self.checked_at.tzinfo is None or self.valid_until.tzinfo is None
                or not self.checked_at < self.valid_until <= min(self.lease.expires_at, self.lease.parent_deadline)
                or self.runtime.target_id != self.target_id or len(self.materials) != len(self.source_receipts)):
            raise ValueError("native_publication_proof_binding_invalid")
        return self

    @property
    def proof_hash(self) -> str:
        return canonical_hash(checked_model(self, NativePublicationProofV1).model_dump(mode="json"))


class NativeConsumptionProofV1(StorageContract):
    """Current read snapshot, never a reusable source grant or runner capability."""
    schema_version: Literal["native_item_current_consumption_v1"] = "native_item_current_consumption_v1"
    publication_proof_id: UUID
    publication_proof_hash: Digest
    version_id: UUID
    source_hash: Digest
    content_hash: Digest
    specification_hash: Digest
    materialization_hash: Digest
    current_source_receipt_hashes: tuple[Digest, ...]
    runtime_profile_hash: Digest
    scorer_version: str
    runtime_health_registry_hash: Digest | None
    checked_at: datetime
    mode: Literal["current_read_transaction_data_only"] = "current_read_transaction_data_only"
    publication_enabled: Literal[False] = False
    inventory_ready: Literal[False] = False


def build_native_practice_material(source: LearningItemSourceV1, *, spec: FiniteCandidateSpecV1,
                                  materials: tuple[PublicMaterialV2, ...]) -> ExerciseAuthorityMaterial:
    """Pure derivation only; the publisher separately verifies actual live authority.

    Preserve source bytes and existing quality/Practice structures, while keeping
    generated author provenance and the finite Python goal compiler in BOTH paths.
    """
    source, spec = checked_model(source, LearningItemSourceV1), checked_model(spec, FiniteCandidateSpecV1)
    prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    material = build_exercise_authority(source)
    if material is None:
        raise NativePublicationPending("native_practice_material_unavailable")
    exercise = replace(material.exercise, source_kind=ExerciseSourceKind.REGISTERED_AUTHOR)
    rubric, runner_payload = material.rubric, dict(material.runner_payload)
    if spec.target_id == "python-state-update-v1":
        tests = compile_goal_tests(source)
        rubric = replace(rubric, private_test_bundle=tests)
        runner_payload["test_cases"] = list(tests)
    require_exercise_quality(exercise, rubric, model_review_validation=material.model_review_validation)
    return replace(material, exercise=exercise, rubric=rubric, runner_payload=runner_payload)
