"""Ordinary PRIVATE KC successors from the retained whole pack; no FormalGate.

Selection runs before original assistance/response writes. Delivery reissues
current owners later; a persisted handle or purpose field grants no authority.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.services.learning.item_bank.contracts import canonical_hash, normalize_answer
from app.services.learning.item_supply.private_enhancement_contracts import (
    IssuedPrivateConsumerAuthority, PrivateNativePending, PrivateTeachingDeliveryContext,
)
from app.services.learning.item_supply.private_native_exposure import PrivateNativeExposureOwner

SuccessorPurpose = Literal['remediation','transfer_check']


class PrivateNativeSuccessorOwner:
    def __init__(self, consumer_owner: Any, exposure_owner: PrivateNativeExposureOwner) -> None:
        from app.services.learning.item_supply.private_native_consumer_bridge import PrivateNativeArtifactConsumerOwner
        if (type(consumer_owner) is not PrivateNativeArtifactConsumerOwner
                or type(exposure_owner) is not PrivateNativeExposureOwner
                or exposure_owner.type_owner is not consumer_owner.type_owner or exposure_owner.conn is not consumer_owner.conn):
            raise PrivateNativePending('private_successor_original_current_whole_pack_owners_required')
        self.consumer,self.exposure,self.conn=consumer_owner,exposure_owner,consumer_owner.conn

    @staticmethod
    def _signature(public: Any) -> str:
        return canonical_hash({'response_kind':public.content.response_kind,
            'prompt':normalize_answer(public.content.prompt_markdown),
            'options':sorted((o.option_id,normalize_answer(o.label)) for o in public.content.options)})

    def select(self, authority: IssuedPrivateConsumerAuthority, *, artifact: Any, purpose: SuccessorPurpose) -> str:
        if purpose not in ('remediation','transfer_check') or authority.action not in ('respond','request_direct_answer'):
            raise PrivateNativePending('private_successor_closed_ordinary_KC_consequence_required')
        current=self.consumer.require(authority,conn=self.conn,artifact=artifact,
            expected_mode='current',expected_action=authority.action)
        if current is None:
            raise PrivateNativePending('private_successor_current_source_required')
        binding=self.consumer._issued[authority.receipt_id][2]
        receipt=self.conn.execute('SELECT reservation_id FROM tutor_item_supply_private_native_consumer_receipts WHERE id=%s AND user_id=%s AND epoch=%s',
            (binding['creation_receipt_id'],self.consumer.type_owner.user_id,self.consumer.type_owner.epoch)).fetchone()
        if receipt is None:
            raise PrivateNativePending('private_successor_original_reservation_required')
        cap,_=self.exposure.resolve_reserved_pack(UUID(str(receipt['reservation_id'])))
        pack=self.exposure.type_owner.require_pack(cap)
        desired='remediation' if purpose=='remediation' else 'practice'
        parent_public=current.quality.source.public
        candidates=[]
        for selected in pack.selected:
            if selected.member.slot!=desired or selected.version_id==authority.version_id:
                continue
            content=self.exposure.type_owner.query.resolve_content(selected.version_id)
            public=content.quality.source.public
            if (public.kind.value!='knowledge_check' or self._signature(public)==self._signature(parent_public)
                    or (purpose=='remediation' and (parent_public.remediation_item_key is None
                        or public.item_key!=parent_public.remediation_item_key))):
                continue
            actual=self.conn.execute('SELECT item_supply_internal.private_native_successor_selected(%s,%s,%s,%s) AS ok',
                (authority.receipt_id,cap.eligibility_id,selected.version_id,purpose)).fetchone()
            if actual is not None and actual['ok'] is True:
                candidates.append(content.publication.item_handle)
        self.consumer.require(authority,conn=self.conn,artifact=artifact,expected_mode='current',expected_action=authority.action)
        if not candidates:
            raise PrivateNativePending('private_successor_current_mapped_nonidentical_training_member_unavailable')
        return sorted(candidates)[0]

    def delivery_context(self, *, parent_artifact_id: UUID, selected_version_id: UUID,
                         purpose: SuccessorPurpose, run_id: UUID) -> PrivateTeachingDeliveryContext:
        self.consumer._guard()
        row=self.conn.execute('SELECT b.pack_task_id,r.reservation_id,r.payload_json AS creation FROM tutor_item_supply_private_native_artifact_bindings b '
            'JOIN tutor_item_supply_private_native_consumer_receipts r ON r.id=b.creation_receipt_id '
            'WHERE b.artifact_id=%s AND b.user_id=%s AND b.epoch=%s',
            (parent_artifact_id,self.consumer.type_owner.user_id,self.consumer.type_owner.epoch)).fetchone()
        if row is None:
            raise PrivateNativePending('private_successor_actual_parent_binding_required')
        creation=row['creation']
        cap,_=self.exposure.resolve_reserved_pack(UUID(str(row['reservation_id'])))
        self.exposure.type_owner.require_pack(cap)
        checked=self.conn.execute('SELECT item_supply_internal.private_native_successor_delivery_current(%s,%s,%s,%s) AS ok',
            (parent_artifact_id,cap.eligibility_id,selected_version_id,purpose)).fetchone()
        if checked is None or checked['ok'] is not True:
            raise PrivateNativePending('private_successor_real_completed_response_current_whole_pack_required')
        return PrivateTeachingDeliveryContext(self.exposure,UUID(creation['mapping_id']),UUID(str(row['reservation_id'])),
            selected_version_id,run_id,UUID(str(row['pack_task_id'])),purpose=purpose,parent_artifact_id=parent_artifact_id)
