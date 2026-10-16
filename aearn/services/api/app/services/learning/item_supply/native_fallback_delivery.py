"""Explicit PUBLIC whole-base fallback DATA on the original per-run writer.

No capability is cached here. Each call reacquires the concrete private union
and original public reservation/capability in the caller's current transaction.
SQL529 is a mandatory receiver, not a feature flag or a verifier callback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from app.services.learning.item_supply.native_supply_service_contracts import NativeSupplyFallbackReadyV1
from app.services.learning.item_supply.persistent_pack_contracts import PersistentPackTaskRef
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending
from app.services.learning.item_supply.storage_contracts import checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
    from app.services.learning.teaching_artifacts import NativeTeachingPracticeDeliveryContext


@dataclass(frozen=True, slots=True)
class NativeTeachingWholeBaseFallbackContext:
    private_service: PrivateEnhancementService = field(repr=False)
    task_ref: PersistentPackTaskRef = field(repr=False)
    selected_version_id: UUID
    run_id: UUID
    _native: NativeTeachingPracticeDeliveryContext = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
        from app.services.learning.teaching_artifacts import NativeTeachingPracticeDeliveryContext

        if (type(self.private_service) is not PrivateEnhancementService
                or type(self.selected_version_id) is not UUID or type(self.run_id) is not UUID):
            raise PrivateNativePending('fallback_delivery_concrete_service_and_run_required')
        task = checked_model(self.task_ref, PersistentPackTaskRef)
        base = self.private_service.base_service
        if ((task.user_id, task.epoch, task.mapping_receipt_id) != (base.user_id, base.epoch, base.mapping_id)
                or base.conn is not self.private_service.conn or base.settings is not self.private_service.settings
                or base.private_owner is not self.private_service):
            raise PrivateNativePending('fallback_delivery_original_same_connection_namespace_required')
        object.__setattr__(self, '_native', NativeTeachingPracticeDeliveryContext(
            base.exposure_owner, task.mapping_receipt_id, base._key(task.demand_id), self.selected_version_id))

    @property
    def native_context(self) -> NativeTeachingPracticeDeliveryContext:
        """Original public context contains locators only, never the fallback cap."""
        return self._native

    def _binding(self, run_id: str) -> None:
        from app.services.learning.item_supply.private_enhancement_service import PrivateEnhancementService
        from app.services.learning.teaching_artifacts import PostgresTeachingArtifactMaterializer

        service = self.private_service
        task = checked_model(self.task_ref, PersistentPackTaskRef)
        if (type(service) is not PrivateEnhancementService or run_id != str(self.run_id)
                or (task.user_id, task.epoch, task.mapping_receipt_id)
                    != (service.base_service.user_id, service.base_service.epoch, service.base_service.mapping_id)
                or service.base_service.private_owner is not service
                or service.base_service.conn is not service.conn
                or self._native.exposure_owner is not service.base_service.exposure_owner
                or self._native.mapping_receipt_id != task.mapping_receipt_id
                or self._native.selected_version_id != self.selected_version_id
                or self._native.reservation_key != service.base_service._key(task.demand_id)):
            raise PrivateNativePending('fallback_delivery_exact_original_run_binding_required')
        PostgresTeachingArtifactMaterializer(service.conn, settings=service.settings)._native_context(self._native)

    def require_current(self, *, run_id: str,
                        stage: Literal['advertise', 'prepare', 'create']) -> None:
        """Fresh same-TX handoff; no end_wait, new task, replacement or JSON cap."""
        self._binding(run_id)
        if stage not in {'advertise', 'prepare', 'create'}:
            raise PrivateNativePending('fallback_delivery_closed_stage_required')
        service = self.private_service
        service._guard()
        # Missing prospective receiver is a safe stop BEFORE any provider call.
        receiver = service.conn.execute("SELECT to_regprocedure('item_supply_internal.private_native_public_fallback_record(jsonb)') AS receiver").fetchone()
        if receiver is None or receiver['receiver'] is None:
            raise PrivateNativePending('fallback_delivery_reviewed_529_receiver_required')
        demand = service.base_service._request_for(self.task_ref.demand_id)
        if demand.enhancement != 'prefer_private':
            raise PrivateNativePending('fallback_delivery_original_private_intent_required')
        result = service.fallback(demand, task_ref=self.task_ref)
        if result.fallback is None or result.base is None or result.base.ready is None:
            raise PrivateNativePending('fallback_delivery_current_whole_base_unavailable')
        handoff = NativeSupplyFallbackReadyV1(base=result.base.ready, whole_base_fallback=result.fallback)
        base = service.base_service.require_fallback_ready(handoff)
        pack = service.base_service.type_owner.require_pack(base.capability)
        selected = next((c for c in pack.selected if c.member.slot == 'practice'
                         and c.version_id == self.selected_version_id), None)
        retained = service.base_service._reservation(self.task_ref.demand_id)
        if (selected is None or retained is None or base.reservation_id != UUID(str(retained['id']))
                or base.reservation_key != self._native.reservation_key
                or selected.owner_id is not None or selected.epoch is not None
                or selected.candidate.visibility != 'public' or selected.candidate.owner_ref is not None
                or len(pack.selected) != 5
                or {str(c.version_id) for c in pack.selected} != set(retained['request_json']['candidate_version_ids'])):
            raise PrivateNativePending('fallback_delivery_retained_five_public_versions_and_practice_required')
        # Locators are DATA. The SQL receiver independently rechecks original
        # 502 reservation, public eligibility, private union and actual run scope.
        from psycopg.types.json import Jsonb
        frame = {'schema_version': 'private_native_public_fallback_clearance_v1',
                 'task_ref': self.task_ref.model_dump(mode='json'), 'run_id': run_id,
                 'stage': stage, 'selected_version_id': str(self.selected_version_id),
                 'reservation_id': str(base.reservation_id),
                 'public_eligibility_id': str(base.capability.eligibility_id),
                 'union_receipt_id': str(handoff.whole_base_fallback.receipt_id)}
        service.conn.execute('SELECT item_supply_internal.private_native_public_fallback_record(%s)', (Jsonb(frame),))
        service.base_service.require_fallback_ready(handoff)
        self._binding(run_id)

