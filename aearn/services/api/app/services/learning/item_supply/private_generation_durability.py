"""Original live PRIVATE output observations, not persistence-recovery authority."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, GenerationResultV2, SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateSlotRef
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.private_enhancement_service import PreparedPrivateSlotGeneration


LOST_C14_CANDIDATE = UUID('eeebd057-3e04-4a61-8979-201446e20221')
C14_GAP_BINDING = UUID('af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6')


@dataclass(frozen=True)
class PrivateGenerationCaptureOutcome:
    # captured means appended in the caller TOP, never a commit acknowledgement.
    status: Literal['captured', 'capture_failed', 'not_applicable']
    output_id: UUID | None = None
    reason: str | None = None


def generation_context(prepared: PreparedPrivateSlotGeneration) -> dict[str, Any]:
    original = prepared.original
    return dict(ref=checked_model(prepared.ref,PrivateSlotRef).model_dump(mode='json'),
        request=checked_model(original.request,GenerationRequestV2).model_dump(mode='json'),
        lease=checked_model(original.lease,JobLeaseV1).model_dump(mode='json'), scope_id=str(original.scope_id),
        reservation_id=str(original.reservation_id),
        sources=[checked_model(s,SourceReceiptV2).model_dump(mode='json') for s in original.sources],
        attempt_bound=original.attempt_bound, mode=original.mode,
        producer_binding=None if original.producer_binding is None else list(original.producer_binding))


def _context_objects(prepared: PreparedPrivateSlotGeneration) -> tuple[object, ...]:
    original = prepared.original
    return prepared.ref, original, original.request, original.lease, original.sources


@dataclass(frozen=True, repr=False)
class ObservedPrivateGeneration:
    prepared: PreparedPrivateSlotGeneration
    result: GenerationResultV2
    result_hash: str
    context_hash: str
    context_objects: tuple[object, ...]

    @classmethod
    def observe(cls, prepared: PreparedPrivateSlotGeneration, result: GenerationResultV2) -> ObservedPrivateGeneration:
        if prepared.original.request.candidate_id == LOST_C14_CANDIDATE:
            raise PrivateNativePending('private_generation_historical_output_backfill_denied')
        checked = checked_model(result, GenerationResultV2)
        return cls(prepared, result, canonical_hash(checked.model_dump(mode='json')),
            canonical_hash(generation_context(prepared)), _context_objects(prepared))

    def require(self, prepared: PreparedPrivateSlotGeneration, result: GenerationResultV2) -> dict[str, Any]:
        if prepared.original.request.candidate_id == LOST_C14_CANDIDATE:
            raise PrivateNativePending('private_generation_historical_output_backfill_denied')
        if (prepared is not self.prepared or result is not self.result
                or any(a is not b for a, b in zip(self.context_objects, _context_objects(prepared), strict=True))):
            raise PrivateNativePending('private_generation_original_output_observation_required')
        payload = checked_model(result, GenerationResultV2).model_dump(mode='json')
        context = generation_context(prepared)
        if (canonical_hash(payload) != self.result_hash or canonical_hash(context) != self.context_hash):
            raise PrivateNativePending('private_generation_observed_output_changed')
        return dict(schema_version='private_generation_capture_v1', context=context, result=payload)
