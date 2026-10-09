"""Private exact frozen-course projections, never supply/publication authority."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier, Slot, Version
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.pack_contracts import PackRequestV1
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model


class FiniteCourseProfileV1(StorageContract):
    """Injected server registry entry; no runtime health or source permission."""
    profile_id: Identifier
    target_id: TargetId
    course_version: Version
    subject_version: Version
    runtime_profile_hash: Digest
    scorer_version: Version
    assistance_policy_hash: Digest
    policy_version: Version
    public_spec_version: Literal["finite-public-spec-v1", "finite-public-spec-v2", "finite-public-spec-v3"]

    @model_validator(mode="after")
    def version_domain(self) -> FiniteCourseProfileV1:
        if self.target_id != "python-state-update-v1" and self.public_spec_version == "finite-public-spec-v2":
            raise ValueError("Python public-spec revision is not a SQL/KC profile")
        if self.target_id == "python-kc-binding-v1" and self.runtime_profile_hash != canonical_hash({
            "runtime": "static-exact-v1", "scorer_version": self.scorer_version,
            "assessment_contract": self.target_id,
        }):
            raise ValueError("static profile must use its exact scorer identity")
        return self

    @property
    def profile_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteCourseProfileV1).model_dump(mode="json"))


class FrozenCourseNodeV1(StorageContract):
    user_id: UUID
    epoch: int = Field(ge=1)
    track_id: UUID
    revision_id: UUID
    node_id: UUID
    session_id: UUID
    draft_id: UUID
    draft_version: int = Field(ge=1)
    source_run_id: UUID
    source_input_revision: int = Field(ge=1)
    draft_content_hash: Digest
    plan_content_hash: Digest
    knowledge_key: Identifier
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=300)
    language_id: Identifier
    is_core: bool
    prerequisite_keys: tuple[Identifier, ...] = Field(max_length=64)
    required_capabilities: tuple[Identifier, ...] = Field(min_length=1, max_length=24)
    catalog_knowledge_key: Identifier | None
    goal_hash: Digest
    selection_handle: Identifier
    selection_digest: Digest
    assessment_binding_id: UUID
    assessment_binding_digest: Digest


class StoredCourseDemandV1(StorageContract):
    slot: Slot
    scope_id: UUID
    demand_id: UUID


class FiniteCourseMappingReceiptV1(StorageContract):
    schema_version: Literal["finite_course_mapping_v1"] = "finite_course_mapping_v1"
    receipt_id: UUID
    frozen_node: FrozenCourseNodeV1
    target_id: TargetId
    target_definition_hash: Digest
    profile: FiniteCourseProfileV1
    mapping_hash: Digest
    pack_request: PackRequestV1
    stored_demands: tuple[StoredCourseDemandV1, ...] = Field(min_length=3, max_length=3)
    # Audit only. resolve MUST re-run C/claim authorization, never restore this.
    source_authorization_hash: Digest
    checked_at: datetime

    @model_validator(mode="after")
    def exact_scope(self) -> FiniteCourseMappingReceiptV1:
        n, p = self.frozen_node, self.pack_request
        if (self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None
                or (p.learner_id, p.epoch, p.track_id, p.revision_id, p.node_id) != (
                    n.user_id, n.epoch, n.track_id, n.revision_id, n.node_id)
                or p.course_mapping_hash != self.mapping_hash
                or p.target_id != self.target_id or self.profile.target_id != self.target_id
                or p.target_definition_hash != self.target_definition_hash
                or tuple(d.slot for d in self.stored_demands) != ("practice", "assessment", "remediation")
                or tuple(d.scope_id for d in self.stored_demands) != tuple(d.storage_scope_id for d in p.demands)):
            raise ValueError("course mapping receipt scope mismatch")
        return self


class FiniteCourseMappingResultV1(StorageContract):
    status: Literal["mapped_internal", "pending"]
    reason: Literal["exact_frozen_mapping", "gate_closed", "confirmed_course_missing", "frozen_node_mismatch",
                    "assessment_binding_missing", "assessment_selection_pending", "source_or_claim_stale",
                    "mapping_missing_or_stale", "profile_missing"]
    receipt: FiniteCourseMappingReceiptV1 | None = None

    @model_validator(mode="after")
    def non_ready(self) -> FiniteCourseMappingResultV1:
        if (self.status == "mapped_internal") != (self.receipt is not None) or (
            self.reason == "exact_frozen_mapping") != (self.status == "mapped_internal"):
            raise ValueError("mapping result is inconsistent")
        return self
