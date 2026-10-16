"""Explicit registered-family child version DATA; never a runtime permission."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import model_validator

from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.finite_candidate_factory import FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1, FiniteSlotAllocationV2
from app.services.learning.item_supply.storage_contracts import StorageContract


class PersistentRegisteredFamilyRevisionV1(StorageContract):
    schema_version: Literal["persistent_registered_family_revision_v1"] = "persistent_registered_family_revision_v1"
    phase_id: UUID
    public_slot_id: UUID
    parent_revision_id: UUID
    parent_specification_hash: Digest
    finding_key: Digest
    child_specification: FiniteCandidateSpecV1

    @model_validator(mode="after")
    def registered_public_kc(self) -> PersistentRegisteredFamilyRevisionV1:
        spec=self.child_specification
        if (spec.target_id!="python-kc-binding-v1" or type(spec.allocation) is not FiniteSlotAllocationV2
                or spec.allocation.slot!="assessment" or spec.blueprint.version!=FLEXIBLE_FACTORY_VERSION
                or spec.coverage_blueprint.scope.visibility!="public" or spec.coverage_blueprint.scope.owner_ref is not None
                or spec.python_goal is not None or spec.sql_target is not None):
            raise ValueError("explicit registered PUBLIC KC assessment child DATA required")
        return self

