"""Private V2 observations, not caller-issued readiness or delivery authority."""
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.services.learning.item_supply.pack_contracts import CompleteExposureV2

TYPE_COLLECTOR_VERSION = "native-type-exposure-v2"
NATIVE_TYPE_EXPOSURE_PRIVATE_PURGE_ORDER = (
    "tutor_item_supply_type_exposure_deliveries",
    "tutor_item_supply_type_exposure_reservations",
    "tutor_item_supply_type_exposure_snapshots",
)


@dataclass(frozen=True)
class NativeTypeExposureSnapshot:
    state: Literal["complete", "pending"]
    safe_reason: str
    exposure: CompleteExposureV2 | None = None
    snapshot_id: UUID | None = None
    original_watermark_id: UUID | None = None


class NativeTypeExposurePending(ValueError):
    """Internal fail-closed diagnostic; not a learner-visible private payload."""
