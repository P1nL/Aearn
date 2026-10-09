"""Private staging contracts; content shape is v1, candidate authority is not."""
from __future__ import annotations

from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.material_contracts_v2 import EvidenceBindingV2
from app.services.grounding.public_course_contracts import PublicCourseEvidenceBindingV1
from app.services.learning.item_bank.contracts import (
    LearningItemBlueprintV1, LearningItemPublicV1, LearningItemSourceV1,
)
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.parameter_profiles import FrozenProfileSnapshot
from app.services.learning.item_supply.storage_contracts import StorageContract


class GenerationLimitsV2(StorageContract):
    max_input_bytes: int = Field(ge=1, le=1_048_576)
    max_output_tokens: int = Field(ge=1, le=131_072)
    max_output_bytes: int = Field(ge=1, le=262_144)


class PublicMaterialV2(StorageContract):
    classification: Literal["approved_public"] = "approved_public"
    binding: Annotated[EvidenceBindingV2 | PublicCourseEvidenceBindingV1, Field(discriminator="contract_version")]
    access_request: AccessRequest
    exact_claims: tuple[VerifiedClaim, ...] = Field(min_length=1, max_length=12)
    excerpt: str = Field(min_length=1, max_length=64_000, repr=False)


class GenerationDemandBindingV1(StorageContract):
    """Server-only exact request locator, never part of the author prompt."""
    demand_id: UUID
    demand_hash: Digest


class GenerationRequestV2(StorageContract):
    schema_version: Literal["item_generation_request_v2"] = "item_generation_request_v2"
    candidate_id: UUID
    scope_hash: Digest
    demand_binding: GenerationDemandBindingV1 | None = Field(default=None, repr=False)
    item_key: Identifier
    version: Identifier
    blueprint: LearningItemBlueprintV1
    # Server-owned public task specification only: no private scoring/reference
    # answers, hidden tests or learner data. This is not source authorization.
    public_template: LearningItemPublicV1 | None = Field(default=None, repr=False)
    profile: FrozenProfileSnapshot
    limits: GenerationLimitsV2
    materials: tuple[PublicMaterialV2, ...] = Field(min_length=1, max_length=12, repr=False)


class ProviderUsageV2(StorageContract):
    state: Literal["known", "unknown"]
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cost: None = None

    @model_validator(mode="after")
    def complete_usage(self) -> ProviderUsageV2:
        if self.state == "known" and (self.input_tokens is None or self.output_tokens is None):
            raise ValueError("known usage requires both token dimensions")
        if self.cached_input_tokens is not None and (
            self.input_tokens is None or self.cached_input_tokens > self.input_tokens
        ):
            raise ValueError("invalid cached usage")
        return self


class ProviderReceiptV2(StorageContract):
    provider: Identifier
    provider_version: Identifier
    configured_model: Identifier
    model: Identifier
    prompt_version: Identifier
    role: Literal["item_author"] = "item_author"
    run_id: UUID
    request_attempt_bound: int = Field(ge=1, le=3)
    # The core exposes no actual retry count; never infer all-attempt usage.
    actual_requests: int | None = Field(default=None, ge=1, le=3)
    usage: ProviderUsageV2
    mode: Literal["provider", "synthetic"]


class SourceReceiptV2(StorageContract):
    material_digest: Digest
    binding_digest: Digest
    corpus_version_id: UUID
    active_generation: int = Field(ge=1)
    checked_at_iso: str = Field(min_length=1, max_length=80)
    claim_receipt_hashes: tuple[Digest, ...] = Field(min_length=1, max_length=12)
    mode: Literal["current_authority", "synthetic"]


class GenerationReceiptV2(StorageContract):
    schema_version: Literal["item_generation_receipt_v2"] = "item_generation_receipt_v2"
    candidate_id: UUID
    scope_hash: Digest
    source_hash: Digest | None = None
    content_hash: Digest | None = None
    provider: ProviderReceiptV2
    sources: tuple[SourceReceiptV2, ...] = Field(min_length=1, max_length=12)


GenerationReason = Literal[
    "generation_disabled", "invalid_request", "source_unavailable", "source_mismatch",
    "privacy_denied", "input_limit", "deadline_exhausted", "provider_failed",
    "invalid_candidate", "candidate_mismatch", "output_limit", "staged",
]


class GenerationResultV2(StorageContract):
    state: Literal["staged", "blocked", "failed"]
    source: LearningItemSourceV1 | None = Field(default=None, repr=False)
    receipt: GenerationReceiptV2 | None = Field(default=None, repr=False)
    safe_reason: GenerationReason

    @model_validator(mode="after")
    def staged_shape(self) -> GenerationResultV2:
        if self.state == "staged":
            if (self.source is None or self.receipt is None or self.safe_reason != "staged"
                    or self.receipt.source_hash != self.source.source_hash
                    or self.receipt.content_hash != self.source.content_hash):
                raise ValueError("invalid staged result")
        elif self.source is not None or self.safe_reason == "staged":
            raise ValueError("rejected result contains candidate")
        return self

    def safe_summary(self) -> dict[str, object]:
        """Explicit external projection, not model_dump of the staging envelope."""
        return {"state": self.state, "safe_reason": self.safe_reason}


class ProviderGenerationV2(StorageContract):
    payload: dict[str, object] = Field(repr=False)
    receipt: ProviderReceiptV2


class GenerationProvider(Protocol):
    @property
    def provider_key(self) -> str: ...

    @property
    def configured_model(self) -> str: ...

    @property
    def request_attempt_bound(self) -> int: ...

    def generate(self, *, messages: tuple[dict[str, str], ...], limits: GenerationLimitsV2,
                 timeout_seconds: float) -> ProviderGenerationV2: ...


class SourceAuthority(Protocol):
    def authorize(self, material: PublicMaterialV2) -> SourceReceiptV2: ...

    def assert_current(self, material: PublicMaterialV2,
                       expected: SourceReceiptV2) -> SourceReceiptV2: ...
