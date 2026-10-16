"""Private native exposure observations, never family-independence/ready grants."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.pack_contracts import CompleteExposureV1
from app.services.learning.item_supply.storage_contracts import StorageContract

COLLECTOR_VERSION = "native-exposure-v1"
# New current-pack observations only; upstream bounds and issued DATA never renew.
CURRENT_PACK_TTL = timedelta(seconds=120)

# All are learner-private. Main must delete in THIS order, after the epoch fence
# and reset permit, before existing private scopes and before the users row.
NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER = (
    "tutor_item_supply_native_exposure_deliveries",
    "tutor_item_supply_native_exposure_reservations",
    "tutor_item_supply_native_exposure_watermarks",
    "tutor_item_supply_native_exposure_events",
    "tutor_item_supply_native_exposure_inbox",
    "tutor_item_supply_native_exposure_births",
)


class NativeExposureBindingV1(StorageContract):
    version_id: UUID
    item_handle: str = Field(pattern=r"^li:[0-9a-f]{64}$")
    content_hash: Digest
    proof_id: UUID
    proof_hash: Digest
    specification_hash: Digest
    family_id: Identifier
    family_definition_hash: Digest
    # Conservative immutable family identity, NOT an independence witness.
    semantic_signature: Digest
    allocation_slot: Literal["practice", "assessment", "remediation"]


@dataclass(frozen=True)
class NativeExposureSnapshot:
    state: Literal["complete", "pending"]
    safe_reason: str
    exposure: CompleteExposureV1 | None = None
    watermark_id: UUID | None = None


class NativeExposurePending(ValueError):
    """Closed internal denial. Never expose another learner's existence."""
