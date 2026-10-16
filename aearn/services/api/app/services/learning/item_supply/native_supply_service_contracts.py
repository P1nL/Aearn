"""DATA-only finite supply references and an intentionally tiny learner projection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.services.learning.item_supply.contracts import SupplyGapV1
from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability
from app.services.learning.item_supply.pack_contracts import PackSelectionV2

if TYPE_CHECKING:
    from app.services.learning.item_supply.private_enhancement_contracts import PrivateEnhancementReady
    from app.services.learning.item_supply.private_native_base_fallback import IssuedPrivateBaseFallback

EnhancementPreference = Literal["base_only", "prefer_private"]
SupplyDiagnostic = Literal[
    "exact_base_reserved", "disabled", "invalid_request", "current_authority_unavailable",
    "gap_dispatch_owner_missing", "relationship_evidence_missing", "inventory_bound_exceeded",
    "reservation_required", "reservation_conflict", "base_invalidated", "whole_pack_unavailable",
    "persistent_pack_preparing", "persistent_pack_blocked", "persistent_pack_paused",
    "private_authority_unavailable", "private_enhancement_preparing", "exact_private_reserved",
    "exact_whole_base_fallback",
]


@dataclass(frozen=True)
class NativeSupplyDemandRef:
    """Server-only original496 locators, NOT proof, lease or a pack capability.

    None means bounded discovery. An explicit tuple is exact: stale members are
    never silently omitted/replaced. Private enhancement is a preference only.
    """
    demand_id: UUID
    mapping_receipt_id: UUID
    candidate_version_ids: tuple[UUID, ...] | None = None
    relation_receipt_ids: tuple[UUID, ...] | None = None
    enhancement: EnhancementPreference = "base_only"

    def __post_init__(self) -> None:
        if type(self.demand_id) is not UUID or type(self.mapping_receipt_id) is not UUID:
            raise ValueError("native_supply_exact_locators_required")
        for refs in (self.candidate_version_ids, self.relation_receipt_ids):
            if refs is not None and (type(refs) is not tuple or len(refs) > 16
                    or any(type(v) is not UUID for v in refs) or len(set(refs)) != len(refs)):
                raise ValueError("native_supply_bounded_locators_required")
        if self.enhancement not in {"base_only", "prefer_private"}:
            raise ValueError("native_supply_invalid_preference")


class NativeSupplyLearnerStatusV1(BaseModel):
    """The ONLY learner-facing output; no IDs, hashes, handles or owner bodies."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["native_supply_learner_status_v1"] = "native_supply_learner_status_v1"
    status: Literal["ready", "preparing", "unavailable"]
    reason: Literal["available", "preparing", "not_available", "disabled"]
    allowed_actions: tuple[Literal["continue", "refresh"], ...]

    @model_validator(mode="after")
    def coherent(self) -> NativeSupplyLearnerStatusV1:
        expected = {"ready": ("available", ("continue",)),
                    "preparing": ("preparing", ("refresh",))}
        if self.status in expected:
            if (self.reason, self.allowed_actions) != expected[self.status]:
                raise ValueError("native_supply_invalid_projection")
        elif self.reason not in {"not_available", "disabled"} or self.allowed_actions != (
                () if self.reason == "disabled" else ("refresh",)):
            raise ValueError("native_supply_invalid_projection")
        return self


@dataclass(frozen=True)
class NativeSupplyReadyV1:
    """Private same-transaction handoff; authority stays with original501/502."""
    demand: NativeSupplyDemandRef = field(repr=False)
    capability: IssuedNativePackCapability = field(repr=False)
    selection: PackSelectionV2 = field(repr=False)
    reservation_id: UUID = field(repr=False)
    reservation_key: str = field(repr=False)


@dataclass(frozen=True)
class NativeSupplyFallbackReadyV1:
    """Explicit server-only pair; the original owners must require BOTH in one TX."""
    base: NativeSupplyReadyV1 = field(repr=False)
    whole_base_fallback: IssuedPrivateBaseFallback = field(repr=False)


@dataclass(frozen=True)
class NativeSupplyResultV1:
    """Do not export/asdict this private result; export .learner only."""
    status: Literal["ready_exact", "gap", "pending", "failed", "stale"]
    diagnostic: SupplyDiagnostic
    learner: NativeSupplyLearnerStatusV1
    enhancement_status: Literal["not_requested", "unsupported", "preparing", "ready", "unavailable", "waiting_ended"] = "not_requested"
    gaps: tuple[SupplyGapV1, ...] = field(default=(), repr=False)
    ready: NativeSupplyReadyV1 | None = field(default=None, repr=False)
    private_ready: PrivateEnhancementReady | None = field(default=None, repr=False)
    fallback_ready: NativeSupplyFallbackReadyV1 | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        is_fallback = self.diagnostic == "exact_whole_base_fallback"
        if is_fallback != (self.fallback_ready is not None):
            raise ValueError("native_supply_explicit_fallback_handoff_required")
        if is_fallback and (type(self.fallback_ready) is not NativeSupplyFallbackReadyV1
                or self.ready is not None or self.private_ready is not None
                or self.status != "ready_exact" or self.enhancement_status != "waiting_ended"
                or self.learner.status != "ready"):
            raise ValueError("native_supply_fallback_cannot_be_ordinary_ready")

