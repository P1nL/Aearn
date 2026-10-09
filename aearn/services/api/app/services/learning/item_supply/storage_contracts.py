"""Strict P2 storage contracts. No provider, worker, scoring or publication."""
from __future__ import annotations

from typing import Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier


class StorageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")


T = TypeVar("T", bound=BaseModel)


def checked_model(value: T, kind: type[T]) -> T:
    """Validate all fields, including subclass extras and copy/construct mutations."""
    if type(value) is not kind:
        raise ValueError("invalid storage contract")
    def original_fields(node: object) -> object:
        if isinstance(node, BaseModel):
            if set(node.__dict__) - set(type(node).model_fields) or node.__pydantic_extra__:
                raise ValueError("invalid storage fields")
            # Do not use any serializer here: excluded fields and base-annotated
            # subclass fields must remain visible to the target's extra=forbid.
            # Legacy Item models do not revalidate instances, so rebuild their
            # original Python tree too, without JSON coercion or mutation.
            return {key: original_fields(child) for key, child in node.__dict__.items()}
        if isinstance(node, tuple):
            return tuple(original_fields(child) for child in node)
        if isinstance(node, list):
            return [original_fields(child) for child in node]
        if isinstance(node, dict):
            return {key: original_fields(child) for key, child in node.items()}
        return node
    try:
        return kind.model_validate(original_fields(value), strict=True)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise ValueError("invalid storage contract") from None


class SourceCoordinatesV2(StorageContract):
    subject: Identifier
    corpus_id: UUID
    document_id: UUID
    chunk_id: UUID
    receipt_id: UUID


class ObservationV2(StorageContract):
    schema_version: Literal["observation_v2"] = "observation_v2"
    origin: Literal["simulation", "real_learner", "deterministic_probe"]
    event_key: Identifier
    event_kind: Identifier
    receipt_hash: Digest
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    collector_identity: Identifier | None = None
    session_id: UUID | None = None
    actor_id: UUID | None = None
    terminal_receipt_id: UUID | None = None
    attempt_id: UUID | None = None

    @model_validator(mode="after")
    def authority_shape(self) -> ObservationV2:
        values = (self.collector_identity, self.session_id, self.actor_id,
                  self.terminal_receipt_id, self.attempt_id)
        if self.origin == "real_learner":
            if any(value is None for value in values):
                raise ValueError("real observation authority missing")
        elif any(value is not None for value in values):
            raise ValueError("non-real observation contains learner authority")
        return self


class EvidenceV2(StorageContract):
    schema_version: Literal["item_supply_evidence_v2"] = "item_supply_evidence_v2"
    policy_version: Literal["autonomous_evidence_policy_v2"] = "autonomous_evidence_policy_v2"
    evidence_key: Identifier
    producer_identity: Identifier
    evidence_kind: Identifier
    receipt_hash: Digest
    source: SourceCoordinatesV2 | None = None


class AutonomousEvidencePolicyV2(StorageContract):
    schema_version: Literal["autonomous_evidence_policy_v2"] = "autonomous_evidence_policy_v2"
    policy_version: Literal["autonomous_evidence_policy_v2"] = "autonomous_evidence_policy_v2"
    publication_enabled: Literal[False] = False
    required_review_roles: tuple[Literal[
        "curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial"
    ], ...] = ("curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial")
    risk_adapter_required: Literal[True] = True
    independent_second_bundle_required: Literal[True] = True

    @model_validator(mode="after")
    def complete_roles(self) -> AutonomousEvidencePolicyV2:
        if self.required_review_roles != (
            "curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial"
        ):
            raise ValueError("v2 review roles cannot be weakened")
        return self

    @property
    def policy_hash(self) -> str:
        return canonical_hash(checked_model(self, AutonomousEvidencePolicyV2).model_dump(mode="json"))


class AdmissionDecisionV2(StorageContract):
    schema_version: Literal["item_supply_admission_v2"] = "item_supply_admission_v2"
    policy_version: Literal["autonomous_evidence_policy_v2"] = "autonomous_evidence_policy_v2"
    admission_key: Identifier
    decision: Literal["blocked", "evidence_pending"]
    safe_reason: Literal["feature_disabled", "trusted_adapters_pending"]
