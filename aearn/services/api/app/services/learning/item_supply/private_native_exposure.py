"""Complete actual PUBLIC+PRIVATE exposure and private assessment protection.

Only original owner-table triggers create origins. Receipt/protection is not delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.native_exposure_contracts import CURRENT_PACK_TTL
from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2, _protected
from app.services.learning.item_supply.pack_contracts import CompleteExposureV2, NativeExposureV2
from app.services.learning.item_supply.private_enhancement_contracts import IssuedPrivatePackCapability, PrivateNativePending
from app.services.learning.item_supply.private_native_type_evidence import PrivateNativeTypeEvidenceOwner


@dataclass(frozen=True)
class PrivateExposureObservation:
    snapshot_id: UUID
    exposure: CompleteExposureV2


class PrivateNativeExposureOwner:
    def __init__(self, conn: Connection[dict[str, Any]], *, type_owner: PrivateNativeTypeEvidenceOwner,
                 public_owner: NativeExposureOwnerV2, enabled: bool = False) -> None:
        if (type(type_owner) is not PrivateNativeTypeEvidenceOwner or type_owner.conn is not conn
                or type(public_owner) is not NativeExposureOwnerV2 or public_owner.conn is not conn
                or (type_owner.user_id, type_owner.epoch) != (public_owner.user_id, public_owner.epoch)):
            raise PrivateNativePending('private_exposure_concrete_same_namespace_required')
        self.conn, self.type_owner, self.public_owner, self.enabled = conn, type_owner, public_owner, enabled
        self.user_id, self.epoch = type_owner.user_id, type_owner.epoch

    def _lock(self) -> None:
        if not self.enabled:
            raise PrivateNativePending('private_exposure_disabled')
        self.type_owner._guard()
        self.public_owner._lock()  # SAME original per-user lock, never a second lock order.

    def snapshot_complete(self) -> PrivateExposureObservation:
        self._lock()
        public = self.public_owner.snapshot_v2()
        if public.snapshot_id is None or public.exposure is None:
            raise PrivateNativePending('private_exposure_public_ledger_incomplete')
        hooks = self.conn.execute('SELECT item_supply_internal.private_native_exposure_hooks_current() AS ok').fetchone()
        if hooks is None or hooks['ok'] is not True:
            raise PrivateNativePending('private_exposure_hooks_incomplete')
        rows = self.conn.execute('SELECT * FROM tutor_item_supply_private_native_exposure_origins WHERE user_id=%s AND epoch=%s ORDER BY sequence LIMIT 4097',
            (self.user_id, self.epoch)).fetchall()
        if len(rows) + len(public.exposure.records) > 4096:
            raise PrivateNativePending('private_exposure_inventory_bound')
        records = list(public.exposure.records)
        for row in rows:
            content = self.type_owner.query.resolve_content(UUID(str(row['version_id'])), current=False)
            if row['binding_hash'] != canonical_hash(content.content.model_dump(mode='json')):
                raise PrivateNativePending('private_exposure_actual_content_required')
            records.append(NativeExposureV2(event_id=UUID(str(row['id'])), item_handle=content.content.item_handle,
                content_hash=content.content.content_hash, family_id=content.quality.spec.allocation.family_id,
                semantic_signature=content.quality.spec.family_definition_hash, kind=row['kind'], content=content.content))
        now, _ = self.type_owner._guard()
        watermark = int(rows[-1]['sequence']) if rows else 0
        digest = canonical_hash({'public': public.exposure.completeness_receipt_hash, 'private_watermark': watermark,
            'private_count': len(rows), 'records': [r.model_dump(mode='json') for r in records]})
        exposure = CompleteExposureV2(learner_id=self.user_id, epoch=self.epoch,
            collector_version='private-native-union-v1', watermark=public.exposure.watermark + watermark,
            completeness_receipt_hash=digest, observed_at=now,
            valid_until=min(public.exposure.valid_until, now + CURRENT_PACK_TTL), records=tuple(records))
        sid = uuid4()
        self.conn.execute('INSERT INTO tutor_item_supply_private_native_exposure_snapshots '
            '(id,user_id,epoch,public_snapshot_id,private_watermark,private_count,payload_json,checked_at,valid_until) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (sid, self.user_id, self.epoch, public.snapshot_id, watermark, len(rows), Jsonb(exposure.model_dump(mode='json')), now, exposure.valid_until))
        return PrivateExposureObservation(sid, self.require_snapshot(sid))

    def require_snapshot(self, sid: UUID) -> CompleteExposureV2:
        self._lock()
        row = self.conn.execute('SELECT item_supply_internal.private_native_exposure_current(%s,%s,%s) AS payload',
            (sid, self.user_id, self.epoch)).fetchone()
        if row is None or row['payload'] is None:
            raise PrivateNativePending('private_exposure_current_snapshot_required')
        return CompleteExposureV2.model_validate_json(json.dumps(row['payload']))

    def reserve_assessment(self, *, cap: IssuedPrivatePackCapability, exposure_snapshot_id: UUID,
                           operation_key: str, base_reservation_id: UUID) -> UUID:
        self._lock()
        pack = self.type_owner.require_pack(cap)
        exposure = self.require_snapshot(exposure_snapshot_id)
        pair = _protected(pack, exposure)
        if pack.exposure_receipt_hash != exposure.completeness_receipt_hash:
            raise PrivateNativePending('private_exposure_same_union_required')
        base = self.conn.execute('SELECT user_id,epoch,scope_id FROM tutor_item_supply_type_exposure_reservations WHERE id=%s',
            (base_reservation_id,)).fetchone()
        if base is None or (UUID(str(base['user_id'])), int(base['epoch'])) != (self.user_id, self.epoch):
            raise PrivateNativePending('private_exposure_original_base_protection_required')
        eligibility = self.conn.execute(
            'SELECT mapping_id,payload_json FROM tutor_item_supply_private_native_eligibility '
            'WHERE id=%s AND user_id=%s AND epoch=%s',
            (cap.eligibility_id, self.user_id, self.epoch)).fetchone()
        if eligibility is None:
            raise PrivateNativePending('private_exposure_current_eligibility_required')
        refs = {'mapping_id': str(eligibility['mapping_id']),
            'versions': [str(c.version_id) for c in pack.selected],
            'relations': eligibility['payload_json']['relations'],
            'pack_request_hash': pack.request.request_hash, 'protected': [b.model_dump(mode='json') for b in pair]}
        # Immutable reconnect identity excludes fresh observations/relationship
        # receipt IDs. Those are re-resolved from current original quality owners.
        refs['binding_hash'] = canonical_hash({k: refs[k] for k in ('mapping_id','versions','pack_request_hash','protected')})
        digest = refs['binding_hash']
        row = self.conn.execute('INSERT INTO tutor_item_supply_private_native_assessment_reservations '
            '(id,user_id,epoch,scope_id,pack_task_id,operation_key,eligibility_id,exposure_snapshot_id,base_reservation_id,base_scope_id,payload_json) '
            'SELECT %s,%s,%s,scope_id,pack_task_id,%s,id,%s,%s,%s,%s FROM tutor_item_supply_private_native_eligibility WHERE id=%s '
            'ON CONFLICT(user_id,epoch,operation_key) DO NOTHING RETURNING id,payload_hash',
            (uuid4(), self.user_id, self.epoch, operation_key, exposure_snapshot_id,
             base_reservation_id, base['scope_id'], Jsonb(refs), cap.eligibility_id)).fetchone()
        if row is None:
            row = self.conn.execute('SELECT id,payload_hash FROM tutor_item_supply_private_native_assessment_reservations WHERE user_id=%s AND epoch=%s AND operation_key=%s',
                (self.user_id, self.epoch, operation_key)).fetchone()
        existing = None if row is None else self.conn.execute(
            'SELECT payload_json FROM tutor_item_supply_private_native_assessment_reservations WHERE id=%s', (row['id'],)).fetchone()
        if row is None or existing is None or existing['payload_json'].get('binding_hash') != digest:
            raise PrivateNativePending('private_exposure_reservation_conflict')
        self.type_owner.require_pack(cap)
        return UUID(str(row['id']))

    def resolve_reserved_pack(self, reservation_id: UUID) -> tuple[IssuedPrivatePackCapability, PrivateExposureObservation]:
        self._lock()
        reserved = self.conn.execute('SELECT * FROM tutor_item_supply_private_native_assessment_reservations WHERE id=%s AND user_id=%s AND epoch=%s',
            (reservation_id,self.user_id,self.epoch)).fetchone()
        if reserved is None:
            raise PrivateNativePending('private_current_retained_reservation_required')
        refs = reserved['payload_json']
        stable = {k: refs[k] for k in ('mapping_id','versions','pack_request_hash','protected')}
        if refs.get('binding_hash') != canonical_hash(stable):
            raise PrivateNativePending('private_immutable_selected_binding_required')
        observation = self.snapshot_complete()
        # Historical reference JSON is DATA only. Independently pick actual
        # committed still-current four-role receipts in this same PRIVATE task.
        rows = self.conn.execute("SELECT id FROM tutor_item_supply_private_native_quality_evidence WHERE user_id=%s AND epoch=%s AND pack_task_id=%s AND kind='relation' AND checked_at<=clock_timestamp() AND valid_until>clock_timestamp() ORDER BY checked_at DESC,id LIMIT 16",
            (self.user_id,self.epoch,reserved['pack_task_id'])).fetchall()
        cap = self.type_owner.resolve_pack(UUID(refs['mapping_id']),tuple(UUID(v) for v in refs['versions']),
            observation.snapshot_id,tuple(UUID(str(r['id'])) for r in rows))
        pack = self.type_owner.require_pack(cap)
        if pack.request.request_hash != refs['pack_request_hash'] or [b.model_dump(mode='json') for b in _protected(pack,observation.exposure)] != refs['protected']:
            raise PrivateNativePending('private_retained_current_whole_pack_changed')
        return cap,observation

    def prepare_practice_delivery(self, *, reservation_id: UUID, version_id: UUID, run_id: UUID,
                                 creation_payload: dict[str, Any], purpose: str = 'knowledge_check',
                                 parent_artifact_id: UUID | None = None) -> UUID:
        self._lock()
        row = self.conn.execute('SELECT * FROM tutor_item_supply_private_native_assessment_reservations WHERE id=%s AND user_id=%s AND epoch=%s',
            (reservation_id, self.user_id, self.epoch)).fetchone()
        if row is None:
            raise PrivateNativePending('private_delivery_reservation_required')
        refs = row['payload_json']
        cap, observation = self.resolve_reserved_pack(reservation_id)
        pack = self.type_owner.require_pack(cap)
        if purpose not in {'knowledge_check','remediation','transfer_check'} or ((purpose=='knowledge_check')!=(parent_artifact_id is None)):
            raise PrivateNativePending('private_delivery_closed_ordinary_successor_scope_required')
        role='remediation' if purpose=='remediation' else 'practice'
        selected = next((c for c in pack.selected if c.version_id == version_id and c.member.slot == role), None)
        if selected is None:
            raise PrivateNativePending('private_delivery_exact_selected_practice_required')
        now, txid = self.type_owner._guard()
        receipt_id = uuid4()
        payload = {'schema_version': 'private_native_creation_v1', 'request': creation_payload,
            'selected': selected.model_dump(mode='json'), 'mapping_id': refs['mapping_id'],
            'pack_request_hash': pack.request.request_hash, 'content': selected.type_evidence.content.model_dump(mode='json')}
        if parent_artifact_id is not None:
            checked=self.conn.execute('SELECT item_supply_internal.private_native_successor_delivery_current(%s,%s,%s,%s) AS ok',
                (parent_artifact_id,cap.eligibility_id,version_id,purpose)).fetchone()
            if checked is None or checked['ok'] is not True:
                raise PrivateNativePending('private_delivery_actual_completed_KC_successor_required')
            payload['parent_artifact_id']=str(parent_artifact_id)
        self.conn.execute('INSERT INTO tutor_item_supply_private_native_consumer_receipts '
            '(id,user_id,epoch,scope_id,pack_task_id,mode,run_id,version_id,reservation_id,eligibility_id,exposure_snapshot_id,payload_json,checked_at,valid_until,txid) '
            "VALUES(%s,%s,%s,%s,%s,'create',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (receipt_id, self.user_id, self.epoch, row['scope_id'], row['pack_task_id'], run_id, version_id,
             reservation_id, cap.eligibility_id, observation.snapshot_id, Jsonb(payload), now, pack.valid_until, txid))
        self.type_owner.require_pack(cap)
        return receipt_id
